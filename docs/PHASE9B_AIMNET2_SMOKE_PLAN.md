# Phase 9B Paired AIMNet2 / Direct-PySCF Smoke Plan

## Status

Plan only. Phase 9B is **not authorized** by this document. Execution requires a
successful Phase 9A-R read-only preflight, a new authority chain, and separate
explicit user authorization.

## Purpose

Measure, on one candidate, whether AIMNet2 preoptimization makes the
high-fidelity pipeline cheaper without changing what it computes.

This is a controlled paired comparison, not a model bake-off. The frozen
decision to use AIMNet2 is not revisited here. Direct PySCF appears only as the
necessary scientific baseline; including it is not model reselection.

## Candidate selection

**Resolved: `LBNPGYISTSLAHY-UHFFFAOYSA-N`**, the candidate characterized in
Phase 9A-I. `QXHIEGFUWOLQIJ-UHFFFAOYSA-N` is excluded because its Phase 8B
authority chain is permanently retired.

Reusing the 9A-I candidate is legitimate and deliberate. Phase 9A-I consumed no
DFT permit, created no remote run root, and opened no attempt in the guarded
runner, so the candidate itself was never spent. Its elements `C F H N` are also
the only set empirically confirmed to run under `validate_species=True`; every
other Phase 7 candidate contains oxygen, whose support remains unverified.

Frozen identities and the full rationale are in
`docs/PHASE9B_AUTHORITY_CHAIN.md`. Runtime substitution remains prohibited.

Reusing the QXH request, attempt, permit, bundle, or remote root is prohibited
in every form. Phase 9B requires:

```text
new candidate selection record
new request ID
new attempt ID
new remote root
new source closure
new one-shot permit
new local invocation record
new preflight
new acceptance/rejection contract
```

## The two routes

Both routes begin from the **identical** frozen Phase 7 initial structure.

### Route D — direct PySCF baseline

```text
Phase 7 initial cation XYZ
  -> PySCF B3LYP-D3(BJ)/def2-SVP
  -> geomeTRIC optimization to frozen convergence
  -> final cation electronic energy

Phase 7 initial neutral XYZ
  -> (same)
  -> final neutral electronic energy
```

### Route A — AIMNet2-assisted PySCF

```text
same Phase 7 initial cation XYZ
  -> AIMNet2 preoptimization (total_charge = +1)
  -> structure validation gates
  -> PySCF B3LYP-D3(BJ)/def2-SVP
  -> geomeTRIC residual optimization to the SAME frozen convergence
  -> final cation electronic energy

same Phase 7 initial neutral XYZ
  -> AIMNet2 preoptimization (total_charge = 0)
  -> structure validation gates
  -> (same)
  -> final neutral electronic energy
```

## Controlled variables

Everything except the presence of the AIMNet2 stage must be identical:

```text
initial structure          identical
atom order                 identical
charge                     identical per endpoint
multiplicity               identical (1)
method                     B3LYP
basis                      def2-SVP
dispersion                 D3(BJ)
SCF convergence            identical
geometry convergence       identical
geomeTRIC maxsteps         identical
wall-time limit            identical
hardware                   identical
thread configuration       identical
CPU affinity               identical
memory limit               identical
failure semantics          identical
```

A configuration difference between the routes invalidates the comparison and is
failure class `G6_route_config_mismatch`.

## Execution order and independence

The two routes are separate attempts under the same authorization, each with
its own attempt identity and its own result tree. Neither may read the other's
intermediate state, reuse its wavefunction, or inherit its convergence history.
Route A must not be seeded by Route D's converged geometry, and Route D must
not be run second "to confirm" Route A.

## Measurements

Recorded separately for cation and neutral.

### AIMNet2 stage

```text
process startup time
torch.compile / warm-up time
optimizer steps
energy evaluations
force evaluations
wall-time
initial max force
final max force
converged (bool)
total RMSD vs input
maximum single-atom displacement
C2-N1 and C2-N3 bond lengths, before and after
N1-C2-N3 angle, before and after
proton identity result
structural integrity result
isolated-root cache bytes written
device and peak memory
failure reason if any
```

Ensemble mean, standard deviation, and force disagreement are **unavailable**:
only member `_0` exists. Those fields are recorded as
`unavailable_single_member` rather than filled with single-member values. See
`docs/PHASE9B_SINGLE_MEMBER_SAFEGUARDS.md`.

### PySCF stage

