#!/usr/bin/env python3
"""Thin exact-once supervisor for the bounded Phase 9B science-pilot pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

SCHEMA: Final = "phase9b-continuous-pipeline-config-v001"
EVIDENCE_SCHEMA: Final = "phase9b-continuous-pipeline-orchestrator-v001"
PARENT_PROTOCOL_SHA256: Final = "227c22a527e567bc4de873ab743fe9f493779eccbb1a698d2913c87695ebf87a"
BASE_WEIGHT_SHA256: Final = "f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28"
INCHIKEY = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
LANE_IDS: Final = ("a", "b", "c", "d")
LANE_BOOTSTRAP_DEADLINE_SECONDS: Final = 60.0


class PipelineOrchestratorError(RuntimeError):
    """The bounded automation contract was violated."""


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_regular(path: Path, *, maximum: int = 1 << 30) -> bytes:
    if not path.is_absolute():
        raise PipelineOrchestratorError("evidence path must be absolute")
    before = path.lstat()
    if path.is_symlink() or not path.is_file() or before.st_nlink != 1:
        raise PipelineOrchestratorError(f"not a single-link regular file: {path}")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1 << 20, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise PipelineOrchestratorError("file exceeds size bound")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise PipelineOrchestratorError("file identity changed during read")
    return b"".join(chunks)


def read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = read_regular(path)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PipelineOrchestratorError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PipelineOrchestratorError(f"JSON root is not an object: {path}")
    return cast(dict[str, Any], value), raw


def write_new(path: Path, raw: bytes) -> dict[str, object]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise PipelineOrchestratorError("evidence write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    reread = read_regular(path, maximum=max(1, len(raw)))
    if reread != raw:
        raise PipelineOrchestratorError("evidence reread mismatch")
    return {"path": str(path), "bytes": len(raw), "sha256": sha256_bytes(raw)}


def parse_cpu_list(value: str) -> tuple[int, ...]:
    if not value or value.strip() != value:
        raise PipelineOrchestratorError("invalid CPU list")
    observed: list[int] = []
    try:
        for part in value.split(","):
            if not part:
                raise ValueError
            if "-" in part:
                pieces = part.split("-", 1)
                lower, upper = int(pieces[0]), int(pieces[1])
                if lower > upper:
                    raise ValueError
                observed.extend(range(lower, upper + 1))
            else:
                observed.append(int(part))
    except ValueError as exc:
        raise PipelineOrchestratorError("invalid CPU list") from exc
    if not observed or len(observed) != len(set(observed)) or min(observed) < 0:
        raise PipelineOrchestratorError("invalid or duplicate CPU list")
    return tuple(observed)


def _relative_file(root: Path, value: object) -> Path:
    relative = Path(str(value))
    if relative.is_absolute() or ".." in relative.parts:
        raise PipelineOrchestratorError("registered source path is not safely relative")
    path = (root / relative).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PipelineOrchestratorError("registered source path escaped repository") from exc
    return path


def _root_name(value: object) -> str:
    name = str(value)
    if not name or Path(name).name != name or name in {".", ".."}:
        raise PipelineOrchestratorError("deployment root name must be one path component")
    return name


def _require_boolean(config: dict[str, Any], name: str, expected: bool) -> None:
    if config.get(name) is not expected:
        raise PipelineOrchestratorError(f"unsafe top-level flag: {name}")


def _candidate_set_from_split(finetune: dict[str, Any], repo_root: Path) -> set[str]:
    data = cast(dict[str, Any], finetune["data"])
    split_path = _relative_file(repo_root, data["split_path"])
    split_raw = read_regular(split_path)
    if sha256_bytes(split_raw) != data["split_sha256"]:
        raise PipelineOrchestratorError("fine-tune split SHA256 mismatch")
    split = json.loads(split_raw)
    if not isinstance(split, dict):
        raise PipelineOrchestratorError("fine-tune split root is invalid")
    result: set[str] = set()
    for name in ("train", "validation", "final_test"):
        profiles = split.get(name)
        if not isinstance(profiles, list) or not profiles:
            raise PipelineOrchestratorError(f"fine-tune split is empty: {name}")
        for profile in profiles:
            candidate = profile.get("candidate") if isinstance(profile, dict) else None
            if not isinstance(candidate, str) or not INCHIKEY.fullmatch(candidate):
                raise PipelineOrchestratorError("fine-tune split candidate is invalid")
            if candidate in result:
                raise PipelineOrchestratorError("candidate appears in more than one split")
            result.add(candidate)
    return result


def load_config(config_path: Path, repo_root: Path) -> tuple[dict[str, Any], bytes]:
    resolved_repo = repo_root.resolve(strict=True)
    config, config_raw = read_json(config_path.resolve(strict=True))
    if config.get("schema") != SCHEMA:
        raise PipelineOrchestratorError("pipeline config schema mismatch")
    for name, expected in {
        "science_pilot_only": True,
        "production_accepted": False,
        "production_label_insertion": False,
        "production_permit": False,
        "retry": False,
        "candidate_replacement": False,
        "speed_benchmark_after_freeze": False,
    }.items():
        _require_boolean(config, name, expected)

    identities = cast(dict[str, Any], config.get("identities"))
    if identities.get("parent_protocol_sha256") != PARENT_PROTOCOL_SHA256:
        raise PipelineOrchestratorError("parent protocol identity mismatch")
    if identities.get("base_weight_sha256") != BASE_WEIGHT_SHA256:
        raise PipelineOrchestratorError("base weight identity mismatch")
    if identities.get("required_candidate_count") != 9:
        raise PipelineOrchestratorError("candidate count must remain nine")
    if identities.get("required_lane_count") != 4:
        raise PipelineOrchestratorError("lane count must remain four")

    programs = cast(dict[str, Any], config.get("programs"))
    if set(programs) != {"autofill", "finetune_watch", "dataset", "finetune", "final_test"}:
        raise PipelineOrchestratorError("pipeline program set mismatch")
    for name, binding in programs.items():
        if not isinstance(binding, dict):
            raise PipelineOrchestratorError(f"program binding is invalid: {name}")
        source = _relative_file(resolved_repo, binding["path"])
        if sha256_bytes(read_regular(source)) != binding["sha256"]:
            raise PipelineOrchestratorError(f"program SHA256 mismatch: {name}")
        compatible = binding.get("adopt_compatible_sha256", [])
        if not isinstance(compatible, list) or any(
            not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            for digest in compatible
        ):
            raise PipelineOrchestratorError(f"program adoption identities are invalid: {name}")

    fine = cast(dict[str, Any], config.get("fine_tune"))
    for name, expected in {
        "single_training_attempt": True,
        "retry": False,
        "speed_benchmark": False,
    }.items():
        if fine.get(name) is not expected:
            raise PipelineOrchestratorError(f"unsafe fine-tune flag: {name}")
    fine_path = _relative_file(resolved_repo, fine["config_relative_path"])
    finetune, fine_raw = read_json(fine_path)
    if sha256_bytes(fine_raw) != fine["config_sha256"]:
        raise PipelineOrchestratorError("fine-tune config SHA256 mismatch")
    for name, expected in {
        "science_pilot_only": True,
        "production_accepted": False,
        "single_training_attempt": True,
        "retry": False,
    }.items():
        if finetune.get(name) is not expected:
            raise PipelineOrchestratorError(f"fine-tune contract is unsafe: {name}")
    post_freeze = cast(dict[str, Any], finetune["post_freeze_evaluation"])
    if post_freeze.get("speed_benchmark") is not False:
        raise PipelineOrchestratorError("fine-tune contract enables a speed benchmark")
    training_config_path = _relative_file(resolved_repo, fine["training_config_relative_path"])
    training_config, training_config_raw = read_json(training_config_path)
    if sha256_bytes(training_config_raw) != fine["training_config_sha256"]:
        raise PipelineOrchestratorError("model-generation config SHA256 mismatch")
    if training_config.get("schema") != "phase9b-aimnet2-model-generation-config-v002":
        raise PipelineOrchestratorError("model-generation config schema mismatch")

    lanes = config.get("lanes")
    if not isinstance(lanes, list) or len(lanes) != 4:
        raise PipelineOrchestratorError("pipeline must contain exactly four lanes")
    lane_ids: list[str] = []
    cpus: set[int] = set()
    queue_candidates: set[str] = set()
    state_names: set[str] = set()
    queue_hashes: list[str] = []
    for lane in lanes:
        if not isinstance(lane, dict):
            raise PipelineOrchestratorError("lane contract is invalid")
        lane_id = str(lane.get("lane_id"))
        lane_ids.append(lane_id)
        cpu_values = parse_cpu_list(str(lane.get("cpu_list")))
        if lane.get("threads") != len(cpu_values):
            raise PipelineOrchestratorError(f"lane {lane_id} thread count mismatch")
        if cpus.intersection(cpu_values):
            raise PipelineOrchestratorError("lane CPU sets overlap")
        cpus.update(cpu_values)
        if type(lane.get("max_memory_mb")) is not int or lane["max_memory_mb"] <= 0:
            raise PipelineOrchestratorError("lane memory is invalid")
        state_name = _root_name(lane.get("state_root_name"))
        if state_name in state_names:
            raise PipelineOrchestratorError("lane state root is duplicated")
        state_names.add(state_name)
        _root_name(lane.get("initial_watch_root_name"))
        queue_relative = Path(str(lane.get("queue_relative_path")))
        if queue_relative.is_absolute() or ".." in queue_relative.parts:
            raise PipelineOrchestratorError("lane queue path is not safely relative")
        digest = lane.get("queue_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise PipelineOrchestratorError("lane queue SHA256 is invalid")
        queue_hashes.append(digest)
        candidates = lane.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise PipelineOrchestratorError("lane candidate list is empty")
        for candidate in candidates:
            if not isinstance(candidate, str) or not INCHIKEY.fullmatch(candidate):
                raise PipelineOrchestratorError("lane candidate identity is invalid")
            if candidate in queue_candidates:
                raise PipelineOrchestratorError("candidate occurs in more than one lane")
            queue_candidates.add(candidate)
    if tuple(lane_ids) != LANE_IDS:
        raise PipelineOrchestratorError("lane order must remain a,b,c,d")
    if cpus != set(range(112)):
        raise PipelineOrchestratorError("frozen lanes must cover logical CPUs 0-111 exactly")

    expected_candidates = config.get("expected_candidates")
    if (
        not isinstance(expected_candidates, list)
        or len(expected_candidates) != 9
        or expected_candidates != sorted(expected_candidates)
        or len(set(expected_candidates)) != 9
    ):
        raise PipelineOrchestratorError("expected candidate registry is invalid")
    if queue_candidates != set(expected_candidates):
        raise PipelineOrchestratorError("lane queues do not cover the candidate registry")
    if _candidate_set_from_split(finetune, resolved_repo) != set(expected_candidates):
        raise PipelineOrchestratorError("fine-tune split and pipeline candidates differ")

    collection = cast(dict[str, Any], finetune["collection"])
    required_roots = [Path(str(value)).name for value in collection["required_queue_state_roots"]]
    if required_roots != [cast(dict[str, Any], lane)["state_root_name"] for lane in lanes]:
        raise PipelineOrchestratorError("fine-tune queue state roots differ from lane roots")
    if list(collection["required_queue_sha256"]) != queue_hashes:
        raise PipelineOrchestratorError("fine-tune queue hashes differ from lane hashes")

    deployment = cast(dict[str, Any], config.get("deployment"))
    for key in (
        "orchestrator_state_root_name",
        "autofill_driver_name",
        "finetune_driver_name",
    ):
        _root_name(deployment.get(key))
    for key in (
        "adopt_compatible_autofill_driver_names",
        "adopt_compatible_finetune_driver_names",
    ):
        names = deployment.get(key)
        if not isinstance(names, list) or not names:
            raise PipelineOrchestratorError("deployment adoption driver registry is invalid")
        for name in names:
            _root_name(name)
    if deployment.get("poll_seconds") != 60 or deployment.get("route_limit_seconds") != 86400:
        raise PipelineOrchestratorError("deployment polling or route deadline changed")
    _root_name(fine.get("watch_state_root_name"))
    _root_name(fine.get("dataset_root_name"))
    _root_name(fine.get("training_root_name"))
    _root_name(fine.get("final_test_root_name"))
    return config, config_raw


def _absolute_directory(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise PipelineOrchestratorError("deployment directory must be absolute")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise PipelineOrchestratorError("deployment directory is invalid")
    return resolved


def _absolute_executable(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise PipelineOrchestratorError("interpreter must be absolute")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise PipelineOrchestratorError("interpreter is not executable")
    return resolved


def deployment_paths(
    config: dict[str, Any],
    args: argparse.Namespace,
    *,
    allow_adopt_compatible: bool,
) -> dict[str, Path]:
    deployment = cast(dict[str, Any], config["deployment"])
    runs_root = _absolute_directory(args.runs_root)
    autofill_driver = _absolute_directory(args.autofill_driver)
    finetune_driver = _absolute_directory(args.finetune_driver)
    allowed_autofill_names = {str(deployment["autofill_driver_name"])}
    allowed_finetune_names = {str(deployment["finetune_driver_name"])}
    if allow_adopt_compatible:
        allowed_autofill_names.update(
            str(value) for value in deployment["adopt_compatible_autofill_driver_names"]
        )
        allowed_finetune_names.update(
            str(value) for value in deployment["adopt_compatible_finetune_driver_names"]
        )
    if autofill_driver.name not in allowed_autofill_names:
        raise PipelineOrchestratorError("auto-fill driver root identity mismatch")
    if finetune_driver.name not in allowed_finetune_names:
        raise PipelineOrchestratorError("fine-tune driver root identity mismatch")
    return {
        "runs_root": runs_root,
        "autofill_driver": autofill_driver,
        "finetune_driver": finetune_driver,
        "gpupyscf_python": _absolute_executable(args.gpupyscf_python),
        "mlff_python": _absolute_executable(args.mlff_python),
        "orchestrator_state_root": runs_root / str(deployment["orchestrator_state_root_name"]),
    }


def _allowed_program_hashes(binding: dict[str, Any], *, allow_adopt_compatible: bool) -> set[str]:
    result = {str(binding["sha256"])}
    if allow_adopt_compatible:
        result.update(str(value) for value in binding.get("adopt_compatible_sha256", []))
    return result


def validate_deployment_files(
    config: dict[str, Any],
    paths: dict[str, Path],
    *,
    allow_adopt_compatible: bool,
) -> None:
    programs = cast(dict[str, Any], config["programs"])
    locations = {
        "autofill": paths["autofill_driver"],
        "finetune_watch": paths["finetune_driver"],
        "dataset": paths["finetune_driver"],
        "finetune": paths["finetune_driver"],
        "final_test": paths["finetune_driver"],
    }
    for name, binding in programs.items():
        path = _relative_file(locations[name], binding["path"])
        allowed = _allowed_program_hashes(
            binding,
            allow_adopt_compatible=allow_adopt_compatible
            and name in {"autofill", "finetune_watch"},
        )
        if sha256_bytes(read_regular(path)) not in allowed:
            raise PipelineOrchestratorError(f"deployed program SHA256 mismatch: {name}")
    fine = cast(dict[str, Any], config["fine_tune"])
    fine_path = _relative_file(paths["finetune_driver"], fine["config_relative_path"])
    if sha256_bytes(read_regular(fine_path)) != fine["config_sha256"]:
        raise PipelineOrchestratorError("deployed fine-tune config SHA256 mismatch")
    training_config_path = _relative_file(
        paths["finetune_driver"], fine["training_config_relative_path"]
    )
    if sha256_bytes(read_regular(training_config_path)) != fine["training_config_sha256"]:
        raise PipelineOrchestratorError("deployed model-generation config SHA256 mismatch")
    for lane in cast(list[dict[str, Any]], config["lanes"]):
        queue = _relative_file(paths["autofill_driver"], lane["queue_relative_path"])
        queue_body, queue_raw = read_json(queue)
        if sha256_bytes(queue_raw) != lane["queue_sha256"]:
            raise PipelineOrchestratorError(f"lane {lane['lane_id']} queue SHA256 mismatch")
        candidates = [item.get("candidate") for item in queue_body.get("candidates", [])]
        if candidates != lane["candidates"]:
            raise PipelineOrchestratorError(f"lane {lane['lane_id']} queue order mismatch")
        initial = paths["runs_root"] / str(lane["initial_watch_root_name"])
        if not initial.is_dir() or initial.is_symlink():
            raise PipelineOrchestratorError(f"lane {lane['lane_id']} predecessor root is absent")


def lane_watch_command(
    config: dict[str, Any], paths: dict[str, Path], lane: dict[str, Any]
) -> list[str]:
    deployment = cast(dict[str, Any], config["deployment"])
    source = _relative_file(
        paths["autofill_driver"],
        cast(dict[str, Any], config["programs"])["autofill"]["path"],
    )
    return [
        str(paths["gpupyscf_python"]),
        "-I",
        "-B",
        str(source),
        "watch",
        "--queue",
        str(_relative_file(paths["autofill_driver"], lane["queue_relative_path"])),
        "--state-root",
        str(paths["runs_root"] / str(lane["state_root_name"])),
        "--initial-watch-root",
        str(paths["runs_root"] / str(lane["initial_watch_root_name"])),
        "--run-root",
        str(paths["runs_root"]),
        "--driver",
        str(paths["autofill_driver"]),
        "--gpupyscf-python",
        str(paths["gpupyscf_python"]),
        "--threads",
        str(lane["threads"]),
        "--cpu-list",
        str(lane["cpu_list"]),
        "--max-memory-mb",
        str(lane["max_memory_mb"]),
        "--route-limit-seconds",
        str(deployment["route_limit_seconds"]),
        "--poll-seconds",
        str(deployment["poll_seconds"]),
    ]


def finetune_watch_command(config: dict[str, Any], paths: dict[str, Path]) -> list[str]:
    programs = cast(dict[str, Any], config["programs"])
    fine = cast(dict[str, Any], config["fine_tune"])
    return [
        str(paths["gpupyscf_python"]),
        "-I",
        "-B",
        str(_relative_file(paths["finetune_driver"], programs["finetune_watch"]["path"])),
        "--config",
        str(_relative_file(paths["finetune_driver"], fine["config_relative_path"])),
        "--repo-root",
        str(paths["finetune_driver"]),
        "--dataset-helper",
        str(_relative_file(paths["finetune_driver"], programs["dataset"]["path"])),
        "--finetune-helper",
        str(_relative_file(paths["finetune_driver"], programs["finetune"]["path"])),
        "--final-test-helper",
        str(_relative_file(paths["finetune_driver"], programs["final_test"]["path"])),
        "--training-config",
        str(_relative_file(paths["finetune_driver"], fine["training_config_relative_path"])),
        "--gpupyscf-python",
        str(paths["gpupyscf_python"]),
        "--mlff-python",
        str(paths["mlff_python"]),
        "--poll-seconds",
        str(fine["poll_seconds"]),
    ]


def _optional_json(path: Path) -> dict[str, Any] | None:
    return read_json(path)[0] if path.exists() else None


def _read_exit(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(read_regular(path, maximum=32).decode().strip())
    except (UnicodeDecodeError, ValueError) as exc:
        raise PipelineOrchestratorError(f"invalid exit code: {path}") from exc


def validate_lane_binding(
    config: dict[str, Any],
    lane: dict[str, Any],
    state_root: Path,
    *,
    allow_adopt_compatible: bool,
) -> dict[str, Any]:
    binding, _ = read_json(state_root / "queue_binding.json")
    expected_cpu = list(parse_cpu_list(str(lane["cpu_list"])))
    if binding.get("queue_sha256") != lane["queue_sha256"]:
        raise PipelineOrchestratorError(f"lane {lane['lane_id']} binding queue mismatch")
    if binding.get("cpu_list") != expected_cpu or binding.get("threads") != lane["threads"]:
        raise PipelineOrchestratorError(f"lane {lane['lane_id']} binding resource mismatch")
    if binding.get("parent_protocol_sha256") != PARENT_PROTOCOL_SHA256:
        raise PipelineOrchestratorError(f"lane {lane['lane_id']} protocol mismatch")
    source_hashes = _allowed_program_hashes(
        cast(dict[str, Any], config["programs"])["autofill"],
        allow_adopt_compatible=allow_adopt_compatible,
    )
    if binding.get("scheduler_source_sha256") not in source_hashes:
        raise PipelineOrchestratorError(f"lane {lane['lane_id']} scheduler source mismatch")
    if binding.get("science_pilot_only") is not True:
        raise PipelineOrchestratorError(f"lane {lane['lane_id']} is not science-pilot-only")
    if binding.get("production_accepted") is not False:
        raise PipelineOrchestratorError(f"lane {lane['lane_id']} enables production")
    return binding


def validate_finetune_binding(
    config: dict[str, Any], paths: dict[str, Path], state_root: Path
) -> dict[str, Any]:
    binding, _ = read_json(state_root / "binding.json")
    programs = cast(dict[str, Any], config["programs"])
    fine = cast(dict[str, Any], config["fine_tune"])
    expected = {
        "config_sha256": fine["config_sha256"],
        "dataset_helper_sha256": programs["dataset"]["sha256"],
        "finetune_helper_sha256": programs["finetune"]["sha256"],
        "final_test_helper_sha256": programs["final_test"]["sha256"],
        "training_config_sha256": fine["training_config_sha256"],
        "single_training_attempt": True,
        "retry": False,
        "production_accepted": False,
    }
    for name, value in expected.items():
        if binding.get(name) != value:
            raise PipelineOrchestratorError(f"fine-tune watcher binding mismatch: {name}")
    expected_root = paths["runs_root"] / str(fine["watch_state_root_name"])
    if state_root != expected_root:
        raise PipelineOrchestratorError("fine-tune state root mismatch")
    return binding


def lane_snapshot(config: dict[str, Any], lane: dict[str, Any], runs_root: Path) -> dict[str, Any]:
    state_root = runs_root / str(lane["state_root_name"])
    result: dict[str, Any] = {
        "lane_id": lane["lane_id"],
        "state_root": str(state_root),
        "exists": state_root.exists(),
        "queue_exhausted": False,
        "claim_count": 0,
        "assignment_count": 0,
        "current_candidate": None,
        "current_root": str(runs_root / str(lane["initial_watch_root_name"])),
        "controller_exit_code": None,
        "route_outcome": None,
        "lane_terminal": None,
        "frame_count_by_endpoint": {"cation": 0, "neutral": 0},
    }
    if not state_root.exists():
        return result
    if state_root.is_symlink() or not state_root.is_dir():
        raise PipelineOrchestratorError("lane state root is invalid")
    validate_lane_binding(
        config,
        lane,
        state_root,
        allow_adopt_compatible=True,
    )
    claims = sorted((state_root / "claims").glob("*.json"))
    assignments = sorted((state_root / "assignments").glob("*.json"))
    result["claim_count"] = len(claims)
    result["assignment_count"] = len(assignments)
    if len(assignments) > len(claims):
        raise PipelineOrchestratorError("lane has more assignments than claims")
    if assignments:
        assignment, _ = read_json(assignments[-1])
        result["current_candidate"] = assignment.get("candidate")
        result["current_root"] = assignment.get("output_root")
    current_root = Path(str(result["current_root"]))
    if current_root.exists():
        result["controller_exit_code"] = _read_exit(current_root / "controller_exit_code")
        route = _optional_json(current_root / "result.json")
        if route is not None:
            result["route_outcome"] = route.get("final_outcome")
        frames = current_root / "training_data"
        for endpoint in ("cation", "neutral"):
            result["frame_count_by_endpoint"][endpoint] = len(
                list((frames / endpoint).glob("frame_*.json"))
            )
    exhausted = _optional_json(state_root / "queue_exhausted.json")
    if exhausted is not None:
        if exhausted.get("queue_exhausted") is not True or exhausted.get("retry") is not False:
            raise PipelineOrchestratorError("lane queue terminal is invalid")
        result["queue_exhausted"] = True
    result["lane_terminal"] = _optional_json(state_root / "lane_terminal.json")
    return result


def finetune_snapshot(config: dict[str, Any], paths: dict[str, Path]) -> dict[str, Any]:
    fine = cast(dict[str, Any], config["fine_tune"])
    state_root = paths["runs_root"] / str(fine["watch_state_root_name"])
    result: dict[str, Any] = {
        "state_root": str(state_root),
        "exists": state_root.exists(),
        "latest_snapshot": None,
        "dataset_claimed": False,
        "dataset_exit_code": None,
        "training_claimed": False,
        "training_exit_code": None,
        "terminal": None,
    }
    if not state_root.exists():
        return result
    if state_root.is_symlink() or not state_root.is_dir():
        raise PipelineOrchestratorError("fine-tune state root is invalid")
    validate_finetune_binding(config, paths, state_root)
    snapshots = sorted((state_root / "snapshots").glob("*.json"))
    if snapshots:
        latest, raw = read_json(snapshots[-1])
        result["latest_snapshot"] = {
            "path": str(snapshots[-1]),
            "sha256": sha256_bytes(raw),
            "body": latest,
        }
    result["dataset_claimed"] = (state_root / "dataset_claim.json").exists()
    result["dataset_exit_code"] = _read_exit(state_root / "dataset_exit_code")
    result["training_claimed"] = (state_root / "training_claim.json").exists()
    result["training_exit_code"] = _read_exit(state_root / "training_exit_code")
    result["terminal"] = _optional_json(state_root / "terminal.json")
    return result


def derive_pipeline_state(lanes: list[dict[str, Any]], fine: dict[str, Any]) -> str:
    if any(isinstance(lane.get("lane_terminal"), dict) for lane in lanes):
        return "TERMINAL_FAILED"
    terminal = fine.get("terminal")
    if isinstance(terminal, dict):
        return "COMPLETE" if terminal.get("outcome") == "PASS" else "TERMINAL_FAILED"
    if fine.get("training_claimed"):
        return "VALIDATE_AND_FREEZE" if fine.get("training_exit_code") == 0 else "TRAIN_ONCE"
    if fine.get("dataset_claimed"):
        return "WAIT_FOR_RESOURCES" if fine.get("dataset_exit_code") == 0 else "BUILD_DATASET_ONCE"
    latest = fine.get("latest_snapshot")
    body = latest.get("body") if isinstance(latest, dict) else None
    if isinstance(body, dict) and body.get("collection_complete") is True:
        return "WAIT_FOR_9_OF_9_PASS"
    if all(lane.get("queue_exhausted") for lane in lanes):
        return "AUDIT_RESULTS"
    return "RUN_LANES"


def deployment_snapshot(config: dict[str, Any], paths: dict[str, Path]) -> dict[str, Any]:
    lanes = [
        lane_snapshot(config, lane, paths["runs_root"])
        for lane in cast(list[dict[str, Any]], config["lanes"])
    ]
    fine = finetune_snapshot(config, paths)
    return {
        "schema": EVIDENCE_SCHEMA,
        "timestamp_ns": time.time_ns(),
        "pipeline_state": derive_pipeline_state(lanes, fine),
        "lanes": lanes,
        "fine_tune": fine,
        "science_pilot_only": True,
        "production_accepted": False,
        "retry": False,
        "speed_benchmark_started": False,
    }


def _clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        environment.pop(name, None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _launch_child(
    *,
    name: str,
    command: list[str],
    state_root: Path,
) -> subprocess.Popen[bytes]:
    command_sha = sha256_bytes("\0".join(command).encode())
    write_new(
        state_root / "children" / f"{name}_claim.json",
        canonical_json(
            {
                "schema": EVIDENCE_SCHEMA,
                "component": name,
                "command_sha256": command_sha,
                "claimed_monotonic_ns": time.monotonic_ns(),
                "retry": False,
            }
        ),
    )
    stdout = (state_root / "children" / f"{name}_stdout").open("xb", buffering=0)
    stderr = (state_root / "children" / f"{name}_stderr").open("xb", buffering=0)
    try:
        process = subprocess.Popen(
            command,
            env=_clean_environment(),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            start_new_session=True,
        )
    finally:
        stdout.close()
        stderr.close()
    write_new(
        state_root / "children" / f"{name}_assignment.json",
        canonical_json(
            {
                "schema": EVIDENCE_SCHEMA,
                "component": name,
                "pid": process.pid,
                "command_sha256": command_sha,
                "assigned_monotonic_ns": time.monotonic_ns(),
                "retry": False,
            }
        ),
    )
    return process


def _adopt(config: dict[str, Any], paths: dict[str, Path], state_root: Path) -> None:
    for lane in cast(list[dict[str, Any]], config["lanes"]):
        lane_root = paths["runs_root"] / str(lane["state_root_name"])
        if not lane_root.is_dir() or lane_root.is_symlink():
            raise PipelineOrchestratorError(f"lane {lane['lane_id']} cannot be adopted")
        binding = validate_lane_binding(
            config,
            lane,
            lane_root,
            allow_adopt_compatible=True,
        )
        write_new(
            state_root / "adoptions" / f"lane_{lane['lane_id']}.json",
            canonical_json(
                {
                    "schema": EVIDENCE_SCHEMA,
                    "component": f"lane_{lane['lane_id']}",
                    "state_root": str(lane_root),
                    "queue_sha256": binding["queue_sha256"],
                    "launched_by_orchestrator": False,
                }
            ),
        )
    fine = cast(dict[str, Any], config["fine_tune"])
    fine_root = paths["runs_root"] / str(fine["watch_state_root_name"])
    if not fine_root.is_dir() or fine_root.is_symlink():
        raise PipelineOrchestratorError("fine-tune watcher cannot be adopted")
    binding = validate_finetune_binding(config, paths, fine_root)
    write_new(
        state_root / "adoptions" / "finetune.json",
        canonical_json(
            {
                "schema": EVIDENCE_SCHEMA,
                "component": "finetune",
                "state_root": str(fine_root),
                "config_sha256": binding["config_sha256"],
                "launched_by_orchestrator": False,
            }
        ),
    )


def preflight_mode(config: dict[str, Any], paths: dict[str, Path], mode: str) -> None:
    fine = cast(dict[str, Any], config["fine_tune"])
    lane_roots = [
        paths["runs_root"] / str(lane["state_root_name"])
        for lane in cast(list[dict[str, Any]], config["lanes"])
    ]
    fine_root = paths["runs_root"] / str(fine["watch_state_root_name"])
    if mode == "start":
        if any(path.exists() for path in [*lane_roots, fine_root]):
            raise PipelineOrchestratorError("start mode refuses an existing watcher state root")
        return
    if mode != "adopt":
        raise PipelineOrchestratorError("unknown orchestrator mode")
    for lane, lane_root in zip(
        cast(list[dict[str, Any]], config["lanes"]), lane_roots, strict=True
    ):
        if not lane_root.is_dir() or lane_root.is_symlink():
            raise PipelineOrchestratorError(f"lane {lane['lane_id']} cannot be adopted")
        validate_lane_binding(
            config,
            lane,
            lane_root,
            allow_adopt_compatible=True,
        )
    if not fine_root.is_dir() or fine_root.is_symlink():
        raise PipelineOrchestratorError("fine-tune watcher cannot be adopted")
    validate_finetune_binding(config, paths, fine_root)


def _start(
    config: dict[str, Any], paths: dict[str, Path], state_root: Path
) -> dict[str, subprocess.Popen[bytes]]:
    fine = cast(dict[str, Any], config["fine_tune"])
    prohibited = [
        paths["runs_root"] / str(lane["state_root_name"])
        for lane in cast(list[dict[str, Any]], config["lanes"])
    ]
    prohibited.append(paths["runs_root"] / str(fine["watch_state_root_name"]))
    if any(path.exists() for path in prohibited):
        raise PipelineOrchestratorError("start mode refuses an existing watcher state root")
    processes: dict[str, subprocess.Popen[bytes]] = {}
    for lane in cast(list[dict[str, Any]], config["lanes"]):
        name = f"lane_{lane['lane_id']}"
        processes[name] = _launch_child(
            name=name,
            command=lane_watch_command(config, paths, lane),
            state_root=state_root,
        )
    wait_for_lane_bindings(config, paths, processes)
    processes["finetune"] = _launch_child(
        name="finetune",
        command=finetune_watch_command(config, paths),
        state_root=state_root,
    )
    return processes


def wait_for_lane_bindings(
    config: dict[str, Any],
    paths: dict[str, Path],
    processes: dict[str, subprocess.Popen[bytes]],
) -> None:
    deadline = time.monotonic() + LANE_BOOTSTRAP_DEADLINE_SECONDS
    lanes = cast(list[dict[str, Any]], config["lanes"])
    while True:
        ready = 0
        for lane in lanes:
            name = f"lane_{lane['lane_id']}"
            state_root = paths["runs_root"] / str(lane["state_root_name"])
            binding_path = state_root / "queue_binding.json"
            if binding_path.exists():
                validate_lane_binding(
                    config,
                    lane,
                    state_root,
                    allow_adopt_compatible=False,
                )
                ready += 1
                continue
            exit_code = processes[name].poll()
            if exit_code is not None:
                raise PipelineOrchestratorError(
                    f"lane {lane['lane_id']} exited before publishing its binding"
                )
        if ready == len(lanes):
            return
        if time.monotonic() >= deadline:
            raise PipelineOrchestratorError("lane watcher binding bootstrap timed out")
        time.sleep(0.1)


def _terminal(state_root: Path, *, outcome: str, details: dict[str, object]) -> dict[str, object]:
    return write_new(
        state_root / "terminal.json",
        canonical_json(
            {
                "schema": EVIDENCE_SCHEMA,
                "outcome": outcome,
                "details": details,
                "retry": False,
                "production_accepted": False,
                "speed_benchmark_started": False,
                "timestamp_ns": time.time_ns(),
            }
        ),
    )


def run(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve(strict=True)
    config, config_raw = load_config(Path(args.config), repo_root)
    paths = deployment_paths(
        config,
        args,
        allow_adopt_compatible=args.mode == "adopt",
    )
    validate_deployment_files(
        config,
        paths,
        allow_adopt_compatible=args.mode == "adopt",
    )
    state_root = paths["orchestrator_state_root"]
    if state_root.exists():
        raise PipelineOrchestratorError("orchestrator state root already exists")
    preflight_mode(config, paths, args.mode)
    state_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    (state_root / "children").mkdir(mode=0o700)
    (state_root / "adoptions").mkdir(mode=0o700)
    (state_root / "snapshots").mkdir(mode=0o700)
    write_new(
        state_root / "binding.json",
        canonical_json(
            {
                "schema": EVIDENCE_SCHEMA,
                "config_sha256": sha256_bytes(config_raw),
                "orchestrator_source_sha256": sha256_bytes(
                    read_regular(Path(__file__).resolve(strict=True))
                ),
                "mode": args.mode,
                "parent_protocol_sha256": PARENT_PROTOCOL_SHA256,
                "base_weight_sha256": BASE_WEIGHT_SHA256,
                "candidate_count": 9,
                "lane_count": 4,
                "science_pilot_only": True,
                "production_accepted": False,
                "retry": False,
            }
        ),
    )
    processes: dict[str, subprocess.Popen[bytes]] = {}
    if args.mode == "adopt":
        _adopt(config, paths, state_root)
    elif args.mode == "start":
        try:
            processes = _start(config, paths, state_root)
        except (OSError, PipelineOrchestratorError) as exc:
            _terminal(
                state_root,
                outcome="WATCHER_BOOTSTRAP_FAILED",
                details={"error": str(exc), "retry_started": False},
            )
            return 3
    else:
        raise PipelineOrchestratorError("unknown orchestrator mode")

    index = 0
    poll_seconds = float(cast(dict[str, Any], config["deployment"])["poll_seconds"])
    while True:
        snapshot = deployment_snapshot(config, paths)
        snapshot_raw = canonical_json(snapshot)
        snapshot_record = write_new(state_root / "snapshots" / f"{index:06d}.json", snapshot_raw)
        index += 1
        fine_terminal = cast(dict[str, Any], snapshot["fine_tune"]).get("terminal")
        failed_lanes = [
            {
                "lane_id": lane["lane_id"],
                "terminal": lane["lane_terminal"],
            }
            for lane in cast(list[dict[str, Any]], snapshot["lanes"])
            if isinstance(lane.get("lane_terminal"), dict)
        ]
        if failed_lanes:
            _terminal(
                state_root,
                outcome="UPSTREAM_LANE_FAILED",
                details={
                    "failed_lanes": failed_lanes,
                    "final_snapshot_sha256": snapshot_record["sha256"],
                    "retry_started": False,
                },
            )
            return 2
        if isinstance(fine_terminal, dict):
            outcome = str(fine_terminal.get("outcome"))
            _terminal(
                state_root,
                outcome="PASS" if outcome == "PASS" else "UPSTREAM_TERMINAL_FAILED",
                details={
                    "fine_tune_outcome": outcome,
                    "final_snapshot_sha256": snapshot_record["sha256"],
                    "watchers_launched": args.mode == "start",
                },
            )
            return 0 if outcome == "PASS" else 2
        for name, process in processes.items():
            exit_code = process.poll()
            if exit_code is None:
                continue
            component_complete = False
            if name == "finetune":
                component_complete = fine_terminal is not None
            else:
                lane_id = name.removeprefix("lane_")
                component_complete = any(
                    lane["lane_id"] == lane_id
                    and (lane["queue_exhausted"] or isinstance(lane.get("lane_terminal"), dict))
                    for lane in cast(list[dict[str, Any]], snapshot["lanes"])
                )
            if not component_complete:
                _terminal(
                    state_root,
                    outcome="WATCHER_EXITED_WITHOUT_TERMINAL",
                    details={
                        "component": name,
                        "exit_code": exit_code,
                        "final_snapshot_sha256": snapshot_record["sha256"],
                        "retry_started": False,
                    },
                )
                return 3
        time.sleep(poll_seconds)


def validate_command(args: argparse.Namespace) -> int:
    config, raw = load_config(
        Path(args.config),
        Path(args.repo_root),
    )
    print(
        canonical_json(
            {
                "schema": EVIDENCE_SCHEMA,
                "status": "PASS",
                "config_sha256": sha256_bytes(raw),
                "candidate_count": len(config["expected_candidates"]),
                "lane_count": len(config["lanes"]),
                "cpu_count": sum(
                    len(parse_cpu_list(str(lane["cpu_list"]))) for lane in config["lanes"]
                ),
                "science_pilot_only": True,
                "production_accepted": False,
            }
        ).decode(),
        end="",
    )
    return 0


def snapshot_command(args: argparse.Namespace) -> int:
    config, _ = load_config(Path(args.config), Path(args.repo_root))
    paths = deployment_paths(config, args, allow_adopt_compatible=True)
    validate_deployment_files(config, paths, allow_adopt_compatible=True)
    print(canonical_json(deployment_snapshot(config, paths)).decode(), end="")
    return 0


def _deployment_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runs-root", required=True)
    parser.add_argument("--autofill-driver", required=True)
    parser.add_argument("--finetune-driver", required=True)
    parser.add_argument("--gpupyscf-python", required=True)
    parser.add_argument("--mlff-python", required=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--config", required=True)
    validate.add_argument("--repo-root", required=True)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--config", required=True)
    snapshot.add_argument("--repo-root", required=True)
    _deployment_arguments(snapshot)
    execute = sub.add_parser("run")
    execute.add_argument("--config", required=True)
    execute.add_argument("--repo-root", required=True)
    execute.add_argument("--mode", choices=("start", "adopt"), required=True)
    _deployment_arguments(execute)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "validate":
        return validate_command(args)
    if args.command == "snapshot":
        return snapshot_command(args)
    if args.command == "run":
        return run(args)
    raise PipelineOrchestratorError("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
