#! /usr/bin/env python3
"""Check compact Python call, definition and class-base layout."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

from pathlib import Path
import io
import re
import sys
import tokenize
from token import NAME, OP
from tokenize import TokenInfo
from typing import NamedTuple, Optional


MAX_LINE_LENGTH = 79
RULE_EMPTY_OPEN = 'empty-open'
RULE_MORE_FITS = 'more-fits'
RULE_EMPTY_CLOSE = 'empty-close'
SUPPRESSION_PATTERN = (
    r'python-layout:?\s+disable(?P<next>-next)?='
    r'(?P<rules>[-\w, ]+)'
)
SUPPRESSION_RE = re.compile(SUPPRESSION_PATTERN)
OPEN_TO_CLOSE = {'(': ')', '[': ']', '{': '}'}
CALL_EXCLUDED_NAMES = {
    'and', 'assert', 'await', 'class', 'def', 'del', 'elif', 'except',
    'for', 'from', 'if', 'import', 'in', 'is', 'lambda', 'not', 'or',
    'raise', 'return', 'while', 'with', 'yield'
}


class Element(NamedTuple):
    """Token span for one argument, parameter, or class base."""

    start_line: int
    start_col: int
    end_line: int
    end_col: int
    text: str
    comma_line: Optional[int]
    comma_end_col: Optional[int]


class Target(NamedTuple):
    """One parenthesized target to check."""

    kind: str
    open_index: int
    close_index: int


class LayoutViolation(NamedTuple):
    """One python-layout finding."""

    path: Path
    line: int
    column: int
    rule: str
    message: str


class Suppressions(NamedTuple):
    """Line based rule suppressions."""

    same_line: dict[int, set[str]]
    next_line: dict[int, set[str]]


def _line_text(lines: list[str], line_number: int) -> str:
    """Return one source line without its line ending."""
    if line_number < 1 or line_number > len(lines):
        return ''
    return lines[line_number - 1]


def _single_line_text(lines: list[str], start: TokenInfo, end: TokenInfo) \
        -> str:
    """Return stripped source text for a single-line token span."""
    if start.start[0] != end.end[0]:
        return ''
    line = _line_text(lines, start.start[0])
    return line[start.start[1]:end.end[1]].strip()


def _previous_token(tokens: list[TokenInfo], index: int) \
        -> Optional[TokenInfo]:
    """Return previous significant token, or None."""
    if index <= 0:
        return None
    return tokens[index - 1]


def _token_before_previous(tokens: list[TokenInfo], index: int) \
        -> Optional[TokenInfo]:
    """Return token before the previous significant token, or None."""
    if index <= 1:
        return None
    return tokens[index - 2]


def _target_kind(tokens: list[TokenInfo], open_index: int) -> Optional[str]:
    """Return the target kind for an opening parenthesis."""
    previous = _previous_token(tokens, open_index)
    before_previous = _token_before_previous(tokens, open_index)
    if previous is None:
        return None
    if (previous.type == NAME and before_previous is not None and
            before_previous.string == 'def'):
        return 'parameter'
    if (previous.type == NAME and before_previous is not None and
            before_previous.string == 'class'):
        return 'base class'
    if previous.string in (')', ']', '}'):
        return 'argument'
    if previous.type == NAME and previous.string not in CALL_EXCLUDED_NAMES:
        return 'argument'
    return None


def _matching_close_index(tokens: list[TokenInfo], open_index: int) \
        -> Optional[int]:
    """Return matching closing parenthesis token index, or None."""
    depth = 0
    expected_close = tokens[open_index].string
    for index in range(open_index, len(tokens)):
        token = tokens[index]
        if token.type != OP:
            continue
        if token.string in OPEN_TO_CLOSE:
            if depth == 0:
                expected_close = OPEN_TO_CLOSE[token.string]
            depth += 1
            continue
        if token.string in OPEN_TO_CLOSE.values():
            depth -= 1
            if depth == 0 and token.string == expected_close:
                return index
    return None


def _targets(tokens: list[TokenInfo]) -> list[Target]:
    """Return all parenthesized calls, definitions and class base lists."""
    targets: list[Target] = []
    for index, token in enumerate(tokens):
        if token.type != OP or token.string != '(':
            continue
        kind = _target_kind(tokens, index)
        if kind is None:
            continue
        close_index = _matching_close_index(tokens, index)
        if close_index is not None:
            targets.append(Target(kind, index, close_index))
    return targets


def _elements(tokens: list[TokenInfo], target: Target, lines: list[str]) \
        -> list[Element]:
    """Return top-level elements inside one parenthesized target."""
    elements: list[Element] = []
    start_token: Optional[TokenInfo] = None
    last_token: Optional[TokenInfo] = None
    depth = 0
    for token in tokens[target.open_index + 1:target.close_index]:
        if token.type == OP and token.string in OPEN_TO_CLOSE:
            depth += 1
        elif token.type == OP and token.string in OPEN_TO_CLOSE.values():
            depth -= 1
        if token.type == OP and token.string == ',' and depth == 0:
            if start_token is not None and last_token is not None:
                text = _single_line_text(lines, start_token, last_token)
                element = Element(start_token.start[0], start_token.start[1],
                                  last_token.end[0], last_token.end[1], text,
                                  token.start[0], token.end[1])
                elements.append(element)
            start_token = None
            last_token = None
            continue
        if start_token is None:
            start_token = token
        last_token = token
    if start_token is not None and last_token is not None:
        text = _single_line_text(lines, start_token, last_token)
        element = Element(start_token.start[0], start_token.start[1],
                          last_token.end[0], last_token.end[1], text, None,
                          None)
        elements.append(element)
    return elements


def _fits_after(column: int, added_text: str, max_line_length: int) -> bool:
    """Return whether added text fits after the given source column."""
    return column + len(added_text) <= max_line_length


def _open_line_violation(tokens: list[TokenInfo], target: Target,
                         elements: list[Element], max_line_length: int) \
        -> Optional[LayoutViolation]:
    """Return violation when the first element should be on the open line."""
    open_token = tokens[target.open_index]
    first = elements[0]
    if first.start_line == open_token.start[0] or first.text == '':
        return None
    if not _fits_after(open_token.end[1], first.text, max_line_length):
        return None
    message = f'Put the first {target.kind} on the opening line.'
    line = open_token.start[0]
    column = open_token.start[1] + 1
    return LayoutViolation(Path(), line, column, RULE_EMPTY_OPEN, message)


def _next_element_text(current: Element, next_element: Element) -> str:
    """Return text needed to move next element to current line."""
    if next_element.text == '':
        return ''
    if current.comma_line == current.end_line:
        return ' ' + next_element.text
    return ', ' + next_element.text


def _current_end_column(current: Element) -> int:
    """Return column after current element and possible comma."""
    if (current.comma_line == current.end_line and
            current.comma_end_col is not None):
        return current.comma_end_col
    return current.end_col


def _more_fits_violations(target: Target, elements: list[Element],
                          max_line_length: int) -> list[LayoutViolation]:
    """Return violations for arguments that fit on the previous line."""
    violations: list[LayoutViolation] = []
    for current, next_element in zip(elements, elements[1:]):
        if current.end_line == next_element.start_line:
            continue
        added_text = _next_element_text(current, next_element)
        if added_text == '':
            continue
        if not _fits_after(_current_end_column(current), added_text,
                           max_line_length):
            continue
        message = f'Move the next {target.kind} to this line.'
        line = current.end_line
        column = current.end_col + 1
        violation = LayoutViolation(Path(), line, column, RULE_MORE_FITS,
                                    message)
        violations.append(violation)
    return violations


def _close_suffix(lines: list[str], close_token: TokenInfo) -> str:
    """Return source text from the closing parenthesis to line end."""
    line = _line_text(lines, close_token.start[0])
    return line[close_token.start[1]:].rstrip()


def _close_violation(tokens: list[TokenInfo], target: Target,
                     elements: list[Element], lines: list[str],
                     max_line_length: int) \
        -> Optional[LayoutViolation]:
    """Return violation when closing parenthesis should be on last line."""
    close_token = tokens[target.close_index]
    last = elements[-1]
    if close_token.start[0] == last.end_line:
        return None
    close_suffix = _close_suffix(lines, close_token)
    end_column = _current_end_column(last)
    if not _fits_after(end_column, close_suffix, max_line_length):
        return None
    message = f'Put the closing parenthesis on the last {target.kind} line.'
    line = close_token.start[0]
    column = close_token.start[1] + 1
    return LayoutViolation(Path(), line, column, RULE_EMPTY_CLOSE, message)


def _raw_violations(path: Path, source: str, max_line_length: int) \
        -> list[LayoutViolation]:
    """Return unsuppressed layout violations for source text."""
    lines = source.splitlines()
    readline = io.StringIO(source).readline
    tokens = [
        token for token in tokenize.generate_tokens(readline)
        if token.type not in (
            tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
            tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER
        )
    ]
    violations: list[LayoutViolation] = []
    for target in _targets(tokens):
        elements = _elements(tokens, target, lines)
        if not elements:
            continue
        open_violation = _open_line_violation(tokens, target, elements,
                                              max_line_length)
        if open_violation is not None:
            violations.append(open_violation._replace(path=path))
        for violation in _more_fits_violations(target, elements,
                                               max_line_length):
            violations.append(violation._replace(path=path))
        close_violation = _close_violation(tokens, target, elements, lines,
                                           max_line_length)
        if close_violation is not None:
            violations.append(close_violation._replace(path=path))
    return violations


def _parse_rule_names(text: str) -> set[str]:
    """Return normalized python-layout rule names from comment text."""
    rules = {rule.strip() for rule in text.split(',')}
    return {rule for rule in rules if rule}


def _suppression_comments(source: str) -> Suppressions:
    """Return line suppressions from python-layout comments."""
    same_line: dict[int, set[str]] = {}
    next_line: dict[int, set[str]] = {}
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        match = SUPPRESSION_RE.search(token.string)
        if match is None:
            continue
        names = _parse_rule_names(match.group('rules'))
        target = next_line if match.group('next') else same_line
        line = token.start[0] + 1 if match.group('next') else token.start[0]
        target.setdefault(line, set()).update(names)
    return Suppressions(same_line=same_line, next_line=next_line)


def _is_suppressed(violation: LayoutViolation, suppressions: Suppressions) \
        -> bool:
    """Return whether a violation is suppressed by source comments."""
    disabled = set()
    disabled.update(suppressions.same_line.get(violation.line, set()))
    disabled.update(suppressions.next_line.get(violation.line, set()))
    return 'all' in disabled or violation.rule in disabled


def check_source(path: Path, source: str,
                 max_line_length: int = MAX_LINE_LENGTH) \
        -> list[LayoutViolation]:
    """Return unsuppressed layout violations for one Python source."""
    suppressions = _suppression_comments(source)
    violations = _raw_violations(path, source, max_line_length)
    return [
        violation for violation in violations
        if not _is_suppressed(violation, suppressions)
    ]


def _python_files(paths: list[Path]) -> list[Path]:
    """Return sorted Python files below paths."""
    files: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix == '.py':
            files.append(path)
            continue
        if path.is_dir():
            files.extend(sorted(path.rglob('*.py')))
    return sorted(files)


def _format_violation(violation: LayoutViolation) -> str:
    """Return one human-readable violation line."""
    return (
        f'{violation.path}:{violation.line}:{violation.column}: '
        f'python-layout {violation.rule}: {violation.message}'
    )


def check_paths(paths: list[Path], max_line_length: int = MAX_LINE_LENGTH) \
        -> list[LayoutViolation]:
    """Return layout violations for all Python files below paths."""
    violations: list[LayoutViolation] = []
    for path in _python_files(paths):
        with tokenize.open(path) as file_obj:
            source = file_obj.read()
        violations.extend(check_source(path, source, max_line_length))
    return violations


def main(args: Optional[list[str]] = None) -> int:
    """Run command-line python-layout checker."""
    active_args = sys.argv[1:] if args is None else args
    paths = [Path(argument) for argument in active_args]
    if not paths:
        print('No python layout targets discovered.')
        return 0
    violations = check_paths(paths)
    if not violations:
        print('No python layout issues found.')
        return 0
    for violation in violations:
        print(_format_violation(violation))
    return 1


if __name__ == '__main__':
    sys.exit(main())
