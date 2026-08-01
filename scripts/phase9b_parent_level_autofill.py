#!/usr/bin/env python3
"""Bounded non-production parent-level CPU-slot auto-fill scheduler."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

SCHEMA: Final = "phase9b-parent-level-autofill-v1"
PROFILE_SCHEMA: Final = "phase9b-parent-level-autofill-queue-v1"
PARENT_PROTOCOL_SHA256: Final = "227c22a527e567bc4de873ab743fe9f493779eccbb1a698d2913c87695ebf87a"
INCHIKEY = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
ENDPOINTS: Final = (("cation", 1), ("neutral", 0))
ATOMIC_NUMBERS: Final = {
    "H": 1,
    "B": 5,
    "C": 6,
    "N": 7,
    "O": 8,
    "F": 9,
    "P": 15,
    "S": 16,
    "Cl": 17,
    "Br": 35,
    "I": 53,
}


class AutofillError(RuntimeError):
    """The bounded auto-fill contract was violated."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_regular(path: Path, *, maximum: int = 4 << 20) -> bytes:
    if not path.is_absolute():
        raise AutofillError("evidence path must be absolute")
    before = path.lstat()
    if path.is_symlink() or not path.is_file() or before.st_nlink != 1:
        raise AutofillError(f"input is not a single-link regular file: {path.name}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw = os.read(fd, maximum + 1)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if len(raw) > maximum:
        raise AutofillError("input exceeds size bound")
    if (before.st_dev, before.st_ino, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise AutofillError("input identity changed during read")
    return raw


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise AutofillError("short evidence write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    if read_regular(path, maximum=max(len(raw), 1)) != raw:
        raise AutofillError("evidence reread mismatch")


def read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = read_regular(path)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AutofillError(f"invalid JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise AutofillError(f"JSON root is not an object: {path.name}")
    return cast(dict[str, Any], value), raw


def _residual_processes(root: Path) -> list[int]:
    proc = Path("/proc")
    if not proc.is_dir():
        return []
    root_text = str(root.resolve(strict=True))
    result: list[int] = []
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            cmdline = (
                (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            )
            cwd = str((entry / "cwd").resolve(strict=True))
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        if root_text in cmdline or cwd == root_text or cwd.startswith(root_text + os.sep):
            result.append(int(entry.name))
    return sorted(result)


def _wait_for_process_cleanup(root: Path, *, maximum_seconds: float = 30.0) -> list[int]:
    deadline = time.monotonic() + maximum_seconds
    while True:
        residual = _residual_processes(root)
        if not residual or time.monotonic() >= deadline:
            return residual
        time.sleep(0.25)


def audit_successful_route(root: Path, *, expected_candidate: str | None) -> dict[str, object]:
    resolved = root.resolve(strict=True)
    exit_raw = read_regular(resolved / "controller_exit_code", maximum=32)
    try:
        exit_code = int(exit_raw.decode().strip())
    except (UnicodeDecodeError, ValueError) as exc:
        raise AutofillError("predecessor controller exit code is invalid") from exc
    if exit_code != 0:
        raise AutofillError("predecessor controller exit code is not zero")
    result, result_raw = read_json(resolved / "result.json")
    candidate = result.get("candidate")
    if not isinstance(candidate, str) or not INCHIKEY.fullmatch(candidate):
        raise AutofillError("predecessor candidate identity is invalid")
    if expected_candidate is not None and candidate != expected_candidate:
        raise AutofillError("predecessor candidate differs from lane assignment")
    if result.get("final_outcome") != "PASS":
        raise AutofillError("predecessor result is not PASS")
    if result.get("science_pilot_only") is not True:
        raise AutofillError("predecessor is not science-pilot-only")
    if result.get("production_accepted") is not False or result.get("retry") is not False:
        raise AutofillError("predecessor safety flags are invalid")
    if result.get("route") != "pure_pyscf":
        raise AutofillError("predecessor route identity is invalid")
    deprotonation = result.get("deprotonation")
    if (
        not isinstance(deprotonation, dict)
        or deprotonation.get("aimnet2_energy_used") is not False
        or isinstance(deprotonation.get("value_kcal_per_mol"), bool)
        or not isinstance(deprotonation.get("value_kcal_per_mol"), (int, float))
        or not math.isfinite(float(deprotonation["value_kcal_per_mol"]))
    ):
        raise AutofillError("predecessor deprotonation result is invalid")
    endpoint_results = result.get("endpoint_results")
    if not isinstance(endpoint_results, dict) or set(endpoint_results) != {"cation", "neutral"}:
        raise AutofillError("predecessor endpoint results are incomplete")
    endpoint_records: dict[str, dict[str, object]] = {}
    for endpoint in ("cation", "neutral"):
        endpoint_result = endpoint_results[endpoint]
        if not isinstance(endpoint_result, dict):
            raise AutofillError("predecessor endpoint result is invalid")
        geometry = endpoint_result.get("geometry_optimization")
        if (
            endpoint_result.get("candidate") != candidate
            or endpoint_result.get("endpoint") != endpoint
            or endpoint_result.get("scf_converged") is not True
            or endpoint_result.get("production_accepted") is not False
            or endpoint_result.get("retry") is not False
            or isinstance(endpoint_result.get("energy_hartree"), bool)
            or not isinstance(endpoint_result.get("energy_hartree"), (int, float))
            or not math.isfinite(float(endpoint_result["energy_hartree"]))
            or not isinstance(geometry, dict)
            or geometry.get("converged") is not True
        ):
            raise AutofillError(f"predecessor {endpoint} endpoint is incomplete")
        manifest_path = resolved / "training_data" / endpoint / "manifest.json"
        manifest, manifest_raw = read_json(manifest_path)
        if (
            manifest.get("schema") != "phase9b-parent-level-training-endpoint-v1"
            or manifest.get("candidate") != candidate
            or manifest.get("endpoint") != endpoint
            or manifest.get("complete_geometry_optimization") is not True
            or manifest.get("parent_protocol_sha256") != PARENT_PROTOCOL_SHA256
            or manifest.get("production_accepted") is not False
        ):
            raise AutofillError(f"predecessor {endpoint} manifest is invalid")
        frames = manifest.get("frames")
        if not isinstance(frames, list) or manifest.get("frame_count") != len(frames):
            raise AutofillError(f"predecessor {endpoint} frame set is invalid")
        registered_names: list[str] = []
        for index, frame in enumerate(frames):
            if not isinstance(frame, dict) or frame.get("frame_index") != index:
                raise AutofillError(f"predecessor {endpoint} frame order is invalid")
            name = str(frame.get("path"))
            if name != f"frame_{index:04d}.json":
                raise AutofillError(f"predecessor {endpoint} frame path is invalid")
            frame_raw = read_regular(manifest_path.parent / name)
            if frame.get("bytes") != len(frame_raw) or frame.get("sha256") != sha256_bytes(
                frame_raw
            ):
                raise AutofillError(f"predecessor {endpoint} frame binding is invalid")
            registered_names.append(name)
        actual_names = sorted(path.name for path in manifest_path.parent.glob("frame_*.json"))
        if actual_names != registered_names:
            raise AutofillError(f"predecessor {endpoint} frame exact set mismatch")
        endpoint_records[endpoint] = {
            "bytes": len(manifest_raw),
            "sha256": sha256_bytes(manifest_raw),
            "frame_count": len(frames),
        }
    route_manifest, route_raw = read_json(resolved / "training_data" / "manifest.json")
    if (
        route_manifest.get("schema") != "phase9b-parent-level-training-route-v1"
        or route_manifest.get("candidate") != candidate
        or route_manifest.get("parent_protocol_sha256") != PARENT_PROTOCOL_SHA256
        or route_manifest.get("production_accepted") is not False
    ):
        raise AutofillError("predecessor route manifest is invalid")
    manifest_endpoints = route_manifest.get("endpoint_manifests")
    if not isinstance(manifest_endpoints, dict) or set(manifest_endpoints) != {"cation", "neutral"}:
        raise AutofillError("predecessor route manifest endpoints are incomplete")
    for endpoint, record in endpoint_records.items():
        bound = manifest_endpoints[endpoint]
        if (
            not isinstance(bound, dict)
            or bound.get("path") != "manifest.json"
            or bound.get("endpoint") != endpoint
            or bound.get("bytes") != record["bytes"]
            or bound.get("sha256") != record["sha256"]
            or bound.get("frame_count") != record["frame_count"]
        ):
            raise AutofillError(f"predecessor {endpoint} route binding mismatch")
    result_manifest = result.get("training_data")
    if (
        not isinstance(result_manifest, dict)
        or result_manifest.get("path") != "manifest.json"
        or result_manifest.get("bytes") != len(route_raw)
        or result_manifest.get("sha256") != sha256_bytes(route_raw)
    ):
        raise AutofillError("predecessor result does not bind the route manifest")
    residual = _wait_for_process_cleanup(resolved)
    if residual:
        raise AutofillError("predecessor has residual processes")
    return {
        "schema": SCHEMA,
        "candidate": candidate,
        "root": str(resolved),
        "controller_exit_code": exit_code,
        "result_sha256": sha256_bytes(result_raw),
        "route_manifest_sha256": sha256_bytes(route_raw),
        "endpoint_manifests": endpoint_records,
        "residual_processes": [],
        "audited_monotonic_ns": time.monotonic_ns(),
        "production_accepted": False,
    }


def _parse_xyz(raw: bytes) -> tuple[tuple[str, ...], tuple[tuple[float, float, float], ...]]:
    try:
        lines = raw.decode("utf-8").splitlines()
        count = int(lines[0])
    except (UnicodeDecodeError, ValueError, IndexError) as exc:
        raise AutofillError("invalid XYZ header") from exc
    if len(lines) != count + 2:
        raise AutofillError("XYZ row count mismatch")
    elements: list[str] = []
    coordinates: list[tuple[float, float, float]] = []
    for line in lines[2:]:
        fields = line.split()
        if len(fields) != 4 or fields[0] not in ATOMIC_NUMBERS:
            raise AutofillError("invalid XYZ atom row")
        try:
            xyz = tuple(float(value) for value in fields[1:])
        except ValueError as exc:
            raise AutofillError("invalid XYZ coordinate") from exc
        if len(xyz) != 3 or not all(math.isfinite(value) for value in xyz):
            raise AutofillError("non-finite XYZ coordinate")
        elements.append(fields[0])
        coordinates.append((xyz[0], xyz[1], xyz[2]))
    minimum = min(
        math.dist(coordinates[left], coordinates[right])
        for left in range(count)
        for right in range(left)
    )
    if minimum < 0.5:
        raise AutofillError("XYZ contains a collision")
    return tuple(elements), tuple(coordinates)


def _profile_endpoint(
    *, profile: dict[str, Any], endpoint: str, charge: int, input_root: Path
) -> tuple[tuple[str, ...], tuple[tuple[float, float, float], ...], int]:
    evidence = profile[endpoint]
    path = Path(evidence["path"])
    if path.is_symlink():
        raise AutofillError(f"input is not a single-link regular file: {path.name}")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(input_root)
    except ValueError as exc:
        raise AutofillError("candidate input escaped frozen input root") from exc
    raw = read_regular(resolved)
    if sha256_bytes(raw) != evidence["sha256"]:
        raise AutofillError(f"{endpoint} SHA256 mismatch")
    elements, coordinates = _parse_xyz(raw)
    if len(elements) != evidence["atom_count"]:
        raise AutofillError(f"{endpoint} atom count mismatch")
    electrons = sum(ATOMIC_NUMBERS[element] for element in elements) - charge
    if electrons != profile["electron_count"] or electrons % 2:
        raise AutofillError(f"{endpoint} electron identity mismatch")
    return elements, coordinates, electrons


def _validate_atom_map(
    *,
    profile: dict[str, Any],
    input_root: Path,
    cation_elements: tuple[str, ...],
    cation_coordinates: tuple[tuple[float, float, float], ...],
    neutral_elements: tuple[str, ...],
) -> None:
    binding = profile.get("atom_map")
    if binding is None:
        return
    if not isinstance(binding, dict):
        raise AutofillError("atom-map binding must be an object")
    expected = {
        "path",
        "sha256",
        "c2_index",
        "n1_index",
        "n3_index",
        "acidic_hydrogen_index",
    }
    if set(binding) != expected:
        raise AutofillError("atom-map binding fields mismatch")
    path = Path(binding["path"])
    if path.is_symlink():
        raise AutofillError("atom-map input is a symlink")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(input_root)
    except ValueError as exc:
        raise AutofillError("atom-map input escaped frozen input root") from exc
    raw = read_regular(resolved)
    if sha256_bytes(raw) != binding["sha256"]:
        raise AutofillError("atom-map SHA256 mismatch")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or set(payload) != {"C2_carbene", "N1", "N3"}:
        raise AutofillError("atom-map payload fields mismatch")
    indexes = {
        "C2_carbene": binding["c2_index"],
        "N1": binding["n1_index"],
        "N3": binding["n3_index"],
    }
    if payload != indexes or not all(type(value) is int for value in indexes.values()):
        raise AutofillError("atom-map index binding mismatch")
    c2 = indexes["C2_carbene"]
    n1 = indexes["N1"]
    n3 = indexes["N3"]
    try:
        cation_identity = (cation_elements[n1], cation_elements[c2], cation_elements[n3])
        neutral_identity = (neutral_elements[n1], neutral_elements[c2], neutral_elements[n3])
    except IndexError as exc:
        raise AutofillError("atom-map index exceeds endpoint atom count") from exc
    if cation_identity != ("N", "C", "N") or neutral_identity != ("N", "C", "N"):
        raise AutofillError("atom-map reaction-centre element identity mismatch")
    acidic_hydrogen = binding["acidic_hydrogen_index"]
    if type(acidic_hydrogen) is not int or not 0 <= acidic_hydrogen < len(cation_elements):
        raise AutofillError("acidic-hydrogen index is invalid")
    if cation_elements[acidic_hydrogen] != "H":
        raise AutofillError("acidic-hydrogen index does not identify hydrogen")
    if (
        tuple(element for index, element in enumerate(cation_elements) if index != acidic_hydrogen)
        != neutral_elements
    ):
        raise AutofillError("removing bound acidic hydrogen does not reproduce neutral order")
    distance = math.dist(cation_coordinates[c2], cation_coordinates[acidic_hydrogen])
    if not 0.8 <= distance <= 1.3:
        raise AutofillError("acidic hydrogen is not bonded to frozen C2")


def load_queue(path: Path) -> dict[str, Any]:
    payload = cast(dict[str, Any], json.loads(read_regular(path)))
    if payload.get("schema") != PROFILE_SCHEMA:
        raise AutofillError("queue schema mismatch")
    if payload.get("parent_protocol_sha256") != PARENT_PROTOCOL_SHA256:
        raise AutofillError("parent protocol identity mismatch")
    input_root_path = Path(payload["input_root"])
    if input_root_path.is_symlink():
        raise AutofillError("frozen input root is invalid")
    input_root = input_root_path.resolve(strict=True)
    if not input_root.is_dir():
        raise AutofillError("frozen input root is invalid")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 8:
        raise AutofillError("queue must contain one to eight candidates")
    seen: set[str] = set()
    for profile in candidates:
        candidate = profile.get("candidate")
        if not isinstance(candidate, str) or not INCHIKEY.fullmatch(candidate):
            raise AutofillError("invalid candidate identity")
        if candidate in seen:
            raise AutofillError("duplicate candidate identity")
        seen.add(candidate)
        rigidity = profile.get("rigidity")
        if not isinstance(rigidity, dict) or rigidity.get("selection_class") != "rigid_small_nhc":
            raise AutofillError("candidate lacks rigid-small preregistration")
        if not 1 <= rigidity.get("heavy_atom_count", 0) <= 18:
            raise AutofillError("candidate exceeds heavy-atom bound")
        if not 0 <= rigidity.get("rotatable_bonds", 99) <= 3:
            raise AutofillError("candidate exceeds rotatable-bond bound")
        if rigidity.get("ring_count", 0) < 1:
            raise AutofillError("candidate is not cyclic")
        cation, cation_coordinates, _ = _profile_endpoint(
            profile=profile, endpoint="cation", charge=1, input_root=input_root
        )
        neutral, _, _ = _profile_endpoint(
            profile=profile, endpoint="neutral", charge=0, input_root=input_root
        )
        if len(cation) != len(neutral) + 1:
            raise AutofillError("endpoint atom cardinality mismatch")
        if tuple(element for element in cation if element != "H") != tuple(
            element for element in neutral if element != "H"
        ):
            raise AutofillError("endpoint heavy-element order mismatch")
        if cation.count("H") != neutral.count("H") + 1:
            raise AutofillError("cation does not contain exactly one extra hydrogen")
        _validate_atom_map(
            profile=profile,
            input_root=input_root,
            cation_elements=cation,
            cation_coordinates=cation_coordinates,
            neutral_elements=neutral,
        )
    return payload


def parse_cpu_list(value: str) -> tuple[int, ...]:
    observed: list[int] = []
    for part in value.split(","):
        if "-" in part:
            lower, upper = (int(piece) for piece in part.split("-", 1))
            observed.extend(range(lower, upper + 1))
        else:
            observed.append(int(part))
    result = tuple(sorted(set(observed)))
    if not result or any(cpu < 0 for cpu in result):
        raise AutofillError("invalid CPU list")
    return result


def _launcher_command(args: argparse.Namespace, profile: dict[str, Any]) -> list[str]:
    driver = Path(args.driver).resolve(strict=True)
    return [
        args.gpupyscf_python,
        "-I",
        "-B",
        str(Path(__file__).resolve(strict=True)),
        "launch-one",
        "--queue",
        str(Path(args.queue).resolve(strict=True)),
        "--candidate",
        profile["candidate"],
        "--output-root",
        str(Path(args.run_root) / f"autofill_{profile['candidate'].lower()}_v001"),
        "--driver",
        str(driver),
        "--gpupyscf-python",
        args.gpupyscf_python,
        "--threads",
        str(args.threads),
        "--cpu-list",
        args.cpu_list,
        "--max-memory-mb",
        str(args.max_memory_mb),
        "--route-limit-seconds",
        str(args.route_limit_seconds),
        "--record-training-frames",
        "--training-data-helper",
        str(driver / "scripts/phase9b_parent_level_training_data.py"),
    ]


def watch(args: argparse.Namespace) -> int:
    queue_path = Path(args.queue).resolve(strict=True)
    queue = load_queue(queue_path)
    state_root = Path(args.state_root)
    state_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    (state_root / "claims").mkdir(mode=0o700)
    (state_root / "assignments").mkdir(mode=0o700)
    (state_root / "audits").mkdir(mode=0o700)
    write_new(
        state_root / "queue_binding.json",
        canonical_json(
            {
                "schema": SCHEMA,
                "queue_sha256": sha256_bytes(read_regular(queue_path)),
                "queue_size": len(queue["candidates"]),
                "parent_protocol_sha256": PARENT_PROTOCOL_SHA256,
                "scheduler_source_sha256": sha256_bytes(read_regular(Path(__file__).resolve())),
                "initial_watch_root": str(Path(args.initial_watch_root).resolve(strict=True)),
                "cpu_list": list(parse_cpu_list(args.cpu_list)),
                "threads": args.threads,
                "science_pilot_only": True,
                "production_accepted": False,
            }
        ),
    )
    watched = Path(args.initial_watch_root).resolve(strict=True)
    expected_predecessor: str | None = None
    for index, profile in enumerate(queue["candidates"]):
        terminal = watched / "controller_exit_code"
        while not terminal.exists():
            time.sleep(args.poll_seconds)
        try:
            audit = audit_successful_route(watched, expected_candidate=expected_predecessor)
        except (AutofillError, OSError) as exc:
            write_new(
                state_root / "lane_terminal.json",
                canonical_json(
                    {
                        "schema": SCHEMA,
                        "outcome": "PREDECESSOR_AUDIT_FAILED",
                        "predecessor_root": str(watched),
                        "expected_candidate": expected_predecessor,
                        "next_candidate_started": False,
                        "error": str(exc),
                        "retry": False,
                        "production_accepted": False,
                    }
                ),
            )
            return 2
        audit_raw = canonical_json(audit)
        write_new(state_root / "audits" / f"{index:03d}_predecessor.json", audit_raw)
        claim = state_root / "claims" / f"{index:03d}_{profile['candidate']}.json"
        command = _launcher_command(args, profile)
        output_root = Path(command[command.index("--output-root") + 1])
        if output_root.exists():
            raise AutofillError("auto-fill output root already exists")
        write_new(
            claim,
            canonical_json(
                {
                    "schema": SCHEMA,
                    "candidate": profile["candidate"],
                    "predecessor_root": str(watched),
                    "predecessor_exit_code": 0,
                    "predecessor_audit_sha256": sha256_bytes(audit_raw),
                    "output_root": str(output_root),
                    "claim_index": index,
                    "claimed_monotonic_ns": time.monotonic_ns(),
                }
            ),
        )
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        write_new(
            state_root / "assignments" / f"{index:03d}_{profile['candidate']}.json",
            canonical_json(
                {
                    "schema": SCHEMA,
                    "candidate": profile["candidate"],
                    "launcher_pid": process.pid,
                    "output_root": str(output_root),
                    "cpu_list": list(parse_cpu_list(args.cpu_list)),
                    "threads": args.threads,
                    "command_sha256": sha256_bytes("\0".join(command).encode()),
                }
            ),
        )
        watched = output_root
        expected_predecessor = profile["candidate"]
    while not (watched / "controller_exit_code").exists():
        time.sleep(args.poll_seconds)
    try:
        final_audit = audit_successful_route(watched, expected_candidate=expected_predecessor)
    except (AutofillError, OSError) as exc:
        write_new(
            state_root / "lane_terminal.json",
            canonical_json(
                {
                    "schema": SCHEMA,
                    "outcome": "FINAL_CANDIDATE_AUDIT_FAILED",
                    "predecessor_root": str(watched),
                    "expected_candidate": expected_predecessor,
                    "queue_exhausted": False,
                    "error": str(exc),
                    "retry": False,
                    "production_accepted": False,
                }
            ),
        )
        return 2
    final_audit_raw = canonical_json(final_audit)
    write_new(
        state_root / "audits" / f"{len(queue['candidates']):03d}_final.json",
        final_audit_raw,
    )
    write_new(
        state_root / "queue_exhausted.json",
        canonical_json(
            {
                "schema": SCHEMA,
                "candidate_count": len(queue["candidates"]),
                "last_root": str(watched),
                "final_audit_sha256": sha256_bytes(final_audit_raw),
                "queue_exhausted": True,
                "retry": False,
            }
        ),
    )
    return 0


def launch_one(args: argparse.Namespace) -> int:
    queue = load_queue(Path(args.queue).resolve(strict=True))
    matches = [item for item in queue["candidates"] if item["candidate"] == args.candidate]
    if len(matches) != 1:
        raise AutofillError("claimed candidate is not unique in queue")
    profile = matches[0]
    root = Path(args.output_root)
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    driver = Path(args.driver).resolve(strict=True)
    cpus = parse_cpu_list(args.cpu_list)
    if len(cpus) != args.threads:
        raise AutofillError("thread count does not match CPU list")
    write_new(
        root / "autofill_assignment.json",
        canonical_json(
            {
                "schema": SCHEMA,
                "candidate": profile["candidate"],
                "queue_sha256": sha256_bytes(read_regular(Path(args.queue).resolve(strict=True))),
                "parent_protocol_sha256": PARENT_PROTOCOL_SHA256,
                "scheduler_source_sha256": sha256_bytes(read_regular(Path(__file__).resolve())),
                "cpu_list": list(cpus),
                "threads": args.threads,
                "max_memory_mb": args.max_memory_mb,
                "science_pilot_only": True,
                "production_accepted": False,
                "retry": False,
            }
        ),
    )
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        environment.pop(name, None)
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "OMP_NUM_THREADS": str(args.threads),
            "MKL_NUM_THREADS": str(args.threads),
            "OPENBLAS_NUM_THREADS": str(args.threads),
            "NUMEXPR_NUM_THREADS": str(args.threads),
            "BLIS_NUM_THREADS": str(args.threads),
            "VECLIB_MAXIMUM_THREADS": str(args.threads),
            "OMP_DYNAMIC": "FALSE",
            "MKL_DYNAMIC": "FALSE",
            "OMP_PROC_BIND": "close",
            "OMP_PLACES": "cores",
        }
    )
    command = [
        "timeout",
        "--signal=TERM",
        "--kill-after=30s",
        f"{max(args.route_limit_seconds - 10, 1)}s",
        "taskset",
        "-c",
        args.cpu_list,
        "/usr/bin/time",
        "-v",
        "-o",
        str(root / "controller_resource_usage.txt"),
        args.gpupyscf_python,
        "-I",
        "-B",
        str(driver / "scripts/phase9b_parent_level_paired_benchmark.py"),
        "parent-worker",
        "--route",
        "pure_pyscf",
        "--route-limit-seconds",
        str(args.route_limit_seconds),
        "--threads",
        str(args.threads),
        "--cpu-list",
        args.cpu_list,
        "--max-memory-mb",
        str(args.max_memory_mb),
        "--candidate",
        profile["candidate"],
        "--electron-count",
        str(profile["electron_count"]),
        "--cation-atom-count",
        str(profile["cation"]["atom_count"]),
        "--neutral-atom-count",
        str(profile["neutral"]["atom_count"]),
        "--cation-sha256",
        profile["cation"]["sha256"],
        "--neutral-sha256",
        profile["neutral"]["sha256"],
        "--root",
        str(root),
        "--source-root",
        str(driver / "src"),
        "--pilot-helper",
        str(driver / "scripts/phase9b_science_pilot.py"),
        "--sp-helper",
        str(driver / "scripts/phase9b_science_pilot_pyscf_continuation.py"),
        "--v006-helper",
        str(driver / "scripts/phase9b_science_pilot_timing_benchmark.py"),
        "--cation-input",
        profile["cation"]["path"],
        "--neutral-input",
        profile["neutral"]["path"],
    ]
    if args.record_training_frames:
        if not args.training_data_helper:
            raise AutofillError("training frame recording requires an explicit helper")
        command.extend(
            [
                "--record-training-frames",
                "--training-data-helper",
                str(Path(args.training_data_helper).resolve(strict=True)),
            ]
        )
    started = time.monotonic()
    with (
        (root / "controller_stdout").open("xb", buffering=0) as stdout,
        (root / "controller_stderr").open("xb", buffering=0) as stderr,
    ):
        completed = subprocess.run(command, env=environment, stdout=stdout, stderr=stderr)
    elapsed = time.monotonic() - started
    write_new(root / "controller_exit_code", f"{completed.returncode}\n".encode())
    write_new(root / "route_elapsed_seconds", f"{elapsed:.9f}\n".encode())
    return int(completed.returncode)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    watcher = sub.add_parser("watch")
    for name in (
        "queue",
        "state-root",
        "initial-watch-root",
        "run-root",
        "driver",
        "gpupyscf-python",
        "cpu-list",
    ):
        watcher.add_argument(f"--{name}", required=True)
    watcher.add_argument("--threads", type=int, required=True)
    watcher.add_argument("--max-memory-mb", type=int, required=True)
    watcher.add_argument("--route-limit-seconds", type=int, default=86400)
    watcher.add_argument("--poll-seconds", type=float, default=60.0)
    launcher = sub.add_parser("launch-one")
    for name in ("queue", "candidate", "output-root", "driver", "gpupyscf-python", "cpu-list"):
        launcher.add_argument(f"--{name}", required=True)
    launcher.add_argument("--threads", type=int, required=True)
    launcher.add_argument("--max-memory-mb", type=int, required=True)
    launcher.add_argument("--route-limit-seconds", type=int, default=86400)
    launcher.add_argument("--record-training-frames", action="store_true")
    launcher.add_argument("--training-data-helper")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "watch":
        return watch(args)
    if args.command == "launch-one":
        return launch_one(args)
    raise AutofillError("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
