#! /usr/bin/env python3
"""Create thin wrapper scripts in repository root."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

import os
from pathlib import Path
from wrapper_file_list import WRAPPER_FILES


def _project_root() -> Path:
    """Return repository root from common_build_tools/src location."""
    return Path(__file__).resolve().parents[2]


def _wrapper_content(target_script_name: str) -> str:
    """Return Python source code for one generated wrapper file."""
    return (
        '#! /usr/bin/env python3\n'
        f'"""Thin wrapper calling {target_script_name} in '
        'common_build_tools/src."""\n\n'
        'import sys\n'
        'from pathlib import Path\n'
        'sys.path.insert(0, str(Path(__file__).parent / '
        "'common_build_tools' / 'src'))\n"
        f'from {target_script_name} import {target_script_name}_cmd  '
        '# pylint: disable=wrong-import-position # noqa: E402\n\n\n'
        "if __name__ == '__main__':\n"
        f'    {target_script_name}_cmd()\n'
    )


def _write_wrapper_file(wrapper_path: Path, target_script_name: str) -> None:
    """Write one thin wrapper script to repository root."""
    wrapper_path.write_text(_wrapper_content(target_script_name),
                            encoding='utf-8')


def _set_wrapper_permissions(wrapper_path: Path) -> None:
    """Set wrapper permissions to owner write + world read/execute."""
    if os.name == 'nt':
        return
    wrapper_path.chmod(0o755)


CUSTOM_BUILD_TOOLS_SPEC_CONTENT = '''
"""Repository-specific build specification for common_build_tools."""

from typing import Optional
from build_spec import BuildSpec


def custom_spec() -> Optional[BuildSpec]:
    """Return custom build spec for this repository."""
    return None
'''

CUSTOM_FOLDER_PLACEHOLDER_CONTENT = {
    'src': '"""Placeholder package for custom build hooks."""\n',
    'test': '"""Placeholder package for custom build tests."""\n',
}


def _create_placeholder_python_file(custom_folder_path: Path,
                                    folder_name: str) -> None:
    """Create a placeholder Python file in newly created custom folder."""
    placeholder_path = custom_folder_path / '__init__.py'
    placeholder_path.write_text(CUSTOM_FOLDER_PLACEHOLDER_CONTENT[folder_name],
                                encoding='utf-8')


def create_custom_folder_structure(root_path: Path) -> None:
    """Create custom folder structure in repository root if not exists."""
    custom_build_tools_path: Path = root_path / 'custom_build_tools'
    if not custom_build_tools_path.exists():
        custom_build_tools_path.mkdir()
    for folder_name in ['test', 'src']:
        custom_build_tools_dir_path = custom_build_tools_path / folder_name
        if not custom_build_tools_dir_path.exists():
            custom_build_tools_dir_path.mkdir()
            _create_placeholder_python_file(
                custom_folder_path=custom_build_tools_dir_path,
                folder_name=folder_name)
    custom_spec_path: Path = custom_build_tools_path / 'custom_spec.py'
    if not custom_spec_path.exists():
        custom_spec_path.write_text(CUSTOM_BUILD_TOOLS_SPEC_CONTENT,
                                    encoding='utf-8')


def create_wrappers() -> None:
    """Create all wrapper files in repository root."""
    root_path = _project_root()
    for wrapper_name, target_script_name in WRAPPER_FILES:
        wrapper_path = root_path / wrapper_name
        _write_wrapper_file(wrapper_path, target_script_name)
        _set_wrapper_permissions(wrapper_path)
        print(f'Created wrapper: {wrapper_path}')
    create_custom_folder_structure(root_path)


if __name__ == '__main__':
    create_wrappers()
