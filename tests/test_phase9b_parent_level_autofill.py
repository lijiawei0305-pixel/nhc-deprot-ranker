from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/phase9b_parent_level_autofill.py"


def _load():
    spec = importlib.util.spec_from_file_location("phase9b_parent_level_autofill_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


autofill = _load()


def _xyz(elements: list[str]) -> bytes:
    rows = [str(len(elements)), "frozen test"]
    rows.extend(
        f"{element} {index * 1.2:.4f} 0.0000 0.0000" for index, element in enumerate(elements)
    )
    return ("\n".join(rows) + "\n").encode()


def _queue(tmp_path: Path) -> Path:
    inputs = tmp_path / "input"
    inputs.mkdir()
    cation = inputs / "AAAAAAAAAAAAAA-BBBBBBBBBB-C_cation.xyz"
    neutral = inputs / "AAAAAAAAAAAAAA-BBBBBBBBBB-C_neutral.xyz"
    cation.write_bytes(_xyz(["C", "N", "H", "H"]))
    neutral.write_bytes(_xyz(["C", "N", "H"]))
    payload = {
        "schema": autofill.PROFILE_SCHEMA,
        "parent_protocol_sha256": autofill.PARENT_PROTOCOL_SHA256,
        "science_pilot_only": True,
        "input_root": str(inputs),
        "candidates": [
            {
                "candidate": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
                "electron_count": 14,
                "cation": {
                    "path": str(cation),
                    "sha256": autofill.sha256_bytes(cation.read_bytes()),
                    "atom_count": 4,
                },
                "neutral": {
                    "path": str(neutral),
                    "sha256": autofill.sha256_bytes(neutral.read_bytes()),
                    "atom_count": 3,
                },
                "rigidity": {
                    "selection_class": "rigid_small_nhc",
                    "heavy_atom_count": 2,
                    "rotatable_bonds": 0,
                    "ring_count": 1,
                },
            }
        ],
    }
    path = tmp_path / "queue.json"
    path.write_text(json.dumps(payload))
    return path


def _successful_route(root: Path, candidate: str) -> None:
    endpoint_records: dict[str, dict[str, object]] = {}
    endpoint_results: dict[str, dict[str, object]] = {}
    for endpoint in ("cation", "neutral"):
        endpoint_root = root / "training_data" / endpoint
        endpoint_root.mkdir(parents=True, exist_ok=True)
        frame_raw = autofill.canonical_json({"frame_index": 0})
        (endpoint_root / "frame_0000.json").write_bytes(frame_raw)
        manifest = {
            "schema": "phase9b-parent-level-training-endpoint-v1",
            "candidate": candidate,
            "endpoint": endpoint,
            "complete_geometry_optimization": True,
            "parent_protocol_sha256": autofill.PARENT_PROTOCOL_SHA256,
            "production_accepted": False,
            "frame_count": 1,
            "frames": [
                {
                    "frame_index": 0,
                    "path": "frame_0000.json",
                    "bytes": len(frame_raw),
                    "sha256": autofill.sha256_bytes(frame_raw),
                }
            ],
        }
        manifest_raw = autofill.canonical_json(manifest)
        (endpoint_root / "manifest.json").write_bytes(manifest_raw)
        endpoint_records[endpoint] = {
            "path": "manifest.json",
            "bytes": len(manifest_raw),
            "sha256": autofill.sha256_bytes(manifest_raw),
            "frame_count": 1,
            "endpoint": endpoint,
        }
        endpoint_results[endpoint] = {
            "candidate": candidate,
            "endpoint": endpoint,
            "scf_converged": True,
            "energy_hartree": -100.0 if endpoint == "cation" else -99.5,
            "geometry_optimization": {"converged": True},
            "production_accepted": False,
            "retry": False,
        }
    route = {
        "schema": "phase9b-parent-level-training-route-v1",
        "candidate": candidate,
        "parent_protocol_sha256": autofill.PARENT_PROTOCOL_SHA256,
        "production_accepted": False,
        "endpoint_manifests": endpoint_records,
    }
    route_raw = autofill.canonical_json(route)
    (root / "training_data" / "manifest.json").write_bytes(route_raw)
    (root / "result.json").write_bytes(
        autofill.canonical_json(
            {
                "candidate": candidate,
                "final_outcome": "PASS",
                "route": "pure_pyscf",
                "science_pilot_only": True,
                "production_accepted": False,
                "retry": False,
                "endpoint_results": endpoint_results,
                "deprotonation": {
                    "aimnet2_energy_used": False,
                    "value_kcal_per_mol": 300.0,
                },
                "training_data": {
                    "path": "manifest.json",
                    "bytes": len(route_raw),
                    "sha256": autofill.sha256_bytes(route_raw),
                },
            }
        )
    )
    (root / "controller_exit_code").write_text("0\n")


def test_queue_validates_frozen_rigid_small_identity(tmp_path: Path) -> None:
    payload = autofill.load_queue(_queue(tmp_path))
    assert payload["candidates"][0]["electron_count"] == 14


def test_queue_rejects_symlink_input(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    payload = json.loads(queue.read_text())
    target = Path(payload["candidates"][0]["cation"]["path"])
    replacement = target.with_suffix(".link")
    replacement.symlink_to(target)
    payload["candidates"][0]["cation"]["path"] = str(replacement)
    queue.write_text(json.dumps(payload))
    with pytest.raises(autofill.AutofillError, match="single-link regular file"):
        autofill.load_queue(queue)


def test_queue_rejects_nonrigid_candidate(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    payload = json.loads(queue.read_text())
    payload["candidates"][0]["rigidity"]["rotatable_bonds"] = 4
    queue.write_text(json.dumps(payload))
    with pytest.raises(autofill.AutofillError, match="rotatable-bond"):
        autofill.load_queue(queue)


def _queue_with_atom_map(tmp_path: Path) -> Path:
    queue = _queue(tmp_path)
    payload = json.loads(queue.read_text())
    inputs = Path(payload["input_root"])
    cation = Path(payload["candidates"][0]["cation"]["path"])
    neutral = Path(payload["candidates"][0]["neutral"]["path"])
    cation.write_text("4\nfrozen test\nN 0 0 0\nC 1.2 0 0\nN 2.4 0 0\nH 1.2 0 1.0\n")
    neutral.write_text("3\nfrozen test\nN 0 0 0\nC 1.2 0 0\nN 2.4 0 0\n")
    atom_map = inputs / "map.json"
    atom_map.write_text(json.dumps({"C2_carbene": 1, "N1": 0, "N3": 2}))
    profile = payload["candidates"][0]
    profile["electron_count"] = 20
    profile["cation"]["sha256"] = autofill.sha256_bytes(cation.read_bytes())
    profile["neutral"]["sha256"] = autofill.sha256_bytes(neutral.read_bytes())
    profile["atom_map"] = {
        "path": str(atom_map),
        "sha256": autofill.sha256_bytes(atom_map.read_bytes()),
        "c2_index": 1,
        "n1_index": 0,
        "n3_index": 2,
        "acidic_hydrogen_index": 3,
    }
    queue.write_text(json.dumps(payload))
    return queue


def test_queue_validates_frozen_c2_h_atom_map(tmp_path: Path) -> None:
    queue = _queue_with_atom_map(tmp_path)
    assert autofill.load_queue(queue)["candidates"][0]["atom_map"]["c2_index"] == 1


def test_queue_rejects_wrong_acidic_hydrogen_host(tmp_path: Path) -> None:
    queue = _queue_with_atom_map(tmp_path)
    payload = json.loads(queue.read_text())
    cation = Path(payload["candidates"][0]["cation"]["path"])
    cation.write_text("4\nfrozen test\nN 0 0 0\nC 1.2 0 0\nN 2.4 0 0\nH 1.2 0 3.0\n")
    profile = payload["candidates"][0]
    profile["cation"]["sha256"] = autofill.sha256_bytes(cation.read_bytes())
    queue.write_text(json.dumps(payload))
    with pytest.raises(autofill.AutofillError, match="acidic hydrogen"):
        autofill.load_queue(queue)


def test_watcher_claims_once_only_after_predecessor_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = _queue(tmp_path)
    predecessor = tmp_path / "predecessor"
    predecessor.mkdir()
    _successful_route(predecessor, "ZZZZZZZZZZZZZZ-YYYYYYYYYY-X")
    run_root = tmp_path / "runs"
    run_root.mkdir()
    driver = tmp_path / "driver"
    driver.mkdir()

    class FakeProcess:
        pid = 1234

        def __init__(self, command: list[str], **_: object) -> None:
            output = Path(command[command.index("--output-root") + 1])
            output.mkdir()
            _successful_route(output, command[command.index("--candidate") + 1])

    monkeypatch.setattr(autofill.subprocess, "Popen", FakeProcess)
    args = argparse.Namespace(
        queue=str(queue),
        state_root=str(tmp_path / "state"),
        initial_watch_root=str(predecessor),
        run_root=str(run_root),
        driver=str(driver),
        gpupyscf_python=sys.executable,
        cpu_list="0-1",
        threads=2,
        max_memory_mb=1000,
        route_limit_seconds=100,
        poll_seconds=0.0,
    )
    assert autofill.watch(args) == 0
    claims = list((tmp_path / "state" / "claims").iterdir())
    assignments = list((tmp_path / "state" / "assignments").iterdir())
    assert len(claims) == 1
    assert len(assignments) == 1
    assert (tmp_path / "state" / "queue_exhausted.json").exists()


def test_watcher_stops_lane_when_predecessor_is_not_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = _queue(tmp_path)
    predecessor = tmp_path / "predecessor"
    predecessor.mkdir()
    _successful_route(predecessor, "ZZZZZZZZZZZZZZ-YYYYYYYYYY-X")
    result = json.loads((predecessor / "result.json").read_text())
    result["final_outcome"] = "FAIL"
    (predecessor / "result.json").write_bytes(autofill.canonical_json(result))
    run_root = tmp_path / "runs"
    run_root.mkdir()
    driver = tmp_path / "driver"
    driver.mkdir()

    def forbidden_spawn(*_: object, **__: object) -> None:
        raise AssertionError("a failed predecessor must not launch the next candidate")

    monkeypatch.setattr(autofill.subprocess, "Popen", forbidden_spawn)
    args = argparse.Namespace(
        queue=str(queue),
        state_root=str(tmp_path / "state"),
        initial_watch_root=str(predecessor),
        run_root=str(run_root),
        driver=str(driver),
        gpupyscf_python=sys.executable,
        cpu_list="0-1",
        threads=2,
        max_memory_mb=1000,
        route_limit_seconds=100,
        poll_seconds=0.0,
    )
    assert autofill.watch(args) == 2
    terminal = json.loads((tmp_path / "state" / "lane_terminal.json").read_text())
    assert terminal["outcome"] == "PREDECESSOR_AUDIT_FAILED"
    assert terminal["next_candidate_started"] is False
    assert not list((tmp_path / "state" / "claims").iterdir())


def test_route_audit_rejects_unregistered_frame_and_residual_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = "ZZZZZZZZZZZZZZ-YYYYYYYYYY-X"
    root = tmp_path / "route"
    root.mkdir()
    _successful_route(root, candidate)
    audit = autofill.audit_successful_route(root, expected_candidate=candidate)
    assert audit["candidate"] == candidate
    (root / "training_data" / "cation" / "frame_9999.json").write_text("{}\n")
    with pytest.raises(autofill.AutofillError, match="exact set"):
        autofill.audit_successful_route(root, expected_candidate=candidate)
    (root / "training_data" / "cation" / "frame_9999.json").unlink()
    monkeypatch.setattr(autofill, "_wait_for_process_cleanup", lambda _: [12345])
    with pytest.raises(autofill.AutofillError, match="residual"):
        autofill.audit_successful_route(root, expected_candidate=candidate)


def test_launcher_enables_parent_training_frame_writer(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    payload = autofill.load_queue(queue)
    driver = tmp_path / "driver"
    driver.mkdir()
    args = argparse.Namespace(
        queue=str(queue),
        output_root=str(tmp_path / "out"),
        driver=str(driver),
        gpupyscf_python=sys.executable,
        threads=2,
        cpu_list="0-1",
        max_memory_mb=1000,
        route_limit_seconds=100,
    )
    args.candidate = payload["candidates"][0]["candidate"]
    command = autofill._launcher_command(
        argparse.Namespace(
            **vars(args), run_root=str(tmp_path), state_root=str(tmp_path / "state")
        ),
        payload["candidates"][0],
    )
    assert "--record-training-frames" in command
    assert "--training-data-helper" in command
