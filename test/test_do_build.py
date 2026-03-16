#! /usr/bin/env python3
"""Tests for common_build_tools.src.do_build."""

# Copyright (c) 2026 Tom Björkholm
# MIT License
# pylint: disable=protected-access

from pathlib import Path
from typing import Callable
import pytest

import do_build
from build_spec import BuildInformation, BuildSpec
from common_build_tools.test.helpers import (
    make_build_information,
    make_package_information,
)


def _report_paths(report_dir: Path, dist_dir: Path) -> dict[str, Path]:
    """Create report path mapping used by do_build internal helpers."""
    flake_dir = report_dir / do_build.FLAKE_DIR_NAME
    mypy_dir = report_dir / do_build.MYPY_DIR_NAME
    flake_dir.mkdir(parents=True, exist_ok=True)
    mypy_dir.mkdir(parents=True, exist_ok=True)
    return {
        'report_dir': report_dir,
        'dist_dir': dist_dir,
        'build_log': report_dir / do_build.BUILD_LOG_NAME,
        'pytest_log': report_dir / do_build.PYTEST_LOG_NAME,
        'pylint_log': report_dir / do_build.PYLINT_LOG_NAME,
        'flake_log': report_dir / do_build.FLAKE_LOG_NAME,
        'mypy_log': report_dir / do_build.MYPY_LOG_NAME,
        'flake_dir': flake_dir,
        'mypy_dir': mypy_dir,
    }


def _report_context(
        build_information: BuildInformation,
        report_paths: dict[str, Path],
        readme_summary_max_skipped: int = 0,
        lint_codes: dict[str, int] | None = None,
        repo_sync_warnings: list[str] | None = None
) -> do_build.ReportGenerationContext:
    """Create report context used by do_build report generation tests."""
    resolved_lint_codes = {'mypy': 0, 'flake8': 0}
    if lint_codes is not None:
        resolved_lint_codes = lint_codes
    resolved_repo_sync_warnings: list[str] = []
    if repo_sync_warnings is not None:
        resolved_repo_sync_warnings = repo_sync_warnings
    return do_build.ReportGenerationContext(
        build_information=build_information,
        build_spec=BuildSpec(
            readme_summary_max_skipped=readme_summary_max_skipped
        ),
        report_paths=report_paths,
        venv_cmd=['venv/bin/python'],
        build_run_status=do_build.BuildRunStatus(
            lint_codes=resolved_lint_codes,
            pytest_code=0
        ),
        repo_sync_warnings=resolved_repo_sync_warnings,
    )


def test_wheel_regex_dash_uscore() -> None:
    """Test wheel regex accepts dash and underscore package name variants."""
    pattern = do_build._wheel_regex_for_package('my_pkg')
    assert pattern.match('my_pkg-1.0.0-py3-none-any.whl')
    assert pattern.match('my-pkg-1.0.0-py3-none-any.whl')
    assert pattern.match('other-1.0.0.whl') is None


def test_wheel_regex_dash_input() -> None:
    """Test wheel regex handles package name input that contains dash."""
    pattern = do_build._wheel_regex_for_package('my-pkg')
    assert pattern.match('my_pkg-1.0.0-py3-none-any.whl')
    assert pattern.match('my-pkg-1.0.0-py3-none-any.whl')


def test_find_wheel_latest(tmp_path: Path) -> None:
    """Test _find_wheel returns lexicographically latest matching wheel."""
    dist_dir = tmp_path / 'dist'
    dist_dir.mkdir()
    (dist_dir / 'pkg-1.0.0-py3-none-any.whl').write_text('a',
                                                         encoding='utf-8')
    (dist_dir / 'pkg-1.0.1-py3-none-any.whl').write_text('b',
                                                         encoding='utf-8')
    wheel = do_build._find_wheel(dist_dir=dist_dir, package_name='pkg')
    assert wheel.name == 'pkg-1.0.1-py3-none-any.whl'


def test_find_wheel_missing(tmp_path: Path) -> None:
    """Test _find_wheel raises ValueError when no matching file exists."""
    dist_dir = tmp_path / 'dist'
    dist_dir.mkdir()
    with pytest.raises(ValueError, match='Built wheel not found'):
        _ = do_build._find_wheel(dist_dir=dist_dir, package_name='pkg')


