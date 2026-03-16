#! /usr/bin/env python3
"""Tests for common_build_tools.src.git_helpers."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import pytest
# Add source directory to path.
# pylint: disable=duplicate-code
_src_path = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(_src_path))
# pylint: disable=wrong-import-position
import git_helpers  # noqa: E402


def _run_git(args: list[str], repo_path: Path) -> str:
    """Run a git command in a repository and return stdout."""
    result = subprocess.run(
        ['git'] + args,
        cwd=repo_path,
        text=True,
        capture_output=True,
        check=False
    )
    if result.returncode != 0:
        cmd_text = ' '.join(['git'] + args)
        raise RuntimeError(f'Git command failed: {cmd_text}\n{result.stderr}')
    return result.stdout.strip()


def _init_repo(repo_path: Path) -> None:
    """Create and configure a git repository."""
    repo_path.mkdir(parents=True, exist_ok=True)
    _run_git(['init'], repo_path)
    _run_git(['config', 'user.name', 'Test User'], repo_path)
    _run_git(['config', 'user.email', 'test@example.com'], repo_path)


def _commit_all(repo_path: Path, message: str) -> None:
    """Commit all tracked and untracked files in a repository."""
    _run_git(['add', '.'], repo_path)
    _run_git(['commit', '-m', message], repo_path)


def _init_bare_repo(base_path: Path, folder_name: str) -> Path:
    """Create a bare git repository and return its path."""
    bare_repo = base_path / folder_name
    bare_repo.mkdir(parents=True, exist_ok=True)
    _run_git(['init', '--bare'], bare_repo)
    return bare_repo


def _set_origin_and_push(repo_path: Path, origin_path: Path) -> None:
    """Set origin remote and push current branch with tracking."""
    branch_name = _run_git(['rev-parse', '--abbrev-ref', 'HEAD'], repo_path)
    _run_git(['remote', 'add', 'origin', str(origin_path)], repo_path)
    _run_git(['push', '-u', 'origin', branch_name], repo_path)


def _clone_repo(remote_path: Path, clone_path: Path) -> None:
    """Clone remote repo to clone path and configure commit identity."""
    clone_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ['git', 'clone', str(remote_path), str(clone_path)],
        cwd=clone_path.parent,
        text=True,
        capture_output=True,
        check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f'Git clone failed: {result.stderr}')
    _run_git(['config', 'user.name', 'Test User'], clone_path)
    _run_git(['config', 'user.email', 'test@example.com'], clone_path)


def _create_repo_with_submodule(
        base_path: Path) -> tuple[Path, Path, Path, Path]:
    """Create a main repo and a local submodule with unstaged changes."""
    submodule_source = base_path / 'submodule_source'
    _init_repo(submodule_source)
    (submodule_source / 'sub.py').write_bytes(b'print(1)\n')
    _commit_all(submodule_source, 'initial submodule commit')
    main_repo = base_path / 'main_repo'
    _init_repo(main_repo)
    main_file = main_repo / 'main.py'
    changed_file = main_repo / 'changed.txt'
    main_file.write_bytes(b'print(1)\n')
    changed_file.write_bytes(b'start\n')
    _run_git(
        [
            '-c',
            'protocol.file.allow=always',
            'submodule',
            'add',
            str(submodule_source),
            'submod'
        ],
        main_repo
    )
    _commit_all(main_repo, 'initial main commit')
    submodule_file = main_repo / 'submod' / 'sub.py'
    main_file.write_bytes(b'print(1)\r\n')
    changed_file.write_bytes(b'changed-content\n')
    (main_repo / 'new.txt').write_bytes(b'new file\n')
    submodule_file.write_bytes(b'print(1)\r\n')
    return main_repo, main_file, submodule_file, changed_file


def _create_simple_repo(base_path: Path, file_name: str,
                        content: bytes) -> Path:
    """Create a single-file repository with one committed file."""
    repo_path = base_path / 'repo'
    _init_repo(repo_path)
    (repo_path / file_name).write_bytes(content)
    _commit_all(repo_path, 'initial commit')
    return repo_path


def test_git_root_submodule_main() -> None:
    """Test get_git_root for both submodule and main repository roots."""
    with TemporaryDirectory() as tmp_dir:
        base_path = Path(tmp_dir)
        main_repo, _, _, _ = _create_repo_with_submodule(base_path)
        submodule_path = main_repo / 'submod' / 'sub.py'
        assert git_helpers.get_git_root(
            pathlocation=submodule_path,
            this_submodule=True
        ).resolve() == (main_repo / 'submod').resolve()
        assert git_helpers.get_git_root(
            pathlocation=submodule_path,
            this_submodule=False
        ).resolve() == main_repo.resolve()


def test_git_root_warns_no_parent() -> None:
    """Test get_git_root warns when there is no parent git repository."""
    with TemporaryDirectory() as tmp_dir:
        repo_path = Path(tmp_dir) / 'standalone_repo'
        _init_repo(repo_path)
        with pytest.warns(UserWarning):
            root_path = git_helpers.get_git_root(pathlocation=repo_path)
        assert root_path.resolve() == repo_path.resolve()


def test_unstaged_files_main_rel(monkeypatch: pytest.MonkeyPatch) -> \
        None:
    """Test unstaged files are reported relative to the main repo."""
    with TemporaryDirectory() as tmp_dir:
        base_path = Path(tmp_dir)
        main_repo, _, _, _ = _create_repo_with_submodule(base_path)
        monkeypatch.setattr(
            git_helpers,
            'get_git_root',
            lambda *_, **__: main_repo
        )
        unstaged = git_helpers.get_unstaged_files(all_submodules=True)
        assert Path('main.py') in unstaged
        assert Path('changed.txt') in unstaged
        assert Path('submod/sub.py') in unstaged
        assert Path('new.txt') not in unstaged
        unstaged_all = git_helpers.get_unstaged_files(
            only_changed=False,
            all_submodules=False
        )
        assert Path('new.txt') in unstaged_all


def test_unstaged_files_wr_rel(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Test wrapped unstaged files are returned as repo-relative paths."""
    with TemporaryDirectory() as tmp_dir:
        base_path = Path(tmp_dir)
        main_repo, _, _, _ = _create_repo_with_submodule(base_path)
        monkeypatch.setattr(
            git_helpers,
            'get_git_root',
            lambda *_, **__: main_repo
        )
        unstaged_wr = git_helpers.get_unstaged_files_wr(all_submodules=True)
        repo_paths: dict[Path, set[Path]] = {}
        for repo, file_path in unstaged_wr:
            repo_root = Path(str(repo.working_tree_dir)).resolve()
            if repo_root not in repo_paths:
                repo_paths[repo_root] = set()
            repo_paths[repo_root].add(file_path)
        assert Path('main.py') in repo_paths[main_repo.resolve()]
        assert Path('sub.py') in repo_paths[(main_repo / 'submod').resolve()]


