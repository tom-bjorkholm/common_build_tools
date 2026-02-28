#!/usr/bin/env python3
"""Helper functions for working with git."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

from pathlib import Path
import re
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


DEF_ALLOWED: tuple[str, ...] = (
    r'.*\.py$',
    r'.*\.md$',
    r'.*\.rst$',
    r'.*\.txt$',
    r'.*\.html$',
    r'.*\.css$',
    r'.*\.js$',
    r'.*\.json$',
    r'.*\.xml$',
    r'.*\.yaml$',
    r'.*\.yml$',
    r'.*\.ini$',
)


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
    patterns = list(DEF_ALLOWED if allowed_patterns is None
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
