"""Deterministic paired bootstrap for the Phase 2 affine coefficients."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from nhc_deprot_ranker.models.affine import AffineCalibrator
from nhc_deprot_ranker.models.base import FloatArray, ModelInputError, finite_vector, validated_keys


@dataclass(frozen=True)
class AffineBootstrapResult:
    """Raw successful replicates and percentile summary."""

    replicates: pd.DataFrame
    summary: dict[str, Any]


def bootstrap_affine(
    *,
    x: Sequence[float] | FloatArray,
    y: Sequence[float] | FloatArray,
    keys: Sequence[str],
    repeats: int,
    seed: int,
    confidence: float,
    min_samples: int,
    condition_number_threshold: float,
) -> AffineBootstrapResult:
    """Resample InChIKey rows, refit B1, and report deterministic intervals."""

    if repeats < 1:
        raise ValueError("bootstrap repeats must be positive")
    if not 0.0 < confidence < 1.0:
        raise ValueError("bootstrap confidence must be between 0 and 1")
    x_array = finite_vector(x, name="x")
    y_array = finite_vector(y, name="y")
    normalized_keys = validated_keys(keys, expected_size=len(x_array))
    if len(y_array) != len(x_array):
        raise ModelInputError("x and y must have equal length")
    generator = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    failures = 0
    for repeat in range(repeats):
        indices = generator.integers(0, len(x_array), size=len(x_array))
        replicate_keys = [
            f"{normalized_keys[index]}#{position}" for position, index in enumerate(indices)
        ]
        try:
            model = AffineCalibrator(
                min_samples=min_samples,
                condition_number_threshold=condition_number_threshold,
            ).fit(x_array[indices], y_array[indices], replicate_keys)
        except ModelInputError:
            failures += 1
            continue
        rows.append(
            {
                "repeat": repeat,
                "beta_0": model.intercept_,
                "rho": model.slope_,
                "used_pseudoinverse": model.used_pseudoinverse_,
            }
        )
    if not rows:
        raise ModelInputError("all affine bootstrap replicates failed")
    frame = pd.DataFrame.from_records(rows)
    alpha = (1.0 - confidence) / 2.0
    summary: dict[str, Any] = {
        "requested_repeats": repeats,
        "successful_repeats": len(frame),
        "failed_repeats": failures,
        "seed": seed,
        "confidence": confidence,
        "interval": "paired_inchikey_percentile",
        "coefficients": {},
    }
    for column in ("beta_0", "rho"):
        values = frame[column].to_numpy(dtype=np.float64)
        summary["coefficients"][column] = {
            "mean": float(np.mean(values)),
            "standard_deviation": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
            "p_low": float(np.quantile(values, alpha)),
            "p50": float(np.quantile(values, 0.5)),
            "p_high": float(np.quantile(values, 1.0 - alpha)),
        }
    return AffineBootstrapResult(replicates=frame, summary=summary)