def test_pytest_folders_dedupe(tmp_path: Path) -> None:
    """Test pytest collection folder list preserves order and removes dupes."""
    folder_a = tmp_path / 'a'
    folder_b = tmp_path / 'b'
    info = BuildInformation(
        project_root=tmp_path,
        package_information=[],
        package_install_order=[],
        flake8_folders=[],
        pylint_folders=[folder_a, folder_b],
        mypy_folders=[],
        pytest_folders=[folder_a],
        mypy_path_folders=[],
    )
    folders = do_build._pytest_collection_folders(info)
    assert folders == [folder_a, folder_b]


def test_pytest_cmd_flags(tmp_path: Path) -> None:
    """Test constructed pytest command includes report and coverage flags."""
    package_folder = tmp_path / 'pkg-one'
    package_folder.mkdir(parents=True, exist_ok=True)
    package = make_package_information(
        package_folder=package_folder,
        name='pkg-one'
    )
    info = make_build_information(tmp_path, [package])
    info['pytest_folders'] = [tmp_path / 'test']
    info['pylint_folders'] = [tmp_path / 'src']
    (tmp_path / '.pylintrc').write_text('[MAIN]\n', encoding='utf-8')
    report_dir = tmp_path / 'reports'
    command = do_build._pytest_command(['venv/bin/python'], info, report_dir)
    command_text = ' '.join(command)
    assert command[:3] == ['venv/bin/python', '-m', 'pytest']
    assert '--self-contained-html' in command
    assert '--pylint' in command
    assert f'--pylint-rcfile={tmp_path / ".pylintrc"}' in command
    assert '--cov=pkg_one' in command
    assert 'pytest_report.html' in command_text


def test_parse_summary_latest(tmp_path: Path) -> None:
    """Test pytest summary parser extracts normalized final summary line."""
    log_file = tmp_path / 'pytest_log.txt'
    log_file.write_text(
        'line one\n'
        '===== 2 failed, 10 passed in 1.23s =====\n',
        encoding='utf-8'
    )
    summary, skipped, failed = do_build._parse_pytest_summary(log_file)
    assert summary == '2 failed, 10 passed in 1s'
    assert skipped == 0
    assert failed is True


def test_parse_summary_missing(tmp_path: Path) -> None:
    """Test pytest summary parser handles missing log file."""
    summary, skipped, failed = do_build._parse_pytest_summary(
        tmp_path / 'missing.log'
    )
    assert summary == ''
    assert skipped == 0
    assert failed is False


def test_parse_summary_skipped(tmp_path: Path) -> None:
    """Test pytest summary parser extracts numeric skipped count."""
    log_file = tmp_path / 'pytest_log.txt'
    log_file.write_text(
        'line one\n'
        '===== 10 passed, 4 skipped in 1.23s =====\n',
        encoding='utf-8'
    )
    summary, skipped, failed = do_build._parse_pytest_summary(log_file)
    assert summary == '10 passed, 4 skipped in 1s'
    assert skipped == 4
    assert failed is False


def test_replace_summary_block(
        tmp_path: Path) -> None:
    """Test README summary block replacement keeps text before heading."""
    readme_path = tmp_path / 'README.md'
    summary_path = tmp_path / 'summary.md'
    readme_path.write_text(
        '# Title\n\ntext\n\n## Test summary\nold line\n',
        encoding='utf-8'
    )
    summary_path.write_text('## Test summary\n\nnew line\n',
                            encoding='utf-8')
    do_build._replace_test_summary_in_readme(
        readme_path=readme_path,
        summary_path=summary_path
    )
    content = readme_path.read_text(encoding='utf-8')
    assert 'old line' not in content
    assert 'new line' in content


