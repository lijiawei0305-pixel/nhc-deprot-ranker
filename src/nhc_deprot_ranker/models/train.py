"""Atomic Phase 2 B0/B1 training and honest-validation runner."""

from __future__ import annotations

import json
import os
import platform
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import joblib  # type: ignore[import-untyped]
import numpy as np
import pandas as pd

from nhc_deprot_ranker.config import (
    BaselineModelConfig,
    EvaluationConfig,
    load_baseline_model_config,
    load_evaluation_config,
)
from nhc_deprot_ranker.data.provenance import sha256_file, sha256_source_tree
from nhc_deprot_ranker.models.affine import AffineCalibrator
from nhc_deprot_ranker.models.bootstrap import bootstrap_affine
from nhc_deprot_ranker.models.registry import BaselineModelBundle
from nhc_deprot_ranker.models.xtb_baseline import XtbBaseline
from nhc_deprot_ranker.reporting.plots import generate_baseline_figures
from nhc_deprot_ranker.validation.metrics import evaluate_predictions
from nhc_deprot_ranker.validation.ranking import deterministic_ranks
from nhc_deprot_ranker.validation.splits import (
    ValidationFold,
    leave_one_group_out_folds,
    loocv_folds,
)


class BaselineTrainingError(ValueError):
    """Phase 2 input, version, or validation contract failed."""


