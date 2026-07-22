#! /usr/bin/env python3
"""Run lint and layout checks for the common build tool."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

import os
from pathlib import Path

from build_spec import BuildInformation, BuildSpec
from build_utils import (append_to_path_env, run_command_logged,
                         venv_script)


def _run_mypy(venv_cmd: list[str], build_information: BuildInformation,
              mypy_log: Path, mypy_dir: Path, project_root: Path) -> int:
    """Run mypy in strict mode on discovered folders."""
    if not build_information['mypy_folders']:
        mypy_log.write_text('No mypy targets discovered.\n', encoding='utf-8')
        return 0
    environment = dict(os.environ)
    environment['MYPYPATH'] = append_to_path_env(
        existing_path=environment.get('MYPYPATH'),
        additional_paths=build_information['mypy_path_folders'])
    return run_command_logged([*venv_cmd, '-m', 'mypy', '--strict',
                               '--explicit-package-bases', '--html-report',
                               str(mypy_dir),
                               *[str(path) for path in
                                 build_information['mypy_folders']]],
                              log_file=mypy_log, check=False, cwd=project_root,
                              env=environment)


def _run_flake8(venv_cmd: list[str], build_information: BuildInformation,
                flake_log: Path, flake_dir: Path, project_root: Path) -> int:
    """Run flake8 on discovered folders."""
    if not build_information['flake8_folders']:
        flake_log.write_text('No flake8 targets discovered.\n',
                             encoding='utf-8')
        return 0
    return run_command_logged([*venv_cmd, '-m', 'flake8', '--format=html',
                               f'--htmldir={flake_dir}',
                               *[str(path) for path in
                                 build_information['flake8_folders']]],
                              log_file=flake_log, check=False,
                              cwd=project_root)


def _is_python_layout_included(folder: Path,
                               excluded_folders: list[Path]) -> bool:
    """Return True when folder is outside every python-layout exclusion."""
    for excluded_folder in excluded_folders:
        try:
            folder.relative_to(excluded_folder)
            return False
        except ValueError:
            continue
    return True


def _python_layout_folders(build_spec: BuildSpec,
                           build_information: BuildInformation,
                           project_root: Path) -> list[Path]:
    """Return flake8 folders after python-layout specific exclusions."""
    excludes = build_spec.python_layout_exclude_folders
    if excludes is None:
        return list(build_information['flake8_folders'])
    resolved_excludes = [(project_root / path).resolve() for path in excludes]
    return [
        folder for folder in build_information['flake8_folders']
        if _is_python_layout_included(folder.resolve(), resolved_excludes)
    ]


def _run_python_layout(venv_cmd: list[str], build_spec: BuildSpec,
                       build_information: BuildInformation, layout_log: Path,
                       project_root: Path) -> int:
    """Run python-layout on discovered flake8 folders."""
    if not build_spec.python_layout_check:
        layout_log.write_text('Python layout check disabled.\n',
                              encoding='utf-8')
        return 0
    folders = _python_layout_folders(build_spec, build_information,
                                     project_root)
    if not folders:
        layout_log.write_text('No python layout targets discovered.\n',
                              encoding='utf-8')
        return 0
    checker = Path(__file__).with_name('check_python_layout.py')
    return run_command_logged(
        _python_layout_command(venv_cmd, build_spec, checker, folders),
        log_file=layout_log, check=False, cwd=project_root)


def _python_layout_command(venv_cmd: list[str], build_spec: BuildSpec,
                           checker: Path, folders: list[Path]) -> list[str]:
    """Return command for python-layout checker."""
    command = [
        *venv_cmd,
        str(checker),
        f'--max-name-length={build_spec.python_layout_max_name_length}'
    ]
    if not build_spec.python_layout_name_guidance:
        command.append('--no-name-guidance')
    if (build_spec.python_layout_name_guidance and
            build_spec.python_layout_name_guidance_fails):
        command.append('--name-guidance-fails')
    command.extend(str(path) for path in folders)
    return command


def _pylint_command(venv_cmd: list[str], build_information: BuildInformation,
                    json_path: Path, project_root: Path) -> list[str]:
    """Return pylint command writing both text and JSON output.

    All discovered folders are passed in a single invocation so that
    cross-file findings such as duplicate-code (R0801) are detected.
    ``--recursive=y`` lets pylint lint folders that are not packages
    (folders without a top-level ``__init__.py``).
    """
    command = [*venv_cmd, '-m', 'pylint', '--recursive=y',
               f'--output-format=text,json:{json_path}']
    rcfile = project_root / '.pylintrc'
    if rcfile.is_file():
        command.append(f'--rcfile={rcfile}')
    command.extend(str(path) for path in build_information['pylint_folders'])
    return command


def _write_pylint_html(json_path: Path, pylint_dir: Path,
                       project_root: Path) -> None:
    """Convert pylint JSON output into an HTML report."""
    if not json_path.is_file():
        return
    run_command_logged(
        [venv_script('pylint-json2html'), '-f', 'json', '-o',
         str(pylint_dir / 'index.html'), str(json_path)],
        log_file=pylint_dir / 'json2html_log.txt', check=False,
        cwd=project_root)


def _run_pylint(venv_cmd: list[str], build_information: BuildInformation,
                pylint_log: Path, pylint_dir: Path, project_root: Path) -> int:
    """Run pylint on discovered folders and build an HTML report."""
    if not build_information['pylint_folders']:
        pylint_log.write_text('No pylint targets discovered.\n',
                              encoding='utf-8')
        return 0
    json_path = pylint_dir / 'pylint.json'
    exit_code = run_command_logged(
        _pylint_command(venv_cmd, build_information, json_path, project_root),
        log_file=pylint_log, check=False, cwd=project_root)
    _write_pylint_html(json_path=json_path, pylint_dir=pylint_dir,
                       project_root=project_root)
    return exit_code


def _run_linters(venv_cmd: list[str], build_information: BuildInformation,
                 report_paths: dict[str, Path], project_root: Path,
                 build_spec: BuildSpec) -> dict[str, int]:
    """Run mypy, flake8, pylint and python-layout, return their codes."""
    mypy_code = _run_mypy(venv_cmd=venv_cmd,
                          build_information=build_information,
                          mypy_log=report_paths['mypy_log'],
                          mypy_dir=report_paths['mypy_dir'],
                          project_root=project_root)
    flake8_code = _run_flake8(venv_cmd=venv_cmd,
                              build_information=build_information,
                              flake_log=report_paths['flake_log'],
                              flake_dir=report_paths['flake_dir'],
                              project_root=project_root)
    pylint_code = _run_pylint(venv_cmd=venv_cmd,
                              build_information=build_information,
                              pylint_log=report_paths['pylint_log'],
                              pylint_dir=report_paths['pylint_dir'],
                              project_root=project_root)
    python_layout_code = _run_python_layout(
        venv_cmd=venv_cmd, build_spec=build_spec,
        build_information=build_information,
        layout_log=report_paths['python_layout_log'],
        project_root=project_root)
    return {
        'mypy': mypy_code,
        'flake8': flake8_code,
        'pylint': pylint_code,
        'python_layout': python_layout_code
    }