def test_reports_update_readmes(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """Test report generation writes outputs and updates README summaries."""
    package_folder = tmp_path / 'pkg-one'
    package_folder.mkdir(parents=True, exist_ok=True)
    package = make_package_information(
        package_folder=package_folder,
        name='pkg-one'
    )
    package_readme = package['package_folder'] / 'README_pypi.md'
    package_readme.write_text('# package\n', encoding='utf-8')
    root_readme = tmp_path / 'README.md'
    root_readme.write_text('# root\n', encoding='utf-8')
    info = make_build_information(tmp_path, [package])
    report_dir = tmp_path / 'reports'
    report_dir.mkdir()
    dist_dir = tmp_path / 'dist'
    dist_dir.mkdir()
    paths = _report_paths(report_dir, dist_dir)
    paths['pytest_log'].write_text(
        '=== 5 passed in 2.11s ===\n',
        encoding='utf-8'
    )
    paths['mypy_log'].write_text('Success: no issues found\n',
                                 encoding='utf-8')
    (paths['flake_dir'] / 'index.html').write_text(
        'No flake8 errors found',
        encoding='utf-8'
    )
    monkeypatch.setattr(do_build, '_get_python_version',
                        lambda **_kwargs: 'Python')
    result = do_build._generate_reports(
        report_context=_report_context(
            build_information=info,
            report_paths=paths
        )
    )
    assert result == 0
    assert (report_dir / 'index.html').exists()
    assert '## Test summary' in root_readme.read_text(encoding='utf-8')
    assert '## Test summary' in package_readme.read_text(encoding='utf-8')


def test_reports_error_on_lint(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """Test report generation returns non-zero when linter fails."""
    info = make_build_information(tmp_path)
    report_dir = tmp_path / 'reports'
    report_dir.mkdir()
    dist_dir = tmp_path / 'dist'
    dist_dir.mkdir()
    paths = _report_paths(report_dir, dist_dir)
    paths['pytest_log'].write_text('=== 2 passed in 0.10s ===\n',
                                   encoding='utf-8')
    (paths['flake_dir'] / 'index.html').write_text('No flake8 errors found',
                                                   encoding='utf-8')
    paths['mypy_log'].write_text('Success: no issues found\n',
                                 encoding='utf-8')
    monkeypatch.setattr(do_build, '_get_python_version',
                        lambda **_kwargs: 'Python')
    result = do_build._generate_reports(
        report_context=_report_context(
            build_information=info,
            report_paths=paths,
            lint_codes={'mypy': 1, 'flake8': 0}
        )
    )
    assert result == 1


def test_reports_sync_warnings(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """Test report generation writes repository sync warnings in html."""
    info = make_build_information(tmp_path)
    report_dir = tmp_path / 'reports'
    report_dir.mkdir()
    dist_dir = tmp_path / 'dist'
    dist_dir.mkdir()
    paths = _report_paths(report_dir, dist_dir)
    paths['pytest_log'].write_text('=== 2 passed in 0.10s ===\n',
                                   encoding='utf-8')
    (paths['flake_dir'] / 'index.html').write_text('No flake8 errors found',
                                                   encoding='utf-8')
    paths['mypy_log'].write_text('Success: no issues found\n',
                                 encoding='utf-8')
    monkeypatch.setattr(do_build, '_get_python_version',
                        lambda **_kwargs: 'Python')
    warning_text = (
        'Main repository: local branch master has 1 '
        'unpushed commit(s) to origin/master.'
    )
    result = do_build._generate_reports(
        report_context=_report_context(
            build_information=info,
            report_paths=paths,
            repo_sync_warnings=[warning_text]
        )
    )
    assert result == 0
    index_text = (report_dir / 'index.html').read_text(encoding='utf-8')
    assert 'Repository synchronization warnings' in index_text
    assert warning_text in index_text


def test_reports_skip_limit(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """Test README summary update is skipped when skipped count is too high."""
    package_folder = tmp_path / 'pkg-one'
    package_folder.mkdir(parents=True, exist_ok=True)
    package = make_package_information(
        package_folder=package_folder,
        name='pkg-one'
    )
    package_readme = package['package_folder'] / 'README_pypi.md'
    package_readme.write_text('# package\n', encoding='utf-8')
    root_readme = tmp_path / 'README.md'
    root_readme.write_text('# root\n', encoding='utf-8')
    info = make_build_information(tmp_path, [package])
    report_dir = tmp_path / 'reports'
    report_dir.mkdir()
    dist_dir = tmp_path / 'dist'
    dist_dir.mkdir()
    paths = _report_paths(report_dir, dist_dir)
    paths['pytest_log'].write_text(
        '=== 5 passed, 4 skipped in 2.11s ===\n',
        encoding='utf-8'
    )
    paths['mypy_log'].write_text('Success: no issues found\n',
                                 encoding='utf-8')
    (paths['flake_dir'] / 'index.html').write_text(
        'No flake8 errors found',
        encoding='utf-8'
    )
    monkeypatch.setattr(do_build, '_get_python_version',
                        lambda **_kwargs: 'Python')
    result = do_build._generate_reports(
        report_context=_report_context(
            build_information=info,
            report_paths=paths,
            readme_summary_max_skipped=3
        )
    )
    assert result == 0
    assert '## Test summary' not in root_readme.read_text(encoding='utf-8')
    assert '## Test summary' not in package_readme.read_text(encoding='utf-8')


def test_reports_reject_neg_skip(
        tmp_path: Path) -> None:
    """Test invalid negative README skipped threshold raises ValueError."""
    info = make_build_information(tmp_path)
    report_dir = tmp_path / 'reports'
    report_dir.mkdir()
    dist_dir = tmp_path / 'dist'
    dist_dir.mkdir()
    paths = _report_paths(report_dir, dist_dir)
    with pytest.raises(
            ValueError,
            match='readme_summary_max_skipped must be non-negative'):
        _ = do_build._generate_reports(
            report_context=_report_context(
                build_information=info,
                report_paths=paths,
                readme_summary_max_skipped=-1
            )
        )


def test_do_build_runs_steps(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """Test do_build orchestrates hooks and core steps in expected order."""
    # pylint: disable=too-many-locals
    events: list[str] = []

    def _hook(tag: str) -> Callable[[BuildSpec, BuildInformation], None]:
        def _inner(_spec: BuildSpec, _info: BuildInformation) -> None:
            events.append(tag)
        return _inner

    package_folder = tmp_path / 'pkg-one'
    package_folder.mkdir(parents=True, exist_ok=True)
    package = make_package_information(
        package_folder=package_folder,
        name='pkg-one'
    )
    info = make_build_information(tmp_path, [package])
    spec = BuildSpec(
        custom_before_clean=[_hook('before_clean')],
        custom_before_build=[_hook('before_build')],
        custom_before_install=[_hook('before_install')],
        custom_before_test=[_hook('before_test')],
        custom_after_test=[_hook('after_test')],
        custom_final=[_hook('final')],
    )

    def _prepare(project_root: Path,
                 build_information: BuildInformation) -> dict[str, Path]:
        _ = project_root
        _ = build_information
        report_dir = tmp_path / 'reports'
        report_dir.mkdir(exist_ok=True)
        dist_dir = tmp_path / 'dist'
        dist_dir.mkdir(exist_ok=True)
        return _report_paths(report_dir, dist_dir)

    monkeypatch.setattr(do_build, 'resolve_target_python',
                        lambda _python_name: ('python3.12', ['python3.12']))

    def _ensure_venv(**_kwargs: object) -> None:
        events.append('ensure_venv')

    def _build_packages(**_kwargs: object) -> int:
        events.append('build')
        return 0

    def _install_packages(**_kwargs: object) -> int:
        events.append('install')
        return 0

    def _run_linters(**_kwargs: object) -> dict[str, int]:
        events.append('linters')
        return {'mypy': 0, 'flake8': 0}

    def _run_pytest(**_kwargs: object) -> int:
        events.append('pytest')
        return 0

    def _run_pydoc_markdown(**_kwargs: object) -> int:
        events.append('pydoc')
        return 0

    def _generate_reports(**_kwargs: object) -> int:
        events.append('reports')
        return 0

    monkeypatch.setattr(do_build, '_ensure_venv', _ensure_venv)
    monkeypatch.setattr(do_build, '_prepare_directories', _prepare)
    monkeypatch.setattr(do_build, '_build_packages', _build_packages)
    monkeypatch.setattr(do_build, '_install_packages', _install_packages)
    monkeypatch.setattr(do_build, '_run_linters', _run_linters)
    monkeypatch.setattr(do_build, '_run_pytest', _run_pytest)
    monkeypatch.setattr(do_build, '_run_pydoc_markdown',
                        _run_pydoc_markdown)
    monkeypatch.setattr(do_build, '_restore_line_end_only_changes',
                        lambda: [])
    monkeypatch.setattr(do_build, '_generate_reports', _generate_reports)
    result = do_build.do_build(
        python_name='python3.12',
        build_spec=spec,
        build_information=info
    )
    assert result == 0
    assert events == [
        'ensure_venv',
        'before_clean',
        'before_build',
        'build',
        'before_install',
        'install',
        'before_test',
        'linters',
        'pytest',
        'after_test',
        'pydoc',
        'final',
        'reports',
    ]


def test_do_build_prints_sync_warns(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """Test do_build prints repository sync warnings at start and end."""
    info = make_build_information(tmp_path)

    def _prepare(project_root: Path,
                 build_information: BuildInformation) -> dict[str, Path]:
        _ = project_root
        _ = build_information
        report_dir = tmp_path / 'reports'
        report_dir.mkdir(exist_ok=True)
        dist_dir = tmp_path / 'dist'
        dist_dir.mkdir(exist_ok=True)
        return _report_paths(report_dir, dist_dir)

    warning_text = (
        'Main repository: local branch master has 1 '
        'unpushed commit(s) to origin/master.'
    )
    monkeypatch.setattr(do_build, 'get_repo_sync_warnings',
                        lambda _project_root: [warning_text])
    monkeypatch.setattr(do_build, 'resolve_target_python',
                        lambda _python_name: ('python3.14', ['python3.14']))
    monkeypatch.setattr(do_build, '_ensure_venv', lambda **_kwargs: None)
    monkeypatch.setattr(do_build, '_prepare_directories', _prepare)
    monkeypatch.setattr(do_build, '_build_packages', lambda **_kwargs: 2)
    result = do_build.do_build(build_spec=BuildSpec(),
                               build_information=info)
    assert result == 2
    out, err = capsys.readouterr()
    assert out == ''
    assert err.count('Repository synchronization warnings') == 2
    assert err.count(warning_text) == 2


def test_do_build_pydoc_error(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """Test do_build returns pydoc error code after report generation."""
    info = make_build_information(tmp_path)

    def _prepare(project_root: Path,
                 build_information: BuildInformation) -> dict[str, Path]:
        _ = project_root
        _ = build_information
        report_dir = tmp_path / 'reports'
        report_dir.mkdir(exist_ok=True)
        dist_dir = tmp_path / 'dist'
        dist_dir.mkdir(exist_ok=True)
        return _report_paths(report_dir, dist_dir)

    monkeypatch.setattr(do_build, 'resolve_target_python',
                        lambda _python_name: ('python3.14', ['python3.14']))
    monkeypatch.setattr(do_build, '_ensure_venv', lambda **_kwargs: None)
    monkeypatch.setattr(do_build, '_prepare_directories', _prepare)
    monkeypatch.setattr(do_build, '_build_packages', lambda **_kwargs: 0)
    monkeypatch.setattr(do_build, '_install_packages', lambda **_kwargs: 0)
    monkeypatch.setattr(do_build, '_run_linters', lambda **_kwargs: {
        'mypy': 0,
        'flake8': 0,
    })
    monkeypatch.setattr(do_build, '_run_pytest', lambda **_kwargs: 0)
    monkeypatch.setattr(do_build, '_run_pydoc_markdown',
                        lambda **_kwargs: 2)
    monkeypatch.setattr(do_build, '_restore_line_end_only_changes',
                        lambda: [])
    monkeypatch.setattr(do_build, '_generate_reports', lambda **_kwargs: 0)
    assert do_build.do_build(build_spec=BuildSpec(),
                             build_information=info) == 2


def test_do_build_logs_traceback(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """Test unexpected exception traceback is appended to build log."""
    info = make_build_information(tmp_path)

    def _prepare(project_root: Path,
                 build_information: BuildInformation) -> dict[str, Path]:
        _ = project_root
        _ = build_information
        report_dir = tmp_path / 'reports'
        report_dir.mkdir(exist_ok=True)
        dist_dir = tmp_path / 'dist'
        dist_dir.mkdir(exist_ok=True)
        return _report_paths(report_dir, dist_dir)

    def _raise_install(**_kwargs: object) -> int:
        raise ValueError('install failed')

    monkeypatch.setattr(do_build, 'resolve_target_python',
                        lambda _python_name: ('python3.14', ['python3.14']))
    monkeypatch.setattr(do_build, '_ensure_venv', lambda **_kwargs: None)
    monkeypatch.setattr(do_build, '_prepare_directories', _prepare)
    monkeypatch.setattr(do_build, '_build_packages', lambda **_kwargs: 0)
    monkeypatch.setattr(do_build, '_install_packages', _raise_install)
    with pytest.raises(ValueError, match='install failed'):
        _ = do_build.do_build(build_spec=BuildSpec(), build_information=info)
    build_log = tmp_path / 'reports' / do_build.BUILD_LOG_NAME
    content = build_log.read_text(encoding='utf-8')
    assert 'Unhandled exception' in content
    assert 'Traceback' in content
    assert 'ValueError: install failed' in content
