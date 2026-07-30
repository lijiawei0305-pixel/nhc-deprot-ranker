#!/usr/bin/env python3
"""Assemble audited P01 frames into molecule-disjoint AIMNet2 NPZ groups."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import math
import os
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, cast

import numpy as np

SPLIT_SCHEMA: Final = "phase9b-aimnet2-finetune-split-v002"
FRAME_SCHEMA: Final = "phase9b-parent-level-training-frame-v1"
ENDPOINT_MANIFEST_SCHEMA: Final = "phase9b-parent-level-training-endpoint-v1"
DATASET_MANIFEST_SCHEMA: Final = "phase9b-parent-level-training-route-v1"
OUTPUT_SCHEMA: Final = "phase9b-aimnet2-training-dataset-v1"
D3_PROJECTION_SCHEMA: Final = "phase9b-aimnet2-training-d3-projection-v1"
PARENT_PROTOCOL_SHA256: Final = "227c22a527e567bc4de873ab743fe9f493779eccbb1a698d2913c87695ebf87a"
HARTREE_TO_EV: Final = 27.211386245988
BOHR_TO_ANGSTROM: Final = 0.529177210903
FORCE_HARTREE_PER_BOHR_TO_EV_PER_ANGSTROM: Final = HARTREE_TO_EV / BOHR_TO_ANGSTROM
PYSCF_VERSION: Final = "2.13.1"
PYSCF_DISPERSION_VERSION: Final = "1.5.0"
ATOMIC_NUMBERS: Final = {
    "H": 1,
    "B": 5,
    "C": 6,
    "N": 7,
    "O": 8,
    "F": 9,
    "Si": 14,
    "P": 15,
    "S": 16,
    "Cl": 17,
    "As": 33,
    "Se": 34,
    "Br": 35,
    "I": 53,
}


class DatasetAssemblyError(RuntimeError):
    """The parent-level training dataset failed its immutable contract."""


D3Projector = Callable[[dict[str, Any]], dict[str, Any]]


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_regular(path: Path, *, maximum: int = 128 << 20) -> bytes:
    before = path.lstat()
    if path.is_symlink() or not path.is_file() or before.st_nlink != 1:
        raise DatasetAssemblyError(f"input is not a single-link regular file: {path.name}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(fd, min(1 << 20, maximum + 1 - observed))
            if not chunk:
                break
            chunks.append(chunk)
            observed += len(chunk)
            if observed > maximum:
                raise DatasetAssemblyError("dataset input exceeds size bound")
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if (before.st_dev, before.st_ino, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise DatasetAssemblyError("dataset input changed during read")
    return b"".join(chunks)


def write_new(path: Path, raw: bytes) -> dict[str, object]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise DatasetAssemblyError("short dataset write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    if read_regular(path, maximum=max(len(raw), 1)) != raw:
        raise DatasetAssemblyError("dataset output reread mismatch")
    return {"path": str(path), "bytes": len(raw), "sha256": sha256_bytes(raw)}


def _json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = read_regular(path)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DatasetAssemblyError(f"invalid JSON: {path.name}") from exc
    if not isinstance(payload, dict):
        raise DatasetAssemblyError(f"JSON root is not an object: {path.name}")
    return cast(dict[str, Any], payload), raw


def load_split(path: Path) -> tuple[dict[str, str], dict[str, dict[str, Any]], str]:
    payload, raw = _json(path)
    if payload.get("schema") != SPLIT_SCHEMA:
        raise DatasetAssemblyError("split schema mismatch")
    assignments: dict[str, str] = {}
    profiles: dict[str, dict[str, Any]] = {}
    for split in ("train", "validation", "final_test"):
        candidates = payload.get(split)
        if not isinstance(candidates, list) or not candidates:
            raise DatasetAssemblyError(f"split is empty: {split}")
        for profile in candidates:
            if not isinstance(profile, dict):
                raise DatasetAssemblyError("candidate profile is not an object")
            candidate = profile.get("candidate")
            if not isinstance(candidate, str) or candidate in assignments:
                raise DatasetAssemblyError("duplicate or invalid split candidate")
            assignments[candidate] = split
            profiles[candidate] = profile
    return assignments, profiles, sha256_bytes(raw)


def _finite_matrix(value: object, *, rows: int, label: str) -> np.ndarray:
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (rows, 3) or not np.isfinite(result).all():
        raise DatasetAssemblyError(f"{label} is not a finite {rows}x3 matrix")
    return result


def _load_frame(
    path: Path,
    *,
    expected_sha256: str,
    expected_candidate: str,
    expected_endpoint: str,
    expected_index: int,
) -> tuple[dict[str, Any], dict[str, np.ndarray | float | int | str]]:
    payload, raw = _json(path)
    if sha256_bytes(raw) != expected_sha256:
        raise DatasetAssemblyError("training frame file SHA256 mismatch")
    if payload.get("schema") != FRAME_SCHEMA:
        raise DatasetAssemblyError("training frame schema mismatch")
    if (
        payload.get("candidate") != expected_candidate
        or payload.get("endpoint") != expected_endpoint
        or payload.get("frame_index") != expected_index
    ):
        raise DatasetAssemblyError("training frame identity mismatch")
    if payload.get("parent_protocol_sha256") != PARENT_PROTOCOL_SHA256:
        raise DatasetAssemblyError("training frame protocol mismatch")
    canonical_digest = payload.get("canonical_sha256")
    without_digest = dict(payload)
    without_digest.pop("canonical_sha256", None)
    if canonical_digest != sha256_bytes(canonical_json(without_digest)):
        raise DatasetAssemblyError("training frame canonical SHA256 mismatch")
    atom_count = payload.get("atom_count")
    elements = payload.get("elements")
    if type(atom_count) is not int or not isinstance(elements, list) or len(elements) != atom_count:
        raise DatasetAssemblyError("training frame atom identity mismatch")
    try:
        numbers = np.asarray([ATOMIC_NUMBERS[str(element)] for element in elements], dtype=np.int64)
    except KeyError as exc:
        raise DatasetAssemblyError("training frame contains unsupported element") from exc
    coordinates_bohr = _finite_matrix(
        payload.get("coordinates_bohr"), rows=atom_count, label="coordinates"
    )
    forces_au = _finite_matrix(
        payload.get("forces_hartree_per_bohr"), rows=atom_count, label="forces"
    )
    gradients_au = _finite_matrix(
        payload.get("gradient_hartree_per_bohr"), rows=atom_count, label="gradients"
    )
    if not np.array_equal(forces_au, -gradients_au):
        raise DatasetAssemblyError("training force is not exactly negative gradient")
    energy_hartree = float(payload.get("energy_hartree", math.nan))
    if not math.isfinite(energy_hartree) or payload.get("scf_converged") is not True:
        raise DatasetAssemblyError("training frame energy/SCF state is invalid")
    charge = payload.get("charge")
    if type(charge) is not int or charge != (1 if expected_endpoint == "cation" else 0):
        raise DatasetAssemblyError("training frame charge mismatch")
    record: dict[str, np.ndarray | float | int | str] = {
        "coord": coordinates_bohr * BOHR_TO_ANGSTROM,
        "numbers": numbers,
        "charge": charge,
        "_energy_hartree": energy_hartree,
        "_gradients_au": gradients_au,
        "_forces_au": forces_au,
        "candidate": expected_candidate,
        "endpoint": expected_endpoint,
        "frame_index": expected_index,
    }
    return payload, record


def _pyscf_d3_projector(frame: dict[str, Any]) -> dict[str, Any]:
    """Recompute the frozen external D3 term for one immutable P01 frame."""

    try:
        import pyscf  # type: ignore[import-untyped]
        from pyscf import gto
        from pyscf.dispersion import dftd3  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - remote scientific environment only
        raise DatasetAssemblyError("PySCF D3 projection environment is unavailable") from exc
    pyscf_version = str(pyscf.__version__)
    dispersion_version = importlib.metadata.version("pyscf-dispersion")
    if pyscf_version != PYSCF_VERSION or dispersion_version != PYSCF_DISPERSION_VERSION:
        raise DatasetAssemblyError("PySCF D3 projection version drifted")
    elements = cast(list[str], frame["elements"])
    coordinates = cast(list[list[float]], frame["coordinates_bohr"])
    molecule = gto.M(
        atom=list(zip(elements, coordinates, strict=True)),
        unit="Bohr",
        basis="def2-TZVPP",
        charge=int(frame["charge"]),
        spin=int(frame["spin"]),
        verbose=0,
    )
    if int(molecule.nelectron) != int(frame["electron_count"]):
        raise DatasetAssemblyError("D3 projection electron count drifted")
    audit = dftd3.DFTD3Dispersion(molecule, xc="wb97m", version="d3bj", atm=False).get_dispersion(
        grad=True
    )
    return {
        "energy_hartree": float(audit["energy"]),
        "gradient_hartree_per_bohr": np.asarray(audit["gradient"], dtype=np.float64),
        "pyscf_version": pyscf_version,
        "pyscf_dispersion_version": dispersion_version,
        "functional": "wb97m",
        "damping": "d3bj",
        "atm": False,
    }


def _project_model_target(
    *,
    frame: dict[str, Any],
    record: dict[str, np.ndarray | float | int | str],
    source_frame_sha256: str,
    projector: D3Projector,
) -> tuple[dict[str, np.ndarray | float | int | str], dict[str, Any]]:
    atom_count = int(frame["atom_count"])
    projection = projector(frame)
    d3_energy = float(projection.get("energy_hartree", math.nan))
    d3_gradient = _finite_matrix(
        projection.get("gradient_hartree_per_bohr"),
        rows=atom_count,
        label="D3 gradient",
    )
    if not math.isfinite(d3_energy):
        raise DatasetAssemblyError("D3 projection energy is non-finite")
    total_energy = float(record["_energy_hartree"])
    total_gradient = cast(np.ndarray, record["_gradients_au"])
    total_forces = cast(np.ndarray, record["_forces_au"])
    residual_gradient = total_gradient - d3_gradient
    d3_forces = -d3_gradient
    residual_forces = total_forces - d3_forces
    if not np.array_equal(residual_forces, -residual_gradient):
        raise DatasetAssemblyError("D3-subtracted force/gradient identity drifted")
    residual_energy = total_energy - d3_energy
    projected = dict(record)
    projected.update(
        {
            "energy": residual_energy * HARTREE_TO_EV,
            "forces": residual_forces * FORCE_HARTREE_PER_BOHR_TO_EV_PER_ANGSTROM,
            "total_energy": total_energy * HARTREE_TO_EV,
            "total_forces": total_forces * FORCE_HARTREE_PER_BOHR_TO_EV_PER_ANGSTROM,
            "d3_energy": d3_energy * HARTREE_TO_EV,
            "d3_forces": d3_forces * FORCE_HARTREE_PER_BOHR_TO_EV_PER_ANGSTROM,
        }
    )
    evidence: dict[str, Any] = {
        "schema": D3_PROJECTION_SCHEMA,
        "candidate": frame["candidate"],
        "endpoint": frame["endpoint"],
        "frame_index": frame["frame_index"],
        "source_frame_sha256": source_frame_sha256,
        "geometry_sha256": frame["geometry_sha256"],
        "parent_protocol_sha256": PARENT_PROTOCOL_SHA256,
        "total_energy_hartree": total_energy,
        "total_gradient_hartree_per_bohr": total_gradient.tolist(),
        "d3_energy_hartree": d3_energy,
        "d3_gradient_hartree_per_bohr": d3_gradient.tolist(),
        "short_range_energy_hartree": residual_energy,
        "short_range_gradient_hartree_per_bohr": residual_gradient.tolist(),
        "short_range_forces_hartree_per_bohr": residual_forces.tolist(),
        "dispersion_identity": {
            key: value
            for key, value in projection.items()
            if key not in {"energy_hartree", "gradient_hartree_per_bohr"}
        },
        "external_d3_required_at_inference": True,
        "production_accepted": False,
    }
    evidence["canonical_sha256"] = sha256_bytes(canonical_json(evidence))
    return projected, evidence


def load_candidate_frames(
    *,
    candidate: str,
    split: str,
    profile: dict[str, Any],
    runs_root: Path,
    projection_root: Path,
    projector: D3Projector,
) -> tuple[list[dict[str, np.ndarray | float | int | str]], dict[str, object]]:
    run_root = runs_root / f"autofill_{candidate.lower()}_v001"
    result, _ = _json(run_root / "result.json")
    if result.get("final_outcome") != "PASS" or result.get("candidate") != candidate:
        raise DatasetAssemblyError(f"candidate route is not complete: {candidate}")
    training_receipt = result.get("training_data")
    if not isinstance(training_receipt, dict):
        raise DatasetAssemblyError("candidate result omitted training-data receipt")
    route_manifest_path = run_root / "training_data" / "manifest.json"
    route_manifest, route_raw = _json(route_manifest_path)
    if sha256_bytes(route_raw) != training_receipt.get("sha256"):
        raise DatasetAssemblyError("route training manifest binding mismatch")
    if (
        route_manifest.get("schema") != DATASET_MANIFEST_SCHEMA
        or route_manifest.get("candidate") != candidate
        or route_manifest.get("parent_protocol_sha256") != PARENT_PROTOCOL_SHA256
    ):
        raise DatasetAssemblyError("route training manifest identity mismatch")
    endpoint_bindings = route_manifest.get("endpoint_manifests")
    if not isinstance(endpoint_bindings, dict) or set(endpoint_bindings) != {"cation", "neutral"}:
        raise DatasetAssemblyError("route endpoint manifest set mismatch")
    records: list[dict[str, np.ndarray | float | int | str]] = []
    endpoint_evidence: dict[str, object] = {}
    for endpoint in ("cation", "neutral"):
        binding = endpoint_bindings[endpoint]
        if not isinstance(binding, dict):
            raise DatasetAssemblyError("endpoint manifest binding is invalid")
        manifest_path = run_root / "training_data" / endpoint / "manifest.json"
        manifest, manifest_raw = _json(manifest_path)
        if sha256_bytes(manifest_raw) != binding.get("sha256"):
            raise DatasetAssemblyError("endpoint manifest SHA256 mismatch")
        if (
            manifest.get("schema") != ENDPOINT_MANIFEST_SCHEMA
            or manifest.get("candidate") != candidate
            or manifest.get("endpoint") != endpoint
            or manifest.get("complete_geometry_optimization") is not True
        ):
            raise DatasetAssemblyError("endpoint training manifest identity mismatch")
        frame_bindings = manifest.get("frames")
        if not isinstance(frame_bindings, list) or not frame_bindings:
            raise DatasetAssemblyError("endpoint training manifest has no frames")
        expected_atom_count = profile[f"{endpoint}_atom_count"]
        endpoint_geometry_hashes: list[str] = []
        projection_receipts: list[dict[str, object]] = []
        for index, frame_binding in enumerate(frame_bindings):
            if not isinstance(frame_binding, dict) or frame_binding.get("frame_index") != index:
                raise DatasetAssemblyError("training frame sequence is not contiguous")
            frame_path = run_root / "training_data" / endpoint / f"frame_{index:04d}.json"
            frame, record = _load_frame(
                frame_path,
                expected_sha256=str(frame_binding.get("sha256")),
                expected_candidate=candidate,
                expected_endpoint=endpoint,
                expected_index=index,
            )
            if frame["atom_count"] != expected_atom_count:
                raise DatasetAssemblyError("training frame differs from split atom count")
            record, projection_evidence = _project_model_target(
                frame=frame,
                record=record,
                source_frame_sha256=str(frame_binding.get("sha256")),
                projector=projector,
            )
            projection_receipt = write_new(
                projection_root / candidate / endpoint / f"frame_{index:04d}.json",
                canonical_json(projection_evidence),
            )
            projection_receipt.update(
                {
                    "frame_index": index,
                    "canonical_sha256": projection_evidence["canonical_sha256"],
                }
            )
            projection_receipts.append(projection_receipt)
            endpoint_geometry_hashes.append(str(frame["geometry_sha256"]))
            records.append(record)
        endpoint_evidence[endpoint] = {
            "manifest_sha256": sha256_bytes(manifest_raw),
            "frame_count": len(frame_bindings),
            "geometry_sha256": endpoint_geometry_hashes,
            "d3_projections": projection_receipts,
        }
    return records, {
        "candidate": candidate,
        "split": split,
        "run_root": str(run_root),
        "route_manifest_sha256": sha256_bytes(route_raw),
        "endpoints": endpoint_evidence,
    }


def _npz(records: list[dict[str, np.ndarray | float | int | str]]) -> bytes:
    arrays = {
        "coord": np.stack([cast(np.ndarray, record["coord"]) for record in records]).astype(
            np.float32
        ),
        "numbers": np.stack([cast(np.ndarray, record["numbers"]) for record in records]).astype(
            np.int64
        ),
        "charge": np.asarray([record["charge"] for record in records], dtype=np.float32),
        "energy": np.asarray([record["energy"] for record in records], dtype=np.float64),
        "forces": np.stack([cast(np.ndarray, record["forces"]) for record in records]).astype(
            np.float32
        ),
        "total_energy": np.asarray(
            [record["total_energy"] for record in records], dtype=np.float64
        ),
        "total_forces": np.stack(
            [cast(np.ndarray, record["total_forces"]) for record in records]
        ).astype(np.float32),
        "d3_energy": np.asarray([record["d3_energy"] for record in records], dtype=np.float64),
        "d3_forces": np.stack([cast(np.ndarray, record["d3_forces"]) for record in records]).astype(
            np.float32
        ),
        "candidate": np.asarray([record["candidate"] for record in records]),
        "endpoint": np.asarray([record["endpoint"] for record in records]),
        "frame_index": np.asarray([record["frame_index"] for record in records], dtype=np.int64),
    }
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **cast(dict[str, Any], arrays))
    return buffer.getvalue()


def assemble(
    *,
    split_path: Path,
    runs_root: Path,
    output_root: Path,
    projector: D3Projector | None = None,
) -> dict[str, object]:
    assignments, profiles, split_sha256 = load_split(split_path)
    output_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    effective_projector = projector or _pyscf_d3_projector
    grouped: dict[str, dict[int, list[dict[str, np.ndarray | float | int | str]]]] = {
        split: defaultdict(list) for split in ("train", "validation", "final_test")
    }
    candidates: list[dict[str, object]] = []
    geometry_owners: dict[str, tuple[str, str]] = {}
    for candidate, split in assignments.items():
        records, evidence = load_candidate_frames(
            candidate=candidate,
            split=split,
            profile=profiles[candidate],
            runs_root=runs_root,
            projection_root=output_root / "d3_projection",
            projector=effective_projector,
        )
        for record in records:
            geometry_key = sha256_bytes(
                canonical_json(
                    {
                        "numbers": cast(np.ndarray, record["numbers"]).tolist(),
                        "coord": cast(np.ndarray, record["coord"]).tolist(),
                    }
                )
            )
            owner = geometry_owners.setdefault(geometry_key, (candidate, split))
            if owner != (candidate, split):
                raise DatasetAssemblyError("identical geometry crosses molecule split")
            atom_count = len(cast(np.ndarray, record["numbers"]))
            grouped[split][atom_count].append(record)
        candidates.append(evidence)
    files: dict[str, list[dict[str, object]]] = {}
    split_counts: dict[str, int] = {}
    for split, groups in grouped.items():
        files[split] = []
        split_counts[split] = 0
        for atom_count, records in sorted(groups.items()):
            raw = _npz(records)
            receipt = write_new(output_root / split / f"{atom_count:03d}.npz", raw)
            receipt.update({"atom_count": atom_count, "frame_count": len(records)})
            files[split].append(receipt)
            split_counts[split] += len(records)
    manifest = {
        "schema": OUTPUT_SCHEMA,
        "parent_protocol_sha256": PARENT_PROTOCOL_SHA256,
        "split_sha256": split_sha256,
        "split_unit": "InChIKey",
        "candidate_count": len(assignments),
        "candidate_evidence": candidates,
        "frame_count_by_split": split_counts,
        "files": files,
        "model_input_units": {
            "coord": "Angstrom",
            "energy": "eV",
            "forces": "eV/Angstrom",
            "charge": "elementary_charge",
        },
        "storage_dtypes": {
            "coord": "float32",
            "numbers": "int64",
            "charge": "float32",
            "energy": "float64_before_sae_float32_after_sae",
            "forces": "float32",
            "total_energy": "float64",
            "total_forces": "float32",
            "d3_energy": "float64",
            "d3_forces": "float32",
        },
        "source_units": {
            "coord": "Bohr",
            "energy": "Hartree",
            "forces": "Hartree/Bohr",
        },
        "conversion_constants": {
            "hartree_to_ev": HARTREE_TO_EV,
            "bohr_to_angstrom": BOHR_TO_ANGSTROM,
            "force_hartree_per_bohr_to_ev_per_angstrom": FORCE_HARTREE_PER_BOHR_TO_EV_PER_ANGSTROM,
        },
        "training_keys": {
            "x": ["coord", "numbers", "charge"],
            "y": ["energy", "forces"],
        },
        "target_definition": {
            "energy": "P01_total_energy_minus_frozen_two_body_D3_BJ",
            "forces": "P01_total_forces_minus_frozen_two_body_D3_BJ_forces",
            "external_d3_required_at_inference": True,
            "d3_functional": "wb97m",
            "d3_damping": "d3bj",
            "atm": False,
        },
        "final_test_used_for_training": False,
        "production_accepted": False,
    }
    manifest_receipt = write_new(output_root / "manifest.json", canonical_json(manifest))
    return {"manifest": manifest, "receipt": manifest_receipt}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--split", required=True)
    result.add_argument("--runs-root", required=True)
    result.add_argument("--output-root", required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    assemble(
        split_path=Path(args.split).resolve(strict=True),
        runs_root=Path(args.runs_root).resolve(strict=True),
        output_root=Path(args.output_root),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
