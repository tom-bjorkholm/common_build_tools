#! /usr/bin/env python3
"""Remove build artifacts and caches from project tree."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

import shutil
from pathlib import Path
from typing import Optional

from build_information import get_build_information
from build_spec import BuildInformation, BuildSpec
from build_utils import exit_if_in_virtualenv
from get_build_spec import get_build_spec

DIRS_TO_REMOVE = [
    'build',
    'dist',
    'reports',
    'venv',
    '.pytest_cache',
    '.mypy_cache',
]

PATTERNS_TO_REMOVE = [
    '__pycache__',
    '*~',
    '*.egg-info',
    '*.pyc',
    '.coverage',
    '.tox',
    'nosetests.xml',
]


def _remove_matching(pattern: str, project_root: Path) -> None:
    """Remove files and folders matching pattern in project tree."""
    for item in project_root.rglob(pattern):
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        elif item.exists():
            item.unlink(missing_ok=True)


def _remove_package_build_dirs(build_information: BuildInformation) -> None:
    """Remove package-local build and dist directories."""
    for package_data in build_information['package_information']:
        package_folder = package_data['package_folder']
        shutil.rmtree(package_folder / 'build', ignore_errors=True)
        shutil.rmtree(package_folder / 'dist', ignore_errors=True)


def clean(build_spec: Optional[BuildSpec] = None,
          build_information: Optional[BuildInformation] = None) -> None:
    """Clean project artifacts, caches and virtual environment."""
    exit_if_in_virtualenv('delete virtual environment')
    active_spec = get_build_spec() if build_spec is None else build_spec
    info = get_build_information(active_spec) if build_information is None \
        else build_information
    project_root = info['project_root']
    for folder_name in DIRS_TO_REMOVE:
        shutil.rmtree(project_root / folder_name, ignore_errors=True)
    _remove_package_build_dirs(info)
    for coverage_item in project_root.glob('.coverage*'):
        if coverage_item.is_dir():
            shutil.rmtree(coverage_item, ignore_errors=True)
        elif coverage_item.exists():
            coverage_item.unlink(missing_ok=True)
    for pattern in PATTERNS_TO_REMOVE:
        _remove_matching(pattern=pattern, project_root=project_root)
