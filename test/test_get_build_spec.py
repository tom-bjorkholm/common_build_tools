#! /usr/bin/env python3
"""Tests for common_build_tools.src.get_build_spec."""

# Copyright (c) 2026 Tom Björkholm
# MIT License
# pylint: disable=protected-access

import pytest

import get_build_spec
from build_spec import BuildSpec


def test_default_build_spec_has_expected_defaults() -> None:
    """Test default build spec values used by common build tools."""
    default_spec = BuildSpec()
    assert default_spec.package_folders is None
    assert default_spec.identical_versions is True
    assert default_spec.mypy_on_test is True
    assert default_spec.custom_final is None


def test_get_build_spec_returns_default_when_custom_none(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_build_spec falls back to default when custom returns None."""
    monkeypatch.setattr(get_build_spec, 'custom_spec', lambda: None)
    resolved = get_build_spec.get_build_spec()
    assert resolved == BuildSpec()


def test_get_build_spec_returns_custom_build_spec(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_build_spec returns valid BuildSpec from custom_spec."""
    custom = BuildSpec(identical_versions=False, mypy_on_test=False)
    monkeypatch.setattr(get_build_spec, 'custom_spec', lambda: custom)
    resolved = get_build_spec.get_build_spec()
    assert resolved == custom


def test_get_build_spec_rejects_invalid_custom_type(
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """Test get_build_spec prints error and returns default on bad type."""
    monkeypatch.setattr(get_build_spec, 'custom_spec', lambda: 'invalid')
    resolved = get_build_spec.get_build_spec()
    assert resolved == BuildSpec()
    captured = capsys.readouterr()
    assert 'custom_spec() did not return BuildSpec.' in captured.err
