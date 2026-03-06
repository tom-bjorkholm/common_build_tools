#! /usr/bin/env python3
"""Tests for common_build_tools.src.do_pypi_build."""

# Copyright (c) 2026 Tom Björkholm
# MIT License
# pylint: disable=protected-access

from pathlib import Path
import sys
import pytest

import do_pypi_build
from build_spec import BuildSpec
from common_build_tools.test.helpers import make_build_information


def test_run_clean_build_or_fail_returns_error_code(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """Test helper prints message and returns code on clean_build failure."""
    info = make_build_information(tmp_path)
    monkeypatch.setattr(do_pypi_build, 'clean_build',
                        lambda **_kwargs: 4)
    result = do_pypi_build._run_clean_build_or_fail(
        python_name='python3.12',
        run_name='First run',
        build_spec=BuildSpec(),
        build_information=info
    )
    assert result == 4
    captured = capsys.readouterr()
    assert 'First run failed with exit code 4.' in captured.err


def test_do_pypi_build_stops_after_first_failed_clean_build(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """Test do_pypi_build returns first non-zero clean_build result."""
    info = make_build_information(tmp_path)
    monkeypatch.setattr(do_pypi_build, 'clean_build',
                        lambda **_kwargs: 2)
    result = do_pypi_build.do_pypi_build(
        python_name='python3.12',
        twine_upload=False,
        build_spec=BuildSpec(),
        build_information=info
    )
    assert result == 2


def test_do_pypi_build_without_twine_upload(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """Test do_pypi_build prints no-upload message when twine is disabled."""
    info = make_build_information(tmp_path)
    monkeypatch.setattr(do_pypi_build, 'clean_build',
                        lambda **_kwargs: 0)
    result = do_pypi_build.do_pypi_build(
        python_name='python3.12',
        twine_upload=False,
        build_spec=BuildSpec(),
        build_information=info
    )
    assert result == 0
    captured = capsys.readouterr()
    assert 'Twine upload not done as it was not requested.' in captured.out


def test_do_pypi_build_with_twine_upload_runs_command(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """Test do_pypi_build runs twine upload command when requested."""
    dist_dir = tmp_path / 'dist'
    dist_dir.mkdir()
    (dist_dir / 'package_a.whl').write_text('x', encoding='utf-8')
    (dist_dir / 'package_b.whl').write_text('y', encoding='utf-8')
    info = make_build_information(tmp_path)
    commands: list[list[str]] = []
    monkeypatch.setattr(do_pypi_build, 'clean_build',
                        lambda **_kwargs: 0)
    monkeypatch.setattr(do_pypi_build, 'venv_script',
                        lambda _name: 'venv/bin/twine')
    monkeypatch.setattr(
        do_pypi_build,
        'run_command',
        lambda cmd, cwd: commands.append(cmd)
    )
    result = do_pypi_build.do_pypi_build(
        python_name='python3.13',
        twine_upload=True,
        build_spec=BuildSpec(),
        build_information=info
    )
    assert result == 0
    assert commands
    upload_cmd = commands[0]
    assert upload_cmd[:2] == ['venv/bin/twine', 'upload']
    assert str(dist_dir / 'package_a.whl') in upload_cmd
    assert str(dist_dir / 'package_b.whl') in upload_cmd


def test_do_pypi_build_cmd_parses_args_and_exits(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Test do_pypi_build_cmd parses command line arguments and exits."""
    monkeypatch.setattr(do_pypi_build, 'extract_python_name',
                        lambda _args: 'python3.14')
    monkeypatch.setattr(sys, 'argv', ['prog', 'twine'])
    monkeypatch.setattr(do_pypi_build, 'do_pypi_build',
                        lambda *_args, **_kwargs: 7)
    with pytest.raises(SystemExit) as exc_info:
        do_pypi_build.do_pypi_build_cmd()
    assert exc_info.value.code == 7
