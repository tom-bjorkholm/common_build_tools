#! /usr/bin/env python3
"""Check and install packages needed in the global (non-venv) Python.

Environment variable CBT_GLOBAL_PIP controls what happens when a global
package is missing or outdated: 'install' (default), 'force' (install with
--break-system-packages), 'stop' (report and abort) or 'skip' (report and
continue without installing).
"""

# Copyright (c) 2026 Tom Björkholm
# MIT License

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from build_spec import BuildSpec
from build_utils import (
    clean_package_names,
    requirement_name,
    run_command_captured,
)

GLOBAL_PACKAGES = ['pip', 'gitpython', 'twine']

GLOBAL_PINNED_PACKAGES: list[str] = []

GLOBAL_PIP_ENV = 'CBT_GLOBAL_PIP'

GLOBAL_PIP_MODES = ('install', 'force', 'stop', 'skip')

CHECK_FAILED_HINT = (
    'Could not check global packages. This needs pip (version 22.2 or '
    'later)\nin the global Python and network access to the package index.')


def global_pip_mode() -> str:
    """Return validated CBT_GLOBAL_PIP mode; unset or empty means install."""
    mode = os.environ.get(GLOBAL_PIP_ENV, '').strip().lower() or 'install'
    if mode in GLOBAL_PIP_MODES:
        return mode
    print(f'Invalid value {os.environ[GLOBAL_PIP_ENV]!r} of {GLOBAL_PIP_ENV}.'
          f' Valid values: {", ".join(GLOBAL_PIP_MODES)}.', file=sys.stderr)
    sys.exit(1)


def _global_package_list(build_spec: BuildSpec) -> list[str]:
    """Return complete list of packages to install in global Python."""
    return (GLOBAL_PACKAGES +
            clean_package_names(build_spec.additional_global_packages) +
            GLOBAL_PINNED_PACKAGES)


def _checked_output(cmd: list[str]) -> str:
    """Return stdout of a check command, exit with a hint if it fails."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return result.stdout
    print(result.stderr, end='', file=sys.stderr)
    print(f'Command failed: {" ".join(cmd)}\n{CHECK_FAILED_HINT}',
          file=sys.stderr)
    sys.exit(result.returncode)


def _interpreters(python_cmd: list[str]) -> list[str]:
    """Return target and launching Python executables, without duplicates.

    The target Python is asked for its executable, as python_cmd may be a
    launcher command such as 'py -3.12' on Windows.
    """
    target = _checked_output([*python_cmd, '-c',
                              'import sys; print(sys.executable)']).strip()
    if Path(target).resolve() == Path(sys.executable).resolve():
        return [target]
    return [target, sys.executable]


def _pending_installs(python: str, packages: list[str]) -> dict[str, str]:
    """Return normalized name -> version for what pip would install.

    The dry-run does not use the pip cache, as the global pip may be older
    than the pip that wrote the cache. pip skips its check for externally
    managed environments (PEP 668) for --dry-run with --report.
    """
    report = json.loads(_checked_output([
        python, '-m', 'pip', 'install', '--upgrade', '--dry-run', '--quiet',
        '--report', '-', '--no-cache-dir', '--disable-pip-version-check',
        *packages]))
    return {requirement_name(item['metadata']['name']):
            str(item['metadata']['version']) for item in report['install']}


def _installed_versions(python: str) -> dict[str, str]:
    """Return normalized name -> installed version for one Python."""
    listing = json.loads(_checked_output([
        python, '-m', 'pip', 'list', '--format=json',
        '--disable-pip-version-check']))
    return {requirement_name(item['name']): str(item['version'])
            for item in listing}


def _report_lines(python: str, changes: dict[str, str]) -> list[str]:
    """Return report lines with installed -> target version for one Python."""
    if not changes:
        return [f'  {python}: up to date']
    installed = _installed_versions(python)
    return [f'  {python}:'] + [
        f'    {name}: {installed.get(name, "not installed")} -> {version}'
        for name, version in changes.items()]


def _report(mode: str, pending: dict[str, dict[str, str]]) -> str:
    """Print and return report of pending changes for all Pythons."""
    lines = [f'Global packages ({GLOBAL_PIP_ENV}={mode}):']
    for python, changes in pending.items():
        lines += _report_lines(python, changes)
    text = '\n'.join(lines) + '\n'
    print(text, end='', flush=True)
    return text


def _fix_hint(pythons: list[str], packages: list[str]) -> str:
    """Return text explaining how to fix outdated global packages."""
    commands = ['    ' + shlex.join([python, '-m', 'pip', 'install',
                                     '--upgrade', *packages])
                for python in pythons]
    return '\n'.join([
        'To fix, either install the packages yourself with:', *commands,
        f'or set environment variable {GLOBAL_PIP_ENV} to:',
        '    install  to let the build install them with pip',
        '    force    to install with --break-system-packages (needed for',
        '             externally managed Python, for example on Ubuntu)',
        '    skip     to continue without installing them'])


def _install(python: str, packages: list[str], changes: dict[str, str],
             mode: str) -> str:
    """Install packages into one global Python and return pip output.

    pip is upgraded first without the cache, so that an old pip never reads
    a cache written by a newer pip.
    """
    install = [python, '-m', 'pip', 'install', '--upgrade']
    if mode == 'force':
        install.append('--break-system-packages')
    commands = [[*install, *packages]]
    pip_specs = [name for name in packages if requirement_name(name) == 'pip']
    if 'pip' in changes and pip_specs:
        commands.insert(0, [*install, '--no-cache-dir', *pip_specs])
    output = ''
    for cmd in commands:
        returncode, text = run_command_captured(cmd)
        output += text
        if returncode != 0:
            print(_fix_hint([python], packages), file=sys.stderr)
            sys.exit(returncode)
    return output


def _handle_pending(mode: str, pending: dict[str, dict[str, str]],
                    packages: list[str]) -> str:
    """Install, skip or stop for Pythons with pending changes."""
    outdated = [python for python, changes in pending.items() if changes]
    if not outdated:
        return ''
    if mode == 'stop':
        print(f'Global packages need changes ({GLOBAL_PIP_ENV}=stop).',
              file=sys.stderr)
        print(_fix_hint(outdated, packages), file=sys.stderr)
        sys.exit(1)
    if mode == 'skip':
        warning = (f'WARNING: global packages not changed '
                   f'({GLOBAL_PIP_ENV}=skip).\n')
        print(warning, end='')
        return warning
    return ''.join(_install(python, packages, pending[python], mode)
                   for python in outdated)


def install_global_packages(python_cmd: list[str],
                            build_spec: BuildSpec) -> str:
    """Check global packages and act according to CBT_GLOBAL_PIP.

    Both the target Python and the Python running the build scripts are
    checked. Returns the report and pip output as text for the build log.
    Exits on an invalid CBT_GLOBAL_PIP value, a failed check, a failed
    install, or when the mode is 'stop' and packages need changes.
    """
    mode = global_pip_mode()
    packages = _global_package_list(build_spec)
    pending = {python: _pending_installs(python, packages)
               for python in _interpreters(python_cmd)}
    return _report(mode, pending) + _handle_pending(mode, pending, packages)
