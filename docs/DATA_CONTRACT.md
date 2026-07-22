# Data Contract

## 1. Versioning and provenance

Every processed dataset is immutable and identified by a dataset version plus a manifest. The manifest records:

- source role, path or read-only URI, byte size, SHA256, and audit timestamp;
- legacy Git branch/HEAD for tracked source code;
- server path and SHA256 for HPC-only data, because the HPC deployment is not a Git checkout;
- parsed row count, columns, key/null/duplicate statistics, and target validation results;
- target definition and label protocol IDs.

`configs/legacy.local.yaml` contains real local/HPC locations and is ignored by Git. Tracked configuration contains only portable placeholders or project-relative output paths.

## 2. CandidateRecord

The standardized candidate table uses snake_case internally:

| Field | Type | Required | Rule |
| --- | --- | --- | --- |
| `inchikey` | string | yes | Unique, non-null primary key |
| `smiles_cation` | string/null | no | Source canonical cation SMILES |
| `smiles_neutral` | string/null | no | Source neutral NHC SMILES |
| `xtb_deprot_kcal` | float | yes | Finite electronic target including `-6.28` constant |
| `xtb_rank` | integer | yes | Rank 1 is lowest energy |
| `xtb_percentile` | float | yes | Direction documented as lower-is-better |
| `n1_frag`, `n3_frag`, `c4_frag`, `c5_frag` | string/null | no | Joined by InChIKey from authoritative graph tables |
| `skeleton` | string | yes | Explicit source metadata; current snapshot is `imidazolium` |
| `axis_a_family` | string | yes | Canonical unordered N1/N3 pair |
| `axis_b_family` | string | yes | Canonical unordered C4/C5 pair |
| `combined_family` | string | yes | Skeleton plus both canonical axes |
| `n_heavy_atoms` | integer/null | no | Derived only by a tested chemistry routine |
| `n_electrons` | integer/null | no | Derived only by a tested chemistry routine |
| `source_file` | string | yes | Logical source path/URI |
| `source_sha256` | string | yes | Lowercase 64-character SHA256 |

Source-column mapping is configured. Legacy capitalization such as `InChIKey` and `SMILES_cation` is normalized only in the processed dataset; source files remain unchanged.

## 3. HighFidelityLabel

| Field | Type | Required | Rule |
| --- | --- | --- | --- |
| `inchikey` | string | yes | Non-null primary key after source merge |
| `e_cation_hartree` | float/null | conditional | Required for formula revalidation |
| `e_neutral_hartree` | float/null | conditional | Required for formula revalidation |
| `electronic_difference_kcal` | float/null | conditional | Endpoint difference without proton constant |
| `dft_deprot_electronic_kcal` | float | yes | Finite label; lower is better |
| `formula_revalidated` | boolean | yes | True only when both endpoints were checked |
| `method` | string | yes | Current: `B3LYP` |
| `basis` | string | yes | Current: `def2-SVP` |
| `dispersion` | string | yes | Current: `D3(BJ)` |
| `geometry_optimizer` | string/null | no | Current: geomeTRIC |
| `cation_converged`, `neutral_converged` | boolean | yes | Failed endpoint rejects the label |
| `hessian_computed` | boolean | yes | False is valid for electronic-energy-only labels |
| `n_imaginary` | integer/null | no | Null when Hessian was not computed |
| `label_quality` | string | yes | Current: `electronic_energy_only` |
| `label_protocol_id` | string | yes | SHA256 over normalized protocol fields |
| `source_group` | string | yes | `gold`, `blind_round1`, or `blind_round2` |
| `source_file` | string | yes | Source path/URI |
| `source_sha256` | string | yes | Exact source hash |

## 4. Formula validation

With both endpoint energies present:

```text
electronic_difference_kcal =
    (e_neutral_hartree - e_cation_hartree) * 627.509474

dft_deprot_electronic_kcal =
    electronic_difference_kcal - 6.28
```

The absolute difference from a stored source label must be at most `0.02 kcal/mol`. Larger differences are hard rejects. If either endpoint is missing, a final label can remain only with `formula_revalidated=false` and complete source/protocol metadata.

## 5. Hessian normalization

Hessian status is determined in this precedence order:

1. explicit `hessian_computed`/`freq_computed`;
2. explicit `frequency_status`;
3. a documented sentinel such as `n_vfreq=-1`;
4. `n_imaginary` only when a Hessian is known to have been computed.

The full xTB legacy table stores `n_imaginary=0` while also storing `hessian_computed=False` and `frequency_status=skipped_hessian`. Import must normalize `n_imaginary` to null/not-computed for these rows; it must not claim frequency confirmation.

## 6. Merge policy

- Candidate inputs: any duplicate InChIKey is a hard failure.
- Label sources: identical repeated labels may merge only when protocol IDs match and numeric differences are within configured tolerance.
- Conflicting labels, endpoints, or protocols are hard failures and are listed in an audit output.
- Candidate/label joins are many-to-one by validated unique candidate key.
- Split manifests store InChIKeys explicitly; no key can appear in more than one split.
- Source rows are never silently dropped. Rejections and unmatched rows are counted with reason codes.

## 7. Current audited inputs

The authoritative full xTB table contains 401,856 complete, unique candidates. The v3 graph and v4-new lookup union covers exactly the same 401,856 keys. The high-fidelity sources contain 71 unique labels with zero overlap or conflict and zero formula failures.
