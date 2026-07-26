# AIMNet2 Asset Audit Plan

## Purpose

Establish what AIMNet2-related assets exist, where, and with what identity,
before any execution is designed against them.

The audit has two halves with different authorization status:

| Half | Scope | Status |
| --- | --- | --- |
| Local asset audit | this repository and the read-only legacy working tree | performed in Phase 9A |
| Server asset audit | the remote environment | **Phase 9A-R, requires separate authorization** |

The server half is specified in `docs/AIMNET2_READONLY_SERVER_PREFLIGHT.md` and
is not executed by Phase 9A.

## Local audit scope

Read-only inspection of:

```text
<CURRENT_PROJECT_ROOT>    this repository
<LEGACY_LOCAL_ROOT>       read-only source of prior environment knowledge
```

Both resolve from the ignored private configuration. Real absolute paths never
enter tracked files.

The legacy tree is read-only in the strongest sense: no modification,
reorganization, deployment, or commit. Its scope — Cu(111) surfaces, VASP,
CP2K, Multiwfn, and the full molecular funnel — is explicitly **not** imported
into this repository. Only environment and model-asset facts are relevant here.

## What the local audit can and cannot establish

It can establish: whether this project has ever recorded an AIMNet2 asset,
whether an environment specification mentions the required stack, and what the
prior project decided about machine-learning potentials.

It cannot establish: whether AIMNet2 is installed on the server, which weights
exist there, or what the installed API looks like. Those are facts about a
machine this phase is not authorized to contact. Any statement about the server
environment that does not come from a Phase 9A-R inspection is a hypothesis,
and must be labelled as one.

## Required outputs of the local audit

For every finding, record the file path, the line, and the verbatim text.
Classify each into exactly one of:

```text
recorded_fact_about_server_environment
plan_or_intention_only
absence_of_evidence
```

This three-way classification is the point of the audit. Prior-project
documents describe work in progress, and an intention to fine-tune a model is
routinely mistaken on rereading for a record that the model is installed. The
classification prevents that error from propagating into a calculation plan.

## Candidate element demand

Completed in Phase 9A from local immutable products. Results are recorded in
`docs/AIMNET2_MODEL_IDENTITY.md`. Summary:

```text
Phase 7 smoke    (4)       H C N O F
labels           (71)      H C N O F Cl Br
acquisition      (50)      H C N O F Cl Br
full pool        (401,856) H C N O F S Cl Br
```

Derived sets required by the audit:

```text
observed_elements     = H C N O F S Cl Br
candidate_elements    = per-tier sets above
unsupported_elements  = pending Phase 9A-R verification of installed coverage
```

`unsupported_elements` cannot be computed in Phase 9A because the installed
model's declared coverage is unknown. It is not assumed empty. Published
documentation suggests it will be empty for every tier, and that expectation is
recorded as `expected_sufficient_pending_verification` rather than as a result.

## Weight identity requirements

For each weight discovered in Phase 9A-R:

```text
registry name
absolute path (private, stays in the ignored local area)
byte size
SHA256
version string
member index within its ensemble
license
```

Only non-private fields — registry name, size, SHA256, version, license — enter
tracked evidence. Absolute paths, host identifiers, and account names do not.

A weight without a computable SHA256 is unusable: failure class
`A3_weight_hash_unknown`.

## Prohibited during any part of this audit

```text
installing or upgrading any package
downloading any model weight
populating any cache
loading a model
constructing an ASE Atoms object with an attached calculator
evaluating energies or forces
running any optimization
constructing a PySCF Mole or calling any kernel
writing to the server
modifying the legacy working tree
```

If inspecting an asset would require any of the above, the asset is reported as
`not_inspectable_without_side_effect` and the audit stops for that item rather
than proceeding.

## Completion criterion

The asset audit is complete when, for every field in
`docs/AIMNET2_MODEL_IDENTITY.md`, there is either a recorded value with its
evidence or an explicit `unknown_pending_9A_R` marker.

An audit with unknowns is a valid audit. An audit that fills unknowns with
plausible defaults is not, and would carry an unverified assumption directly
into a resource-committing calculation.
