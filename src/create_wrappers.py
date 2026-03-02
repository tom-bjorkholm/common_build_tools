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
        f'"""Thin wrapper calling common_build_tools/src/'
        f'{target_script_name}."""\n\n'
        'import sys\n'
        'from run_wrapper_common import run_target_script\n\n\n'
        "if __name__ == '__main__':\n"
        '    sys.exit(run_target_script(\n'
        f"        '{target_script_name}',\n"
        '        sys.argv[1:],\n'
        '    ))\n'
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


def create_wrappers() -> None:
    """Create all wrapper files in repository root."""
    root_path = _project_root()
    for wrapper_name, target_script_name in WRAPPER_FILES:
        wrapper_path = root_path / wrapper_name
        _write_wrapper_file(wrapper_path, target_script_name)
        _set_wrapper_permissions(wrapper_path)
        print(f'Created wrapper: {wrapper_path}')


if __name__ == '__main__':
    create_wrappers()
