"""End-to-end synthetic tests for the immutable Phase 4 decision result."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from nhc_deprot_ranker.data.provenance import sha256_file
from nhc_deprot_ranker.models.base import key_set_sha256
from nhc_deprot_ranker.validation.evaluate import (
    DecisionEvaluationError,
    evaluate_decision,
)


@dataclass(frozen=True)
class Phase4Fixture:
    dataset: Path
    baselines: Path
    hierarchical: Path
    dataset_evidence: Path
    baseline_evidence: Path
    hierarchical_evidence: Path
    evaluation_config: Path
    output: Path


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _hashes(root: Path, names: list[str]) -> dict[str, str]:
    return {name: sha256_file(root / name) for name in names}


def _make_fixture(tmp_path: Path) -> Phase4Fixture:
    dataset = tmp_path / "data/vtest"
    baselines = tmp_path / "results/baselines_vtest"
    hierarchical = tmp_path / "results/hierarchical_vtest"
    dataset.mkdir(parents=True)
    baselines.mkdir(parents=True)
    hierarchical.mkdir(parents=True)
    keys = [f"KEY-{index:03d}" for index in range(71)]
    training_hash = key_set_sha256(keys)
    (dataset / "labels.txt").write_text("synthetic frozen labels\n", encoding="utf-8")
    dataset_evidence = tmp_path / "dataset_evidence.json"
    _write_json(
        dataset_evidence,
        {"dataset_version": "vtest", "output_sha256": _hashes(dataset, ["labels.txt"])},
    )

    truth = np.linspace(200.0, 270.0, 71)
    b0 = np.linspace(30.0, 100.0, 71)
    b1 = truth + 0.5 * np.sin(np.arange(71))
    h1 = truth + 0.2 * np.cos(np.arange(71))
    baseline_rows: list[dict[str, object]] = []
    hierarchical_rows: list[dict[str, object]] = []
    for protocol in ("loocv", "leave_axis_a_out", "leave_axis_b_out"):
        for index, key in enumerate(keys):
            held_out = None if protocol == "loocv" else f"G-{index % 10}"
            fold_id = f"{protocol}::{held_out or key}"
            common = {
                "protocol": protocol,
                "fold_id": fold_id,
                "held_out_group": held_out,
                "inchikey": key,
                "true_dft_kcal": truth[index],
                "b0_prediction_kcal": b0[index],
                "b1_prediction_kcal": b1[index],
            }
            baseline_rows.append(common)
            hierarchical_rows.append(
                {
                    **common,
                    "h1_prediction_kcal": h1[index],
                    "axis_a_effect": 0.0,
                    "axis_b_effect": 0.0,
                    "axis_a_family_known": protocol != "leave_axis_a_out",
                    "axis_b_family_known": protocol != "leave_axis_b_out",
                }
            )
    pd.DataFrame.from_records(baseline_rows).to_csv(baselines / "oof_predictions.csv", index=False)
    pd.DataFrame.from_records(hierarchical_rows).to_csv(
        hierarchical / "oof_predictions.csv", index=False
    )
    _write_json(
        baselines / "model_manifest.json",
        {"dataset_version": "vtest", "training_key_sha256": training_hash},
    )
    _write_json(baselines / "phase2_gate.json", {"status": "passed"})
    _write_json(baselines / "_SUCCESS", {"status": "passed"})
    baseline_evidence = tmp_path / "baseline_evidence.json"
    baseline_names = ["oof_predictions.csv", "model_manifest.json", "phase2_gate.json", "_SUCCESS"]
    _write_json(
        baseline_evidence,
        {
            "dataset_version": "vtest",
            "model": {"training_key_sha256": training_hash},
            "output_sha256": _hashes(baselines, baseline_names),
        },
    )

    source_hash = "synthetic-source-tree"
    _write_json(
        hierarchical / "model_manifest.json",
        {
            "dataset_version": "vtest",
            "training_key_sha256": training_hash,
            "source_tree_sha256": source_hash,
        },
    )
    _write_json(hierarchical / "phase3_gate.json", {"status": "passed"})
    _write_json(hierarchical / "_SUCCESS", {"status": "passed"})
    effects = pd.DataFrame.from_records(
        [
            {
                "term": "axis_a_family",
                "level": "A",
                "support": 35,
                "sign_stability": 0.8,
                "present_fraction": 1.0,
            },
            {
                "term": "axis_b_family",
                "level": "B",
                "support": 36,
                "sign_stability": 0.8,
                "present_fraction": 1.0,
            },
        ]
    )
    effects.to_parquet(hierarchical / "bootstrap_family_effects.parquet", index=False)
    pd.DataFrame.from_records(
        [
            {"term": "axis_a_family", "level": "A", "effect_kcal": 0.1},
            {"term": "axis_b_family", "level": "B", "effect_kcal": -0.1},
        ]
    ).to_csv(hierarchical / "family_effects.csv", index=False)
    hierarchical_evidence = tmp_path / "hierarchical_evidence.json"
    hierarchical_names = [
        "oof_predictions.csv",
        "model_manifest.json",
        "phase3_gate.json",
        "_SUCCESS",
        "bootstrap_family_effects.parquet",
        "family_effects.csv",
    ]
    _write_json(
        hierarchical_evidence,
        {
            "dataset_version": "vtest",
            "model": {"training_key_sha256": training_hash},
            "source_tree_sha256": source_hash,
            "output_sha256": _hashes(hierarchical, hierarchical_names),
        },
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
                    "true_top_m": [5, 10],
                    "predicted_budget_k": [10, 20, 50],
                    "ndcg_k": [10, 20, 50],
                    "pairwise_tie_threshold_kcal": 0.1,
                },
                "bootstrap_ci": {"repeats": 10, "confidence": 0.95, "seed": 17},
                "promotion": {
                    "min_spearman_delta": -0.01,
                    "min_kendall_delta": -0.02,
                    "max_regret_increase_kcal": 1.0,
                    "require_no_family_collapse": True,
                    "primary_rank": {
                        "min_delta": 0.0,
                        "require_95_percent_lower_bound_nonnegative": True,
                    },
                    "family_collapse": {
                        "max_heldout_mae_increase_kcal": 3.0,
                        "max_heldout_mae_ratio": 2.0,
                        "catastrophic_requires_both": True,
                    },
                    "family_offset_stability": {
                        "minimum_support": 3,
                        "min_conditional_sign_stability": 0.6,
                    },
                    "head_recall": {
                        "min_delta": 0.0,
                        "require_95_percent_lower_bound_nonnegative": True,
                    },
                },
                "blind_holdout": {"status": "missing", "reason": "synthetic"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return Phase4Fixture(
        dataset=dataset,
        baselines=baselines,
        hierarchical=hierarchical,
        dataset_evidence=dataset_evidence,
        baseline_evidence=baseline_evidence,
        hierarchical_evidence=hierarchical_evidence,
        evaluation_config=evaluation_config,
        output=tmp_path / "results/decision_vtest",
    )


def _evaluate(fixture: Phase4Fixture, *, dry_run: bool = False) -> dict[str, object]:
    return evaluate_decision(
        dataset_dir=fixture.dataset,
        baseline_results_dir=fixture.baselines,
        hierarchical_results_dir=fixture.hierarchical,
        evaluation_config_path=fixture.evaluation_config,
        dataset_evidence_path=fixture.dataset_evidence,
        baseline_evidence_path=fixture.baseline_evidence,
        hierarchical_evidence_path=fixture.hierarchical_evidence,
        output_dir=fixture.output,
        seed=17,
        dry_run=dry_run,
    ).payload


def test_phase4_end_to_end_outputs_and_immutability(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    result = _evaluate(fixture)
    assert result["status"] == "complete"
    assert result["full_pool_scoring"] is False
    assert len(list((fixture.output / "figures").glob("*.png"))) == 4
    gate = json.loads((fixture.output / "phase4_gate.json").read_text())
    assert gate["status"] == "passed"
    manifest = json.loads((fixture.output / "decision_manifest.json").read_text())
    for name, expected in manifest["output_sha256"].items():
        assert sha256_file(fixture.output / name) == expected
    with pytest.raises(DecisionEvaluationError, match="already exists"):
        _evaluate(fixture)


def test_phase4_dry_run_is_nonwriting_and_hash_mismatch_rejects(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    plan = _evaluate(fixture, dry_run=True)
    assert plan["models_refit"] is False
    assert plan["phase5_authorized"] is False
    assert not fixture.output.exists()
    with (fixture.baselines / "oof_predictions.csv").open("a", encoding="utf-8") as stream:
        stream.write("tampered\n")
    with pytest.raises(DecisionEvaluationError, match="input hash mismatch"):
        _evaluate(fixture)
    assert not fixture.output.exists()
