#!/usr/bin/env python3
"""Resource-safe continuation of the parent-level P01 fixed-geometry audit.

This is an isolated science-pilot utility.  It discovers effective Linux CPU
and memory limits, performs a bounded physical-vs-SMT calibration, and runs the
grid-3-density -> grid-4 energy/gradient audit.  It never imports production
authority or opens an execution gate.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata as metadata
import json
import math
import os
import platform
import resource
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Final, cast

PARENT_XC: Final = "wb97m-d3bj"
PARENT_D3_METHOD: Final = "wb97m"
PARENT_BASIS: Final = "def2-tzvpp"
SCF_TOLERANCE: Final = 1.0e-9
SCF_MAX_CYCLES: Final = 100
MEMORY_CAP_MB: Final = 64_000
SMT_IMPROVEMENT_FRACTION: Final = 0.05
INPUT_SHA256: Final = "ea796a5c81504184382b965d57c588c74968a09de8942148d3d9cbadf70a7774"
WEIGHT_SHA256: Final = "f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28"
SCHEMA: Final = "nhc-phase9b-parent-level-p01-r1-v1"


class R1Error(RuntimeError):
    """A resource or scientific audit invariant did not close."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode()


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
    reread = read_regular(path, maximum=max(len(raw), 1) + 1)
    if reread != raw:
        raise R1Error(f"evidence reread failed: {path.name}")
    return {"bytes": len(raw), "sha256": sha256_bytes(raw)}


def write_json_new(path: Path, payload: object) -> dict[str, object]:
    return write_new(path, canonical_json(payload))


def make_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=False, exist_ok=False)
    fsync_directory(path.parent)


def read_regular(path: Path, *, maximum: int = 512 << 20) -> bytes:
    if path.is_symlink():
        raise R1Error(f"symlink forbidden: {path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise R1Error(f"unsafe file identity: {path}")
        if before.st_size < 0 or before.st_size > maximum:
            raise R1Error(f"file size outside bound: {path}")
        raw = b""
        while len(raw) < before.st_size:
            block = os.read(descriptor, min(1 << 20, before.st_size - len(raw)))
            if not block:
                raise R1Error(f"short read: {path}")
            raw += block
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    def identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            stat.S_IMODE(value.st_mode),
            value.st_nlink,
        )

    if identity(before) != identity(after):
        raise R1Error(f"file changed during read: {path}")
    return raw


def parse_cpu_list(value: str) -> tuple[int, ...]:
    result: set[int] = set()
    for item in value.strip().split(","):
        if not item:
            continue
        if "-" in item:
            left, right = item.split("-", 1)
            start, stop = int(left), int(right)
            if start < 0 or stop < start:
                raise R1Error("invalid CPU range")
            result.update(range(start, stop + 1))
        else:
            cpu = int(item)
            if cpu < 0:
                raise R1Error("negative CPU")
            result.add(cpu)
    if not result:
        raise R1Error("empty CPU list")
    return tuple(sorted(result))


def format_cpu_list(cpus: Sequence[int]) -> str:
    ordered = sorted(set(cpus))
    if not ordered:
        raise R1Error("empty CPU list")
    chunks: list[str] = []
    start = previous = ordered[0]
    for cpu in ordered[1:]:
        if cpu == previous + 1:
            previous = cpu
            continue
        chunks.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = cpu
    chunks.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(chunks)


def topology_from_lscpu(raw: str) -> dict[int, tuple[int, int, int]]:
    result: dict[int, tuple[int, int, int]] = {}
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split(",")
        if len(fields) != 5 or fields[4].strip().lower() not in {"yes", "y", "1"}:
            continue
        cpu, node, socket, core = (int(fields[index]) for index in range(4))
        result[cpu] = (node, socket, core)
    if not result:
        raise R1Error("CPU topology is empty")
    return result


