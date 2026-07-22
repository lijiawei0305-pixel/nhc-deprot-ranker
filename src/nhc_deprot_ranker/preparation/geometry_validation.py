"""Fail-closed validation for the four-candidate Phase 7 geometry smoke.

This file is deliberately self-contained because the Phase 7 transfer bundle copies it
beside its tiny CLI wrapper.  RDKit is imported lazily only when no chemistry adapter is
injected.  Unit tests inject a synthetic adapter and therefore perform no chemistry run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import stat
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

PHASE7_SMOKE_KEYS = (
    "IJWCXRPLHNQISE-UHFFFAOYSA-N",
    "LBNPGYISTSLAHY-UHFFFAOYSA-N",
    "QXHIEGFUWOLQIJ-UHFFFAOYSA-N",
    "HQKHXILTVGYEGE-UHFFFAOYSA-N",
)
INPUT_COLUMNS = ("InChIKey", "SMILES_cation", "SMILES_neutral")
MAP_KEYS = frozenset({"C2_carbene", "N1", "N3"})
INCHIKEY_PATTERN = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_ATOMS = 512
MAX_ABS_COORDINATE_ANGSTROM = 100.0
MIN_INTERATOMIC_DISTANCE_ANGSTROM = 0.20

# IUPAC element symbols through oganesson.  XYZ pseudo-atoms and isotope labels are rejected.
ELEMENT_SYMBOLS = frozenset(
    re.findall(
        r"[A-Z][a-z]?",
        """
        H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn
        Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce
        Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn
        Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl
        Mc Lv Ts Og
        """,
    )
)


class GeometryValidationError(RuntimeError):
    """Raised when a Phase 7 request or geometry artifact fails validation."""


@dataclass(frozen=True)
class MoleculeGraph:
    """Hydrogen-explicit molecular graph returned by a chemistry adapter."""

    atom_symbols: tuple[str, ...]
    formal_charge: int
    neighbors: tuple[tuple[int, ...], ...]
    five_membered_rings: tuple[tuple[int, ...], ...]


class ChemistryAdapter(Protocol):
    """Minimal seam used by the validator's graph and endpoint checks."""

    @property
    def version(self) -> str:
        """Return the chemistry implementation version."""

    def graph_from_smiles(self, smiles: str) -> MoleculeGraph:
        """Parse a SMILES and return its hydrogen-explicit graph."""


@dataclass(frozen=True)
class XYZData:
    """Strictly parsed XYZ contents and finite coordinate statistics."""

    elements: tuple[str, ...]
    coordinates: tuple[tuple[float, float, float], ...]
    coordinate_min: float
    coordinate_max: float
    minimum_distance: float | None


@dataclass(frozen=True)
class GeometryValidationResult:
    """In-memory successful validation and corrected endpoint maps."""

    report: dict[str, Any]
    endpoint_maps: dict[str, dict[str, Any]]


class _RDKitAdapter:
    """Small lazy RDKit adapter; its constructor receives already imported modules."""

    def __init__(self, chemistry_module: Any, version: str) -> None:
        self._chemistry_module = chemistry_module
        self._version = version

    @property
    def version(self) -> str:
        return self._version

    def graph_from_smiles(self, smiles: str) -> MoleculeGraph:
        chemistry = self._chemistry_module
        molecule = chemistry.MolFromSmiles(smiles)
        if molecule is None:
            raise GeometryValidationError("RDKit could not parse an endpoint SMILES")
        molecule = chemistry.AddHs(molecule)
        atoms = tuple(molecule.GetAtoms())
        symbols = tuple(str(atom.GetSymbol()) for atom in atoms)
        charge = sum(int(atom.GetFormalCharge()) for atom in atoms)
        neighbors = tuple(
            tuple(sorted(int(neighbor.GetIdx()) for neighbor in atom.GetNeighbors()))
            for atom in atoms
        )
        rings = tuple(
            tuple(int(index) for index in ring)
            for ring in molecule.GetRingInfo().AtomRings()
            if len(ring) == 5
        )
        return MoleculeGraph(
            atom_symbols=symbols,
            formal_charge=charge,
            neighbors=neighbors,
            five_membered_rings=rings,
        )


