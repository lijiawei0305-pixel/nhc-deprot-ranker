# Phase 9B AIMNet2 fine-tuning data plan

## Objective

The current parent-level calculations are no longer treated as an isolated
speed benchmark.  Their primary purpose is to produce NHC-specific reference
data for a later AIMNet2 fine-tuning stage.  The reference protocol remains the
frozen Parent-Level P01 protocol:

```text
gas-phase closed-shell RKS
omegaB97M-D3(BJ)/def2-TZVPP
two-body D3(BJ), ATM disabled, VV10 disabled
PySCF grid level 4, SCF conv_tol 1e-9
```

This is a non-production research track.  It does not change the production
runner, the 71 production labels, or any public execution gate.

## Data contract

Every newly scheduled pure-PySCF geometry optimization must durably record the
following at the real PySCF/geomeTRIC analytic-gradient boundary:

- candidate and endpoint identity;
- ordered elements and atom count;
- charge, multiplicity, spin, and electron count;
- exact evaluated Cartesian coordinates in Bohr;
- converged total parent-level energy in Hartree, including the frozen D3 term;
- complete analytic gradient in Hartree/Bohr;
- complete force array (`-gradient`) in Hartree/Bohr;
- frame number, protocol SHA256, source identity, and canonical frame SHA256.

Frames are immutable, exclusively created, fsynced, reread, and closed by an
endpoint manifest.  A route-level training manifest binds both endpoint
manifests.  A partial or failed calculation may retain individual frames, but
unmanifested frames are not automatically admitted to model training.

Existing P01 calculations are preserved unchanged.  Their trajectory XYZ and
energies remain useful for geometry and endpoint-energy analysis, but they do
not contain complete per-atom gradient vectors and therefore cannot by
themselves support force-aware fine-tuning.

The audited training projection converts coordinates from Bohr to Angstrom,
energies from Hartree to eV, and forces from Hartree/Bohr to eV/Angstrom.  These
are the native input/target units expected by the installed AIMNet2 training
stack.  The model inputs are `coord`, `numbers`, and molecular `charge`; the
supervised targets are total `energy` and complete atomic `forces`.  No
unavailable atomic-charge target is fabricated.

The NPZ projection stores `coord`, molecular `charge`, and `forces` as
`float32`, and `numbers` as `int64`, matching the installed model's training
tensor path.  Total energy is retained as `float64` on disk while applying the
training-only atomic self-energy shift; AIMNet's loader then casts the shifted
energy target to `float32`.  Candidate and endpoint provenance arrays are
stored in the files for audit but excluded by the explicit training `x`/`y`
key lists.

## Split and leakage contract

The split unit is the InChIKey, never an individual geometry.  The cation,
neutral, and every trajectory frame for one InChIKey must remain in the same
split.  Validation and final-test candidates must not contribute to training
loss, optimizer state, early stopping, hyperparameter selection, atomic energy
baselines, or normalization statistics.

The concrete cohort and its train/validation/final-test assignment must be
frozen before those candidates are launched.  Failed candidates are retained
under their original assignment and are not replaced after observing results.

## Fine-tuning boundary

The installed `aimnet 0.2.0` package exposes its own `aimnet.train` modules.
The future fine-tuning stage will use that implementation and the frozen local
`aimnet2_wb97m_d3_0.pt` base weight.  Training configuration, loss weights,
units, atomic reference treatment, random seeds, checkpoint selection, and
model export identity must be frozen in a separate implementation step after
the reference dataset is audited.

No current AIMNet2 energy enters the PySCF deprotonation label.  The final model
will be benchmarked only after model freezing, on molecule-level held-out
candidates and under an isolated, equal-resource timing protocol.