def physical_count(cpus: Sequence[int], topology: dict[int, tuple[int, int, int]]) -> int:
    return len({(topology[cpu][1], topology[cpu][2]) for cpu in cpus})


def safe_shared_node_selection(
    *,
    allowed: Sequence[int],
    topology: dict[int, tuple[int, int, int]],
    active_cpus: Sequence[int],
    selected_socket: int = 0,
) -> dict[str, object]:
    """Conservatively use one socket and leave the other socket untouched."""

    allowed_set = set(allowed)
    active_cores = {(topology[cpu][1], topology[cpu][2]) for cpu in active_cpus if cpu in topology}
    core_to_cpus: dict[tuple[int, int], list[int]] = {}
    for cpu in sorted(allowed_set):
        _, socket, core = topology[cpu]
        if socket == selected_socket:
            core_to_cpus.setdefault((socket, core), []).append(cpu)
    safe_cores = [key for key in sorted(core_to_cpus) if key not in active_cores]
    if not safe_cores:
        raise R1Error("INCONCLUSIVE_RESOURCE_ALLOCATION")
    physical = tuple(min(core_to_cpus[key]) for key in safe_cores)
    logical = tuple(sorted(cpu for key in safe_cores for cpu in core_to_cpus[key]))
    return {
        "node_exclusive": False,
        "allocation_status": "NODE_NOT_CONFIRMED_EXCLUSIVE",
        "selected_socket": selected_socket,
        "active_physical_cores_excluded": [list(item) for item in sorted(active_cores)],
        "physical_cpu_list": format_cpu_list(physical),
        "logical_cpu_list": format_cpu_list(logical),
        "n_safe_physical": len(safe_cores),
        "n_safe_logical": len(logical),
        "untouched_sockets": sorted({value[1] for value in topology.values()} - {selected_socket}),
    }


def memory_safe_mb(*, available_bytes: int, cgroup_limit: int | None) -> int:
    candidates = [available_bytes]
    if cgroup_limit is not None:
        candidates.append(cgroup_limit)
    safe = math.floor(min(candidates) * 0.80 / 1_000_000)
    return min(MEMORY_CAP_MB, safe)


def thread_environment(threads: int) -> dict[str, str]:
    if threads <= 0 or threads > 112:
        raise R1Error("thread count outside frozen bound")
    result = {
        name: str(threads)
        for name in (
            "OMP_NUM_THREADS",
            "MKL_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "BLIS_NUM_THREADS",
            "VECLIB_MAXIMUM_THREADS",
        )
    }
    result.update(
        {
            "OMP_DYNAMIC": "FALSE",
            "MKL_DYNAMIC": "FALSE",
            "OMP_PROC_BIND": "close",
            "OMP_PLACES": "cores",
        }
    )
    return result


def _run(command: Sequence[str], *, timeout: float = 30.0) -> dict[str, object]:
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return {
        "argv": list(command),
        "returncode": completed.returncode,
        "stdout": completed.stdout.decode("utf-8", errors="replace"),
        "stderr": completed.stderr.decode("utf-8", errors="replace"),
    }


def _cgroup_values() -> dict[str, object]:
    line = Path("/proc/self/cgroup").read_text().strip()
    relative = line.split(":", 2)[2] if line.startswith("0::") else ""
    current = Path("/sys/fs/cgroup") / relative.lstrip("/")

    def inherited(name: str) -> str:
        probe = current
        while True:
            candidate = probe / name
            if candidate.is_file():
                return candidate.read_text().strip()
            if probe == Path("/sys/fs/cgroup"):
                return "unavailable"
            probe = probe.parent

    return {
        "path": relative,
        "cpuset_cpus_effective": inherited("cpuset.cpus.effective"),
        "cpu_max": inherited("cpu.max"),
        "memory_max": inherited("memory.max"),
        "memory_current": inherited("memory.current"),
        "memory_swap_max": inherited("memory.swap.max"),
        "memory_swap_current": inherited("memory.swap.current"),
    }


