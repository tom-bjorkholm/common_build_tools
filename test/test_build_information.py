#! /usr/bin/env python3
"""Tests for common_build_tools.src.build_information."""

# Copyright (c) 2026 Tom Björkholm
# MIT License
# pylint: disable=protected-access

from pathlib import Path
import pytest

import build_information
from build_spec import BuildSpec, PackageInformation
from common_build_tools.test.helpers import make_package_information


def _write_text(path: Path, text: str) -> None:
    """Write UTF-8 text to path and create parent folders as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _package_data(name: str, version: str,
                  dependencies: list[str]) -> PackageInformation:
    """Create minimal PackageInformation test object."""
    return make_package_information(
        package_folder=Path('/tmp') / name, name=name, version=version,
        dependencies=dependencies,
        normalized_name=name.strip().lower().replace('-', '_'),)


def test_discover_pkgs_skips_venv(tmp_path: Path) -> None:
    """Test auto-discovery ignores excluded folders like venv."""
    _write_text(tmp_path / 'pkg' / 'setup.py', 'from setuptools import setup')
    _write_text(tmp_path / 'venv' / 'hidden_pkg' / 'setup.py',
                'from setuptools import setup')
    discovered = build_information._discover_package_folders(tmp_path)
    assert discovered == [(tmp_path / 'pkg').resolve()]


def test_parse_setup_reads_literals(tmp_path: Path) -> None:
    """Test setup.py parser resolves literal-assigned metadata values."""
    setup_path = tmp_path / 'setup.py'
    _write_text(setup_path,
                'from setuptools import setup\n'
                "NAME = 'pkg-name'\n"
                "VERSION = '1.2.3'\n"
                "DESC = 'Package description'\n"
                "REQUIRES = ['dep >= 1.0', 'dep-two==2.0']\n"
                "setup(name=NAME, version=VERSION, description=DESC,\n"
                "      python_requires='>=3.12', install_requires=REQUIRES)\n")
    parsed = build_information._parse_setup_file(setup_path)
    assert parsed['name'] == 'pkg-name'
    assert parsed['version'] == '1.2.3'
    assert parsed['description'] == 'Package description'
    assert parsed['python_requires'] == '>=3.12'
    assert parsed['dependencies'] == ['dep>=1.0', 'dep-two==2.0']


def test_parse_setup_needs_call(tmp_path: Path) -> None:
    """Test setup.py parser fails when no setup(...) call exists."""
    setup_path = tmp_path / 'setup.py'
    _write_text(setup_path, 'VALUE = 1\n')
    with pytest.raises(ValueError, match='No setup'):
        _ = build_information._parse_setup_file(setup_path)


def test_parse_pyproject_dyn_deps(tmp_path: Path) -> None:
    """Test pyproject parser returns None for dynamic dependencies."""
    pyproject_path = tmp_path / 'pyproject.toml'
    _write_text(pyproject_path,
                '[project]\n'
                "name = 'pkg-dynamic'\n"
                "version = '2.0.0'\n"
                "dynamic = ['dependencies']\n")
    parsed = build_information._parse_pyproject_file(pyproject_path)
    assert parsed['name'] == 'pkg-dynamic'
    assert parsed['version'] == '2.0.0'
    assert parsed['dependencies'] is None


def test_setup_pyproject_mismatch() -> None:
    """Test mismatch between setup.py and pyproject.toml raises ValueError."""
    setup_data: build_information._PackageFileData = {
        'name': 'pkg-a',
        'version': '1.0.0',
        'description': 'same',
        'python_requires': '>=3.12',
        'dependencies': ['dep>=1.0'],
    }
    pyproject_data: build_information._PackageFileData = {
        'name': 'pkg-a',
        'version': '1.0.1',
        'description': 'same',
        'python_requires': '>=3.12',
        'dependencies': ['dep>=1.0'],
    }
    with pytest.raises(ValueError, match='Inconsistent version'):
        build_information._check_setup_pyproject_match(
            package_folder=Path('/tmp/pkg'), setup_data=setup_data,
            pyproject_data=pyproject_data)


def test_combine_pkg_data_dirs(tmp_path: Path) -> None:
    """Test combined package data includes detected src and test folders."""
    package_folder = tmp_path / 'pkg'
    (package_folder / 'src').mkdir(parents=True)
    (package_folder / 'test').mkdir(parents=True)
    setup_path = package_folder / 'setup.py'
    pyproject_path = package_folder / 'pyproject.toml'
    _write_text(setup_path,
                'from setuptools import setup\n'
                "setup(name='pkg-one', version='1.0.0',\n"
                "      install_requires=['dep>=2.0'])\n")
    _write_text(pyproject_path,
                '[project]\n'
                "name = 'pkg-one'\n"
                "version = '1.0.0'\n"
                "dependencies = ['dep>=2.0']\n")
    combined = build_information._combine_package_data(
        package_folder=package_folder, setup_file=setup_path,
        pyproject_file=pyproject_path)
    assert combined['name'] == 'pkg-one'
    assert combined['normalized_name'] == 'pkg_one'
    assert combined['src_folder'] == (package_folder / 'src')
    assert combined['test_folder'] == (package_folder / 'test')


def test_dep_versions_need_min() -> None:
    """Test internal dependencies must include >= minimum version specifier."""
    packages = [
        _package_data('pkg-a', '1.2.0', []),
        _package_data('pkg-b', '1.2.0', ['pkg-a==1.2.0']),
    ]
    with pytest.raises(ValueError, match='without >= version constraint'):
        build_information._check_dep_versions(packages)


def test_dep_versions_accept_min() -> None:
    """Test internal dependency checks pass with valid minimum versions."""
    packages = [
        _package_data('pkg-a', '1.2.0', []),
        _package_data('pkg-b', '1.2.0', ['pkg-a>=1.2.0']),
    ]
    build_information._check_dep_versions(packages)


def test_install_order_uses_deps() -> None:
    """Test install order puts dependency packages before dependents."""
    packages = [
        _package_data('pkg-base', '1.0.0', []),
        _package_data('pkg-app', '1.0.0', ['pkg-base>=1.0.0']),
    ]
    install_order = build_information._package_install_order(packages)
    assert install_order == ['pkg-base', 'pkg-app']


def test_install_order_has_cycle() -> None:
    """Test cycle detection in internal package dependency graph."""
    packages = [
        _package_data('pkg-a', '1.0.0', ['pkg-b>=1.0.0']),
        _package_data('pkg-b', '1.0.0', ['pkg-a>=1.0.0']),
    ]
    with pytest.raises(ValueError, match='cyclic'):
        _ = build_information._package_install_order(packages)


def test_discover_build_info_repo(tmp_path: Path) -> None:
    """Test discover_build_information on a temporary multi-package repo."""
    package_base = tmp_path / 'pkg_base'
    package_app = tmp_path / 'pkg_app'
    _write_text(package_base / 'pyproject.toml',
                '[project]\n'
                "name = 'pkg-base'\n"
                "version = '1.0.0'\n"
                'dependencies = []\n')
    _write_text(package_app / 'setup.py',
                'from setuptools import setup\n'
                "setup(name='pkg-app', version='1.0.0',\n"
                "      install_requires=['pkg-base>=1.0.0'])\n")
    (package_base / 'src').mkdir(parents=True)
    (package_base / 'test').mkdir(parents=True)
    (package_app / 'src').mkdir(parents=True)
    (package_app / 'test').mkdir(parents=True)
    (tmp_path / 'custom_build_tools').mkdir()
    (tmp_path / 'extra').mkdir()
    build_spec = BuildSpec(package_folders=[Path('pkg_base'), Path('pkg_app')],
                           mypy_on_test=False,
                           flake8_additional_folders=[Path('extra')],
                           flake8_exclude_folders=[Path('pkg_app/test')],
                           mypy_paths=[Path('extra')])
    discovered = build_information.discover_build_information(
        build_spec=build_spec, project_root=tmp_path)
    assert discovered['package_install_order'] == ['pkg-base', 'pkg-app']
    assert discovered['project_root'] == tmp_path.resolve()
    assert (package_base / 'test').resolve() in discovered['pytest_folders']
    assert (package_app / 'test').resolve() in discovered['pytest_folders']
    assert (package_base / 'test').resolve() not in discovered['mypy_folders']
    assert (tmp_path / 'extra').resolve() in discovered['flake8_folders']
    assert (package_app / 'test').resolve() not in discovered['flake8_folders']
    assert (tmp_path / 'custom_build_tools').resolve() in \
        discovered['mypy_path_folders']


def test_get_build_info_uses_spec(monkeypatch: pytest.MonkeyPatch,
                                  tmp_path: Path) -> None:
    """Test get_build_information forwards explicit build spec unchanged."""
    expected = {
        'project_root': tmp_path,
        'package_information': [],
        'package_install_order': [],
        'flake8_folders': [],
        'pylint_folders': [],
        'mypy_folders': [],
        'pytest_folders': [],
        'mypy_path_folders': [],
    }
    monkeypatch.setattr(build_information, 'discover_build_information',
                        lambda **_kwargs: expected)
    spec = BuildSpec()
    assert build_information.get_build_information(spec, tmp_path) == expected
