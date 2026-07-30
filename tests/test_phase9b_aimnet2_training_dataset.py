from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/phase9b_aimnet2_training_dataset.py"


def _load():
    spec = importlib.util.spec_from_file_location("phase9b_training_dataset_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dataset = _load()


def test_unit_projection_matches_aimnet_native_units() -> None:
    assert pytest.approx(27.211386245988) == dataset.HARTREE_TO_EV
    assert pytest.approx(0.529177210903) == dataset.BOHR_TO_ANGSTROM
    assert pytest.approx(51.422067476325886) == (dataset.FORCE_HARTREE_PER_BOHR_TO_EV_PER_ANGSTROM)


def test_npz_projection_has_exact_aimnet_keys_and_shapes() -> None:
    records = [
        {
            "coord": np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
            "numbers": np.asarray([6, 7]),
            "charge": 1,
            "energy": -10.0,
            "forces": np.asarray([[0.1, 0.0, 0.0], [-0.1, 0.0, 0.0]]),
            "candidate": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
            "endpoint": "cation",
            "frame_index": 0,
        }
    ]
    raw = dataset._npz(records)
    archive = np.load(__import__("io").BytesIO(raw))
    assert set(archive.files) == {
        "coord",
        "numbers",
        "charge",
        "energy",
        "forces",
        "candidate",
        "endpoint",
        "frame_index",
    }
    assert archive["coord"].shape == (1, 2, 3)
    assert archive["forces"].shape == (1, 2, 3)
    assert archive["charge"].shape == (1,)
    assert archive["energy"].shape == (1,)
    assert archive["coord"].dtype == np.float32
    assert archive["numbers"].dtype == np.int64
    assert archive["charge"].dtype == np.float32
    assert archive["energy"].dtype == np.float64
    assert archive["forces"].dtype == np.float32


def test_split_loader_rejects_molecule_overlap(tmp_path: Path) -> None:
    profile = {
        "candidate": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
        "electron_count": 10,
        "cation_atom_count": 2,
        "neutral_atom_count": 1,
        "cation_sha256": "a" * 64,
        "neutral_sha256": "b" * 64,
    }
    payload = {
        "schema": dataset.SPLIT_SCHEMA,
        "train": [profile],
        "validation": [profile],
        "final_test": [{**profile, "candidate": "CCCCCCCCCCCCCC-DDDDDDDDDD-E"}],
    }
    path = tmp_path / "split.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(dataset.DatasetAssemblyError, match="duplicate"):
        dataset.load_split(path)


def test_frame_loader_rejects_force_gradient_sign_drift(tmp_path: Path) -> None:
    body = {
        "schema": dataset.FRAME_SCHEMA,
        "candidate": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
        "endpoint": "cation",
        "frame_index": 0,
        "parent_protocol_sha256": dataset.PARENT_PROTOCOL_SHA256,
        "atom_count": 2,
        "elements": ["C", "N"],
        "coordinates_bohr": [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
        "energy_hartree": -10.0,
        "gradient_hartree_per_bohr": [[0.1, 0.0, 0.0], [-0.1, 0.0, 0.0]],
        "forces_hartree_per_bohr": [[0.1, 0.0, 0.0], [-0.1, 0.0, 0.0]],
        "charge": 1,
        "scf_converged": True,
    }
    body["canonical_sha256"] = dataset.sha256_bytes(dataset.canonical_json(body))
    path = tmp_path / "frame.json"
    raw = dataset.canonical_json(body)
    path.write_bytes(raw)
    with pytest.raises(dataset.DatasetAssemblyError, match="negative gradient"):
        dataset._load_frame(
            path,
            expected_sha256=dataset.sha256_bytes(raw),
            expected_candidate=body["candidate"],
            expected_endpoint="cation",
            expected_index=0,
        )
