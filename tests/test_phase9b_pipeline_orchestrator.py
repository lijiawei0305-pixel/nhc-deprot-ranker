from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/phase9b_pipeline_orchestrator.py"
CONFIG = ROOT / "docs/PHASE9B_PIPELINE_CONFIG_V001.json"


def _load():
    spec = importlib.util.spec_from_file_location("phase9b_pipeline_orchestrator_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


orchestrator = _load()


def _config() -> dict[str, object]:
    return orchestrator.load_config(CONFIG, ROOT)[0]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(orchestrator.canonical_json(value))


def _lane_binding(config: dict[str, object], lane: dict[str, object]) -> dict[str, object]:
    return {
        "queue_sha256": lane["queue_sha256"],
        "cpu_list": list(orchestrator.parse_cpu_list(str(lane["cpu_list"]))),
        "threads": lane["threads"],
        "parent_protocol_sha256": orchestrator.PARENT_PROTOCOL_SHA256,
        "scheduler_source_sha256": config["programs"]["autofill"]["adopt_compatible_sha256"][0],
        "science_pilot_only": True,
        "production_accepted": False,
    }


def _fine_binding(config: dict[str, object]) -> dict[str, object]:
    programs = config["programs"]
    fine = config["fine_tune"]
    return {
        "config_sha256": fine["config_sha256"],
        "dataset_helper_sha256": programs["dataset"]["sha256"],
        "finetune_helper_sha256": programs["finetune"]["sha256"],
        "final_test_helper_sha256": programs["final_test"]["sha256"],
        "training_config_sha256": fine["training_config_sha256"],
        "single_training_attempt": True,
        "retry": False,
        "production_accepted": False,
    }


def _adoption_fixture(tmp_path: Path) -> tuple[dict[str, object], dict[str, Path], Path]:
    config = _config()
    runs = tmp_path / "runs"
    runs.mkdir(parents=True)
    for lane in config["lanes"]:
        state = runs / lane["state_root_name"]
        _write_json(state / "queue_binding.json", _lane_binding(config, lane))
        (state / "claims").mkdir()
        (state / "assignments").mkdir()
    fine = config["fine_tune"]
    fine_root = runs / fine["watch_state_root_name"]
    _write_json(fine_root / "binding.json", _fine_binding(config))
    (fine_root / "snapshots").mkdir()
    paths = {"runs_root": runs}
    state_root = runs / "test_orchestrator"
    state_root.mkdir()
    return config, paths, state_root


def test_public_pipeline_config_is_bounded_and_covers_all_112_cpus() -> None:
    config, raw = orchestrator.load_config(CONFIG, ROOT)
    cpus = {
        cpu for lane in config["lanes"] for cpu in orchestrator.parse_cpu_list(lane["cpu_list"])
    }
    assert cpus == set(range(112))
    assert len(config["expected_candidates"]) == 9
    assert config["retry"] is False
    assert config["candidate_replacement"] is False
    assert config["production_accepted"] is False
    assert config["speed_benchmark_after_freeze"] is False
    assert (
        orchestrator.sha256_bytes(raw)
        == "8c41b1dd224d9d7c20ef8eaa88985c3a9b60302ed7fab0dc517a844bdb16fb69"
    )


def test_config_rejects_retry_and_overlapping_lane_cpu(tmp_path: Path) -> None:
    payload = json.loads(CONFIG.read_text())
    payload["retry"] = True
    path = tmp_path / "retry.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(orchestrator.PipelineOrchestratorError, match="retry"):
        orchestrator.load_config(path, ROOT)

    payload = json.loads(CONFIG.read_text())
    payload["lanes"][1]["cpu_list"] = "27-54"
    payload["lanes"][1]["threads"] = 28
    path = tmp_path / "overlap.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(orchestrator.PipelineOrchestratorError, match="overlap"):
        orchestrator.load_config(path, ROOT)


def test_config_rejects_candidate_replacement_or_split_drift(tmp_path: Path) -> None:
    payload = json.loads(CONFIG.read_text())
    payload["candidate_replacement"] = True
    path = tmp_path / "replacement.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(orchestrator.PipelineOrchestratorError, match="candidate_replacement"):
        orchestrator.load_config(path, ROOT)

    payload = json.loads(CONFIG.read_text())
    payload["lanes"][0]["candidates"][0] = payload["lanes"][1]["candidates"][0]
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(orchestrator.PipelineOrchestratorError, match="more than one lane"):
        orchestrator.load_config(path, ROOT)


def test_adopt_validates_existing_writers_and_never_spawns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, paths, state_root = _adoption_fixture(tmp_path)

    def forbidden_spawn(*_: object, **__: object) -> None:
        raise AssertionError("adopt mode must not spawn")

    monkeypatch.setattr(orchestrator.subprocess, "Popen", forbidden_spawn)
    orchestrator._adopt(config, paths, state_root)
    assert len(list((state_root / "adoptions").glob("lane_*.json"))) == 4
    assert (state_root / "adoptions" / "finetune.json").exists()
    assert not (state_root / "children").exists()


def test_adopt_rejects_queue_or_training_binding_mismatch(tmp_path: Path) -> None:
    config, paths, state_root = _adoption_fixture(tmp_path)
    first = config["lanes"][0]
    _write_json(
        paths["runs_root"] / first["state_root_name"] / "queue_binding.json",
        {**_lane_binding(config, first), "queue_sha256": "0" * 64},
    )
    with pytest.raises(orchestrator.PipelineOrchestratorError, match="binding queue"):
        orchestrator._adopt(config, paths, state_root)

    config, paths, state_root = _adoption_fixture(tmp_path / "second")
    fine = config["fine_tune"]
    _write_json(
        paths["runs_root"] / fine["watch_state_root_name"] / "binding.json",
        {**_fine_binding(config), "retry": True},
    )
    with pytest.raises(orchestrator.PipelineOrchestratorError, match="retry"):
        orchestrator._adopt(config, paths, state_root)


def test_start_launches_four_lane_watchers_and_one_finetune_watcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config()
    runs = tmp_path / "runs"
    runs.mkdir()
    state = runs / "orchestrator"
    state.mkdir()
    launched: list[str] = []

    def fake_launch(*, name: str, command: list[str], state_root: Path):
        del command, state_root
        launched.append(name)
        return SimpleNamespace(pid=1000 + len(launched), poll=lambda: None)

    monkeypatch.setattr(orchestrator, "_launch_child", fake_launch)
    monkeypatch.setattr(
        orchestrator,
        "lane_watch_command",
        lambda _config, _paths, lane: ["lane", lane["lane_id"]],
    )
    monkeypatch.setattr(
        orchestrator,
        "finetune_watch_command",
        lambda _config, _paths: ["finetune"],
    )

    def fake_wait(_config: object, _paths: object, _processes: object) -> None:
        assert launched == ["lane_a", "lane_b", "lane_c", "lane_d"]

    monkeypatch.setattr(orchestrator, "wait_for_lane_bindings", fake_wait)
    processes = orchestrator._start(config, {"runs_root": runs}, state)
    assert launched == ["lane_a", "lane_b", "lane_c", "lane_d", "finetune"]
    assert set(processes) == set(launched)


def test_finetune_is_blocked_when_lane_exits_before_binding(tmp_path: Path) -> None:
    config = _config()
    runs = tmp_path / "runs"
    runs.mkdir()
    processes = {
        f"lane_{lane}": SimpleNamespace(poll=lambda lane=lane: 7 if lane == "a" else None)
        for lane in "abcd"
    }
    with pytest.raises(orchestrator.PipelineOrchestratorError, match="before publishing"):
        orchestrator.wait_for_lane_bindings(config, {"runs_root": runs}, processes)


def test_start_refuses_existing_writer_root_before_any_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config()
    runs = tmp_path / "runs"
    runs.mkdir()
    first = config["lanes"][0]
    (runs / first["state_root_name"]).mkdir()
    launched = False

    def fake_launch(**_: object) -> None:
        nonlocal launched
        launched = True

    monkeypatch.setattr(orchestrator, "_launch_child", fake_launch)
    with pytest.raises(orchestrator.PipelineOrchestratorError, match="existing"):
        orchestrator._start(config, {"runs_root": runs}, runs / "state")
    assert launched is False


def test_start_requires_new_driver_identity_but_adopt_accepts_frozen_history(
    tmp_path: Path,
) -> None:
    config = _config()
    runs = tmp_path / "runs"
    old_auto = tmp_path / "phase9b_parent_level_training_driver_d287ef7"
    old_fine = tmp_path / "phase9b_aimnet2_finetune_driver_befa889"
    for root in (runs, old_auto, old_fine):
        root.mkdir()
    args = SimpleNamespace(
        runs_root=str(runs),
        autofill_driver=str(old_auto),
        finetune_driver=str(old_fine),
        gpupyscf_python=sys.executable,
        mlff_python=sys.executable,
    )
    with pytest.raises(orchestrator.PipelineOrchestratorError, match="driver root identity"):
        orchestrator.deployment_paths(config, args, allow_adopt_compatible=False)
    paths = orchestrator.deployment_paths(config, args, allow_adopt_compatible=True)
    assert paths["autofill_driver"] == old_auto
    assert paths["finetune_driver"] == old_fine


def test_snapshot_is_observational_and_tracks_collection_state(tmp_path: Path) -> None:
    config, paths, _ = _adoption_fixture(tmp_path)
    first = config["lanes"][0]
    first_state = paths["runs_root"] / first["state_root_name"]
    output = paths["runs_root"] / "autofill_test_v001"
    _write_json(
        first_state / "claims" / f"000_{first['candidates'][0]}.json",
        {"candidate": first["candidates"][0]},
    )
    _write_json(
        first_state / "assignments" / f"000_{first['candidates'][0]}.json",
        {"candidate": first["candidates"][0], "output_root": str(output)},
    )
    _write_json(output / "training_data" / "cation" / "frame_0000.json", {})
    fine = config["fine_tune"]
    fine_root = paths["runs_root"] / fine["watch_state_root_name"]
    _write_json(
        fine_root / "snapshots" / "000000.json",
        {
            "complete_candidate_count": 1,
            "required_candidate_count": 9,
            "failed_candidates": [],
            "frame_count_by_split": {"train": 1, "validation": 0, "final_test": 0},
            "collection_complete": False,
        },
    )
    snapshot = orchestrator.deployment_snapshot(config, paths)
    assert snapshot["pipeline_state"] == "RUN_LANES"
    assert snapshot["lanes"][0]["current_candidate"] == first["candidates"][0]
    assert snapshot["lanes"][0]["frame_count_by_endpoint"]["cation"] == 1
    assert snapshot["fine_tune"]["latest_snapshot"]["body"]["complete_candidate_count"] == 1


def test_pipeline_state_propagates_failure_and_never_retries() -> None:
    lanes = [{"queue_exhausted": True} for _ in range(4)]
    assert (
        orchestrator.derive_pipeline_state(lanes, {"terminal": {"outcome": "COLLECTION_FAILED"}})
        == "TERMINAL_FAILED"
    )
    assert (
        orchestrator.derive_pipeline_state(lanes, {"terminal": {"outcome": "PASS"}}) == "COMPLETE"
    )
    lanes[0]["lane_terminal"] = {"outcome": "PREDECESSOR_AUDIT_FAILED", "retry": False}
    assert orchestrator.derive_pipeline_state(lanes, {"terminal": None}) == "TERMINAL_FAILED"


def test_commands_preserve_frozen_resources_and_delegate_science(tmp_path: Path) -> None:
    config = _config()
    driver = tmp_path / "driver"
    fine_driver = tmp_path / "fine"
    runs = tmp_path / "runs"
    for root in (driver, fine_driver, runs):
        root.mkdir()
    program = driver / "scripts" / "phase9b_parent_level_autofill.py"
    program.parent.mkdir()
    program.write_text("# helper\n")
    paths = {
        "autofill_driver": driver,
        "finetune_driver": fine_driver,
        "runs_root": runs,
        "gpupyscf_python": Path(sys.executable),
        "mlff_python": Path(sys.executable),
    }
    lane = deepcopy(config["lanes"][2])
    queue = driver / lane["queue_relative_path"]
    queue.parent.mkdir(parents=True)
    queue.write_text("{}\n")
    command = orchestrator.lane_watch_command(config, paths, lane)
    assert command[command.index("--cpu-list") + 1] == "1,56-83"
    assert command[command.index("--threads") + 1] == "29"
    assert command[command.index("--max-memory-mb") + 1] == "40000"
    assert command[command.index("--route-limit-seconds") + 1] == "86400"
    assert "launch-one" not in command


def test_immutable_writer_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    orchestrator.write_new(path, b"{}\n")
    with pytest.raises(FileExistsError):
        orchestrator.write_new(path, b"{}\n")
