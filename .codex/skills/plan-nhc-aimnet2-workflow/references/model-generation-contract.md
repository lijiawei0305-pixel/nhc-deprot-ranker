# AIMNet2 Model Generation Contract

## Purpose

Treat one model generation as one immutable experiment. Do not equate a
successful training process with scientific acceptance or promotion.

## 1. Register a generation before training

Assign a unique generation ID and freeze a manifest containing:

- parent/base bundle path projection, byte count, SHA256, embedded model
  identity, and external Coulomb/D3 metadata;
- train/validation dataset manifests, permanent split registry, and sealed
  final-test commitment;
- model YAML, trainable parameter set, target definition, loss, weighting,
  optimizer, scheduler, stopping rule, epoch budget, checkpoint rule, and seed;
- code/source identity, environment/package identity, device/dtype, deterministic
  settings, and export schema;
- every validation, final-test, handoff, and promotion threshold already frozen
  by repository authority.

Also bind the intended downstream route. A generation registered for
`PRECONDITIONER_FULL_PARENT_OPT` may be validated only as a preconditioner and
must carry `single_point_only_eligible=false`. Its AIMNet2 `GAU_LOOSE` handoff
profile is not a parent-gradient, geometry-accuracy, label-accuracy, or single-point promotion
threshold.

The active preconditioner generation binds one GAU_LOOSE YAML identity. Its
five AIMNet2-surface criteria are distinct from the parent handoff calibration,
which reads only the first successful energy/analytic gradient emitted by the
continuing full parent optimization. Neither handoff calibration outcome may
select a single-point-only route.

If any required threshold or identity is absent or conflicting, set the
generation to `BLOCKED_BEFORE_TRAINING`. Do not infer or tune it.

## 2. Keep epoch 0 selectable

Evaluate the unchanged base AIMNet2 as `epoch_0000` on the exact validation
inputs, aggregation rules, and complete intended-use path used for fine-tuned
checkpoints. Keep it eligible for selection.

Select a fine-tuned checkpoint only if it satisfies every frozen validation
gate relative to epoch 0. If no checkpoint does, select epoch 0 as the no-op
result, mark the fine-tune generation `VALIDATION_REJECTED`, and do not consume
final-test. Never force selection of an epoch merely because training ran.

When no fine-tuned checkpoint qualifies and epoch 0 would be the no-op fallback,
epoch 0 must also pass every absolute structure, parent-gradient, endpoint,
label, and applicability gate required for the intended use. If it does not,
record rejection_reason_code=`BASELINE_INELIGIBLE`, keep the fine-tune
generation `VALIDATION_REJECTED`, and do not describe the unchanged base as an
eligible replacement. This fallback check does not disqualify a fine-tuned
checkpoint that independently passes every absolute and relative frozen gate.
Selecting epoch 0 as a no-op leaves the base deployment unchanged; it does not
freeze epoch 0 as a new promoted generation.

Use validation only for trainable-layer, loss, optimizer, stopping,
hyperparameter, and checkpoint choices. Aggregate by InChIKey/candidate before
selection. Preserve signed differences and exact units. Apply the frozen
tie-break only after all scientific gates pass.

## 3. Enforce the generation state machine

Permit only these forward transitions:

~~~text
REGISTERED -> BLOCKED_BEFORE_TRAINING [terminal]
REGISTERED -> TRAINING_CLAIMED
TRAINING_CLAIMED -> TRAINING_FAILED [terminal]
TRAINING_CLAIMED -> TRAINING_COMPLETE
TRAINING_COMPLETE -> VALIDATION_REJECTED [terminal]
TRAINING_COMPLETE -> VALIDATION_SELECTED
VALIDATION_SELECTED -> MODEL_FROZEN
VALIDATION_SELECTED -> RETIRED [terminal]
MODEL_FROZEN -> FINAL_TEST_CONSUMED
MODEL_FROZEN -> RETIRED [terminal]
FINAL_TEST_CONSUMED -> FINAL_TEST_REJECTED [terminal]
FINAL_TEST_CONSUMED -> FINAL_TEST_ACCEPTED
FINAL_TEST_ACCEPTED -> SINGLE_POINT_ONLY_PROMOTED
FINAL_TEST_ACCEPTED -> RETIRED [terminal]
SINGLE_POINT_ONLY_PROMOTED -> SUPERSEDED [terminal]
SINGLE_POINT_ONLY_PROMOTED -> RETIRED [terminal]
~~~

