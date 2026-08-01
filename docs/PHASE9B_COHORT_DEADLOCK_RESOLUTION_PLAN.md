# Phase 9B Cohort Deadlock Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the permanently unsatisfiable `WAIT_FOR_9_OF_9_PASS` gate with a mechanically derived, hash-frozen, smaller cohort registry (split v003 + generation v003) so that the science-pilot pipeline can advance past `AUDIT_RESULTS` without retrying a candidate, substituting a candidate, or weakening the exact-match property of the gate.

**Architecture:** The deadlock is resolved by *shrinking the frozen cohort registry*, not by loosening the gate that reads it. A new bounded writer (`scripts/phase9b_cohort_degradation.py`) ingests transcribed terminal evidence from the four lanes, derives the survivor set deterministically, fails closed when the cohort is not quiescent or when the sealed final-test cohort is damaged, and emits two immutable documents: a superseding split registry `PHASE9B_AIMNET2_FINETUNE_SPLIT_V003.json` and a supersession record that accounts for every withdrawn InChIKey with a reason code. Every downstream reader is then re-bound to the new hashes, and the orchestrator gains a *withdrawal reconciliation* rule (`lane queue candidate set == split candidate set ⊎ withdrawn set`) so the four already-bound lane queue files stay byte-identical and no immutable lane evidence is rewritten. The `collection_complete` predicate keeps its exact-match form (`complete == len(candidates)`); only `len(candidates)` changes.

**Tech Stack:** Python 3.11-target stdlib + numpy (scripts are standalone `scripts/*.py` modules loaded by path in tests), pytest, ruff, mypy strict. No new dependencies.

## Global Constraints

Every task inherits these. They are copied verbatim from repository authority.

- `science_pilot_only: true` — this automation "cannot write production labels, consume a production permit, change runner v9, add a candidate, retry a failed candidate, or run a speed benchmark" (`docs/PHASE9B_CONTINUOUS_PIPELINE_AUTOMATION.md:5-9`).
- `production_accepted: false`, `production_label_insertion: false`, `production_permit: false`, `retry: false`, `candidate_replacement: false`, `speed_benchmark_after_freeze: false` — machine-checked booleans in `docs/PHASE9B_PIPELINE_CONFIG_V001.json:3-9`, enforced by `scripts/phase9b_pipeline_orchestrator.py:198-204` (`_require_boolean`). **No task in this plan may flip any of them.**
- "An attempted candidate or model generation is never silently replaced. Failed, partial, timed-out, manifest-open, or structurally invalid work remains diagnostic and is not admitted as reference data." (`.codex/skills/plan-nhc-aimnet2-workflow/references/workflow-contract.md:68-70`)
- "Use InChIKey as the permanent split unit. Keep both endpoints and every frame of one InChIKey in one split." … "Accumulate permanently assigned cohorts; never move an InChIKey between splits." (`reference-data-contract.md:79-80`, `workflow-contract.md:43`)
- "No state authorizes its successor. Every transition requires immutable input identities, a unique writer, independently recomputable evidence, a terminal classification, and one exact next permitted action." (`workflow-contract.md:26-27`)
- "If a required numeric threshold has no frozen authority, present an evidence-backed calibration design and request confirmation. Do not invent a threshold or consume final-test data to choose it." (`workflow-contract.md:62-63`)
- Do **not** modify `PHASE_STATUS.md` in any task of this plan. Another agent owns that file concurrently. The status entry for this work is written separately by its owner after Task 8 lands.
- Do **not** modify `scripts/` runner v9 or any of the 71 production labels.
- Do **not** SSH, do **not** start or stop any process, do **not** touch the remote host. Every task in this plan is repository-local. Remote observation enters the repo only as a transcribed, hashed evidence document (Task 1) produced by an authorized human operator.
- Gate command (all four must pass before every commit):
  `python3 -m pytest -q && python3 -m ruff check . && python3 -m ruff format --check . && python3 -m mypy`
  Use CPython 3.14 (`python3`, currently 3.14.3). The repo `.venv` is CPython 3.13.12 and is known to produce spurious failures in the sibling repository; prefer the system interpreter for the gate.

---

## Part I — Verified situation

All facts below were read directly from the working tree at
`/Users/cc/nhc-deprot-ranker-science-pilot`, branch `agent/phase9b-science-pilot`,
HEAD `befa889`.

### I.1 The frozen state machine

`docs/PHASE9B_CONTINUOUS_PIPELINE_AUTOMATION.md:28-38`:

```text
BIND_CONFIG → RUN_LANES → AUDIT_RESULTS → WAIT_FOR_9_OF_9_PASS
→ BUILD_DATASET_ONCE → WAIT_FOR_RESOURCES → TRAIN_ONCE → VALIDATE_AND_FREEZE → COMPLETE
```

Derived in code at `scripts/phase9b_pipeline_orchestrator.py:676-693`.

### I.2 The gate that cannot be satisfied

`scripts/phase9b_aimnet2_finetune_watch.py:212-214`:

```python
"collection_complete": not failed_queue_states
and complete == len(candidates)
and all(item["exhausted"] for item in queue_states),
```

`len(candidates)` is the length of the v002 split registry, validated to equal
`data.required_candidate_count` at `scripts/phase9b_aimnet2_finetune_watch.py:120`;
that value is `9` in `docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V002.json:18`.
The orchestrator independently hard-asserts nine at
`scripts/phase9b_pipeline_orchestrator.py:204` and `:302-307`.

The frozen cohort (`docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002.json`,
sha256 `772094bc08012f8f40c76994a1600985f11a1956bef66d2c7710006b3aa0b995`,
recomputed and confirmed):

| Split | InChIKey | electrons | cation atoms |
| --- | --- | --- | --- |
| train | `ACGCNTKELWXJPN-UHFFFAOYSA-N` | 72 | 19 |
| train | `CLXFIGGGSODORK-UHFFFAOYSA-N` | 114 | 33 |
| train | `PDIYCCLDBKWBTK-UHFFFAOYSA-N` | 100 | 29 |
| train | `RBKFFSUUCLDQER-UHFFFAOYSA-N` | 120 | 38 |
| train | `VNYHGZAUUQMMDL-UHFFFAOYSA-N` | 68 | 16 |
| validation | `KZYKDQNIIMATMJ-UHFFFAOYSA-N` | 100 | 29 |
| validation | `RMEQTBVGGNKAEQ-UHFFFAOYSA-N` | 76 | 23 |
| final_test | `RATKDJDMBGPDPZ-UHFFFAOYSA-N` | 94 | 17 |
| final_test | `VPAFDQIFHJWCBK-UHFFFAOYSA-N` | 124 | 36 |

`CLXFIGGGSODORK-UHFFFAOYSA-N` reached a terminal timeout. Retry is not
authorized (`retry: false`; `workflow-contract.md:68`), replacement is not
authorized (`candidate_replacement: false`; `forbidden: ["candidate_replacement"]`
at `docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V002.json:50-57`). Therefore
`complete` can never reach 9 and `failed_queue_states` can never be empty.

### I.3 The lane loop is strictly sequential — the loss is larger than one candidate

This is the single most important finding of the investigation and it changes
the shape of every option below.

`scripts/phase9b_parent_level_autofill.py:521-539` iterates the lane queue in
order. Before launching queue entry `index`, it audits the *predecessor* route.
On audit failure it writes `lane_terminal.json` with
`"outcome": "PREDECESSOR_AUDIT_FAILED"`, `"next_candidate_started": False`,
`"retry": False`, and **returns 2 without launching entry `index` or anything
after it.**

Lane composition (`docs/PHASE9B_PIPELINE_CONFIG_V001.json:56-129`):

| Lane | CPUs | Queue order |
| --- | --- | --- |
| a | `0,2-27` | `VNYHGZAUUQMMDL` → `VPAFDQIFHJWCBK` (final_test) → `RBKFFSUUCLDQER` |
| b | `28-55` | `ACGCNTKELWXJPN` → `RATKDJDMBGPDPZ` (final_test) |
| c | `1,56-83` | `CLXFIGGGSODORK` → `KZYKDQNIIMATMJ` (validation) |
| d | `84-111` | `PDIYCCLDBKWBTK` → `RMEQTBVGGNKAEQ` (validation) |

Consequences that must be verified before any file is written:

1. **`CLXFIGGGSODORK` is lane c entry 0.** Its timeout terminates lane c before
   entry 1. `KZYKDQNIIMATMJ` — one of only two validation InChIKeys — was
   therefore very likely **never launched**. The survivor count is probably 7,
   not 8, and validation probably collapses to a single molecule
   (`RMEQTBVGGNKAEQ`).
2. **`RBKFFSUUCLDQER` is lane a entry 2**, yet
   `docs/PHASE9B_RBK_THROUGHPUT_CONTINUATION_V001.md:5-8` describes it as
   "the one pre-registered and **never-claimed** candidate" being run as a
   *separate* continuation. Under the sequential loop, "never-claimed" implies
   lane a terminated at entry 0 or entry 1. Entry 1 is
   `VPAFDQIFHJWCBK-UHFFFAOYSA-N`, a **sealed final-test candidate**.
3. If `VPAFDQIFHJWCBK` did not complete, the sealed final-test cohort is
   damaged. `scripts/phase9b_aimnet2_final_test.py:169` requires
   `candidate_count == 2` in the final-test dataset manifest, and
   `scripts/phase9b_aimnet2_training_dataset.py:558-561` derives that count from
   the registry. In that case **no option in this plan reaches
   `SINGLE_POINT_ONLY_PROMOTION`**, and the only lawful continuation is a new
   generation with a new, unopened final-test cohort
   (`model-generation-contract.md:76-79`), which is out of scope here and needs
   fresh user authorization and fresh compute.

**These three points are structural inferences from local code plus local
documents. They are not remote observations.** Task 1 exists precisely to turn
them into hashed evidence before anything is frozen.

### I.4 `RBKFFSUUCLDQER` does not unlock the gate even if it passes

`docs/PHASE9B_RBK_THROUGHPUT_CONTINUATION_V001.md:5-9`: the continuation
"is not a retry or replacement for the timed-out `CLXFIGGGSODORK-UHFFFAOYSA-N`
route, does not add a candidate, and **does not reopen the failed
nine-candidate training cohort**." Its split is recorded as
`train (diagnostic only; current cohort remains blocked by CLX timeout)`
(`:26`).

It is also the largest train molecule in the cohort — 120 electrons, 38 cation
atoms versus CLX's 114 / 33 — running under the same `86400 s` hard wall with
"no retry or continuation … authorized" (`:33`). A second timeout is the modal
outcome.

### I.5 The v002 watcher deployment is almost certainly already terminal

`scripts/phase9b_aimnet2_finetune_watch.py:441-451`: as soon as a snapshot has
non-empty `failed_candidates` or `failed_queue_states`, the watcher writes
`terminal.json` with `outcome="COLLECTION_FAILED"`, `training_started: False`,
and returns 2. `derive_pipeline_state`
(`scripts/phase9b_pipeline_orchestrator.py:676-681`) then reports
`TERMINAL_FAILED`, not `WAIT_FOR_9_OF_9_PASS`.

State roots are write-once: `state_root.mkdir(mode=0o700, parents=False, exist_ok=False)`
at `scripts/phase9b_aimnet2_finetune_watch.py:389`, and every evidence file is
written with `O_EXCL` (`write_new`, `:65-77`). The existing watch state root
`phase9b_aimnet2_finetune_watch_v002` therefore cannot be reused or repaired.
**Any resolution requires a brand-new watch state root, dataset root, training
root, and final-test root — i.e. a genuinely new generation.** This is
consistent with `model-generation-contract.md:76-79`.

### I.6 A second, independent deadlock sits behind the first

Even a perfect 9/9 pass would not train. `scripts/phase9b_aimnet2_finetune.py:111-124`:

```python
if not isinstance(readiness, dict) or readiness.get("state") != "REGISTERED":
    raise FineTuneError("generation is BLOCKED_BEFORE_TRAINING")
for gate in (
    "final_test_isolation_implemented",
    "final_test_evaluator_scientifically_complete",
    "epoch_zero_selection_implemented",
    "validation_selection_gates_frozen",
    "baseline_eligibility_gates_frozen",
    "final_test_acceptance_gates_frozen",
    "stopping_handoff_promotion_gates_frozen",
):
    if readiness.get(gate) is not True:
        raise FineTuneError(f"generation readiness gate is not frozen: {gate}")
```

`docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V002.json:8-24` has
`state: "BLOCKED_BEFORE_TRAINING"` and six unfrozen gates.

**Hazard — the one-shot attempt can be destroyed.** The watcher writes the
irreversible `training_claim.json` *before* running the trainer
(`scripts/phase9b_aimnet2_finetune_watch.py:534-560` region), and
`single_training_attempt: true` / `retry: false` mean the claim is not
reusable. Deploying a cohort fix while the six readiness gates are still
unfrozen would burn the single authorized training attempt on a guaranteed
`FineTuneError`. **Task 8 therefore ends at repository freeze, not at
deployment, and this plan explicitly forbids launching the v003 watcher until
the readiness blockers are separately frozen.**

---

## Part II — Option evaluation

Each option is assessed on the four dimensions requested: files touched,
sha256 rebinds invalidated, effect on existing immutable evidence, and
final-test contamination risk.

### Option (a) — Freeze a v003 split with the reduced cohort

Freeze a superseding registry containing only the InChIKeys that reached a
`PASS` terminal, keeping every surviving InChIKey in its original split
(deletions only, never moves), and record the degradation and its statistical
cost explicitly.

**Files to change**

| File | Change |
| --- | --- |
| `docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V003.json` | new; schema `phase9b-aimnet2-finetune-split-v003` |
| `docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002_SUPERSESSION.json` | new; one reason code per withdrawn InChIKey |
| `docs/PHASE9B_COHORT_DEGRADATION_EVIDENCE_V001.json` | new; transcribed lane/route terminal receipts |
| `docs/PHASE9B_COHORT_SELECTION_FLOOR_V001.json` | new; user-frozen minimum per-split survivor counts |
| `scripts/phase9b_cohort_degradation.py` | new; the unique writer for the two documents above |
| `scripts/phase9b_aimnet2_training_dataset.py:20` | `SPLIT_SCHEMA` → `…-v003` |
| `scripts/phase9b_aimnet2_final_test.py:20` | `SPLIT_SCHEMA` → `…-v003` |
| `scripts/phase9b_aimnet2_finetune.py:31,165,193` | `SPLIT_SHA256` → v003 digest; `candidate_count != 7` and `len(candidates) != 7` → new development count |
| `scripts/phase9b_aimnet2_finetune_watch.py:459` | hard-coded `phase9b_aimnet2_final_test_v002` root name → v003 |
| `scripts/phase9b_pipeline_orchestrator.py:204,302-312` | nine-assertions replaced by withdrawal reconciliation |
| `docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V003.json` | new; `split_path`/`split_sha256`/`required_candidate_count` rebound, new state roots |
| `docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json` | new; new `generation_id`, new development counts, re-sealed commitment |
| `docs/PHASE9B_PIPELINE_CONFIG_V002.json` | new; program digests, `withdrawn_candidates`, v003 fine-tune bindings |
| `docs/PHASE9B_CONTINUOUS_PIPELINE_AUTOMATION.md:28-38` | state name update |
| `tests/test_phase9b_*.py` (4 files) + 1 new | rebind assertions |

**sha256 bindings invalidated and needing recomputation**

1. Split registry digest `772094bc…` → v003 digest. Referenced at
   `docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V002.json:17`,
   `docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V002.json:40`,
   `docs/PHASE9B_AIMNET2_FINETUNE_CONFIG_V001.json:44`, and hard-coded at
   `scripts/phase9b_aimnet2_finetune.py:31`.
2. `scripts/phase9b_aimnet2_finetune.py` source digest
   `88bc384f…` → `programs.finetune.sha256`.
3. `scripts/phase9b_aimnet2_training_dataset.py` digest `98cf4282…`.
4. `scripts/phase9b_aimnet2_final_test.py` digest `ad84fa46…`.
5. `scripts/phase9b_aimnet2_finetune_watch.py` digest `c1b9e408…`.
6. `scripts/phase9b_pipeline_orchestrator.py` — not self-bound, but its
   behaviour change forces new tests.
7. The orchestration config digest `09d18c62…` → `fine_tune.config_sha256`.
8. The model-generation config digest `22b377ed…` → `fine_tune.training_config_sha256`.
9. The pipeline config digest `8c41b1dd…`, asserted literally in
   `tests/test_phase9b_pipeline_orchestrator.py:96-98`.
10. **Not invalidated, deliberately:** the four lane queue digests
    (`20ba326d…`, `a91b43e4…`, `d7a515a3…`, `45e091c3…`). The design keeps the
    queue files byte-identical so the already-written remote
    `queue_binding.json` files continue to verify at
    `scripts/phase9b_aimnet2_finetune_watch.py:181-184`.

**Effect on existing immutable evidence**

Zero rewrites. No lane state root, `queue_binding.json`, `lane_terminal.json`,
`queue_exhausted.json`, route `result.json`, or the v002 watcher `terminal.json`
is touched, read-modified, or invalidated. The v002 split, orchestration
config, model-generation config, and pipeline config all remain in the tree as
superseded-but-intact documents, matching the precedent set by
`docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V001_REJECTION.json`. The v003 deployment
consumes the v002 lane evidence read-only.

Note the one asymmetry with that precedent: v001 was rejected *before launch*
(`"candidate_launched": false`, `"calculation_started": false`). v002 has
launched, burned compute, and produced terminal receipts, so the v003 record
must be classified as a **degradation**, not a rejection, and must carry the
statistical-power statement required by `workflow-contract.md:43`.

**Final-test contamination**

Low, and mechanically checkable. `included_splits` at
`scripts/phase9b_aimnet2_training_dataset.py:463` keeps `final_test` out of the
development scope, and `scripts/phase9b_aimnet2_finetune.py:138-140` rejects any
training config that names a final-test path. The residual risk is the
**re-sealing** of `sealed_final_test_commitment.split_registry_sha256`
(`docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V002.json:39-42`,
written from the live registry at
`scripts/phase9b_aimnet2_training_dataset.py:558-561`, consumed irreversibly as
`cohort_commitment_sha256` at `scripts/phase9b_aimnet2_final_test.py:133`).
Re-sealing to a new digest is only safe if the `final_test` array is proven
byte-identical between v002 and v003. Task 3 enforces exactly that with a
canonical-JSON equality test, and the supersession record binds the old
commitment digest to the new one so the chain stays traceable.

**Verdict:** viable. The gate keeps its exact-match form, the authority stays in
a hashed registry, and every deletion is accounted for.

### Option (b) — Authorize a replacement candidate

**Files to change:** everything in option (a), **plus** flipping
`candidate_replacement` to `true` in the pipeline config
(`docs/PHASE9B_PIPELINE_CONFIG_V001.json:9`) and removing
`"candidate_replacement"` from `forbidden`
(`docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V002.json:52`), **plus** a new
lane queue file with a new queue digest, a new lane state root, and a new
86400 s P01 route.

**sha256 bindings invalidated:** all of option (a), **plus** at least one lane
queue digest, which breaks the correspondence enforced at
`scripts/phase9b_pipeline_orchestrator.py:315-319`
(`fine-tune queue hashes differ from lane hashes`) against a
`queue_binding.json` that a terminated lane has already written.

**Effect on existing immutable evidence:** this is where it fails. The
substitute must run on a lane, and every lane already holds a
`queue_binding.json` bound to its v002 queue digest. Introducing a substitute
means either rewriting that binding — forbidden — or standing up an entirely
new fifth lane outside the frozen four-lane, 112-CPU partition, which
`scripts/phase9b_pipeline_orchestrator.py:255-258` and `:298-300`
(`lane count must remain four`, `frozen lanes must cover logical CPUs 0-111
exactly`) reject.

**Final-test contamination:** highest of the three. `_candidate_set_from_split`
(`scripts/phase9b_pipeline_orchestrator.py:159-179`) checks only exact InChIKey
disjointness. It performs no family, scaffold, or substituent check. The
geometry-collision guard in the dataset builder
(`scripts/phase9b_aimnet2_training_dataset.py:481-489`,
`identical geometry crosses molecule split`) only compares geometries *inside*
`included_splits`, and development scope excludes `final_test` entirely — so a
substitute that is a near-duplicate of `RATKDJDMBGPDPZ` or `VPAFDQIFHJWCBK`
would **not** be caught by any existing check. Selecting the substitute also
requires re-running the diversity selection described in
`workflow-contract.md:39-43` without looking at final-test outcomes, on a pool
whose remaining members are, by construction, the ones the selection already
declined.

**Additional cost:** it does not actually fix the problem. Replacing `CLX`
leaves `KZYKDQNIIMATMJ` (validation, never launched under I.3) still missing, so
a *second* substitution would be needed. And the timeouts are size-correlated —
CLX at 33 atoms timed out and RBK at 38 atoms is running against the same wall —
so a substitute large enough to be scientifically comparable is likely to time
out too, producing the identical deadlock one cycle later at greater cost.

**Verdict: reject.** It requires flipping a fail-closed boolean that exists
specifically to prevent it, it collides with immutable lane bindings, it is the
only option with an uncovered final-test leakage path, and it does not resolve
the deadlock in one move.

### Option (c) — Replace 9/9 with a frozen N-of-M gate

**Files to change:** `scripts/phase9b_aimnet2_finetune_watch.py:212-214`
(predicate) and `:120` (count check), the orchestration JSON (new
`minimum_passing_candidate_count`), `scripts/phase9b_pipeline_orchestrator.py:204,302-307`,
`docs/PHASE9B_CONTINUOUS_PIPELINE_AUTOMATION.md:31`, and three test files. The
split registry is *not* touched.

**sha256 bindings invalidated:** fewer than option (a) — the split digest
`772094bc…` survives, so `sealed_final_test_commitment`,
`scripts/phase9b_aimnet2_finetune.py:31,133-137`, and
`docs/PHASE9B_AIMNET2_FINETUNE_CONFIG_V001.json:44` all stay valid. The watcher,
orchestrator, and both configs still need rebinding. **This is option (c)'s only
genuine advantage.**

**Effect on existing immutable evidence:** no rewrites, but it destroys a
property rather than a file. `complete >= N` is satisfiable by *many different*
survivor sets. The identity of the trained cohort would no longer be determined
by a hashed registry, so `manifest.split_sha256` would no longer let a third
party recompute which molecules were trained on. That is a direct hit on
"independently recomputable evidence" (`workflow-contract.md:26-27`) and on
"permanent split-registry binding" (`reference-data-contract.md:108`).

**Final-test contamination:** the seal survives on paper, but the mechanism
that makes the seal meaningful — a registry that names exactly the trained
cohort — is what the change removes.

**Fatal technical objection.** An N-of-M gate does not unblock the pipeline. Two
reasons:

1. The deadlock's proximate cause is `not failed_queue_states`, not
   `complete == len(candidates)`. Lane c holds a `lane_terminal.json`, so
   `failed_queue_states` is non-empty regardless of N. Unblocking would require
   also weakening the lane-terminal check — and that check is precisely what
   detects the never-launched candidates from I.3. Weakening it means training
   on a cohort whose composition nobody recorded.
2. Even if the gate passed, `BUILD_DATASET_ONCE` fails immediately. `assemble`
   (`scripts/phase9b_aimnet2_training_dataset.py:468-479`) iterates **every**
   assignment from the split, and `load_candidate_frames`
   (`:328-331`) raises `DatasetAssemblyError` on the first missing or non-`PASS`
   route root. With the registry still listing nine, the missing CLX route
   aborts assembly. Making the builder skip missing candidates would mean the
   development dataset's `candidate_count` is no longer determined by the
   registry — the worst outcome available.

**Verdict: reject.** It moves the deadlock one state downstream while
permanently degrading the evidence model.

---

## Part III — Recommendation

**Adopt option (a), in the hardened form specified below. Reject (b) and (c).**

Hardening rules, all enforced by tests in Tasks 1–7:

- **R1 — Derive, never choose.** The survivor set is computed mechanically from
  transcribed terminal receipts. No human picks who stays.
- **R2 — Quiescence required.** If any route in the v002 cohort is still
  in flight (notably `RBKFFSUUCLDQER`), derivation fails closed with
  `COHORT_NOT_QUIESCENT`. A cohort cannot be frozen around a running process.
