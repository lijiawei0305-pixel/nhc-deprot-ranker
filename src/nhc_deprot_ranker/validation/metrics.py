"""Absolute and lower-is-better ranking metrics for honest predictions."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from scipy.stats import kendalltau, spearmanr  # type: ignore[import-untyped]

from nhc_deprot_ranker.models.base import FloatArray, ModelInputError, finite_vector, validated_keys
from nhc_deprot_ranker.validation.ranking import (
    deterministic_ranks,
    ndcg_at_k,
    pairwise_accuracy,
    top_selection_metrics,
)


def evaluate_predictions(
    *,
    true_values: Sequence[float] | FloatArray,
    predicted_values: Sequence[float] | FloatArray,
    keys: Sequence[str],
    true_top_m: Sequence[int],
    predicted_budget_k: Sequence[int],
    ndcg_k: Sequence[int],
    pairwise_tie_threshold_kcal: float,
    lower_is_better: bool,
) -> dict[str, Any]:
    """Evaluate finite predictions under one pre-specified protocol."""

    truth = finite_vector(true_values, name="true values")
    predicted = finite_vector(predicted_values, name="predicted values")
    normalized_keys = validated_keys(keys, expected_size=len(truth))
    if len(predicted) != len(truth):
        raise ModelInputError("true and predicted values must have equal length")
    true_ranks = deterministic_ranks(truth, normalized_keys, lower_is_better=lower_is_better)
    predicted_ranks = deterministic_ranks(
        predicted, normalized_keys, lower_is_better=lower_is_better
    )
    spearman = float(spearmanr(true_ranks, predicted_ranks).statistic)
    kendall = float(kendalltau(true_ranks, predicted_ranks).statistic)
    if not np.isfinite(spearman) or not np.isfinite(kendall):
        raise ModelInputError("rank correlation is non-finite")
    errors = predicted - truth
    pairwise, eligible_pairs = pairwise_accuracy(
        truth,
        predicted,
        tie_threshold=pairwise_tie_threshold_kcal,
    )
    total_sum_squares = float(np.sum((truth - np.mean(truth)) ** 2))
    r2 = 1.0 - float(np.sum(errors**2)) / total_sum_squares
    result: dict[str, Any] = {
        "n": len(truth),
        "mae_kcal": float(np.mean(np.abs(errors))),
        "rmse_kcal": float(np.sqrt(np.mean(errors**2))),
        "r2": r2,
        "spearman_rho": spearman,
        "kendall_tau": kendall,
        "pairwise_accuracy": pairwise,
        "pairwise_eligible_pairs": eligible_pairs,
        "pairwise_tie_threshold_kcal": pairwise_tie_threshold_kcal,
        "lower_is_better": lower_is_better,
    }
    result.update(
        top_selection_metrics(
            true_values=truth,
            predicted_values=predicted,
            keys=normalized_keys,
            true_top_m=true_top_m,
            predicted_budget_k=predicted_budget_k,
            lower_is_better=lower_is_better,
        )
    )
    for k in ndcg_k:
        result[f"ndcg_at_{k}"] = ndcg_at_k(
            true_values=truth,
            predicted_values=predicted,
            keys=normalized_keys,
            k=k,
            lower_is_better=lower_is_better,
        )
    if any(not isinstance(value, bool | int | float | str) for value in result.values()):
        raise ModelInputError("metric output contains unsupported values")
    if any(isinstance(value, float) and not np.isfinite(value) for value in result.values()):
        raise ModelInputError("metric output contains non-finite values")
    return result
