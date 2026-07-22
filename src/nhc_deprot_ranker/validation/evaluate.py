"""Atomic Phase 4 decision runner over frozen Phase 2/3 evidence."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from nhc_deprot_ranker.config import EvaluationConfig, load_evaluation_config
from nhc_deprot_ranker.data.provenance import sha256_file, sha256_source_tree
from nhc_deprot_ranker.models.base import key_set_sha256, validated_keys
from nhc_deprot_ranker.reporting.decision_plots import generate_decision_figures
from nhc_deprot_ranker.validation.promotion import (
    PROTOCOLS,
    audit_family_collapse,
    audit_family_stability,
    comparison_frame,
    evaluate_frozen_oof,
    evaluate_promotion_gates,
    paired_oof_bootstrap,
)


class DecisionEvaluationError(ValueError):
    """Phase 4 frozen-evidence or immutable-output contract failed."""


@dataclass(frozen=True)
class DecisionEvaluationResult:
    """CLI-facing Phase 4 result."""

    payload: dict[str, Any]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise DecisionEvaluationError(f"JSON root must be an object: {path.name}")
    return raw


def _verify_evidence(
    root: Path, evidence_path: Path, expected_version: str
) -> tuple[dict[str, str], dict[str, Any]]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    evidence = _read_json(evidence_path)
    if evidence.get("dataset_version") != expected_version:
        raise DecisionEvaluationError(
            f"evidence version mismatch for {root.name}: {evidence.get('dataset_version')}"
        )
    hashes = evidence.get("output_sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise DecisionEvaluationError(f"evidence has no output hashes: {evidence_path.name}")
    verified: dict[str, str] = {}
    for name, expected in hashes.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise DecisionEvaluationError("invalid evidence hash entry")
        actual = sha256_file(root / name)
        if actual != expected:
            raise DecisionEvaluationError(
                f"input hash mismatch for {root.name}/{name}: {actual} != {expected}"
            )
        verified[name] = actual
    expected_manifest_hash = evidence.get("model_manifest_sha256")
    if expected_manifest_hash is not None:
        if not isinstance(expected_manifest_hash, str):
            raise DecisionEvaluationError("model_manifest_sha256 must be a string")
        actual_manifest_hash = sha256_file(root / "model_manifest.json")
        if actual_manifest_hash != expected_manifest_hash:
            raise DecisionEvaluationError("hierarchical model manifest hash mismatch")
        verified["model_manifest.json"] = actual_manifest_hash
    return verified, evidence


def _verify_result_identity(
    *,
    baseline_results_dir: Path,
    hierarchical_results_dir: Path,
    baseline_evidence: dict[str, Any],
    hierarchical_evidence: dict[str, Any],
) -> str:
    baseline_manifest = _read_json(baseline_results_dir / "model_manifest.json")
    hierarchical_manifest = _read_json(hierarchical_results_dir / "model_manifest.json")
    training_hashes = {
        str(baseline_manifest.get("training_key_sha256")),
        str(hierarchical_manifest.get("training_key_sha256")),
        str(baseline_evidence.get("model", {}).get("training_key_sha256")),
        str(hierarchical_evidence.get("model", {}).get("training_key_sha256")),
    }
    if len(training_hashes) != 1 or "None" in training_hashes:
        raise DecisionEvaluationError("Phase 2/3 training-key identities disagree")
    if hierarchical_manifest.get("source_tree_sha256") != hierarchical_evidence.get(
        "source_tree_sha256"
    ):
        raise DecisionEvaluationError("Phase 3 source-tree identity disagrees with evidence")
    for root, gate_name in (
        (baseline_results_dir, "phase2_gate.json"),
        (hierarchical_results_dir, "phase3_gate.json"),
    ):
        if _read_json(root / gate_name).get("status") != "passed":
            raise DecisionEvaluationError(f"upstream gate is not passed: {gate_name}")
        if _read_json(root / "_SUCCESS").get("status") != "passed":
            raise DecisionEvaluationError(f"upstream completion is not passed: {root.name}")
    return training_hashes.pop()


def _aligned_predictions(
    baseline_results_dir: Path, hierarchical_results_dir: Path, training_hash: str
) -> pd.DataFrame:
    baseline = pd.read_csv(baseline_results_dir / "oof_predictions.csv")
    hierarchical = pd.read_csv(hierarchical_results_dir / "oof_predictions.csv")
    reference_columns = [
        "protocol",
        "inchikey",
        "fold_id",
        "held_out_group",
        "true_dft_kcal",
        "b0_prediction_kcal",
        "b1_prediction_kcal",
    ]
    missing_baseline = sorted(set(reference_columns) - set(baseline.columns))
    missing_hierarchical = sorted(
        set([*reference_columns, "h1_prediction_kcal"]) - set(hierarchical.columns)
    )
    if missing_baseline or missing_hierarchical:
        raise DecisionEvaluationError(
            f"OOF columns missing; baseline={missing_baseline}, H1={missing_hierarchical}"
        )
    reference = baseline.loc[:, reference_columns].copy()
    candidate = hierarchical.copy()
    merged = candidate.merge(
        reference,
        on=["protocol", "inchikey"],
        how="inner",
        validate="one_to_one",
        suffixes=("_h1", "_baseline"),
    )
    if len(merged) != len(candidate) or len(merged) != len(reference):
        raise DecisionEvaluationError("Phase 2/3 OOF rows do not align one-to-one")
    for column in ("true_dft_kcal", "b0_prediction_kcal", "b1_prediction_kcal"):
        if not np.array_equal(
            merged[f"{column}_h1"].to_numpy(dtype=np.float64),
            merged[f"{column}_baseline"].to_numpy(dtype=np.float64),
        ):
            raise DecisionEvaluationError(f"Phase 2/3 OOF values disagree: {column}")
        merged[column] = merged[f"{column}_h1"]
    for column in ("fold_id", "held_out_group"):
        left = merged[f"{column}_h1"].fillna("").astype(str)
        right = merged[f"{column}_baseline"].fillna("").astype(str)
        if not left.equals(right):
            raise DecisionEvaluationError(f"Phase 2/3 OOF split identities disagree: {column}")
        merged[column] = merged[f"{column}_h1"]
    keep = [
        "protocol",
        "fold_id",
        "held_out_group",
        "inchikey",
        "true_dft_kcal",
        "b0_prediction_kcal",
        "b1_prediction_kcal",
        "h1_prediction_kcal",
        "axis_a_effect",
        "axis_b_effect",
        "axis_a_family_known",
        "axis_b_family_known",
    ]
    aligned = merged.loc[:, keep].sort_values(["protocol", "inchikey"]).reset_index(drop=True)
    for protocol in PROTOCOLS:
        subset = aligned.loc[aligned["protocol"].eq(protocol)]
        keys = validated_keys(subset["inchikey"].astype(str).tolist(), expected_size=len(subset))
        if len(subset) != 71 or key_set_sha256(keys) != training_hash:
            raise DecisionEvaluationError(f"Phase 4 OOF coverage/identity failed: {protocol}")
    if len(aligned) != 213:
        raise DecisionEvaluationError("Phase 4 requires exactly 213 aligned OOF rows")
    return aligned


def _fallback_check(predictions: pd.DataFrame) -> bool:
    numeric = predictions[
        ["true_dft_kcal", "b0_prediction_kcal", "b1_prediction_kcal", "h1_prediction_kcal"]
    ].to_numpy(dtype=np.float64)
    axis_a = predictions.loc[predictions["protocol"].eq("leave_axis_a_out")]
    axis_b = predictions.loc[predictions["protocol"].eq("leave_axis_b_out")]
    return bool(
        np.isfinite(numeric).all()
        and np.array_equal(axis_a["axis_a_effect"].to_numpy(dtype=np.float64), np.zeros(71))
        and np.array_equal(axis_b["axis_b_effect"].to_numpy(dtype=np.float64), np.zeros(71))
        and not axis_a["axis_a_family_known"].astype(bool).any()
        and not axis_b["axis_b_family_known"].astype(bool).any()
    )


def _input_manifest(
    *,
    dataset_version: str,
    dataset_hashes: dict[str, str],
    baseline_hashes: dict[str, str],
    hierarchical_hashes: dict[str, str],
    dataset_evidence_path: Path,
    baseline_evidence_path: Path,
    hierarchical_evidence_path: Path,
    evaluation_config_path: Path,
    training_hash: str,
) -> dict[str, Any]:
    return {
        "dataset_version": dataset_version,
        "training_rows": 71,
        "training_key_sha256": training_hash,
        "input_sha256": {
            **{f"dataset/{name}": digest for name, digest in dataset_hashes.items()},
            **{f"baselines/{name}": digest for name, digest in baseline_hashes.items()},
            **{f"hierarchical/{name}": digest for name, digest in hierarchical_hashes.items()},
            "dataset_evidence": sha256_file(dataset_evidence_path),
            "baseline_evidence": sha256_file(baseline_evidence_path),
            "hierarchical_evidence": sha256_file(hierarchical_evidence_path),
            "evaluation_config": sha256_file(evaluation_config_path),
        },
    }


def evaluate_decision(
    *,
    dataset_dir: Path,
    baseline_results_dir: Path,
    hierarchical_results_dir: Path,
    evaluation_config_path: Path,
    dataset_evidence_path: Path,
    baseline_evidence_path: Path,
    hierarchical_evidence_path: Path,
    output_dir: Path,
    seed: int,
    dry_run: bool = False,
    overwrite: bool = False,
) -> DecisionEvaluationResult:
    """Evaluate immutable B0/B1/H1 evidence and publish one Phase 4 decision."""

    config: EvaluationConfig = load_evaluation_config(evaluation_config_path)
    dataset_version = dataset_dir.name
    expected_output_name = f"decision_{dataset_version}"
    if baseline_results_dir.name != f"baselines_{dataset_version}":
        raise DecisionEvaluationError("baseline result version does not match dataset")
    if hierarchical_results_dir.name != f"hierarchical_{dataset_version}":
        raise DecisionEvaluationError("hierarchical result version does not match dataset")
    if output_dir.name != expected_output_name:
        raise DecisionEvaluationError(
            f"output directory name {output_dir.name!r} must equal {expected_output_name!r}"
        )
    if output_dir.exists():
        raise DecisionEvaluationError(f"immutable decision result already exists: {output_dir}")
    if overwrite:
        raise DecisionEvaluationError("--overwrite cannot replace an immutable decision result")
    if seed != config.bootstrap_ci.seed:
        raise DecisionEvaluationError(
            "CLI seed must equal the registered evaluation bootstrap seed"
        )
    plan = {
        "command": "evaluate",
        "decision_version": dataset_version,
        "dataset_version": dataset_version,
        "output_dir": str(output_dir),
        "dry_run": dry_run,
        "frozen_models": ["B0_raw_xTB", "B1_global_affine", "H1_hierarchical_linear"],
        "models_refit": False,
        "penalties_retuned": False,
        "full_pool_scoring": False,
        "phase5_authorized": False,
        "hpc_connection": False,
        "quantum_chemistry": False,
    }
    if dry_run:
        return DecisionEvaluationResult(payload=plan)

    dataset_hashes, _dataset_evidence = _verify_evidence(
        dataset_dir, dataset_evidence_path, dataset_version
    )
    baseline_hashes, baseline_evidence = _verify_evidence(
        baseline_results_dir, baseline_evidence_path, dataset_version
    )
    hierarchical_hashes, hierarchical_evidence = _verify_evidence(
        hierarchical_results_dir, hierarchical_evidence_path, dataset_version
    )
    training_hash = _verify_result_identity(
        baseline_results_dir=baseline_results_dir,
        hierarchical_results_dir=hierarchical_results_dir,
        baseline_evidence=baseline_evidence,
        hierarchical_evidence=hierarchical_evidence,
    )
    predictions = _aligned_predictions(
        baseline_results_dir, hierarchical_results_dir, training_hash
    )
    model_metrics = evaluate_frozen_oof(predictions, config)
    points = comparison_frame(model_metrics)
    bootstrap = paired_oof_bootstrap(predictions, config)
    collapse = audit_family_collapse(predictions, config)
    bootstrap_effects = pd.read_parquet(
        hierarchical_results_dir / "bootstrap_family_effects.parquet"
    )
    stability = audit_family_stability(bootstrap_effects, config)
    family_effects = pd.read_csv(hierarchical_results_dir / "family_effects.csv")
    exact_combined_absent = (
        not family_effects["term"].astype(str).str.contains("combined", case=False).any()
    )
    fallback_passed = _fallback_check(predictions)
    decision = evaluate_promotion_gates(
        uncertainty=bootstrap.summary,
        family_collapse=collapse,
        family_stability=stability,
        config=config,
        fallback_exact_zero_and_finite=fallback_passed,
        exact_combined_absent=exact_combined_absent,
        artifacts_reproduced=True,
    )
    decision.update(
        {
            "decision_version": dataset_version,
            "dataset_version": dataset_version,
            "lower_is_better": True,
            "bootstrap": bootstrap.metadata,
            "policy_source": "configs/evaluation.yaml",
            "blind_holdout": {
                "status": "blind_test_missing",
                "reason": config.blind_holdout.reason,
            },
            "size_extrapolation": {"status": "unavailable_missing_validated_size"},
        }
    )
    comparison_payload = {
        "dataset_version": dataset_version,
        "models": model_metrics,
        "point_comparisons": points.to_dict("records"),
    }
    input_manifest = _input_manifest(
        dataset_version=dataset_version,
        dataset_hashes=dataset_hashes,
        baseline_hashes=baseline_hashes,
        hierarchical_hashes=hierarchical_hashes,
        dataset_evidence_path=dataset_evidence_path,
        baseline_evidence_path=baseline_evidence_path,
        hierarchical_evidence_path=hierarchical_evidence_path,
        evaluation_config_path=evaluation_config_path,
        training_hash=training_hash,
    )

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(
        tempfile.mkdtemp(prefix=f".{expected_output_name}.tmp.", dir=output_dir.parent)
    )
    try:
        _write_json(temporary_dir / "promotion_decision.json", decision)
        _write_json(temporary_dir / "model_comparison.json", comparison_payload)
        bootstrap.summary.to_parquet(
            temporary_dir / "metric_uncertainty.parquet", index=False, compression="zstd"
        )
        collapse.to_csv(temporary_dir / "family_collapse_audit.csv", index=False)
        stability.to_csv(temporary_dir / "family_stability_audit.csv", index=False)
        _write_json(temporary_dir / "input_manifest.json", input_manifest)
        gate_checks = {
            "upstream_hashes_verified": True,
            "aligned_oof_rows": len(predictions) == 213,
            "bootstrap_attempts_complete": all(
                value == config.bootstrap_ci.repeats
                for value in bootstrap.metadata["successful_repeats_by_protocol"].values()
            )
            and bootstrap.metadata["failed_repeats"] == 0,
            "outcome_allowed": decision["outcome"]
            in {
                "raw_xTB_wins",
                "global_affine_wins",
                "hierarchical_wins",
                "insufficient_evidence",
            },
            "no_refit_or_retune": True,
            "phase5_not_authorized": decision["phase5_authorized"] is False,
        }
        phase4_gate = {
            "status": "passed" if all(gate_checks.values()) else "failed",
            "checks": gate_checks,
            "outcome": decision["outcome"],
            "production_default": decision["production_default"],
        }
        _write_json(temporary_dir / "phase4_gate.json", phase4_gate)
        generate_decision_figures(
            uncertainty=bootstrap.summary,
            family_collapse=collapse,
            family_stability=stability,
            output_dir=temporary_dir / "figures",
            min_sign_stability=config.promotion.family_offset_stability.min_conditional_sign_stability,
            n=71,
            dataset_version=dataset_version,
            decision_version=dataset_version,
        )
        output_hashes = {
            path.relative_to(temporary_dir).as_posix(): sha256_file(path)
            for path in sorted(temporary_dir.rglob("*"))
            if path.is_file()
        }
        decision_manifest = {
            **input_manifest,
            "decision_version": dataset_version,
            "source_tree_sha256": sha256_source_tree(Path(__file__).parents[1]),
            "output_sha256": output_hashes,
            "outcome": decision["outcome"],
            "production_default": decision["production_default"],
        }
        _write_json(temporary_dir / "decision_manifest.json", decision_manifest)
        completion = {
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "dataset_version": dataset_version,
            "decision_version": dataset_version,
            "status": phase4_gate["status"],
            "outcome": decision["outcome"],
            "production_default": decision["production_default"],
            "decision_manifest_sha256": sha256_file(temporary_dir / "decision_manifest.json"),
            "promotion_decision_sha256": sha256_file(temporary_dir / "promotion_decision.json"),
            "phase4_gate_sha256": sha256_file(temporary_dir / "phase4_gate.json"),
        }
        _write_json(temporary_dir / "_SUCCESS", completion)
        if phase4_gate["status"] != "passed":
            raise DecisionEvaluationError("Phase 4 result gate failed")
        os.replace(temporary_dir, output_dir)
    except BaseException:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise
    return DecisionEvaluationResult(
        payload={
            **plan,
            "dry_run": False,
            "status": "complete",
            "outcome": decision["outcome"],
            "production_default": decision["production_default"],
            "B1_gate": decision["B1_gate"]["status"],
            "H1_gate": decision["H1_gate"]["status"],
            "bootstrap_failed": bootstrap.metadata["failed_repeats"],
            "output_files": sorted(
                path.relative_to(output_dir).as_posix()
                for path in output_dir.rglob("*")
                if path.is_file()
            ),
        }
    )
