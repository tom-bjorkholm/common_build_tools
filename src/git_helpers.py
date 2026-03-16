#!/usr/bin/env python3
"""Helper functions for working with git."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

from pathlib import Path
import os
import re
import subprocess
import sys
from typing import Optional
from warnings import warn
try:
    from git import Repo
    from git.exc import InvalidGitRepositoryError
except ImportError:
    print('You need to install the gitpython package.', file=sys.stderr)
    print('\n\tpython3 -m pip install --upgrade gitpython\n',
          file=sys.stderr)
    sys.exit(1)
from end_of_line import dos2unix
from eol_patterns import EOL_ALLOWED_PATTERNS

COMMON_BUILD_TOOLS_DIR_NAME = 'common_build_tools'
REMOTE_FETCH_TIMEOUT_SECONDS = 5.0


def _run_git_subprocess(repo_path: Path, args: list[str],
                        timeout_seconds: float) -> \
                            subprocess.CompletedProcess[str]:
    """Run git command in one repository with prompt disabled."""
    environment = dict(os.environ)
    environment['GIT_TERMINAL_PROMPT'] = '0'
    return subprocess.run(
        ['git', '-C', str(repo_path), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
        env=environment
    )


def _git_error_text(process: subprocess.CompletedProcess[str]) -> str:
    """Return first non-empty error line from a git subprocess result."""
    combined_text = process.stderr.strip() or process.stdout.strip()
    if not combined_text:
        return 'no details available'
    return combined_text.splitlines()[0]


def _parse_rev_list_counts(count_text: str) -> Optional[tuple[int, int]]:
    """Parse output from rev-list --left-right --count into ints."""
    parts = count_text.strip().split()
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _git_stdout_or_warning(repo_label: str, repo_path: Path, args: list[str],
                           timeout_seconds: float, action_text: str) -> \
                               tuple[Optional[str], Optional[str]]:
    """Return git stdout or a formatted warning text for one command."""
    try:
        process = _run_git_subprocess(
            repo_path=repo_path,
            args=args,
            timeout_seconds=timeout_seconds
        )
    except subprocess.TimeoutExpired:
        return None, (
            f'{repo_label}: {action_text} timed out after '
            f'{timeout_seconds:.1f}s.'
        )
    if process.returncode != 0:
        return None, (
            f'{repo_label}: {action_text} failed: {_git_error_text(process)}'
        )
    return process.stdout.strip(), None


def _upstream_name_or_warning(repo_label: str, repo_path: Path,
                              branch_name: str,
                              timeout_seconds: float) -> \
                                  tuple[Optional[str], Optional[str]]:
    """Return upstream branch name or a warning when it cannot be resolved."""
    try:
        process = _run_git_subprocess(
            repo_path=repo_path,
            args=['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'],
            timeout_seconds=timeout_seconds
        )
    except subprocess.TimeoutExpired:
        return None, (
            f'{repo_label}: upstream check timed out after '
            f'{timeout_seconds:.1f}s.'
        )
    if process.returncode != 0:
        return None, (
            f'{repo_label}: branch {branch_name} has no upstream branch.'
        )
    return process.stdout.strip(), None


def _fetch_warning(repo_label: str, repo_path: Path,
                   timeout_seconds: float) -> tuple[bool, Optional[str]]:
    """Fetch remote refs and return success flag plus optional warning."""
    try:
        process = _run_git_subprocess(
            repo_path=repo_path,
            args=['fetch', '--quiet'],
            timeout_seconds=timeout_seconds
        )
    except subprocess.TimeoutExpired:
        return False, (
            f'{repo_label}: remote check timed out after '
            f'{timeout_seconds:.1f}s (offline build continues).'
        )
    if process.returncode != 0:
        return False, (
            f'{repo_label}: remote check failed: {_git_error_text(process)}'
        )
    return True, None


def _compare_counts_or_warning(repo_label: str, repo_path: Path,
                               upstream_name: str,
                               timeout_seconds: float) -> \
                                   tuple[Optional[tuple[int, int]],
                                         Optional[str]]:
    """Return behind/ahead counts or warning text for branch comparison."""
    try:
        process = _run_git_subprocess(
            repo_path=repo_path,
            args=['rev-list', '--left-right', '--count',
                  f'{upstream_name}...HEAD'],
            timeout_seconds=timeout_seconds
        )
    except subprocess.TimeoutExpired:
        return None, (
            f'{repo_label}: branch compare timed out after '
            f'{timeout_seconds:.1f}s.'
        )
    if process.returncode != 0:
        return None, (
            f'{repo_label}: branch compare failed: {_git_error_text(process)}'
        )
    counts = _parse_rev_list_counts(process.stdout)
    if counts is None:
        return None, (
            f'{repo_label}: could not parse branch difference counts.'
        )
    return counts, None


def _branch_upstream_or_warn(
        repo_label: str, repo_path: Path, timeout_seconds: float) -> \
            tuple[Optional[tuple[str, str]], list[str]]:
    """Resolve branch/upstream names, or return warning list."""
    warnings_list: list[str] = []
    resolved_pair: Optional[tuple[str, str]] = None
    probe_text, probe_warning = _git_stdout_or_warning(
        repo_label=repo_label,
        repo_path=repo_path,
        args=['rev-parse', '--is-inside-work-tree'],
        timeout_seconds=timeout_seconds,
        action_text='git check'
    )
    if probe_warning is not None:
        warnings_list.append(probe_warning)
    elif probe_text != 'true':
        warnings_list.append(
            f'{repo_label}: folder is not a git repository: {repo_path}'
        )
    if not warnings_list:
        branch_text, branch_warning = _git_stdout_or_warning(
            repo_label=repo_label,
            repo_path=repo_path,
            args=['rev-parse', '--abbrev-ref', 'HEAD'],
            timeout_seconds=timeout_seconds,
            action_text='branch check'
        )
        if branch_warning is not None:
            warnings_list.append(branch_warning)
        elif branch_text == 'HEAD':
            warnings_list.append(
                f'{repo_label}: detached HEAD, cannot check push/pull status.'
            )
        elif branch_text is None:
            warnings_list.append(
                f'{repo_label}: branch check produced empty output.'
            )
        else:
            upstream_text, upstream_warning = _upstream_name_or_warning(
                repo_label=repo_label,
                repo_path=repo_path,
                branch_name=branch_text,
                timeout_seconds=timeout_seconds
            )
            if upstream_warning is not None:
                warnings_list.append(upstream_warning)
            elif upstream_text is None:
                warnings_list.append(
                    f'{repo_label}: upstream check produced empty output.'
                )
            else:
                resolved_pair = (branch_text, upstream_text)
    return resolved_pair, warnings_list


def _repo_sync_warnings(repo_label: str, repo_path: Path,
                        timeout_seconds: float) -> list[str]:
    """Return synchronization warnings for one git repository."""
    if not repo_path.is_dir():
        return [
            f'{repo_label}: repository folder is missing: {repo_path}'
        ]
    warnings_list: list[str] = []
    branch_data, branch_warnings = _branch_upstream_or_warn(
        repo_label=repo_label,
        repo_path=repo_path,
        timeout_seconds=timeout_seconds
    )
    warnings_list.extend(branch_warnings)
    if branch_data is None:
        return warnings_list
    branch_name, upstream_name = branch_data
    fetch_ok, fetch_warning = _fetch_warning(
        repo_label=repo_label,
        repo_path=repo_path,
        timeout_seconds=timeout_seconds
    )
    if fetch_warning is not None:
        warnings_list.append(fetch_warning)
    counts, compare_warning = _compare_counts_or_warning(
        repo_label=repo_label,
        repo_path=repo_path,
        upstream_name=upstream_name,
        timeout_seconds=timeout_seconds
    )
    if compare_warning is not None:
        warnings_list.append(compare_warning)
        return warnings_list
    if counts is None:
        return warnings_list
    behind_count, ahead_count = counts
    if ahead_count > 0:
        warnings_list.append(
            f'{repo_label}: local branch {branch_name} has '
            f'{ahead_count} unpushed commit(s) to {upstream_name}.'
        )
    if fetch_ok and behind_count > 0:
        warnings_list.append(
            f'{repo_label}: remote branch {upstream_name} has '
            f'{behind_count} newer commit(s) to pull.'
        )
    return warnings_list


def get_repo_sync_warnings(
        project_root: Path,
        timeout_seconds: float = REMOTE_FETCH_TIMEOUT_SECONDS) -> list[str]:
    """Return synchronization warnings for main repo and submodule repo."""
    warnings_list: list[str] = []
    repo_checks = [
        ('Main repository', project_root),
        ('common_build_tools repository',
         project_root / COMMON_BUILD_TOOLS_DIR_NAME),
    ]
    for repo_label, repo_path in repo_checks:
        warnings_list.extend(
            _repo_sync_warnings(
                repo_label=repo_label,
                repo_path=repo_path,
                timeout_seconds=timeout_seconds
            )
        )
    return warnings_list


def get_git_root(pathlocation: Optional[Path] = None,
                 this_submodule: bool = False) -> Path:
    """Get the root of the git repository.

    Get the path to the root of the git repo that contains the given path.

    Args:
        pathlocation: The path to the directory to start the search from.
                      If None, the directory of the script will be used.
        this_submodule: If True, the path will be the path to root
                        of the submodule repo with the code.
                        If False, the path will be the path to the root
                        of the main git repo that contains the submodule.

    Returns:
        The path to the root of the git repo.
    """
    usepath: Path = pathlocation if pathlocation is not None else Path(
        __file__
    ).parent
    try:
        repo: Repo = Repo(usepath, search_parent_directories=True)
    except InvalidGitRepositoryError as exc:
        errmsg: str = 'Found no git repository containing '
        errmsg += f'{usepath}'
        raise ValueError(errmsg) from exc
    this_repo_path: Path = Path(repo.git.rev_parse('--show-toplevel'))
    if this_submodule:
        return this_repo_path
    try:
        repo = Repo(this_repo_path.parent, search_parent_directories=True)
    except InvalidGitRepositoryError as exc:
        errmsg = 'Found no git repository containing '
        errmsg += f'{this_repo_path.parent}. {str(exc)}'
        warn(errmsg)
        return this_repo_path
    return Path(repo.git.rev_parse('--show-toplevel'))


def _repo_root(repo: Repo) -> Path:
    """Get the root path of the given repository."""
    root_text = repo.working_tree_dir
    if root_text is None:
        raise ValueError('Repository has no working tree directory.')
    return Path(root_text)


def _get_main_repo() -> Repo:
    """Get a Repo object for the main repository."""
    return Repo(get_git_root())


def _submodule_repos(main_repo: Repo) -> list[Repo]:
    """Get available submodule repositories for a main repository."""
    repos: list[Repo] = []
    for submodule in main_repo.submodules:
        try:
            repos.append(submodule.module())
        except (ValueError, InvalidGitRepositoryError) as exc:
            warn(f'Could not load submodule {submodule.path}: {exc}')
    return repos


def _to_main_relative_path(main_repo: Repo, repo: Repo,
                           repo_relative_path: Path) -> Path:
    """Convert a repo-relative path to main-repo-relative form."""
    main_root = _repo_root(main_repo)
    repo_root = _repo_root(repo)
    try:
        rel_repo_root = repo_root.relative_to(main_root)
    except ValueError:
        warn(f'{repo_root} is not inside main repo root {main_root}.')
        return repo_relative_path
    if rel_repo_root == Path('.'):
        return repo_relative_path
    return rel_repo_root / repo_relative_path


def _get_unstaged_repo_paths(repo: Repo,
                             only_changed: bool = True) -> list[Path]:
    """Get unstaged repo-relative paths for one repository."""
    unstaged_paths: list[Path] = []
    for diff in repo.index.diff(None):
        if diff.a_path is None:
            continue
        if diff.change_type == 'D':
            continue
        if only_changed and diff.change_type == 'A':
            continue
        unstaged_paths.append(Path(diff.a_path))
    if not only_changed:
        unstaged_paths.extend(
            Path(path_text) for path_text in repo.untracked_files
        )
    unique_paths: list[Path] = []
    seen_paths: set[Path] = set()
    for file_path in unstaged_paths:
        if file_path in seen_paths:
            continue
        seen_paths.add(file_path)
        unique_paths.append(file_path)
    return unique_paths


def get_unstaged_files_wr(only_changed: bool = True,
                          all_submodules: bool = True) -> \
                              list[tuple[Repo, Path]]:
    """Get the unstaged files (with repo object) in the git repository.

    Args:
        only_changed: If True, only the unstaged files that are changed
                      will be returned, that is files that was previously
                      added to the git repository.
                      If False, all unstaged files including files to add
                      will be returned.
        all_submodules: If True, the unstaged files in all
                        submodules will be returned.
                        If False, only the unstaged files in the
                        main repository will be returned.

    Returns:
        A list of tuples with repo objects and repo-relative file paths.
        Deleted files are not included.
    """
    main_repo = _get_main_repo()
    unstaged_files = [
        (main_repo, file_path) for file_path in
        _get_unstaged_repo_paths(main_repo, only_changed=only_changed)
    ]
    if not all_submodules:
        return unstaged_files
    for submodule_repo in _submodule_repos(main_repo):
        unstaged_files.extend(
            [
                (submodule_repo, file_path) for file_path in
                _get_unstaged_repo_paths(submodule_repo,
                                         only_changed=only_changed)
            ]
        )
    return unstaged_files


def get_unstaged_files(only_changed: bool = True,
                       all_submodules: bool = True) -> list[Path]:
    """Get the unstaged files in the git repository.

    Args:
        only_changed: If True, only the unstaged files that are changed
                      will be returned, that is files that was previously
                      added to the git repository.
                      If False, all unstaged files will be returned.
        all_submodules: If True, the unstaged files in all
                        submodules will be returned.
                        If False, only the unstaged files in the
                        main repository will be returned.

    Returns:
        A list of main-repo-relative paths for unstaged files.
        Deleted files are not included.
    """
    main_repo = _get_main_repo()
    unstaged_files = get_unstaged_files_wr(
        only_changed=only_changed,
        all_submodules=all_submodules
    )
    return [
        _to_main_relative_path(main_repo, repo, file_path)
        for repo, file_path in unstaged_files
    ]


def get_only_line_end_changes(all_submodules: bool = True) -> list[Path]:
    """Get files where only line ending has changed.

    Args:
        all_submodules: If True, the only line end changes in all
                        submodules will be returned.
                        If False, only the only line end changes in the
                        main repository will be returned.

    Returns:
        A list of main-repo-relative paths where only line ending changed.
    """
    only_eol_changes: list[Path] = []
    main_repo = _get_main_repo()
    unstaged_files = get_unstaged_files_wr(all_submodules=all_submodules)
    for repo, file_path in unstaged_files:
        diff_output = repo.git.diff('--ignore-cr-at-eol',
                                    '--ignore-space-at-eol',
                                    file_path.as_posix())
        if not diff_output.strip():
            only_eol_changes.append(
                _to_main_relative_path(main_repo, repo, file_path)
            )
    return only_eol_changes


def _matches_allowed_patterns(path: Path,
                              allowed_patterns: list[str]) -> bool:
    """Check if a path matches at least one allowed regex pattern."""
    path_text = path.as_posix()
    return any(re.match(pattern, path_text) for pattern in allowed_patterns)


def _tracked_files_for_repo(repo: Repo) -> list[Path]:
    """Get tracked files for one repository as repo-relative paths."""
    file_text = repo.git.ls_files()
    if not file_text.strip():
        return []
    return [Path(line) for line in file_text.splitlines()]


def _candidate_files_for_restore(main_repo: Repo, all_submodules: bool,
                                 force_unix: bool) -> \
                                     list[tuple[Repo, Path, Path]]:
    """Collect candidate files for restore operation."""
    if force_unix:
        candidate_files: list[tuple[Repo, Path, Path]] = []
        repos = [main_repo]
        if all_submodules:
            repos.extend(_submodule_repos(main_repo))
        for repo in repos:
            repo_files = _tracked_files_for_repo(repo)
            for repo_path in repo_files:
                main_rel_path = _to_main_relative_path(
                    main_repo, repo, repo_path)
                candidate_files.append((repo, repo_path, main_rel_path))
        return candidate_files
    main_rel_only_eol = get_only_line_end_changes(all_submodules)
    unstaged_wr = get_unstaged_files_wr(all_submodules=all_submodules)
    unstaged_by_main_rel = {
        _to_main_relative_path(main_repo, repo, repo_path): (repo, repo_path)
        for repo, repo_path in unstaged_wr
    }
    candidate_files = []
    for main_rel_path in main_rel_only_eol:
        repo_file = unstaged_by_main_rel.get(main_rel_path)
        if repo_file is None:
            continue
        repo, repo_path = repo_file
        candidate_files.append((repo, repo_path, main_rel_path))
    return candidate_files


def restore_bad_eol_changes(all_submodules: bool = True,
                            force_unix: bool = False,
                            allowed_patterns: Optional[list[str]] = None,
                            verbose: bool = False) -> list[Path]:
    """Restore files where only change is DOS line endings.

    If the change is only that the line endings have changed
    from Unix (LF) to DOS (CRLF) the file will be restored to
    the Unix line endings.

    Args:
        all_submodules: If True, the only line end changes in all
                        submodules will be returned.
                        If False, only the only line end changes in the
                        main repository will be returned.
        force_unix: If True all line endings will be converted to
                    Unix line endings (LF), even line endings that
                    are DOS line endings (CRLF) previously committed
                    and not changed in the working tree.
        allowed_patterns: A list of strings with regex patterns matching
                 files that are allowed to be restored.
                 If the file name matches any of the patterns, it will be
                 restored.
        verbose: If True, the function will print verbose output
                 including the files that are being restored.

    Returns:
        A list of Path objects representing the files that were restored
        or changed to Unix line endings.
    """
    patterns = list(EOL_ALLOWED_PATTERNS if allowed_patterns is None
                    else allowed_patterns)
    main_repo = _get_main_repo()
    candidate_files = _candidate_files_for_restore(
        main_repo,
        all_submodules=all_submodules,
        force_unix=force_unix
    )
    seen_paths: set[Path] = set()
    restored_files: list[Path] = []
    for repo, repo_rel_path, main_rel_path in candidate_files:
        if main_rel_path in seen_paths:
            continue
        seen_paths.add(main_rel_path)
        if not _matches_allowed_patterns(main_rel_path, patterns):
            if verbose and force_unix:
                print(f'Not allowed to convert path: {main_rel_path}',
                      file=sys.stderr)
            continue
        full_path = _repo_root(repo) / repo_rel_path
        if not full_path.is_file():
            continue
        dos2unix(full_path)
        restored_files.append(main_rel_path)
        if verbose:
            print(f'Converted to Unix line endings: {main_rel_path}',
                  file=sys.stderr)
    return restored_files
