# Data Audit

## Candidate pool

| Check | Result |
| --- | ---: |
| Rows | 401,856 |
| Unique InChIKeys | 401,856 |
| Null/duplicate keys | 0 / 0 |
| Missing/non-finite xTB target | 0 |
| Missing endpoint electronic energies | 0 |
| Missing cation/neutral SMILES | 0 / 0 |
| Target range | 44.002403–124.685725 kcal/mol |
| Formula failures over 0.02 | 0 |
| Fragment lookup coverage | 401,856/401,856 |

The authoritative 28-column full table is used instead of the 16-column reduced projection. The reduced table has the same key set/order and target, but other common fields diverge.

All xTB rows skip Hessian. Their legacy `n_imaginary=0` value is semantically overridden by `hessian_computed=False` and `frequency_status=skipped_hessian`.

## Family tables

| Source | Rows | Unique keys | Fragment null cells | Overlap |
| --- | ---: | ---: | ---: | ---: |
| v3 graph | 36,585 | 36,585 | 0 | 0 |
| v4 new-only | 365,271 | 365,271 | 0 | 0 |
| Union | 401,856 | 401,856 | 0 | — |

The obsolete 15,130-row local string-builder table is explicitly excluded.

## High-fidelity labels

| Group | Rows | Formula revalidated | Successful | Hessian computed |
| --- | ---: | ---: | ---: | ---: |
| Gold | 24 | 24 | 24 | 0 |
| Blind round 1 | 12 | 12 | 12 | 0 |
| Blind round 2 | 35 | 35 | 35 | 0 |
| Total | 71 | 71 | 71 | 0 |

The three key sets have zero overlap and zero conflict. Maximum stored-formula difference is below `0.00025 kcal/mol`; there are zero failures over `0.02`.

## Label family support

| Grouping | Families | Singletons | Maximum support |
| --- | ---: | ---: | ---: |
| Axis A | 38 | 22 | 10 |
| Axis B | 35 | 16 | 5 |
| Exact combined | 71 | 71 | 1 |

These counts establish severe sparsity and justify partial pooling plus unknown-family fallback. They do not establish that family offsets improve ranking.

## Provenance

Machine-readable source hashes and logical paths are in `LEGACY_SOURCE_MANIFEST.json`. Large legacy inputs remain outside this repository.
