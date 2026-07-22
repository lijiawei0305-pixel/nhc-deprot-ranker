"""B0 raw xTB identity baseline."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from nhc_deprot_ranker.models.base import FloatArray, finite_vector, key_set_sha256


class XtbBaseline:
    """Return xTB deprotonation energies unchanged."""

    def __init__(self) -> None:
        self.n_samples_: int | None = None
        self.x_min_: float | None = None
        self.x_max_: float | None = None
        self.training_key_sha256_: str | None = None

    def fit(self, x: Sequence[float] | FloatArray, keys: Sequence[str]) -> XtbBaseline:
        """Record the applicability range without learning parameters."""

        vector = finite_vector(x, name="x")
        self.training_key_sha256_ = key_set_sha256(keys)
        if len(keys) != len(vector):
            raise ValueError("x and keys must have equal length")
        self.n_samples_ = len(vector)
        self.x_min_ = float(vector.min())
        self.x_max_ = float(vector.max())
        return self

    def predict(self, x: Sequence[float] | FloatArray) -> FloatArray:
        """Return a defensive copy of finite xTB values."""

        return finite_vector(x, name="x").copy()

    def metadata(self) -> dict[str, Any]:
        """Return fitted B0 identity and applicability metadata."""

        if self.n_samples_ is None:
            raise RuntimeError("XtbBaseline is not fitted")
        return {
            "model": "B0_raw_xtb",
            "n_samples": self.n_samples_,
            "x_min": self.x_min_,
            "x_max": self.x_max_,
            "training_key_sha256": self.training_key_sha256_,
            "lower_is_better": True,
        }
