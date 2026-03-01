#! /usr/bin/env python3
"""Shared file patterns used for line-ending normalization."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

EOL_ALLOWED_PATTERNS: tuple[str, ...] = (
    r'.*\.py$',
    r'.*\.md$',
    r'.*\.rst$',
    r'.*\.txt$',
    r'.*\.html$',
    r'.*\.css$',
    r'.*\.js$',
    r'.*\.json$',
    r'.*\.xml$',
    r'.*\.yaml$',
    r'.*\.yml$',
    r'.*\.ini$',
)
