"""Shared validation and identity helpers for fitted models."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


class ModelInputError(ValueError):
    """Model input violates a finite-shape or identity contract."""


def finite_vector(values: Sequence[float] | FloatArray, *, name: str) -> FloatArray:
    """Return a finite one-dimensional float64 vector."""

    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ModelInputError(f"{name} must be one-dimensional")
    if array.size == 0:
        raise ModelInputError(f"{name} must not be empty")
    if not np.isfinite(array).all():
        raise ModelInputError(f"{name} contains non-finite values")
    return array


def validated_keys(keys: Sequence[str], *, expected_size: int) -> tuple[str, ...]:
    """Validate unique nonblank model identity keys."""

    normalized = tuple(str(key).strip() for key in keys)
    if len(normalized) != expected_size:
        raise ModelInputError(
            f"key count {len(normalized)} does not match row count {expected_size}"
        )
    if any(not key for key in normalized):
        raise ModelInputError("model keys must be nonblank")
    if len(set(normalized)) != len(normalized):
        raise ModelInputError("model keys must be unique")
    return normalized


def key_set_sha256(keys: Sequence[str]) -> str:
    """Hash the sorted unique InChIKey training identity set."""

    normalized = validated_keys(keys, expected_size=len(keys))
    encoded = "\n".join(sorted(normalized)).encode("utf-8") + b"\n"
    return hashlib.sha256(encoded).hexdigest()
