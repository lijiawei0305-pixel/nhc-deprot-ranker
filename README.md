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

Phase 0 through Phase 4 are complete. The immutable processed dataset `v001` passed with 401,856 candidates and 71 labels. Frozen B0/B1/H1 comparisons and paired OOF uncertainty produced the Phase 4 outcome `raw_xTB_wins`: B0 remains the production ranking default, B1 remains the absolute-calibration companion, and H1 is not promoted. No full-pool prediction or quantum-chemistry calculation has run. See [Phase Status](PHASE_STATUS.md), [Phase 4 Report](docs/PHASE4_REPORT.md), and [Model Card](docs/MODEL_CARD.md).

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

Remove `--dry-run` only after reviewing the source plan. Existing processed and result versions are never overwritten. Phase 5 commands remain unavailable and do not silently create outputs.

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

## Repository map

- `configs/`: portable specifications plus an ignored real-location file;
- `docs/`: science, data, family, model, validation, acquisition, audit, and reporting contracts;
- `src/nhc_deprot_ranker/`: audit, import, baseline, hierarchical-model, validation, and reporting code;
- `scripts/`: direct audit and label-formula entry points;
- `tests/`: synthetic, HPC-independent tests for Phases 0–4;
- `data/`, `models/`, `results/`: ignored runtime roots with tracked placeholders.

## License

MIT. See [LICENSE](LICENSE).
