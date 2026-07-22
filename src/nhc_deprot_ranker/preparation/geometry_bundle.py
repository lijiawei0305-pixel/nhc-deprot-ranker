"""Build the immutable, portable four-row Phase 7 geometry smoke bundle."""

from __future__ import annotations

import csv
import hashlib
import io
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

import pandas as pd

from nhc_deprot_ranker.config import GeometrySmokeConfig, load_geometry_smoke_config
from nhc_deprot_ranker.data.provenance import sha256_file, sha256_source_tree

PROJECT_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR_CORE = PROJECT_ROOT / "src/nhc_deprot_ranker/preparation/geometry_validation.py"
VALIDATOR_WRAPPER = PROJECT_ROOT / "scripts/validate_geometry_smoke.py"
SOURCE_ROOT = PROJECT_ROOT / "src/nhc_deprot_ranker"
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
INCHIKEY = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
PRIVATE_PATH = re.compile(r"/(?:Users|home)/[^\s\"']+")
IPV4 = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
SCRIPT_FORBIDDEN = re.compile(
    r"(?i)(?:\b(?:dft|xtb|pyscf|hessian|molden|sbatch|qsub|srun|nohup|rm|rmdir|unlink)\b|--delete)"
)


class GeometryBundleError(ValueError):
    """The Phase 7 local bundle contract failed closed."""


@dataclass(frozen=True)
class GeometryBundleResult:
    """CLI-facing Phase 7 local bundle result."""

    payload: dict[str, Any]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GeometryBundleError(f"invalid JSON input: {path.name}") from exc
    if not isinstance(raw, dict):
        raise GeometryBundleError(f"JSON root must be an object: {path.name}")
    return raw


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")


