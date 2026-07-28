#!/usr/bin/env python3
"""One-shot direct frozen-geometry PySCF comparison for science pilot v005."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import resource
import stat
import sys
import tempfile
import time
import traceback
from importlib import metadata
from pathlib import Path
from typing import Any, Final, cast

CANDIDATE: Final = "LBNPGYISTSLAHY-UHFFFAOYSA-N"
ROOT_NAME: Final = "science_pilot_lbn_direct_sp_v005"
V002_ROOT_NAME: Final = "science_pilot_lbn_v002"
V004_ROOT_NAME: Final = "science_pilot_lbn_pyscf_v004"
ENDPOINTS: Final = ("cation", "neutral")
CHARGES: Final = {"cation": 1, "neutral": 0}
MULTIPLICITIES: Final = {"cation": 1, "neutral": 1}
SPINS: Final = {"cation": 0, "neutral": 0}
ATOM_COUNTS: Final = {"cation": 26, "neutral": 25}
ELECTRON_COUNT: Final = 160
DIRECT_BYTES: Final = {"cation": 1075, "neutral": 1036}
DIRECT_SHA256: Final = {
    "cation": "543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286",
    "neutral": "af9c30640801eec3ab27538a33204186849303dd57592ca5c93320ec1390f4b8",
}
ASSISTED_INPUT_SHA256: Final = {
    "cation": "ea796a5c81504184382b965d57c588c74968a09de8942148d3d9cbadf70a7774",
    "neutral": "c40ca77bce9d8c8deefc2357bf2633fb4c0981ce9d4bd23aceb342d40646bc93",
}
ATOM_ORDER_SHA256: Final = {
    "cation": "eb7439bedb2ecbc38e2a1dd214b5f4ed08c1cb775a88fe853bcc60ad23d13f4a",
    "neutral": "8a81d92db63e3056908ad6e550f4193246b016bbfca7270f53a9eebd82675380",
}
V002_RESULT_SHA256: Final = "b1362a3b1df7ef7ba276bac0c91fd8002fd27123eca37d84a82b937edacd7071"
V002_AIMNET_RESULT_SHA256: Final = {
    "cation": "38dd7a9ca9b203a33634bdaee2b7ec16d4dd90ba0e2f5ade6f479a57814ea3d7",
    "neutral": "d117bac41435315349e912cb34bbd039fe0ee1fcf90ddb585313a20018ae89ee",
}
REVIEW_RESULT_SHA256: Final = "f8f5cd80f117edc8ce061f901f797bce23b6934dc6ded6d1c8a52871b533f86e"
V004_CONTINUATION_SHA256: Final = "40029ba06bdf7109ab96ea1172c39af1445d1f7ca655dddefabe707bc1c69a73"
GEOMETRY_REVIEW_SOURCE_SHA256: Final = (
    "659021fbd5981906ca563810f62cb096347bd94c9facb5f7f55c129868c4d97f"
)
HELPER_SOURCE_SHA256: Final = "b38aa93008f744551c2dec352214c1bcc53f71e3ceddfcfe0e5e73ce15a04a55"
TWO_ENDPOINT_SOURCE_SHA256: Final = (
    "44e16576ae37e52ff7b0d399a1b11d3932a9baa19b6a4aae8c603c8e29f9d977"
)
V004_RESULT_SHA256: Final = "dbb0a66fa937e97a19c947d69d409db9323702ba58666865482db80a76c0621c"
V004_ENDPOINT_SHA256: Final = {
    "cation": "1e881fbf50bc963ab3d23c1fa6942c5ea16d6f63eae9aed5f37b745bd43f1eb0",
    "neutral": "8e17664f5cadae807ac4f6bba672112f8c5fcaa014e28b98ce3b6cbe00060880",
}
V004_RUN_CONFIG_SHA256: Final = {
    "cation": "fede60870a337253d8a093a8917279dacd967edb361447b5f1b099467e0af729",
    "neutral": "c6b848e82c94ce8f580961e24461fb2628977da1fa9a18bef2e2bc5bebdbb5de",
}
EXPECTED_ASSISTED: Final = {
    "cation": {
        "energy_hartree": -1407.5280546795084,
        "scf_cycles": 12,
        "wall_seconds": 76.15011653210968,
    },
    "neutral": {
        "energy_hartree": -1407.137418762397,
        "scf_cycles": 12,
        "wall_seconds": 123.84613075200468,
    },
}
EXPECTED_ASSISTED_LABEL: Final = 238.8477388721244
EXPECTED_EXECUTABLE_SHA256: Final = (
    "24a07a0a383fd666309acf92ad4e913dd372b3f2d4592d60f1f2f0ca7138fc61"
)
SCHEMA_VERSION: Final = "nhc-phase9b-science-pilot-direct-comparison-v005"
WALL_LIMIT_SECONDS: Final = 7170.0
MAX_BOOTSTRAP_BYTES: Final = 64 << 20
HISTORICAL_AND_SCOPE_FLAGS: Final = {
    "production_accepted": False,
    "production_label_inserted": False,
    "aimnet2_rerun": False,
    "pyscf_geometry_optimization": False,
    "second_candidate": False,
    "batch": False,
    "v001_unchanged": True,
    "v002_unchanged": True,
    "v004_assisted_result_unchanged": True,
    "production_10_degree_gate_unchanged": True,
}

PROTOCOL_KEYS: Final = (
    "protocol_kind",
    "parent_protocol_reference_only",
    "method",
    "basis",
    "dispersion",
    "d3_owner_setting",
    "grid_level",
    "scf_conv_tol",
    "standard_max_cycles",
    "soscf_max_cycles",
    "soscf_policy",
    "initial_guess_policy",
    "geometry_optimization",
    "geometry_optimizer_invoked",
    "charge",
    "multiplicity",
    "spin",
    "electron_count",
    "threads",
    "max_memory_mb",
    "cpu_affinity",
)


class DirectComparisonError(RuntimeError):
    """The isolated direct comparison failed its evidence contract."""


class DirectHandoffError(DirectComparisonError):
    """Frozen initial XYZ bytes did not survive the direct handoff."""


class ProtocolMismatchError(DirectComparisonError):
    """Direct and assisted single-point protocol projections differ."""


class ScientificResultError(DirectComparisonError):
    """The frozen PySCF protocol produced an invalid scientific result."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def bootstrap_read(path: Path) -> bytes:
    if path.is_symlink():
        raise DirectComparisonError(f"bootstrap source is a symlink: {path.name}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise DirectComparisonError(f"unsafe bootstrap source: {path.name}")
        if before.st_size < 0 or before.st_size > MAX_BOOTSTRAP_BYTES:
            raise DirectComparisonError(f"bootstrap source size is invalid: {path.name}")
        remaining = before.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1 << 20))
            if not chunk:
                raise DirectComparisonError(f"short bootstrap read: {path.name}")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise DirectComparisonError(f"bootstrap source drifted: {path.name}")
    return b"".join(chunks)


