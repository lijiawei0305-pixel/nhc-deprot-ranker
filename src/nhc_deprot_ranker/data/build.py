"""Atomic Phase 1 construction of immutable processed dataset versions."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nhc_deprot_ranker.config import (
    load_data_config,
    load_families_config,
    load_legacy_config,
)
from nhc_deprot_ranker.constants import GAS_PROTON_KCAL_MOL, HARTREE_TO_KCAL_MOL
from nhc_deprot_ranker.data.candidates import import_candidates, import_fragment_lookup
from nhc_deprot_ranker.data.labels import import_high_fidelity_labels
from nhc_deprot_ranker.data.provenance import sha256_file
from nhc_deprot_ranker.legacy.paths import resolve_source
from nhc_deprot_ranker.legacy.source_io import SourceReader


class ImmutableDatasetError(ValueError):
    """An immutable version would be overwritten or mislabeled."""


@dataclass(frozen=True)
class BuildDatasetResult:
    """Build status returned to the CLI."""

    payload: dict[str, Any]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _config_hashes(paths: tuple[Path, Path, Path]) -> dict[str, str]:
    roles = ("legacy_config", "data_config", "families_config")
    return {role: sha256_file(path) for role, path in zip(roles, paths, strict=True)}


def build_dataset(
    *,
    legacy_config_path: Path,
    data_config_path: Path,
    families_config_path: Path,
    output_dir: Path,
    dry_run: bool = False,
    overwrite: bool = False,
) -> BuildDatasetResult:
    """Build one immutable processed dataset from local/SSH read-only sources."""

    legacy_config = load_legacy_config(legacy_config_path)
    data_config = load_data_config(data_config_path)
    families_config = load_families_config(families_config_path)
    if output_dir.name != data_config.dataset_version:
        raise ImmutableDatasetError(
            f"output directory name {output_dir.name!r} must equal dataset_version "
            f"{data_config.dataset_version!r}"
        )
    if output_dir.exists():
        raise ImmutableDatasetError(f"immutable dataset version already exists: {output_dir}")
    if overwrite:
        raise ImmutableDatasetError(
            "--overwrite cannot replace an immutable processed dataset; "
            "choose a new dataset_version"
        )
    if data_config.protocol.proton_constant_kcal != GAS_PROTON_KCAL_MOL:
        raise ValueError(
            "protocol proton constant does not match locked project constant: "
            f"{data_config.protocol.proton_constant_kcal} != {GAS_PROTON_KCAL_MOL}"
        )
    if families_config.exact_combined_family.enabled:
        raise ValueError("Phase 1 requires exact_combined_family.enabled=false")

    candidate_source = resolve_source(legacy_config, legacy_config.candidates.xtb_crude_csv)
    v3_source = resolve_source(legacy_config, legacy_config.candidates.v3_graph_csv)
    v4_source = resolve_source(legacy_config, legacy_config.candidates.v4_new_only_csv)
    label_sources = tuple(
        (source, resolve_source(legacy_config, source)) for source in legacy_config.labels.sources
    )
    plan = {
        "command": "build-dataset",
        "dataset_version": data_config.dataset_version,
        "output_dir": str(output_dir),
        "dry_run": dry_run,
        "read_only_sources": [
            candidate_source.source_id,
            v3_source.source_id,
            v4_source.source_id,
            *(resolved.source_id for _, resolved in label_sources),
        ],
        "remote_writes": False,
        "raw_sources_persisted": False,
    }
    if dry_run:
        return BuildDatasetResult(payload=plan)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(
        tempfile.mkdtemp(prefix=f".{data_config.dataset_version}.tmp.", dir=output_dir.parent)
    )
    try:
        reader = SourceReader()
        fragments = import_fragment_lookup(
            reader=reader,
            sources=(v3_source, v4_source),
            columns=data_config.candidate_columns,
        )
        candidates = import_candidates(
            reader=reader,
            source=candidate_source,
            fragments=fragments,
            columns=data_config.candidate_columns,
            families=families_config,
            formula_tolerance_kcal=data_config.validation.formula_absolute_tolerance_kcal,
        )
        labels = import_high_fidelity_labels(
            reader=reader,
            sources=label_sources,
            data_config=data_config,
            candidate_keys=set(candidates.frame["inchikey"]),
        )

        candidates_path = temporary_dir / "candidates.parquet"
        labels_path = temporary_dir / "labels.parquet"
        membership_path = temporary_dir / "label_source_membership.csv"
        protocol_path = temporary_dir / "protocol_manifest.json"
        source_manifest_path = temporary_dir / "source_manifest.json"
        quality_path = temporary_dir / "data_quality.json"

        candidates.frame.to_parquet(candidates_path, index=False, compression="zstd")
        labels.frame.to_parquet(labels_path, index=False, compression="zstd")
        labels.membership.to_csv(membership_path, index=False)
        _write_json(
            protocol_path,
            {
                "label_protocol_id": labels.protocol_id,
                "protocol": labels.protocol,
                "hartree_to_kcal_mol": HARTREE_TO_KCAL_MOL,
                "lower_is_better": True,
            },
        )

        source_records = [
            {
                "role": "xtb_full_candidates",
                "parsed_rows": candidates.audit["rows"],
                **candidates.source_metadata.to_dict(),
            },
            {
                "role": "fragment_lookup_v3",
                "parsed_rows": fragments.audit["source_rows"][
                    fragments.source_metadata[0].source_id
                ],
                **fragments.source_metadata[0].to_dict(),
            },
            {
                "role": "fragment_lookup_v4_new",
                "parsed_rows": fragments.audit["source_rows"][
                    fragments.source_metadata[1].source_id
                ],
                **fragments.source_metadata[1].to_dict(),
            },
        ]
        source_records.extend(
            {
                "role": f"labels_{source_config.source_group}",
                "parsed_rows": labels.audit["source_rows"][source_config.source_group],
                **source_metadata.to_dict(),
            }
            for (source_config, _), source_metadata in zip(
                label_sources, labels.source_metadata, strict=True
            )
        )
        _write_json(
            source_manifest_path,
            {
                "dataset_version": data_config.dataset_version,
                "legacy_expected_commit": legacy_config.legacy_repo.expected_commit,
                "legacy_expected_remote": legacy_config.legacy_repo.expected_remote,
                "config_sha256": _config_hashes(
                    (legacy_config_path, data_config_path, families_config_path)
                ),
                "sources": source_records,
            },
        )

        primary_output_hashes = {
            path.name: sha256_file(path)
            for path in (
                candidates_path,
                labels_path,
                membership_path,
                protocol_path,
                source_manifest_path,
            )
        }
        quality = {
            "dataset_version": data_config.dataset_version,
            "candidate_audit": candidates.audit,
            "fragment_audit": fragments.audit,
            "label_audit": labels.audit,
            "candidate_columns": list(candidates.frame.columns),
            "label_columns": list(labels.frame.columns),
            "output_sha256": primary_output_hashes,
            "phase1_gate": {
                "primary_key_unique": bool(
                    candidates.audit["rows"] == candidates.audit["unique_inchikeys"]
                ),
                "formula_failures": int(
                    candidates.audit["formula_failures"] + labels.audit["formula_failures"]
                ),
                "fragment_coverage_fraction": candidates.audit["fragment_coverage_fraction"],
                "label_conflicts": labels.audit["conflicts"],
                "protocol_ids": labels.audit["protocol_ids"],
                "labels_missing_candidates": labels.audit["labels_missing_candidates"],
            },
        }
        _write_json(quality_path, quality)
        completion = {
            "dataset_version": data_config.dataset_version,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "rows": {"candidates": len(candidates.frame), "labels": len(labels.frame)},
            "manifest_sha256": sha256_file(source_manifest_path),
            "quality_sha256": sha256_file(quality_path),
            "protocol_sha256": sha256_file(protocol_path),
        }
        _write_json(temporary_dir / "_SUCCESS", completion)
        os.replace(temporary_dir, output_dir)
    except BaseException:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise
    return BuildDatasetResult(
        payload={
            **plan,
            "dry_run": False,
            "status": "complete",
            "candidate_rows": int(candidates.audit["rows"]),
            "label_rows": int(labels.audit["unique_labels"]),
            "output_files": sorted(path.name for path in output_dir.iterdir()),
        }
    )