- **R3 — Deletions only, never moves.** Every surviving InChIKey keeps its v002
  split. Enforced by a per-candidate assertion, satisfying
  `workflow-contract.md:43`.
- **R4 — The seal is inviolable.** If either final-test InChIKey is not a
  survivor, derivation fails closed with `SEALED_FINAL_TEST_COHORT_DEGRADED`
  and this plan terminates. The `final_test` array must be canonically
  byte-identical between v002 and v003.
- **R5 — Queues are untouched.** The four lane queue files and their digests
  stay byte-identical. The orchestrator reconciles
  `queue set == split set ⊎ withdrawn set` instead of demanding equality.
- **R6 — The gate keeps exact-match semantics.** `complete == len(candidates)`
  is unchanged; only `len(candidates)` shrinks. `failed_queue_states` and
  `exhausted` handling are unchanged in kind — a lane terminal that is *already
  accounted for* in the withdrawal registry is the only thing that becomes
  admissible, and it must match by root and expected candidate.
- **R7 — Schema bump, not silent reuse.** The split schema becomes
  `phase9b-aimnet2-finetune-split-v003` so a v002-era reader physically cannot
  consume the degraded cohort.
- **R8 — New generation, new roots.** `generation_id`
  `phase9b-aimnet2-nhc-p01-v003`, new dataset/training/final-test/watch roots,
  per `model-generation-contract.md:76-79` and I.5.
- **R9 — Floors are user-frozen, not invented.** Per
  `workflow-contract.md:62-63`, the minimum per-split survivor counts are read
  from a signed document, not chosen by the implementer.
- **R10 — Freeze only; do not deploy.** Because of I.6, no watcher is launched
  by this plan.

Why (a) over the alternatives, in one line each: (b) requires flipping a
fail-closed boolean and still leaves the validation gap; (c) preserves fewer
hashes but destroys registry-determined cohort identity *and* does not actually
unblock `BUILD_DATASET_ONCE`; (a) is the only option where the thing that
changes is the *recorded scientific claim* rather than the *machinery that
verifies it*.

---

## Part IV — What this plan does and does not achieve

This section is mandatory reading before executing any task. It exists because
the mechanical result of this plan is easy to mistake for the scientific goal.

**`workflow-contract.md:43`, verbatim:**

> A 5 train / 2 validation / 2 final-test cohort is a pilot cohort. It can test
> mechanics and expose large failures, but it cannot establish a general
> stopping rule, general single-point-only eligibility, or statistical
> performance across the NHC domain. Accumulate permanently assigned cohorts;
> never move an InChIKey between splits.

The stated user goal is AIMNet2 pre-optimization handing off to PySCF
Parent-Level P01 single points, ending in `SINGLE_POINT_ONLY_PROMOTION`.

**What this plan achieves:** the pipeline stops being permanently stuck. The
state machine can leave `AUDIT_RESULTS`, the dataset can be assembled, and the
degradation is recorded in hashed, recomputable form with every withdrawn
molecule accounted for. That is a real and necessary result — an
un-deadlocked, honestly-documented pipeline.

**What this plan does not achieve, and cannot:**

1. **It weakens the cohort, it does not repair it.** The contract already
   declares 5/2/2 insufficient for a general claim. This plan produces at best
   4/2/2 and realistically 3/1/2 (see I.3). Every statement made about the
   original cohort's insufficiency applies *more strongly* to the degraded one.
2. **Validation may collapse to one InChIKey.** `model-generation-contract.md:47-50`
   requires aggregation by InChIKey before checkpoint selection. With one
   validation molecule, checkpoint selection is a single-molecule decision and
   `validation_weighted_loss`
   (`docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V002.json:77-82`) carries
   essentially no generalization signal. This is why R9 requires a user-frozen
   floor rather than an implementer's judgement.
3. **Training is still blocked by six independent readiness gates** (I.6). This
   plan does not touch, and must not touch,
   `EPOCH_ZERO_SELECTION_NOT_IMPLEMENTED`,
   `FINAL_TEST_EVALUATOR_INCOMPLETE`,
   `VALIDATION_SELECTION_GATES_NOT_FROZEN`,
   `BASELINE_ELIGIBILITY_GATES_NOT_FROZEN`,
   `FINAL_TEST_ACCEPTANCE_GATES_NOT_FROZEN`, or
   `STOPPING_HANDOFF_PROMOTION_GATES_NOT_FROZEN`. After this plan the pipeline
   advances to `BUILD_DATASET_ONCE` and then blocks again at `TRAIN_ONCE`. That
   second blocker is a separate work item requiring frozen numerical thresholds
   that do not yet exist in repository authority.
4. **`SINGLE_POINT_ONLY_PROMOTION` remains unreachable.** Per
   `workflow-contract.md:81-84`, promotion "remains blocked until the complete
   handoff contract passes on an **adequate** unopened final-test cohort." Two
   final-test molecules is not an adequate cohort for a domain-general claim,
   and this plan does not change that number — it only preserves it.
5. **If R4 trips, the plan terminates.** Should `VPAFDQIFHJWCBK` prove
   incomplete, the correct outcome is a fail-closed record and a request for a
   new generation with a fresh unopened final-test cohort — not a smaller
   final-test set.

The honest summary to report upward: **this un-deadlocks the mechanism and
documents the damage; it does not deliver the science.** Reaching the stated
goal requires new compute on a larger accumulated cohort plus the six frozen
readiness gates, and both are outside this plan.

---

## Part V — Decision points requiring the user before Task 3

Per `workflow-contract.md:62-63`, these thresholds have no frozen authority and
must not be invented. Task 2 writes them into
`docs/PHASE9B_COHORT_SELECTION_FLOOR_V001.json` only after the user states them.

| # | Decision | Default proposed | Consequence if not met |
| --- | --- | --- | --- |
| D1 | Minimum surviving `final_test` InChIKeys | `2` (non-negotiable; derived from the seal) | `SEALED_FINAL_TEST_COHORT_DEGRADED`, plan terminates |
| D2 | Minimum surviving `validation` InChIKeys | `2` | `COHORT_DEGRADED_BELOW_SELECTION_FLOOR`, freeze the record and stop before generation v003 |
| D3 | Minimum surviving `train` InChIKeys | `3` | same as D2 |
| D4 | Proceed if D2 is relaxed to `1`? | not proposed | single-molecule checkpoint selection; must be recorded verbatim in the supersession record |
| D5 | Wait for `RBKFFSUUCLDQER` terminal before freezing? | **yes**, required by R2 | freezing now yields a cohort that a later terminal invalidates, forcing a v004 |

---

## File Structure

**New files**

- `scripts/phase9b_cohort_degradation.py` — the single writer for cohort
  degradation. Owns evidence loading, survivor derivation, floor checking, v003
  split derivation, and the supersession record. Owns nothing else: no
  chemistry, no process control, no deployment.
- `tests/test_phase9b_cohort_degradation.py` — tests for the above.
- `docs/PHASE9B_COHORT_DEGRADATION_EVIDENCE_V001.json` — transcribed remote
  terminal receipts (Task 1 input, human-produced).
- `docs/PHASE9B_COHORT_SELECTION_FLOOR_V001.json` — user-frozen floors.
- `docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V003.json` — derived output.
- `docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002_SUPERSESSION.json` — derived output.
- `docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V003.json` — watcher contract.
- `docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json` — generation record.
- `docs/PHASE9B_PIPELINE_CONFIG_V002.json` — orchestrator contract.

**Modified files**

- `scripts/phase9b_aimnet2_training_dataset.py` — schema constant only.
- `scripts/phase9b_aimnet2_final_test.py` — schema constant only.
- `scripts/phase9b_aimnet2_finetune.py` — split digest and development counts.
- `scripts/phase9b_aimnet2_finetune_watch.py` — final-test root name.
- `scripts/phase9b_pipeline_orchestrator.py` — withdrawal reconciliation, state name.
- `docs/PHASE9B_CONTINUOUS_PIPELINE_AUTOMATION.md` — state machine text.
- `tests/test_phase9b_aimnet2_finetune_watch.py`,
  `tests/test_phase9b_pipeline_orchestrator.py`,
  `tests/test_phase9b_aimnet2_finetune.py`,
  `tests/test_phase9b_aimnet2_training_dataset.py` — rebind assertions.

**Explicitly untouched**

`PHASE_STATUS.md`, `docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002.json`,
`docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V002.json`,
`docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V002.json`,
`docs/PHASE9B_PIPELINE_CONFIG_V001.json`, all `queues/*.json`,
`scripts/phase9b_parent_level_autofill.py`, runner v9, all production labels.

---

## Task 1: Cohort degradation evidence intake

**Files:**
- Create: `scripts/phase9b_cohort_degradation.py`
- Create: `tests/test_phase9b_cohort_degradation.py`
- Create: `docs/PHASE9B_COHORT_DEGRADATION_EVIDENCE_V001.json` (content supplied by the operator; see Step 6)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `CohortDegradationError(RuntimeError)`
  - `EVIDENCE_SCHEMA: Final[str] = "phase9b-cohort-degradation-evidence-v1"`
  - `SOURCE_SPLIT_SHA256: Final[str] = "772094bc08012f8f40c76994a1600985f11a1956bef66d2c7710006b3aa0b995"`
  - `canonical_json(value: object) -> bytes`
  - `sha256_bytes(raw: bytes) -> str`
  - `read_regular(path: Path, *, maximum: int = 1 << 30) -> bytes`
  - `read_json(path: Path) -> tuple[dict[str, Any], bytes]`
  - `load_evidence(path: Path) -> tuple[dict[str, Any], bytes]`