def test_only_eol_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test detection of line-ending-only changes including submodules."""
    with TemporaryDirectory() as tmp_dir:
        base_path = Path(tmp_dir)
        main_repo, _, _, _ = _create_repo_with_submodule(base_path)
        monkeypatch.setattr(
            git_helpers,
            'get_git_root',
            lambda *_, **__: main_repo
        )
        only_eol = git_helpers.get_only_line_end_changes(all_submodules=True)
        assert Path('main.py') in only_eol
        assert Path('submod/sub.py') in only_eol
        assert Path('changed.txt') not in only_eol


def test_restore_eol_only(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Test restore_bad_eol_changes restores only line-ending changes."""
    with TemporaryDirectory() as tmp_dir:
        base_path = Path(tmp_dir)
        main_repo, main_file, submodule_file, changed_file = \
            _create_repo_with_submodule(base_path)
        monkeypatch.setattr(
            git_helpers,
            'get_git_root',
            lambda *_, **__: main_repo
        )
        restored = git_helpers.restore_bad_eol_changes(all_submodules=True)
        assert Path('main.py') in restored
        assert Path('submod/sub.py') in restored
        assert Path('changed.txt') not in restored
        assert main_file.read_bytes() == b'print(1)\n'
        assert submodule_file.read_bytes() == b'print(1)\n'
        assert changed_file.read_bytes() == b'changed-content\n'


