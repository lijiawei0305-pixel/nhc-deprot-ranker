#!/usr/bin/env python3
"""One-candidate, non-production AIMNet2 -> PySCF science pilot.

This entry point deliberately lives outside the Phase 9B runner source closure.
It does not consume a permit, enter a campaign, or write production receipts.
It reuses the frozen scientific implementations behind their authority shells
for one explicitly authorized ``science_pilot_only`` experiment.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import importlib.util
import json
import math
import os
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, cast

CANDIDATE: Final = "LBNPGYISTSLAHY-UHFFFAOYSA-N"
PILOT_KIND: Final = "science_pilot_only"
PILOT_SCHEMA: Final = "nhc-phase9b-science-pilot-v2"
PILOT_RUN_NAME: Final = "science_pilot_lbn_v002"

ENDPOINTS: Final = ("cation", "neutral")
CHARGES: Final = {"cation": 1, "neutral": 0}
MULTIPLICITIES: Final = {"cation": 1, "neutral": 1}
ATOM_COUNTS: Final = {"cation": 26, "neutral": 25}
INPUT_SHA256: Final = {
    "cation": "543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286",
    "neutral": "af9c30640801eec3ab27538a33204186849303dd57592ca5c93320ec1390f4b8",
}
INPUT_BYTES: Final = {"cation": 1075, "neutral": 1036}
ATOM_MAP: Final = {"C2_carbene": 14, "N1": 8, "N3": 15}
ACIDIC_PROTON_INDEX: Final = 23
ELECTRON_COUNT: Final = 160

WEIGHT_FILENAME: Final = "aimnet2_wb97m_d3_0.pt"
WEIGHT_BYTES: Final = 8_836_941
WEIGHT_SHA256: Final = "f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28"

HARTREE_TO_KCAL_MOL: Final = 627.509474
GAS_PROTON_KCAL_MOL: Final = -6.28
LABEL_FORMULA: Final = "((E_neutral_PySCF - E_cation_PySCF) * 627.509474) - 6.28"

AIMNET_WALL_LIMIT_SECONDS: Final = 900.0
PYSCF_WALL_LIMIT_SECONDS: Final = 7200.0
MAX_ABS_COORDINATE_ANGSTROM: Final = 100.0
MIN_PAIR_DISTANCE_ANGSTROM: Final = 0.20
FILE_MODE: Final = 0o600
DIRECTORY_MODE: Final = 0o700
MAX_EVIDENCE_BYTES: Final = 64 << 20
P01R4_SHORT_CACHE_MODE: Final = "NHC_P01R4_SHORT_CACHE_MODE"
P01R4_SHORT_CACHE_AUDIT: Final = "NHC_P01R4_SHORT_CACHE_AUDIT"
P01R4_SHORT_CACHE_ROOT: Final = "NHC_P01R2_SHORT_TMP_ROOT"
P01R4_CACHE_VARIABLES: Final = (
    "TMPDIR",
    "TMP",
    "TEMP",
    "CUDA_CACHE_PATH",
    "TORCH_EXTENSIONS_DIR",
    "TORCHINDUCTOR_CACHE_DIR",
    "TRITON_CACHE_DIR",
    "XDG_CACHE_HOME",
    "NUMBA_CACHE_DIR",
    "TORCH_HOME",
    "HF_HOME",
)

ATOMIC_NUMBERS: Final = {"H": 1, "C": 6, "N": 7, "F": 9}


class PilotError(RuntimeError):
    """The isolated pilot could not satisfy its frozen contract."""


class ScientificFailure(PilotError):
    """The frozen candidate or scientific method failed a measured gate."""


class InconclusiveFailure(PilotError):
    """Infrastructure prevented a scientific conclusion."""


class HandoffFailure(ScientificFailure):
    """The AIMNet2-to-PySCF byte or chemical identity was not preserved."""


@dataclass(frozen=True, slots=True)
class ProtonHostIdentity:
    """Index-bound identity of the one frozen cation acidic proton."""

    proton_atom_index: int
    initial_host_atom_index: int
    final_host_atom_index: int | None
    preserved: bool


@dataclass(frozen=True, slots=True)
class PilotStructuralValidation:
    """Pilot-only structure gates with no hard-coded chemical host assumption."""

    total_rmsd_angstrom: float
    max_single_atom_displacement_angstrom: float
    c2_n1_bond_change_angstrom: float
    c2_n3_bond_change_angstrom: float
    ring_angle_change_degrees: float
    atom_count_preserved: bool
    atom_order_preserved: bool
    connectivity_preserved: bool
    proton_host_index_preserved: bool
    acidic_proton_index: int | None
    initial_host_atom_index: int | None
    final_host_atom_index: int | None
    all_gates_passed: bool


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _make_directory(path: Path) -> None:
    path.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
    observed = path.lstat()
    if not stat.S_ISDIR(observed.st_mode) or path.is_symlink():
        raise PilotError(f"unsafe pilot directory: {path}")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_new(path: Path, raw: bytes) -> dict[str, object]:
    if len(raw) > MAX_EVIDENCE_BYTES:
        raise PilotError(f"evidence exceeds its size limit: {path.name}")
    _make_directory(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, FILE_MODE)
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            raise PilotError(f"unsafe new evidence file: {path.name}")
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)
    reread = _read_regular_file(path)
    if reread != raw:
        raise PilotError(f"evidence reread mismatch: {path.name}")
    return {"bytes": len(raw), "sha256": _sha256(raw)}


def _write_json_new(path: Path, payload: object) -> dict[str, object]:
    return _write_new(path, _canonical_json_bytes(payload))


def _read_regular_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise PilotError(f"not a regular file: {path}")
        if before.st_size < 0 or before.st_size > MAX_EVIDENCE_BYTES:
            raise PilotError(f"file size is outside the pilot limit: {path}")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1 << 20))
            if not chunk:
                raise PilotError(f"short read: {path}")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise PilotError(f"file identity drifted while reading: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _validate_p01r4_short_cache_environment(
    environ: Mapping[str, str],
    *,
    allowed_parents: Sequence[Path] = (Path("/dev/shm"), Path("/tmp")),
    maximum_root_length: int = 40,
) -> Path | None:
    mode = environ.get(P01R4_SHORT_CACHE_MODE)
    if mode is None:
        return None
    if mode != "1":
        raise PilotError("P01-R4 short-cache mode was not explicitly enabled")
    root_text = environ.get(P01R4_SHORT_CACHE_ROOT)
    audit_text = environ.get(P01R4_SHORT_CACHE_AUDIT)
    if not root_text or not audit_text:
        raise PilotError("P01-R4 short-cache root or audit binding is absent")
    logical_root = Path(root_text)
    if not logical_root.is_absolute() or len(logical_root.as_posix()) > maximum_root_length:
        raise PilotError("P01-R4 short-cache root is not a short absolute path")
    if logical_root in {Path("/"), Path("/tmp"), Path("/dev/shm")}:
        raise PilotError("P01-R4 short-cache root is a broad directory")
    if not logical_root.name.startswith("p01r4."):
        raise PilotError("P01-R4 short-cache root was not created with its registered prefix")
    root = logical_root.resolve(strict=True)
    allowed = {parent.resolve(strict=True) for parent in allowed_parents}
    if root.parent not in allowed:
        raise PilotError("P01-R4 short-cache root is outside its registered parent")
    observed = logical_root.lstat()
    if (
        not stat.S_ISDIR(observed.st_mode)
        or logical_root.is_symlink()
        or observed.st_uid != os.getuid()
        or stat.S_IMODE(observed.st_mode) != DIRECTORY_MODE
        or not os.access(root, os.W_OK)
    ):
        raise PilotError("P01-R4 short-cache root owner, mode, type, or access drifted")
    audit = json.loads(_read_regular_file(Path(audit_text)))
    if (
        audit.get("root") != logical_root.as_posix()
        or audit.get("resolved_root") != root.as_posix()
        or audit.get("created_by_mkdtemp") is not True
    ):
        raise PilotError("P01-R4 short-cache audit does not bind the effective root")
    for name in P01R4_CACHE_VARIABLES:
        value = environ.get(name)
        if not value:
            raise PilotError(f"P01-R4 short-cache variable is absent: {name}")
        logical_child = Path(value)
        if not logical_child.is_absolute() or logical_child.is_symlink():
            raise PilotError(f"P01-R4 short-cache variable is unsafe: {name}")
        child = logical_child.resolve(strict=True)
        try:
            child.relative_to(root)
        except ValueError as exc:
            raise PilotError(f"P01-R4 short-cache variable escaped its root: {name}") from exc
        child_stat = logical_child.lstat()
        if (
            not stat.S_ISDIR(child_stat.st_mode)
            or child_stat.st_uid != os.getuid()
            or stat.S_IMODE(child_stat.st_mode) != DIRECTORY_MODE
            or not os.access(child, os.W_OK)
        ):
            raise PilotError(f"P01-R4 short-cache child owner, mode, or access drifted: {name}")
    return root


@contextlib.contextmanager
def _capture_fds(stdout_path: Path, stderr_path: Path) -> Iterator[None]:
    _make_directory(stdout_path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    stdout_fd = os.open(stdout_path, flags, FILE_MODE)
    stderr_fd = os.open(stderr_path, flags, FILE_MODE)
    saved_stdout = os.dup(1)
    saved_stderr = os.dup(2)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(stdout_fd, 1)
        os.dup2(stderr_fd, 2)
        try:
            yield
        finally:
            with contextlib.suppress(BaseException):
                sys.stdout.flush()
            with contextlib.suppress(BaseException):
                sys.stderr.flush()
            with contextlib.suppress(OSError):
                os.fsync(stdout_fd)
            with contextlib.suppress(OSError):
                os.fsync(stderr_fd)
    finally:
        os.dup2(saved_stdout, 1)
        os.dup2(saved_stderr, 2)
        os.close(saved_stdout)
        os.close(saved_stderr)
        os.close(stdout_fd)
        os.close(stderr_fd)
        _fsync_directory(stdout_path.parent)


@contextlib.contextmanager
def _working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _add_source_root(source_root: Path) -> None:
    try:
        source = source_root.resolve(strict=True)
    except OSError as exc:
        raise InconclusiveFailure("pilot source root is unavailable") from exc
    package = source / "nhc_deprot_ranker"
    if not package.is_dir() or package.is_symlink():
        raise PilotError("pilot source root does not contain nhc_deprot_ranker")
    sys.path.insert(0, str(source))


def _parse_xyz_minimal(
    raw: bytes,
) -> tuple[tuple[str, ...], tuple[tuple[float, float, float], ...]]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise PilotError("XYZ is not UTF-8") from exc
    if len(lines) < 3:
        raise PilotError("XYZ is too short")
    try:
        atom_count = int(lines[0].strip())
    except ValueError as exc:
        raise PilotError("XYZ atom count is invalid") from exc
    if len(lines) != atom_count + 2:
        raise PilotError("XYZ line count drifted")
    elements: list[str] = []
    coordinates: list[tuple[float, float, float]] = []
    for line in lines[2:]:
        fields = line.split()
        if len(fields) != 4:
            raise PilotError("XYZ atom row must have exactly four fields")
        try:
            point = tuple(float(value) for value in fields[1:])
        except ValueError as exc:
            raise PilotError("XYZ coordinate is invalid") from exc
        if len(point) != 3 or not all(math.isfinite(value) for value in point):
            raise PilotError("XYZ coordinate is non-finite")
        elements.append(fields[0])
        coordinates.append(point)
    return tuple(elements), tuple(coordinates)


def _minimum_pair_distance(points: Sequence[Sequence[float]]) -> float:
    distances = []
    for left in range(len(points)):
        for right in range(left + 1, len(points)):
            distances.append(
                math.sqrt(sum((points[left][axis] - points[right][axis]) ** 2 for axis in range(3)))
            )
    if not distances:
        raise PilotError("geometry does not contain an atom pair")
    return min(distances)


def _distance(points: Sequence[Sequence[float]], left: int, right: int) -> float:
    return math.sqrt(sum((points[left][axis] - points[right][axis]) ** 2 for axis in range(3)))


def _angle_degrees(points: Sequence[Sequence[float]], left: int, centre: int, right: int) -> float:
    first = [points[left][axis] - points[centre][axis] for axis in range(3)]
    second = [points[right][axis] - points[centre][axis] for axis in range(3)]
    first_norm = math.sqrt(sum(value * value for value in first))
    second_norm = math.sqrt(sum(value * value for value in second))
    if first_norm == 0.0 or second_norm == 0.0:
        raise PilotError("structure contains a degenerate mapped angle")
    cosine = sum(first[axis] * second[axis] for axis in range(3)) / (first_norm * second_norm)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _bonded_neighbors(bonds: frozenset[tuple[int, int]], atom_index: int) -> tuple[int, ...]:
    return tuple(
        sorted(
            right if left == atom_index else left
            for left, right in bonds
            if left == atom_index or right == atom_index
        )
    )


def validate_proton_host_identity(
    *,
    elements_before: Sequence[str],
    bonds_before: frozenset[tuple[int, int]],
    elements_after: Sequence[str],
    bonds_after: frozenset[tuple[int, int]],
    proton_atom_index: int,
    expected_initial_host_atom_index: int,
) -> ProtonHostIdentity:
    """Require the frozen proton to remain on its observed original atom index."""

    if (
        proton_atom_index >= len(elements_before)
        or proton_atom_index >= len(elements_after)
        or elements_before[proton_atom_index] != "H"
        or elements_after[proton_atom_index] != "H"
    ):
        raise PilotError("the frozen acidic proton index is not hydrogen")
    initial_hosts = tuple(
        index
        for index in _bonded_neighbors(bonds_before, proton_atom_index)
        if elements_before[index] != "H"
    )
    if initial_hosts != (expected_initial_host_atom_index,):
        raise PilotError("the frozen input acidic proton host identity drifted")
    final_hosts = tuple(
        index
        for index in _bonded_neighbors(bonds_after, proton_atom_index)
        if elements_after[index] != "H"
    )
    final_host = final_hosts[0] if len(final_hosts) == 1 else None
    return ProtonHostIdentity(
        proton_atom_index=proton_atom_index,
        initial_host_atom_index=initial_hosts[0],
        final_host_atom_index=final_host,
        preserved=final_hosts == initial_hosts,
    )


def _validate_pilot_structure(
    *,
    runtime: Any,
    endpoint: str,
    elements_before: Sequence[str],
    before: Sequence[Sequence[float]],
    elements_after: Sequence[str],
    after: Sequence[Sequence[float]],
) -> PilotStructuralValidation:
    """Apply the frozen gates while deriving proton identity from the input graph."""

    atom_count_preserved = len(elements_before) == len(elements_after)
    atom_order_preserved = tuple(elements_before) == tuple(elements_after)
    if not atom_count_preserved or not atom_order_preserved:
        raise PilotError("atom count or element order changed during preoptimization")
    c2, n1, n3 = ATOM_MAP["C2_carbene"], ATOM_MAP["N1"], ATOM_MAP["N3"]
    if elements_before[c2] != "C" or elements_before[n1] != "N" or elements_before[n3] != "N":
        raise PilotError("the frozen C2/N1/N3 atom map drifted")

    squared = sum(
        sum((after[index][axis] - before[index][axis]) ** 2 for axis in range(3))
        for index in range(len(before))
    )
    total_rmsd = math.sqrt(squared / len(before))
    max_displacement = max(
        _distance((before[index], after[index]), 0, 1) for index in range(len(before))
    )
    c2_n1_change = abs(_distance(after, c2, n1) - _distance(before, c2, n1))
    c2_n3_change = abs(_distance(after, c2, n3) - _distance(before, c2, n3))
    ring_angle_change = abs(_angle_degrees(after, n1, c2, n3) - _angle_degrees(before, n1, c2, n3))

    bonds_before = runtime.infer_connectivity(elements_before, before)
    bonds_after = runtime.infer_connectivity(elements_after, after)
    connectivity_preserved = bonds_before == bonds_after
    all_proton_hosts_preserved = runtime._proton_hosts(
        elements_before, bonds_before
    ) == runtime._proton_hosts(elements_after, bonds_after)

    acidic_proton_index: int | None = None
    initial_host_atom_index: int | None = None
    final_host_atom_index: int | None = None
    if endpoint == "cation":
        identity = validate_proton_host_identity(
            elements_before=elements_before,
            bonds_before=bonds_before,
            elements_after=elements_after,
            bonds_after=bonds_after,
            proton_atom_index=ACIDIC_PROTON_INDEX,
            expected_initial_host_atom_index=c2,
        )
        acidic_proton_index = identity.proton_atom_index
        initial_host_atom_index = identity.initial_host_atom_index
        final_host_atom_index = identity.final_host_atom_index
        proton_host_index_preserved = identity.preserved and all_proton_hosts_preserved
    elif endpoint == "neutral":
        initial_c2_hydrogens = tuple(
            index for index in _bonded_neighbors(bonds_before, c2) if elements_before[index] == "H"
        )
        final_c2_hydrogens = tuple(
            index for index in _bonded_neighbors(bonds_after, c2) if elements_after[index] == "H"
        )
        proton_host_index_preserved = (
            not initial_c2_hydrogens and not final_c2_hydrogens and all_proton_hosts_preserved
        )
    else:
        raise PilotError("unknown AIMNet2 endpoint")

    passed = (
        total_rmsd <= runtime.MAX_TOTAL_RMSD_ANGSTROM
        and max_displacement <= runtime.MAX_SINGLE_ATOM_DISPLACEMENT_ANGSTROM
        and c2_n1_change <= runtime.MAX_C2_N_BOND_CHANGE_ANGSTROM
        and c2_n3_change <= runtime.MAX_C2_N_BOND_CHANGE_ANGSTROM
        and ring_angle_change <= runtime.MAX_RING_ANGLE_CHANGE_DEGREES
        and connectivity_preserved
        and proton_host_index_preserved
    )
    return PilotStructuralValidation(
        total_rmsd_angstrom=total_rmsd,
        max_single_atom_displacement_angstrom=max_displacement,
        c2_n1_bond_change_angstrom=c2_n1_change,
        c2_n3_bond_change_angstrom=c2_n3_change,
        ring_angle_change_degrees=ring_angle_change,
        atom_count_preserved=atom_count_preserved,
        atom_order_preserved=atom_order_preserved,
        connectivity_preserved=connectivity_preserved,
        proton_host_index_preserved=proton_host_index_preserved,
        acidic_proton_index=acidic_proton_index,
        initial_host_atom_index=initial_host_atom_index,
        final_host_atom_index=final_host_atom_index,
        all_gates_passed=passed,
    )


def _validate_frozen_endpoint(
    endpoint: str,
    raw: bytes,
) -> tuple[tuple[str, ...], tuple[tuple[float, float, float], ...]]:
    if endpoint not in ENDPOINTS:
        raise PilotError("unknown endpoint")
    if len(raw) != INPUT_BYTES[endpoint] or _sha256(raw) != INPUT_SHA256[endpoint]:
        raise PilotError(f"{endpoint} frozen input identity drifted")
    elements, coordinates = _parse_xyz_minimal(raw)
    if len(elements) != ATOM_COUNTS[endpoint]:
        raise PilotError(f"{endpoint} atom count drifted")
    if elements[ATOM_MAP["C2_carbene"]] != "C":
        raise PilotError("C2 atom map drifted")
    if elements[ATOM_MAP["N1"]] != "N" or elements[ATOM_MAP["N3"]] != "N":
        raise PilotError("N atom map drifted")
    try:
        electrons = sum(ATOMIC_NUMBERS[element] for element in elements) - CHARGES[endpoint]
    except KeyError as exc:
        raise PilotError("frozen endpoint contains an unsupported element") from exc
    if electrons != ELECTRON_COUNT:
        raise PilotError(f"{endpoint} electron count drifted")
    return elements, coordinates


def _trajectory_payload(outcome: object) -> dict[str, object]:
    frames = []
    for frame in cast(Any, outcome).trajectory:
        payload = asdict(frame)
        payload["coordinates"] = [list(point) for point in frame.coordinates]
        frames.append(payload)
    return {
        "schema_version": "nhc-phase9b-science-pilot-trajectory-v1",
        "science_pilot_only": True,
        "frames": frames,
    }


def _failure_payload(stage: str, exc: BaseException) -> dict[str, object]:
    return {
        "stage": stage,
        "exception_class": type(exc).__name__,
        "message": str(exc)[:1000],
    }


def _empty_deprotonation() -> dict[str, object]:
    return {
        "formula": LABEL_FORMULA,
        "unit": "kcal/mol",
        "electronic_difference_kcal_per_mol": None,
        "value": None,
        "definition": "gas_phase_electronic_energy_only",
    }


def _minimal_endpoint_results(
    *, aimnet_status: Mapping[str, str] | None = None
) -> dict[str, object]:
    statuses = aimnet_status or {}
    return {
        endpoint: {
            "charge": CHARGES[endpoint],
            "multiplicity": MULTIPLICITIES[endpoint],
            "aimnet2_status": statuses.get(endpoint, "not_run"),
            "pyscf_status": "not_run",
            "energy_hartree": None,
        }
        for endpoint in ENDPOINTS
    }


def _gpu_observation(physical_index: int, expected_uuid: str) -> dict[str, object]:
    command = [
        "nvidia-smi",
        f"--id={physical_index}",
        "--query-gpu=index,name,uuid,compute_cap,memory.used,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    completed = subprocess.run(command, check=False, capture_output=True, timeout=15)
    if completed.returncode != 0:
        raise PilotError("nvidia-smi failed before the one-shot model load")
    try:
        fields = [field.strip() for field in completed.stdout.decode("utf-8").strip().split(",")]
        index_text, name, uuid, compute_cap, memory_used, utilization = fields
        memory_mib = int(memory_used)
        utilization_percent = int(utilization)
    except (UnicodeDecodeError, ValueError) as exc:
        raise PilotError("nvidia-smi returned an unexpected GPU identity") from exc
    if (
        int(index_text) != physical_index
        or uuid != expected_uuid
        or name != "Tesla V100-SXM2-32GB"
        or compute_cap != "7.0"
    ):
        raise PilotError("selected GPU identity drifted")
    if memory_mib > 100 or utilization_percent != 0:
        raise PilotError("selected V100 is not idle at the one-shot launch boundary")
    return {
        "physical_index": physical_index,
        "uuid": uuid,
        "name": name,
        "compute_capability": compute_cap,
        "memory_used_mib_before": memory_mib,
        "utilization_percent_before": utilization_percent,
    }


def _aimnet2_command(args: argparse.Namespace) -> int:
    root = Path(args.pilot_root).resolve(strict=True)
    if root.name != PILOT_RUN_NAME:
        raise PilotError("pilot root logical identity drifted")
    _add_source_root(Path(args.source_root))

    cache_root = root / "aimnet2" / "cache"
    _make_directory(cache_root)
    effective_cache_root = cache_root
    for name, value in {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }.items():
        os.environ[name] = value
    audited_short_root = _validate_p01r4_short_cache_environment(os.environ)
    short_root_text = os.environ.get(P01R4_SHORT_CACHE_ROOT)
    if short_root_text:
        short_root = Path(short_root_text).resolve(strict=True)
        if audited_short_root is None or audited_short_root != short_root:
            raise PilotError("P01-R4 audited short-cache mode is required for a short root")
        effective_cache_root = short_root
    else:
        for name in (
            "TORCHINDUCTOR_CACHE_DIR",
            "TRITON_CACHE_DIR",
            "CUDA_CACHE_PATH",
            "TORCH_HOME",
            "XDG_CACHE_HOME",
            "HF_HOME",
            "TMPDIR",
        ):
            destination = cache_root / name.lower()
            _make_directory(destination)
            os.environ[name] = str(destination)
    for forbidden in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "AIMNET2_MODEL"):
        os.environ.pop(forbidden, None)

    if audited_short_root is not None:
        _write_json_new(
            root / "aimnet2" / "short_cache_worker_environment.json",
            {
                "schema_version": "nhc-phase9b-parent-level-p01-r4-worker-environment-v1",
                "science_pilot_only": True,
                "pid": os.getpid(),
                "working_directory": Path.cwd().as_posix(),
                "short_root": audited_short_root.as_posix(),
                "tempfile_gettempdir": tempfile.gettempdir(),
                "environment": {name: os.environ[name] for name in P01R4_CACHE_VARIABLES},
                "physical_gpu_index": args.physical_gpu_index,
                "model_loaded": False,
            },
        )

    gpu = _gpu_observation(args.physical_gpu_index, args.physical_gpu_uuid)
    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.physical_gpu_index)

    from importlib import metadata

    from nhc_deprot_ranker.quantum import phase9b_aimnet2_runtime as runtime

    helper_path = Path(args.gau_loose_helper).resolve(strict=True)
    helper_spec = importlib.util.spec_from_file_location("phase9b_gau_loose_runtime", helper_path)
    if helper_spec is None or helper_spec.loader is None:
        raise PilotError("cannot load the frozen GAU_LOOSE helper")
    gau_loose = importlib.util.module_from_spec(helper_spec)
    sys.modules[helper_spec.name] = gau_loose
    helper_spec.loader.exec_module(gau_loose)
    gau_loose_contract = Path(args.gau_loose_contract).resolve(strict=True)
    profile = gau_loose.load_gau_loose_profile(gau_loose_contract)

    weight_path = Path(args.weight).resolve(strict=True)
    if (
        weight_path.name != WEIGHT_FILENAME
        or weight_path.stat().st_size != WEIGHT_BYTES
        or _sha256(_read_regular_file(weight_path)) != WEIGHT_SHA256
    ):
        raise PilotError("AIMNet2 weight identity drifted")
    runtime.verify_weight(weight_path)
    runtime.verify_offline_environment(os.environ, cache_root=effective_cache_root)

    inputs: dict[str, tuple[bytes, tuple[str, ...], tuple[tuple[float, float, float], ...]]] = {}
    for endpoint in ENDPOINTS:
        raw = _read_regular_file(root / "input" / f"{endpoint}_initial.xyz")
        elements, coordinates = _validate_frozen_endpoint(endpoint, raw)
        inputs[endpoint] = (raw, elements, coordinates)

    model_stdout = root / "aimnet2" / "model_stdout"
    model_stderr = root / "aimnet2" / "model_stderr"
    model_started = time.monotonic()
    try:
        with _capture_fds(model_stdout, model_stderr):
            torch = importlib.import_module("torch")

            logical_device = "cuda:0"
            if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
                raise PilotError("selected GPU was not exposed as exactly one logical CUDA device")
            properties = torch.cuda.get_device_properties(0)
            if properties.name != "Tesla V100-SXM2-32GB" or (
                properties.major,
                properties.minor,
            ) != (7, 0):
                raise PilotError("torch CUDA device identity drifted")
            base_model = runtime._construct_base_model_after_authorization(
                weight_path=weight_path,
                device=logical_device,
            )
        model_seconds = time.monotonic() - model_started
    except BaseException as exc:
        failure = _failure_payload("aimnet2_model_load", exc)
        _write_json_new(root / "aimnet2" / "summary.json", {"status": "failed", **failure})
        _write_json_new(
            root / "result.json",
            {
                "schema_version": PILOT_SCHEMA,
                "science_pilot_only": True,
                "candidate": CANDIDATE,
                "endpoint_results": _minimal_endpoint_results(),
                "handoff": {"status": "not_run"},
                "deprotonation": _empty_deprotonation(),
                "final_outcome": "INCONCLUSIVE",
                "failure": failure,
                "production_accepted": False,
            },
        )
        raise

    a1_started = model_started
    a1_deadline = a1_started + AIMNET_WALL_LIMIT_SECONDS
    endpoint_results: dict[str, object] = {}
    wrapper_count = 0
    try:
        for endpoint in ENDPOINTS:
            endpoint_root = root / "aimnet2" / endpoint
            _make_directory(endpoint_root)
            raw, elements, coordinates = inputs[endpoint]
            del raw
            with _capture_fds(endpoint_root / "stdout", endpoint_root / "stderr"):
                wrapper_count += 1
                calculator = base_model.calculator_for(
                    charge=CHARGES[endpoint], multiplicity=MULTIPLICITIES[endpoint]
                )
                outcome = gau_loose.optimize_aimnet2_gau_loose(
                    calculator=calculator,
                    coordinates=coordinates,
                    elements=elements,
                    profile=profile,
                    deadline_monotonic=a1_deadline,
                    read_energy_and_forces=lambda atoms, atom_count: runtime.read_energy_and_forces(
                        atoms, atom_count=atom_count
                    ),
                    logfile="-",
                )
            trajectory_receipt = _write_json_new(
                endpoint_root / "trajectory.json", _trajectory_payload(outcome)
            )
            final_raw = runtime.render_xyz(
                elements,
                outcome.coordinates,
                comment=f"science_pilot_only {CANDIDATE} {endpoint} AIMNet2 final",
            )
            final_receipt = _write_new(endpoint_root / "final.xyz", final_raw)
            structure = _validate_pilot_structure(
                runtime=runtime,
                endpoint=endpoint,
                elements_before=elements,
                before=coordinates,
                elements_after=elements,
                after=outcome.coordinates,
            )
            max_abs_coordinate = max(abs(value) for point in outcome.coordinates for value in point)
            minimum_distance = _minimum_pair_distance(outcome.coordinates)
            sanity_passed = (
                max_abs_coordinate <= MAX_ABS_COORDINATE_ANGSTROM
                and minimum_distance >= MIN_PAIR_DISTANCE_ANGSTROM
            )
            accepted = (
                outcome.converged
                and outcome.final_max_force <= profile.ase_fmax_ev_angstrom
                and outcome.trajectory[-1].metrics["aimnet2_gau_loose_converged"] is True
                and structure.all_gates_passed
                and sanity_passed
            )
            endpoint_payload = {
                "status": "success" if accepted else "failed",
                "charge": CHARGES[endpoint],
                "multiplicity": MULTIPLICITIES[endpoint],
                "atom_count": len(elements),
                "atom_order_preserved": True,
                "initial_energy_ev": outcome.initial_energy_ev,
                "final_energy_ev": outcome.final_energy_ev,
                "initial_max_force_ev_per_angstrom": outcome.initial_max_force,
                "final_max_force_ev_per_angstrom": outcome.final_max_force,
                "optimization_steps": outcome.steps,
                "energy_property_reads": outcome.energy_evaluations,
                "force_property_reads": outcome.force_evaluations,
                "calculator_invocations": outcome.calculator_invocations,
                "function_evaluations": {
                    "definition": "AIMNet2ASE.calculate calls",
                    "count": outcome.calculator_invocations,
                },
                "base_model_forward_calls": "unmeasured",
                "wall_seconds": outcome.elapsed_seconds,
                "optimizer_terminal_state": outcome.terminal_state.value,
                "optimizer_failure_reason": outcome.failure_reason,
                "gau_loose_profile": "GAU_LOOSE",
                "gau_loose_five_metrics": outcome.trajectory[-1].metrics,
                "structure": asdict(structure),
                "max_abs_coordinate_angstrom": max_abs_coordinate,
                "minimum_pair_distance_angstrom": minimum_distance,
                "sanity_passed": sanity_passed,
                "trajectory": trajectory_receipt,
                "final_xyz": final_receipt,
            }
            _write_json_new(endpoint_root / "result.json", endpoint_payload)
            endpoint_results[endpoint] = endpoint_payload
            if not accepted:
                message = f"AIMNet2 {endpoint} optimization or structural gate failed"
                if outcome.terminal_state.value in {"failed", "timeout"}:
                    raise InconclusiveFailure(message)
                raise ScientificFailure(message)
    except BaseException as exc:
        failure = _failure_payload(f"aimnet2_{endpoint}", exc)
        outcome_name = "FAIL" if isinstance(exc, ScientificFailure) else "INCONCLUSIVE"
        failure_summary = {
            "schema_version": "nhc-phase9b-science-pilot-aimnet2-v2",
            "status": "failed",
            "candidate": CANDIDATE,
            "failure": failure,
            "endpoints": endpoint_results,
            "model_load_count": int(getattr(base_model, "load_count", 0)),
            "endpoint_wrapper_count": wrapper_count,
            "base_model_forward_calls": "unmeasured",
            "model_load_seconds": model_seconds,
            "total_wall_seconds": time.monotonic() - a1_started,
        }
        _write_json_new(root / "aimnet2" / "summary.json", failure_summary)
        _write_json_new(
            root / "result.json",
            {
                "schema_version": PILOT_SCHEMA,
                "science_pilot_only": True,
                "candidate": CANDIDATE,
                "endpoint_results": _minimal_endpoint_results(
                    aimnet_status={
                        name: cast(dict[str, Any], endpoint_results.get(name, {})).get(
                            "status", "not_run"
                        )
                        for name in ENDPOINTS
                    }
                ),
                "handoff": {"status": "not_run"},
                "deprotonation": _empty_deprotonation(),
                "final_outcome": outcome_name,
                "failure": failure,
                "production_accepted": False,
            },
        )
        raise

    torch = importlib.import_module("torch")

    summary = {
        "schema_version": "nhc-phase9b-science-pilot-aimnet2-v2",
        "science_pilot_only": True,
        "status": "success",
        "candidate": CANDIDATE,
        "source_commit": args.source_commit,
        "pilot_script_sha256": _sha256(_read_regular_file(Path(__file__).resolve(strict=True))),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "aimnet_version": metadata.version("aimnet"),
        "ase_version": metadata.version("ase"),
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "weight": {
            "filename": WEIGHT_FILENAME,
            "bytes": WEIGHT_BYTES,
            "sha256": WEIGHT_SHA256,
            "path": weight_path.as_posix(),
            "path_scope": "private_server_local_explicit_absolute_path",
        },
        "gpu": gpu,
        "logical_device": "cuda:0",
        "compile_model": False,
        "validate_species": True,
        "model_load_count": int(getattr(base_model, "load_count", 0)),
        "model_load_seconds": model_seconds,
        "endpoint_wrapper_count": wrapper_count,
        "base_model_forward_calls": "unmeasured",
        "gau_loose_contract": {
            "profile": "GAU_LOOSE",
            "sha256": _sha256(_read_regular_file(gau_loose_contract)),
            "helper_sha256": _sha256(_read_regular_file(helper_path)),
        },
        "total_wall_seconds": time.monotonic() - a1_started,
        "endpoints": endpoint_results,
    }
    _write_json_new(root / "aimnet2" / "summary.json", summary)
    return 0


def _link_authoritative_input(
    source: Path, destination: Path, *, endpoint: str
) -> dict[str, object]:
    source_before = source.lstat()
    if (
        not stat.S_ISREG(source_before.st_mode)
        or source.is_symlink()
        or source_before.st_nlink != 1
    ):
        raise HandoffFailure("AIMNet2 final XYZ is not an exclusive regular file before handoff")
    _make_directory(destination.parent)
    os.link(source, destination, follow_symlinks=False)
    _fsync_directory(destination.parent)
    source_after = source.lstat()
    destination_stat = destination.lstat()
    if (
        source_after.st_dev,
        source_after.st_ino,
        source_after.st_size,
    ) != (
        destination_stat.st_dev,
        destination_stat.st_ino,
        destination_stat.st_size,
    ):
        raise HandoffFailure("handoff hardlink is not the same file object")
    if source_after.st_nlink != 2 or destination_stat.st_nlink != 2:
        raise HandoffFailure("handoff hardlink count drifted")
    source_raw = _read_regular_file(source)
    input_raw = _read_regular_file(destination)
    if source_raw != input_raw:
        raise HandoffFailure("AIMNet2-to-PySCF handoff bytes differ")
    return {
        "method": "same_inode_hardlink_no_copy_no_reserialization",
        "source_relative": f"aimnet2/{endpoint}/final.xyz",
        "input_relative": f"pyscf/{endpoint}/input.xyz",
        "same_device_inode": True,
        "byte_count": len(source_raw),
        "sha256": _sha256(source_raw),
        "bytes_equal": True,
    }


def _verify_handoff_against_aimnet_summary(
    *, aimnet_summary: object, endpoint: str, handoff: Mapping[str, object]
) -> None:
    if not isinstance(aimnet_summary, dict):
        raise HandoffFailure("AIMNet2 summary is not an object")
    endpoints = aimnet_summary.get("endpoints")
    if not isinstance(endpoints, dict):
        raise HandoffFailure("AIMNet2 endpoint summary is missing")
    endpoint_summary = endpoints.get(endpoint)
    if not isinstance(endpoint_summary, dict) or endpoint_summary.get("status") != "success":
        raise HandoffFailure(f"AIMNet2 {endpoint} summary is not accepted")
    final_xyz = endpoint_summary.get("final_xyz")
    if not isinstance(final_xyz, dict):
        raise HandoffFailure(f"AIMNet2 {endpoint} final XYZ receipt is missing")
    if final_xyz.get("sha256") != handoff.get("sha256") or final_xyz.get("bytes") != handoff.get(
        "byte_count"
    ):
        raise HandoffFailure(
            f"{endpoint} handoff differs from the durable AIMNet2 final XYZ receipt"
        )


class _SciencePilotPySCFBackend:
    """Factory wrapper created after the frozen module has been imported."""

    @staticmethod
    def build(module: Any) -> Any:
        class SciencePilotPySCFBackend(module.PySCFBackend):  # type: ignore[misc]
            def __init__(self) -> None:
                super().__init__(object())
                self._modules: Any = None
                self.pilot_metrics: dict[str, dict[str, object]] = {}
                self._pilot_context: tuple[str, str, str] | None = None
                self._pilot_last_mean_field: object | None = None

            def _load_modules(self) -> object:
                if self._modules is not None:
                    if (
                        module._configure_pyscf_threads(self._modules.lib)
                        != self._modules.pyscf_threads
                    ):
                        raise module.ResourceConfigurationError("cached PySCF thread state drifted")
                    return self._modules
                thread_environment = module._validate_thread_environment(os.environ)
                try:
                    gto = importlib.import_module("pyscf.gto")
                    dft = importlib.import_module("pyscf.dft")
                    geometric_solver = importlib.import_module("pyscf.geomopt.geometric_solver")
                    lib = importlib.import_module("pyscf.lib")
                    dftd3 = importlib.import_module("pyscf.dispersion.dftd3")
                    metadata = importlib.import_module("importlib.metadata")
                    versions = {
                        "pyscf": str(metadata.version("pyscf")),
                        "geometric": str(metadata.version("geometric")),
                        "pyscf-dispersion": str(metadata.version("pyscf-dispersion")),
                    }
                except ImportError as exc:
                    raise module.BackendError("science pilot PySCF stack is unavailable") from exc
                expected = {
                    "pyscf": "2.13.1",
                    "geometric": "1.1.1",
                    "pyscf-dispersion": "1.5.0",
                }
                if versions != expected:
                    raise module.BackendError(f"science pilot PySCF versions drifted: {versions}")
                modules = module._PySCFModules(
                    gto=gto,
                    dft=dft,
                    geometric_solver=geometric_solver,
                    lib=lib,
                    dftd3=dftd3,
                    thread_environment=thread_environment,
                    pyscf_threads=module._configure_pyscf_threads(lib),
                    adapter_version=versions["pyscf-dispersion"],
                )
                self._modules = modules
                return modules

            def _mean_field(self, **kwargs: object) -> tuple[object, object, object]:
                result = super()._mean_field(**kwargs)
                self._pilot_last_mean_field = result[0]
                return cast(tuple[object, object, object], result)

            def optimize(self, **kwargs: object) -> object:
                endpoint = str(kwargs["endpoint"])
                strategy = str(kwargs["strategy"])
                started = time.monotonic()
                self._pilot_context = (endpoint, "optimization", strategy)
                try:
                    return super().optimize(**kwargs)
                finally:
                    record = self.pilot_metrics.setdefault(endpoint, {})
                    record[f"optimization_{strategy}_wall_seconds"] = time.monotonic() - started

            def final_scf(self, **kwargs: object) -> object:
                endpoint = str(kwargs["endpoint"])
                strategy = str(kwargs["strategy"])
                started = time.monotonic()
                self._pilot_context = (endpoint, "final_scf", strategy)
                try:
                    result = super().final_scf(**kwargs)
                    mean_field = self._pilot_last_mean_field
                    raw_cycles = getattr(mean_field, "cycles", None)
                    cycles: int | str
                    if type(raw_cycles) is int and raw_cycles >= 0:
                        cycles = raw_cycles
                    else:
                        cycles = "unavailable"
                    record = self.pilot_metrics.setdefault(endpoint, {})
                    record["final_scf_cycles"] = cycles
                    return result
                finally:
                    record = self.pilot_metrics.setdefault(endpoint, {})
                    record[f"final_scf_{strategy}_wall_seconds"] = time.monotonic() - started

        return SciencePilotPySCFBackend()


def _pyscf_failure_outcome(module: Any, exc: BaseException) -> str:
    scientific = (
        module.SCFNotConvergedError,
        module.GeometryConvergenceError,
    )
    environmental = (
        module.BackendTimeoutError,
        module.ResourceConfigurationError,
        module.ResourceLimitError,
        ImportError,
        OSError,
    )
    if isinstance(exc, scientific):
        return "FAIL"
    if isinstance(exc, environmental):
        return "INCONCLUSIVE"
    return "INCONCLUSIVE"


def _run_pyscf_endpoint_without_retry(
    *, module: Any, backend: Any, endpoint: Any, deadline: float
) -> tuple[Any, Any, dict[str, object]]:
    """Run the frozen standard protocol once; v002 authorizes no SOSCF retry."""

    optimization = module._call_optimize(
        backend=backend,
        endpoint=endpoint,
        strategy="standard",
        deadline=deadline,
    )
    final_scf = module._call_scf(
        backend=backend,
        endpoint=endpoint,
        geometry=optimization.geometry,
        strategy="standard",
        deadline=deadline,
    )
    record: dict[str, object] = {
        "charge": endpoint.charge,
        "multiplicity": endpoint.multiplicity,
        "electron_count": endpoint.electron_count,
        "input_xyz_path": endpoint.xyz_relative_path,
        "input_xyz_sha256": endpoint.xyz_sha256,
        "retry": {
            "authorized": False,
            "attempts": 1,
            "soscf_consumed": False,
        },
        "optimization": {
            "optimizer": "geomeTRIC",
            "geometry_converged": True,
            "scf_converged": True,
            "selected_strategy": "standard",
            "last_energy_hartree": optimization.last_energy_hartree,
            "attempts": [{"strategy": "standard", "converged": True}],
            "runtime": module._runtime_evidence_payload(optimization.runtime),
            "dispersion": module._optimization_dispersion_payload(optimization.dispersion),
        },
        "final_scf": {
            "converged": True,
            "selected_strategy": "standard",
            "energy_hartree": final_scf.energy_hartree,
            "attempts": [{"strategy": "standard", "converged": True}],
            "runtime": module._runtime_evidence_payload(final_scf.runtime),
            "dispersion": module._final_dispersion_payload(final_scf.dispersion),
        },
    }
    return optimization, final_scf, record


def _pyscf_command(args: argparse.Namespace) -> int:
    root = Path(args.pilot_root).resolve(strict=True)
    if root.name != PILOT_RUN_NAME:
        raise PilotError("pilot root logical identity drifted")
    _add_source_root(Path(args.source_root))
    from importlib import metadata

    from nhc_deprot_ranker.quantum import two_endpoint as two_endpoint

    pyscf_tmp = root / "pyscf" / "tmp"
    _make_directory(pyscf_tmp)
    os.environ["TMPDIR"] = str(pyscf_tmp)
    for name, expected in two_endpoint.THREAD_ENVIRONMENT.items():
        os.environ[name] = expected
    set_affinity = getattr(os, "sched_setaffinity", None)
    get_affinity = getattr(os, "sched_getaffinity", None)
    if callable(set_affinity) and callable(get_affinity):
        set_affinity(0, {0, 1, 2, 3})
        if set(get_affinity(0)) != {0, 1, 2, 3}:
            raise PilotError("PySCF CPU affinity did not retain cores 0-3")
    else:
        raise PilotError("the exact Linux CPU affinity API is unavailable")

    aimnet_summary = json.loads(_read_regular_file(root / "aimnet2" / "summary.json"))
    if aimnet_summary.get("status") != "success":
        raise PilotError("PySCF may not start without two accepted AIMNet2 endpoints")

    handoffs: dict[str, object] = {}
    requests: dict[str, object] = {}
    for endpoint in ENDPOINTS:
        source = root / "aimnet2" / endpoint / "final.xyz"
        destination = root / "pyscf" / endpoint / "input.xyz"
        handoffs[endpoint] = _link_authoritative_input(source, destination, endpoint=endpoint)
        _verify_handoff_against_aimnet_summary(
            aimnet_summary=aimnet_summary,
            endpoint=endpoint,
            handoff=cast(dict[str, object], handoffs[endpoint]),
        )
        raw = _read_regular_file(destination)
        if _sha256(raw) != cast(dict[str, object], handoffs[endpoint])["sha256"]:
            raise HandoffFailure("PySCF input reread drifted after handoff")
        geometry = two_endpoint._parse_xyz(raw, label=f"science pilot {endpoint} handoff")
        observed_elements = tuple(atom.element for atom in geometry.atoms)
        initial_elements, _ = _parse_xyz_minimal(
            _read_regular_file(root / "input" / f"{endpoint}_initial.xyz")
        )
        if observed_elements != initial_elements or len(geometry.atoms) != ATOM_COUNTS[endpoint]:
            raise HandoffFailure(f"{endpoint} handoff atom order drifted")
        handoff_record = cast(dict[str, object], handoffs[endpoint])
        handoff_record.update(
            {
                "atom_count": len(observed_elements),
                "atom_order_preserved": True,
                "element_order_sha256": _sha256(" ".join(observed_elements).encode("utf-8")),
                "parser_input_sha256": _sha256(raw),
                "parser_input_byte_count": len(raw),
                "disk_equals_parser": True,
                "charge": CHARGES[endpoint],
                "multiplicity": MULTIPLICITIES[endpoint],
            }
        )
        electrons = two_endpoint._electron_count_for_geometry(geometry, charge=CHARGES[endpoint])
        if electrons != ELECTRON_COUNT:
            raise HandoffFailure(f"{endpoint} handoff electron count drifted")
        requests[endpoint] = two_endpoint.EndpointRequest(
            name=cast(Any, endpoint),
            xyz_relative_path=f"pyscf/{endpoint}/input.xyz",
            xyz_path=destination,
            xyz_sha256=_sha256(raw),
            charge=CHARGES[endpoint],
            multiplicity=MULTIPLICITIES[endpoint],
            electron_count=ELECTRON_COUNT,
            geometry=geometry,
        )

    backend = _SciencePilotPySCFBackend.build(two_endpoint)
    deadline = time.monotonic() + PYSCF_WALL_LIMIT_SECONDS
    endpoint_results: dict[str, object] = {}
    final_energies: dict[str, float] = {}
    try:
        for endpoint in ENDPOINTS:
            endpoint_root = root / "pyscf" / endpoint
            started = time.monotonic()
            with (
                _capture_fds(endpoint_root / "stdout", endpoint_root / "stderr"),
                _working_directory(endpoint_root),
            ):
                optimization, final_scf, record = _run_pyscf_endpoint_without_retry(
                    module=two_endpoint,
                    backend=backend,
                    endpoint=cast(Any, requests[endpoint]),
                    deadline=deadline,
                )
            wall_seconds = time.monotonic() - started
            optimized_xyz = optimization.geometry.to_xyz_bytes(
                comment=f"science_pilot_only {CANDIDATE} {endpoint} PySCF final"
            )
            output_receipt = _write_new(endpoint_root / "output", optimized_xyz)
            metrics = cast(dict[str, object], backend.pilot_metrics.get(endpoint, {}))
            result_payload = {
                "status": "success",
                "charge": CHARGES[endpoint],
                "multiplicity": MULTIPLICITIES[endpoint],
                "electron_count": ELECTRON_COUNT,
                "input_handoff": handoffs[endpoint],
                "protocol": two_endpoint.LOCKED_PROTOCOL,
                "protocol_sha256": two_endpoint.LOCKED_PROTOCOL_SHA256,
                "optimization": record["optimization"],
                "final_scf": record["final_scf"],
                "final_scf_cycles": metrics.get("final_scf_cycles", "unavailable"),
                "instrumentation": metrics,
                "wall_seconds": wall_seconds,
                "output": output_receipt,
            }
            _write_json_new(endpoint_root / "result.json", result_payload)
            endpoint_results[endpoint] = result_payload
            final_energies[endpoint] = final_scf.energy_hartree
    except BaseException as exc:
        traceback.print_exc()
        failure = _failure_payload(f"pyscf_{endpoint}", exc)
        failed_root = root / "pyscf" / endpoint
        if not (failed_root / "result.json").exists():
            _write_json_new(
                failed_root / "result.json",
                {
                    "status": "failed",
                    "charge": CHARGES[endpoint],
                    "multiplicity": MULTIPLICITIES[endpoint],
                    "input_handoff": handoffs.get(endpoint),
                    "failure": failure,
                    "instrumentation": backend.pilot_metrics.get(endpoint, {}),
                },
            )
        endpoint_results[endpoint] = {
            "status": "failed",
            "failure": failure,
            "input_handoff": handoffs.get(endpoint),
        }
        outcome = _pyscf_failure_outcome(two_endpoint, exc)
        failure_summary = {
            "schema_version": "nhc-phase9b-science-pilot-pyscf-v2",
            "status": "failed",
            "candidate": CANDIDATE,
            "failure": failure,
            "endpoints": endpoint_results,
        }
        _write_json_new(root / "pyscf" / "summary.json", failure_summary)
        _write_json_new(
            root / "result.json",
            {
                "schema_version": PILOT_SCHEMA,
                "science_pilot_only": True,
                "candidate": CANDIDATE,
                "endpoint_results": {
                    name: {
                        "aimnet2_status": cast(dict[str, Any], aimnet_summary["endpoints"])[name][
                            "status"
                        ],
                        "pyscf_status": cast(dict[str, Any], endpoint_results.get(name, {})).get(
                            "status", "not_run"
                        ),
                        "energy_hartree": final_energies.get(name),
                    }
                    for name in ENDPOINTS
                },
                "handoff": {"status": "PASS", "endpoints": handoffs},
                "deprotonation": _empty_deprotonation(),
                "final_outcome": outcome,
                "failure": failure,
                "production_accepted": False,
                "production_label_written": False,
            },
        )
        raise

    electronic_difference = (
        final_energies["neutral"] - final_energies["cation"]
    ) * HARTREE_TO_KCAL_MOL
    value = electronic_difference + GAS_PROTON_KCAL_MOL
    if not math.isfinite(electronic_difference) or not math.isfinite(value):
        raise PilotError("deprotonation formula produced a non-finite value")
    summary: dict[str, object] = {
        "schema_version": "nhc-phase9b-science-pilot-pyscf-v2",
        "science_pilot_only": True,
        "status": "success",
        "candidate": CANDIDATE,
        "source_commit": args.source_commit,
        "pilot_script_sha256": _sha256(_read_regular_file(Path(__file__).resolve(strict=True))),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "versions": {
            "pyscf": metadata.version("pyscf"),
            "geometric": metadata.version("geometric"),
            "pyscf-dispersion": metadata.version("pyscf-dispersion"),
        },
        "cpu_affinity": [0, 1, 2, 3],
        "max_memory_mb": 12000,
        "protocol": two_endpoint.LOCKED_PROTOCOL,
        "protocol_sha256": two_endpoint.LOCKED_PROTOCOL_SHA256,
        "endpoints": endpoint_results,
    }
    _write_json_new(root / "pyscf" / "summary.json", summary)
    _write_json_new(
        root / "result.json",
        {
            "schema_version": PILOT_SCHEMA,
            "science_pilot_only": True,
            "candidate": CANDIDATE,
            "endpoint_results": {
                name: {
                    "charge": CHARGES[name],
                    "multiplicity": MULTIPLICITIES[name],
                    "aimnet2_status": cast(dict[str, Any], aimnet_summary["endpoints"])[name][
                        "status"
                    ],
                    "pyscf_status": "success",
                    "energy_hartree": final_energies[name],
                }
                for name in ENDPOINTS
            },
            "handoff": {
                "status": "PASS",
                "endpoints": handoffs,
            },
            "deprotonation": {
                "formula": LABEL_FORMULA,
                "electronic_difference_kcal_per_mol": electronic_difference,
                "unit": "kcal/mol",
                "value": value,
                "lower_is_better": True,
                "definition": "gas_phase_electronic_energy_only",
            },
            "final_outcome": "PASS",
            "production_accepted": False,
            "production_label_written": False,
        },
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    aimnet = subparsers.add_parser("aimnet2")
    aimnet.add_argument("--pilot-root", required=True)
    aimnet.add_argument("--source-root", required=True)
    aimnet.add_argument("--source-commit", required=True)
    aimnet.add_argument("--weight", required=True)
    aimnet.add_argument("--physical-gpu-index", required=True, type=int)
    aimnet.add_argument("--physical-gpu-uuid", required=True)
    aimnet.add_argument("--gau-loose-helper", required=True)
    aimnet.add_argument("--gau-loose-contract", required=True)
    pyscf = subparsers.add_parser("pyscf")
    pyscf.add_argument("--pilot-root", required=True)
    pyscf.add_argument("--source-root", required=True)
    pyscf.add_argument("--source-commit", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "aimnet2":
            return _aimnet2_command(args)
        if args.command == "pyscf":
            return _pyscf_command(args)
        raise PilotError("unknown science pilot command")
    except BaseException as exc:
        root = Path(args.pilot_root)
        result_path = root / "result.json"
        if root.is_dir() and not result_path.exists():
            try:
                _write_json_new(
                    result_path,
                    {
                        "schema_version": PILOT_SCHEMA,
                        "science_pilot_only": True,
                        "candidate": CANDIDATE,
                        "endpoint_results": _minimal_endpoint_results(),
                        "handoff": {
                            "status": "FAIL" if isinstance(exc, HandoffFailure) else "not_run"
                        },
                        "deprotonation": _empty_deprotonation(),
                        "final_outcome": (
                            "FAIL" if isinstance(exc, ScientificFailure) else "INCONCLUSIVE"
                        ),
                        "failure": _failure_payload(args.command, exc),
                        "production_accepted": False,
                        "production_label_written": False,
                    },
                )
            except BaseException:
                traceback.print_exc()
        raise


if __name__ == "__main__":
    raise SystemExit(main())
