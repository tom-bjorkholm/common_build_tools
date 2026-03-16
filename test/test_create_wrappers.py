#! /usr/bin/env python3
"""Tests for common_build_tools.src.create_wrappers."""

# Copyright (c) 2026 Tom Björkholm
# MIT License
# pylint: disable=protected-access

from pathlib import Path
import os
import stat
import pytest

import create_wrappers
from wrapper_file_list import WRAPPER_FILES


def test_wrapper_content_target() -> None:
    """Test wrapper content imports and calls the target command function."""
    content = create_wrappers._wrapper_content('do_build')
    assert 'from do_build import do_build_cmd' in content
    assert 'if __name__ == \"__main__\":' in content.replace("'", '"')


def test_custom_folders_keep_spec(
        tmp_path: Path) -> None:
    """Test custom folder structure creation does not overwrite custom_spec."""
    custom_path = tmp_path / 'custom_build_tools'
    custom_path.mkdir()
    existing = custom_path / 'custom_spec.py'
    existing.write_text('ORIGINAL\n', encoding='utf-8')
    create_wrappers.create_custom_folder_structure(tmp_path)
    assert (custom_path / 'src').is_dir()
    assert (custom_path / 'test').is_dir()
    assert (custom_path / 'src' / '__init__.py').is_file()
    assert (custom_path / 'test' / '__init__.py').is_file()
    assert existing.read_text(encoding='utf-8') == 'ORIGINAL\n'


def test_wrapper_perms_non_windows(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """Test _set_wrapper_permissions sets executable bits on non-Windows."""
    wrapper_path = tmp_path / 'run_build.py'
    wrapper_path.write_text('print(1)\n', encoding='utf-8')
    monkeypatch.setattr(os, 'name', 'posix')
    create_wrappers._set_wrapper_permissions(wrapper_path)
    mode = stat.S_IMODE(wrapper_path.stat().st_mode)
    assert mode == 0o755


def test_create_wrappers_files(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """Test create_wrappers writes expected wrappers and custom folder tree."""
    monkeypatch.setattr(create_wrappers, '_project_root', lambda: tmp_path)
    monkeypatch.setattr(os, 'name', 'nt')
    create_wrappers.create_wrappers()
    for wrapper_name, target_name in WRAPPER_FILES:
        wrapper_path = tmp_path / wrapper_name
        assert wrapper_path.exists()
        content = wrapper_path.read_text(encoding='utf-8')
        assert f'from {target_name} import {target_name}_cmd' in content
    assert (tmp_path / 'custom_build_tools' / 'src').is_dir()
    assert (tmp_path / 'custom_build_tools' / 'test').is_dir()
    assert (tmp_path / 'custom_build_tools' / 'src' / '__init__.py').is_file()
    assert (tmp_path / 'custom_build_tools' / 'test' /
            '__init__.py').is_file()
    assert (tmp_path / 'custom_build_tools' / 'custom_spec.py').is_file()
