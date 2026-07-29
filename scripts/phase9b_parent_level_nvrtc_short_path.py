#!/usr/bin/env python3
"""Private short-path preparation and one-evaluation AIMNet2 smoke for P01-R2."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

SCHEMA: Final = "nhc-phase9b-parent-level-p01-r2-nvrtc-v1"
CONTROL_VARIABLE: Final = "NHC_P01R2_SHORT_TMP_ROOT"
REQUIRED_TEMP_VARIABLES: Final = (
    "TMPDIR",
    "TMP",
    "TEMP",
    "CUDA_CACHE_PATH",
    "TORCH_EXTENSIONS_DIR",
    "TRITON_CACHE_DIR",
    "XDG_CACHE_HOME",
    "NUMBA_CACHE_DIR",
)
SUBDIRECTORIES: Final = {
    "TMPDIR": "tmp",
    "TMP": "tmp",
    "TEMP": "tmp",
    "CUDA_CACHE_PATH": "cuda",
    "TORCH_EXTENSIONS_DIR": "torch",
    "TRITON_CACHE_DIR": "triton",
    "XDG_CACHE_HOME": "xdg",
    "NUMBA_CACHE_DIR": "numba",
}
MINIMUM_AVAILABLE_BYTES: Final = 5_000_000_000
MAXIMUM_ROOT_LENGTH: Final = 40
WEIGHT_SHA256: Final = "f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28"
INPUT_SHA256: Final = "543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286"


class RecoveryError(RuntimeError):
    """The one-shot short-path recovery contract could not be satisfied."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, raw)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if path.read_bytes() != raw:
        raise RecoveryError("exclusive evidence reread mismatch")


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_short_root(
    path: Path, *, minimum_available: int = MINIMUM_AVAILABLE_BYTES
) -> dict[str, object]:
    if len(path.as_posix()) > MAXIMUM_ROOT_LENGTH:
        raise RecoveryError("short temporary root exceeds 40 characters")
    observed = path.lstat()
    if not stat.S_ISDIR(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
        raise RecoveryError("short temporary root is not a real directory")
    if observed.st_uid != os.getuid() or stat.S_IMODE(observed.st_mode) != 0o700:
        raise RecoveryError("short temporary root owner or mode drifted")
    if not os.access(path, os.W_OK):
        raise RecoveryError("short temporary root is not writable")
    filesystem = os.statvfs(path)
    available = filesystem.f_bavail * filesystem.f_frsize
    if available < minimum_available:
        raise RecoveryError("short temporary root has less than 5 GB available")
    return {
        "path": path.as_posix(),
        "path_length": len(path.as_posix()),
        "owner_uid": observed.st_uid,
        "owner_gid": observed.st_gid,
        "mode": "0700",
        "available_bytes": available,
    }


def create_short_root(
    candidates: Sequence[Path] = (Path("/dev/shm"), Path("/tmp")),
) -> tuple[Path, dict[str, object]]:
    failures: list[str] = []
    for candidate in candidates:
        try:
            observed = candidate.lstat()
            if not stat.S_ISDIR(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
                raise RecoveryError("candidate is not a real directory")
            filesystem = os.statvfs(candidate)
            if filesystem.f_bavail * filesystem.f_frsize < MINIMUM_AVAILABLE_BYTES:
                raise RecoveryError("candidate has insufficient free space")
            created = Path(tempfile.mkdtemp(prefix="p01r2.", dir=candidate))
            created.chmod(0o700)
            evidence = validate_short_root(created)
            evidence["selected_parent"] = candidate.as_posix()
            return created, evidence
        except (OSError, RecoveryError) as exc:
            failures.append(f"{candidate}: {exc}")
    raise RecoveryError("NO_SAFE_SHORT_TEMP_ROOT: " + "; ".join(failures))


def build_short_environment(root: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    validate_short_root(root)
    environment = dict(os.environ if base is None else base)
    environment[CONTROL_VARIABLE] = root.as_posix()
    for relative in sorted(set(SUBDIRECTORIES.values())):
        destination = root / relative
        destination.mkdir(mode=0o700, exist_ok=False)
        destination.chmod(0o700)
    for name, relative in SUBDIRECTORIES.items():
        environment[name] = (root / relative).as_posix()
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return environment


def validate_short_environment(environment: dict[str, str]) -> dict[str, object]:
    root_text = environment.get(CONTROL_VARIABLE)
    if not root_text:
        raise RecoveryError("short temporary root control variable is absent")
    root = Path(root_text).resolve(strict=True)
    root_evidence = validate_short_root(root)
    values: dict[str, object] = {}
    for name in REQUIRED_TEMP_VARIABLES:
        value = environment.get(name)
        if not value:
            raise RecoveryError(f"{name} is absent")
        path = Path(value).resolve(strict=True)
        if not _inside(path, root) or path.is_symlink() or not path.is_dir():
            raise RecoveryError(f"{name} escaped the short root")
        observed = path.lstat()
        if observed.st_uid != os.getuid() or stat.S_IMODE(observed.st_mode) != 0o700:
            raise RecoveryError(f"{name} owner or mode drifted")
        values[name] = {"path": path.as_posix(), "length": len(path.as_posix())}
    if Path(tempfile.gettempdir()).resolve(strict=True) != Path(environment["TMPDIR"]).resolve(
        strict=True
    ):
        raise RecoveryError("Python tempfile.gettempdir did not bind TMPDIR")
    return {
        "root": root_evidence,
        "variables": values,
        "tempfile_gettempdir": tempfile.gettempdir(),
    }


def child_environment_probe(environment: dict[str, str], python: Path) -> dict[str, object]:
    code = (
        "import json,os,tempfile;"
        "keys=" + repr(REQUIRED_TEMP_VARIABLES) + ";"
        "print(json.dumps({'pid':os.getpid(),'cwd':os.getcwd(),"
        "'tempfile_gettempdir':tempfile.gettempdir(),"
        "'environment':{k:os.environ.get(k) for k in keys}},sort_keys=True))"
    )
    completed = subprocess.run(
        [python.as_posix(), "-I", "-B", "-c", code],
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RecoveryError("short-path child environment probe failed")
    child = json.loads(completed.stdout)
    expected = {name: environment[name] for name in REQUIRED_TEMP_VARIABLES}
    if child["environment"] != expected or child["tempfile_gettempdir"] != environment["TMPDIR"]:
        raise RecoveryError("SHORT_TEMP_ENV_NOT_PROPAGATED")
    return cast(dict[str, object], child)


def safe_cleanup_root(path: Path) -> bool:
    text = path.as_posix()
    valid_prefix = text.startswith("/dev/shm/p01r2.") or text.startswith("/tmp/p01r2.")
    if not text or not valid_prefix or text in {"/", "/tmp", "/dev/shm"}:
        return False
    try:
        validate_short_root(path, minimum_available=0)
    except (OSError, RecoveryError):
        return False
    return True


def cleanup_short_root(path: Path) -> dict[str, object]:
    if not safe_cleanup_root(path):
        raise RecoveryError("unsafe cleanup path rejected")
    files = [item for item in path.rglob("*") if item.is_file() and not item.is_symlink()]
    bytes_before = sum(item.stat().st_size for item in files)
    shutil.rmtree(path)
    if path.exists():
        raise RecoveryError("short temporary root survived cleanup")
    return {
        "temporary_directory_cleaned": True,
        "file_count_before_cleanup": len(files),
        "bytes_before_cleanup": bytes_before,
        "residual_files": 0,
    }


def _load(path: Path, name: str) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RecoveryError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def smoke(args: argparse.Namespace) -> int:
    evidence_root = Path(args.evidence_root).resolve(strict=True)
    source_root = Path(args.source_root).resolve(strict=True)
    pilot = _load(Path(args.pilot_helper).resolve(strict=True), "p01r2_pilot_helper")
    pilot._add_source_root(source_root)
    environment_evidence = validate_short_environment(dict(os.environ))
    raw = Path(args.xyz).resolve(strict=True).read_bytes()
    if sha256_bytes(raw) != INPUT_SHA256:
        raise RecoveryError("frozen cation smoke input drifted")
    _elements, coordinates = pilot._validate_frozen_endpoint("cation", raw)
    weight = Path(args.weight).resolve(strict=True)
    if sha256_bytes(weight.read_bytes()) != WEIGHT_SHA256:
        raise RecoveryError("AIMNet2 smoke weight drifted")
    gpu = pilot._gpu_observation(args.gpu_index, args.gpu_uuid)
    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu_index)
    from nhc_deprot_ranker.quantum import phase9b_aimnet2_runtime as runtime

    started = time.monotonic()
    base = runtime._construct_base_model_after_authorization(weight_path=weight, device="cuda:0")
    calculator = base.calculator_for(charge=1, multiplicity=1)
    energy, forces = calculator.energy_and_forces(coordinates)
    elapsed = time.monotonic() - started
    maximum_force = runtime.max_force(forces)
    if not math.isfinite(energy) or not math.isfinite(maximum_force):
        raise RecoveryError("AIMNet2 smoke returned non-finite values")
    result = {
        "schema_version": SCHEMA,
        "science_pilot_only": True,
        "production_accepted": False,
        "production_label_created": False,
        "optimizer_started": False,
        "trajectory_frames": 0,
        "model_load_count": int(base.load_count),
        "endpoint_wrapper_count": 1,
        "calculator_invocations": cast(Any, calculator).evaluation_counts()[2],
        "energy_finite": True,
        "forces_finite": True,
        "max_force_ev_per_angstrom": maximum_force,
        "nvrtc_result": "PASS",
        "gpu": gpu,
        "environment": environment_evidence,
        "input_sha256": INPUT_SHA256,
        "weight_sha256": WEIGHT_SHA256,
        "wall_seconds": elapsed,
        "exit_code": 0,
    }
    write_new(evidence_root / "smoke_result.json", canonical_json(result))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    smoke_parser = sub.add_parser("smoke")
    for name in ("evidence-root", "source-root", "pilot-helper", "xyz", "weight", "gpu-uuid"):
        smoke_parser.add_argument(f"--{name}", required=True)
    smoke_parser.add_argument("--gpu-index", type=int, required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "smoke":
        return smoke(args)
    raise RecoveryError("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
