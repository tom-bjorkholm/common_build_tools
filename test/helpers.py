#! /usr/bin/env python3
"""Shared helper builders for common_build_tools test modules."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

from pathlib import Path

from build_spec import BuildInformation, PackageInformation


def make_package_information(package_folder: Path, name: str = 'pkg',
                             version: str = '1.0.0',
                             dependencies: list[str] | None = None,
                             normalized_name: str | None = None) -> \
        PackageInformation:
    """Create PackageInformation with optional dependency and name data."""
    deps = [] if dependencies is None else list(dependencies)
    normalized = normalized_name
    if normalized is None:
        normalized = name.strip().lower().replace('-', '_')
    return PackageInformation(name=name, normalized_name=normalized,
                              version=version, dependencies=deps,
                              package_folder=package_folder, setup_file=None,
                              pyproject_file=None, src_folder=None,
                              test_folder=None,)


def make_build_information(project_root: Path,
                           package_information: list[PackageInformation] | None
                           = None) -> BuildInformation:
    """Create BuildInformation with empty folder lists by default."""
    packages = [] if package_information is None else list(package_information)
    return BuildInformation(
        project_root=project_root, package_information=packages,
        package_install_order=[item['name'] for item in packages],
        flake8_folders=[], pylint_folders=[], mypy_folders=[],
        pytest_folders=[], mypy_path_folders=[],)
