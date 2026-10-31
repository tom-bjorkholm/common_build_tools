"""Shared utility functions for common build scripts."""

# Copyright (c) 2024 - 2026 Tom Björkholm
# MIT License

import io
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import IO, Optional


def resolve_python_command(python_name: str) -> list[str]:
    """Resolve a Python name to a subprocess command list."""
    executable_path = shutil.which(python_name)
    if executable_path:
        return [executable_path]
    return _try_py_launcher(python_name)


def run_py_launcher(args: list[str]) -> Optional[str]:
    """Return stdout of the Windows py launcher, or None on any failure.

    Returns None when the launcher is missing, times out or exits with a
    non-zero code, so that callers only have to handle one failure value.
    """
    if not shutil.which('py'):
        return None
    try:
        process = subprocess.run(['py', *args], capture_output=True,
                                 encoding='utf-8', errors='replace',
                                 timeout=10, check=False)
    except subprocess.TimeoutExpired:
        return None
    if process.returncode != 0:
        return None
    return process.stdout


def _try_py_launcher(python_name: str) -> list[str]:
    """Try to resolve python_name via the Windows py launcher."""
    if not is_windows():
        return []
    match = re.match(r'python(\d+\.\d+)', python_name)
    if not match:
        return []
    flag = f'-{match.group(1)}'
    if run_py_launcher([flag, '--version']) is None:
        return []
    return ['py', flag]


def venv_python(venv_dir: str = 'venv') -> list[str]:
    """Return the command list to invoke the venv Python."""
    if is_windows():
        path = Path(venv_dir) / 'Scripts' / 'python.exe'
    else:
        path = Path(venv_dir) / 'bin' / 'python'
    return [str(path)]


def venv_script(name: str, venv_dir: str = 'venv') -> str:
    """Return full path to a script installed in the venv."""
    if is_windows():
        path = Path(venv_dir) / 'Scripts' / f'{name}.exe'
    else:
        path = Path(venv_dir) / 'bin' / name
    return str(path)


def run_command(cmd: list[str], check: bool = True, cwd: Optional[Path] = None,
                env: Optional[dict[str, str]] = None) -> int:
    """Run a command, print it and optionally fail on non-zero exit code."""
    print(f'+ {" ".join(cmd)}')
    result = subprocess.run(cmd, check=False, cwd=cwd, env=env)
    if check and result.returncode != 0:
        _print_error(result.returncode)
        sys.exit(result.returncode)
    return result.returncode


def run_command_logged(cmd: list[str], log_file: Path, check: bool = True,
                       cwd: Optional[Path] = None,
                       env: Optional[dict[str, str]] = None) -> int:
    """Run a command and stream merged stdout/stderr to screen and log."""
    print(f'+ {" ".join(cmd)}')
    returncode = _tee_to_file(cmd=cmd, log_file=log_file, mode='a', cwd=cwd,
                              env=env)
    if check and returncode != 0:
        _print_error(returncode)
        sys.exit(returncode)
    return returncode


def run_command_captured(cmd: list[str]) -> tuple[int, str]:
    """Run a command, stream merged output to screen and return it.

    The returned text starts with the printed command line, so that it can
    be written to a log file that does not exist yet when the command runs.
    """
    command_line = f'+ {" ".join(cmd)}\n'
    print(command_line, end='')
    with io.StringIO() as sink:
        returncode = _tee(cmd=cmd, sink=sink)
        return returncode, command_line + sink.getvalue()


def _tee_to_file(cmd: list[str], log_file: Path, mode: str,
                 cwd: Optional[Path] = None,
                 env: Optional[dict[str, str]] = None) -> int:
    """Run command and write merged output to stdout and log file."""
    with open(log_file, mode, encoding='utf-8') as log_file_obj:
        return _tee(cmd=cmd, sink=log_file_obj, cwd=cwd, env=env)


def _tee(cmd: list[str], sink: IO[str], cwd: Optional[Path] = None,
         env: Optional[dict[str, str]] = None) -> int:
    """Run command and write merged output to stdout and sink."""
    with subprocess.Popen(cmd, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, encoding='utf-8',
                          errors='replace', cwd=cwd,
                          env=utf8_child_env(env)) as process:
        for line in (process.stdout or []):
            sys.stdout.write(line)
            sys.stdout.flush()
            sink.write(line)
    return process.returncode


def utf8_child_env(env: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Return a copy of env (default os.environ) with UTF-8 Python stdio.

    Python child processes then write UTF-8 to pipes on all platforms and
    Python versions. (On Windows before Python 3.15 they would otherwise
    use the ANSI code page, which differs from what newer versions use.)
    """
    environment = dict(os.environ if env is None else env)
    environment['PYTHONIOENCODING'] = 'utf-8'
    return environment


def _print_error(returncode: int) -> None:
    """Print a colored error message for a failed command."""
    print(f'\033[31mExiting due to command error code {returncode}\033[0m',
          file=sys.stderr)


def is_in_virtualenv() -> bool:
    """Return True if running inside a virtual environment."""
    return bool(os.environ.get('VIRTUAL_ENV'))


def exit_if_in_virtualenv(action: str) -> None:
    """Exit with error if already inside a virtual environment."""
    if not is_in_virtualenv():
        return
    print(f'Cannot {action} when already in virtual environment.',
          file=sys.stderr)
    print('First run: deactivate', file=sys.stderr)
    sys.exit(1)


def validate_python_name(name: str) -> None:
    """Validate that a string looks like a Python executable name."""
    if 'python' in name:
        return
    print(f'{name} does not look like a python version.', file=sys.stderr)
    sys.exit(1)


def extract_python_name(args: list[str]) -> Optional[str]:
    """Extract the first python* argument from command line args."""
    for arg in args:
        if 'python' in arg and not arg.endswith('.py'):
            return arg
    return None


def get_version_from_file(path: Path) -> str:
    """Extract version string from setup.py/pyproject.toml style lines."""
    with open(path, encoding='utf-8') as file_obj:
        for line in file_obj:
            stripped = line.strip()
            if stripped.startswith(('version =', 'version=')):
                value = stripped.split('=', 1)[1]
                return value.strip(' \t\n\r"\',')
    return ''


def append_to_path_env(existing_path: Optional[str],
                       additional_paths: list[Path]) -> str:
    """Return a PATH-like string with unique path entries appended."""
    merged_entries: list[str] = []
    seen_entries: set[str] = set()
    for entry in (existing_path or '').split(os.pathsep):
        if not entry:
            continue
        if entry in seen_entries:
            continue
        seen_entries.add(entry)
        merged_entries.append(entry)
    for add_path in additional_paths:
        add_text = str(add_path)
        if add_text in seen_entries:
            continue
        seen_entries.add(add_text)
        merged_entries.append(add_text)
    return os.pathsep.join(merged_entries)


def normalize_package_name(name: str) -> str:
    """Normalize package names for dependency and lookup checks."""
    return name.strip().lower().replace('-', '_')


def requirement_name(requirement: str) -> str:
    """Return normalized package name of a requirement, '' if none found."""
    match = re.match(r'^\s*([A-Za-z0-9_.-]+)', requirement)
    if match is None:
        return ''
    return normalize_package_name(match.group(1))


def clean_package_names(names: Optional[list[str]]) -> list[str]:
    """Return package names stripped, without empty ones (None gives [])."""
    return [name.strip() for name in names or [] if name.strip()]


def is_windows() -> bool:
    """Return True on Microsoft Windows."""
    return platform.system() == 'Windows'
