#! /usr/bin/env python3
"""Tests for common_build_tools.src.build_utils."""

# Copyright (c) 2026 Tom Björkholm
# MIT License
# pylint: disable=protected-access
# mypy: disable-error-code=attr-defined

from pathlib import Path
import subprocess
import pytest

import build_utils


def test_resolve_python_command_uses_which(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Test resolve_python_command uses shutil.which when available."""
    monkeypatch.setattr(
        build_utils.shutil,
        'which',
        lambda name: '/usr/bin/python3.12' if name == 'python3.12' else None
    )
    result = build_utils.resolve_python_command('python3.12')
    assert result == ['/usr/bin/python3.12']


def test_resolve_python_command_falls_back_to_py_launcher(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Test resolve_python_command falls back to py launcher lookup."""
    monkeypatch.setattr(build_utils.shutil, 'which', lambda _name: None)
    monkeypatch.setattr(
        build_utils,
        '_try_py_launcher',
        lambda _name: ['py', '-3.12']
    )
    result = build_utils.resolve_python_command('python3.12')
    assert result == ['py', '-3.12']


def test_try_py_launcher_returns_command_on_success(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Test _try_py_launcher returns command when py launcher works."""
    monkeypatch.setattr(build_utils, 'is_windows', lambda: True)
    monkeypatch.setattr(
        build_utils.shutil,
        'which',
        lambda name: '/usr/bin/py' if name == 'py' else None
    )
    completed = subprocess.CompletedProcess(
        args=['py', '-3.14', '--version'],
        returncode=0,
        stdout='Python 3.14.0',
        stderr=''
    )
    monkeypatch.setattr(build_utils.subprocess, 'run', lambda *_a, **_k:
                        completed)
    assert build_utils._try_py_launcher('python3.14') == ['py', '-3.14']


def test_try_py_launcher_returns_empty_on_timeout(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Test _try_py_launcher handles subprocess timeout by returning empty."""
    monkeypatch.setattr(build_utils, 'is_windows', lambda: True)
    monkeypatch.setattr(
        build_utils.shutil,
        'which',
        lambda name: '/usr/bin/py' if name == 'py' else None
    )

    def _raise_timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd='py', timeout=10)

    monkeypatch.setattr(build_utils.subprocess, 'run', _raise_timeout)
    assert not build_utils._try_py_launcher('python3.14')


@pytest.mark.parametrize(
    'windows_flag, expected_path',
    [
        (False, 'venv/bin/python'),
        (True, 'venv/Scripts/python.exe'),
    ]
)
def test_venv_python_resolves_expected_path(
        monkeypatch: pytest.MonkeyPatch,
        windows_flag: bool,
        expected_path: str) -> None:
    """Test venv_python path selection on Windows and non-Windows."""
    monkeypatch.setattr(build_utils, 'is_windows', lambda: windows_flag)
    assert build_utils.venv_python() == [expected_path]


@pytest.mark.parametrize(
    'windows_flag, expected_path',
    [
        (False, 'venv/bin/twine'),
        (True, 'venv/Scripts/twine.exe'),
    ]
)
def test_venv_script_resolves_expected_path(
        monkeypatch: pytest.MonkeyPatch,
        windows_flag: bool,
        expected_path: str) -> None:
    """Test venv_script returns expected script path for platform."""
    monkeypatch.setattr(build_utils, 'is_windows', lambda: windows_flag)
    assert build_utils.venv_script('twine') == expected_path


def test_run_command_returns_non_zero_when_check_false(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Test run_command returns process code when check is False."""
    completed = subprocess.CompletedProcess(
        args=['cmd'],
        returncode=7,
        stdout='',
        stderr=''
    )
    monkeypatch.setattr(build_utils.subprocess, 'run',
                        lambda *_args, **_kwargs: completed)
    result = build_utils.run_command(['cmd'], check=False)
    assert result == 7


def test_run_command_exits_when_check_true_and_non_zero(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Test run_command exits on non-zero return when check is True."""
    completed = subprocess.CompletedProcess(
        args=['cmd'],
        returncode=5,
        stdout='',
        stderr=''
    )
    monkeypatch.setattr(build_utils.subprocess, 'run',
                        lambda *_args, **_kwargs: completed)
    with pytest.raises(SystemExit) as exc_info:
        build_utils.run_command(['cmd'], check=True)
    assert exc_info.value.code == 5


def test_run_command_logged_exits_on_non_zero(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """Test run_command_logged exits when tee helper returns non-zero."""
    monkeypatch.setattr(build_utils, '_tee_to_file',
                        lambda *_args, **_kwargs: 4)
    with pytest.raises(SystemExit) as exc_info:
        build_utils.run_command_logged(['cmd'], tmp_path / 'log.txt')
    assert exc_info.value.code == 4


def test_exit_if_in_virtualenv_raises(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Test exit_if_in_virtualenv exits when VIRTUAL_ENV is set."""
    monkeypatch.setenv('VIRTUAL_ENV', '/tmp/venv')
    with pytest.raises(SystemExit) as exc_info:
        build_utils.exit_if_in_virtualenv('run command')
    assert exc_info.value.code == 1


def test_validate_python_name_rejects_invalid_name() -> None:
    """Test validate_python_name rejects names without python substring."""
    with pytest.raises(SystemExit) as exc_info:
        build_utils.validate_python_name('pypy3.12')
    assert exc_info.value.code == 1


def test_extract_python_name_returns_first_match() -> None:
    """Test extract_python_name returns first python-like CLI argument."""
    args = ['-q', 'python3.13', 'script.py', 'python3.14']
    assert build_utils.extract_python_name(args) == 'python3.13'


def test_get_version_from_file_reads_first_version_line(tmp_path: Path) -> \
        None:
    """Test get_version_from_file reads first matching version assignment."""
    file_path = tmp_path / 'setup.py'
    file_path.write_text(
        'name = "example"\nversion = "1.2.3"\nversion = "1.2.4"\n',
        encoding='utf-8'
    )
    assert build_utils.get_version_from_file(file_path) == '1.2.3'


def test_append_to_path_env_deduplicates_and_preserves_order() -> None:
    """Test append_to_path_env appends unique entries in order."""
    existing = '/a:/b:/a'
    added = [Path('/b'), Path('/c')]
    assert build_utils.append_to_path_env(existing, added) == '/a:/b:/c'


def test_is_windows_uses_platform_system(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Test is_windows returns True only for Windows platform string."""
    monkeypatch.setattr(build_utils.platform, 'system', lambda: 'Windows')
    assert build_utils.is_windows() is True
    monkeypatch.setattr(build_utils.platform, 'system', lambda: 'Linux')
    assert build_utils.is_windows() is False