def discover(args: argparse.Namespace) -> int:
    root = Path(args.root)
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    make_directory(root / "resource_discovery")
    make_directory(root / "grid4_audit")
    make_directory(root / "grid_comparison")
    make_directory(root / "paired_benchmark")
    evidence = root / "resource_discovery"
    commands = {
        "hostname_date_uname": ["bash", "-lc", "hostname; date -u; uname -a"],
        "lscpu": ["lscpu"],
        "lscpu_extended": ["lscpu", "-e=CPU,NODE,SOCKET,CORE,ONLINE"],
        "lscpu_parse": ["lscpu", "-p=CPU,NODE,SOCKET,CORE,ONLINE"],
        "counts_affinity": [
            "bash",
            "-lc",
            "nproc; nproc --all; getconf _NPROCESSORS_ONLN; taskset -pc $$; "
            "grep -E 'Cpus_allowed|Cpus_allowed_list|Mems_allowed|Mems_allowed_list' "
            "/proc/self/status",
        ],
        "cgroup": ["bash", "-lc", "cat /proc/self/cgroup; cat /proc/self/mountinfo"],
        "scheduler": [
            "bash",
            "-lc",
            "env | sort | grep -E "
            "'^(SLURM|PBS|LSB|SGE|NSLOTS|OMP|MKL|OPENBLAS|NUMEXPR|VECLIB|BLIS)_' || true",
        ],
        "numa": ["bash", "-lc", "numactl --hardware 2>/dev/null || true"],
        "load": [
            "bash",
            "-lc",
            "uptime; free -h; ps -eo user,pid,ppid,psr,pcpu,pmem,etime,stat,comm,args "
            "--sort=-pcpu | head -n 60",
        ],
        "mpstat": ["bash", "-lc", "mpstat -P ALL 1 3 2>/dev/null || true"],
        "vmstat": ["vmstat", "1", "5"],
    }
    raw_outputs: dict[str, dict[str, object]] = {}
    for name, command in commands.items():
        result = _run(command, timeout=15.0)
        raw_outputs[name] = result
        write_new(evidence / f"{name}.txt", str(result["stdout"]).encode())
    topology = topology_from_lscpu(str(raw_outputs["lscpu_parse"]["stdout"]))
    linux_os = cast(Any, os)
    allowed = tuple(sorted(linux_os.sched_getaffinity(0)))
    process_rows = str(raw_outputs["load"]["stdout"]).splitlines()
    active: list[int] = []
    for row in process_rows:
        fields = row.split()
        if len(fields) < 5 or fields[0] == "USER":
            continue
        try:
            cpu, pcpu = int(fields[3]), float(fields[4])
        except ValueError:
            continue
        if pcpu >= 50.0 and fields[8] not in {"ps", "head"}:
            active.append(cpu)
    selection = safe_shared_node_selection(
        allowed=allowed,
        topology=topology,
        active_cpus=active,
        selected_socket=0,
    )
    memory = _run(["free", "-b"], timeout=5.0)
    rows = str(memory["stdout"]).splitlines()
    available = int(rows[1].split()[6])
    cgroup = _cgroup_values()
    limit_raw = str(cgroup["memory_max"])
    cgroup_limit = None if limit_raw in {"max", "unavailable"} else int(limit_raw)
    selection.update(
        {
            "schema_version": SCHEMA,
            "n_system_logical": len(topology),
            "n_system_physical": physical_count(tuple(topology), topology),
            "n_allowed_logical": len(allowed),
            "n_allowed_physical": physical_count(allowed, topology),
            "n_scheduler_allocated": None,
            "scheduler_detected": False,
            "process_affinity": format_cpu_list(allowed),
            "cgroup": cgroup,
            "available_memory_bytes": available,
            "memory_safe_mb": memory_safe_mb(available_bytes=available, cgroup_limit=cgroup_limit),
            "active_cpu_sample": sorted(set(active)),
            "selection_policy": (
                "shared node: one NUMA socket, exclude active cores, leave other socket untouched"
            ),
            "production_accepted": False,
        }
    )
    write_json_new(
        evidence / "cpu_topology.json",
        {
            str(cpu): {"node": values[0], "socket": values[1], "core": values[2]}
            for cpu, values in topology.items()
        },
    )
    write_json_new(evidence / "cgroup_limits.json", cgroup)
    write_json_new(evidence / "thread_selection_candidates.json", selection)
    write_json_new(
        evidence / "scheduler_allocation.json",
        {
            "detected": False,
            "allocated_cpus": None,
            "environment": {
                key: value
                for key, value in os.environ.items()
                if key.startswith(("SLURM_", "PBS_", "LSB_", "SGE_", "NSLOTS"))
            },
        },
    )
    write_json_new(
        evidence / "memory_snapshot.json",
        {
            "available_bytes": available,
            "cgroup_limit_bytes": cgroup_limit,
            "memory_safe_mb": selection["memory_safe_mb"],
            "raw_free": memory,
        },
    )
    write_json_new(
        evidence / "process_affinity.json",
        {
            "allowed_cpu_list": format_cpu_list(allowed),
            "allowed_logical": len(allowed),
        },
    )
    print(json.dumps(selection, sort_keys=True))
    return 0


