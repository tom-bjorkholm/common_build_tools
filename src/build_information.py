#! /usr/bin/env python3
"""Discover and validate package and folder information for builds."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

import ast
import os
from pathlib import Path
import re
import tomllib
from typing import Any, Optional

from build_spec import BuildInformation, BuildSpec, PackageInformation
from get_build_spec import get_build_spec


IGNORED_SCAN_DIRS = {
    '.git',
    '.mypy_cache',
    '.pytest_cache',
    '.tox',
    '__pycache__',
    'build',
    'dist',
    'reports',
    'venv',
}


def _project_root_from_common_build_tools() -> Path:
    """Return repository root from common_build_tools/src location."""
    return Path(__file__).resolve().parents[2]


def _normalize_package_name(name: str) -> str:
    """Normalize package names for dependency and lookup checks."""
    return name.strip().lower().replace('-', '_')


def _discover_package_folders(project_root: Path) -> list[Path]:
    """Auto-discover package folders from setup.py and pyproject.toml."""
    discovered: set[Path] = set()
    for dir_path, dir_names, file_names in os.walk(project_root):
        dir_names[:] = [
            name for name in dir_names
            if name not in IGNORED_SCAN_DIRS and not name.startswith('.')
        ]
        file_set = set(file_names)
        if 'setup.py' in file_set or 'pyproject.toml' in file_set:
            discovered.add(Path(dir_path))
    return sorted(discovered)


def _resolve_package_folders(build_spec: BuildSpec,
                             project_root: Path) -> list[Path]:
    """Return package folders from spec or auto-discovery."""
    if build_spec.package_folders is None:
        return _discover_package_folders(project_root)
    resolved: list[Path] = []
    for folder in build_spec.package_folders:
        resolved_path = (project_root / folder).resolve()
        if resolved_path.is_dir():
            resolved.append(resolved_path)
    return sorted(set(resolved))


def _extract_module_literals(module_tree: ast.Module) -> dict[str, Any]:
    """Extract simple top-level assignments that can be literal-evaluated."""
    literal_values: dict[str, Any] = {}
    for node in module_tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            literal_values[target.id] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            continue
    return literal_values


def _is_setup_call(node: ast.Call) -> bool:
    """Return True when call node is a call to setup(...)."""
    if isinstance(node.func, ast.Name):
        return node.func.id == 'setup'
    if isinstance(node.func, ast.Attribute):
        return node.func.attr == 'setup'
    return False


def _find_setup_call(module_tree: ast.Module) -> Optional[ast.Call]:
    """Find first setup(...) call in the parsed setup.py module."""
    for node in ast.walk(module_tree):
        if isinstance(node, ast.Call) and _is_setup_call(node):
            return node
    return None


def _eval_simple_node(node: ast.AST, literals: dict[str, Any]) -> Any:
    """Evaluate literal-like AST nodes using known top-level literals."""
    if isinstance(node, ast.Name):
        return literals.get(node.id)
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return None


def _normalize_dependency_string(requirement: str) -> str:
    """Normalize dependency text for comparison and checks."""
    return re.sub(r'\s+', '', requirement.strip())


def _parse_setup_file(setup_path: Path) -> dict[str, Any]:
    """Parse selected metadata from setup.py without executing it."""
    source = setup_path.read_text(encoding='utf-8')
    module_tree = ast.parse(source, filename=str(setup_path))
    literals = _extract_module_literals(module_tree)
    setup_call = _find_setup_call(module_tree)
    if setup_call is None:
        raise ValueError(f'No setup(...) call found in {setup_path}')
    values: dict[str, Any] = {
        'name': None,
        'version': None,
        'description': None,
        'python_requires': None,
        'dependencies': [],
    }
    for keyword in setup_call.keywords:
        if keyword.arg is None:
            continue
        value = _eval_simple_node(keyword.value, literals)
        if keyword.arg == 'name':
            values['name'] = value
        elif keyword.arg == 'version':
            values['version'] = value
        elif keyword.arg == 'description':
            values['description'] = value
        elif keyword.arg == 'python_requires':
            values['python_requires'] = value
        elif keyword.arg == 'install_requires' and isinstance(value, list):
            values['dependencies'] = [
                _normalize_dependency_string(str(item))
                for item in value
            ]
    return values


def _parse_pyproject_file(pyproject_path: Path) -> dict[str, Any]:
    """Parse selected metadata from pyproject.toml."""
    with open(pyproject_path, 'rb') as file_obj:
        pyproject_data = tomllib.load(file_obj)
    project_data = pyproject_data.get('project', {})
    dynamic_list = project_data.get('dynamic', [])
    dependencies: Optional[list[str]]
    if 'dependencies' in dynamic_list:
        dependencies = None
    else:
        dep_list = project_data.get('dependencies', [])
        dependencies = [
            _normalize_dependency_string(str(item))
            for item in dep_list
        ]
    return {
        'name': project_data.get('name'),
        'version': project_data.get('version'),
        'description': project_data.get('description'),
        'python_requires': project_data.get('requires-python'),
        'dependencies': dependencies,
    }


def _check_consistency_between_setup_and_pyproject(
        package_folder: Path, setup_data: dict[str, Any],
        pyproject_data: dict[str, Any]) -> None:
    """Raise ValueError if setup.py and pyproject.toml disagree."""
    for key in ['name', 'version', 'description', 'python_requires']:
        setup_value = setup_data.get(key)
        pyproject_value = pyproject_data.get(key)
        if setup_value is None or pyproject_value is None:
            continue
        if str(setup_value) != str(pyproject_value):
            raise ValueError(
                f'Inconsistent {key} in {package_folder}: '
                f'setup.py has {setup_value!r}, '
                f'pyproject.toml has {pyproject_value!r}'
            )
    pyproject_deps = pyproject_data.get('dependencies')
    if pyproject_deps is None:
        return
    setup_deps = setup_data.get('dependencies', [])
    if sorted(setup_deps) == sorted(pyproject_deps):
        return
    raise ValueError(
        f'Inconsistent dependencies in {package_folder}: '
        'setup.py install_requires and pyproject.toml '
        '[project].dependencies differ.'
    )


def _combine_package_data(
        package_folder: Path, setup_file: Optional[Path],
        pyproject_file: Optional[Path]) -> PackageInformation:
    """Combine parsed setup.py and pyproject.toml data into package info."""
    setup_data: dict[str, Any] = {}
    pyproject_data: dict[str, Any] = {}
    if setup_file is not None:
        setup_data = _parse_setup_file(setup_file)
    if pyproject_file is not None:
        pyproject_data = _parse_pyproject_file(pyproject_file)
    if setup_file is not None and pyproject_file is not None:
        _check_consistency_between_setup_and_pyproject(
            package_folder=package_folder,
            setup_data=setup_data,
            pyproject_data=pyproject_data
        )
    name_value = setup_data.get('name') or pyproject_data.get('name')
    version_value = setup_data.get('version') or pyproject_data.get('version')
    if not isinstance(name_value, str) or not name_value:
        raise ValueError(f'Missing package name in {package_folder}')
    if not isinstance(version_value, str) or not version_value:
        raise ValueError(f'Missing package version in {package_folder}')
    dependencies_value = setup_data.get('dependencies')
    if not isinstance(dependencies_value, list):
        dependencies_value = pyproject_data.get('dependencies') or []
    src_folder = package_folder / 'src'
    test_folder = package_folder / 'test'
    return PackageInformation(
        name=name_value,
        normalized_name=_normalize_package_name(name_value),
        version=version_value,
        dependencies=[str(item) for item in dependencies_value],
        package_folder=package_folder,
        setup_file=setup_file,
        pyproject_file=pyproject_file,
        src_folder=src_folder if src_folder.is_dir() else None,
        test_folder=test_folder if test_folder.is_dir() else None,
    )


def _load_package_information(package_folder: Path) -> PackageInformation:
    """Load package information from metadata files in package folder."""
    setup_file = package_folder / 'setup.py'
    pyproject_file = package_folder / 'pyproject.toml'
    setup_path = setup_file if setup_file.is_file() else None
    pyproject_path = pyproject_file if pyproject_file.is_file() else None
    if setup_path is None and pyproject_path is None:
        raise ValueError(
            f'No setup.py or pyproject.toml found in {package_folder}'
        )
    return _combine_package_data(package_folder=package_folder,
                                 setup_file=setup_path,
                                 pyproject_file=pyproject_path)


def _version_key(version_text: str) -> tuple[tuple[int, object], ...]:
    """Return sortable key for simple dotted version text."""
    parts = re.split(r'[.\-_+]', version_text)
    key_parts: list[tuple[int, object]] = []
    for part in parts:
        if part.isdigit():
            key_parts.append((0, int(part)))
        else:
            key_parts.append((1, part.lower()))
    return tuple(key_parts)


def _extract_dependency_name(requirement: str) -> str:
    """Extract normalized package name from a dependency requirement."""
    match = re.match(r'^\s*([A-Za-z0-9_.-]+)', requirement)
    if match is None:
        return ''
    return _normalize_package_name(match.group(1))


def _extract_minimum_version(requirement: str) -> Optional[str]:
    """Extract largest minimum version specified with >= in requirement."""
    matches: list[str] = re.findall(
        r'>=\s*([A-Za-z0-9_.+\-]+)',
        requirement
    )
    if not matches:
        return None
    best = matches[0]
    for version_text in matches[1:]:
        if _version_key(version_text) > _version_key(best):
            best = version_text
    return best


def _check_internal_dependency_versions(
        package_information: list[PackageInformation]) -> None:
    """Check that internal dependencies specify >= built package version."""
    by_name = {
        package_data['normalized_name']: package_data
        for package_data in package_information
    }
    for package_data in package_information:
        for requirement in package_data['dependencies']:
            dep_name = _extract_dependency_name(requirement)
            if dep_name not in by_name:
                continue
            required_package = by_name[dep_name]
            min_version = _extract_minimum_version(requirement)
            if min_version is None:
                raise ValueError(
                    f'Package {package_data["name"]} depends on '
                    f'{required_package["name"]} without >= version '
                    f'constraint in requirement {requirement!r}.'
                )
            if _version_key(min_version) >= _version_key(
                    required_package['version']):
                continue
            raise ValueError(
                f'Package {package_data["name"]} depends on '
                f'{required_package["name"]} with minimum version '
                f'{min_version}, but built package version is '
                f'{required_package["version"]}.'
            )


def _check_identical_versions(build_spec: BuildSpec,
                              package_information: list[PackageInformation]) \
        -> None:
    """Check optional constraint that all package versions are identical."""
    if not build_spec.identical_versions:
        return
    if not package_information:
        return
    first_version = package_information[0]['version']
    for package_data in package_information[1:]:
        if package_data['version'] == first_version:
            continue
        raise ValueError(
            f'Package versions differ: {package_information[0]["name"]} has '
            f'{first_version}, {package_data["name"]} has '
            f'{package_data["version"]}.'
        )


def _dependency_edges_for_internal_packages(
        package_information: list[PackageInformation]) -> \
            dict[str, list[str]]:
    """Return graph edges dependency -> dependent for internal packages."""
    by_name = {
        package_data['normalized_name']: package_data
        for package_data in package_information
    }
    graph: dict[str, list[str]] = {
        package_data['normalized_name']: []
        for package_data in package_information
    }
    for package_data in package_information:
        package_name = package_data['normalized_name']
        for requirement in package_data['dependencies']:
            dep_name = _extract_dependency_name(requirement)
            if dep_name not in by_name:
                continue
            graph[dep_name].append(package_name)
    return graph


def _package_install_order(package_information: list[PackageInformation]) -> \
        list[str]:
    """Return package install order based on internal dependencies."""
    graph = _dependency_edges_for_internal_packages(package_information)
    indegree: dict[str, int] = {name: 0 for name in graph}
    by_name = {
        package_data['normalized_name']: package_data
        for package_data in package_information
    }
    for package_data in package_information:
        package_name = package_data['normalized_name']
        for requirement in package_data['dependencies']:
            dep_name = _extract_dependency_name(requirement)
            if dep_name in indegree:
                indegree[package_name] += 1
    ready_names = sorted(name for name, degree in indegree.items()
                         if degree == 0)
    install_order_norm: list[str] = []
    while ready_names:
        current = ready_names.pop(0)
        install_order_norm.append(current)
        for dependent in sorted(graph[current]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready_names.append(dependent)
                ready_names.sort()
    if len(install_order_norm) != len(package_information):
        raise ValueError('Detected cyclic internal package dependencies.')
    return [by_name[name]['name'] for name in install_order_norm]


def _collect_named_folders(project_root: Path, folder_name: str) -> list[Path]:
    """Collect folders in project tree with exact folder_name."""
    discovered: list[Path] = []
    seen: set[Path] = set()
    for dir_path, dir_names, _file_names in os.walk(project_root):
        dir_names[:] = [
            name for name in dir_names
            if name not in IGNORED_SCAN_DIRS and not name.startswith('.')
        ]
        current = Path(dir_path)
        if current.name != folder_name:
            continue
        resolved = current.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        discovered.append(resolved)
    return sorted(discovered)


def _resolve_folder_list(folder_list: Optional[list[Path]],
                         project_root: Path) -> list[Path]:
    """Resolve a list of paths relative to project root."""
    if not folder_list:
        return []
    resolved: list[Path] = []
    for folder in folder_list:
        candidate = (project_root / folder).resolve()
        if candidate.is_dir():
            resolved.append(candidate)
    return sorted(set(resolved))


def _is_path_included(path: Path, excluded_folders: list[Path]) -> bool:
    """Return True when path is not excluded by any excluded folder."""
    for excluded in excluded_folders:
        try:
            path.relative_to(excluded)
            return False
        except ValueError:
            continue
    return True


def _merge_and_filter_folders(default_folders: list[Path],
                              additional_folders: Optional[list[Path]],
                              exclude_folders: Optional[list[Path]],
                              project_root: Path) -> list[Path]:
    """Merge defaults and additions, then remove excluded folders."""
    combined: list[Path] = []
    seen: set[Path] = set()
    for folder in default_folders + _resolve_folder_list(
            additional_folders, project_root):
        if folder in seen:
            continue
        seen.add(folder)
        combined.append(folder)
    excluded = _resolve_folder_list(exclude_folders, project_root)
    return [folder for folder in sorted(combined)
            if _is_path_included(folder, excluded)]


def discover_build_information(build_spec: BuildSpec,
                               project_root: Optional[Path] = None) -> \
        BuildInformation:
    """Discover packages and tool folders and validate build consistency."""
    resolved_root = (project_root or _project_root_from_common_build_tools()) \
        .resolve()
    package_folders = _resolve_package_folders(build_spec=build_spec,
                                               project_root=resolved_root)
    package_information = [
        _load_package_information(folder) for folder in package_folders
    ]
    _check_identical_versions(build_spec=build_spec,
                              package_information=package_information)
    _check_internal_dependency_versions(
        package_information=package_information
    )
    install_order = _package_install_order(package_information)
    src_folders = _collect_named_folders(project_root=resolved_root,
                                         folder_name='src')
    test_folders = _collect_named_folders(project_root=resolved_root,
                                          folder_name='test')
    flake8_folders = _merge_and_filter_folders(
        default_folders=src_folders + test_folders,
        additional_folders=build_spec.flake8_additional_folders,
        exclude_folders=build_spec.flake8_exclude_folders,
        project_root=resolved_root
    )
    pylint_folders = _merge_and_filter_folders(
        default_folders=src_folders + test_folders,
        additional_folders=build_spec.pylint_additional_folders,
        exclude_folders=build_spec.pylint_exclude_folders,
        project_root=resolved_root
    )
    mypy_defaults = list(src_folders)
    if build_spec.mypy_on_test:
        mypy_defaults.extend(test_folders)
    mypy_folders = _merge_and_filter_folders(
        default_folders=mypy_defaults,
        additional_folders=build_spec.mypy_additional_folders,
        exclude_folders=build_spec.mypy_exclude_folders,
        project_root=resolved_root
    )
    pytest_folders = _merge_and_filter_folders(
        default_folders=test_folders,
        additional_folders=build_spec.pytest_additional_folders,
        exclude_folders=build_spec.pytest_exclude_folders,
        project_root=resolved_root
    )
    mypy_paths = _merge_and_filter_folders(
        default_folders=mypy_defaults,
        additional_folders=build_spec.mypy_paths,
        exclude_folders=None,
        project_root=resolved_root
    )
    return BuildInformation(
        project_root=resolved_root,
        package_information=package_information,
        package_install_order=install_order,
        flake8_folders=flake8_folders,
        pylint_folders=pylint_folders,
        mypy_folders=mypy_folders,
        pytest_folders=pytest_folders,
        mypy_path_folders=mypy_paths,
    )


def get_build_information(build_spec: Optional[BuildSpec] = None,
                          project_root: Optional[Path] = None) -> \
        BuildInformation:
    """Return build information using build spec from custom/default source."""
    active_spec = get_build_spec() if build_spec is None else build_spec
    return discover_build_information(build_spec=active_spec,
                                      project_root=project_root)
