from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase9b_parent_level_gtho_continuation.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("gtho_continuation_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _xyz(shift: float = 0.0) -> bytes:
    return (f"3\nframe\nC {shift:.1f} 0.0 0.0\nN 0.0 1.0 0.0\nH 0.0 0.0 1.0\n").encode()


def test_last_complete_frame_is_copied_without_reserialization() -> None:
    module = _load()
    first = _xyz(0.0)
    last = _xyz(0.5)
    observed, count = module.last_complete_xyz_frame(
        first + last,
        expected_atoms=3,
        expected_elements=("C", "N", "H"),
    )
    assert observed == last
    assert count == 2


def test_incomplete_or_reordered_trajectory_is_rejected() -> None:
    module = _load()
    with pytest.raises(module.ContinuationError, match="incomplete"):
        module.last_complete_xyz_frame(
            _xyz() + b"3\npartial\nC 0 0 0\n",
            expected_atoms=3,
            expected_elements=("C", "N", "H"),
        )
    reordered = _xyz().replace(b"C 0.0", b"O 0.0", 1)
    with pytest.raises(module.ContinuationError, match="element order"):
        module.last_complete_xyz_frame(
            reordered,
            expected_atoms=3,
            expected_elements=("C", "N", "H"),
        )


def test_basic_route_audit_requires_both_converged_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    root = tmp_path.resolve()
    payload = {
        "candidate": module.CANDIDATE,
        "final_outcome": "PASS",
        "science_pilot_only": True,
        "production_accepted": False,
        "endpoint_results": {
            endpoint: {
                "candidate": module.CANDIDATE,
                "endpoint": endpoint,
                "scf_converged": True,
                "geometry_optimization": {"converged": True},
                "energy_hartree": -100.0 + index,
            }
            for index, endpoint in enumerate(("cation", "neutral"))
        },
        "deprotonation": {
            "aimnet2_energy_used": False,
            "value_kcal_per_mol": 200.0,
        },
    }
    (root / "result.json").write_bytes(module.canonical_json(payload))
    monkeypatch.setattr(module, "residual_processes", lambda _root: [])
    assert module.basic_route_audit(root, expected_candidate=module.CANDIDATE)["audit_pass"]
    payload["endpoint_results"]["neutral"]["scf_converged"] = False
    (root / "result.json").write_bytes(module.canonical_json(payload))
    with pytest.raises(module.ContinuationError, match="neutral endpoint"):
        module.basic_route_audit(root, expected_candidate=module.CANDIDATE)


def test_contract_is_one_continuation_without_production_or_protocol_drift() -> None:
    module = _load()
    source = SCRIPT.read_text()
    assert module.CONTINUATION_SECONDS == 86400
    assert module.CPU_LIST == "0,2-27"
    assert module.THREADS == 27
    assert module.MEMORY_MB == 64000
    assert module.PROTOCOL_SHA256 == (
        "227c22a527e567bc4de873ab743fe9f493779eccbb1a698d2913c87695ebf87a"
    )
    assert '"continuation_index": 1' in source
    assert '"production_accepted": False' in source
    assert "xtb" not in source.lower()
    assert "gfn" not in source.lower()


def test_manifest_excludes_runtime_scratch(tmp_path: Path) -> None:
    module = _load()
    root = tmp_path.resolve()
    (root / "durable").mkdir()
    (root / "durable" / "result.json").write_text(json.dumps({"ok": True}))
    (root / "runtime_tmp").mkdir()
    (root / "runtime_tmp" / "checkpoint").write_bytes(b"ephemeral")
    manifest = module.build_file_manifest(root)
    assert [item["path"] for item in manifest["files"]] == ["durable/result.json"]
