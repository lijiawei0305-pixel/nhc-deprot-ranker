"""Synthetic end-to-end tests for immutable Phase 3 H1 results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from nhc_deprot_ranker.config import BaselineModelConfig
from nhc_deprot_ranker.data.provenance import sha256_file
from nhc_deprot_ranker.models.base import key_set_sha256
from nhc_deprot_ranker.models.train import _evaluate_folds
from nhc_deprot_ranker.models.train_hierarchical import (
    HierarchicalTrainingError,
    train_hierarchical,
)
from nhc_deprot_ranker.validation.splits import leave_one_group_out_folds, loocv_folds


@dataclass(frozen=True)
class Phase3Fixture:
    dataset: Path
    baselines: Path
    dataset_evidence: Path
    baseline_evidence: Path
    model_config: Path
    evaluation_config: Path
    output: Path


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _baseline_config() -> BaselineModelConfig:
    return BaselineModelConfig.model_validate(
        {
            "model_name": "baseline_suite",
            "model_version": "vtest",
            "dataset_version": "vtest",
            "target_column": "dft_deprot_electronic_kcal",
            "baseline_column": "xtb_deprot_kcal",
            "lower_is_better": True,
            "affine": {"min_samples": 3, "condition_number_threshold": 1e12},
            "bootstrap": {
                "development_repeats": 5,
                "final_repeats": 10,
                "confidence": 0.95,
                "seed": 5,
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
        }
    )


def _make_fixture(tmp_path: Path) -> Phase3Fixture:
    dataset = tmp_path / "data/vtest"
    baselines = tmp_path / "results/baselines_vtest"
    dataset.mkdir(parents=True)
    baselines.mkdir(parents=True)
    keys = [f"KEY-{index:02d}" for index in range(12)]
    x = np.linspace(50.0, 105.0, 12)
    axis_a = ["A1"] * 3 + ["A2"] * 3 + ["A3"] * 3 + ["A4"] * 3
    axis_b = ["B1", "B2", "B3"] * 4
    a_effect = {"A1": -2.5, "A2": 2.0, "A3": 1.0, "A4": -0.5}
    b_effect = {"B1": -1.0, "B2": 0.25, "B3": 0.75}
    noise = np.asarray([0.1, -0.2, 0.3, -0.1, 0.15, -0.25, 0.2, -0.15, 0.05, 0.1, -0.05, 0.0])
    y = np.asarray(
        [
            190.0 + 0.72 * value + a_effect[a] + b_effect[b] + delta
            for value, a, b, delta in zip(x, axis_a, axis_b, noise, strict=True)
        ]
    )
    candidates = pd.DataFrame(
        {
            "inchikey": keys,
            "xtb_deprot_kcal": x,
            "skeleton": ["imidazolium"] * 12,
            "axis_a_family": axis_a,
            "axis_b_family": axis_b,
            "combined_family": [f"C-{index}" for index in range(12)],
        }
    )
    labels = pd.DataFrame(
        {
            "inchikey": keys,
            "dft_deprot_electronic_kcal": y,
            "source_group": ["gold"] * 12,
            "label_protocol_id": ["f" * 64] * 12,
        }
    )
    candidates.to_parquet(dataset / "candidates.parquet", index=False)
    labels.to_parquet(dataset / "labels.parquet", index=False)
    dataset_evidence = tmp_path / "dataset_evidence.json"
    _write_json(
        dataset_evidence,
        {
            "dataset_version": "vtest",
            "output_sha256": {
                name: sha256_file(dataset / name)
                for name in ("candidates.parquet", "labels.parquet")
            },
        },
    )

    baseline_config = _baseline_config()
    protocol_folds = {
        "loocv": loocv_folds(keys),
        "leave_axis_a_out": leave_one_group_out_folds(
            keys=keys, groups=axis_a, protocol="leave_axis_a_out"
        ),
        "leave_axis_b_out": leave_one_group_out_folds(
            keys=keys, groups=axis_b, protocol="leave_axis_b_out"
        ),
    }
    labeled = labels.merge(candidates, on="inchikey", validate="one_to_one").sort_values("inchikey")
    labeled = labeled.reset_index(drop=True)
    baseline_predictions = [
        _evaluate_folds(labeled=labeled, folds=folds, model_config=baseline_config)
        for folds in protocol_folds.values()
    ]
    pd.concat(baseline_predictions, ignore_index=True).to_csv(
        baselines / "oof_predictions.csv", index=False
    )
    _write_json(
        baselines / "split_manifest.json",
        {
            "dataset_version": "vtest",
            "protocols": {
                protocol: [fold.to_manifest(keys) for fold in folds]
                for protocol, folds in protocol_folds.items()
            },
        },
    )
    training_hash = key_set_sha256(keys)
    _write_json(
        baselines / "model_manifest.json",
        {"dataset_version": "vtest", "training_key_sha256": training_hash},
    )
    baseline_evidence = tmp_path / "baseline_evidence.json"
    baseline_names = ["oof_predictions.csv", "split_manifest.json", "model_manifest.json"]
    _write_json(
        baseline_evidence,
        {
            "dataset_version": "vtest",
            "model": {"training_key_sha256": training_hash},
            "output_sha256": {name: sha256_file(baselines / name) for name in baseline_names},
        },
    )

    model_config = tmp_path / "model.yaml"
    model_config.write_text(
        yaml.safe_dump(
            {
                "model_name": "hierarchical_linear",
                "model_version": "vtest",
                "dataset_version": "vtest",
                "baseline_result_version": "vtest",
                "expected_label_rows": 12,
                "target_column": "dft_deprot_electronic_kcal",
                "baseline_column": "xtb_deprot_kcal",
                "lower_is_better": True,
                "family_terms": ["skeleton", "axis_a_family", "axis_b_family"],
                "include_size": False,
                "size_column": "n_electrons",
                "slope": {"free": True, "prior_center": 1.0, "penalty": 0.0},
                "regularization": {
                    "shared_family_coarse_grid": [1.0, 10.0],
                    "axis_specific_refinement": True,
                    "lambda_skeleton_grid": [1.0],
                    "lambda_axis_a_grid": [1.0, 10.0],
                    "lambda_axis_b_grid": [1.0, 10.0],
                },
                "bootstrap": {
                    "development_repeats": 5,
                    "final_repeats": 10,
                    "seed": 5,
                    "regularization_policy": "fixed_from_nested_cv",
                },
                "unknown_family_policy": "zero_effect",
                "skeleton_policy": "inactive_if_single_level",
                "inner_cv": {"folds": 3, "seed": 5},
                "numerical": {"condition_number_threshold": 1e12},
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
                    "true_top_m": [2, 4],
                    "predicted_budget_k": [3, 6],
                    "ndcg_k": [3, 6],
                    "pairwise_tie_threshold_kcal": 0.1,
                },
                "bootstrap_ci": {"repeats": 10, "confidence": 0.95},
                "promotion": {
                    "min_spearman_delta": -0.01,
                    "min_kendall_delta": -0.02,
                    "max_regret_increase_kcal": 1.0,
                    "require_no_family_collapse": True,
                },
                "blind_holdout": {"status": "missing", "reason": "synthetic"},
            },
            sort_keys=False,
        )
    )
    return Phase3Fixture(
        dataset=dataset,
        baselines=baselines,
        dataset_evidence=dataset_evidence,
        baseline_evidence=baseline_evidence,
        model_config=model_config,
        evaluation_config=evaluation_config,
        output=tmp_path / "results/hierarchical_vtest",
    )


def _train(fixture: Phase3Fixture, *, dry_run: bool = False) -> dict[str, object]:
    return train_hierarchical(
        dataset_dir=fixture.dataset,
        baseline_results_dir=fixture.baselines,
        model_config_path=fixture.model_config,
        evaluation_config_path=fixture.evaluation_config,
        dataset_evidence_path=fixture.dataset_evidence,
        baseline_evidence_path=fixture.baseline_evidence,
        output_dir=fixture.output,
        seed=5,
        dry_run=dry_run,
    ).payload


def test_phase3_end_to_end_nested_outputs(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    result = _train(fixture)
    assert result["phase3_gate"] == "passed"
    gate = json.loads((fixture.output / "phase3_gate.json").read_text())
    assert gate["status"] == "passed"
    predictions = pd.read_csv(fixture.output / "oof_predictions.csv")
    assert len(predictions) == 36
    assert predictions.groupby("protocol")["inchikey"].nunique().eq(12).all()
    assert predictions.query("protocol == 'leave_axis_a_out'")["axis_a_effect"].eq(0.0).all()
    assert predictions.query("protocol == 'leave_axis_b_out'")["axis_b_effect"].eq(0.0).all()
    assert len(list((fixture.output / "figures").glob("*.png"))) == 9
    manifest = json.loads((fixture.output / "model_manifest.json").read_text())
    for name, expected in manifest["output_sha256"].items():
        assert sha256_file(fixture.output / name) == expected


def test_phase3_dry_run_and_immutability(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    plan = _train(fixture, dry_run=True)
    assert plan["dry_run"] is True
    assert plan["phase4_promotion"] is False
    assert not fixture.output.exists()
    _train(fixture)
    success_hash = sha256_file(fixture.output / "_SUCCESS")
    with pytest.raises(HierarchicalTrainingError, match="already exists"):
        _train(fixture)
    assert sha256_file(fixture.output / "_SUCCESS") == success_hash
