# Phase 1 Data Import Report

## Outcome

Phase 1 passed on 2026-07-22. The importer built the immutable local dataset `data/processed/v001` from six audited, read-only sources. HPC files were streamed through non-interactive SSH; no source file was copied into the repository and no server write or compute command was issued.

The checked-in evidence snapshot is `PROCESSED_V001_MANIFEST.json`. The full Parquet/CSV/JSON output remains under the ignored runtime `data/` tree.

## Production result

| Check | Result |
| --- | ---: |
| Candidate rows / unique InChIKeys | 401,856 / 401,856 |
| Candidate duplicates | 0 |
| xTB endpoint formula checks / failures | 401,856 / 0 |
| Maximum xTB formula error | `1.4211e-14 kcal/mol` |
| xTB target range | `44.0024` to `124.6857 kcal/mol` |
| Fragment coverage | 401,856 / 401,856 (100%) |
| Axis A / Axis B families | 528 / 406 |
| Combined families | 214,368 |
| Unique labels / source memberships | 71 / 71 |
| Label formula checks / failures | 71 / 0 |
| Maximum label formula error | `0.0002476 kcal/mol` |
| Label conflicts / missing candidate keys | 0 / 0 |
| Label protocol IDs | 1 |

The label composition is gold 24, blind round 1 12, and blind round 2 35. All label endpoints are present and marked converged. Hessians were not computed, so all 71 `n_imaginary` values are deliberately null and the quality remains `electronic_energy_only`.

The optional candidate fields `n_heavy_atoms` and `n_electrons` are deliberately null for all rows because Phase 1 does not infer them from unvalidated shortcuts. Every required candidate and label field has zero missing values.

## Protocol lock

The only label protocol ID is:

```text
2d03e2dc62c94cbf2bb6aaa1a40b842bb1369427c9df10b742441ef7227850fd
```

It represents B3LYP-D3(BJ)/def2-SVP electronic deprotonation energies, geomeTRIC geometries, singlet cation/neutral endpoints with charges +1/0, and the locked `-6.28 kcal/mol` proton constant. Lower values are better.

## Import guarantees exercised

- Local and SSH sources expose only logical identifiers in output manifests; no user absolute path is present.
- Each exact source has SHA256, byte size, transport, role, and parsed row count.
- Candidate keys are unique and the v3/v4 fragment lookup is an exact, disjoint, bidirectional cover.
- Every stored candidate and label target is recomputed from endpoint Hartree energies.
- Family pairs are exchange invariant, and ranks have deterministic target/key tie breaking.
- Consistent duplicate labels are supported with source-membership preservation; conflicting labels are hard failures. The production inputs contained no overlaps.
- Output is written to a sibling temporary directory and atomically renamed only after all artifacts and manifests succeed.
- An existing version, including `v001`, cannot be replaced with `--overwrite`.

## Independent verification

After the production build, a separate readback loaded both Parquet files and the membership CSV, then independently checked counts, key uniqueness, deterministic sorting/ranks, label-to-candidate containment, one protocol ID, all output SHA256 values, `_SUCCESS` manifest hashes, source parsed-row counts, and absence of private absolute paths. All assertions passed.

The final automated gate also passed 31 pytest tests, Ruff formatting/lint, strict mypy, package build, pre-commit hooks, CLI smoke tests, and repository secret/private-path scans. Exact results are in `PHASE1_TEST_REPORT.md`. No quantum-chemistry job, model fit, or full-pool prediction was performed.

## Gate decision

Phase 1 is complete. Phase 2 remains blocked by phase sequencing until separately authorized.
