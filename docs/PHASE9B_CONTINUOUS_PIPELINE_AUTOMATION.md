# Phase 9B Continuous Compute and AIMNet2 Fine-Tune Automation

## Scope

This document freezes the non-production automation boundary for the
preregistered nine-candidate parent-level data collection and the single
AIMNet2 fine-tuning attempt.  The automation is `science_pilot_only`; it cannot
write production labels, consume a production permit, change runner v9, add a
candidate, retry a failed candidate, or run a speed benchmark.

The top-level orchestrator is deliberately thin.  It does not implement
chemistry, frame generation, D3 subtraction, dataset construction, or model
training.  Those actions remain owned by the existing bounded components:

| Owner | Exclusive responsibility |
| --- | --- |
| `phase9b_parent_level_autofill.py` | One lane's ordered claims, assignments, fixed-resource launches, and queue terminal |
| parent-level worker | Geometry optimization and immutable parent-level energy/force frames |
| `phase9b_aimnet2_finetune_watch.py` | 9/9 and four-queue gate, one dataset claim, resource gate, one training claim, final terminal |
| `phase9b_aimnet2_training_dataset.py` | Independent D3 recomputation/subtraction and split-safe dataset |
| `phase9b_aimnet2_finetune.py` | Train/validation-only one-shot fine-tuning, validation selection, and bundle freeze at `MODEL_FROZEN` |
| `phase9b_aimnet2_final_test.py` | Separate post-freeze final-test consumer; writes the irreversible claim before payload access |
| `phase9b_pipeline_orchestrator.py` | Configuration binding, watcher start/adoption, and unified read-only snapshots |

## Frozen state machine

```text
BIND_CONFIG
→ RUN_LANES
→ AUDIT_RESULTS
→ WAIT_FOR_9_OF_9_PASS
→ BUILD_DATASET_ONCE
→ WAIT_FOR_RESOURCES
→ TRAIN_ONCE
→ VALIDATE_AND_FREEZE
→ COMPLETE
```

The orchestrator derives this state from durable files written by the owning
component.  It never advances a scientific gate by inference from logs, PID
existence, elapsed time, or file modification time.

For each lane, the only legal lifecycle is:

```text
PENDING → CLAIMED → RUNNING → TERMINAL → AUDITED → next preregistered candidate
```

The lane watcher owns the `CLAIMED` transition.  The orchestrator must never
create a lane claim or assignment itself.

## Modes

`validate` checks the public contract, source/config identities, the four
disjoint CPU sets, candidate coverage, and all fail-closed flags.  It performs
no external action.

`snapshot` reads an existing deployment and prints a canonical unified status.
It creates no file and starts no process.

`run --mode start` creates one new orchestrator state root, then starts exactly
four lane watchers and exactly one fine-tune watcher.  Each watcher launch has
an exclusive orchestrator claim and assignment.  Existing watcher state roots
are a hard error, so `start` cannot duplicate a deployment.

`run --mode adopt` creates one new orchestrator observation root and validates
the already-existing queue bindings and fine-tune watcher binding.  It launches
nothing.  This is the only mode suitable for the currently running v002
deployment.

The public config records the already-running watcher source digests as
`adopt_compatible_sha256`.  Compatibility applies only to `snapshot` and
`adopt`; `start` requires the new fail-closed sources that audit exit code,
PASS result, both endpoint manifests, the route manifest, the exact frame set,
and process cleanup before the next claim.  Adoption does not silently replace
or mutate an old watcher.

An existing orchestrator state root is never overwritten or reused.  Restarting
the command cannot relaunch a candidate or training attempt because the child
watchers own those immutable claims and their state roots are also unique.

## Frozen lanes

The lane resource sets are disjoint and together cover logical CPUs `0-111`.
The orchestrator validates, but never changes, these values.

| Lane | CPUs | Threads | Memory MB | Ordered preregistered work |
| --- | --- | ---: | ---: | --- |
| A | `0,2-27` | 27 | 64000 | VNY → VPA → RBK after the GTHO predecessor |
| B | `28-55` | 28 | 64000 | RAT after completed ACG |
| C | `1,56-83` | 29 | 40000 | CLX → KZY after the IJW predecessor |
| D | `84-111` | 28 | 40000 | PDIY → RME after the HQK predecessor |

No queue is extended after launch.  A candidate failure blocks collection and
training; it is not replaced.  The orchestrator does not stop other already
running lanes, retry the failed lane, or edit any queue.

## Evidence and exact-once rules

Every orchestrator file is exclusive-created, fsynced, reread, and SHA256
bound.  The state root contains:

```text
binding.json
children/
    lane_<id>_claim.json
    lane_<id>_assignment.json
    finetune_claim.json
    finetune_assignment.json
adoptions/
    lane_<id>.json
    finetune.json
snapshots/
    000000.json
    ...
terminal.json
```

Only one of `children/` or `adoptions/` is populated for a run.  Snapshots bind
queue state, latest lane assignment/result, fine-tune watcher state, candidate
and frame counts already published by the fine-tune watcher, dataset/training
claims, and final terminal.  They are observational evidence, not authority to
perform the underlying transition.

The orchestrator does not delete files, clean VASP outputs, signal VASP, alter
process affinity, or terminate adopted processes.  `WAVECAR` and `CHGCAR` are
outside this automation's namespace.

## Failure semantics

- A malformed or mismatched public contract fails before creating state.
- A queue binding mismatch fails adoption and launches nothing.
- A fine-tune config or helper binding mismatch fails adoption and launches
  nothing.
- A newly started watcher that exits without its durable terminal is recorded
  as `WATCHER_EXITED_WITHOUT_TERMINAL`; it is not restarted.
- Any non-`PASS` fine-tune watcher terminal becomes the orchestrator terminal
  without reinterpretation.
- Model freeze `PASS` ends all orchestrator monitoring.  No benchmark or second
  cohort is launched.

## Deployment boundary

This source/config change does not deploy, restart, replace, or signal the
currently running four lanes or fine-tune watcher.  The current deployment may
later be observed with `run --mode adopt`; `start` is reserved for a genuinely
new, absent deployment root.

## Command surface

Local contract validation is portable and performs no remote action:

```bash
python scripts/phase9b_pipeline_orchestrator.py validate \
  --config docs/PHASE9B_PIPELINE_CONFIG_V001.json \
  --repo-root .
```

On the compute host, `snapshot` is read-only.  Deployment-specific absolute
roots and interpreters are supplied at invocation time rather than committed:

```bash
python phase9b_pipeline_orchestrator.py snapshot \
  --config <PIPELINE_CONFIG> \
  --repo-root <ORCHESTRATOR_DRIVER_ROOT> \
  --runs-root <RUNS_ROOT> \
  --autofill-driver <AUTOFILL_DRIVER_ROOT> \
  --finetune-driver <FINETUNE_DRIVER_ROOT> \
  --gpupyscf-python <GPUPYSCF_PYTHON> \
  --mlff-python <MLFF_PYTHON>
```

`run` takes the same paths plus exactly one explicit mode:

```text
--mode adopt  # observe the current immutable deployment; launch nothing
--mode start  # only for a new deployment whose five watcher roots are absent
```
