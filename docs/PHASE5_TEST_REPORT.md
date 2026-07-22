# Phase 5 Test Report

Date: 2026-07-22
Environment: local macOS, Python 3.14.3
Project support floor: Python 3.11

## Automated result

| Gate | Result |
| --- | --- |
| pytest | 87 passed |
| Ruff lint/format | Passed; 74 files formatted before final documentation additions |
| strict mypy | Passed; 50 package source files checked |
| pre-commit | Passed all configured hooks |
| Wheel build | Passed: `nhc_deprot_ranker-0.1.0-py3-none-any.whl` |
| Wheel SHA256 | `2db79cc89ff4367494963919cf712a257ac33cadd0a23e3553c52524c3082fdb` |
| Installed-wheel CLI smoke | Passed in a fresh venv; score/acquire dry-runs wrote nothing |
| CLI dry-run | Passed; score/acquire non-writing and no HPC/quantum action |
| Synthetic full runner | 120 scored, Top-100, 50 acquired, eight figures |
| Real scoring | 401,856 rows/keys; exact B0 ranks; Top-100 verified |
| Real acquisition | 50 unique; 71 labels excluded; quotas 15/13/12/10 |
| Output hash readback | All 18 runtime files matched checked-in evidence |
| Visual QA | Eight figures inspected; post-fix footers fully visible |
| External action | None; `submit_hpc=false` and server write unauthorized |

## Behavior covered

- typed Phase 5 policy, quota-sum and Top-K validation;
- chunked affine coefficient-bootstrap summaries versus an unbounded reference;
- rejection of nonpositive bootstrap slopes;
- exact positive-affine rank preservation and deterministic Top-10/50/100 membership;
- baseline range, family support, sparse family, uncertainty, and explicit size-unavailable flags;
- no false fully in-domain status when validated size is absent;
- bounded acquisition components and zero rank-shift contribution;
- deterministic largest-remainder quotas, stable tie-breaking, and greedy family/fragment diversity;
- exclusion of labeled keys, uniqueness, exact batch size, and reason codes;
- registered input/output hashes, atomic writes, immutable output rejection, and dry-run non-writing;
- local high-fidelity interoperability manifest with no HPC or server authorization.

## Real-result audit

The independent audit loaded the complete Parquet result, not a sample. It verified 401,856 sequential production ranks, equality of production/calibrated ranks, zero nonzero rank shifts, exact Top-K probability columns, 100 Top rows identical to the full-table prefix, 100% explicit size-unavailable coverage, and all seven pre-manifest scoring hashes.

The acquisition audit verified 50/50 unique selected keys, zero overlap with 71 labels, exact bucket counts, zero quota fill, 46 combined families, all seven pre-manifest acquisition hashes, and false values for both HPC submission and server-write authorization.

## Test boundary

CI remains independent of production Parquet data, PySCF, xTB, and HPC. Real-data execution was a local release gate only. No test attempts to validate DFT accuracy, Gibbs free energy, synthetic feasibility, Hessian minima, or scheduler interoperability.
