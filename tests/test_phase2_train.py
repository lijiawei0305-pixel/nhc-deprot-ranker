"""End-to-end synthetic tests for immutable Phase 2 baseline results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import pandas as pd
import pytest
import yaml

from nhc_deprot_ranker.data.provenance import sha256_file
from nhc_deprot_ranker.models.registry import BaselineModelBundle
from nhc_deprot_ranker.models.train import BaselineTrainingError, train_baselines


@dataclass(frozen=True)
class Phase2Fixture:
    dataset: Path
    model_config: Path
    evaluation_config: Path
    evidence: Path
    output: Path


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _make_fixture(tmp_path: Path) -> Phase2Fixture:
    dataset = tmp_path / "data/vtest"
    dataset.mkdir(parents=True)
    keys = [f"KEY-{index:02d}" for index in range(8)]
    x = [42.0, 49.0, 56.0, 65.0, 73.0, 84.0, 96.0, 111.0]
    noise = [0.2, -0.3, 0.1, 0.5, -0.4, 0.25, -0.15, 0.35]
    candidates = pd.DataFrame(
        {
            "inchikey": keys,
            "xtb_deprot_kcal": x,
            "axis_a_family": ["A1", "A1", "A2", "A2", "A3", "A3", "A4", "A4"],
            "axis_b_family": ["B1", "B2", "B1", "B2", "B3", "B4", "B3", "B4"],
            "combined_family": [f"C{index}" for index in range(8)],
        }
    )
    labels = pd.DataFrame(
        {
            "inchikey": keys,
            "dft_deprot_electronic_kcal": [
                10.0 + 0.73 * value + delta for value, delta in zip(x, noise, strict=True)
            ],
            "source_group": ["gold"] * 3 + ["blind_round1"] * 2 + ["blind_round2"] * 3,
        }
    )
    candidates.to_parquet(dataset / "candidates.parquet", index=False)
    labels.to_parquet(dataset / "labels.parquet", index=False)
    pd.DataFrame({"inchikey": keys, "source_group": labels["source_group"]}).to_csv(
        dataset / "label_source_membership.csv", index=False
    )
    _write_json(dataset / "source_manifest.json", {"dataset_version": "vtest"})
    _write_json(dataset / "protocol_manifest.json", {"dataset_version": "vtest"})
    _write_json(dataset / "data_quality.json", {"dataset_version": "vtest"})
    _write_json(dataset / "_SUCCESS", {"dataset_version": "vtest", "rows": {"labels": 8}})
    artifact_names = [
        "candidates.parquet",
        "labels.parquet",
        "label_source_membership.csv",
        "source_manifest.json",
        "protocol_manifest.json",
        "data_quality.json",
    ]
    evidence = tmp_path / "evidence.json"
    _write_json(
        evidence,
        {
            "dataset_version": "vtest",
            "rows": {"candidates": 8, "labels": 8, "label_source_memberships": 8},
            "output_sha256": {name: sha256_file(dataset / name) for name in artifact_names},
        },
    )
    model_config = tmp_path / "baselines.yaml"
    model_config.write_text(
        yaml.safe_dump(
            {
                "model_name": "baseline_suite",
                "model_version": "vtest",
                "dataset_version": "vtest",
                "target_column": "dft_deprot_electronic_kcal",
                "baseline_column": "xtb_deprot_kcal",
                "lower_is_better": True,
                "affine": {"min_samples": 3, "condition_number_threshold": 1e12},
                "bootstrap": {
                    "development_repeats": 10,
                    "final_repeats": 20,
                    "confidence": 0.95,
                    "seed": 11,
                },
                "historical_reference": {
                    "enforce": False,
                    "intercept": 0.0,
                    "slope": 0.0,
                    "loocv_mae": 0.0,
                    "loocv_rmse": 0.0,
                    "loocv_spearman": 0.0,
                    "loocv_kendall": 0.0,
                    "raw_spearman": 0.0,
                    "raw_kendall": 0.0,
                    "intercept_absolute_tolerance": 0.0,
                    "slope_absolute_tolerance": 0.0,
                    "metric_absolute_tolerance": 0.0,
                },
            },
            sort_keys=False,
        )
    )
    evaluation_config = tmp_path / "evaluation.yaml"
    evaluation_config.write_text(
        yaml.safe_dump(
            {
                "protocols": [
                    "loocv",
                    "leave_axis_a_out",
                    "leave_axis_b_out",
                    "combined_family_holdout_if_supported",
                    "size_extrapolation",
                ],
                "ranking": {
                    "lower_is_better": True,
                    "true_top_m": [2],
                    "predicted_budget_k": [2, 4],
                    "ndcg_k": [2, 4],
                    "pairwise_tie_threshold_kcal": 0.1,
                },
                "bootstrap_ci": {"repeats": 20, "confidence": 0.95},
                "promotion": {
                    "min_spearman_delta": -0.01,
                    "min_kendall_delta": -0.02,
                    "max_regret_increase_kcal": 1.0,
                    "require_no_family_collapse": True,
                },
                "blind_holdout": {
                    "status": "missing",
                    "reason": "synthetic fixture has no blind holdout",
                },
            },
            sort_keys=False,
        )
    )
    return Phase2Fixture(
        dataset=dataset,
        model_config=model_config,
        evaluation_config=evaluation_config,
        evidence=evidence,
        output=tmp_path / "results/baselines_vtest",
    )


def _train(fixture: Phase2Fixture, *, dry_run: bool = False) -> dict[str, object]:
    return train_baselines(
        dataset_dir=fixture.dataset,
        model_config_path=fixture.model_config,
        evaluation_config_path=fixture.evaluation_config,
        evidence_path=fixture.evidence,
        output_dir=fixture.output,
        seed=11,
        dry_run=dry_run,
    ).payload


def test_phase2_end_to_end_outputs_and_oof_contract(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    result = _train(fixture)
    assert result["phase2_gate"] == "passed"
    gate = json.loads((fixture.output / "phase2_gate.json").read_text())
    assert gate["status"] == "passed"
    predictions = pd.read_csv(fixture.output / "oof_predictions.csv")
    assert len(predictions) == 24
    assert predictions.groupby("protocol")["inchikey"].nunique().to_dict() == {
        "leave_axis_a_out": 8,
        "leave_axis_b_out": 8,
        "loocv": 8,
    }
    rank_audit = pd.read_csv(fixture.output / "rank_shift_audit.csv")
    assert len(rank_audit) == 8
    assert rank_audit["true_rank"].tolist() == sorted(rank_audit["true_rank"])
    assert len(list((fixture.output / "figures").glob("*.png"))) == 9
    bundle = joblib.load(fixture.output / "model.pkl")
    assert isinstance(bundle, BaselineModelBundle)
    manifest = json.loads((fixture.output / "model_manifest.json").read_text())
    for name, expected in manifest["output_sha256"].items():
        assert sha256_file(fixture.output / name) == expected


def test_phase2_dry_run_is_nonwriting(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    result = _train(fixture, dry_run=True)
    assert result["dry_run"] is True
    assert result["size_extrapolation"] == "unavailable_missing_validated_size"
    assert not fixture.output.exists()


def test_phase2_existing_result_is_immutable(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    _train(fixture)
    success_hash = sha256_file(fixture.output / "_SUCCESS")
    with pytest.raises(BaselineTrainingError, match="already exists"):
        _train(fixture)
    assert sha256_file(fixture.output / "_SUCCESS") == success_hash


def test_phase2_rejects_input_hash_mismatch(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    evidence = json.loads(fixture.evidence.read_text())
    evidence["output_sha256"]["labels.parquet"] = "0" * 64
    _write_json(fixture.evidence, evidence)
    with pytest.raises(BaselineTrainingError, match="hash mismatch"):
        _train(fixture)
    assert not fixture.output.exists()


def test_phase2_failure_cleans_atomic_temporary_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _make_fixture(tmp_path)

    def fail_figure_generation(**_: object) -> tuple[Path, ...]:
        raise RuntimeError("synthetic figure failure")

    monkeypatch.setattr(
        "nhc_deprot_ranker.models.train.generate_baseline_figures",
        fail_figure_generation,
    )
    with pytest.raises(RuntimeError, match="synthetic figure failure"):
        _train(fixture)
    assert not fixture.output.exists()
    assert not list(fixture.output.parent.glob(".baselines_vtest.tmp.*"))
