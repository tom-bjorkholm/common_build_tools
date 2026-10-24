#! /usr/bin/env python3
"""Set up virtual environment and build tool dependencies."""

# Copyright (c) 2024 - 2026 Tom Björkholm
# MIT License

import shutil
import sys
from pathlib import Path
from typing import Optional

from best_installed_python import resolve_target_python
from build_information import get_build_information
from build_spec import BuildInformation, BuildSpec
from build_utils import (
    clean_package_names,
    exit_if_in_virtualenv,
    extract_python_name,
    requirement_name,
    run_command,
    venv_python,
)
from get_build_spec import get_build_spec
from global_packages import install_global_packages

VENV_PACKAGES = [
    'pip',
    'build',
    'setuptools',
    'wheel',
    'twine',
    'pytest',
    'pytest-html',
    'pytest-cov',
    'flake8',
    'flake8-html',
    'pylint',
    'pylint-json2html',
    'mypy',
    'coverage',
    'pydoc-markdown',
    'lxml',
    'gitpython',
    'pytest-skip-slow',
    'flake8-docstrings',
    'readme_renderer[md]'
]

# flake8 and pylint are run as standalone build steps (see build_lint.py),
# not through pytest plugins, so pytest is not pinned. This avoids the
# pytest-flake8 and pytest-pylint plugins, whose pytest_collect_file hook
# still uses the 'path' parameter removed in pytest 9.1.
VENV_PINNED_PACKAGES: list[str] = []


def _create_or_recreate_venv(python_cmd: list[str],
                             force_recreate: bool = False) -> None:
    """Create venv if missing, optionally recreating existing environment."""
    venv_path = Path('venv')
    if force_recreate and venv_path.exists():
        shutil.rmtree(venv_path)
    if venv_path.exists():
        return
    run_command([*python_cmd, '-m', 'venv', 'venv'])
    # upgrade pip bundled with venv to latest version so it can read pip cache
    run_command([*venv_python(), '-m', 'pip', 'install', '--upgrade', 'pip',
                 '--no-cache-dir'])


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
            dep_name = requirement_name(requirement)
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
    return clean_package_names(build_spec.additional_venv_packages)


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
                            None) -> str:
    """Set up build environment for selected Python version.

    Returns the global package report and pip output for the build log.
    """
    active_spec = get_build_spec() if build_spec is None else build_spec
    active_information = build_information
    if active_information is None:
        active_information = get_build_information(active_spec)
    exit_if_in_virtualenv('set up build environment')
    python_cmd = resolve_target_python(python_name)[1]
    setup_log = install_global_packages(python_cmd, active_spec)
    _create_or_recreate_venv(python_cmd, force_recreate=force_recreate)
    _install_venv_packages(active_spec, active_information)
    return setup_log


def setup_build_environment_cmd(build_spec: Optional[BuildSpec]
                                = None,
                                build_information: Optional[BuildInformation]
                                = None) -> None:
    """Run setup build environment command."""
    python_name = extract_python_name(sys.argv[1:])
    setup_build_environment(python_name, False, build_spec, build_information)
    sys.exit(0)


if __name__ == '__main__':
    setup_build_environment_cmd()
