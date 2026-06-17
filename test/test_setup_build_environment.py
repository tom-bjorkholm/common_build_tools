#! /usr/bin/env python3
"""Tests for common_build_tools.src.setup_build_environment."""

# Copyright (c) 2026 Tom Björkholm
# MIT License
# pylint: disable=protected-access

from pathlib import Path
import pytest

import setup_build_environment
from build_spec import BuildSpec
from common_build_tools.test.helpers import (
    make_build_information,
    make_package_information,
)


def test_dyn_deps_skip_internal() -> None:
    """Test dynamic package list excludes internal and deduplicates entries."""
    info = make_build_information(project_root=Path('/tmp/project'),
                                  package_information=[
            make_package_information(
                package_folder=Path('/tmp/pkg-core'), name='pkg-core',
                dependencies=['requests>=2.0', 'pkg-utils>=1.0']),
            make_package_information(
                package_folder=Path('/tmp/pkg-utils'), name='pkg-utils',
                dependencies=['requests>=2.0', 'typing-extensions']),
        ])
    dependencies = setup_build_environment._dynamic_package_dependencies(info)
    assert dependencies == ['requests>=2.0', 'typing-extensions']


def test_additional_venv_strips_ws() -> None:
    """Test additional venv packages remove empty and whitespace-only items."""
    spec = BuildSpec(additional_venv_packages=['  extra-one ', ' ', 'extra2'])
    assert setup_build_environment._additional_venv_packages(spec) == [
        'extra-one',
        'extra2',
    ]


def test_venv_install_list_sources() -> None:
    """Test venv install list merges base, dynamic, custom and pinned sets."""
    spec = BuildSpec(additional_venv_packages=['extra-package'])
    info = make_build_information(project_root=Path('/tmp/project'),
                                  package_information=[
            make_package_information(package_folder=Path('/tmp/pkg-core'),
                                     name='pkg-core',
                                     dependencies=['requests>=2.0']),
        ])
    install_list = setup_build_environment._venv_install_list(spec, info)
    assert install_list[0] == 'pip'
    assert 'requests>=2.0' in install_list
    assert 'extra-package' in install_list
    pinned = setup_build_environment.VENV_PINNED_PACKAGES
    assert install_list[-len(pinned):] == pinned
    assert 'pytest<9.1' in pinned
    assert 'twine' in setup_build_environment.VENV_PACKAGES


def test_setup_env_runs_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test setup_build_environment orchestrates helper calls in sequence."""
    events: list[str] = []
    info = make_build_information(Path('/tmp/project'))
    monkeypatch.setattr(setup_build_environment, 'exit_if_in_virtualenv',
                        lambda _action: events.append('exit_check'))
    monkeypatch.setattr(setup_build_environment, 'resolve_target_python',
                        lambda _python_name: ('python3.13', ['python3.13']))
    monkeypatch.setattr(setup_build_environment, '_install_global_packages',
                        lambda _cmd: events.append('install_global'))
    monkeypatch.setattr(
        setup_build_environment, '_create_or_recreate_venv', lambda _cmd,
        force_recreate: events.append(f'create_venv:{force_recreate}'))
    monkeypatch.setattr(setup_build_environment, '_install_venv_packages',
                        lambda _spec, _info: events.append('install_venv'))
    setup_build_environment.setup_build_environment(python_name='python3.13',
                                                    force_recreate=True,
                                                    build_spec=BuildSpec(),
                                                    build_information=info)
    assert events == [
        'exit_check',
        'install_global',
        'create_venv:True',
        'install_venv',
    ]


def test_setup_env_default_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test setup_build_environment calls get_build_spec when spec is None."""
    resolved_spec = BuildSpec()
    info = make_build_information(Path('/tmp/project'))
    monkeypatch.setattr(setup_build_environment, 'get_build_spec',
                        lambda: resolved_spec)
    monkeypatch.setattr(setup_build_environment, 'get_build_information',
                        lambda _spec: info)
    monkeypatch.setattr(setup_build_environment, 'exit_if_in_virtualenv',
                        lambda _action: None)
    monkeypatch.setattr(setup_build_environment, 'resolve_target_python',
                        lambda _python_name: ('python3.14', ['python3.14']))
    monkeypatch.setattr(setup_build_environment, '_install_global_packages',
                        lambda _cmd: None)
    monkeypatch.setattr(setup_build_environment, '_create_or_recreate_venv',
                        lambda _cmd, force_recreate: None)
    monkeypatch.setattr(setup_build_environment, '_install_venv_packages',
                        lambda _spec, _info: None)
    setup_build_environment.setup_build_environment()


def test_setup_env_cmd_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test setup_build_environment_cmd exits zero after setup call."""
    called: list[str] = []
    monkeypatch.setattr(setup_build_environment, 'extract_python_name',
                        lambda _args: 'python3.12')
    monkeypatch.setattr(setup_build_environment, 'setup_build_environment',
                        lambda python_name, force_recreate, build_spec,
                        build_information: called.append(
                            f'{python_name}:{force_recreate}'))
    with pytest.raises(SystemExit) as exc_info:
        setup_build_environment.setup_build_environment_cmd()
    assert called == ['python3.12:False']
    assert exc_info.value.code == 0
