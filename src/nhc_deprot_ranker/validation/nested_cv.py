"""Finite leakage-safe inner penalty selection for H1."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from nhc_deprot_ranker.config import HierarchicalModelConfig
from nhc_deprot_ranker.models.base import FloatArray, ModelInputError, finite_vector
from nhc_deprot_ranker.models.hierarchical import HierarchicalLinearCalibrator
from nhc_deprot_ranker.validation.splits import ValidationFold


@dataclass(frozen=True)
class PenaltySet:
    """One H1 family-penalty candidate."""

    lambda_skeleton: float
    lambda_axis_a: float
    lambda_axis_b: float

    def to_dict(self) -> dict[str, float]:
        """Return a JSON-compatible mapping."""

        return {
            "lambda_skeleton": self.lambda_skeleton,
            "lambda_axis_a": self.lambda_axis_a,
            "lambda_axis_b": self.lambda_axis_b,
        }


@dataclass(frozen=True)
class NestedSelectionResult:
    """Selected penalties and complete finite search evidence."""

    selected: PenaltySet
    selected_rmse: float
    candidates: tuple[dict[str, Any], ...]


def _model(penalties: PenaltySet, config: HierarchicalModelConfig) -> HierarchicalLinearCalibrator:
    return HierarchicalLinearCalibrator(
        lambda_skeleton=penalties.lambda_skeleton,
        lambda_axis_a=penalties.lambda_axis_a,
        lambda_axis_b=penalties.lambda_axis_b,
        lambda_slope=config.slope.penalty,
        rho_prior=config.slope.prior_center,
        condition_number_threshold=config.numerical.condition_number_threshold,
        skeleton_policy=config.skeleton_policy,
    )


def _evaluate_candidate(
    *,
    frame: pd.DataFrame,
    target: FloatArray,
    folds: tuple[ValidationFold, ...],
    penalties: PenaltySet,
    config: HierarchicalModelConfig,
) -> dict[str, Any]:
    predictions = np.empty(len(frame), dtype=np.float64)
    seen = np.zeros(len(frame), dtype=bool)
    fold_records: list[dict[str, Any]] = []
    try:
        for fold in folds:
            train = np.asarray(fold.train_indices, dtype=np.int64)
            test = np.asarray(fold.test_indices, dtype=np.int64)
            if np.any(seen[test]):
                raise ModelInputError(f"inner fold duplicates test rows: {fold.fold_id}")
            estimator = _model(penalties, config).fit(
                frame.iloc[train].reset_index(drop=True), target[train]
            )
            fold_predictions = estimator.predict(frame.iloc[test].reset_index(drop=True))
            predictions[test] = fold_predictions
            seen[test] = True
            fold_records.append(
                {
                    "fold_id": fold.fold_id,
                    "train_n": len(train),
                    "test_n": len(test),
                    "rmse": float(np.sqrt(np.mean((fold_predictions - target[test]) ** 2))),
                    "train_x_mean": estimator.x_mean_,
                    "train_x_scale": estimator.x_scale_,
                    "vocabulary_sizes": {
                        column: len(values) for column, values in estimator.vocabularies_.items()
                    },
                }
            )
        if not seen.all():
            raise ModelInputError("inner folds do not cover every selection row exactly once")
        rmse = float(np.sqrt(np.mean((predictions - target) ** 2)))
        return {
            "status": "complete",
            "penalties": penalties.to_dict(),
            "rmse": rmse,
            "folds": fold_records,
        }
    except (RuntimeError, ValueError, np.linalg.LinAlgError) as exc:
        return {
            "status": "failed",
            "penalties": penalties.to_dict(),
            "error": f"{type(exc).__name__}: {exc}",
            "folds": fold_records,
        }


def _selection_key(record: dict[str, Any]) -> tuple[float, float, float, float]:
    penalties = record["penalties"]
    return (
        float(record["rmse"]),
        -float(penalties["lambda_axis_a"] + penalties["lambda_axis_b"]),
        float(penalties["lambda_axis_a"]),
        float(penalties["lambda_axis_b"]),
    )


def _nearest_three(values: list[float], center: float) -> list[float]:
    def distance(value: float) -> tuple[float, float]:
        if value == center:
            return (0.0, value)
        if value > 0.0 and center > 0.0:
            return (abs(math.log10(value) - math.log10(center)), value)
        return (abs(value - center), value)

    return sorted(sorted(values, key=distance)[:3])


def select_hierarchical_penalties(
    *,
    frame: pd.DataFrame,
    y: FloatArray | list[float],
    inner_folds: tuple[ValidationFold, ...],
    config: HierarchicalModelConfig,
) -> NestedSelectionResult:
    """Run shared coarse search then at-most-3x3 axis refinement."""

    target = finite_vector(y, name="inner target")
    if len(target) != len(frame):
        raise ModelInputError("inner target length does not match frame")
    if not inner_folds:
        raise ModelInputError("inner penalty selection requires folds")
    records: list[dict[str, Any]] = []
    evaluated: dict[tuple[float, float], dict[str, Any]] = {}

    def evaluate(penalties: PenaltySet, stage: str) -> dict[str, Any]:
        key = (penalties.lambda_axis_a, penalties.lambda_axis_b)
        existing = evaluated.get(key)
        if existing is None:
            existing = _evaluate_candidate(
                frame=frame,
                target=target,
                folds=inner_folds,
                penalties=penalties,
                config=config,
            )
            evaluated[key] = existing
        record = {**existing, "stage": stage}
        records.append(record)
        return record

    coarse_records = [
        evaluate(
            PenaltySet(lambda_skeleton=0.0, lambda_axis_a=value, lambda_axis_b=value),
            "shared_coarse",
        )
        for value in config.regularization.shared_family_coarse_grid
    ]
    successful_coarse = [record for record in coarse_records if record["status"] == "complete"]
    if not successful_coarse:
        raise ModelInputError("all shared-family coarse candidates failed")
    coarse_winner = min(successful_coarse, key=_selection_key)
    coarse_center = float(coarse_winner["penalties"]["lambda_axis_a"])
    axis_a_values = _nearest_three(config.regularization.lambda_axis_a_grid, coarse_center)
    axis_b_values = _nearest_three(config.regularization.lambda_axis_b_grid, coarse_center)
    refinement_records = [
        evaluate(
            PenaltySet(lambda_skeleton=0.0, lambda_axis_a=axis_a, lambda_axis_b=axis_b),
            "axis_refinement",
        )
        for axis_a in axis_a_values
        for axis_b in axis_b_values
    ]
    successful_refinement = [
        record for record in refinement_records if record["status"] == "complete"
    ]
    if not successful_refinement:
        raise ModelInputError("all axis-specific refinement candidates failed")
    winner = min(successful_refinement, key=_selection_key)
    selected = PenaltySet(
        lambda_skeleton=0.0,
        lambda_axis_a=float(winner["penalties"]["lambda_axis_a"]),
        lambda_axis_b=float(winner["penalties"]["lambda_axis_b"]),
    )
    return NestedSelectionResult(
        selected=selected,
        selected_rmse=float(winner["rmse"]),
        candidates=tuple(records),
    )
