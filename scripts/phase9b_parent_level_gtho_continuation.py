#!/usr/bin/env python3
"""One-shot GTHO neutral continuation and fail-closed Lane A handoff.

This is non-production science-pilot orchestration.  It neither modifies the
original timed attempt nor provides a general retry surface.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import math
import os
import resource
import stat
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

CANDIDATE: Final = "GTHOEAZLMAMKTA-UHFFFAOYSA-N"
PROTOCOL_SHA256: Final = "227c22a527e567bc4de873ab743fe9f493779eccbb1a698d2913c87695ebf87a"
CPU_LIST: Final = "0,2-27"
THREADS: Final = 27
MEMORY_MB: Final = 64000
ELECTRONS: Final = 132
CATION_ATOMS: Final = 34
NEUTRAL_ATOMS: Final = 33
CONTINUATION_SECONDS: Final = 86400
QUEUE_ROUTE_SECONDS: Final = 86400
SCHEMA: Final = "phase9b-gtho-neutral-continuation-v001"


class ContinuationError(RuntimeError):
    """The authorized continuation could not proceed safely."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ContinuationError(f"cannot load helper: {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_regular(path: Path, *, maximum: int = 512 << 20) -> bytes:
    if not path.is_absolute():
        raise ContinuationError("evidence path must be absolute")
    before = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ContinuationError(f"not a single-link regular file: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(1 << 20, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise ContinuationError(f"file exceeds read limit: {path.name}")
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ContinuationError(f"file identity changed during read: {path.name}")
    return b"".join(chunks)


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise ContinuationError("short evidence write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    if read_regular(path, maximum=max(len(raw), 1)) != raw:
        raise ContinuationError("evidence reread mismatch")


def write_json_new(path: Path, value: object) -> bytes:
    raw = canonical_json(value)
    write_new(path, raw)
    return raw


def read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = read_regular(path)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContinuationError(f"invalid JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise ContinuationError(f"JSON root is not an object: {path.name}")
    return cast(dict[str, Any], value), raw


def parse_single_xyz(raw: bytes, *, expected_atoms: int) -> tuple[tuple[str, ...], bytes]:
    lines = raw.splitlines(keepends=True)
    if len(lines) != expected_atoms + 2:
        raise ContinuationError("XYZ line count drifted")
    try:
        count = int(lines[0].strip())
    except ValueError as exc:
        raise ContinuationError("XYZ atom count is invalid") from exc
    if count != expected_atoms:
        raise ContinuationError("XYZ atom count drifted")
    elements: list[str] = []
    for line in lines[2:]:
        fields = line.decode("utf-8").split()
        if len(fields) != 4:
            raise ContinuationError("XYZ atom row is invalid")
        elements.append(fields[0])
        if not all(math.isfinite(float(value)) for value in fields[1:]):
            raise ContinuationError("XYZ contains a non-finite coordinate")
    return tuple(elements), raw


def last_complete_xyz_frame(
    trajectory: bytes, *, expected_atoms: int, expected_elements: Sequence[str]
) -> tuple[bytes, int]:
    lines = trajectory.splitlines(keepends=True)
    cursor = 0
    frames: list[bytes] = []
    while cursor < len(lines):
        if not lines[cursor].strip():
            cursor += 1
            continue
        try:
            count = int(lines[cursor].strip())
        except ValueError as exc:
            raise ContinuationError("trajectory atom count is invalid") from exc
        end = cursor + count + 2
        if count != expected_atoms or end > len(lines):
            raise ContinuationError("trajectory contains an incomplete or wrong-size frame")
        frame = b"".join(lines[cursor:end])
        elements, _ = parse_single_xyz(frame, expected_atoms=expected_atoms)
        if tuple(elements) != tuple(expected_elements):
            raise ContinuationError("trajectory element order drifted")
        frames.append(frame)
        cursor = end
    if not frames:
        raise ContinuationError("trajectory contains no complete frame")
    return frames[-1], len(frames)


def residual_processes(root: Path, *, excluded: set[int] | None = None) -> list[int]:
    excluded = set() if excluded is None else set(excluded)
    excluded.add(os.getpid())
    text = str(root.resolve(strict=True))
    result: list[int] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return result
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) in excluded:
            continue
        try:
            cmdline = (
                (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            )
            cwd = str((entry / "cwd").resolve(strict=True))
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        if text in cmdline or cwd == text or cwd.startswith(text + os.sep):
            result.append(int(entry.name))
    return sorted(result)


def wait_for_cleanup(root: Path, *, seconds: float = 60.0) -> list[int]:
    deadline = time.monotonic() + seconds
    while True:
        observed = residual_processes(root)
        if not observed or time.monotonic() >= deadline:
            return observed
        time.sleep(0.5)


def basic_route_audit(root: Path, *, expected_candidate: str) -> dict[str, object]:
    result, result_raw = read_json(root / "result.json")
    if result.get("candidate") != expected_candidate or result.get("final_outcome") != "PASS":
        raise ContinuationError("route result identity or outcome is invalid")
    if result.get("science_pilot_only") is not True:
        raise ContinuationError("route is not science-pilot-only")
    if result.get("production_accepted") is not False:
        raise ContinuationError("route is production accepted")
    endpoints = result.get("endpoint_results")
    if not isinstance(endpoints, dict) or set(endpoints) != {"cation", "neutral"}:
        raise ContinuationError("route endpoint results are incomplete")
    energies: dict[str, float] = {}
    for endpoint in ("cation", "neutral"):
        item = endpoints[endpoint]
        if not isinstance(item, dict):
            raise ContinuationError(f"{endpoint} endpoint result is invalid")
        energy = item.get("energy_hartree")
        geometry = item.get("geometry_optimization")
        if (
            item.get("candidate") != expected_candidate
            or item.get("endpoint") != endpoint
            or item.get("scf_converged") is not True
            or not isinstance(geometry, dict)
            or geometry.get("converged") is not True
            or isinstance(energy, bool)
            or not isinstance(energy, (int, float))
            or not math.isfinite(float(energy))
        ):
            raise ContinuationError(f"{endpoint} endpoint is incomplete")
        energies[endpoint] = float(energy)
    deprot = result.get("deprotonation")
    if (
        not isinstance(deprot, dict)
        or deprot.get("aimnet2_energy_used") is not False
        or not math.isfinite(float(cast(float, deprot.get("value_kcal_per_mol"))))
    ):
        raise ContinuationError("route deprotonation result is invalid")
    residual = residual_processes(root)
    if residual:
        raise ContinuationError(f"route has residual processes: {residual}")
    return {
        "schema": SCHEMA,
        "candidate": expected_candidate,
        "root": str(root),
        "result_sha256": sha256_bytes(result_raw),
        "cation_energy_hartree": energies["cation"],
        "neutral_energy_hartree": energies["neutral"],
        "residual_processes": [],
        "audit_pass": True,
    }


def previous_cation_binding(previous_root: Path, benchmark: Any) -> tuple[dict[str, Any], bytes]:
    path = previous_root / "final_single_point" / "cation" / "endpoint_result.json"
    result, raw = read_json(path)
    expected_protocol = benchmark.protocol(
        threads=THREADS,
        cpu_affinity=benchmark._parse_cpu_list(CPU_LIST),
        max_memory_mb=MEMORY_MB,
    )
    energy = result.get("energy_hartree")
    geometry = result.get("geometry_optimization")
    if (
        result.get("candidate") != CANDIDATE
        or result.get("endpoint") != "cation"
        or result.get("route") != "pure_pyscf"
        or result.get("protocol") != expected_protocol
        or result.get("scf_converged") is not True
        or not isinstance(geometry, dict)
        or geometry.get("converged") is not True
        or isinstance(energy, bool)
        or not isinstance(energy, (int, float))
        or not math.isfinite(float(energy))
    ):
        raise ContinuationError("previous cation endpoint is incomplete")
    final_xyz = read_regular(previous_root / "optimization" / "cation" / "final.xyz")
    if geometry.get("final_xyz_sha256") != sha256_bytes(final_xyz):
        raise ContinuationError("previous cation final geometry binding failed")
    return result, raw


def build_file_manifest(root: Path) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or "runtime_tmp" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        if relative == "file_manifest.json":
            continue
        raw = read_regular(path)
        files.append({"path": relative, "bytes": len(raw), "sha256": sha256_bytes(raw)})
    return {
        "schema": SCHEMA,
        "candidate": CANDIDATE,
        "post_worker_exit": True,
        "ephemeral_runtime_tmp_excluded": True,
        "files": files,
    }


def _rusage() -> tuple[float, float, int | str]:
    observed = resource.getrusage(resource.RUSAGE_SELF)
    maximum: int | str = int(observed.ru_maxrss) if observed.ru_maxrss >= 0 else "unavailable"
    return float(observed.ru_utime), float(observed.ru_stime), maximum


def worker(args: argparse.Namespace) -> int:
    benchmark = load_module(Path(args.benchmark_helper).resolve(strict=True), "gtho_benchmark")
    helper = load_module(Path(args.v006_helper).resolve(strict=True), "gtho_v006")
    pilot = load_module(Path(args.pilot_helper).resolve(strict=True), "gtho_pilot")
    single_point = load_module(Path(args.sp_helper).resolve(strict=True), "gtho_sp")
    source_root = Path(args.source_root).resolve(strict=True)
    pilot._add_source_root(source_root)
    from nhc_deprot_ranker.quantum import two_endpoint

    root = Path(args.root).resolve(strict=True)
    cpu_list = benchmark._parse_cpu_list(CPU_LIST)
    benchmark._configure_parent_resources(
        module=two_endpoint,
        root=root,
        threads=THREADS,
        cpu_list=cpu_list,
        memory_mb=MEMORY_MB,
    )
    started = time.monotonic()
    deadline = started + float(args.route_limit_seconds)
    request, handoff = benchmark._request(
        two_endpoint,
        helper,
        "neutral",
        root / "input" / "neutral_continuation.xyz",
        "pure_pyscf",
        expected_sha256=args.neutral_sha256,
        expected_atom_count=NEUTRAL_ATOMS,
        expected_electron_count=ELECTRONS,
    )
    helper.write_json_new(root / "handoff" / "neutral.json", handoff)
    backend = benchmark.build_parent_backend(
        pilot=pilot,
        module=two_endpoint,
        threads=THREADS,
        memory_mb=MEMORY_MB,
        expected_electron_count=ELECTRONS,
    )
    endpoint_started = time.monotonic()
    before_user, before_system, _ = _rusage()
    output_root = root / "optimization" / "neutral"
    with (
        helper._capture(output_root / "stdout", output_root / "stderr"),
        helper._cwd(output_root),
    ):
        optimization = two_endpoint._call_optimize(
            backend=backend,
            endpoint=request,
            strategy="standard",
            deadline=deadline,
        )
    optimized_raw = optimization.geometry.to_xyz_bytes(comment="P01 GTHO neutral continuation")
    helper.write_new(output_root / "final.xyz", optimized_raw)
    final_root = root / "final_single_point" / "neutral"
    optimized_request = dataclasses.replace(
        request,
        xyz_relative_path="final.xyz",
        xyz_path=output_root / "final.xyz",
        xyz_sha256=sha256_bytes(optimized_raw),
        geometry=optimization.geometry,
    )
    with (
        helper._capture(final_root / "stdout", final_root / "stderr"),
        helper._cwd(final_root),
    ):
        result, strategy, attempts = single_point.run_single_point(
            module=two_endpoint,
            backend=backend,
            endpoint=optimized_request,
            deadline=deadline,
        )
    after_user, after_system, maximum_rss = _rusage()
    metrics = cast(dict[str, object], backend.pilot_metrics.get("neutral", {}))
    neutral_payload: dict[str, object] = {
        "schema_version": benchmark.SCHEMA,
        "candidate": CANDIDATE,
        "endpoint": "neutral",
        "route": "pure_pyscf_continuation",
        "charge": 0,
        "multiplicity": 1,
        "spin": 0,
        "electron_count": ELECTRONS,
        "protocol": benchmark.protocol(
            threads=THREADS, cpu_affinity=cpu_list, max_memory_mb=MEMORY_MB
        ),
        "input": handoff,
        "parent_backend_identity": backend.parent_identity,
        "selected_strategy": strategy,
        "attempts": attempts,
        "scf_converged": bool(result.converged),
        "scf_cycles": metrics.get("final_scf_cycles", "unavailable"),
        "energy_hartree": float(result.energy_hartree),
        "d3": two_endpoint._final_dispersion_payload(result.dispersion),
        "runtime": two_endpoint._runtime_evidence_payload(result.runtime),
        "endpoint_wall_seconds": time.monotonic() - endpoint_started,
        "process_user_cpu_seconds": after_user - before_user,
        "process_system_cpu_seconds": after_system - before_system,
        "maximum_rss": maximum_rss,
        "geometry_optimization": {
            "converged": bool(optimization.geometry_converged),
            "last_energy_hartree": float(optimization.last_energy_hartree),
            "wall_seconds": metrics.get("optimization_standard_wall_seconds", "unavailable"),
            "geometry_steps": optimization.dispersion.gradient_hook_calls,
            "geometry_steps_definition": "observed D3 gradient-hook evaluations",
            "d3_energy_calls": optimization.dispersion.energy_hook_calls,
            "d3_gradient_calls": optimization.dispersion.gradient_hook_calls,
            "final_xyz_sha256": sha256_bytes(optimized_raw),
            "final_xyz_bytes": len(optimized_raw),
        },
        "retry": False,
        "continuation_authorized": True,
        "production_accepted": False,
    }
    helper.write_json_new(final_root / "endpoint_result.json", neutral_payload)
    cation, _ = previous_cation_binding(Path(args.previous_root).resolve(strict=True), benchmark)
    terminal = {
        "schema": SCHEMA,
        "science_pilot_only": True,
        "production_accepted": False,
        "production_label_inserted": False,
        "candidate": CANDIDATE,
        "route": "pure_pyscf_continuation",
        "single_candidate": True,
        "continuation_authorized": True,
        "continuation_index": 1,
        "automatic_retry": False,
        "retry": False,
        "protocol_sha256": PROTOCOL_SHA256,
        "protocol": benchmark.protocol(
            threads=THREADS, cpu_affinity=cpu_list, max_memory_mb=MEMORY_MB
        ),
        "endpoint_results": {"cation": cation, "neutral": neutral_payload},
        "deprotonation": benchmark.deprotonation(
            float(cast(float, cation["energy_hartree"])),
            float(cast(float, neutral_payload["energy_hartree"])),
        ),
        "continuation_wall_seconds": time.monotonic() - started,
        "final_outcome": "PASS",
    }
    helper.write_json_new(root / "result.json", terminal)
    return 0


def prepare_continuation(
    *, previous_root: Path, continuation_root: Path, benchmark: Any
) -> tuple[str, dict[str, object]]:
    cation, cation_raw = previous_cation_binding(previous_root, benchmark)
    initial_raw = read_regular(previous_root / "input" / "neutral_initial.xyz")
    elements, _ = parse_single_xyz(initial_raw, expected_atoms=NEUTRAL_ATOMS)
    trajectories = sorted(previous_root.glob("runtime_tmp/*/*_optim.xyz"))
    if len(trajectories) != 1:
        raise ContinuationError("expected exactly one neutral partial trajectory")
    trajectory_raw = read_regular(trajectories[0])
    last_raw, frame_count = last_complete_xyz_frame(
        trajectory_raw,
        expected_atoms=NEUTRAL_ATOMS,
        expected_elements=elements,
    )
    continuation_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    for relative in (
        "input",
        "handoff",
        "optimization/neutral",
        "final_single_point/neutral",
        "historical_binding",
    ):
        (continuation_root / relative).mkdir(mode=0o700, parents=True, exist_ok=False)
    write_new(continuation_root / "input" / "neutral_continuation.xyz", last_raw)
    binding = {
        "schema": SCHEMA,
        "candidate": CANDIDATE,
        "previous_root": str(previous_root),
        "previous_controller_exit_code": 124,
        "previous_cation_endpoint_result_sha256": sha256_bytes(cation_raw),
        "previous_cation_energy_hartree": cation["energy_hartree"],
        "partial_trajectory_path": str(trajectories[0].relative_to(previous_root)),
        "partial_trajectory_sha256": sha256_bytes(trajectory_raw),
        "partial_trajectory_bytes": len(trajectory_raw),
        "complete_frame_count": frame_count,
        "last_complete_frame_sha256": sha256_bytes(last_raw),
        "last_complete_frame_bytes": len(last_raw),
        "atom_count": NEUTRAL_ATOMS,
        "element_order_sha256": sha256_bytes(" ".join(elements).encode()),
        "protocol_sha256": PROTOCOL_SHA256,
        "continuation_authorized": True,
        "continuation_count": 1,
        "production_accepted": False,
    }
    write_json_new(continuation_root / "historical_binding" / "previous_attempt.json", binding)
    return sha256_bytes(last_raw), binding


def run_continuation(args: argparse.Namespace, benchmark: Any) -> Path:
    previous_root = Path(args.previous_root).resolve(strict=True)
    continuation_root = Path(args.continuation_root)
    if continuation_root.exists():
        raise ContinuationError("continuation root already exists")
    code = int(read_regular(previous_root / "controller_exit_code", maximum=32).decode().strip())
    if code != 124:
        raise ContinuationError("continuation requires original timeout exit 124")
    residual = wait_for_cleanup(previous_root)
    if residual:
        raise ContinuationError(f"original process tree remains: {residual}")
    neutral_sha, _ = prepare_continuation(
        previous_root=previous_root,
        continuation_root=continuation_root,
        benchmark=benchmark,
    )
    command = [
        "timeout",
        "--signal=TERM",
        "--kill-after=30s",
        f"{CONTINUATION_SECONDS - 10}s",
        "taskset",
        "-c",
        CPU_LIST,
        "/usr/bin/time",
        "-v",
        "-o",
        str(continuation_root / "controller_resource_usage.txt"),
        args.gpupyscf_python,
        "-I",
        "-B",
        str(Path(__file__).resolve(strict=True)),
        "worker",
        "--root",
        str(continuation_root),
        "--previous-root",
        str(previous_root),
        "--source-root",
        str(Path(args.source_root).resolve(strict=True)),
        "--benchmark-helper",
        str(Path(args.benchmark_helper).resolve(strict=True)),
        "--pilot-helper",
        str(Path(args.pilot_helper).resolve(strict=True)),
        "--sp-helper",
        str(Path(args.sp_helper).resolve(strict=True)),
        "--v006-helper",
        str(Path(args.v006_helper).resolve(strict=True)),
        "--neutral-sha256",
        neutral_sha,
        "--route-limit-seconds",
        str(CONTINUATION_SECONDS),
    ]
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        environment.pop(name, None)
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "OMP_NUM_THREADS": str(THREADS),
            "MKL_NUM_THREADS": str(THREADS),
            "OPENBLAS_NUM_THREADS": str(THREADS),
            "NUMEXPR_NUM_THREADS": str(THREADS),
            "BLIS_NUM_THREADS": str(THREADS),
            "VECLIB_MAXIMUM_THREADS": str(THREADS),
            "OMP_DYNAMIC": "FALSE",
            "MKL_DYNAMIC": "FALSE",
            "OMP_PROC_BIND": "close",
            "OMP_PLACES": "cores",
        }
    )
    started = time.monotonic()
    with (
        (continuation_root / "controller_stdout").open("xb", buffering=0) as stdout,
        (continuation_root / "controller_stderr").open("xb", buffering=0) as stderr,
    ):
        completed = subprocess.run(command, env=environment, stdout=stdout, stderr=stderr)
    elapsed = time.monotonic() - started
    write_new(continuation_root / "controller_exit_code", f"{completed.returncode}\n".encode())
    write_new(continuation_root / "route_elapsed_seconds", f"{elapsed:.9f}\n".encode())
    write_json_new(continuation_root / "file_manifest.json", build_file_manifest(continuation_root))
    if completed.returncode != 0:
        raise ContinuationError(f"continuation exited {completed.returncode}")
    basic_route_audit(continuation_root, expected_candidate=CANDIDATE)
    return continuation_root


def write_lane_terminal(state_root: Path, *, code: str, detail: str) -> None:
    path = state_root / "lane_terminal.json"
    if path.exists():
        return
    write_json_new(
        path,
        {
            "schema": SCHEMA,
            "outcome": code,
            "detail": detail,
            "next_candidate_started": False,
            "retry": False,
            "production_accepted": False,
        },
    )


def resume_lane_queue(
    args: argparse.Namespace, *, predecessor: Path, predecessor_audit: dict[str, object]
) -> None:
    autofill = load_module(Path(args.autofill_helper).resolve(strict=True), "gtho_autofill")
    queue_path = Path(args.queue).resolve(strict=True)
    queue = autofill.load_queue(queue_path)
    state_root = Path(args.state_root).resolve(strict=True)
    binding, _ = read_json(state_root / "queue_binding.json")
    if binding.get("queue_sha256") != sha256_bytes(read_regular(queue_path)):
        raise ContinuationError("Lane A queue binding drifted")
    if binding.get("initial_watch_root") != str(Path(args.previous_root).resolve(strict=True)):
        raise ContinuationError("Lane A initial predecessor binding drifted")
    claims = state_root / "claims"
    assignments = state_root / "assignments"
    if list(claims.iterdir()) or list(assignments.iterdir()):
        raise ContinuationError("Lane A was already consumed")
    audits = state_root / "audits"
    audits.mkdir(mode=0o700, exist_ok=False)
    watched = predecessor
    audit: dict[str, object] = predecessor_audit
    expected: str | None = None
    for index, profile in enumerate(queue["candidates"]):
        audit_raw = canonical_json(audit)
        write_new(audits / f"{index:03d}_predecessor.json", audit_raw)
        namespace = argparse.Namespace(
            queue=str(queue_path),
            run_root=args.run_root,
            driver=args.driver,
            gpupyscf_python=args.gpupyscf_python,
            threads=THREADS,
            cpu_list=CPU_LIST,
            max_memory_mb=MEMORY_MB,
            route_limit_seconds=QUEUE_ROUTE_SECONDS,
        )
        command = autofill._launcher_command(namespace, profile)
        output_root = Path(command[command.index("--output-root") + 1])
        if output_root.exists():
            raise ContinuationError("next Lane A output root already exists")
        write_json_new(
            claims / f"{index:03d}_{profile['candidate']}.json",
            {
                "schema": autofill.SCHEMA,
                "candidate": profile["candidate"],
                "predecessor_root": str(watched),
                "predecessor_exit_code": 0,
                "predecessor_audit_sha256": sha256_bytes(audit_raw),
                "output_root": str(output_root),
                "claim_index": index,
                "claimed_monotonic_ns": time.monotonic_ns(),
                "continuation_supervisor": True,
            },
        )
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        write_json_new(
            assignments / f"{index:03d}_{profile['candidate']}.json",
            {
                "schema": autofill.SCHEMA,
                "candidate": profile["candidate"],
                "launcher_pid": process.pid,
                "output_root": str(output_root),
                "cpu_list": list(autofill.parse_cpu_list(CPU_LIST)),
                "threads": THREADS,
                "command_sha256": sha256_bytes("\0".join(command).encode()),
                "continuation_supervisor": True,
            },
        )
        watched = output_root
        expected = str(profile["candidate"])
        while not (watched / "controller_exit_code").exists():
            time.sleep(args.poll_seconds)
        try:
            audit = autofill.audit_successful_route(watched, expected_candidate=expected)
        except Exception as exc:
            write_lane_terminal(
                state_root,
                code="CANDIDATE_AUDIT_FAILED",
                detail=f"{type(exc).__name__}: {exc}",
            )
            return
    final_raw = canonical_json(audit)
    write_new(audits / f"{len(queue['candidates']):03d}_final.json", final_raw)
    write_json_new(
        state_root / "queue_exhausted.json",
        {
            "schema": autofill.SCHEMA,
            "candidate_count": len(queue["candidates"]),
            "last_root": str(watched),
            "final_audit_sha256": sha256_bytes(final_raw),
            "queue_exhausted": True,
            "retry": False,
        },
    )


def supervise(args: argparse.Namespace) -> int:
    supervisor_root = Path(args.supervisor_root)
    supervisor_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    previous_root = Path(args.previous_root).resolve(strict=True)
    state_root = Path(args.state_root).resolve(strict=True)
    if Path("/proc").joinpath(str(args.retired_watcher_pid)).exists():
        raise ContinuationError("legacy Lane A watcher is still alive")
    source_raw = read_regular(Path(__file__).resolve(strict=True))
    write_json_new(
        supervisor_root / "binding.json",
        {
            "schema": SCHEMA,
            "candidate": CANDIDATE,
            "source_sha256": sha256_bytes(source_raw),
            "previous_root": str(previous_root),
            "continuation_root": str(Path(args.continuation_root)),
            "state_root": str(state_root),
            "retired_legacy_watcher_pid": args.retired_watcher_pid,
            "continuation_seconds": CONTINUATION_SECONDS,
            "cpu_list": CPU_LIST,
            "threads": THREADS,
            "max_memory_mb": MEMORY_MB,
            "production_accepted": False,
        },
    )
    terminal = previous_root / "controller_exit_code"
    while not terminal.exists():
        time.sleep(args.poll_seconds)
    code = int(read_regular(terminal, maximum=32).decode().strip())
    try:
        if code == 0:
            if wait_for_cleanup(previous_root):
                raise ContinuationError("completed original route has residual processes")
            predecessor = previous_root
            audit = basic_route_audit(predecessor, expected_candidate=CANDIDATE)
            branch = "original_completed_before_deadline"
        elif code == 124:
            benchmark = load_module(
                Path(args.benchmark_helper).resolve(strict=True), "gtho_supervisor_benchmark"
            )
            predecessor = run_continuation(args, benchmark)
            audit = basic_route_audit(predecessor, expected_candidate=CANDIDATE)
            branch = "authorized_neutral_continuation_completed"
        else:
            raise ContinuationError(f"original route exited with non-timeout status {code}")
        write_json_new(
            supervisor_root / "predecessor_terminal.json",
            {"schema": SCHEMA, "branch": branch, "audit": audit},
        )
        resume_lane_queue(args, predecessor=predecessor, predecessor_audit=audit)
        write_json_new(
            supervisor_root / "terminal.json",
            {"schema": SCHEMA, "outcome": "PASS", "lane_queue_resumed": True},
        )
        return 0
    except Exception as exc:
        write_lane_terminal(
            state_root,
            code="GTHO_CONTINUATION_FAILED",
            detail=f"{type(exc).__name__}: {exc}",
        )
        write_json_new(
            supervisor_root / "terminal.json",
            {
                "schema": SCHEMA,
                "outcome": "INCONCLUSIVE",
                "error": f"{type(exc).__name__}: {exc}",
                "lane_queue_resumed": False,
            },
        )
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    worker_parser = sub.add_parser("worker")
    for name in (
        "root",
        "previous-root",
        "source-root",
        "benchmark-helper",
        "pilot-helper",
        "sp-helper",
        "v006-helper",
        "neutral-sha256",
    ):
        worker_parser.add_argument(f"--{name}", required=True)
    worker_parser.add_argument("--route-limit-seconds", type=float, required=True)
    supervisor = sub.add_parser("supervise")
    for name in (
        "supervisor-root",
        "previous-root",
        "continuation-root",
        "state-root",
        "queue",
        "run-root",
        "driver",
        "gpupyscf-python",
        "source-root",
        "benchmark-helper",
        "pilot-helper",
        "sp-helper",
        "v006-helper",
        "autofill-helper",
    ):
        supervisor.add_argument(f"--{name}", required=True)
    supervisor.add_argument("--retired-watcher-pid", type=int, required=True)
    supervisor.add_argument("--poll-seconds", type=float, default=30.0)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "worker":
        return worker(args)
    if args.command == "supervise":
        return supervise(args)
    raise ContinuationError("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
