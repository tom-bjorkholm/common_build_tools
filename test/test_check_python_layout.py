#! /usr/bin/env python3
"""Tests for common_build_tools.src.check_python_layout."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

from pathlib import Path
import pytest

import check_python_layout as layout


def _rules(source: str) -> list[str]:
    """Return python-layout rule names for source."""
    return [
        violation.rule
        for violation in layout.check_source(Path('sample.py'), source)
    ]


def test_accepts_compact_call() -> None:
    """Test compact calls have no violations."""
    source = 'result = func(first, second)\n'
    assert _rules(source) == []


def test_rejects_empty_open_call() -> None:
    """Test call with empty opening line is rejected."""
    source = 'result = func(\n    value)\n'
    assert _rules(source) == [layout.RULE_EMPTY_OPEN]


def test_rejects_more_fits_call() -> None:
    """Test next argument must stay on previous line when it fits."""
    source = 'result = func(first,\n              second)\n'
    assert _rules(source) == [layout.RULE_MORE_FITS]


def test_rejects_more_fits_after_first_line() -> None:
    """Test argument compaction is checked on later lines too."""
    source = (
        'result = func(argument_name_that_uses_most_of_the_line_but_still_'
        'fits_now,\n'
        '              second,\n'
        '              third)\n'
    )
    assert _rules(source) == [layout.RULE_MORE_FITS]


def test_rejects_empty_close_call() -> None:
    """Test closing parenthesis must stay with the last argument."""
    source = 'result = func(first,\n              second\n             )\n'
    assert layout.RULE_EMPTY_CLOSE in _rules(source)


@pytest.mark.parametrize('source', [
    'def func(\n        value: int) -> None:\n    pass\n',
    'class Example(\n        Base):\n    pass\n'])
def test_rejects_definitions_and_class_bases(source: str) -> None:
    """Test functions and class base lists use the same layout rules."""
    assert _rules(source) == [layout.RULE_EMPTY_OPEN]


def test_suppresses_next_line() -> None:
    """Test disable-next suppresses one named rule on the following line."""
    source = (
        '# python-layout disable-next=empty-open\n'
        'result = func(\n'
        '    value)\n'
    )
    assert _rules(source) == []


def test_suppresses_same_line() -> None:
    """Test same-line disable suppresses one named rule."""
    source = 'result = func(  # python-layout disable=empty-open\n    value)\n'
    assert _rules(source) == []


def test_suppresses_all_rules() -> None:
    """Test all suppresses all python-layout rule names."""
    source = (
        '# python-layout disable-next=all\n'
        'result = func(\n'
        '    value)\n'
    )
    assert _rules(source) == []


def test_ignores_parenthesized_tuple() -> None:
    """Test non-call parentheses are not checked."""
    source = 'value = (\n    1,\n    2)\n'
    assert _rules(source) == []


def test_check_paths_reads_python_files(tmp_path: Path) -> None:
    """Test path checking recursively reads Python files."""
    package = tmp_path / 'pkg'
    package.mkdir()
    good_source = 'value = func(1, 2)\n'
    bad_source = 'value = func(\n    1)\n'
    (package / 'good.py').write_text(good_source, encoding='utf-8')
    (package / 'bad.py').write_text(bad_source, encoding='utf-8')
    violations = layout.check_paths([package])
    assert [violation.rule for violation in violations] == [
        layout.RULE_EMPTY_OPEN
    ]
