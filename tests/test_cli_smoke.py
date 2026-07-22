"""Phase 0 CLI smoke tests."""

from pathlib import Path
from typing import Any

import pytest

import nhc_deprot_ranker.cli as cli_module
from nhc_deprot_ranker.cli import run
from nhc_deprot_ranker.preparation.dft_plan import DFTPlanResult


def test_audit_legacy_dry_run_is_nonwriting() -> None:
    output = Path("results/should-not-exist.json")
    assert not output.exists()
    status = run(
        [
            "audit-legacy",
            "--config",
            "configs/legacy.example.yaml",
            "--out",
            str(output),
            "--dry-run",
        ]
    )
    assert status == 0
    assert not output.exists()


def test_later_phase_command_fails_clearly() -> None:
    assert run(["report", "--dry-run"]) == 2


def test_phase2_train_dry_run_is_nonwriting(tmp_path: Path) -> None:
    output = tmp_path / "baselines_v001"
    assert (
        run(
            [
                "train",
                "--dataset",
                "data/processed/v001",
                "--model-config",
                "configs/baselines.yaml",
                "--evaluation-config",
                "configs/evaluation.yaml",
                "--out",
                str(output),
                "--dry-run",
            ]
        )
        == 0
    )
    assert not output.exists()


def test_phase3_train_dry_run_dispatches_from_model_config(tmp_path: Path) -> None:
    output = tmp_path / "hierarchical_v001"
    assert (
        run(
            [
                "train",
                "--dataset",
                "data/processed/v001",
                "--baseline-results",
                "results/baselines_v001",
                "--model-config",
                "configs/model.yaml",
                "--evaluation-config",
                "configs/evaluation.yaml",
                "--out",
                str(output),
                "--dry-run",
            ]
        )
        == 0
    )
    assert not output.exists()


def test_phase4_evaluate_dry_run_is_nonwriting(tmp_path: Path) -> None:
    output = tmp_path / "decision_v001"
    assert (
        run(
            [
                "evaluate",
                "--dataset",
                "data/processed/v001",
                "--baseline-results",
                "results/baselines_v001",
                "--hierarchical-results",
                "results/hierarchical_v001",
                "--evaluation-config",
                "configs/evaluation.yaml",
                "--out",
                str(output),
                "--dry-run",
            ]
        )
        == 0
    )
    assert not output.exists()


def test_phase5_score_dry_run_is_nonwriting(tmp_path: Path) -> None:
    output = tmp_path / "scoring_v001"
    assert (
        run(
            [
                "score",
                "--dataset",
                "data/processed/v001",
                "--baseline-results",
                "results/baselines_v001",
                "--decision-results",
                "results/decision_v001",
                "--out",
                str(output),
                "--dry-run",
            ]
        )
        == 0
    )
    assert not output.exists()


def test_phase5_acquire_dry_run_is_nonwriting(tmp_path: Path) -> None:
    output = tmp_path / "acquisition_v001"
    assert (
        run(
            [
                "acquire",
                "--dataset",
                "data/processed/v001",
                "--scored-results",
                "results/scoring_v001",
                "--out",
                str(output),
                "--dry-run",
            ]
        )
        == 0
    )
    assert not output.exists()


def test_phase6_prepare_dft_plan_dry_run_is_nonwriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "dft_input_plan_v001"
    called: dict[str, Any] = {}

    def fake_prepare_dft_plan(**kwargs: Any) -> DFTPlanResult:
        called.update(kwargs)
        return DFTPlanResult(
            payload={
                "command": "prepare-dft-plan",
                "dry_run": True,
                "input_validated": True,
                "execution_ready": False,
            }
        )

    monkeypatch.setattr(cli_module, "prepare_dft_plan", fake_prepare_dft_plan)
    assert (
        run(
            [
                "prepare-dft-plan",
                "--dataset",
                "data/processed/v001",
                "--acquisition-results",
                "results/acquisition_v001",
                "--out",
                str(output),
                "--dry-run",
            ]
        )
        == 0
    )
    assert not output.exists()
    assert called["dry_run"] is True
    assert called["output_dir"] == output
