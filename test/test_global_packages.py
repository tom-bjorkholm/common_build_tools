#! /usr/bin/env python3
"""Tests for common_build_tools.src.global_packages."""

# Copyright (c) 2026 Tom Björkholm
# MIT License
# pylint: disable=protected-access

import json
import subprocess
import sys
from typing import Optional
import pytest

import global_packages
from build_spec import BuildSpec

TARGET = '/py/target'
LAUNCHER = '/py/launcher'
DEFAULT_LIST = ['pip', 'gitpython', 'twine']


def _set_mode(monkeypatch: pytest.MonkeyPatch, mode: Optional[str]) -> None:
    """Set or remove CBT_GLOBAL_PIP for one test."""
    if mode is None:
        monkeypatch.delenv(global_packages.GLOBAL_PIP_ENV, raising=False)
    else:
        monkeypatch.setenv(global_packages.GLOBAL_PIP_ENV, mode)


def _fake_pip(monkeypatch: pytest.MonkeyPatch,
              pending: dict[str, list[tuple[str, str]]],
              target: str = TARGET, returncode: int = 0) -> list[list[str]]:
    """Fake target lookup, pip dry-run and pip list; return their commands.

    Installed versions are always pip 26.0 and twine 5.1.1.
    """
    calls: list[list[str]] = []
    installed = [{'name': 'pip', 'version': '26.0'},
                 {'name': 'twine', 'version': '5.1.1'}]

    def _run(cmd: list[str],
             **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if '-c' in cmd:
            stdout = target + '\n'
        elif '--dry-run' in cmd:
            stdout = json.dumps({'install': [
                {'metadata': {'name': name, 'version': version}}
                for name, version in pending.get(cmd[0], [])]})
        else:
            stdout = json.dumps(installed)
        return subprocess.CompletedProcess(cmd, returncode, stdout,
                                           'pip error\n')

    monkeypatch.setattr(sys, 'executable', LAUNCHER)
    monkeypatch.setattr(subprocess, 'run', _run)
    return calls


def _fake_install(monkeypatch: pytest.MonkeyPatch,
                  returncode: int = 0) -> list[list[str]]:
    """Fake pip install commands; return the recorded commands."""
    calls: list[list[str]] = []

    def _run(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        return returncode, f'installed {cmd[0]}\n'

    monkeypatch.setattr(global_packages, 'run_command_captured', _run)
    return calls


def _install_cmd(python: str, *args: str) -> list[str]:
    """Return expected pip install command."""
    return [python, '-m', 'pip', 'install', '--upgrade', *args]


@pytest.mark.parametrize('value, expected', [
    (None, 'install'), ('', 'install'), ('install', 'install'),
    ('  FORCE ', 'force'), ('Stop', 'stop'), ('skip', 'skip')])
def test_mode_valid(monkeypatch: pytest.MonkeyPatch, value: Optional[str],
                    expected: str) -> None:
    """Test CBT_GLOBAL_PIP values are case-insensitive, unset is install."""
    _set_mode(monkeypatch, value)
    assert global_packages.global_pip_mode() == expected


@pytest.mark.parametrize('value', ['yes', 'ok', 'no', 'ignore', 'report'])
def test_mode_invalid(monkeypatch: pytest.MonkeyPatch,
                      capsys: pytest.CaptureFixture[str], value: str) -> None:
    """Test invalid CBT_GLOBAL_PIP value exits with error listing values."""
    _set_mode(monkeypatch, value)
    with pytest.raises(SystemExit) as exc_info:
        global_packages.global_pip_mode()
    assert exc_info.value.code == 1
    assert 'install, force, stop, skip' in capsys.readouterr().err


def test_package_list_additional() -> None:
    """Test additional global packages are cleaned and added."""
    spec = BuildSpec(additional_global_packages=[' extra ', ' ', 'other'])
    assert global_packages._global_package_list(spec) == [
        *DEFAULT_LIST, 'extra', 'other']


def test_package_list_default() -> None:
    """Test default global package list without additional packages."""
    assert global_packages._global_package_list(BuildSpec()) == DEFAULT_LIST


@pytest.mark.parametrize('mode', ['install', 'force', 'stop', 'skip'])
def test_up_to_date(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """Test nothing is installed and no mode stops when up to date."""
    _set_mode(monkeypatch, mode)
    checks = _fake_pip(monkeypatch, pending={})
    installs = _fake_install(monkeypatch)
    log = global_packages.install_global_packages(['python3'], BuildSpec())
    assert not installs
    assert log == (f'Global packages (CBT_GLOBAL_PIP={mode}):\n'
                   f'  {TARGET}: up to date\n  {LAUNCHER}: up to date\n')
    dry_runs = [cmd for cmd in checks if '--dry-run' in cmd]
    assert [cmd[0] for cmd in dry_runs] == [TARGET, LAUNCHER]
    assert all('--no-cache-dir' in cmd for cmd in dry_runs)


def test_same_python_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test target Python equal to launching Python is checked once."""
    _set_mode(monkeypatch, None)
    checks = _fake_pip(monkeypatch, pending={}, target=LAUNCHER)
    _fake_install(monkeypatch)
    log = global_packages.install_global_packages(['py', '-3'], BuildSpec())
    assert checks[0] == ['py', '-3', '-c', 'import sys; print(sys.executable)']
    assert [cmd[0] for cmd in checks if '--dry-run' in cmd] == [LAUNCHER]
    assert log.endswith(f'  {LAUNCHER}: up to date\n')


@pytest.mark.parametrize('mode, flags', [
    (None, []), ('install', []), ('force', ['--break-system-packages'])])
def test_install_modes(monkeypatch: pytest.MonkeyPatch, mode: Optional[str],
                       flags: list[str]) -> None:
    """Test install and force modes install only into outdated Python."""
    _set_mode(monkeypatch, mode)
    _fake_pip(monkeypatch, pending={TARGET: [('twine', '6.0.0'),
                                             ('zipp', '4.1.2')]})
    installs = _fake_install(monkeypatch)
    log = global_packages.install_global_packages(['python3'], BuildSpec())
    assert installs == [_install_cmd(TARGET, *flags, *DEFAULT_LIST)]
    assert '    twine: 5.1.1 -> 6.0.0\n' in log
    assert '    zipp: not installed -> 4.1.2\n' in log
    assert f'  {LAUNCHER}: up to date\n' in log
    assert log.endswith(f'installed {TARGET}\n')


def test_pip_upgraded_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test outdated pip is upgraded alone without cache before the rest."""
    _set_mode(monkeypatch, 'force')
    _fake_pip(monkeypatch, pending={LAUNCHER: [('pip', '26.3')]})
    installs = _fake_install(monkeypatch)
    spec = BuildSpec(additional_global_packages=['pip>=26'])
    global_packages.install_global_packages(['python3'], spec)
    force = '--break-system-packages'
    assert installs == [
        _install_cmd(LAUNCHER, force, '--no-cache-dir', 'pip', 'pip>=26'),
        _install_cmd(LAUNCHER, force, *DEFAULT_LIST, 'pip>=26')]


def test_stop_reports_all(monkeypatch: pytest.MonkeyPatch,
                          capsys: pytest.CaptureFixture[str]) -> None:
    """Test stop mode reports both Pythons, explains fix and exits."""
    _set_mode(monkeypatch, 'stop')
    _fake_pip(monkeypatch, pending={TARGET: [('twine', '6.0.0')],
                                    LAUNCHER: [('gitpython', '3.1.45')]})
    installs = _fake_install(monkeypatch)
    with pytest.raises(SystemExit) as exc_info:
        global_packages.install_global_packages(['python3'], BuildSpec())
    assert exc_info.value.code == 1
    assert not installs
    captured = capsys.readouterr()
    assert '    twine: 5.1.1 -> 6.0.0\n' in captured.out
    assert '    gitpython: not installed -> 3.1.45\n' in captured.out
    assert f'    {TARGET} -m pip install --upgrade pip' in captured.err
    assert f'    {LAUNCHER} -m pip install --upgrade pip' in captured.err
    assert 'CBT_GLOBAL_PIP' in captured.err


def test_skip_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test skip mode reports and warns but installs nothing."""
    _set_mode(monkeypatch, 'skip')
    _fake_pip(monkeypatch, pending={TARGET: [('twine', '6.0.0')]})
    installs = _fake_install(monkeypatch)
    log = global_packages.install_global_packages(['python3'], BuildSpec())
    assert not installs
    assert '    twine: 5.1.1 -> 6.0.0\n' in log
    assert log.endswith('WARNING: global packages not changed '
                        '(CBT_GLOBAL_PIP=skip).\n')


@pytest.mark.parametrize('mode', ['install', 'force', 'stop', 'skip'])
def test_check_failure_exits(monkeypatch: pytest.MonkeyPatch,
                             capsys: pytest.CaptureFixture[str],
                             mode: str) -> None:
    """Test a failing check (no pip, no network) stops in every mode."""
    _set_mode(monkeypatch, mode)
    _fake_pip(monkeypatch, pending={}, returncode=3)
    installs = _fake_install(monkeypatch)
    with pytest.raises(SystemExit) as exc_info:
        global_packages.install_global_packages(['python3'], BuildSpec())
    assert exc_info.value.code == 3
    assert not installs
    err = capsys.readouterr().err
    assert err.startswith('pip error\nCommand failed: python3 -c')
    assert 'network access' in err


def test_install_failure_exits(monkeypatch: pytest.MonkeyPatch,
                               capsys: pytest.CaptureFixture[str]) -> None:
    """Test a failing install exits with its code and explains the fix."""
    _set_mode(monkeypatch, 'install')
    _fake_pip(monkeypatch, pending={TARGET: [('twine', '6.0.0')]})
    installs = _fake_install(monkeypatch, returncode=2)
    with pytest.raises(SystemExit) as exc_info:
        global_packages.install_global_packages(['python3'], BuildSpec())
    assert exc_info.value.code == 2
    assert len(installs) == 1
    assert '--break-system-packages' in capsys.readouterr().err