```text
geometry optimizer steps
energy/gradient evaluations
total SCF cycles
wall-time
CPU/GPU resources and peak memory
SCF failure count
geometry convergence status
final max gradient
final electronic energy
final structure
timeout status
```

### End to end

```text
total_assisted_time = aimnet2_process_startup
                    + aimnet2_compile
                    + aimnet2_optimization_steps
                    + handoff_and_validation
                    + assisted_pyscf_time

direct_pyscf_time
```

The comparison is `total_assisted_time` against `direct_pyscf_time`. Reporting a
reduction in PySCF time alone, without the AIMNet2 cost included, is prohibited.

Phase 9A-I measured the warm-up term directly and it is not negligible for a
single candidate: the first AIMNet2 call in a process took **21.9 s** including
`torch.compile`, while subsequent calls took **1.6 s** (cation) and **0.2 s**
(neutral). That fixed cost amortizes over many optimization steps but is real
here, and it must appear in the accounting rather than be written off as
warm-up.

## Scientific consistency comparison

Between Route D and Route A:

- final cation electronic energy;
- final neutral electronic energy;
- final deprotonation electronic energy;
- final structure RMSD;
- key bond lengths;
- NHC ring geometry;
- proton position;
- chemical connectivity;
- whether both routes reached the same local minimum;
- whether either found a distinct, lower PySCF minimum;
- evidence of basin dependence.

Pointwise coordinate identity is **not** required. Different minima are
reported honestly, are not automatically a failure, and do not license
selecting the lower-energy route as the production answer. The preregistered
basin rule in `docs/AIMNET2_PROMOTION_GATES.md` governs.

## Label handling

A label may be produced only if **both** endpoints of a route satisfy every
acceptance gate. The label is computed only from PySCF electronic energies:

```text
dft_deprot_electronic_kcal =
    (E_neutral_hartree - E_cation_hartree) * 627.509474 - 6.28
```

with the accompanying constant-free difference retained and
`lower_is_better=true`.

Two distinct tolerances apply and must not be confused:

```text
runner self-consistency (two_endpoint.py)  abs_tol = 1e-12
legacy label ingest     (constants.py)     abs_tol = 0.02 kcal/mol
```

The runner recomputes its own label from its own endpoint energies and holds
itself to `1e-12`; the postflight repeats that check at the same tolerance. The
`0.02 kcal/mol` constant is `LABEL_FORMULA_ATOL_KCAL_MOL`, used by the data
layer to validate *harvested legacy* labels against stored source values. It
does not govern runner output. Applying the looser ingest tolerance to fresh
runner results would silently permit arithmetic drift the runner is designed to
reject.

AIMNet2 energies never enter this formula.

A Phase 9B label is a smoke result. It does not join the production label table
by virtue of existing; the data-contract protocol and conflict rules govern
that separately.

## Deployment transaction

Deployment is one transaction over both routes, implemented in
`preparation/phase9b_deploy.py`.

```text
verify local     paths, regular-file type, byte size, recomputed SHA256, and the
                 exact registered set in both directions
roots absent     both final roots and both staging roots
stage            one directed stream per route into a fresh, attempt-unique
                 staging root, exclusive-create only
verify remote    per-file relative path, type, size, SHA256, total count, and no
                 extra file
promote          only after BOTH routes verify
```

Only manifest-registered files are sent; there is no directory-level sync, and an
unregistered file in the bundle is a hard stop. The transport uses a
standard-library receiver over one SSH call per route: no `rsync`, no `scp`, no
`--delete`, `O_EXCL` and `O_NOFOLLOW` on every create, and no delete verb
anywhere on either side.

Three SSH invocations total: two uploads and one promotion.

**A single successful upload is never grounds for launchability.** If either
route fails, nothing is promoted, and the failure record names every root it
touched so the state is auditable rather than guessed.

**Promotion is two renames and therefore cannot be one atomic step.** This is
stated rather than papered over: if the second rename fails after the first
succeeded, the outcome is recorded as possibly partial and names all four roots.
The module does not roll back, because rolling back would mean a destructive
remote delete, which it never performs.

## Launch transaction

Launching is one transaction over both routes, implemented in
`preparation/phase9b_launch.py`. It is control plane: it lives outside the runner
source closure, so editing it cannot change `runner_source_sha256` and cannot
invalidate a frozen request, manifest, or permit.

