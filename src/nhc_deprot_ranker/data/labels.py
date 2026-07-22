"""Electronic deprotonation-energy formula and protocol validation."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from nhc_deprot_ranker.config import DataConfig, LabelSource
from nhc_deprot_ranker.constants import (
    GAS_PROTON_KCAL_MOL,
    HARTREE_TO_KCAL_MOL,
    LABEL_FORMULA_ATOL_KCAL_MOL,
)
from nhc_deprot_ranker.legacy.paths import ResolvedSource
from nhc_deprot_ranker.legacy.source_io import SourceMetadata, SourceReader


class LabelFormulaMismatchError(ValueError):
    """Stored label disagrees with endpoint electronic energies."""


def _finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def electronic_difference_kcal(e_neutral_hartree: float, e_cation_hartree: float) -> float:
    """Return `(E_neutral - E_cation)` in kcal/mol, without the proton term."""

    neutral = _finite(float(e_neutral_hartree), "e_neutral_hartree")
    cation = _finite(float(e_cation_hartree), "e_cation_hartree")
    return (neutral - cation) * HARTREE_TO_KCAL_MOL


def dft_deprot_electronic_kcal(
    e_neutral_hartree: float,
    e_cation_hartree: float,
) -> float:
    """Return the legacy-compatible DFT electronic deprotonation label."""

    return electronic_difference_kcal(e_neutral_hartree, e_cation_hartree) + GAS_PROTON_KCAL_MOL


@dataclass(frozen=True)
class LabelFormulaCheck:
    """Result of comparing a stored target with recomputed endpoint energy."""

    electronic_difference_kcal: float
    expected_target_kcal: float
    stored_target_kcal: float
    absolute_error_kcal: float
    tolerance_kcal: float

    @property
    def passed(self) -> bool:
        """Whether the absolute error is within tolerance."""

        return self.absolute_error_kcal <= self.tolerance_kcal


def check_stored_label(
    *,
    e_neutral_hartree: float,
    e_cation_hartree: float,
    stored_target_kcal: float,
    tolerance_kcal: float = LABEL_FORMULA_ATOL_KCAL_MOL,
) -> LabelFormulaCheck:
    """Recompute a label and raise on disagreement beyond tolerance."""

    if tolerance_kcal < 0 or not math.isfinite(tolerance_kcal):
        raise ValueError("tolerance_kcal must be finite and non-negative")
    stored = _finite(float(stored_target_kcal), "stored_target_kcal")
    difference = electronic_difference_kcal(e_neutral_hartree, e_cation_hartree)
    expected = difference + GAS_PROTON_KCAL_MOL
    result = LabelFormulaCheck(
        electronic_difference_kcal=difference,
        expected_target_kcal=expected,
        stored_target_kcal=stored,
        absolute_error_kcal=abs(expected - stored),
        tolerance_kcal=tolerance_kcal,
    )
    if not result.passed:
        raise LabelFormulaMismatchError(
            "stored label differs from endpoint formula: "
            f"expected={expected:.12g}, stored={stored:.12g}, "
            f"abs_error={result.absolute_error_kcal:.6g}, tolerance={tolerance_kcal:.6g}"
        )
    return result


def label_protocol_id(protocol: Mapping[str, Any]) -> str:
    """Hash a normalized protocol mapping deterministically."""

    encoded = json.dumps(
        dict(protocol),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class LabelImportError(ValueError):
    """A label source violates formula, key, or protocol contracts."""


@dataclass(frozen=True)
class LabelImportResult:
    """Normalized labels, all source memberships, and audit evidence."""

    frame: pd.DataFrame
    membership: pd.DataFrame
    source_metadata: tuple[SourceMetadata, ...]
    protocol: dict[str, Any]
    protocol_id: str
    audit: dict[str, Any]


def _source_float(value: str | None, *, field: str, source_id: str, row_number: int) -> float:
    try:
        parsed = float(value) if value is not None else math.nan
    except ValueError as exc:
        raise LabelImportError(
            f"{source_id} row {row_number}: invalid numeric {field}={value!r}"
        ) from exc
    if not math.isfinite(parsed):
        raise LabelImportError(
            f"{source_id} row {row_number}: non-finite numeric {field}={value!r}"
        )
    return parsed


def import_high_fidelity_labels(
    *,
    reader: SourceReader,
    sources: tuple[tuple[LabelSource, ResolvedSource], ...],
    data_config: DataConfig,
    candidate_keys: set[str],
) -> LabelImportResult:
    """Import formula-validated labels and reject cross-source conflicts."""

    protocol = data_config.protocol.model_dump(mode="json")
    protocol_hash = label_protocol_id(protocol)
    records: dict[str, dict[str, Any]] = {}
    membership_rows: list[dict[str, Any]] = []
    metadata: list[SourceMetadata] = []
    source_counts: dict[str, int] = {}
    consistent_duplicate_memberships = 0
    max_formula_error = 0.0
    endpoint_tolerance_hartree = (
        data_config.validation.duplicate_target_tolerance_kcal / HARTREE_TO_KCAL_MOL
    )
    for source_config, source in sources:
        mapping = data_config.label_columns.for_group(source_config.source_group)
        source_metadata = reader.metadata(source)
        metadata.append(source_metadata)
        rows = 0
        with reader.open_text(source) as stream:
            csv_reader = csv.DictReader(stream)
            fields = set(csv_reader.fieldnames or [])
            required = {
                mapping.inchikey,
                mapping.e_cation_hartree,
                mapping.e_neutral_hartree,
                mapping.stored_target,
            }
            missing = sorted(required - fields)
            if missing:
                raise LabelImportError(f"{source.source_id} is missing required columns: {missing}")
            for row_number, row in enumerate(csv_reader, start=2):
                rows += 1
                key = (row.get(mapping.inchikey) or "").strip()
                if not key:
                    raise LabelImportError(f"{source.source_id} row {row_number}: blank InChIKey")
                e_cation = _source_float(
                    row.get(mapping.e_cation_hartree),
                    field=mapping.e_cation_hartree,
                    source_id=source.source_id,
                    row_number=row_number,
                )
                e_neutral = _source_float(
                    row.get(mapping.e_neutral_hartree),
                    field=mapping.e_neutral_hartree,
                    source_id=source.source_id,
                    row_number=row_number,
                )
                stored_target = _source_float(
                    row.get(mapping.stored_target),
                    field=mapping.stored_target,
                    source_id=source.source_id,
                    row_number=row_number,
                )
                try:
                    formula = check_stored_label(
                        e_neutral_hartree=e_neutral,
                        e_cation_hartree=e_cation,
                        stored_target_kcal=stored_target,
                        tolerance_kcal=data_config.validation.formula_absolute_tolerance_kcal,
                    )
                except LabelFormulaMismatchError as exc:
                    raise LabelImportError(
                        f"{source.source_id} row {row_number} ({key}): {exc}"
                    ) from exc
                max_formula_error = max(max_formula_error, formula.absolute_error_kcal)
                membership_rows.append(
                    {
                        "inchikey": key,
                        "source_group": source_config.source_group,
                        "source_file": source.source_id,
                        "source_sha256": source_metadata.sha256,
                        "stored_target_kcal": stored_target,
                        "formula_absolute_error_kcal": formula.absolute_error_kcal,
                    }
                )
                normalized = {
                    "inchikey": key,
                    "e_cation_hartree": e_cation,
                    "e_neutral_hartree": e_neutral,
                    "electronic_difference_kcal": formula.electronic_difference_kcal,
                    "dft_deprot_electronic_kcal": formula.expected_target_kcal,
                    "formula_revalidated": True,
                    "method": data_config.protocol.method,
                    "basis": data_config.protocol.basis,
                    "dispersion": data_config.protocol.dispersion,
                    "geometry_optimizer": data_config.protocol.geometry_optimizer,
                    "cation_converged": data_config.label_defaults.cation_converged,
                    "neutral_converged": data_config.label_defaults.neutral_converged,
                    "hessian_computed": data_config.label_defaults.hessian_computed,
                    "n_imaginary": data_config.label_defaults.n_imaginary,
                    "label_quality": data_config.protocol.label_quality,
                    "label_protocol_id": protocol_hash,
                    "source_group": source_config.source_group,
                    "source_file": source.source_id,
                    "source_sha256": source_metadata.sha256,
                }
                existing = records.get(key)
                if existing is None:
                    records[key] = normalized
                    continue
                target_difference = abs(
                    float(existing["dft_deprot_electronic_kcal"]) - formula.expected_target_kcal
                )
                endpoint_difference = max(
                    abs(float(existing["e_cation_hartree"]) - e_cation),
                    abs(float(existing["e_neutral_hartree"]) - e_neutral),
                )
                if (
                    existing["label_protocol_id"] != protocol_hash
                    or target_difference > data_config.validation.duplicate_target_tolerance_kcal
                    or endpoint_difference > endpoint_tolerance_hartree
                ):
                    raise LabelImportError(
                        f"conflicting label for {key}: target_diff={target_difference:.6g} kcal, "
                        f"endpoint_diff={endpoint_difference:.6g} Hartree"
                    )
                consistent_duplicate_memberships += 1
        source_counts[source_config.source_group] = rows
    missing_candidates = sorted(set(records) - candidate_keys)
    if missing_candidates:
        raise LabelImportError(
            f"{len(missing_candidates)} label key(s) are absent from candidates; "
            f"example={missing_candidates[0]}"
        )
    frame = (
        pd.DataFrame.from_records(list(records.values()))
        .sort_values("inchikey")
        .reset_index(drop=True)
    )
    if frame.empty:
        raise LabelImportError("label inputs are empty")
    frame["n_imaginary"] = frame["n_imaginary"].astype("Int64")
    membership = pd.DataFrame.from_records(membership_rows).sort_values(
        ["inchikey", "source_group", "source_file"]
    )
    membership = membership.reset_index(drop=True)
    audit = {
        "source_rows": source_counts,
        "source_memberships": len(membership),
        "unique_labels": len(frame),
        "formula_checked": len(membership),
        "formula_failures": 0,
        "max_formula_absolute_error_kcal": max_formula_error,
        "consistent_duplicate_memberships": consistent_duplicate_memberships,
        "conflicts": 0,
        "protocol_ids": int(frame["label_protocol_id"].nunique()),
        "labels_missing_candidates": 0,
        "hessian_computed": int(frame["hessian_computed"].sum()),
        "missing_values": {column: int(frame[column].isna().sum()) for column in frame.columns},
    }
    return LabelImportResult(
        frame=frame,
        membership=membership,
        source_metadata=tuple(metadata),
        protocol=protocol,
        protocol_id=protocol_hash,
        audit=audit,
    )
