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

Phase 0/1/2/3/4/5/6 utilities use no quantum-chemistry package. Phase 1 uses pandas and PyArrow for normalized Parquet output; Phases 2–5 add SciPy statistics, joblib serialization, scikit-learn-compatible estimators, paired/parameter-bootstrap uncertainty, and headless Matplotlib reports. Phase 6 only validates and partitions the frozen acquisition into text planning artifacts.

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

PYTHONPATH=src python -m nhc_deprot_ranker.cli score \
  --dataset data/processed/v001 \
  --baseline-results results/baselines_v001 \
  --decision-results results/decision_v001 \
  --acquisition-config configs/acquisition.yaml \
  --dataset-evidence docs/PROCESSED_V001_MANIFEST.json \
  --baseline-evidence docs/BASELINES_V001_MANIFEST.json \
  --decision-evidence docs/DECISION_V001_MANIFEST.json \
  --out results/scoring_v001 \
  --seed 20260722 \
  --dry-run

PYTHONPATH=src python -m nhc_deprot_ranker.cli score \
  --dataset data/processed/v001 \
  --baseline-results results/baselines_v001 \
  --decision-results results/decision_v001 \
  --acquisition-config configs/acquisition.yaml \
  --dataset-evidence docs/PROCESSED_V001_MANIFEST.json \
  --baseline-evidence docs/BASELINES_V001_MANIFEST.json \
  --decision-evidence docs/DECISION_V001_MANIFEST.json \
  --out results/scoring_v001 \
  --seed 20260722

PYTHONPATH=src python -m nhc_deprot_ranker.cli acquire \
  --dataset data/processed/v001 \
  --scored-results results/scoring_v001 \
  --acquisition-config configs/acquisition.yaml \
  --dataset-evidence docs/PROCESSED_V001_MANIFEST.json \
  --out results/acquisition_v001 \
  --seed 20260722 \
  --dry-run

PYTHONPATH=src python -m nhc_deprot_ranker.cli acquire \
  --dataset data/processed/v001 \
  --scored-results results/scoring_v001 \
  --acquisition-config configs/acquisition.yaml \
  --dataset-evidence docs/PROCESSED_V001_MANIFEST.json \
  --out results/acquisition_v001 \
  --seed 20260722

PYTHONPATH=src python -m nhc_deprot_ranker.cli prepare-dft-plan \
  --dataset data/processed/v001 \
  --acquisition-results results/acquisition_v001 \
  --plan-config configs/dft_plan.yaml \
  --dataset-evidence docs/PROCESSED_V001_MANIFEST.json \
  --acquisition-evidence docs/ACQUISITION_V001_MANIFEST.json \
  --out results/dft_input_plan_v001 \
  --seed 20260722 \
  --dry-run

PYTHONPATH=src python -m nhc_deprot_ranker.cli prepare-dft-plan \
  --dataset data/processed/v001 \
  --acquisition-results results/acquisition_v001 \
  --plan-config configs/dft_plan.yaml \
  --dataset-evidence docs/PROCESSED_V001_MANIFEST.json \
  --acquisition-evidence docs/ACQUISITION_V001_MANIFEST.json \
  --out results/dft_input_plan_v001 \
  --seed 20260722
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
- Phase 5 applies frozen B1 coefficient replicates in bounded 4,096-row chunks and validates every slope as positive before deterministic Top-K membership is emitted.
- Phase 5 acquisition rounds quotas by largest remainder in configuration order, selects without replacement, and breaks ties by score, B0 rank, and InChIKey.
- Score and acquisition outputs are built in sibling temporary directories and atomically published; existing result versions are rejected.
- Phase 6 verifies the external evidence, runtime-manifest hashes, `_SUCCESS` pointers, versions, protocol, key order, SMILES, and label exclusion before both dry-run and real output.
- Phase 6 assigns fixed per-bucket slices to the exact registered 5×10 matrix; its smoke subset is the first assigned batch-01 row from each bucket.
- The local DFT plan uses an exact text-file/directory allowlist, is atomically published, cannot be overwritten, and records unresolved geometry/runner blockers instead of inferring execution readiness.

## Phase 1 evidence

The large processed and runtime result artifacts are intentionally ignored. Phase 1 evidence is recorded in `PROCESSED_V001_MANIFEST.json`; B0/B1 evidence in `BASELINES_V001_MANIFEST.json`; H1 evidence in `HIERARCHICAL_V001_MANIFEST.json`; the final `raw_xTB_wins` decision in `DECISION_V001_MANIFEST.json`; full scoring in `SCORING_V001_MANIFEST.json`; local acquisition in `ACQUISITION_V001_MANIFEST.json`; and the non-executable DFT handoff plan in `DFT_INPUT_PLAN_V001_MANIFEST.json`.
