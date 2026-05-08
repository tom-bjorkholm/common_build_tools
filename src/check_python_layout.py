#! /usr/bin/env python3
"""Check compact Python layout and changed-line naming guidance."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

from pathlib import Path
import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize
from token import NAME, OP
from tokenize import TokenInfo
from typing import NamedTuple, Optional, Union


MAX_LINE_LENGTH = 79
DEFAULT_MAX_NAME_LENGTH = 32
RULE_EMPTY_OPEN = 'empty-open'
RULE_MORE_FITS = 'more-fits'
RULE_EMPTY_CLOSE = 'empty-close'
SUPPRESSION_PATTERN = (
    r'python-layout:?\s+disable(?P<next>-next)?='
    r'(?P<rules>[-\w, ]+)'
)
SUPPRESSION_RE = re.compile(SUPPRESSION_PATTERN)
OPEN_TO_CLOSE = {'(': ')', '[': ']', '{': '}'}
DIFF_HUNK_PATTERN = (
    r'^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@'
)
DIFF_HUNK_RE = re.compile(DIFF_HUNK_PATTERN)
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


class NameGuidance(NamedTuple):
    """One changed-line long-name guidance message."""

    path: Path
    line: int
    column: int
    kind: str
    name_length: int
    max_length: int


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


class NameGuidanceVisitor(ast.NodeVisitor):
    """Collect long-name guidance for changed definition and binding lines."""

    # pylint: disable=invalid-name

    def __init__(self, path: Path, changed_lines: set[int],
                 max_name_length: int) -> None:
        """Initialize guidance visitor for one file."""
        self._path = path
        self._changed_lines = changed_lines
        self._max_name_length = max_name_length
        self._scope_stack = ['module']
        self.guidance: list[NameGuidance] = []

    def _line_changed(self, line: int) -> bool:
        """Return whether line is part of the current git diff."""
        return line in self._changed_lines

    def _add_guidance(self, name: str, kind: str, line: int, column: int) \
            -> None:
        """Add guidance when name is long and its line changed."""
        if len(name) <= self._max_name_length:
            return
        if not self._line_changed(line):
            return
        self.guidance.append(NameGuidance(self._path, line, column, kind,
                                          len(name), self._max_name_length))

    def _variable_kind(self) -> Optional[str]:
        """Return guidance kind for the current assignment scope."""
        current_scope = self._scope_stack[-1]
        if current_scope == 'module':
            return 'global variable name'
        if current_scope == 'function':
            return 'local variable name'
        return None

    def _check_binding(self, name: str, line: int, column: int) -> None:
        """Check one variable binding name."""
        kind = self._variable_kind()
        if kind is not None:
            self._add_guidance(name, kind, line, column)

    def _check_parameter(self, argument: ast.arg) -> None:
        """Check one function parameter name."""
        if argument.arg in ('self', 'cls'):
            return
        column = argument.col_offset + 1
        self._add_guidance(argument.arg, 'parameter name', argument.lineno,
                           column)

    def _check_arguments(self, arguments: ast.arguments) -> None:
        """Check all function parameter names."""
        for argument in arguments.posonlyargs:
            self._check_parameter(argument)
        for argument in arguments.args:
            self._check_parameter(argument)
        if arguments.vararg is not None:
            self._check_parameter(arguments.vararg)
        for argument in arguments.kwonlyargs:
            self._check_parameter(argument)
        if arguments.kwarg is not None:
            self._check_parameter(arguments.kwarg)

    def _visit_statements(self, statements: list[ast.stmt]) -> None:
        """Visit statements in their existing scope."""
        for statement in statements:
            self.visit(statement)

    def _visit_function(self, node: Union[ast.FunctionDef,
                                          ast.AsyncFunctionDef]) -> None:
        """Check function name and body-local names."""
        self._add_guidance(node.name, 'function name', node.lineno,
                           node.col_offset + 1)
        self._check_arguments(node.args)
        self._scope_stack.append('function')
        self._visit_statements(node.body)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit a normal function definition."""
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit an async function definition."""
        self._visit_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit a class definition."""
        self._add_guidance(node.name, 'class name', node.lineno,
                           node.col_offset + 1)
        self._scope_stack.append('class')
        self._visit_statements(node.body)
        self._scope_stack.pop()

    def _check_target(self, target: ast.AST) -> None:
        """Check names introduced by an assignment target."""
        if isinstance(target, ast.Name):
            column = target.col_offset + 1
            self._check_binding(target.id, target.lineno, column)
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._check_target(element)
            return
        if isinstance(target, ast.Starred):
            self._check_target(target.value)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Visit an assignment statement."""
        for target in node.targets:
            self._check_target(target)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Visit an annotated assignment statement."""
        self._check_target(node.target)
        self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """Visit an augmented assignment statement."""
        self._check_target(node.target)
        self.visit(node.value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        """Visit an assignment expression."""
        self._check_target(node.target)
        self.visit(node.value)

    def _visit_for(self, node: Union[ast.For, ast.AsyncFor]) -> None:
        """Visit a for statement."""
        self._check_target(node.target)
        self.visit(node.iter)
        self._visit_statements(node.body)
        self._visit_statements(node.orelse)

    def visit_For(self, node: ast.For) -> None:
        """Visit a normal for statement."""
        self._visit_for(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        """Visit an async for statement."""
        self._visit_for(node)

    def _visit_with(self, node: Union[ast.With, ast.AsyncWith]) -> None:
        """Visit a with statement."""
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._check_target(item.optional_vars)
        self._visit_statements(node.body)

    def visit_With(self, node: ast.With) -> None:
        """Visit a normal with statement."""
        self._visit_with(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        """Visit an async with statement."""
        self._visit_with(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        """Visit an exception handler."""
        if node.type is not None:
            self.visit(node.type)
        if node.name is not None:
            self._check_binding(node.name, node.lineno, node.col_offset + 1)
        self._visit_statements(node.body)


def check_guidance_source(path: Path, source: str, changed_lines: set[int],
                          max_name_length: int) -> list[NameGuidance]:
    """Return long-name guidance for changed lines in one Python source."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    visitor = NameGuidanceVisitor(path=path, changed_lines=changed_lines,
                                  max_name_length=max_name_length)
    visitor.visit(tree)
    return visitor.guidance


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


def changed_lines_from_diff(diff_text: str) -> dict[Path, set[int]]:
    """Return changed new-file line numbers parsed from unified diff text."""
    changed_lines: dict[Path, set[int]] = {}
    current_path: Optional[Path] = None
    for line in diff_text.splitlines():
        if line.startswith('+++ b/'):
            current_path = Path(line[6:])
            changed_lines.setdefault(current_path, set())
            continue
        if line.startswith('+++ /dev/null'):
            current_path = None
            continue
        if current_path is None:
            continue
        match = DIFF_HUNK_RE.match(line)
        if match is None:
            continue
        start = int(match.group('start'))
        count_text = match.group('count')
        count = 1 if count_text is None else int(count_text)
        changed_lines[current_path].update(range(start, start + count))
    return changed_lines


def _git_output(args: list[str], project_root: Path) -> Optional[str]:
    """Return git command output, or None when git command fails."""
    process = subprocess.run(args, cwd=project_root, capture_output=True,
                             text=True, check=False)
    if process.returncode != 0:
        return None
    return process.stdout


def _git_root(start_folder: Path) -> Optional[Path]:
    """Return git repository root for start_folder, or None."""
    output = _git_output(['git', 'rev-parse', '--show-toplevel'], start_folder)
    if output is None:
        return None
    return Path(output.strip()).resolve()


def _relative_file_paths(files: list[Path], project_root: Path) -> list[Path]:
    """Return file paths relative to project_root."""
    relative_paths: list[Path] = []
    for file_path in files:
        try:
            resolved_path = file_path.resolve()
            relative_paths.append(resolved_path.relative_to(project_root))
        except ValueError:
            continue
    return relative_paths


def _all_file_lines(path: Path) -> set[int]:
    """Return every line number in a Python source file."""
    with tokenize.open(path) as file_obj:
        line_count = len(file_obj.read().splitlines())
    return set(range(1, line_count + 1))


def _files_by_git_root(files: list[Path], root: Optional[Path]) \
        -> dict[Path, list[Path]]:
    """Return files grouped by git root."""
    if root is not None:
        return {root.resolve(): files}
    grouped: dict[Path, list[Path]] = {}
    for file_path in files:
        git_root = _git_root(file_path.parent)
        if git_root is not None:
            grouped.setdefault(git_root, []).append(file_path)
    return grouped


def _changed_lines_in_root(files: list[Path], project_root: Path) \
        -> dict[Path, set[int]]:
    """Return changed line numbers for files in one git root."""
    relative_paths = _relative_file_paths(files, project_root)
    if not relative_paths:
        return {}
    path_args = [str(path) for path in relative_paths]
    diff_args = ['git', 'diff', '--unified=0', 'HEAD', '--', *path_args]
    diff_output = _git_output(diff_args, project_root)
    if diff_output is None:
        return {}
    parsed = changed_lines_from_diff(diff_output)
    changed_lines = {
        (project_root / path).resolve(): lines
        for path, lines in parsed.items()
    }
    untracked_args = [
        'git', 'ls-files', '--others', '--exclude-standard', '--', *path_args]
    untracked_output = _git_output(untracked_args, project_root)
    if untracked_output is None:
        return changed_lines
    for line in untracked_output.splitlines():
        path = (project_root / line).resolve()
        if path.suffix == '.py' and path.is_file():
            changed_lines[path] = _all_file_lines(path)
    return changed_lines


def changed_lines_for_files(files: list[Path],
                            project_root: Optional[Path] = None) \
        -> dict[Path, set[int]]:
    """Return changed line numbers for tracked and untracked files."""
    changed_lines: dict[Path, set[int]] = {}
    grouped_files = _files_by_git_root(files, project_root)
    for git_root, root_files in grouped_files.items():
        changed_lines.update(_changed_lines_in_root(root_files, git_root))
    return changed_lines


def _format_violation(violation: LayoutViolation) -> str:
    """Return one human-readable violation line."""
    return (
        f'{violation.path}:{violation.line}:{violation.column}: '
        f'python-layout {violation.rule}: {violation.message}'
    )


def _format_guidance(guidance: NameGuidance) -> str:
    """Return one human-readable long-name guidance line."""
    return (
        f'{guidance.path}:{guidance.line}:{guidance.column}: '
        f'python-layout long-name guidance: {guidance.kind} is '
        f'{guidance.name_length} chars; consider <= {guidance.max_length}'
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


def check_guidance_paths(paths: list[Path],
                         max_name_length: int = DEFAULT_MAX_NAME_LENGTH,
                         project_root: Optional[Path] = None) \
        -> list[NameGuidance]:
    """Return changed-line name guidance for all Python files below paths."""
    files = _python_files(paths)
    changed_lines_by_path = changed_lines_for_files(files, project_root)
    guidance: list[NameGuidance] = []
    for path in files:
        changed_lines = changed_lines_by_path.get(path.resolve(), set())
        if not changed_lines:
            continue
        with tokenize.open(path) as file_obj:
            source = file_obj.read()
        messages = check_guidance_source(path, source, changed_lines,
                                         max_name_length)
        guidance.extend(messages)
    return guidance


def _argument_parser() -> argparse.ArgumentParser:
    """Return command line argument parser."""
    description = (
        'Check compact Python layout and changed-line name guidance.'
    )
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--max-name-length', type=int,
                        default=DEFAULT_MAX_NAME_LENGTH)
    parser.add_argument('--no-name-guidance', action='store_true')
    parser.add_argument('--name-guidance-fails', action='store_true')
    parser.add_argument('paths', nargs='*')
    return parser


def _print_layout_section(violations: list[LayoutViolation]) -> None:
    """Print layout section of checker output."""
    if not violations:
        print('No python layout issues found.')
        return
    for violation in violations:
        print(_format_violation(violation))


def _print_guidance_section(guidance: list[NameGuidance],
                            guidance_enabled: bool) -> None:
    """Print guidance section of checker output."""
    print()
    if not guidance_enabled:
        print('python-layout guidance disabled.')
        return
    if not guidance:
        print('No python-layout guidance messages.')
        return
    for message in guidance:
        print(_format_guidance(message))


def main(args: Optional[list[str]] = None) -> int:
    """Run command-line python-layout checker."""
    active_args = sys.argv[1:] if args is None else args
    parsed_args = _argument_parser().parse_args(active_args)
    if parsed_args.max_name_length < 1:
        print('--max-name-length must be greater than zero.', file=sys.stderr)
        return 2
    paths = [Path(argument) for argument in parsed_args.paths]
    if not paths:
        print('No python layout targets discovered.')
        return 0
    violations = check_paths(paths)
    guidance_enabled = not parsed_args.no_name_guidance
    guidance: list[NameGuidance] = []
    if guidance_enabled:
        guidance = check_guidance_paths(paths, parsed_args.max_name_length)
    _print_layout_section(violations)
    _print_guidance_section(guidance, guidance_enabled)
    if violations:
        return 1
    if guidance and parsed_args.name_guidance_fails:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
