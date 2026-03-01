#! /usr/bin/env python3
"""Get the build specification for the common_build_tools."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

import sys
from pathlib import Path
from typing import Optional
from build_spec import BuildSpec
try:
    custom_build_tools_folder = (
        Path(__file__).resolve().parents[2] / 'custom_build_tools'
    )
    sys.path.insert(0, str(custom_build_tools_folder))
    # pylint: disable=wrong-import-order
    from custom_spec import custom_spec
except ImportError:
    def custom_spec() -> Optional[BuildSpec]:
        """Return None as no custom build specification found."""
        print('No custom build specification found.', file=sys.stderr)
        print('Looked for custom_spec() in', file=sys.stderr)
        print(f'  {custom_build_tools_folder / "custom_spec.py"}',
              file=sys.stderr)
        print('Using default build specification.', file=sys.stderr)
        custom_build_spec: Optional[BuildSpec] = None
        return custom_build_spec


def _default_build_spec() -> BuildSpec:
    """Return the default common build specification."""
    return BuildSpec(
        package_folders=None,
        identical_versions=True,
        mypy_on_test=True,
        custom_before_clean=None,
        custom_before_build=None,
        custom_before_install=None,
        custom_before_test=None,
        custom_after_test=None,
        custom_final=None,
    )


def get_build_spec() -> BuildSpec:
    """Get the active build specification.

    If `custom_build_tools/custom_spec.py` defines `custom_spec()` and that
    function returns a `BuildSpec`, that specification is used.
    """
    custom_build_spec = custom_spec()
    if custom_build_spec is None:
        return _default_build_spec()
    assert custom_build_spec is not None
    if isinstance(custom_build_spec, BuildSpec):
        return custom_build_spec
    print('custom_spec() did not return BuildSpec.', file=sys.stderr)
    print('Using default build specification.', file=sys.stderr)
    return _default_build_spec()