def _csv_bytes(rows: list[list[object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_relative(name: str) -> Path:
    if not isinstance(name, str) or not name or name.strip() != name or "\\" in name:
        raise GeometryBundleError("invalid registered path")
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != name:
        raise GeometryBundleError(f"unsafe registered path: {name}")
    return path


def _safe_file(root: Path, name: str) -> Path:
    relative = _safe_relative(name)
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise GeometryBundleError(f"registered path is a symlink: {name}")
    try:
        root_resolved = root.resolve(strict=True)
        path = (root / relative).resolve(strict=True)
        path.relative_to(root_resolved)
    except FileNotFoundError:
        raise
    except ValueError as exc:
        raise GeometryBundleError(f"registered path escapes its root: {name}") from exc
    if not path.is_file():
        raise GeometryBundleError(f"registered path is not a file: {name}")
    return path


def _validated_hash_map(raw: object, *, source: str) -> dict[str, str]:
    if not isinstance(raw, dict) or not raw:
        raise GeometryBundleError(f"{source} has no registered hashes")
    result: dict[str, str] = {}
    for raw_name, raw_digest in raw.items():
        if not isinstance(raw_name, str) or not isinstance(raw_digest, str):
            raise GeometryBundleError(f"{source} has an invalid hash entry")
        _safe_relative(raw_name)
        if HEX_SHA256.fullmatch(raw_digest) is None:
            raise GeometryBundleError(f"{source} has an invalid SHA256: {raw_name}")
        result[raw_name] = raw_digest
    return result


def _verify_phase6(
    *, root: Path, evidence_path: Path, config: GeometrySmokeConfig
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    """Verify every Phase 6 byte plus its evidence/package/success hash chain."""

    if not root.is_dir() or root.is_symlink():
        raise FileNotFoundError(root)
    if not evidence_path.is_file() or evidence_path.is_symlink():
        raise FileNotFoundError(evidence_path)
    if sha256_file(evidence_path) != config.phase6_inputs.evidence_sha256:
        raise GeometryBundleError("checked-in Phase 6 evidence hash changed")
    evidence = _read_json(evidence_path)
    if evidence.get("gate_status") != "passed":
        raise GeometryBundleError("Phase 6 evidence gate is not passed")
    if evidence.get("plan_version") != config.phase6_plan_version:
        raise GeometryBundleError("Phase 6 evidence version changed")
    registered = _validated_hash_map(evidence.get("output_sha256"), source="Phase 6 evidence")
    actual_files: set[str] = set()
    for candidate in root.rglob("*"):
        name = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            raise GeometryBundleError(f"Phase 6 result contains a symlink: {name}")
        if candidate.is_file():
            actual_files.add(name)
    if actual_files != set(registered):
        raise GeometryBundleError("Phase 6 result file set differs from checked-in evidence")
    verified: dict[str, str] = {}
    for name, expected in registered.items():
        actual = sha256_file(_safe_file(root, name))
        if actual != expected:
            raise GeometryBundleError(f"Phase 6 result hash mismatch: {name}")
        verified[name] = actual

    critical = {
        "smoke.csv": config.phase6_inputs.smoke_csv_sha256,
        "candidates.csv": config.phase6_inputs.candidates_csv_sha256,
        "package_manifest.json": config.phase6_inputs.package_manifest_sha256,
    }
    for name, expected in critical.items():
        if verified.get(name) != expected:
            raise GeometryBundleError(f"frozen Phase 6 identity changed: {name}")
    if evidence.get("package_manifest_sha256") != critical["package_manifest.json"]:
        raise GeometryBundleError("Phase 6 evidence package pointer changed")

    package = _read_json(_safe_file(root, "package_manifest.json"))
    package_hashes = _validated_hash_map(
        package.get("output_sha256"), source="Phase 6 package manifest"
    )
    for name, expected in package_hashes.items():
        if verified.get(name) != expected:
            raise GeometryBundleError(f"Phase 6 package hash chain changed: {name}")
    if package.get("plan_version") != config.phase6_plan_version:
        raise GeometryBundleError("Phase 6 package version changed")
    if package.get("smoke_keys") != list(config.ordered_keys):
        raise GeometryBundleError("Phase 6 package smoke key order changed")
    no_action = {
        "execution_ready": False,
        "geometry_generated": False,
        "hessian_computed": False,
        "quantum_chemistry_run": False,
        "server_write_authorized": False,
        "submit_hpc": False,
    }
    for field, expected_flag in no_action.items():
        if package.get(field) is not expected_flag:
            raise GeometryBundleError(f"Phase 6 package no-action field changed: {field}")

    success = _read_json(_safe_file(root, "_LOCAL_PLAN_SUCCESS"))
    if success.get("status") != "local_plan_passed":
        raise GeometryBundleError("Phase 6 success marker is not passed")
    if success.get("package_manifest_sha256") != critical["package_manifest.json"]:
        raise GeometryBundleError("Phase 6 success marker package pointer changed")
    for field, expected_flag in no_action.items():
        if field in success and success.get(field) is not expected_flag:
            raise GeometryBundleError(f"Phase 6 success no-action field changed: {field}")
    return verified, evidence, package


def _build_canonical_input(
    *, root: Path, config: GeometrySmokeConfig
) -> tuple[bytes, list[dict[str, str]]]:
    """Join the two frozen Phase 6 tables without reordering or backfill."""

    smoke = pd.read_csv(_safe_file(root, "smoke.csv"), dtype={"InChIKey": "string"})
    candidates = pd.read_csv(
        _safe_file(root, "candidates.csv"),
        dtype={
            "InChIKey": "string",
            "SMILES_cation": "string",
            "SMILES_neutral": "string",
        },
    )
    if smoke.columns.tolist() != ["InChIKey", "pass_filter"]:
        raise GeometryBundleError("Phase 6 smoke CSV schema changed")
    required_candidate_columns = {"InChIKey", "SMILES_cation", "SMILES_neutral"}
    if not required_candidate_columns.issubset(candidates.columns):
        raise GeometryBundleError("Phase 6 candidates CSV lacks the legacy M2 columns")
    if len(smoke) != config.expected_smoke_count:
        raise GeometryBundleError("Phase 6 smoke row count changed")
    pass_filter = smoke["pass_filter"]
    if not pass_filter.map(lambda value: value is True).all():
        raise GeometryBundleError("Phase 6 smoke contains a failing row")
    if candidates["InChIKey"].duplicated().any():
        raise GeometryBundleError("Phase 6 candidates contain duplicate InChIKeys")
    smoke_keys = smoke["InChIKey"].astype(str).tolist()
    if tuple(smoke_keys) != config.ordered_keys:
        raise GeometryBundleError("Phase 6 smoke key order changed")
    if any(INCHIKEY.fullmatch(key) is None for key in smoke_keys):
        raise GeometryBundleError("Phase 6 smoke contains a malformed InChIKey")

    selected = smoke[["InChIKey"]].merge(
        candidates[["InChIKey", "SMILES_cation", "SMILES_neutral"]],
        on="InChIKey",
        how="left",
        sort=False,
        validate="one_to_one",
    )
    records: list[dict[str, str]] = []
    rows: list[list[object]] = [list(config.canonical_input.columns)]
    for raw in selected.to_dict("records"):
        record = {str(name): str(value) for name, value in raw.items()}
        if record["SMILES_cation"] in {"", "<NA>", "nan"} or record["SMILES_neutral"] in {
            "",
            "<NA>",
            "nan",
        }:
            raise GeometryBundleError("Phase 6 smoke join has a missing endpoint SMILES")
        if any(re.search(r"[\r\n\x00]", value) for value in record.values()):
            raise GeometryBundleError("Phase 6 smoke join contains unsafe control characters")
        records.append(record)
        rows.append([record[column] for column in config.canonical_input.columns])
    payload = _csv_bytes(rows)
    if len(payload) != config.canonical_input.bytes:
        raise GeometryBundleError("canonical M2 input byte count changed")
    if _sha256_bytes(payload) != config.canonical_input.sha256:
        raise GeometryBundleError("canonical M2 input SHA256 changed")
    return payload, records


def _expected_outputs(config: GeometrySmokeConfig) -> tuple[bytes, list[dict[str, str]]]:
    records = [
        {
            "inchikey": key,
            "cation_xyz": f"{key}_cation.xyz",
            "neutral_xyz": f"{key}_neutral.xyz",
            "legacy_atom_map": f"{key}_atom_map.json",
        }
        for key in config.ordered_keys
    ]
    rows: list[list[object]] = [
        ["request_order", "InChIKey", "cation_xyz", "neutral_xyz", "legacy_atom_map"]
    ]
    rows.extend(
        [
            index,
            record["inchikey"],
            record["cation_xyz"],
            record["neutral_xyz"],
            record["legacy_atom_map"],
        ]
        for index, record in enumerate(records, start=1)
    )
    return _csv_bytes(rows), records


def _geometry_request(
    *,
    config: GeometrySmokeConfig,
    candidates: list[dict[str, str]],
    expected_outputs: list[dict[str, str]],
) -> dict[str, Any]:
    m2 = config.m2
    normalized_candidates = [
        {
            "inchikey": record["InChIKey"],
            "smiles_cation": record["SMILES_cation"],
            "smiles_neutral": record["SMILES_neutral"],
        }
        for record in candidates
    ]
    return {
        "schema_version": "geometry-smoke-request-v1",
        "request_id": f"geometry_smoke_{config.version}",
        "bundle_version": config.version,
        "phase6_plan_version": config.phase6_plan_version,
        "expected_count": config.expected_smoke_count,
        "ordered_keys": list(config.ordered_keys),
        "candidates": normalized_candidates,
        "seed": m2.seed,
        "num_conformers": m2.num_conformers,
        "parallel": m2.parallel,
        "embedding_method": m2.embedding_method,
        "use_random_coords": m2.use_random_coords,
        "force_field_primary": m2.force_field_primary,
        "force_field_fallback": m2.force_field_fallback,
        "geometry_quality": m2.geometry_quality,
        "force_field_convergence": m2.force_field_convergence,
        "input_csv": {
            "name": config.canonical_input.name,
            "sha256": config.canonical_input.sha256,
            "bytes": config.canonical_input.bytes,
            "rows": config.expected_smoke_count,
            "columns": list(config.canonical_input.columns),
        },
        "legacy": {
            "commit": config.legacy.commit,
            "gen_3d": {
                "path": config.legacy.gen_3d.path.as_posix(),
                "sha256": config.legacy.gen_3d.sha256,
            },
            "structure_gen": {
                "path": config.legacy.structure_gen.path.as_posix(),
                "sha256": config.legacy.structure_gen.sha256,
            },
        },
        "expected_outputs": expected_outputs,
        "execution_scope": {
            "operation": "legacy_m2_initial_geometry_only",
            "candidate_scope": "exact_preregistered_smoke_four",
            "synchronous": True,
            "scheduler_submission": False,
        },
        "prohibitions": [
            "no_candidate_replacement_or_backfill",
            "no_xTB",
            "no_PySCF",
            "no_Hessian",
            "no_legacy_M4",
            "no_dedicated_runner_execution",
        ],
    }


def _render_run_script(config: GeometrySmokeConfig) -> bytes:
    """Render a host-free synchronous M2-and-validator shell script."""

    gen_3d = config.legacy.gen_3d.path.as_posix()
    environment = config.m2.environment_script.as_posix()
    rendered = f"""#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "usage: $0 <project-root> <run-root>" >&2
  exit 64
fi

PROJECT_ROOT="$1"
RUN_ROOT="$2"
if [[ ! -d "$PROJECT_ROOT" || -L "$PROJECT_ROOT" ]]; then
  echo "project root must be a real directory" >&2
  exit 65
fi
if [[ ! -d "$RUN_ROOT" || -L "$RUN_ROOT" ]]; then
  echo "run root must be a real directory" >&2
  exit 66
fi
BUNDLE_ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd -P)"
RUN_ROOT="$(cd "$RUN_ROOT" && pwd -P)"
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd -P)"
if [[ ! -d "$PROJECT_ROOT/data" || -L "$PROJECT_ROOT/data" || \
      ! -d "$PROJECT_ROOT/data/runs" || -L "$PROJECT_ROOT/data/runs" ]]; then
  echo "project data/runs namespace must be a real directory" >&2
  exit 72
fi
EXPECTED_RUN_PARENT="$(cd "$PROJECT_ROOT/data/runs" && pwd -P)"
RUN_NAME="$(basename "$RUN_ROOT")"
if [[ "$(dirname "$RUN_ROOT")" != "$EXPECTED_RUN_PARENT" || \
      ! "$RUN_NAME" =~ ^nhc_deprot_ranker_phase7_smoke_[A-Za-z0-9._-]+$ ]]; then
  echo "run root is outside the dedicated Phase 7 smoke namespace" >&2
  exit 72
fi
if [[ "$BUNDLE_ROOT" != "$RUN_ROOT" ]]; then
  echo "script must run from the transferred bundle root" >&2
  exit 67
fi
if [[ -e "$RUN_ROOT/m2" || -L "$RUN_ROOT/m2" ]]; then
  echo "m2 output already exists; refusing to replace it" >&2
  exit 68
fi
for directory in logs audit; do
  path="$RUN_ROOT/$directory"
  if [[ -L "$path" || ( -e "$path" && ! -d "$path" ) ]]; then
    echo "unsafe run directory: $directory" >&2
    exit 69
  fi
  mkdir -p "$path"
done
if [[ -e "$RUN_ROOT/logs/legacy_m2.log" || -e "$RUN_ROOT/audit/geometry_validation.json" ]]; then
  echo "run output already exists; refusing to replace it" >&2
  exit 70
fi

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT"
export PYTHONDONTWRITEBYTECODE=1
if [[ ! -f "$PROJECT_ROOT/{environment}" || -L "$PROJECT_ROOT/{environment}" ]]; then
  echo "molecular environment script is missing or unsafe" >&2
  exit 71
fi
set +u
source "$PROJECT_ROOT/{environment}"
set -u

python -B - "$RUN_ROOT" "$PROJECT_ROOT" <<'PY'
import hashlib
import json
import pathlib
import sys

run_root = pathlib.Path(sys.argv[1]).resolve(strict=True)
project_root = pathlib.Path(sys.argv[2]).resolve(strict=True)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

manifest_path = run_root / "package_manifest.json"
ready_path = run_root / "_READY_FOR_REMOTE_GEOMETRY"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
ready = json.loads(ready_path.read_text(encoding="utf-8"))
if ready.get("package_manifest_sha256") != digest(manifest_path):
    raise SystemExit("ready marker does not match package manifest")
for name, expected in manifest.get("output_sha256", {{}}).items():
    relative = pathlib.PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit("unsafe bundle manifest path")
    path = (run_root / pathlib.Path(*relative.parts)).resolve(strict=True)
    path.relative_to(run_root)
    if not path.is_file() or path.is_symlink() or digest(path) != expected:
        raise SystemExit("bundle hash check failed: " + name)
request = json.loads((run_root / "input/geometry_request.json").read_text(encoding="utf-8"))
for field in ("gen_3d", "structure_gen"):
    item = request["legacy"][field]
    relative = pathlib.PurePosixPath(item["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit("unsafe legacy source path")
    path = (project_root / pathlib.Path(*relative.parts)).resolve(strict=True)
    path.relative_to(project_root)
    if not path.is_file() or path.is_symlink() or digest(path) != item["sha256"]:
        raise SystemExit("legacy source hash check failed: " + field)
PY

mkdir "$RUN_ROOT/m2"
python -B "$PROJECT_ROOT/{gen_3d}" \
  --input "$RUN_ROOT/input/smoke_candidates.csv" \
  --output "$RUN_ROOT/m2" \
  --num-confs {config.m2.num_conformers} \
  --parallel {config.m2.parallel} 2>&1 | tee "$RUN_ROOT/logs/legacy_m2.log"

python -B "$RUN_ROOT/tools/validate_geometry_smoke.py" \
  --request "$RUN_ROOT/input/geometry_request.json" \
  --input "$RUN_ROOT/input/smoke_candidates.csv" \
  --xyz-dir "$RUN_ROOT/m2/xyz" \
  --output-dir "$RUN_ROOT/audit"
"""
    if SCRIPT_FORBIDDEN.search(rendered):
        raise GeometryBundleError("generated M2 script contains a forbidden operation")
    required = (
        f"--num-confs {config.m2.num_conformers}",
        f"--parallel {config.m2.parallel}",
        "validate_geometry_smoke.py",
        f'set +u\nsource "$PROJECT_ROOT/{environment}"\nset -u',
        f'source "$PROJECT_ROOT/{environment}"',
        'export PYTHONPATH="$PROJECT_ROOT"',
        "export PYTHONDONTWRITEBYTECODE=1",
        "nhc_deprot_ranker_phase7_smoke_[A-Za-z0-9._-]+",
        'python -B "$PROJECT_ROOT/',
        'python -B "$RUN_ROOT/tools/validate_geometry_smoke.py"',
    )
    if any(item not in rendered for item in required):
        raise GeometryBundleError("generated M2 script is missing a required safety contract")
    return rendered.encode("utf-8")


def _verify_validator_sources() -> tuple[bytes, bytes]:
    sources: list[bytes] = []
    for path in (VALIDATOR_CORE, VALIDATOR_WRAPPER):
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(path)
        payload = path.read_bytes()
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GeometryBundleError(f"validator source is not UTF-8: {path.name}") from exc
        if PRIVATE_PATH.search(text) or IPV4.search(text):
            raise GeometryBundleError(
                f"validator source contains a host-specific value: {path.name}"
            )
        sources.append(payload)
    return sources[0], sources[1]


def _assert_safe_bundle(*, root: Path, manifest: dict[str, Any], require_complete: bool) -> None:
    allowed = {
        "input/smoke_candidates.csv",
        "input/geometry_request.json",
        "input/expected_outputs.csv",
        "tools/run_legacy_m2_smoke.sh",
        "tools/geometry_validation.py",
        "tools/validate_geometry_smoke.py",
        "package_manifest.json",
        "_READY_FOR_REMOTE_GEOMETRY",
    }
    actual: set[str] = set()
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise GeometryBundleError(f"bundle contains a symlink: {name}")
        if not path.is_file():
            continue
        actual.add(name)
        if name not in allowed:
            raise GeometryBundleError(f"bundle contains an unregistered file: {name}")
        mode = stat.S_IMODE(path.stat().st_mode)
        if name == "tools/run_legacy_m2_smoke.sh":
            if mode & stat.S_IXUSR == 0:
                raise GeometryBundleError("M2 script is not executable by its owner")
        elif mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            raise GeometryBundleError(f"unexpected executable bundle file: {name}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise GeometryBundleError(f"bundle contains a non-text file: {name}") from exc
        if PRIVATE_PATH.search(text) or IPV4.search(text):
            raise GeometryBundleError(f"bundle contains a host-specific value: {name}")
    if require_complete and actual != allowed:
        raise GeometryBundleError(f"bundle file set mismatch: {sorted(allowed - actual)}")
    hashes = _validated_hash_map(manifest.get("output_sha256"), source="bundle manifest")
    for name, expected in hashes.items():
        if name not in actual or sha256_file(root / name) != expected:
            raise GeometryBundleError(f"bundle output hash mismatch: {name}")


def prepare_geometry_smoke_bundle(
    *,
    dft_plan_dir: Path,
    dft_plan_evidence_path: Path,
    geometry_config_path: Path,
    output_dir: Path,
    dry_run: bool = False,
    overwrite: bool = False,
) -> GeometryBundleResult:
    """Validate frozen Phase 6 inputs and optionally create one immutable bundle."""

    if overwrite:
        raise GeometryBundleError("Phase 7 geometry bundles are immutable; overwrite is prohibited")
    if os.path.lexists(output_dir):
        raise FileExistsError(f"immutable output already exists: {output_dir}")
    if not geometry_config_path.is_file() or geometry_config_path.is_symlink():
        raise FileNotFoundError(geometry_config_path)
    config = load_geometry_smoke_config(geometry_config_path)
    phase6_hashes, _evidence, _package = _verify_phase6(
        root=dft_plan_dir,
        evidence_path=dft_plan_evidence_path,
        config=config,
    )
    input_csv, candidates = _build_canonical_input(root=dft_plan_dir, config=config)
    expected_csv, expected_records = _expected_outputs(config)
    request = _geometry_request(
        config=config,
        candidates=candidates,
        expected_outputs=expected_records,
    )
    request_bytes = _json_bytes(request)
    script_bytes = _render_run_script(config)
    validator_core, validator_wrapper = _verify_validator_sources()

    staged: dict[str, bytes] = {
        "input/smoke_candidates.csv": input_csv,
        "input/geometry_request.json": request_bytes,
        "input/expected_outputs.csv": expected_csv,
        "tools/run_legacy_m2_smoke.sh": script_bytes,
        "tools/geometry_validation.py": validator_core,
        "tools/validate_geometry_smoke.py": validator_wrapper,
    }
    input_hashes = {
        **{f"phase6/{name}": digest for name, digest in sorted(phase6_hashes.items())},
        "phase6_evidence": sha256_file(dft_plan_evidence_path),
        "geometry_config": sha256_file(geometry_config_path),
        "validator_core_source": sha256_file(VALIDATOR_CORE),
        "validator_wrapper_source": sha256_file(VALIDATOR_WRAPPER),
    }
    output_hashes = {name: _sha256_bytes(payload) for name, payload in sorted(staged.items())}
    manifest: dict[str, Any] = {
        "schema_version": "geometry-smoke-bundle-manifest-v1",
        "bundle_version": config.version,
        "phase6_plan_version": config.phase6_plan_version,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "candidate_count": config.expected_smoke_count,
        "ordered_keys": list(config.ordered_keys),
        "canonical_input_bytes": len(input_csv),
        "canonical_input_sha256": _sha256_bytes(input_csv),
        "input_sha256": input_hashes,
        "output_sha256": output_hashes,
        "source_tree_sha256": sha256_source_tree(SOURCE_ROOT),
        "remote_layout": {
            "input": "input",
            "tools": "tools",
            "logs": "logs",
            "geometry_output": "m2/xyz",
            "audit": "audit",
        },
        "execution_scope": {
            "operation": "legacy_m2_initial_geometry_only",
            "geometry_scope": config.geometry_scope,
            "seed": config.m2.seed,
            "num_conformers": config.m2.num_conformers,
            "parallel": config.m2.parallel,
        },
        "no_action": {
            "geometry_generated": False,
            "remote_execution_performed": False,
            "quantum_chemistry_run": config.quantum_chemistry_run,
            "hessian_computed": config.hessian_computed,
            "old_m4_run": config.old_m4_run,
            "dedicated_runner_run": config.dedicated_runner_run,
            "submit_hpc": config.submit_hpc,
        },
        "portable": True,
        "contains_host_or_private_path": False,
    }
    manifest_bytes = _json_bytes(manifest)
    ready = {
        "status": "ready_for_remote_geometry_preflight",
        "bundle_version": config.version,
        "candidate_count": config.expected_smoke_count,
        "ordered_keys": list(config.ordered_keys),
        "package_manifest_sha256": _sha256_bytes(manifest_bytes),
        "canonical_input_sha256": config.canonical_input.sha256,
        "geometry_generated": False,
        "remote_execution_performed": False,
        "quantum_chemistry_run": False,
        "submit_hpc": False,
    }
    ready_bytes = _json_bytes(ready)

    payload: dict[str, Any] = {
        "command": "prepare-geometry-smoke",
        "dry_run": dry_run,
        "input_validated": True,
        "bundle_created": False,
        "bundle_version": config.version,
        "candidate_rows": len(candidates),
        "ordered_keys": list(config.ordered_keys),
        "canonical_input_bytes": len(input_csv),
        "canonical_input_sha256": _sha256_bytes(input_csv),
        "package_manifest_sha256": _sha256_bytes(manifest_bytes),
        "geometry_generated": False,
        "remote_execution_performed": False,
        "quantum_chemistry_run": False,
        "submit_hpc": False,
    }
    if dry_run:
        return GeometryBundleResult(payload=payload)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.parent.is_symlink():
        raise GeometryBundleError("output parent may not be a symlink")
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=str(output_dir.parent))
    )
    try:
        (temporary / "input").mkdir()
        (temporary / "tools").mkdir()
        for name, content in staged.items():
            path = temporary / name
            path.write_bytes(content)
            path.chmod(0o750 if name == "tools/run_legacy_m2_smoke.sh" else 0o640)
        (temporary / "package_manifest.json").write_bytes(manifest_bytes)
        (temporary / "package_manifest.json").chmod(0o640)
        (temporary / "_READY_FOR_REMOTE_GEOMETRY").write_bytes(ready_bytes)
        (temporary / "_READY_FOR_REMOTE_GEOMETRY").chmod(0o640)
        _assert_safe_bundle(root=temporary, manifest=manifest, require_complete=True)
        if os.path.lexists(output_dir):
            raise FileExistsError(f"immutable output already exists: {output_dir}")
        temporary.rename(output_dir)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    payload["bundle_created"] = True
    return GeometryBundleResult(payload=payload)