def parse_xyz(raw: bytes) -> tuple[tuple[str, ...], list[list[float]]]:
    lines = raw.decode("ascii", errors="strict").splitlines()
    count = int(lines[0])
    if len(lines) != count + 2:
        raise R1Error("XYZ line count drifted")
    elements: list[str] = []
    coordinates: list[list[float]] = []
    for line in lines[2:]:
        fields = line.split()
        if len(fields) != 4:
            raise R1Error("invalid XYZ row")
        xyz = [float(value) for value in fields[1:]]
        if not all(math.isfinite(value) for value in xyz):
            raise R1Error("non-finite XYZ")
        elements.append(fields[0])
        coordinates.append(xyz)
    return tuple(elements), coordinates


def configure_runtime(*, threads: int, cpus: tuple[int, ...]) -> dict[str, object]:
    for key, value in thread_environment(threads).items():
        os.environ[key] = value
    linux_os = cast(Any, os)
    linux_os.sched_setaffinity(0, set(cpus))
    actual_affinity = tuple(sorted(linux_os.sched_getaffinity(0)))
    if actual_affinity != cpus:
        raise R1Error("CPU_THREAD_BINDING_MISMATCH")
    return {
        "requested_threads": threads,
        "allowed_cpu_list": format_cpu_list(cpus),
        "process_affinity": format_cpu_list(actual_affinity),
        "thread_environment": thread_environment(threads),
    }


@contextlib.contextmanager
def thread_sampler(interval: float = 0.05) -> Iterator[dict[str, int]]:
    state = {"maximum_observed_process_threads": len(list(Path("/proc/self/task").iterdir()))}
    stopped = threading.Event()

    def sample() -> None:
        while not stopped.wait(interval):
            count = len(list(Path("/proc/self/task").iterdir()))
            state["maximum_observed_process_threads"] = max(
                state["maximum_observed_process_threads"], count
            )

    worker = threading.Thread(target=sample, name="p01-r1-thread-sampler", daemon=True)
    worker.start()
    try:
        yield state
    finally:
        stopped.set()
        worker.join(timeout=2.0)