Reason codes used across Tasks 1–3, fixed here:
`PASSED`, `TERMINAL_FAILED`, `NEVER_LAUNCHED`, `IN_FLIGHT`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase9b_cohort_degradation.py`:

```python
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/phase9b_cohort_degradation.py"
SPLIT_V002 = ROOT / "docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002.json"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("phase9b_cohort_degradation_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


degradation = _load()


def _evidence(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": degradation.EVIDENCE_SCHEMA,
        "science_pilot_only": True,
        "production_accepted": False,
        "retry": False,
        "candidate_replacement": False,
        "source_split_sha256": degradation.SOURCE_SPLIT_SHA256,
        "observed_utc": "2026-08-01T00:00:00Z",
        "observer": "operator",
        "candidates": [],
    }
    value.update(overrides)
    return value


def _write(tmp_path: Path, value: dict[str, Any]) -> Path:
    path = tmp_path / "evidence.json"
    path.write_bytes(degradation.canonical_json(value))
    return path


def test_v002_split_digest_is_the_frozen_source() -> None:
    assert degradation.sha256_bytes(SPLIT_V002.read_bytes()) == degradation.SOURCE_SPLIT_SHA256


def test_evidence_requires_the_frozen_schema(tmp_path: Path) -> None:
    path = _write(tmp_path, _evidence(schema="phase9b-cohort-degradation-evidence-v0"))
    with pytest.raises(degradation.CohortDegradationError, match="schema"):
        degradation.load_evidence(path)


def test_evidence_must_bind_the_v002_split_digest(tmp_path: Path) -> None:
    path = _write(tmp_path, _evidence(source_split_sha256="0" * 64))
    with pytest.raises(degradation.CohortDegradationError, match="source split"):
        degradation.load_evidence(path)


def test_evidence_cannot_widen_the_one_shot_boundary(tmp_path: Path) -> None:
    for name in ("retry", "candidate_replacement", "production_accepted"):
        path = _write(tmp_path, _evidence(**{name: True}))
        with pytest.raises(degradation.CohortDegradationError, match="boundary"):
            degradation.load_evidence(path)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_phase9b_cohort_degradation.py -v`
Expected: collection error — `scripts/phase9b_cohort_degradation.py` does not exist.

- [ ] **Step 3: Write the minimal implementation**

Create `scripts/phase9b_cohort_degradation.py`:

```python
"""Derive the degraded Phase 9B cohort from immutable terminal evidence.

This module is the single writer for the split v003 registry and its
supersession record.  It performs no chemistry, starts no process, and
never rewrites existing evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Final, cast

EVIDENCE_SCHEMA: Final = "phase9b-cohort-degradation-evidence-v1"
SOURCE_SPLIT_SHA256: Final = (
    "772094bc08012f8f40c76994a1600985f11a1956bef66d2c7710006b3aa0b995"
)


class CohortDegradationError(RuntimeError):
    """The cohort degradation contract failed closed."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_regular(path: Path, *, maximum: int = 1 << 30) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise CohortDegradationError(f"not a regular file: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(fd, min(1 << 20, maximum + 1 - observed))
            if not chunk:
                break
            observed += len(chunk)
            if observed > maximum:
                raise CohortDegradationError(f"file exceeds maximum size: {path}")
            chunks.append(chunk)
    finally:
        os.close(fd)
    return b"".join(chunks)


def read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = read_regular(path)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CohortDegradationError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CohortDegradationError(f"JSON root is not an object: {path}")
    return cast(dict[str, Any], value), raw


def load_evidence(path: Path) -> tuple[dict[str, Any], bytes]:
    evidence, raw = read_json(path)
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        raise CohortDegradationError("cohort degradation evidence schema mismatch")
    if evidence.get("source_split_sha256") != SOURCE_SPLIT_SHA256:
        raise CohortDegradationError("cohort evidence source split digest mismatch")
    if evidence.get("science_pilot_only") is not True:
        raise CohortDegradationError("cohort evidence is not science_pilot_only")
    for name in ("retry", "candidate_replacement", "production_accepted"):
        if evidence.get(name) is not False:
            raise CohortDegradationError(f"cohort evidence widened the one-shot boundary: {name}")
    return evidence, raw
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_phase9b_cohort_degradation.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full gate**

Run: `python3 -m pytest -q && python3 -m ruff check . && python3 -m ruff format --check . && python3 -m mypy`
Expected: all four succeed. `mypy` is configured with `packages = ["nhc_deprot_ranker"]` and does not cover `scripts/`, so a clean `ruff` run is the type-adjacent check here.

- [ ] **Step 6: Request the evidence document from the operator**

Do **not** SSH and do **not** invent values. Post this exact request and wait:

> To continue, transcribe the following read-only observations from the compute
> host into `docs/PHASE9B_COHORT_DEGRADATION_EVIDENCE_V001.json`. Do not modify
> anything on the host.
>
> For each of the four lane state roots under
> `/home/plab/test/WJW/data/runs/phase9b_parent_level_finetune_lane_{a,b,c,d}_state_v002`:
> the `queue_binding.json` digest, whether `queue_exhausted.json` exists, and the
> full contents plus sha256 of `lane_terminal.json` if it exists.
>
> For each of the nine InChIKeys, from
> `/home/plab/test/WJW/data/runs/autofill_<inchikey_lower>_v001`: whether the
> root exists, the integer in `controller_exit_code` (or `null` if absent),
> `result.json`'s `final_outcome` and `candidate` fields plus the file's sha256
> (or `null` if absent).
>
> Also state whether any route is still running.

- [ ] **Step 7: Commit**

```bash
git add scripts/phase9b_cohort_degradation.py tests/test_phase9b_cohort_degradation.py
git commit -m "feat: add fail-closed cohort degradation evidence reader"
```

---

## Task 2: Survivor derivation, quiescence, and the selection floor

**Files:**
- Modify: `scripts/phase9b_cohort_degradation.py`
- Modify: `tests/test_phase9b_cohort_degradation.py`
- Create: `docs/PHASE9B_COHORT_SELECTION_FLOOR_V001.json`

**Interfaces:**
- Consumes: `CohortDegradationError`, `EVIDENCE_SCHEMA`, `SOURCE_SPLIT_SHA256`,
  `canonical_json`, `sha256_bytes`, `read_json`, `load_evidence` from Task 1.
- Produces:
  - `FLOOR_SCHEMA: Final[str] = "phase9b-cohort-selection-floor-v1"`
  - `CLASSIFICATIONS: Final[frozenset[str]]` = `{"PASSED", "TERMINAL_FAILED", "NEVER_LAUNCHED", "IN_FLIGHT"}`
  - `split_assignments(split: dict[str, Any]) -> dict[str, str]`
  - `derive_survivors(evidence: dict[str, Any], split: dict[str, Any]) -> dict[str, Any]`
    returning `{"survivors": dict[str, str], "withdrawn": list[dict[str, str]], "counts_by_split": dict[str, int]}`
    where `withdrawn` items are `{"candidate", "split", "reason_code"}` sorted by candidate.
  - `check_floor(derivation: dict[str, Any], floor: dict[str, Any]) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_phase9b_cohort_degradation.py`:

```python
SPLIT_FIXTURE: dict[str, Any] = {
    "schema": "phase9b-aimnet2-finetune-split-v002",
    "train": [
        {"candidate": "ACGCNTKELWXJPN-UHFFFAOYSA-N"},
        {"candidate": "CLXFIGGGSODORK-UHFFFAOYSA-N"},
        {"candidate": "PDIYCCLDBKWBTK-UHFFFAOYSA-N"},
        {"candidate": "RBKFFSUUCLDQER-UHFFFAOYSA-N"},
        {"candidate": "VNYHGZAUUQMMDL-UHFFFAOYSA-N"},
    ],
    "validation": [
        {"candidate": "KZYKDQNIIMATMJ-UHFFFAOYSA-N"},
        {"candidate": "RMEQTBVGGNKAEQ-UHFFFAOYSA-N"},
    ],
    "final_test": [
        {"candidate": "RATKDJDMBGPDPZ-UHFFFAOYSA-N"},
        {"candidate": "VPAFDQIFHJWCBK-UHFFFAOYSA-N"},
    ],
}

ALL_PASS = {
    "ACGCNTKELWXJPN-UHFFFAOYSA-N": "PASSED",
    "CLXFIGGGSODORK-UHFFFAOYSA-N": "PASSED",
    "PDIYCCLDBKWBTK-UHFFFAOYSA-N": "PASSED",
    "RBKFFSUUCLDQER-UHFFFAOYSA-N": "PASSED",
    "VNYHGZAUUQMMDL-UHFFFAOYSA-N": "PASSED",
    "KZYKDQNIIMATMJ-UHFFFAOYSA-N": "PASSED",
    "RMEQTBVGGNKAEQ-UHFFFAOYSA-N": "PASSED",
    "RATKDJDMBGPDPZ-UHFFFAOYSA-N": "PASSED",
    "VPAFDQIFHJWCBK-UHFFFAOYSA-N": "PASSED",
}


def _candidates(classifications: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "candidate": candidate,
            "classification": classification,
            "controller_exit_code": 0 if classification == "PASSED" else None,
            "final_outcome": "PASS" if classification == "PASSED" else None,
        }
        for candidate, classification in sorted(classifications.items())
    ]


def _floor(train: int = 3, validation: int = 2) -> dict[str, Any]:
    return {
        "schema": degradation.FLOOR_SCHEMA,
        "minimum_survivors_by_split": {
            "train": train,
            "validation": validation,
            "final_test": 2,
        },
    }


def test_derivation_keeps_every_survivor_in_its_original_split() -> None:
    evidence = _evidence(candidates=_candidates(ALL_PASS))
    result = degradation.derive_survivors(evidence, SPLIT_FIXTURE)
    assert result["survivors"]["KZYKDQNIIMATMJ-UHFFFAOYSA-N"] == "validation"
    assert result["withdrawn"] == []
    assert result["counts_by_split"] == {"train": 5, "validation": 2, "final_test": 2}


def test_derivation_withdraws_failed_and_never_launched_candidates() -> None:
    classifications = dict(ALL_PASS)
    classifications["CLXFIGGGSODORK-UHFFFAOYSA-N"] = "TERMINAL_FAILED"
    classifications["KZYKDQNIIMATMJ-UHFFFAOYSA-N"] = "NEVER_LAUNCHED"
    evidence = _evidence(candidates=_candidates(classifications))
    result = degradation.derive_survivors(evidence, SPLIT_FIXTURE)
    assert result["withdrawn"] == [
        {
            "candidate": "CLXFIGGGSODORK-UHFFFAOYSA-N",
            "split": "train",
            "reason_code": "TERMINAL_FAILED",
        },
        {
            "candidate": "KZYKDQNIIMATMJ-UHFFFAOYSA-N",
            "split": "validation",
            "reason_code": "NEVER_LAUNCHED",
        },
    ]
    assert result["counts_by_split"] == {"train": 4, "validation": 1, "final_test": 2}


def test_derivation_fails_closed_while_a_route_is_in_flight() -> None:
    classifications = dict(ALL_PASS)
    classifications["RBKFFSUUCLDQER-UHFFFAOYSA-N"] = "IN_FLIGHT"
    evidence = _evidence(candidates=_candidates(classifications))
    with pytest.raises(degradation.CohortDegradationError, match="COHORT_NOT_QUIESCENT"):
        degradation.derive_survivors(evidence, SPLIT_FIXTURE)


def test_derivation_requires_every_cohort_candidate_exactly_once() -> None:
    classifications = dict(ALL_PASS)
    classifications.pop("VNYHGZAUUQMMDL-UHFFFAOYSA-N")
    evidence = _evidence(candidates=_candidates(classifications))
    with pytest.raises(degradation.CohortDegradationError, match="cohort coverage"):
        degradation.derive_survivors(evidence, SPLIT_FIXTURE)


def test_sealed_final_test_cohort_cannot_shrink() -> None:
    classifications = dict(ALL_PASS)
    classifications["VPAFDQIFHJWCBK-UHFFFAOYSA-N"] = "TERMINAL_FAILED"
    evidence = _evidence(candidates=_candidates(classifications))
    derivation = degradation.derive_survivors(evidence, SPLIT_FIXTURE)
    with pytest.raises(
        degradation.CohortDegradationError, match="SEALED_FINAL_TEST_COHORT_DEGRADED"
    ):
        degradation.check_floor(derivation, _floor())


def test_floor_blocks_a_single_validation_molecule() -> None:
    classifications = dict(ALL_PASS)
    classifications["KZYKDQNIIMATMJ-UHFFFAOYSA-N"] = "NEVER_LAUNCHED"
    evidence = _evidence(candidates=_candidates(classifications))
    derivation = degradation.derive_survivors(evidence, SPLIT_FIXTURE)
    with pytest.raises(
        degradation.CohortDegradationError,
        match="COHORT_DEGRADED_BELOW_SELECTION_FLOOR",
    ):
        degradation.check_floor(derivation, _floor())


def test_floor_accepts_a_cohort_that_meets_every_minimum() -> None:
    classifications = dict(ALL_PASS)
    classifications["CLXFIGGGSODORK-UHFFFAOYSA-N"] = "TERMINAL_FAILED"
    evidence = _evidence(candidates=_candidates(classifications))
    derivation = degradation.derive_survivors(evidence, SPLIT_FIXTURE)
    assert degradation.check_floor(derivation, _floor()) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_phase9b_cohort_degradation.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'FLOOR_SCHEMA'` and `'derive_survivors'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `scripts/phase9b_cohort_degradation.py`:

```python
FLOOR_SCHEMA: Final = "phase9b-cohort-selection-floor-v1"
SPLIT_NAMES: Final = ("train", "validation", "final_test")
CLASSIFICATIONS: Final = frozenset(
    {"PASSED", "TERMINAL_FAILED", "NEVER_LAUNCHED", "IN_FLIGHT"}
)


def split_assignments(split: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in SPLIT_NAMES:
        profiles = split.get(name)
        if not isinstance(profiles, list) or not profiles:
            raise CohortDegradationError(f"source split is empty: {name}")
        for profile in profiles:
            if not isinstance(profile, dict):
                raise CohortDegradationError("source split profile is not an object")
            candidate = profile.get("candidate")
            if not isinstance(candidate, str) or candidate in result:
                raise CohortDegradationError("duplicate or invalid source split candidate")
            result[candidate] = name
    return result


def derive_survivors(evidence: dict[str, Any], split: dict[str, Any]) -> dict[str, Any]:
    assignments = split_assignments(split)
    observed: dict[str, str] = {}
    for item in cast(list[Any], evidence.get("candidates", [])):
        if not isinstance(item, dict):
            raise CohortDegradationError("cohort evidence candidate is not an object")
        candidate = item.get("candidate")
        classification = item.get("classification")
        if not isinstance(candidate, str) or candidate in observed:
            raise CohortDegradationError("duplicate or invalid cohort evidence candidate")
        if classification not in CLASSIFICATIONS:
            raise CohortDegradationError(f"unknown cohort classification: {classification!r}")
        if classification == "PASSED" and (
            item.get("controller_exit_code") != 0 or item.get("final_outcome") != "PASS"
        ):
            raise CohortDegradationError(f"PASSED classification lacks a PASS receipt: {candidate}")
        observed[candidate] = cast(str, classification)
    if set(observed) != set(assignments):
        raise CohortDegradationError("cohort coverage mismatch between evidence and split")
    if any(classification == "IN_FLIGHT" for classification in observed.values()):
        raise CohortDegradationError("COHORT_NOT_QUIESCENT: a cohort route is still running")
    survivors = {
        candidate: assignments[candidate]
        for candidate, classification in sorted(observed.items())
        if classification == "PASSED"
    }
    withdrawn = [
        {
            "candidate": candidate,
            "split": assignments[candidate],
            "reason_code": classification,
        }
        for candidate, classification in sorted(observed.items())
        if classification != "PASSED"
    ]
    counts = {
        name: sum(value == name for value in survivors.values()) for name in SPLIT_NAMES
    }
    return {"survivors": survivors, "withdrawn": withdrawn, "counts_by_split": counts}


def check_floor(derivation: dict[str, Any], floor: dict[str, Any]) -> None:
    if floor.get("schema") != FLOOR_SCHEMA:
        raise CohortDegradationError("cohort selection floor schema mismatch")
    minimums = floor.get("minimum_survivors_by_split")
    if not isinstance(minimums, dict) or set(minimums) != set(SPLIT_NAMES):
        raise CohortDegradationError("cohort selection floor is incomplete")
    counts = cast(dict[str, int], derivation["counts_by_split"])
    if counts["final_test"] != 2:
        raise CohortDegradationError(
            "SEALED_FINAL_TEST_COHORT_DEGRADED: the sealed final-test cohort is not intact"
        )
    for name in SPLIT_NAMES:
        if counts[name] < int(minimums[name]):
            raise CohortDegradationError(
                "COHORT_DEGRADED_BELOW_SELECTION_FLOOR: "
                f"{name} survivors {counts[name]} < {minimums[name]}"
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_phase9b_cohort_degradation.py -v`
Expected: 11 passed.

- [ ] **Step 5: Freeze the user-confirmed floor**

Do **not** write this file until the user has answered D1–D4 from Part V.
Then create `docs/PHASE9B_COHORT_SELECTION_FLOOR_V001.json` with exactly the
confirmed integers:

```json
{
  "schema": "phase9b-cohort-selection-floor-v1",
  "science_pilot_only": true,
  "production_accepted": false,
  "authority": "user_confirmed_no_frozen_repository_threshold",
  "confirmation_reference": "<verbatim user statement>",
  "minimum_survivors_by_split": {
    "train": 3,
    "validation": 2,
    "final_test": 2
  },
  "rationale": "workflow-contract.md:62-63 forbids inventing an unfrozen numeric threshold; these minima are user-frozen for this degraded cohort only and confer no general validity."
}
```

- [ ] **Step 6: Run the full gate**

Run: `python3 -m pytest -q && python3 -m ruff check . && python3 -m ruff format --check . && python3 -m mypy`
Expected: all four succeed.

- [ ] **Step 7: Commit**

```bash
git add scripts/phase9b_cohort_degradation.py tests/test_phase9b_cohort_degradation.py docs/PHASE9B_COHORT_SELECTION_FLOOR_V001.json
git commit -m "feat: derive degraded cohort survivors under a user-frozen floor"
```

---

## Task 3: Derive split v003 and the supersession record

**Files:**
- Modify: `scripts/phase9b_cohort_degradation.py`
- Modify: `tests/test_phase9b_cohort_degradation.py`
- Create (generated): `docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V003.json`
- Create (generated): `docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002_SUPERSESSION.json`

**Interfaces:**
- Consumes: `derive_survivors`, `check_floor`, `split_assignments`,
  `canonical_json`, `sha256_bytes`, `read_json`, `load_evidence`,
  `SOURCE_SPLIT_SHA256`, `FLOOR_SCHEMA` from Tasks 1–2.
- Produces:
  - `SPLIT_V003_SCHEMA: Final[str] = "phase9b-aimnet2-finetune-split-v003"`
  - `SUPERSESSION_SCHEMA: Final[str] = "phase9b-aimnet2-finetune-split-supersession-v1"`
  - `derive_split_v003(split_v002: dict[str, Any], derivation: dict[str, Any]) -> dict[str, Any]`
  - `supersession_record(*, derivation: dict[str, Any], evidence_sha256: str, floor_sha256: str, split_v003_sha256: str) -> dict[str, Any]`
  - `main(argv: Sequence[str] | None = None) -> int` — CLI writing both documents with `O_EXCL`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_phase9b_cohort_degradation.py`:

```python
def _degraded_derivation() -> dict[str, Any]:
    classifications = dict(ALL_PASS)
    classifications["CLXFIGGGSODORK-UHFFFAOYSA-N"] = "TERMINAL_FAILED"
    evidence = _evidence(candidates=_candidates(classifications))
    return degradation.derive_survivors(evidence, SPLIT_FIXTURE)


def test_split_v003_uses_a_new_schema_so_v002_readers_fail_closed() -> None:
    split = degradation.derive_split_v003(SPLIT_FIXTURE, _degraded_derivation())
    assert split["schema"] == "phase9b-aimnet2-finetune-split-v003"
    assert split["supersedes_split"] == "PHASE9B_AIMNET2_FINETUNE_SPLIT_V002"
    assert split["supersedes_split_sha256"] == degradation.SOURCE_SPLIT_SHA256
    assert split["classification"] == "degraded_after_launch"


def test_split_v003_deletes_only_and_never_moves_an_inchikey() -> None:
    split = degradation.derive_split_v003(SPLIT_FIXTURE, _degraded_derivation())
    for name in ("train", "validation", "final_test"):
        source = {profile["candidate"] for profile in SPLIT_FIXTURE[name]}
        derived = {profile["candidate"] for profile in split[name]}
        assert derived <= source
    assert [profile["candidate"] for profile in split["train"]] == [
        "ACGCNTKELWXJPN-UHFFFAOYSA-N",
        "PDIYCCLDBKWBTK-UHFFFAOYSA-N",
        "RBKFFSUUCLDQER-UHFFFAOYSA-N",
        "VNYHGZAUUQMMDL-UHFFFAOYSA-N",
    ]


def test_split_v003_final_test_block_is_byte_identical_to_v002() -> None:
    split = degradation.derive_split_v003(SPLIT_FIXTURE, _degraded_derivation())
    assert degradation.canonical_json(split["final_test"]) == degradation.canonical_json(
        SPLIT_FIXTURE["final_test"]
    )


def test_split_v003_preserves_the_candidate_profiles_verbatim() -> None:
    source = {
        "schema": "phase9b-aimnet2-finetune-split-v002",
        "train": [
            {"candidate": "ACGCNTKELWXJPN-UHFFFAOYSA-N", "electron_count": 72},
            {"candidate": "CLXFIGGGSODORK-UHFFFAOYSA-N", "electron_count": 114},
            {"candidate": "PDIYCCLDBKWBTK-UHFFFAOYSA-N", "electron_count": 100},
            {"candidate": "RBKFFSUUCLDQER-UHFFFAOYSA-N", "electron_count": 120},
            {"candidate": "VNYHGZAUUQMMDL-UHFFFAOYSA-N", "electron_count": 68},
        ],
        "validation": SPLIT_FIXTURE["validation"],
        "final_test": SPLIT_FIXTURE["final_test"],
    }
    classifications = dict(ALL_PASS)
    classifications["CLXFIGGGSODORK-UHFFFAOYSA-N"] = "TERMINAL_FAILED"
    derivation = degradation.derive_survivors(_evidence(candidates=_candidates(classifications)), source)
    split = degradation.derive_split_v003(source, derivation)
    assert split["train"][0] == {"candidate": "ACGCNTKELWXJPN-UHFFFAOYSA-N", "electron_count": 72}


def test_supersession_record_accounts_for_every_withdrawn_inchikey() -> None:
    derivation = _degraded_derivation()
    record = degradation.supersession_record(
        derivation=derivation,
        evidence_sha256="a" * 64,
        floor_sha256="b" * 64,
        split_v003_sha256="c" * 64,
    )
    assert record["schema"] == "phase9b-aimnet2-finetune-split-supersession-v1"
    assert record["withdrawn"] == derivation["withdrawn"]
    assert record["superseded_split_sha256"] == degradation.SOURCE_SPLIT_SHA256
    assert record["split_v003_sha256"] == "c" * 64
    assert record["retry"] is False
    assert record["candidate_replacement"] is False
    assert record["statistical_power"]["general_claim_supported"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_phase9b_cohort_degradation.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'derive_split_v003'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `scripts/phase9b_cohort_degradation.py`:

```python
SPLIT_V003_SCHEMA: Final = "phase9b-aimnet2-finetune-split-v003"
SUPERSESSION_SCHEMA: Final = "phase9b-aimnet2-finetune-split-supersession-v1"
STATISTICAL_POWER_STATEMENT: Final = (
    "workflow-contract.md:43 already declares a 5/2/2 pilot cohort insufficient to "
    "establish a general stopping rule, general single-point-only eligibility, or "
    "statistical performance across the NHC domain.  This degraded cohort is strictly "
    "smaller and therefore supports strictly less."
)


def derive_split_v003(
    split_v002: dict[str, Any], derivation: dict[str, Any]
) -> dict[str, Any]:
    survivors = cast(dict[str, str], derivation["survivors"])
    result: dict[str, Any] = {
        "schema": SPLIT_V003_SCHEMA,
        "status": "degraded_from_preregistered_v002_cohort",
        "classification": "degraded_after_launch",
        "supersedes_split": "PHASE9B_AIMNET2_FINETUNE_SPLIT_V002",
        "supersedes_split_sha256": SOURCE_SPLIT_SHA256,
        "split_unit": split_v002["split_unit"],
        "parent_protocol_sha256": split_v002["parent_protocol_sha256"],
        "input_cohort": split_v002["input_cohort"],
    }
    for name in SPLIT_NAMES:
        profiles = [
            profile
            for profile in cast(list[dict[str, Any]], split_v002[name])
            if survivors.get(str(profile["candidate"])) == name
        ]
        if not profiles:
            raise CohortDegradationError(f"degraded split would empty a split: {name}")
        result[name] = profiles
    if canonical_json(result["final_test"]) != canonical_json(split_v002["final_test"]):
        raise CohortDegradationError(
            "SEALED_FINAL_TEST_COHORT_DEGRADED: final-test block is not byte-identical"
        )
    result["identity_requirements"] = split_v002["identity_requirements"]
    result["leakage_rules"] = split_v002["leakage_rules"]
    result["candidate_substitution_performed"] = False
    result["candidate_retry_performed"] = False
    result["science_pilot_only"] = True
    result["production_accepted"] = False
    result["production_labels_modified"] = False
    return result


def supersession_record(
    *,
    derivation: dict[str, Any],
    evidence_sha256: str,
    floor_sha256: str,
    split_v003_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": SUPERSESSION_SCHEMA,
        "superseded_split": "PHASE9B_AIMNET2_FINETUNE_SPLIT_V002",
        "superseded_split_sha256": SOURCE_SPLIT_SHA256,
        "split_v003": "PHASE9B_AIMNET2_FINETUNE_SPLIT_V003",
        "split_v003_sha256": split_v003_sha256,
        "evidence_sha256": evidence_sha256,
        "selection_floor_sha256": floor_sha256,
        "classification": "degraded_after_launch",
        "withdrawn": derivation["withdrawn"],
        "surviving_counts_by_split": derivation["counts_by_split"],
        "retry": False,
        "candidate_replacement": False,
        "sealed_final_test_cohort_intact": True,
        "inchikey_moved_between_splits": False,
        "queue_files_modified": False,
        "lane_evidence_modified": False,
        "statistical_power": {
            "general_claim_supported": False,
            "statement": STATISTICAL_POWER_STATEMENT,
        },
        "science_pilot_only": True,
        "production_accepted": False,
    }
```

Add the CLI at the end of the module:

```python
def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--evidence", required=True)
    result.add_argument("--split-v002", required=True)
    result.add_argument("--floor", required=True)
    result.add_argument("--split-v003-out", required=True)
    result.add_argument("--supersession-out", required=True)
    return result


def write_new(path: Path, raw: bytes) -> str:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise CohortDegradationError("short cohort evidence write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    return sha256_bytes(raw)


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    evidence, evidence_raw = load_evidence(Path(args.evidence).resolve(strict=True))
    split_v002, split_raw = read_json(Path(args.split_v002).resolve(strict=True))
    if sha256_bytes(split_raw) != SOURCE_SPLIT_SHA256:
        raise CohortDegradationError("source split digest mismatch")
    floor, floor_raw = read_json(Path(args.floor).resolve(strict=True))
    derivation = derive_survivors(evidence, split_v002)
    check_floor(derivation, floor)
    split_v003 = derive_split_v003(split_v002, derivation)
    split_v003_raw = canonical_json(split_v003)
    split_v003_sha256 = write_new(Path(args.split_v003_out), split_v003_raw)
    record = supersession_record(
        derivation=derivation,
        evidence_sha256=sha256_bytes(evidence_raw),
        floor_sha256=sha256_bytes(floor_raw),
        split_v003_sha256=split_v003_sha256,
    )
    write_new(Path(args.supersession_out), canonical_json(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Add `import argparse` and `from collections.abc import Sequence` to the module imports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_phase9b_cohort_degradation.py -v`
Expected: 16 passed.

- [ ] **Step 5: Generate the two frozen documents**

Only after Task 1 Step 6 has delivered real evidence and Task 2 Step 5 has
frozen the floor:

```bash
python3 scripts/phase9b_cohort_degradation.py \
  --evidence docs/PHASE9B_COHORT_DEGRADATION_EVIDENCE_V001.json \
  --split-v002 docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002.json \
  --floor docs/PHASE9B_COHORT_SELECTION_FLOOR_V001.json \
  --split-v003-out docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V003.json \
  --supersession-out docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002_SUPERSESSION.json
```

Expected: exit 0. If it exits with `SEALED_FINAL_TEST_COHORT_DEGRADED` or
`COHORT_DEGRADED_BELOW_SELECTION_FLOOR`, **stop the plan here**, commit the
evidence and floor documents, and report the terminal classification. Tasks 4–8
are not authorized in that case.

- [ ] **Step 6: Record the new digests**

Run: `python3 -c "import hashlib,pathlib; [print(p, hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()) for p in ['docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V003.json','docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002_SUPERSESSION.json']]"`

Write the split v003 digest down; Tasks 4–7 all consume it. Call it `<SPLIT_V003_SHA256>` below.

- [ ] **Step 7: Run the full gate and commit**

```bash
python3 -m pytest -q && python3 -m ruff check . && python3 -m ruff format --check . && python3 -m mypy
git add scripts/phase9b_cohort_degradation.py tests/test_phase9b_cohort_degradation.py docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V003.json docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002_SUPERSESSION.json docs/PHASE9B_COHORT_DEGRADATION_EVIDENCE_V001.json
git commit -m "feat: freeze degraded split v003 and its supersession record"
```

---

## Task 4: Rebind the dataset and final-test readers to split v003

**Files:**
- Modify: `scripts/phase9b_aimnet2_training_dataset.py:20`
- Modify: `scripts/phase9b_aimnet2_final_test.py:20`
- Modify: `tests/test_phase9b_aimnet2_training_dataset.py`

**Interfaces:**
- Consumes: `<SPLIT_V003_SHA256>` and the file
  `docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V003.json` from Task 3.
- Produces: `SPLIT_SCHEMA == "phase9b-aimnet2-finetune-split-v003"` in both
  modules. No other symbol changes. `included_splits`
  (`scripts/phase9b_aimnet2_training_dataset.py:463`) is **not** modified.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_phase9b_aimnet2_training_dataset.py`:

```python
def test_dataset_reader_only_accepts_the_degraded_v003_registry(tmp_path: Path) -> None:
    assert dataset.SPLIT_SCHEMA == "phase9b-aimnet2-finetune-split-v003"
    stale = tmp_path / "v002.json"
    stale.write_bytes(
        dataset.canonical_json(
            {
                "schema": "phase9b-aimnet2-finetune-split-v002",
                "train": [{"candidate": "AAAAAAAAAAAAAA-BBBBBBBBBB-C"}],
                "validation": [{"candidate": "BBBBBBBBBBBBBB-BBBBBBBBBB-C"}],
                "final_test": [{"candidate": "CCCCCCCCCCCCCC-BBBBBBBBBB-C"}],
            }
        )
    )
    with pytest.raises(dataset.DatasetAssemblyError, match="split schema mismatch"):
        dataset.load_split(stale)


def test_final_test_reader_only_accepts_the_degraded_v003_registry() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "phase9b_aimnet2_final_test_schema_test",
        ROOT / "scripts/phase9b_aimnet2_final_test.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert module.SPLIT_SCHEMA == "phase9b-aimnet2-finetune-split-v003"
```

If `sys` or `ROOT` is not already imported in that test module, add
`import sys` and reuse the module's existing `ROOT` constant.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_phase9b_aimnet2_training_dataset.py -k v003 -v`
Expected: FAIL — `assert 'phase9b-aimnet2-finetune-split-v002' == 'phase9b-aimnet2-finetune-split-v003'`.

- [ ] **Step 3: Write the minimal implementation**

In `scripts/phase9b_aimnet2_training_dataset.py:20` and
`scripts/phase9b_aimnet2_final_test.py:20`, change:

```python
SPLIT_SCHEMA: Final = "phase9b-aimnet2-finetune-split-v002"
```

to:

```python
SPLIT_SCHEMA: Final = "phase9b-aimnet2-finetune-split-v003"
```

Change nothing else in either file. In particular do not touch
`included_splits` at `:463`, `sealed_final_test_commitment` at `:558-561`, or
`candidate_count != 2` at `scripts/phase9b_aimnet2_final_test.py:169` — the
sealed cohort keeps exactly two members by construction (Task 2 `check_floor`).

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_phase9b_aimnet2_training_dataset.py -v`
Expected: all pass, including the two new tests.

- [ ] **Step 5: Record the new source digests**

Run: `python3 -c "import hashlib,pathlib; [print(p, hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()) for p in ['scripts/phase9b_aimnet2_training_dataset.py','scripts/phase9b_aimnet2_final_test.py']]"`

Task 7 needs both values.

- [ ] **Step 6: Run the full gate and commit**

```bash
python3 -m pytest -q && python3 -m ruff check . && python3 -m ruff format --check . && python3 -m mypy
git add scripts/phase9b_aimnet2_training_dataset.py scripts/phase9b_aimnet2_final_test.py tests/test_phase9b_aimnet2_training_dataset.py
git commit -m "refactor: bind dataset and final-test readers to split v003"
```

---

## Task 5: Register generation v003 and rebind the trainer

**Files:**
- Create: `docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json`
- Modify: `scripts/phase9b_aimnet2_finetune.py:31,165,193`
- Modify: `tests/test_phase9b_aimnet2_finetune.py`

**Interfaces:**
- Consumes: `<SPLIT_V003_SHA256>` from Task 3; the surviving per-split counts
  from `docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002_SUPERSESSION.json`
  (`surviving_counts_by_split`).
- Produces: `SPLIT_SHA256 == <SPLIT_V003_SHA256>` and
  `DEVELOPMENT_CANDIDATE_COUNT: Final[int]` in
  `scripts/phase9b_aimnet2_finetune.py`, consumed by Task 7's digest rebind.

Let `T` = surviving train count, `V` = surviving validation count,
`D = T + V` = development candidate count. With the expected degradation
(`CLXFIGGGSODORK` withdrawn only) `T=4`, `V=2`, `D=6`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_phase9b_aimnet2_finetune.py`:

```python
GENERATION_V003 = ROOT / "docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json"
SUPERSESSION = ROOT / "docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002_SUPERSESSION.json"


def test_generation_v003_reseals_the_intact_final_test_cohort() -> None:
    config = json.loads(GENERATION_V003.read_text())
    supersession = json.loads(SUPERSESSION.read_text())
    counts = supersession["surviving_counts_by_split"]
    assert config["generation_id"] == "phase9b-aimnet2-nhc-p01-v003"
    assert config["schema"] == "phase9b-aimnet2-model-generation-config-v002"
    assert config["data"]["sealed_final_test_commitment"] == {
        "split_registry_sha256": supersession["split_v003_sha256"],
        "candidate_count": 2,
    }
    assert config["data"]["development_candidate_count"] == counts["train"] + counts["validation"]
    assert config["data"]["development_candidate_count_by_split"] == {
        "train": counts["train"],
        "validation": counts["validation"],
    }


def test_generation_v003_keeps_every_readiness_blocker() -> None:
    config = json.loads(GENERATION_V003.read_text())
    readiness = config["readiness"]
    assert readiness["state"] == "BLOCKED_BEFORE_TRAINING"
    assert set(readiness["blocking_reason_codes"]) == {
        "EPOCH_ZERO_SELECTION_NOT_IMPLEMENTED",
        "FINAL_TEST_EVALUATOR_INCOMPLETE",
        "VALIDATION_SELECTION_GATES_NOT_FROZEN",
        "BASELINE_ELIGIBILITY_GATES_NOT_FROZEN",
        "FINAL_TEST_ACCEPTANCE_GATES_NOT_FROZEN",
        "STOPPING_HANDOFF_PROMOTION_GATES_NOT_FROZEN",
    }


def test_generation_v003_uses_new_output_roots() -> None:
    config = json.loads(GENERATION_V003.read_text())
    v002 = json.loads((ROOT / "docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V002.json").read_text())
    assert config["paths"]["dataset_root"] != v002["paths"]["dataset_root"]
    assert config["paths"]["training_root"] != v002["paths"]["training_root"]
    assert config["paths"]["final_bundle_name"] != v002["paths"]["final_bundle_name"]


def test_trainer_is_bound_to_the_degraded_registry_and_counts() -> None:
    supersession = json.loads(SUPERSESSION.read_text())
    counts = supersession["surviving_counts_by_split"]
    assert finetune.SPLIT_SHA256 == supersession["split_v003_sha256"]
    assert finetune.DEVELOPMENT_CANDIDATE_COUNT == counts["train"] + counts["validation"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_phase9b_aimnet2_finetune.py -v`
Expected: FAIL — `FileNotFoundError` for the v003 generation config.

- [ ] **Step 3: Create the generation v003 config**

Copy `docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V002.json` to
`docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json` and change **only**
these fields (keep `schema` at `phase9b-aimnet2-model-generation-config-v002`;
the trainer's `CONFIG_SCHEMA` check at
`scripts/phase9b_aimnet2_finetune.py:26` requires it, and the generation
identity is carried by `generation_id`):

```json
{
  "generation_id": "phase9b-aimnet2-nhc-p01-v003",
  "data": {
    "development_candidate_count": 6,
    "development_candidate_count_by_split": {"train": 4, "validation": 2},
    "sealed_final_test_commitment": {
      "split_registry_sha256": "<SPLIT_V003_SHA256>",
      "candidate_count": 2
    }
  },
  "paths": {
    "dataset_root": "/home/plab/test/WJW/data/runs/phase9b_aimnet2_development_dataset_v003",
    "training_root": "/home/plab/test/WJW/data/runs/phase9b_aimnet2_model_freeze_v003",
    "final_bundle_name": "aimnet2_wb97m_d3_0_nhc_p01_v003.pt"
  },
  "cohort_degradation": {
    "supersedes_generation_id": "phase9b-aimnet2-nhc-p01-v002",
    "supersession_record": "docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002_SUPERSESSION.json",
    "previous_sealed_commitment_sha256": "772094bc08012f8f40c76994a1600985f11a1956bef66d2c7710006b3aa0b995",
    "candidate_replacement": false,
    "retry": false
  }
}
```

Substitute the real integers from `surviving_counts_by_split` and the real
`<SPLIT_V003_SHA256>`. Leave `readiness`, `base_bundle`, `training_model`,
`training`, `environment`, and `resource_preflight` byte-identical to v002.
`readiness.state` stays `BLOCKED_BEFORE_TRAINING` — see Part I.6 and Part IV.3.

- [ ] **Step 4: Rebind the trainer constants**

In `scripts/phase9b_aimnet2_finetune.py`, change line 31 to the v003 digest and
introduce the development count constant next to it:

```python
SPLIT_SHA256: Final = "<SPLIT_V003_SHA256>"
DEVELOPMENT_CANDIDATE_COUNT: Final = 6
```

Change line 165 from `or manifest.get("candidate_count") != 7` to:

```python
        or manifest.get("candidate_count") != DEVELOPMENT_CANDIDATE_COUNT
```

Change line 193 from `if not isinstance(candidates, list) or len(candidates) != 7:` to:

```python
    if not isinstance(candidates, list) or len(candidates) != DEVELOPMENT_CANDIDATE_COUNT:
```

Change nothing else. The equality check at `:133-137` and the forbidden-key
check at `:138-140` keep their exact form; only `SPLIT_SHA256` behind them moved.

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_phase9b_aimnet2_finetune.py -v`
Expected: all pass.

- [ ] **Step 6: Record the new trainer digest**

Run: `python3 -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('scripts/phase9b_aimnet2_finetune.py').read_bytes()).hexdigest())"`

- [ ] **Step 7: Run the full gate and commit**

```bash
python3 -m pytest -q && python3 -m ruff check . && python3 -m ruff format --check . && python3 -m mypy
git add scripts/phase9b_aimnet2_finetune.py docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json tests/test_phase9b_aimnet2_finetune.py
git commit -m "feat: register generation v003 on the degraded cohort"
```

---

## Task 6: Rebind the fine-tune watcher to the v003 cohort

**Files:**
- Create: `docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V003.json`
- Modify: `scripts/phase9b_aimnet2_finetune_watch.py:459`
- Modify: `tests/test_phase9b_aimnet2_finetune_watch.py`

**Interfaces:**
- Consumes: `<SPLIT_V003_SHA256>` (Task 3), surviving counts (Task 3),
  generation v003 paths (Task 5).
- Produces: `FINAL_TEST_ROOT_NAME: Final[str] = "phase9b_aimnet2_final_test_v003"`
  in `scripts/phase9b_aimnet2_finetune_watch.py`, and the orchestration v003
  digest consumed by Task 7.

Let `N` = total surviving candidates = `T + V + 2`. Expected `N = 8`.

- [ ] **Step 1: Write the failing tests**

Replace the count assertions in `tests/test_phase9b_aimnet2_finetune_watch.py`
so the fixture is parameterised by the frozen cohort size, and add the
regression that the gate stays exact-match. Change `_collection_fixture` to
build `N` candidates instead of 9:

```python
SUPERSESSION = ROOT / "docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002_SUPERSESSION.json"
COUNTS = json.loads(SUPERSESSION.read_text())["surviving_counts_by_split"]
COHORT_SIZE = COUNTS["train"] + COUNTS["validation"] + COUNTS["final_test"]
```

and inside `_collection_fixture` use:

```python
    split = {
        "train": [{"candidate": f"TRAIN{i:09d}AA-BBBBBBBBBB-C"} for i in range(COUNTS["train"])],
        "validation": [
            {"candidate": f"VALID{i:09d}AA-BBBBBBBBBB-C"} for i in range(COUNTS["validation"])
        ],
        "final_test": [
            {"candidate": f"FINAL{i:09d}AA-BBBBBBBBBB-C"} for i in range(COUNTS["final_test"])
        ],
    }
```

with `"required_candidate_count": COHORT_SIZE` in the config dict, and update the
three existing assertions from `9` to `COHORT_SIZE` and the frame counts from
`{"train": 10, "validation": 4, "final_test": 4}` to
`{"train": COUNTS["train"] * 2, "validation": COUNTS["validation"] * 2, "final_test": COUNTS["final_test"] * 2}`.

Rename `test_collection_gate_requires_all_nine_pass_and_all_queues_exhausted` to
`test_collection_gate_requires_the_whole_frozen_cohort_and_all_queues_exhausted`.

Then append:

```python
def test_gate_remains_exact_match_not_n_of_m(tmp_path: Path) -> None:
    config, repo = _collection_fixture(tmp_path)
    runs = Path(config["paths"]["runs_root"])
    last = watcher.expected_candidates(config, repo)[-1][0]
    (runs / f"autofill_{last.lower()}_v001" / "controller_exit_code").unlink()
    snapshot = watcher.collection_snapshot(config, repo)
    assert snapshot["collection_complete"] is False
    assert snapshot["complete_candidate_count"] == COHORT_SIZE - 1


def test_orchestration_v003_binds_the_degraded_registry() -> None:
    config = json.loads((ROOT / "docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V003.json").read_text())
    supersession = json.loads(SUPERSESSION.read_text())
    assert config["data"]["split_path"] == "docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V003.json"
    assert config["data"]["split_sha256"] == supersession["split_v003_sha256"]
    assert config["data"]["required_candidate_count"] == COHORT_SIZE
    assert "candidate_replacement" in config["forbidden"]
    assert config["retry"] is False
    assert config["single_training_attempt"] is True


def test_orchestration_v003_reuses_the_untouched_lane_queue_digests() -> None:
    v002 = json.loads((ROOT / "docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V002.json").read_text())
    v003 = json.loads((ROOT / "docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V003.json").read_text())
    assert v003["collection"]["required_queue_sha256"] == v002["collection"]["required_queue_sha256"]
    assert v003["collection"]["required_queue_state_roots"] == v002["collection"]["required_queue_state_roots"]
    assert v003["paths"]["watch_state_root"] != v002["paths"]["watch_state_root"]


def test_watcher_final_test_root_is_generation_v003() -> None:
    assert watcher.FINAL_TEST_ROOT_NAME == "phase9b_aimnet2_final_test_v003"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_phase9b_aimnet2_finetune_watch.py -v`
Expected: FAIL — missing orchestration v003 file and missing
`watcher.FINAL_TEST_ROOT_NAME`.

- [ ] **Step 3: Create the orchestration v003 config**

Copy `docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V002.json` to
`docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V003.json` and change **only**:

```json
{
  "schema": "phase9b-aimnet2-finetune-orchestration-v002",
  "data": {
    "split_path": "docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V003.json",
    "split_sha256": "<SPLIT_V003_SHA256>",
    "required_candidate_count": 8
  },
  "paths": {
    "runs_root": "/home/plab/test/WJW/data/runs",
    "watch_state_root": "/home/plab/test/WJW/data/runs/phase9b_aimnet2_finetune_watch_v003"
  }
}
```

Keep `schema` at `phase9b-aimnet2-finetune-orchestration-v002` — the watcher's
`CONFIG_SCHEMA` check at `scripts/phase9b_aimnet2_finetune_watch.py:97` requires
it. Keep `collection.required_queue_state_roots` and
`collection.required_queue_sha256` byte-identical to v002 (rule R5). Keep
`forbidden`, `retry`, `single_training_attempt`, `production_accepted`,
`science_pilot_only`, `base_bundle`, `training_model`, `resource_preflight`, and
`post_freeze_evaluation` unchanged. Substitute the real `N`.

- [ ] **Step 4: Fix the hard-coded final-test root name**

In `scripts/phase9b_aimnet2_finetune_watch.py`, add next to the other module
constants:

```python
FINAL_TEST_ROOT_NAME: Final = "phase9b_aimnet2_final_test_v003"
```

and change line 459 from:

```python
    final_test_root = training_root.parent / "phase9b_aimnet2_final_test_v002"
```

to:

```python
    final_test_root = training_root.parent / FINAL_TEST_ROOT_NAME
```

Do **not** change `collection_snapshot` (`:130-215`). The gate predicate at
`:212-214` stays exactly as written — rule R6.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_phase9b_aimnet2_finetune_watch.py -v`
Expected: all pass.

- [ ] **Step 6: Record the new digests**

Run: `python3 -c "import hashlib,pathlib; [print(p, hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()) for p in ['scripts/phase9b_aimnet2_finetune_watch.py','docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V003.json','docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json']]"`

- [ ] **Step 7: Run the full gate and commit**

```bash
python3 -m pytest -q && python3 -m ruff check . && python3 -m ruff format --check . && python3 -m mypy
git add scripts/phase9b_aimnet2_finetune_watch.py docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V003.json tests/test_phase9b_aimnet2_finetune_watch.py
git commit -m "feat: bind the fine-tune watcher to the degraded v003 cohort"
```

---

## Task 7: Orchestrator withdrawal reconciliation and pipeline config v002

**Files:**
- Modify: `scripts/phase9b_pipeline_orchestrator.py:204,302-312,676-693`
- Create: `docs/PHASE9B_PIPELINE_CONFIG_V002.json`
- Modify: `tests/test_phase9b_pipeline_orchestrator.py`

**Interfaces:**
- Consumes: all five program digests recorded in Tasks 4–6, the orchestration
  v003 and generation v003 digests (Task 6 Step 6), and the withdrawal list from
  `docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002_SUPERSESSION.json`.
- Produces:
  - `COHORT_STATE: Final[str] = "WAIT_FOR_FROZEN_COHORT_PASS"`
  - `_withdrawn_candidate_set(config: dict[str, Any]) -> set[str]`
  - `derive_pipeline_state` returning `COHORT_STATE` where it previously
    returned `"WAIT_FOR_9_OF_9_PASS"`.

The key semantic change: the lane queue registry keeps all nine InChIKeys
(the queue files are untouched), and the split registry has `N`. The
orchestrator now requires

```text
set(expected_candidates) == split_candidate_set | withdrawn_candidate_set
set()                    == split_candidate_set & withdrawn_candidate_set
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_phase9b_pipeline_orchestrator.py`:

```python
CONFIG_V002 = ROOT / "docs/PHASE9B_PIPELINE_CONFIG_V002.json"
SUPERSESSION = ROOT / "docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002_SUPERSESSION.json"


def test_pipeline_config_v002_keeps_nine_queue_candidates_and_all_112_cpus() -> None:
    config, _ = orchestrator.load_config(CONFIG_V002, ROOT)
    cpus = {
        cpu for lane in config["lanes"] for cpu in orchestrator.parse_cpu_list(lane["cpu_list"])
    }
    assert cpus == set(range(112))
    assert len(config["expected_candidates"]) == 9
    assert config["retry"] is False
    assert config["candidate_replacement"] is False
    assert config["production_accepted"] is False
    assert config["speed_benchmark_after_freeze"] is False


def test_pipeline_config_v002_reconciles_split_with_withdrawn_candidates() -> None:
    config, _ = orchestrator.load_config(CONFIG_V002, ROOT)
    supersession = json.loads(SUPERSESSION.read_text())
    withdrawn = {item["candidate"] for item in supersession["withdrawn"]}
    assert {item["candidate"] for item in config["withdrawn_candidates"]} == withdrawn
    assert config["identities"]["required_candidate_count"] == 9 - len(withdrawn)


def test_config_rejects_an_unaccounted_split_deletion(tmp_path: Path) -> None:
    payload = json.loads(CONFIG_V002.read_text())
    payload["withdrawn_candidates"] = []
    path = tmp_path / "unaccounted.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(orchestrator.PipelineOrchestratorError, match="withdrawal"):
        orchestrator.load_config(path, ROOT)


def test_config_rejects_a_withdrawn_candidate_that_is_still_in_the_split(tmp_path: Path) -> None:
    payload = json.loads(CONFIG_V002.read_text())
    survivor = sorted(
        set(payload["expected_candidates"])
        - {item["candidate"] for item in payload["withdrawn_candidates"]}
    )[0]
    payload["withdrawn_candidates"].append(
        {"candidate": survivor, "split": "train", "reason_code": "TERMINAL_FAILED"}
    )
    path = tmp_path / "overlap.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(orchestrator.PipelineOrchestratorError, match="withdrawal"):
        orchestrator.load_config(path, ROOT)


def test_state_machine_reports_the_frozen_cohort_state() -> None:
    lanes = [{"lane_terminal": None, "queue_exhausted": True} for _ in range(4)]
    fine = {
        "terminal": None,
        "training_claimed": False,
        "dataset_claimed": False,
        "latest_snapshot": {"body": {"collection_complete": True}},
    }
    assert orchestrator.derive_pipeline_state(lanes, fine) == "WAIT_FOR_FROZEN_COHORT_PASS"
    assert orchestrator.COHORT_STATE == "WAIT_FOR_FROZEN_COHORT_PASS"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_phase9b_pipeline_orchestrator.py -v`
Expected: FAIL — missing `docs/PHASE9B_PIPELINE_CONFIG_V002.json` and missing
`orchestrator.COHORT_STATE`.

- [ ] **Step 3: Implement withdrawal reconciliation**

In `scripts/phase9b_pipeline_orchestrator.py`, add the constant next to the
other module constants:

```python
COHORT_STATE: Final = "WAIT_FOR_FROZEN_COHORT_PASS"
WITHDRAWAL_REASON_CODES: Final = frozenset({"TERMINAL_FAILED", "NEVER_LAUNCHED"})
```

Add the reader above `load_config`:

```python
def _withdrawn_candidate_set(config: dict[str, Any]) -> set[str]:
    entries = config.get("withdrawn_candidates")
    if not isinstance(entries, list):
        raise PipelineOrchestratorError("withdrawal registry is missing")
    result: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise PipelineOrchestratorError("withdrawal entry is invalid")
        candidate = entry.get("candidate")
        if not isinstance(candidate, str) or not INCHIKEY.fullmatch(candidate):
            raise PipelineOrchestratorError("withdrawal candidate identity is invalid")
        if candidate in result:
            raise PipelineOrchestratorError("withdrawal registry repeats a candidate")
        if entry.get("split") not in {"train", "validation", "final_test"}:
            raise PipelineOrchestratorError("withdrawal entry has no split")
        if entry.get("reason_code") not in WITHDRAWAL_REASON_CODES:
            raise PipelineOrchestratorError("withdrawal reason code is not permitted")
        result.add(candidate)
    return result
```

Replace line 204:

```python
    if identities.get("required_candidate_count") != 9:
        raise PipelineOrchestratorError("candidate count must remain nine")
```

with:

```python
    withdrawn = _withdrawn_candidate_set(config)
    if identities.get("required_candidate_count") != 9 - len(withdrawn):
        raise PipelineOrchestratorError("candidate count must equal the surviving cohort")
```

Replace the final check of the `expected_candidates` block (line 312):

```python
    if _candidate_set_from_split(finetune, resolved_repo) != set(expected_candidates):
        raise PipelineOrchestratorError("fine-tune split and pipeline candidates differ")
```

with:

```python
    split_candidates = _candidate_set_from_split(finetune, resolved_repo)
    if split_candidates & withdrawn:
        raise PipelineOrchestratorError("withdrawal registry overlaps the surviving split")
    if split_candidates | withdrawn != set(expected_candidates):
        raise PipelineOrchestratorError("withdrawal registry does not reconcile lane queues")
```

Leave lines 302-310 (`len(expected_candidates) != 9`, sortedness, uniqueness,
`queue_candidates != set(expected_candidates)`) exactly as they are — the lane
queues still cover all nine and must keep doing so (rule R5).

Replace `"WAIT_FOR_9_OF_9_PASS"` at line 689 with `COHORT_STATE`.

- [ ] **Step 4: Create pipeline config v002**

Copy `docs/PHASE9B_PIPELINE_CONFIG_V001.json` to
`docs/PHASE9B_PIPELINE_CONFIG_V002.json` and change **only**:

- `schema` stays `phase9b-continuous-pipeline-config-v001` (the orchestrator's
  `SCHEMA` check at `:185` requires it).
- `identities.required_candidate_count`: `9` → `N` (expected `8`).
- All five `programs.*.sha256` values: the digests recorded in Tasks 4–6.
  Leave every `adopt_compatible_sha256` array unchanged — those describe the
  already-running v002 watchers and must remain readable for `snapshot`.
- `fine_tune.config_relative_path` → `docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V003.json`
  and `fine_tune.config_sha256` → its digest.
- `fine_tune.training_config_relative_path` → `docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json`
  and `fine_tune.training_config_sha256` → its digest.
- `fine_tune.watch_state_root_name` → `phase9b_aimnet2_finetune_watch_v003`;
  `dataset_root_name` → `phase9b_aimnet2_development_dataset_v003`;
  `training_root_name` → `phase9b_aimnet2_model_freeze_v003`;
  `final_test_root_name` → `phase9b_aimnet2_final_test_v003`.
- `deployment.orchestrator_state_root_name` → `phase9b_continuous_pipeline_orchestrator_v002`.
- Add the new top-level key, copied from the supersession record:

```json
  "withdrawn_candidates": [
    {
      "candidate": "CLXFIGGGSODORK-UHFFFAOYSA-N",
      "split": "train",
      "reason_code": "TERMINAL_FAILED"
    }
  ],
  "withdrawal_authority": "docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002_SUPERSESSION.json",
```

Leave `lanes` (including every `candidates` array and every `queue_sha256`),
`expected_candidates`, and all six top-level safety booleans byte-identical to
v001.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_phase9b_pipeline_orchestrator.py -v`
Expected: all pass. The pre-existing
`test_public_pipeline_config_is_bounded_and_covers_all_112_cpus` still asserts
the v001 digest `8c41b1dd…` against the untouched v001 file and must keep
passing unchanged.

- [ ] **Step 6: Run the full gate and commit**

```bash
python3 -m pytest -q && python3 -m ruff check . && python3 -m ruff format --check . && python3 -m mypy
git add scripts/phase9b_pipeline_orchestrator.py docs/PHASE9B_PIPELINE_CONFIG_V002.json tests/test_phase9b_pipeline_orchestrator.py
git commit -m "feat: reconcile the orchestrator against the withdrawal registry"
```

---

## Task 8: Update the frozen automation document and close the plan

**Files:**
- Modify: `docs/PHASE9B_CONTINUOUS_PIPELINE_AUTOMATION.md:28-38` and the owner table at `:15-23`
- Modify: `tests/test_phase9b_cohort_degradation.py`

**Interfaces:**
- Consumes: `COHORT_STATE` from Task 7.
- Produces: nothing consumed by later tasks. This is the final task.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_phase9b_cohort_degradation.py`:

```python
AUTOMATION = ROOT / "docs/PHASE9B_CONTINUOUS_PIPELINE_AUTOMATION.md"


def test_automation_document_no_longer_claims_a_nine_of_nine_gate() -> None:
    text = AUTOMATION.read_text()
    assert "WAIT_FOR_9_OF_9_PASS" not in text
    assert "WAIT_FOR_FROZEN_COHORT_PASS" in text


def test_automation_document_names_the_degradation_writer() -> None:
    text = AUTOMATION.read_text()
    assert "phase9b_cohort_degradation.py" in text
    assert "PHASE9B_AIMNET2_FINETUNE_SPLIT_V002_SUPERSESSION.json" in text


def test_automation_document_states_the_remaining_training_blocker() -> None:
    text = AUTOMATION.read_text()
    assert "BLOCKED_BEFORE_TRAINING" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_phase9b_cohort_degradation.py -k automation -v`
Expected: FAIL — `assert 'WAIT_FOR_9_OF_9_PASS' not in text`.

- [ ] **Step 3: Update the automation document**

In `docs/PHASE9B_CONTINUOUS_PIPELINE_AUTOMATION.md`, change the state machine
block at `:28-38` to:

```text
BIND_CONFIG
→ RUN_LANES
→ AUDIT_RESULTS
→ WAIT_FOR_FROZEN_COHORT_PASS
→ BUILD_DATASET_ONCE
→ WAIT_FOR_RESOURCES
→ TRAIN_ONCE
→ VALIDATE_AND_FREEZE
→ COMPLETE
```

Add one row to the owner table at `:15-23`:

```markdown
| `phase9b_cohort_degradation.py` | The single derivation of the surviving cohort, the split v003 registry, and the supersession record |
```

Change the `phase9b_aimnet2_finetune_watch.py` row from
"9/9 and four-queue gate" to
"whole-frozen-cohort and four-queue gate".

Append this section immediately after the state machine block:

```markdown
## Cohort degradation (generation v003)

`WAIT_FOR_FROZEN_COHORT_PASS` is an exact-match gate, not an N-of-M gate. It
requires every InChIKey in the frozen split registry to hold a `PASS` terminal,
every lane queue to be exhausted, and no unaccounted lane terminal. The gate was
never loosened; the registry was shrunk.

The surviving cohort is derived once by `scripts/phase9b_cohort_degradation.py`
from transcribed terminal evidence and frozen as
`docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V003.json`. Every withdrawn InChIKey is
accounted for with a reason code in
`docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002_SUPERSESSION.json`. No candidate was
retried, no candidate was substituted, no lane queue file was modified, no lane
evidence was rewritten, and no InChIKey moved between splits. The sealed
final-test cohort is byte-identical to v002.

This degradation restores forward motion only. Per `workflow-contract.md:43` a
5/2/2 pilot cohort already could not establish a general stopping rule, general
single-point-only eligibility, or statistical performance across the NHC domain;
a strictly smaller cohort supports strictly less. Generation v003 remains
`BLOCKED_BEFORE_TRAINING` on six unfrozen readiness gates
(`docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json`), and no watcher may be
launched against it until those gates are frozen — launching earlier would burn
the single authorized training attempt on a guaranteed failure.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_phase9b_cohort_degradation.py -v`
Expected: all pass.

- [ ] **Step 5: Verify no forbidden file was touched**

Run:

```bash
git status --porcelain
git diff --name-only HEAD~7..HEAD
```

Expected: `PHASE_STATUS.md`, `docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002.json`,
`docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V002.json`,
`docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V002.json`,
`docs/PHASE9B_PIPELINE_CONFIG_V001.json`, and
`scripts/phase9b_parent_level_autofill.py` appear in **neither** list.

- [ ] **Step 6: Confirm the v002 registry digest is still intact**

Run:

```bash
python3 -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002.json').read_bytes()).hexdigest())"
```

Expected: `772094bc08012f8f40c76994a1600985f11a1956bef66d2c7710006b3aa0b995`.

- [ ] **Step 7: Run the full gate and commit**

```bash
python3 -m pytest -q && python3 -m ruff check . && python3 -m ruff format --check . && python3 -m mypy
git add docs/PHASE9B_CONTINUOUS_PIPELINE_AUTOMATION.md tests/test_phase9b_cohort_degradation.py
git commit -m "docs: freeze the degraded cohort gate in the automation contract"
```

- [ ] **Step 8: Report, and do not deploy**

Report to the user:

- the surviving cohort composition and every withdrawal reason code;
- the new digests for split v003, orchestration v003, generation v003, and
  pipeline config v002;
- that the pipeline can now reach `BUILD_DATASET_ONCE` and will then block at
  `TRAIN_ONCE` on the six readiness gates;
- that `SINGLE_POINT_ONLY_PROMOTION` remains unreachable on this cohort;
- that `PHASE_STATUS.md` still needs an entry from its owner.

Do **not** start the v003 watcher. Do **not** SSH. Deployment is a separate,
separately-authorized action that must not happen before the readiness gates are
frozen (Part I.6).

---

## Post-plan work, explicitly out of scope

1. **Freeze the six readiness gates.** `EPOCH_ZERO_SELECTION_NOT_IMPLEMENTED`,
   `FINAL_TEST_EVALUATOR_INCOMPLETE`, `VALIDATION_SELECTION_GATES_NOT_FROZEN`,
   `BASELINE_ELIGIBILITY_GATES_NOT_FROZEN`,
   `FINAL_TEST_ACCEPTANCE_GATES_NOT_FROZEN`,
   `STOPPING_HANDOFF_PROMOTION_GATES_NOT_FROZEN`. Each needs an
   evidence-backed calibration design and user confirmation per
   `workflow-contract.md:62-63`. Until then `TRAIN_ONCE` fails closed.
2. **Accumulate a second cohort.** Per `workflow-contract.md:43` the only route
   to a domain-general claim is accumulating additional permanently assigned
   cohorts. That is new compute against the 86400 s wall and needs its own
   authorization.
3. **Route-limit calibration.** CLX timed out at 33 atoms and RBK is running at
   38 atoms under the same wall. Before any new cohort is launched, the
   relationship between molecule size and P01 wall-clock needs a frozen,
   evidence-backed limit — otherwise the next cohort deadlocks the same way.
4. **`PHASE_STATUS.md` entry**, written by its owner.
