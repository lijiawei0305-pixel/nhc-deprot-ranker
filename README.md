# nhc-deprot-ranker

Independent, provenance-first ranking calibration for gas-phase NHC precursor deprotonation electronic energies.

The project combines a complete GFN2-xTB candidate ranking with a small set of B3LYP-D3(BJ)/def2-SVP electronic-energy labels. Future phases will compare raw xTB, a free-slope global affine calibration, and a partially pooled additive family calibration. A more complex model is promoted only when honest ranking validation supports it.

## Scientific boundary

The reaction is `NHC-H+ -> NHC + H+`. The compatibility target is

```text
(E_neutral - E_cation) * 627.509474 - 6.28 kcal/mol
```

It is an electronic-energy label, not a complete Gibbs free energy. Lower is better. Skipped Hessians do not invalidate the electronic label and do not establish frequency-confirmed minima. See [Science Scope](docs/SCIENCE_SCOPE.md).

## Current status

Phase 0 and Phase 1 are complete. The legacy repository and HPC-only tables were read and audited without modification, and the immutable processed dataset `v001` has passed its production gate with 401,856 candidates and 71 high-fidelity labels. No model has been trained, no full-pool prediction has run, and no quantum-chemistry calculation has been submitted. See [Phase Status](PHASE_STATUS.md), [Phase 1 Report](docs/PHASE1_REPORT.md), and [Legacy Audit](docs/LEGACY_AUDIT.md).

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

Remove `--dry-run` only after reviewing the source plan. Existing processed versions are never overwritten. Commands for later phases report that their phase is not implemented; they do not silently create outputs.

## Repository map

- `configs/`: portable specifications plus an ignored real-location file;
- `docs/`: science, data, family, model, validation, acquisition, audit, and reporting contracts;
- `src/nhc_deprot_ranker/`: audit utilities and the Phase 1 streaming importer;
- `scripts/`: direct audit and label-formula entry points;
- `tests/`: synthetic, HPC-independent Phase 0/1 tests;
- `data/`, `models/`, `results/`: ignored runtime roots with tracked placeholders.

## License

MIT. See [LICENSE](LICENSE).
