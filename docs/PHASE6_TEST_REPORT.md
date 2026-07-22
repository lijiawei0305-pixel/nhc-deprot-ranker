# Phase 6 Test Report

Date: 2026-07-22
Environment: local macOS, Python 3.14.3
Project support floor: Python 3.11

## Automated result

| Gate | Result |
| --- | --- |
| pytest | 106 passed |
| Ruff lint | Passed |
| Ruff format | Passed; 77 files already formatted |
| strict mypy | Passed; 54 source/script files checked |
| pre-commit | Passed all configured hooks |
| Wheel build | Passed with PEP 517 `pip wheel --no-build-isolation` |
| Wheel SHA256 | `1f570d5c7aff00e1173d24ffb53d9ececc6236401a9f1856c96e950b75d4fafe` |
| Installed-wheel CLI smoke | Passed in a fresh system-site-packages venv |
| Installed-wheel Phase 6 dry-run | Validated real inputs and wrote no result |
| Real dry-run | 50 candidates, 71 labels, zero overlap, no output |
| Real local plan | 50 unique, 5×10, smoke 4, `local_plan_passed` |
| Output hash readback | 15/15 checked-in outputs matched |
| Package hash readback | 13/13 outputs and 18/18 inputs matched |
| Filesystem safety | 0 extras, symlinks, executables, private paths, or actual chemistry artifacts |
| External action | None |

The local environment does not expose the third-party `build` module as `python -m build`; that attempted command stopped after all code/test gates had already passed. The equivalent PEP 517 wheel build succeeded with the installed setuptools backend, and the resulting wheel passed clean-install CLI and real-input dry-run checks.

## Behavior covered

- strict Phase 6 literals, protocol constants, exact batch IDs, exact 5×10 matrix, and `15/13/12/10` totals;
- deterministic full plan, exact per-batch crosstab, four-row batch-01 smoke subset, uniqueness, and full partition;
- external evidence hashes, runtime-manifest hashes, `_SUCCESS` manifest/candidate pointers, version identity, and required upstream registration;
- dry-run full input validation plus zero writes, including missing-evidence rejection;
- rejection of outer evidence tampering, signed bad success pointers, signed bad runtime output hashes, traversal, absolute registered paths, and registered symlinks;
- strict canonical InChIKeys, label exclusion, nonblank endpoint SMILES/text fields, finite scores, and positive integer ranks;
- controlled `DFTPlanError` for non-object and missing-field handoff records;
- atomic temporary-output cleanup after a synthetic write failure and immutable output rejection;
- exact legacy M2 column names, full/batch/smoke screen membership, relative future-path inventory, and no generated geometry;
- exact file/directory allowlist plus direct negative tests for extra directories, output symlinks, executable bits, and private absolute paths;
- top-level no-action/Hessian/blocker fields, package hashes, source-tree hash, and success marker.

## Real-result audit

Two independent readbacks loaded the complete result rather than samples. They verified 50 unique candidates, zero overlap with 71 labels, exact Phase 5 endpoint SMILES, five ten-row batches, the 3/3/2/2 and 3/2/3/2 per-batch matrices, total quotas, four-bucket smoke identity, screen order, relative expected outputs, and all manifest flags.

The audited tree contains exactly 15 files and six directories. It has no symlink, executable bit, private absolute path, actual XYZ/Molden/`freq.json`, binary quantum result, upload command, server destination, or job script. All future artifact paths listed in `expected_outputs.csv` are relative and absent.

Four `acquisition_score` values changed only at CSV decimal serialization precision; the maximum parsed absolute difference was `4.44e-16`. Keys, SMILES, remaining provenance, ordering, quotas, and batch assignment are exact and unchanged.

## Test boundary

The automated suite uses synthetic Parquet/CSV/JSON fixtures and does not depend on ignored production data, RDKit, PySCF, xTB, an SSH session, or HPC. The real-data dry-run/output audit was a separate local release gate. No test validates DFT accuracy, Gibbs free energy, frequency minima, synthetic feasibility, server capacity, or scheduler compatibility.
