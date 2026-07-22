"""Synthetic Phase 6 local DFT handoff-plan tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

import nhc_deprot_ranker.preparation.dft_plan as dft_plan_module
from nhc_deprot_ranker.config import load_dft_plan_config
from nhc_deprot_ranker.data.provenance import sha256_file
from nhc_deprot_ranker.preparation.dft_plan import (
    DFTPlanError,
    build_batch_plan,
    prepare_dft_plan,
)

BUCKET_COUNTS = {
    "predicted_top_region": 15,
    "cutoff_region": 13,
    "chemical_family_diversity": 12,
    "uncertain_ood_conflict": 10,
}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _base26(value: int, width: int) -> str:
    letters: list[str] = []
    for _ in range(width):
        value, remainder = divmod(value, 26)
        letters.append(chr(ord("A") + remainder))
    return "".join(reversed(letters))


def _key(index: int) -> str:
    return f"{_base26(index + 1, 14)}-{_base26(index + 101, 10)}-A"


def _protocol() -> dict[str, Any]:
    return {
        "basis": "def2-SVP",
        "cation_charge": 1,
        "cation_multiplicity": 1,
        "dispersion": "D3(BJ)",
        "geometry_optimizer": "geomeTRIC",
        "label_quality": "electronic_energy_only",
        "method": "B3LYP",
        "neutral_charge": 0,
        "neutral_multiplicity": 1,
        "proton_constant_kcal": -6.28,
        "target_definition": "electronic_deprotonation_energy",
    }


def _acquisition_frame() -> pd.DataFrame:
    buckets: list[str] = []
    for bucket, count in BUCKET_COUNTS.items():
        buckets.extend([bucket] * count)
    rows = []
    for index, bucket in enumerate(buckets):
        rows.append(
            {
                "inchikey": _key(index),
                "smiles_cation": "C[n+]1ccn(C)c1",
                "smiles_neutral": "C[n]1ccn(C)c1",
                "production_rank": index + 1,
                "acquisition_score": 100.0 - index,
                "acquisition_bucket": bucket,
                "reason_codes": f"{bucket};size_unavailable",
                "suggested_priority": "high" if bucket != "chemical_family_diversity" else "medium",
            }
        )
    frame = pd.DataFrame(rows).sort_values(
        ["acquisition_score", "production_rank", "inchikey"],
        ascending=[False, True, True],
        kind="mergesort",
    )
    return frame.reset_index(drop=True)


def _hashes(root: Path, names: list[str]) -> dict[str, str]:
    return {name: sha256_file(root / name) for name in names}


def _resign_acquisition(inputs: dict[str, Path]) -> None:
    """Refresh the synthetic three-layer Phase 5 hash chain after a deliberate mutation."""

    root = inputs["acquisition"]
    manifest = json.loads((root / "acquisition_manifest.json").read_text())
    manifest["output_sha256"] = _hashes(
        root, ["acquisition_candidates.csv", "high_fidelity_batch_manifest.json"]
    )
    _write_json(root / "acquisition_manifest.json", manifest)
    success = json.loads((root / "_SUCCESS").read_text())
    success["acquisition_manifest_sha256"] = sha256_file(root / "acquisition_manifest.json")
    success["candidate_csv_sha256"] = sha256_file(root / "acquisition_candidates.csv")
    _write_json(root / "_SUCCESS", success)
    evidence = json.loads(inputs["acquisition_evidence"].read_text())
    evidence["output_sha256"] = _hashes(
        root,
        [
            "_SUCCESS",
            "acquisition_candidates.csv",
            "acquisition_manifest.json",
            "high_fidelity_batch_manifest.json",
        ],
    )
    _write_json(inputs["acquisition_evidence"], evidence)


def _build_inputs(tmp_path: Path) -> dict[str, Path]:
    dataset = tmp_path / "vtest"
    acquisition = tmp_path / "acquisition_vtest"
    dataset.mkdir()
    acquisition.mkdir()
    labels = pd.DataFrame({"inchikey": [_key(100 + index) for index in range(3)]})
    labels.to_parquet(dataset / "labels.parquet", index=False)
    _write_json(
        dataset / "protocol_manifest.json",
        {
            "hartree_to_kcal_mol": 627.509474,
            "label_protocol_id": (
                "2d03e2dc62c94cbf2bb6aaa1a40b842bb1369427c9df10b742441ef7227850fd"
            ),
            "lower_is_better": True,
            "protocol": _protocol(),
        },
    )
    dataset_evidence = tmp_path / "dataset_evidence.json"
    _write_json(
        dataset_evidence,
        {
            "dataset_version": "vtest",
            "rows": {"labels": len(labels)},
            "output_sha256": _hashes(dataset, ["labels.parquet", "protocol_manifest.json"]),
        },
    )

    frame = _acquisition_frame()
    frame.to_csv(acquisition / "acquisition_candidates.csv", index=False)
    records = []
    for raw in frame.to_dict("records"):
        row = {str(key): value for key, value in raw.items()}
        records.append(
            {
                "inchikey": row["inchikey"],
                "smiles_cation": row["smiles_cation"],
                "smiles_neutral": row["smiles_neutral"],
                "production_rank": row["production_rank"],
                "acquisition_bucket": row["acquisition_bucket"],
                "suggested_priority": row["suggested_priority"],
                "reason_codes": str(row["reason_codes"]).split(";"),
            }
        )
    _write_json(
        acquisition / "high_fidelity_batch_manifest.json",
        {
            "manifest_type": "local_high_fidelity_suggestion_only",
            "dataset_version": "vtest",
            "acquisition_version": "vtest",
            "candidate_count": len(records),
            "candidates": records,
            "protocol": _protocol(),
            "hessian_computed": False,
            "lower_is_better": True,
            "submit_hpc": False,
            "server_write_authorized": False,
            "target_reaction": "NHC-H+ -> NHC + H+",
        },
    )
    _write_json(
        acquisition / "acquisition_manifest.json",
        {
            "dataset_version": "vtest",
            "acquisition_version": "vtest",
            "ranking_model": "B0_raw_xTB",
            "batch_size": 50,
            "submit_hpc": False,
            "output_sha256": _hashes(
                acquisition,
                ["acquisition_candidates.csv", "high_fidelity_batch_manifest.json"],
            ),
        },
    )
    _write_json(
        acquisition / "_SUCCESS",
        {
            "dataset_version": "vtest",
            "acquisition_version": "vtest",
            "status": "passed",
            "selected": 50,
            "submit_hpc": False,
            "acquisition_manifest_sha256": sha256_file(acquisition / "acquisition_manifest.json"),
            "candidate_csv_sha256": sha256_file(acquisition / "acquisition_candidates.csv"),
        },
    )
    acquisition_evidence = tmp_path / "acquisition_evidence.json"
    acquisition_files = [
        "_SUCCESS",
        "acquisition_candidates.csv",
        "acquisition_manifest.json",
        "high_fidelity_batch_manifest.json",
    ]
    _write_json(
        acquisition_evidence,
        {
            "dataset_version": "vtest",
            "acquisition_version": "vtest",
            "gate_status": "passed",
            "ranking_model": "B0_raw_xTB",
            "batch_size": 50,
            "submit_hpc": False,
            "output_sha256": _hashes(acquisition, acquisition_files),
        },
    )

    raw_config = yaml.safe_load(Path("configs/dft_plan.yaml").read_text(encoding="utf-8"))
    raw_config["version"] = "vtest"
    raw_config["dataset_version"] = "vtest"
    raw_config["acquisition_version"] = "vtest"
    raw_config["expected_labels"] = 3
    config = tmp_path / "dft_plan.yaml"
    config.write_text(yaml.safe_dump(raw_config, sort_keys=False), encoding="utf-8")
    return {
        "dataset": dataset,
        "dataset_evidence": dataset_evidence,
        "acquisition": acquisition,
        "acquisition_evidence": acquisition_evidence,
        "config": config,
    }


def test_batch_plan_is_exact_and_deterministic() -> None:
    config = load_dft_plan_config(Path("configs/dft_plan.yaml"))
    frame = _acquisition_frame()
    frame["acquisition_order"] = range(1, len(frame) + 1)
    first = build_batch_plan(frame, config)
    second = build_batch_plan(frame, config)
    pd.testing.assert_frame_equal(first, second)
    assert first["InChIKey"].nunique() == len(first) == 50
    assert first.groupby("batch_id").size().to_dict() == {
        f"batch_{index:02d}": 10 for index in range(1, 6)
    }
    assert first.pivot_table(
        index="batch_id",
        columns="acquisition_bucket",
        values="InChIKey",
        aggfunc="count",
    ).to_dict("index") == {
        "batch_01": {
            "chemical_family_diversity": 2,
            "cutoff_region": 3,
            "predicted_top_region": 3,
            "uncertain_ood_conflict": 2,
        },
        "batch_02": {
            "chemical_family_diversity": 2,
            "cutoff_region": 3,
            "predicted_top_region": 3,
            "uncertain_ood_conflict": 2,
        },
        "batch_03": {
            "chemical_family_diversity": 2,
            "cutoff_region": 3,
            "predicted_top_region": 3,
            "uncertain_ood_conflict": 2,
        },
        "batch_04": {
            "chemical_family_diversity": 3,
            "cutoff_region": 2,
            "predicted_top_region": 3,
            "uncertain_ood_conflict": 2,
        },
        "batch_05": {
            "chemical_family_diversity": 3,
            "cutoff_region": 2,
            "predicted_top_region": 3,
            "uncertain_ood_conflict": 2,
        },
    }
    smoke = first.loc[first["is_smoke"]]
    assert len(smoke) == 4
    assert smoke["batch_id"].eq("batch_01").all()
    assert smoke["acquisition_bucket"].value_counts().to_dict() == {
        bucket: 1 for bucket in BUCKET_COUNTS
    }


def test_phase6_end_to_end_creates_only_a_nonexecuting_plan(tmp_path: Path) -> None:
    inputs = _build_inputs(tmp_path)
    output = tmp_path / "dft_input_plan_vtest"
    result = prepare_dft_plan(
        dataset_dir=inputs["dataset"],
        acquisition_results_dir=inputs["acquisition"],
        plan_config_path=inputs["config"],
        dataset_evidence_path=inputs["dataset_evidence"],
        acquisition_evidence_path=inputs["acquisition_evidence"],
        output_dir=output,
        seed=20260722,
    )
    assert result.payload["candidate_rows"] == 50
    assert result.payload["geometry_generated"] is False
    assert result.payload["quantum_chemistry_run"] is False
    assert result.payload["execution_ready"] is False
    candidates = pd.read_csv(output / "candidates.csv")
    assert candidates.columns[:3].tolist() == [
        "InChIKey",
        "SMILES_cation",
        "SMILES_neutral",
    ]
    assert candidates["geometry_status"].eq("not_generated").all()
    plan = pd.read_csv(output / "batch_plan.csv")
    assert len(plan) == plan["InChIKey"].nunique() == 50
    assert plan.groupby("batch_id").size().eq(10).all()
    assert len(pd.read_csv(output / "smoke.csv")) == 4
    assert len(list((output / "batches").glob("batch_*/screen.csv"))) == 5
    protocol = json.loads((output / "protocol_manifest.json").read_text())
    assert protocol["geometry_generated"] is False
    assert protocol["hessian_computed"] is False
    assert protocol["execution_ready"] is False
    assert protocol["legacy_compatibility"] == [
        "blocked_no_xyz",
        "blocked_runner_extra_steps",
    ]
    assert protocol["runtime_parameters"]["server_destination"] is None
    assert protocol["legacy_interface"]["compatibility_blockers"] == [
        "blocked_no_xyz",
        "blocked_runner_extra_steps",
    ]
    forbidden = {".xyz", ".molden", ".sh", ".pbs", ".slurm"}
    assert not any(path.suffix in forbidden for path in output.rglob("*"))
    assert not list(output.rglob("freq.json"))
    assert {
        path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()
    } == {
        "_LOCAL_PLAN_SUCCESS",
        "HANDOFF.md",
        "batch_plan.csv",
        "candidates.csv",
        "expected_outputs.csv",
        "package_manifest.json",
        "protocol_manifest.json",
        "screen_full.csv",
        "smoke.csv",
        "validation_report.json",
        *(f"batches/batch_{index:02d}/screen.csv" for index in range(1, 6)),
    }
    manifest = json.loads((output / "package_manifest.json").read_text())
    for name, expected in manifest["output_sha256"].items():
        assert sha256_file(output / name) == expected
    success = json.loads((output / "_LOCAL_PLAN_SUCCESS").read_text())
    assert success["status"] == "local_plan_passed"
    assert success["hessian_computed"] is False
    assert success["legacy_compatibility"] == [
        "blocked_no_xyz",
        "blocked_runner_extra_steps",
    ]
    assert success["package_manifest_sha256"] == sha256_file(output / "package_manifest.json")
    with pytest.raises(DFTPlanError, match="already exists"):
        prepare_dft_plan(
            dataset_dir=inputs["dataset"],
            acquisition_results_dir=inputs["acquisition"],
            plan_config_path=inputs["config"],
            dataset_evidence_path=inputs["dataset_evidence"],
            acquisition_evidence_path=inputs["acquisition_evidence"],
            output_dir=output,
            seed=20260722,
        )


def test_phase6_rejects_tampered_acquisition_evidence(tmp_path: Path) -> None:
    inputs = _build_inputs(tmp_path)
    evidence = json.loads(inputs["acquisition_evidence"].read_text())
    evidence["output_sha256"]["acquisition_candidates.csv"] = "0" * 64
    _write_json(inputs["acquisition_evidence"], evidence)
    with pytest.raises(DFTPlanError, match="hash mismatch"):
        prepare_dft_plan(
            dataset_dir=inputs["dataset"],
            acquisition_results_dir=inputs["acquisition"],
            plan_config_path=inputs["config"],
            dataset_evidence_path=inputs["dataset_evidence"],
            acquisition_evidence_path=inputs["acquisition_evidence"],
            output_dir=tmp_path / "dft_input_plan_vtest",
            seed=20260722,
        )


def test_phase6_dry_run_validates_inputs_without_writing(tmp_path: Path) -> None:
    inputs = _build_inputs(tmp_path)
    output = tmp_path / "dft_input_plan_vtest"
    result = prepare_dft_plan(
        dataset_dir=inputs["dataset"],
        acquisition_results_dir=inputs["acquisition"],
        plan_config_path=inputs["config"],
        dataset_evidence_path=inputs["dataset_evidence"],
        acquisition_evidence_path=inputs["acquisition_evidence"],
        output_dir=output,
        seed=20260722,
        dry_run=True,
    )
    assert result.payload["status"] == "dry_run_validated"
    assert result.payload["input_validated"] is True
    assert result.payload["candidate_rows"] == 50
    assert not output.exists()

    inputs["dataset_evidence"].unlink()
    with pytest.raises(FileNotFoundError):
        prepare_dft_plan(
            dataset_dir=inputs["dataset"],
            acquisition_results_dir=inputs["acquisition"],
            plan_config_path=inputs["config"],
            dataset_evidence_path=inputs["dataset_evidence"],
            acquisition_evidence_path=inputs["acquisition_evidence"],
            output_dir=output,
            seed=20260722,
            dry_run=True,
        )
    assert not output.exists()


@pytest.mark.parametrize("unsafe_name", ["../outside.csv", "/tmp/outside.csv"])
def test_phase6_rejects_unsafe_registered_evidence_path(tmp_path: Path, unsafe_name: str) -> None:
    inputs = _build_inputs(tmp_path)
    evidence = json.loads(inputs["acquisition_evidence"].read_text())
    evidence["output_sha256"][unsafe_name] = "0" * 64
    _write_json(inputs["acquisition_evidence"], evidence)
    with pytest.raises(DFTPlanError, match="unsafe registered evidence path"):
        prepare_dft_plan(
            dataset_dir=inputs["dataset"],
            acquisition_results_dir=inputs["acquisition"],
            plan_config_path=inputs["config"],
            dataset_evidence_path=inputs["dataset_evidence"],
            acquisition_evidence_path=inputs["acquisition_evidence"],
            output_dir=tmp_path / "dft_input_plan_vtest",
            seed=20260722,
            dry_run=True,
        )


def test_phase6_rejects_a_registered_symlink(tmp_path: Path) -> None:
    inputs = _build_inputs(tmp_path)
    root = inputs["acquisition"]
    (root / "linked.csv").symlink_to(root / "acquisition_candidates.csv")
    evidence = json.loads(inputs["acquisition_evidence"].read_text())
    evidence["output_sha256"]["linked.csv"] = sha256_file(root / "linked.csv")
    _write_json(inputs["acquisition_evidence"], evidence)
    with pytest.raises(DFTPlanError, match="is a symlink"):
        prepare_dft_plan(
            dataset_dir=inputs["dataset"],
            acquisition_results_dir=root,
            plan_config_path=inputs["config"],
            dataset_evidence_path=inputs["dataset_evidence"],
            acquisition_evidence_path=inputs["acquisition_evidence"],
            output_dir=tmp_path / "dft_input_plan_vtest",
            seed=20260722,
            dry_run=True,
        )


def test_phase6_rejects_a_signed_bad_success_pointer(tmp_path: Path) -> None:
    inputs = _build_inputs(tmp_path)
    success_path = inputs["acquisition"] / "_SUCCESS"
    success = json.loads(success_path.read_text())
    success["candidate_csv_sha256"] = "0" * 64
    _write_json(success_path, success)
    evidence = json.loads(inputs["acquisition_evidence"].read_text())
    evidence["output_sha256"]["_SUCCESS"] = sha256_file(success_path)
    _write_json(inputs["acquisition_evidence"], evidence)
    with pytest.raises(DFTPlanError, match="success marker candidate hash mismatch"):
        prepare_dft_plan(
            dataset_dir=inputs["dataset"],
            acquisition_results_dir=inputs["acquisition"],
            plan_config_path=inputs["config"],
            dataset_evidence_path=inputs["dataset_evidence"],
            acquisition_evidence_path=inputs["acquisition_evidence"],
            output_dir=tmp_path / "dft_input_plan_vtest",
            seed=20260722,
            dry_run=True,
        )


def test_phase6_rejects_a_signed_bad_runtime_output_hash(tmp_path: Path) -> None:
    inputs = _build_inputs(tmp_path)
    root = inputs["acquisition"]
    manifest_path = root / "acquisition_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["output_sha256"]["acquisition_candidates.csv"] = "0" * 64
    _write_json(manifest_path, manifest)
    success_path = root / "_SUCCESS"
    success = json.loads(success_path.read_text())
    success["acquisition_manifest_sha256"] = sha256_file(manifest_path)
    _write_json(success_path, success)
    evidence = json.loads(inputs["acquisition_evidence"].read_text())
    evidence["output_sha256"]["acquisition_manifest.json"] = sha256_file(manifest_path)
    evidence["output_sha256"]["_SUCCESS"] = sha256_file(success_path)
    _write_json(inputs["acquisition_evidence"], evidence)
    with pytest.raises(DFTPlanError, match="runtime output hash mismatch"):
        prepare_dft_plan(
            dataset_dir=inputs["dataset"],
            acquisition_results_dir=root,
            plan_config_path=inputs["config"],
            dataset_evidence_path=inputs["dataset_evidence"],
            acquisition_evidence_path=inputs["acquisition_evidence"],
            output_dir=tmp_path / "dft_input_plan_vtest",
            seed=20260722,
            dry_run=True,
        )


def test_phase6_rejects_a_signed_malformed_handoff_record(tmp_path: Path) -> None:
    inputs = _build_inputs(tmp_path)
    path = inputs["acquisition"] / "high_fidelity_batch_manifest.json"
    handoff = json.loads(path.read_text())
    handoff["candidates"][0] = "not-an-object"
    _write_json(path, handoff)
    _resign_acquisition(inputs)
    with pytest.raises(DFTPlanError, match="record 0 is not an object"):
        prepare_dft_plan(
            dataset_dir=inputs["dataset"],
            acquisition_results_dir=inputs["acquisition"],
            plan_config_path=inputs["config"],
            dataset_evidence_path=inputs["dataset_evidence"],
            acquisition_evidence_path=inputs["acquisition_evidence"],
            output_dir=tmp_path / "dft_input_plan_vtest",
            seed=20260722,
            dry_run=True,
        )


def test_phase6_rejects_a_signed_handoff_record_with_a_missing_field(tmp_path: Path) -> None:
    inputs = _build_inputs(tmp_path)
    path = inputs["acquisition"] / "high_fidelity_batch_manifest.json"
    handoff = json.loads(path.read_text())
    del handoff["candidates"][0]["smiles_neutral"]
    _write_json(path, handoff)
    _resign_acquisition(inputs)
    with pytest.raises(DFTPlanError, match="record 0 is missing"):
        prepare_dft_plan(
            dataset_dir=inputs["dataset"],
            acquisition_results_dir=inputs["acquisition"],
            plan_config_path=inputs["config"],
            dataset_evidence_path=inputs["dataset_evidence"],
            acquisition_evidence_path=inputs["acquisition_evidence"],
            output_dir=tmp_path / "dft_input_plan_vtest",
            seed=20260722,
            dry_run=True,
        )


@pytest.mark.parametrize("invalid_rank", [float("inf"), 1.5])
def test_phase6_rejects_a_signed_invalid_rank(tmp_path: Path, invalid_rank: float) -> None:
    inputs = _build_inputs(tmp_path)
    path = inputs["acquisition"] / "acquisition_candidates.csv"
    frame = pd.read_csv(path)
    frame["production_rank"] = frame["production_rank"].astype(float)
    frame.loc[0, "production_rank"] = invalid_rank
    frame.to_csv(path, index=False)
    _resign_acquisition(inputs)
    with pytest.raises(DFTPlanError, match="production ranks must be finite integers"):
        prepare_dft_plan(
            dataset_dir=inputs["dataset"],
            acquisition_results_dir=inputs["acquisition"],
            plan_config_path=inputs["config"],
            dataset_evidence_path=inputs["dataset_evidence"],
            acquisition_evidence_path=inputs["acquisition_evidence"],
            output_dir=tmp_path / "dft_input_plan_vtest",
            seed=20260722,
            dry_run=True,
        )


def test_phase6_rejects_a_signed_nonfinite_acquisition_score(tmp_path: Path) -> None:
    inputs = _build_inputs(tmp_path)
    path = inputs["acquisition"] / "acquisition_candidates.csv"
    frame = pd.read_csv(path)
    frame.loc[0, "acquisition_score"] = float("inf")
    frame.to_csv(path, index=False)
    _resign_acquisition(inputs)
    with pytest.raises(DFTPlanError, match="acquisition scores must be finite"):
        prepare_dft_plan(
            dataset_dir=inputs["dataset"],
            acquisition_results_dir=inputs["acquisition"],
            plan_config_path=inputs["config"],
            dataset_evidence_path=inputs["dataset_evidence"],
            acquisition_evidence_path=inputs["acquisition_evidence"],
            output_dir=tmp_path / "dft_input_plan_vtest",
            seed=20260722,
            dry_run=True,
        )


def test_phase6_cleans_temporary_output_after_a_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _build_inputs(tmp_path)
    output = tmp_path / "dft_input_plan_vtest"
    original = dft_plan_module._write_json

    def fail_during_write(path: Path, payload: dict[str, Any]) -> None:
        if path.name == "validation_report.json":
            raise RuntimeError("synthetic write failure")
        original(path, payload)

    monkeypatch.setattr(dft_plan_module, "_write_json", fail_during_write)
    with pytest.raises(RuntimeError, match="synthetic write failure"):
        prepare_dft_plan(
            dataset_dir=inputs["dataset"],
            acquisition_results_dir=inputs["acquisition"],
            plan_config_path=inputs["config"],
            dataset_evidence_path=inputs["dataset_evidence"],
            acquisition_evidence_path=inputs["acquisition_evidence"],
            output_dir=output,
            seed=20260722,
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".dft_input_plan_vtest.tmp.*"))


def test_phase6_safe_tree_rejects_direct_output_hazards(tmp_path: Path) -> None:
    config = load_dft_plan_config(Path("configs/dft_plan.yaml"))

    extra_root = tmp_path / "extra"
    (extra_root / "unexpected").mkdir(parents=True)
    with pytest.raises(DFTPlanError, match="unregistered directory"):
        dft_plan_module._assert_safe_tree(extra_root, config, require_complete=False)

    symlink_root = tmp_path / "symlink"
    symlink_root.mkdir()
    target = tmp_path / "target.md"
    target.write_text("safe\n", encoding="utf-8")
    (symlink_root / "HANDOFF.md").symlink_to(target)
    with pytest.raises(DFTPlanError, match="must not contain symlinks"):
        dft_plan_module._assert_safe_tree(symlink_root, config, require_complete=False)

    executable_root = tmp_path / "executable"
    executable_root.mkdir()
    executable = executable_root / "HANDOFF.md"
    executable.write_text("safe\n", encoding="utf-8")
    executable.chmod(0o755)
    with pytest.raises(DFTPlanError, match="must not be executable"):
        dft_plan_module._assert_safe_tree(executable_root, config, require_complete=False)

    private_root = tmp_path / "private"
    private_root.mkdir()
    (private_root / "HANDOFF.md").write_text("/private/secret/path\n", encoding="utf-8")
    with pytest.raises(DFTPlanError, match="private absolute path"):
        dft_plan_module._assert_safe_tree(private_root, config, require_complete=False)
