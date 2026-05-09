#! /usr/bin/env python3
"""Run clean + build with one shared BuildSpec/BuildInformation context."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

import sys
from typing import Optional

from best_installed_python import resolve_target_python
from build_information import get_build_information
from build_spec import BuildInformation, BuildSpec
from build_utils import exit_if_in_virtualenv, extract_python_name
from get_build_spec import get_build_spec
from clean import clean
from do_build import do_build
from setup_build_environment import setup_build_environment


def clean_build(python_name: Optional[str] = None,
                build_spec: Optional[BuildSpec] = None,
                build_information: Optional[BuildInformation] = None) -> int:
    """Run clean build using one discovered specification and build info."""
    active_spec = get_build_spec() if build_spec is None else build_spec
    active_information = build_information
    if active_information is None:
        active_information = get_build_information(active_spec)
    exit_if_in_virtualenv('delete virtual environment')
    resolved_name = resolve_target_python(python_name)[0]
    clean(build_spec=active_spec, build_information=active_information)
    setup_build_environment(python_name=resolved_name, build_spec=active_spec,
                            build_information=active_information)
    return do_build(python_name=resolved_name, build_spec=active_spec,
                    build_information=active_information)


def clean_build_cmd(build_spec: Optional[BuildSpec] = None,
                    build_information: Optional[BuildInformation] = None) \
                        -> None:
    """Run clean build command."""
    python_name = extract_python_name(sys.argv[1:])
    sys.exit(clean_build(python_name, build_spec, build_information))


if __name__ == '__main__':
    clean_build_cmd()
