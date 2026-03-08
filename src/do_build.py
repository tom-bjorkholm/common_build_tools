#! /usr/bin/env python3
"""Build packages, run checks/tests and generate reports."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

from datetime import datetime
import html
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback
from typing import NamedTuple, Optional

from best_installed_python import resolve_target_python
from build_information import get_build_information
from build_spec import (
    BuildInformation,
    BuildSpec,
    CustomFunction,
    PackageInformation,
)
from build_utils import (
    append_to_path_env,
    extract_python_name,
    run_command_logged,
    venv_python,
    venv_script,
)
from get_build_spec import get_build_spec
from git_helpers import get_repo_sync_warnings, restore_bad_eol_changes
from setup_build_environment import setup_build_environment


REPORT_DIR_NAME = 'reports'
DIST_DIR_NAME = 'dist'
CUSTOM_BUILD_TOOLS_DIR_NAME = 'custom_build_tools'
BUILD_LOG_NAME = 'build_log.txt'
PYTEST_LOG_NAME = 'pytest_log.txt'
PYLINT_LOG_NAME = 'pylint_log.txt'
FLAKE_LOG_NAME = 'flake8_log.txt'
MYPY_LOG_NAME = 'mypy_errors.txt'
FLAKE_DIR_NAME = 'flake_report'
MYPY_DIR_NAME = 'mypy_report'

REPORT_LINKS = [
    ('pytest_report.html?visible=failed,error,xfailed,xpassed,rerun',
     'pytest report'),
    ('coverage/index.html', 'coverage report'),
    ('flake_report/index.html', 'flake8 report'),
    ('mypy_report/index.html', 'mypy report'),
    ('mypy_errors.txt', 'mypy errors'),
    ('pylint_log.txt', 'pylint log'),
    ('build_log.txt', 'build log'),
    ('pytest_log.txt', 'pytest log'),
]


class ReportSummary(NamedTuple):
    """Summary values shared by html and markdown report writers."""

    version_text: str
    test_summary: str
    flake8_clean: bool
    mypy_clean: bool
    python_version: str
    repo_sync_warnings: list[str]


class BuildRunStatus(NamedTuple):
    """Exit status values needed when generating final build reports."""

    lint_codes: dict[str, int]
    pytest_code: int


class ReportGenerationContext(NamedTuple):
    """Inputs required for final report generation."""

    build_information: BuildInformation
    build_spec: BuildSpec
    report_paths: dict[str, Path]
    venv_cmd: list[str]
    build_run_status: BuildRunStatus
    repo_sync_warnings: list[str]


def _run_custom_hooks(hooks: Optional[list[CustomFunction]],
                      build_spec: BuildSpec,
                      build_information: BuildInformation) -> None:
    """Run custom hooks in specified order."""
    if not hooks:
        return
    for hook in hooks:
        hook(build_spec, build_information)


def _ensure_venv(python_name: Optional[str], project_root: Path,
                 build_spec: BuildSpec,
                 build_information: BuildInformation) -> None:
    """Create build environment if venv is missing."""
    venv_cmd = venv_python()
    venv_path = project_root / venv_cmd[0]
    if venv_path.exists():
        return
    setup_build_environment(
        python_name=python_name,
        build_spec=build_spec,
        build_information=build_information
    )


def _clean_cache_folders(build_information: BuildInformation) -> None:
    """Remove __pycache__ folders below discovered lint/test folders."""
    candidate_roots = (
        build_information['flake8_folders'] +
        build_information['pylint_folders'] +
        build_information['mypy_folders'] +
        build_information['pytest_folders']
    )
    seen: set[Path] = set()
    for root_folder in candidate_roots:
        if root_folder in seen:
            continue
        seen.add(root_folder)
        if not root_folder.is_dir():
            continue
        for cache_folder in root_folder.rglob('__pycache__'):
            shutil.rmtree(cache_folder, ignore_errors=True)


def _prepare_directories(
        project_root: Path,
        build_information: BuildInformation) -> dict[str, Path]:
    """Clean and recreate output directories used by do_build."""
    report_dir = project_root / REPORT_DIR_NAME
    dist_dir = project_root / DIST_DIR_NAME
    shutil.rmtree(report_dir, ignore_errors=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(dist_dir, ignore_errors=True)
    dist_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(project_root / 'build', ignore_errors=True)
    for package_data in build_information['package_information']:
        package_folder = package_data['package_folder']
        shutil.rmtree(package_folder / 'build', ignore_errors=True)
        shutil.rmtree(package_folder / 'dist', ignore_errors=True)
    (report_dir / FLAKE_DIR_NAME).mkdir(parents=True, exist_ok=True)
    (report_dir / MYPY_DIR_NAME).mkdir(parents=True, exist_ok=True)
    _clean_cache_folders(build_information)
    return {
        'report_dir': report_dir,
        'dist_dir': dist_dir,
        'build_log': report_dir / BUILD_LOG_NAME,
        'pytest_log': report_dir / PYTEST_LOG_NAME,
        'pylint_log': report_dir / PYLINT_LOG_NAME,
        'flake_log': report_dir / FLAKE_LOG_NAME,
        'mypy_log': report_dir / MYPY_LOG_NAME,
        'flake_dir': report_dir / FLAKE_DIR_NAME,
        'mypy_dir': report_dir / MYPY_DIR_NAME,
    }


def _package_map_by_name(
        build_information: BuildInformation) -> dict[str, PackageInformation]:
    """Return package info lookup by package name."""
    return {
        package_data['name']: package_data
        for package_data in build_information['package_information']
    }


def _build_packages(venv_cmd: list[str], build_information: BuildInformation,
                    build_log: Path, project_root: Path) -> int:
    """Build all packages to the main repository dist/ directory."""
    package_map = _package_map_by_name(build_information)
    for package_name in build_information['package_install_order']:
        package_data = package_map[package_name]
        package_folder = package_data['package_folder']
        return_code = run_command_logged(
            [*venv_cmd, '-m', 'build', str(package_folder), '--outdir',
             DIST_DIR_NAME],
            log_file=build_log,
            check=False,
            cwd=project_root,
        )
        if return_code != 0:
            return return_code
    return 0


def _wheel_regex_for_package(package_name: str) -> re.Pattern[str]:
    """Return regex for wheel files of one package."""
    escaped_name = ''.join(
        '[-_]' if char in '-_' else re.escape(char)
        for char in package_name
    )
    return re.compile(rf'^{escaped_name}-.*\.whl$')


def _find_wheel(dist_dir: Path, package_name: str) -> Path:
    """Find built wheel file for package in dist directory."""
    pattern = _wheel_regex_for_package(package_name)
    wheel_files = sorted(
        wheel for wheel in dist_dir.glob('*.whl')
        if pattern.match(wheel.name)
    )
    if wheel_files:
        return wheel_files[-1]
    raise ValueError(f'Built wheel not found for package {package_name}')


def _install_packages(venv_cmd: list[str], build_information: BuildInformation,
                      build_log: Path, dist_dir: Path,
                      project_root: Path) -> int:
    """Install built wheel packages in dependency order."""
    pip_names = [
        package_data['name'].replace('_', '-')
        for package_data in build_information['package_information']
    ]
    run_command_logged(
        [*venv_cmd, '-m', 'pip', 'uninstall', '-y', *pip_names],
        log_file=build_log,
        check=False,
        cwd=project_root,
    )
    package_map = _package_map_by_name(build_information)
    for package_name in build_information['package_install_order']:
        _ = package_map[package_name]
        wheel_file = _find_wheel(dist_dir=dist_dir, package_name=package_name)
        return_code = run_command_logged(
            [*venv_cmd, '-m', 'pip', 'install', str(wheel_file)],
            log_file=build_log,
            check=False,
            cwd=project_root,
        )
        if return_code != 0:
            return return_code
    return 0


def _run_mypy(venv_cmd: list[str], build_information: BuildInformation,
              mypy_log: Path, mypy_dir: Path, project_root: Path) -> int:
    """Run mypy in strict mode on discovered folders."""
    if not build_information['mypy_folders']:
        mypy_log.write_text('No mypy targets discovered.\n', encoding='utf-8')
        return 0
    environment = dict(os.environ)
    environment['MYPYPATH'] = append_to_path_env(
        existing_path=environment.get('MYPYPATH'),
        additional_paths=build_information['mypy_path_folders']
    )
    return run_command_logged(
        [*venv_cmd, '-m', 'mypy', '--strict', '--explicit-package-bases',
         '--html-report', str(mypy_dir),
         *[str(path) for path in build_information['mypy_folders']]],
        log_file=mypy_log,
        check=False,
        cwd=project_root,
        env=environment,
    )


def _run_flake8(venv_cmd: list[str], build_information: BuildInformation,
                flake_log: Path, flake_dir: Path, project_root: Path) -> int:
    """Run flake8 on discovered folders."""
    if not build_information['flake8_folders']:
        flake_log.write_text('No flake8 targets discovered.\n',
                             encoding='utf-8')
        return 0
    return run_command_logged(
        [*venv_cmd, '-m', 'flake8', '--format=html',
         f'--htmldir={flake_dir}',
         *[str(path) for path in build_information['flake8_folders']]],
        log_file=flake_log,
        check=False,
        cwd=project_root,
    )


def _run_linters(venv_cmd: list[str], build_information: BuildInformation,
                 report_paths: dict[str, Path], project_root: Path) -> \
        dict[str, int]:
    """Run mypy and flake8 and return their exit codes."""
    mypy_code = _run_mypy(
        venv_cmd=venv_cmd,
        build_information=build_information,
        mypy_log=report_paths['mypy_log'],
        mypy_dir=report_paths['mypy_dir'],
        project_root=project_root
    )
    flake8_code = _run_flake8(
        venv_cmd=venv_cmd,
        build_information=build_information,
        flake_log=report_paths['flake_log'],
        flake_dir=report_paths['flake_dir'],
        project_root=project_root
    )
    return {
        'mypy': mypy_code,
        'flake8': flake8_code,
    }


def _pytest_collection_folders(
        build_information: BuildInformation) -> list[Path]:
    """Return pytest collection folders for tests and pylint targets."""
    folders = (
        build_information['pytest_folders'] +
        build_information['pylint_folders']
    )
    unique_folders: list[Path] = []
    seen: set[Path] = set()
    for folder in folders:
        if folder in seen:
            continue
        seen.add(folder)
        unique_folders.append(folder)
    return unique_folders


def _pytest_command(venv_cmd: list[str], build_information: BuildInformation,
                    report_dir: Path) -> list[str]:
    """Construct pytest command for discovered test and pylint folders."""
    command = [*venv_cmd, '-m', 'pytest']
    command.extend(
        str(path) for path in _pytest_collection_folders(build_information)
    )
    command.extend([
        f'--html={report_dir / "pytest_report.html"}',
        '--self-contained-html',
        f'--cov-report=html:{report_dir / "coverage"}',
        '--pylint',
        f'--pylint-output-file={report_dir / PYLINT_LOG_NAME}',
    ])
    for package_data in build_information['package_information']:
        command.append(f'--cov={package_data["normalized_name"]}')
    return command


def _run_pytest(venv_cmd: list[str], build_information: BuildInformation,
                pytest_log: Path, report_dir: Path, project_root: Path) -> int:
    """Run pytest and return pytest exit code."""
    pylint_log = report_dir / PYLINT_LOG_NAME
    if not _pytest_collection_folders(build_information):
        pytest_log.write_text('No pytest targets discovered.\n',
                              encoding='utf-8')
        pylint_log.write_text('No pylint targets discovered.\n',
                              encoding='utf-8')
        return 0
    pylint_log.touch(exist_ok=True)
    return run_command_logged(
        _pytest_command(venv_cmd=venv_cmd,
                        build_information=build_information,
                        report_dir=report_dir),
        log_file=pytest_log,
        check=False,
        cwd=project_root,
    )


def _run_pydoc_markdown(venv_cmd: list[str], build_spec: BuildSpec,
                        build_log: Path, project_root: Path) -> int:
    """Run pydoc-markdown for all matching config files."""
    _ = venv_cmd
    _ = build_spec
    custom_folder = project_root / CUSTOM_BUILD_TOOLS_DIR_NAME
    if not custom_folder.is_dir():
        return 0
    (project_root / 'doc').mkdir(parents=True, exist_ok=True)
    pydoc_markdown_script = venv_script('pydoc-markdown')
    for config_file in sorted(custom_folder.glob('pydoc-markdown*.yml')):
        return_code = run_command_logged(
            [pydoc_markdown_script, '--render-toc', str(config_file)],
            log_file=build_log,
            check=False,
            cwd=project_root,
        )
        if return_code != 0:
            return return_code
    return 0


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
        for count_text in re.findall(r'(\d+)\s+skipped\b', last_summary)
    )
    return cleaned, skipped_count, (
        'failed' in last_summary or 'error' in last_summary
    )


def _check_flake8_clean(report_paths: dict[str, Path]) -> bool:
    """Return True when flake8 report indicates no issues."""
    index_file = report_paths['flake_dir'] / 'index.html'
    if not index_file.exists():
        return False
    return 'No flake8 errors found' in index_file.read_text(encoding='utf-8')


def _check_mypy_clean(report_paths: dict[str, Path]) -> bool:
    """Return True when mypy log indicates success."""
    if not report_paths['mypy_log'].exists():
        return False
    content = report_paths['mypy_log'].read_text(encoding='utf-8')
    return 'Success: no issues found' in content


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


def _print_repo_sync_warnings(repo_sync_warnings: list[str],
                              at_build_end: bool = False) -> None:
    """Print repository synchronization warnings to stderr."""
    if not repo_sync_warnings:
        return
    if at_build_end:
        phase_text = 'at build end'
    else:
        phase_text = 'at build start'
    print(f'Repository synchronization warnings ({phase_text}):',
          file=sys.stderr)
    for warning_text in repo_sync_warnings:
        print(f'  - {warning_text}', file=sys.stderr)


def _write_html_report(build_information: BuildInformation,
                       report_paths: dict[str, Path],
                       report_summary: ReportSummary) -> None:
    """Write reports/index.html summary page."""
    now = datetime.now().astimezone()
    index_file = report_paths['report_dir'] / 'index.html'
    with open(index_file, 'w', encoding='utf-8') as file_obj:
        file_obj.write('<!DOCTYPE html>\n<html>\n<head>\n')
        file_obj.write('  <meta charset="utf-8" />\n')
        file_obj.write('  <title>Build report</title>\n')
        file_obj.write('</head>\n<body>\n')
        file_obj.write(
            now.strftime(
                '<h1>Build report %Y-%m-%d %H:%M</h1>\n'
            )
        )
        package_names = ', '.join(
            package_data['name']
            for package_data in build_information['package_information']
        )
        file_obj.write(f'<h2>Packages: {package_names}</h2>\n')
        file_obj.write(
            f'<h3>Version(s): {report_summary.version_text}</h3>\n'
        )
        if report_summary.test_summary:
            file_obj.write(f'<p>{report_summary.test_summary}</p>\n')
        if report_summary.flake8_clean:
            file_obj.write('<p>No flake8 warnings.</p>\n')
        else:
            file_obj.write('<p>Flake8 errors/warnings.</p>\n')
        if report_summary.mypy_clean:
            file_obj.write('<p>No mypy errors found.</p>\n')
        else:
            file_obj.write('<p>mypy errors.</p>\n')
        if report_summary.repo_sync_warnings:
            file_obj.write('<h3>Repository synchronization warnings</h3>\n')
            file_obj.write('<ul>\n')
            for warning_text in report_summary.repo_sync_warnings:
                escaped_warning = html.escape(warning_text)
                file_obj.write(f'  <li>{escaped_warning}</li>\n')
            file_obj.write('</ul>\n')
        file_obj.write(
            f'<p>Build and test using {report_summary.python_version}</p>\n'
        )
        file_obj.write('<ul>\n')
        for href, text in REPORT_LINKS:
            file_obj.write(f'  <li><a href="{href}">{text}</a></li>\n')
        file_obj.write('</ul>\n')
        file_obj.write('</body>\n</html>\n')


def _write_test_summary(report_paths: dict[str, Path],
                        report_summary: ReportSummary) -> Path:
    """Write reports/test_summary.md and return its path."""
    summary_file = report_paths['report_dir'] / 'test_summary.md'
    with open(summary_file, 'w', encoding='utf-8') as file_obj:
        file_obj.write('## Test summary\n\n')
        file_obj.write(f'- Test result: {report_summary.test_summary}\n')
        if report_summary.flake8_clean:
            file_obj.write('- No Flake8 warnings.\n')
        else:
            file_obj.write('- Flake8 errors/warnings.\n')
        if report_summary.mypy_clean:
            file_obj.write('- No mypy errors found.\n')
        else:
            file_obj.write('- mypy errors.\n')
        file_obj.write(f'- Built version(s): {report_summary.version_text}\n')
        file_obj.write(
            f'- Build and test using {report_summary.python_version}\n'
        )
    return summary_file


def _generate_reports(report_context: ReportGenerationContext) -> int:
    """Generate HTML/markdown reports and return final status code."""
    if report_context.build_spec.readme_summary_max_skipped < 0:
        raise ValueError('readme_summary_max_skipped must be non-negative.')
    pytest_summary, skipped, pytest_failed = _parse_pytest_summary(
        report_context.report_paths['pytest_log']
    )
    flake8_clean = _check_flake8_clean(report_context.report_paths)
    mypy_clean = _check_mypy_clean(report_context.report_paths)
    version_text = _build_version_text(report_context.build_information)
    python_version = _get_python_version(
        venv_cmd=report_context.venv_cmd,
        project_root=report_context.build_information['project_root']
    )
    report_summary = ReportSummary(
        version_text=version_text,
        test_summary=pytest_summary,
        flake8_clean=flake8_clean,
        mypy_clean=mypy_clean,
        python_version=python_version,
        repo_sync_warnings=list(report_context.repo_sync_warnings),
    )
    _write_html_report(
        build_information=report_context.build_information,
        report_paths=report_context.report_paths,
        report_summary=report_summary
    )
    summary_file = _write_test_summary(
        report_paths=report_context.report_paths,
        report_summary=report_summary
    )
    if skipped <= report_context.build_spec.readme_summary_max_skipped:
        _update_readmes(build_information=report_context.build_information,
                        summary_file=summary_file)
    lint_failed = any(
        return_code != 0
        for return_code in report_context.build_run_status.lint_codes.values()
    )
    if (report_context.build_run_status.pytest_code != 0 or
            pytest_failed or lint_failed):
        return 1
    return 0


def _restore_line_end_only_changes() -> list[Path]:
    """Restore files changed only by line endings and return restored paths."""
    return restore_bad_eol_changes(
        all_submodules=True,
        force_unix=False,
        verbose=True
    )


def _append_exception_traceback_to_build_log(
        project_root: Path,
        report_paths: Optional[dict[str, Path]]) -> None:
    """Append traceback for unexpected do_build exceptions to build log."""
    log_path: Optional[Path]
    if report_paths is None:
        log_path = project_root / REPORT_DIR_NAME / BUILD_LOG_NAME
    else:
        log_path = report_paths.get('build_log')
    if log_path is None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, 'a', encoding='utf-8') as file_obj:
        file_obj.write('\n')
        file_obj.write(
            datetime.now().astimezone().strftime(
                'Unhandled exception %Y-%m-%d %H:%M:%S %Z\n'
            )
        )
        file_obj.write(traceback.format_exc())


def do_build(python_name: Optional[str] = None,
             build_spec: Optional[BuildSpec] = None,
             build_information: Optional[BuildInformation] = None) -> int:
    """Run complete build process with reports and optional custom hooks."""
    # pylint: disable=too-many-locals
    active_spec = get_build_spec() if build_spec is None else build_spec
    active_information = build_information
    if active_information is None:
        active_information = get_build_information(active_spec)
    project_root = active_information['project_root']
    repo_sync_warnings = get_repo_sync_warnings(project_root)
    _print_repo_sync_warnings(repo_sync_warnings=repo_sync_warnings)
    report_paths: Optional[dict[str, Path]] = None
    try:
        _name, _python_cmd = resolve_target_python(python_name)
        _ensure_venv(
            python_name=python_name,
            project_root=project_root,
            build_spec=active_spec,
            build_information=active_information
        )
        venv_cmd = venv_python()
        _run_custom_hooks(active_spec.custom_before_clean, active_spec,
                          active_information)
        report_paths = _prepare_directories(
            project_root=project_root,
            build_information=active_information
        )
        report_paths['build_log'].write_text(
            datetime.now().astimezone().strftime(
                'Build started %Y-%m-%d %H:%M:%S %Z\n'
            ),
            encoding='utf-8'
        )
        _run_custom_hooks(active_spec.custom_before_build, active_spec,
                          active_information)
        build_code = _build_packages(
            venv_cmd=venv_cmd,
            build_information=active_information,
            build_log=report_paths['build_log'],
            project_root=project_root
        )
        if build_code != 0:
            return build_code
        _run_custom_hooks(active_spec.custom_before_install, active_spec,
                          active_information)
        install_code = _install_packages(
            venv_cmd=venv_cmd,
            build_information=active_information,
            build_log=report_paths['build_log'],
            dist_dir=report_paths['dist_dir'],
            project_root=project_root
        )
        if install_code != 0:
            return install_code
        _run_custom_hooks(active_spec.custom_before_test, active_spec,
                          active_information)
        lint_codes = _run_linters(
            venv_cmd=venv_cmd,
            build_information=active_information,
            report_paths=report_paths,
            project_root=project_root
        )
        pytest_code = _run_pytest(
            venv_cmd=venv_cmd,
            build_information=active_information,
            pytest_log=report_paths['pytest_log'],
            report_dir=report_paths['report_dir'],
            project_root=project_root
        )
        _run_custom_hooks(active_spec.custom_after_test, active_spec,
                          active_information)
        pydoc_code = _run_pydoc_markdown(
            venv_cmd=venv_cmd,
            build_spec=active_spec,
            build_log=report_paths['build_log'],
            project_root=project_root
        )
        _run_custom_hooks(active_spec.custom_final, active_spec,
                          active_information)
        restored_files = _restore_line_end_only_changes()
        if restored_files:
            print(f'Restored {len(restored_files)} line-ending-only changes.',
                  file=sys.stderr)
        build_run_status = BuildRunStatus(
            lint_codes=lint_codes,
            pytest_code=pytest_code
        )
        report_context = ReportGenerationContext(
            build_information=active_information,
            build_spec=active_spec,
            report_paths=report_paths,
            venv_cmd=venv_cmd,
            build_run_status=build_run_status,
            repo_sync_warnings=repo_sync_warnings
        )
        report_code = _generate_reports(report_context=report_context)
        if pydoc_code != 0:
            return pydoc_code
        return report_code
    except Exception:
        _append_exception_traceback_to_build_log(
            project_root=project_root,
            report_paths=report_paths
        )
        raise
    finally:
        _print_repo_sync_warnings(
            repo_sync_warnings=repo_sync_warnings,
            at_build_end=True
        )


def do_build_cmd(build_spec: Optional[BuildSpec] = None,
                 build_information: Optional[BuildInformation] = None) -> None:
    """Run build command."""
    python_name = extract_python_name(sys.argv[1:])
    sys.exit(do_build(python_name, build_spec, build_information))


if __name__ == '__main__':
    do_build_cmd()
