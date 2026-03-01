#! /usr/bin/env python3
"""Run two clean builds and optionally upload with twine."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

import sys
from typing import Optional

from build_information import get_build_information
from build_spec import BuildInformation, BuildSpec
from build_utils import extract_python_name, run_command, venv_script
from clean_build import clean_build
from get_build_spec import get_build_spec


def _run_clean_build_or_fail(python_name: Optional[str], run_name: str,
                             build_spec: BuildSpec,
                             build_information: BuildInformation) -> int:
    """Run one clean build and print context on failure."""
    result = clean_build(python_name=python_name, build_spec=build_spec,
                         build_information=build_information)
    if result == 0:
        return 0
    print(f'{run_name} failed with exit code {result}.', file=sys.stderr)
    return result


def do_pypi_build(python_name: Optional[str] = None,
                  twine_upload: bool = False,
                  build_spec: Optional[BuildSpec] = None,
                  build_information: Optional[BuildInformation] = None) -> int:
    """Run two clean builds and optionally upload distributions to PyPI."""
    active_spec = get_build_spec() if build_spec is None else build_spec
    active_information = build_information
    if active_information is None:
        active_information = get_build_information(active_spec)
    first_result = _run_clean_build_or_fail(
        python_name=python_name,
        run_name='First clean build',
        build_spec=active_spec,
        build_information=active_information
    )
    if first_result != 0:
        return first_result
    second_result = _run_clean_build_or_fail(
        python_name=python_name,
        run_name='Second clean build',
        build_spec=active_spec,
        build_information=active_information
    )
    if second_result != 0:
        return second_result
    if not twine_upload:
        print('Twine upload not done as it was not requested.')
        print('To upload to PyPI, run: python3 '
              'common_build_tools/src/do_pypi_build.py twine')
        return 0
    dist_dir = active_information['project_root'] / 'dist'
    dist_files = sorted(str(path) for path in dist_dir.iterdir())
    run_command([venv_script('twine'), 'upload', *dist_files],
                cwd=active_information['project_root'])
    return 0


if __name__ == '__main__':
    PYTHON_NAME = extract_python_name(sys.argv[1:])
    TWINE_UPLOAD = 'twine' in sys.argv[1:]
    sys.exit(do_pypi_build(PYTHON_NAME, TWINE_UPLOAD))
