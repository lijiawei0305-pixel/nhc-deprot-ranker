"""Local launcher and validator for the Phase 8B read-only HPC preflight."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final, cast

from nhc_deprot_ranker.preparation.phase8b_remote import (
    Phase8BRemoteConfig,
    load_phase8b_remote_config,
)

_HEREDOC: Final = "__NHC_PHASE8B_PREFLIGHT_PY__"
_MAX_STDOUT_BYTES: Final = 1024 * 1024
_MAX_STDERR_BYTES: Final = 64 * 1024
_FROZEN_INSPECTOR_PATH: Final = (
    Path(__file__).resolve().parents[3] / "scripts/phase8b_remote_preflight.py"
)
_FROZEN_INSPECTOR_SHA256: Final = "a3d11aa2c1ebfe7c284d199527b8ea8298a07ffbb895467ef4e6e240741f8415"
_EXPECTED_CHECKS: Final = {
    "phase7_exact_file_count",
    "phase7_tree_matches",
    "project_sources_match",
    "installed_sources_match",
    "function_sources_match",
    "versions_match",
    "nproc_sufficient",
    "load1_sufficient",
    "load5_sufficient",
    "memory_sufficient",
    "disk_sufficient",
    "taskset_available",
    "fixed_cpus_online",
    "target_absent",
    "no_conflicting_process",
    "phase7_unchanged",
    "project_sources_unchanged",
}
_EXPECTED_PHASE7: Final = {
    "file_count": 27,
    "tree_sha256": "9b92a1f453274995661bd262e607239a86f4992bf4cc2809a311207dceadbecb",
}
_EXPECTED_PROJECT_SOURCE_SHA256: Final = {
    "env/envs/molenv.sh": "e9b3e124f53a10e84c43cfc71a56af3ddd56a86f082610593d2b23ed9692ea6f",
    "scripts/mol/gen_3d.py": "d23c7ad9a6e35948949f6485b53caafb0f3f5705148f642e3a4a30fb589a946a",
    "scripts/mol/structure_gen.py": (
        "a50b50b9967ac9e8203b398fe69f3daebf40a144f37dae8e0aa086e613ad1365"
    ),
}
_EXPECTED_INSTALLED_SOURCE_SHA256: Final = {
    "pyscf.scf.hf": "27a7a235010f03a11df9c4c033ad23691997855acf89eb2b31948be49ea80158",
    "pyscf.scf.dispersion": "8c4c728c9f2a60cf20a41c003ed89d85adfa0d049c47be1f89aa6b3dbbb41cd1",
    "pyscf.grad.rhf": "7627fb2b65a180436f33c98a4946060687cf57dcd4b5ae03302dc08086b082e2",
    "pyscf.grad.dispersion": "508eb61a8fa976822adda3e23f9ef39bde7d44cf7435774dc8faae680d574c6c",
    "pyscf.dispersion.dftd3": ("92dbfcdb71e67e4fa5e9a23054c871cb1a1efb731bf4ce6349e836c43d996dc9"),
}
_EXPECTED_FUNCTION_SOURCE_SHA256: Final = {
    "geometric_kernel": "491f31cd409af17da00d46112ad67f6b9456e41e95f07e68b169743eea015bee",
    "geometric_optimize": "e66c264d4a4b016d8fd0d1f013aa0cb92c08b2ceec8755dfa1642f7e08c61c3f",
    "dftd3_adapter": "134896ae9b832efe8dc079c5acaadbe9134a77b698d98f20cb4fc4b8b10434c3",
}
_MIN_MEMORY_AVAILABLE_KIB: Final = 32 * 1024 * 1024
_MIN_DISK_AVAILABLE_BYTES: Final = 20 * 1024 * 1024 * 1024


class Phase8BPreflightError(RuntimeError):
    """The read-only preflight could not prove every frozen condition."""


class _CompletedProcessLike:
    returncode: int
    stdout: bytes
    stderr: bytes


RunCommand = Callable[..., _CompletedProcessLike]


def _strict_json_object(raw: bytes) -> dict[str, object]:
    if not raw or len(raw) > _MAX_STDOUT_BYTES:
        raise Phase8BPreflightError("preflight stdout size is invalid")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Phase8BPreflightError("preflight stdout is not UTF-8") from exc

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase8BPreflightError(f"duplicate preflight key: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        raise Phase8BPreflightError(f"non-finite preflight value: {value}")

    try:
        payload = json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except Phase8BPreflightError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise Phase8BPreflightError("preflight stdout is not strict JSON") from exc
    if not isinstance(payload, dict):
        raise Phase8BPreflightError("preflight stdout must be one JSON object")
    return cast(dict[str, object], payload)


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _require_exact_keys(payload: dict[str, object], expected: set[str], *, label: str) -> None:
    if set(payload) != expected:
        raise Phase8BPreflightError(f"{label} fields drifted")


def validate_phase8b_preflight(payload: dict[str, object]) -> dict[str, object]:
    """Validate the portable contract without importing any server dependency."""

    _require_exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "checks",
            "versions",
            "phase7",
            "project_source_sha256",
            "installed_source_sha256",
            "function_source_sha256",
            "resources",
            "processes",
            "safety",
        },
        label="preflight",
    )
    if payload["schema_version"] != "phase8b.remote-preflight.v1":
        raise Phase8BPreflightError("preflight schema_version drifted")
    checks = payload["checks"]
    if (
        not isinstance(checks, dict)
        or set(checks) != _EXPECTED_CHECKS
        or any(type(value) is not bool for value in checks.values())
    ):
        raise Phase8BPreflightError("preflight checks are invalid")
    if payload["status"] != "passed" or not all(checks.values()):
        failed = sorted(name for name, value in checks.items() if value is not True)
        raise Phase8BPreflightError(f"Phase 8B preflight failed: {failed}")
    versions = payload["versions"]
    if versions != {
        "python": "3.11.15",
        "pyscf": "2.13.1",
        "geometric": "1.1.1",
        "pyscf_dispersion": "1.5.0",
    }:
        raise Phase8BPreflightError("preflight versions drifted")
    if payload["phase7"] != _EXPECTED_PHASE7:
        raise Phase8BPreflightError("preflight Phase 7 identity drifted")
    if payload["project_source_sha256"] != _EXPECTED_PROJECT_SOURCE_SHA256:
        raise Phase8BPreflightError("preflight project source hashes drifted")
    if payload["installed_source_sha256"] != _EXPECTED_INSTALLED_SOURCE_SHA256:
        raise Phase8BPreflightError("preflight installed source hashes drifted")
    if payload["function_source_sha256"] != _EXPECTED_FUNCTION_SOURCE_SHA256:
        raise Phase8BPreflightError("preflight function source hashes drifted")
    safety = payload["safety"]
    expected_safety = {
        "read_only": True,
        "molecule_constructed": False,
        "kernel_called": False,
        "gradient_called": False,
        "dispersion_evaluated": False,
        "hessian_called": False,
        "target_created": False,
    }
    if safety != expected_safety:
        raise Phase8BPreflightError("preflight safety claims drifted")
    resources = payload["resources"]
    if not isinstance(resources, dict) or set(resources) != {
        "nproc",
        "load1",
        "load5",
        "memory_available_kib",
        "disk_available_bytes",
        "online_cpus",
        "fixed_cpus",
    }:
        raise Phase8BPreflightError("preflight resources are invalid")
    nproc = resources.get("nproc")
    load1 = resources.get("load1")
    load5 = resources.get("load5")
    memory_kib = resources.get("memory_available_kib")
    disk_bytes = resources.get("disk_available_bytes")
    fixed_cpus = resources.get("fixed_cpus")
    online_cpus = resources.get("online_cpus")
    if (
        type(nproc) is not int
        or nproc < 8
        or type(load1) not in {int, float}
        or type(load5) not in {int, float}
        or not math.isfinite(float(cast(float, load1)))
        or not math.isfinite(float(cast(float, load5)))
        or float(cast(float, load1)) > 0.75 * nproc
        or float(cast(float, load5)) > 0.75 * nproc
        or type(memory_kib) is not int
        or memory_kib < _MIN_MEMORY_AVAILABLE_KIB
        or type(disk_bytes) is not int
        or disk_bytes < _MIN_DISK_AVAILABLE_BYTES
        or fixed_cpus != [0, 1, 2, 3]
        or not isinstance(online_cpus, list)
        or any(type(cpu) is not int or cpu < 0 for cpu in online_cpus)
        or online_cpus != sorted(set(online_cpus))
    ):
        raise Phase8BPreflightError("preflight CPU evidence drifted")
    if not set(fixed_cpus).issubset(set(online_cpus)):
        raise Phase8BPreflightError("frozen CPUs are not online")
    processes = payload["processes"]
    if not isinstance(processes, dict) or set(processes) != {
        "current_uid_process_count",
        "conflict_pids",
        "top_rss",
    }:
        raise Phase8BPreflightError("preflight process evidence is invalid")
    process_count = processes.get("current_uid_process_count")
    top_rss = processes.get("top_rss")
    if (
        type(process_count) is not int
        or process_count < 0
        or processes.get("conflict_pids") != []
        or not isinstance(top_rss, list)
        or len(top_rss) > 10
    ):
        raise Phase8BPreflightError("preflight found a conflicting process")
    for row in top_rss:
        if (
            not isinstance(row, dict)
            or set(row) != {"pid", "rss_kib", "cwd_under_project"}
            or type(row.get("pid")) is not int
            or cast(int, row["pid"]) <= 0
            or type(row.get("rss_kib")) is not int
            or cast(int, row["rss_kib"]) < 0
            or type(row.get("cwd_under_project")) is not bool
        ):
            raise Phase8BPreflightError("preflight process row is invalid")
    return payload


def _read_bound_inspector(
    path: Path,
    *,
    expected_path: Path = _FROZEN_INSPECTOR_PATH,
    expected_sha256: str = _FROZEN_INSPECTOR_SHA256,
) -> bytes:
    """Read the one reviewed inspector without following or racing a replacement."""

    absolute = Path(os.path.abspath(path))
    expected = Path(os.path.abspath(expected_path))
    if absolute != expected or absolute.parent.resolve(strict=True) != absolute.parent:
        raise Phase8BPreflightError("preflight inspector path drifted")
    descriptor: int | None = None
    try:
        descriptor = os.open(absolute, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size <= 0
            or opened.st_size > _MAX_STDOUT_BYTES
        ):
            raise Phase8BPreflightError("preflight inspector filesystem identity drifted")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                raise Phase8BPreflightError("preflight inspector changed while being read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise Phase8BPreflightError("preflight inspector grew while being read")
        finished = os.fstat(descriptor)
        current = os.stat(absolute, follow_symlinks=False)
        stable = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns")
        identity = tuple(getattr(opened, field) for field in stable)
        if (
            tuple(getattr(finished, field) for field in stable) != identity
            or tuple(getattr(current, field) for field in stable) != identity
        ):
            raise Phase8BPreflightError("preflight inspector changed while being read")
        raw = b"".join(chunks)
    except Phase8BPreflightError:
        raise
    except OSError as exc:
        raise Phase8BPreflightError("preflight inspector cannot be read safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise Phase8BPreflightError("preflight inspector SHA256 drifted")
    return raw


def _remote_wrapper(*, inspector_source: bytes, config: Phase8BRemoteConfig) -> bytes:
    try:
        source = inspector_source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Phase8BPreflightError("preflight inspector must be UTF-8") from exc
    if _HEREDOC in source:
        raise Phase8BPreflightError("preflight inspector collides with heredoc marker")
    project = config.remote.project_root
    environment = config.remote.environment_relative
    phase7 = config.remote.phase7_run_relative
    phase8b = config.remote.phase8b_run_relative
    script = f"""set -euo pipefail
