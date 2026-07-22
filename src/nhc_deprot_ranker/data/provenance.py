"""Byte-level provenance utilities."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path, *, block_size: int = 1024 * 1024) -> str:
    """Return SHA256 for the exact bytes at `path`."""

    if block_size <= 0:
        raise ValueError("block_size must be positive")
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_source_tree(root: Path) -> str:
    """Hash relative paths and exact bytes for every Python source below `root`."""

    if not root.is_dir():
        raise NotADirectoryError(root)
    paths = sorted(path for path in root.rglob("*.py") if path.is_file())
    if not paths:
        raise ValueError(f"source tree has no Python files: {root}")
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