@dataclass(frozen=True)
class TrainBaselinesResult:
    """CLI-facing Phase 2 result."""

    payload: dict[str, Any]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _verify_dataset(
    *, dataset_dir: Path, evidence_path: Path, expected_version: str
) -> tuple[dict[str, Any], dict[str, str]]:
    if dataset_dir.name != expected_version:
        raise BaselineTrainingError(
            f"dataset directory {dataset_dir.name!r} does not match {expected_version!r}"
        )
    if not evidence_path.is_file():
        raise FileNotFoundError(evidence_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("dataset_version") != expected_version:
        raise BaselineTrainingError("checked-in evidence dataset version does not match config")
    expected_hashes = evidence.get("output_sha256")
    if not isinstance(expected_hashes, dict):
        raise BaselineTrainingError("processed evidence has no output_sha256 mapping")
    required_artifacts = {
        "candidates.parquet",
        "labels.parquet",
        "label_source_membership.csv",
        "source_manifest.json",
        "protocol_manifest.json",
        "data_quality.json",
    }
    missing_artifacts = sorted(required_artifacts - set(expected_hashes))
    if missing_artifacts:
        raise BaselineTrainingError(
            f"processed evidence is missing required hashes: {missing_artifacts}"
        )
    verified_hashes: dict[str, str] = {}
    for name, expected_hash in expected_hashes.items():
        if not isinstance(name, str) or not isinstance(expected_hash, str):
            raise BaselineTrainingError("processed evidence hash entry is invalid")
        path = dataset_dir / name
        actual = sha256_file(path)
        if actual != expected_hash:
            raise BaselineTrainingError(
                f"processed input hash mismatch for {name}: {actual} != {expected_hash}"
            )
        verified_hashes[name] = actual
    success_path = dataset_dir / "_SUCCESS"
    success = json.loads(success_path.read_text(encoding="utf-8"))
    if success.get("dataset_version") != expected_version:
        raise BaselineTrainingError("processed _SUCCESS dataset version mismatch")
    return evidence, verified_hashes


def _load_labeled_frame(
    *, dataset_dir: Path, model_config: BaselineModelConfig, evidence: dict[str, Any]
) -> pd.DataFrame:
    candidates = pd.read_parquet(dataset_dir / "candidates.parquet")
    labels = pd.read_parquet(dataset_dir / "labels.parquet")
    candidate_columns = [
        "inchikey",
        model_config.baseline_column,
        "axis_a_family",
        "axis_b_family",
        "combined_family",
    ]
    label_columns = ["inchikey", model_config.target_column, "source_group"]
    for name, frame, required in (
        ("candidates", candidates, candidate_columns),
        ("labels", labels, label_columns),
    ):
        missing = sorted(set(required) - set(frame.columns))
        if missing:
            raise BaselineTrainingError(f"{name} missing required columns: {missing}")
        if frame["inchikey"].isna().any() or frame["inchikey"].duplicated().any():
            raise BaselineTrainingError(f"{name} InChIKey must be non-null and unique")
    expected_rows = evidence.get("rows", {})
    if len(candidates) != expected_rows.get("candidates"):
        raise BaselineTrainingError("candidate row count disagrees with checked-in evidence")
    if len(labels) != expected_rows.get("labels"):
        raise BaselineTrainingError("label row count disagrees with checked-in evidence")
    labeled = labels.loc[:, label_columns].merge(
        candidates.loc[:, candidate_columns], on="inchikey", how="left", validate="one_to_one"
    )
    if labeled[candidate_columns[1:]].isna().any().any():
        raise BaselineTrainingError("one or more labels have no complete candidate join")
    for column in (model_config.baseline_column, model_config.target_column):
        values = labeled[column].to_numpy(dtype=np.float64)
        if not np.isfinite(values).all():
            raise BaselineTrainingError(f"{column} contains non-finite values")
    for family_column in ("axis_a_family", "axis_b_family", "combined_family"):
        if labeled[family_column].astype(str).str.strip().eq("").any():
            raise BaselineTrainingError(f"{family_column} contains blank values")
    return labeled.sort_values("inchikey", kind="mergesort").reset_index(drop=True)


def _evaluate_folds(
    *,
    labeled: pd.DataFrame,
    folds: tuple[ValidationFold, ...],
    model_config: BaselineModelConfig,
) -> pd.DataFrame:
    x = labeled[model_config.baseline_column].to_numpy(dtype=np.float64)
    y = labeled[model_config.target_column].to_numpy(dtype=np.float64)
    keys = labeled["inchikey"].astype(str).tolist()
    rows: list[dict[str, Any]] = []
    for fold in folds:
        train = np.asarray(fold.train_indices, dtype=np.int64)
        test = np.asarray(fold.test_indices, dtype=np.int64)
        affine = AffineCalibrator(
            min_samples=model_config.affine.min_samples,
            condition_number_threshold=model_config.affine.condition_number_threshold,
        ).fit(x[train], y[train], [keys[index] for index in train])
        predictions = affine.predict(x[test])
        for local_index, row_index in enumerate(test):
            source = labeled.iloc[int(row_index)]
            rows.append(
                {
                    "protocol": fold.protocol,
                    "fold_id": fold.fold_id,
                    "held_out_group": fold.held_out_group,
                    "inchikey": source["inchikey"],
                    "true_dft_kcal": float(y[row_index]),
                    "xtb_deprot_kcal": float(x[row_index]),
                    "b0_prediction_kcal": float(x[row_index]),
                    "b1_prediction_kcal": float(predictions[local_index]),
                    "b1_beta_0": affine.intercept_,
                    "b1_rho": affine.slope_,
                    "train_n": len(train),
                    "axis_a_family": source["axis_a_family"],
                    "axis_b_family": source["axis_b_family"],
                    "combined_family": source["combined_family"],
                    "source_group": source["source_group"],
                }
            )
    frame = pd.DataFrame.from_records(rows).sort_values("inchikey", kind="mergesort")
    frame = frame.reset_index(drop=True)
    if len(frame) != len(labeled) or frame["inchikey"].duplicated().any():
        raise BaselineTrainingError(f"{folds[0].protocol} does not produce one OOF row per key")
    if set(frame["inchikey"]) != set(keys):
        raise BaselineTrainingError(f"{folds[0].protocol} OOF key coverage is incomplete")
    return frame


def _protocol_metrics(
    predictions: pd.DataFrame, evaluation_config: EvaluationConfig
) -> dict[str, Any]:
    ranking = evaluation_config.ranking
    common: dict[str, Any] = {
        "true_values": predictions["true_dft_kcal"].to_numpy(dtype=np.float64),
        "keys": predictions["inchikey"].astype(str).tolist(),
        "true_top_m": ranking.true_top_m,
        "predicted_budget_k": ranking.predicted_budget_k,
        "ndcg_k": ranking.ndcg_k,
        "pairwise_tie_threshold_kcal": ranking.pairwise_tie_threshold_kcal,
        "lower_is_better": ranking.lower_is_better,
    }
    model_metrics = {
        "B0": evaluate_predictions(
            predicted_values=predictions["b0_prediction_kcal"].to_numpy(dtype=np.float64),
            **common,
        ),
        "B1": evaluate_predictions(
            predicted_values=predictions["b1_prediction_kcal"].to_numpy(dtype=np.float64),
            **common,
        ),
    }
    group_summaries: list[dict[str, Any]] = []
    if predictions["held_out_group"].notna().all():
        for group, subset in predictions.groupby("held_out_group", sort=True):
            group_summaries.append(
                {
                    "held_out_group": str(group),
                    "n": len(subset),
                    "B0_mae_kcal": float(
                        np.mean(
                            np.abs(
                                subset["b0_prediction_kcal"].to_numpy(dtype=np.float64)
                                - subset["true_dft_kcal"].to_numpy(dtype=np.float64)
                            )
                        )
                    ),
                    "B1_mae_kcal": float(
                        np.mean(
                            np.abs(
                                subset["b1_prediction_kcal"].to_numpy(dtype=np.float64)
                                - subset["true_dft_kcal"].to_numpy(dtype=np.float64)
                            )
                        )
                    ),
                }
            )
    return {
        "status": "complete",
        "n": len(predictions),
        "folds": int(predictions["fold_id"].nunique()),
        "models": model_metrics,
        "held_out_group_absolute_error": group_summaries,
    }


def _historical_reproduction(
    *,
    model_config: BaselineModelConfig,
    coefficients: dict[str, Any],
    loo_metrics: dict[str, Any],
) -> dict[str, Any]:
    reference = model_config.historical_reference
    observed = {
        "intercept": coefficients["B1"]["beta_0"],
        "slope": coefficients["B1"]["rho"],
        "loocv_mae": loo_metrics["B1"]["mae_kcal"],
        "loocv_rmse": loo_metrics["B1"]["rmse_kcal"],
        "loocv_spearman": loo_metrics["B1"]["spearman_rho"],
        "loocv_kendall": loo_metrics["B1"]["kendall_tau"],
        "raw_spearman": loo_metrics["B0"]["spearman_rho"],
        "raw_kendall": loo_metrics["B0"]["kendall_tau"],
    }
    expected = {
        "intercept": reference.intercept,
        "slope": reference.slope,
        "loocv_mae": reference.loocv_mae,
        "loocv_rmse": reference.loocv_rmse,
        "loocv_spearman": reference.loocv_spearman,
        "loocv_kendall": reference.loocv_kendall,
        "raw_spearman": reference.raw_spearman,
        "raw_kendall": reference.raw_kendall,
    }
    comparisons: dict[str, Any] = {}
    for name, value in observed.items():
        if name == "intercept":
            tolerance = reference.intercept_absolute_tolerance
        elif name == "slope":
            tolerance = reference.slope_absolute_tolerance
        else:
            tolerance = reference.metric_absolute_tolerance
        difference = abs(float(value) - float(expected[name]))
        comparisons[name] = {
            "observed": value,
            "historical": expected[name],
            "absolute_difference": difference,
            "tolerance": tolerance,
            "passed": difference <= tolerance,
        }
    return {
        "status": "reproduced"
        if all(item["passed"] for item in comparisons.values())
        else "mismatch",
        "normalization_note": (
            "Legacy coefficients used stored rounded targets; v001 fits endpoint-recomputed "
            "electronic targets, so separate pre-registered coefficient tolerances apply."
        ),
        "comparisons": comparisons,
    }


def _rank_shift_audit(loocv: pd.DataFrame) -> pd.DataFrame:
    keys = loocv["inchikey"].astype(str).tolist()
    truth = loocv["true_dft_kcal"].to_numpy(dtype=np.float64)
    b0 = loocv["b0_prediction_kcal"].to_numpy(dtype=np.float64)
    b1 = loocv["b1_prediction_kcal"].to_numpy(dtype=np.float64)
    frame = loocv.copy()
    frame["true_rank"] = deterministic_ranks(truth, keys, lower_is_better=True).astype(int)
    frame["b0_rank"] = deterministic_ranks(b0, keys, lower_is_better=True).astype(int)
    frame["b1_rank"] = deterministic_ranks(b1, keys, lower_is_better=True).astype(int)
    frame["b0_rank_error"] = frame["b0_rank"] - frame["true_rank"]
    frame["b1_rank_error"] = frame["b1_rank"] - frame["true_rank"]
    frame["b0_residual_kcal"] = frame["b0_prediction_kcal"] - frame["true_dft_kcal"]
    frame["b1_residual_kcal"] = frame["b1_prediction_kcal"] - frame["true_dft_kcal"]
    return frame


def train_baselines(
    *,
    dataset_dir: Path,
    model_config_path: Path,
    evaluation_config_path: Path,
    evidence_path: Path,
    output_dir: Path,
    seed: int,
    dry_run: bool = False,
    overwrite: bool = False,
) -> TrainBaselinesResult:
    """Fit and evaluate Phase 2 baselines into one immutable result directory."""

    model_config = load_baseline_model_config(model_config_path)
    evaluation_config = load_evaluation_config(evaluation_config_path)
    expected_output_name = f"baselines_{model_config.model_version}"
    if output_dir.name != expected_output_name:
        raise BaselineTrainingError(
            f"output directory name {output_dir.name!r} must equal {expected_output_name!r}"
        )
    if output_dir.exists():
        raise BaselineTrainingError(f"immutable baseline result already exists: {output_dir}")
    if overwrite:
        raise BaselineTrainingError("--overwrite cannot replace an immutable baseline result")
    if model_config.bootstrap.final_repeats != evaluation_config.bootstrap_ci.repeats:
        raise BaselineTrainingError("model/evaluation bootstrap repeat settings disagree")
    if model_config.bootstrap.confidence != evaluation_config.bootstrap_ci.confidence:
        raise BaselineTrainingError("model/evaluation bootstrap confidence settings disagree")
    plan = {
        "command": "train",
        "dataset_version": model_config.dataset_version,
        "model_version": model_config.model_version,
        "models": ["B0_raw_xtb", "B1_global_affine"],
        "protocols": evaluation_config.protocols,
        "output_dir": str(output_dir),
        "dry_run": dry_run,
        "size_extrapolation": "unavailable_missing_validated_size",
        "blind_holdout": "missing_revealed_legacy_rounds",
        "hpc_writes": False,
        "quantum_chemistry": False,
    }
    if dry_run:
        return TrainBaselinesResult(payload=plan)

    evidence, input_hashes = _verify_dataset(
        dataset_dir=dataset_dir,
        evidence_path=evidence_path,
        expected_version=model_config.dataset_version,
    )
    labeled = _load_labeled_frame(
        dataset_dir=dataset_dir,
        model_config=model_config,
        evidence=evidence,
    )
    keys = labeled["inchikey"].astype(str).tolist()
    x = labeled[model_config.baseline_column].to_numpy(dtype=np.float64)
    y = labeled[model_config.target_column].to_numpy(dtype=np.float64)
    b0 = XtbBaseline().fit(x, keys)
    b1 = AffineCalibrator(
        min_samples=model_config.affine.min_samples,
        condition_number_threshold=model_config.affine.condition_number_threshold,
    ).fit(x, y, keys)
    coefficients = {"B0": b0.metadata(), "B1": b1.coefficients()}
    bootstrap = bootstrap_affine(
        x=x,
        y=y,
        keys=keys,
        repeats=model_config.bootstrap.final_repeats,
        seed=seed,
        confidence=model_config.bootstrap.confidence,
        min_samples=model_config.affine.min_samples,
        condition_number_threshold=model_config.affine.condition_number_threshold,
    )

    protocols = {
        "loocv": loocv_folds(keys),
        "leave_axis_a_out": leave_one_group_out_folds(
            keys=keys,
            groups=labeled["axis_a_family"].astype(str).tolist(),
            protocol="leave_axis_a_out",
        ),
        "leave_axis_b_out": leave_one_group_out_folds(
            keys=keys,
            groups=labeled["axis_b_family"].astype(str).tolist(),
            protocol="leave_axis_b_out",
        ),
    }
    prediction_frames: dict[str, pd.DataFrame] = {
        protocol: _evaluate_folds(
            labeled=labeled,
            folds=folds,
            model_config=model_config,
        )
        for protocol, folds in protocols.items()
    }
    rank_audit = _rank_shift_audit(prediction_frames["loocv"])
    prediction_frames["loocv"] = rank_audit
    protocol_metrics = {
        protocol: _protocol_metrics(frame, evaluation_config)
        for protocol, frame in prediction_frames.items()
    }
    metrics: dict[str, Any] = {
        "dataset_version": model_config.dataset_version,
        "model_version": model_config.model_version,
        "protocols": {
            **protocol_metrics,
            "combined_family_holdout_if_supported": {
                "status": "unavailable_redundant_singletons",
                "unique_groups": int(labeled["combined_family"].nunique()),
                "rows": len(labeled),
            },
            "size_extrapolation": {
                "status": "unavailable_missing_validated_size",
                "n_heavy_atoms_nonnull": 0,
                "n_electrons_nonnull": 0,
            },
            "blind_holdout": {
                "status": "blind_test_missing",
                "reason": evaluation_config.blind_holdout.reason,
            },
        },
    }
    historical = _historical_reproduction(
        model_config=model_config,
        coefficients=coefficients,
        loo_metrics=protocol_metrics["loocv"]["models"],
    )
    metrics["historical_reproduction"] = historical
    split_manifest = {
        "dataset_version": model_config.dataset_version,
        "split_unit": "inchikey",
        "protocols": {
            protocol: [fold.to_manifest(keys) for fold in folds]
            for protocol, folds in protocols.items()
        },
        "unavailable": {
            "combined_family": "redundant_all_singletons",
            "size_extrapolation": "missing_validated_size",
            "blind_holdout": "revealed_legacy_rounds",
        },
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(
        tempfile.mkdtemp(prefix=f".{expected_output_name}.tmp.", dir=output_dir.parent)
    )
    try:
        bundle = BaselineModelBundle(
            dataset_version=model_config.dataset_version,
            model_version=model_config.model_version,
            b0=b0,
            b1=b1,
        )
        joblib.dump(bundle, temporary_dir / "model.pkl", compress=3)
        _write_json(temporary_dir / "coefficients.json", coefficients)
        _write_json(temporary_dir / "bootstrap_summary.json", bootstrap.summary)
        bootstrap.replicates.to_parquet(
            temporary_dir / "bootstrap_summary.parquet", index=False, compression="zstd"
        )
        pd.DataFrame.from_records(
            [
                {
                    "model": "B0/B1",
                    "term": "family_effects",
                    "status": "not_applicable_phase2_baselines",
                    "effect": None,
                }
            ]
        ).to_csv(temporary_dir / "family_effects.csv", index=False)
        all_predictions = pd.concat(
            [prediction_frames[protocol] for protocol in protocols], ignore_index=True
        )
        all_predictions.to_csv(temporary_dir / "oof_predictions.csv", index=False)
        _write_json(temporary_dir / "split_manifest.json", split_manifest)
        _write_json(temporary_dir / "metrics.json", metrics)
        rank_audit.to_csv(temporary_dir / "rank_shift_audit.csv", index=False)
        _write_json(
            temporary_dir / "promotion_decision.json",
            {
                "status": "deferred_to_phase4",
                "reason": "H1 is not implemented in Phase 2; B0 remains the production baseline.",
                "historical_reproduction": historical["status"],
            },
        )
        gate_checks = {
            "historical_reproduced": (
                historical["status"] == "reproduced"
                or not model_config.historical_reference.enforce
            ),
            "loocv_rows": len(prediction_frames["loocv"]) == len(labeled),
            "axis_a_rows": len(prediction_frames["leave_axis_a_out"]) == len(labeled),
            "axis_b_rows": len(prediction_frames["leave_axis_b_out"]) == len(labeled),
            "bootstrap_repeats": bootstrap.summary["successful_repeats"]
            + bootstrap.summary["failed_repeats"]
            == model_config.bootstrap.final_repeats,
            "combined_family_status_honest": True,
            "size_status_honest": True,
            "blind_status_honest": True,
        }
        phase2_gate = {
            "status": "passed" if all(gate_checks.values()) else "failed",
            "checks": gate_checks,
            "rows": len(labeled),
        }
        _write_json(temporary_dir / "phase2_gate.json", phase2_gate)
        generate_baseline_figures(
            labeled=labeled,
            loocv=rank_audit,
            metrics=metrics,
            coefficients=coefficients,
            output_dir=temporary_dir / "figures",
            dataset_version=model_config.dataset_version,
            model_version=model_config.model_version,
        )
        hashable_paths = sorted(path for path in temporary_dir.rglob("*") if path.is_file())
        output_hashes = {
            path.relative_to(temporary_dir).as_posix(): sha256_file(path) for path in hashable_paths
        }
        model_manifest = {
            "dataset_version": model_config.dataset_version,
            "model_name": model_config.model_name,
            "model_version": model_config.model_version,
            "seed": seed,
            "source_tree_sha256": sha256_source_tree(Path(__file__).parents[1]),
            "training_rows": len(labeled),
            "training_key_sha256": b1.training_key_sha256_,
            "input_sha256": {
                **input_hashes,
                "processed_evidence": sha256_file(evidence_path),
                "model_config": sha256_file(model_config_path),
                "evaluation_config": sha256_file(evaluation_config_path),
            },
            "output_sha256": output_hashes,
            "software": {
                "python": platform.python_version(),
                "numpy": version("numpy"),
                "pandas": version("pandas"),
                "scipy": version("scipy"),
                "scikit_learn": version("scikit-learn"),
                "matplotlib": version("matplotlib"),
            },
            "predictions": {
                "loocv_oof": True,
                "axis_a_oof": True,
                "axis_b_oof": True,
                "full_fit_predictions_reported_as_oof": False,
            },
        }
        _write_json(temporary_dir / "model_manifest.json", model_manifest)
        completion = {
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "dataset_version": model_config.dataset_version,
            "model_version": model_config.model_version,
            "rows": len(labeled),
            "status": phase2_gate["status"],
            "model_manifest_sha256": sha256_file(temporary_dir / "model_manifest.json"),
            "metrics_sha256": sha256_file(temporary_dir / "metrics.json"),
            "phase2_gate_sha256": sha256_file(temporary_dir / "phase2_gate.json"),
        }
        _write_json(temporary_dir / "_SUCCESS", completion)
        if phase2_gate["status"] != "passed":
            raise BaselineTrainingError("Phase 2 real-data gate failed")
        os.replace(temporary_dir, output_dir)
    except BaseException:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise
    return TrainBaselinesResult(
        payload={
            **plan,
            "dry_run": False,
            "status": "complete",
            "rows": len(labeled),
            "phase2_gate": "passed",
            "historical_reproduction": historical["status"],
            "output_files": sorted(
                path.relative_to(output_dir).as_posix()
                for path in output_dir.rglob("*")
                if path.is_file()
            ),
        }
    )