project_root={project!r}
environment_relative={environment!r}
phase7_relative={phase7!r}
phase8b_relative={phase8b!r}
test -d "$project_root"
test ! -L "$project_root"
cd "$project_root"
test -f "$environment_relative"
test ! -L "$environment_relative"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
set +u
source "$environment_relative" >/dev/null 2>&1
set -u
python -I -B - "$phase7_relative" "$phase8b_relative" <<'{_HEREDOC}'
{source}
{_HEREDOC}
"""
    return script.encode("utf-8")


def phase8b_preflight_command(config: Phase8BRemoteConfig) -> tuple[str, ...]:
    """Return the fixed SSH argv; the wrapper itself is supplied on stdin."""

    return (
        "ssh",
        *config.ssh_options(),
        config.connection.ssh_alias,
        "bash",
        "-s",
    )


def run_phase8b_preflight(
    *,
    config_path: Path,
    inspector_path: Path,
    timeout_seconds: float = 180.0,
    run_command: RunCommand | None = None,
) -> dict[str, object]:
    """Run the single approved read-only inspection and validate its JSON."""

    if timeout_seconds <= 0.0 or timeout_seconds > 300.0:
        raise ValueError("preflight timeout must be in (0, 300]")
    config = load_phase8b_remote_config(config_path)
    config.require_read_only_preflight()
    inspector = _read_bound_inspector(inspector_path)
    wrapper = _remote_wrapper(inspector_source=inspector, config=config)
    command_runner = cast(RunCommand, subprocess.run) if run_command is None else run_command
    try:
        completed = command_runner(
            phase8b_preflight_command(config),
            input=wrapper,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise Phase8BPreflightError("Phase 8B SSH preflight could not run") from exc
    if len(completed.stderr) > _MAX_STDERR_BYTES:
        raise Phase8BPreflightError("preflight stderr exceeded its bound")
    payload = _strict_json_object(completed.stdout)
    if completed.stdout != _canonical_json_bytes(payload):
        raise Phase8BPreflightError("preflight stdout is not canonical JSON")
    try:
        validated = validate_phase8b_preflight(payload)
    except Phase8BPreflightError:
        raise
    if completed.returncode != 0:
        raise Phase8BPreflightError(f"Phase 8B preflight exited nonzero: {completed.returncode}")
    return validated


def portable_phase8b_preflight(payload: dict[str, object]) -> dict[str, object]:
    """Remove ephemeral PIDs/RSS while retaining every execution gate fact."""

    validated = validate_phase8b_preflight(payload)
    portable = dict(validated)
    processes = validated["processes"]
    if not isinstance(processes, dict):
        raise Phase8BPreflightError("preflight processes are invalid")
    portable["processes"] = {
        "current_uid_process_count": processes.get("current_uid_process_count"),
        "conflict_count": len(cast(Sequence[object], processes.get("conflict_pids", []))),
        "rss_snapshot_recorded": isinstance(processes.get("top_rss"), list),
    }
    return portable


__all__ = [
    "Phase8BPreflightError",
    "phase8b_preflight_command",
    "portable_phase8b_preflight",
    "run_phase8b_preflight",
    "validate_phase8b_preflight",
]
