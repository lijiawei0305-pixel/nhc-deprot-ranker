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

Only Phase 0 is in scope. The legacy repository has been audited read-only; no new model has been trained and no full-pool scoring or quantum-chemistry calculation has run. See [Phase Status](PHASE_STATUS.md) and [Legacy Audit](docs/LEGACY_AUDIT.md).

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

Phase 0 CLI discovery:

```bash
nhc-deprot --help
nhc-deprot audit-legacy --config configs/legacy.local.yaml --dry-run
nhc-deprot validate-labels --help
```

Commands for later phases report that their phase is not implemented; they do not silently create outputs.

## Repository map

- `configs/`: portable specifications plus an ignored real-location file;
- `docs/`: science, data, family, model, validation, acquisition, audit, and reporting contracts;
- `src/nhc_deprot_ranker/`: package skeleton and Phase 0 audit utilities;
- `scripts/`: direct audit and label-formula entry points;
- `tests/`: synthetic, HPC-independent Phase 0 tests;
- `data/`, `models/`, `results/`: ignored runtime roots with tracked placeholders.

## License

MIT. See [LICENSE](LICENSE).
