# nhc-deprot-ranker

Independent, provenance-first ranking calibration for gas-phase NHC precursor deprotonation electronic energies.

The project combines a complete GFN2-xTB candidate ranking with a small set of B3LYP-D3(BJ)/def2-SVP electronic-energy labels. It compares raw xTB, a free-slope global affine calibration, and a partially pooled additive family calibration. A more complex model is promoted only when honest ranking validation supports it.

## Scientific boundary

The reaction is `NHC-H+ -> NHC + H+`. The compatibility target is

```text
(E_neutral - E_cation) * 627.509474 - 6.28 kcal/mol
```

It is an electronic-energy label, not a complete Gibbs free energy. Lower is better. Skipped Hessians do not invalidate the electronic label and do not establish frequency-confirmed minima. See [Science Scope](docs/SCIENCE_SCOPE.md).

## Current status

Phase 0 through Phase 8A are complete. The immutable processed dataset `v001`
contains 401,856 candidates and 71 labels. Phase 4 selected `raw_xTB_wins`: B0
is the production ranking, B1 is only the absolute-calibration and parameter-
uncertainty companion, and H1 is not promoted. Phase 7 produced validated
initial cation/neutral geometries for four frozen smoke candidates, and Phase
8A established the hard process-tree timeout and read-only server API contract.

The only authorized Phase 8B QXH DFT smoke attempt was consumed and rejected
at the execution-protocol layer. It produced no acceptable endpoint energy,
dynamic D3 evidence, or deprotonation label and must not be retried. The source
execution gate remains closed. See [Phase Status](PHASE_STATUS.md), the
[Phase 8B Report](docs/PHASE8B_REPORT.md), and the [Model Card](docs/MODEL_CARD.md).

## Source policy

- Legacy code/data are read only.
- Real source locations live in ignored `configs/legacy.local.yaml`.
- No legacy large data file is committed or copied into this repository.
- Server-only inputs are pinned by path and SHA256 because the server deployment is not a Git checkout.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check .
mypy src scripts
```

Phase 1 dataset build:

```bash
nhc-deprot --help
nhc-deprot audit-legacy --config configs/legacy.local.yaml --dry-run
nhc-deprot build-dataset \
  --legacy-config configs/legacy.local.yaml \
  --data-config configs/data.yaml \
  --families-config configs/families.yaml \
  --out data/processed/v001 \
  --dry-run
```

Remove `--dry-run` only after reviewing the source plan. Existing processed and result versions are never overwritten.

Phase 2 baseline dry-run:

```bash
nhc-deprot train \
  --dataset data/processed/v001 \
  --model-config configs/baselines.yaml \
  --evaluation-config configs/evaluation.yaml \
  --out results/baselines_v001 \
  --dry-run
```

Phase 3 hierarchical dry-run:

```bash
nhc-deprot train \
  --dataset data/processed/v001 \
  --baseline-results results/baselines_v001 \
  --model-config configs/model.yaml \
  --evaluation-config configs/evaluation.yaml \
  --out results/hierarchical_v001 \
  --dry-run
```

Phase 4 decision dry-run:

```bash
nhc-deprot evaluate \
  --dataset data/processed/v001 \
  --baseline-results results/baselines_v001 \
  --hierarchical-results results/hierarchical_v001 \
  --evaluation-config configs/evaluation.yaml \
  --out results/decision_v001 \
  --dry-run
```

Phase 5 full-score and local acquisition dry-runs:

```bash
nhc-deprot score \
  --dataset data/processed/v001 \
  --baseline-results results/baselines_v001 \
  --decision-results results/decision_v001 \
  --acquisition-config configs/acquisition.yaml \
  --out results/scoring_v001 \
  --dry-run

nhc-deprot acquire \
  --dataset data/processed/v001 \
  --scored-results results/scoring_v001 \
  --acquisition-config configs/acquisition.yaml \
  --out results/acquisition_v001 \
  --dry-run
```

The acquisition command only writes a local suggestion manifest. It never connects to a server or submits a calculation.

Phase 6 local DFT-plan dry-run:

```bash
nhc-deprot prepare-dft-plan \
  --dataset data/processed/v001 \
  --acquisition-results results/acquisition_v001 \
  --plan-config configs/dft_plan.yaml \
  --dataset-evidence docs/PROCESSED_V001_MANIFEST.json \
  --acquisition-evidence docs/ACQUISITION_V001_MANIFEST.json \
  --out results/dft_input_plan_v001 \
  --seed 20260722 \
  --dry-run
```

This command validates every registered input before returning. Removing `--dry-run` creates only the immutable local plan; it does not generate XYZ files, run DFT, connect to HPC, transfer files, or submit jobs.

## Repository map

- `configs/`: portable specifications plus an ignored real-location file;
- `docs/`: science, data, family, model, validation, acquisition, audit, and reporting contracts;
- `src/nhc_deprot_ranker/`: audit, import, modeling, validation, full scoring, acquisition, and local preparation code;
- `scripts/`: direct audit and label-formula entry points;
- `tests/`: synthetic, HPC-independent tests for Phases 0–6;
- `data/`, `models/`, `results/`: ignored runtime roots with tracked placeholders.

## License

MIT. See [LICENSE](LICENSE).