def test_restore_force_unix(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Test force_unix converts tracked files even without unstaged changes."""
    with TemporaryDirectory() as tmp_dir:
        base_path = Path(tmp_dir)
        repo_path = _create_simple_repo(base_path, 'dos.txt', b'a\r\nb\r\n')
        monkeypatch.setattr(
            git_helpers,
            'get_git_root',
            lambda *_, **__: repo_path
        )
        restored = git_helpers.restore_bad_eol_changes(
            all_submodules=False,
            force_unix=True,
            allowed_patterns=[r'.*\.txt$']
        )
        assert restored == [Path('dos.txt')]
        assert (repo_path / 'dos.txt').read_bytes() == b'a\nb\n'


def test_restore_not_allowed_msg(
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """Test verbose force_unix reports files blocked by allowed patterns."""
    with TemporaryDirectory() as tmp_dir:
        base_path = Path(tmp_dir)
        repo_path = _create_simple_repo(base_path, 'skip.bin', b'a\r\n')
        monkeypatch.setattr(
            git_helpers,
            'get_git_root',
            lambda *_, **__: repo_path
        )
        restored = git_helpers.restore_bad_eol_changes(
            all_submodules=False,
            force_unix=True,
            allowed_patterns=[r'.*\.txt$'],
            verbose=True
        )
        assert not restored
        out, err = capsys.readouterr()
        assert out == ''
        assert 'Not allowed to convert path: skip.bin' in err


def test_sync_warns_unpushed() -> None:
    """Test repo sync warnings report local commits that are not pushed."""
    with TemporaryDirectory() as tmp_dir:
        base_path = Path(tmp_dir)
        repo_path = base_path / 'repo'
        _init_repo(repo_path)
        tracked_file = repo_path / 'tracked.txt'
        tracked_file.write_text('line one\n', encoding='utf-8')
        _commit_all(repo_path, 'initial commit')
        origin_path = _init_bare_repo(base_path, 'origin_repo.git')
        _set_origin_and_push(repo_path=repo_path, origin_path=origin_path)
        tracked_file.write_text('line two\n', encoding='utf-8')
        _commit_all(repo_path, 'local commit')
        warnings_list = git_helpers.get_repo_sync_warnings(
            project_root=repo_path,
            timeout_seconds=5.0
        )
        assert any(
            'unpushed commit(s)' in warning_text
            for warning_text in warnings_list
        )


def test_sync_warns_remote_newer() -> None:
    """Test repo sync warnings report when remote has newer commit(s)."""
    with TemporaryDirectory() as tmp_dir:
        base_path = Path(tmp_dir)
        repo_path = base_path / 'repo'
        _init_repo(repo_path)
        tracked_file = repo_path / 'tracked.txt'
        tracked_file.write_text('line one\n', encoding='utf-8')
        _commit_all(repo_path, 'initial commit')
        origin_path = _init_bare_repo(base_path, 'origin_repo.git')
        _set_origin_and_push(repo_path=repo_path, origin_path=origin_path)
        updater_path = base_path / 'updater'
        _clone_repo(remote_path=origin_path, clone_path=updater_path)
        updater_file = updater_path / 'tracked.txt'
        updater_file.write_text('line two\n', encoding='utf-8')
        _commit_all(updater_path, 'remote commit')
        _run_git(['push'], updater_path)
        warnings_list = git_helpers.get_repo_sync_warnings(
            project_root=repo_path,
            timeout_seconds=5.0
        )
        assert any(
            'newer commit(s) to pull.' in warning_text
            for warning_text in warnings_list
        )


def test_sync_warns_both_repos() -> None:
    """Test sync warnings include checks for main and common build tools."""
    with TemporaryDirectory() as tmp_dir:
        base_path = Path(tmp_dir)
        project_root = base_path / 'project_root'
        _init_repo(project_root)
        root_file = project_root / 'root.txt'
        root_file.write_text('root\n', encoding='utf-8')
        _commit_all(project_root, 'initial main commit')
        main_origin = _init_bare_repo(base_path, 'main_origin.git')
        _set_origin_and_push(repo_path=project_root, origin_path=main_origin)
        root_file.write_text('root changed\n', encoding='utf-8')
        _commit_all(project_root, 'main local commit')
        submodule_root = project_root / 'common_build_tools'
        _init_repo(submodule_root)
        submodule_file = submodule_root / 'tool.txt'
        submodule_file.write_text('tool\n', encoding='utf-8')
        _commit_all(submodule_root, 'initial submodule commit')
        submodule_origin = _init_bare_repo(base_path, 'cbt_origin.git')
        _set_origin_and_push(
            repo_path=submodule_root,
            origin_path=submodule_origin
        )
        submodule_file.write_text('tool changed\n', encoding='utf-8')
        _commit_all(submodule_root, 'submodule local commit')
        warnings_list = git_helpers.get_repo_sync_warnings(
            project_root=project_root,
            timeout_seconds=5.0
        )
        assert any(
            warning_text.startswith('Main repository:')
            for warning_text in warnings_list
        )
        assert any(
            warning_text.startswith('common_build_tools repository:')
            for warning_text in warnings_list
        )
