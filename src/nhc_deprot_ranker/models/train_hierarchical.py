"""Atomic Phase 3 H1 nested validation and uncertainty runner."""

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

import numpy as np
import pandas as pd

from nhc_deprot_ranker.config import (
    EvaluationConfig,
    HierarchicalModelConfig,
    load_evaluation_config,
    load_hierarchical_model_config,
)
from nhc_deprot_ranker.data.provenance import sha256_file, sha256_source_tree
from nhc_deprot_ranker.models.bootstrap import bootstrap_hierarchical
from nhc_deprot_ranker.models.hierarchical import HierarchicalLinearCalibrator
from nhc_deprot_ranker.reporting.hierarchical_plots import generate_hierarchical_figures
from nhc_deprot_ranker.validation.metrics import evaluate_predictions
from nhc_deprot_ranker.validation.nested_cv import (
    NestedSelectionResult,
    PenaltySet,
    select_hierarchical_penalties,
)
from nhc_deprot_ranker.validation.ranking import deterministic_ranks
from nhc_deprot_ranker.validation.splits import (
    ValidationFold,
    hashed_group_kfolds,
    hashed_kfolds,
)


class HierarchicalTrainingError(ValueError):
    """Phase 3 input, nesting, or immutable-output contract failed."""


@dataclass(frozen=True)
class TrainHierarchicalResult:
    """CLI-facing Phase 3 result."""

    payload: dict[str, Any]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _verify_evidence(root: Path, evidence_path: Path, expected_version: str) -> dict[str, str]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("dataset_version") != expected_version:
        raise HierarchicalTrainingError(
            f"evidence version mismatch for {root}: {evidence.get('dataset_version')}"
        )
    hashes = evidence.get("output_sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise HierarchicalTrainingError(f"evidence has no output hashes: {evidence_path}")
    verified: dict[str, str] = {}
    for name, expected in hashes.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise HierarchicalTrainingError("invalid evidence hash entry")
        actual = sha256_file(root / name)
        if actual != expected:
            raise HierarchicalTrainingError(
                f"input hash mismatch for {root.name}/{name}: {actual} != {expected}"
            )
        verified[name] = actual
    return verified


def _load_labeled(dataset_dir: Path, config: HierarchicalModelConfig) -> pd.DataFrame:
    candidates = pd.read_parquet(dataset_dir / "candidates.parquet")
    labels = pd.read_parquet(dataset_dir / "labels.parquet")
    candidate_columns = [
        "inchikey",
        config.baseline_column,
        "skeleton",
        "axis_a_family",
        "axis_b_family",
        "combined_family",
    ]
    label_columns = ["inchikey", config.target_column, "source_group", "label_protocol_id"]
    for name, frame, columns in (
        ("candidates", candidates, candidate_columns),
        ("labels", labels, label_columns),
    ):
        missing = sorted(set(columns) - set(frame.columns))
        if missing:
            raise HierarchicalTrainingError(f"{name} missing columns: {missing}")
        if frame["inchikey"].isna().any() or frame["inchikey"].duplicated().any():
            raise HierarchicalTrainingError(f"{name} keys must be unique and non-null")
    labeled = labels.loc[:, label_columns].merge(
        candidates.loc[:, candidate_columns], on="inchikey", how="left", validate="one_to_one"
    )
    if len(labeled) != config.expected_label_rows:
        raise HierarchicalTrainingError(
            f"Phase 3 requires {config.expected_label_rows} labels, found {len(labeled)}"
        )
    if labeled.isna().any().any():
        raise HierarchicalTrainingError("Phase 3 labeled frame contains missing required values")
    if labeled["label_protocol_id"].nunique() != 1:
        raise HierarchicalTrainingError("Phase 3 labels must share one protocol")
    for column in (config.baseline_column, config.target_column):
        if not np.isfinite(labeled[column].to_numpy(dtype=np.float64)).all():
            raise HierarchicalTrainingError(f"{column} contains non-finite values")
    return labeled.sort_values("inchikey", kind="mergesort").reset_index(drop=True)


def _outer_folds_from_baseline(
    *, baseline_results_dir: Path, keys: list[str]
) -> dict[str, tuple[ValidationFold, ...]]:
    manifest = json.loads((baseline_results_dir / "split_manifest.json").read_text())
    key_to_index = {key: index for index, key in enumerate(keys)}
    protocols: dict[str, tuple[ValidationFold, ...]] = {}
    for protocol in ("loocv", "leave_axis_a_out", "leave_axis_b_out"):
        folds: list[ValidationFold] = []
        for source in manifest["protocols"][protocol]:
            try:
                train_indices = tuple(key_to_index[key] for key in source["train_keys"])
                test_indices = tuple(key_to_index[key] for key in source["test_keys"])
            except KeyError as exc:
                raise HierarchicalTrainingError(
                    f"baseline split contains unknown key: {exc}"
                ) from exc
            folds.append(
                ValidationFold(
                    protocol=protocol,
                    fold_id=str(source["fold_id"]),
                    train_indices=train_indices,
                    test_indices=test_indices,
                    held_out_group=source.get("held_out_group"),
                )
            )
        test_keys = [keys[index] for fold in folds for index in fold.test_indices]
        if len(test_keys) != len(keys) or len(set(test_keys)) != len(keys):
            raise HierarchicalTrainingError(f"baseline outer split coverage failed: {protocol}")
        protocols[protocol] = tuple(folds)
    return protocols


def _inner_folds(
    *, outer_training: pd.DataFrame, outer_protocol: str, config: HierarchicalModelConfig
) -> tuple[ValidationFold, ...]:
    keys = outer_training["inchikey"].astype(str).tolist()
    if outer_protocol == "loocv":
        return hashed_kfolds(
            keys=keys,
            n_splits=config.inner_cv.folds,
            seed=config.inner_cv.seed,
            protocol="inner_hashed_key_5fold",
        )
    group_column = "axis_a_family" if outer_protocol == "leave_axis_a_out" else "axis_b_family"
    group_count = int(outer_training[group_column].nunique())
    return hashed_group_kfolds(
        keys=keys,
        groups=outer_training[group_column].astype(str).tolist(),
        n_splits=min(config.inner_cv.folds, group_count),
        seed=config.inner_cv.seed,
        protocol=f"inner_{group_column}_group_5fold",
    )


def _estimator(
    penalties: PenaltySet, config: HierarchicalModelConfig
) -> HierarchicalLinearCalibrator:
    return HierarchicalLinearCalibrator(
        lambda_skeleton=penalties.lambda_skeleton,
        lambda_axis_a=penalties.lambda_axis_a,
        lambda_axis_b=penalties.lambda_axis_b,
        lambda_slope=config.slope.penalty,
        rho_prior=config.slope.prior_center,
        condition_number_threshold=config.numerical.condition_number_threshold,
        skeleton_policy=config.skeleton_policy,
    )


def _nested_protocol(
    *,
    labeled: pd.DataFrame,
    target: np.ndarray,
    outer_folds: tuple[ValidationFold, ...],
    config: HierarchicalModelConfig,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    search_records: list[dict[str, Any]] = []
    for outer_number, outer_fold in enumerate(outer_folds):
        train = np.asarray(outer_fold.train_indices, dtype=np.int64)
        test = np.asarray(outer_fold.test_indices, dtype=np.int64)
        outer_training = labeled.iloc[train].reset_index(drop=True)
        outer_target = target[train]
        inner_folds = _inner_folds(
            outer_training=outer_training,
            outer_protocol=outer_fold.protocol,
            config=config,
        )
        selection = select_hierarchical_penalties(
            frame=outer_training,
            y=outer_target,
            inner_folds=inner_folds,
            config=config,
        )
        model = _estimator(selection.selected, config).fit(outer_training, outer_target)
        query = labeled.iloc[test].reset_index(drop=True)
        components = model.predict_components(query)
        if outer_fold.protocol == "leave_axis_a_out" and (
            components["axis_a_family_known"].any()
            or not np.allclose(components["axis_a_effect"], 0.0)
        ):
            raise HierarchicalTrainingError(
                f"held-out axis-A fallback failed: {outer_fold.fold_id}"
            )
        if outer_fold.protocol == "leave_axis_b_out" and (
            components["axis_b_family_known"].any()
            or not np.allclose(components["axis_b_effect"], 0.0)
        ):
            raise HierarchicalTrainingError(
                f"held-out axis-B fallback failed: {outer_fold.fold_id}"
            )
        for local_index, row_index in enumerate(test):
            source = labeled.iloc[int(row_index)]
            component = components.iloc[local_index]
            rows.append(
                {
                    "protocol": outer_fold.protocol,
                    "fold_id": outer_fold.fold_id,
                    "held_out_group": outer_fold.held_out_group,
                    "inchikey": source["inchikey"],
                    "true_dft_kcal": float(target[row_index]),
                    "xtb_deprot_kcal": float(source[config.baseline_column]),
                    "h1_prediction_kcal": float(component["final_prediction"]),
                    "global_intercept": float(component["global_intercept"]),
                    "global_slope_contribution": float(component["global_slope_contribution"]),
                    "skeleton_effect": float(component["skeleton_effect"]),
                    "axis_a_effect": float(component["axis_a_effect"]),
                    "axis_b_effect": float(component["axis_b_effect"]),
                    "skeleton_known": bool(component["skeleton_known"]),
                    "axis_a_family_known": bool(component["axis_a_family_known"]),
                    "axis_b_family_known": bool(component["axis_b_family_known"]),
                    "lambda_axis_a": selection.selected.lambda_axis_a,
                    "lambda_axis_b": selection.selected.lambda_axis_b,
                    "axis_a_family": source["axis_a_family"],
                    "axis_b_family": source["axis_b_family"],
                    "combined_family": source["combined_family"],
                    "source_group": source["source_group"],
                }
            )
        outer_keys = outer_training["inchikey"].astype(str).tolist()
        search_records.append(
            {
                "outer_fold_number": outer_number,
                "outer_fold_id": outer_fold.fold_id,
                "outer_protocol": outer_fold.protocol,
                "outer_train_n": len(train),
                "outer_test_n": len(test),
                "selected_penalties": selection.selected.to_dict(),
                "selected_inner_rmse": selection.selected_rmse,
                "inner_folds": [fold.to_manifest(outer_keys) for fold in inner_folds],
                "candidates": list(selection.candidates),
            }
        )
    frame = pd.DataFrame.from_records(rows).sort_values("inchikey", kind="mergesort")
    frame = frame.reset_index(drop=True)
    if len(frame) != len(labeled) or frame["inchikey"].duplicated().any():
        raise HierarchicalTrainingError(f"nested OOF coverage failed: {outer_folds[0].protocol}")
    return frame, search_records


def _metrics(predictions: pd.DataFrame, evaluation: EvaluationConfig) -> dict[str, Any]:
    ranking = evaluation.ranking
    common: dict[str, Any] = {
        "true_values": predictions["true_dft_kcal"].to_numpy(dtype=np.float64),
        "keys": predictions["inchikey"].astype(str).tolist(),
        "true_top_m": ranking.true_top_m,
        "predicted_budget_k": ranking.predicted_budget_k,
        "ndcg_k": ranking.ndcg_k,
        "pairwise_tie_threshold_kcal": ranking.pairwise_tie_threshold_kcal,
        "lower_is_better": ranking.lower_is_better,
    }
    models = {
        name: evaluate_predictions(
            predicted_values=predictions[column].to_numpy(dtype=np.float64), **common
        )
        for name, column in (
            ("B0", "b0_prediction_kcal"),
            ("B1", "b1_prediction_kcal"),
            ("H1", "h1_prediction_kcal"),
        )
    }
    group_summaries: list[dict[str, Any]] = []
    if predictions["held_out_group"].notna().all():
        for group, subset in predictions.groupby("held_out_group", sort=True):
            truth = subset["true_dft_kcal"].to_numpy(dtype=np.float64)
            group_summaries.append(
                {
                    "held_out_group": str(group),
                    "n": len(subset),
                    "B1_mae_kcal": float(
                        np.mean(
                            np.abs(subset["b1_prediction_kcal"].to_numpy(dtype=np.float64) - truth)
                        )
                    ),
                    "H1_mae_kcal": float(
                        np.mean(
                            np.abs(subset["h1_prediction_kcal"].to_numpy(dtype=np.float64) - truth)
                        )
                    ),
                }
            )
    return {
        "status": "complete",
        "n": len(predictions),
        "folds": int(predictions["fold_id"].nunique()),
        "models": models,
        "held_out_group_absolute_error": group_summaries,
    }


def _rank_audit(loocv: pd.DataFrame) -> pd.DataFrame:
    frame = loocv.copy()
    keys = frame["inchikey"].astype(str).tolist()
    truth = frame["true_dft_kcal"].to_numpy(dtype=np.float64)
    ranks = {
        "true_rank": deterministic_ranks(truth, keys, lower_is_better=True),
        "b0_rank": deterministic_ranks(
            frame["b0_prediction_kcal"].to_numpy(dtype=np.float64),
            keys,
            lower_is_better=True,
        ),
        "b1_rank": deterministic_ranks(
            frame["b1_prediction_kcal"].to_numpy(dtype=np.float64),
            keys,
            lower_is_better=True,
        ),
        "h1_rank": deterministic_ranks(
            frame["h1_prediction_kcal"].to_numpy(dtype=np.float64),
            keys,
            lower_is_better=True,
        ),
    }
    for name, values in ranks.items():
        frame[name] = values.astype(int)
    for model in ("b0", "b1", "h1"):
        frame[f"{model}_rank_error"] = frame[f"{model}_rank"] - frame["true_rank"]
        frame[f"{model}_residual_kcal"] = frame[f"{model}_prediction_kcal"] - frame["true_dft_kcal"]
    return frame


def _provisional_comparison(metrics: dict[str, Any]) -> dict[str, Any]:
    comparisons: dict[str, Any] = {}
    for protocol in ("loocv", "leave_axis_a_out", "leave_axis_b_out"):
        models = metrics["protocols"][protocol]["models"]
        deltas: dict[str, float] = {}
        for name in models["H1"]:
            if name in {"spearman_rho", "kendall_tau"} or name.startswith(("recall_", "regret_")):
                deltas[name] = float(models["H1"][name] - models["B1"][name])
        comparisons[protocol] = deltas
    return {
        "status": "deferred_to_phase4",
        "reason": "Phase 3 records H1 evidence but does not promote a production model.",
        "H1_minus_B1": comparisons,
    }


def train_hierarchical(
    *,
    dataset_dir: Path,
    baseline_results_dir: Path,
    model_config_path: Path,
    evaluation_config_path: Path,
    dataset_evidence_path: Path,
    baseline_evidence_path: Path,
    output_dir: Path,
    seed: int,
    dry_run: bool = False,
    overwrite: bool = False,
) -> TrainHierarchicalResult:
    """Fit and nested-evaluate H1 into one immutable result directory."""

    config = load_hierarchical_model_config(model_config_path)
    evaluation = load_evaluation_config(evaluation_config_path)
    expected_name = f"hierarchical_{config.model_version}"
    if dataset_dir.name != config.dataset_version:
        raise HierarchicalTrainingError("dataset directory version does not match model config")
    if baseline_results_dir.name != f"baselines_{config.baseline_result_version}":
        raise HierarchicalTrainingError("baseline result version does not match model config")
    if output_dir.name != expected_name:
        raise HierarchicalTrainingError(
            f"output directory name {output_dir.name!r} must equal {expected_name!r}"
        )
    if output_dir.exists():
        raise HierarchicalTrainingError(f"immutable H1 result already exists: {output_dir}")
    if overwrite:
        raise HierarchicalTrainingError("--overwrite cannot replace an immutable H1 result")
    if config.bootstrap.final_repeats != evaluation.bootstrap_ci.repeats:
        raise HierarchicalTrainingError("model/evaluation bootstrap repeat settings disagree")
    plan = {
        "command": "train",
        "model": "H1_hierarchical_linear",
        "dataset_version": config.dataset_version,
        "baseline_result_version": config.baseline_result_version,
        "model_version": config.model_version,
        "output_dir": str(output_dir),
        "dry_run": dry_run,
        "skeleton_policy": "inactive_single_level_zero_effect",
        "nested_protocols": ["loocv", "leave_axis_a_out", "leave_axis_b_out"],
        "bootstrap_regularization": config.bootstrap.regularization_policy,
        "size_model": False,
        "phase4_promotion": False,
        "hpc_writes": False,
        "quantum_chemistry": False,
    }
    if dry_run:
        return TrainHierarchicalResult(payload=plan)

    dataset_hashes = _verify_evidence(dataset_dir, dataset_evidence_path, config.dataset_version)
    baseline_hashes = _verify_evidence(
        baseline_results_dir, baseline_evidence_path, config.dataset_version
    )
    labeled = _load_labeled(dataset_dir, config)
    keys = labeled["inchikey"].astype(str).tolist()
    target = labeled[config.target_column].to_numpy(dtype=np.float64)
    baseline_manifest = json.loads(
        (baseline_results_dir / "model_manifest.json").read_text(encoding="utf-8")
    )
    if (
        baseline_manifest["training_key_sha256"]
        != json.loads(baseline_evidence_path.read_text(encoding="utf-8"))["model"][
            "training_key_sha256"
        ]
    ):
        raise HierarchicalTrainingError("baseline training-key hashes disagree")
    outer_protocols = _outer_folds_from_baseline(
        baseline_results_dir=baseline_results_dir, keys=keys
    )
    nested_predictions: dict[str, pd.DataFrame] = {}
    nested_search: dict[str, Any] = {}
    for protocol, folds in outer_protocols.items():
        predictions, searches = _nested_protocol(
            labeled=labeled,
            target=target,
            outer_folds=folds,
            config=config,
        )
        nested_predictions[protocol] = predictions
        nested_search[protocol] = searches
    baseline_oof = pd.read_csv(baseline_results_dir / "oof_predictions.csv")
    combined_predictions: dict[str, pd.DataFrame] = {}
    for protocol, h1_predictions in nested_predictions.items():
        reference = baseline_oof.loc[
            baseline_oof["protocol"].eq(protocol),
            [
                "inchikey",
                "true_dft_kcal",
                "b0_prediction_kcal",
                "b1_prediction_kcal",
            ],
        ]
        combined = h1_predictions.merge(
            reference,
            on="inchikey",
            how="inner",
            validate="one_to_one",
            suffixes=("_h1", "_baseline"),
        )
        if len(combined) != len(labeled) or not np.allclose(
            combined["true_dft_kcal_h1"], combined["true_dft_kcal_baseline"], atol=1e-12
        ):
            raise HierarchicalTrainingError(f"B1/H1 OOF alignment failed: {protocol}")
        combined = combined.drop(columns=["true_dft_kcal_baseline"]).rename(
            columns={"true_dft_kcal_h1": "true_dft_kcal"}
        )
        combined_predictions[protocol] = combined.sort_values("inchikey").reset_index(drop=True)
    rank_audit = _rank_audit(combined_predictions["loocv"])
    combined_predictions["loocv"] = rank_audit
    protocol_metrics = {
        protocol: _metrics(frame, evaluation) for protocol, frame in combined_predictions.items()
    }
    metrics: dict[str, Any] = {
        "dataset_version": config.dataset_version,
        "model_version": config.model_version,
        "protocols": {
            **protocol_metrics,
            "combined_family_holdout_if_supported": {"status": "unavailable_redundant_singletons"},
            "size_extrapolation": {"status": "unavailable_missing_validated_size"},
            "blind_holdout": {"status": "blind_test_missing"},
        },
    }
    final_inner_folds = hashed_kfolds(
        keys=keys,
        n_splits=config.inner_cv.folds,
        seed=config.inner_cv.seed,
        protocol="final_inner_hashed_key_5fold",
    )
    final_selection: NestedSelectionResult = select_hierarchical_penalties(
        frame=labeled,
        y=target,
        inner_folds=final_inner_folds,
        config=config,
    )
    final_model = _estimator(final_selection.selected, config).fit(labeled, target)
    family_effects = final_model.family_effects()
    bootstrap = bootstrap_hierarchical(
        training_frame=labeled,
        y=target,
        query_frame=labeled,
        penalties=final_selection.selected,
        lambda_slope=config.slope.penalty,
        rho_prior=config.slope.prior_center,
        condition_number_threshold=config.numerical.condition_number_threshold,
        skeleton_policy=config.skeleton_policy,
        repeats=config.bootstrap.final_repeats,
        seed=seed,
        confidence=evaluation.bootstrap_ci.confidence,
        top_k=evaluation.ranking.predicted_budget_k,
    )
    promotion = _provisional_comparison(metrics)
    metrics["provisional_comparison"] = promotion
    nested_search["final_fit_selection"] = {
        "selected_penalties": final_selection.selected.to_dict(),
        "selected_inner_rmse": final_selection.selected_rmse,
        "inner_folds": [fold.to_manifest(keys) for fold in final_inner_folds],
        "candidates": list(final_selection.candidates),
    }
    split_manifest = {
        "dataset_version": config.dataset_version,
        "split_unit": "inchikey",
        "outer_source": "results/baselines_v001/split_manifest.json",
        "outer_protocols": {
            protocol: [fold.to_manifest(keys) for fold in folds]
            for protocol, folds in outer_protocols.items()
        },
        "inner_policy": {
            "loocv": "hashed_key_5fold",
            "axis_a": "support_balanced_group_disjoint_5fold",
            "axis_b": "support_balanced_group_disjoint_5fold",
            "seed": config.inner_cv.seed,
        },
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix=f".{expected_name}.tmp.", dir=output_dir.parent))
    try:
        final_model.save(temporary_dir / "model.pkl")
        loaded = HierarchicalLinearCalibrator.load(temporary_dir / "model.pkl")
        if not np.array_equal(final_model.predict(labeled), loaded.predict(labeled)):
            raise HierarchicalTrainingError("serialized H1 predictions changed after reload")
        _write_json(temporary_dir / "coefficients.json", final_model.get_coefficients())
        family_effects.to_csv(temporary_dir / "family_effects.csv", index=False)
        _write_json(temporary_dir / "nested_search.json", nested_search)
        bootstrap.predictions.to_parquet(
            temporary_dir / "bootstrap_summary.parquet", index=False, compression="zstd"
        )
        bootstrap.family_effects.to_parquet(
            temporary_dir / "bootstrap_family_effects.parquet",
            index=False,
            compression="zstd",
        )
        _write_json(temporary_dir / "bootstrap_metadata.json", bootstrap.metadata)
        all_predictions = pd.concat(
            [combined_predictions[protocol] for protocol in outer_protocols], ignore_index=True
        )
        all_predictions.to_csv(temporary_dir / "oof_predictions.csv", index=False)
        _write_json(temporary_dir / "split_manifest.json", split_manifest)
        _write_json(temporary_dir / "metrics.json", metrics)
        rank_audit.to_csv(temporary_dir / "rank_shift_audit.csv", index=False)
        _write_json(temporary_dir / "promotion_decision.json", promotion)
        fallback_checks = {
            "axis_a": bool(
                np.allclose(combined_predictions["leave_axis_a_out"]["axis_a_effect"], 0.0)
            ),
            "axis_b": bool(
                np.allclose(combined_predictions["leave_axis_b_out"]["axis_b_effect"], 0.0)
            ),
        }
        gate_checks = {
            "loocv_rows": len(combined_predictions["loocv"]) == config.expected_label_rows,
            "axis_a_rows": len(combined_predictions["leave_axis_a_out"])
            == config.expected_label_rows,
            "axis_b_rows": len(combined_predictions["leave_axis_b_out"])
            == config.expected_label_rows,
            "axis_a_unknown_zero": fallback_checks["axis_a"],
            "axis_b_unknown_zero": fallback_checks["axis_b"],
            "skeleton_inactive_zero": bool(
                family_effects.query("term == 'skeleton'")["effect_kcal"].eq(0.0).all()
            ),
            "nested_penalties_finite": all(
                np.isfinite(frame[["lambda_axis_a", "lambda_axis_b"]].to_numpy()).all()
                for frame in combined_predictions.values()
            ),
            "bootstrap_attempts_complete": bootstrap.metadata["successful_repeats"]
            + bootstrap.metadata["failed_repeats"]
            == config.bootstrap.final_repeats,
            "serialization_exact": True,
            "promotion_deferred": promotion["status"] == "deferred_to_phase4",
        }
        phase3_gate = {
            "status": "passed" if all(gate_checks.values()) else "failed",
            "checks": gate_checks,
            "rows": len(labeled),
            "selected_penalties": final_selection.selected.to_dict(),
        }
        _write_json(temporary_dir / "phase3_gate.json", phase3_gate)
        generate_hierarchical_figures(
            loocv=rank_audit,
            metrics=metrics,
            family_effects=family_effects,
            bootstrap_predictions=bootstrap.predictions,
            bootstrap_family_effects=bootstrap.family_effects,
            output_dir=temporary_dir / "figures",
            dataset_version=config.dataset_version,
            model_version=config.model_version,
        )
        output_hashes = {
            path.relative_to(temporary_dir).as_posix(): sha256_file(path)
            for path in sorted(temporary_dir.rglob("*"))
            if path.is_file()
        }
        model_manifest = {
            "dataset_version": config.dataset_version,
            "baseline_result_version": config.baseline_result_version,
            "model_name": config.model_name,
            "model_version": config.model_version,
            "seed": seed,
            "source_tree_sha256": sha256_source_tree(Path(__file__).parents[1]),
            "training_rows": len(labeled),
            "training_key_sha256": final_model.training_key_sha256_,
            "input_sha256": {
                **{f"dataset/{name}": digest for name, digest in dataset_hashes.items()},
                **{f"baselines/{name}": digest for name, digest in baseline_hashes.items()},
                "dataset_evidence": sha256_file(dataset_evidence_path),
                "baseline_evidence": sha256_file(baseline_evidence_path),
                "model_config": sha256_file(model_config_path),
                "evaluation_config": sha256_file(evaluation_config_path),
            },
            "output_sha256": output_hashes,
            "software": {
                "python": platform.python_version(),
                "numpy": version("numpy"),
                "pandas": version("pandas"),
                "scipy": version("scipy"),
                "matplotlib": version("matplotlib"),
                "joblib": version("joblib"),
            },
            "predictions": {
                "nested_outer_oof": True,
                "bootstrap_queries_oof": False,
                "bootstrap_query_scope": "71_labeled_rows_not_full_pool",
            },
        }
        _write_json(temporary_dir / "model_manifest.json", model_manifest)
        completion = {
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "dataset_version": config.dataset_version,
            "model_version": config.model_version,
            "rows": len(labeled),
            "status": phase3_gate["status"],
            "model_manifest_sha256": sha256_file(temporary_dir / "model_manifest.json"),
            "metrics_sha256": sha256_file(temporary_dir / "metrics.json"),
            "phase3_gate_sha256": sha256_file(temporary_dir / "phase3_gate.json"),
        }
        _write_json(temporary_dir / "_SUCCESS", completion)
        if phase3_gate["status"] != "passed":
            raise HierarchicalTrainingError("Phase 3 real-data gate failed")
        os.replace(temporary_dir, output_dir)
    except BaseException:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise
    return TrainHierarchicalResult(
        payload={
            **plan,
            "dry_run": False,
            "status": "complete",
            "rows": len(labeled),
            "phase3_gate": "passed",
            "selected_penalties": final_selection.selected.to_dict(),
            "bootstrap_successful": bootstrap.metadata["successful_repeats"],
            "bootstrap_failed": bootstrap.metadata["failed_repeats"],
            "output_files": sorted(
                path.relative_to(output_dir).as_posix()
                for path in output_dir.rglob("*")
                if path.is_file()
            ),
        }
    )
