"""Lower-is-better ranking metric tests."""

import numpy as np
import pytest

from nhc_deprot_ranker.validation.metrics import evaluate_predictions
from nhc_deprot_ranker.validation.ranking import (
    deterministic_ranks,
    pairwise_accuracy,
    top_selection_metrics,
)


def _metrics(predicted: list[float]) -> dict[str, object]:
    return evaluate_predictions(
        true_values=[1, 2, 3, 4, 5, 6],
        predicted_values=predicted,
        keys=["A", "B", "C", "D", "E", "F"],
        true_top_m=[2],
        predicted_budget_k=[2, 3],
        ndcg_k=[3],
        pairwise_tie_threshold_kcal=0.0,
        lower_is_better=True,
    )


def test_perfect_ranking_metrics_equal_one_and_regret_zero() -> None:
    metrics = _metrics([1, 2, 3, 4, 5, 6])
    assert metrics["spearman_rho"] == pytest.approx(1.0)
    assert metrics["kendall_tau"] == pytest.approx(1.0)
    assert metrics["pairwise_accuracy"] == pytest.approx(1.0)
    assert metrics["ndcg_at_3"] == pytest.approx(1.0)
    assert metrics["regret_at_2"] == pytest.approx(0.0)


def test_reversed_ranking_has_negative_one_kendall() -> None:
    metrics = _metrics([6, 5, 4, 3, 2, 1])
    assert metrics["kendall_tau"] == pytest.approx(-1.0)
    assert float(metrics["ndcg_at_3"]) < 1.0
    assert metrics["regret_at_2"] == pytest.approx(4.0)


def test_top_m_and_budget_k_are_distinct() -> None:
    metrics = top_selection_metrics(
        true_values=[1, 2, 3, 4, 5, 6],
        predicted_values=[1, 5, 2, 3, 4, 6],
        keys=["A", "B", "C", "D", "E", "F"],
        true_top_m=[2],
        predicted_budget_k=[3],
        lower_is_better=True,
    )
    assert metrics["recall_true_top_2_in_predicted_top_3"] == pytest.approx(0.5)
    assert metrics["precision_true_top_2_in_predicted_top_3"] == pytest.approx(1 / 3)
    assert metrics["enrichment_true_top_2_in_predicted_top_3"] == pytest.approx(1.0)


def test_pairwise_tie_threshold_excludes_close_true_pairs() -> None:
    accuracy, eligible = pairwise_accuracy(
        [1.0, 1.5, 4.0],
        [2.0, 1.0, 4.0],
        tie_threshold=1.0,
    )
    assert eligible == 2
    assert accuracy == pytest.approx(1.0)


def test_deterministic_ties_use_key_order() -> None:
    ranks = deterministic_ranks(
        np.asarray([1.0, 1.0, 2.0]),
        ["B", "A", "C"],
        lower_is_better=True,
    )
    assert ranks.tolist() == [2.0, 1.0, 3.0]


def test_wrong_direction_is_rejected() -> None:
    with pytest.raises(ValueError, match="lower_is_better"):
        deterministic_ranks([1.0, 2.0], ["A", "B"], lower_is_better=False)
