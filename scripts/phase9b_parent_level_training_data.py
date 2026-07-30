#!/usr/bin/env python3
"""Immutable parent-level energy/gradient frames for AIMNet2 fine-tuning."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Final, cast

FRAME_SCHEMA: Final = "phase9b-parent-level-training-frame-v1"
ENDPOINT_MANIFEST_SCHEMA: Final = "phase9b-parent-level-training-endpoint-v1"
DATASET_MANIFEST_SCHEMA: Final = "phase9b-parent-level-training-route-v1"
PARENT_PROTOCOL_SHA256: Final = "227c22a527e567bc4de873ab743fe9f493779eccbb1a698d2913c87695ebf87a"


class TrainingDataError(RuntimeError):
    """A parent-level training frame could not be recorded safely."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_regular(path: Path, *, maximum: int = 64 << 20) -> bytes:
    before = path.lstat()
    if path.is_symlink() or not path.is_file() or before.st_nlink != 1:
        raise TrainingDataError("training evidence is not a single-link regular file")
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
                raise TrainingDataError("training evidence exceeds size bound")
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if (before.st_dev, before.st_ino, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise TrainingDataError("training evidence identity changed during read")
    return b"".join(chunks)


def write_new(path: Path, raw: bytes) -> dict[str, object]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise TrainingDataError("short training evidence write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    if read_regular(path, maximum=max(len(raw), 1)) != raw:
        raise TrainingDataError("training evidence reread mismatch")
    return {"path": path.name, "bytes": len(raw), "sha256": sha256_bytes(raw)}


def _matrix(value: object, *, rows: int, label: str) -> list[list[float]]:
    candidate = value.tolist() if hasattr(value, "tolist") else value
    if not isinstance(candidate, (list, tuple)) or len(candidate) != rows:
        raise TrainingDataError(f"{label} row count mismatch")
    result: list[list[float]] = []
    for row in candidate:
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            raise TrainingDataError(f"{label} shape mismatch")
        numeric = [float(component) for component in row]
        if not all(math.isfinite(component) for component in numeric):
            raise TrainingDataError(f"{label} contains non-finite values")
        result.append(numeric)
    return result


class TrainingFrameRecorder:
    """Write one immutable frame after each converged analytic-gradient call."""

    def __init__(self, *, root: Path, candidate: str, source_sha256: str) -> None:
        self.root = root
        self.candidate = candidate
        self.source_sha256 = source_sha256
        self.frames: dict[str, list[dict[str, object]]] = {"cation": [], "neutral": []}
        self.endpoint_manifests: dict[str, dict[str, object]] = {}
        self.root.mkdir(mode=0o700, parents=False, exist_ok=False)

    def capture(self, environment: dict[str, object], *, endpoint: str) -> dict[str, object]:
        if endpoint not in self.frames:
            raise TrainingDataError("unknown training endpoint")
        scanner = environment.get("g_scanner")
        if getattr(scanner, "converged", None) is not True:
            raise TrainingDataError("training frame SCF is not explicitly converged")
        molecule = cast(Any, environment.get("mol"))
        if molecule is None:
            raise TrainingDataError("training callback omitted molecule")
        atom_count = int(getattr(molecule, "natm", 0))
        if atom_count <= 0:
            raise TrainingDataError("training frame has no atoms")
        elements = [str(molecule.atom_symbol(index)) for index in range(atom_count)]
        coordinates = _matrix(
            molecule.atom_coords(unit="Bohr"), rows=atom_count, label="coordinates"
        )
        gradients = _matrix(environment.get("gradients"), rows=atom_count, label="gradients")
        energy = float(cast(Any, environment.get("energy", math.nan)))
        if not math.isfinite(energy):
            raise TrainingDataError("training frame energy is non-finite")
        charge = int(getattr(molecule, "charge", 99))
        spin = int(getattr(molecule, "spin", 99))
        expected_charge = 1 if endpoint == "cation" else 0
        if charge != expected_charge or spin != 0:
            raise TrainingDataError("training frame endpoint state drifted")
        frame_index = len(self.frames[endpoint])
        geometry_identity = {
            "elements": elements,
            "coordinates_bohr": coordinates,
        }
        body: dict[str, object] = {
            "schema": FRAME_SCHEMA,
            "candidate": self.candidate,
            "endpoint": endpoint,
            "frame_index": frame_index,
            "parent_protocol_sha256": PARENT_PROTOCOL_SHA256,
            "source_sha256": self.source_sha256,
            "charge": charge,
            "multiplicity": spin + 1,
            "spin": spin,
            "electron_count": int(getattr(molecule, "nelectron", -1)),
            "atom_count": atom_count,
            "elements": elements,
            "coordinates_bohr": coordinates,
            "energy_hartree": energy,
            "gradient_hartree_per_bohr": gradients,
            "forces_hartree_per_bohr": [[-component for component in row] for row in gradients],
            "geometry_sha256": sha256_bytes(canonical_json(geometry_identity)),
            "scf_converged": True,
            "total_energy_includes_two_body_d3_bj": True,
            "atm": False,
            "vv10": False,
            "production_accepted": False,
        }
        body["canonical_sha256"] = sha256_bytes(canonical_json(body))
        path = self.root / endpoint / f"frame_{frame_index:04d}.json"
        receipt = write_new(path, canonical_json(body))
        receipt.update(
            {
                "frame_index": frame_index,
                "canonical_sha256": body["canonical_sha256"],
                "geometry_sha256": body["geometry_sha256"],
            }
        )
        self.frames[endpoint].append(receipt)
        return receipt

    def finalize_endpoint(self, endpoint: str) -> dict[str, object]:
        frames = self.frames.get(endpoint)
        if not frames:
            raise TrainingDataError("cannot finalize an endpoint without frames")
        payload = {
            "schema": ENDPOINT_MANIFEST_SCHEMA,
            "candidate": self.candidate,
            "endpoint": endpoint,
            "parent_protocol_sha256": PARENT_PROTOCOL_SHA256,
            "frame_count": len(frames),
            "frames": frames,
            "complete_geometry_optimization": True,
            "production_accepted": False,
        }
        receipt = write_new(self.root / endpoint / "manifest.json", canonical_json(payload))
        receipt.update({"endpoint": endpoint, "frame_count": len(frames)})
        self.endpoint_manifests[endpoint] = receipt
        return receipt

    def finalize_dataset(self) -> dict[str, object]:
        if set(self.endpoint_manifests) != {"cation", "neutral"}:
            raise TrainingDataError("both endpoint manifests are required")
        payload = {
            "schema": DATASET_MANIFEST_SCHEMA,
            "candidate": self.candidate,
            "parent_protocol_sha256": PARENT_PROTOCOL_SHA256,
            "source_sha256": self.source_sha256,
            "endpoint_manifests": self.endpoint_manifests,
            "split_unit": "InChIKey",
            "training_admission": "pending_dataset_audit",
            "production_accepted": False,
        }
        return write_new(self.root / "manifest.json", canonical_json(payload))
