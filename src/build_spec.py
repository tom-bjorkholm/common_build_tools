#! /usr/bin/env python3
"""Build specification and build information types for common_build_tools."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

from pathlib import Path
from typing import Callable, NamedTuple, Optional, TypeAlias, TypedDict


class PackageInformation(TypedDict):
    """Information discovered for one package in the build."""

    name: str
    normalized_name: str
    version: str
    dependencies: list[str]
    package_folder: Path
    setup_file: Optional[Path]
    pyproject_file: Optional[Path]
    src_folder: Optional[Path]
    test_folder: Optional[Path]


class BuildInformation(TypedDict):
    """Discovered information used by the common build process."""

    project_root: Path
    package_information: list[PackageInformation]
    package_install_order: list[str]
    flake8_folders: list[Path]
    pylint_folders: list[Path]
    mypy_folders: list[Path]
    pytest_folders: list[Path]
    mypy_path_folders: list[Path]


CustomFunction: TypeAlias = Callable[['BuildSpec', BuildInformation], None]
"""Type of custom hook functions in build specifications."""


class BuildSpec(NamedTuple):
    """Build specification for the common build tools.

    The build flow is:
    1. Discover package and folder information.
    2. Verify consistency.
    3. Run `custom_before_clean` hooks.
    4. Clean build artifacts.
    5. Run `custom_before_build` hooks.
    6. Build discovered packages.
    7. Run `custom_before_install` hooks.
    8. Install built wheel packages in dependency order.
    9. Run `custom_before_test` hooks.
    10. Run flake8 and mypy on discovered folders.
    11. Run pytest on discovered test and pylint folders.
    12. Run `custom_after_test` hooks.
    13. Run pydoc-markdown for
        `custom_build_tools/pydoc-markdown*.yml` in project root.
    14. Run `custom_final` hooks.
    15. Restore generated files with line-ending-only git changes.
    16. Generate reports under `reports/` and update README summaries.
    """

    package_folders: Optional[list[Path]] = None
    """Folders containing package metadata files.

    If None, package folders are auto-discovered by finding directories with
    `setup.py` or `pyproject.toml`.
    """

    identical_versions: bool = False
    """If True all discovered packages must have the same version."""

    mypy_on_test: bool = False
    """If True run mypy also on discovered `test` folders."""

    custom_before_clean: Optional[list[CustomFunction]] = None
    """Custom hooks run before cleaning build artifacts."""

    custom_before_build: Optional[list[CustomFunction]] = None
    """Custom hooks run before building wheel packages."""

    custom_before_install: Optional[list[CustomFunction]] = None
    """Custom hooks run before installing built wheel packages."""

    custom_before_test: Optional[list[CustomFunction]] = None
    """Custom hooks run before lint and pytest."""

    custom_after_test: Optional[list[CustomFunction]] = None
    """Custom hooks run after lint and pytest."""

    custom_final: Optional[list[CustomFunction]] = None
    """Custom hooks run at the very end of build."""

    mypy_additional_folders: Optional[list[Path]] = None
    """Additional folders to include in mypy run."""

    flake8_additional_folders: Optional[list[Path]] = None
    """Additional folders to include in flake8 run."""

    pylint_additional_folders: Optional[list[Path]] = None
    """Additional folders to include in pylint run."""

    pytest_additional_folders: Optional[list[Path]] = None
    """Additional folders to include in pytest run."""

    mypy_exclude_folders: Optional[list[Path]] = None
    """Folders to exclude from mypy run."""

    flake8_exclude_folders: Optional[list[Path]] = None
    """Folders to exclude from flake8 run."""

    pylint_exclude_folders: Optional[list[Path]] = None
    """Folders to exclude from pylint run."""

    pytest_exclude_folders: Optional[list[Path]] = None
    """Folders to exclude from pytest run."""

    mypy_paths: Optional[list[Path]] = None
    """Additional paths to add to MYPYPATH for mypy run."""

    additional_venv_packages: Optional[list[str]] = None
    """Additional packages to install in the venv."""