def build_mean_field(
    *, raw_xyz: bytes, grid_level: int, memory_mb: int, threads: int
) -> tuple[Any, Any, Any]:
    from pyscf import dft, gto, lib  # type: ignore[import-untyped]

    elements, coordinates = parse_xyz(raw_xyz)
    molecule = gto.M(
        atom=list(zip(elements, coordinates, strict=True)),
        unit="Angstrom",
        basis=PARENT_BASIS,
        charge=1,
        spin=0,
        max_memory=memory_mb,
        verbose=4,
    )
    if molecule.nelectron != 160 or molecule.natm != 26:
        raise R1Error("molecule identity drifted")
    lib.num_threads(threads)
    if lib.num_threads() != threads:
        raise R1Error("CPU_THREAD_BINDING_MISMATCH")
    mean_field = dft.RKS(molecule)
    mean_field.xc = PARENT_XC
    mean_field.grids.level = grid_level
    mean_field.conv_tol = SCF_TOLERANCE
    mean_field.max_cycle = SCF_MAX_CYCLES
    mean_field.disp = "d3bj"
    if mean_field.do_nlc():
        raise R1Error("VV10 unexpectedly enabled")
    return molecule, mean_field, lib


def scf_calibration(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(strict=True)
    cpus = parse_cpu_list(args.cpu_list)
    runtime = configure_runtime(threads=args.threads, cpus=cpus)
    raw = read_regular(Path(args.xyz).resolve(strict=True))
    if sha256_bytes(raw) != INPUT_SHA256:
        raise R1Error("fixed geometry drifted")
    _, mean_field, lib = build_mean_field(
        raw_xyz=raw,
        grid_level=4,
        memory_mb=args.memory_mb,
        threads=args.threads,
    )
    mean_field.max_cycle = 1
    before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.monotonic()
    with thread_sampler() as sample:
        energy = float(mean_field.kernel())
    wall = time.monotonic() - started
    after = resource.getrusage(resource.RUSAGE_SELF)
    payload = {
        "schema_version": SCHEMA,
        "kind": "smt_calibration",
        "threads": args.threads,
        "cpu_list": format_cpu_list(cpus),
        "memory_mb": args.memory_mb,
        "grid_level": 4,
        "max_scf_cycles": 1,
        "completed_scf_cycles": int(mean_field.cycles),
        "expected_nonconverged": not bool(mean_field.converged),
        "last_energy_hartree": energy,
        "wall_seconds": wall,
        "process_user_cpu_seconds": after.ru_utime - before.ru_utime,
        "process_system_cpu_seconds": after.ru_stime - before.ru_stime,
        "maximum_rss_kb": int(after.ru_maxrss),
        "pyscf_threads": int(lib.num_threads()),
        "runtime": runtime,
        "thread_observation": sample,
        "scientific_result": False,
        "production_accepted": False,
    }
    write_json_new(root / f"calibration_{args.name}.json", payload)
    return 0


def select_threads(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(strict=True)
    physical = json.loads(read_regular(root / "calibration_physical.json"))
    logical_path = root / "calibration_logical.json"
    logical = json.loads(read_regular(logical_path)) if logical_path.exists() else None
    physical_wall = float(physical["wall_seconds"])
    use_logical = False
    reason = "SMT_BENCHMARK_INCONCLUSIVE"
    if logical is not None:
        logical_wall = float(logical["wall_seconds"])
        energy_equal = (
            abs(float(logical["last_energy_hartree"]) - float(physical["last_energy_hartree"]))
            <= 1.0e-10
        )
        if energy_equal and logical_wall <= physical_wall * (1.0 - SMT_IMPROVEMENT_FRACTION):
            use_logical = True
            reason = "logical_threads_at_least_5_percent_faster"
        elif energy_equal:
            reason = "logical_threads_not_5_percent_faster"
        else:
            reason = "SMT_BENCHMARK_NUMERICAL_MISMATCH"
    chosen = logical if use_logical else physical
    if chosen is None:
        raise R1Error("SMT selection has no physical fallback")
    payload = {
        "schema_version": SCHEMA,
        "smt_improvement_threshold_fraction": SMT_IMPROVEMENT_FRACTION,
        "physical_wall_seconds": physical_wall,
        "logical_wall_seconds": None if logical is None else float(logical["wall_seconds"]),
        "use_smt": use_logical,
        "reason": reason,
        "n_threads": int(chosen["threads"]),
        "allowed_cpu_list": chosen["cpu_list"],
        "memory_mb": int(chosen["memory_mb"]),
        "production_accepted": False,
    }
    write_json_new(root / "thread_selection.json", payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def save_density_new(path: Path, density: Any) -> dict[str, object]:
    import numpy as np

    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            np.save(handle, density, allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    fsync_directory(path.parent)
    return {"bytes": path.stat().st_size, "sha256": sha256_bytes(read_regular(path))}


def run_level(
    *,
    raw_xyz: bytes,
    grid_level: int,
    memory_mb: int,
    threads: int,
    dm0: Any | None,
) -> tuple[dict[str, object], Any]:
    import numpy as np
    from pyscf.dft.rks import parse_dft  # type: ignore[import-untyped]
    from pyscf.dispersion.dftd3 import DFTD3Dispersion  # type: ignore[import-untyped]

    molecule, mean_field, lib = build_mean_field(
        raw_xyz=raw_xyz,
        grid_level=grid_level,
        memory_mb=memory_mb,
        threads=threads,
    )
    before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.monotonic()
    with thread_sampler() as sample:
        energy = float(mean_field.kernel(dm0=dm0))
        if not mean_field.converged or not math.isfinite(energy):
            raise R1Error(f"grid {grid_level} SCF did not converge")
        gradient = np.asarray(mean_field.nuc_grad_method().kernel(), dtype=float)
    wall = time.monotonic() - started
    after = resource.getrusage(resource.RUSAGE_SELF)
    if gradient.shape != (26, 3) or not np.isfinite(gradient).all():
        raise R1Error(f"grid {grid_level} gradient invalid")
    components = {
        key: float(mean_field.scf_summary[key])
        for key in ("nuc", "e1", "coul", "exc", "dispersion")
    }
    reconstruction = sum(components.values())
    if abs(reconstruction - energy) > 1.0e-12:
        raise R1Error("energy reconstruction failed")
    d3 = DFTD3Dispersion(molecule, xc=PARENT_D3_METHOD, version="d3bj", atm=False).get_dispersion(
        grad=True
    )
    d3_energy = float(d3["energy"])
    d3_gradient = np.asarray(d3["gradient"], dtype=float)
    if not math.isfinite(d3_energy) or not np.isfinite(d3_gradient).all():
        raise R1Error("D3 result invalid")
    if abs(d3_energy - components["dispersion"]) > 1.0e-12:
        raise R1Error("D3 energy mismatch")
    parsed_xc, parsed_nlc, parsed_dispersion = parse_dft(PARENT_XC)
    payload = {
        "schema_version": SCHEMA,
        "grid_level": grid_level,
        "scf_converged": True,
        "scf_cycles": int(mean_field.cycles),
        "energy_hartree": energy,
        "components_hartree": components,
        "reconstructed_energy_hartree": reconstruction,
        "d3_energy_hartree": d3_energy,
        "d3_gradient_hartree_per_bohr": d3_gradient.tolist(),
        "gradient_hartree_per_bohr": gradient.tolist(),
        "gradient_rms_hartree_per_bohr": float(np.sqrt(np.mean(gradient**2))),
        "gradient_max_hartree_per_bohr": float(np.max(np.abs(gradient))),
        "gradient_finite": True,
        "grid_point_count": int(mean_field.grids.coords.shape[0]),
        "wall_seconds": wall,
        "process_user_cpu_seconds": after.ru_utime - before.ru_utime,
        "process_system_cpu_seconds": after.ru_stime - before.ru_stime,
        "maximum_rss_kb": int(after.ru_maxrss),
        "pyscf_threads": int(lib.num_threads()),
        "maximum_observed_process_threads": sample["maximum_observed_process_threads"],
        "initial_guess_source": "minao" if dm0 is None else "converged_grid3_density",
        "parsed_xc": parsed_xc,
        "parsed_nlc": parsed_nlc,
        "parsed_dispersion": parsed_dispersion,
        "vv10": bool(mean_field.do_nlc()),
        "atm": False,
    }
    return payload, np.asarray(mean_field.make_rdm1(), dtype=float)


def finite_payload(payload: dict[str, object], key: str) -> float:
    value = payload[key]
    if type(value) not in {int, float}:
        raise R1Error(f"{key} is not numeric")
    result = float(cast(float, value))
    if not math.isfinite(result):
        raise R1Error(f"{key} is not finite")
    return result


def integer_payload(payload: dict[str, object], key: str) -> int:
    value = payload[key]
    if type(value) is not int:
        raise R1Error(f"{key} is not an integer")
    return value


def grid_audit(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve(strict=True)
    cpus = parse_cpu_list(args.cpu_list)
    runtime = configure_runtime(threads=args.threads, cpus=cpus)
    raw = read_regular(Path(args.xyz).resolve(strict=True))
    if sha256_bytes(raw) != INPUT_SHA256:
        raise R1Error("fixed geometry drifted")
    actual_source_sha256 = sha256_bytes(read_regular(Path(args.audit_source).resolve(strict=True)))
    if actual_source_sha256 != args.audit_source_sha256:
        raise R1Error("audit source drifted")
    audit_root = root / "grid4_audit"
    make_directory(audit_root / "input")
    write_new(audit_root / "input" / "cation_aimnet2_final.xyz", raw)
    run_config = {
        "schema_version": SCHEMA,
        "xyz_sha256": INPUT_SHA256,
        "weight_sha256": WEIGHT_SHA256,
        "functional": PARENT_XC,
        "basis": PARENT_BASIS,
        "dispersion": "two-body D3(BJ)",
        "atm": False,
        "vv10": False,
        "grid_levels": [3, 4],
        "grid4_initial_guess": "converged_grid3_density",
        "scf_conv_tol": SCF_TOLERANCE,
        "scf_max_cycles": SCF_MAX_CYCLES,
        "threads": args.threads,
        "cpu_list": format_cpu_list(cpus),
        "memory_mb": args.memory_mb,
        "runtime": runtime,
        "audit_source_sha256": args.audit_source_sha256,
        "interpreter_sha256": args.interpreter_sha256,
        "retry": False,
        "production_accepted": False,
    }
    protocol_sha = sha256_bytes(canonical_json(run_config))
    run_config["protocol_sha256"] = protocol_sha
    write_json_new(audit_root / "run_config.json", run_config)
    level3, density = run_level(
        raw_xyz=raw,
        grid_level=3,
        memory_mb=args.memory_mb,
        threads=args.threads,
        dm0=None,
    )
    write_json_new(audit_root / "grid3_result.json", level3)
    density_identity = save_density_new(audit_root / "grid3_density.npy", density)
    trace = float(__import__("numpy").trace(density))
    density_binding = {
        "schema_version": SCHEMA,
        "source": "converged_grid3_density",
        "density": density_identity,
        "ao_dimension": list(density.shape),
        "electron_count": 160,
        "density_trace_raw": trace,
        "note": "AO density trace is not electron count without overlap matrix",
        "grid3_result_sha256": sha256_bytes(canonical_json(level3)),
    }
    write_json_new(audit_root / "grid3_density_binding.json", density_binding)
    level4, _ = run_level(
        raw_xyz=raw,
        grid_level=4,
        memory_mb=args.memory_mb,
        threads=args.threads,
        dm0=density,
    )
    level4["grid3_density_sha256"] = density_identity["sha256"]
    write_json_new(audit_root / "result.json", level4)
    comparison = {
        "schema_version": SCHEMA,
        "energy_delta_hartree_grid4_minus_grid3": finite_payload(level4, "energy_hartree")
        - finite_payload(level3, "energy_hartree"),
        "energy_delta_kcal_grid4_minus_grid3": (
            finite_payload(level4, "energy_hartree") - finite_payload(level3, "energy_hartree")
        )
        * 627.509474,
        "gradient_rms_delta_hartree_per_bohr": finite_payload(
            level4, "gradient_rms_hartree_per_bohr"
        )
        - finite_payload(level3, "gradient_rms_hartree_per_bohr"),
        "gradient_max_delta_hartree_per_bohr": finite_payload(
            level4, "gradient_max_hartree_per_bohr"
        )
        - finite_payload(level3, "gradient_max_hartree_per_bohr"),
        "scf_cycle_delta": integer_payload(level4, "scf_cycles")
        - integer_payload(level3, "scf_cycles"),
        "wall_ratio_grid4_over_grid3": finite_payload(level4, "wall_seconds")
        / finite_payload(level3, "wall_seconds"),
        "preregistered_scientific_threshold": False,
        "selected_grid": 4,
        "selection_reason": "more robust grid selected because no preregistered threshold exists",
    }
    write_json_new(root / "grid_comparison" / "comparison.json", comparison)
    protocol_lock = {
        "schema_version": SCHEMA,
        "status": "GRID_AUDIT_PASS",
        "functional": PARENT_XC,
        "basis": PARENT_BASIS,
        "dispersion": "two-body D3(BJ)",
        "atm": False,
        "vv10": False,
        "grid": 4,
        "scf_tolerance": SCF_TOLERANCE,
        "thread_count": args.threads,
        "allowed_cpu_list": format_cpu_list(cpus),
        "memory_mb": args.memory_mb,
        "interpreter_sha256": args.interpreter_sha256,
        "python": platform.python_version(),
        "pyscf": metadata.version("pyscf"),
        "pyscf_dispersion": metadata.version("pyscf-dispersion"),
        "libxc": __import__("pyscf.dft.libxc", fromlist=["__version__"]).__version__,
        "protocol_sha256": protocol_sha,
        "grid3_result_sha256": sha256_bytes(canonical_json(level3)),
        "grid4_result_sha256": sha256_bytes(canonical_json(level4)),
        "comparison_sha256": sha256_bytes(canonical_json(comparison)),
        "retry": False,
        "production_accepted": False,
    }
    write_json_new(root / "grid_comparison" / "protocol_lock.json", protocol_lock)
    write_json_new(
        root / "result.json",
        {
            "schema_version": SCHEMA,
            "status": "GRID_AUDIT_PASS",
            "grid_audit": level4,
            "comparison": comparison,
            "protocol_lock": protocol_lock,
            "group_a": "not_started",
            "group_b": "not_started",
            "retry": False,
            "production_accepted": False,
        },
    )
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    discovery = sub.add_parser("discover")
    discovery.add_argument("--root", required=True)
    calibration = sub.add_parser("calibrate")
    for name in ("root", "name", "cpu-list", "xyz"):
        calibration.add_argument(f"--{name}", required=True)
    calibration.add_argument("--threads", type=int, required=True)
    calibration.add_argument("--memory-mb", type=int, required=True)
    selection = sub.add_parser("select-threads")
    selection.add_argument("--root", required=True)
    audit = sub.add_parser("grid-audit")
    for name in (
        "root",
        "cpu-list",
        "xyz",
        "audit-source",
        "audit-source-sha256",
        "interpreter-sha256",
    ):
        audit.add_argument(f"--{name}", required=True)
    audit.add_argument("--threads", type=int, required=True)
    audit.add_argument("--memory-mb", type=int, required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "discover":
        return discover(args)
    if args.command == "calibrate":
        return scf_calibration(args)
    if args.command == "select-threads":
        return select_threads(args)
    if args.command == "grid-audit":
        return grid_audit(args)
    raise R1Error("unknown command")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise
