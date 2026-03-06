#! /usr/bin/env python3
"""Tests for constant-only modules in common_build_tools/src."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

from eol_patterns import EOL_ALLOWED_PATTERNS
from wrapper_file_list import WRAPPER_FILES


def test_eol_allowed_patterns_include_expected_extensions() -> None:
    """Test EOL pattern list includes core text-oriented extensions."""
    assert r'.*\.py$' in EOL_ALLOWED_PATTERNS
    assert r'.*\.md$' in EOL_ALLOWED_PATTERNS
    assert r'.*\.json$' in EOL_ALLOWED_PATTERNS


def test_wrapper_files_define_expected_targets() -> None:
    """Test wrapper mapping includes core wrapper-to-script relations."""
    assert ('run_build.py', 'do_build') in WRAPPER_FILES
    assert ('run_clean.py', 'clean') in WRAPPER_FILES
    assert ('run_pypi_build.py', 'do_pypi_build') in WRAPPER_FILES
