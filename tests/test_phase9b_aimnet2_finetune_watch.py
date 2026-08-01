from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/phase9b_aimnet2_finetune_watch.py"
CONFIG = ROOT / "docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V002.json"


def _load():
    spec = importlib.util.spec_from_file_location("phase9b_aimnet2_finetune_watch_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


watcher = _load()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(watcher.canonical_json(value))


def _collection_fixture(tmp_path: Path) -> tuple[dict[str, object], Path]:
    repo = tmp_path / "repo"
    runs = tmp_path / "runs"
    repo.mkdir()
    runs.mkdir()
    split = {
        "train": [{"candidate": f"TRAIN{i:09d}AA-BBBBBBBBBB-C"} for i in range(5)],
        "validation": [{"candidate": f"VALID{i:09d}AA-BBBBBBBBBB-C"} for i in range(2)],
        "final_test": [{"candidate": f"FINAL{i:09d}AA-BBBBBBBBBB-C"} for i in range(2)],
    }
    _write_json(repo / "split.json", split)
    state_roots = [runs / f"lane_{index}" for index in range(4)]
    queue_hashes = [str(index) * 64 for index in range(1, 5)]
    for state, digest in zip(state_roots, queue_hashes, strict=True):
        _write_json(state / "queue_binding.json", {"queue_sha256": digest})
        _write_json(state / "queue_exhausted.json", {"queue_exhausted": True})
    config: dict[str, object] = {
        "data": {
            "split_path": "split.json",
            "required_candidate_count": 9,
        },
        "paths": {"runs_root": str(runs)},
        "collection": {
            "run_name_template": "autofill_{candidate_lower}_v001",
            "required_queue_state_roots": [str(path) for path in state_roots],
            "required_queue_sha256": queue_hashes,
        },
    }
    for profiles in split.values():
        for profile in profiles:
            candidate = profile["candidate"]
            route = runs / f"autofill_{candidate.lower()}_v001"
            _write_json(route / "result.json", {"candidate": candidate, "final_outcome": "PASS"})
            (route / "controller_exit_code").write_text("0\n")
            _write_json(route / "training_data" / "cation" / "frame_0000.json", {})
            _write_json(route / "training_data" / "neutral" / "frame_0000.json", {})
    return config, repo


def test_collection_gate_requires_all_nine_pass_and_all_queues_exhausted(
    tmp_path: Path,
) -> None:
    config, repo = _collection_fixture(tmp_path)
    snapshot = watcher.collection_snapshot(config, repo)
    assert snapshot["collection_complete"] is True
    assert snapshot["complete_candidate_count"] == 9
    assert snapshot["failed_candidates"] == []
    assert snapshot["frame_count_by_split"] == {
        "train": 10,
        "validation": 4,
        "final_test": 4,
    }


def test_collection_failure_is_fail_closed_and_not_replaced(tmp_path: Path) -> None:
    config, repo = _collection_fixture(tmp_path)
    runs = Path(config["paths"]["runs_root"])
    first = watcher.expected_candidates(config, repo)[0][0]
    _write_json(
        runs / f"autofill_{first.lower()}_v001" / "result.json",
        {"candidate": first, "final_outcome": "FAIL"},
    )
    snapshot = watcher.collection_snapshot(config, repo)
    assert snapshot["collection_complete"] is False
    assert snapshot["failed_candidates"] == [first]
    assert snapshot["required_candidate_count"] == 9


def test_lane_terminal_blocks_collection_and_training(tmp_path: Path) -> None:
    config, repo = _collection_fixture(tmp_path)
    lane = Path(config["collection"]["required_queue_state_roots"][0])
    _write_json(
        lane / "lane_terminal.json",
        {
            "outcome": "FINAL_CANDIDATE_AUDIT_FAILED",
            "expected_candidate": "TRAIN000000000AA-BBBBBBBBBB-C",
            "retry": False,
        },
    )
    snapshot = watcher.collection_snapshot(config, repo)
    assert snapshot["collection_complete"] is False
    assert snapshot["failed_queue_states"] == [
        {
            "root": str(lane),
            "outcome": "FINAL_CANDIDATE_AUDIT_FAILED",
            "expected_candidate": "TRAIN000000000AA-BBBBBBBBBB-C",
        }
    ]


def test_gpu_selection_uses_lowest_idle_gpu_with_enough_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            "0, GPU-A, 0, 25000, 32768\n1, GPU-B, 0, 26000, 32768\n",
            "GPU-A, 12345\n",
        ]
    )

    def fake_run(*_: object, **__: object) -> SimpleNamespace:
        return SimpleNamespace(stdout=next(responses))

    monkeypatch.setattr(subprocess, "run", fake_run)
    config = {
        "resource_preflight": {
            "maximum_gpu_utilization_percent": 10,
            "minimum_free_gpu_memory_bytes": 20 * 1024**3,
        }
    }
    selected = watcher.select_gpu(config)
    assert selected is not None
    assert selected["index"] == 1
    assert selected["uuid"] == "GPU-B"


def test_short_cache_is_private_and_cleanup_is_narrow(tmp_path: Path) -> None:
    with pytest.raises(watcher.FineTuneWatchError, match="unsafe"):
        watcher.cleanup_short_cache(Path("/tmp"))
    root = tmp_path / "not-authorized-prefix"
    root.mkdir(mode=0o700)
    with pytest.raises(watcher.FineTuneWatchError, match="unsafe"):
        watcher.cleanup_short_cache(root)


def test_frozen_config_disallows_retry_speed_benchmark_and_production() -> None:
    config = json.loads(CONFIG.read_text())
    assert config["single_training_attempt"] is True
    assert config["retry"] is False
    assert config["production_accepted"] is False
    assert config["post_freeze_evaluation"]["speed_benchmark"] is False
    assert "candidate_replacement" in config["forbidden"]


def test_watcher_freezes_model_before_starting_separate_final_test_process() -> None:
    source = SCRIPT.read_text()
    frozen_gate = source.index('result.get("final_outcome") != "MODEL_FROZEN"')
    evaluator_command = source.index("final_test_command = [")
    assert frozen_gate < evaluator_command
    assert '"separate_evaluator_process": True' in source
    assert '"--scope",\n        "development"' in source


def test_blocked_generation_stops_before_collection_or_dataset_assembly() -> None:
    source = SCRIPT.read_text()
    blocked = source.index('outcome="BLOCKED_BEFORE_TRAINING"')
    collection = source.index("while True:", blocked)
    dataset = source.index("dataset_command = [")
    assert blocked < collection < dataset
