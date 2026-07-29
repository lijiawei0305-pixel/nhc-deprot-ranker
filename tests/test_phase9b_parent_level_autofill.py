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


def test_watcher_claims_once_only_after_predecessor_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = _queue(tmp_path)
    predecessor = tmp_path / "predecessor"
    predecessor.mkdir()
    (predecessor / "controller_exit_code").write_text("0\n")
    run_root = tmp_path / "runs"
    run_root.mkdir()
    driver = tmp_path / "driver"
    driver.mkdir()

    class FakeProcess:
        pid = 1234

        def __init__(self, command: list[str], **_: object) -> None:
            output = Path(command[command.index("--output-root") + 1])
            output.mkdir()
            (output / "controller_exit_code").write_text("0\n")

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
