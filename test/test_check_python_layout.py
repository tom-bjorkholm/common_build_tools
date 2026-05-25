#! /usr/bin/env python3
"""Tests for common_build_tools.src.check_python_layout."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

import check_python_layout as layout

EXPECTED_EMPTY_OPEN_WORDS = (
    'argument',
    'same line',
    'opening parenthesis'
)


def _rules(source: str) -> list[str]:
    """Return python-layout rule names for source."""
    return [
        violation.rule
        for violation in layout.check_source(Path('sample.py'), source)
    ]


def _guidance(source: str, changed_lines: set[int], max_len: int = 8) \
        -> list[layout.NameGuidance]:
    """Return long-name guidance for source."""
    return layout.check_guidance_source(Path('sample.py'), source,
                                        changed_lines, max_len)


def _copy_bad_fixture(fixture_name: str, tmp_dir: str) -> Path:
    """Copy one bad fixture to a temporary Python file."""
    fixture_path = Path(__file__).with_name(fixture_name)
    target_path = Path(tmp_dir) / 'bad_xx.py'
    source = fixture_path.read_text(encoding='utf-8')
    target_path.write_text(source, encoding='utf-8')
    return target_path


def _has_empty_open_message(text: str) -> bool:
    """Return True when text explains the empty-open argument failure."""
    lowered_text = text.lower()
    return all(word in lowered_text for word in EXPECTED_EMPTY_OPEN_WORDS)


def _has_empty_open_error(violations: list[layout.LayoutViolation]) -> bool:
    """Return True when violations contain the expected empty-open error."""
    return any(
        violation.rule == layout.RULE_EMPTY_OPEN and
        _has_empty_open_message(violation.message)
        for violation in violations)


@pytest.mark.parametrize('fixture_name', ['bad_1.txt', 'bad_2.txt'])
def test_rejects_empty_open_depdoc(fixture_name: str,
                                   capsys: pytest.CaptureFixture[str]) \
        -> None:
    """Test real depdoc snippets reject empty opening argument lines."""
    with TemporaryDirectory() as tmp_dir:
        bad_file = _copy_bad_fixture(fixture_name, tmp_dir)
        violations = layout.check_paths([bad_file])
        api_found = _has_empty_open_error(violations)
        exit_code = layout.main(['--no-name-guidance', str(bad_file)])
        output = capsys.readouterr().out
    main_found = exit_code == 1 and _has_empty_open_message(output)
    assert {'api': api_found, 'main': main_found} == {
        'api': True,
        'main': True
    }


def test_accepts_compact_call() -> None:
    """Test compact calls have no violations."""
    source = 'result = func(first, second)\n'
    assert _rules(source) == []


def test_rejects_empty_open_call() -> None:
    """Test call with empty opening line is rejected."""
    source = 'result = func(\n    value)\n'
    assert _rules(source) == [layout.RULE_EMPTY_OPEN]


def test_skips_open_for_long_indent() -> None:
    """Test empty-open is skipped when visual indent would be too long."""
    source = (
        'def function_name_that_is_long(\n'
        '        first_value_with_extra_words: int,\n'
        '        second_value_with_long_annotation: dict[str, str]) -> None:\n'
        '    pass\n'
    )
    assert _rules(source) == []


@pytest.mark.parametrize('source', [
    'def func(\n'
    '        file_access: FileAccess, capabilities: Capabilities,\n'
    '        error_file: TextIO = NO_ERROR_OUTPUT) -> None:\n'
    '    pass\n',
    'value = func(\n'
    '        first_arg, second_arg_with_a_name_that_makes_tail_long,\n'
    '        third_arg)\n'])
def test_rejects_open_long_tail(source: str) -> None:
    """Test only the first same-line item has to fit after open."""
    assert layout.RULE_EMPTY_OPEN in _rules(source)


def test_skips_open_long_tail() -> None:
    """Test empty-open is skipped when a later same-line item is too long."""
    source = (
        'def function_name_that_is_long(\n'
        '        first_value: int, second_value_with_long_annotation: '
        'dict[str, str]) -> None:\n'
        '    pass\n'
    )
    assert _rules(source) == []


def test_skips_open_long_following() -> None:
    """Test empty-open is skipped when later lines would be too long."""
    source = (
        'def function_name_that_is_long(\n'
        '        first_value: int,\n'
        '        second_value_with_long_annotation: dict[str, str]) -> None:\n'
        '    pass\n'
    )
    assert _rules(source) == []


def test_rejects_more_fits_call() -> None:
    """Test next argument must stay on previous line when it fits."""
    source = 'result = func(first,\n              second)\n'
    assert _rules(source) == [layout.RULE_MORE_FITS]


def test_skips_move_for_long_suffix() -> None:
    """Test more-fits is skipped when close suffix would make line long."""
    source = (
        'value = function_with_long_name(first_argument_with_padding,\n'
        '                                second_argument_with_padding'
        ').method_suffix()\n'
    )
    assert _rules(source) == []


def test_skips_move_for_long_comma() -> None:
    """Test more-fits counts the comma that moves with an argument."""
    source = (
        'def sample() -> None:\n'
        '    try:\n'
        "        process = subprocess.run(['py', flag, '--version'],\n"
        '                                 capture_output=True,\n'
        '                                 check_argument_name_that_is_long='
        'False)\n'
        '    except TimeoutError:\n'
        '        return\n'
    )
    assert _rules(source) == []


def test_skips_move_for_multi_line() -> None:
    """Test more-fits is skipped when the next argument is multi-line."""
    source = (
        'write_text(path,\n'
        "           'first line\\n'\n"
        "           'second line\\n')\n"
    )
    assert _rules(source) == []


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


def test_guidance_reports_names() -> None:
    """Test changed-line guidance reports long names by kind."""
    source = (
        'long_global = 1\n'
        'class LongClassName:\n'
        '    pass\n'
        'def long_function(long_parameter: int) -> None:\n'
        '    long_local = long_parameter\n'
    )
    messages = _guidance(source, {1, 2, 4, 5})
    assert [message.kind for message in messages] == [
        'global variable name',
        'class name',
        'function name',
        'parameter name',
        'local variable name'
    ]


def test_guidance_changed_lines() -> None:
    """Test unchanged long names do not produce guidance."""
    source = (
        'long_global = 1\n'
        'def long_function() -> None:\n'
        '    long_local = 1\n'
    )
    assert [message.kind for message in _guidance(source, {3})] == [
        'local variable name'
    ]


def test_guidance_ignores_skipped() -> None:
    """Test imports and conventional method parameters are ignored."""
    source = (
        'import module as long_import_alias\n'
        'def method(self, cls) -> None:\n'
        '    pass\n'
    )
    assert not _guidance(source, {1, 2}, max_len=10)


def test_changed_lines_from_diff() -> None:
    """Test changed line parser reads unified diff hunks."""
    diff_text = (
        'diff --git a/pkg.py b/pkg.py\n'
        '--- a/pkg.py\n'
        '+++ b/pkg.py\n'
        '@@ -2,0 +3,2 @@\n'
        '+first\n'
        '+second\n'
    )
    assert layout.changed_lines_from_diff(diff_text) == {
        Path('pkg.py'): {3, 4}
    }
