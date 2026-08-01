#!/usr/bin/env python3
"""Durable one-shot gate from P01 frame collection to AIMNet2 fine-tuning."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

CONFIG_SCHEMA: Final = "phase9b-aimnet2-finetune-orchestration-v002"
WATCH_SCHEMA: Final = "phase9b-aimnet2-finetune-watch-v001"
PASS: Final = "PASS"
TEMP_PREFIXES: Final = ("/dev/shm/p9bft.", "/tmp/p9bft.")


class FineTuneWatchError(RuntimeError):
    """The automatic one-shot fine-tuning gate failed closed."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_regular(path: Path, *, maximum: int = 1 << 30) -> bytes:
    before = path.lstat()
    if path.is_symlink() or not path.is_file() or before.st_nlink != 1:
        raise FineTuneWatchError(f"not a single-link regular file: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(fd, min(1 << 20, maximum + 1 - observed))
            if not chunk:
                break
            chunks.append(chunk)
            observed += len(chunk)
            if observed > maximum:
                raise FineTuneWatchError("watch input exceeds size bound")
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if (before.st_dev, before.st_ino, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise FineTuneWatchError("watch input changed during read")
    return b"".join(chunks)


def write_new(path: Path, raw: bytes) -> dict[str, object]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise FineTuneWatchError("short watcher evidence write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    if read_regular(path, maximum=max(1, len(raw))) != raw:
        raise FineTuneWatchError("watcher evidence reread mismatch")
    return {"path": str(path), "bytes": len(raw), "sha256": sha256_bytes(raw)}


def read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = read_regular(path)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FineTuneWatchError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FineTuneWatchError(f"JSON root is not an object: {path}")
    return cast(dict[str, Any], value), raw


def load_contract(config_path: Path, repo_root: Path) -> tuple[dict[str, Any], bytes]:
    config, raw = read_json(config_path)
    if config.get("schema") != CONFIG_SCHEMA or config.get("single_training_attempt") is not True:
        raise FineTuneWatchError("watcher config identity mismatch")
    if config.get("retry") is not False or config.get("production_accepted") is not False:
        raise FineTuneWatchError("watcher config widened the one-shot boundary")
    data = cast(dict[str, Any], config["data"])
    split_path = (repo_root / str(data["split_path"])).resolve(strict=True)
    if sha256_bytes(read_regular(split_path)) != data["split_sha256"]:
        raise FineTuneWatchError("watcher split SHA256 mismatch")
    model = cast(dict[str, Any], config["training_model"])
    model_path = (repo_root / str(model["path"])).resolve(strict=True)
    if sha256_bytes(read_regular(model_path)) != model["sha256"]:
        raise FineTuneWatchError("watcher training model SHA256 mismatch")
    return config, raw


def expected_candidates(config: dict[str, Any], repo_root: Path) -> list[tuple[str, str]]:
    split_path = repo_root / str(cast(dict[str, Any], config["data"])["split_path"])
    split, _ = read_json(split_path.resolve(strict=True))
    result: list[tuple[str, str]] = []
    for name in ("train", "validation", "final_test"):
        profiles = split.get(name)
        if not isinstance(profiles, list) or not profiles:
            raise FineTuneWatchError(f"watcher split is empty: {name}")
        result.extend((str(profile["candidate"]), name) for profile in profiles)
    if len(result) != int(cast(dict[str, Any], config["data"])["required_candidate_count"]):
        raise FineTuneWatchError("watcher candidate count mismatch")
    return result


def collection_snapshot(config: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    paths = cast(dict[str, Any], config["paths"])
    collection = cast(dict[str, Any], config["collection"])
    runs_root = Path(str(paths["runs_root"]))
    candidates: list[dict[str, Any]] = []
    failed: list[str] = []
    complete = 0
    frame_counts = {"train": 0, "validation": 0, "final_test": 0}
    for candidate, split in expected_candidates(config, repo_root):
        root = runs_root / str(collection["run_name_template"]).format(
            candidate_lower=candidate.lower()
        )
        item: dict[str, Any] = {
            "candidate": candidate,
            "split": split,
            "root": str(root),
            "exists": root.exists(),
            "terminal": False,
            "outcome": None,
            "controller_exit_code": None,
            "frame_count": 0,
        }
        exit_path = root / "controller_exit_code"
        result_path = root / "result.json"
        if root.exists():
            item["frame_count"] = len(list((root / "training_data").glob("*/frame_*.json")))
            frame_counts[split] += int(item["frame_count"])
        if exit_path.exists():
            try:
                item["controller_exit_code"] = int(
                    read_regular(exit_path, maximum=32).decode().strip()
                )
            except (UnicodeDecodeError, ValueError) as exc:
                raise FineTuneWatchError("candidate controller exit code is invalid") from exc
            item["terminal"] = True
            if result_path.exists():
                result, _ = read_json(result_path)
                item["outcome"] = result.get("final_outcome")
                item["result_candidate"] = result.get("candidate")
            if (
                item["controller_exit_code"] != 0
                or item["outcome"] != PASS
                or item.get("result_candidate") != candidate
            ):
                failed.append(candidate)
            else:
                complete += 1
        candidates.append(item)
    queue_states: list[dict[str, Any]] = []
    failed_queue_states: list[dict[str, Any]] = []
    expected_queue_hashes = list(collection["required_queue_sha256"])
    state_roots = list(collection["required_queue_state_roots"])
    if len(expected_queue_hashes) != len(state_roots):
        raise FineTuneWatchError("queue state/hash count mismatch")
    for state_root_value, expected_hash in zip(state_roots, expected_queue_hashes, strict=True):
        state_root = Path(str(state_root_value))
        binding, _ = read_json(state_root / "queue_binding.json")
        if binding.get("queue_sha256") != expected_hash:
            raise FineTuneWatchError("queue binding SHA256 mismatch")
        lane_terminal = None
        if (state_root / "lane_terminal.json").exists():
            lane_terminal, _ = read_json(state_root / "lane_terminal.json")
            failed_queue_states.append(
                {
                    "root": str(state_root),
                    "outcome": lane_terminal.get("outcome"),
                    "expected_candidate": lane_terminal.get("expected_candidate"),
                }
            )
        queue_states.append(
            {
                "root": str(state_root),
                "queue_sha256": expected_hash,
                "exhausted": (state_root / "queue_exhausted.json").exists(),
                "lane_terminal": lane_terminal,
            }
        )
    return {
        "schema": WATCH_SCHEMA,
        "timestamp_ns": time.time_ns(),
        "candidates": candidates,
        "complete_candidate_count": complete,
        "required_candidate_count": len(candidates),
        "failed_candidates": failed,
        "failed_queue_states": failed_queue_states,
        "frame_count_by_split": frame_counts,
        "queues": queue_states,
        "collection_complete": not failed_queue_states
        and complete == len(candidates)
        and all(item["exhausted"] for item in queue_states),
    }


def _clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        environment.pop(name, None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _run_captured(
    command: list[str], *, environment: dict[str, str], stdout_path: Path, stderr_path: Path
) -> int:
    with (
        stdout_path.open("xb", buffering=0) as stdout,
        stderr_path.open("xb", buffering=0) as stderr,
    ):
        completed = subprocess.run(
            command,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
        )
    return int(completed.returncode)


def _host_resources(config: dict[str, Any], parent: Path) -> dict[str, int]:
    limits = cast(dict[str, Any], config["resource_preflight"])
    disk_free = shutil.disk_usage(parent).free
    memory_available = 0
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            memory_available = int(line.split()[1]) * 1024
            break
    return {
        "disk_free_bytes": disk_free,
        "memory_available_bytes": memory_available,
        "disk_pass": int(disk_free >= int(limits["minimum_free_disk_bytes"])),
        "memory_pass": int(memory_available >= int(limits["minimum_available_host_memory_bytes"])),
    }


def select_gpu(config: dict[str, Any]) -> dict[str, object] | None:
    limits = cast(dict[str, Any], config["resource_preflight"])
    output = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,utilization.gpu,memory.free,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    process_output = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    busy_uuids = {
        line.split(",", 1)[0].strip()
        for line in process_output.splitlines()
        if "," in line and line.split(",", 1)[1].strip().isdigit()
    }
    candidates: list[dict[str, object]] = []
    for line in output.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 5:
            raise FineTuneWatchError("nvidia-smi GPU snapshot is invalid")
        index, uuid, utilization, free_mib, total_mib = (
            int(fields[0]),
            fields[1],
            int(fields[2]),
            int(fields[3]),
            int(fields[4]),
        )
        free_bytes = free_mib * 1024 * 1024
        if (
            uuid not in busy_uuids
            and utilization <= int(limits["maximum_gpu_utilization_percent"])
            and free_bytes >= int(limits["minimum_free_gpu_memory_bytes"])
        ):
            candidates.append(
                {
                    "index": index,
                    "uuid": uuid,
                    "utilization_percent": utilization,
                    "free_bytes": free_bytes,
                    "total_bytes": total_mib * 1024 * 1024,
                }
            )
    return min(candidates, key=lambda item: cast(int, item["index"])) if candidates else None


def create_short_cache() -> tuple[Path, dict[str, str]]:
    parent = Path("/dev/shm") if os.access("/dev/shm", os.W_OK) else Path("/tmp")
    root = Path(tempfile.mkdtemp(prefix="p9bft.", dir=parent))
    root.chmod(0o700)
    if (
        len(str(root)) > 40
        or root.is_symlink()
        or root.stat().st_uid != os.getuid()
        or stat.S_IMODE(root.stat().st_mode) != 0o700
    ):
        raise FineTuneWatchError("short-cache root safety check failed")
    children = {
        "TMPDIR": "tmp",
        "TMP": "tmp",
        "TEMP": "tmp",
        "CUDA_CACHE_PATH": "cuda",
        "TORCH_EXTENSIONS_DIR": "torch",
        "TORCHINDUCTOR_CACHE_DIR": "torchinductor",
        "TRITON_CACHE_DIR": "triton",
        "XDG_CACHE_HOME": "xdg",
        "NUMBA_CACHE_DIR": "numba",
    }
    environment: dict[str, str] = {}
    for variable, child_name in children.items():
        child = root / child_name
        child.mkdir(mode=0o700, exist_ok=child.exists())
        child.chmod(0o700)
        environment[variable] = str(child)
    return root, environment


def cleanup_short_cache(root: Path) -> dict[str, object]:
    resolved = root.resolve(strict=True)
    if (
        not any(str(resolved).startswith(prefix) for prefix in TEMP_PREFIXES)
        or resolved in {Path("/"), Path("/tmp"), Path("/dev/shm")}
        or resolved.is_symlink()
        or resolved.stat().st_uid != os.getuid()
    ):
        raise FineTuneWatchError("unsafe short-cache cleanup target")
    files = sum(1 for path in resolved.rglob("*") if path.is_file())
    bytes_total = sum(path.stat().st_size for path in resolved.rglob("*") if path.is_file())
    shutil.rmtree(resolved)
    return {
        "root": str(resolved),
        "file_count_before_cleanup": files,
        "bytes_before_cleanup": bytes_total,
        "cleaned": not resolved.exists(),
    }


def terminal(state_root: Path, *, outcome: str, details: dict[str, object]) -> dict[str, object]:
    body = {
        "schema": WATCH_SCHEMA,
        "outcome": outcome,
        "details": details,
        "retry": False,
        "production_accepted": False,
        "speed_benchmark_run": False,
        "timestamp_ns": time.time_ns(),
    }
    return write_new(state_root / "terminal.json", canonical_json(body))


def watch(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve(strict=True)
    config_path = Path(args.config).resolve(strict=True)
    config, config_raw = load_contract(config_path, repo_root)
    paths = cast(dict[str, Any], config["paths"])
    state_root = Path(str(paths["watch_state_root"]))
    if state_root.exists():
        raise FineTuneWatchError("fine-tuning watch state root already exists")
    state_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    (state_root / "snapshots").mkdir(mode=0o700)
    dataset_helper = Path(args.dataset_helper).resolve(strict=True)
    finetune_helper = Path(args.finetune_helper).resolve(strict=True)
    final_test_helper = Path(args.final_test_helper).resolve(strict=True)
    training_config_path = Path(args.training_config).resolve(strict=True)
    training_config, training_config_raw = read_json(training_config_path)
    if training_config.get("schema") != "phase9b-aimnet2-model-generation-config-v002":
        raise FineTuneWatchError("model-generation config identity mismatch")
    write_new(
        state_root / "binding.json",
        canonical_json(
            {
                "schema": WATCH_SCHEMA,
                "config_sha256": sha256_bytes(config_raw),
                "split_sha256": cast(dict[str, Any], config["data"])["split_sha256"],
                "dataset_helper_sha256": sha256_bytes(read_regular(dataset_helper)),
                "finetune_helper_sha256": sha256_bytes(read_regular(finetune_helper)),
                "final_test_helper_sha256": sha256_bytes(read_regular(final_test_helper)),
                "training_config_sha256": sha256_bytes(training_config_raw),
                "single_training_attempt": True,
                "retry": False,
                "production_accepted": False,
            }
        ),
    )
    readiness = training_config.get("readiness")
    if not isinstance(readiness, dict) or readiness.get("state") != "REGISTERED":
        terminal(
            state_root,
            outcome="BLOCKED_BEFORE_TRAINING",
            details={
                "training_started": False,
                "final_test_consumed": False,
                "blocking_reason_codes": (
                    readiness.get("blocking_reason_codes")
                    if isinstance(readiness, dict)
                    else ["GENERATION_READINESS_MISSING"]
                ),
            },
        )
        return 9
    poll_seconds = float(args.poll_seconds)
    snapshot_index = 0
    while True:
        snapshot = collection_snapshot(config, repo_root)
        snapshot["host_resources"] = _host_resources(config, Path(str(paths["runs_root"])))
        write_new(
            state_root / "snapshots" / f"{snapshot_index:06d}.json",
            canonical_json(snapshot),
        )
        snapshot_index += 1
        if snapshot["failed_candidates"] or snapshot["failed_queue_states"]:
            terminal(
                state_root,
                outcome="COLLECTION_FAILED",
                details={
                    "failed_candidates": snapshot["failed_candidates"],
                    "failed_queue_states": snapshot["failed_queue_states"],
                    "training_started": False,
                },
            )
            return 2
        if snapshot["collection_complete"]:
            break
        time.sleep(poll_seconds)

    generation_paths = cast(dict[str, Any], training_config["paths"])
    dataset_root = Path(str(generation_paths["dataset_root"]))
    training_root = Path(str(generation_paths["training_root"]))
    final_test_root = training_root.parent / "phase9b_aimnet2_final_test_v002"
    if dataset_root.exists() or training_root.exists() or final_test_root.exists():
        terminal(
            state_root,
            outcome="OUTPUT_ROOT_ALREADY_EXISTS",
            details={"training_started": False},
        )
        return 3
    dataset_environment = _clean_environment()
    dataset_environment.update(
        {
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
    )
    dataset_command = [
        args.gpupyscf_python,
        "-I",
        "-B",
        str(dataset_helper),
        "--split",
        str((repo_root / str(cast(dict[str, Any], config["data"])["split_path"])).resolve()),
        "--runs-root",
        str(paths["runs_root"]),
        "--output-root",
        str(dataset_root),
        "--scope",
        "development",
    ]
    write_new(
        state_root / "dataset_claim.json",
        canonical_json(
            {
                "schema": WATCH_SCHEMA,
                "command_sha256": sha256_bytes("\0".join(dataset_command).encode()),
                "output_root": str(dataset_root),
                "retry": False,
            }
        ),
    )
    dataset_exit = _run_captured(
        dataset_command,
        environment=dataset_environment,
        stdout_path=state_root / "dataset_stdout",
        stderr_path=state_root / "dataset_stderr",
    )
    write_new(state_root / "dataset_exit_code", f"{dataset_exit}\n".encode())
    if dataset_exit != 0 or not (dataset_root / "manifest.json").exists():
        terminal(
            state_root,
            outcome="DATASET_ASSEMBLY_FAILED",
            details={"exit_code": dataset_exit, "training_started": False},
        )
        return 4

    while True:
        host = _host_resources(config, Path(str(paths["runs_root"])))
        gpu = select_gpu(config)
        waiting = {
            "schema": WATCH_SCHEMA,
            "host_resources": host,
            "selected_gpu": gpu,
            "timestamp_ns": time.time_ns(),
        }
        write_new(
            state_root / "snapshots" / f"{snapshot_index:06d}.json",
            canonical_json(waiting),
        )
        snapshot_index += 1
        if host["disk_pass"] and host["memory_pass"] and gpu is not None:
            break
        time.sleep(poll_seconds)

    short_root, short_environment = create_short_cache()
    training_environment = _clean_environment()
    training_environment.update(short_environment)
    training_command = [
        args.mlff_python,
        "-I",
        "-B",
        str(finetune_helper),
        "--config",
        str(training_config_path),
        "--repo-root",
        str(repo_root),
        "--dataset-root",
        str(dataset_root),
        "--output-root",
        str(training_root),
        "--base-bundle",
        str(cast(dict[str, Any], config["base_bundle"])["path"]),
        "--gpu-index",
        str(gpu["index"]),
    ]
    write_new(
        state_root / "training_claim.json",
        canonical_json(
            {
                "schema": WATCH_SCHEMA,
                "command_sha256": sha256_bytes("\0".join(training_command).encode()),
                "dataset_manifest_sha256": sha256_bytes(
                    read_regular(dataset_root / "manifest.json")
                ),
                "selected_gpu": gpu,
                "short_cache_root": str(short_root),
                "single_training_attempt": True,
                "retry": False,
            }
        ),
    )
    training_exit = _run_captured(
        training_command,
        environment=training_environment,
        stdout_path=state_root / "training_stdout",
        stderr_path=state_root / "training_stderr",
    )
    write_new(state_root / "training_exit_code", f"{training_exit}\n".encode())
    if training_exit != 0 or not (training_root / "result.json").exists():
        cleanup = cleanup_short_cache(short_root)
        write_new(state_root / "short_cache_cleanup.json", canonical_json(cleanup))
        terminal(
            state_root,
            outcome="TRAINING_FAILED",
            details={"exit_code": training_exit, "cleanup": cleanup},
        )
        return 5
    result, result_raw = read_json(training_root / "result.json")
    if result.get("final_outcome") != "MODEL_FROZEN":
        cleanup = cleanup_short_cache(short_root)
        write_new(state_root / "short_cache_cleanup.json", canonical_json(cleanup))
        terminal(
            state_root,
            outcome="TRAINING_RESULT_INVALID",
            details={"training_result_sha256": sha256_bytes(result_raw)},
        )
        return 6
    final_test_command = [
        args.mlff_python,
        "-I",
        "-B",
        str(final_test_helper),
        "--training-config",
        str(training_config_path),
        "--repo-root",
        str(repo_root),
        "--split",
        str((repo_root / str(cast(dict[str, Any], config["data"])["split_path"])).resolve()),
        "--runs-root",
        str(paths["runs_root"]),
        "--dataset-helper",
        str(dataset_helper),
        "--finetune-helper",
        str(finetune_helper),
        "--model-freeze-root",
        str(training_root),
        "--output-root",
        str(final_test_root),
        "--base-bundle",
        str(cast(dict[str, Any], training_config["base_bundle"])["path"]),
        "--gpupyscf-python",
        args.gpupyscf_python,
        "--gpu-index",
        str(gpu["index"]),
    ]
    write_new(
        state_root / "final_test_claim.json",
        canonical_json(
            {
                "schema": WATCH_SCHEMA,
                "command_sha256": sha256_bytes("\0".join(final_test_command).encode()),
                "model_freeze_result_sha256": sha256_bytes(result_raw),
                "separate_evaluator_process": True,
                "retry": False,
            }
        ),
    )
    final_test_exit = _run_captured(
        final_test_command,
        environment=training_environment,
        stdout_path=state_root / "final_test_stdout",
        stderr_path=state_root / "final_test_stderr",
    )
    cleanup = cleanup_short_cache(short_root)
    write_new(state_root / "short_cache_cleanup.json", canonical_json(cleanup))
    write_new(state_root / "final_test_exit_code", f"{final_test_exit}\n".encode())
    if final_test_exit != 0 or not (final_test_root / "result.json").exists():
        terminal(
            state_root,
            outcome="FINAL_TEST_EVALUATION_FAILED_CONSUMED",
            details={"exit_code": final_test_exit, "cleanup": cleanup},
        )
        return 7
    final_test_result, final_test_raw = read_json(final_test_root / "result.json")
    if final_test_result.get("final_outcome") != "FINAL_TEST_EVALUATED":
        terminal(
            state_root,
            outcome="FINAL_TEST_RESULT_INVALID_CONSUMED",
            details={"final_test_result_sha256": sha256_bytes(final_test_raw)},
        )
        return 8
    terminal(
        state_root,
        outcome="PASS",
        details={
            "training_result_sha256": sha256_bytes(result_raw),
            "frozen_bundle": result.get("frozen_bundle"),
            "final_test_result_sha256": sha256_bytes(final_test_raw),
            "final_test_decision": final_test_result.get("final_test_decision"),
            "cleanup": cleanup,
        },
    )
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    for name in (
        "config",
        "repo-root",
        "dataset-helper",
        "finetune-helper",
        "final-test-helper",
        "training-config",
        "gpupyscf-python",
        "mlff-python",
    ):
        result.add_argument(f"--{name}", required=True)
    result.add_argument("--poll-seconds", type=float, default=300.0)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return watch(parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
