"""Deterministic lower-is-better ranking and selection metrics."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from nhc_deprot_ranker.models.base import FloatArray, ModelInputError, finite_vector, validated_keys


def deterministic_ranks(
    values: Sequence[float] | FloatArray,
    keys: Sequence[str],
    *,
    lower_is_better: bool,
) -> FloatArray:
    """Return one-based ranks with InChIKey as a deterministic tie breaker."""

    if not lower_is_better:
        raise ValueError("Phase 2 supports only lower_is_better=true")
    vector = finite_vector(values, name="rank values")
    normalized_keys = validated_keys(keys, expected_size=len(vector))
    key_array = np.asarray(normalized_keys, dtype=np.str_)
    order = np.lexsort((key_array, vector))
    ranks = np.empty(len(vector), dtype=np.float64)
    ranks[order] = np.arange(1, len(vector) + 1, dtype=np.float64)
    return ranks


def top_indices(
    values: Sequence[float] | FloatArray,
    keys: Sequence[str],
    k: int,
    *,
    lower_is_better: bool,
) -> np.ndarray:
    """Return deterministic indices for the best K rows."""

    vector = finite_vector(values, name="top-k values")
    normalized_keys = validated_keys(keys, expected_size=len(vector))
    if not 1 <= k <= len(vector):
        raise ValueError(f"k must be between 1 and {len(vector)}")
    if not lower_is_better:
        raise ValueError("Phase 2 supports only lower_is_better=true")
    return np.lexsort((np.asarray(normalized_keys, dtype=np.str_), vector))[:k]


def pairwise_accuracy(
    true_values: Sequence[float] | FloatArray,
    predicted_values: Sequence[float] | FloatArray,
    *,
    tie_threshold: float,
) -> tuple[float, int]:
    """Return ordering accuracy after excluding close true-energy pairs."""

    if tie_threshold < 0.0:
        raise ValueError("tie_threshold must be non-negative")
    truth = finite_vector(true_values, name="true values")
    predicted = finite_vector(predicted_values, name="predicted values")
    if len(truth) != len(predicted):
        raise ModelInputError("true and predicted values must have equal length")
    left, right = np.triu_indices(len(truth), k=1)
    true_difference = truth[left] - truth[right]
    predicted_difference = predicted[left] - predicted[right]
    eligible = np.abs(true_difference) > tie_threshold
    eligible_pairs = int(np.sum(eligible))
    if eligible_pairs == 0:
        raise ValueError("no eligible pairs remain after tie filtering")
    correct = (true_difference[eligible] * predicted_difference[eligible]) > 0.0
    return float(np.mean(correct)), eligible_pairs


def top_selection_metrics(
    *,
    true_values: Sequence[float] | FloatArray,
    predicted_values: Sequence[float] | FloatArray,
    keys: Sequence[str],
    true_top_m: Sequence[int],
    predicted_budget_k: Sequence[int],
    lower_is_better: bool,
) -> dict[str, float]:
    """Return recall, precision, enrichment, and regret across M/K grids."""

    truth = finite_vector(true_values, name="true values")
    predicted = finite_vector(predicted_values, name="predicted values")
    normalized_keys = validated_keys(keys, expected_size=len(truth))
    if len(predicted) != len(truth):
        raise ModelInputError("true and predicted values must have equal length")
    metrics: dict[str, float] = {}
    for m in true_top_m:
        true_set = set(top_indices(truth, normalized_keys, m, lower_is_better=lower_is_better))
        for k in predicted_budget_k:
            predicted_indices = top_indices(
                predicted, normalized_keys, k, lower_is_better=lower_is_better
            )
            predicted_set = set(predicted_indices)
            overlap = len(true_set & predicted_set)
            prefix = f"true_top_{m}_in_predicted_top_{k}"
            precision = overlap / k
            metrics[f"recall_{prefix}"] = overlap / m
            metrics[f"precision_{prefix}"] = precision
            metrics[f"enrichment_{prefix}"] = precision / (m / len(truth))
    global_best = float(np.min(truth))
    for k in predicted_budget_k:
        predicted_indices = top_indices(
            predicted, normalized_keys, k, lower_is_better=lower_is_better
        )
        metrics[f"regret_at_{k}"] = float(np.min(truth[predicted_indices]) - global_best)
    return metrics


def ndcg_at_k(
    *,
    true_values: Sequence[float] | FloatArray,
    predicted_values: Sequence[float] | FloatArray,
    keys: Sequence[str],
    k: int,
    lower_is_better: bool,
) -> float:
    """Return rank-relevance NDCG@K with linear gain."""

    truth = finite_vector(true_values, name="true values")
    predicted = finite_vector(predicted_values, name="predicted values")
    normalized_keys = validated_keys(keys, expected_size=len(truth))
    if len(predicted) != len(truth):
        raise ModelInputError("true and predicted values must have equal length")
    predicted_order = top_indices(predicted, normalized_keys, k, lower_is_better=lower_is_better)
    ideal_order = top_indices(truth, normalized_keys, k, lower_is_better=lower_is_better)
    true_ranks = deterministic_ranks(truth, normalized_keys, lower_is_better=lower_is_better)
    relevance = len(truth) + 1.0 - true_ranks
    discounts = np.log2(np.arange(2, k + 2, dtype=np.float64))
    dcg = float(np.sum(relevance[predicted_order] / discounts))
    ideal_dcg = float(np.sum(relevance[ideal_order] / discounts))
    if ideal_dcg <= 0.0:
        raise ValueError("ideal DCG must be positive")
    return dcg / ideal_dcg
