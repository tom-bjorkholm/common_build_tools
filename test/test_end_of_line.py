#! /usr/bin/env python3
"""Tests for common_build_tools.src.end_of_line."""

# Copyright (c) 2026 Tom Björkholm
# MIT License

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import pytest
# Add source directory to path.
# pylint: disable=duplicate-code
_src_path = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(_src_path))
# pylint: disable=wrong-import-position
from end_of_line import (  # noqa: E402
    dos2unix,
    eol_command,
    unix2dos,
)


@pytest.mark.parametrize('source_bytes, expected_bytes', [
        (b'line1\r\nline2\r\n', b'line1\nline2\n'),
        (b'line1\nline2\n', b'line1\nline2\n'),
    ])
def test_dos2unix_in_place(source_bytes: bytes, expected_bytes: bytes) -> None:
    """Test dos2unix in-place conversion."""
    with TemporaryDirectory() as tmp_dir:
        file_path = Path(tmp_dir) / 'sample.txt'
        file_path.write_bytes(source_bytes)
        dos2unix(file_path)
        assert file_path.read_bytes() == expected_bytes


def test_dos2unix_target_file() -> None:
    """Test dos2unix conversion to a separate target file."""
    with TemporaryDirectory() as tmp_dir:
        source_path = Path(tmp_dir) / 'source.txt'
        target_path = Path(tmp_dir) / 'target.txt'
        source_path.write_bytes(b'a\r\nb\r\n')
        dos2unix(source_path, target_file=target_path)
        assert source_path.read_bytes() == b'a\r\nb\r\n'
        assert target_path.read_bytes() == b'a\nb\n'


def test_dos2unix_fix_extra_cr_seq() -> None:
    """Test dos2unix cleanup of extra CR sequences."""
    with TemporaryDirectory() as tmp_dir:
        file_path = Path(tmp_dir) / 'broken.txt'
        file_path.write_bytes(b'a\r\r\nb\n\rc\r\n')
        dos2unix(file_path, fix_extra_cr_seq=True)
        assert file_path.read_bytes() == b'a\nb\nc\n'


def test_dos2unix_cr_as_newline() -> None:
    """Test dos2unix conversion of standalone CR when enabled."""
    with TemporaryDirectory() as tmp_dir:
        file_path = Path(tmp_dir) / 'legacy.txt'
        file_path.write_bytes(b'a\rb\r\nc\r')
        dos2unix(file_path, every_cr_is_new_line=True)
        assert file_path.read_bytes() == b'a\nb\nc\n'


def test_unix2dos_keeps_crlf() -> None:
    """Test unix2dos converts LF without duplicating CR in CRLF."""
    with TemporaryDirectory() as tmp_dir:
        file_path = Path(tmp_dir) / 'source.txt'
        file_path.write_bytes(b'a\nb\r\nc\rd\n')
        unix2dos(file_path)
        assert file_path.read_bytes() == b'a\r\nb\r\nc\rd\r\n'


def test_eol_cmd_dos2unix() -> None:
    """Test eol_command successful dos2unix conversion."""
    with TemporaryDirectory() as tmp_dir:
        source_path = Path(tmp_dir) / 'source.txt'
        source_path.write_bytes(b'a\r\nb\r\n')
        exit_code = eol_command(['dos2unix', '-i', str(source_path)])
        assert exit_code == 0
        assert source_path.read_bytes() == b'a\nb\n'


def test_eol_cmd_unix2dos_target() -> None:
    """Test eol_command unix2dos conversion to target file."""
    with TemporaryDirectory() as tmp_dir:
        source_path = Path(tmp_dir) / 'source.txt'
        target_path = Path(tmp_dir) / 'target.txt'
        source_path.write_bytes(b'a\nb\n')
        exit_code = eol_command([
            'unix2dos',
            '--input',
            str(source_path),
            '--output',
            str(target_path)
        ])
        assert exit_code == 0
        assert source_path.read_bytes() == b'a\nb\n'
        assert target_path.read_bytes() == b'a\r\nb\r\n'


def test_eol_command_missing_file(capsys: pytest.CaptureFixture[str]) -> None:
    """Test eol_command failure when source file does not exist."""
    exit_code = eol_command(['dos2unix', '-i', 'missing-file.txt'])
    assert exit_code == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert 'Error:' in err


def test_eol_cmd_bad_args(capsys: pytest.CaptureFixture[str]) -> None:
    """Test eol_command returns failure for invalid arguments."""
    exit_code = eol_command(['not-a-command'])
    assert exit_code == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert 'usage:' in err
