"""Streaming Phase 0 CSV audit tests."""

import csv
from pathlib import Path

from nhc_deprot_ranker.data.labels import dft_deprot_electronic_kcal
from nhc_deprot_ranker.legacy.audit import (
    audit_csv_keys_and_numeric,
    validate_label_csv,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_streaming_key_audit_counts_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "candidate.csv"
    _write_csv(
        path,
        [
            {"InChIKey": "A", "target": 1.0},
            {"InChIKey": "A", "target": 2.0},
            {"InChIKey": "B", "target": ""},
        ],
    )
    audit = audit_csv_keys_and_numeric(path, key_column="InChIKey", numeric_columns=("target",))
    assert audit["rows"] == 3
    assert audit["unique_keys"] == 2
    assert audit["duplicate_key_values"] == 1
    assert audit["numeric_missing_or_nonfinite"]["target"] == 1


def test_label_csv_formula_check(tmp_path: Path) -> None:
    path = tmp_path / "labels.csv"
    target = dft_deprot_electronic_kcal(-9.5, -10.0)
    _write_csv(
        path,
        [
            {
                "InChIKey": "A",
                "E_cation": -10.0,
                "E_neutral": -9.5,
                "target": target,
            }
        ],
    )
    audit = validate_label_csv(
        path,
        key_column="InChIKey",
        cation_column="E_cation",
        neutral_column="E_neutral",
        target_column="target",
        tolerance_kcal=0.02,
    )
    assert audit["formula_checked"] == 1
    assert audit["formula_failures"] == 0
