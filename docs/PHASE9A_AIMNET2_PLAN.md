# Phase 9A — AIMNet2 Preoptimization Integration Audit and Design

## Frozen decision

This project has frozen AIMNet2 as the structure preoptimization model for the
cation and neutral endpoints. AIMNet2 performs the bulk of the geometry
optimization; PySCF B3LYP-D3(BJ)/def2-SVP performs the residual final
optimization, the final electronic energies, and the official deprotonation
electronic-energy label.

Model selection is not reopened here. No alternative machine-learned potential
is proposed, compared, or recommended.

## Target pipeline

```text
SMILES
  -> RDKit ETKDGv3 initial 3D conformers
  -> MMFF94, UFF on exception
  -> separate NHC-H+ cation and NHC neutral endpoints
  -> AIMNet2 geometry preoptimization
  -> PySCF B3LYP-D3(BJ)/def2-SVP residual final optimization
  -> PySCF final cation and neutral electronic energies
  -> high-fidelity deprotonation electronic-energy label
```

## Scope of this phase

Phase 9A is read-only audit, document-first design, interface design, gate
design, test design, and forward planning.

It does **not** run AIMNet2, does not run PySCF, does not run xTB, MMFF, or UFF,
does not connect to a server, does not install or download anything, does not
create geometry, does not create a permit, and does not open any execution gate.

Every execution gate is unchanged and closed:

```text
EXECUTION_AUTHORIZED                              = False
phase8b_bundle._PRODUCTION_AUTHORIZATION_CONSUMED = True
phase8b_deploy._PRODUCTION_AUTHORIZATION_CONSUMED = True
phase8b_launch._PRODUCTION_AUTHORIZATION_CONSUMED = True
```

## Phase 8B boundary, restated

Phase 8B failed closed. It is not a partial success. It produced zero complete
cation endpoints, zero complete neutral endpoints, and zero DFT labels. The
high-fidelity label count remains **71**. No Phase 8B computational result is
inheritable. The QXH request, attempt, permit, bundle, and remote root are
permanently unusable.

The large volume of Phase 8B infrastructure code does not indicate that DFT
results were obtained.

## Documents produced

```text
docs/PHASE9A_AIMNET2_PLAN.md                    this document
docs/AIMNET2_ASSET_AUDIT_PLAN.md                asset audit scope and method
docs/AIMNET2_MODEL_IDENTITY.md                  identity fields, element coverage
docs/AIMNET2_PREOPTIMIZATION_CONTRACT.md        input/output/optimizer contract
docs/AIMNET2_STRUCTURE_VALIDATION.md            pre/post checks, test design
docs/AIMNET2_PYSCF_HANDOFF_CONTRACT.md          the stage boundary
docs/PYSCF_RESIDUAL_OPTIMIZATION_CONTRACT.md    final optimization requirements
docs/AIMNET2_FAILURE_TAXONOMY.md                every failure class
docs/AIMNET2_PROMOTION_GATES.md                 preregistered promotion criteria
docs/AIMNET2_READONLY_SERVER_PREFLIGHT.md       Phase 9A-R plan
docs/PHASE9B_AIMNET2_SMOKE_PLAN.md              paired direct/assisted smoke
docs/NEXT_PHASE_AUTHORIZATION.md                what the user must decide next
```

## Audit findings that shape the design

### Finding 1 — element coverage is not a blocker

Measured from local immutable products by three independent methods:

```text
Phase 7 smoke    (4)        H C N O F
labels           (71)       H C N O F Cl Br
acquisition      (50)       H C N O F Cl Br
full pool        (401,856)  H C N O F S Cl Br
```

No candidate at any tier contains an element outside that set. Published
AIMNet2 coverage includes all eight, so element support is expected to be
sufficient even for the full pool — pending verification of the installed
weight in Phase 9A-R.

### Finding 2 — the preoptimizer must live outside the runner source closure

The two-endpoint runner hashes an exact 14-file source closure into
`runner_source_sha256`, which is validated three times and bound into the permit
and every artifact. Adding the preoptimizer inside that closure would
invalidate the authority chain on every edit and would make a heavy ML stack
part of the guarded worker's identity.

The preoptimizer is therefore an **upstream producer** under `preparation/`. It
writes optimized XYZ files and regenerates the request; the runner consumes them
exactly as it consumes Phase 7 geometry and is not modified.

### Finding 3 — the two endpoints have no guaranteed index correspondence

The cation and neutral are built independently from two separate SMILES columns.
No code removes a proton programmatically. Historically 3 of 8 audited examples
showed cation-map/neutral-index mismatches.

Consequences: per-endpoint validation is mandatory, atom order must be preserved
exactly, and the stricter **ordered** heavy-element comparison used at the DFT
gate must be adopted rather than the Phase 7 multiset check.

### Finding 4 — two environments, one file-based boundary

