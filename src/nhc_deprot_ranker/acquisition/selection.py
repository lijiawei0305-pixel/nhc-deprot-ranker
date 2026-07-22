"""Deterministic Phase 5 quota selection and local batch-manifest runner."""

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

from nhc_deprot_ranker.acquisition.diversity import (
    greedy_diverse_indices,
    static_diversity_score,
)
from nhc_deprot_ranker.acquisition.quotas import BUCKET_ORDER, largest_remainder_quotas
from nhc_deprot_ranker.config import AcquisitionConfig, load_acquisition_config
from nhc_deprot_ranker.data.provenance import sha256_file, sha256_source_tree
from nhc_deprot_ranker.models.base import ModelInputError, validated_keys
from nhc_deprot_ranker.reporting.scoring_plots import generate_acquisition_figures


class AcquisitionSelectionError(ValueError):
    """Phase 5 acquisition input, quota, or immutable-output contract failed."""


@dataclass(frozen=True)
class AcquisitionSelectionResult:
    """CLI-facing immutable acquisition result."""

    payload: dict[str, Any]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AcquisitionSelectionError(f"JSON root must be an object: {path.name}")
    return raw


def _verify_dataset_evidence(
    dataset_dir: Path, evidence_path: Path, dataset_version: str
) -> dict[str, str]:
    evidence = _read_json(evidence_path)
    if evidence.get("dataset_version") != dataset_version:
        raise AcquisitionSelectionError("dataset evidence version mismatch")
    hashes = evidence.get("output_sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise AcquisitionSelectionError("dataset evidence has no output hashes")
    verified: dict[str, str] = {}
    for name, expected in hashes.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise AcquisitionSelectionError("invalid dataset hash entry")
        actual = sha256_file(dataset_dir / name)
        if actual != expected:
            raise AcquisitionSelectionError(f"dataset input hash mismatch: {name}")
        verified[name] = actual
    return verified


def _verify_scoring(scored_results_dir: Path) -> dict[str, Any]:
    success = _read_json(scored_results_dir / "_SUCCESS")
    manifest = _read_json(scored_results_dir / "score_manifest.json")
    if success.get("status") != "passed":
        raise AcquisitionSelectionError("scoring result is not passed")
    if sha256_file(scored_results_dir / "score_manifest.json") != success.get(
        "score_manifest_sha256"
    ):
        raise AcquisitionSelectionError("score manifest hash mismatch")
    hashes = manifest.get("output_sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise AcquisitionSelectionError("score manifest has no output hashes")
    for name, expected in hashes.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise AcquisitionSelectionError("invalid score output hash entry")
        if sha256_file(scored_results_dir / name) != expected:
            raise AcquisitionSelectionError(f"score output hash mismatch: {name}")
    return manifest


def _normalize_absolute(values: pd.Series) -> np.ndarray:
    vector = np.abs(values.to_numpy(dtype=np.float64))
    maximum = float(vector.max()) if len(vector) else 0.0
    return vector / maximum if maximum > 0.0 else np.zeros(len(vector), dtype=np.float64)


def acquisition_component_frame(scored: pd.DataFrame, config: AcquisitionConfig) -> pd.DataFrame:
    """Add normalized acquisition components without selecting rows."""

    required = {
        "inchikey",
        "production_rank",
        "xtb_rank",
        "rank_shift",
        "prediction_interval_width_kcal",
        f"probability_top_{config.top_k}",
        "axis_a_seen_in_training",
        "axis_b_seen_in_training",
        "axis_a_label_count",
        "axis_b_label_count",
        "baseline_in_training_range",
        "high_uncertainty",
        "combined_family",
        *config.diversity_fields,
    }
    missing = sorted(required - set(scored.columns))
    if missing:
        raise ModelInputError(f"scored acquisition columns are missing: {missing}")
    frame = scored.copy()
    frame["top_component"] = frame[f"probability_top_{config.top_k}"].astype(float)
    frame["uncertainty_component"] = frame["prediction_interval_width_kcal"].rank(
        method="average", pct=True
    )
    frame["rank_shift_component"] = _normalize_absolute(frame["rank_shift"])
    unseen_a = ~frame["axis_a_seen_in_training"].astype(bool)
    unseen_b = ~frame["axis_b_seen_in_training"].astype(bool)
    unseen_count = unseen_a.astype(int) + unseen_b.astype(int)
    minimum_support = frame[["axis_a_label_count", "axis_b_label_count"]].min(axis=1)
    supported_novelty = 0.5 * np.clip(
        1.0 - minimum_support.to_numpy(dtype=np.float64) / config.sparse_family_min_support,
        0.0,
        1.0,
    )
    frame["family_novelty_component"] = np.where(
        unseen_count.eq(2), 1.0, np.where(unseen_count.eq(1), 0.5, supported_novelty)
    )
    distance = np.abs(frame["production_rank"].to_numpy(dtype=np.float64) - config.cutoff_rank)
    frame["cutoff_component"] = np.clip(1.0 - distance / config.cutoff_window, 0.0, 1.0)
    frame["diversity_component"] = static_diversity_score(frame, config.diversity_fields)
    weights = config.weights
    frame["acquisition_score"] = (
        weights.top * frame["top_component"]
        + weights.uncertainty * frame["uncertainty_component"]
        + weights.rank_shift * frame["rank_shift_component"]
        + weights.family_novelty * frame["family_novelty_component"]
        + weights.cutoff * frame["cutoff_component"]
        + weights.diversity * frame["diversity_component"]
    )
    components = frame[
        [
            "top_component",
            "uncertainty_component",
            "rank_shift_component",
            "family_novelty_component",
            "cutoff_component",
            "diversity_component",
        ]
    ].to_numpy(dtype=np.float64)
    if not np.isfinite(components).all() or np.any(components < 0.0) or np.any(components > 1.0):
        raise ModelInputError("normalized acquisition components must be finite in [0,1]")
    return frame


def _bucket_mask(frame: pd.DataFrame, bucket: str, config: AcquisitionConfig) -> pd.Series:
    if bucket == "predicted_top_region":
        return frame["production_rank"].le(config.top_region_max_rank)
    if bucket == "cutoff_region":
        return frame["production_rank"].sub(config.cutoff_rank).abs().le(config.cutoff_window)
    if bucket == "chemical_family_diversity":
        return pd.Series(True, index=frame.index)
    if bucket == "uncertain_ood_conflict":
        return (
            ~frame["baseline_in_training_range"].astype(bool)
            | ~frame["axis_a_seen_in_training"].astype(bool)
            | ~frame["axis_b_seen_in_training"].astype(bool)
            | frame["high_uncertainty"].astype(bool)
            | frame["rank_shift"].ne(0)
        )
    raise ValueError(f"unknown acquisition bucket: {bucket}")


def _stable_best(frame: pd.DataFrame, count: int) -> list[int]:
    ranked = frame.sort_values(
        ["acquisition_score", "production_rank", "inchikey"],
        ascending=[False, True, True],
        kind="mergesort",
    )
    return [int(index) for index in ranked.head(count).index]


def select_acquisition_batch(
    *, scored: pd.DataFrame, labeled_keys: set[str], config: AcquisitionConfig
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Select exact deterministic quota counts from unlabeled scored rows."""

    validated_keys(scored["inchikey"].astype(str).tolist(), expected_size=len(scored))
    frame = acquisition_component_frame(scored, config)
    eligible = frame.loc[~frame["inchikey"].astype(str).isin(labeled_keys)].copy()
    excluded_labeled = len(frame) - len(eligible)
    if excluded_labeled != len(labeled_keys):
        raise ModelInputError("not every labeled key was excluded exactly once")
    quotas = largest_remainder_quotas(config)
    selected_indices: list[int] = []
    selected_buckets: dict[int, str] = {}
    fills: dict[str, int] = {}
    for bucket in BUCKET_ORDER:
        count = quotas[bucket]
        available = eligible.loc[~eligible.index.isin(selected_indices)]
        pool = available.loc[_bucket_mask(available, bucket, config)]
        if bucket == "chemical_family_diversity":
            chosen = greedy_diverse_indices(
                pool,
                count=min(count, len(pool)),
                fields=config.diversity_fields,
                base_score_column="acquisition_score",
                diversity_weight=config.weights.diversity,
            )
        else:
            chosen = _stable_best(pool, min(count, len(pool)))
        fill_count = count - len(chosen)
        if fill_count:
            remaining = available.loc[~available.index.isin(chosen)]
            chosen.extend(_stable_best(remaining, fill_count))
        fills[bucket] = fill_count
        for index in chosen:
            selected_indices.append(index)
            selected_buckets[index] = bucket
    if len(selected_indices) != config.acquisition_batch_size or len(set(selected_indices)) != len(
        selected_indices
    ):
        raise ModelInputError("acquisition batch size or uniqueness failed")
    selected = eligible.loc[selected_indices].copy()
    selected["acquisition_bucket"] = [selected_buckets[int(index)] for index in selected.index]
    selected = selected.sort_values(
        ["acquisition_score", "production_rank", "inchikey"],
        ascending=[False, True, True],
        kind="mergesort",
    ).reset_index(drop=True)
    selected["predicted_rank"] = selected["production_rank"]
    selected["prediction_interval"] = [
        f"[{low:.6f}, {high:.6f}]"
        for low, high in zip(selected["prediction_p05"], selected["prediction_p95"], strict=True)
    ]
    selected["family"] = selected["combined_family"]
    reason_codes: list[str] = []
    for raw_row in selected.to_dict("records"):
        row = {str(key): value for key, value in raw_row.items()}
        reasons = [str(row["acquisition_bucket"])]
        if int(row["production_rank"]) <= config.top_region_max_rank:
            reasons.append("predicted_top_region")
        if abs(int(row["production_rank"]) - config.cutoff_rank) <= config.cutoff_window:
            reasons.append("cutoff_proximity")
        if not bool(row["baseline_in_training_range"]):
            reasons.append("baseline_extrapolation")
        if not bool(row["axis_a_seen_in_training"]):
            reasons.append("unseen_axis_a")
        if not bool(row["axis_b_seen_in_training"]):
            reasons.append("unseen_axis_b")
        if bool(row["sparse_family"]):
            reasons.append("sparse_family")
        if bool(row["high_uncertainty"]):
            reasons.append("high_uncertainty")
        if int(row["rank_shift"]) == 0:
            reasons.append("rank_shift_zero_by_positive_affine")
        reason_codes.append(";".join(dict.fromkeys(reasons)))
    selected["reason_codes"] = reason_codes
    selected["suggested_priority"] = selected["acquisition_bucket"].map(
        {
            "predicted_top_region": "high",
            "cutoff_region": "high",
            "chemical_family_diversity": "medium",
            "uncertain_ood_conflict": "high",
        }
    )
    realized = selected["acquisition_bucket"].value_counts().to_dict()
    if any(int(realized.get(bucket, 0)) != quotas[bucket] for bucket in BUCKET_ORDER):
        raise ModelInputError("realized acquisition quotas differ from registered quotas")
    summary = {
        "eligible_unlabeled": len(eligible),
        "excluded_labeled": excluded_labeled,
        "selected": len(selected),
        "quotas": quotas,
        "realized_quotas": {bucket: int(realized.get(bucket, 0)) for bucket in BUCKET_ORDER},
        "quota_fill_counts": fills,
        "unique_keys": int(selected["inchikey"].nunique()),
        "unique_combined_families": int(selected["combined_family"].nunique()),
        "unique_axis_a_families": int(selected["axis_a_family"].nunique()),
        "unique_axis_b_families": int(selected["axis_b_family"].nunique()),
        "baseline_extrapolation": int((~selected["baseline_in_training_range"]).sum()),
        "size_unavailable": int((~selected["size_available"]).sum()),
        "unseen_axis_a": int((~selected["axis_a_seen_in_training"]).sum()),
        "unseen_axis_b": int((~selected["axis_b_seen_in_training"]).sum()),
        "high_uncertainty": int(selected["high_uncertainty"].sum()),
        "nonzero_rank_shift": int(selected["rank_shift"].ne(0).sum()),
        "submit_hpc": False,
    }
    return selected, summary


def acquire_candidates(
    *,
    dataset_dir: Path,
    scored_results_dir: Path,
    acquisition_config_path: Path,
    dataset_evidence_path: Path,
    output_dir: Path,
    seed: int,
    dry_run: bool = False,
    overwrite: bool = False,
) -> AcquisitionSelectionResult:
    """Create an immutable local high-fidelity suggestion batch without external action."""

    config: AcquisitionConfig = load_acquisition_config(acquisition_config_path)
    if dataset_dir.name != config.dataset_version:
        raise AcquisitionSelectionError("dataset version does not match acquisition config")
    if scored_results_dir.name != f"scoring_{config.version}":
        raise AcquisitionSelectionError("scored result version does not match config")
    if output_dir.name != f"acquisition_{config.version}":
        raise AcquisitionSelectionError("acquisition output directory name does not match config")
    if output_dir.exists():
        raise AcquisitionSelectionError(
            f"immutable acquisition result already exists: {output_dir}"
        )
    if overwrite:
        raise AcquisitionSelectionError(
            "--overwrite cannot replace an immutable acquisition result"
        )
    if seed != config.seed:
        raise AcquisitionSelectionError("CLI seed must equal the registered acquisition seed")
    plan = {
        "command": "acquire",
        "dataset_version": config.dataset_version,
        "acquisition_version": config.version,
        "batch_size": config.acquisition_batch_size,
        "output_dir": str(output_dir),
        "dry_run": dry_run,
        "exclude_already_labeled": True,
        "submit_hpc": False,
        "hpc_connection": False,
        "quantum_chemistry": False,
        "seed": seed,
    }
    if dry_run:
        return AcquisitionSelectionResult(payload=plan)

    dataset_hashes = _verify_dataset_evidence(
        dataset_dir, dataset_evidence_path, config.dataset_version
    )
    score_manifest = _verify_scoring(scored_results_dir)
    if score_manifest.get("ranking_model") != "B0_raw_xTB":
        raise AcquisitionSelectionError("acquisition requires B0 production scoring")
    scored = pd.read_parquet(scored_results_dir / "full_ranked_candidates.parquet")
    labels = pd.read_parquet(dataset_dir / "labels.parquet")
    labeled_keys = set(labels["inchikey"].astype(str))
    selected, summary = select_acquisition_batch(
        scored=scored, labeled_keys=labeled_keys, config=config
    )
    protocol_manifest = _read_json(dataset_dir / "protocol_manifest.json")
    protocol = protocol_manifest.get("protocol")
    if not isinstance(protocol, dict):
        raise AcquisitionSelectionError("dataset protocol manifest is invalid")
    batch_records: list[dict[str, Any]] = []
    for raw_row in selected.to_dict("records"):
        row = {str(key): value for key, value in raw_row.items()}
        batch_records.append(
            {
                "inchikey": str(row["inchikey"]),
                "smiles_cation": str(row["smiles_cation"]),
                "smiles_neutral": str(row["smiles_neutral"]),
                "suggested_priority": str(row["suggested_priority"]),
                "acquisition_bucket": str(row["acquisition_bucket"]),
                "reason_codes": str(row["reason_codes"]).split(";"),
                "production_rank": int(row["production_rank"]),
                "xtb_deprot_kcal": float(row["xtb_deprot_kcal"]),
                "calibrated_dft_deprot_kcal": float(row["calibrated_dft_deprot_kcal"]),
                "prediction_p05": float(row["prediction_p05"]),
                "prediction_p95": float(row["prediction_p95"]),
            }
        )
    batch_manifest = {
        "manifest_type": "local_high_fidelity_suggestion_only",
        "dataset_version": config.dataset_version,
        "acquisition_version": config.version,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "target_reaction": "NHC-H+ -> NHC + H+",
        "lower_is_better": True,
        "protocol": protocol,
        "hessian_computed": False,
        "submit_hpc": False,
        "server_write_authorized": False,
        "candidate_count": len(batch_records),
        "candidates": batch_records,
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(
        tempfile.mkdtemp(prefix=f".acquisition_{config.version}.tmp.", dir=output_dir.parent)
    )
    try:
        selected.to_csv(temporary_dir / "acquisition_candidates.csv", index=False)
        _write_json(temporary_dir / "high_fidelity_batch_manifest.json", batch_manifest)
        _write_json(temporary_dir / "acquisition_summary.json", summary)
        generate_acquisition_figures(
            selected=selected,
            output_dir=temporary_dir / "figures",
            dataset_version=config.dataset_version,
            acquisition_version=config.version,
        )
        output_hashes = {
            path.relative_to(temporary_dir).as_posix(): sha256_file(path)
            for path in sorted(temporary_dir.rglob("*"))
            if path.is_file()
        }
        input_hashes = {
            **{f"dataset/{name}": digest for name, digest in dataset_hashes.items()},
            "dataset_evidence": sha256_file(dataset_evidence_path),
            "score_manifest": sha256_file(scored_results_dir / "score_manifest.json"),
            "scored_candidates": sha256_file(scored_results_dir / "full_ranked_candidates.parquet"),
            "acquisition_config": sha256_file(acquisition_config_path),
        }
        acquisition_manifest = {
            "dataset_version": config.dataset_version,
            "acquisition_version": config.version,
            "ranking_model": "B0_raw_xTB",
            "batch_size": len(selected),
            "submit_hpc": False,
            "source_tree_sha256": sha256_source_tree(Path(__file__).parents[1]),
            "input_sha256": input_hashes,
            "output_sha256": output_hashes,
            "summary": summary,
        }
        _write_json(temporary_dir / "acquisition_manifest.json", acquisition_manifest)
        completion = {
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "dataset_version": config.dataset_version,
            "acquisition_version": config.version,
            "status": "passed",
            "selected": len(selected),
            "submit_hpc": False,
            "acquisition_manifest_sha256": sha256_file(temporary_dir / "acquisition_manifest.json"),
            "candidate_csv_sha256": sha256_file(temporary_dir / "acquisition_candidates.csv"),
        }
        _write_json(temporary_dir / "_SUCCESS", completion)
        os.replace(temporary_dir, output_dir)
    except BaseException:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise
    return AcquisitionSelectionResult(
        payload={
            **plan,
            "dry_run": False,
            "status": "complete",
            "selected": len(selected),
            "quotas": summary["realized_quotas"],
            "output_files": sorted(
                path.relative_to(output_dir).as_posix()
                for path in output_dir.rglob("*")
                if path.is_file()
            ),
        }
    )
