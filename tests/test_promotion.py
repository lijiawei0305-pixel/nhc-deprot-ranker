"""Phase 4 paired uncertainty and promotion-rule tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from nhc_deprot_ranker.config import EvaluationConfig
from nhc_deprot_ranker.validation.promotion import (
    PROTOCOLS,
    audit_family_collapse,
    audit_family_stability,
    evaluate_promotion_gates,
    paired_oof_bootstrap,
    select_outcome,
)


def _config(*, repeats: int = 20) -> EvaluationConfig:
    return EvaluationConfig.model_validate(
        {
            "protocols": [
                "loocv",
                "leave_axis_a_out",
                "leave_axis_b_out",
                "combined_family_holdout_if_supported",
                "size_extrapolation",
            ],
            "ranking": {
                "lower_is_better": True,
                "true_top_m": [2, 4],
                "predicted_budget_k": [3, 6],
                "ndcg_k": [3, 6],
                "pairwise_tie_threshold_kcal": 0.1,
            },
            "bootstrap_ci": {"repeats": repeats, "confidence": 0.95, "seed": 17},
            "promotion": {
                "min_spearman_delta": -0.01,
                "min_kendall_delta": -0.02,
                "max_regret_increase_kcal": 1.0,
                "require_no_family_collapse": True,
                "primary_rank": {
                    "min_delta": 0.0,
                    "require_95_percent_lower_bound_nonnegative": True,
                },
                "family_collapse": {
                    "max_heldout_mae_increase_kcal": 3.0,
                    "max_heldout_mae_ratio": 2.0,
                    "catastrophic_requires_both": True,
                },
                "family_offset_stability": {
                    "minimum_support": 3,
                    "min_conditional_sign_stability": 0.6,
                },
                "head_recall": {
                    "min_delta": 0.0,
                    "require_95_percent_lower_bound_nonnegative": True,
                },
            },
            "blind_holdout": {"status": "missing", "reason": "synthetic"},
        }
    )


def _predictions() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    truth = np.asarray([2.0, 1.0, 4.0, 3.0, 8.0, 7.0, 6.0, 5.0, 12.0, 11.0, 10.0, 9.0])
    b0 = np.asarray([2.0, 1.0, 3.0, 4.0, 8.0, 6.0, 7.0, 5.0, 11.0, 12.0, 10.0, 9.0])
    b1 = np.asarray([2.1, 1.1, 3.1, 4.1, 8.1, 6.1, 7.1, 5.1, 11.1, 12.1, 10.1, 9.1])
    h1 = truth + 0.05
    for protocol in PROTOCOLS:
        for index in range(len(truth)):
            rows.append(
                {
                    "protocol": protocol,
                    "inchikey": f"KEY-{index:03d}",
                    "held_out_group": f"G-{index % 4}",
                    "true_dft_kcal": truth[index],
                    "b0_prediction_kcal": b0[index],
                    "b1_prediction_kcal": b1[index],
                    "h1_prediction_kcal": h1[index],
                }
            )
    return pd.DataFrame.from_records(rows)


def test_paired_oof_bootstrap_is_deterministic_and_aligned() -> None:
    predictions = _predictions()
    first = paired_oof_bootstrap(predictions, _config())
    second = paired_oof_bootstrap(predictions, _config())
    assert first.metadata == second.metadata
    assert first.summary.equals(second.summary)
    assert first.metadata["failed_repeats"] == 0
    assert set(first.metadata["successful_repeats_by_protocol"].values()) == {20}
    assert set(first.summary["comparison"]) == {
        "B1_minus_B0",
        "H1_minus_B0",
        "H1_minus_B1",
    }


def test_family_collapse_requires_absolute_and_ratio_failure() -> None:
    rows: list[dict[str, object]] = []
    for protocol in ("leave_axis_a_out", "leave_axis_b_out"):
        for group, b1, h1 in (
            ("both", 1.0, 5.0),
            ("absolute_only", 10.0, 14.0),
            ("ratio_only", 0.1, 0.3),
        ):
            rows.append(
                {
                    "protocol": protocol,
                    "held_out_group": group,
                    "true_dft_kcal": 0.0,
                    "b1_prediction_kcal": b1,
                    "h1_prediction_kcal": h1,
                }
            )
    audit = audit_family_collapse(pd.DataFrame.from_records(rows), _config())
    by_group = audit.groupby("held_out_group")["catastrophic"].all().to_dict()
    assert by_group == {"absolute_only": False, "both": True, "ratio_only": False}


def test_family_stability_is_conditional_and_support_filtered() -> None:
    effects = pd.DataFrame.from_records(
        [
            {
                "term": "axis_a_family",
                "level": "unstable_supported",
                "support": 3,
                "sign_stability": 0.50,
                "present_fraction": 0.90,
            },
            {
                "term": "axis_a_family",
                "level": "stable_supported",
                "support": 3,
                "sign_stability": 0.70,
                "present_fraction": 0.90,
            },
            {
                "term": "axis_b_family",
                "level": "rare",
                "support": 1,
                "sign_stability": 0.20,
                "present_fraction": 0.60,
            },
        ]
    )
    audit = audit_family_stability(effects, _config()).set_index("level")
    assert audit.loc["unstable_supported", "conditional_sign_stability"] == 0.50 / 0.90
    assert not bool(audit.loc["unstable_supported", "stable"])
    assert bool(audit.loc["stable_supported", "stable"])
    assert not bool(audit.loc["rare", "eligible"])
    assert bool(audit.loc["rare", "stable"])


def test_all_four_outcomes_are_explicitly_reachable() -> None:
    assert select_outcome(
        b1_passed=False, h1_passed=True, h1_beats_b0=True, evidence_complete=True
    ) == ("hierarchical_wins", "H1_hierarchical_linear")
    assert select_outcome(
        b1_passed=True, h1_passed=False, h1_beats_b0=False, evidence_complete=True
    ) == ("global_affine_wins", "B1_global_affine")
    assert select_outcome(
        b1_passed=False, h1_passed=False, h1_beats_b0=False, evidence_complete=True
    ) == ("raw_xTB_wins", "B0_raw_xTB")
    assert select_outcome(
        b1_passed=False, h1_passed=False, h1_beats_b0=False, evidence_complete=False
    ) == ("insufficient_evidence", "B0_raw_xTB_pending_more_evidence")


def _uncertainty_for_gate(*, recall_ci_low: float) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for comparison in ("B1_minus_B0", "H1_minus_B1", "H1_minus_B0"):
        for protocol in PROTOCOLS:
            for metric in ("spearman_rho", "kendall_tau"):
                rows.append(
                    {
                        "comparison": comparison,
                        "protocol": protocol,
                        "metric": metric,
                        "point_delta": 0.02,
                        "ci_low": 0.001,
                        "ci_high": 0.04,
                    }
                )
            rows.append(
                {
                    "comparison": comparison,
                    "protocol": protocol,
                    "metric": "recall_true_top_2_in_predicted_top_3",
                    "point_delta": 0.10 if comparison == "H1_minus_B1" else 0.0,
                    "ci_low": recall_ci_low if comparison == "H1_minus_B1" else 0.0,
                    "ci_high": 0.20,
                }
            )
            rows.append(
                {
                    "comparison": comparison,
                    "protocol": protocol,
                    "metric": "regret_at_3",
                    "point_delta": 0.0,
                    "ci_low": 0.0,
                    "ci_high": 0.0,
                }
            )
    return pd.DataFrame.from_records(rows)


def test_head_recall_interval_and_family_audits_block_h1() -> None:
    collapse = pd.DataFrame({"catastrophic": [False]})
    stability = pd.DataFrame(
        {"eligible": [True], "stable": [True], "conditional_sign_stability": [0.8]}
    )
    passed = evaluate_promotion_gates(
        uncertainty=_uncertainty_for_gate(recall_ci_low=0.0),
        family_collapse=collapse,
        family_stability=stability,
        config=_config(),
        fallback_exact_zero_and_finite=True,
        exact_combined_absent=True,
        artifacts_reproduced=True,
    )
    assert passed["outcome"] == "hierarchical_wins"
    failed = evaluate_promotion_gates(
        uncertainty=_uncertainty_for_gate(recall_ci_low=-0.01),
        family_collapse=collapse,
        family_stability=stability,
        config=_config(),
        fallback_exact_zero_and_finite=True,
        exact_combined_absent=True,
        artifacts_reproduced=True,
    )
    assert failed["H1_gate"]["checks"]["stable_head_recall_improvement"]["status"] == "failed"
    assert failed["outcome"] == "global_affine_wins"