The legacy record places AIMNet2 in a separate conda prefix
(`$WJW/env/conda/mlff`, with torch and ase), while this project is restricted to
the `molecular` environment, which has ase but no torch and no aimnet. Mixing
software stacks and installing dependencies are both prohibited.

AIMNet2 and PySCF therefore cannot share one process or one environment. The
pipeline runs them as separate processes in separate environments with a
file-based, hash-closed handoff — which is what the source-closure constraint
independently requires.

Whether this project may use the `mlff` prefix at all is a user decision, not an
inference. It is listed in `docs/NEXT_PHASE_AUTHORIZATION.md`.

### Finding 5 — provenance labels must change

`geometry_quality = initial_force_field_geometry` is re-checked at the DFT gate.
After AIMNet2 preoptimization it is no longer true. A new, explicit label value
and a versioned endpoint-atom-map schema are required. The new value must not
claim a validated local minimum or frequency verification.

### Finding 6 — a prior negative result exists and must not be buried

This is the most consequential finding of the audit.

The legacy project already ran this experiment, on the same hardware and the
same chemistry, and closed it on 2026-07-15. Its recorded measurement:

```text
AIMNet2 as a preoptimizer to cut DFT steps
  fair same-basin comparison, n = 12
  median speedup 1.10x, best 3.28x, worst 0.78x
  verdict: physically limited, dead end
```

with the recorded root cause:

```text
geomeTRIC convergence threshold   ~0.015-0.023 eV/A
fine-tuned MLFF near-minimum force MAE   0.088 eV/A   (4-6x above threshold)
=> DFT still needs ~20 steps from any starting point (measured mean 21.9)
=> a good starting point beat a poor one by only 1.10x
```

and an explicit note to successors not to pursue this model as a preoptimizer
again. The legacy conclusion was that starting geometry was never the
bottleneck, and that per-step cost was the thing worth attacking.

That prior experiment used a **fine-tuned** AIMNet2, not the base weight, and
its measurement is the same quantity as this project's efficiency gates E1 and
E2. Those gates are exactly the gates it already failed.

**This does not by itself decide Phase 9.** Three differences are real and are
reasons the result could differ here:

1. the legacy baseline already had a good starting geometry from its own
   prescreen, whereas this project currently goes from MMFF94/UFF straight to
   DFT, so the gap being closed is larger;
2. the legacy fine-tune targeted a different objective and carried a known D3
   parameter hazard;
3. this project's per-candidate cost and acceptance regime differ.

But the prior number is the single best available prior for what Phase 9B will
measure, and honesty requires stating it before the measurement rather than
after. It is recorded here so that a 1.1x result in Phase 9B is recognised as a
**replication**, not a surprise, and so that non-promotion is understood in
advance as a likely and legitimate outcome.

Two further legacy records are relevant and are reported without being acted on:
the same project measured a large speedup from GPU-accelerated PySCF with
bit-identical results, and it separately found value in AIMNet2 **embeddings as
descriptors** rather than as a potential. Neither is proposed here; both are
recorded because the audit was asked to read the legacy AIMNet2 experiment
reports, and omitting them would misrepresent what those reports contain.

### Finding 7 — only one ensemble member has any evidence

The single weight ever recorded on the host is `aimnet2_wb97m_d3_0.pt`. Members
`_1`, `_2`, `_3` have no evidence in either project. A four-member ensemble
cannot be assumed, and the missing members may not be downloaded.

### Finding 8 — unit conversion is mandatory at the boundary

The recorded ASE interface returns **eV and eV/Å**; the runner and its XYZ files
use **Ångström**, and PySCF energies are in Hartree. AIMNet2's internal DFTD3
module also reports eV. Every conversion must be explicit and verified against
the installed API, never assumed.

## Scientific invariants, unchanged

```text
reaction   NHC-H+ -> NHC + H+
cation     charge +1, multiplicity 1
neutral    charge  0, multiplicity 1
method     gas-phase B3LYP-D3(BJ)/def2-SVP, PySCF, geomeTRIC

dft_deprot_electronic_kcal =
    (E_neutral_hartree - E_cation_hartree) * 627.509474 - 6.28

lower_is_better = true
```

The label is a gas-phase electronic energy difference, not a Gibbs free energy.
AIMNet2 energies never enter the formula. No Hessian is computed, so no
structure may be described as frequency-verified.

## Forward route

```text
Phase 9A     read-only audit and design                    this phase, complete
Phase 9A-R   read-only server preflight                    needs user authorization
Phase 9B     paired direct / assisted two-endpoint smoke   needs new authority chain
Phase 9C     small pilot, 3-5 diverse candidates           after 9B passes
Phase 10     batched production labelling                  after 9C freezes thresholds
```

Each arrow is a separate authorization. Document planning is not implementation
authorization; implementation is not server-write authorization; server-write is
not compute authorization.

## Stopping condition

Phase 9A stops on completion of this audit, these contracts, and this phase
design. No implementation code is written in this phase.
