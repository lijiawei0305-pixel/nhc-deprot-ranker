"""Typed legacy configuration tests."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from nhc_deprot_ranker.config import (
    LegacyConfig,
    load_acquisition_config,
    load_baseline_model_config,
    load_data_config,
    load_dft_plan_config,
    load_evaluation_config,
    load_families_config,
    load_geometry_smoke_config,
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


def test_phase6_dft_plan_config_loads() -> None:
    config = load_dft_plan_config(Path("configs/dft_plan.yaml"))
    assert config.expected_candidates == 50
    assert len(config.batches) == 5
    assert all(batch.counts.total() == 10 for batch in config.batches)
    assert config.geometry_generated is False
    assert config.execution_ready is False
    assert config.legacy_interface.compatibility_blockers == (
        "blocked_no_xyz",
        "blocked_runner_extra_steps",
    )


def test_phase6_rejects_a_rebalanced_batch_matrix(tmp_path: Path) -> None:
    raw = yaml.safe_load(Path("configs/dft_plan.yaml").read_text(encoding="utf-8"))
    raw["batches"][0]["counts"]["predicted_top_region"] = 2
    raw["batches"][0]["counts"]["chemical_family_diversity"] = 3
    raw["batches"][1]["counts"]["predicted_top_region"] = 4
    raw["batches"][1]["counts"]["chemical_family_diversity"] = 1
    path = tmp_path / "dft_plan.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValidationError, match="allocation matrix changed"):
        load_dft_plan_config(path)


def test_phase7_geometry_smoke_config_locks_exact_request() -> None:
    config = load_geometry_smoke_config(Path("configs/geometry_smoke.yaml"))
    assert config.expected_smoke_count == 4
    assert config.canonical_input.bytes == 542
    assert config.canonical_input.sha256 == (
        "f486f93a2d58fb144c05a7340fd432334eeec46385c9319aca34d2e1b5c4cc87"
    )
    assert config.m2.seed == 42
    assert config.m2.num_conformers == 10
    assert config.m2.parallel == 1
    assert config.quantum_chemistry_run is False


def test_phase7_geometry_smoke_config_rejects_scope_expansion(tmp_path: Path) -> None:
    raw = yaml.safe_load(Path("configs/geometry_smoke.yaml").read_text(encoding="utf-8"))
    raw["expected_smoke_count"] = 5
    raw["m2"]["parallel"] = 2
    path = tmp_path / "geometry_smoke.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_geometry_smoke_config(path)


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
