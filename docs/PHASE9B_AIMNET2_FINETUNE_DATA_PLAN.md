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

The current downstream role is `PRECONDITIONER_FULL_PARENT_OPT`. A frozen
generation uses one ASE LBFGS trajectory for at most 100 steps and must satisfy
all five AIMNet2-surface `GAU_LOOSE` metrics plus its `Fmax <= 0.10
eV/Angstrom` cap. It then passes chemical-identity gates and hands the exact
final XYZ bytes to a mandatory full Parent-Level P01 PySCF/geomeTRIC
optimization. This stopping point means only that AIMNet2 preoptimization is
complete. It is not a parent-level convergence claim and does not authorize
skipping PySCF geometry optimization. See
`PHASE9B_AIMNET2_GAU_LOOSE_V001.yaml` and
`PHASE9B_AIMNET2_PRECONDITIONER_CONTRACT_V001.json`.

The handoff check reuses the first successful parent energy and analytic
gradient emitted by that continuing optimization; it does not launch a static
duplicate job. It records `HANDOFF_CALIBRATION_PASS` only when both fixed
GAU_LOOSE gradient components pass, otherwise a valid observation records
`HANDOFF_CALIBRATION_MISS`. Both continue to final parent `GAU` and the final
single point. Invalid parent evidence is `FAILED_PARENT_HANDOFF`.

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
supervised targets are D3-subtracted `energy` and complete atomic `forces`.  No
unavailable atomic-charge target is fabricated.

The frozen AIMNet2 export applies two-body D3(BJ) outside the neural-network
core.  Dataset assembly therefore independently recomputes that exact D3
energy and gradient for every immutable P01 frame with PySCF 2.13.1 and
`pyscf-dispersion` 1.5.0, then trains on `P01 total - D3`.  The total and D3
components remain in the NPZ audit projection, while only the short-range
`energy` and `forces` keys enter the loss.  The fine-tuned export must retain
the original external D3 parameters; this prevents dispersion from being
learned once and added a second time at inference.

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

The installed `aimnet 0.2.0` package exposes its own training primitives.  The
V001 fine-tuning configuration is retained as a rejected pre-execution design in
`PHASE9B_AIMNET2_FINETUNE_CONFIG_V001.json`; its model structure is frozen in
`PHASE9B_AIMNET2_FINETUNE_MODEL_V001.yaml`.  It restores the base model's
training-time long-range Coulomb module, excludes embedded D3 because D3 is
already removed from the targets, and maps the trained Coulomb state back to
the immutable export schema afterward.  A remote strict-load audit proved the
37 base state entries migrate to the training model and back with no missing or
unexpected keys.

Only the energy output MLP is trainable in V001.  The pretrained representation,
charge-producing path, atomic shift, AEV parameters, and Coulomb physics remain
frozen.  The fixed seed is `20260730`; RAdam uses a learning rate of `1e-4`, and
energy and force losses have equal frozen weights.  Validation weighted loss
selects the earliest best checkpoint.  Static audit found that V001 nevertheless
placed final-test files under the development dataset root, validated their
receipts in the trainer, and evaluated them in that same process.  V001 therefore
fails the final-test isolation contract and must not be launched.

V002 uses two frozen views.  `PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V002.json`
contains only train/validation settings plus a sealed final-test commitment and
count; it has no split-registry path, final-test directory, candidate identity,
receipt, or payload path.  Its development dataset contains exactly five train
and two validation candidates.  The trainer validates only those directories
and terminates at `MODEL_FROZEN` after serialization and runtime-load audit.

Only after that process exits may `phase9b_aimnet2_final_test.py` run as a
separate evaluator.  Before its first final-test route/frame read it writes an
immutable consumption claim binding the generation, cohort commitment,
candidate identities, frozen bundle, model-freeze result, and evaluator source.
It then assembles a separate final-test-only dataset and evaluates the frozen
bundle and unchanged base on identical inputs.  The evaluator cannot select a
checkpoint, change a threshold, promote a model, retry, or write a production
label.  Because scientific validation/final-test acceptance thresholds and the
epoch-0 selection path are not yet frozen, V002 is currently
`BLOCKED_BEFORE_TRAINING`; neither training nor final-test consumption is
permitted until a separately approved config registers those gates.

`phase9b_aimnet2_finetune_watch.py` is the durable transition gate.  It waits for
all nine preregistered candidates and all four lane terminals, stops on any
candidate failure, assembles the D3-audited dataset once, waits for disk, host
memory, and one idle V100, and then claims exactly one training attempt.  There
is no retry, replacement candidate, extension cohort, production label write,
or speed benchmark in this state machine.  V002 launches dataset assembly with
`--scope development`, passes the sanitized generation config to the trainer,
verifies `MODEL_FROZEN`, and only then launches the evaluator.  Its current
readiness guard stops before dataset assembly while V002 remains blocked.  The
legacy V001 orchestration is historical and must not be resumed.

The lane watcher now writes a structured `lane_terminal.json` and stops before
the next claim if the completed route cannot independently prove exit code 0,
PASS, two complete endpoint manifests, the route-manifest binding, the exact
frame set, and process cleanup.  The fine-tune watcher treats any such lane
terminal as a collection failure, so an initial-predecessor or mid-queue
failure cannot leave the training gate waiting indefinitely or permit a
replacement.

No current AIMNet2 energy enters the PySCF deprotonation label.  The final model
will be benchmarked only after model freezing, on molecule-level held-out
candidates and under an isolated, equal-resource timing protocol.  Parent
gradient reduction is compared with the same frozen initial geometry;
fine-tuning improvement is compared with epoch 0/base AIMNet2; and expensive
PySCF-work reduction is compared with pure P01 optimization from identical
initial bytes.  Both routes must complete full P01 optimization before their
signed final labels are compared.
