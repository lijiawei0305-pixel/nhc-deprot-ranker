# Phase 1 Test Report

Date: 2026-07-22
Environment: local macOS, Python 3.14.3
Project support floor: Python 3.11

## Results

| Gate | Result |
| --- | --- |
| pytest | 31 passed in 0.54 s |
| Ruff lint | All checks passed |
| Ruff format | 54 files already formatted |
| mypy | Success; 45 package/script source files checked |
| pre-commit | All six configured hooks passed |
| YAML/JSON/TOML parse | Passed |
| CLI discovery and Phase 1 dry-run | Passed; no output created |
| Wheel build | Passed: `nhc_deprot_ranker-0.1.0-py3-none-any.whl` |
| Wheel SHA256 | `49efe851c25c565977503457617811dd530f1b01713c31942f0f4ceb21014b27` |
| Ignored local config, prompt, and processed Parquet | Passed |
| Private path, fake-IP, private-key, password, and API-key pattern scan | No matches outside ignored inputs/runtime data |
| Git whitespace check | Passed |

The wheel was produced with `python -m pip wheel . --no-deps --wheel-dir dist`. The environment's `python -m build` entry point was unavailable, so it was not used for this gate.

## Synthetic Phase 1 behavior

- end-to-end CSV normalization to candidates/labels Parquet, source-membership CSV, manifests, quality report, and `_SUCCESS`;
- stable ascending target/key order, one-based rank, percentile direction, and exchange-invariant family construction;
- per-source parsed row counts and manifest/hash linkage;
- dry-run creates no output;
- existing dataset versions cannot be overwritten;
- candidate formula mismatch removes the temporary build and leaves no final version;
- missing fragment coverage is a hard failure;
- numerically consistent duplicate label memberships merge without losing provenance;
- conflicting duplicate labels are hard failures.

## Production readback

The ignored real `v001` artifacts were independently loaded after construction. The readback asserted:

- 401,856 unique, deterministically ranked candidates;
- 71 unique labels and 71 source memberships;
- all label keys are present among candidate keys;
- one protocol ID matching the protocol manifest;
- parsed source row counts `[401856, 36585, 365271, 24, 12, 35]`;
- exact SHA256 matches for all primary outputs and `_SUCCESS` links;
- all Phase 1 gate values pass;
- no private local absolute path appears in the source manifest.

All assertions passed.
