#! /usr/bin/env python3
"""Tests for common_build_tools.src.clean."""

# Copyright (c) 2026 Tom Björkholm
# MIT License
# pylint: disable=protected-access

from pathlib import Path
import pytest

import clean
from build_spec import BuildSpec
from common_build_tools.test.helpers import (
    make_build_information,
    make_package_information,
)


def test_clean_removes_artifacts(monkeypatch: pytest.MonkeyPatch,
                                 tmp_path: Path) -> None:
    """Test clean removes root and package build artifacts."""
    package_folder = tmp_path / 'package_a'
    (tmp_path / 'build').mkdir()
    (tmp_path / 'dist').mkdir()
    (tmp_path / 'reports').mkdir()
    (tmp_path / 'venv').mkdir()
    (tmp_path / '.pytest_cache').mkdir()
    (tmp_path / '.mypy_cache').mkdir()
    (tmp_path / '__pycache__').mkdir()
    (tmp_path / 'module.pyc').write_text('x', encoding='utf-8')
    (tmp_path / '.coverage').write_text('data', encoding='utf-8')
    (tmp_path / '.coverage.extra').write_text('data', encoding='utf-8')
    (package_folder / 'build').mkdir(parents=True)
    (package_folder / 'dist').mkdir(parents=True)
    package = make_package_information(package_folder=package_folder)
    info = make_build_information(tmp_path, [package])
    monkeypatch.setattr(clean, 'exit_if_in_virtualenv', lambda _action: None)
    clean.clean(build_spec=BuildSpec(), build_information=info)
    assert not (tmp_path / 'build').exists()
    assert not (tmp_path / 'dist').exists()
    assert not (tmp_path / 'reports').exists()
    assert not (tmp_path / 'venv').exists()
    assert not (tmp_path / '.pytest_cache').exists()
    assert not (tmp_path / '.mypy_cache').exists()
    assert not (tmp_path / '__pycache__').exists()
    assert not (tmp_path / 'module.pyc').exists()
    assert not (tmp_path / '.coverage').exists()
    assert not (tmp_path / '.coverage.extra').exists()
    assert not (package_folder / 'build').exists()
    assert not (package_folder / 'dist').exists()


def test_remove_matching_paths(tmp_path: Path) -> None:
    """Test _remove_matching removes both directories and file matches."""
    (tmp_path / 'a' / '__pycache__').mkdir(parents=True)
    (tmp_path / 'b').mkdir(parents=True)
    (tmp_path / 'b' / 'temp~').write_text('x', encoding='utf-8')
    clean._remove_matching('__pycache__', tmp_path)
    clean._remove_matching('*~', tmp_path)
    assert not (tmp_path / 'a' / '__pycache__').exists()
    assert not (tmp_path / 'b' / 'temp~').exists()


def test_clean_cmd_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test clean_cmd exits with code zero after calling clean."""
    called: list[bool] = []

    def _fake_clean(*_args: object, **_kwargs: object) -> None:
        called.append(True)

    monkeypatch.setattr(clean, 'clean', _fake_clean)
    with pytest.raises(SystemExit) as exc_info:
        clean.clean_cmd()
    assert called == [True]
    assert exc_info.value.code == 0
