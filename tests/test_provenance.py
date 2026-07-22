"""Byte-level provenance tests."""

import hashlib
from pathlib import Path

import pytest

from nhc_deprot_ranker.data.provenance import sha256_file, sha256_source_tree


def test_sha256_is_exact_and_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_bytes(b"a,b\n1,2\n")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    assert sha256_file(source) == expected
    assert sha256_file(source, block_size=2) == expected


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        sha256_file(tmp_path / "missing")


def test_source_tree_hash_includes_relative_paths_and_bytes(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "a.py").write_text("A = 1\n")
    (tmp_path / "nested/b.py").write_text("B = 2\n")
    first = sha256_source_tree(tmp_path)
    (tmp_path / "nested/b.py").write_text("B = 3\n")
    assert sha256_source_tree(tmp_path) != first
