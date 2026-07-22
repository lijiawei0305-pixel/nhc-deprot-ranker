"""Deterministic paired bootstrap for the Phase 2 affine coefficients."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from nhc_deprot_ranker.models.affine import AffineCalibrator
from nhc_deprot_ranker.models.base import FloatArray, ModelInputError, finite_vector, validated_keys
from nhc_deprot_ranker.models.hierarchical import FAMILY_COLUMNS, HierarchicalLinearCalibrator
from nhc_deprot_ranker.validation.nested_cv import PenaltySet
from nhc_deprot_ranker.validation.ranking import top_indices


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


@dataclass(frozen=True)
class HierarchicalBootstrapResult:
    """H1 query and family uncertainty summaries."""

    predictions: pd.DataFrame
    family_effects: pd.DataFrame
    metadata: dict[str, Any]


def bootstrap_hierarchical(
    *,
    training_frame: pd.DataFrame,
    y: Sequence[float] | FloatArray,
    query_frame: pd.DataFrame,
    penalties: PenaltySet,
    lambda_slope: float,
    rho_prior: float,
    condition_number_threshold: float,
    skeleton_policy: str,
    repeats: int,
    seed: int,
    confidence: float,
    top_k: Sequence[int],
) -> HierarchicalBootstrapResult:
    """Refit H1 on paired key resamples with fixed nested-CV penalties."""

    if repeats < 1:
        raise ValueError("bootstrap repeats must be positive")
    if not 0.0 < confidence < 1.0:
        raise ValueError("bootstrap confidence must be between 0 and 1")
    target = finite_vector(y, name="H1 bootstrap target")
    if len(target) != len(training_frame):
        raise ModelInputError("H1 bootstrap target length does not match training rows")
    training_keys = validated_keys(
        training_frame["inchikey"].astype(str).tolist(), expected_size=len(training_frame)
    )
    query_keys = validated_keys(
        query_frame["inchikey"].astype(str).tolist(), expected_size=len(query_frame)
    )
    for k in top_k:
        if not 1 <= k <= len(query_frame):
            raise ValueError(f"bootstrap Top-K must be between 1 and {len(query_frame)}")
    levels = {
        column: tuple(sorted(training_frame[column].astype(str).unique().tolist()))
        for column in FAMILY_COLUMNS
    }
    supports = {
        column: {
            str(level): int(count)
            for level, count in training_frame[column].astype(str).value_counts().items()
        }
        for column in FAMILY_COLUMNS
    }
    generator = np.random.default_rng(seed)
    prediction_rows: list[FloatArray] = []
    family_rows: list[dict[tuple[str, str], float]] = []
    present_rows: list[set[tuple[str, str]]] = []
    top_counts = {k: np.zeros(len(query_frame), dtype=np.int64) for k in top_k}
    failures: list[dict[str, Any]] = []
    for repeat in range(repeats):
        indices = generator.integers(0, len(training_frame), size=len(training_frame))
        sampled = training_frame.iloc[indices].copy().reset_index(drop=True)
        sampled["inchikey"] = [
            f"{training_keys[index]}#{position}" for position, index in enumerate(indices)
        ]
        try:
            model = HierarchicalLinearCalibrator(
                lambda_skeleton=penalties.lambda_skeleton,
                lambda_axis_a=penalties.lambda_axis_a,
                lambda_axis_b=penalties.lambda_axis_b,
                lambda_slope=lambda_slope,
                rho_prior=rho_prior,
                condition_number_threshold=condition_number_threshold,
                skeleton_policy=skeleton_policy,
            ).fit(sampled, target[indices])
            predictions = model.predict(query_frame)
        except (RuntimeError, ValueError, np.linalg.LinAlgError) as exc:
            failures.append({"repeat": repeat, "error": f"{type(exc).__name__}: {exc}"})
            continue
        prediction_rows.append(predictions)
        for k in top_k:
            selected = top_indices(predictions, query_keys, k, lower_is_better=True)
            top_counts[k][selected] += 1
        effects_frame = model.family_effects()
        effect_mapping = {
            (term, level): float(effect)
            for term, level, effect in zip(
                effects_frame["term"].astype(str).tolist(),
                effects_frame["level"].astype(str).tolist(),
                effects_frame["effect_kcal"].to_numpy(dtype=np.float64),
                strict=True,
            )
        }
        family_rows.append(effect_mapping)
        present_rows.append(set(effect_mapping))
    if not prediction_rows:
        raise ModelInputError("all H1 bootstrap replicates failed")
    prediction_matrix = np.vstack(prediction_rows)
    alpha = (1.0 - confidence) / 2.0
    prediction_summary = pd.DataFrame(
        {
            "inchikey": query_keys,
            "prediction_mean": np.mean(prediction_matrix, axis=0),
            "prediction_std": np.std(prediction_matrix, axis=0, ddof=1)
            if len(prediction_matrix) > 1
            else np.zeros(len(query_frame)),
            "prediction_p025": np.quantile(prediction_matrix, alpha, axis=0),
            "prediction_p05": np.quantile(prediction_matrix, 0.05, axis=0),
            "prediction_p50": np.quantile(prediction_matrix, 0.5, axis=0),
            "prediction_p95": np.quantile(prediction_matrix, 0.95, axis=0),
            "prediction_p975": np.quantile(prediction_matrix, 1.0 - alpha, axis=0),
        }
    )
    for k in top_k:
        prediction_summary[f"probability_top_{k}"] = top_counts[k] / len(prediction_rows)
    family_summary_rows: list[dict[str, Any]] = []
    for column in FAMILY_COLUMNS:
        for level in levels[column]:
            identity = (column, level)
            values = np.asarray(
                [mapping.get(identity, 0.0) for mapping in family_rows], dtype=np.float64
            )
            family_summary_rows.append(
                {
                    "term": column,
                    "level": level,
                    "support": supports[column][level],
                    "effect_mean": float(np.mean(values)),
                    "effect_std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
                    "effect_p025": float(np.quantile(values, alpha)),
                    "effect_p05": float(np.quantile(values, 0.05)),
                    "effect_p50": float(np.quantile(values, 0.5)),
                    "effect_p95": float(np.quantile(values, 0.95)),
                    "effect_p975": float(np.quantile(values, 1.0 - alpha)),
                    "probability_positive": float(np.mean(values > 0.0)),
                    "probability_negative": float(np.mean(values < 0.0)),
                    "sign_stability": float(max(np.mean(values > 0.0), np.mean(values < 0.0))),
                    "present_fraction": float(
                        np.mean([identity in present for present in present_rows])
                    ),
                }
            )
    family_summary = pd.DataFrame.from_records(family_summary_rows).sort_values(["term", "level"])
    family_summary = family_summary.reset_index(drop=True)
    metadata = {
        "requested_repeats": repeats,
        "successful_repeats": len(prediction_rows),
        "failed_repeats": len(failures),
        "failures": failures,
        "seed": seed,
        "confidence": confidence,
        "interval": "paired_inchikey_percentile",
        "regularization_policy": "fixed_from_nested_cv",
        "penalties": penalties.to_dict(),
        "query_scope": "71_labeled_rows_not_full_pool",
    }
    return HierarchicalBootstrapResult(
        predictions=prediction_summary,
        family_effects=family_summary,
        metadata=metadata,
    )
