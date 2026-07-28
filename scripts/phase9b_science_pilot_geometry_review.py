#!/usr/bin/env python3
"""Read-only scientific review of the retained v002 AIMNet2 geometries.

The script never imports a chemistry package and never changes an existing
v002 byte.  It uses frozen atom indices and deterministic NumPy linear algebra;
there is no graph isomorphism, atom matching, or coordinate optimization.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import stat
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

import numpy as np
from numpy.typing import NDArray

CANDIDATE: Final = "LBNPGYISTSLAHY-UHFFFAOYSA-N"
V002_ROOT_NAME: Final = "science_pilot_lbn_v002"
REVIEW_SCHEMA: Final = "nhc-phase9b-science-pilot-geometry-review-v1"
CLASSIFICATIONS: Final = (
    "SAME_BASIN_LIKELY",
    "DIFFERENT_BASIN_OR_INVALID",
    "INCONCLUSIVE",
)

C2: Final = 14
N1: Final = 8
N3: Final = 15
ACIDIC_H: Final = 23
EXPECTED_CHARGE: Final = {"cation": 1, "neutral": 0}
EXPECTED_MULTIPLICITY: Final = {"cation": 1, "neutral": 1}
EXPECTED_ATOMS: Final = {"cation": 26, "neutral": 25}
EXPECTED_FILES: Final = {
    "input/cation_initial.xyz": (
        1075,
        "543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286",
    ),
    "input/neutral_initial.xyz": (
        1036,
        "af9c30640801eec3ab27538a33204186849303dd57592ca5c93320ec1390f4b8",
    ),
    "aimnet2/cation/final.xyz": (
        1181,
        "ea796a5c81504184382b965d57c588c74968a09de8942148d3d9cbadf70a7774",
    ),
    "aimnet2/neutral/final.xyz": (
        1133,
        "c40ca77bce9d8c8deefc2357bf2633fb4c0981ce9d4bd23aceb342d40646bc93",
    ),
    "result.json": (
        1003,
        "b1362a3b1df7ef7ba276bac0c91fd8002fd27123eca37d84a82b937edacd7071",
    ),
}

COVALENT_RADII: Final = {"H": 0.31, "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57}
BOND_TOLERANCE: Final = 1.30
PRODUCTION_MIN_PAIR_ANGSTROM: Final = 0.20
OBVIOUS_COLLISION_ANGSTROM: Final = 0.70
MAX_ALIGNED_RMSD_ANGSTROM: Final = 1.0
MAX_ALIGNED_DISPLACEMENT_ANGSTROM: Final = 2.5
MAX_C2_N_CHANGE_ANGSTROM: Final = 0.15
MIN_C2_N_ANGSTROM: Final = 1.20
MAX_C2_N_ANGSTROM: Final = 1.60
MAX_RING_RMS_OOP_ANGSTROM: Final = 0.10
MAX_RING_OOP_ANGSTROM: Final = 0.20
MAX_C2_HEIGHT_ANGSTROM: Final = 0.20
MAX_RING_DIHEDRAL_DEGREES: Final = 30.0
MAX_RING_NORMAL_CHANGE_DEGREES: Final = 30.0
SUBSTITUENT_FLIP_DEGREES: Final = 120.0
PRODUCTION_RING_ANGLE_GATE_DEGREES: Final = 10.0
MAX_FILE_BYTES: Final = 16 << 20
FILE_MODE: Final = 0o600
DIRECTORY_MODE: Final = 0o700


class ReviewError(RuntimeError):
    """The geometry review could not establish a reliable result."""


class InvalidGeometryError(ReviewError):
    """The retained geometry violates a frozen identity or topology condition."""


@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int
    mode: int
    link_count: int
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class FileEvidence:
    relative_path: str
    byte_count: int
    sha256: str
    regular_file: bool
    symlink: bool
    before: FileIdentity
    after: FileIdentity


@dataclass(frozen=True, slots=True)
class Geometry:
    elements: tuple[str, ...]
    coordinates: NDArray[np.float64]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _number(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise ReviewError("numeric geometry payload field is invalid")


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _identity(observed: os.stat_result) -> FileIdentity:
    return FileIdentity(
        device=observed.st_dev,
        inode=observed.st_ino,
        mode=stat.S_IMODE(observed.st_mode),
        link_count=observed.st_nlink,
        size=observed.st_size,
        mtime_ns=observed.st_mtime_ns,
    )


def read_regular_file(root: Path, relative_path: str) -> tuple[bytes, FileEvidence]:
    path = root / relative_path
    if path.is_symlink():
        raise InvalidGeometryError(f"symlink is forbidden: {relative_path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before_stat = os.fstat(descriptor)
        if not stat.S_ISREG(before_stat.st_mode) or before_stat.st_nlink != 1:
            raise InvalidGeometryError(f"unsafe evidence file: {relative_path}")
        if before_stat.st_size < 0 or before_stat.st_size > MAX_FILE_BYTES:
            raise InvalidGeometryError(f"evidence size is invalid: {relative_path}")
        chunks: list[bytes] = []
        remaining = before_stat.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1 << 20))
            if not chunk:
                raise ReviewError(f"short evidence read: {relative_path}")
            chunks.append(chunk)
            remaining -= len(chunk)
        after_stat = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    before = _identity(before_stat)
    after = _identity(after_stat)
    if before != after:
        raise ReviewError(f"file identity drifted during read: {relative_path}")
    raw = b"".join(chunks)
    return raw, FileEvidence(
        relative_path=relative_path,
        byte_count=len(raw),
        sha256=_sha256(raw),
        regular_file=True,
        symlink=False,
        before=before,
        after=after,
    )


def _make_new_directory(path: Path) -> None:
    path.mkdir(mode=DIRECTORY_MODE, parents=False, exist_ok=False)
    observed = path.lstat()
    if not stat.S_ISDIR(observed.st_mode) or path.is_symlink():
        raise ReviewError("review output directory is unsafe")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_new(path: Path, raw: bytes) -> dict[str, object]:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        FILE_MODE,
    )
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            raise ReviewError(f"new review evidence is unsafe: {path.name}")
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)
    reread = path.read_bytes()
    if reread != raw:
        raise ReviewError(f"review evidence reread mismatch: {path.name}")
    return {"relative_path": f"review/{path.name}", "bytes": len(raw), "sha256": _sha256(raw)}


def parse_xyz(raw: bytes) -> Geometry:
    try:
        lines = raw.decode("utf-8").splitlines()
        atom_count = int(lines[0].strip())
    except (UnicodeDecodeError, ValueError, IndexError) as exc:
        raise InvalidGeometryError("XYZ header is invalid") from exc
    if len(lines) != atom_count + 2:
        raise InvalidGeometryError("XYZ line count is invalid")
    elements: list[str] = []
    coordinates: list[tuple[float, float, float]] = []
    for line in lines[2:]:
        fields = line.split()
        if len(fields) != 4 or fields[0] not in COVALENT_RADII:
            raise InvalidGeometryError("XYZ atom row is invalid")
        try:
            point = tuple(float(value) for value in fields[1:])
        except ValueError as exc:
            raise InvalidGeometryError("XYZ coordinate is invalid") from exc
        if len(point) != 3 or not all(math.isfinite(value) for value in point):
            raise InvalidGeometryError("XYZ coordinate is non-finite")
        elements.append(fields[0])
        coordinates.append(point)
    return Geometry(tuple(elements), np.asarray(coordinates, dtype=np.float64))


def verify_expected_file_identity(
    evidence: FileEvidence, *, expected_bytes: int, expected_sha256: str
) -> None:
    if evidence.byte_count != expected_bytes or evidence.sha256 != expected_sha256:
        raise InvalidGeometryError(f"frozen evidence identity drifted: {evidence.relative_path}")


def cation_minus_proton_elements(
    elements: Sequence[str], *, proton_index: int = ACIDIC_H
) -> tuple[str, ...]:
    if proton_index >= len(elements) or elements[proton_index] != "H":
        raise InvalidGeometryError("cation acidic proton identity drifted")
    return tuple(element for index, element in enumerate(elements) if index != proton_index)


def distance(points: NDArray[np.float64], left: int, right: int) -> float:
    return float(np.linalg.norm(points[left] - points[right]))


def angle_degrees(points: NDArray[np.float64], left: int, centre: int, right: int) -> float:
    first = points[left] - points[centre]
    second = points[right] - points[centre]
    denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
    if denominator == 0.0:
        raise InvalidGeometryError("degenerate angle")
    cosine = float(np.dot(first, second) / denominator)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def dihedral_degrees(points: NDArray[np.float64], indices: Sequence[int]) -> float:
    left, centre_left, centre_right, right = indices
    b0 = points[centre_left] - points[left]
    b1 = points[centre_right] - points[centre_left]
    b2 = points[right] - points[centre_right]
    norm = float(np.linalg.norm(b1))
    if norm == 0.0:
        raise InvalidGeometryError("degenerate dihedral")
    unit = b1 / norm
    v = b0 - np.dot(b0, unit) * unit
    w = b2 - np.dot(b2, unit) * unit
    if float(np.linalg.norm(v)) == 0.0 or float(np.linalg.norm(w)) == 0.0:
        raise InvalidGeometryError("collinear dihedral")
    return math.degrees(math.atan2(float(np.dot(np.cross(unit, v), w)), float(np.dot(v, w))))


def circular_delta_degrees(final: float, initial: float) -> float:
    return abs((final - initial + 180.0) % 360.0 - 180.0)


def infer_connectivity(
    elements: Sequence[str], points: NDArray[np.float64]
) -> frozenset[tuple[int, int]]:
    bonds: set[tuple[int, int]] = set()
    for left in range(len(elements)):
        for right in range(left + 1, len(elements)):
            if (
                distance(points, left, right)
                <= (COVALENT_RADII[elements[left]] + COVALENT_RADII[elements[right]])
                * BOND_TOLERANCE
            ):
                bonds.add((left, right))
    return frozenset(bonds)


def neighbors(bonds: Iterable[tuple[int, int]], atom: int) -> tuple[int, ...]:
    return tuple(
        sorted(right if left == atom else left for left, right in bonds if atom in (left, right))
    )


def connected_components(atom_count: int, bonds: frozenset[tuple[int, int]]) -> list[list[int]]:
    remaining = set(range(atom_count))
    components: list[list[int]] = []
    while remaining:
        pending = [min(remaining)]
        component: set[int] = set()
        while pending:
            atom = pending.pop()
            if atom in component:
                continue
            component.add(atom)
            pending.extend(index for index in neighbors(bonds, atom) if index not in component)
        remaining -= component
        components.append(sorted(component))
    return components


def find_five_membered_ring(bonds: frozenset[tuple[int, int]]) -> tuple[int, ...]:
    if tuple(sorted((N1, C2))) not in bonds or tuple(sorted((C2, N3))) not in bonds:
        raise InvalidGeometryError("N1-C2-N3 ring edges are absent")
    paths: set[tuple[int, ...]] = set()

    def walk(current: int, path: tuple[int, ...]) -> None:
        if len(path) == 4:
            if current == N1:
                paths.add((N1, C2, N3, path[1], path[2]))
            return
        for next_atom in neighbors(bonds, current):
            if next_atom in path or next_atom == C2 or (next_atom == N1 and len(path) != 3):
                continue
            walk(next_atom, (*path, next_atom))

    walk(N3, (N3,))
    if len(paths) != 1:
        raise InvalidGeometryError(f"expected one mapped five-membered ring, observed {len(paths)}")
    return next(iter(paths))


def kabsch_align(
    reference: NDArray[np.float64], mobile: NDArray[np.float64]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    if reference.shape != mobile.shape or reference.ndim != 2 or reference.shape[1] != 3:
        raise InvalidGeometryError("Kabsch coordinate shapes differ")
    reference_centroid = reference.mean(axis=0)
    mobile_centroid = mobile.mean(axis=0)
    covariance = (mobile - mobile_centroid).T @ (reference - reference_centroid)
    left, _, right_t = np.linalg.svd(covariance)
    if np.linalg.det(left @ right_t) < 0.0:
        left[:, -1] *= -1.0
    rotation = left @ right_t
    return (mobile - mobile_centroid) @ rotation + reference_centroid, rotation


def best_fit_plane(points: NDArray[np.float64]) -> dict[str, object]:
    centroid = points.mean(axis=0)
    _, _, right_t = np.linalg.svd(points - centroid)
    normal = right_t[-1]
    for value in normal:
        if abs(float(value)) > 1.0e-12:
            if value < 0.0:
                normal = -normal
            break
    signed = (points - centroid) @ normal
    return {
        "centroid": centroid.tolist(),
        "normal": normal.tolist(),
        "signed_distances_angstrom": signed.tolist(),
        "rms_out_of_plane_angstrom": float(np.sqrt(np.mean(signed * signed))),
        "max_out_of_plane_angstrom": float(np.max(np.abs(signed))),
    }


def point_height_above_plane(
    point: NDArray[np.float64], plane_points: NDArray[np.float64]
) -> float:
    plane = best_fit_plane(plane_points)
    centroid = np.asarray(plane["centroid"], dtype=np.float64)
    normal = np.asarray(plane["normal"], dtype=np.float64)
    return float(np.dot(point - centroid, normal))


def ring_payload(
    elements: Sequence[str], points: NDArray[np.float64], ring: Sequence[int]
) -> dict[str, object]:
    bonds_payload: list[dict[str, object]] = []
    angles_payload: list[dict[str, object]] = []
    dihedrals_payload: list[dict[str, object]] = []
    for offset, atom in enumerate(ring):
        next_atom = ring[(offset + 1) % len(ring)]
        previous = ring[(offset - 1) % len(ring)]
        bonds_payload.append(
            {
                "indices": [atom, next_atom],
                "elements": [elements[atom], elements[next_atom]],
                "length_angstrom": distance(points, atom, next_atom),
            }
        )
        angles_payload.append(
            {
                "indices": [previous, atom, next_atom],
                "centre_index": atom,
                "degrees": angle_degrees(points, previous, atom, next_atom),
            }
        )
        quadruple = [
            ring[(offset - 1) % len(ring)],
            atom,
            next_atom,
            ring[(offset + 2) % len(ring)],
        ]
        dihedrals_payload.append(
            {"indices": quadruple, "degrees": dihedral_degrees(points, quadruple)}
        )
    plane = best_fit_plane(points[np.asarray(ring, dtype=int)])
    other_ring_atoms = [index for index in ring if index != C2]
    c2_height = point_height_above_plane(points[C2], points[np.asarray(other_ring_atoms)])
    return {
        "atom_indices": list(ring),
        "elements": [elements[index] for index in ring],
        "bonds": bonds_payload,
        "angles": angles_payload,
        "angle_sum_degrees": sum(_number(item["degrees"]) for item in angles_payload),
        "angle_sum_deviation_from_planar_540_degrees": abs(
            sum(_number(item["degrees"]) for item in angles_payload) - 540.0
        ),
        "plane": plane,
        "dihedrals": dihedrals_payload,
        "max_abs_dihedral_degrees": max(
            abs(_number(item["degrees"])) for item in dihedrals_payload
        ),
        "c2_height_above_other_ring_plane_angstrom": c2_height,
        "c2_two_coordinate_pyramidalization_directly_defined": False,
    }


def _all_heavy_dihedrals(
    elements: Sequence[str], bonds: frozenset[tuple[int, int]]
) -> tuple[tuple[int, int, int, int], ...]:
    paths: set[tuple[int, int, int, int]] = set()
    for centre_left, centre_right in bonds:
        for left in neighbors(bonds, centre_left):
            if left == centre_right or elements[left] == "H":
                continue
            for right in neighbors(bonds, centre_right):
                if right in (centre_left, left) or elements[right] == "H":
                    continue
                path = (left, centre_left, centre_right, right)
                reverse = (right, centre_right, centre_left, left)
                paths.add(min(path, reverse))
    return tuple(sorted(paths))


def dihedral_changes(
    elements: Sequence[str],
    initial: NDArray[np.float64],
    final: NDArray[np.float64],
    bonds: frozenset[tuple[int, int]],
    ring: Sequence[int],
) -> list[dict[str, object]]:
    ring_set = set(ring)
    payload: list[dict[str, object]] = []
    for indices in _all_heavy_dihedrals(elements, bonds):
        initial_value = dihedral_degrees(initial, indices)
        final_value = dihedral_degrees(final, indices)
        central = indices[1:3]
        ring_sidechain = (central[0] in ring_set) != (central[1] in ring_set)
        payload.append(
            {
                "indices": list(indices),
                "elements": [elements[index] for index in indices],
                "central_bond": list(central),
                "ring_sidechain_connection": ring_sidechain,
                "initial_degrees": initial_value,
                "final_degrees": final_value,
                "absolute_delta_degrees": circular_delta_degrees(final_value, initial_value),
            }
        )
    return sorted(payload, key=lambda item: _number(item["absolute_delta_degrees"]), reverse=True)


def _minimum_pair(points: NDArray[np.float64]) -> tuple[float, tuple[int, int]]:
    minimum = math.inf
    pair = (-1, -1)
    for left in range(len(points)):
        for right in range(left + 1, len(points)):
            observed = distance(points, left, right)
            if observed < minimum:
                minimum = observed
                pair = (left, right)
    return minimum, pair


def _minimum_nonbonded_pair(
    points: NDArray[np.float64], bonds: frozenset[tuple[int, int]]
) -> tuple[float, tuple[int, int]]:
    minimum = math.inf
    pair = (-1, -1)
    for left in range(len(points)):
        for right in range(left + 1, len(points)):
            if (left, right) in bonds:
                continue
            observed = distance(points, left, right)
            if observed < minimum:
                minimum = observed
                pair = (left, right)
    return minimum, pair


def _plane_normal_angle(left: dict[str, object], right: dict[str, object]) -> float:
    left_normal = np.asarray(left["normal"], dtype=np.float64)
    right_normal = np.asarray(right["normal"], dtype=np.float64)
    cosine = abs(float(np.dot(left_normal, right_normal)))
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _ring_comparison(initial: dict[str, object], final: dict[str, object]) -> dict[str, object]:
    initial_bonds = initial["bonds"]
    final_bonds = final["bonds"]
    initial_angles = initial["angles"]
    final_angles = final["angles"]
    assert isinstance(initial_bonds, list) and isinstance(final_bonds, list)
    assert isinstance(initial_angles, list) and isinstance(final_angles, list)
    bonds = []
    for before, after in zip(initial_bonds, final_bonds, strict=True):
        assert isinstance(before, dict) and isinstance(after, dict)
        bonds.append(
            {
                "indices": before["indices"],
                "initial_angstrom": before["length_angstrom"],
                "final_angstrom": after["length_angstrom"],
                "absolute_delta_angstrom": abs(
                    _number(after["length_angstrom"]) - _number(before["length_angstrom"])
                ),
                "relative_delta": abs(
                    _number(after["length_angstrom"]) - _number(before["length_angstrom"])
                )
                / _number(before["length_angstrom"]),
            }
        )
    angles = []
    for before, after in zip(initial_angles, final_angles, strict=True):
        assert isinstance(before, dict) and isinstance(after, dict)
        angles.append(
            {
                "indices": before["indices"],
                "centre_index": before["centre_index"],
                "initial_degrees": before["degrees"],
                "final_degrees": after["degrees"],
                "signed_delta_degrees": _number(after["degrees"]) - _number(before["degrees"]),
                "absolute_delta_degrees": abs(
                    _number(after["degrees"]) - _number(before["degrees"])
                ),
            }
        )
    initial_plane = initial["plane"]
    final_plane = final["plane"]
    assert isinstance(initial_plane, dict) and isinstance(final_plane, dict)
    return {
        "bonds": bonds,
        "angles": angles,
        "initial_angle_sum_degrees": initial["angle_sum_degrees"],
        "final_angle_sum_degrees": final["angle_sum_degrees"],
        "plane_normal_angle_degrees": _plane_normal_angle(initial_plane, final_plane),
        "c2_height_change_angstrom": abs(
            _number(final["c2_height_above_other_ring_plane_angstrom"])
            - _number(initial["c2_height_above_other_ring_plane_angstrom"])
        ),
    }


def _structure_local_metrics(
    elements: Sequence[str], points: NDArray[np.float64], ring: Sequence[int]
) -> dict[str, object]:
    ring_data = ring_payload(elements, points, ring)
    plane = ring_data["plane"]
    if not isinstance(plane, dict):
        raise ReviewError("ring plane payload is invalid")
    return {
        "n1_c2_n3_angle_degrees": angle_degrees(points, N1, C2, N3),
        "c2_n1_angstrom": distance(points, C2, N1),
        "c2_n3_angstrom": distance(points, C2, N3),
        "ring_plane_rms_out_of_plane_angstrom": plane["rms_out_of_plane_angstrom"],
        "ring_plane_max_out_of_plane_angstrom": plane["max_out_of_plane_angstrom"],
        "c2_height_above_other_ring_plane_angstrom": ring_data[
            "c2_height_above_other_ring_plane_angstrom"
        ],
    }


def review_geometry(root: Path) -> tuple[dict[str, object], dict[str, bytes]]:
    if root.name != V002_ROOT_NAME:
        raise ReviewError("v002 root logical name drifted")
    review_root = root / "review"
    if review_root.exists() or review_root.is_symlink():
        raise ReviewError("review output already exists")

    raw_files: dict[str, bytes] = {}
    file_evidence: dict[str, FileEvidence] = {}
    for relative_path, (expected_bytes, expected_sha) in EXPECTED_FILES.items():
        raw, evidence = read_regular_file(root, relative_path)
        verify_expected_file_identity(
            evidence, expected_bytes=expected_bytes, expected_sha256=expected_sha
        )
        raw_files[relative_path] = raw
        file_evidence[relative_path] = evidence

    cation_initial = parse_xyz(raw_files["input/cation_initial.xyz"])
    neutral_initial = parse_xyz(raw_files["input/neutral_initial.xyz"])
    cation_final = parse_xyz(raw_files["aimnet2/cation/final.xyz"])
    neutral_final = parse_xyz(raw_files["aimnet2/neutral/final.xyz"])

    for endpoint, initial, final in (
        ("cation", cation_initial, cation_final),
        ("neutral", neutral_initial, neutral_final),
    ):
        if len(initial.elements) != EXPECTED_ATOMS[endpoint]:
            raise InvalidGeometryError(f"{endpoint} atom count drifted")
        if initial.elements != final.elements:
            raise InvalidGeometryError(f"{endpoint} element order drifted")
        if (
            initial.elements[C2] != "C"
            or initial.elements[N1] != "N"
            or initial.elements[N3] != "N"
        ):
            raise InvalidGeometryError("frozen atom map drifted")

    if cation_initial.elements[ACIDIC_H] != "H":
        raise InvalidGeometryError("cation H23 identity drifted")
    common_cation_elements = cation_minus_proton_elements(cation_initial.elements)
    if common_cation_elements != neutral_initial.elements:
        raise InvalidGeometryError("cation-minus-H23 and neutral element sequences differ")

    raw_result = json.loads(raw_files["result.json"])
    endpoint_results = raw_result.get("endpoint_results")
    if not isinstance(endpoint_results, dict):
        raise InvalidGeometryError("v002 endpoint result object is missing")
    for endpoint in ("cation", "neutral"):
        endpoint_result = endpoint_results.get(endpoint)
        if not isinstance(endpoint_result, dict):
            raise InvalidGeometryError(f"v002 {endpoint} result is missing")
        if (
            endpoint_result.get("charge") != EXPECTED_CHARGE[endpoint]
            or endpoint_result.get("multiplicity") != EXPECTED_MULTIPLICITY[endpoint]
        ):
            raise InvalidGeometryError(f"v002 {endpoint} charge/multiplicity drifted")

    initial_bonds = infer_connectivity(neutral_initial.elements, neutral_initial.coordinates)
    final_bonds = infer_connectivity(neutral_final.elements, neutral_final.coordinates)
    added_bonds = sorted(final_bonds - initial_bonds)
    removed_bonds = sorted(initial_bonds - final_bonds)
    initial_components = connected_components(len(neutral_initial.elements), initial_bonds)
    final_components = connected_components(len(neutral_final.elements), final_bonds)
    initial_ring = find_five_membered_ring(initial_bonds)
    final_ring = find_five_membered_ring(final_bonds)
    if initial_ring != final_ring:
        raise InvalidGeometryError("mapped ring identity changed")

    aligned_final, _ = kabsch_align(neutral_initial.coordinates, neutral_final.coordinates)
    displacements = np.linalg.norm(aligned_final - neutral_initial.coordinates, axis=1)
    aligned_rmsd = float(np.sqrt(np.mean(displacements * displacements)))
    max_displacement_index = int(np.argmax(displacements))
    ring_indices = np.asarray(initial_ring, dtype=int)
    nonring_indices = np.asarray(
        [index for index in range(len(neutral_initial.elements)) if index not in set(initial_ring)],
        dtype=int,
    )
    ring_rmsd = float(np.sqrt(np.mean(displacements[ring_indices] ** 2)))
    nonring_rmsd = float(np.sqrt(np.mean(displacements[nonring_indices] ** 2)))

    initial_ring_payload = ring_payload(
        neutral_initial.elements, neutral_initial.coordinates, initial_ring
    )
    final_ring_payload = ring_payload(neutral_final.elements, aligned_final, final_ring)
    ring_comparison = _ring_comparison(initial_ring_payload, final_ring_payload)

    dihedrals = dihedral_changes(
        neutral_initial.elements,
        neutral_initial.coordinates,
        aligned_final,
        initial_bonds,
        initial_ring,
    )
    ring_sidechain_dihedrals = [item for item in dihedrals if item["ring_sidechain_connection"]]
    maximum_ring_sidechain_delta = max(
        (_number(item["absolute_delta_degrees"]) for item in ring_sidechain_dihedrals), default=0.0
    )

    initial_minimum, initial_min_pair = _minimum_pair(neutral_initial.coordinates)
    final_minimum, final_min_pair = _minimum_pair(neutral_final.coordinates)
    initial_nonbonded, initial_nonbonded_pair = _minimum_nonbonded_pair(
        neutral_initial.coordinates, initial_bonds
    )
    final_nonbonded, final_nonbonded_pair = _minimum_nonbonded_pair(
        neutral_final.coordinates, final_bonds
    )

    final_ring_plane = final_ring_payload["plane"]
    assert isinstance(final_ring_plane, dict)
    c2_n1_initial = distance(neutral_initial.coordinates, C2, N1)
    c2_n1_final = distance(neutral_final.coordinates, C2, N1)
    c2_n3_initial = distance(neutral_initial.coordinates, C2, N3)
    c2_n3_final = distance(neutral_final.coordinates, C2, N3)
    ring_angle_initial = angle_degrees(neutral_initial.coordinates, N1, C2, N3)
    ring_angle_final = angle_degrees(neutral_final.coordinates, N1, C2, N3)
    ring_angle_delta = abs(ring_angle_final - ring_angle_initial)
    normal_angle = _number(ring_comparison["plane_normal_angle_degrees"])
    final_c2_height = abs(_number(final_ring_payload["c2_height_above_other_ring_plane_angstrom"]))
    final_ring_rms_oop = _number(final_ring_plane["rms_out_of_plane_angstrom"])
    final_ring_max_oop = _number(final_ring_plane["max_out_of_plane_angstrom"])
    final_max_ring_dihedral = _number(final_ring_payload["max_abs_dihedral_degrees"])

    fluorine_distances = [
        {
            "fluorine_index": index,
            "reaction_centre_index": centre,
            "initial_angstrom": distance(neutral_initial.coordinates, index, centre),
            "final_angstrom": distance(neutral_final.coordinates, index, centre),
        }
        for index, element in enumerate(neutral_initial.elements)
        if element == "F"
        for centre in (C2, N1, N3)
    ]
    closest_fluorine = min(fluorine_distances, key=lambda item: _number(item["final_angstrom"]))

    cation_initial_bonds = infer_connectivity(cation_initial.elements, cation_initial.coordinates)
    cation_final_bonds = infer_connectivity(cation_final.elements, cation_final.coordinates)
    cation_initial_ring = find_five_membered_ring(cation_initial_bonds)
    cation_final_ring = find_five_membered_ring(cation_final_bonds)
    if cation_initial_ring != initial_ring or cation_final_ring != final_ring:
        raise InvalidGeometryError("cation/neutral mapped ring identity differs")

    common_indices = [index for index in range(len(cation_initial.elements)) if index != ACIDIC_H]
    cation_initial_common = cation_initial.coordinates[np.asarray(common_indices)]
    cation_final_common = cation_final.coordinates[np.asarray(common_indices)]
    aligned_neutral_initial, _ = kabsch_align(cation_initial_common, neutral_initial.coordinates)
    aligned_neutral_final, _ = kabsch_align(cation_final_common, neutral_final.coordinates)
    common_initial_displacements = np.linalg.norm(
        aligned_neutral_initial - cation_initial_common, axis=1
    )
    common_final_displacements = np.linalg.norm(aligned_neutral_final - cation_final_common, axis=1)

    four_structure_comparison = {
        "cation_initial_minus_h23": _structure_local_metrics(
            cation_initial.elements, cation_initial.coordinates, cation_initial_ring
        ),
        "cation_final_minus_h23": _structure_local_metrics(
            cation_final.elements, cation_final.coordinates, cation_final_ring
        ),
        "neutral_initial": _structure_local_metrics(
            neutral_initial.elements, neutral_initial.coordinates, initial_ring
        ),
        "neutral_final": _structure_local_metrics(
            neutral_final.elements, neutral_final.coordinates, final_ring
        ),
        "common_atom_mapping": {
            "cation_h_removed": ACIDIC_H,
            "element_sequence_equal": True,
            "initial_aligned_rmsd_angstrom": float(
                np.sqrt(np.mean(common_initial_displacements**2))
            ),
            "final_aligned_rmsd_angstrom": float(np.sqrt(np.mean(common_final_displacements**2))),
            "initial_ring_rmsd_angstrom": float(
                np.sqrt(np.mean(common_initial_displacements[ring_indices] ** 2))
            ),
            "final_ring_rmsd_angstrom": float(
                np.sqrt(np.mean(common_final_displacements[ring_indices] ** 2))
            ),
        },
    }

    identity_ok = (
        neutral_initial.elements == neutral_final.elements
        and len(neutral_initial.elements) == 25
        and common_cation_elements == neutral_initial.elements
    )
    topology_ok = (
        initial_bonds == final_bonds
        and not added_bonds
        and not removed_bonds
        and len(initial_components) == 1
        and len(final_components) == 1
        and initial_ring == final_ring
    )
    no_collision = final_minimum >= OBVIOUS_COLLISION_ANGSTROM
    global_continuity = (
        aligned_rmsd <= MAX_ALIGNED_RMSD_ANGSTROM
        and float(displacements[max_displacement_index]) <= MAX_ALIGNED_DISPLACEMENT_ANGSTROM
    )
    c2_continuity = (
        abs(c2_n1_final - c2_n1_initial) <= MAX_C2_N_CHANGE_ANGSTROM
        and abs(c2_n3_final - c2_n3_initial) <= MAX_C2_N_CHANGE_ANGSTROM
        and MIN_C2_N_ANGSTROM <= c2_n1_final <= MAX_C2_N_ANGSTROM
        and MIN_C2_N_ANGSTROM <= c2_n3_final <= MAX_C2_N_ANGSTROM
    )
    plane_continuity = (
        final_ring_rms_oop <= MAX_RING_RMS_OOP_ANGSTROM
        and final_ring_max_oop <= MAX_RING_OOP_ANGSTROM
        and final_c2_height <= MAX_C2_HEIGHT_ANGSTROM
        and final_max_ring_dihedral <= MAX_RING_DIHEDRAL_DEGREES
        and normal_angle <= MAX_RING_NORMAL_CHANGE_DEGREES
    )
    no_substituent_flip = maximum_ring_sidechain_delta < SUBSTITUENT_FLIP_DEGREES
    frozen_other_gates_pass = (
        global_continuity
        and c2_continuity
        and topology_ok
        and final_minimum >= PRODUCTION_MIN_PAIR_ANGSTROM
    )
    only_ten_degree_gate_failed = (
        ring_angle_delta > PRODUCTION_RING_ANGLE_GATE_DEGREES and frozen_other_gates_pass
    )
    same_basin_likely = (
        identity_ok
        and topology_ok
        and no_collision
        and global_continuity
        and c2_continuity
        and plane_continuity
        and no_substituent_flip
        and only_ten_degree_gate_failed
    )
    classification = "SAME_BASIN_LIKELY" if same_basin_likely else "DIFFERENT_BASIN_OR_INVALID"

    top_displacements = sorted(
        (
            {
                "atom_index": index,
                "element": neutral_initial.elements[index],
                "aligned_displacement_angstrom": float(displacements[index]),
                "ring_atom": index in set(initial_ring),
            }
            for index in range(len(displacements))
        ),
        key=lambda item: _number(item["aligned_displacement_angstrom"]),
        reverse=True,
    )

    geometry_metrics: dict[str, object] = {
        "schema_version": REVIEW_SCHEMA,
        "candidate": CANDIDATE,
        "neutral_identity": {
            "charge": 0,
            "multiplicity": 1,
            "atom_count_initial": len(neutral_initial.elements),
            "atom_count_final": len(neutral_final.elements),
            "element_sequence_equal": neutral_initial.elements == neutral_final.elements,
            "all_coordinates_finite": bool(
                np.isfinite(neutral_initial.coordinates).all()
                and np.isfinite(neutral_final.coordinates).all()
            ),
            "cation_h23_absent": len(cation_initial.elements) - len(neutral_initial.elements) == 1,
            "cation_minus_h23_sequence_equal": common_cation_elements == neutral_initial.elements,
        },
        "global_geometry": {
            "kabsch_no_reordering": True,
            "aligned_rmsd_angstrom": aligned_rmsd,
            "ring_atom_rmsd_angstrom": ring_rmsd,
            "nonring_atom_rmsd_angstrom": nonring_rmsd,
            "max_aligned_displacement_angstrom": float(displacements[max_displacement_index]),
            "max_displacement_atom_index": max_displacement_index,
            "max_displacement_element": neutral_initial.elements[max_displacement_index],
            "top_five_displacements": top_displacements[:5],
            "max_abs_coordinate_initial_angstrom": float(
                np.max(np.abs(neutral_initial.coordinates))
            ),
            "max_abs_coordinate_final_angstrom": float(np.max(np.abs(neutral_final.coordinates))),
            "minimum_pair_initial_angstrom": initial_minimum,
            "minimum_pair_initial_indices": list(initial_min_pair),
            "minimum_pair_final_angstrom": final_minimum,
            "minimum_pair_final_indices": list(final_min_pair),
            "minimum_nonbonded_initial_angstrom": initial_nonbonded,
            "minimum_nonbonded_initial_indices": list(initial_nonbonded_pair),
            "minimum_nonbonded_final_angstrom": final_nonbonded,
            "minimum_nonbonded_final_indices": list(final_nonbonded_pair),
        },
        "connectivity": {
            "criterion": "v002 covalent radii multiplied by 1.30",
            "initial_bonds": [list(pair) for pair in sorted(initial_bonds)],
            "final_bonds": [list(pair) for pair in sorted(final_bonds)],
            "added_bonds": [list(pair) for pair in added_bonds],
            "removed_bonds": [list(pair) for pair in removed_bonds],
            "initial_components": initial_components,
            "final_components": final_components,
            "c2_neighbors_initial": list(neighbors(initial_bonds, C2)),
            "c2_neighbors_final": list(neighbors(final_bonds, C2)),
            "n1_neighbors_initial": list(neighbors(initial_bonds, N1)),
            "n1_neighbors_final": list(neighbors(final_bonds, N1)),
            "n3_neighbors_initial": list(neighbors(initial_bonds, N3)),
            "n3_neighbors_final": list(neighbors(final_bonds, N3)),
            "one_component": len(initial_components) == len(final_components) == 1,
            "fragmented": len(final_components) != 1,
            "obvious_collision": final_minimum < OBVIOUS_COLLISION_ANGSTROM,
        },
        "sidechain": {
            "heavy_atom_dihedrals": dihedrals,
            "top_five_changes": dihedrals[:5],
            "ring_sidechain_dihedrals": ring_sidechain_dihedrals,
            "maximum_ring_sidechain_delta_degrees": maximum_ring_sidechain_delta,
            "obvious_substituent_flip": not no_substituent_flip,
            "closest_fluorine_to_reaction_centre": closest_fluorine,
            "new_nonbonded_abnormal_contact": final_nonbonded < OBVIOUS_COLLISION_ANGSTROM,
        },
        "four_structure_common_atom_comparison": four_structure_comparison,
    }
    ring_metrics: dict[str, object] = {
        "schema_version": REVIEW_SCHEMA,
        "candidate": CANDIDATE,
        "ring_atom_indices": list(initial_ring),
        "initial": initial_ring_payload,
        "final_after_global_kabsch": final_ring_payload,
        "comparison": ring_comparison,
        "c2_local": {
            "c2_n1_initial_angstrom": c2_n1_initial,
            "c2_n1_final_angstrom": c2_n1_final,
            "c2_n3_initial_angstrom": c2_n3_initial,
            "c2_n3_final_angstrom": c2_n3_final,
            "c2_n_bond_asymmetry_initial_angstrom": abs(c2_n1_initial - c2_n3_initial),
            "c2_n_bond_asymmetry_final_angstrom": abs(c2_n1_final - c2_n3_final),
            "n1_c2_n3_initial_degrees": ring_angle_initial,
            "n1_c2_n3_final_degrees": ring_angle_final,
            "n1_c2_n3_absolute_delta_degrees": ring_angle_delta,
            "c2_height_final_angstrom": final_c2_height,
            "two_coordinate_pyramidalization_directly_defined": False,
            "interpretation": (
                "Local relaxation after C2 deprotonation is chemically possible, but geometry "
                "alone does not establish an electronic-structure mechanism."
            ),
        },
    }
    review_result: dict[str, object] = {
        "schema_version": REVIEW_SCHEMA,
        "science_pilot_only": True,
        "candidate": CANDIDATE,
        "classification": classification,
        "classification_contract": list(CLASSIFICATIONS),
        "v002_terminal_unchanged": True,
        "v002_terminal_status": "FAIL",
        "production_10_degree_gate_unchanged": True,
        "production_10_degree_gate_result": "failed",
        "analysis_only_diagnostics_not_production_gates": True,
        "conditions": {
            "identity_ok": identity_ok,
            "topology_ok": topology_ok,
            "one_component": len(final_components) == 1,
            "no_collision": no_collision,
            "global_continuity": global_continuity,
            "c2_continuity": c2_continuity,
            "ring_plane_continuity": plane_continuity,
            "no_ring_flip": plane_continuity,
            "no_substituent_flip": no_substituent_flip,
            "only_ten_degree_gate_failed": only_ten_degree_gate_failed,
        },
        "scientific_interpretation": (
            "The retained geometry supports preservation of connectivity, reaction-centre "
            "identity, and local conformation; this is not a mathematical proof of one "
            "potential-energy basin."
            if same_basin_likely
            else "One or more frozen continuity conditions were not satisfied."
        ),
        "stage_b_authorized_by_classification": classification == "SAME_BASIN_LIKELY",
        "review_source_sha256": _sha256(Path(__file__).read_bytes()),
        "v002_result_sha256": EXPECTED_FILES["result.json"][1],
        "neutral_initial_sha256": EXPECTED_FILES["input/neutral_initial.xyz"][1],
        "neutral_final_sha256": EXPECTED_FILES["aimnet2/neutral/final.xyz"][1],
        "cation_final_sha256": EXPECTED_FILES["aimnet2/cation/final.xyz"][1],
        "overlay_png": "unavailable_no_allowed_renderer",
    }

    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        csv_buffer,
        fieldnames=["atom_index", "element", "ring_atom", "aligned_displacement_angstrom"],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(top_displacements)

    output_bytes = {
        "file_manifest.json": _canonical_json(
            {
                "schema_version": REVIEW_SCHEMA,
                "files": {name: asdict(value) for name, value in file_evidence.items()},
                "all_regular": True,
                "all_non_symlink": True,
                "all_read_identities_stable": True,
            }
        ),
        "neutral_geometry_metrics.json": _canonical_json(geometry_metrics),
        "ring_local_geometry.json": _canonical_json(ring_metrics),
        "per_atom_displacement.csv": csv_buffer.getvalue().encode("utf-8"),
        "neutral_initial_final_overlay.xyz": (
            raw_files["input/neutral_initial.xyz"] + raw_files["aimnet2/neutral/final.xyz"]
        ),
        "review_result.json": _canonical_json(review_result),
    }
    return review_result, output_bytes


def execute_review(root: Path) -> dict[str, object]:
    result, output_bytes = review_geometry(root)
    review_root = root / "review"
    _make_new_directory(review_root)
    receipts: dict[str, object] = {}
    for name in (
        "file_manifest.json",
        "neutral_geometry_metrics.json",
        "ring_local_geometry.json",
        "per_atom_displacement.csv",
        "neutral_initial_final_overlay.xyz",
        "review_result.json",
    ):
        receipts[name] = write_new(review_root / name, output_bytes[name])

    # Prove that creating the separate review output did not alter any v002 input.
    for relative_path, (expected_bytes, expected_sha) in EXPECTED_FILES.items():
        raw, evidence = read_regular_file(root, relative_path)
        if len(raw) != expected_bytes or evidence.sha256 != expected_sha:
            raise ReviewError(f"v002 evidence changed after review: {relative_path}")
    return {**result, "output_receipts": receipts}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-root", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = execute_review(Path(args.pilot_root).resolve(strict=True))
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
