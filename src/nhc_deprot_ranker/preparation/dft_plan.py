"""Build an immutable local DFT handoff plan without geometry or execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from nhc_deprot_ranker.config import DFTPlanConfig, load_dft_plan_config
from nhc_deprot_ranker.data.provenance import sha256_file, sha256_source_tree
from nhc_deprot_ranker.models.base import key_set_sha256, validated_keys

INCHIKEY_PATTERN = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
FORBIDDEN_OUTPUT_SUFFIXES = {".xyz", ".molden", ".sh", ".pbs", ".slurm"}
FORBIDDEN_OUTPUT_NAMES = {"freq.json"}


class DFTPlanError(ValueError):
    """The Phase 6 local-plan contract failed."""


@dataclass(frozen=True)
class DFTPlanResult:
    """CLI-facing Phase 6 result."""

    payload: dict[str, Any]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise DFTPlanError(f"JSON root must be an object: {path.name}")
    return raw


def _ordered_key_sha256(keys: list[str]) -> str:
    validated = validated_keys(keys, expected_size=len(keys))
    return hashlib.sha256(("\n".join(validated) + "\n").encode()).hexdigest()


def _safe_registered_file(root: Path, name: str) -> Path:
    """Resolve one registered input artifact without traversal or symlinks."""

    if not isinstance(name, str) or not name or name.strip() != name:
        raise DFTPlanError("invalid registered evidence path")
    registered = Path(name)
    if (
        registered.is_absolute()
        or ".." in registered.parts
        or registered.as_posix() != name
        or "\\" in name
    ):
        raise DFTPlanError(f"unsafe registered evidence path: {name}")
    candidate = root / registered
    current = root
    for part in registered.parts:
        current /= part
        if current.is_symlink():
            raise DFTPlanError(f"registered evidence path is a symlink: {name}")
    try:
        root_resolved = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except FileNotFoundError:
        raise
    except ValueError as exc:
        raise DFTPlanError(f"registered evidence path escapes its root: {name}") from exc
    if not resolved.is_file():
        raise DFTPlanError(f"registered evidence path is not a file: {name}")
    return resolved


def _require_registered_file(*, root: Path, hashes: dict[str, str], name: str, source: str) -> Path:
    """Require a critical input to be both registered and byte-identical."""

    path = _safe_registered_file(root, name)
    actual = sha256_file(path)
    if hashes.get(name) != actual:
        raise DFTPlanError(f"{source} does not register the required file: {name}")
    return path


def _verify_evidence_outputs(
    *, root: Path, evidence_path: Path, expected_versions: dict[str, str]
) -> tuple[dict[str, str], dict[str, Any]]:
    if not root.is_dir() or root.is_symlink():
        raise FileNotFoundError(root)
    if not evidence_path.is_file() or evidence_path.is_symlink():
        raise FileNotFoundError(evidence_path)
    evidence = _read_json(evidence_path)
    for field, expected in expected_versions.items():
        if evidence.get(field) != expected:
            raise DFTPlanError(f"{root.name} evidence {field} mismatch")
    hashes = evidence.get("output_sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise DFTPlanError(f"evidence has no output hashes: {evidence_path.name}")
    verified: dict[str, str] = {}
    for name, expected in hashes.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise DFTPlanError("invalid registered evidence hash entry")
        resolved = _safe_registered_file(root, name)
        actual = sha256_file(resolved)
        if actual != expected:
            raise DFTPlanError(f"input hash mismatch: {root.name}/{name}")
        verified[name] = actual
    return verified, evidence


def _validate_acquisition_identity(
    *,
    root: Path,
    evidence: dict[str, Any],
    evidence_hashes: dict[str, str],
    runtime_manifest: dict[str, Any],
    success: dict[str, Any],
    config: DFTPlanConfig,
) -> None:
    """Close the Phase 5 evidence, runtime-manifest, and success-marker hash chain."""

    required_evidence = {
        "gate_status": "passed",
        "ranking_model": "B0_raw_xTB",
        "batch_size": config.expected_candidates,
        "submit_hpc": False,
    }
    for field, expected in required_evidence.items():
        if evidence.get(field) != expected:
            raise DFTPlanError(f"acquisition evidence field changed: {field}")

    runtime_hashes = runtime_manifest.get("output_sha256")
    if not isinstance(runtime_hashes, dict) or not runtime_hashes:
        raise DFTPlanError("acquisition runtime manifest has no output hashes")
    for name, expected in runtime_hashes.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise DFTPlanError("invalid acquisition runtime hash entry")
        actual = sha256_file(_safe_registered_file(root, name))
        if actual != expected:
            raise DFTPlanError(f"acquisition runtime output hash mismatch: {name}")
        if evidence_hashes.get(name) != actual:
            raise DFTPlanError(f"acquisition evidence omits or changes runtime output: {name}")

    manifest_path = _require_registered_file(
        root=root,
        hashes=evidence_hashes,
        name="acquisition_manifest.json",
        source="acquisition evidence",
    )
    candidate_path = _require_registered_file(
        root=root,
        hashes=evidence_hashes,
        name="acquisition_candidates.csv",
        source="acquisition evidence",
    )
    _require_registered_file(
        root=root,
        hashes=evidence_hashes,
        name="high_fidelity_batch_manifest.json",
        source="acquisition evidence",
    )
    _require_registered_file(
        root=root,
        hashes=evidence_hashes,
        name="_SUCCESS",
        source="acquisition evidence",
    )
    manifest_hash = sha256_file(manifest_path)
    candidate_hash = sha256_file(candidate_path)
    if success.get("acquisition_manifest_sha256") != manifest_hash:
        raise DFTPlanError("acquisition success marker manifest hash mismatch")
    if success.get("candidate_csv_sha256") != candidate_hash:
        raise DFTPlanError("acquisition success marker candidate hash mismatch")
    if evidence_hashes.get("acquisition_manifest.json") != manifest_hash:
        raise DFTPlanError("acquisition evidence manifest hash mismatch")
    if evidence_hashes.get("acquisition_candidates.csv") != candidate_hash:
        raise DFTPlanError("acquisition evidence candidate hash mismatch")
    for source, name in (
        (runtime_manifest, "runtime manifest"),
        (success, "success marker"),
    ):
        if source.get("dataset_version") != config.dataset_version:
            raise DFTPlanError(f"acquisition {name} dataset version changed")
        if source.get("acquisition_version") != config.acquisition_version:
            raise DFTPlanError(f"acquisition {name} version changed")


def _core_protocol(config: DFTPlanConfig) -> dict[str, Any]:
    protocol = config.protocol
    return {
        "basis": protocol.basis,
        "cation_charge": protocol.cation_charge,
        "cation_multiplicity": protocol.cation_multiplicity,
        "dispersion": protocol.dispersion,
        "geometry_optimizer": protocol.geometry_optimizer,
        "label_quality": protocol.label_quality,
        "method": protocol.method,
        "neutral_charge": protocol.neutral_charge,
        "neutral_multiplicity": protocol.neutral_multiplicity,
        "proton_constant_kcal": protocol.proton_constant_kcal,
        "target_definition": protocol.target_definition,
    }


def _validate_protocol(
    *, dataset_protocol: dict[str, Any], handoff_manifest: dict[str, Any], config: DFTPlanConfig
) -> None:
    expected = _core_protocol(config)
    if dataset_protocol.get("label_protocol_id") != config.protocol.label_protocol_id:
        raise DFTPlanError("dataset label protocol identity changed")
    if dataset_protocol.get("protocol") != expected:
        raise DFTPlanError("dataset protocol does not match the Phase 6 plan")
    if dataset_protocol.get("hartree_to_kcal_mol") != config.protocol.hartree_to_kcal_mol:
        raise DFTPlanError("Hartree conversion differs from the Phase 6 plan")
    if dataset_protocol.get("lower_is_better") is not True:
        raise DFTPlanError("dataset ranking direction is not lower-is-better")
    if handoff_manifest.get("protocol") != expected:
        raise DFTPlanError("Phase 5 handoff protocol differs from the dataset protocol")
    required_top_level = {
        "hessian_computed": False,
        "lower_is_better": True,
        "submit_hpc": False,
        "server_write_authorized": False,
        "target_reaction": config.protocol.reaction,
    }
    for field, expected_value in required_top_level.items():
        if handoff_manifest.get(field) != expected_value:
            raise DFTPlanError(f"Phase 5 handoff field changed: {field}")


def _normalized_record(raw: dict[Any, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in raw.items()}


def _validate_acquisition(
    *,
    acquisition: pd.DataFrame,
    acquisition_manifest: dict[str, Any],
    acquisition_success: dict[str, Any],
    handoff_manifest: dict[str, Any],
    labeled_keys: set[str],
    config: DFTPlanConfig,
) -> tuple[pd.DataFrame, list[str]]:
    required_columns = {
        "inchikey",
        "smiles_cation",
        "smiles_neutral",
        "production_rank",
        "acquisition_score",
        "acquisition_bucket",
        "reason_codes",
        "suggested_priority",
    }
    missing = sorted(required_columns - set(acquisition.columns))
    if missing:
        raise DFTPlanError(f"acquisition columns are missing: {missing}")
    if len(acquisition) != config.expected_candidates:
        raise DFTPlanError("acquisition candidate count changed")
    keys = list(
        validated_keys(
            acquisition["inchikey"].astype(str).tolist(),
            expected_size=config.expected_candidates,
        )
    )
    invalid_keys = [key for key in keys if INCHIKEY_PATTERN.fullmatch(key) is None]
    if invalid_keys:
        raise DFTPlanError(f"noncanonical InChIKey shape: {invalid_keys[0]}")
    if set(keys) & labeled_keys:
        raise DFTPlanError("Phase 6 candidates overlap the frozen labels")
    for column in (
        "smiles_cation",
        "smiles_neutral",
        "reason_codes",
        "suggested_priority",
        "acquisition_bucket",
    ):
        values = acquisition[column].astype("string")
        if values.isna().any() or values.str.strip().eq("").any():
            raise DFTPlanError(f"acquisition has blank values: {column}")
        if values.str.contains(r"[\r\n\x00]", regex=True).any():
            raise DFTPlanError(f"acquisition has unsafe control characters: {column}")
    ranks = pd.to_numeric(acquisition["production_rank"], errors="coerce").to_numpy(
        dtype=np.float64
    )
    scores = pd.to_numeric(acquisition["acquisition_score"], errors="coerce").to_numpy(
        dtype=np.float64
    )
    if not np.isfinite(ranks).all() or not np.equal(ranks, np.floor(ranks)).all():
        raise DFTPlanError("production ranks must be finite integers")
    if np.any(ranks < 1):
        raise DFTPlanError("production ranks must be positive")
    if not np.isfinite(scores).all():
        raise DFTPlanError("acquisition scores must be finite")
    if acquisition_manifest.get("ranking_model") != "B0_raw_xTB":
        raise DFTPlanError("Phase 6 requires the B0 acquisition result")
    if acquisition_manifest.get("batch_size") != config.expected_candidates:
        raise DFTPlanError("acquisition runtime manifest count changed")
    if acquisition_manifest.get("submit_hpc") is not False:
        raise DFTPlanError("acquisition runtime manifest authorizes HPC")
    if acquisition_manifest.get("dataset_version") != config.dataset_version:
        raise DFTPlanError("acquisition runtime dataset version changed")
    if acquisition_manifest.get("acquisition_version") != config.acquisition_version:
        raise DFTPlanError("acquisition runtime version changed")
    if acquisition_success.get("status") != "passed":
        raise DFTPlanError("acquisition runtime result is not passed")
    if acquisition_success.get("selected") != config.expected_candidates:
        raise DFTPlanError("acquisition success count changed")
    if acquisition_success.get("submit_hpc") is not False:
        raise DFTPlanError("acquisition success marker authorizes HPC")
    if acquisition_success.get("dataset_version") != config.dataset_version:
        raise DFTPlanError("acquisition success dataset version changed")
    if acquisition_success.get("acquisition_version") != config.acquisition_version:
        raise DFTPlanError("acquisition success version changed")
    if handoff_manifest.get("candidate_count") != config.expected_candidates:
        raise DFTPlanError("Phase 5 handoff candidate count changed")
    if handoff_manifest.get("manifest_type") != "local_high_fidelity_suggestion_only":
        raise DFTPlanError("Phase 5 handoff manifest type changed")
    if handoff_manifest.get("dataset_version") != config.dataset_version:
        raise DFTPlanError("Phase 5 handoff dataset version changed")
    if handoff_manifest.get("acquisition_version") != config.acquisition_version:
        raise DFTPlanError("Phase 5 handoff acquisition version changed")
    records = handoff_manifest.get("candidates")
    if not isinstance(records, list) or len(records) != config.expected_candidates:
        raise DFTPlanError("Phase 5 handoff candidate records are invalid")
    required_record_fields = {
        "inchikey",
        "smiles_cation",
        "smiles_neutral",
        "production_rank",
        "acquisition_bucket",
        "suggested_priority",
        "reason_codes",
    }
    normalized_records: list[dict[str, Any]] = []
    for index, raw_record in enumerate(records):
        if not isinstance(raw_record, dict):
            raise DFTPlanError(f"Phase 5 handoff record {index} is not an object")
        record = _normalized_record(raw_record)
        missing_record_fields = sorted(required_record_fields - set(record))
        if missing_record_fields:
            raise DFTPlanError(
                f"Phase 5 handoff record {index} is missing: {missing_record_fields}"
            )
        normalized_records.append(record)
    handoff_keys = [str(record["inchikey"]) for record in normalized_records]
    if handoff_keys != keys:
        raise DFTPlanError("Phase 5 CSV and handoff candidate order differ")
    acquisition = acquisition.copy()
    acquisition["acquisition_order"] = range(1, len(acquisition) + 1)
    expected_global = (
        acquisition.sort_values(
            ["acquisition_score", "production_rank", "inchikey"],
            ascending=[False, True, True],
            kind="mergesort",
        )["inchikey"]
        .astype(str)
        .tolist()
    )
    if expected_global != keys:
        raise DFTPlanError("Phase 5 acquisition stable global order changed")
    bucket_counts = acquisition["acquisition_bucket"].value_counts().to_dict()
    expected_counts = {
        bucket: sum(int(getattr(batch.counts, bucket)) for batch in config.batches)
        for bucket in config.bucket_order
    }
    realized_counts = {bucket: int(bucket_counts.get(bucket, 0)) for bucket in config.bucket_order}
    if realized_counts != expected_counts:
        raise DFTPlanError("Phase 5 acquisition bucket quotas changed")
    if set(bucket_counts) != set(config.bucket_order):
        raise DFTPlanError("Phase 5 acquisition contains an unregistered bucket")
    for bucket in config.bucket_order:
        subset = acquisition.loc[acquisition["acquisition_bucket"].eq(bucket)]
        expected_bucket_order = (
            subset.sort_values(
                ["acquisition_score", "production_rank", "inchikey"],
                ascending=[False, True, True],
                kind="mergesort",
            )["inchikey"]
            .astype(str)
            .tolist()
        )
        if subset["inchikey"].astype(str).tolist() != expected_bucket_order:
            raise DFTPlanError(f"Phase 5 stable order changed within bucket: {bucket}")
    selected_by_key = {
        str(row["inchikey"]): row
        for row in (_normalized_record(raw) for raw in acquisition.to_dict("records"))
    }
    for record in normalized_records:
        key = str(record["inchikey"])
        selected = selected_by_key[key]
        scalar_fields = (
            "smiles_cation",
            "smiles_neutral",
            "production_rank",
            "acquisition_bucket",
            "suggested_priority",
        )
        if any(str(record[field]) != str(selected[field]) for field in scalar_fields):
            raise DFTPlanError(f"Phase 5 handoff/CSV mismatch for {key}")
        reasons = record.get("reason_codes")
        if not isinstance(reasons, list) or [str(value) for value in reasons] != str(
            selected["reason_codes"]
        ).split(";"):
            raise DFTPlanError(f"Phase 5 reason-code mismatch for {key}")
    return acquisition, keys


def build_batch_plan(acquisition: pd.DataFrame, config: DFTPlanConfig) -> pd.DataFrame:
    """Partition the frozen acquisition deterministically into five batches."""

    grouped = {
        bucket: acquisition.loc[acquisition["acquisition_bucket"].eq(bucket)].copy()
        for bucket in config.bucket_order
    }
    cursors = {bucket: 0 for bucket in config.bucket_order}
    rows: list[dict[str, Any]] = []
    first_batch = config.batches[0].batch_id
    for batch in config.batches:
        batch_position = 0
        for bucket in config.bucket_order:
            count = int(getattr(batch.counts, bucket))
            start = cursors[bucket]
            stop = start + count
            chunk = grouped[bucket].iloc[start:stop]
            if len(chunk) != count:
                raise DFTPlanError(f"insufficient rows for {batch.batch_id}/{bucket}")
            for offset, raw in enumerate(chunk.to_dict("records"), start=1):
                source = _normalized_record(raw)
                batch_position += 1
                rows.append(
                    {
                        "batch_id": batch.batch_id,
                        "batch_position": batch_position,
                        "bucket_position": start + offset,
                        "is_smoke": batch.batch_id == first_batch and offset <= 1,
                        "InChIKey": str(source["inchikey"]),
                        "acquisition_order": int(source["acquisition_order"]),
                        "production_rank": int(source["production_rank"]),
                        "acquisition_score": float(source["acquisition_score"]),
                        "acquisition_bucket": bucket,
                        "suggested_priority": str(source["suggested_priority"]),
                    }
                )
            cursors[bucket] = stop
    plan = pd.DataFrame(rows)
    planned_keys = validated_keys(plan["InChIKey"].astype(str).tolist(), expected_size=len(plan))
    source_keys = validated_keys(
        acquisition["inchikey"].astype(str).tolist(), expected_size=len(acquisition)
    )
    if len(plan) != config.expected_candidates or set(planned_keys) != set(source_keys):
        raise DFTPlanError("batch plan does not exactly partition the acquisition")
    batch_sizes = plan["batch_id"].value_counts().to_dict()
    if any(
        int(batch_sizes.get(batch.batch_id, 0)) != config.batch_size for batch in config.batches
    ):
        raise DFTPlanError("batch plan has an incorrect batch size")
    smoke = plan.loc[plan["is_smoke"]]
    if len(smoke) != len(config.bucket_order) * config.smoke_per_bucket:
        raise DFTPlanError("smoke plan has an incorrect row count")
    if smoke["batch_id"].nunique() != 1 or str(smoke.iloc[0]["batch_id"]) != first_batch:
        raise DFTPlanError("every smoke row must belong to the first batch")
    if smoke["acquisition_bucket"].value_counts().to_dict() != {
        bucket: config.smoke_per_bucket for bucket in config.bucket_order
    }:
        raise DFTPlanError("smoke plan must contain one row from every bucket")
    return plan


def _candidate_export(acquisition: pd.DataFrame, config: DFTPlanConfig) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "InChIKey": acquisition["inchikey"].astype(str),
            "SMILES_cation": acquisition["smiles_cation"].astype(str),
            "SMILES_neutral": acquisition["smiles_neutral"].astype(str),
            "acquisition_order": acquisition["acquisition_order"].astype(int),
            "production_rank": acquisition["production_rank"].astype(int),
            "acquisition_score": acquisition["acquisition_score"].astype(float),
            "acquisition_bucket": acquisition["acquisition_bucket"].astype(str),
            "suggested_priority": acquisition["suggested_priority"].astype(str),
            "reason_codes": acquisition["reason_codes"].astype(str),
            "geometry_status": config.geometry_status,
            "execution_ready": config.execution_ready,
        }
    )
    return frame


def _screen(keys: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"InChIKey": keys, "pass_filter": [True] * len(keys)})


def _expected_outputs(plan: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for raw in plan.to_dict("records"):
        row = _normalized_record(raw)
        key = str(row["InChIKey"])
        rows.append(
            {
                "InChIKey": key,
                "batch_id": str(row["batch_id"]),
                "geometry_status": "not_generated",
                "initial_cation_xyz": f"xyz/{key}_cation.xyz",
                "initial_neutral_xyz": f"xyz/{key}_neutral.xyz",
                "atom_map_json": f"xyz/{key}_atom_map.json",
                "optimized_cation_xyz": f"runs/{key}/cation.xyz",
                "optimized_neutral_xyz": f"runs/{key}/neutral.xyz",
                "cation_molden": f"runs/{key}/cation.molden",
                "neutral_molden": f"runs/{key}/neutral.molden",
                "radical_molden": f"runs/{key}/radical.molden",
                "result_json": f"runs/{key}/freq.json",
            }
        )
    return pd.DataFrame(rows)


def _handoff_text(config: DFTPlanConfig) -> str:
    return f"""# Local DFT Handoff Plan {config.version}

