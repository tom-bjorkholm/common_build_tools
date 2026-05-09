#! /usr/bin/env python3
"""Generate final build reports for the common build tool."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

from datetime import datetime
import html
from pathlib import Path
import re
import subprocess
from typing import Mapping, NamedTuple, Optional

from build_spec import BuildInformation, BuildSpec


REPORT_DIR_NAME = 'reports'
BUILD_LOG_NAME = 'build_log.txt'
PYTEST_LOG_NAME = 'pytest_log.txt'
PYLINT_LOG_NAME = 'pylint_log.txt'
FLAKE_LOG_NAME = 'flake8_log.txt'
MYPY_LOG_NAME = 'mypy_errors.txt'
PYTHON_LAYOUT_LOG_NAME = 'python_layout_log.txt'
FLAKE_DIR_NAME = 'flake_report'
MYPY_DIR_NAME = 'mypy_report'

REPORT_LINKS = [
    ('pytest_report.html?visible=failed,error,xfailed,xpassed,rerun',
     'pytest report'),
    ('coverage/index.html', 'coverage report'),
    ('flake_report/index.html', 'flake8 report'),
    ('mypy_report/index.html', 'mypy report'),
    ('mypy_errors.txt', 'mypy errors'),
    ('python_layout_log.txt', 'python layout log'),
    ('pylint_log.txt', 'pylint log'),
    ('build_log.txt', 'build log'),
    ('pytest_log.txt', 'pytest log')
]


class ReportSummary(NamedTuple):
    """Summary values shared by html and markdown report writers."""

    version_text: str
    test_summary: str
    flake8_clean: Optional[bool]
    mypy_clean: Optional[bool]
    python_layout_clean: Optional[bool]
    python_version: str
    build_failed: bool
    failure_messages: list[str]
    missing_report_messages: dict[str, str]
    repo_sync_warnings: list[str]


class BuildRunStatus(NamedTuple):
    """Exit status values needed when generating final build reports."""

    lint_codes: Mapping[str, Optional[int]]
    pytest_code: Optional[int]
    pydoc_code: Optional[int]


class BuildFailure(NamedTuple):
    """Failure details for builds that fail after wheel installation."""

    phase: str
    detail: str


class ReportGenerationContext(NamedTuple):
    """Inputs required for final report generation."""

    build_information: BuildInformation
    build_spec: BuildSpec
    report_paths: dict[str, Path]
    venv_cmd: list[str]
    build_run_status: BuildRunStatus
    build_failure: Optional[BuildFailure]
    repo_sync_warnings: list[str]


def _parse_pytest_summary(pytest_log: Path) -> tuple[str, int, bool]:
    """Parse pytest summary line from log file.

    Return tuple of (summary text, number of skipped tests, boolean failed).
    """
    if not pytest_log.exists():
        return '', 0, False
    last_summary = ''
    with open(pytest_log, encoding='utf-8') as file_obj:
        for line in file_obj:
            if (' passed' in line or ' failed' in line or
                    ' error' in line or ' skipped' in line):
                last_summary = line
    if not last_summary:
        return '', 0, False
    cleaned = last_summary.replace('=', '').strip()
    cleaned = re.sub(r'\.\d\ds', 's', cleaned)
    skipped_count = sum(
        int(count_text)
        for count_text in re.findall(r'(\d+)\s+skipped\b', last_summary))
    return cleaned, skipped_count, (
        'failed' in last_summary or 'error' in last_summary
    )


def _check_flake8_clean(report_paths: dict[str, Path]) -> Optional[bool]:
    """Return flake8 status, or None if no flake8 report was generated."""
    index_file = report_paths['flake_dir'] / 'index.html'
    if not index_file.exists():
        return None
    return 'No flake8 errors found' in index_file.read_text(encoding='utf-8')


def _check_mypy_clean(report_paths: dict[str, Path]) -> Optional[bool]:
    """Return mypy status, or None if no mypy log was generated."""
    if not report_paths['mypy_log'].exists():
        return None
    content = report_paths['mypy_log'].read_text(encoding='utf-8')
    if 'No mypy targets discovered.' in content:
        return None
    return 'Success: no issues found' in content


def _check_python_layout_clean(
        report_paths: dict[str, Path]) -> Optional[bool]:
    """Return python-layout status, or None if log was not generated."""
    if not report_paths['python_layout_log'].exists():
        return None
    content = report_paths['python_layout_log'].read_text(encoding='utf-8')
    if 'No python layout targets discovered.' in content:
        return None
    if 'Python layout check disabled.' in content:
        return None
    return 'No python layout issues found.' in content


def _test_summary_text(test_summary: str) -> str:
    """Return display text for the pytest summary."""
    if test_summary:
        return test_summary
    return 'Pytest summary not available.'


def _flake8_summary_text(flake8_clean: Optional[bool]) -> str:
    """Return display text for the flake8 summary."""
    if flake8_clean is True:
        return 'No flake8 warnings.'
    if flake8_clean is False:
        return 'Flake8 errors/warnings.'
    return 'Flake8 report not available.'


def _mypy_summary_text(mypy_clean: Optional[bool]) -> str:
    """Return display text for the mypy summary."""
    if mypy_clean is True:
        return 'No mypy errors found.'
    if mypy_clean is False:
        return 'mypy errors.'
    return 'mypy report not available.'


def _python_layout_summary_text(python_layout_clean: Optional[bool]) -> str:
    """Return display text for the python-layout summary."""
    if python_layout_clean is True:
        return 'No python layout warnings.'
    if python_layout_clean is False:
        return 'Python layout warnings.'
    return 'Python layout report not available.'


def _build_failure_messages(report_context: ReportGenerationContext,
                            pytest_failed: bool) -> list[str]:
    """Return failure messages for the final build summary."""
    failure_messages: list[str] = []
    if report_context.build_failure is not None:
        failure_messages.append(
            f'Failure in phase {report_context.build_failure.phase}: '
            f'{report_context.build_failure.detail}')
    if report_context.build_run_status.pydoc_code not in (None, 0):
        failure_messages.append(
            'pydoc-markdown returned '
            f'exit code {report_context.build_run_status.pydoc_code}.')
    flake8_code = report_context.build_run_status.lint_codes.get('flake8')
    if flake8_code not in (None, 0):
        failure_messages.append('flake8 reported errors or warnings.')
    mypy_code = report_context.build_run_status.lint_codes.get('mypy')
    if mypy_code not in (None, 0):
        failure_messages.append('mypy reported errors.')
    layout_code = report_context.build_run_status.lint_codes.get(
        'python_layout')
    if layout_code not in (None, 0):
        failure_messages.append(
            'python-layout reported warnings or failing guidance.')
    if (report_context.build_run_status.pytest_code not in (None, 0) or
            pytest_failed):
        failure_messages.append('pytest reported failures or errors.')
    return failure_messages


def _report_path_from_href(report_dir: Path, href: str) -> Path:
    """Return file path for one report link."""
    return report_dir / href.split('?', maxsplit=1)[0]


def _missing_report_message(href: str, build_run_status: BuildRunStatus,
                            build_failed: bool) -> str:
    """Return explanation text for one missing report link."""
    if not build_failed:
        return 'not generated'
    if href in ('mypy_report/index.html', 'mypy_errors.txt'):
        if build_run_status.lint_codes.get('mypy') is None:
            return 'not generated because build failed earlier'
    if href in ('flake_report/index.html', 'flake8_log.txt'):
        if build_run_status.lint_codes.get('flake8') is None:
            return 'not generated because build failed earlier'
    if href == 'python_layout_log.txt':
        if build_run_status.lint_codes.get('python_layout') is None:
            return 'not generated because build failed earlier'
    if (href.startswith('pytest_report.html') or
            href in ('coverage/index.html', 'pylint_log.txt',
                     'pytest_log.txt')):
        if build_run_status.pytest_code is None:
            return 'not generated because build failed earlier'
    return 'not generated'


def _missing_report_messages(report_paths: dict[str, Path],
                             build_run_status: BuildRunStatus,
                             build_failed: bool) -> dict[str, str]:
    """Return missing-report explanations keyed by link target."""
    missing_messages: dict[str, str] = {}
    report_dir = report_paths['report_dir']
    for href, _text in REPORT_LINKS:
        if _report_path_from_href(report_dir=report_dir, href=href).exists():
            continue
        missing_messages[href] = _missing_report_message(
            href=href, build_run_status=build_run_status,
            build_failed=build_failed)
    return missing_messages


def _replace_test_summary_in_readme(readme_path: Path,
                                    summary_path: Path) -> None:
    """Replace README content from `## Test summary` heading to end of file."""
    lines = readme_path.read_text(encoding='utf-8').splitlines(keepends=True)
    summary_start = len(lines)
    for index, line in enumerate(lines):
        if line.startswith('## Test summary'):
            summary_start = index
            break
    summary_text = summary_path.read_text(encoding='utf-8')
    with open(readme_path, 'w', encoding='utf-8') as file_obj:
        file_obj.writelines(lines[:summary_start])
        file_obj.write(summary_text)


def _update_readmes(build_information: BuildInformation, summary_file: Path) \
        -> None:
    """Update root and package README files with test summary."""
    readmes = [build_information['project_root'] / 'README.md']
    for package_data in build_information['package_information']:
        readmes.append(package_data['package_folder'] / 'README_pypi.md')
    for readme_path in readmes:
        if readme_path.exists():
            _replace_test_summary_in_readme(readme_path=readme_path,
                                            summary_path=summary_file)


def _get_python_version(venv_cmd: list[str], project_root: Path) -> str:
    """Return version text from virtual environment Python executable."""
    process = subprocess.run([*venv_cmd, '--version'], capture_output=True,
                             text=True, check=False, cwd=project_root)
    version_text = process.stdout.strip()
    if version_text:
        return version_text
    return process.stderr.strip()


def _build_version_text(build_information: BuildInformation) -> str:
    """Return single build version text for report header."""
    versions = sorted({
        package_data['version']
        for package_data in build_information['package_information']
    })
    if not versions:
        return 'unknown'
    if len(versions) == 1:
        return versions[0]
    return ', '.join(versions)


def _write_html_report(build_information: BuildInformation,
                       report_paths: dict[str, Path],
                       report_summary: ReportSummary) -> None:
    """Write reports/index.html summary page."""
    # pylint: disable=too-many-locals
    now = datetime.now().astimezone()
    index_file = report_paths['report_dir'] / 'index.html'
    layout_text = _python_layout_summary_text(
        report_summary.python_layout_clean)
    with open(index_file, 'w', encoding='utf-8') as file_obj:
        file_obj.write('<!DOCTYPE html>\n<html>\n<head>\n')
        file_obj.write('  <meta charset="utf-8" />\n')
        file_obj.write('  <title>Build report</title>\n')
        file_obj.write('</head>\n<body>\n')
        file_obj.write(now.strftime('<h1>Build report %Y-%m-%d %H:%M</h1>\n'))
        if report_summary.build_failed:
            file_obj.write('  <h2 style="color: #a00000;">Build failed</h2>\n')
            file_obj.write('  <ul>\n')
            for failure_message in report_summary.failure_messages:
                escaped_message = html.escape(failure_message)
                file_obj.write(f'    <li>{escaped_message}</li>\n')
            file_obj.write('  </ul>\n')
        else:
            file_obj.write(
                '  <h2 style="color: #006400;">Build succeeded</h2>\n')
        package_names = ', '.join(
            package_data['name']
            for package_data in build_information['package_information'])
        file_obj.write(f'<h2>Packages: {html.escape(package_names)}</h2>\n')
        file_obj.write(
            f'<h3>Version(s): '
            f'{html.escape(report_summary.version_text)}</h3>\n')
        file_obj.write(
            '<p>'
            f'{html.escape(_test_summary_text(report_summary.test_summary))}'
            '</p>\n')
        file_obj.write(
            '<p>'
            f'{html.escape(_flake8_summary_text(report_summary.flake8_clean))}'
            '</p>\n')
        file_obj.write(
            '<p>'
            f'{html.escape(_mypy_summary_text(report_summary.mypy_clean))}'
            '</p>\n')
        file_obj.write(
            '<p>'
            f'{html.escape(layout_text)}'
            '</p>\n')
        if report_summary.repo_sync_warnings:
            file_obj.write('<h3>Repository synchronization warnings</h3>\n')
            file_obj.write('<ul>\n')
            for warning_text in report_summary.repo_sync_warnings:
                escaped_warning = html.escape(warning_text)
                file_obj.write(f'  <li>{escaped_warning}</li>\n')
            file_obj.write('</ul>\n')
        file_obj.write(
            '<p>Build and test using '
            f'{html.escape(report_summary.python_version)}</p>\n')
        file_obj.write('<ul>\n')
        for href, text in REPORT_LINKS:
            missing_message = report_summary.missing_report_messages.get(href)
            if missing_message is None:
                file_obj.write(
                    '  <li><a href="'
                    f'{href}">{html.escape(text)}</a></li>\n')
                continue
            escaped_text = html.escape(text)
            escaped_message = html.escape(missing_message)
            file_obj.write(f'  <li>{escaped_text} ({escaped_message}).</li>\n')
        file_obj.write('</ul>\n')
        file_obj.write('</body>\n</html>\n')


def _write_test_summary(report_paths: dict[str, Path],
                        report_summary: ReportSummary) -> Path:
    """Write reports/test_summary.md and return its path."""
    summary_file = report_paths['report_dir'] / 'test_summary.md'
    layout_text = _python_layout_summary_text(
        report_summary.python_layout_clean)
    with open(summary_file, 'w', encoding='utf-8') as file_obj:
        file_obj.write('## Test summary\n\n')
        file_obj.write(
            f'- Test result: '
            f'{_test_summary_text(report_summary.test_summary)}\n')
        file_obj.write(
            f'- {_flake8_summary_text(report_summary.flake8_clean)}\n')
        file_obj.write(f'- {_mypy_summary_text(report_summary.mypy_clean)}\n')
        file_obj.write(f'- {layout_text}\n')
        file_obj.write(f'- Built version(s): {report_summary.version_text}\n')
        file_obj.write(
            f'- Build and test using {report_summary.python_version}\n')
    return summary_file


def _generate_reports(report_context: ReportGenerationContext) -> int:
    """Generate HTML/markdown reports and return final status code."""
    if report_context.build_spec.readme_summary_max_skipped < 0:
        raise ValueError('readme_summary_max_skipped must be non-negative.')
    pytest_summary, skipped, pytest_failed = _parse_pytest_summary(
        report_context.report_paths['pytest_log'])
    flake8_clean = _check_flake8_clean(report_context.report_paths)
    mypy_clean = _check_mypy_clean(report_context.report_paths)
    python_layout_clean = _check_python_layout_clean(
        report_context.report_paths)
    version_text = _build_version_text(report_context.build_information)
    python_version = _get_python_version(
        venv_cmd=report_context.venv_cmd,
        project_root=report_context.build_information['project_root'])
    failure_messages = _build_failure_messages(report_context=report_context,
                                               pytest_failed=pytest_failed)
    build_failed = bool(failure_messages)
    report_summary = ReportSummary(
        version_text=version_text, test_summary=pytest_summary,
        flake8_clean=flake8_clean, mypy_clean=mypy_clean,
        python_layout_clean=python_layout_clean, python_version=python_version,
        build_failed=build_failed, failure_messages=failure_messages,
        missing_report_messages=_missing_report_messages(
            report_paths=report_context.report_paths,
            build_run_status=report_context.build_run_status,
            build_failed=build_failed),
        repo_sync_warnings=list(report_context.repo_sync_warnings))
    _write_html_report(build_information=report_context.build_information,
                       report_paths=report_context.report_paths,
                       report_summary=report_summary)
    summary_file = _write_test_summary(
        report_paths=report_context.report_paths,
        report_summary=report_summary)
    if (pytest_summary and
            skipped <= report_context.build_spec.readme_summary_max_skipped):
        _update_readmes(build_information=report_context.build_information,
                        summary_file=summary_file)
    if build_failed:
        return 1
    return 0
