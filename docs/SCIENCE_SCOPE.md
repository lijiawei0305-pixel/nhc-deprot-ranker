# Science Scope

## 1. Scientific question

This repository ranks a large pool of NHC precursor candidates by their tendency to undergo the gas-phase deprotonation reaction

```text
NHC-H+ -> NHC + H+
```

The operational question is not whether every candidate has a chemically accurate 298.15 K deprotonation Gibbs free energy. It is whether low-fidelity GFN2-xTB electronic deprotonation energies, calibrated with a small number of high-fidelity B3LYP-D3(BJ)/def2-SVP electronic-energy labels, can retain more genuinely high-ranking candidates under a limited downstream selection budget.

Lower energy is always better:

```yaml
lower_is_better: true
```

## 2. Target definitions

The electronic energy difference without the common proton term is

```text
electronic_difference_kcal =
    (E_neutral_hartree - E_cation_hartree) * 627.509474
```

The legacy-compatible DFT target is

```text
dft_deprot_electronic_kcal = electronic_difference_kcal - 6.28
```

The `-6.28 kcal/mol` gas-phase proton constant is retained for compatibility with the legacy project. Because it is identical for all molecules, it cannot change their ordering.

This target is an electronic-energy ranking label. It is not a complete Gibbs free energy. Without a Hessian, it contains no verified zero-point energy, vibrational entropy, or full thermal correction. Allowed target names are:

- `dft_deprot_electronic_kcal`
- `delta_e_deprot_dft_kcal`

Names implying a Gibbs free energy are prohibited.

## 3. Hessian and label acceptance boundary

- Phase 0 does not run Hessians.
- `hessian_computed=false` or legacy `n_imaginary=-1` does not by itself reject an electronic-energy label.
- A label is eligible when the cation and neutral geometry/electronic calculations succeeded and the calculation protocol is traceable.
- Such a label is marked `electronic_energy_only`.
- No claim is made that every geometry is a frequency-confirmed strict local minimum.
- If both endpoint electronic energies are available, the stored target must be recomputed and agree within `0.02 kcal/mol`; otherwise it is rejected.
- If only a final target is available, it may be retained with `formula_revalidated=false`, subject to source and protocol checks.

## 4. Data and identity scope

- InChIKey is the unique primary key.
- A molecule cannot cross training, validation, or test boundaries.
- All joins must report duplicates, missingness, source overlap, and conflicting labels.
- Every input is identified by SHA256 and source path.
- Every high-fidelity label records its method, basis, dispersion, geometry protocol, convergence, Hessian status, source group, and protocol ID when the source permits.
- Different computational protocols or target definitions are never silently pooled.

## 5. Chemical-family scope

The first hierarchical model, if Phase 0–2 establish adequate data, may use additive effects for:

- `skeleton`
- `axis_a_family = canonical_sorted_pair(N1_frag, N3_frag)`
- `axis_b_family = canonical_sorted_pair(C4_frag, C5_frag)`

The exact combined family is retained for audit and grouped validation but is not a default model effect. Unknown families receive a zero family effect and fall back to the global calibration. Symmetry is measured from actual data rather than assumed.

## 6. Model comparison scope

Later phases must compare:

- B0: raw xTB ranking;
- B1: global affine calibration with a freely learned slope;
- H1: partially pooled hierarchical linear calibration.

H1 is not presumed to win. Production selection may legitimately be `raw_xTB_wins`, `global_affine_wins`, `hierarchical_wins`, or `insufficient_evidence`.

The production model does not default to a broad collection of xTB-derived HOMO, LUMO, ESP, or related collinear descriptors. Such features may only appear in explicitly named, honestly validated ablations.

## 7. Validation priority

Absolute-error metrics are secondary. Promotion decisions emphasize out-of-fold or held-out ranking behavior, including Spearman, Kendall, pairwise accuracy, true-top-M recall under predicted budget K, NDCG, enrichment, and Top-K regret. Grouped family holdouts and size extrapolation are distinct from random validation.

No result may be called blind unless the holdout was genuinely pre-registered, excluded from all model and family-definition choices, and evaluated once after model freezing.

## 8. Current Phase 0 boundary

Phase 0 is evidence gathering and repository setup only. It may perform read-only source inspection, lightweight tabular audits, hashing, schema inspection, and tests of audit utilities. It must not:

- train or select B0/B1/H1 as a production model;
- score the full candidate pool;
- run PySCF, xTB, Hessian, VASP, or CP2K calculations;
- submit HPC jobs;
- invent missing labels, protocols, or performance values.

Phase 0 passes only when the actual candidate count, primary-key status, target definitions, label count and sources, protocol consistency, Hessian boundary, family sources and coverage, and required legacy code/report evidence have all been recorded.
