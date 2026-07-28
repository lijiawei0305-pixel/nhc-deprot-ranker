#!/usr/bin/env python3
"""One-candidate, non-production AIMNet2/PySCF timing benchmark.

The module is a thin orchestrator around the already-audited science-pilot
AIMNet2 entry point, V004 single-point helper, and frozen two-endpoint PySCF
backend.  It deliberately contains no production authority or batch logic.
"""

from __future__ import annotations

import argparse
import contextlib
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
from pathlib import Path
from typing import Any, Final, cast

CANDIDATE: Final = "LBNPGYISTSLAHY-UHFFFAOYSA-N"
ENDPOINTS: Final = ("cation", "neutral")
CHARGES: Final = {"cation": 1, "neutral": 0}
MULTIPLICITIES: Final = {"cation": 1, "neutral": 1}
SPINS: Final = {"cation": 0, "neutral": 0}
ATOM_COUNTS: Final = {"cation": 26, "neutral": 25}
INPUT_SHA256: Final = {
    "cation": "543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286",
    "neutral": "af9c30640801eec3ab27538a33204186849303dd57592ca5c93320ec1390f4b8",
}
INPUT_BYTES: Final = {"cation": 1075, "neutral": 1036}
ASSISTED_SHA256: Final = {
    "cation": "ea796a5c81504184382b965d57c588c74968a09de8942148d3d9cbadf70a7774",
    "neutral": "c40ca77bce9d8c8deefc2357bf2633fb4c0981ce9d4bd23aceb342d40646bc93",
}
HARTREE_TO_KCAL: Final = 627.509474
PROTON_CORRECTION: Final = 6.28
ROUTE_LIMIT_SECONDS: Final = 7200
SCHEMA: Final = "nhc-phase9b-science-pilot-timing-v006"


