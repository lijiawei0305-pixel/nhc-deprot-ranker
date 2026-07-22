# Reproducibility

## Source identity

- Legacy source code: branch/HEAD and dirty-state declaration in `LEGACY_SOURCE_MANIFEST.json`.
- HPC-only data: logical `<HPC_PROJECT_ROOT>`-relative path plus SHA256; the deployment is not a Git checkout.
- Real roots and SSH alias: ignored `configs/legacy.local.yaml` only.
- No large legacy input is copied into this repository.

## Local environment used for Phase 0 checks

- Python 3.14.3; project support floor is Python 3.11.
- Pydantic 2.12.5, PyYAML 6.0.3, pytest 9.0.3.
- The legacy declared molecular environment uses Python 3.11.

Phase 0 utilities use no quantum-chemistry package.

## Commands

```bash
PYTHONPATH=src python -m pytest
ruff check .
ruff format --check .
mypy src scripts

PYTHONPATH=src python -m nhc_deprot_ranker.cli \
  audit-legacy --config configs/legacy.local.yaml --dry-run

PYTHONPATH=src python scripts/verify_label_formula.py \
  --input <LEGACY_LOCAL_ROOT>/reports/part1-blind-round2-2026-07-09/deltaE_final.csv \
  --target-column dft_deprot_kcal --dry-run
```

The approved server audit used direct, read-only SSH and an stdin-fed standard-library Python scanner. It printed only aggregate metadata and hashes. The exact allowed/prohibited operation classes and completion record are in `SERVER_READONLY_PLAN.md`.

## Determinism

- Default seed: `20260722`.
- SHA256 reads exact file bytes in fixed-size blocks.
- Protocol IDs use sorted canonical JSON with NaN prohibited.
- Family pairs use deterministic normalized sorting.
- Dry-run commands do not create explicit outputs.

## Remaining reproducibility work

Phase 1 will create an immutable processed dataset manifest and checked-in audit command output schema. Model/data manifests and prediction hashes are unavailable because no model or processed production dataset exists yet.
