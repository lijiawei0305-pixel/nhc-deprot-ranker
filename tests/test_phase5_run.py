"""Small end-to-end Phase 5 scoring and local acquisition test."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml

from nhc_deprot_ranker.acquisition.scoring import FullScoringError, score_full_pool
from nhc_deprot_ranker.acquisition.selection import acquire_candidates
from nhc_deprot_ranker.data.provenance import sha256_file


def _candidates(n: int = 120) -> pd.DataFrame:
    rank = np.arange(1, n + 1)
    return pd.DataFrame(
        {
            "inchikey": [f"KEY-{index:04d}" for index in range(n)],
            "smiles_cation": [f"C[N+]({index % 5})(C)C" for index in range(n)],
            "smiles_neutral": [f"CN({index % 5})C" for index in range(n)],
            "xtb_deprot_kcal": np.linspace(50.0, 120.0, n),
            "xtb_rank": rank,
            "xtb_percentile": (rank - 1) / (n - 1),
            "n1_frag": [f"N{index % 7}" for index in range(n)],
            "n3_frag": [f"N{(index + 1) % 7}" for index in range(n)],
            "c4_frag": [f"C{index % 6}" for index in range(n)],
            "c5_frag": [f"C{(index + 2) % 6}" for index in range(n)],
            "skeleton": ["imidazolium"] * n,
            "axis_a_family": [f"A{index % 20}" for index in range(n)],
            "axis_b_family": [f"B{index % 18}" for index in range(n)],
            "combined_family": [f"F{index % 60}" for index in range(n)],
            "n_heavy_atoms": pd.Series([pd.NA] * n, dtype="Int64"),
            "n_electrons": pd.Series([pd.NA] * n, dtype="Int64"),
        }
    )


def _bootstrap() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "repeat": np.arange(20),
            "beta_0": np.linspace(190.0, 200.0, 20),
            "rho": np.linspace(0.65, 0.78, 20),
        }
    )


def _coefficients() -> dict[str, Any]:
    return {
        "B0": {"x_min": 55.0, "x_max": 115.0},
        "B1": {"beta_0": 196.0, "rho": 0.72, "x_min": 55.0, "x_max": 115.0},
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _hashes(root: Path, names: list[str]) -> dict[str, str]:
    return {name: sha256_file(root / name) for name in names}


def _build_inputs(tmp_path: Path) -> dict[str, Path]:
    dataset = tmp_path / "vtest"
    baselines = tmp_path / "baselines_vtest"
    decision = tmp_path / "decision_vtest"
    dataset.mkdir()
    baselines.mkdir()
    decision.mkdir()

    candidates = _candidates()
    labels = pd.DataFrame({"inchikey": candidates["inchikey"].iloc[10:16].tolist()})
    candidates.to_parquet(dataset / "candidates.parquet", index=False)
    labels.to_parquet(dataset / "labels.parquet", index=False)
    _write_json(
        dataset / "protocol_manifest.json",
        {
            "protocol": {
                "method": "DLPNO-CCSD(T)",
                "basis": "def2-TZVPP",
                "target_definition": "electronic_deprotonation_energy",
            }
        },
    )
    dataset_evidence = tmp_path / "dataset_evidence.json"
    _write_json(
        dataset_evidence,
        {
            "dataset_version": "vtest",
            "rows": {"candidates": len(candidates), "labels": len(labels)},
            "output_sha256": _hashes(
                dataset,
                ["candidates.parquet", "labels.parquet", "protocol_manifest.json"],
            ),
        },
    )

    _write_json(baselines / "coefficients.json", _coefficients())
    _bootstrap().to_parquet(baselines / "bootstrap_summary.parquet", index=False)
    (baselines / "model.pkl").write_bytes(b"frozen-test-model")
    baseline_evidence = tmp_path / "baseline_evidence.json"
    _write_json(
        baseline_evidence,
        {
            "dataset_version": "vtest",
            "output_sha256": _hashes(
                baselines,
                ["coefficients.json", "bootstrap_summary.parquet", "model.pkl"],
            ),
        },
    )

    _write_json(
        decision / "promotion_decision.json",
        {"outcome": "raw_xTB_wins", "production_default": "B0_raw_xTB"},
    )
    _write_json(decision / "decision_manifest.json", {"decision_version": "vtest"})
    decision_evidence = tmp_path / "decision_evidence.json"
    _write_json(
        decision_evidence,
        {
            "dataset_version": "vtest",
            "decision_manifest_sha256": sha256_file(decision / "decision_manifest.json"),
            "training_key_sha256": "c" * 64,
            "output_sha256": _hashes(
                decision, ["promotion_decision.json", "decision_manifest.json"]
            ),
        },
    )

    config_raw = yaml.safe_load(Path("configs/acquisition.yaml").read_text(encoding="utf-8"))
    config_raw["version"] = "vtest"
    config_raw["dataset_version"] = "vtest"
    config = tmp_path / "acquisition.yaml"
    config.write_text(yaml.safe_dump(config_raw, sort_keys=False), encoding="utf-8")
    return {
        "dataset": dataset,
        "baselines": baselines,
        "decision": decision,
        "dataset_evidence": dataset_evidence,
        "baseline_evidence": baseline_evidence,
        "decision_evidence": decision_evidence,
        "config": config,
    }


def test_phase5_end_to_end_outputs_are_complete_and_immutable(tmp_path: Path) -> None:
    inputs = _build_inputs(tmp_path)
    scoring = tmp_path / "scoring_vtest"
    acquisition = tmp_path / "acquisition_vtest"
    result = score_full_pool(
        dataset_dir=inputs["dataset"],
        baseline_results_dir=inputs["baselines"],
        decision_results_dir=inputs["decision"],
        acquisition_config_path=inputs["config"],
        dataset_evidence_path=inputs["dataset_evidence"],
        baseline_evidence_path=inputs["baseline_evidence"],
        decision_evidence_path=inputs["decision_evidence"],
        output_dir=scoring,
        seed=20260722,
    )
    assert result.payload["rows"] == 120
    assert len(pd.read_csv(scoring / "top_candidates.csv")) == 100
    assert len(pd.read_parquet(scoring / "full_ranked_candidates.parquet")) == 120
    assert len(list((scoring / "figures").glob("*.png"))) == 4
    assert json.loads((scoring / "_SUCCESS").read_text())["status"] == "passed"

    selection = acquire_candidates(
        dataset_dir=inputs["dataset"],
        scored_results_dir=scoring,
        acquisition_config_path=inputs["config"],
        dataset_evidence_path=inputs["dataset_evidence"],
        output_dir=acquisition,
        seed=20260722,
    )
    assert selection.payload["selected"] == 50
    assert selection.payload["quotas"] == {
        "predicted_top_region": 15,
        "cutoff_region": 13,
        "chemical_family_diversity": 12,
        "uncertain_ood_conflict": 10,
    }
    batch = pd.read_csv(acquisition / "acquisition_candidates.csv")
    assert len(batch) == batch["inchikey"].nunique() == 50
    assert len(list((acquisition / "figures").glob("*.png"))) == 4
    local_manifest = json.loads((acquisition / "high_fidelity_batch_manifest.json").read_text())
    assert local_manifest["submit_hpc"] is False
    assert local_manifest["server_write_authorized"] is False

    with pytest.raises(FullScoringError, match="already exists"):
        score_full_pool(
            dataset_dir=inputs["dataset"],
            baseline_results_dir=inputs["baselines"],
            decision_results_dir=inputs["decision"],
            acquisition_config_path=inputs["config"],
            dataset_evidence_path=inputs["dataset_evidence"],
            baseline_evidence_path=inputs["baseline_evidence"],
            decision_evidence_path=inputs["decision_evidence"],
            output_dir=scoring,
            seed=20260722,
        )