Make terminal failure and rejection states immutable. Never move backward,
rewrite a result, reuse a consumed test, or tune the same generation after
final-test. A later scientific attempt is a new generation with a new ID,
manifest, output root, and unopened final-test cohort.

Bind `MODEL_FROZEN` to the selected checkpoint, exported bundle, runtime-load
audit, external physics metadata, inference protocol, complete generation
manifest, and SHA256. Freeze before making any final-test payload readable.

## 4. Isolate final-test evaluation

Run final-test in a separate evaluator process and authority boundary. The
training/checkpoint process may know only the final-test commitment and split
count; it must not mount, open, hash, validate, preprocess, or enumerate
final-test frames, targets, directories, receipts, or candidate outcomes.

Treat a final-test directory visible or mounted in the training process as
rejection_reason_code=`FINAL_TEST_ISOLATION_FAILED` even when no payload read
is reported. Block model freeze/final-test progression and map the failure by
discovery point:

~~~text
before validation selection:
  TRAINING_COMPLETE -> VALIDATION_REJECTED
after VALIDATION_SELECTED but before MODEL_FROZEN:
  VALIDATION_SELECTED -> RETIRED
after MODEL_FROZEN with independently proved zero payload access:
  MODEL_FROZEN -> RETIRED
after MODEL_FROZEN plus a consumption claim, payload access, or access uncertainty:
  MODEL_FROZEN -> FINAL_TEST_CONSUMED -> FINAL_TEST_REJECTED
~~~

Keep the cohort unconsumed only when an independent access audit proves no
payload open, hash, enumeration, preprocessing, or consumption claim. If access
cannot be disproved before MODEL_FROZEN, keep the generation on its
stage-appropriate VALIDATION_REJECTED or RETIRED path and separately mark the
entire committed cohort consumed/historical; do not fabricate a MODEL_FROZEN
transition.
The independent isolation/final-test authority, never the training process,
writes that consumption record from the sealed split registry. It may bind the
cohort commitment and registry identity without exposing payload files to the
training process.

Give the evaluator only:

```text
frozen generation manifest and bundle
unchanged base bundle
sealed final-test capability
pre-registered evaluator source/configuration
write-once result and consumption-registry destinations
```

Before the first final-test payload read, append an irreversible consumption
record containing generation ID, cohort commitment, candidate identities,
bundle SHA256, evaluator SHA256, timestamp, and claim identity. Treat a crash,
timeout, partial read, malformed result, or evaluator failure after that claim
as consumed. Never rerun or reuse those candidates.

For conservative consumption caused by pre-evaluator isolation failure, write
an immutable isolation-invalidation receipt instead. Bind the generation,
cohort commitment, sealed split-registry identity, isolation-audit/accessor
identity, evidence, timestamp, and reason code; set evaluator SHA256 to
`not_applicable`. The registry authority maps the commitment to candidates
without exposing payloads to training.

Evaluate the fine-tuned bundle and unchanged base on identical final-test
inputs. Final-test may accept or reject the already frozen generation; it may
not select a checkpoint, change a threshold, alter an optimizer, or motivate a
same-generation retry. Mark every revealed candidate permanently
`consumed/historical` in the append-only registry.

## 5. Distinguish three scientific statuses

Use these statuses independently:

1. `TRAINING_COMPLETE`: a loadable artifact was produced; no scientific claim.
2. `SCIENTIFICALLY_VALIDATED`: validation selected and froze one generation;
   final-test and promotion remain unavailable.
3. `SINGLE_POINT_ONLY_PROMOTED`: the frozen generation passed its one-time
   final-test and every gate in `aimnet2-handoff-promotion.md`.

Never derive status 2 from status 1 or status 3 from status 2. Keep
`production_accepted` and `production_label_inserted` separate and false unless
a later, explicit production authority changes them.

## 6. Close every generation with evidence

Write immutable claims, transitions, metrics, checkpoint/export receipts,
final-test consumption, rejection reasons, and terminal state. Compare the
bundle against the base numerically for energy and forces and verify runtime
external Coulomb and D3 behavior; metadata equality alone is insufficient.

Use stable rejection_reason_code values at minimum for
`FINAL_TEST_ISOLATION_FAILED`, `BASELINE_INELIGIBLE`,
`PARENT_GRADIENT_FAILED`, `GEOMETRY_GATE_FAILED`,
`ENDPOINT_PENALTY_FAILED`, and `SIGNED_LABEL_ERROR_FAILED`. Preserve
the measured signed values, units, thresholds, and evidence identities beside
each code.
