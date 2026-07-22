"""End-to-end synthetic tests for immutable Phase 1 dataset construction."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from nhc_deprot_ranker.data.build import ImmutableDatasetError, build_dataset
from nhc_deprot_ranker.data.candidates import CandidateImportError
from nhc_deprot_ranker.data.labels import LabelFormulaMismatchError, LabelImportError
from nhc_deprot_ranker.data.provenance import sha256_file


@dataclass(frozen=True)
class FixturePaths:
    legacy_config: Path
    data_config: Path
    families_config: Path
    output: Path
    expected_order: list[str]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _target(e_cation: float, e_neutral: float) -> float:
    return (e_neutral - e_cation) * 627.509474 - 6.28


def _make_fixture(
    tmp_path: Path,
    *,
    candidate_formula_offset: float = 0.0,
    duplicate_label_delta_hartree: float | None = None,
    missing_fragment: bool = False,
) -> FixturePaths:
    legacy = tmp_path / "legacy"
    candidates = [
        ("KEY-A", "C[N+]", "CN", -10.0, -9.80),
        ("KEY-B", "CC[N+]", "CCN", -20.0, -19.90),
        ("KEY-C", "CCC[N+]", "CCCN", -30.0, -29.85),
        ("KEY-D", "CCCC[N+]", "CCCCN", -40.0, -39.95),
    ]
    candidate_rows = [
        {
            "InChIKey": key,
            "SMILES_cation": smiles_cation,
            "SMILES_neutral": smiles_neutral,
            "e_cation": e_cation,
            "e_neutral": e_neutral,
            "delta_e_deprot_kcal": _target(e_cation, e_neutral)
            + (candidate_formula_offset if key == "KEY-C" else 0.0),
        }
        for key, smiles_cation, smiles_neutral, e_cation, e_neutral in candidates
    ]
    _write_csv(legacy / "candidates/full.csv", candidate_rows)
    _write_csv(legacy / "candidates/reduced.csv", candidate_rows)
    fragment_rows = [
        {
            "InChIKey": "KEY-A",
            "N1_frag": "Me",
            "N3_frag": "Et",
            "C4_frag": "H",
            "C5_frag": "Cl",
        },
        {
            "InChIKey": "KEY-B",
            "N1_frag": "Et",
            "N3_frag": "Me",
            "C4_frag": "Cl",
            "C5_frag": "H",
        },
    ]
    v4_rows = [
        {
            "InChIKey": "KEY-C",
            "N1_frag": "Me",
            "N3_frag": "Me",
            "C4_frag": "H",
            "C5_frag": "H",
        },
        {
            "InChIKey": "KEY-D",
            "N1_frag": "iPr",
            "N3_frag": "Me",
            "C4_frag": "Br",
            "C5_frag": "H",
        },
    ]
    if missing_fragment:
        v4_rows.pop()
    _write_csv(legacy / "families/v3.csv", fragment_rows)
    _write_csv(legacy / "families/v4.csv", v4_rows)
    (legacy / "descriptors").mkdir(parents=True)
    (legacy / "descriptors/sample.parquet").write_bytes(b"not-used-in-phase1-fixture")

    gold_energy = candidates[0]
    _write_csv(
        legacy / "labels/gold.csv",
        [
            {
                "InChIKey": gold_energy[0],
                "E_cation": gold_energy[3],
                "E_neutral": gold_energy[4],
                "delta_e_deprot_dft_kcal": _target(gold_energy[3], gold_energy[4]),
            }
        ],
    )
    blind_energy = candidates[1] if duplicate_label_delta_hartree is None else candidates[0]
    blind_neutral = blind_energy[4] + (duplicate_label_delta_hartree or 0.0)
    _write_csv(
        legacy / "labels/blind1.csv",
        [
            {
                "InChIKey": blind_energy[0],
                "E_cation": blind_energy[3],
                "E_neutral": blind_neutral,
                "real_dft_kcal": _target(blind_energy[3], blind_neutral),
            }
        ],
    )
    round2_energy = candidates[2]
    _write_csv(
        legacy / "labels/round2.csv",
        [
            {
                "InChIKey": round2_energy[0],
                "E_cation": round2_energy[3],
                "E_neutral": round2_energy[4],
                "dft_deprot_kcal": _target(round2_energy[3], round2_energy[4]),
            }
        ],
    )

    legacy_config = {
        "legacy_repo": {
            "root": str(legacy),
            "expected_remote": "https://example.invalid/legacy.git",
            "expected_commit": "a" * 40,
        },
        "source_access": {"mode": "local", "read_only": True},
        "candidates": {
            "xtb_crude_csv": {"location": "legacy_repo", "path": "candidates/full.csv"},
            "xtb_reduced_csv": {
                "location": "legacy_repo",
                "path": "candidates/reduced.csv",
            },
            "v3_graph_csv": {"location": "legacy_repo", "path": "families/v3.csv"},
            "v4_new_only_csv": {"location": "legacy_repo", "path": "families/v4.csv"},
            "descriptors_parquet": {
                "location": "legacy_repo",
                "path": "descriptors/sample.parquet",
            },
        },
        "labels": {
            "sources": [
                {
                    "source_group": "gold",
                    "location": "legacy_repo",
                    "path": "labels/gold.csv",
                    "type": "electronic_energy",
                },
                {
                    "source_group": "blind_round1",
                    "location": "legacy_repo",
                    "path": "labels/blind1.csv",
                    "type": "electronic_energy",
                },
                {
                    "source_group": "blind_round2",
                    "location": "legacy_repo",
                    "path": "labels/round2.csv",
                    "type": "electronic_energy",
                },
            ]
        },
    }
    legacy_config_path = tmp_path / "legacy.yaml"
    legacy_config_path.write_text(yaml.safe_dump(legacy_config, sort_keys=False))

    data_config = yaml.safe_load(Path("configs/data.yaml").read_text())
    data_config["dataset_version"] = "vtest"
    data_config["processed_root"] = str(tmp_path / "processed")
    data_config_path = tmp_path / "data.yaml"
    data_config_path.write_text(yaml.safe_dump(data_config, sort_keys=False))
    families_config_path = tmp_path / "families.yaml"
    families_config_path.write_text(Path("configs/families.yaml").read_text())
    expected_order = [
        row["InChIKey"]
        for row in sorted(
            candidate_rows,
            key=lambda row: (float(row["delta_e_deprot_kcal"]), str(row["InChIKey"])),
        )
    ]
    return FixturePaths(
        legacy_config=legacy_config_path,
        data_config=data_config_path,
        families_config=families_config_path,
        output=tmp_path / "processed/vtest",
        expected_order=expected_order,
    )


def _build(paths: FixturePaths, *, dry_run: bool = False) -> dict[str, Any]:
    return build_dataset(
        legacy_config_path=paths.legacy_config,
        data_config_path=paths.data_config,
        families_config_path=paths.families_config,
        output_dir=paths.output,
        dry_run=dry_run,
    ).payload


def test_end_to_end_build_writes_immutable_normalized_dataset(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    result = _build(paths)
    assert result["status"] == "complete"
    assert result["candidate_rows"] == 4
    assert result["label_rows"] == 3
    candidates = pd.read_parquet(paths.output / "candidates.parquet")
    labels = pd.read_parquet(paths.output / "labels.parquet")
    membership = pd.read_csv(paths.output / "label_source_membership.csv")
    assert candidates["inchikey"].tolist() == paths.expected_order
    assert candidates["xtb_rank"].tolist() == [1, 2, 3, 4]
    assert candidates["xtb_percentile"].tolist() == pytest.approx([0.0, 1 / 3, 2 / 3, 1.0])
    assert candidates.loc[candidates.inchikey.eq("KEY-A"), "axis_a_family"].item() == "Et|Me"
    assert candidates.loc[candidates.inchikey.eq("KEY-B"), "axis_a_family"].item() == "Et|Me"
    assert len(labels) == 3
    assert labels["label_protocol_id"].nunique() == 1
    assert labels["formula_revalidated"].all()
    assert not labels["hessian_computed"].any()
    assert len(membership) == 3
    quality = json.loads((paths.output / "data_quality.json").read_text())
    assert quality["phase1_gate"] == {
        "formula_failures": 0,
        "fragment_coverage_fraction": 1.0,
        "label_conflicts": 0,
        "labels_missing_candidates": 0,
        "primary_key_unique": True,
        "protocol_ids": 1,
    }
    source_manifest = json.loads((paths.output / "source_manifest.json").read_text())
    assert [source["parsed_rows"] for source in source_manifest["sources"]] == [
        4,
        2,
        2,
        1,
        1,
        1,
    ]
    success = json.loads((paths.output / "_SUCCESS").read_text())
    assert success["rows"] == {"candidates": 4, "labels": 3}
    assert success["manifest_sha256"] == sha256_file(paths.output / "source_manifest.json")


def test_dry_run_does_not_create_output(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    result = _build(paths, dry_run=True)
    assert result["dry_run"] is True
    assert result["remote_writes"] is False
    assert not paths.output.exists()


def test_existing_version_is_never_overwritten(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    _build(paths)
    success_hash = sha256_file(paths.output / "_SUCCESS")
    with pytest.raises(ImmutableDatasetError, match="already exists"):
        _build(paths)
    assert sha256_file(paths.output / "_SUCCESS") == success_hash


def test_candidate_formula_mismatch_cleans_partial_output(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path, candidate_formula_offset=0.03)
    with pytest.raises(LabelFormulaMismatchError):
        _build(paths)
    assert not paths.output.exists()
    assert not list(paths.output.parent.glob(".vtest.tmp.*"))


def test_missing_fragment_is_hard_reject(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path, missing_fragment=True)
    with pytest.raises(CandidateImportError, match="no fragment"):
        _build(paths)
    assert not paths.output.exists()


def test_consistent_duplicate_label_membership_merges(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path, duplicate_label_delta_hartree=0.0)
    result = _build(paths)
    assert result["label_rows"] == 2
    membership = pd.read_csv(paths.output / "label_source_membership.csv")
    assert len(membership) == 3
    quality = json.loads((paths.output / "data_quality.json").read_text())
    assert quality["label_audit"]["consistent_duplicate_memberships"] == 1


def test_conflicting_duplicate_label_is_hard_reject(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path, duplicate_label_delta_hartree=0.001)
    with pytest.raises(LabelImportError, match="conflicting label"):
        _build(paths)
    assert not paths.output.exists()
