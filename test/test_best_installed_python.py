#! /usr/bin/env python3
"""Tests for common_build_tools.src.best_installed_python."""

# Copyright (c) 2026 Tom Björkholm
# MIT License
# pylint: disable=protected-access

from pathlib import Path
import shutil
import stat
import subprocess
import pytest

import best_installed_python


def test_py_launcher_parses_py3(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test py launcher parsing keeps unique Python 3 major versions."""
    monkeypatch.setattr(shutil, 'which',
                        lambda name: 'py' if name == 'py' else None)
    process = subprocess.CompletedProcess(
        args=['py', '--list'], returncode=0,
        stdout=' -V:3.12 * Python 3.12\n -V:2.7 Python 2.7\n'
               ' -3.14-64\n -3.12-64\n', stderr='')
    monkeypatch.setattr(subprocess, 'run', lambda *_args, **_kwargs: process)
    versions = best_installed_python._find_via_py_launcher()
    assert sorted(versions) == [(3, 12), (3, 14)]


def test_py_launcher_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test py launcher discovery returns empty list after timeout."""
    monkeypatch.setattr(shutil, 'which',
                        lambda name: 'py' if name == 'py' else None)

    def _raise_timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd='py --list', timeout=10)

    monkeypatch.setattr(subprocess, 'run', _raise_timeout)
    assert not best_installed_python._find_via_py_launcher()


def _create_executable(path: Path) -> None:
    """Create an executable file for PATH scan testing."""
    path.write_text('#! /bin/sh\nexit 0\n', encoding='utf-8')
    current_mode = path.stat().st_mode
    path.chmod(current_mode | stat.S_IXUSR)


def test_path_scan_finds_pythons(monkeypatch: pytest.MonkeyPatch,
                                 tmp_path: Path) -> None:
    """Test path scan finds python3.X executables and deduplicates minors."""
    first_dir = tmp_path / 'first'
    second_dir = tmp_path / 'second'
    first_dir.mkdir()
    second_dir.mkdir()
    _create_executable(first_dir / 'python3.12')
    _create_executable(first_dir / 'python3.14')
    _create_executable(second_dir / 'python3.14')
    monkeypatch.setattr(best_installed_python, 'is_windows', lambda: False)
    monkeypatch.setenv('PATH', f'{first_dir}:{second_dir}')
    versions = best_installed_python._find_via_path_scan()
    assert versions == [(3, 12), (3, 14)]


def test_best_python_from_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test best python name is selected from path scan candidates."""
    monkeypatch.setattr(best_installed_python, 'is_windows', lambda: False)
    monkeypatch.setattr(best_installed_python, '_find_via_path_scan',
                        lambda: [(3, 12), (3, 14), (3, 13)])
    assert best_installed_python.find_best_python_name() == 'python3.14'


def test_best_python_exits_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test find_best_python_name exits when no interpreter is discovered."""
    monkeypatch.setattr(best_installed_python, 'is_windows', lambda: False)
    monkeypatch.setattr(best_installed_python, '_find_via_path_scan',
                        lambda: [])
    with pytest.raises(SystemExit) as exc_info:
        best_installed_python.find_best_python_name()
    assert exc_info.value.code == 1


def test_resolve_target_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test explicit python version resolution for resolve_target_python."""
    monkeypatch.setattr(best_installed_python, 'validate_python_name',
                        lambda _name: None)
    monkeypatch.setattr(best_installed_python, 'resolve_python_command',
                        lambda _name: ['/usr/bin/python3.13'])
    name, command = best_installed_python.resolve_target_python('python3.13')
    assert name == 'python3.13'
    assert command == ['/usr/bin/python3.13']


def test_resolve_target_uses_best(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test resolve_target_python uses discovered best version if omitted."""
    monkeypatch.setattr(best_installed_python, 'find_best_python_name',
                        lambda: 'python3.14')
    monkeypatch.setattr(best_installed_python, 'resolve_python_command',
                        lambda _name: ['python3.14'])
    name, command = best_installed_python.resolve_target_python()
    assert name == 'python3.14'
    assert command == ['python3.14']


def test_resolve_target_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test resolve_target_python exits when command resolution fails."""
    monkeypatch.setattr(best_installed_python, 'validate_python_name',
                        lambda _name: None)
    monkeypatch.setattr(best_installed_python, 'resolve_python_command',
                        lambda _name: [])
    with pytest.raises(SystemExit) as exc_info:
        best_installed_python.resolve_target_python('python3.14')
    assert exc_info.value.code == 1