class BenchmarkError(RuntimeError):
    """The benchmark could not establish a trustworthy result."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode()


def read_regular(path: Path, *, maximum: int = 64 << 20) -> bytes:
    if path.is_symlink():
        raise BenchmarkError(f"symlink is forbidden: {path.name}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise BenchmarkError(f"unsafe regular-file identity: {path.name}")
        if before.st_size < 0 or before.st_size > maximum:
            raise BenchmarkError(f"file size is outside the frozen bound: {path.name}")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            block = os.read(descriptor, min(remaining, 1 << 20))
            if not block:
                raise BenchmarkError(f"short read: {path.name}")
            chunks.append(block)
            remaining -= len(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda value: (  # noqa: E731
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        stat.S_IMODE(value.st_mode),
        value.st_nlink,
    )
    if identity(before) != identity(after):
        raise BenchmarkError(f"file changed during read: {path.name}")
    return b"".join(chunks)


def make_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=False, exist_ok=False)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_new(path: Path, raw: bytes) -> dict[str, object]:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    fsync_directory(path.parent)
    reread = read_regular(path)
    if reread != raw:
        raise BenchmarkError(f"exclusive evidence reread failed: {path.name}")
    return {"bytes": len(raw), "sha256": sha256_bytes(raw)}


def write_json_new(path: Path, payload: object) -> dict[str, object]:
    return write_new(path, canonical_json(payload))


def load_module(path: Path, name: str) -> Any:
    raw = read_regular(path)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BenchmarkError(f"cannot load helper: {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if read_regular(path) != raw:
        raise BenchmarkError(f"helper changed while importing: {path.name}")
    return module


def deprotonation(cation: float, neutral: float) -> dict[str, object]:
    if not math.isfinite(cation) or not math.isfinite(neutral):
        raise BenchmarkError("endpoint energy is non-finite")
    difference = neutral - cation
    electronic = difference * HARTREE_TO_KCAL
    value = electronic - PROTON_CORRECTION
    return {
        "cation_energy_hartree": cation,
        "neutral_energy_hartree": neutral,
        "hartree_difference": difference,
        "conversion_factor_kcal_per_hartree": HARTREE_TO_KCAL,
        "electronic_difference_kcal_per_mol": electronic,
        "proton_correction_kcal_per_mol": PROTON_CORRECTION,
        "value_kcal_per_mol": value,
        "formula": "((E_neutral_PySCF - E_cation_PySCF) * 627.509474) - 6.28",
        "aimnet2_energy_used": False,
        "lower_is_better": True,
    }


def timing_comparison(assisted: float, pyscf_only: float) -> dict[str, float]:
    if assisted <= 0 or pyscf_only <= 0:
        raise BenchmarkError("route wall times must be positive")
    saved = pyscf_only - assisted
    return {
        "assisted_total_seconds": assisted,
        "pyscf_only_total_seconds": pyscf_only,
        "time_saved_seconds": saved,
        "speedup_ratio_pyscf_only_over_assisted": pyscf_only / assisted,
        "percent_time_saved": saved / pyscf_only * 100.0,
    }


def system_snapshot(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(strict=True)
    if args.label not in {"before_assisted", "before_pyscf_only"}:
        raise BenchmarkError("snapshot label is not pre-registered")
    hostname_digest = sha256_bytes(os.uname().nodename.encode())
    cpu_model = "unavailable"
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            cpu_model = line.split(":", 1)[1].strip()
            break
    memory = "unavailable"
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            memory = line.split(":", 1)[1].strip()
            break
    gpu = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,name,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout.splitlines()
    process_summary = subprocess.run(
        ["ps", "-eo", "comm="],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout.splitlines()
    executable_identities = {}
    for name, value in {
        "mlff": args.mlff_python,
        "gpupyscf": args.gpupyscf_python,
    }.items():
        raw = read_regular(Path(value).resolve(strict=True))
        executable_identities[name] = {"bytes": len(raw), "sha256": sha256_bytes(raw)}
    snapshot = {
        "schema_version": SCHEMA,
        "science_pilot_only": True,
        "label": args.label,
        "hostname_digest": hostname_digest,
        "boot_id_digest": sha256_bytes(Path("/proc/sys/kernel/random/boot_id").read_bytes()),
        "cpu_model": cpu_model,
        "available_memory": memory,
        "load_average": list(os.getloadavg()),
        "active_process_name_counts": {
            name: process_summary.count(name) for name in sorted(set(process_summary))
        },
        "gpu_observations_private_runtime": gpu,
        "selected_gpu_index": args.gpu_index,
        "selected_gpu_uuid": args.gpu_uuid,
        "interpreter_identities": executable_identities,
        "monotonic_ns": time.monotonic_ns(),
    }
    write_json_new(root / f"system_snapshot_{args.label}.json", snapshot)
    if args.label == "before_assisted":
        write_json_new(
            root / "benchmark_config.json",
            {
                "schema_version": SCHEMA,
                "science_pilot_only": True,
                "candidate": CANDIDATE,
                "route_order": ["AIMNet2-assisted", "60-second idle", "PySCF-only"],
                "route_attempts": 1,
                "route_deadline_seconds": 7200,
                "idle_seconds": 60,
                "second_candidate": False,
                "batch": False,
                "retry": False,
            },
        )
        write_json_new(
            root / "timing_definition.json",
            {
                "schema_version": SCHEMA,
                "clock": "CLOCK_MONOTONIC",
                "authoritative_route_wall": "external GNU time around each complete route",
                "speedup_definition": "PySCF-only time / AIMNet2-assisted time",
                "idle_excluded": True,
                "startup_handoff_parsing_and_evidence_included": True,
            },
        )
    return 0


def _rusage() -> tuple[float, float, int | str]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss: int | str = int(usage.ru_maxrss) if usage.ru_maxrss >= 0 else "unavailable"
    return float(usage.ru_utime), float(usage.ru_stime), rss


@contextlib.contextmanager
def _capture(stdout: Path, stderr: Path) -> Any:
    with stdout.open("xb", buffering=0) as out, stderr.open("xb", buffering=0) as err:
        saved_out, saved_err = os.dup(1), os.dup(2)
        try:
            os.dup2(out.fileno(), 1)
            os.dup2(err.fileno(), 2)
            yield
        finally:
            os.dup2(saved_out, 1)
            os.dup2(saved_err, 2)
            os.close(saved_out)
            os.close(saved_err)
    fsync_directory(stdout.parent)


@contextlib.contextmanager
def _cwd(path: Path) -> Any:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _configure_pyscf(module: Any, root: Path) -> None:
    for key, value in module.THREAD_ENVIRONMENT.items():
        os.environ[key] = value
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["TMPDIR"] = str(root / "runtime_tmp")
    make_directory(root / "runtime_tmp")
    if not hasattr(os, "sched_setaffinity") or not hasattr(os, "sched_getaffinity"):
        raise BenchmarkError("Linux CPU affinity API is unavailable")
    os.sched_setaffinity(0, {0, 1, 2, 3})
    if set(os.sched_getaffinity(0)) != {0, 1, 2, 3}:
        raise BenchmarkError("CPU affinity drifted")


def _input_request(module: Any, endpoint: str, path: Path) -> tuple[Any, dict[str, object]]:
    raw = read_regular(path)
    if len(raw) != INPUT_BYTES[endpoint] and sha256_bytes(raw) == INPUT_SHA256[endpoint]:
        raise BenchmarkError("impossible frozen input byte identity")
    expected_sha = INPUT_SHA256[endpoint]
    if "aimnet2" in path.name or "final" in path.name:
        expected_sha = ASSISTED_SHA256[endpoint]
    geometry = module._parse_xyz(raw, label=f"v006 {endpoint}")
    elements = tuple(atom.element for atom in geometry.atoms)
    if len(elements) != ATOM_COUNTS[endpoint]:
        raise BenchmarkError(f"{endpoint} atom count drifted")
    if module._electron_count_for_geometry(geometry, charge=CHARGES[endpoint]) != 160:
        raise BenchmarkError(f"{endpoint} electron count drifted")
    if sha256_bytes(raw) != expected_sha:
        raise BenchmarkError(f"{endpoint} XYZ identity drifted")
    request = module.EndpointRequest(
        name=cast(Any, endpoint),
        xyz_relative_path=path.name,
        xyz_path=path,
        xyz_sha256=sha256_bytes(raw),
        charge=CHARGES[endpoint],
        multiplicity=MULTIPLICITIES[endpoint],
        electron_count=160,
        geometry=geometry,
    )
    return request, {
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
        "parser_sha256": sha256_bytes(raw),
        "atom_order_sha256": sha256_bytes(" ".join(elements).encode()),
        "charge": CHARGES[endpoint],
        "multiplicity": MULTIPLICITIES[endpoint],
        "spin": SPINS[endpoint],
        "atom_count": len(elements),
        "exact_bytes": True,
    }


def _endpoint_payload(module: Any, result: Any, metrics: dict[str, object]) -> dict[str, object]:
    return {
        "energy_hartree": result.energy_hartree,
        "scf_converged": result.converged,
        "scf_cycles": metrics.get("final_scf_cycles", "unavailable"),
        "runtime": module._runtime_evidence_payload(result.runtime),
        "d3": module._final_dispersion_payload(result.dispersion),
    }


def _clean_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        environment.pop(name, None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def assisted_controller(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(strict=True)
    v002 = Path(args.aimnet_root).resolve(strict=True)
    repo = Path(args.repo).resolve(strict=True)
    script = Path(__file__).resolve(strict=True)
    environment = _clean_environment()
    aimnet_stdout = (root / "aimnet_driver_stdout").open("xb", buffering=0)
    aimnet_stderr = (root / "aimnet_driver_stderr").open("xb", buffering=0)
    try:
        aimnet = subprocess.run(
            [
                args.mlff_python,
                "-I",
                "-B",
                str(repo / "scripts/phase9b_science_pilot.py"),
                "aimnet2",
                "--pilot-root",
                str(v002),
                "--source-root",
                str(repo / "src"),
                "--source-commit",
                args.source_commit,
                "--weight",
                args.weight,
                "--physical-gpu-index",
                str(args.gpu_index),
                "--physical-gpu-uuid",
                args.gpu_uuid,
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=aimnet_stdout,
            stderr=aimnet_stderr,
            timeout=1000,
            check=False,
        )
    finally:
        aimnet_stdout.close()
        aimnet_stderr.close()
    if aimnet.returncode == 0:
        raise BenchmarkError("AIMNet2 unexpectedly passed the unchanged production gate")
    for endpoint in ENDPOINTS:
        raw = read_regular(v002 / "aimnet2" / endpoint / "final.xyz")
        if sha256_bytes(raw) != ASSISTED_SHA256[endpoint]:
            raise BenchmarkError("new AIMNet2 output needs a fresh read-only review")
    with (
        (root / "review_stdout").open("xb") as stdout,
        (root / "review_stderr").open("xb") as stderr,
    ):
        subprocess.run(
            [
                args.gpupyscf_python,
                "-I",
                "-B",
                str(repo / "scripts/phase9b_science_pilot_geometry_review.py"),
                "--pilot-root",
                str(v002),
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            timeout=120,
            check=True,
        )
    with (
        (root / "pyscf_driver_stdout").open("xb") as stdout,
        (root / "pyscf_driver_stderr").open("xb") as stderr,
    ):
        subprocess.run(
            [
                "taskset",
                "-c",
                "0-3",
                args.gpupyscf_python,
                "-I",
                "-B",
                str(script),
                "pyscf-worker",
                "--route",
                "assisted",
                "--root",
                str(root),
                "--source-root",
                str(repo / "src"),
                "--pilot-helper",
                str(repo / "scripts/phase9b_science_pilot.py"),
                "--v004-helper",
                str(repo / "scripts/phase9b_science_pilot_pyscf_continuation.py"),
                "--cation-input",
                str(v002 / "aimnet2/cation/final.xyz"),
                "--neutral-input",
                str(v002 / "aimnet2/neutral/final.xyz"),
                "--aimnet-summary",
                str(v002 / "aimnet2/summary.json"),
                "--review-result",
                str(v002 / "review_v004/review_result.json"),
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            timeout=ROUTE_LIMIT_SECONDS,
            check=True,
        )
    return 0


def run_pyscf_worker(args: argparse.Namespace) -> int:
    started = time.monotonic()
    deadline = started + ROUTE_LIMIT_SECONDS
    root = Path(args.root).resolve(strict=True)
    source_root = Path(args.source_root).resolve(strict=True)
    pilot = load_module(Path(args.pilot_helper).resolve(strict=True), "v006_pilot_helper")
    v004 = load_module(Path(args.v004_helper).resolve(strict=True), "v006_sp_helper")
    pilot._add_source_root(source_root)
    from nhc_deprot_ranker.quantum import two_endpoint

    _configure_pyscf(two_endpoint, root)
    aimnet_summary: dict[str, object] | None = None
    review_binding: dict[str, object] | None = None
    if args.route == "assisted":
        if args.aimnet_summary is None or args.review_result is None:
            raise BenchmarkError("assisted route requires AIMNet2 and review evidence")
        aimnet_summary = json.loads(read_regular(Path(args.aimnet_summary)))
        review_binding = json.loads(read_regular(Path(args.review_result)))
        endpoints = aimnet_summary.get("endpoints")
        if (
            aimnet_summary.get("model_load_count") != 1
            or aimnet_summary.get("endpoint_wrapper_count") != 2
            or not isinstance(endpoints, dict)
            or any(
                not isinstance(endpoints.get(endpoint), dict)
                or cast(dict[str, object], endpoints[endpoint]).get("optimizer_terminal_state")
                != "converged"
                for endpoint in ENDPOINTS
            )
        ):
            raise BenchmarkError("AIMNet2 metrology is not a two-endpoint converged run")
        if (
            review_binding.get("classification") != "SAME_BASIN_LIKELY"
            or review_binding.get("production_10_degree_gate_unchanged") is not True
        ):
            raise BenchmarkError("corrected geometry review did not admit the assisted geometry")
    for name in ("input", "handoff"):
        make_directory(root / name)
    if args.route == "assisted":
        make_directory(root / "pyscf")
        for endpoint in ENDPOINTS:
            make_directory(root / "pyscf" / endpoint)
    else:
        make_directory(root / "optimization")
        make_directory(root / "final_single_point")
        for endpoint in ENDPOINTS:
            make_directory(root / "optimization" / endpoint)
            make_directory(root / "final_single_point" / endpoint)

    requests: dict[str, Any] = {}
    handoffs: dict[str, object] = {}
    for endpoint in ENDPOINTS:
        source = Path(getattr(args, f"{endpoint}_input")).resolve(strict=True)
        raw = read_regular(source)
        destination = (
            root
            / "input"
            / (
                f"{endpoint}_aimnet2_final.xyz"
                if args.route == "assisted"
                else f"{endpoint}_initial.xyz"
            )
        )
        write_new(destination, raw)
        request, handoff = _input_request(two_endpoint, endpoint, destination)
        requests[endpoint] = request
        handoffs[endpoint] = handoff
        write_json_new(root / "handoff" / f"{endpoint}.json", handoff)

    backend = (
        v004.build_observed_backend(pilot=pilot, module=two_endpoint)
        if args.route == "assisted"
        else pilot._SciencePilotPySCFBackend.build(two_endpoint)
    )
    endpoint_results: dict[str, object] = {}
    energies: dict[str, float] = {}
    for endpoint in ENDPOINTS:
        if endpoint == "neutral" and "cation" not in energies:
            break
        before_user, before_system, _ = _rusage()
        endpoint_started = time.monotonic()
        if args.route == "assisted":
            output_root = root / "pyscf" / endpoint
        else:
            output_root = root / "optimization" / endpoint
        try:
            if args.route == "assisted":
                with _capture(output_root / "stdout", output_root / "stderr"), _cwd(output_root):
                    result, strategy, attempts = v004.run_single_point(
                        module=two_endpoint,
                        backend=backend,
                        endpoint=requests[endpoint],
                        deadline=deadline,
                    )
                optimization = None
            else:
                optimization_started = time.monotonic()
                with _capture(output_root / "stdout", output_root / "stderr"), _cwd(output_root):
                    optimization = two_endpoint._call_optimize(
                        backend=backend,
                        endpoint=requests[endpoint],
                        strategy="standard",
                        deadline=deadline,
                    )
                optimization_wall = time.monotonic() - optimization_started
                optimized = optimization.geometry.to_xyz_bytes(
                    comment=f"science_pilot_only {CANDIDATE} {endpoint} PySCF optimized"
                )
                final_receipt = write_new(output_root / "final.xyz", optimized)
                final_root = root / "final_single_point" / endpoint
                write_new(final_root / "final.xyz", optimized)
                final_started = time.monotonic()
                with _capture(final_root / "stdout", final_root / "stderr"), _cwd(final_root):
                    result = two_endpoint._call_scf(
                        backend=backend,
                        endpoint=requests[endpoint],
                        geometry=optimization.geometry,
                        strategy="standard",
                        deadline=deadline,
                    )
                final_wall = time.monotonic() - final_started
                strategy = "standard"
                attempts = [{"strategy": "standard", "converged": True}]
        except BaseException as exc:
            write_json_new(
                root / "result.json",
                {
                    "schema_version": SCHEMA,
                    "science_pilot_only": True,
                    "production_accepted": False,
                    "route": args.route,
                    "final_outcome": "FAIL",
                    "failed_endpoint": endpoint,
                    "failure": {"class": type(exc).__name__, "message": str(exc)[:1000]},
                    "endpoint_results": endpoint_results,
                    "deprotonation": None,
                },
            )
            raise
        endpoint_wall = time.monotonic() - endpoint_started
        after_user, after_system, max_rss = _rusage()
        metrics = cast(dict[str, object], backend.pilot_metrics.get(endpoint, {}))
        payload = {
            "status": "success",
            "endpoint": endpoint,
            "charge": CHARGES[endpoint],
            "multiplicity": 1,
            "spin": 0,
            "geometry_provenance": (
                "aimnet2_preoptimized" if args.route == "assisted" else "frozen_initial"
            ),
            "strategy": strategy,
            "attempts": attempts,
            "endpoint_total_wall_seconds": endpoint_wall,
            "process_user_cpu_seconds": after_user - before_user,
            "process_system_cpu_seconds": after_system - before_system,
            "maximum_rss_native_units": max_rss,
            "handoff": handoffs[endpoint],
            **_endpoint_payload(two_endpoint, result, metrics),
        }
        if optimization is not None:
            dispersion = two_endpoint._optimization_dispersion_payload(optimization.dispersion)
            payload["geometry_optimization"] = {
                "optimizer": "geomeTRIC",
                "converged": True,
                "maximum_steps": 100,
                "geometry_steps": dispersion.get("gradient_hook_calls", "unavailable"),
                "geometry_steps_definition": "observed D3 gradient-hook evaluations",
                "d3_energy_calls": dispersion.get("energy_hook_calls", "unavailable"),
                "d3_gradient_calls": dispersion.get("gradient_hook_calls", "unavailable"),
                "cumulative_scf_cycles": "unavailable_not_exposed_by_frozen_backend",
                "wall_seconds": optimization_wall,
                "last_energy_hartree": optimization.last_energy_hartree,
                "final_xyz": final_receipt,
            }
            payload["final_single_point_wall_seconds"] = final_wall
            write_json_new(final_root / "endpoint_result.json", payload)
        else:
            payload["final_single_point_wall_seconds"] = metrics.get(
                f"final_scf_{strategy}_wall_seconds", "unavailable"
            )
        write_json_new(output_root / "endpoint_result.json", payload)
        endpoint_results[endpoint] = payload
        energies[endpoint] = result.energy_hartree

    label = deprotonation(energies["cation"], energies["neutral"])
    terminal = {
        "schema_version": SCHEMA,
        "science_pilot_only": True,
        "production_accepted": False,
        "production_label_inserted": False,
        "second_candidate": False,
        "batch": False,
        "retry": False,
        "candidate": CANDIDATE,
        "route": args.route,
        "protocol_sha256": two_endpoint.LOCKED_PROTOCOL_SHA256,
        "protocol": two_endpoint.LOCKED_PROTOCOL,
        "aimnet2": aimnet_summary,
        "geometry_review": review_binding,
        "endpoint_results": endpoint_results,
        "deprotonation": label,
        "internal_wall_seconds": time.monotonic() - started,
        "final_outcome": "PASS",
    }
    write_json_new(root / "result.json", terminal)
    return 0


def manifest(root: Path) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise BenchmarkError("evidence contains symlink")
        if path.is_dir() or "runtime_tmp" in path.parts or path.name == "manifest.json":
            continue
        raw = read_regular(path)
        files.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
            }
        )
    return {"schema_version": SCHEMA, "science_pilot_only": True, "files": files}


def finalize(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(strict=True)
    assisted = json.loads(read_regular(root / "assisted" / "result.json"))
    direct = json.loads(read_regular(root / "pyscf_only" / "result.json"))
    assisted_total = float(read_regular(Path(args.assisted_elapsed)).decode().strip())
    direct_total = float(read_regular(Path(args.pyscf_only_elapsed)).decode().strip())
    route_timing = timing_comparison(assisted_total, direct_total)
    endpoint_timing: dict[str, object] = {}
    energy_comparison: dict[str, object] = {}
    for endpoint in ENDPOINTS:
        left = assisted["endpoint_results"][endpoint]
        right = direct["endpoint_results"][endpoint]
        left_wall = float(left["endpoint_total_wall_seconds"])
        right_wall = float(right["endpoint_total_wall_seconds"])
        endpoint_timing[endpoint] = {
            "assisted_seconds": left_wall,
            "pyscf_only_seconds": right_wall,
            "time_saved_seconds": right_wall - left_wall,
            "speedup_ratio_pyscf_only_over_assisted": right_wall / left_wall,
        }
        energy_comparison[endpoint] = {
            "assisted_hartree": left["energy_hartree"],
            "pyscf_only_hartree": right["energy_hartree"],
            "assisted_minus_pyscf_only_hartree": left["energy_hartree"] - right["energy_hartree"],
        }
    label_delta = (
        assisted["deprotonation"]["value_kcal_per_mol"]
        - direct["deprotonation"]["value_kcal_per_mol"]
    )
    comparison_root = root / "comparison"
    write_json_new(comparison_root / "endpoint_timing.json", endpoint_timing)
    write_json_new(comparison_root / "route_timing.json", route_timing)
    write_json_new(comparison_root / "energy_comparison.json", energy_comparison)
    write_json_new(
        comparison_root / "label_comparison.json",
        {
            "assisted_kcal_per_mol": assisted["deprotonation"]["value_kcal_per_mol"],
            "pyscf_only_kcal_per_mol": direct["deprotonation"]["value_kcal_per_mol"],
            "assisted_minus_pyscf_only_kcal_per_mol": label_delta,
        },
    )
    terminal = {
        "schema_version": SCHEMA,
        "science_pilot_only": True,
        "production_accepted": False,
        "production_label_inserted": False,
        "candidate": CANDIDATE,
        "second_candidate": False,
        "batch": False,
        "route_order": ["AIMNet2-assisted", "60-second idle", "PySCF-only"],
        "route_timing": route_timing,
        "endpoint_timing": endpoint_timing,
        "energy_comparison": energy_comparison,
        "label_delta_assisted_minus_pyscf_only_kcal_per_mol": label_delta,
        "final_outcome": "PASS",
        "final_conclusion": "PASS — AIMNet2-assisted 与 PySCF-only 端到端时间对照已完成",
    }
    write_json_new(root / "result.json", terminal)
    write_json_new(root / "file_manifest.json", manifest(root))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--root", required=True)
    snapshot.add_argument("--label", required=True)
    snapshot.add_argument("--mlff-python", required=True)
    snapshot.add_argument("--gpupyscf-python", required=True)
    snapshot.add_argument("--gpu-index", required=True, type=int)
    snapshot.add_argument("--gpu-uuid", required=True)
    assisted = sub.add_parser("assisted-controller")
    assisted.add_argument("--root", required=True)
    assisted.add_argument("--aimnet-root", required=True)
    assisted.add_argument("--repo", required=True)
    assisted.add_argument("--source-commit", required=True)
    assisted.add_argument("--mlff-python", required=True)
    assisted.add_argument("--gpupyscf-python", required=True)
    assisted.add_argument("--weight", required=True)
    assisted.add_argument("--gpu-index", required=True, type=int)
    assisted.add_argument("--gpu-uuid", required=True)
    worker = sub.add_parser("pyscf-worker")
    worker.add_argument("--route", choices=("assisted", "pyscf_only"), required=True)
    worker.add_argument("--root", required=True)
    worker.add_argument("--source-root", required=True)
    worker.add_argument("--pilot-helper", required=True)
    worker.add_argument("--v004-helper", required=True)
    worker.add_argument("--cation-input", required=True)
    worker.add_argument("--neutral-input", required=True)
    worker.add_argument("--aimnet-summary")
    worker.add_argument("--review-result")
    complete = sub.add_parser("finalize")
    complete.add_argument("--root", required=True)
    complete.add_argument("--assisted-elapsed", required=True)
    complete.add_argument("--pyscf-only-elapsed", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    if args.command == "snapshot":
        return system_snapshot(args)
    if args.command == "assisted-controller":
        return assisted_controller(args)
    if args.command == "pyscf-worker":
        return run_pyscf_worker(args)
    if args.command == "finalize":
        return finalize(args)
    raise BenchmarkError("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
