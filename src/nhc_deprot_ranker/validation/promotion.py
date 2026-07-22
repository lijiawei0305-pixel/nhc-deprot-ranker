"""Frozen-OOF bootstrap comparison and deterministic Phase 4 promotion gates."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from nhc_deprot_ranker.config import EvaluationConfig
from nhc_deprot_ranker.models.base import ModelInputError, validated_keys
from nhc_deprot_ranker.validation.metrics import evaluate_predictions

PROTOCOLS = ("loocv", "leave_axis_a_out", "leave_axis_b_out")
MODEL_COLUMNS = {
    "B0": "b0_prediction_kcal",
    "B1": "b1_prediction_kcal",
    "H1": "h1_prediction_kcal",
}
COMPARISONS = (
    ("B1_minus_B0", "B1", "B0"),
    ("H1_minus_B1", "H1", "B1"),
    ("H1_minus_B0", "H1", "B0"),
)
PRIMARY_METRICS = ("spearman_rho", "kendall_tau")


@dataclass(frozen=True)
class ComparisonBootstrapResult:
    """Paired OOF comparison summaries and replicate accounting."""

    summary: pd.DataFrame
    metadata: dict[str, Any]


def _is_reported_metric(name: str) -> bool:
    return name in {
        "mae_kcal",
        "rmse_kcal",
        "spearman_rho",
        "kendall_tau",
        "pairwise_accuracy",
    } or name.startswith(("recall_true_top_", "regret_at_", "ndcg_at_"))


def _metric_direction(name: str) -> str:
    if name in {"mae_kcal", "rmse_kcal"} or name.startswith("regret_at_"):
        return "lower_is_better"
    return "higher_is_better"


def _evaluate_models(frame: pd.DataFrame, config: EvaluationConfig) -> dict[str, dict[str, Any]]:
    keys = frame["inchikey"].astype(str).tolist()
    common: dict[str, Any] = {
        "true_values": frame["true_dft_kcal"].to_numpy(dtype=np.float64),
        "keys": keys,
        "true_top_m": config.ranking.true_top_m,
        "predicted_budget_k": config.ranking.predicted_budget_k,
        "ndcg_k": config.ranking.ndcg_k,
        "pairwise_tie_threshold_kcal": config.ranking.pairwise_tie_threshold_kcal,
        "lower_is_better": config.ranking.lower_is_better,
    }
    return {
        model: evaluate_predictions(
            predicted_values=frame[column].to_numpy(dtype=np.float64), **common
        )
        for model, column in MODEL_COLUMNS.items()
    }


def evaluate_frozen_oof(
    predictions: pd.DataFrame, config: EvaluationConfig
) -> dict[str, dict[str, Any]]:
    """Recompute B0/B1/H1 metrics on aligned immutable OOF rows."""

    required = {"protocol", "inchikey", "true_dft_kcal", *MODEL_COLUMNS.values()}
    missing = sorted(required - set(predictions.columns))
    if missing:
        raise ModelInputError(f"Phase 4 OOF frame is missing columns: {missing}")
    result: dict[str, dict[str, Any]] = {}
    for protocol in PROTOCOLS:
        subset = predictions.loc[predictions["protocol"].eq(protocol)].copy()
        subset = subset.sort_values("inchikey", kind="mergesort").reset_index(drop=True)
        if subset.empty:
            raise ModelInputError(f"Phase 4 OOF protocol is empty: {protocol}")
        validated_keys(subset["inchikey"].astype(str).tolist(), expected_size=len(subset))
        result[protocol] = _evaluate_models(subset, config)
    return result


def comparison_frame(model_metrics: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """Return candidate-minus-baseline point deltas for registered metrics."""

    rows: list[dict[str, Any]] = []
    for protocol in PROTOCOLS:
        models = model_metrics[protocol]
        for comparison, candidate, baseline in COMPARISONS:
            candidate_metrics = models[candidate]
            baseline_metrics = models[baseline]
            metric_names = sorted(
                name
                for name in candidate_metrics
                if _is_reported_metric(name) and name in baseline_metrics
            )
            for metric in metric_names:
                candidate_value = float(candidate_metrics[metric])
                baseline_value = float(baseline_metrics[metric])
                rows.append(
                    {
                        "protocol": protocol,
                        "comparison": comparison,
                        "candidate": candidate,
                        "baseline": baseline,
                        "metric": metric,
                        "direction": _metric_direction(metric),
                        "baseline_value": baseline_value,
                        "candidate_value": candidate_value,
                        "point_delta": candidate_value - baseline_value,
                    }
                )
    return (
        pd.DataFrame.from_records(rows)
        .sort_values(["protocol", "comparison", "metric"], kind="mergesort")
        .reset_index(drop=True)
    )


def _protocol_rng(seed: int, protocol: str) -> np.random.Generator:
    digest = hashlib.sha256(protocol.encode("utf-8")).digest()
    protocol_seed = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return np.random.default_rng(np.random.SeedSequence([seed, protocol_seed]))


def paired_oof_bootstrap(
    predictions: pd.DataFrame, config: EvaluationConfig
) -> ComparisonBootstrapResult:
    """Bootstrap fixed aligned OOF rows without refitting or retuning models."""

    point_metrics = evaluate_frozen_oof(predictions, config)
    points = comparison_frame(point_metrics)
    values: dict[tuple[str, str, str], list[float]] = {
        (str(row.protocol), str(row.comparison), str(row.metric)): []
        for row in points.itertuples(index=False)
    }
    failures: list[dict[str, Any]] = []
    successes: dict[str, int] = {}
    for protocol in PROTOCOLS:
        subset = predictions.loc[predictions["protocol"].eq(protocol)].copy()
        subset = subset.sort_values("inchikey", kind="mergesort").reset_index(drop=True)
        original_keys = validated_keys(
            subset["inchikey"].astype(str).tolist(), expected_size=len(subset)
        )
        generator = _protocol_rng(config.bootstrap_ci.seed, protocol)
        successful = 0
        for repeat in range(config.bootstrap_ci.repeats):
            indices = generator.integers(0, len(subset), size=len(subset))
            sampled = subset.iloc[indices].copy().reset_index(drop=True)
            sampled["inchikey"] = [
                f"{original_keys[index]}#r{repeat:04d}p{position:03d}"
                for position, index in enumerate(indices)
            ]
            try:
                replicate_metrics = _evaluate_models(sampled, config)
            except (RuntimeError, ValueError, np.linalg.LinAlgError) as exc:
                failures.append(
                    {
                        "protocol": protocol,
                        "repeat": repeat,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            successful += 1
            for comparison, candidate, baseline in COMPARISONS:
                for metric, candidate_value in replicate_metrics[candidate].items():
                    identity = (protocol, comparison, metric)
                    if identity not in values:
                        continue
                    values[identity].append(
                        float(candidate_value) - float(replicate_metrics[baseline][metric])
                    )
        successes[protocol] = successful
    alpha = (1.0 - config.bootstrap_ci.confidence) / 2.0
    rows: list[dict[str, Any]] = []
    for point in points.to_dict("records"):
        point_record = {str(key): value for key, value in point.items()}
        identity = (
            str(point_record["protocol"]),
            str(point_record["comparison"]),
            str(point_record["metric"]),
        )
        vector = np.asarray(values[identity], dtype=np.float64)
        if vector.size == 0:
            raise ModelInputError(f"all paired bootstrap replicates failed for {identity}")
        rows.append(
            {
                **point_record,
                "bootstrap_mean": float(np.mean(vector)),
                "bootstrap_std": float(np.std(vector, ddof=1)) if len(vector) > 1 else 0.0,
                "p025": float(np.quantile(vector, 0.025)),
                "p05": float(np.quantile(vector, 0.05)),
                "p50": float(np.quantile(vector, 0.5)),
                "p95": float(np.quantile(vector, 0.95)),
                "p975": float(np.quantile(vector, 0.975)),
                "ci_low": float(np.quantile(vector, alpha)),
                "ci_high": float(np.quantile(vector, 1.0 - alpha)),
                "probability_delta_positive": float(np.mean(vector > 0.0)),
                "probability_delta_nonnegative": float(np.mean(vector >= 0.0)),
                "probability_delta_nonpositive": float(np.mean(vector <= 0.0)),
                "successful_repeats": len(vector),
            }
        )
    summary = (
        pd.DataFrame.from_records(rows)
        .sort_values(["protocol", "comparison", "metric"], kind="mergesort")
        .reset_index(drop=True)
    )
    metadata = {
        "method": "paired_inchikey_bootstrap_of_frozen_oof_predictions",
        "models_refit": False,
        "penalties_retuned": False,
        "seed": config.bootstrap_ci.seed,
        "confidence": config.bootstrap_ci.confidence,
        "requested_repeats_per_protocol": config.bootstrap_ci.repeats,
        "successful_repeats_by_protocol": successes,
        "failed_repeats": len(failures),
        "failures": failures,
    }
    return ComparisonBootstrapResult(summary=summary, metadata=metadata)


def audit_family_collapse(predictions: pd.DataFrame, config: EvaluationConfig) -> pd.DataFrame:
    """Apply the confirmed absolute-and-ratio held-out-family collapse rule."""

    policy = config.promotion.family_collapse
    rows: list[dict[str, Any]] = []
    for protocol in ("leave_axis_a_out", "leave_axis_b_out"):
        subset = predictions.loc[predictions["protocol"].eq(protocol)]
        if subset.empty or subset["held_out_group"].isna().any():
            raise ModelInputError(f"held-out groups are unavailable for {protocol}")
        for group, family in subset.groupby("held_out_group", sort=True):
            truth = family["true_dft_kcal"].to_numpy(dtype=np.float64)
            b1_mae = float(
                np.mean(np.abs(family["b1_prediction_kcal"].to_numpy(dtype=np.float64) - truth))
            )
            h1_mae = float(
                np.mean(np.abs(family["h1_prediction_kcal"].to_numpy(dtype=np.float64) - truth))
            )
            increase = h1_mae - b1_mae
            ratio = h1_mae / b1_mae if b1_mae > 0.0 else math.inf
            absolute_failure = increase > policy.max_heldout_mae_increase_kcal
            ratio_failure = ratio > policy.max_heldout_mae_ratio
            rows.append(
                {
                    "protocol": protocol,
                    "held_out_group": str(group),
                    "n": len(family),
                    "B1_mae_kcal": b1_mae,
                    "H1_mae_kcal": h1_mae,
                    "mae_increase_kcal": increase,
                    "mae_ratio": ratio,
                    "absolute_failure": absolute_failure,
                    "ratio_failure": ratio_failure,
                    "catastrophic": absolute_failure and ratio_failure,
                }
            )
    return (
        pd.DataFrame.from_records(rows)
        .sort_values(["protocol", "held_out_group"], kind="mergesort")
        .reset_index(drop=True)
    )


def audit_family_stability(effects: pd.DataFrame, config: EvaluationConfig) -> pd.DataFrame:
    """Apply minimum-support conditional bootstrap sign stability."""

    required = {
        "term",
        "level",
        "support",
        "sign_stability",
        "present_fraction",
    }
    missing = sorted(required - set(effects.columns))
    if missing:
        raise ModelInputError(f"family bootstrap is missing columns: {missing}")
    policy = config.promotion.family_offset_stability
    frame = effects.loc[effects["term"].isin(("axis_a_family", "axis_b_family"))].copy()
    if frame.empty:
        raise ModelInputError("no active axis-family bootstrap effects are available")
    present = frame["present_fraction"].to_numpy(dtype=np.float64)
    sign = frame["sign_stability"].to_numpy(dtype=np.float64)
    if not np.isfinite(present).all() or not np.isfinite(sign).all() or np.any(present <= 0.0):
        raise ModelInputError("family bootstrap probabilities must be finite and positive")
    frame["conditional_sign_stability"] = sign / present
    frame["eligible"] = frame["support"].astype(int).ge(policy.minimum_support)
    frame["stable"] = (~frame["eligible"]) | frame["conditional_sign_stability"].ge(
        policy.min_conditional_sign_stability
    )
    return frame.sort_values(["term", "level"], kind="mergesort").reset_index(drop=True)


def _gate(passed: bool, *, actual: Any, threshold: Any) -> dict[str, Any]:
    return {
        "status": "passed" if passed else "failed",
        "actual": actual,
        "threshold": threshold,
    }


def _rows(
    uncertainty: pd.DataFrame,
    *,
    comparison: str,
    metrics: tuple[str, ...] | None = None,
    metric_prefix: str | None = None,
    protocols: tuple[str, ...] = PROTOCOLS,
) -> pd.DataFrame:
    frame = uncertainty.loc[
        uncertainty["comparison"].eq(comparison) & uncertainty["protocol"].isin(protocols)
    ]
    if metrics is not None:
        frame = frame.loc[frame["metric"].isin(metrics)]
    if metric_prefix is not None:
        frame = frame.loc[frame["metric"].str.startswith(metric_prefix)]
    return frame.copy()


def select_outcome(
    *, b1_passed: bool, h1_passed: bool, h1_beats_b0: bool, evidence_complete: bool
) -> tuple[str, str]:
    """Select one allowed outcome and its production ranking default."""

    if not evidence_complete:
        return "insufficient_evidence", "B0_raw_xTB_pending_more_evidence"
    if h1_passed and h1_beats_b0:
        return "hierarchical_wins", "H1_hierarchical_linear"
    if b1_passed:
        return "global_affine_wins", "B1_global_affine"
    return "raw_xTB_wins", "B0_raw_xTB"


def evaluate_promotion_gates(
    *,
    uncertainty: pd.DataFrame,
    family_collapse: pd.DataFrame,
    family_stability: pd.DataFrame,
    config: EvaluationConfig,
    fallback_exact_zero_and_finite: bool,
    exact_combined_absent: bool,
    artifacts_reproduced: bool,
) -> dict[str, Any]:
    """Evaluate all B1/H1 gates and produce the Phase 4 outcome."""

    promotion = config.promotion
    b1_primary = _rows(uncertainty, comparison="B1_minus_B0", metrics=PRIMARY_METRICS)
    b1_positive = b1_primary.loc[b1_primary["point_delta"].gt(promotion.primary_rank.min_delta)]
    b1_stable = b1_positive.loc[b1_positive["ci_low"].ge(0.0)]
    b1_spearman = _rows(uncertainty, comparison="B1_minus_B0", metrics=("spearman_rho",))
    b1_kendall = _rows(uncertainty, comparison="B1_minus_B0", metrics=("kendall_tau",))
    b1_regret = _rows(uncertainty, comparison="B1_minus_B0", metric_prefix="regret_at_")
    b1_gates = {
        "positive_primary_point_improvement": _gate(
            not b1_positive.empty,
            actual=len(b1_positive),
            threshold="at_least_one_protocol_metric_delta_gt_0",
        ),
        "stable_primary_improvement": _gate(
            not b1_stable.empty,
            actual=len(b1_stable),
            threshold="positive_point_and_95_percent_ci_low_ge_0",
        ),
        "spearman_noninferior_all_protocols": _gate(
            bool(b1_spearman["point_delta"].ge(promotion.min_spearman_delta).all()),
            actual=b1_spearman[["protocol", "point_delta"]].to_dict("records"),
            threshold=promotion.min_spearman_delta,
        ),
        "kendall_noninferior_all_protocols": _gate(
            bool(b1_kendall["point_delta"].ge(promotion.min_kendall_delta).all()),
            actual=b1_kendall[["protocol", "point_delta"]].to_dict("records"),
            threshold=promotion.min_kendall_delta,
        ),
        "regret_within_tolerance": _gate(
            bool(b1_regret["point_delta"].le(promotion.max_regret_increase_kcal).all()),
            actual=float(b1_regret["point_delta"].max()),
            threshold=promotion.max_regret_increase_kcal,
        ),
        "artifacts_reproduced": _gate(
            artifacts_reproduced, actual=artifacts_reproduced, threshold=True
        ),
    }
    b1_passed = all(gate["status"] == "passed" for gate in b1_gates.values())

    grouped_protocols = ("leave_axis_a_out", "leave_axis_b_out")
    h1_spearman = _rows(
        uncertainty,
        comparison="H1_minus_B1",
        metrics=("spearman_rho",),
        protocols=grouped_protocols,
    )
    h1_kendall = _rows(
        uncertainty,
        comparison="H1_minus_B1",
        metrics=("kendall_tau",),
        protocols=grouped_protocols,
    )
    h1_recall = _rows(uncertainty, comparison="H1_minus_B1", metric_prefix="recall_true_top_")
    positive_recall = h1_recall.loc[h1_recall["point_delta"].gt(promotion.head_recall.min_delta)]
    stable_recall = positive_recall.loc[positive_recall["ci_low"].ge(0.0)]
    h1_regret = _rows(uncertainty, comparison="H1_minus_B1", metric_prefix="regret_at_")
    eligible_stability = family_stability.loc[family_stability["eligible"]]
    collapse_passed = not bool(family_collapse["catastrophic"].any())
    stability_passed = bool(eligible_stability["stable"].all()) and not eligible_stability.empty
    h1_vs_b0 = _rows(uncertainty, comparison="H1_minus_B0", metrics=PRIMARY_METRICS)
    h1_vs_b0_stable = h1_vs_b0.loc[
        h1_vs_b0["point_delta"].gt(promotion.primary_rank.min_delta) & h1_vs_b0["ci_low"].ge(0.0)
    ]
    h1_beats_b0 = not h1_vs_b0_stable.empty
    h1_gates = {
        "grouped_spearman_noninferior": _gate(
            bool(h1_spearman["point_delta"].ge(promotion.min_spearman_delta).all()),
            actual=h1_spearman[["protocol", "point_delta"]].to_dict("records"),
            threshold=promotion.min_spearman_delta,
        ),
        "grouped_kendall_noninferior": _gate(
            bool(h1_kendall["point_delta"].ge(promotion.min_kendall_delta).all()),
            actual=h1_kendall[["protocol", "point_delta"]].to_dict("records"),
            threshold=promotion.min_kendall_delta,
        ),
        "stable_head_recall_improvement": _gate(
            not stable_recall.empty,
            actual=stable_recall[
                ["protocol", "metric", "point_delta", "ci_low", "ci_high"]
            ].to_dict("records"),
            threshold="point_delta_gt_0_and_95_percent_ci_low_ge_0",
        ),
        "regret_within_tolerance": _gate(
            bool(h1_regret["point_delta"].le(promotion.max_regret_increase_kcal).all()),
            actual=float(h1_regret["point_delta"].max()),
            threshold=promotion.max_regret_increase_kcal,
        ),
        "unknown_family_fallback": _gate(
            fallback_exact_zero_and_finite,
            actual=fallback_exact_zero_and_finite,
            threshold="exact_zero_effect_and_finite_prediction",
        ),
        "no_catastrophic_family_error": _gate(
            collapse_passed,
            actual=int(family_collapse["catastrophic"].sum()),
            threshold={
                "mae_increase_kcal_gt": promotion.family_collapse.max_heldout_mae_increase_kcal,
                "mae_ratio_gt": promotion.family_collapse.max_heldout_mae_ratio,
                "requires_both": True,
            },
        ),
        "supported_family_offsets_stable": _gate(
            stability_passed,
            actual={
                "eligible": len(eligible_stability),
                "unstable": int((~eligible_stability["stable"]).sum()),
                "minimum_conditional_sign_stability": float(
                    eligible_stability["conditional_sign_stability"].min()
                )
                if not eligible_stability.empty
                else None,
            },
            threshold={
                "minimum_support": promotion.family_offset_stability.minimum_support,
                "min_conditional_sign_stability": (
                    promotion.family_offset_stability.min_conditional_sign_stability
                ),
            },
        ),
        "exact_combined_effect_absent": _gate(
            exact_combined_absent, actual=exact_combined_absent, threshold=True
        ),
        "blind_holdout": {
            "status": "not_applicable_missing",
            "actual": config.blind_holdout.status,
            "threshold": "evaluate_if_genuine_unused_holdout_exists",
        },
        "size_extrapolation": {
            "status": "not_applicable_missing",
            "actual": "unavailable_missing_validated_size",
            "threshold": "evaluate_if_validated_size_exists",
        },
        "artifacts_reproduced": _gate(
            artifacts_reproduced, actual=artifacts_reproduced, threshold=True
        ),
        "honest_primary_improvement_over_B0": _gate(
            h1_beats_b0,
            actual=h1_vs_b0_stable[
                ["protocol", "metric", "point_delta", "ci_low", "ci_high"]
            ].to_dict("records"),
            threshold="positive_point_and_95_percent_ci_low_ge_0",
        ),
    }
    required_h1 = [
        gate for gate in h1_gates.values() if gate["status"] not in {"not_applicable_missing"}
    ]
    h1_passed = all(gate["status"] == "passed" for gate in required_h1)
    evidence_complete = artifacts_reproduced
    outcome, production_default = select_outcome(
        b1_passed=b1_passed,
        h1_passed=h1_passed,
        h1_beats_b0=h1_beats_b0,
        evidence_complete=evidence_complete,
    )
    return {
        "outcome": outcome,
        "production_default": production_default,
        "absolute_calibration_model": "B1_global_affine",
        "B1_gate": {"status": "passed" if b1_passed else "failed", "checks": b1_gates},
        "H1_gate": {"status": "passed" if h1_passed else "failed", "checks": h1_gates},
        "evidence_complete": evidence_complete,
        "phase5_authorized": False,
    }
