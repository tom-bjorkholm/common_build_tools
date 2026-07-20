#! /usr/bin/env python3
"""Wrapper files in repo root and their target scripts."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

WRAPPER_FILES: tuple[tuple[str, str], ...] = (
    ('run_build.py', 'do_build'),
    ('run_clean_build.py', 'clean_build'),
    ('run_pypi_build.py', 'do_pypi_build'),
    ('run_clean.py', 'clean'),
    ('run_setup_build_environment.py', 'setup_build_environment'),
    ('run_static_checks.py', 'static_checks'),
)
