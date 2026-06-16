#! /usr/bin/env python3
"""Build packages, run checks/tests and generate reports."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

from datetime import datetime
from pathlib import Path
import re
import shutil
import sys
import traceback
from typing import Optional

from best_installed_python import resolve_target_python
from build_information import get_build_information
from build_lint import _run_linters
from build_reports import (
    BUILD_LOG_NAME,
    FLAKE_DIR_NAME,
    FLAKE_LOG_NAME,
    MYPY_DIR_NAME,
    MYPY_LOG_NAME,
    PYLINT_LOG_NAME,
    PYTEST_LOG_NAME,
    PYTHON_LAYOUT_LOG_NAME,
    REPORT_DIR_NAME,
    BuildFailure,
    BuildRunStatus,
    ReportGenerationContext,
    _generate_reports
)
from build_spec import (
    BuildInformation,
    BuildSpec,
    CustomFunction,
    PackageInformation,
)
from build_utils import (
    extract_python_name,
    run_command_logged,
    venv_python,
    venv_script,
)
from get_build_spec import get_build_spec
from git_helpers import get_repo_sync_warnings, restore_bad_eol_changes
from setup_build_environment import setup_build_environment


DIST_DIR_NAME = 'dist'
CUSTOM_BUILD_TOOLS_DIR_NAME = 'custom_build_tools'


def _run_custom_hooks(hooks: Optional[list[CustomFunction]],
                      build_spec: BuildSpec,
                      build_information: BuildInformation) -> None:
    """Run custom hooks in specified order."""
    if not hooks:
        return
    for hook in hooks:
        hook(build_spec, build_information)


def _initial_build_run_status() -> BuildRunStatus:
    """Return build run status before lint, pytest and pydoc have run."""
    return BuildRunStatus(
        lint_codes={'mypy': None, 'flake8': None, 'python_layout': None},
        pytest_code=None, pydoc_code=None)


def _ensure_venv(python_name: Optional[str], project_root: Path,
                 build_spec: BuildSpec,
                 build_information: BuildInformation) -> None:
    """Create build environment if venv is missing."""
    venv_cmd = venv_python()
    venv_path = project_root / venv_cmd[0]
    if venv_path.exists():
        return
    setup_build_environment(python_name=python_name, build_spec=build_spec,
                            build_information=build_information)


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
        'python_layout_log': report_dir / PYTHON_LAYOUT_LOG_NAME,
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
             DIST_DIR_NAME], log_file=build_log, check=False,
            cwd=project_root,)
        if return_code != 0:
            return return_code
    return 0


def _wheel_regex_for_package(package_name: str) -> re.Pattern[str]:
    """Return regex for wheel files of one package."""
    escaped_name = ''.join(
        '[-_]' if char in '-_' else re.escape(char)
        for char in package_name)
    return re.compile(rf'^{escaped_name}-.*\.whl$')


def _find_wheel(dist_dir: Path, package_name: str) -> Path:
    """Find built wheel file for package in dist directory."""
    pattern = _wheel_regex_for_package(package_name)
    wheel_files = sorted(
        wheel for wheel in dist_dir.glob('*.whl')
        if pattern.match(wheel.name))
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
    run_command_logged([*venv_cmd, '-m', 'pip', 'uninstall', '-y', *pip_names],
                       log_file=build_log, check=False, cwd=project_root,)
    package_map = _package_map_by_name(build_information)
    for package_name in build_information['package_install_order']:
        _ = package_map[package_name]
        wheel_file = _find_wheel(dist_dir=dist_dir, package_name=package_name)
        return_code = run_command_logged(
            [*venv_cmd, '-m', 'pip', 'install', str(wheel_file)],
            log_file=build_log, check=False, cwd=project_root,)
        if return_code != 0:
            return return_code
    return 0


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


def _write_cov_config(build_information: BuildInformation,
                      report_dir: Path) -> Optional[Path]:
    """Write a coverage config and return its path, or None.

    Coverage treats a ``--cov`` value as a directory when a folder of
    that name exists in the working directory. With one project folder
    per package that folder shadows the package, so coverage measures
    the test folder instead of the installed package. Listing packages
    under ``source_pkgs`` makes coverage resolve them as importable
    packages regardless of same-named folders. Returns None when no
    packages were discovered, which leaves coverage disabled.
    """
    packages = build_information['package_information']
    names = [data['normalized_name'] for data in packages]
    if not names:
        return None
    lines = ['[run]', 'source_pkgs ='] + [f'    {name}' for name in names]
    config_path = report_dir / 'coverage_config.ini'
    config_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return config_path


def _pytest_command(venv_cmd: list[str], build_information: BuildInformation,
                    report_dir: Path, cov_config: Optional[Path]) -> list[str]:
    """Construct pytest command for discovered test and pylint folders."""
    command = [*venv_cmd, '-m', 'pytest']
    command.extend(
        str(path) for path in _pytest_collection_folders(build_information))
    command.extend([
        f'--html={report_dir / "pytest_report.html"}',
        '--self-contained-html',
        f'--cov-report=html:{report_dir / "coverage"}',
        '--pylint',
        f'--pylint-output-file={report_dir / PYLINT_LOG_NAME}',
    ])
    pylint_rcfile = report_dir.parent / '.pylintrc'
    if pylint_rcfile.is_file():
        command.append(f'--pylint-rcfile={pylint_rcfile}')
    if cov_config is not None:
        command.extend(['--cov', f'--cov-config={cov_config}'])
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
    cov_config = _write_cov_config(build_information, report_dir)
    return run_command_logged(
        _pytest_command(venv_cmd=venv_cmd, build_information=build_information,
                        report_dir=report_dir, cov_config=cov_config),
        log_file=pytest_log, check=False, cwd=project_root,)


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
            log_file=build_log, check=False, cwd=project_root,)
        if return_code != 0:
            return return_code
    return 0


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


def _restore_line_end_only_changes() -> list[Path]:
    """Restore files changed only by line endings and return restored paths."""
    return restore_bad_eol_changes(all_submodules=True, force_unix=False,
                                   verbose=True)


def _append_traceback_to_build_log(
        project_root: Path, report_paths: Optional[dict[str, Path]]) -> None:
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
                'Unhandled exception %Y-%m-%d %H:%M:%S %Z\n'))
        file_obj.write(traceback.format_exc())


def _build_failure_detail(error: Exception) -> str:
    """Return short failure detail text for one raised exception."""
    return f'{type(error).__name__}: {error}'


def _generate_reports_after_failure(
        report_context: ReportGenerationContext) -> None:
    """Best-effort report generation for failures after wheel install."""
    try:
        _ = _generate_reports(report_context=report_context)
    # pylint: disable-next=broad-exception-caught
    except Exception:
        _append_traceback_to_build_log(
            project_root=report_context.build_information['project_root'],
            report_paths=report_context.report_paths)


def do_build(python_name: Optional[str] = None,
             build_spec: Optional[BuildSpec] = None,
             build_information: Optional[BuildInformation] = None) -> int:
    """Run complete build process with reports and optional custom hooks."""
    # pylint: disable=too-many-locals,too-many-statements
    active_spec = get_build_spec() if build_spec is None else build_spec
    active_information = build_information
    if active_information is None:
        active_information = get_build_information(active_spec)
    project_root = active_information['project_root']
    repo_sync_warnings = get_repo_sync_warnings(project_root)
    _print_repo_sync_warnings(repo_sync_warnings=repo_sync_warnings)
    report_paths: Optional[dict[str, Path]] = None
    venv_cmd: Optional[list[str]] = None
    build_run_status = _initial_build_run_status()
    reports_enabled = False
    current_phase = 'initialization'
    try:
        current_phase = 'python selection'
        resolve_target_python(python_name)
        current_phase = 'virtual environment setup'
        _ensure_venv(python_name=python_name, project_root=project_root,
                     build_spec=active_spec,
                     build_information=active_information)
        venv_cmd = venv_python()
        current_phase = 'custom_before_clean hooks'
        _run_custom_hooks(active_spec.custom_before_clean, active_spec,
                          active_information)
        current_phase = 'prepare output directories'
        report_paths = _prepare_directories(
            project_root=project_root, build_information=active_information)
        report_paths['build_log'].write_text(
            datetime.now().astimezone().strftime(
                'Build started %Y-%m-%d %H:%M:%S %Z\n'), encoding='utf-8')
        current_phase = 'custom_before_build hooks'
        _run_custom_hooks(active_spec.custom_before_build, active_spec,
                          active_information)
        current_phase = 'build wheel packages'
        build_code = _build_packages(venv_cmd=venv_cmd,
                                     build_information=active_information,
                                     build_log=report_paths['build_log'],
                                     project_root=project_root)
        if build_code != 0:
            return build_code
        current_phase = 'custom_before_install hooks'
        _run_custom_hooks(active_spec.custom_before_install, active_spec,
                          active_information)
        current_phase = 'install wheel packages'
        install_code = _install_packages(venv_cmd=venv_cmd,
                                         build_information=active_information,
                                         build_log=report_paths['build_log'],
                                         dist_dir=report_paths['dist_dir'],
                                         project_root=project_root)
        if install_code != 0:
            return install_code
        reports_enabled = True
        current_phase = 'custom_before_test hooks'
        _run_custom_hooks(active_spec.custom_before_test, active_spec,
                          active_information)
        current_phase = 'mypy, flake8 and python-layout'
        lint_codes = _run_linters(venv_cmd=venv_cmd,
                                  build_information=active_information,
                                  report_paths=report_paths,
                                  project_root=project_root,
                                  build_spec=active_spec)
        build_run_status = BuildRunStatus(lint_codes=lint_codes,
                                          pytest_code=None, pydoc_code=None)
        current_phase = 'pytest'
        pytest_code = _run_pytest(venv_cmd=venv_cmd,
                                  build_information=active_information,
                                  pytest_log=report_paths['pytest_log'],
                                  report_dir=report_paths['report_dir'],
                                  project_root=project_root)
        build_run_status = BuildRunStatus(lint_codes=lint_codes,
                                          pytest_code=pytest_code,
                                          pydoc_code=None)
        current_phase = 'custom_after_test hooks'
        _run_custom_hooks(active_spec.custom_after_test, active_spec,
                          active_information)
        current_phase = 'pydoc-markdown'
        pydoc_code = _run_pydoc_markdown(venv_cmd=venv_cmd,
                                         build_spec=active_spec,
                                         build_log=report_paths['build_log'],
                                         project_root=project_root)
        build_run_status = BuildRunStatus(lint_codes=lint_codes,
                                          pytest_code=pytest_code,
                                          pydoc_code=pydoc_code)
        current_phase = 'custom_final hooks'
        _run_custom_hooks(active_spec.custom_final, active_spec,
                          active_information)
        current_phase = 'restore line-ending-only changes'
        restored_files = _restore_line_end_only_changes()
        if restored_files:
            print(f'Restored {len(restored_files)} line-ending-only changes.',
                  file=sys.stderr)
        report_context = ReportGenerationContext(
            build_information=active_information, build_spec=active_spec,
            report_paths=report_paths, venv_cmd=venv_cmd,
            build_run_status=build_run_status, build_failure=None,
            repo_sync_warnings=repo_sync_warnings)
        report_code = _generate_reports(report_context=report_context)
        if pydoc_code != 0:
            return pydoc_code
        return report_code
    except Exception as error:
        _append_traceback_to_build_log(project_root=project_root,
                                       report_paths=report_paths)
        if (reports_enabled and report_paths is not None and
                venv_cmd is not None):
            _generate_reports_after_failure(
                report_context=ReportGenerationContext(
                    build_information=active_information,
                    build_spec=active_spec, report_paths=report_paths,
                    venv_cmd=venv_cmd, build_run_status=build_run_status,
                    build_failure=BuildFailure(
                        phase=current_phase,
                        detail=_build_failure_detail(error)),
                    repo_sync_warnings=repo_sync_warnings))
        raise
    finally:
        _print_repo_sync_warnings(repo_sync_warnings=repo_sync_warnings,
                                  at_build_end=True)


def do_build_cmd(build_spec: Optional[BuildSpec] = None,
                 build_information: Optional[BuildInformation] = None) -> None:
    """Run build command."""
    python_name = extract_python_name(sys.argv[1:])
    sys.exit(do_build(python_name, build_spec, build_information))


if __name__ == '__main__':
    do_build_cmd()
