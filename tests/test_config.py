"""Typed legacy configuration tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from nhc_deprot_ranker.config import LegacyConfig, load_legacy_config
from nhc_deprot_ranker.legacy.audit import build_source_plan


def test_example_config_loads() -> None:
    config = load_legacy_config(Path("configs/legacy.example.yaml"))
    plan = build_source_plan(config)
    assert plan["read_only"] is True
    assert plan["remote_execution_performed"] is False
    assert plan["candidates"]["xtb_crude_csv"].startswith("/path/to/nhc-predictor")


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
