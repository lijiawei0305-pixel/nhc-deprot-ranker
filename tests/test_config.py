"""Typed legacy configuration tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from nhc_deprot_ranker.config import (
    LegacyConfig,
    load_acquisition_config,
    load_baseline_model_config,
    load_data_config,
    load_evaluation_config,
    load_families_config,
    load_hierarchical_model_config,
    load_legacy_config,
)
from nhc_deprot_ranker.legacy.audit import build_source_plan


def test_example_config_loads() -> None:
    config = load_legacy_config(Path("configs/legacy.example.yaml"))
    plan = build_source_plan(config)
    assert plan["read_only"] is True
    assert plan["remote_execution_performed"] is False
    assert plan["candidates"]["xtb_crude_csv"].startswith("/path/to/nhc-predictor")


def test_phase1_configs_load() -> None:
    data = load_data_config(Path("configs/data.yaml"))
    families = load_families_config(Path("configs/families.yaml"))
    assert data.dataset_version == "v001"
    assert data.lower_is_better is True
    assert data.label_defaults.hessian_computed is False
    assert families.axis_a.canonicalization == "sorted_pair"
    assert families.exact_combined_family.enabled is False


def test_phase2_configs_load() -> None:
    baselines = load_baseline_model_config(Path("configs/baselines.yaml"))
    evaluation = load_evaluation_config(Path("configs/evaluation.yaml"))
    assert baselines.model_name == "baseline_suite"
    assert baselines.historical_reference.enforce is True
    assert baselines.bootstrap.final_repeats == 2000
    assert evaluation.ranking.lower_is_better is True
    assert evaluation.blind_holdout.status == "missing"
    assert evaluation.bootstrap_ci.seed == 20260722
    assert evaluation.promotion.family_collapse.catastrophic_requires_both is True
    assert evaluation.promotion.family_offset_stability.minimum_support == 3


def test_phase3_config_loads() -> None:
    model = load_hierarchical_model_config(Path("configs/model.yaml"))
    assert model.model_name == "hierarchical_linear"
    assert model.expected_label_rows == 71
    assert model.skeleton_policy == "inactive_if_single_level"
    assert model.bootstrap.regularization_policy == "fixed_from_nested_cv"


def test_phase5_config_loads_and_has_exact_quotas() -> None:
    config = load_acquisition_config(Path("configs/acquisition.yaml"))
    assert config.acquisition_batch_size == 50
    assert config.score_top_n == 100
    assert config.probability_top_k == [10, 50, 100]
    assert sum(config.quotas.model_dump().values()) == pytest.approx(1.0)
    assert config.submit_hpc is False


def test_writable_legacy_access_is_rejected() -> None:
    with pytest.raises(ValidationError, match="read_only"):
        LegacyConfig.model_validate(
            {
                "legacy_repo": {
                    "root": "/tmp/legacy",
                    "expected_remote": "https://example.invalid/repo",
                },
                "source_access": {"mode": "local", "read_only": False},
                "candidates": {
                    name: {"location": "legacy_repo", "path": f"{name}.csv"}
                    for name in (
                        "xtb_crude_csv",
                        "xtb_reduced_csv",
                        "v3_graph_csv",
                        "v4_new_only_csv",
                        "descriptors_parquet",
                    )
                },
                "labels": {"sources": []},
            }
        )
