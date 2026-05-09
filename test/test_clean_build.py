#! /usr/bin/env python3
"""Tests for common_build_tools.src.clean_build."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

from pathlib import Path
import pytest

import clean_build
from build_spec import BuildSpec
from common_build_tools.test.helpers import make_build_information


def test_clean_build_step_order(monkeypatch: pytest.MonkeyPatch,
                                tmp_path: Path) -> None:
    """Test clean_build calls clean, setup, then do_build in order."""
    info = make_build_information(tmp_path)
    events: list[str] = []
    monkeypatch.setattr(clean_build, 'exit_if_in_virtualenv',
                        lambda _action: events.append('exit_check'))
    monkeypatch.setattr(clean_build, 'resolve_target_python',
                        lambda _name: ('python3.13', ['python3.13']))

    def _fake_clean(*_args: object, **_kwargs: object) -> None:
        events.append('clean')

    def _fake_setup(*_args: object, **_kwargs: object) -> None:
        events.append('setup')

    def _fake_do_build(*_args: object, **_kwargs: object) -> int:
        events.append('build')
        return 0

    monkeypatch.setattr(clean_build, 'clean', _fake_clean)
    monkeypatch.setattr(clean_build, 'setup_build_environment', _fake_setup)
    monkeypatch.setattr(clean_build, 'do_build', _fake_do_build)
    result = clean_build.clean_build(python_name='python3.13',
                                     build_spec=BuildSpec(),
                                     build_information=info)
    assert result == 0
    assert events == ['exit_check', 'clean', 'setup', 'build']


def test_clean_build_gets_spec_info(monkeypatch: pytest.MonkeyPatch,
                                    tmp_path: Path) -> None:
    """Test clean_build discovers BuildSpec and BuildInformation if omitted."""
    info = make_build_information(tmp_path)
    spec = BuildSpec()
    monkeypatch.setattr(clean_build, 'get_build_spec', lambda: spec)
    monkeypatch.setattr(clean_build, 'get_build_information',
                        lambda build_spec: info)
    monkeypatch.setattr(clean_build, 'exit_if_in_virtualenv',
                        lambda _action: None)
    monkeypatch.setattr(clean_build, 'resolve_target_python',
                        lambda _name: ('python3.14', ['python3.14']))
    monkeypatch.setattr(clean_build, 'clean', lambda **_kwargs: None)
    monkeypatch.setattr(clean_build, 'setup_build_environment',
                        lambda **_kwargs: None)
    monkeypatch.setattr(clean_build, 'do_build', lambda **_kwargs: 0)
    assert clean_build.clean_build() == 0


def test_clean_build_cmd_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test clean_build_cmd exits with the code from clean_build."""
    monkeypatch.setattr(clean_build, 'extract_python_name',
                        lambda _args: 'python3.12')
    monkeypatch.setattr(clean_build, 'clean_build', lambda *_args,
                        **_kwargs: 3)
    with pytest.raises(SystemExit) as exc_info:
        clean_build.clean_build_cmd()
    assert exc_info.value.code == 3
