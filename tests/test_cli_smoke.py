"""Phase 0 CLI smoke tests."""

from pathlib import Path

from nhc_deprot_ranker.cli import run


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
    assert run(["evaluate", "--dry-run"]) == 2


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
