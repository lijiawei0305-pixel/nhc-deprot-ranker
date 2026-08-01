#!/usr/bin/env python3
"""One-shot, molecule-disjoint AIMNet2 fine-tuning for audited P01 frames."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import io
import json
import math
import os
import random
import re
import shutil
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

import numpy as np
import yaml

CONFIG_SCHEMA: Final = "phase9b-aimnet2-model-generation-config-v002"
DATASET_SCHEMA: Final = "phase9b-aimnet2-development-dataset-v2"
RESULT_SCHEMA: Final = "phase9b-aimnet2-model-freeze-result-v002"
BASE_SHA256: Final = "f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28"
MODEL_YAML_SHA256: Final = "f3a374cb0824f522b03a2f423980d5c7121c10fe49718e08782af47e7259b3b1"
SPLIT_SHA256: Final = "772094bc08012f8f40c76994a1600985f11a1956bef66d2c7710006b3aa0b995"
SHORT_RANGE_KEY: Final = "outputs.srcoulomb.rc"
LONG_RANGE_KEY: Final = "outputs.lrcoulomb.rc"


class FineTuneError(RuntimeError):
    """The frozen one-shot fine-tuning contract failed closed."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_regular(path: Path, *, maximum: int = 1 << 30) -> bytes:
    before = path.lstat()
    if path.is_symlink() or not path.is_file() or before.st_nlink != 1:
        raise FineTuneError(f"not a single-link regular file: {path}")
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
                raise FineTuneError("fine-tuning input exceeds size bound")
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if (before.st_dev, before.st_ino, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise FineTuneError("fine-tuning input changed during read")
    return b"".join(chunks)


def write_new(path: Path, raw: bytes) -> dict[str, object]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise FineTuneError("short fine-tuning evidence write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    if read_regular(path, maximum=max(1, len(raw))) != raw:
        raise FineTuneError("fine-tuning evidence reread mismatch")
    return {"path": str(path), "bytes": len(raw), "sha256": sha256_bytes(raw)}


def read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = read_regular(path)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FineTuneError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FineTuneError(f"JSON root is not an object: {path}")
    return cast(dict[str, Any], value), raw


def load_frozen_config(config_path: Path, repo_root: Path) -> tuple[dict[str, Any], bytes]:
    config, raw = read_json(config_path)
    if config.get("schema") != CONFIG_SCHEMA or config.get("single_training_attempt") is not True:
        raise FineTuneError("fine-tuning config identity mismatch")
    if config.get("retry") is not False or config.get("production_accepted") is not False:
        raise FineTuneError("fine-tuning config widened the one-shot boundary")
    readiness = config.get("readiness")
    if not isinstance(readiness, dict) or readiness.get("state") != "REGISTERED":
        raise FineTuneError("generation is BLOCKED_BEFORE_TRAINING")
    for gate in (
        "final_test_isolation_implemented",
        "final_test_evaluator_scientifically_complete",
        "epoch_zero_selection_implemented",
        "validation_selection_gates_frozen",
        "baseline_eligibility_gates_frozen",
        "final_test_acceptance_gates_frozen",
        "stopping_handoff_promotion_gates_frozen",
    ):
        if readiness.get(gate) is not True:
            raise FineTuneError(f"generation readiness gate is not frozen: {gate}")
    base = cast(dict[str, Any], config.get("base_bundle"))
    model = cast(dict[str, Any], config.get("training_model"))
    data = cast(dict[str, Any], config.get("data"))
    if (
        base.get("sha256") != BASE_SHA256
        or base.get("embedded_model_yaml_sha256") != MODEL_YAML_SHA256
    ):
        raise FineTuneError("base model identity drifted")
    if data.get("sealed_final_test_commitment") != {
        "split_registry_sha256": SPLIT_SHA256,
        "candidate_count": 2,
    }:
        raise FineTuneError("molecule split or final-test isolation drifted")
    forbidden_final_test_keys = {"split_path", "final_test_directory", "final_test_candidates"}
    if forbidden_final_test_keys.intersection(data):
        raise FineTuneError("training config exposes final-test identity or path")
    model_path = (repo_root / str(model["path"])).resolve(strict=True)
    if sha256_bytes(read_regular(model_path)) != model.get("sha256"):
        raise FineTuneError("training model YAML SHA256 mismatch")
    return config, raw


def _verify_receipt(receipt: object, *, root: Path) -> None:
    if not isinstance(receipt, dict):
        raise FineTuneError("dataset receipt is not an object")
    path = Path(str(receipt.get("path", ""))).resolve(strict=True)
    if not path.is_relative_to(root):
        raise FineTuneError("dataset receipt escaped the dataset root")
    raw = read_regular(path)
    if len(raw) != receipt.get("bytes") or sha256_bytes(raw) != receipt.get("sha256"):
        raise FineTuneError("dataset receipt binding mismatch")


def validate_dataset(dataset_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    root = dataset_root.resolve(strict=True)
    manifest, manifest_raw = read_json(root / "manifest.json")
    if (
        manifest.get("schema") != DATASET_SCHEMA
        or manifest.get("scope") != "development"
        or manifest.get("split_sha256") != SPLIT_SHA256
        or manifest.get("candidate_count") != 7
        or manifest.get("final_test_payload_present") is not False
        or manifest.get("final_test_used_for_training") is not False
    ):
        raise FineTuneError("training dataset manifest identity mismatch")
    target = manifest.get("target_definition")
    if not isinstance(target, dict) or target.get("external_d3_required_at_inference") is not True:
        raise FineTuneError("training dataset did not subtract external D3")
    files = manifest.get("files")
    counts = manifest.get("frame_count_by_split")
    if not isinstance(files, dict) or not isinstance(counts, dict):
        raise FineTuneError("training dataset file set is missing")
    if set(files) != {"train", "validation"} or set(counts) != {"train", "validation"}:
        raise FineTuneError("development dataset exposes a non-development split")
    if (root / "final_test").exists():
        raise FineTuneError("final-test directory is visible to the training process")
    for split in ("train", "validation"):
        receipts = files.get(split)
        if (
            not isinstance(receipts, list)
            or not receipts
            or type(counts.get(split)) is not int
            or counts[split] <= 0
        ):
            raise FineTuneError(f"training dataset split is empty: {split}")
        for receipt in receipts:
            _verify_receipt(receipt, root=root)
    candidates = manifest.get("candidate_evidence")
    if not isinstance(candidates, list) or len(candidates) != 7:
        raise FineTuneError("training dataset candidate evidence is incomplete")
    observed = {
        (item.get("candidate"), item.get("split")) for item in candidates if isinstance(item, dict)
    }
    if {split for _, split in observed} != {"train", "validation"}:
        raise FineTuneError("training dataset candidate split drifted")
    expected_counts = cast(
        dict[str, int], cast(dict[str, Any], config["data"])["development_candidate_count_by_split"]
    )
    observed_counts = {
        split: sum(observed_split == split for _, observed_split in observed)
        for split in ("train", "validation")
    }
    if observed_counts != expected_counts:
        raise FineTuneError("development candidate counts drifted")
    if (
        manifest.get("sealed_final_test_commitment")
        != cast(dict[str, Any], config["data"])["sealed_final_test_commitment"]
    ):
        raise FineTuneError("sealed final-test commitment drifted")
    for item in candidates:
        endpoints = cast(dict[str, Any], cast(dict[str, Any], item)["endpoints"])
        if set(endpoints) != {"cation", "neutral"}:
            raise FineTuneError("training dataset endpoint set drifted")
        for endpoint in endpoints.values():
            projections = cast(dict[str, Any], endpoint).get("d3_projections")
            if not isinstance(projections, list) or not projections:
                raise FineTuneError("D3 projection evidence is missing")
            for receipt in projections:
                _verify_receipt(receipt, root=root)
    return {
        "manifest_sha256": sha256_bytes(manifest_raw),
        "frame_count_by_split": counts,
        "candidate_count": len(candidates),
    }


def migrate_base_state(state: dict[str, Any], *, to_training: bool) -> dict[str, Any]:
    migrated = dict(state)
    source, destination = (
        (SHORT_RANGE_KEY, LONG_RANGE_KEY) if to_training else (LONG_RANGE_KEY, SHORT_RANGE_KEY)
    )
    if source not in migrated or destination in migrated:
        raise FineTuneError("Coulomb state-key migration contract failed")
    migrated[destination] = migrated.pop(source)
    return migrated


def validate_export_metadata(base: dict[str, Any], exported: dict[str, Any]) -> None:
    immutable = {
        "format_version",
        "model_yaml",
        "cutoff",
        "needs_coulomb",
        "needs_dispersion",
        "coulomb_mode",
        "coulomb_sr_rc",
        "coulomb_sr_envelope",
        "d3_params",
        "has_embedded_lr",
        "implemented_species",
    }
    if any(exported.get(key) != base.get(key) for key in immutable):
        raise FineTuneError("fine-tuned export changed frozen runtime metadata")
    if exported.get("needs_coulomb") is not True or exported.get("needs_dispersion") is not True:
        raise FineTuneError("fine-tuned export dropped an external physical term")


def _package_versions(config: dict[str, Any]) -> dict[str, str]:
    expected = cast(dict[str, str], config["environment"])
    distributions = {
        "aimnet_version": "aimnet",
        "torch_version": "torch",
        "numpy_version": "numpy",
        "pytorch_ignite_version": "pytorch-ignite",
        "omegaconf_version": "omegaconf",
        "nvalchemi_toolkit_ops_version": "nvalchemi-toolkit-ops",
        "ase_version": "ase",
    }
    observed = {key: importlib.metadata.version(package) for key, package in distributions.items()}
    for key, value in observed.items():
        if value != expected[key]:
            raise FineTuneError(f"fine-tuning package version drifted: {key}")
    return observed


def _available_memory_bytes() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise FineTuneError("MemAvailable is unavailable")


def resource_preflight(
    config: dict[str, Any], output_parent: Path, torch: Any, physical_gpu_index: int
) -> dict[str, object]:
    limits = cast(dict[str, Any], config["resource_preflight"])
    disk_free = shutil.disk_usage(output_parent).free
    host_available = _available_memory_bytes()
    if disk_free < int(limits["minimum_free_disk_bytes"]):
        raise FineTuneError("insufficient disk for one-shot fine-tuning")
    if host_available < int(limits["minimum_available_host_memory_bytes"]):
        raise FineTuneError("insufficient host memory for one-shot fine-tuning")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise FineTuneError("fine-tuning process does not see exactly one CUDA GPU")
    snapshot = subprocess.run(
        [
            "nvidia-smi",
            "-i",
            str(physical_gpu_index),
            "--query-gpu=index,uuid,utilization.gpu,memory.free,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    fields = [field.strip() for field in snapshot.split(",")]
    if len(fields) != 5 or int(fields[0]) != physical_gpu_index:
        raise FineTuneError("GPU resource snapshot is invalid")
    utilization = int(fields[2])
    if utilization > int(limits["maximum_gpu_utilization_percent"]):
        raise FineTuneError("selected GPU is already active")
    compute_processes = subprocess.run(
        [
            "nvidia-smi",
            "-i",
            str(physical_gpu_index),
            "--query-compute-apps=pid",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    foreign_pids = {
        int(value.strip())
        for value in compute_processes
        if value.strip().isdigit() and int(value.strip()) != os.getpid()
    }
    if foreign_pids:
        raise FineTuneError("selected GPU has a foreign compute process")
    free_gpu, total_gpu = torch.cuda.mem_get_info(0)
    if free_gpu < int(limits["minimum_free_gpu_memory_bytes"]):
        raise FineTuneError("insufficient free GPU memory for one-shot fine-tuning")
    return {
        "disk_free_bytes": disk_free,
        "host_available_memory_bytes": host_available,
        "gpu_free_bytes": int(free_gpu),
        "gpu_total_bytes": int(total_gpu),
        "gpu_name": torch.cuda.get_device_name(0),
        "physical_gpu_index": physical_gpu_index,
        "gpu_uuid": fields[1],
        "gpu_utilization_percent": utilization,
        "foreign_compute_processes": [],
    }


def _evaluate(model: Any, loader: Any, loss_fn: Any, prepare_batch: Any) -> dict[str, float]:
    model.eval()
    weighted_loss = 0.0
    energy_absolute = 0.0
    force_absolute = 0.0
    samples = 0
    force_components = 0
    for x, y in loader:
        x = prepare_batch(x, device="cuda", non_blocking=True)
        y = prepare_batch(y, device="cuda", non_blocking=True)
        predicted = model(x)
        batch = int(y["energy"].shape[0])
        loss = loss_fn(predicted, y)["loss"]
        if not math.isfinite(float(loss.detach().cpu())):
            raise FineTuneError("validation loss is non-finite")
        weighted_loss += float(loss.detach().cpu()) * batch
        energy_absolute += float((predicted["energy"] - y["energy"]).abs().sum().detach().cpu())
        force_absolute += float((predicted["forces"] - y["forces"]).abs().sum().detach().cpu())
        samples += batch
        force_components += int(y["forces"].numel())
    if samples <= 0 or force_components <= 0:
        raise FineTuneError("evaluation dataset is empty")
    return {
        "weighted_loss": weighted_loss / samples,
        "energy_mae_ev": energy_absolute / samples,
        "force_mae_ev_per_angstrom": force_absolute / force_components,
        "sample_count": float(samples),
    }


def evaluate_frozen_bundle(
    *,
    bundle_path: Path,
    dataset_split_root: Path,
    config: dict[str, Any],
    repo_root: Path,
    gpu_index: int,
) -> dict[str, float]:
    """Evaluate one already-frozen bundle; called only by the separate evaluator process."""

    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    import torch  # type: ignore[import-not-found]
    from aimnet.config import build_module  # type: ignore[import-not-found]
    from aimnet.data import SizeGroupedDataset, SizeGroupedSampler  # type: ignore[import-not-found]
    from aimnet.modules import Forces  # type: ignore[import-not-found]
    from aimnet.train.loss import MTLoss  # type: ignore[import-not-found]
    from aimnet.train.utils import prepare_batch  # type: ignore[import-not-found]

    bundle_raw = read_regular(bundle_path)
    bundle = torch.load(io.BytesIO(bundle_raw), map_location="cpu", weights_only=False)
    if not isinstance(bundle, dict) or not isinstance(bundle.get("state_dict"), dict):
        raise FineTuneError("evaluation bundle is invalid")
    model_path = (repo_root / str(cast(dict[str, Any], config["training_model"])["path"])).resolve(
        strict=True
    )
    core = build_module(copy.deepcopy(yaml.safe_load(read_regular(model_path))))
    core.outputs.atomic_shift.double()
    evaluation_state = migrate_base_state(dict(bundle["state_dict"]), to_training=True)
    core.load_state_dict(evaluation_state, strict=True)
    model = Forces(core).cuda()
    data = cast(dict[str, Any], config["data"])
    training = cast(dict[str, Any], config["training"])
    x_keys = list(data["x"])
    y_keys = list(data["y"])
    dataset = SizeGroupedDataset(str(dataset_split_root), keys=x_keys + y_keys)
    sampler = SizeGroupedSampler(
        dataset,
        batch_size=int(training["batch_size"]),
        batch_mode=str(training["batch_mode"]),
        shuffle=False,
        batches_per_epoch=-1,
        seed=int(training["seed"]),
    )
    loader = dataset.get_loader(sampler, x_keys, y_keys, num_workers=0, pin_memory=True)
    loss_config = cast(dict[str, float], training["loss"])
    loss_fn = MTLoss(
        {
            "energy": {
                "fn": "aimnet.train.loss.energy_loss_fn",
                "weight": float(loss_config["energy_weight"]),
            },
            "forces": {
                "fn": "aimnet.train.loss.peratom_loss_fn",
                "weight": float(loss_config["forces_weight"]),
                "kwargs": {"key_true": "forces", "key_pred": "forces"},
            },
        }
    )
    return _evaluate(model, loader, loss_fn, prepare_batch)


def _save_torch_new(path: Path, value: object, torch: Any) -> dict[str, object]:
    buffer = io.BytesIO()
    torch.save(value, buffer)
    return write_new(path, buffer.getvalue())


def run_training(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve(strict=True)
    config_path = Path(args.config).resolve(strict=True)
    config, config_raw = load_frozen_config(config_path, repo_root)
    configured_paths = cast(dict[str, Any], config["paths"])
    dataset_root = Path(args.dataset_root).resolve(strict=True)
    output_root = Path(args.output_root)
    if (
        str(dataset_root) != configured_paths["dataset_root"]
        or str(output_root) != configured_paths["training_root"]
    ):
        raise FineTuneError("fine-tuning root differs from frozen config")
    if output_root.exists():
        raise FineTuneError("fine-tuning output root already exists")
    dataset_evidence = validate_dataset(dataset_root, config)
    base_path = Path(args.base_bundle).resolve(strict=True)
    base_raw = read_regular(base_path)
    if sha256_bytes(base_raw) != BASE_SHA256:
        raise FineTuneError("AIMNet2 base bundle SHA256 mismatch")
    model_path = (repo_root / str(cast(dict[str, Any], config["training_model"])["path"])).resolve(
        strict=True
    )
    model_raw = read_regular(model_path)

    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu_index)
    import torch
    from aimnet.config import build_module
    from aimnet.data import (
        SizeGroupedDataset,
        SizeGroupedSampler,
    )
    from aimnet.models.base import load_model  # type: ignore[import-not-found]
    from aimnet.modules import Forces
    from aimnet.train.loss import MTLoss
    from aimnet.train.utils import prepare_batch

    versions = _package_versions(config)
    resources = resource_preflight(config, output_root.parent, torch, args.gpu_index)
    expected_cuda = str(cast(dict[str, Any], config["environment"])["cuda_version"])
    if str(torch.version.cuda) != expected_cuda:
        raise FineTuneError("CUDA version drifted")
    output_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    started = time.monotonic()
    training = cast(dict[str, Any], config["training"])
    seed = int(training["seed"])
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False

    base = torch.load(io.BytesIO(base_raw), map_location="cpu", weights_only=False)
    if (
        not isinstance(base, dict)
        or sha256_bytes(str(base["model_yaml"]).encode()) != MODEL_YAML_SHA256
    ):
        raise FineTuneError("base bundle embedded model identity mismatch")
    training_model_config = yaml.safe_load(model_raw)
    core = build_module(copy.deepcopy(training_model_config))
    core.outputs.atomic_shift.double()
    training_state = migrate_base_state(dict(base["state_dict"]), to_training=True)
    core.load_state_dict(training_state, strict=True)
    patterns = [re.compile(value) for value in training["trainable_parameter_regex"]]
    trainable_names: list[str] = []
    for name, parameter in core.named_parameters():
        enabled = any(pattern.search(name) for pattern in patterns)
        parameter.requires_grad_(enabled)
        if enabled:
            trainable_names.append(name)
    if not trainable_names or any(
        not name.startswith("outputs.energy_mlp.") for name in trainable_names
    ):
        raise FineTuneError("fine-tuning trainable parameter boundary drifted")
    model = Forces(core).cuda()

    keys = list(cast(dict[str, Any], config["data"])["x"]) + list(
        cast(dict[str, Any], config["data"])["y"]
    )
    train_ds = SizeGroupedDataset(str(dataset_root / "train"), keys=keys)
    validation_ds = SizeGroupedDataset(str(dataset_root / "validation"), keys=keys)
    if len(train_ds) <= 0 or len(validation_ds) <= 0:
        raise FineTuneError("fine-tuning train or validation dataset is empty")
    batch_size = int(training["batch_size"])
    train_sampler = SizeGroupedSampler(
        train_ds,
        batch_size=batch_size,
        batch_mode=str(training["batch_mode"]),
        shuffle=True,
        batches_per_epoch=int(training["batches_per_epoch"]),
        seed=seed,
    )
    validation_sampler = SizeGroupedSampler(
        validation_ds,
        batch_size=batch_size,
        batch_mode=str(training["batch_mode"]),
        shuffle=False,
        batches_per_epoch=-1,
        seed=seed,
    )
    x_keys = list(cast(dict[str, Any], config["data"])["x"])
    y_keys = list(cast(dict[str, Any], config["data"])["y"])
    train_loader = train_ds.get_loader(
        train_sampler, x_keys, y_keys, num_workers=0, pin_memory=True
    )
    validation_loader = validation_ds.get_loader(
        validation_sampler, x_keys, y_keys, num_workers=0, pin_memory=True
    )
    loss_config = cast(dict[str, float], training["loss"])
    loss_fn = MTLoss(
        {
            "energy": {
                "fn": "aimnet.train.loss.energy_loss_fn",
                "weight": float(loss_config["energy_weight"]),
            },
            "forces": {
                "fn": "aimnet.train.loss.peratom_loss_fn",
                "weight": float(loss_config["forces_weight"]),
                "kwargs": {"key_true": "forces", "key_pred": "forces"},
            },
        }
    )
    optimizer = torch.optim.RAdam(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=float(training["learning_rate"]),
        weight_decay=float(training["weight_decay"]),
    )
    scheduler_config = cast(dict[str, Any], training["scheduler"])
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        factor=float(scheduler_config["factor"]),
        patience=int(scheduler_config["patience_epochs"]),
    )
    baseline_validation = _evaluate(model, validation_loader, loss_fn, prepare_batch)
    history: list[dict[str, object]] = []
    checkpoints: list[dict[str, object]] = []
    best_loss = math.inf
    best_epoch = -1
    best_state: dict[str, Any] | None = None
    for epoch in range(1, int(training["epochs"]) + 1):
        model.train()
        training_loss = 0.0
        batches = 0
        for x, y in train_loader:
            x = prepare_batch(x, device="cuda", non_blocking=True)
            y = prepare_batch(y, device="cuda", non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            predicted = model(x)
            loss = loss_fn(predicted, y)["loss"]
            if not math.isfinite(float(loss.detach().cpu())):
                raise FineTuneError("training loss is non-finite")
            loss.backward()
            torch.nn.utils.clip_grad_value_(
                model.parameters(), float(training["gradient_clip_value"])
            )
            optimizer.step()
            training_loss += float(loss.detach().cpu())
            batches += 1
        if batches <= 0:
            raise FineTuneError("training epoch had no batches")
        validation = _evaluate(model, validation_loader, loss_fn, prepare_batch)
        validation_loss = validation["weighted_loss"]
        learning_rate = float(optimizer.param_groups[0]["lr"])
        improved = validation_loss < best_loss
        if improved:
            best_loss = validation_loss
            best_epoch = epoch
            best_state = {
                name: tensor.detach().cpu().clone() for name, tensor in core.state_dict().items()
            }
            receipt = _save_torch_new(
                output_root / "checkpoints" / f"best_epoch_{epoch:04d}.pt",
                best_state,
                torch,
            )
            receipt.update({"epoch": epoch, "validation_weighted_loss": validation_loss})
            checkpoints.append(receipt)
        history.append(
            {
                "epoch": epoch,
                "train_batch_mean_weighted_loss": training_loss / batches,
                "validation": validation,
                "learning_rate": learning_rate,
                "selected_as_best": improved,
            }
        )
        scheduler.step(validation_loss)
        if float(optimizer.param_groups[0]["lr"]) < float(
            scheduler_config["minimum_learning_rate"]
        ):
            break
    if best_state is None or best_epoch <= 0:
        raise FineTuneError("fine-tuning produced no selectable validation checkpoint")
    core.load_state_dict(best_state, strict=True)
    selected_validation = _evaluate(model, validation_loader, loss_fn, prepare_batch)

    exported = {key: value for key, value in base.items() if key != "state_dict"}
    exported["state_dict"] = migrate_base_state(best_state, to_training=False)
    validate_export_metadata(base, exported)
    embedded_config = yaml.safe_load(str(base["model_yaml"]))
    audit_core = build_module(copy.deepcopy(embedded_config))
    audit_core.outputs.atomic_shift.double()
    audit_core.load_state_dict(exported["state_dict"], strict=True)
    final_bundle_path = output_root / str(configured_paths["final_bundle_name"])
    final_bundle_receipt = _save_torch_new(final_bundle_path, exported, torch)
    frozen_bundle_sha256 = str(final_bundle_receipt["sha256"])
    _, runtime_metadata = load_model(str(final_bundle_path), device="cpu")
    runtime_metadata_dict = dict(runtime_metadata)
    if (
        runtime_metadata_dict.get("needs_coulomb") is not True
        or runtime_metadata_dict.get("needs_dispersion") is not True
        or runtime_metadata_dict.get("d3_params") != base.get("d3_params")
    ):
        raise FineTuneError("frozen bundle runtime load audit failed")

    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "science_pilot_only": True,
        "production_accepted": False,
        "production_label_inserted": False,
        "single_training_attempt": True,
        "retry": False,
        "config_sha256": sha256_bytes(config_raw),
        "dataset": dataset_evidence,
        "base_bundle_sha256": BASE_SHA256,
        "training_model_sha256": sha256_bytes(model_raw),
        "environment": versions,
        "resources": resources,
        "seed": seed,
        "trainable_parameter_names": trainable_names,
        "trainable_parameter_count": sum(
            parameter.numel() for parameter in core.parameters() if parameter.requires_grad
        ),
        "baseline_validation": baseline_validation,
        "selected_epoch": best_epoch,
        "selected_validation": selected_validation,
        "checkpoints": checkpoints,
        "frozen_bundle": final_bundle_receipt,
        "frozen_bundle_runtime_metadata": runtime_metadata_dict,
        "frozen_bundle_sha256": frozen_bundle_sha256,
        "final_test_access": "not_mounted_not_read_not_enumerated",
        "final_test_commitment": cast(dict[str, Any], config["data"])[
            "sealed_final_test_commitment"
        ],
        "final_test_consumed": False,
        "speed_benchmark_run": False,
        "wall_seconds": time.monotonic() - started,
        "final_outcome": "MODEL_FROZEN",
    }
    write_new(output_root / "training_history.json", canonical_json(history))
    write_new(output_root / "result.json", canonical_json(result))
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--config", required=True)
    result.add_argument("--repo-root", required=True)
    result.add_argument("--dataset-root", required=True)
    result.add_argument("--output-root", required=True)
    result.add_argument("--base-bundle", required=True)
    result.add_argument("--gpu-index", required=True, type=int)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    run_training(parser().parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
