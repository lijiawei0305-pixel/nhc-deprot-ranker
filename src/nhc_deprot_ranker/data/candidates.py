"""Streaming candidate and fragment import for immutable Phase 1 datasets."""

from __future__ import annotations

import csv
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from nhc_deprot_ranker.chemistry.families import canonical_sorted_pair, combined_family
from nhc_deprot_ranker.config import CandidateColumnMap, FamiliesConfig
from nhc_deprot_ranker.data.labels import check_stored_label
from nhc_deprot_ranker.legacy.paths import ResolvedSource
from nhc_deprot_ranker.legacy.source_io import SourceMetadata, SourceReader


class CandidateImportError(ValueError):
    """Candidate or family input violates the Phase 1 data contract."""


@dataclass(frozen=True)
class FragmentLookupResult:
    """Validated InChIKey-to-fragment lookup and provenance."""

    lookup: dict[str, tuple[str, str, str, str]]
    source_metadata: tuple[SourceMetadata, ...]
    audit: dict[str, Any]


@dataclass(frozen=True)
class CandidateImportResult:
    """Normalized candidates and audit evidence."""

    frame: pd.DataFrame
    source_metadata: SourceMetadata
    audit: dict[str, Any]


def _required_columns(fieldnames: Sequence[str] | None, required: set[str], source_id: str) -> None:
    fields = set(fieldnames or [])
    missing = sorted(required - fields)
    if missing:
        raise CandidateImportError(f"{source_id} is missing required columns: {missing}")


def _finite_float(value: str | None, *, field: str, source_id: str, row_number: int) -> float:
    try:
        parsed = float(value) if value is not None else math.nan
    except ValueError as exc:
        raise CandidateImportError(
            f"{source_id} row {row_number}: invalid numeric {field}={value!r}"
        ) from exc
    if not math.isfinite(parsed):
        raise CandidateImportError(
            f"{source_id} row {row_number}: non-finite numeric {field}={value!r}"
        )
    return parsed


def import_fragment_lookup(
    *,
    reader: SourceReader,
    sources: tuple[ResolvedSource, ResolvedSource],
    columns: CandidateColumnMap,
) -> FragmentLookupResult:
    """Read two disjoint family sources and reject missing/conflicting identity."""

    fragment_columns = (columns.n1_frag, columns.n3_frag, columns.c4_frag, columns.c5_frag)
    required = {columns.inchikey, *fragment_columns}
    lookup: dict[str, tuple[str, str, str, str]] = {}
    metadata: list[SourceMetadata] = []
    source_rows: dict[str, int] = {}
    for source in sources:
        metadata.append(reader.metadata(source))
        rows = 0
        with reader.open_text(source) as stream:
            csv_reader = csv.DictReader(stream)
            _required_columns(csv_reader.fieldnames, required, source.source_id)
            for row_number, row in enumerate(csv_reader, start=2):
                rows += 1
                key = (row.get(columns.inchikey) or "").strip()
                if not key:
                    raise CandidateImportError(
                        f"{source.source_id} row {row_number}: blank InChIKey"
                    )
                fragments = tuple((row.get(column) or "").strip() for column in fragment_columns)
                if any(not fragment for fragment in fragments):
                    raise CandidateImportError(
                        f"{source.source_id} row {row_number}: missing fragment for {key}"
                    )
                typed_fragments = (fragments[0], fragments[1], fragments[2], fragments[3])
                existing = lookup.get(key)
                if existing is not None:
                    detail = (
                        "same assignment"
                        if existing == typed_fragments
                        else "conflicting assignment"
                    )
                    raise CandidateImportError(
                        f"duplicate fragment key {key} across sources ({detail})"
                    )
                lookup[key] = typed_fragments
        source_rows[source.source_id] = rows
    return FragmentLookupResult(
        lookup=lookup,
        source_metadata=tuple(metadata),
        audit={
            "source_rows": source_rows,
            "union_rows": sum(source_rows.values()),
            "unique_inchikeys": len(lookup),
            "source_overlap_keys": 0,
            "missing_fragment_cells": 0,
        },
    )