Status: blocked; this is not a geometry set and not an execution authorization.

The package contains {config.expected_candidates} frozen Phase 5 candidates in five planning
batches. It is ready only for review and a future legacy M2 handoff. No XYZ geometry, quantum
result, private server path, upload instruction, or executable job script is included.

Before any execution, a new authorization must resolve both blockers:

1. `blocked_no_xyz`: choose and validate one uniform initial-geometry workflow.
2. `blocked_runner_extra_steps`: approve a dedicated two-endpoint electronic-label runner or
   explicitly accept the legacy runner's additional cation/neutral/radical single points.

Runtime concurrency, memory, timeout, destination, and scheduler settings are intentionally unset.
The registered label remains gas-phase B3LYP-D3(BJ)/def2-SVP electronic energy with no Hessian;
it is not a Gibbs free energy and does not prove a frequency-confirmed minimum.
"""


def _allowed_output_paths(config: DFTPlanConfig) -> set[str]:
    paths = {
        "candidates.csv",
        "screen_full.csv",
        "smoke.csv",
        "batch_plan.csv",
        "expected_outputs.csv",
        "protocol_manifest.json",
        "validation_report.json",
        "HANDOFF.md",
        "package_manifest.json",
        "_LOCAL_PLAN_SUCCESS",
    }
    paths.update(f"batches/{batch.batch_id}/screen.csv" for batch in config.batches)
    return paths


def _allowed_output_directories(config: DFTPlanConfig) -> set[str]:
    return {
        "batches",
        *(f"batches/{batch.batch_id}" for batch in config.batches),
    }


def _assert_safe_tree(root: Path, config: DFTPlanConfig, *, require_complete: bool) -> None:
    allowed = _allowed_output_paths(config)
    allowed_directories = _allowed_output_directories(config)
    actual: set[str] = set()
    actual_directories: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise DFTPlanError(f"plan output must not contain symlinks: {path.name}")
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            actual_directories.add(relative)
            if relative not in allowed_directories:
                raise DFTPlanError(f"unregistered directory in local plan: {relative}")
            continue
        if not path.is_file():
            raise DFTPlanError(f"unsupported filesystem entry in local plan: {relative}")
        actual.add(relative)
        if relative not in allowed:
            raise DFTPlanError(f"unregistered file in local plan: {relative}")
        if path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            raise DFTPlanError(f"local plan file must not be executable: {relative}")
        if path.suffix.lower() in FORBIDDEN_OUTPUT_SUFFIXES or path.name in FORBIDDEN_OUTPUT_NAMES:
            raise DFTPlanError(f"forbidden execution artifact in local plan: {path.name}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise DFTPlanError(f"local plan contains a non-text artifact: {path.name}") from exc
        if re.search(
            r"/(?:Users|home|Volumes|root|srv|mnt|private|tmp|var|opt|etc)/[^<\s]",
            text,
        ) or re.search(r"[A-Za-z]:\\", text):
            raise DFTPlanError(f"local plan contains a private absolute path: {path.name}")
    if require_complete and (actual != allowed or actual_directories != allowed_directories):
        missing = sorted((allowed - actual) | (allowed_directories - actual_directories))
        raise DFTPlanError(f"local plan tree differs from the contract: {missing}")


def prepare_dft_plan(
    *,
    dataset_dir: Path,
    acquisition_results_dir: Path,
    plan_config_path: Path,
    dataset_evidence_path: Path,
    acquisition_evidence_path: Path,
    output_dir: Path,
    seed: int,
    dry_run: bool = False,
    overwrite: bool = False,
) -> DFTPlanResult:
    """Create the immutable Phase 6 local plan without generating geometry."""

    config = load_dft_plan_config(plan_config_path)
    if dataset_dir.name != config.dataset_version:
        raise DFTPlanError("dataset directory version does not match the plan")
    if acquisition_results_dir.name != f"acquisition_{config.acquisition_version}":
        raise DFTPlanError("acquisition result version does not match the plan")
    if output_dir.name != f"dft_input_plan_{config.version}":
        raise DFTPlanError("output directory name does not match the plan version")
    if output_dir.exists() or output_dir.is_symlink():
        raise DFTPlanError(f"immutable DFT plan already exists: {output_dir}")
    if overwrite:
        raise DFTPlanError("--overwrite cannot replace an immutable DFT plan")
    if seed != config.seed:
        raise DFTPlanError("CLI seed must equal the registered DFT plan seed")
    payload = {
        "command": "prepare-dft-plan",
        "dataset_version": config.dataset_version,
        "acquisition_version": config.acquisition_version,
        "plan_version": config.version,
        "output_dir": str(output_dir),
        "expected_candidates": config.expected_candidates,
        "batches": len(config.batches),
        "batch_size": config.batch_size,
        "smoke_rows": len(config.bucket_order) * config.smoke_per_bucket,
        "dry_run": dry_run,
        "geometry_generated": False,
        "quantum_chemistry_run": False,
        "hessian_computed": False,
        "execution_ready": False,
        "hpc_connection": False,
        "legacy_compatibility": list(config.legacy_interface.compatibility_blockers),
        "server_write_authorized": False,
        "submit_hpc": False,
        "seed": seed,
    }

    dataset_hashes, dataset_evidence = _verify_evidence_outputs(
        root=dataset_dir,
        evidence_path=dataset_evidence_path,
        expected_versions={"dataset_version": config.dataset_version},
    )
    acquisition_hashes, acquisition_evidence = _verify_evidence_outputs(
        root=acquisition_results_dir,
        evidence_path=acquisition_evidence_path,
        expected_versions={
            "dataset_version": config.dataset_version,
            "acquisition_version": config.acquisition_version,
        },
    )
    dataset_rows = dataset_evidence.get("rows")
    if not isinstance(dataset_rows, dict):
        raise DFTPlanError("dataset evidence row counts are invalid")
    label_rows = int(dataset_rows.get("labels", -1))
    if label_rows != config.expected_labels:
        raise DFTPlanError("dataset evidence label count changed")
    labels_path = _require_registered_file(
        root=dataset_dir,
        hashes=dataset_hashes,
        name="labels.parquet",
        source="dataset evidence",
    )
    protocol_path = _require_registered_file(
        root=dataset_dir,
        hashes=dataset_hashes,
        name="protocol_manifest.json",
        source="dataset evidence",
    )
    labels = pd.read_parquet(labels_path)
    if "inchikey" not in labels.columns:
        raise DFTPlanError("label table has no inchikey column")
    labeled = validated_keys(labels["inchikey"].astype(str).tolist(), expected_size=len(labels))
    if len(labeled) != config.expected_labels:
        raise DFTPlanError("label table count changed")
    dataset_protocol = _read_json(protocol_path)
    acquisition_path = _require_registered_file(
        root=acquisition_results_dir,
        hashes=acquisition_hashes,
        name="acquisition_candidates.csv",
        source="acquisition evidence",
    )
    acquisition_manifest_path = _require_registered_file(
        root=acquisition_results_dir,
        hashes=acquisition_hashes,
        name="acquisition_manifest.json",
        source="acquisition evidence",
    )
    acquisition_success_path = _require_registered_file(
        root=acquisition_results_dir,
        hashes=acquisition_hashes,
        name="_SUCCESS",
        source="acquisition evidence",
    )
    handoff_manifest_path = _require_registered_file(
        root=acquisition_results_dir,
        hashes=acquisition_hashes,
        name="high_fidelity_batch_manifest.json",
        source="acquisition evidence",
    )
    acquisition = pd.read_csv(acquisition_path)
    acquisition_manifest = _read_json(acquisition_manifest_path)
    acquisition_success = _read_json(acquisition_success_path)
    handoff_manifest = _read_json(handoff_manifest_path)
    _validate_acquisition_identity(
        root=acquisition_results_dir,
        evidence=acquisition_evidence,
        evidence_hashes=acquisition_hashes,
        runtime_manifest=acquisition_manifest,
        success=acquisition_success,
        config=config,
    )
    _validate_protocol(
        dataset_protocol=dataset_protocol,
        handoff_manifest=handoff_manifest,
        config=config,
    )
    acquisition, keys = _validate_acquisition(
        acquisition=acquisition,
        acquisition_manifest=acquisition_manifest,
        acquisition_success=acquisition_success,
        handoff_manifest=handoff_manifest,
        labeled_keys=set(labeled),
        config=config,
    )
    plan = build_batch_plan(acquisition, config)
    if dry_run:
        return DFTPlanResult(
            payload={
                **payload,
                "input_validated": True,
                "candidate_rows": len(keys),
                "labeled_overlap": 0,
                "status": "dry_run_validated",
            }
        )
    candidate_export = _candidate_export(acquisition, config)
    planned_keys = plan["InChIKey"].astype(str).tolist()
    smoke = plan.loc[plan["is_smoke"]].copy()

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(
        tempfile.mkdtemp(prefix=f".dft_input_plan_{config.version}.tmp.", dir=output_dir.parent)
    )
    try:
        candidate_export.to_csv(temporary_dir / "candidates.csv", index=False)
        _screen(planned_keys).to_csv(temporary_dir / "screen_full.csv", index=False)
        _screen(smoke["InChIKey"].astype(str).tolist()).to_csv(
            temporary_dir / "smoke.csv", index=False
        )
        plan.to_csv(temporary_dir / "batch_plan.csv", index=False)
        _expected_outputs(plan).to_csv(temporary_dir / "expected_outputs.csv", index=False)
        for batch in config.batches:
            batch_dir = temporary_dir / "batches" / batch.batch_id
            batch_dir.mkdir(parents=True, exist_ok=False)
            batch_keys = (
                plan.loc[plan["batch_id"].eq(batch.batch_id), "InChIKey"].astype(str).tolist()
            )
            _screen(batch_keys).to_csv(batch_dir / "screen.csv", index=False)
        protocol_manifest = {
            "manifest_type": "local_dft_execution_plan_only",
            "dataset_version": config.dataset_version,
            "acquisition_version": config.acquisition_version,
            "plan_version": config.version,
            "label_protocol_id": config.protocol.label_protocol_id,
            "protocol": config.protocol.model_dump(mode="json"),
            "legacy_interface": config.legacy_interface.model_dump(mode="json"),
            "geometry_generated": False,
            "geometry_status": "not_generated",
            "quantum_chemistry_run": False,
            "hessian_computed": False,
            "execution_ready": False,
            "legacy_compatibility": list(config.legacy_interface.compatibility_blockers),
            "server_write_authorized": False,
            "submit_hpc": False,
            "runtime_parameters": {
                "server_destination": None,
                "parallel": None,
                "threads_per_job": None,
                "memory_per_job_mb": None,
                "timeout_seconds": None,
                "scheduler": None,
            },
        }
        _write_json(temporary_dir / "protocol_manifest.json", protocol_manifest)
        validation = {
            "candidate_rows": len(keys),
            "unique_keys": len(set(keys)),
            "labeled_keys": len(labeled),
            "labeled_overlap": len(set(keys) & set(labeled)),
            "bucket_counts": {
                bucket: int(acquisition["acquisition_bucket"].eq(bucket).sum())
                for bucket in config.bucket_order
            },
            "batch_sizes": {
                batch.batch_id: int(plan["batch_id"].eq(batch.batch_id).sum())
                for batch in config.batches
            },
            "smoke_rows": len(smoke),
            "smoke_bucket_counts": {
                bucket: int(smoke["acquisition_bucket"].eq(bucket).sum())
                for bucket in config.bucket_order
            },
            "geometry_files": 0,
            "geometry_status": "not_generated",
            "hessian_computed": False,
            "execution_ready": False,
            "compatibility_blockers": list(config.legacy_interface.compatibility_blockers),
            "legacy_compatibility": list(config.legacy_interface.compatibility_blockers),
            "quantum_chemistry_run": False,
            "server_write_authorized": False,
            "submit_hpc": False,
            "status": "local_plan_passed",
        }
        _write_json(temporary_dir / "validation_report.json", validation)
        (temporary_dir / "HANDOFF.md").write_text(_handoff_text(config), encoding="utf-8")
        _assert_safe_tree(temporary_dir, config, require_complete=False)
        output_hashes = {
            path.relative_to(temporary_dir).as_posix(): sha256_file(path)
            for path in sorted(temporary_dir.rglob("*"))
            if path.is_file()
        }
        input_hashes = {
            **{f"dataset/{name}": digest for name, digest in dataset_hashes.items()},
            **{f"acquisition/{name}": digest for name, digest in acquisition_hashes.items()},
            "dataset_evidence": sha256_file(dataset_evidence_path),
            "acquisition_evidence": sha256_file(acquisition_evidence_path),
            "dft_plan_config": sha256_file(plan_config_path),
        }
        package_manifest = {
            "dataset_version": config.dataset_version,
            "acquisition_version": config.acquisition_version,
            "plan_version": config.version,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "candidate_rows": len(keys),
            "candidate_key_set_sha256": key_set_sha256(keys),
            "candidate_key_order_sha256": _ordered_key_sha256(keys),
            "planned_key_order_sha256": _ordered_key_sha256(planned_keys),
            "smoke_keys": smoke["InChIKey"].astype(str).tolist(),
            "batch_membership": {
                batch.batch_id: plan.loc[plan["batch_id"].eq(batch.batch_id), "InChIKey"]
                .astype(str)
                .tolist()
                for batch in config.batches
            },
            "geometry_generated": False,
            "quantum_chemistry_run": False,
            "hessian_computed": False,
            "execution_ready": False,
            "legacy_compatibility": list(config.legacy_interface.compatibility_blockers),
            "server_write_authorized": False,
            "submit_hpc": False,
            "source_tree_sha256": sha256_source_tree(Path(__file__).parents[1]),
            "input_sha256": input_hashes,
            "output_sha256": output_hashes,
        }
        _write_json(temporary_dir / "package_manifest.json", package_manifest)
        completion = {
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "dataset_version": config.dataset_version,
            "acquisition_version": config.acquisition_version,
            "plan_version": config.version,
            "status": "local_plan_passed",
            "candidate_rows": len(keys),
            "geometry_generated": False,
            "quantum_chemistry_run": False,
            "hessian_computed": False,
            "execution_ready": False,
            "legacy_compatibility": list(config.legacy_interface.compatibility_blockers),
            "server_write_authorized": False,
            "submit_hpc": False,
            "package_manifest_sha256": sha256_file(temporary_dir / "package_manifest.json"),
        }
        _write_json(temporary_dir / "_LOCAL_PLAN_SUCCESS", completion)
        _assert_safe_tree(temporary_dir, config, require_complete=True)
        os.replace(temporary_dir, output_dir)
    except BaseException:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise
    return DFTPlanResult(
        payload={
            **payload,
            "dry_run": False,
            "status": "local_plan_passed",
            "candidate_rows": len(keys),
            "output_files": sorted(
                path.relative_to(output_dir).as_posix()
                for path in output_dir.rglob("*")
                if path.is_file()
            ),
        }
    )
