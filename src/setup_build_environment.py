#! /usr/bin/env python3
"""Set up virtual environment and build tool dependencies."""

# Copyright (c) 2024 - 2026 Tom Björkholm
# MIT License

import shutil
import sys
from pathlib import Path

from best_installed_python import resolve_target_python
from build_utils import (
    exit_if_in_virtualenv,
    extract_python_name,
    run_command,
    venv_python,
)

GLOBAL_PACKAGES = ['pip']

GLOBAL_PINNED_PACKAGES = ['twine==6.0.1']

VENV_PACKAGES = [
    'pip',
    'build',
    'setuptools',
    'wheel',
    'pytest',
    'pytest-html',
    'pytest-cov',
    'pytest-flake8',
    'pytest-pylint',
    'pytest-skip-slow',
    'flake8',
    'flake8-html',
    'flake8-docstrings',
    'pylint',
    'mypy',
    'coverage',
    'pypi-simple',
    'requests',
    'types-requests',
    'argcomplete',
    'lxml',
    'python-docx',
    'odfdo',
    'mammoth',
    'odfpy',
    'pydoc-markdown',
    'pymarkdownlnt',
    'restructuredtext-lint',
    'html5lib',
    'htmlcompare',
    'gitpython',
]

VENV_PINNED_PACKAGES = ['twine==6.0.1']


def _install_global_packages(python_cmd: list[str]) -> None:
    """Install required global packages in selected system Python."""
    for package_name in GLOBAL_PACKAGES + GLOBAL_PINNED_PACKAGES:
        run_command([*python_cmd, '-m', 'pip', 'install', '--upgrade',
                     package_name])


def _create_or_recreate_venv(python_cmd: list[str],
                             force_recreate: bool = False) -> None:
    """Create venv if missing, optionally recreating existing environment."""
    venv_path = Path('venv')
    if force_recreate and venv_path.exists():
        shutil.rmtree(venv_path)
    if venv_path.exists():
        return
    run_command([*python_cmd, '-m', 'venv', 'venv'])


def _install_venv_packages() -> None:
    """Install required packages inside the virtual environment."""
    venv_cmd = venv_python()
    for package_name in VENV_PACKAGES + VENV_PINNED_PACKAGES:
        run_command([*venv_cmd, '-m', 'pip', 'install', '--upgrade',
                     package_name])


def setup_build_environment(python_name: str | None = None,
                            force_recreate: bool = False) -> None:
    """Set up build environment for selected Python version."""
    exit_if_in_virtualenv('set up build environment')
    _name, python_cmd = resolve_target_python(python_name)
    _install_global_packages(python_cmd)
    _create_or_recreate_venv(python_cmd, force_recreate=force_recreate)
    _install_venv_packages()


if __name__ == '__main__':
    setup_build_environment(extract_python_name(sys.argv[1:]))