def import_candidates(
    *,
    reader: SourceReader,
    source: ResolvedSource,
    fragments: FragmentLookupResult,
    columns: CandidateColumnMap,
    families: FamiliesConfig,
    formula_tolerance_kcal: float,
) -> CandidateImportResult:
    """Normalize, formula-check, family-join, and deterministically rank candidates."""

    required = {
        columns.inchikey,
        columns.smiles_cation,
        columns.smiles_neutral,
        columns.e_cation_hartree,
        columns.e_neutral_hartree,
        columns.xtb_deprot_kcal,
    }
    metadata = reader.metadata(source)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_formula_error = 0.0
    with reader.open_text(source) as stream:
        csv_reader = csv.DictReader(stream)
        _required_columns(csv_reader.fieldnames, required, source.source_id)
        for row_number, row in enumerate(csv_reader, start=2):
            key = (row.get(columns.inchikey) or "").strip()
            if not key:
                raise CandidateImportError(f"{source.source_id} row {row_number}: blank InChIKey")
            if key in seen:
                raise CandidateImportError(
                    f"{source.source_id} row {row_number}: duplicate key {key}"
                )
            seen.add(key)
            smiles_cation = (row.get(columns.smiles_cation) or "").strip()
            smiles_neutral = (row.get(columns.smiles_neutral) or "").strip()
            if not smiles_cation or not smiles_neutral:
                raise CandidateImportError(
                    f"{source.source_id} row {row_number}: missing SMILES for {key}"
                )
            e_cation = _finite_float(
                row.get(columns.e_cation_hartree),
                field=columns.e_cation_hartree,
                source_id=source.source_id,
                row_number=row_number,
            )
            e_neutral = _finite_float(
                row.get(columns.e_neutral_hartree),
                field=columns.e_neutral_hartree,
                source_id=source.source_id,
                row_number=row_number,
            )
            target = _finite_float(
                row.get(columns.xtb_deprot_kcal),
                field=columns.xtb_deprot_kcal,
                source_id=source.source_id,
                row_number=row_number,
            )
            formula = check_stored_label(
                e_neutral_hartree=e_neutral,
                e_cation_hartree=e_cation,
                stored_target_kcal=target,
                tolerance_kcal=formula_tolerance_kcal,
            )
            max_formula_error = max(max_formula_error, formula.absolute_error_kcal)
            fragment_values = fragments.lookup.get(key)
            if fragment_values is None:
                raise CandidateImportError(f"candidate {key} has no fragment lookup row")
            n1, n3, c4, c5 = fragment_values
            axis_a = canonical_sorted_pair(n1, n3, unknown_token=families.unknown_token)
            axis_b = canonical_sorted_pair(c4, c5, unknown_token=families.unknown_token)
            skeleton = families.skeleton.current_value
            rows.append(
                {
                    "inchikey": key,
                    "smiles_cation": smiles_cation,
                    "smiles_neutral": smiles_neutral,
                    "xtb_deprot_kcal": target,
                    "n1_frag": n1,
                    "n3_frag": n3,
                    "c4_frag": c4,
                    "c5_frag": c5,
                    "skeleton": skeleton,
                    "axis_a_family": axis_a,
                    "axis_b_family": axis_b,
                    "combined_family": combined_family(
                        skeleton=skeleton,
                        axis_a_family=axis_a,
                        axis_b_family=axis_b,
                        unknown_token=families.unknown_token,
                    ),
                    "source_file": source.source_id,
                    "source_sha256": metadata.sha256,
                }
            )
    extra_lookup = set(fragments.lookup) - seen
    if extra_lookup:
        example = min(extra_lookup)
        raise CandidateImportError(
            f"fragment lookup has {len(extra_lookup)} key(s) absent from candidates; "
            f"example={example}"
        )
    frame = pd.DataFrame.from_records(rows)
    if frame.empty:
        raise CandidateImportError("candidate input is empty")
    frame = frame.sort_values(["xtb_deprot_kcal", "inchikey"], kind="mergesort").reset_index(
        drop=True
    )
    frame.insert(4, "xtb_rank", np.arange(1, len(frame) + 1, dtype=np.int64))
    denominator = max(len(frame) - 1, 1)
    frame.insert(5, "xtb_percentile", (frame["xtb_rank"] - 1) / denominator)
    frame["n_heavy_atoms"] = pd.array([None] * len(frame), dtype="Int64")
    frame["n_electrons"] = pd.array([None] * len(frame), dtype="Int64")
    column_order = [
        "inchikey",
        "smiles_cation",
        "smiles_neutral",
        "xtb_deprot_kcal",
        "xtb_rank",
        "xtb_percentile",
        "n1_frag",
        "n3_frag",
        "c4_frag",
        "c5_frag",
        "skeleton",
        "axis_a_family",
        "axis_b_family",
        "combined_family",
        "n_heavy_atoms",
        "n_electrons",
        "source_file",
        "source_sha256",
    ]
    frame = frame.loc[:, column_order]
    audit = {
        "rows": len(frame),
        "unique_inchikeys": int(frame["inchikey"].nunique()),
        "duplicate_inchikeys": int(frame["inchikey"].duplicated().sum()),
        "formula_checked": len(frame),
        "formula_failures": 0,
        "max_formula_absolute_error_kcal": max_formula_error,
        "fragment_coverage_rows": len(frame),
        "fragment_coverage_fraction": 1.0,
        "axis_a_families": int(frame["axis_a_family"].nunique()),
        "axis_b_families": int(frame["axis_b_family"].nunique()),
        "combined_families": int(frame["combined_family"].nunique()),
        "xtb_target_min": float(frame["xtb_deprot_kcal"].min()),
        "xtb_target_max": float(frame["xtb_deprot_kcal"].max()),
        "missing_values": {column: int(frame[column].isna().sum()) for column in frame.columns},
        "lower_is_better": True,
    }
    return CandidateImportResult(frame=frame, source_metadata=metadata, audit=audit)
