#! /usr/bin/env python3
"""Helper functions for working with end of line characters."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

import argparse
from pathlib import Path
import re
import sys
from typing import Optional


def _resolve_target_path(source_file: Path,
                         target_file: Optional[Path]) -> Path:
    """Resolve the output path for an end-of-line conversion."""
    return source_file if target_file is None else target_file


def _read_file_bytes(path: Path) -> bytes:
    """Read a file as bytes."""
    with open(path, 'rb') as file_obj:
        return file_obj.read()


def _write_file_bytes(path: Path, data: bytes) -> None:
    """Write bytes to a file."""
    with open(path, 'wb') as file_obj:
        file_obj.write(data)


def _fix_extra_cr_sequences(data: bytes) -> bytes:
    """Remove extra CR around LF for known corrupted EOL sequences."""
    previous_data = b''
    fixed_data = data
    while previous_data != fixed_data:
        previous_data = fixed_data
        fixed_data = fixed_data.replace(b'\r\r\n', b'\r\n')
        fixed_data = fixed_data.replace(b'\n\r', b'\n')
    return fixed_data


def dos2unix(source_file: Path, target_file: Optional[Path] = None,
             fix_extra_cr_seq: bool = False,
             every_cr_is_new_line: bool = False) -> None:
    """Convert a file from DOS line endings to Unix line endings.

    Args:
        source_file: The path to the source file.
        target_file: The path to the target file.
            If None, the source file will be overwritten.
        fix_extra_cr_seq: If True, extra CR just before or after a LF will be
            removed. This is useful for files that have been corrupted by
            runnning unix2dos on a file that was originally DOS line endings,
            or for files from ancient macs that used LFCR line endings.
        every_cr_is_new_line: If True, add an extra pass after the normal
            conversion to convert CR that are not followed by an LF
            to LF. This is solely for fixing files that have been corrupted.

    Returns:
        None
    """
    source_data = _read_file_bytes(source_file)
    if fix_extra_cr_seq:
        source_data = _fix_extra_cr_sequences(source_data)
    converted_data = source_data.replace(b'\r\n', b'\n')
    if every_cr_is_new_line:
        converted_data = converted_data.replace(b'\r', b'\n')
    destination_path = _resolve_target_path(source_file, target_file)
    _write_file_bytes(destination_path, converted_data)


def unix2dos(source_file: Path, target_file: Optional[Path] = None) -> None:
    """Convert a file from Unix line endings to DOS line endings.

    Args:
        source_file: The path to the source file.
        target_file: The path to the target file.
            If None, the source file will be overwritten.
    """
    source_data = _read_file_bytes(source_file)
    converted_data = re.sub(rb'(?<!\r)\n', b'\r\n', source_data)
    destination_path = _resolve_target_path(source_file, target_file)
    _write_file_bytes(destination_path, converted_data)


def _create_argument_parser() -> argparse.ArgumentParser:
    """Create the argument parser for command line EOL conversion."""
    parser = argparse.ArgumentParser(
        description='Convert files between DOS and Unix line endings.')
    subparsers = parser.add_subparsers(dest='command', required=True)
    dos2unix_parser = subparsers.add_parser(
        'dos2unix', help='Convert CRLF line endings to LF line endings.')
    dos2unix_parser.add_argument('-i', '--input', required=True,
                                 dest='source_file', type=Path,
                                 help='Input file to convert.')
    dos2unix_parser.add_argument('-o', '--output', required=False,
                                 dest='target_file', type=Path, default=None,
                                 help='Optional output file path.')
    dos2unix_parser.add_argument(
        '--fix-extra-cr-seq', action='store_true',
        help='Remove extra CR around LF before conversion.')
    dos2unix_parser.add_argument(
        '--every-cr-is-new-line', action='store_true',
        help='Convert remaining CR bytes into LF bytes.')
    unix2dos_parser = subparsers.add_parser(
        'unix2dos', help='Convert LF line endings to CRLF line endings.')
    unix2dos_parser.add_argument('-i', '--input', required=True,
                                 dest='source_file', type=Path,
                                 help='Input file to convert.')
    unix2dos_parser.add_argument('-o', '--output', required=False,
                                 dest='target_file', type=Path, default=None,
                                 help='Optional output file path.')
    return parser


def eol_command(args: Optional[list[str]] = None) -> int:
    """Parse command line args for dos2unix and unix2dos commands.

    Args:
        args: The command line arguments.
            If None, the command line arguments will be parsed from sys.argv.

    Returns:
        The exit code.
    """
    parser = _create_argument_parser()
    try:
        parsed_args = parser.parse_args(args)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1
    try:
        if parsed_args.command == 'dos2unix':
            dos2unix(source_file=parsed_args.source_file,
                     target_file=parsed_args.target_file,
                     fix_extra_cr_seq=parsed_args.fix_extra_cr_seq,
                     every_cr_is_new_line=parsed_args.every_cr_is_new_line)
        else:
            unix2dos(source_file=parsed_args.source_file,
                     target_file=parsed_args.target_file)
    except OSError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(eol_command())
