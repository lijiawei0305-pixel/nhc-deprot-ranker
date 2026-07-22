"""B0 production scoring with an explicitly separate B1 uncertainty companion."""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from nhc_deprot_ranker.config import AcquisitionConfig, load_acquisition_config
from nhc_deprot_ranker.data.provenance import sha256_file, sha256_source_tree
from nhc_deprot_ranker.models.base import ModelInputError, key_set_sha256, validated_keys
from nhc_deprot_ranker.reporting.scoring_plots import generate_scoring_figures


class FullScoringError(ValueError):
    """Phase 5 full-pool scoring contract failed."""


@dataclass(frozen=True)
class AffineUncertainty:
    """Chunked B1 coefficient-bootstrap summaries at query x values."""

    mean: np.ndarray
    standard_deviation: np.ndarray
    p05: np.ndarray
    p50: np.ndarray
    p95: np.ndarray


@dataclass(frozen=True)
class FullScoringResult:
    """CLI-facing immutable full-score result."""

    payload: dict[str, Any]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise FullScoringError(f"JSON root must be an object: {path.name}")
    return raw


def _verify_evidence(
    root: Path, evidence_path: Path, expected_version: str
) -> tuple[dict[str, str], dict[str, Any]]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    evidence = _read_json(evidence_path)
    if evidence.get("dataset_version") != expected_version:
        raise FullScoringError(f"evidence version mismatch for {root.name}")
    hashes = evidence.get("output_sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise FullScoringError(f"evidence has no output hashes: {evidence_path.name}")
    verified: dict[str, str] = {}
    for name, expected in hashes.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise FullScoringError("invalid evidence hash entry")
        actual = sha256_file(root / name)
        if actual != expected:
            raise FullScoringError(f"input hash mismatch for {root.name}/{name}")
        verified[name] = actual
    return verified, evidence


def affine_bootstrap_uncertainty(
    x: np.ndarray,
    bootstrap_coefficients: pd.DataFrame,
    *,
    chunk_rows: int,
) -> AffineUncertainty:
    """Apply stored affine coefficient replicates in bounded row chunks."""

    vector = np.asarray(x, dtype=np.float64)
    if vector.ndim != 1 or vector.size == 0 or not np.isfinite(vector).all():
        raise ModelInputError("B1 uncertainty queries must be a finite nonempty vector")
    if chunk_rows < 1:
        raise ValueError("chunk_rows must be positive")
    required = {"beta_0", "rho"}
    missing = sorted(required - set(bootstrap_coefficients.columns))
    if missing:
        raise ModelInputError(f"B1 bootstrap coefficients are missing: {missing}")
    beta = bootstrap_coefficients["beta_0"].to_numpy(dtype=np.float64)
    rho = bootstrap_coefficients["rho"].to_numpy(dtype=np.float64)
    if beta.size == 0 or beta.size != rho.size:
        raise ModelInputError("B1 bootstrap coefficient lengths are invalid")
    if not np.isfinite(beta).all() or not np.isfinite(rho).all():
        raise ModelInputError("B1 bootstrap coefficients must be finite")
    if np.any(rho <= 0.0):
        raise ModelInputError("B1 Top-K invariance requires every bootstrap slope to be positive")
    mean = np.empty(len(vector), dtype=np.float64)
    standard_deviation = np.empty(len(vector), dtype=np.float64)
    p05 = np.empty(len(vector), dtype=np.float64)
    p50 = np.empty(len(vector), dtype=np.float64)
    p95 = np.empty(len(vector), dtype=np.float64)
    for start in range(0, len(vector), chunk_rows):
        stop = min(start + chunk_rows, len(vector))
        predictions = beta[:, None] + rho[:, None] * vector[None, start:stop]
        mean[start:stop] = np.mean(predictions, axis=0)
        standard_deviation[start:stop] = np.std(predictions, axis=0, ddof=1)
        quantiles = np.quantile(predictions, [0.05, 0.5, 0.95], axis=0)
        p05[start:stop], p50[start:stop], p95[start:stop] = quantiles
    return AffineUncertainty(
        mean=mean,
        standard_deviation=standard_deviation,
        p05=p05,
        p50=p50,
        p95=p95,
    )


def _append_status(status: pd.Series, mask: pd.Series, label: str) -> None:
    empty = status.eq("") & mask
    nonempty = status.ne("") & mask
    status.loc[empty] = label
    status.loc[nonempty] = status.loc[nonempty] + ";" + label


def score_candidate_frame(
    *,
    candidates: pd.DataFrame,
    labels: pd.DataFrame,
    coefficients: dict[str, Any],
    bootstrap_coefficients: pd.DataFrame,
    config: AcquisitionConfig,
    production_model_sha256: str,
    decision_manifest_sha256: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build the full B0-ranked table with separate B1 companion fields."""

    required = {
        "inchikey",
        "smiles_cation",
        "smiles_neutral",
        "xtb_deprot_kcal",
        "xtb_rank",
        "xtb_percentile",
        "n1_frag",
        "n3_frag",
        "c4_frag",
        "c5_frag",
        "skeleton",
        "axis_a_family",
        "axis_b_family",
        "combined_family",
        "n_heavy_atoms",
        "n_electrons",
    }
    missing = sorted(required - set(candidates.columns))
    if missing:
        raise ModelInputError(f"candidate scoring columns are missing: {missing}")
    keys = validated_keys(
        candidates["inchikey"].astype(str).tolist(), expected_size=len(candidates)
    )
    label_keys = validated_keys(labels["inchikey"].astype(str).tolist(), expected_size=len(labels))
    if not set(label_keys).issubset(keys):
        raise ModelInputError("labeled keys are not a subset of candidates")
    x = candidates["xtb_deprot_kcal"].to_numpy(dtype=np.float64)
    if not np.isfinite(x).all():
        raise ModelInputError("candidate xTB scores must be finite")
    ordered = candidates.sort_values(
        ["xtb_deprot_kcal", "inchikey"], ascending=[True, True], kind="mergesort"
    ).reset_index(drop=True)
    expected_rank = np.arange(1, len(ordered) + 1, dtype=np.int64)
    if not np.array_equal(ordered["xtb_rank"].to_numpy(dtype=np.int64), expected_rank):
        raise ModelInputError("stored xTB ranks do not match deterministic lower-is-better order")
    expected_percentile = (expected_rank - 1) / max(len(ordered) - 1, 1)
    if not np.allclose(
        ordered["xtb_percentile"].to_numpy(dtype=np.float64), expected_percentile, atol=1e-12
    ):
        raise ModelInputError("stored xTB percentiles do not match deterministic ranks")

    b1 = coefficients.get("B1")
    if not isinstance(b1, dict):
        raise ModelInputError("B1 coefficients are unavailable")
    beta_0 = float(b1["beta_0"])
    rho = float(b1["rho"])
    x_min = float(b1["x_min"])
    x_max = float(b1["x_max"])
    if not all(math.isfinite(value) for value in (beta_0, rho, x_min, x_max)) or rho <= 0.0:
        raise ModelInputError("B1 companion coefficients/range are invalid")
    ordered_x = ordered["xtb_deprot_kcal"].to_numpy(dtype=np.float64)
    uncertainty = affine_bootstrap_uncertainty(
        ordered_x, bootstrap_coefficients, chunk_rows=config.bootstrap_chunk_rows
    )
    label_x = ordered.loc[ordered["inchikey"].isin(label_keys), "xtb_deprot_kcal"].to_numpy(
        dtype=np.float64
    )
    label_uncertainty = affine_bootstrap_uncertainty(
        label_x, bootstrap_coefficients, chunk_rows=config.bootstrap_chunk_rows
    )
    uncertainty_width = uncertainty.p95 - uncertainty.p05
    label_width = label_uncertainty.p95 - label_uncertainty.p05
    high_uncertainty_threshold = float(np.quantile(label_width, config.high_uncertainty_quantile))

    labeled_candidates = ordered.loc[ordered["inchikey"].isin(label_keys)]
    skeleton_support = labeled_candidates["skeleton"].astype(str).value_counts()
    axis_a_support = labeled_candidates["axis_a_family"].astype(str).value_counts()
    axis_b_support = labeled_candidates["axis_b_family"].astype(str).value_counts()
    result = ordered.copy()
    result["production_score_kcal"] = ordered_x
    result["production_rank"] = expected_rank
    result["production_percentile"] = expected_percentile
    result["calibrated_dft_deprot_kcal"] = beta_0 + rho * ordered_x
    result["calibrated_rank"] = expected_rank
    result["calibrated_percentile"] = expected_percentile
    result["prediction_mean_kcal"] = uncertainty.mean
    result["prediction_std_kcal"] = uncertainty.standard_deviation
    result["prediction_p05"] = uncertainty.p05
    result["prediction_p50"] = uncertainty.p50
    result["prediction_p95"] = uncertainty.p95
    result["prediction_interval_width_kcal"] = uncertainty_width
    for top_k in config.probability_top_k:
        result[f"probability_top_{top_k}"] = (expected_rank <= top_k).astype(np.float64)
    result["rank_shift"] = np.zeros(len(result), dtype=np.int64)
    result["global_component"] = result["calibrated_dft_deprot_kcal"]
    result["skeleton_component"] = 0.0
    result["axis_a_component"] = 0.0
    result["axis_b_component"] = 0.0

    result["skeleton_label_count"] = (
        result["skeleton"].astype(str).map(skeleton_support).fillna(0).astype(int)
    )
    result["axis_a_label_count"] = (
        result["axis_a_family"].astype(str).map(axis_a_support).fillna(0).astype(int)
    )
    result["axis_b_label_count"] = (
        result["axis_b_family"].astype(str).map(axis_b_support).fillna(0).astype(int)
    )
    result["skeleton_seen_in_training"] = result["skeleton_label_count"].gt(0)
    result["axis_a_seen_in_training"] = result["axis_a_label_count"].gt(0)
    result["axis_b_seen_in_training"] = result["axis_b_label_count"].gt(0)
    result["family_seen_in_training"] = (
        result["axis_a_seen_in_training"] & result["axis_b_seen_in_training"]
    )
    result["baseline_in_training_range"] = result["xtb_deprot_kcal"].between(x_min, x_max)
    result["size_available"] = result["n_heavy_atoms"].notna() & result["n_electrons"].notna()
    result["sparse_family"] = result["axis_a_label_count"].between(
        1, config.sparse_family_min_support - 1
    ) | result["axis_b_label_count"].between(1, config.sparse_family_min_support - 1)
    result["high_uncertainty"] = result["prediction_interval_width_kcal"].gt(
        high_uncertainty_threshold
    )
    result["extrapolation_flag"] = ~result["baseline_in_training_range"]
    result["core_model_in_domain"] = (
        result["baseline_in_training_range"]
        & result["family_seen_in_training"]
        & ~result["sparse_family"]
        & ~result["high_uncertainty"]
    )
    status = pd.Series("", index=result.index, dtype="string")
    _append_status(status, ~result["baseline_in_training_range"], "baseline_extrapolation")
    _append_status(status, ~result["size_available"], "size_unavailable")
    _append_status(status, ~result["axis_a_seen_in_training"], "unseen_axis_a")
    _append_status(status, ~result["axis_b_seen_in_training"], "unseen_axis_b")
    _append_status(status, result["sparse_family"], "sparse_family")
    _append_status(status, result["high_uncertainty"], "high_uncertainty")
    status.loc[status.eq("")] = "in_domain"
    result["applicability_status"] = status
    result["ranking_model"] = "B0_raw_xTB"
    result["calibration_model"] = "B1_global_affine_companion"
    result["uncertainty_scope"] = "B1_coefficient_bootstrap_only"
    result["model_version"] = config.version
    result["model_sha256"] = production_model_sha256
    result["decision_manifest_sha256"] = decision_manifest_sha256
    result["dataset_version"] = config.dataset_version
    if (
        not np.array_equal(
            result["calibrated_rank"].to_numpy(dtype=np.int64),
            result["production_rank"].to_numpy(dtype=np.int64),
        )
        or not result["rank_shift"].eq(0).all()
    ):
        raise ModelInputError("positive B1 companion must preserve every B0 rank")
    summary = {
        "rows": len(result),
        "unique_keys": int(result["inchikey"].nunique()),
        "ranking_model": "B0_raw_xTB",
        "calibration_model": "B1_global_affine_companion",
        "B1_beta_0": beta_0,
        "B1_rho": rho,
        "B1_bootstrap_repeats": len(bootstrap_coefficients),
        "B1_bootstrap_rho_min": float(bootstrap_coefficients["rho"].min()),
        "B1_bootstrap_rho_max": float(bootstrap_coefficients["rho"].max()),
        "rank_shift_nonzero": int(result["rank_shift"].ne(0).sum()),
        "baseline_training_range": [x_min, x_max],
        "baseline_extrapolation": int((~result["baseline_in_training_range"]).sum()),
        "size_unavailable": int((~result["size_available"]).sum()),
        "unseen_axis_a": int((~result["axis_a_seen_in_training"]).sum()),
        "unseen_axis_b": int((~result["axis_b_seen_in_training"]).sum()),
        "both_axes_seen": int(result["family_seen_in_training"].sum()),
        "sparse_family": int(result["sparse_family"].sum()),
        "high_uncertainty": int(result["high_uncertainty"].sum()),
        "high_uncertainty_interval_width_threshold_kcal": high_uncertainty_threshold,
        "fully_in_domain": int(result["applicability_status"].eq("in_domain").sum()),
        "core_model_in_domain": int(result["core_model_in_domain"].sum()),
        "uncertainty_scope": "B1_coefficient_bootstrap_only",
    }
    return result, summary


def score_full_pool(
    *,
    dataset_dir: Path,
    baseline_results_dir: Path,
    decision_results_dir: Path,
    acquisition_config_path: Path,
    dataset_evidence_path: Path,
    baseline_evidence_path: Path,
    decision_evidence_path: Path,
    output_dir: Path,
    seed: int,
    dry_run: bool = False,
    overwrite: bool = False,
) -> FullScoringResult:
    """Create one immutable full-pool score result without model fitting."""

    config = load_acquisition_config(acquisition_config_path)
    if dataset_dir.name != config.dataset_version:
        raise FullScoringError("dataset directory version does not match acquisition config")
    if baseline_results_dir.name != f"baselines_{config.dataset_version}":
        raise FullScoringError("baseline result version does not match acquisition config")
    if decision_results_dir.name != f"decision_{config.dataset_version}":
        raise FullScoringError("decision result version does not match acquisition config")
    if output_dir.name != f"scoring_{config.version}":
        raise FullScoringError("score output directory name does not match config version")
    if output_dir.exists():
        raise FullScoringError(f"immutable scoring result already exists: {output_dir}")
    if overwrite:
        raise FullScoringError("--overwrite cannot replace an immutable scoring result")
    if seed != config.seed:
        raise FullScoringError("CLI seed must equal the registered acquisition seed")
    plan = {
        "command": "score",
        "dataset_version": config.dataset_version,
        "score_version": config.version,
        "output_dir": str(output_dir),
        "dry_run": dry_run,
        "ranking_model": "B0_raw_xTB",
        "calibration_companion": "B1_global_affine",
        "rows_expected": 401856,
        "model_refit": False,
        "H1_used": False,
        "size_derived": False,
        "hpc_connection": False,
        "quantum_chemistry": False,
        "seed": seed,
    }
    if dry_run:
        return FullScoringResult(payload=plan)

    dataset_hashes, dataset_evidence = _verify_evidence(
        dataset_dir, dataset_evidence_path, config.dataset_version
    )
    baseline_hashes, _baseline_evidence = _verify_evidence(
        baseline_results_dir, baseline_evidence_path, config.dataset_version
    )
    decision_hashes, decision_evidence = _verify_evidence(
        decision_results_dir, decision_evidence_path, config.dataset_version
    )
    decision = _read_json(decision_results_dir / "promotion_decision.json")
    if (
        decision.get("outcome") != "raw_xTB_wins"
        or decision.get("production_default") != "B0_raw_xTB"
    ):
        raise FullScoringError("Phase 5 requires the frozen raw_xTB_wins decision")
    expected_rows = int(dataset_evidence.get("rows", {}).get("candidates", -1))
    if config.dataset_version == "v001" and expected_rows != 401856:
        raise FullScoringError("Phase 5 requires the audited 401,856-row candidate dataset")
    candidates = pd.read_parquet(dataset_dir / "candidates.parquet")
    labels = pd.read_parquet(dataset_dir / "labels.parquet")
    coefficients = _read_json(baseline_results_dir / "coefficients.json")
    bootstrap_coefficients = pd.read_parquet(baseline_results_dir / "bootstrap_summary.parquet")
    production_model_sha256 = sha256_file(baseline_results_dir / "model.pkl")
    decision_manifest_sha256 = sha256_file(decision_results_dir / "decision_manifest.json")
    if decision_manifest_sha256 != decision_evidence.get("decision_manifest_sha256"):
        raise FullScoringError("Phase 4 decision-manifest identity mismatch")
    scored, summary = score_candidate_frame(
        candidates=candidates,
        labels=labels,
        coefficients=coefficients,
        bootstrap_coefficients=bootstrap_coefficients,
        config=config,
        production_model_sha256=production_model_sha256,
        decision_manifest_sha256=decision_manifest_sha256,
    )
    if len(scored) != expected_rows:
        raise FullScoringError("full scoring row count changed")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(
        tempfile.mkdtemp(prefix=f".scoring_{config.version}.tmp.", dir=output_dir.parent)
    )
    try:
        scored.to_parquet(
            temporary_dir / "full_ranked_candidates.parquet",
            index=False,
            compression="zstd",
        )
        scored.head(config.score_top_n).to_csv(temporary_dir / "top_candidates.csv", index=False)
        _write_json(temporary_dir / "applicability_summary.json", summary)
        generate_scoring_figures(
            scored=scored,
            summary=summary,
            output_dir=temporary_dir / "figures",
            dataset_version=config.dataset_version,
            score_version=config.version,
        )
        output_hashes = {
            path.relative_to(temporary_dir).as_posix(): sha256_file(path)
            for path in sorted(temporary_dir.rglob("*"))
            if path.is_file()
        }
        input_hashes = {
            **{f"dataset/{name}": digest for name, digest in dataset_hashes.items()},
            **{f"baselines/{name}": digest for name, digest in baseline_hashes.items()},
            **{f"decision/{name}": digest for name, digest in decision_hashes.items()},
            "dataset_evidence": sha256_file(dataset_evidence_path),
            "baseline_evidence": sha256_file(baseline_evidence_path),
            "decision_evidence": sha256_file(decision_evidence_path),
            "acquisition_config": sha256_file(acquisition_config_path),
        }
        score_manifest = {
            "dataset_version": config.dataset_version,
            "score_version": config.version,
            "rows": len(scored),
            "training_key_sha256": decision_evidence.get("training_key_sha256"),
            "candidate_key_sha256": key_set_sha256(scored["inchikey"].astype(str).tolist()),
            "ranking_model": "B0_raw_xTB",
            "calibration_companion": "B1_global_affine",
            "production_model_sha256": production_model_sha256,
            "decision_manifest_sha256": decision_manifest_sha256,
            "source_tree_sha256": sha256_source_tree(Path(__file__).parents[1]),
            "input_sha256": input_hashes,
            "output_sha256": output_hashes,
            "summary": summary,
        }
        _write_json(temporary_dir / "score_manifest.json", score_manifest)
        completion = {
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "dataset_version": config.dataset_version,
            "score_version": config.version,
            "rows": len(scored),
            "status": "passed",
            "ranking_model": "B0_raw_xTB",
            "score_manifest_sha256": sha256_file(temporary_dir / "score_manifest.json"),
            "full_ranked_candidates_sha256": sha256_file(
                temporary_dir / "full_ranked_candidates.parquet"
            ),
        }
        _write_json(temporary_dir / "_SUCCESS", completion)
        os.replace(temporary_dir, output_dir)
    except BaseException:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise
    return FullScoringResult(
        payload={
            **plan,
            "dry_run": False,
            "status": "complete",
            "rows": len(scored),
            "top_rows": config.score_top_n,
            "baseline_extrapolation": summary["baseline_extrapolation"],
            "size_unavailable": summary["size_unavailable"],
            "output_files": sorted(
                path.relative_to(output_dir).as_posix()
                for path in output_dir.rglob("*")
                if path.is_file()
            ),
        }
    )
