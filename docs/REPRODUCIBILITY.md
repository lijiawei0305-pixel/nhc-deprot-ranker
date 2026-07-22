# Reproducibility

## Source identity

- Legacy source code: branch/HEAD and dirty-state declaration in `LEGACY_SOURCE_MANIFEST.json`.
- HPC-only data: logical `<HPC_PROJECT_ROOT>`-relative path plus SHA256; the deployment is not a Git checkout.
- Real roots and SSH alias: ignored `configs/legacy.local.yaml` only.
- No large legacy input is copied into this repository.

## Local environment used for Phase 0/1 checks

- Python 3.14.3; project support floor is Python 3.11.
- Pydantic 2.12.5, PyYAML 6.0.3, pytest 9.0.3.
- The legacy declared molecular environment uses Python 3.11.

Phase 0/1/2/3/4 utilities use no quantum-chemistry package. Phase 1 uses pandas and PyArrow for normalized Parquet output; Phases 2–4 add SciPy statistics, joblib serialization, scikit-learn-compatible estimators, paired OOF uncertainty, and headless Matplotlib reports.

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

PYTHONPATH=src python -m nhc_deprot_ranker.cli build-dataset \
  --legacy-config configs/legacy.local.yaml \
  --data-config configs/data.yaml \
  --families-config configs/families.yaml \
  --out data/processed/v001 \
  --dry-run

PYTHONPATH=src python -m nhc_deprot_ranker.cli build-dataset \
  --legacy-config configs/legacy.local.yaml \
  --data-config configs/data.yaml \
  --families-config configs/families.yaml \
  --out data/processed/v001

PYTHONPATH=src python -m nhc_deprot_ranker.cli train \
  --dataset data/processed/v001 \
  --model-config configs/baselines.yaml \
  --evaluation-config configs/evaluation.yaml \
  --out results/baselines_v001 \
  --dry-run

PYTHONPATH=src python -m nhc_deprot_ranker.cli train \
  --dataset data/processed/v001 \
  --model-config configs/baselines.yaml \
  --evaluation-config configs/evaluation.yaml \
  --out results/baselines_v001

PYTHONPATH=src python -m nhc_deprot_ranker.cli train \
  --dataset data/processed/v001 \
  --baseline-results results/baselines_v001 \
  --model-config configs/model.yaml \
  --evaluation-config configs/evaluation.yaml \
  --out results/hierarchical_v001 \
  --dry-run

PYTHONPATH=src python -m nhc_deprot_ranker.cli train \
  --dataset data/processed/v001 \
  --baseline-results results/baselines_v001 \
  --model-config configs/model.yaml \
  --evaluation-config configs/evaluation.yaml \
  --out results/hierarchical_v001

PYTHONPATH=src python -m nhc_deprot_ranker.cli evaluate \
  --dataset data/processed/v001 \
  --baseline-results results/baselines_v001 \
  --hierarchical-results results/hierarchical_v001 \
  --evaluation-config configs/evaluation.yaml \
  --out results/decision_v001 \
  --dry-run

PYTHONPATH=src python -m nhc_deprot_ranker.cli evaluate \
  --dataset data/processed/v001 \
  --baseline-results results/baselines_v001 \
  --hierarchical-results results/hierarchical_v001 \
  --evaluation-config configs/evaluation.yaml \
  --out results/decision_v001
```

The approved server audit used direct, read-only SSH and an stdin-fed standard-library Python scanner. It printed only aggregate metadata and hashes. The exact allowed/prohibited operation classes and completion record are in `SERVER_READONLY_PLAN.md`.

## Determinism

- Default seed: `20260722`.
- SHA256 reads exact file bytes in fixed-size blocks.
- Protocol IDs use sorted canonical JSON with NaN prohibited.
- Family pairs use deterministic normalized sorting.
- Dry-run commands do not create explicit outputs.
- Candidate rows use stable `(xtb_deprot_kcal, inchikey)` ascending order.
- A processed version is built in a sibling temporary directory and atomically published only after manifests and hashes succeed.
- Existing versions are immutable; a rebuild after source/config changes requires a new dataset version.
- Phase 3 inner folds use deterministic key/group hashing and support-balanced group assignment.
- Phase 3 bootstrap fixes the all-data nested-CV penalties and refits scaling, vocabularies, and coefficients for each paired InChIKey resample.
- Phase 4 bootstrap resamples aligned frozen OOF truth/B0/B1/H1 rows together and never refits a model or retunes a penalty.

## Phase 1 evidence

The large processed, baseline-result, hierarchical-result, and decision-result artifacts are intentionally ignored. Phase 1 evidence is recorded in `PROCESSED_V001_MANIFEST.json`; B0/B1 evidence in `BASELINES_V001_MANIFEST.json`; H1 evidence in `HIERARCHICAL_V001_MANIFEST.json`; and the final `raw_xTB_wins` decision in `DECISION_V001_MANIFEST.json`. Full-pool prediction hashes remain unavailable because Phase 5 has not started.
