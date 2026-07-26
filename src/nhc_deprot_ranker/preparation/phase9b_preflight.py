"""Phase 9B fresh read-only server preflight.

Builds the inspection command and strictly parses its result.  It performs no SSH
itself: the caller injects the command runner, so every test drives this module
with a fake and nothing here reaches a network.

Two chains' worth of expectations are checked before any write is contemplated:
the PySCF stack the residual optimization needs, and the AIMNet2 stack the
preoptimization needs.  Both route roots must be absent, because an existing root
means either a prior attempt or a name collision, and neither may be overwritten.

Everything is read-only by construction.  The remote script inspects and prints;
it creates no file, no directory, and no cache, and it never imports a chemistry
kernel or evaluates anything.

No chemistry import, no compute, no label.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol, cast

from nhc_deprot_ranker.quantum.phase9b_permit import REMOTE_ROOT_RELATIVE
from nhc_deprot_ranker.quantum.phase9b_resources import (
    AIMNET2_STAGE_BUDGET,
    PHASE9B_RESOURCES,
)

# Running a real preflight is a separate read-only authorization.
EXECUTION_AUTHORIZED: Final[bool] = False

PREFLIGHT_SCHEMA_VERSION: Final = "phase9b.readonly_preflight.v1"

_MAX_STDOUT_BYTES: Final = 1024 * 1024
_MAX_STDERR_BYTES: Final = 64 * 1024

# Verified live by the Phase 9A-R inspection; a preflight that disagrees means the
# environment moved under us and the run must stop rather than adapt.
EXPECTED_TORCH_VERSION: Final = "2.8.0+cu128"
EXPECTED_ASE_VERSION: Final = "3.29.0"
EXPECTED_AIMNET_VERSION: Final = "0.2.0"
EXPECTED_WEIGHT_SHA256: Final = "f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28"
EXPECTED_WEIGHT_BYTES: Final = 8836941

# Recorded by the Phase 8A read-only API inspection.
EXPECTED_PYSCF_VERSION: Final = "2.13.1"
EXPECTED_GEOMETRIC_VERSION: Final = "1.1.1"
EXPECTED_DISPERSION_VERSION: Final = "1.5.0"

_REQUIRED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "torch_version",
        "torch_sm70",
        "ase_version",
        "aimnet_version",
        "weight_sha256",
        "weight_bytes",
        "pyscf_version",
        "geometric_version",
        "dispersion_version",
        "free_gpu_indices",
        "memory_available_kib",
        "disk_available_bytes",
        "direct_root_absent",
        "assisted_root_absent",
        "wrote_nothing",
    }
)

_MIN_MEMORY_AVAILABLE_KIB: Final = 32 * 1024 * 1024
_MIN_DISK_AVAILABLE_BYTES: Final = 20 * 1024 * 1024 * 1024


class Phase9BPreflightError(RuntimeError):
    """The preflight could not prove the environment matches the frozen plan."""


class Phase9BPreflightNotAuthorizedError(Phase9BPreflightError):
    """A real preflight was attempted while the source gate is closed."""


class CommandRunner(Protocol):
    """Injectable seam.  Production supplies SSH; tests supply a fake."""

    def __call__(self, command: Sequence[str], *, timeout: float) -> tuple[int, bytes, bytes]: ...


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """A passed preflight, with only non-private facts retained."""

    torch_version: str
    ase_version: str
    aimnet_version: str
    pyscf_version: str
    geometric_version: str
    dispersion_version: str
    weight_sha256: str
    selected_gpu_index: int
    free_gpu_count: int
    memory_available_kib: int
    disk_available_bytes: int
    wrote_nothing: bool


# Read-only by construction: it prints and exits.  No mkdir, no open for write, no
# model load, no kernel call, and offline flags are set before any import.
REMOTE_INSPECTOR_SOURCE: Final = r"""import hashlib, importlib, json, os, shutil, subprocess, sys
out = {"schema_version": "phase9b.readonly_preflight.v1", "wrote_nothing": True}
def ver(name):
    try:
        m = importlib.import_module(name)
    except BaseException:
        return None
    v = getattr(m, "__version__", None)
    if v is None:
        try:
            import importlib.metadata as md
            v = md.version(name)
        except BaseException:
            v = None
    return v
out["torch_version"] = ver("torch")
try:
    import torch
    out["torch_sm70"] = "sm_70" in torch.cuda.get_arch_list()
except BaseException:
    out["torch_sm70"] = False
