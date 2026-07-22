"""Byte-level provenance tests."""

import hashlib
from pathlib import Path

import pytest

from nhc_deprot_ranker.data.provenance import sha256_file


def test_sha256_is_exact_and_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_bytes(b"a,b\n1,2\n")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    assert sha256_file(source) == expected
    assert sha256_file(source, block_size=2) == expected


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        sha256_file(tmp_path / "missing")
