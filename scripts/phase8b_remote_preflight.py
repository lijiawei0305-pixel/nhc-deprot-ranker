#!/usr/bin/env python3
"""Read-only Phase 8B server inspection; never construct a chemistry object."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import inspect
import json
import os
import shutil
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Final

SCHEMA_VERSION: Final = "phase8b.remote-preflight.v1"
EXPECTED_PHASE7_FILE_COUNT: Final = 27
EXPECTED_PHASE7_TREE_SHA256: Final = (
    "9b92a1f453274995661bd262e607239a86f4992bf4cc2809a311207dceadbecb"
)
EXPECTED_PHASE8B_RELATIVE: Final = "data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001"
EXPECTED_VERSIONS: Final[dict[str, str]] = {
    "python": "3.11.15",
    "pyscf": "2.13.1",
    "geometric": "1.1.1",
    "pyscf_dispersion": "1.5.0",
}
EXPECTED_PROJECT_SOURCE_SHA256: Final[dict[str, str]] = {
    "env/envs/molenv.sh": "e9b3e124f53a10e84c43cfc71a56af3ddd56a86f082610593d2b23ed9692ea6f",
    "scripts/mol/gen_3d.py": "d23c7ad9a6e35948949f6485b53caafb0f3f5705148f642e3a4a30fb589a946a",
    "scripts/mol/structure_gen.py": (
        "a50b50b9967ac9e8203b398fe69f3daebf40a144f37dae8e0aa086e613ad1365"
    ),
}
EXPECTED_INSTALLED_SOURCE_SHA256: Final[dict[str, str]] = {
    "pyscf.scf.hf": "27a7a235010f03a11df9c4c033ad23691997855acf89eb2b31948be49ea80158",
    "pyscf.scf.dispersion": ("8c4c728c9f2a60cf20a41c003ed89d85adfa0d049c47be1f89aa6b3dbbb41cd1"),
    "pyscf.grad.rhf": "7627fb2b65a180436f33c98a4946060687cf57dcd4b5ae03302dc08086b082e2",
    "pyscf.grad.dispersion": ("508eb61a8fa976822adda3e23f9ef39bde7d44cf7435774dc8faae680d574c6c"),
    "pyscf.dispersion.dftd3": ("92dbfcdb71e67e4fa5e9a23054c871cb1a1efb731bf4ce6349e836c43d996dc9"),
}
EXPECTED_FUNCTION_SOURCE_SHA256: Final[dict[str, str]] = {
    "geometric_kernel": "491f31cd409af17da00d46112ad67f6b9456e41e95f07e68b169743eea015bee",
    "geometric_optimize": ("e66c264d4a4b016d8fd0d1f013aa0cb92c08b2ceec8755dfa1642f7e08c61c3f"),
    "dftd3_adapter": "134896ae9b832efe8dc079c5acaadbe9134a77b698d98f20cb4fc4b8b10434c3",
}
MIN_MEMORY_AVAILABLE_KIB: Final = 32 * 1024 * 1024
MIN_DISK_AVAILABLE_BYTES: Final = 20 * 1024 * 1024 * 1024
FIXED_CPUS: Final = frozenset({0, 1, 2, 3})


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_run_relative(raw: str, *, phase: str) -> PurePosixPath:
    relative = PurePosixPath(raw)
    expected_prefix = f"nhc_deprot_ranker_{phase}_"
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != raw
        or len(relative.parts) != 3
        or relative.parts[:2] != ("data", "runs")
        or not relative.parts[-1].startswith(expected_prefix)
    ):
        raise ValueError(f"unsafe {phase} run identity")
    return relative


def _phase7_tree(root: Path) -> tuple[int, str]:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("Phase 7 root is missing or unsafe")
    mapping: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("Phase 7 tree contains a symlink")
        if path.is_file():
            mapping[path.relative_to(root).as_posix()] = _sha256_file(path)
    canonical = json.dumps(
        mapping, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return len(mapping), _sha256_bytes(canonical)


def _import(name: str) -> ModuleType:
    module = importlib.import_module(name)
    if not isinstance(module, ModuleType):
        raise RuntimeError(f"import did not return a module: {name}")
    return module


def _module_file(module: ModuleType) -> Path:
    raw = getattr(module, "__file__", None)
    if not isinstance(raw, str):
        raise RuntimeError(f"module has no source file: {module.__name__}")
    path = Path(raw)
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"module source is unsafe: {module.__name__}")
    return path


def _function_sha256(value: object) -> str:
    return _sha256_bytes(inspect.getsource(value).encode("utf-8"))


def _parse_cpu_list(raw: str) -> frozenset[int]:
    cpus: set[int] = set()
    for part in raw.strip().split(","):
        if not part:
            continue
        bounds = part.split("-", maxsplit=1)
        start = int(bounds[0])
        stop = int(bounds[-1])
        if start < 0 or stop < start:
            raise ValueError("invalid online CPU range")
        cpus.update(range(start, stop + 1))
    return frozenset(cpus)


def _memory_available_kib() -> int:
    fields: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        name, _, remainder = line.partition(":")
        tokens = remainder.split()
        if tokens and tokens[0].isdigit():
            fields[name] = int(tokens[0])
    if "MemAvailable" not in fields:
        raise RuntimeError("MemAvailable is unavailable")
    return fields["MemAvailable"]


def _proc_stat_fields(pid: int) -> tuple[int, int, int, int]:
    raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    close = raw.rfind(")")
    if close < 0:
        raise RuntimeError("malformed proc stat")
    fields = raw[close + 2 :].split()
    if len(fields) < 22:
        raise RuntimeError("short proc stat")
    return int(fields[1]), int(fields[2]), int(fields[3]), int(fields[21])


def _process_snapshot(*, needles: tuple[str, ...], project_root: Path) -> dict[str, object]:
    current_uid = os.getuid()
    conflicts: list[int] = []
    rows: list[tuple[int, int, bool]] = []
    proc_root = Path("/proc")
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            if entry.stat().st_uid != current_uid:
                continue
            status = (entry / "status").read_text(encoding="ascii", errors="strict")
            rss_kib = 0
            for line in status.splitlines():
                if line.startswith("VmRSS:"):
                    rss_kib = int(line.split()[1])
                    break
            cmdline = (
                (entry / "cmdline")
                .read_bytes()
                .replace(b"\x00", b" ")
                .decode("utf-8", errors="replace")
            )
            cwd_under_project = False
            try:
                cwd = (entry / "cwd").resolve(strict=True)
                cwd.relative_to(project_root)
                cwd_under_project = True
            except (FileNotFoundError, PermissionError, ValueError):
                pass
            if any(needle in cmdline for needle in needles):
                conflicts.append(pid)
            rows.append((rss_kib, pid, cwd_under_project))
        except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError):
            continue
    rows.sort(reverse=True)
    return {
        "current_uid_process_count": len(rows),
        "conflict_pids": sorted(conflicts),
        "top_rss": [
            {"pid": pid, "rss_kib": rss, "cwd_under_project": under}
            for rss, pid, under in rows[:10]
        ],
    }


def inspect_server(phase7_relative: str, phase8b_relative: str) -> dict[str, object]:
    """Collect strict read-only facts from the already selected project root."""

    project_root = Path.cwd()
    if project_root.is_symlink() or not project_root.is_dir():
        raise RuntimeError("project root is unsafe")
    phase7 = project_root.joinpath(*_safe_run_relative(phase7_relative, phase="phase7").parts)
    phase8b_safe = _safe_run_relative(phase8b_relative, phase="phase8b")
    if phase8b_safe.as_posix() != EXPECTED_PHASE8B_RELATIVE:
        raise RuntimeError("Phase 8B root identity drifted")
    phase8b = project_root.joinpath(*phase8b_safe.parts)
    phase8b_parent = phase8b.parent
    if phase8b_parent.is_symlink() or not phase8b_parent.is_dir():
        raise RuntimeError("Phase 8B parent is unsafe")

    phase7_before = _phase7_tree(phase7)
    project_sources_before = {
        name: _sha256_file(project_root / name) for name in sorted(EXPECTED_PROJECT_SOURCE_SHA256)
    }

    modules = {
        name: _import(name)
        for name in (
            "pyscf.scf.hf",
            "pyscf.scf.dispersion",
            "pyscf.grad.rhf",
            "pyscf.grad.dispersion",
            "pyscf.dispersion.dftd3",
            "pyscf.geomopt.geometric_solver",
        )
    }
    installed_sources = {
        name: _sha256_file(_module_file(modules[name])) for name in EXPECTED_INSTALLED_SOURCE_SHA256
    }
    geometric_solver = modules["pyscf.geomopt.geometric_solver"]
    dftd3 = modules["pyscf.dispersion.dftd3"]
    functions = {
        "geometric_kernel": _function_sha256(vars(geometric_solver)["kernel"]),
        "geometric_optimize": _function_sha256(vars(geometric_solver)["optimize"]),
        "dftd3_adapter": _function_sha256(vars(dftd3)["DFTD3Dispersion"]),
    }

    nproc = os.cpu_count() or 0
    load1, load5, _ = os.getloadavg()
    memory_kib = _memory_available_kib()
    disk_bytes = shutil.disk_usage(project_root).free
    online = _parse_cpu_list(Path("/sys/devices/system/cpu/online").read_text(encoding="ascii"))
    process_snapshot = _process_snapshot(
        needles=("phase8b-qxh-smoke-v001", phase8b.as_posix()),
        project_root=project_root,
    )

    checks = {
        "phase7_exact_file_count": phase7_before[0] == EXPECTED_PHASE7_FILE_COUNT,
        "phase7_tree_matches": phase7_before[1] == EXPECTED_PHASE7_TREE_SHA256,
        "project_sources_match": project_sources_before == EXPECTED_PROJECT_SOURCE_SHA256,
        "installed_sources_match": installed_sources == EXPECTED_INSTALLED_SOURCE_SHA256,
        "function_sources_match": functions == EXPECTED_FUNCTION_SOURCE_SHA256,
        "versions_match": {
            "python": ".".join(str(item) for item in sys.version_info[:3]),
            "pyscf": importlib.metadata.version("pyscf"),
            "geometric": importlib.metadata.version("geometric"),
            "pyscf_dispersion": importlib.metadata.version("pyscf-dispersion"),
        }
        == EXPECTED_VERSIONS,
        "nproc_sufficient": nproc >= 8,
        "load1_sufficient": load1 <= 0.75 * nproc,
        "load5_sufficient": load5 <= 0.75 * nproc,
        "memory_sufficient": memory_kib >= MIN_MEMORY_AVAILABLE_KIB,
        "disk_sufficient": disk_bytes >= MIN_DISK_AVAILABLE_BYTES,
        "taskset_available": shutil.which("taskset") is not None,
        "fixed_cpus_online": FIXED_CPUS.issubset(online),
        "target_absent": not os.path.lexists(phase8b),
        "no_conflicting_process": process_snapshot["conflict_pids"] == [],
    }

    phase7_after = _phase7_tree(phase7)
    project_sources_after = {
        name: _sha256_file(project_root / name) for name in sorted(EXPECTED_PROJECT_SOURCE_SHA256)
    }
    checks["phase7_unchanged"] = phase7_before == phase7_after
    checks["project_sources_unchanged"] = project_sources_before == project_sources_after
    status = "passed" if all(checks.values()) else "failed"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "checks": checks,
        "versions": {
            "python": ".".join(str(item) for item in sys.version_info[:3]),
            "pyscf": importlib.metadata.version("pyscf"),
            "geometric": importlib.metadata.version("geometric"),
            "pyscf_dispersion": importlib.metadata.version("pyscf-dispersion"),
        },
        "phase7": {"file_count": phase7_before[0], "tree_sha256": phase7_before[1]},
        "project_source_sha256": project_sources_before,
        "installed_source_sha256": installed_sources,
        "function_source_sha256": functions,
        "resources": {
            "nproc": nproc,
            "load1": load1,
            "load5": load5,
            "memory_available_kib": memory_kib,
            "disk_available_bytes": disk_bytes,
            "online_cpus": sorted(online),
            "fixed_cpus": sorted(FIXED_CPUS),
        },
        "processes": process_snapshot,
        "safety": {
            "read_only": True,
            "molecule_constructed": False,
            "kernel_called": False,
            "gradient_called": False,
            "dispersion_evaluated": False,
            "hessian_called": False,
            "target_created": False,
        },
    }


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: phase8b_remote_preflight.py PHASE7_RELATIVE PHASE8B_RELATIVE")
    payload = inspect_server(sys.argv[1], sys.argv[2])
    print(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