def load_exact_module(path: Path, *, module_name: str, expected_sha256: str) -> Any:
    raw = bootstrap_read(path)
    if sha256_bytes(raw) != expected_sha256:
        raise DirectComparisonError(f"module source identity drifted: {path.name}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise DirectComparisonError(f"module loader is unavailable: {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if bootstrap_read(path) != raw:
        raise DirectComparisonError(f"module source drifted across import: {path.name}")
    return module


def strict_json(raw: bytes, *, label: str) -> dict[str, object]:
    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in pairs:
            if key in payload:
                raise DirectComparisonError(f"{label} contains a duplicate JSON key")
            payload[key] = value
        return payload

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs_hook,
            parse_constant=lambda token: (_ for _ in ()).throw(
                DirectComparisonError(f"{label} contains {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectComparisonError(f"{label} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise DirectComparisonError(f"{label} is not a JSON object")
    return cast(dict[str, object], value)


def protocol_projection(config: dict[str, object]) -> dict[str, object]:
    missing = [key for key in PROTOCOL_KEYS if key not in config]
    if missing:
        raise ProtocolMismatchError(f"run config is missing protocol fields: {missing}")
    return {key: config[key] for key in PROTOCOL_KEYS}


def compare_protocol(
    *, direct: dict[str, object], assisted: dict[str, object], endpoint: str
) -> None:
    if protocol_projection(direct) != protocol_projection(assisted):
        raise ProtocolMismatchError(f"{endpoint} direct/assisted protocol mismatch")


def interpreter_projection(identity: dict[str, object]) -> dict[str, object]:
    keys = (
        "environment_root",
        "logical_launcher",
        "resolved_executable",
        "resolved_executable_bytes",
        "resolved_executable_sha256",
        "resolved_inside_environment_root",
    )
    if any(key not in identity for key in keys):
        raise DirectComparisonError("interpreter identity is missing stable fields")
    return {key: identity[key] for key in keys}


def calculate_comparison(
    *,
    direct_endpoints: dict[str, dict[str, object]],
    assisted_endpoints: dict[str, dict[str, object]],
    direct_label: float,
    assisted_label: float,
) -> tuple[dict[str, object], dict[str, object]]:
    endpoints: dict[str, object] = {}
    for endpoint in ENDPOINTS:
        direct = direct_endpoints[endpoint]
        assisted = assisted_endpoints[endpoint]
        direct_energy = float(cast(float, direct["energy_hartree"]))
        assisted_energy = float(cast(float, assisted["energy_hartree"]))
        direct_cycles = direct["scf_cycles"]
        assisted_cycles = assisted["scf_cycles"]
        direct_wall = float(cast(float, direct["wall_seconds"]))
        assisted_wall = float(cast(float, assisted["wall_seconds"]))
        if not all(
            math.isfinite(value)
            for value in (direct_energy, assisted_energy, direct_wall, assisted_wall)
        ):
            raise DirectComparisonError(f"{endpoint} comparison contains non-finite values")
        if direct_wall <= 0.0 or assisted_wall <= 0.0:
            raise DirectComparisonError(f"{endpoint} comparison wall time is not positive")
        if type(direct_cycles) is not int or type(assisted_cycles) is not int:
            cycle_delta: int | str = "unavailable"
        else:
            cycle_delta = assisted_cycles - direct_cycles
        endpoints[endpoint] = {
            "endpoint": endpoint,
            "direct_geometry_provenance": "frozen_initial",
            "assisted_geometry_provenance": "aimnet2_preoptimized",
            "direct_energy_hartree": direct_energy,
            "assisted_energy_hartree": assisted_energy,
            "energy_shift_assisted_minus_direct_hartree": assisted_energy - direct_energy,
            "energy_shift_assisted_minus_direct_kcal_per_mol": (assisted_energy - direct_energy)
            * 627.509474,
            "direct_scf_cycles": direct_cycles,
            "assisted_scf_cycles": assisted_cycles,
            "cycle_delta_assisted_minus_direct": cycle_delta,
            "direct_wall_seconds": direct_wall,
            "assisted_wall_seconds": assisted_wall,
            "wall_delta_assisted_minus_direct_seconds": assisted_wall - direct_wall,
            "wall_ratio_direct_over_assisted": direct_wall / assisted_wall,
        }
    if not math.isfinite(direct_label) or not math.isfinite(assisted_label):
        raise DirectComparisonError("label comparison contains a non-finite value")
    label: dict[str, object] = {
        "direct_dft_deprot_electronic_kcal_per_mol": direct_label,
        "assisted_dft_deprot_electronic_kcal_per_mol": assisted_label,
        "label_delta_assisted_minus_direct_kcal_per_mol": assisted_label - direct_label,
    }
    return endpoints, label


def validate_endpoint_start(*, endpoint: str, completed: tuple[str, ...]) -> None:
    expected = ENDPOINTS[len(completed)] if len(completed) < len(ENDPOINTS) else None
    if endpoint != expected or completed != ENDPOINTS[: len(completed)]:
        raise DirectComparisonError("direct endpoints are not executing exactly once in order")


def classify_runtime_failure(*, v004: Any, two_endpoint: Any, exc: BaseException) -> str:
    if isinstance(exc, (DirectHandoffError, ProtocolMismatchError, ScientificResultError)):
        return "FAIL"
    return cast(str, v004._failure_outcome(two_endpoint, exc))


def validate_and_copy_input(
    *,
    v004: Any,
    two_endpoint: Any,
    endpoint: str,
    source: Path,
    evidence_copy: Path,
    parser_input: Path,
) -> tuple[bytes, Any, dict[str, object]]:
    source_raw, source_identity = v004.read_regular_file(source)
    if (
        len(source_raw) != DIRECT_BYTES[endpoint]
        or sha256_bytes(source_raw) != DIRECT_SHA256[endpoint]
    ):
        raise DirectHandoffError(f"{endpoint} frozen initial XYZ identity drifted")
    evidence_receipt = v004.write_new(evidence_copy, source_raw)
    parser_receipt = v004.write_new(parser_input, source_raw)
    copied_raw, copied_identity = v004.read_regular_file(evidence_copy)
    parser_raw, parser_identity = v004.read_regular_file(parser_input)
    if not (source_raw == copied_raw == parser_raw):
        raise DirectHandoffError(f"{endpoint} direct exact-byte handoff failed")
    try:
        geometry = two_endpoint._parse_xyz(parser_raw, label=f"science pilot v005 {endpoint}")
    except two_endpoint.RequestValidationError as exc:
        raise DirectHandoffError(f"{endpoint} frozen XYZ is not parseable") from exc
    elements = tuple(atom.element for atom in geometry.atoms)
    element_digest = sha256_bytes(" ".join(elements).encode("utf-8"))
    if (
        len(elements) != ATOM_COUNTS[endpoint]
        or element_digest != ATOM_ORDER_SHA256[endpoint]
        or two_endpoint._electron_count_for_geometry(geometry, charge=CHARGES[endpoint])
        != ELECTRON_COUNT
        or MULTIPLICITIES[endpoint] - 1 != SPINS[endpoint]
    ):
        raise DirectHandoffError(f"{endpoint} direct endpoint identity drifted")
    receipt = {
        "schema_version": "nhc-phase9b-science-pilot-direct-handoff-v005",
        "science_pilot_only": True,
        "candidate": CANDIDATE,
        "endpoint": endpoint,
        "geometry_provenance": "frozen_initial",
        "source_path_scope": "retained_v002_private_root",
        "source_identity": v004.asdict(source_identity),
        "source_byte_count": len(source_raw),
        "source_sha256": sha256_bytes(source_raw),
        "copied_input_identity": v004.asdict(copied_identity),
        "copied_input_byte_count": evidence_receipt["bytes"],
        "copied_input_sha256": evidence_receipt["sha256"],
        "parser_input_identity": v004.asdict(parser_identity),
        "parser_input_byte_count": parser_receipt["bytes"],
        "parser_input_sha256": parser_receipt["sha256"],
        "source_equals_copy": True,
        "copy_equals_parser": True,
        "atom_order_sha256": element_digest,
        "atom_order_preserved": True,
        "charge": CHARGES[endpoint],
        "multiplicity": MULTIPLICITIES[endpoint],
        "spin": SPINS[endpoint],
        "atom_count": ATOM_COUNTS[endpoint],
        "electron_count": ELECTRON_COUNT,
    }
    return parser_raw, geometry, receipt


def read_bound_json(
    *, v004: Any, root: Path, relative_path: str, expected_sha256: str
) -> tuple[bytes, dict[str, object]]:
    raw, _ = v004.read_regular_file(root / relative_path)
    if sha256_bytes(raw) != expected_sha256:
        raise DirectComparisonError(f"bound evidence identity drifted: {relative_path}")
    return raw, strict_json(raw, label=relative_path)


def load_assisted_reference(*, v004: Any, v004_root: Path) -> dict[str, object]:
    result_raw, result = read_bound_json(
        v004=v004,
        root=v004_root,
        relative_path="result.json",
        expected_sha256=V004_RESULT_SHA256,
    )
    if (
        result.get("final_outcome") != "PASS"
        or result.get("handoff_status") != "PASS"
        or result.get("science_pilot_only") is not True
        or result.get("production_accepted") is not False
    ):
        raise DirectComparisonError("v004 assisted terminal is not the frozen PASS")
    endpoint_payloads: dict[str, dict[str, object]] = {}
    run_configs: dict[str, dict[str, object]] = {}
    evidence: dict[str, object] = {
        "result": {"bytes": len(result_raw), "sha256": sha256_bytes(result_raw)},
        "endpoints": {},
    }
    for endpoint in ENDPOINTS:
        endpoint_raw, endpoint_payload = read_bound_json(
            v004=v004,
            root=v004_root,
            relative_path=f"pyscf/{endpoint}/endpoint_result.json",
            expected_sha256=V004_ENDPOINT_SHA256[endpoint],
        )
        run_raw, run_config = read_bound_json(
            v004=v004,
            root=v004_root,
            relative_path=f"pyscf/{endpoint}/run_config.json",
            expected_sha256=V004_RUN_CONFIG_SHA256[endpoint],
        )
        input_raw, _ = v004.read_regular_file(v004_root / "pyscf" / endpoint / "input.xyz")
        if sha256_bytes(input_raw) != ASSISTED_INPUT_SHA256[endpoint]:
            raise DirectComparisonError(f"v004 {endpoint} assisted input identity drifted")
        expected = EXPECTED_ASSISTED[endpoint]
        if (
            endpoint_payload.get("status") != "success"
            or endpoint_payload.get("scf_converged") is not True
            or endpoint_payload.get("selected_strategy") != "standard"
            or endpoint_payload.get("energy_hartree") != expected["energy_hartree"]
            or endpoint_payload.get("scf_cycles") != expected["scf_cycles"]
            or endpoint_payload.get("wall_seconds") != expected["wall_seconds"]
            or endpoint_payload.get("charge") != CHARGES[endpoint]
            or endpoint_payload.get("multiplicity") != MULTIPLICITIES[endpoint]
            or endpoint_payload.get("spin") != SPINS[endpoint]
        ):
            raise DirectComparisonError(f"v004 {endpoint} assisted endpoint drifted")
        interpreter = endpoint_payload.get("interpreter")
        if not isinstance(interpreter, dict) or interpreter.get("python_version") != "3.11.15":
            raise DirectComparisonError(f"v004 {endpoint} interpreter evidence is invalid")
        before = interpreter.get("before")
        after = interpreter.get("after")
        if (
            not isinstance(before, dict)
            or not isinstance(after, dict)
            or before != after
            or before.get("resolved_executable_sha256") != EXPECTED_EXECUTABLE_SHA256
            or before.get("resolved_executable_bytes") != 25409784
            or before.get("resolved_inside_environment_root") is not True
        ):
            raise DirectComparisonError(f"v004 {endpoint} interpreter identity drifted")
        endpoint_payloads[endpoint] = endpoint_payload
        run_configs[endpoint] = run_config
        cast(dict[str, object], evidence["endpoints"])[endpoint] = {
            "endpoint_result": {"bytes": len(endpoint_raw), "sha256": sha256_bytes(endpoint_raw)},
            "run_config": {"bytes": len(run_raw), "sha256": sha256_bytes(run_raw)},
            "input": {"bytes": len(input_raw), "sha256": sha256_bytes(input_raw)},
        }
    deprotonation = result.get("deprotonation")
    if (
        not isinstance(deprotonation, dict)
        or deprotonation.get("value_kcal_per_mol") != EXPECTED_ASSISTED_LABEL
        or deprotonation.get("aimnet2_energy_used") is not False
    ):
        raise DirectComparisonError("v004 assisted label identity drifted")
    return {
        "result": result,
        "endpoint_payloads": endpoint_payloads,
        "run_configs": run_configs,
        "evidence": evidence,
    }


def geometry_context(
    *,
    review: Any,
    endpoint: str,
    initial_raw: bytes,
    assisted_raw: bytes,
    review_classification: str,
) -> dict[str, object]:
    initial = review.parse_xyz(initial_raw)
    assisted = review.parse_xyz(assisted_raw)
    if initial.elements != assisted.elements:
        raise DirectComparisonError(f"{endpoint} geometry element order drifted")
    initial_bonds = review.infer_connectivity(initial.elements, initial.coordinates)
    assisted_bonds = review.infer_connectivity(assisted.elements, assisted.coordinates)
    aligned, _ = review.kabsch_align(initial.coordinates, assisted.coordinates)
    displacements = review.np.linalg.norm(aligned - initial.coordinates, axis=1)
    max_index = int(review.np.argmax(displacements))
    if endpoint == "cation" and ((14, 23) not in initial_bonds or (14, 23) not in assisted_bonds):
        raise DirectComparisonError("cation H23-C14 identity drifted")
    return {
        "endpoint": endpoint,
        "initial_sha256": sha256_bytes(initial_raw),
        "assisted_sha256": sha256_bytes(assisted_raw),
        "atom_order_equal": True,
        "aligned_rmsd_angstrom": float(
            review.np.sqrt(review.np.mean(displacements * displacements))
        ),
        "maximum_aligned_displacement_angstrom": float(displacements[max_index]),
        "maximum_displacement_atom_index": max_index,
        "maximum_displacement_element": initial.elements[max_index],
        "connectivity_equal": initial_bonds == assisted_bonds,
        "added_bonds": sorted(assisted_bonds - initial_bonds),
        "removed_bonds": sorted(initial_bonds - assisted_bonds),
        "c2_n1_initial_angstrom": review.distance(initial.coordinates, 14, 8),
        "c2_n1_assisted_angstrom": review.distance(assisted.coordinates, 14, 8),
        "c2_n3_initial_angstrom": review.distance(initial.coordinates, 14, 15),
        "c2_n3_assisted_angstrom": review.distance(assisted.coordinates, 14, 15),
        "n1_c2_n3_initial_degrees": review.angle_degrees(initial.coordinates, 8, 14, 15),
        "n1_c2_n3_assisted_degrees": review.angle_degrees(assisted.coordinates, 8, 14, 15),
        "same_basin_review": review_classification,
        "single_point_energy_does_not_establish_global_minimum": True,
    }


def runtime_snapshot(*, v004: Any, runtime_root: Path) -> dict[str, dict[str, object]]:
    snapshot: dict[str, dict[str, object]] = {}
    for path in sorted(runtime_root.iterdir()):
        raw, identity = v004.read_regular_file(path)
        snapshot[path.name] = {
            "name_sha256": sha256_bytes(path.name.encode("utf-8")),
            "bytes": len(raw),
            "sha256": sha256_bytes(raw),
            "identity": v004.asdict(identity),
        }
    return snapshot


def checkpoint_diagnostic(
    *,
    v004: Any,
    runtime_root: Path,
    backend: Any,
    created_by_endpoint: dict[str, set[str]],
) -> dict[str, object]:
    configured = []
    for key, evidence in sorted(backend.initial_guess_evidence.items()):
        owners = cast(list[dict[str, object]], evidence.get("owners", []))
        configured.append(
            {
                "attempt": key,
                "chkfile_configured_before": any(
                    owner.get("chkfile_before") is True for owner in owners
                ),
                "chkfile_configured_after": any(
                    owner.get("chkfile_after") is True for owner in owners
                ),
            }
        )
    snapshot = runtime_snapshot(v004=v004, runtime_root=runtime_root)
    registered_names = set().union(*created_by_endpoint.values())
    if set(snapshot) != registered_names:
        raise DirectComparisonError("ephemeral runtime file registry does not match disk")
    observed = [snapshot[name] for name in sorted(snapshot)]
    return {
        "ephemeral_checkpoint_created": all(
            bool(created_by_endpoint.get(endpoint)) for endpoint in ENDPOINTS
        ),
        "ephemeral_checkpoint_expected_to_disappear": True,
        "post_exit_audit_required": True,
        "configured_attempts": configured,
        "created_by_endpoint": {
            endpoint: [
                snapshot[name]["name_sha256"] for name in sorted(created_by_endpoint[endpoint])
            ]
            for endpoint in ENDPOINTS
        },
        "files_observed_before_exit": observed,
        "durable_manifest_includes_checkpoint": False,
    }


def durable_manifest(
    *, v004: Any, root: Path, required_paths: set[str] | None
) -> dict[str, object]:
    files: list[dict[str, object]] = []
    observed_paths: set[str] = set()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        observed = path.lstat()
        if relative == "driver" or relative.startswith("driver/"):
            continue
        if stat.S_ISLNK(observed.st_mode):
            raise DirectComparisonError(f"durable evidence contains symlink: {relative}")
        if stat.S_ISDIR(observed.st_mode):
            continue
        if not stat.S_ISREG(observed.st_mode):
            raise DirectComparisonError(f"durable evidence contains special file: {relative}")
        if relative == "file_manifest.json":
            continue
        raw, identity = v004.read_regular_file(path)
        observed_paths.add(relative)
        files.append(
            {
                "relative_path": relative,
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
                "mode": identity.mode,
                "link_count": identity.link_count,
            }
        )
    if required_paths is not None and observed_paths != required_paths:
        raise DirectComparisonError("durable evidence exact path set mismatch")
    return {
        "schema_version": "nhc-phase9b-science-pilot-durable-manifest-v005",
        "science_pilot_only": True,
        "candidate": CANDIDATE,
        "scope": "durable_preterminal_files_driver_and_ephemeral_runtime_excluded",
        "terminal_binding": "result_written_last_and_binds_this_manifest",
        "ephemeral_runtime_files_included": False,
        "files": files,
    }


def audit_post_exit_evidence(*, v004: Any, root: Path) -> dict[str, object]:
    manifest_raw, _ = v004.read_regular_file(root / "file_manifest.json")
    manifest = strict_json(manifest_raw, label="file_manifest.json")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise DirectComparisonError("post-exit manifest has no file list")
    listed: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise DirectComparisonError("post-exit manifest entry is invalid")
        relative = entry.get("relative_path")
        expected_bytes = entry.get("bytes")
        expected_sha256 = entry.get("sha256")
        if (
            not isinstance(relative, str)
            or relative in listed
            or relative.startswith("/")
            or relative.startswith("driver/")
            or any(part in {"", ".", ".."} for part in Path(relative).parts)
        ):
            raise DirectComparisonError("post-exit manifest path is invalid")
        raw, _ = v004.read_regular_file(root / relative)
        if len(raw) != expected_bytes or sha256_bytes(raw) != expected_sha256:
            raise DirectComparisonError(f"post-exit evidence drifted: {relative}")
        listed.add(relative)
    result_raw, _ = v004.read_regular_file(root / "result.json")
    result = strict_json(result_raw, label="result.json")
    bindings = result.get("evidence_bindings")
    if (
        not isinstance(bindings, dict)
        or bindings.get("durable_preterminal_manifest_sha256") != sha256_bytes(manifest_raw)
        or bindings.get("durable_preterminal_manifest_bytes") != len(manifest_raw)
    ):
        raise DirectComparisonError("result does not bind the durable manifest")
    actual: set[str] = set()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        observed = path.lstat()
        if relative == "driver" or relative.startswith("driver/"):
            continue
        if stat.S_ISDIR(observed.st_mode):
            continue
        if not stat.S_ISREG(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
            raise DirectComparisonError(f"post-exit durable tree is unsafe: {relative}")
        actual.add(relative)
    expected_actual = listed | {"file_manifest.json", "result.json"}
    if actual != expected_actual:
        raise DirectComparisonError("post-exit durable exact file set mismatch")
    runtime_root = root / "driver" / "runtime_tmp"
    runtime_files = sorted(path.name for path in runtime_root.iterdir())
    return {
        "schema_version": "nhc-phase9b-science-pilot-post-exit-audit-v005",
        "science_pilot_only": True,
        "manifest_sha256": sha256_bytes(manifest_raw),
        "manifest_bytes": len(manifest_raw),
        "result_sha256": sha256_bytes(result_raw),
        "result_bytes": len(result_raw),
        "durable_file_count": len(actual),
        "ephemeral_runtime_file_count_after_exit": len(runtime_files),
        "full_manifest_post_exit_stable": not runtime_files,
    }


def execute(args: argparse.Namespace) -> int:
    started = time.monotonic()
    deadline = started + WALL_LIMIT_SECONDS
    root_path = Path(args.root)
    v002_path = Path(args.v002_root)
    v004_path = Path(args.v004_root)
    source_path = Path(args.source_root)
    continuation_path = (
        root_path / "driver" / "scripts" / "phase9b_science_pilot_pyscf_continuation.py"
    )
    direct_source_path = Path(__file__)
    direct_raw = bootstrap_read(direct_source_path)
    if sha256_bytes(direct_raw) != args.direct_source_sha256:
        raise DirectComparisonError("direct driver source identity drifted")
    v004 = load_exact_module(
        continuation_path,
        module_name="phase9b_science_pilot_v004_shared_single_point",
        expected_sha256=V004_CONTINUATION_SHA256,
    )
    root = v004.resolve_safe_directory(root_path, label="direct v005 root")
    v002_root = v004.resolve_safe_directory(v002_path, label="retained v002 root")
    v004_root = v004.resolve_safe_directory(v004_path, label="retained v004 root")
    source_root = v004.resolve_safe_directory(source_path, label="deployed source root")
    if (
        root.name != ROOT_NAME
        or v002_root.name != V002_ROOT_NAME
        or v004_root.name != V004_ROOT_NAME
        or root.parent != v002_root.parent
        or root.parent != v004_root.parent
        or source_root != root / "driver" / "src"
    ):
        raise DirectComparisonError("science-pilot root identity drifted")
    if direct_source_path != root / "driver" / "scripts" / direct_source_path.name:
        raise DirectComparisonError("direct driver was not launched from its deployed regular file")
    runtime_root = root / "driver" / "runtime_tmp"
    v004.make_directory(runtime_root)
    os.environ["TMPDIR"] = str(runtime_root)
    tempfile.tempdir = None
    if Path(tempfile.gettempdir()) != runtime_root:
        raise DirectComparisonError("temporary runtime root did not bind before chemistry imports")
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        raise DirectComparisonError("source commit is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_executable_sha256):
        raise DirectComparisonError("expected interpreter identity is invalid")
    if args.expected_executable_sha256 != EXPECTED_EXECUTABLE_SHA256:
        raise DirectComparisonError("expected interpreter is not the frozen v004 executable")
    if os.path.lexists(root / "result.json"):
        raise DirectComparisonError("v005 terminal already exists")
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        os.environ.pop(name, None)
    if sys.version_info[:3] != (3, 11, 15):
        raise DirectComparisonError("science-pilot requires Python 3.11.15")
    interpreter_before = v004.capture_interpreter(
        Path(sys.executable), expected_executable_sha256=args.expected_executable_sha256
    )
    if interpreter_before.get("resolved_executable_sha256") != EXPECTED_EXECUTABLE_SHA256:
        raise DirectComparisonError("runtime interpreter is not the frozen v004 executable")

    helper_path = root / "driver" / "scripts" / "phase9b_science_pilot.py"
    two_endpoint_path = source_root / "nhc_deprot_ranker" / "quantum" / "two_endpoint.py"
    helper_raw, helper_identity = v004.read_regular_file(helper_path)
    two_raw, two_identity = v004.read_regular_file(two_endpoint_path)
    if sha256_bytes(helper_raw) != HELPER_SOURCE_SHA256:
        raise DirectComparisonError("science-pilot helper identity drifted")
    if sha256_bytes(two_raw) != TWO_ENDPOINT_SOURCE_SHA256:
        raise DirectComparisonError("two-endpoint identity drifted")
    pilot = v004.load_pilot_helpers(helper_path)
    pilot._add_source_root(source_root)
    from nhc_deprot_ranker.quantum import two_endpoint

    if Path(two_endpoint.__file__).resolve(strict=True) != two_endpoint_path:
        raise DirectComparisonError("two-endpoint imported from another source root")
    helper_after, helper_identity_after = v004.read_regular_file(helper_path)
    two_after, two_identity_after = v004.read_regular_file(two_endpoint_path)
    if helper_raw != helper_after or helper_identity != helper_identity_after:
        raise DirectComparisonError("helper drifted across import")
    if two_raw != two_after or two_identity != two_identity_after:
        raise DirectComparisonError("two-endpoint drifted across import")
    for name, value in two_endpoint.THREAD_ENVIRONMENT.items():
        os.environ[name] = value
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    set_affinity = getattr(os, "sched_setaffinity", None)
    get_affinity = getattr(os, "sched_getaffinity", None)
    if not callable(set_affinity) or not callable(get_affinity):
        raise DirectComparisonError("Linux affinity API is unavailable")
    set_affinity(0, {0, 1, 2, 3})
    if set(get_affinity(0)) != {0, 1, 2, 3}:
        raise DirectComparisonError("CPU affinity did not retain cores 0-3")

    v002_result_raw, _ = v004.read_regular_file(v002_root / "result.json")
    if sha256_bytes(v002_result_raw) != V002_RESULT_SHA256:
        raise DirectComparisonError("v002 terminal identity drifted")
    assisted = load_assisted_reference(v004=v004, v004_root=v004_root)
    if {
        "pyscf": metadata.version("pyscf"),
        "geometric": metadata.version("geometric"),
        "pyscf_dispersion": metadata.version("pyscf-dispersion"),
    } != {"pyscf": "2.13.1", "geometric": "1.1.1", "pyscf_dispersion": "1.5.0"}:
        raise DirectComparisonError("runtime package versions differ from v004")
    assisted_endpoint_payloads = cast(dict[str, dict[str, object]], assisted["endpoint_payloads"])
    for endpoint in ENDPOINTS:
        frozen_interpreter = cast(
            dict[str, object],
            cast(dict[str, object], assisted_endpoint_payloads[endpoint]["interpreter"])["before"],
        )
        if interpreter_projection(interpreter_before) != interpreter_projection(frozen_interpreter):
            raise DirectComparisonError(f"{endpoint} interpreter differs from v004")

    review_source = root / "driver" / "scripts" / "phase9b_science_pilot_geometry_review.py"
    review_source_raw = bootstrap_read(review_source)
    if sha256_bytes(review_source_raw) != GEOMETRY_REVIEW_SOURCE_SHA256:
        raise DirectComparisonError("geometry review source identity drifted")
    review = load_exact_module(
        review_source,
        module_name="phase9b_science_pilot_v005_geometry_context",
        expected_sha256=GEOMETRY_REVIEW_SOURCE_SHA256,
    )
    review_raw, review_payload = read_bound_json(
        v004=v004,
        root=v002_root,
        relative_path="review_v004/review_result.json",
        expected_sha256=REVIEW_RESULT_SHA256,
    )
    if review_payload.get("classification") != "SAME_BASIN_LIKELY":
        raise DirectComparisonError("neutral corrected review identity drifted")
    assisted_geometry_raw: dict[str, bytes] = {}
    aimnet_result_raw: dict[str, bytes] = {}
    basin_classification: dict[str, str] = {}
    for endpoint in ENDPOINTS:
        assisted_raw, _ = v004.read_regular_file(v002_root / "aimnet2" / endpoint / "final.xyz")
        if sha256_bytes(assisted_raw) != ASSISTED_INPUT_SHA256[endpoint]:
            raise DirectComparisonError(f"{endpoint} assisted geometry identity drifted")
        result_raw, result_payload = read_bound_json(
            v004=v004,
            root=v002_root,
            relative_path=f"aimnet2/{endpoint}/result.json",
            expected_sha256=V002_AIMNET_RESULT_SHA256[endpoint],
        )
        if endpoint == "cation":
            structure = result_payload.get("structure")
            if not isinstance(structure, dict) or structure.get("all_gates_passed") is not True:
                raise DirectComparisonError("cation structural gate identity drifted")
            basin_classification[endpoint] = "v002_frozen_structure_gates_passed"
        else:
            basin_classification[endpoint] = "SAME_BASIN_LIKELY"
        assisted_geometry_raw[endpoint] = assisted_raw
        aimnet_result_raw[endpoint] = result_raw

    for directory in ("input", "handoff", "pyscf", "comparison"):
        v004.make_directory(root / directory)
    for endpoint in ENDPOINTS:
        v004.make_directory(root / "pyscf" / endpoint)

    handoffs: dict[str, dict[str, object]] = {}
    direct_raw_inputs: dict[str, bytes] = {}
    input_manifest: dict[str, object] = {
        "schema_version": "nhc-phase9b-science-pilot-direct-input-manifest-v005",
        "science_pilot_only": True,
        "candidate": CANDIDATE,
        "geometry_provenance": "frozen_initial",
        "endpoints": {},
    }
    for endpoint in ENDPOINTS:
        raw, geometry, handoff = validate_and_copy_input(
            v004=v004,
            two_endpoint=two_endpoint,
            endpoint=endpoint,
            source=v002_root / "input" / f"{endpoint}_initial.xyz",
            evidence_copy=root / "input" / f"{endpoint}_initial.xyz",
            parser_input=root / "pyscf" / endpoint / "input.xyz",
        )
        handoff_receipt = v004.write_json_new(
            root / "handoff" / f"{endpoint}_handoff.json", handoff
        )
        handoffs[endpoint] = {
            "payload": handoff,
            "receipt_sha256": handoff_receipt["sha256"],
            "receipt_bytes": handoff_receipt["bytes"],
        }
        direct_raw_inputs[endpoint] = raw
        del geometry
        cast(dict[str, object], input_manifest["endpoints"])[endpoint] = {
            "source_sha256": DIRECT_SHA256[endpoint],
            "source_bytes": DIRECT_BYTES[endpoint],
            "parser_sha256": sha256_bytes(raw),
            "parser_bytes": len(raw),
            "atom_order_sha256": ATOM_ORDER_SHA256[endpoint],
            "charge": CHARGES[endpoint],
            "multiplicity": MULTIPLICITIES[endpoint],
            "spin": SPINS[endpoint],
            "handoff_receipt_sha256": handoff_receipt["sha256"],
        }
    v004.write_json_new(root / "input" / "input_manifest.json", input_manifest)

    geometry_endpoints: dict[str, object] = {}
    for endpoint in ENDPOINTS:
        context = geometry_context(
            review=review,
            endpoint=endpoint,
            initial_raw=direct_raw_inputs[endpoint],
            assisted_raw=assisted_geometry_raw[endpoint],
            review_classification=basin_classification[endpoint],
        )
        context["aimnet2_result_sha256"] = sha256_bytes(aimnet_result_raw[endpoint])
        geometry_endpoints[endpoint] = context

    direct_run_configs: dict[str, dict[str, object]] = {}
    for endpoint in ENDPOINTS:
        reference_config = cast(dict[str, dict[str, object]], assisted["run_configs"])[endpoint]
        direct_config = {
            **reference_config,
            "schema_version": "nhc-phase9b-science-pilot-direct-run-config-v005",
            "deadline_monotonic": deadline,
            "handoff_sha256": handoffs[endpoint]["receipt_sha256"],
            "geometry_provenance": "frozen_initial",
            "comparison_reference": "v004_aimnet2_preoptimized",
            "internal_wall_limit_seconds": WALL_LIMIT_SECONDS,
        }
        compare_protocol(direct=direct_config, assisted=reference_config, endpoint=endpoint)
        direct_run_configs[endpoint] = direct_config
        v004.write_json_new(root / "pyscf" / endpoint / "run_config.json", direct_config)

    pre_scf_paths = {
        "input/cation_initial.xyz",
        "input/neutral_initial.xyz",
        "input/input_manifest.json",
        "handoff/cation_handoff.json",
        "handoff/neutral_handoff.json",
        "pyscf/cation/input.xyz",
        "pyscf/cation/run_config.json",
        "pyscf/neutral/input.xyz",
        "pyscf/neutral/run_config.json",
    }
    durable_manifest(v004=v004, root=root, required_paths=pre_scf_paths)

    backend = v004.build_observed_backend(pilot=pilot, module=two_endpoint)
    direct_endpoints: dict[str, dict[str, object]] = {}
    endpoint_receipts: dict[str, dict[str, object]] = {}
    energies: dict[str, float] = {}
    checkpoint_files: dict[str, set[str]] = {endpoint: set() for endpoint in ENDPOINTS}
    active_endpoint = "cation"
    try:
        for endpoint in ENDPOINTS:
            active_endpoint = endpoint
            validate_endpoint_start(endpoint=endpoint, completed=tuple(direct_endpoints))
            endpoint_root = root / "pyscf" / endpoint
            parser_raw, _ = v004.read_regular_file(endpoint_root / "input.xyz")
            if parser_raw != direct_raw_inputs[endpoint]:
                raise DirectHandoffError(f"{endpoint} parser input drifted before SCF")
            try:
                parser_geometry = two_endpoint._parse_xyz(
                    parser_raw, label=f"science pilot v005 {endpoint} immediate parser input"
                )
            except two_endpoint.RequestValidationError as exc:
                raise DirectHandoffError(
                    f"{endpoint} parser input became invalid before SCF"
                ) from exc
            request = two_endpoint.EndpointRequest(
                name=cast(Any, endpoint),
                xyz_relative_path=f"pyscf/{endpoint}/input.xyz",
                xyz_path=endpoint_root / "input.xyz",
                xyz_sha256=sha256_bytes(parser_raw),
                charge=CHARGES[endpoint],
                multiplicity=MULTIPLICITIES[endpoint],
                electron_count=ELECTRON_COUNT,
                geometry=parser_geometry,
            )
            runtime_before = set(runtime_snapshot(v004=v004, runtime_root=runtime_root))
            before_cpu = resource.getrusage(resource.RUSAGE_SELF)
            endpoint_started = time.monotonic()
            with (
                pilot._capture_fds(endpoint_root / "stdout", endpoint_root / "stderr"),
                pilot._working_directory(endpoint_root),
            ):
                result, strategy, attempts = v004.run_single_point(
                    module=two_endpoint,
                    backend=backend,
                    endpoint=request,
                    deadline=deadline,
                )
            wall_seconds = time.monotonic() - endpoint_started
            runtime_after = set(runtime_snapshot(v004=v004, runtime_root=runtime_root))
            checkpoint_files[endpoint] = runtime_after - runtime_before
            if not checkpoint_files[endpoint]:
                raise DirectComparisonError(
                    f"{endpoint} did not create a registered ephemeral checkpoint"
                )
            after_cpu = resource.getrusage(resource.RUSAGE_SELF)
            stdout_raw, _ = v004.read_regular_file(endpoint_root / "stdout")
            stderr_raw, _ = v004.read_regular_file(endpoint_root / "stderr")
            metrics = cast(dict[str, object], backend.pilot_metrics.get(endpoint, {}))
            guess_evidence = {
                key: value
                for key, value in backend.initial_guess_evidence.items()
                if key.startswith(f"{endpoint}:")
            }
            v004.validate_initial_guess_evidence(
                endpoint=endpoint,
                selected_strategy=strategy,
                evidence=guess_evidence,
            )
            interpreter_after = v004.capture_interpreter(
                Path(sys.executable),
                expected_executable_sha256=args.expected_executable_sha256,
            )
            if interpreter_after != interpreter_before:
                raise DirectComparisonError(f"{endpoint} interpreter identity drifted")
            if result.converged is not True or not math.isfinite(result.energy_hartree):
                raise ScientificResultError(f"{endpoint} did not produce a finite converged energy")
            payload = {
                "schema_version": "nhc-phase9b-science-pilot-direct-endpoint-result-v005",
                "shared_science_result_schema": "nhc-phase9b-science-pilot-endpoint-result-v004",
                "science_pilot_only": True,
                "candidate": CANDIDATE,
                "endpoint": endpoint,
                "geometry_provenance": "frozen_initial",
                "status": "success",
                "interpreter": {
                    "before": interpreter_before,
                    "after": interpreter_after,
                    "python_version": sys.version.split()[0],
                },
                "versions": {
                    "pyscf": metadata.version("pyscf"),
                    "geometric": metadata.version("geometric"),
                    "pyscf_dispersion": metadata.version("pyscf-dispersion"),
                },
                "method": "B3LYP",
                "basis": "def2-SVP",
                "grid_level": 3,
                "charge": CHARGES[endpoint],
                "multiplicity": MULTIPLICITIES[endpoint],
                "spin": SPINS[endpoint],
                "atom_count": ATOM_COUNTS[endpoint],
                "electron_count": ELECTRON_COUNT,
                "threads": 4,
                "max_memory_mb": 12000,
                "scf_tolerance": 1.0e-9,
                "standard_max_cycles": 100,
                "soscf_max_cycles": 200,
                "initial_guess_evidence": guess_evidence,
                "selected_strategy": strategy,
                "attempts": attempts,
                "scf_converged": result.converged,
                "scf_cycles": metrics.get("final_scf_cycles", "unavailable"),
                "energy_hartree": result.energy_hartree,
                "d3": two_endpoint._final_dispersion_payload(result.dispersion),
                "d3_audit_protocol": {
                    "xc": "B3LYP",
                    "version": "d3bj",
                    "atm": False,
                    "grad": True,
                },
                "runtime": two_endpoint._runtime_evidence_payload(result.runtime),
                "wall_seconds": wall_seconds,
                "process_user_cpu_seconds": after_cpu.ru_utime - before_cpu.ru_utime,
                "process_system_cpu_seconds": after_cpu.ru_stime - before_cpu.ru_stime,
                "handoff": handoffs[endpoint],
                "stdout": {"bytes": len(stdout_raw), "sha256": sha256_bytes(stdout_raw)},
                "stderr": {"bytes": len(stderr_raw), "sha256": sha256_bytes(stderr_raw)},
                "warnings": "captured_in_raw_stderr",
                "shared_single_point_source_sha256": V004_CONTINUATION_SHA256,
                "direct_wrapper_source_sha256": args.direct_source_sha256,
            }
            endpoint_receipts[endpoint] = v004.write_json_new(
                endpoint_root / "endpoint_result.json", payload
            )
            direct_endpoints[endpoint] = payload
            energies[endpoint] = result.energy_hartree
    except BaseException as exc:
        traceback.print_exc()
        outcome = classify_runtime_failure(v004=v004, two_endpoint=two_endpoint, exc=exc)
        endpoint_root = root / "pyscf" / active_endpoint
        failure_payload = {
            "schema_version": "nhc-phase9b-science-pilot-direct-endpoint-result-v005",
            "shared_science_result_schema": "nhc-phase9b-science-pilot-endpoint-result-v004",
            "science_pilot_only": True,
            "candidate": CANDIDATE,
            "endpoint": active_endpoint,
            "geometry_provenance": "frozen_initial",
            "status": "failed",
            "failure": {"exception_class": type(exc).__name__, "message": str(exc)[:1000]},
            "handoff": handoffs.get(active_endpoint),
            "initial_guess_evidence": {
                key: value
                for key, value in backend.initial_guess_evidence.items()
                if key.startswith(f"{active_endpoint}:")
            },
        }
        failure_path = endpoint_root / "endpoint_result.json"
        if not os.path.lexists(failure_path):
            v004.write_json_new(failure_path, failure_payload)
        direct_endpoints[active_endpoint] = failure_payload
        terminal = {
            "schema_version": SCHEMA_VERSION,
            "science_pilot_only": True,
            **HISTORICAL_AND_SCOPE_FLAGS,
            "candidate": CANDIDATE,
            "direct_endpoints": direct_endpoints,
            "direct_deprotonation": None,
            "comparison": None,
            "final_outcome": outcome,
            "failure": {
                "stage": f"direct_pyscf_{active_endpoint}",
                "exception_class": type(exc).__name__,
                "message": str(exc)[:1000],
            },
        }
        v004.write_json_new(root / "result.json", terminal)
        v004.write_json_new(
            root / "file_manifest.json",
            durable_manifest(v004=v004, root=root, required_paths=None),
        )
        raise

    v002_result_after, _ = v004.read_regular_file(v002_root / "result.json")
    if v002_result_after != v002_result_raw:
        raise DirectComparisonError("v002 terminal drifted during direct comparison")
    if load_assisted_reference(v004=v004, v004_root=v004_root) != assisted:
        raise DirectComparisonError("v004 assisted evidence drifted during direct comparison")
    if bootstrap_read(review_source) != review_source_raw:
        raise DirectComparisonError("geometry review source drifted during direct comparison")
    review_after, _ = v004.read_regular_file(v002_root / "review_v004" / "review_result.json")
    if review_after != review_raw:
        raise DirectComparisonError("geometry review result drifted during direct comparison")
    for endpoint in ENDPOINTS:
        direct_after, _ = v004.read_regular_file(v002_root / "input" / f"{endpoint}_initial.xyz")
        assisted_after, _ = v004.read_regular_file(v002_root / "aimnet2" / endpoint / "final.xyz")
        aimnet_after, _ = v004.read_regular_file(v002_root / "aimnet2" / endpoint / "result.json")
        if direct_after != direct_raw_inputs[endpoint]:
            raise DirectComparisonError(f"{endpoint} frozen input drifted during comparison")
        if assisted_after != assisted_geometry_raw[endpoint]:
            raise DirectComparisonError(f"{endpoint} assisted input drifted during comparison")
        if aimnet_after != aimnet_result_raw[endpoint]:
            raise DirectComparisonError(f"{endpoint} AIMNet2 result drifted during comparison")

    if tuple(direct_endpoints) != ENDPOINTS or set(energies) != set(ENDPOINTS):
        raise DirectComparisonError("both direct endpoints are required before label calculation")
    direct_deprotonation = v004.compute_deprotonation(energies["cation"], energies["neutral"])
    assisted_endpoints = cast(dict[str, dict[str, object]], assisted["endpoint_payloads"])
    assisted_deprotonation = cast(
        dict[str, object], cast(dict[str, object], assisted["result"])["deprotonation"]
    )
    assisted_label = float(cast(float, assisted_deprotonation["value_kcal_per_mol"]))
    endpoint_comparison, label_comparison = calculate_comparison(
        direct_endpoints=direct_endpoints,
        assisted_endpoints=assisted_endpoints,
        direct_label=float(cast(float, direct_deprotonation["value_kcal_per_mol"])),
        assisted_label=assisted_label,
    )
    comparison_receipts: dict[str, dict[str, object]] = {}
    comparison_receipts["assisted_result_binding"] = v004.write_json_new(
        root / "comparison" / "assisted_result_binding.json",
        {
            "schema_version": "nhc-phase9b-science-pilot-assisted-binding-v005",
            "science_pilot_only": True,
            "candidate": CANDIDATE,
            "geometry_provenance": "aimnet2_preoptimized",
            "v004_terminal": "PASS",
            "v004_evidence": assisted["evidence"],
            "v004_result": assisted["result"],
            "v004_evidence_unchanged": True,
            "v004_manifest_post_exit_stable": False,
            "v004_manifest_caveat": "two_ephemeral_checkpoints_were_listed_as_durable",
            "production_accepted": False,
        },
    )
    comparison_receipts["endpoint_comparison"] = v004.write_json_new(
        root / "comparison" / "endpoint_comparison.json",
        {
            "schema_version": "nhc-phase9b-science-pilot-endpoint-comparison-v005",
            "science_pilot_only": True,
            "production_accepted": False,
            "candidate": CANDIDATE,
            "direction": "assisted_minus_direct",
            "endpoints": endpoint_comparison,
        },
    )
    comparison_receipts["label_comparison"] = v004.write_json_new(
        root / "comparison" / "label_comparison.json",
        {
            "schema_version": "nhc-phase9b-science-pilot-label-comparison-v005",
            "science_pilot_only": True,
            "production_accepted": False,
            "candidate": CANDIDATE,
            "direction": "assisted_minus_direct",
            **label_comparison,
        },
    )

    comparison_receipts["geometry_context"] = v004.write_json_new(
        root / "comparison" / "geometry_context.json",
        {
            "schema_version": "nhc-phase9b-science-pilot-geometry-context-v005",
            "science_pilot_only": True,
            "production_accepted": False,
            "candidate": CANDIDATE,
            "review_result": {"bytes": len(review_raw), "sha256": sha256_bytes(review_raw)},
            "endpoints": geometry_endpoints,
        },
    )

    checkpoints = checkpoint_diagnostic(
        v004=v004,
        runtime_root=runtime_root,
        backend=backend,
        created_by_endpoint=checkpoint_files,
    )
    required_paths = {
        "input/cation_initial.xyz",
        "input/neutral_initial.xyz",
        "input/input_manifest.json",
        "handoff/cation_handoff.json",
        "handoff/neutral_handoff.json",
        "pyscf/cation/input.xyz",
        "pyscf/cation/run_config.json",
        "pyscf/cation/stdout",
        "pyscf/cation/stderr",
        "pyscf/cation/endpoint_result.json",
        "pyscf/neutral/input.xyz",
        "pyscf/neutral/run_config.json",
        "pyscf/neutral/stdout",
        "pyscf/neutral/stderr",
        "pyscf/neutral/endpoint_result.json",
        "comparison/assisted_result_binding.json",
        "comparison/endpoint_comparison.json",
        "comparison/label_comparison.json",
        "comparison/geometry_context.json",
    }
    manifest_receipt = v004.write_json_new(
        root / "file_manifest.json",
        durable_manifest(v004=v004, root=root, required_paths=required_paths),
    )
    result_payload = {
        "schema_version": SCHEMA_VERSION,
        "science_pilot_only": True,
        **HISTORICAL_AND_SCOPE_FLAGS,
        "v002_unchanged_scope": "frozen result/input/final bytes and terminal",
        "candidate": CANDIDATE,
        "source_commit": args.source_commit,
        "direct_wrapper_source_sha256": args.direct_source_sha256,
        "shared_single_point_source_sha256": V004_CONTINUATION_SHA256,
        "direct_endpoints": {
            endpoint: {
                "status": "success",
                "charge": CHARGES[endpoint],
                "multiplicity": MULTIPLICITIES[endpoint],
                "spin": SPINS[endpoint],
                "scf_cycles": direct_endpoints[endpoint]["scf_cycles"],
                "wall_seconds": direct_endpoints[endpoint]["wall_seconds"],
                "energy_hartree": direct_endpoints[endpoint]["energy_hartree"],
            }
            for endpoint in ENDPOINTS
        },
        "direct_deprotonation": direct_deprotonation,
        "assisted_reference": {
            "result_sha256": V004_RESULT_SHA256,
            "deprotonation_kcal_per_mol": assisted_label,
        },
        "comparison": {
            "endpoint_comparison": endpoint_comparison,
            "label_comparison": label_comparison,
        },
        "evidence_bindings": {
            "handoff_receipts": {
                endpoint: handoffs[endpoint]["receipt_sha256"] for endpoint in ENDPOINTS
            },
            "endpoint_result_receipts": {
                endpoint: endpoint_receipts[endpoint]["sha256"] for endpoint in ENDPOINTS
            },
            "comparison_receipts": {
                name: receipt["sha256"] for name, receipt in comparison_receipts.items()
            },
            "durable_preterminal_manifest_sha256": manifest_receipt["sha256"],
            "durable_preterminal_manifest_bytes": manifest_receipt["bytes"],
        },
        "ephemeral_runtime": checkpoints,
        "post_exit_manifest_audit_status": "pending_external_read_only_post_exit_audit",
        "internal_wall_limit_seconds": WALL_LIMIT_SECONDS,
        "outer_term_limit_seconds": 7190,
        "outer_kill_grace_seconds": 10,
        "total_wall_seconds": time.monotonic() - started,
        "final_outcome": "PASS",
        "failure": None,
    }
    v004.write_json_new(root / "result.json", result_payload)
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--root", required=True)
    value.add_argument("--v002-root", required=True)
    value.add_argument("--v004-root", required=True)
    value.add_argument("--source-root", required=True)
    value.add_argument("--source-commit", required=True)
    value.add_argument("--direct-source-sha256", required=True)
    value.add_argument("--expected-executable-sha256", required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        return execute(args)
    except BaseException as exc:
        traceback.print_exc()
        root = Path(args.root)
        try:
            observed = root.lstat()
            if stat.S_ISDIR(observed.st_mode) and not root.is_symlink():
                continuation_path = (
                    root / "driver" / "scripts" / "phase9b_science_pilot_pyscf_continuation.py"
                )
                v004 = load_exact_module(
                    continuation_path,
                    module_name="phase9b_science_pilot_v005_failure_writer",
                    expected_sha256=V004_CONTINUATION_SHA256,
                )
                result_path = root / "result.json"
                if not os.path.lexists(result_path):
                    v004.write_json_new(
                        result_path,
                        {
                            "schema_version": SCHEMA_VERSION,
                            "science_pilot_only": True,
                            **HISTORICAL_AND_SCOPE_FLAGS,
                            "candidate": CANDIDATE,
                            "direct_deprotonation": None,
                            "comparison": None,
                            "final_outcome": (
                                "FAIL"
                                if isinstance(
                                    exc,
                                    (
                                        DirectHandoffError,
                                        ProtocolMismatchError,
                                        ScientificResultError,
                                    ),
                                )
                                else "INCONCLUSIVE"
                            ),
                            "failure": {
                                "stage": "setup_or_comparison",
                                "exception_class": type(exc).__name__,
                                "message": str(exc)[:1000],
                            },
                        },
                    )
                manifest_path = root / "file_manifest.json"
                if not os.path.lexists(manifest_path) and result_path.is_file():
                    v004.write_json_new(
                        manifest_path,
                        durable_manifest(v004=v004, root=root, required_paths=None),
                    )
        except BaseException:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