It consumes already-validated records and rebuilds none of them —
the parsed permit, the bundle payload, the deploy `RoutePlan` with its verified
byte sizes, the `DeploymentOutcome`, and the read-only `PreflightResult` — and
cross-checks every field the records share:

```text
route            permit, payload, and deploy plan must name the same route
attempt          all three must carry that route's frozen attempt identity
request hash     permit against payload, and against the deployed request bytes
manifest hash    permit against payload, and against the deployed manifest bytes
final root       deploy plan against the permit's own run root
paths            request, output, and permit paths must sit inside the final root
files            the verified set, every SHA256, and every byte size
retired chain    no root, path, or attempt may name a Phase 8B artifact
```

It selects nothing. GPU index comes from the preflight record, CPU affinity and
wall-time from `PHASE9B_RESOURCES`, route order from `PHASE9B_RESOURCES["routes"]`
— `direct` then `assisted`. If the frozen device budget no longer holds, or the
preflight cannot prove it wrote nothing, the launch fails closed. There is no
card swap, no queue, no wait, and no degraded run.

### Deploy proof obligations

```text
state              DeployState.PROMOTED, nothing else
promoted routes    exactly both
failure record     no failure reason and no failure root
ssh invocations    exactly three: two uploads and one promotion
roots              both final and both staging roots match the launch plans
```

A possibly partial promotion is recorded by `deploy_both_routes` as `FAILED` with
a failure reason naming all four roots, so it can never be read as launchable.
A record that claims `PROMOTED` while still naming a failure is contradictory and
is refused for that reason alone.

### One-shot semantics

The permit is verified locally before any call: the ready permit must be present,
its bytes must hash to the permitted digest, and no consumed permit may exist. A
consumed permit is never restored. The remote half is verified by the supervisor
itself, which is passed `--expected-permit-sha256` along with the request,
manifest, runner-source, and resource digests it must re-check before spawning.

A route already launched under this permit is never launched again.

### Canonical remote argv

```text
python3 -B -s -m nhc_deprot_ranker.quantum.phase9b_supervisor
  --route --attempt-id --request-path --output-root --permit-path
  --expected-request-sha256 --expected-payload-manifest-sha256
  --expected-permit-sha256 --expected-runner-source-sha256
  --expected-resources-sha256 --gpu-index --cpu-affinity --timeout-seconds
```

Thirteen whitelisted flags, rendered from structured fields, with a fixed
argument count. Every value is refused if it contains a shell metacharacter, a
path traversal segment, a newline, a NUL, or any control character; there is no
`shell=True` and no free text anywhere. Only that entry may be started: AIMNet2
and PySCF are never invoked directly and no script may stand in for the
supervisor. The recorded argv has absolute paths replaced by `<PATH>`, so the
audit trail keeps the shape without the private layout.

The supervisor must print back its own identity, attempt, route, and entry. A
zero exit that does not prove what it started leaves the remote state unknown.

### States

```text
not_launched         nothing was started; every precondition failure lands here
launched             both routes started and both proved their identity
partially_launched   one route started, the second failed; terminal
indeterminate        a remote state is unknowable; terminal
failed               the first route failed, so the second was never started
```

Both routes always report their own identity and their own state, including the
one that was never attempted. There is no retry, no rollback, and no backfill:
every state except `launched` yields `stop_and_report`.

The launch receipt records phase, candidate, request, host digest, start time,
per-route request/manifest/permit/argv digests, SSH return codes, stdout and
stderr digests, supervisor identity and PID, each route's state, and the overall
state. It carries **no** endpoint energy, AIMNet2 energy or force, SCF or
geometry convergence status, deprotonation label, or claim that a computation
succeeded; every serialized key is screened so none can be added. Those belong to
`phase9b_postflight`.

## Stopping conditions

Phase 9B stops immediately and fails closed on:

- any failure class in `docs/AIMNET2_FAILURE_TAXONOMY.md`;
- any drift between planned and actual protocol identity;
- any attempt to alter frozen thresholds mid-run;
- any resource increase requested at runtime;
- any second attempt for the same endpoint.

There is no retry. As in Phase 8B, the permit is consumed irreversibly before
spawn, and a consumed permit is never restored.

## Explicit non-goals

Phase 9B does not compare other machine-learning potentials, does not tune
AIMNet2, does not calibrate AIMNet2 against DFT, does not compute Hessians or
frequencies, does not claim frequency-verified minima, and does not promote the
pipeline to production. Promotion requires the Phase 9C pilot.
