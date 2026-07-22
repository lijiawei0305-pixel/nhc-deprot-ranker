"""Phase 0 local CSV audit and safe source-plan generation."""

from __future__ import annotations

import csv
import math
from collections import Counter
from pathlib import Path
from typing import Any

from nhc_deprot_ranker.config import LegacyConfig
from nhc_deprot_ranker.data.labels import LabelFormulaMismatchError, check_stored_label
from nhc_deprot_ranker.data.provenance import sha256_file
from nhc_deprot_ranker.legacy.paths import resolve_source


def _parse_finite(value: str | None) -> float | None:
    try:
        parsed = float(value) if value is not None else math.nan
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def audit_csv_keys_and_numeric(
    path: Path,
    *,
    key_column: str,
    numeric_columns: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Audit one local CSV without loading it fully into memory."""

    if not path.is_file():
        raise FileNotFoundError(path)
    rows = 0
    keys: Counter[str] = Counter()
    numeric_missing = Counter({column: 0 for column in numeric_columns})
    numeric_min: dict[str, float] = {}
    numeric_max: dict[str, float] = {}
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        required = {key_column, *numeric_columns}
        missing_fields = sorted(required - set(fields))
        if missing_fields:
            raise ValueError(f"missing required columns in {path}: {missing_fields}")
        for row in reader:
            rows += 1
            keys[row.get(key_column, "")] += 1
            for column in numeric_columns:
                value = _parse_finite(row.get(column))
                if value is None:
                    numeric_missing[column] += 1
                    continue
                numeric_min[column] = min(numeric_min.get(column, value), value)
                numeric_max[column] = max(numeric_max.get(column, value), value)
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "columns": fields,
        "rows": rows,
        "unique_keys": len(keys) - int("" in keys),
        "blank_key_rows": keys.get("", 0),
        "duplicate_key_values": sum(count > 1 for key, count in keys.items() if key),
        "duplicate_rows": sum(count - 1 for key, count in keys.items() if key and count > 1),
        "numeric_missing_or_nonfinite": dict(numeric_missing),
        "numeric_min": numeric_min,
        "numeric_max": numeric_max,
    }


def validate_label_csv(
    path: Path,
    *,
    key_column: str,
    cation_column: str,
    neutral_column: str,
    target_column: str,
    tolerance_kcal: float,
) -> dict[str, Any]:
    """Validate every formula-complete row in one local label CSV."""

    if not path.is_file():
        raise FileNotFoundError(path)
    rows = 0
    checked = 0
    incomplete = 0
    failures: list[dict[str, Any]] = []
    max_error = 0.0
    keys: Counter[str] = Counter()
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        required = {key_column, cation_column, neutral_column, target_column}
        missing_fields = sorted(required - set(fields))
        if missing_fields:
            raise ValueError(f"missing required columns in {path}: {missing_fields}")
        for row_number, row in enumerate(reader, start=2):
            rows += 1
            key = row.get(key_column, "")
            keys[key] += 1
            cation = _parse_finite(row.get(cation_column))
            neutral = _parse_finite(row.get(neutral_column))
            target = _parse_finite(row.get(target_column))
            if cation is None or neutral is None or target is None:
                incomplete += 1
                continue
            checked += 1
            try:
                result = check_stored_label(
                    e_neutral_hartree=neutral,
                    e_cation_hartree=cation,
                    stored_target_kcal=target,
                    tolerance_kcal=tolerance_kcal,
                )
                max_error = max(max_error, result.absolute_error_kcal)
            except LabelFormulaMismatchError as exc:
                failures.append({"row": row_number, "inchikey": key, "error": str(exc)})
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "rows": rows,
        "unique_keys": len(keys) - int("" in keys),
        "blank_key_rows": keys.get("", 0),
        "duplicate_key_values": sum(count > 1 for key, count in keys.items() if key),
        "formula_checked": checked,
        "formula_incomplete": incomplete,
        "formula_failures": len(failures),
        "max_absolute_error_kcal": max_error,
        "failure_details": failures,
    }


def build_source_plan(config: LegacyConfig) -> dict[str, Any]:
    """Resolve all sources without opening remote paths or mutating anything."""

    candidate_plan = {
        name: resolve_source(config, getattr(config.candidates, name)).display()
        for name in type(config.candidates).model_fields
    }
    labels = [
        {
            "source_group": source.source_group,
            "source": resolve_source(config, source).display(),
            "type": source.type,
        }
        for source in config.labels.sources
    ]
    return {
        "read_only": config.source_access.read_only,
        "mode": config.source_access.mode,
        "legacy_root": str(config.legacy_repo.root),
        "expected_remote": config.legacy_repo.expected_remote,
        "expected_commit": config.legacy_repo.expected_commit,
        "candidates": candidate_plan,
        "labels": labels,
        "remote_execution_performed": False,
    }
