#! /usr/bin/env python3
"""Set up virtual environment and build tool dependencies."""

# Copyright (c) 2024 - 2026 Tom Björkholm
# MIT License

import shutil
import sys
from pathlib import Path
import re
from typing import Optional

from best_installed_python import resolve_target_python
from build_information import get_build_information
from build_spec import BuildInformation, BuildSpec
from build_utils import (
    exit_if_in_virtualenv,
    extract_python_name,
    run_command,
    venv_python,
)
from get_build_spec import get_build_spec

GLOBAL_PACKAGES = ['pip', 'gitpython']

GLOBAL_PINNED_PACKAGES = ['twine==6.0.1']

VENV_PACKAGES = [
    'pip',
    'build',
    'setuptools',
    'wheel',
    'pytest',
    'pytest-html',
    'pytest-cov',
    'flake8',
    'flake8-html',
    'pylint',
    'mypy',
    'coverage',
    'pydoc-markdown',
    'lxml',
    'gitpython',
    'pytest-flake8',
    'pytest-pylint',
    'pytest-skip-slow',
    'flake8-docstrings'
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


def _normalize_package_name(package_name: str) -> str:
    """Normalize package name for package matching."""
    return package_name.strip().lower().replace('-', '_')


def _extract_dependency_name(requirement: str) -> Optional[str]:
    """Extract package name from dependency requirement string."""
    match = re.match(r'^\s*([A-Za-z0-9_.-]+)', requirement)
    if match is None:
        return None
    return _normalize_package_name(match.group(1))


def _dynamic_package_dependencies(
        build_information: BuildInformation) -> list[str]:
    """Return package dependency requirements from discovered packages.

    Dependencies on packages that are part of the same build are excluded.
    """
    internal_package_names = {
        package_info['normalized_name']
        for package_info in build_information['package_information']
    }
    dependencies: list[str] = []
    seen_requirements: set[str] = set()
    for package_info in build_information['package_information']:
        for requirement in package_info['dependencies']:
            dep_name = _extract_dependency_name(requirement)
            if dep_name in internal_package_names:
                continue
            requirement_text = requirement.strip()
            if not requirement_text:
                continue
            if requirement_text in seen_requirements:
                continue
            seen_requirements.add(requirement_text)
            dependencies.append(requirement_text)
    return dependencies


def _additional_venv_packages(build_spec: BuildSpec) -> list[str]:
    """Return additional venv packages configured by build specification."""
    if build_spec.additional_venv_packages is None:
        return []
    return [
        package_name.strip()
        for package_name in build_spec.additional_venv_packages
        if package_name.strip()
    ]


def _venv_install_list(build_spec: BuildSpec,
                       build_information: BuildInformation) -> list[str]:
    """Return complete package list to install in venv."""
    return (
        VENV_PACKAGES +
        _dynamic_package_dependencies(build_information) +
        _additional_venv_packages(build_spec) +
        VENV_PINNED_PACKAGES
    )


def _install_venv_packages(build_spec: BuildSpec,
                           build_information: BuildInformation) -> None:
    """Install required packages inside the virtual environment."""
    venv_cmd = venv_python()
    for package_name in _venv_install_list(build_spec, build_information):
        run_command([*venv_cmd, '-m', 'pip', 'install', '--upgrade',
                     package_name])


def setup_build_environment(python_name: str | None = None,
                            force_recreate: bool = False,
                            build_spec: Optional[BuildSpec] = None,
                            build_information: Optional[BuildInformation] =
                            None) -> None:
    """Set up build environment for selected Python version."""
    active_spec = get_build_spec() if build_spec is None else build_spec
    active_information = build_information
    if active_information is None:
        active_information = get_build_information(active_spec)
    exit_if_in_virtualenv('set up build environment')
    _name, python_cmd = resolve_target_python(python_name)
    _install_global_packages(python_cmd)
    _create_or_recreate_venv(python_cmd, force_recreate=force_recreate)
    _install_venv_packages(active_spec, active_information)


def setup_build_environment_cmd(build_spec: Optional[BuildSpec]
                                = None,
                                build_information: Optional[BuildInformation]
                                = None) -> None:
    """Run setup build environment command."""
    python_name = extract_python_name(sys.argv[1:])
    setup_build_environment(python_name, False,
                            build_spec, build_information)
    sys.exit(0)


if __name__ == '__main__':
    setup_build_environment_cmd()