out["ase_version"] = ver("ase")
out["aimnet_version"] = ver("aimnet")
out["pyscf_version"] = ver("pyscf")
out["geometric_version"] = ver("geometric")
try:
    import importlib.metadata as md
    out["dispersion_version"] = md.version("pyscf-dispersion")
except BaseException:
    out["dispersion_version"] = None
weight = os.path.join(os.path.expanduser("~"), ".cache", "aimnet", "aimnet2_wb97m_d3_0.pt")
if os.path.isfile(weight) and not os.path.islink(weight):
    h = hashlib.sha256()
    with open(weight, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    out["weight_sha256"] = h.hexdigest()
    out["weight_bytes"] = os.path.getsize(weight)
else:
    out["weight_sha256"] = None
    out["weight_bytes"] = 0
free = []
try:
    q = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, timeout=30, check=False,
    )
    for line in q.stdout.decode("utf-8", "replace").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) < 100:
            free.append(int(parts[0]))
except BaseException:
    free = []
out["free_gpu_indices"] = sorted(free)
avail = 0
try:
    with open("/proc/meminfo", "r") as fh:
        for line in fh:
            if line.startswith("MemAvailable:"):
                avail = int(line.split()[1])
                break
except BaseException:
    avail = 0
out["memory_available_kib"] = avail
root = sys.argv[1]
try:
    out["disk_available_bytes"] = shutil.disk_usage(root).free
except BaseException:
    out["disk_available_bytes"] = 0