def _load_rdkit_adapter() -> ChemistryAdapter:
    """Import RDKit only inside a real validation call."""

    try:
        import rdkit  # type: ignore[import-not-found]
        from rdkit import Chem
    except ImportError as exc:  # pragma: no cover - exercised only in the HPC environment
        raise GeometryValidationError(
            "RDKit is required for real geometry validation but could not be imported"
        ) from exc
    return _RDKitAdapter(Chem, str(rdkit.__version__))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GeometryValidationError(f"JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> None:
    raise GeometryValidationError(f"JSON contains a non-finite number: {value}")


def _load_json_object(path: Path, *, description: str) -> dict[str, Any]:
    _require_regular_file(path, description=description)
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise GeometryValidationError(f"{description} is not UTF-8 text") from exc
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except (json.JSONDecodeError, GeometryValidationError) as exc:
        if isinstance(exc, GeometryValidationError):
            raise
        raise GeometryValidationError(f"{description} is not strict JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise GeometryValidationError(f"{description} must contain a JSON object")
    return payload


def _require_regular_file(path: Path, *, description: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise GeometryValidationError(f"missing {description}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise GeometryValidationError(f"{description} must not be a symlink")
    if not stat.S_ISREG(metadata.st_mode):
        raise GeometryValidationError(f"{description} must be a regular file")


def _safe_relative_path(root: Path, value: object, *, description: str) -> Path:
    if not isinstance(value, str) or not value:
        raise GeometryValidationError(f"{description} must be a nonempty relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
        raise GeometryValidationError(f"{description} is not a safe relative path")
    if root.is_symlink():
        raise GeometryValidationError(f"root for {description} must not be a symlink")
    candidate = root / relative
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise GeometryValidationError(f"{description} traverses a symlink")
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise GeometryValidationError(f"{description} escapes its declared root") from exc
    return candidate


def _require_exact_int(value: object, expected: int, *, description: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise GeometryValidationError(f"{description} must equal integer {expected}")


def _require_exact_string(value: object, expected: str, *, description: str) -> None:
    if value != expected:
        raise GeometryValidationError(f"{description} must equal {expected!r}")


def _require_sha256(value: object, *, description: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise GeometryValidationError(f"{description} must be a lowercase SHA256")
    return value


def _mapping(value: object, *, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GeometryValidationError(f"{description} must be an object")
    return value


def _sequence(value: object, *, description: str) -> list[Any]:
    if not isinstance(value, list):
        raise GeometryValidationError(f"{description} must be an array")
    return value


def _validate_request(request: dict[str, Any]) -> list[dict[str, str]]:
    schema_version = request.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version.strip():
        raise GeometryValidationError("request schema_version must be a nonempty string")
    _require_exact_int(request.get("expected_count"), 4, description="request expected_count")
    _require_exact_int(request.get("seed"), 42, description="request seed")
    _require_exact_int(request.get("num_conformers"), 10, description="request num_conformers")
    _require_exact_int(request.get("parallel"), 1, description="request parallel")
    _require_exact_string(
        request.get("embedding_method"), "ETKDGv3", description="embedding method"
    )
    if request.get("use_random_coords") is not False:
        raise GeometryValidationError("request use_random_coords must be false")
    _require_exact_string(
        request.get("force_field_primary"), "MMFF94", description="primary force field"
    )
    _require_exact_string(
        request.get("force_field_fallback"), "UFF", description="fallback force field"
    )
    _require_exact_string(
        request.get("geometry_quality"),
        "initial_force_field_geometry",
        description="geometry quality",
    )
    _require_exact_string(
        request.get("force_field_convergence"),
        "unavailable_legacy_m2",
        description="force-field convergence",
    )
    expected_scope = {
        "operation": "legacy_m2_initial_geometry_only",
        "candidate_scope": "exact_preregistered_smoke_four",
        "synchronous": True,
        "scheduler_submission": False,
    }
    if request.get("execution_scope") != expected_scope:
        raise GeometryValidationError("request execution_scope changed")
    expected_prohibitions = [
        "no_candidate_replacement_or_backfill",
        "no_xTB",
        "no_PySCF",
        "no_Hessian",
        "no_legacy_M4",
        "no_dedicated_runner_execution",
    ]
    if request.get("prohibitions") != expected_prohibitions:
        raise GeometryValidationError("request prohibitions changed")

    raw_candidates = _sequence(request.get("candidates"), description="request candidates")
    if len(raw_candidates) != 4:
        raise GeometryValidationError("request must contain exactly four candidates")
    candidates: list[dict[str, str]] = []
    for position, raw_candidate in enumerate(raw_candidates, start=1):
        candidate = _mapping(raw_candidate, description=f"candidate {position}")
        if set(candidate) != {"inchikey", "smiles_cation", "smiles_neutral"}:
            raise GeometryValidationError(
                f"candidate {position} must contain exactly inchikey and both endpoint SMILES"
            )
        key = candidate.get("inchikey")
        cation = candidate.get("smiles_cation")
        neutral = candidate.get("smiles_neutral")
        if not isinstance(key, str) or INCHIKEY_PATTERN.fullmatch(key) is None:
            raise GeometryValidationError(f"candidate {position} has an invalid InChIKey")
        if not isinstance(cation, str) or not cation.strip():
            raise GeometryValidationError(f"candidate {position} has an empty cation SMILES")
        if not isinstance(neutral, str) or not neutral.strip():
            raise GeometryValidationError(f"candidate {position} has an empty neutral SMILES")
        candidates.append({"inchikey": key, "smiles_cation": cation, "smiles_neutral": neutral})

    keys = tuple(candidate["inchikey"] for candidate in candidates)
    if keys != PHASE7_SMOKE_KEYS:
        raise GeometryValidationError("request keys/order differ from the frozen Phase 7 smoke")
    if len(set(keys)) != 4:
        raise GeometryValidationError("request candidate InChIKeys must be unique")

    if (
        "ordered_keys" in request
        and tuple(_sequence(request["ordered_keys"], description="request ordered_keys")) != keys
    ):
        raise GeometryValidationError("request ordered_keys disagree with candidates")

    raw_outputs = _sequence(request.get("expected_outputs"), description="expected outputs")
    if len(raw_outputs) != 4:
        raise GeometryValidationError("request expected_outputs must contain exactly four rows")
    for candidate, raw_output in zip(candidates, raw_outputs, strict=True):
        output = _mapping(raw_output, description="expected output")
        expected = {
            "inchikey": candidate["inchikey"],
            "cation_xyz": f"{candidate['inchikey']}_cation.xyz",
            "neutral_xyz": f"{candidate['inchikey']}_neutral.xyz",
            "legacy_atom_map": f"{candidate['inchikey']}_atom_map.json",
        }
        if output != expected:
            raise GeometryValidationError("request expected_outputs differ from fixed core names")
        for field in ("cation_xyz", "neutral_xyz", "legacy_atom_map"):
            path = Path(str(output[field]))
            if path.is_absolute() or len(path.parts) != 1 or ".." in path.parts:
                raise GeometryValidationError("expected core names must be safe basenames")
    return candidates


def _validate_candidate_csv(
    path: Path, request: dict[str, Any], candidates: Sequence[dict[str, str]]
) -> dict[str, Any]:
    _require_regular_file(path, description="candidate CSV")
    descriptor = _mapping(request.get("input_csv"), description="request input_csv")
    if set(descriptor) != {"name", "sha256", "bytes", "rows", "columns"}:
        raise GeometryValidationError("request input_csv descriptor has unexpected fields")
    if descriptor.get("name") != path.name or Path(path.name).name != path.name:
        raise GeometryValidationError("candidate CSV name disagrees with its request descriptor")
    expected_hash = _require_sha256(
        descriptor.get("sha256"), description="candidate CSV registered hash"
    )
    actual_hash = _sha256(path)
    if actual_hash != expected_hash:
        raise GeometryValidationError("candidate CSV SHA256 mismatch")
    _require_exact_int(descriptor.get("bytes"), path.stat().st_size, description="CSV bytes")
    _require_exact_int(descriptor.get("rows"), 4, description="CSV row count")
    if descriptor.get("columns") != list(INPUT_COLUMNS):
        raise GeometryValidationError("candidate CSV registered columns changed")

    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != INPUT_COLUMNS:
                raise GeometryValidationError(
                    "candidate CSV must have exactly the legacy M2 columns"
                )
            rows = list(reader)
    except UnicodeDecodeError as exc:
        raise GeometryValidationError("candidate CSV is not UTF-8") from exc
    if len(rows) != 4:
        raise GeometryValidationError("candidate CSV must contain exactly four rows")
    normalized = [
        {
            "inchikey": row["InChIKey"],
            "smiles_cation": row["SMILES_cation"],
            "smiles_neutral": row["SMILES_neutral"],
        }
        for row in rows
    ]
    if normalized != list(candidates):
        raise GeometryValidationError("candidate CSV differs from the frozen request/order")
    return {
        "name": path.name,
        "sha256": actual_hash,
        "bytes": path.stat().st_size,
        "rows": len(rows),
        "columns": list(INPUT_COLUMNS),
    }


def _validate_legacy_files(request: dict[str, Any], legacy_root: Path) -> dict[str, Any]:
    legacy = _mapping(request.get("legacy"), description="request legacy")
    commit = legacy.get("commit")
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise GeometryValidationError("legacy commit must be a full lowercase Git SHA")
    realized: dict[str, Any] = {"commit": commit, "files": {}}
    for key in ("gen_3d", "structure_gen"):
        descriptor = _mapping(legacy.get(key), description=f"legacy {key}")
        if set(descriptor) != {"path", "sha256"}:
            raise GeometryValidationError(f"legacy {key} descriptor has unexpected fields")
        path = _safe_relative_path(
            legacy_root, descriptor.get("path"), description=f"legacy {key} path"
        )
        _require_regular_file(path, description=f"legacy {key} source")
        expected = _require_sha256(
            descriptor.get("sha256"), description=f"legacy {key} registered hash"
        )
        actual = _sha256(path)
        if actual != expected:
            raise GeometryValidationError(f"legacy {key} SHA256 mismatch")
        realized["files"][key] = {
            "path": str(descriptor["path"]),
            "sha256": actual,
            "bytes": path.stat().st_size,
        }
    return realized


def _parse_xyz(path: Path, *, description: str) -> XYZData:
    _require_regular_file(path, description=description)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise GeometryValidationError(f"{description} is not UTF-8") from exc
    if "\x00" in text:
        raise GeometryValidationError(f"{description} contains a NUL byte")
    lines = text.splitlines()
    if len(lines) < 3:
        raise GeometryValidationError(f"{description} is incomplete")
    count_token = lines[0].strip()
    if re.fullmatch(r"[1-9][0-9]*", count_token) is None:
        raise GeometryValidationError(f"{description} atom count must be an exact positive integer")
    atom_count = int(count_token)
    if atom_count > MAX_ATOMS:
        raise GeometryValidationError(f"{description} exceeds the atom-count safety bound")
    if len(lines) != atom_count + 2:
        raise GeometryValidationError(f"{description} line count differs from its atom count")

    elements: list[str] = []
    coordinates: list[tuple[float, float, float]] = []
    for line_number, line in enumerate(lines[2:], start=3):
        tokens = line.split()
        if len(tokens) != 4:
            raise GeometryValidationError(
                f"{description} line {line_number} must contain exactly four fields"
            )
        element = tokens[0]
        if element not in ELEMENT_SYMBOLS:
            raise GeometryValidationError(
                f"{description} line {line_number} has an unrecognized element"
            )
        try:
            coordinate = tuple(float(token) for token in tokens[1:])
        except ValueError as exc:
            raise GeometryValidationError(
                f"{description} line {line_number} has a nonnumeric coordinate"
            ) from exc
        if len(coordinate) != 3 or not all(math.isfinite(value) for value in coordinate):
            raise GeometryValidationError(
                f"{description} line {line_number} has a non-finite coordinate"
            )
        if any(abs(value) > MAX_ABS_COORDINATE_ANGSTROM for value in coordinate):
            raise GeometryValidationError(
                f"{description} line {line_number} exceeds the coordinate bound"
            )
        elements.append(element)
        coordinates.append((coordinate[0], coordinate[1], coordinate[2]))

    minimum_distance: float | None = None
    if len(coordinates) > 1:
        minimum_distance = min(
            math.dist(coordinates[left], coordinates[right])
            for left in range(len(coordinates))
            for right in range(left + 1, len(coordinates))
        )
        if minimum_distance < MIN_INTERATOMIC_DISTANCE_ANGSTROM:
            raise GeometryValidationError(f"{description} contains colliding atoms")
    flattened = [coordinate for point in coordinates for coordinate in point]
    return XYZData(
        elements=tuple(elements),
        coordinates=tuple(coordinates),
        coordinate_min=min(flattened),
        coordinate_max=max(flattened),
        minimum_distance=minimum_distance,
    )


def _validate_graph(graph: MoleculeGraph, *, description: str) -> None:
    atom_count = len(graph.atom_symbols)
    if atom_count < 1 or atom_count > MAX_ATOMS:
        raise GeometryValidationError(f"{description} graph has an invalid atom count")
    if isinstance(graph.formal_charge, bool) or not isinstance(graph.formal_charge, int):
        raise GeometryValidationError(f"{description} formal charge must be an integer")
    if len(graph.neighbors) != atom_count:
        raise GeometryValidationError(f"{description} graph neighbor table has the wrong size")
    if any(symbol not in ELEMENT_SYMBOLS for symbol in graph.atom_symbols):
        raise GeometryValidationError(f"{description} graph has an unrecognized element")
    for index, neighbors in enumerate(graph.neighbors):
        if len(neighbors) != len(set(neighbors)):
            raise GeometryValidationError(f"{description} graph repeats a neighbor")
        for neighbor in neighbors:
            if isinstance(neighbor, bool) or not isinstance(neighbor, int):
                raise GeometryValidationError(f"{description} graph index must be an integer")
            if neighbor < 0 or neighbor >= atom_count or neighbor == index:
                raise GeometryValidationError(f"{description} graph index is out of range")
            if index not in graph.neighbors[neighbor]:
                raise GeometryValidationError(f"{description} graph adjacency is asymmetric")
    for ring in graph.five_membered_rings:
        if len(ring) != 5 or len(set(ring)) != 5:
            raise GeometryValidationError(f"{description} ring must contain five unique atoms")
        if any(
            isinstance(index, bool)
            or not isinstance(index, int)
            or index < 0
            or index >= atom_count
            for index in ring
        ):
            raise GeometryValidationError(f"{description} ring index is out of range")


def _load_legacy_atom_map(path: Path, graph: MoleculeGraph) -> dict[str, int]:
    payload = _load_json_object(path, description="legacy atom map")
    if set(payload) != MAP_KEYS:
        raise GeometryValidationError("legacy atom map must contain exactly C2_carbene/N1/N3")
    result: dict[str, int] = {}
    for key in sorted(MAP_KEYS):
        value = payload[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise GeometryValidationError(f"legacy atom-map value {key} must be an exact integer")
        if value < 0 or value >= len(graph.atom_symbols):
            raise GeometryValidationError(f"legacy atom-map value {key} is out of range")
        result[key] = value
    if len(set(result.values())) != 3:
        raise GeometryValidationError("legacy atom-map indices must be distinct")
    expected_symbols = {"C2_carbene": "C", "N1": "N", "N3": "N"}
    for key, symbol in expected_symbols.items():
        if graph.atom_symbols[result[key]] != symbol:
            raise GeometryValidationError(f"legacy atom-map value {key} maps to the wrong element")
    return result


def _hydrogen_neighbors(graph: MoleculeGraph, atom_index: int) -> tuple[int, ...]:
    return tuple(
        neighbor for neighbor in graph.neighbors[atom_index] if graph.atom_symbols[neighbor] == "H"
    )


def _derive_ring_map(graph: MoleculeGraph, *, require_c2_hydrogens: int) -> dict[str, int]:
    candidates: list[dict[str, int]] = []
    for carbon_index, symbol in enumerate(graph.atom_symbols):
        if symbol != "C" or len(_hydrogen_neighbors(graph, carbon_index)) != require_c2_hydrogens:
            continue
        nitrogen_neighbors = sorted(
            neighbor
            for neighbor in graph.neighbors[carbon_index]
            if graph.atom_symbols[neighbor] == "N"
        )
        if len(nitrogen_neighbors) != 2:
            continue
        shared_rings = [
            ring
            for ring in graph.five_membered_rings
            if carbon_index in ring and all(nitrogen in ring for nitrogen in nitrogen_neighbors)
        ]
        if not shared_rings:
            continue
        candidates.append(
            {
                "C2_carbene": carbon_index,
                "N1": nitrogen_neighbors[0],
                "N3": nitrogen_neighbors[1],
            }
        )
    if len(candidates) != 1:
        raise GeometryValidationError(
            "endpoint graph must yield exactly one C2 in a shared five-membered two-N ring"
        )
    return candidates[0]


def _validate_endpoint_pair(
    key: str,
    candidate: dict[str, str],
    cation_xyz: XYZData,
    neutral_xyz: XYZData,
    cation_graph: MoleculeGraph,
    legacy_map: dict[str, int],
    chemistry_adapter: ChemistryAdapter,
) -> tuple[dict[str, Any], dict[str, Any]]:
    neutral_graph = chemistry_adapter.graph_from_smiles(candidate["smiles_neutral"])
    _validate_graph(cation_graph, description=f"{key} cation")
    _validate_graph(neutral_graph, description=f"{key} neutral")
    if cation_graph.formal_charge != 1:
        raise GeometryValidationError(f"{key} cation formal charge is not +1")
    if neutral_graph.formal_charge != 0:
        raise GeometryValidationError(f"{key} neutral formal charge is not 0")
    if cation_xyz.elements != cation_graph.atom_symbols:
        raise GeometryValidationError(f"{key} cation XYZ elements/order disagree with AddHs")
    if neutral_xyz.elements != neutral_graph.atom_symbols:
        raise GeometryValidationError(f"{key} neutral XYZ elements/order disagree with AddHs")

    cation_heavy = Counter(symbol for symbol in cation_graph.atom_symbols if symbol != "H")
    neutral_heavy = Counter(symbol for symbol in neutral_graph.atom_symbols if symbol != "H")
    if cation_heavy != neutral_heavy:
        raise GeometryValidationError(f"{key} endpoint heavy-atom element multisets differ")
    cation_hydrogens = cation_graph.atom_symbols.count("H")
    neutral_hydrogens = neutral_graph.atom_symbols.count("H")
    if cation_hydrogens != neutral_hydrogens + 1:
        raise GeometryValidationError(f"{key} endpoints do not differ by exactly one proton")

    cation_derived = _derive_ring_map(cation_graph, require_c2_hydrogens=1)
    if legacy_map["C2_carbene"] != cation_derived["C2_carbene"] or {
        legacy_map["N1"],
        legacy_map["N3"],
    } != {cation_derived["N1"], cation_derived["N3"]}:
        raise GeometryValidationError(f"{key} legacy cation atom map disagrees with its graph")
    neutral_derived = _derive_ring_map(neutral_graph, require_c2_hydrogens=0)

    endpoint_map = {
        "schema_version": "phase7.endpoint_atom_map.v1",
        "inchikey": key,
        "mapping_basis": {
            "cation": "validated_legacy_m2_cation_map",
            "neutral": "independent_graph_shared_five_membered_ring",
        },
        "cation": legacy_map,
        "neutral": neutral_derived,
    }
    checks = {
        "formal_charges": {"cation": 1, "neutral": 0},
        "atom_counts": {
            "cation": len(cation_graph.atom_symbols),
            "neutral": len(neutral_graph.atom_symbols),
        },
        "hydrogen_counts": {"cation": cation_hydrogens, "neutral": neutral_hydrogens},
        "heavy_element_multiset": dict(sorted(cation_heavy.items())),
        "legacy_cation_map": legacy_map,
        "neutral_graph_map": neutral_derived,
        "coordinate_extrema_angstrom": {
            "cation": {"minimum": cation_xyz.coordinate_min, "maximum": cation_xyz.coordinate_max},
            "neutral": {
                "minimum": neutral_xyz.coordinate_min,
                "maximum": neutral_xyz.coordinate_max,
            },
        },
        "minimum_interatomic_distance_angstrom": {
            "cation": cation_xyz.minimum_distance,
            "neutral": neutral_xyz.minimum_distance,
        },
        "element_sequence_matches_add_hs": {"cation": True, "neutral": True},
        "one_c2_proton_difference": True,
    }
    return checks, endpoint_map


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _validate_core_tree(xyz_dir: Path, keys: Sequence[str]) -> dict[str, Path]:
    if xyz_dir.is_symlink():
        raise GeometryValidationError("XYZ directory must not be a symlink")
    if not xyz_dir.is_dir():
        raise GeometryValidationError("XYZ directory is missing")
    expected_names = {
        name
        for key in keys
        for name in (f"{key}_cation.xyz", f"{key}_neutral.xyz", f"{key}_atom_map.json")
    }
    actual_entries = list(xyz_dir.iterdir())
    actual_names = {entry.name for entry in actual_entries}
    if actual_names != expected_names or len(actual_entries) != 12:
        raise GeometryValidationError(
            "XYZ directory must contain exactly the 12 registered core files"
        )
    files: dict[str, Path] = {}
    for name in sorted(expected_names):
        path = _safe_relative_path(xyz_dir, name, description=f"core file {name}")
        _require_regular_file(path, description=f"core file {name}")
        files[name] = path
    return files


def validate_geometry_smoke(
    *,
    request_path: Path,
    input_path: Path,
    xyz_dir: Path,
    chemistry_adapter: ChemistryAdapter | None = None,
    legacy_root: Path | None = None,
) -> GeometryValidationResult:
    """Validate the exact frozen smoke and return an in-memory report.

    This function performs no output write.  Passing ``chemistry_adapter`` keeps RDKit entirely
    unimported, which is the required local-test path.
    """

    request = _load_json_object(request_path, description="geometry request")
    candidates = _validate_request(request)
    input_provenance = _validate_candidate_csv(input_path, request, candidates)
    legacy_provenance = _validate_legacy_files(request, legacy_root or Path.cwd())
    core_files = _validate_core_tree(xyz_dir, [candidate["inchikey"] for candidate in candidates])
    adapter = chemistry_adapter if chemistry_adapter is not None else _load_rdkit_adapter()

    candidate_results: list[dict[str, Any]] = []
    endpoint_maps: dict[str, dict[str, Any]] = {}
    output_hashes: dict[str, str] = {}
    for request_order, candidate in enumerate(candidates, start=1):
        key = candidate["inchikey"]
        cation_name = f"{key}_cation.xyz"
        neutral_name = f"{key}_neutral.xyz"
        map_name = f"{key}_atom_map.json"
        cation_xyz = _parse_xyz(core_files[cation_name], description=f"{key} cation XYZ")
        neutral_xyz = _parse_xyz(core_files[neutral_name], description=f"{key} neutral XYZ")
        cation_graph = adapter.graph_from_smiles(candidate["smiles_cation"])
        _validate_graph(cation_graph, description=f"{key} cation")
        legacy_map = _load_legacy_atom_map(core_files[map_name], cation_graph)
        checks, endpoint_map = _validate_endpoint_pair(
            key,
            candidate,
            cation_xyz,
            neutral_xyz,
            cation_graph,
            legacy_map,
            adapter,
        )
        endpoint_maps[key] = endpoint_map
        file_hashes = {
            cation_name: _sha256(core_files[cation_name]),
            neutral_name: _sha256(core_files[neutral_name]),
            map_name: _sha256(core_files[map_name]),
        }
        output_hashes.update(file_hashes)
        candidate_results.append(
            {
                "request_order": request_order,
                "inchikey": key,
                "status": "passed",
                "files": file_hashes,
                "checks": checks,
                "force_field_convergence": "unavailable_legacy_m2",
                "geometry_quality": "initial_force_field_geometry",
            }
        )

    report: dict[str, Any] = {
        "schema_version": "phase7.geometry_validation.v1",
        "validation_status": "passed",
        "validated_candidates": 4,
        "expected_candidates": 4,
        "ordered_keys": list(PHASE7_SMOKE_KEYS),
        "request": {
            "sha256": _sha256(request_path),
            "schema_version": request["schema_version"],
            "seed": 42,
            "num_conformers": 10,
            "parallel": 1,
            "force_field_primary": "MMFF94",
            "force_field_fallback": "UFF",
        },
        "input_csv": input_provenance,
        "legacy": legacy_provenance,
        "validator_source": {
            "name": Path(__file__).name,
            "sha256": _sha256(Path(__file__)),
        },
        "runtime_versions": {
            "python": platform.python_version(),
            "rdkit": adapter.version,
            "pandas": _distribution_version("pandas"),
            "numpy": _distribution_version("numpy"),
        },
        "coordinate_policy": {
            "maximum_atoms": MAX_ATOMS,
            "maximum_absolute_coordinate_angstrom": MAX_ABS_COORDINATE_ANGSTROM,
            "minimum_interatomic_distance_angstrom": MIN_INTERATOMIC_DISTANCE_ANGSTROM,
        },
        "core_file_count": len(core_files),
        "core_output_sha256": dict(sorted(output_hashes.items())),
        "candidate_results": candidate_results,
        "force_field_convergence": "unavailable_legacy_m2",
        "geometry_quality": "initial_force_field_geometry",
        "quantum_chemistry_run": False,
        "hessian_computed": False,
        "replacement_candidate_used": False,
    }
    # Prove before any output write that the full report is strict JSON with no NaN/Infinity.
    _json_bytes(report)
    for endpoint_map in endpoint_maps.values():
        _json_bytes(endpoint_map)
    return GeometryValidationResult(report=report, endpoint_maps=endpoint_maps)


def _check_output_location(output_dir: Path) -> tuple[Path, Path]:
    if output_dir.is_symlink():
        raise GeometryValidationError("validation output directory must not be a symlink")
    if output_dir.exists() and not output_dir.is_dir():
        raise GeometryValidationError("validation output location is not a directory")
    report_path = output_dir / "geometry_validation.json"
    maps_dir = output_dir / "endpoint_atom_maps"
    if report_path.exists() or report_path.is_symlink():
        raise GeometryValidationError(
            "geometry validation report already exists; refusing overwrite"
        )
    if maps_dir.exists() or maps_dir.is_symlink():
        raise GeometryValidationError(
            "endpoint atom-map directory already exists; refusing overwrite"
        )
    return report_path, maps_dir


def _atomic_create_bytes(path: Path, payload: bytes) -> None:
    """Atomically create a new regular file without replacing an existing path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise GeometryValidationError(
                f"output already exists; refusing overwrite: {path.name}"
            ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _write_success_artifacts(
    output_dir: Path, validation: GeometryValidationResult
) -> dict[str, Any]:
    report_path, maps_dir = _check_output_location(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    maps_dir.mkdir()
    map_hashes: dict[str, str] = {}
    for key in PHASE7_SMOKE_KEYS:
        name = f"{key}_endpoint_atom_map.json"
        payload = _json_bytes(validation.endpoint_maps[key])
        _atomic_create_bytes(maps_dir / name, payload)
        map_hashes[name] = _sha256_bytes(payload)
    report = dict(validation.report)
    report["endpoint_atom_map_sha256"] = dict(sorted(map_hashes.items()))
    _atomic_create_bytes(report_path, _json_bytes(report))
    return report


def _failure_report(message: str, chemistry_adapter: ChemistryAdapter | None) -> dict[str, Any]:
    return {
        "schema_version": "phase7.geometry_validation.v1",
        "validation_status": "failed",
        "validated_candidates": 0,
        "expected_candidates": 4,
        "ordered_keys": list(PHASE7_SMOKE_KEYS),
        "error": message,
        "runtime_versions": {
            "python": platform.python_version(),
            "rdkit": chemistry_adapter.version if chemistry_adapter is not None else "unavailable",
            "pandas": _distribution_version("pandas"),
            "numpy": _distribution_version("numpy"),
        },
        "quantum_chemistry_run": False,
        "hessian_computed": False,
        "replacement_candidate_used": False,
    }


def run_geometry_validation(
    *,
    request_path: Path,
    input_path: Path,
    xyz_dir: Path,
    output_dir: Path,
    chemistry_adapter: ChemistryAdapter | None = None,
    legacy_root: Path | None = None,
) -> int:
    """Validate, atomically create a report, and return a CLI-compatible status code."""

    try:
        _check_output_location(output_dir)
    except GeometryValidationError as exc:
        print(f"geometry validation refused: {exc}", file=sys.stderr)
        return 2
    try:
        validation = validate_geometry_smoke(
            request_path=request_path,
            input_path=input_path,
            xyz_dir=xyz_dir,
            chemistry_adapter=chemistry_adapter,
            legacy_root=legacy_root,
        )
        _write_success_artifacts(output_dir, validation)
    except GeometryValidationError as exc:
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "geometry_validation.json"
        try:
            _atomic_create_bytes(
                report_path,
                _json_bytes(_failure_report(str(exc), chemistry_adapter)),
            )
        except GeometryValidationError as write_exc:
            print(
                f"geometry validation failed and report was not written: {write_exc}",
                file=sys.stderr,
            )
            return 2
        print(f"geometry validation failed: {exc}", file=sys.stderr)
        return 1
    print("geometry validation passed: 4/4 candidates and 12/12 core files")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone Phase 7 validation CLI."""

    parser = argparse.ArgumentParser(description="Validate the frozen Phase 7 geometry smoke")
    parser.add_argument("--request", required=True, type=Path, help="geometry_request.json")
    parser.add_argument("--input", required=True, type=Path, help="four-row smoke CSV")
    parser.add_argument("--xyz-dir", required=True, type=Path, help="legacy M2 XYZ directory")
    parser.add_argument(
        "--output-dir", required=True, type=Path, help="new validation audit directory"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone validator without importing project-internal modules."""

    arguments = build_parser().parse_args(argv)
    return run_geometry_validation(
        request_path=arguments.request,
        input_path=arguments.input,
        xyz_dir=arguments.xyz_dir,
        output_dir=arguments.output_dir,
        legacy_root=Path.cwd(),
    )


if __name__ == "__main__":  # pragma: no cover - wrapper and tests exercise main directly
    raise SystemExit(main())
