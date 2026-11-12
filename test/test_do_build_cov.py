#! /usr/bin/env python3
"""Tests for the coverage config written by common_build_tools do_build."""

# Copyright (c) 2026 Tom Björkholm
# MIT License
# pylint: disable=protected-access

import os
import subprocess
import sys
from pathlib import Path

import do_build
from common_build_tools.test.helpers import (
    make_build_information,
    make_package_information,
)


_OVERLOAD_MODULE = '''"""Module with overload stubs spanning several lines."""
import typing
from typing import overload


@overload
def double(value: int,
           unused: int = 0) -> int: ...


@typing.overload
def double(value: str,
           unused: int = 0) -> str: ...


def double(value: int | str, unused: int = 0) -> int | str:
    """Return value doubled."""
    return value * 2 + unused if isinstance(value, int) else value * 2
'''


def test_cov_cfg_overload(tmp_path: Path) -> None:
    """Test coverage config gives 100% for a module with overload stubs."""
    package_folder = tmp_path / 'lib' / 'pkg_one'
    package_folder.mkdir(parents=True)
    (package_folder / '__init__.py').write_text(_OVERLOAD_MODULE,
                                                encoding='utf-8')
    script = tmp_path / 'use_pkg.py'
    script.write_text('from pkg_one import double\n'
                      'print(double(1), double("a"))\n', encoding='utf-8')
    package = make_package_information(package_folder=package_folder,
                                       name='pkg-one')
    info = make_build_information(tmp_path, [package])
    cov_config = do_build._write_cov_config(info, tmp_path)
    assert cov_config is not None
    env = {**os.environ, 'PYTHONPATH': str(tmp_path / 'lib')}
    rcfile = f'--rcfile={cov_config}'
    for args in (['run', rcfile, str(script)],
                 ['report', rcfile, '-m', '--fail-under=100']):
        result = subprocess.run([sys.executable, '-m', 'coverage', *args],
                                cwd=tmp_path, env=env, capture_output=True,
                                text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
    assert 'Branch' in result.stdout