rel = sys.argv[2]
out["direct_root_absent"] = not os.path.lexists(os.path.join(root, rel, "direct"))
out["assisted_root_absent"] = not os.path.lexists(os.path.join(root, rel, "assisted"))
print(json.dumps(out, sort_keys=True))
"""


def build_preflight_command(*, ssh_alias: str, project_root: str) -> tuple[str, ...]:
    """One bounded SSH invocation that inspects and prints, nothing else."""

    if not ssh_alias or not project_root.startswith("/"):
        raise Phase9BPreflightError("preflight needs an ssh alias and an absolute project root")
    remote = " && ".join(
        (
            f"cd {shlex.quote(project_root)}",
            "export PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 "
            "TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1",
            "exec python3 -I -B -c "
            + shlex.quote(REMOTE_INSPECTOR_SOURCE)
            + f" {shlex.quote(project_root)} {shlex.quote(REMOTE_ROOT_RELATIVE)}",
        )
    )
    return (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ConnectTimeout=15",
        ssh_alias,
        remote,
    )


def _strict_json_object(raw: bytes) -> dict[str, object]:
    if not raw or len(raw) > _MAX_STDOUT_BYTES:
        raise Phase9BPreflightError("preflight stdout size is invalid")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        seen: dict[str, object] = {}
        for key, value in pairs:
            if key in seen:
                raise Phase9BPreflightError(f"duplicate preflight key: {key}")
            seen[key] = value
        return seen

    def reject_nonfinite(value: str) -> object:
        raise Phase9BPreflightError(f"non-finite preflight value: {value}")

    try:
        decoded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except Phase9BPreflightError:
        raise
    except (UnicodeDecodeError, ValueError) as exc:
        raise Phase9BPreflightError("preflight stdout is not strict JSON") from exc
    if not isinstance(decoded, dict):
        raise Phase9BPreflightError("preflight stdout must be one JSON object")
    return cast(dict[str, object], decoded)


def evaluate_preflight(payload: Mapping[str, object]) -> PreflightResult:
    """Apply every frozen gate.  Any failure stops the phase; none is relaxed."""

    missing = sorted(_REQUIRED_KEYS - set(payload))
    if missing:
        raise Phase9BPreflightError(f"preflight payload is missing keys: {missing[0]}")
    extra = sorted(set(payload) - _REQUIRED_KEYS)
    if extra:
        raise Phase9BPreflightError(f"preflight payload has unexpected keys: {extra[0]}")
    if payload["schema_version"] != PREFLIGHT_SCHEMA_VERSION:
        raise Phase9BPreflightError("preflight schema version drifted")
    if payload["wrote_nothing"] is not True:
        raise Phase9BPreflightError("preflight did not prove it wrote nothing")

    for key, expected in (
        ("torch_version", EXPECTED_TORCH_VERSION),
        ("ase_version", EXPECTED_ASE_VERSION),
        ("aimnet_version", EXPECTED_AIMNET_VERSION),
        ("pyscf_version", EXPECTED_PYSCF_VERSION),
        ("geometric_version", EXPECTED_GEOMETRIC_VERSION),
        ("dispersion_version", EXPECTED_DISPERSION_VERSION),
    ):
        if payload[key] != expected:
            raise Phase9BPreflightError(f"{key} drifted from the recorded environment")
    if payload["torch_sm70"] is not True:
        raise Phase9BPreflightError("torch no longer supports the Volta architecture")

    if payload["weight_sha256"] != EXPECTED_WEIGHT_SHA256:
        raise Phase9BPreflightError("AIMNet2 weight SHA256 drifted")
    if payload["weight_bytes"] != EXPECTED_WEIGHT_BYTES:
        raise Phase9BPreflightError("AIMNet2 weight byte size drifted")

    if payload["direct_root_absent"] is not True:
        raise Phase9BPreflightError("the direct route root already exists")
    if payload["assisted_root_absent"] is not True:
        raise Phase9BPreflightError("the assisted route root already exists")

    free = payload["free_gpu_indices"]
    if not isinstance(free, list) or not all(type(index) is int for index in free):
        raise Phase9BPreflightError("free GPU index list is malformed")
    if len(free) < int(cast(int, AIMNET2_STAGE_BUDGET["gpu_count"])):
        raise Phase9BPreflightError("no free GPU satisfies the frozen stage budget")

    memory = payload["memory_available_kib"]
    disk = payload["disk_available_bytes"]
    if type(memory) is not int or memory < _MIN_MEMORY_AVAILABLE_KIB:
        raise Phase9BPreflightError("available memory is below the frozen floor")
    if type(disk) is not int or disk < _MIN_DISK_AVAILABLE_BYTES:
        raise Phase9BPreflightError("available disk is below the frozen floor")

    return PreflightResult(
        torch_version=cast(str, payload["torch_version"]),
        ase_version=cast(str, payload["ase_version"]),
        aimnet_version=cast(str, payload["aimnet_version"]),
        pyscf_version=cast(str, payload["pyscf_version"]),
        geometric_version=cast(str, payload["geometric_version"]),
        dispersion_version=EXPECTED_DISPERSION_VERSION,
        weight_sha256=EXPECTED_WEIGHT_SHA256,
        # Lowest free index, chosen deterministically so the record is reproducible.
        selected_gpu_index=min(cast(list[int], free)),
        free_gpu_count=len(cast(list[int], free)),
        memory_available_kib=memory,
        disk_available_bytes=disk,
        wrote_nothing=True,
    )


def run_preflight(
    *,
    ssh_alias: str,
    project_root: str,
    run_command: CommandRunner | None = None,
    timeout_seconds: float = 180.0,
) -> PreflightResult:
    """Issue one bounded read-only inspection and evaluate every frozen gate."""

    if run_command is None and EXECUTION_AUTHORIZED is not True:
        raise Phase9BPreflightNotAuthorizedError(
            "a real Phase 9B preflight needs explicit read-only authorization"
        )
    if not 0.0 < timeout_seconds <= 600.0:
        raise ValueError("preflight timeout must be in (0, 600]")
    if run_command is None:  # pragma: no cover - unreachable while the gate is closed
        raise Phase9BPreflightNotAuthorizedError("no production preflight runner is wired")

    command = build_preflight_command(ssh_alias=ssh_alias, project_root=project_root)
    returncode, stdout, stderr = run_command(command, timeout=timeout_seconds)
    if len(stderr) > _MAX_STDERR_BYTES:
        raise Phase9BPreflightError("preflight stderr exceeded its bound")
    if returncode != 0:
        raise Phase9BPreflightError(f"preflight exited nonzero: {returncode}")
    if stderr:
        raise Phase9BPreflightError("preflight produced unexpected stderr")
    return evaluate_preflight(_strict_json_object(stdout))


__all__ = [
    "EXECUTION_AUTHORIZED",
    "EXPECTED_AIMNET_VERSION",
    "EXPECTED_ASE_VERSION",
    "EXPECTED_TORCH_VERSION",
    "EXPECTED_WEIGHT_BYTES",
    "EXPECTED_WEIGHT_SHA256",
    "PREFLIGHT_SCHEMA_VERSION",
    "REMOTE_INSPECTOR_SOURCE",
    "CommandRunner",
    "Phase9BPreflightError",
    "Phase9BPreflightNotAuthorizedError",
    "PreflightResult",
    "build_preflight_command",
    "evaluate_preflight",
    "run_preflight",
]


_ = PHASE9B_RESOURCES  # frozen budget is imported for provenance of the floors
