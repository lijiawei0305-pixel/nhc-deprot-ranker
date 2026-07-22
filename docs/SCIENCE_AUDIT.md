# Science Audit

## Decision

The Phase 0 scientific definition is internally consistent and suitable for a ranking-calibration project, with one mandatory naming correction: the target is an electronic deprotonation energy, not a complete Gibbs free energy.

## Locked definition

```text
NHC-H+ -> NHC + H+

electronic_difference_kcal =
    (E_neutral - E_cation) * 627.509474

dft_deprot_electronic_kcal =
    electronic_difference_kcal - 6.28
```

Lower is better. The common `-6.28 kcal/mol` proton term is retained for legacy compatibility and cannot alter rank.

## Electronic protocol

All 71 labels use B3LYP-D3(BJ)/def2-SVP optimized electronic energies through PySCF/pyscf-dispersion and geomeTRIC. Cation and neutral endpoint states are closed-shell singlets with charges +1 and 0. All Hessians were skipped; all labels are `electronic_energy_only`.

No ZPE, vibrational entropy, or full thermal correction may be inferred. `G=E` in skipped-Hessian legacy records is a sentinel behavior, not a computed Gibbs energy.

## Family interpretation

Legacy “symmetry” means mirror-exchange canonicalization, not identical paired substituents. Only 0.223% of the full pool has equality on both axes. The correct model identity is therefore an unordered N1/N3 pair plus an unordered C4/C5 pair.

Current exact combined families are unusable as a label effect: every one of the 71 labeled combined families is a singleton. Additive partially pooled axis effects are scientifically and statistically better motivated, but still require grouped validation.

## Historical calibration finding

The old Δ-learning form fixes the explicit xTB coefficient at 1. The audited 71-label affine fit has slope about 0.716, so the fixed-slope assumption is not supported. Historical raw xTB ranking is already strong; this makes B0 a serious baseline and means a hierarchical model must demonstrate head-recall value rather than merely improve in-sample residuals.

## Approved claims after Phase 0

- The electronic target and direction are defined and formula-validated.
- Current labels share one electronic protocol and need no Hessian for this purpose.
- The full candidate and fragment universes join completely by InChIKey.
- Broad same-run xTB electronics/ESP are shortcut-prone and remain ablations, not default features.

No claim is made that a new model wins, reaches DFT accuracy, predicts experimental chemistry, or identifies the best synthesis candidate.
