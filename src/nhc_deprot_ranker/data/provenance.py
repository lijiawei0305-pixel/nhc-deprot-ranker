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
