#!/usr/bin/env python3
"""One-time final-test consumer for an already frozen AIMNet2 generation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

RESULT_SCHEMA: Final = "phase9b-aimnet2-final-test-result-v1"
DATASET_SCHEMA: Final = "phase9b-aimnet2-final-test-dataset-v1"
SPLIT_SCHEMA: Final = "phase9b-aimnet2-finetune-split-v002"


class FinalTestError(RuntimeError):
    """The one-time final-test authority failed closed."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_regular(path: Path, *, maximum: int = 1 << 30) -> bytes:
    before = path.lstat()
    if path.is_symlink() or not path.is_file() or before.st_nlink != 1:
        raise FinalTestError(f"not a single-link regular file: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw = b""
        while True:
            chunk = os.read(fd, min(1 << 20, maximum + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
            if len(raw) > maximum:
                raise FinalTestError("final-test input exceeds size bound")
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if (before.st_dev, before.st_ino, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise FinalTestError("final-test input changed during read")
    return raw


def write_new(path: Path, raw: bytes) -> dict[str, object]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise FinalTestError("short final-test evidence write")
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    if read_regular(path, maximum=max(1, len(raw))) != raw:
        raise FinalTestError("final-test evidence reread mismatch")
    return {"path": str(path), "bytes": len(raw), "sha256": sha256_bytes(raw)}


def read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = read_regular(path)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise FinalTestError(f"JSON root is not an object: {path}")
    return cast(dict[str, Any], value), raw


def _load_helper(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("phase9b_frozen_model_evaluator", path)
    if spec is None or spec.loader is None:
        raise FinalTestError("cannot load frozen evaluator helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def consume_and_evaluate(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve(strict=True)
    training_config_path = Path(args.training_config).resolve(strict=True)
    preregistered_config, _ = read_json(training_config_path)
    readiness = preregistered_config.get("readiness")
    if not isinstance(readiness, dict) or readiness.get("state") != "REGISTERED":
        raise FinalTestError("generation is BLOCKED_BEFORE_TRAINING")
    if readiness.get("final_test_acceptance_gates_frozen") is not True:
        raise FinalTestError("final-test acceptance gates are not frozen")
    if readiness.get("final_test_evaluator_scientifically_complete") is not True:
        raise FinalTestError("final-test evaluator is not scientifically complete")
    split_path = Path(args.split).resolve(strict=True)
    split, split_raw = read_json(split_path)
    if split.get("schema") != SPLIT_SCHEMA:
        raise FinalTestError("final-test split schema mismatch")
    final_profiles = split.get("final_test")
    if not isinstance(final_profiles, list) or len(final_profiles) != 2:
        raise FinalTestError("sealed final-test cohort mismatch")
    candidates = [str(profile["candidate"]) for profile in final_profiles]
    output_root = Path(args.output_root)
    output_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    model_freeze_root = Path(args.model_freeze_root).resolve(strict=True)
    freeze_result, freeze_raw = read_json(model_freeze_root / "result.json")
    if freeze_result.get("final_outcome") != "MODEL_FROZEN":
        raise FinalTestError("generation is not MODEL_FROZEN")
    bundle_receipt = freeze_result.get("frozen_bundle")
    if not isinstance(bundle_receipt, dict):
        raise FinalTestError("frozen bundle receipt is absent")
    frozen_bundle = Path(str(bundle_receipt["path"])).resolve(strict=True)
    frozen_raw = read_regular(frozen_bundle)
    if sha256_bytes(frozen_raw) != bundle_receipt.get("sha256"):
        raise FinalTestError("frozen bundle binding mismatch")
    evaluator_source = Path(__file__).resolve(strict=True)
    claim = {
        "schema": "phase9b-aimnet2-final-test-consumption-v1",
        "generation_id": "phase9b-aimnet2-nhc-p01-v002",
        "cohort_commitment_sha256": sha256_bytes(split_raw),
        "candidate_identities": candidates,
        "frozen_bundle_sha256": sha256_bytes(frozen_raw),
        "model_freeze_result_sha256": sha256_bytes(freeze_raw),
        "evaluator_sha256": sha256_bytes(read_regular(evaluator_source)),
        "claimed_before_payload_read": True,
        "irreversible": True,
        "timestamp_ns": time.time_ns(),
    }
    claim_receipt = write_new(output_root / "consumption_claim.json", canonical_json(claim))

    dataset_root = output_root / "dataset"
    command = [
        args.gpupyscf_python,
        "-I",
        "-B",
        str(Path(args.dataset_helper).resolve(strict=True)),
        "--split",
        str(split_path),
        "--runs-root",
        str(Path(args.runs_root).resolve(strict=True)),
        "--output-root",
        str(dataset_root),
        "--scope",
        "final_test",
    ]
    completed = subprocess.run(command, check=False, capture_output=True)
    write_new(output_root / "dataset_stdout", completed.stdout)
    write_new(output_root / "dataset_stderr", completed.stderr)
    if completed.returncode != 0:
        raise FinalTestError("consumed final-test dataset assembly failed")
    manifest, manifest_raw = read_json(dataset_root / "manifest.json")
    if (
        manifest.get("schema") != DATASET_SCHEMA
        or manifest.get("scope") != "final_test"
        or set(cast(dict[str, Any], manifest.get("files", {}))) != {"final_test"}
        or manifest.get("candidate_count") != 2
    ):
        raise FinalTestError("final-test dataset boundary mismatch")

    helper = _load_helper(Path(args.finetune_helper).resolve(strict=True))
    config, config_raw = helper.load_frozen_config(training_config_path, repo_root)
    frozen_metrics = helper.evaluate_frozen_bundle(
        bundle_path=frozen_bundle,
        dataset_split_root=dataset_root / "final_test",
        config=config,
        repo_root=repo_root,
        gpu_index=args.gpu_index,
    )
    base_path = Path(args.base_bundle).resolve(strict=True)
    base_metrics = helper.evaluate_frozen_bundle(
        bundle_path=base_path,
        dataset_split_root=dataset_root / "final_test",
        config=config,
        repo_root=repo_root,
        gpu_index=args.gpu_index,
    )
    if sha256_bytes(read_regular(frozen_bundle)) != claim["frozen_bundle_sha256"]:
        raise FinalTestError("frozen bundle changed during final-test evaluation")
    result = {
        "schema": RESULT_SCHEMA,
        "generation_id": claim["generation_id"],
        "consumption_claim": claim_receipt,
        "config_sha256": sha256_bytes(config_raw),
        "dataset_manifest_sha256": sha256_bytes(manifest_raw),
        "frozen_bundle_sha256": claim["frozen_bundle_sha256"],
        "frozen_generation_metrics": frozen_metrics,
        "unchanged_base_metrics": base_metrics,
        "checkpoint_selection_changed": False,
        "thresholds_changed": False,
        "final_test_decision": "UNADJUDICATED_THRESHOLDS_NOT_FROZEN",
        "production_accepted": False,
        "production_label_inserted": False,
        "final_outcome": "FINAL_TEST_EVALUATED",
    }
    write_new(output_root / "result.json", canonical_json(result))
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    for name in (
        "training-config",
        "repo-root",
        "split",
        "runs-root",
        "dataset-helper",
        "finetune-helper",
        "model-freeze-root",
        "output-root",
        "base-bundle",
        "gpupyscf-python",
    ):
        result.add_argument(f"--{name}", required=True)
    result.add_argument("--gpu-index", required=True, type=int)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    consume_and_evaluate(parser().parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
