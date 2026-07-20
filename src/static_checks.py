#! /usr/bin/env python3
"""Run static checks on individual files with build settings.

This runs mypy, flake8, python-layout and pylint on the files given as
arguments, using the same checking settings as ``run_clean_build.py``.
No caches are cleared and nothing is built. Report-only options such as
mypy ``--html-report`` and flake8 ``--htmldir`` are dropped so that the
output goes to the terminal.

Because only the given files are analyzed, cross-file findings such as
pylint duplicate-code (R0801) reflect just those files, not the whole
folder set analyzed by a clean build.
"""

# Copyright (c) 2026 Tom Björkholm
# MIT License

import os
import sys
from pathlib import Path
from typing import Optional

from build_information import get_build_information
from build_lint import _python_layout_command
from build_spec import BuildInformation, BuildSpec
from build_utils import (append_to_path_env, is_windows,
                         resolve_python_command, run_command)
from get_build_spec import get_build_spec


def _project_root() -> Path:
    """Return repository root from common_build_tools/src location."""
    return Path(__file__).resolve().parents[2]


def _venv_python_path() -> Path:
    """Return the expected venv python path for this platform."""
    root = _project_root()
    if is_windows():
        return root / 'venv' / 'Scripts' / 'python.exe'
    return root / 'venv' / 'bin' / 'python3'


def _python_from_path() -> list[str]:
    """Return python3 or python from PATH, or exit if none found."""
    for name in ('python3', 'python'):
        command = resolve_python_command(name)
        if command:
            return command
    print('No python3 interpreter found on PATH.', file=sys.stderr)
    sys.exit(1)


def _resolve_python() -> list[str]:
    """Return venv python if present, else python3/python from PATH."""
    venv_python_path = _venv_python_path()
    if venv_python_path.is_file():
        return [str(venv_python_path)]
    return _python_from_path()


def _resolve_files(arguments: list[str]) -> list[Path]:
    """Return absolute file paths, exiting on missing args or files."""
    if not arguments:
        print('Usage: run_static_checks.py FILE [FILE ...]', file=sys.stderr)
        sys.exit(2)
    files = [Path(argument).resolve() for argument in arguments]
    missing = [path for path in files if not path.is_file()]
    for path in missing:
        print(f'No such file: {path}', file=sys.stderr)
    if missing:
        sys.exit(2)
    return files


def _mypy_env(build_info: BuildInformation) -> dict[str, str]:
    """Return environment with MYPYPATH set like the build does."""
    environment = dict(os.environ)
    environment['MYPYPATH'] = append_to_path_env(
        existing_path=environment.get('MYPYPATH'),
        additional_paths=build_info['mypy_path_folders'])
    return environment


def _mypy_command(python_cmd: list[str], files: list[Path]) -> list[str]:
    """Return mypy strict command matching build checking settings."""
    return [*python_cmd, '-m', 'mypy', '--strict',
            '--explicit-package-bases', *[str(path) for path in files]]


def _flake8_command(python_cmd: list[str], files: list[Path]) -> list[str]:
    """Return flake8 command matching build checking settings."""
    return [*python_cmd, '-m', 'flake8', *[str(path) for path in files]]


def _pylint_command(python_cmd: list[str], files: list[Path],
                    project_root: Path) -> list[str]:
    """Return pylint command using the build's rcfile when present."""
    command = [*python_cmd, '-m', 'pylint']
    rcfile = project_root / '.pylintrc'
    if rcfile.is_file():
        command.append(f'--rcfile={rcfile}')
    command.extend(str(path) for path in files)
    return command


def _run(command: list[str], project_root: Path,
         env: Optional[dict[str, str]] = None) -> int:
    """Run one check command from project root and return exit code."""
    return run_command(command, check=False, cwd=project_root, env=env)


def _run_layout(python_cmd: list[str], build_spec: BuildSpec,
                files: list[Path], project_root: Path) -> int:
    """Run python-layout check, honoring the build spec toggle."""
    if not build_spec.python_layout_check:
        print('python-layout check disabled by build spec.')
        return 0
    checker = Path(__file__).with_name('check_python_layout.py')
    command = _python_layout_command(python_cmd, build_spec, checker, files)
    return _run(command, project_root)


def _run_checks(python_cmd: list[str], build_spec: BuildSpec,
                build_info: BuildInformation, files: list[Path],
                project_root: Path) -> dict[str, int]:
    """Run all four static checks and return each tool's exit code."""
    mypy_code = _run(_mypy_command(python_cmd, files), project_root,
                     _mypy_env(build_info))
    flake8_code = _run(_flake8_command(python_cmd, files), project_root)
    layout_code = _run_layout(python_cmd, build_spec, files, project_root)
    pylint_code = _run(_pylint_command(python_cmd, files, project_root),
                       project_root)
    return {'mypy': mypy_code, 'flake8': flake8_code,
            'python-layout': layout_code, 'pylint': pylint_code}


def _print_summary(results: dict[str, int]) -> None:
    """Print a per-tool pass or fail summary line."""
    print('Static check summary:')
    for name, code in results.items():
        status = 'OK' if code == 0 else f'FAILED (exit {code})'
        print(f'  {name}: {status}')


def static_checks_cmd() -> None:
    """Run mypy, flake8, python-layout and pylint on given files."""
    files = _resolve_files(sys.argv[1:])
    python_cmd = _resolve_python()
    build_spec = get_build_spec()
    build_info = get_build_information(build_spec)
    project_root = build_info['project_root']
    results = _run_checks(python_cmd=python_cmd, build_spec=build_spec,
                          build_info=build_info, files=files,
                          project_root=project_root)
    _print_summary(results)
    sys.exit(1 if any(code != 0 for code in results.values()) else 0)


if __name__ == '__main__':
    static_checks_cmd()
