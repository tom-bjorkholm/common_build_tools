#! /usr/bin/env python3
"""Find and resolve the highest available Python 3 version."""

# Copyright (c) 2024 - 2026 Tom Björkholm
# MIT License

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from build_utils import (
    is_windows,
    resolve_python_command,
    validate_python_name,
)


def _find_via_py_launcher() -> list[tuple[int, int]]:
    """Discover Python 3.x versions via the Windows py launcher."""
    if not shutil.which('py'):
        return []
    results: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    try:
        process = subprocess.run(['py', '--list'], capture_output=True,
                                 text=True, timeout=10, check=False)
    except subprocess.TimeoutExpired:
        return []
    if process.returncode != 0:
        return results
    for line in process.stdout.splitlines():
        match = re.search(r'-(\d+)\.(\d+)', line)
        if not match:
            continue
        major = int(match.group(1))
        minor = int(match.group(2))
        version = (major, minor)
        if major != 3 or version in seen:
            continue
        seen.add(version)
        results.append(version)
    return results


def _is_executable_file(path: Path) -> bool:
    """Return True when path points to an executable file."""
    if not path.is_file():
        return False
    if is_windows():
        return True
    return os.access(path, os.X_OK)


def _find_via_path_scan() -> list[tuple[int, int]]:
    """Discover Python 3.x versions by scanning PATH directories."""
    results: list[tuple[int, int]] = []
    seen_minors: set[int] = set()
    suffix = r'\.exe' if is_windows() else ''
    pattern = re.compile(r'^python3\.(\d+)' + suffix + r'$')
    for path_item in os.environ.get('PATH', '').split(os.pathsep):
        path_dir = Path(path_item)
        if not path_dir.is_dir():
            continue
        try:
            _scan_directory(path_dir=path_dir, pattern=pattern,
                            seen_minors=seen_minors, results=results)
        except (PermissionError, OSError):
            continue
    return results


def _scan_directory(path_dir: Path, pattern: re.Pattern[str],
                    seen_minors: set[int],
                    results: list[tuple[int, int]]) -> None:
    """Scan a directory for python3.X executables."""
    for entry in path_dir.iterdir():
        match = pattern.match(entry.name)
        if not match:
            continue
        if not _is_executable_file(entry):
            continue
        minor = int(match.group(1))
        if minor in seen_minors:
            continue
        seen_minors.add(minor)
        results.append((3, minor))


def find_best_python_name() -> str:
    """Return the highest available Python name, such as python3.14."""
    candidates: list[tuple[int, int]] = []
    if is_windows():
        candidates = _find_via_py_launcher()
    if not candidates:
        candidates = _find_via_path_scan()
    if not candidates:
        print('Error: No Python 3.x installation found.', file=sys.stderr)
        sys.exit(1)
    candidates.sort()
    major, minor = candidates[-1]
    return f'python{major}.{minor}'


def resolve_target_python(python_name: str | None = None) -> tuple[str,
                                                                   list[str]]:
    """Resolve the python executable to use for the build."""
    if python_name is None:
        name = find_best_python_name()
    else:
        validate_python_name(python_name)
        name = python_name
    command = resolve_python_command(name)
    if command:
        print(f'Using PYTHON {name}')
        return name, command
    print(f'Cannot find executable for {name}', file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
    print(find_best_python_name())
