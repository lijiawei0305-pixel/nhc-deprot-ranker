# Phase 9B AIMNet2 Training-Readiness Unblock Implementation Plan

> **2026-08-01 route amendment:** the current user-selected target is
> `PRECONDITIONER_FULL_PARENT_OPT`, not `SINGLE_POINT_ONLY_CANDIDATE`. AIMNet2
> reaches the frozen five-metric AIMNet2 `GAU_LOOSE` profile plus its `Fmax <=
> 0.10 eV/Angstrom` cap within at most 100 ASE-LBFGS steps, then hands the exact
> geometry bytes to a mandatory full Parent-Level P01 PySCF/geomeTRIC
> optimization. Its first successful parent energy/analytic gradient is only
> `PARENT_GAU_LOOSE_GRADIENT_CHECK`; PASS and MISS both continue to final
> parent `GAU`. The single-point-only promotion tasks below are
> retained as a historical analysis of the stronger route, but they are not the
> current implementation authority. The new route remains blocked until its
> parent-gradient reduction, compute-burden reduction, and signed final-label
> invariance gates are preregistered; neither Fmax nor the first parent gradient
> alone can satisfy those gates. Sections below that describe a static
> single-point intended-use route are historical stronger-route analysis and
> are not active implementation authority.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear all six `blocking_reason_codes` that hold the AIMNet2 fine-tuning generation at `BLOCKED_BEFORE_TRAINING`, so that a registered generation can legally enter `TRAINING_CLAIMED` without any threshold being invented, inherited, or chosen after seeing results.

**Architecture:** Four of the six blockers are threshold-freezing work and two are implementation work, but they are not independent: every threshold instantiates a *gate object*, and no gate object exists yet in code. The plan therefore builds one shared, pure-Python **gate library** and one **stopping-contract state machine** first, then instantiates the four frozen-gate sets against them, then rewrites the trainer's selection path and the final-test evaluator to consume them. Numeric values that no repository authority supplies are not invented here: they are presented as evidence-backed calibration designs with an explicit user-confirmation marker, and where the contract forbids pre-training instantiation the plan freezes the *rule plus a bounded candidate grid plus a deterministic selection procedure* instead of a number.

**Tech Stack:** Python 3.11 (server `mlff`/`gpupyscf` envs) and CPython 3.14 for the local gate; `pytest`; `aimnet 0.2.0` / `torch 2.8.0` (server only, never imported by the pure modules); PySCF 2.13.1 + `pyscf-dispersion` 1.5.0 through the unchanged runner v9 boundary.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from repository authority.

- `science_pilot_only: true`, `production_accepted: false`, `production_label_inserted: false` on every artifact this plan creates (`docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V002.json:4-5`).
- `single_training_attempt: true`, `retry: false` (`docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V002.json:5-6`). No task may add a retry, a replacement candidate, or an extension cohort.
- Orchestration `forbidden` list is binding: `retry`, `candidate_replacement`, `final_test_model_selection`, `production_label_insertion`, `production_runner_change`, `speed_benchmark` (`docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V002.json:50-57`).
- Runner v9 source is frozen. The validation and final-test routes consume Parent-Level P01 through the existing runner boundary as a black box; no task in this plan edits runner v9.
- Fail-closed everywhere: "If a required threshold is absent, ambiguous, contradictory, or chosen after seeing results, return `PROMOTION_BLOCKED`" (`aimnet2-handoff-promotion.md:139-141`).
- Immutable evidence: every writer uses the existing `write_new` (`O_CREAT|O_EXCL|O_NOFOLLOW`, fsync, reread) pattern already in `scripts/phase9b_aimnet2_finetune.py:76-91`.
- Final-test payload must never be mounted, opened, hashed, enumerated, or preprocessed by the training process (`model-generation-contract.md:84-94`).
- Parent-Level P01 is frozen as: gas-phase closed-shell RKS, omegaB97M-D3(BJ)/def2-TZVPP, two-body D3(BJ) with ATM disabled and VV10 disabled, PySCF grid level 4, SCF `conv_tol 1e-9` (`docs/PHASE9B_AIMNET2_FINETUNE_DATA_PLAN.md:10-15`).
- AIMNet2 energy is an optimization signal only and never enters the label (`workflow-contract.md:7`).
- Do not modify `PHASE_STATUS.md` as part of this plan; another agent owns it.

---

## Part A — Blocker analysis

This is the spec. Each blocker states what the contract requires, what is missing in code today, and what must happen for the readiness flag to become `true`.

### Structural finding that gates all six: V002 cannot be unblocked in place

`model-generation-contract.md:57` declares `REGISTERED -> BLOCKED_BEFORE_TRAINING [terminal]`, and `:74-78` adds: "Make terminal failure and rejection states immutable. Never move backward, rewrite a result, reuse a consumed test, or tune the same generation after final-test. A later scientific attempt is a new generation with a new ID, manifest, output root, and unopened final-test cohort."

`docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V002.json:9` sets `readiness.state = "BLOCKED_BEFORE_TRAINING"`. Editing that field to `REGISTERED` — which is exactly what `scripts/phase9b_aimnet2_finetune.py:112-113` demands before it will run — is a backward transition out of a terminal state.

**Consequence:** the six flags must be satisfied on a *new* generation `phase9b-aimnet2-nhc-p01-v003`, with a new generation ID, a new manifest, and a new `training_root`. V002 stays terminal and untouched.

**Concurrent work — do not create a competing V003.** `docs/PHASE9B_COHORT_DEADLOCK_RESOLUTION_PLAN.md` (untracked in this working tree, owned by another agent) independently reaches the same conclusion and already schedules the creation of `docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json` with `generation_id: "phase9b-aimnet2-nhc-p01-v003"` (its Task at `:1459-1571`), deliberately keeping `readiness.state = "BLOCKED_BEFORE_TRAINING"` and all six codes intact because "the readiness blockers are separately frozen" and "outside this plan" (`:191-195, 498`). The two plans dovetail exactly: that plan re-seals the *cohort*, this plan clears the *readiness gates* on the record it produces. Task 7 below is written to amend that record rather than to create a second one. If the cohort plan has not landed when Task 7 starts, Task 7 creates the record itself using the same generation ID and the V002 cohort.

**Cohort-size coupling.** The cohort plan shrinks the frozen cohort below 5/2/2. Every statement in this plan about cohort adequacy (CONFIRM-5, CONFIRM-6) is stated for 5/2/2 and holds *a fortiori* for any smaller cohort. Task 4 must read the final candidate counts from whichever split registry V003 binds, not from `docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002.json`.

**Re-using the sealed cohort:** V003 may bind the same sealed final-test commitment (`split_registry_sha256 772094bc…`, `candidate_count 2`) only if the cohort is provably unopened. The contract's test is "an independent access audit proves no payload open, hash, enumeration, preprocessing, or consumption claim" (`model-generation-contract.md:106-109`). The available local evidence is consistent with unopened — V002 never left `BLOCKED_BEFORE_TRAINING`, so `phase9b_aimnet2_finetune.py:112` and `phase9b_aimnet2_final_test.py:102` both refuse before any read, and the watch script terminates at `BLOCKED_BEFORE_TRAINING` before dataset assembly (`scripts/phase9b_aimnet2_finetune_watch.py:415-425`) — but local source inspection is not an access audit. **CONFIRM-0** below covers this.

### Blocker 1 — `EPOCH_ZERO_SELECTION_NOT_IMPLEMENTED`

**What the contract requires.** `model-generation-contract.md:26-31`: "Evaluate the unchanged base AIMNet2 as `epoch_0000` on the exact validation inputs, aggregation rules, and complete intended-use path used for fine-tuned checkpoints. Keep it eligible for selection." And `:32-36`: "Select a fine-tuned checkpoint only if it satisfies every frozen validation gate relative to epoch 0. If no checkpoint does, select epoch 0 as the no-op result, mark the fine-tune generation `VALIDATION_REJECTED`, and do not consume final-test. Never force selection of an epoch merely because training ran." Plus `:47-49`: "Aggregate by InChIKey/candidate before selection."

**What is missing (verified in code).**

| Gap | Location | Detail |
| --- | --- | --- |
| Epoch 0 is measured but never a selection candidate | `scripts/phase9b_aimnet2_finetune.py:583` | `baseline_validation = _evaluate(...)` is computed, then only stored in the result at `:683`. It never enters the comparison. |
| Selection can never return epoch 0 | `scripts/phase9b_aimnet2_finetune.py:586-588, 613` | `best_loss = math.inf`, `best_epoch = -1`; `improved = validation_loss < best_loss` compares only against previous fine-tuned epochs, so epoch 1 always wins by construction. |
| Selection is forced | `scripts/phase9b_aimnet2_finetune.py:641-642` | `if best_state is None or best_epoch <= 0: raise FineTuneError("fine-tuning produced no selectable validation checkpoint")` — the "no fine-tuned checkpoint qualifies" case is an error, not the contract's `VALIDATION_REJECTED` outcome. |
| No `VALIDATION_REJECTED` path exists | `scripts/phase9b_aimnet2_finetune.py:697` | `"final_outcome": "MODEL_FROZEN"` is an unconditional literal. `grep` over the repository finds `VALIDATION_REJECTED` only inside the contract reference, never in `scripts/` or `src/`. |
| Aggregation is by frame, not by candidate | `scripts/phase9b_aimnet2_finetune.py:352-379` | `_evaluate` accumulates over `samples` (frames) and `force_components`, returning `weighted_loss`, `energy_mae_ev`, `force_mae_ev_per_angstrom`. Nothing is keyed by InChIKey. |
| Candidate identity is unreachable from the loader | `scripts/phase9b_aimnet2_training_dataset.py:441` writes a `candidate` array into the NPZ, but `docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V002.json:43-44` restricts `x`/`y` to `["coord","numbers","charge"]` / `["energy","forces"]`, and `scripts/phase9b_aimnet2_finetune.py:416` builds `SizeGroupedDataset(..., keys=x_keys + y_keys)`. The candidate column is on disk and never loaded. |
| Epoch 0 is not evaluated on the intended-use path | `scripts/phase9b_aimnet2_finetune.py:583` | `_evaluate` is a dataset loss over stored P01 frames. The intended use is AIMNet2 geometry optimization → exact-byte handoff → P01 single point → label (`aimnet2-handoff-promotion.md:7-13`). A frame loss is not that path. |

**Classification: implementation work, plus a dependency on Blocker 3.** The mechanical parts (candidate key plumbing, epoch 0 as candidate `0000`, the `VALIDATION_REJECTED` terminal, removal of the forced-selection raise) need no numbers and can start immediately. The adjudication step — "satisfies every frozen validation gate relative to epoch 0" — cannot be written until Blocker 3 defines what those gates are.

### Blocker 2 — `FINAL_TEST_EVALUATOR_INCOMPLETE`

**What the contract requires.** `aimnet2-handoff-promotion.md:100-123` requires the evaluator to run both routes from the same frozen initial XYZ and to measure, by candidate and endpoint: AIMNet2 completion and failure class; P01 analytic-gradient norm and maximum component at the handed-off geometry; aligned all-atom, heavy-atom and reaction-centre geometry metrics; connectivity, collision, proton identity and C2-centred geometry; signed endpoint penalty `E_assisted_geometry_SP - E_pure_PySCF_optimized_SP`; signed label error `label_assisted_geometry_SP - label_pure_PySCF_optimized_SP`; and candidate-level success rate and systematic direction. `model-generation-contract.md:140-145` adds that the evaluator must evaluate the fine-tuned bundle and the unchanged base on identical inputs, may not select a checkpoint or change a threshold, and must "Mark every revealed candidate permanently `consumed/historical` in the append-only registry."

**What is missing (verified in code).**

| Gap | Location | Detail |
| --- | --- | --- |
| The evaluator never runs the intended-use route | `scripts/phase9b_aimnet2_final_test.py:175-189` | It calls `helper.evaluate_frozen_bundle` twice — once for the frozen bundle, once for the base — and that helper (`scripts/phase9b_aimnet2_finetune.py:382-440`) is a dataset-loss evaluator. No geometry optimization is run, no handoff is proved, no PySCF single point is invoked. |
| No parent-gradient, geometry, endpoint-penalty, or label-error measurement exists | `scripts/phase9b_aimnet2_final_test.py:192-207` | The result carries only `frozen_generation_metrics` and `unchanged_base_metrics`, each of which is the three-scalar dict from `_evaluate`. Every quantity required by `aimnet2-handoff-promotion.md:106-118` is absent. |
| Metrics are frame-level, not candidate-level | `scripts/phase9b_aimnet2_finetune.py:372-379` | Same aggregation defect as Blocker 1, inherited by the evaluator. Violates `reference-data-contract.md:93`. |
| No adjudication | `scripts/phase9b_aimnet2_final_test.py:203` | `"final_test_decision": "UNADJUDICATED_THRESHOLDS_NOT_FROZEN"` is a literal. There is no `FINAL_TEST_ACCEPTED` / `FINAL_TEST_REJECTED` terminal and no `rejection_reason_code` emission of the stable codes required by `model-generation-contract.md:168-172`. |
| Two invariants are asserted, not proved | `scripts/phase9b_aimnet2_final_test.py:201-202` | `"checkpoint_selection_changed": False` and `"thresholds_changed": False` are hardcoded literals. Nothing binds the pre-registered threshold document hash and compares it after evaluation. |
| Evaluator identity is under-bound | `scripts/phase9b_aimnet2_final_test.py:129, 137` | `evaluator_source = Path(__file__)` and `"evaluator_sha256": sha256_bytes(read_regular(evaluator_source))` bind only this one file, while the process also executes the dataset helper (`:149`) and exec-loads the fine-tune helper (`:173`). `model-generation-contract.md:118-125` requires a pre-registered evaluator source *and* configuration. |
| The consumption record is not an append-only registry | `scripts/phase9b_aimnet2_final_test.py:142` | The claim is written to `output_root / "consumption_claim.json"`, inside the run's own freshly created directory (`:117`). `model-generation-contract.md:145` requires marking candidates `consumed/historical` in an append-only registry that outlives the run, and `:134-139` requires an isolation-invalidation receipt path that does not exist at all. |

**Classification: substantial implementation work.** It depends on Blocker 6 (the route it must execute must first exist and be specified) and on Blocker 5 (the numbers it adjudicates against).

### Blocker 3 — `VALIDATION_SELECTION_GATES_NOT_FROZEN`

**What the contract requires.** `model-generation-contract.md:32-33`: "Select a fine-tuned checkpoint only if it satisfies every frozen validation gate relative to epoch 0." `:47-50`: use validation only for trainable-layer, loss, optimizer, stopping, hyperparameter and checkpoint choices; aggregate by candidate; preserve signed differences and exact units; "Apply the frozen tie-break only after all scientific gates pass." `aimnet2-handoff-promotion.md:133` names promotion gate 8 as "validation success relative to unchanged base AIMNet2". `workflow-contract.md:64`: "If a required numeric threshold has no frozen authority, present an evidence-backed calibration design and request confirmation. Do not invent a threshold or consume final-test data to choose it."

**What is missing (verified in code).** `docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V002.json:77-82` defines `checkpoint_selection` as `metric: validation_weighted_loss`, `direction: minimum`, `tie_break: earliest_epoch`. That is the tie-break, and the contract says a tie-break is applied *after* the scientific gates pass — but no scientific gate exists. Worse, a single scalar loss minimum is precisely what `aimnet2-handoff-promotion.md:141` forbids: "A good mean cannot override an individual hard failure." No per-candidate, per-endpoint, signed gate exists anywhere in `scripts/` or `src/`.

**Classification: threshold freezing, plus the candidate-aggregation implementation it shares with Blocker 1.** Needs the gate objects from Blocker 6's structural half before the numbers can be attached to anything.

### Blocker 4 — `BASELINE_ELIGIBILITY_GATES_NOT_FROZEN`

**What the contract requires.** `model-generation-contract.md:36-45`: "When no fine-tuned checkpoint qualifies and epoch 0 would be the no-op fallback, epoch 0 must also pass every absolute structure, parent-gradient, endpoint, label, and applicability gate required for the intended use. If it does not, record rejection_reason_code=`BASELINE_INELIGIBLE`, keep the fine-tune generation `VALIDATION_REJECTED`, and do not describe the unchanged base as an eligible replacement. This fallback check does not disqualify a fine-tuned checkpoint that independently passes every absolute and relative frozen gate."

**What is missing (verified in code).** `grep -rn "BASELINE_INELIGIBLE"` over the repository returns exactly one hit — `model-generation-contract.md:169` — and nothing in `scripts/` or `src/`. There is no absolute-gate evaluator and no reason-code vocabulary.

**Classification: threshold freezing, but not independent of Blocker 3.** The insight is that Blocker 3 and Blocker 4 are the *relative* and *absolute* arms of one gate library: the same five gate families (structure, parent-gradient, endpoint penalty, label error, applicability) evaluated once against epoch 0 (relative, Blocker 3) and once against a fixed bound (absolute, Blocker 4). Freezing them as one artifact is the only way to keep them consistent; freezing them separately invites the contradiction that `aimnet2-handoff-promotion.md:139-141` treats as `PROMOTION_BLOCKED`.

### Blocker 5 — `FINAL_TEST_ACCEPTANCE_GATES_NOT_FROZEN`

**What the contract requires.** `aimnet2-handoff-promotion.md:124-137` lists the ten promotion gates in order, of which gate 9 is "one-time final-test acceptance on unopened candidates" and gate 10 is "any separately frozen reliability, domain, and efficiency requirements". `:139-143`: only thresholds frozen before the relevant measurements may be used; a good mean cannot override an individual hard failure; a failed chemistry, gradient or label gate may not be traded for speed.

**What is missing (verified in code).** `scripts/phase9b_aimnet2_final_test.py:203` is the entire state of this gate: a string constant announcing its own absence.

**A second, harder gap — cohort adequacy.** `workflow-contract.md:43`: "A 5 train / 2 validation / 2 final-test cohort is a pilot cohort. It can test mechanics and expose large failures, but it cannot establish a general stopping rule, general single-point-only eligibility, or statistical performance across the NHC domain." `docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002.json` is exactly a 5/2/2 cohort. `docs/AIMNET2_PROMOTION_GATES.md:71-73` (gate R1) "explicitly forbids promoting on the strength of one successful candidate" and defers the candidate count to a later plan. Two final-test candidates cannot satisfy R1 in any general sense. Freezing a final-test acceptance gate whose passing terminal is `SINGLE_POINT_ONLY_PROMOTED` would therefore be freezing a gate the contract already says this cohort cannot support.

**Classification: threshold freezing plus one scope decision that only the user can make** (CONFIRM-6).

### Blocker 6 — `STOPPING_HANDOFF_PROMOTION_GATES_NOT_FROZEN`

**What the contract requires.** `aimnet2-handoff-promotion.md:20-36` lists thirteen field groups that must be bound before validation or final-test optimization. `:43-49` requires exactly one of three endpoint stopping states. `:56-67` requires *all* stopping predicates on the same accepted step. `:86-98` requires exact-byte handoff. `:124-137` requires the ten ordered promotion gates.

**What is missing (verified in code).** `src/nhc_deprot_ranker/preparation/phase9b_preopt.py` is the only stopping implementation.

| Required by contract | Status in `phase9b_preopt.py` |
| --- | --- |
| complete-force stopping metric, threshold, evaluation interval, tie rule (`:31`) | Threshold present (`:44` `FMAX_EV_PER_A = 0.05`); evaluation interval and tie rule absent. |
| accepted-step energy-change rule, total and per-atom absolute delta, consecutive-pass streak length, exact reset behavior (`:32-33`) | **Entirely absent.** No energy-delta logic exists; `:390` tests only `last.max_force_ev_per_a <= FMAX_EV_PER_A`. `aimnet2-handoff-promotion.md:69-70` states explicitly that "the force gate cannot replace energy stabilization." |
| aligned RMS and max displacement from the initial **and preceding accepted** geometries (`:34-35`) | Only from initial (`:397-402`). The preceding-accepted-geometry arm is absent, and `rmsd` at `:204-211` is deliberately non-superposed, which is not the contract's "aligned" metric. |
| optimizer-health rules for oscillation, repeated/non-progressing frames, rejected steps, numerical exceptions (`:35-36`) | **Entirely absent.** |
| structural, disagreement/applicability, and failure gates (`:36`) | Structural gates present and good (`:404-430`). Disagreement/applicability absent: `:461-462` records `ensemble_members=1`, `ensemble_uncertainty_available=False`. |
| exactly one of `AIMNET2_CONVERGED` / `AIMNET2_LIMIT_REACHED` / `AIMNET2_FAILED` (`:43-49`) | Absent. The function raises `Phase9BPreoptError` (`:391-395`) or returns `converged=True` (`:441`); the three states never appear. `grep` finds them only in the contract and in narrative docs. |
| "accepted step index is strictly less than maximum steps" (`:66`) | **Contradicted.** `:377` raises only when `len(trajectory) - 1 > MAX_STEPS`, so a trajectory that used exactly `MAX_STEPS` steps is accepted as converged. `:71-72` states this case is `AIMNET2_LIMIT_REACHED`, "even if the final frame happens to satisfy a subset of the predicates." |
| external Coulomb and two-body D3(BJ) energy/force definitions (`:29-30`) | Not bound at optimize time. |
| optimizer settings, max wall limit, restart policy, device, dtype, deterministic settings (`:26-28`) | Constants exist (`:31, 49, 52`) but are not carried into `PreoptResult`; restart policy, device, dtype and deterministic settings are absent. |
| A production optimizer at all | `:29` `EXECUTION_AUTHORIZED: Final[bool] = False`; `:327-334` `build_production_optimizer` raises unconditionally. |

**And the constants are explicitly non-inheritable.** `aimnet2-handoff-promotion.md:38-41`: "Calibrate the stopping and handoff rule on training/development validation only. **Do not inherit a base-model `fmax`, step budget, or structural tolerance without validation under the frozen fine-tuned generation.** Do not change a rule after viewing final-test." Every constant in `phase9b_preopt.py:44-69` was derived for the *base* model against a *B3LYP-D3(BJ)/def2-SVP* parent level — see the comment block at `:37-43` naming the geomeTRIC 0.015-0.023 eV/Å band and a 0.088 eV/Å legacy model force error, and `:65-69` naming C2-N and ring-angle bounds. The current parent level is omegaB97M-D3(BJ)/def2-TZVPP Grid-4. The inherited 10-degree ring-angle bound is already known to fail: `docs/PHASE9B_SCIENCE_PILOT_V006_RESULT.json:109` records `"production_10_degree_gate": "failed_unchanged"` for the neutral endpoint.

**Promotion gates 4-7 and 10 have no numbers anywhere.** `docs/AIMNET2_PROMOTION_GATES.md` is a complete gate *inventory* (C1-C11, E1-E2, R1-R3) but supplies no numeric threshold for parent-gradient acceptance, geometry acceptance, endpoint penalty, or signed label error, and explicitly defers the E2 margin (`:62-63`) and the R1 candidate count (`:71-73`) to "the Phase 9B plan" — that is, to this document.

**Classification: both, and the largest of the six.** Roughly two-thirds implementation (energy-delta streak machinery, optimizer health, three-state classification, aligned metrics, applicability gate, exact-byte handoff proof) and one-third threshold freezing.

### The contract tension this plan must resolve

`scripts/phase9b_aimnet2_finetune.py:114-124` requires `stopping_handoff_promotion_gates_frozen` to be `true` **before training starts**. But `aimnet2-handoff-promotion.md:38-41` forbids fixing `fmax`, the step budget, or a structural tolerance without validating it "under the frozen fine-tuned generation" — which does not exist until after training. Read naively, the two rules make each other unsatisfiable.

They are reconcilable, because `aimnet2-handoff-promotion.md:22` binds the stopping contract "before validation or final-test **optimization**", not before training, and `:139` requires thresholds "frozen before the **relevant measurements**". The relevant measurement for a stopping threshold is the validation-geometry optimization, not the fine-tuning loop.

**Resolution adopted by this plan — the two-artifact split.** `stopping_handoff_promotion_gates_frozen` is satisfied by freezing, before training, an artifact containing:

1. the complete rule structure: which predicates, evaluated in which order, on which step, with what streak and reset semantics, producing which of the three states;
2. the complete decision procedure for every promotion gate, including ordering and the fail-closed default;
3. a **bounded candidate grid** of admissible numeric values for each quantity that cannot be fixed pre-training;
4. a **deterministic selection rule** over that grid — monotone, and evaluated only on development-validation candidates — so the resulting number is a function of preregistered inputs and cannot be chosen after seeing results;
5. the explicit prohibition on touching any of it after final-test is revealed.

The numeric instantiation is then produced by executing (4) after training, and sealed as an immutable addendum **before any validation-geometry optimization and before any final-test read**. This satisfies both rules. It changes the meaning of the readiness flag from "the numbers are frozen" to "the rule and its preregistered calibration procedure are frozen", which is a semantic change the user must ratify — **CONFIRM-7**.

---

## Part B — Thresholds requiring user confirmation

Per `workflow-contract.md:64`, each of these is presented as an evidence-backed calibration design, not a decision. **No value below may be written into a frozen artifact until the user confirms it.** None of the evidence cited comes from a final-test candidate.

### Evidence inventory (all pre-existing, all non-final-test)

| Anchor | Value | Source | Why it is usable |
| --- | --- | --- | --- |
| P01 Grid-4 analytic gradient at a base-AIMNet2 handed-off cation geometry | `gradient_max = 6.979380e-3` Ha/Bohr, `gradient_rms = 1.6430555e-3` Ha/Bohr | `docs/PHASE9B_PARENT_LEVEL_P01_R1_RESULT.json:67-68` | Candidate `LBNPGYISTSLAHY-UHFFFAOYSA-N` (`:6` of the V006 result) is **not** in `docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002.json` in any split. Correct parent level. The geometry (`:43`, `ea796a5c…`) is the AIMNet2 assisted cation output from `docs/PHASE9B_SCIENCE_PILOT_V006_RESULT.json:100`. |
| P01 Grid-4 numerical floor | `energy` 9.6465e-3 kcal/mol, `gradient_max` 7.979e-6 Ha/Bohr | `docs/PHASE9B_PARENT_LEVEL_P01_R1_RESULT.json:77, 79` | Grid-4 minus Grid-3 on a fixed geometry. Sets the level below which any threshold would be measuring integration noise. |
| Signed endpoint penalty, base model, cation | `+2.335953` kcal/mol | `docs/PHASE9B_SCIENCE_PILOT_V006_RESULT.json:193` | Order-of-magnitude anchor only — B3LYP/def2-SVP, one endpoint, base model. Must not be used as a threshold directly. |
| Assisted-vs-pure geometry deviation, base model, cation | aligned RMSD 0.250871 Å; max displacement 0.582139 Å; C2-N1 Δ 0.008862 Å; C2-N3 Δ 0.009524 Å; N1-C2-N3 Δ 0.039416° | `docs/PHASE9B_SCIENCE_PILOT_V006_RESULT.json:203-211` | Same caveats; establishes the scale the fine-tuned model must at minimum match. |
| Repository-frozen ranking indistinguishability band | `pairwise_tie_threshold_kcal: 1.0` | `configs/evaluation.yaml:13` | Repository authority, frozen long before Phase 9B. The project already declares label differences at or below 1.0 kcal/mol unresolvable for ranking. |
| Label-recomputation tolerance | `0.02` kcal/mol | `docs/SCIENCE_SCOPE.md:50`, `docs/DATA_CONTRACT.md:74` | Formula-reproducibility floor, not a method-accuracy budget. |
| Observed base-model optimizer cost | 54 steps (cation), 64 steps (neutral); final Fmax 0.045105 / 0.044275 eV/Å | `docs/PHASE9B_SCIENCE_PILOT_V006_RESULT.json:96-107` | Sets a realistic step-budget scale. |

### CONFIRM-0 — Unopened-cohort proof for the V002 sealed final-test commitment

The plan assumes V003 may re-bind `split_registry_sha256 772094bc…` with `candidate_count 2`. That requires an independent access audit proving no payload open, hash, enumeration, preprocessing, or consumption claim (`model-generation-contract.md:106-109`). Local source inspection supports it but does not constitute the audit. **Decision needed:** either (a) the isolation/final-test authority issues the unopened receipt and V003 re-binds the same cohort, or (b) the cohort is conservatively marked consumed/historical and V003 requires a new, never-committed final-test cohort — which the 5/2/2 pool cannot supply without new P01 reference candidates.

### CONFIRM-1 — Parent-gradient acceptance (promotion gate 4; absolute arm of Blockers 4 and 5)

- **Evidence.** The only measured P01 Grid-4 gradient at an AIMNet2-handed-off geometry is `gradient_max 6.979e-3`, `gradient_rms 1.643e-3` Ha/Bohr, produced by the *unchanged base model*. The Grid-4 numerical floor is `gradient_max` 7.98e-6 Ha/Bohr — three orders of magnitude below, so a threshold at the anchor scale is measuring physics, not noise.
- **Reasoning.** A fine-tuned generation whose handed-off geometries carry a larger parent gradient than the base model already achieved on a comparable NHC has not earned promotion. Setting the bound at the base-model anchor makes "no worse than base" the absolute floor. It is deliberately *not* set at the geomeTRIC convergence criterion (roughly 3e-4 Ha/Bohr max), because the assisted route never claims to reach a P01 stationary point (`docs/AIMNET2_STRUCTURE_VALIDATION.md:161-166`) and a gate that demanded it would be a disguised requirement to re-run the optimization.
- **Proposed values, per endpoint, hard-fail, no averaging:** `gradient_max <= 7.0e-3` Ha/Bohr and `gradient_rms <= 1.7e-3` Ha/Bohr (the anchor rounded up to two significant figures).
- **Known weakness the user must weigh.** The anchor is one candidate, one endpoint, one parent level. The neutral endpoint has no anchor at all, and the neutral carbene is the least certain region of the AIMNet2 surface (`docs/AIMNET2_STRUCTURE_VALIDATION.md:124-131`). The user may prefer a looser neutral bound, or may prefer to defer this number into the CONFIRM-7 candidate-grid mechanism.

### CONFIRM-2 — Geometry and reaction-centre acceptance (promotion gate 5)

- **Evidence.** Base-model, B3LYP/SVP: aligned RMSD 0.2509 Å, max displacement 0.5821 Å, C2-N Δ ≤ 0.0095 Å, ring angle Δ 0.0394°. Existing (non-inheritable) constants: RMSD 1.0 Å, single-atom 2.5 Å, C2-N 0.15 Å, ring angle 10.0°.
- **Reasoning.** The identity gates (connectivity under the identity permutation, proton host, atom order, C2 hydrogen count) carry no numeric freedom and are frozen as-is from `phase9b_preopt.py:404-414` — they are correct and contract-compliant. The *tolerances* are the problem: the inherited values are 40× to 250× looser than what the base model actually produced, which makes them incapable of detecting a regression, and the 10° ring-angle bound has already failed once in production form (`docs/PHASE9B_SCIENCE_PILOT_V006_RESULT.json:109`).
- **Proposed candidate grids** (instantiated by the CONFIRM-7 procedure on development-validation only): aligned heavy-atom RMSD ∈ {0.25, 0.30, 0.40, 0.50} Å; reaction-centre C2-N bond change ∈ {0.02, 0.03, 0.05} Å; N1-C2-N3 angle change ∈ {2.0, 3.0, 5.0}°; maximum single-atom displacement ∈ {0.60, 0.80, 1.00} Å.
- **Proposed selection rule:** the smallest grid value that every development-validation endpoint passes; if the largest grid value still fails, return `GEOMETRY_GATE_FAILED` and `PROMOTION_BLOCKED`. This is monotone and preregistered, so it cannot be relaxed after seeing results.

### CONFIRM-3 — Signed endpoint energy penalty (promotion gate 6)

- **Evidence.** `E_assisted_geometry_SP - E_pure_PySCF_optimized_SP = +2.335953` kcal/mol, base model, cation, B3LYP/def2-SVP. Grid-4 numerical floor 0.0096 kcal/mol.
- **Reasoning.** The penalty is positive by construction (the assisted geometry is not the P01 minimum, so its single-point energy is higher). Reducing it is the entire purpose of fine-tuning. An absolute ceiling *at* the base-model anchor would let a generation pass by changing nothing; a ceiling meaningfully below it requires genuine improvement.
- **Proposed values:** per endpoint, `|signed penalty| <= 2.0` kcal/mol as the absolute arm; plus a relative arm requiring the candidate-mean signed penalty to be strictly smaller in magnitude than epoch 0's on the same endpoints. Signed values preserved; absolute value reported as a secondary view only (`aimnet2-handoff-promotion.md:116-117`).
- **Known weakness.** The 2.336 anchor is at the wrong parent level. def2-TZVPP with Grid 4 may place the penalty at a different scale entirely. The user may prefer to route this number through the CONFIRM-7 grid instead of fixing it now.

### CONFIRM-4 — Signed deprotonation-label error and systematic bias (promotion gate 7)

- **Evidence.** `configs/evaluation.yaml:13` freezes `pairwise_tie_threshold_kcal: 1.0` — the band inside which this project already treats two candidates as unordered.
- **Reasoning.** The assisted route's purpose is to produce labels that rank the same way as pure-PySCF labels. An assisted-route label error smaller than the project's own tie band can never flip a pair the project considers resolvable. Taking half the band leaves a factor-of-two margin for the error in the *other* member of any compared pair. This derivation uses only repository authority; it invents nothing.
- **Proposed values:** per candidate, `|label_assisted_SP - label_pure_PySCF_SP| <= 0.50` kcal/mol (hard, individual, no averaging); and `|mean signed label error| <= 0.25` kcal/mol as the systematic-bias arm. Both required; per `aimnet2-handoff-promotion.md:141` the mean arm can never rescue an individual failure.
- **User must confirm** both the numbers and the "half the frozen tie band" derivation.

### CONFIRM-5 — Validation selection gates relative to epoch 0 (Blocker 3; promotion gate 8)

- **Evidence.** None exists. No fine-tuned NHC AIMNet2 generation has ever been trained in this project, so there is no distribution to calibrate against — and `single_training_attempt: true` / `retry: false` forbid producing one by repeating the run.
- **Reasoning.** Because no noise estimate can be obtained without a forbidden repeat, an absolute improvement threshold would be invented. A *relative* rule with a margin plus a no-individual-regression clause is the strongest honest construction: it can be stated fully before any measurement and it cannot be satisfied by noise in a favorable direction on one endpoint.
- **Proposed rule.** A fine-tuned checkpoint is selectable only if, aggregated by InChIKey over the two development-validation candidates: (a) candidate-mean `|signed endpoint penalty|` improves over epoch 0 by ≥ 10% relative; **and** (b) candidate-mean force MAE improves over epoch 0 by ≥ 10% relative; **and** (c) no individual endpoint of any validation candidate regresses relative to epoch 0 on either quantity; **and** (d) the checkpoint independently passes every absolute gate from CONFIRM-1 through CONFIRM-4. If no checkpoint qualifies, epoch 0 is selected as the no-op result and the generation becomes `VALIDATION_REJECTED`.
- **User must confirm** the 10% margin, clause (c), and — importantly — must acknowledge that two validation candidates make this a pilot gate that cannot support a statistical claim (`workflow-contract.md:43`).

### CONFIRM-6 — Final-test acceptance scope (Blocker 5) — the most consequential decision

- **Evidence.** `workflow-contract.md:43` states a 5/2/2 cohort "cannot establish … general single-point-only eligibility". `docs/AIMNET2_PROMOTION_GATES.md:71-73` (R1) forbids promoting on one candidate and defers the required count elsewhere. The sealed cohort is 2 candidates.
- **Reasoning.** Freezing a gate whose passing terminal is `SINGLE_POINT_ONLY_PROMOTED` would freeze a claim the cohort provably cannot support, and `aimnet2-handoff-promotion.md:84` forbids promoting directly from `AIMNET2_CONVERGED` to `SINGLE_POINT_ONLY_ELIGIBLE`.
- **Proposed freeze.** The final-test acceptance gate is identical in shape to the absolute arm (CONFIRM-1 … CONFIRM-4) plus "not worse than the unchanged base on identical inputs", applied exactly once, producing terminal `FINAL_TEST_ACCEPTED` or `FINAL_TEST_REJECTED`. And it is frozen, in the same artifact, that `FINAL_TEST_ACCEPTED` on a 2-candidate cohort **does not** authorize `SINGLE_POINT_ONLY_PROMOTED`; the maximum terminal reachable by this generation is `FINAL_TEST_ACCEPTED` with `single_point_only_eligible: false` and `promotion_blocked_reason: "PILOT_COHORT_INADEQUATE_FOR_GENERAL_ELIGIBILITY"`.
- **Also proposed:** efficiency gates E1/E2 are declared **out of promotion authority** for this generation, since `docs/PHASE9B_AIMNET2_FINETUNE_ORCHESTRATION_V002.json:48, 56` set `speed_benchmark: false` and list `speed_benchmark` as forbidden, and `aimnet2-handoff-promotion.md:118` requires frozen efficiency metrics only "when efficiency is part of promotion authority". This removes the deferred E2 margin and R1 count from the threshold list entirely rather than inventing them.
- **User must confirm** the terminal cap and the efficiency-out-of-scope declaration.

### CONFIRM-7 — The two-artifact split for the stopping contract (Blocker 6)

- **What is being asked.** Ratify that `stopping_handoff_promotion_gates_frozen: true` means "rule structure, decision procedure, bounded candidate grid, and deterministic monotone selection rule are frozen pre-training; numeric instantiation is produced by executing that frozen procedure on development-validation only, and sealed before any validation-geometry optimization and before any final-test read."
- **Why it is necessary.** Without it, `scripts/phase9b_aimnet2_finetune.py:114-124` and `aimnet2-handoff-promotion.md:38-41` are mutually unsatisfiable — see "The contract tension this plan must resolve" above.
- **Proposed candidate grids for the stopping numerics:** `fmax` ∈ {0.030, 0.040, 0.050} eV/Å; maximum steps ∈ {200, 300, 400}; wall limit ∈ {900, 1800} s; accepted-step total `|ΔE|` ∈ {1e-4, 3e-4, 1e-3} eV; accepted-step per-atom `|ΔE|` ∈ {1e-5, 3e-5, 1e-4} eV/atom; consecutive-pass streak ∈ {3, 5}; per-step aligned RMS displacement bound ∈ {0.05, 0.10} Å; non-progress window ∈ {10, 20} steps.
- **Proposed selection rule:** the tightest grid tuple under lexicographic order (fmax, then streak, then energy deltas) for which every development-validation endpoint returns `AIMNET2_CONVERGED` and passes CONFIRM-1 through CONFIRM-4; if no tuple qualifies, return `AIMNET2_FAILED` for the generation and `PROMOTION_BLOCKED`.
- **User must confirm** the split, the grids, and the selection rule.

---

## Part C — File structure

New pure modules carry no torch, ASE, aimnet, PySCF, or RDKit import at any level, matching the existing discipline in `src/nhc_deprot_ranker/preparation/phase9b_preopt.py:4-9`. This keeps every gate testable locally under CPython 3.14 with no GPU and no chemistry.

| File | Responsibility |
| --- | --- |
| `src/nhc_deprot_ranker/quantum/phase9b_gate_library.py` (create) | Pure gate objects and evaluation: parent-gradient, geometry/reaction-centre, signed endpoint penalty, signed label error, applicability. One `evaluate_*` per family, each returning a signed measurement plus pass/fail plus a stable `rejection_reason_code`. Absolute and relative arms share one implementation. |
| `src/nhc_deprot_ranker/preparation/phase9b_stopping_contract.py` (create) | The stopping state machine: accepted-step ledger, total and per-atom energy-delta streak with reset, aligned displacement vs. initial and vs. preceding accepted step, optimizer health, and the three-state classifier. No optimizer, no model. |
| `src/nhc_deprot_ranker/quantum/phase9b_candidate_aggregation.py` (create) | Frame-to-candidate aggregation keyed by InChIKey and endpoint, preserving signed differences and units. Consumed by both the trainer and the evaluator so they cannot diverge. |
| `docs/PHASE9B_AIMNET2_GATE_LIBRARY_V001.json` (create) | The frozen gate artifact: absolute arm, relative arm, final-test arm, candidate grids, selection rules, reason-code vocabulary, and the CONFIRM ratification record. Satisfies Blockers 3, 4, 5. |
| `docs/PHASE9B_AIMNET2_STOPPING_CONTRACT_V001.json` (create) | The frozen stopping/handoff/promotion artifact: all thirteen field groups from `aimnet2-handoff-promotion.md:22-36`, the ordered ten promotion gates, and the CONFIRM-7 calibration procedure. Satisfies Blocker 6. |
| `docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json` (create) | New generation `phase9b-aimnet2-nhc-p01-v003`, `readiness.state: "REGISTERED"`, all six flags `true`, binding both artifacts by SHA256. |
| `scripts/phase9b_aimnet2_finetune.py` (modify) | Epoch 0 as selection candidate `0000`; candidate-level aggregation; `VALIDATION_REJECTED` terminal; baseline-eligibility check; remove the forced-selection raise. |
| `scripts/phase9b_aimnet2_training_dataset.py` (modify) | Emit the candidate/endpoint weight audit required by `reference-data-contract.md:88-90, 106`; make the `candidate` and `endpoint` columns loadable. |
| `scripts/phase9b_aimnet2_validation_route.py` (create) | The intended-use route runner: AIMNet2 optimization under the stopping contract → exact-byte handoff proof → P01 single point via the unchanged runner v9 → gate-library measurement. Used by validation and, unchanged, by final test. |
| `scripts/phase9b_aimnet2_final_test.py` (modify) | Execute the intended-use route instead of a dataset loss; adjudicate against the frozen final-test arm; emit `FINAL_TEST_ACCEPTED`/`FINAL_TEST_REJECTED` with reason codes; bind all three evaluator sources; write to an append-only consumption registry; add the isolation-invalidation receipt path. |
| `tests/test_phase9b_gate_library.py`, `tests/test_phase9b_stopping_contract.py`, `tests/test_phase9b_candidate_aggregation.py`, `tests/test_phase9b_validation_route.py` (create) | Local, no-chemistry, fail-closed-first tests, following `docs/AIMNET2_STRUCTURE_VALIDATION.md:178-210`. |
| `tests/test_phase9b_aimnet2_finetune.py`, `tests/test_phase9b_aimnet2_final_test.py`, `tests/test_phase9b_aimnet2_training_dataset.py` (modify) | Extend for the new terminals, aggregation, and adjudication. |

---

## Part D — Task breakdown

Tasks are ordered by dependency. Every task ends with an independently testable deliverable and a commit. Run tests with CPython 3.14 per the verification-environment note; the repository `.venv` reports spurious failures.

### Task 1: Stopping-contract state machine (structural half of Blocker 6)

**Files:**
- Create: `src/nhc_deprot_ranker/preparation/phase9b_stopping_contract.py`
- Test: `tests/test_phase9b_stopping_contract.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `StoppingSettings` (frozen dataclass: `fmax_ev_per_a: float`, `max_steps: int`, `max_wall_seconds: float`, `energy_delta_total_ev: float`, `energy_delta_per_atom_ev: float`, `streak_length: int`, `step_rms_displacement_angstrom: float`, `initial_rms_displacement_angstrom: float`, `max_single_atom_displacement_angstrom: float`, `non_progress_window: int`); `AcceptedStep` (frozen dataclass: `index: int`, `coordinates: tuple[tuple[float,float,float], ...]`, `energy_ev: float`, `max_force_ev_per_a: float`, `accepted: bool`); `classify(steps: Sequence[AcceptedStep], settings: StoppingSettings, *, atom_count: int, wall_seconds: float) -> StoppingVerdict`; `StoppingVerdict` (frozen dataclass: `state: str` in `{"AIMNET2_CONVERGED","AIMNET2_LIMIT_REACHED","AIMNET2_FAILED"}`, `reason_code: str | None`, `accepted_step_index: int`, `predicates: Mapping[str, bool]`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_phase9b_stopping_contract.py
from __future__ import annotations

import pytest

from nhc_deprot_ranker.preparation import phase9b_stopping_contract as sc

SETTINGS = sc.StoppingSettings(
    fmax_ev_per_a=0.05,
    max_steps=200,
    max_wall_seconds=900.0,
    energy_delta_total_ev=3e-4,
    energy_delta_per_atom_ev=3e-5,
    streak_length=3,
    step_rms_displacement_angstrom=0.10,
    initial_rms_displacement_angstrom=1.0,
    max_single_atom_displacement_angstrom=2.5,
    non_progress_window=10,
)


def _steps(count: int, *, energy_step: float = 1e-5, force: float = 0.04):
    out = []
    for index in range(count):
        shift = 0.001 * index
        out.append(
            sc.AcceptedStep(
                index=index,
                coordinates=((0.0, 0.0, 0.0), (1.1 + shift, 0.0, 0.0)),
                energy_ev=-100.0 - energy_step * index,
                max_force_ev_per_a=2.0 if index == 0 else force,
                accepted=True,
            )
        )
    return out


def test_all_predicates_on_one_accepted_step_yields_converged() -> None:
    verdict = sc.classify(_steps(12), SETTINGS, atom_count=2, wall_seconds=30.0)
    assert verdict.state == "AIMNET2_CONVERGED"
    assert verdict.reason_code is None
    assert all(verdict.predicates.values())


def test_force_gate_alone_cannot_converge_without_the_energy_streak() -> None:
    """aimnet2-handoff-promotion.md:69 — the force gate cannot replace energy stabilization."""
    steps = _steps(12, energy_step=0.5)  # never stabilizes
    verdict = sc.classify(steps, SETTINGS, atom_count=2, wall_seconds=30.0)
    assert verdict.state == "AIMNET2_LIMIT_REACHED"
    assert verdict.predicates["energy_delta_total"] is False


def test_energy_streak_alone_cannot_converge_without_the_force_gate() -> None:
    steps = _steps(12, force=0.9)
    verdict = sc.classify(steps, SETTINGS, atom_count=2, wall_seconds=30.0)
    assert verdict.state == "AIMNET2_LIMIT_REACHED"
    assert verdict.predicates["fmax"] is False


def test_a_single_bad_step_resets_the_streak() -> None:
    steps = _steps(12)
    bad = steps[9]
    steps[9] = sc.AcceptedStep(
        index=bad.index,
        coordinates=bad.coordinates,
        energy_ev=bad.energy_ev + 0.5,
        max_force_ev_per_a=bad.max_force_ev_per_a,
        accepted=True,
    )
    verdict = sc.classify(steps[:11], SETTINGS, atom_count=2, wall_seconds=30.0)
    assert verdict.state == "AIMNET2_LIMIT_REACHED"


def test_exactly_max_steps_is_limit_reached_not_converged() -> None:
    """aimnet2-handoff-promotion.md:66 — strictly less than maximum steps."""
    settings = sc.StoppingSettings(**{**SETTINGS.__dict__, "max_steps": 11})
    verdict = sc.classify(_steps(12), settings, atom_count=2, wall_seconds=30.0)
    assert verdict.state == "AIMNET2_LIMIT_REACHED"
    assert verdict.reason_code == "STEP_BUDGET_EXHAUSTED"


def test_non_finite_energy_is_failed_not_limit_reached() -> None:
    steps = _steps(12)
    steps[5] = sc.AcceptedStep(
        index=5,
        coordinates=steps[5].coordinates,
        energy_ev=float("nan"),
        max_force_ev_per_a=0.04,
        accepted=True,
    )
    verdict = sc.classify(steps, SETTINGS, atom_count=2, wall_seconds=30.0)
    assert verdict.state == "AIMNET2_FAILED"
    assert verdict.reason_code == "NON_FINITE_VALUE"


def test_wall_limit_exhaustion_is_limit_reached() -> None:
    verdict = sc.classify(_steps(12), SETTINGS, atom_count=2, wall_seconds=901.0)
    assert verdict.state == "AIMNET2_LIMIT_REACHED"
    assert verdict.reason_code == "WALL_LIMIT_EXHAUSTED"


def test_non_progressing_frames_are_an_optimizer_health_failure() -> None:
    steps = _steps(12, energy_step=0.0)
    repeated = [
        sc.AcceptedStep(
            index=step.index,
            coordinates=steps[0].coordinates,
            energy_ev=steps[0].energy_ev,
            max_force_ev_per_a=step.max_force_ev_per_a,
            accepted=True,
        )
        for step in steps
    ]
    verdict = sc.classify(repeated, SETTINGS, atom_count=2, wall_seconds=30.0)
    assert verdict.state == "AIMNET2_FAILED"
    assert verdict.reason_code == "OPTIMIZER_NON_PROGRESS"


def test_the_three_states_are_the_only_states() -> None:
    assert sc.STOPPING_STATES == (
        "AIMNET2_CONVERGED",
        "AIMNET2_LIMIT_REACHED",
        "AIMNET2_FAILED",
    )


def test_empty_trajectory_fails_closed() -> None:
    with pytest.raises(sc.StoppingContractError):
        sc.classify([], SETTINGS, atom_count=2, wall_seconds=1.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.14 -m pytest tests/test_phase9b_stopping_contract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nhc_deprot_ranker.preparation.phase9b_stopping_contract'`

- [ ] **Step 3: Implement the state machine**

Implement `phase9b_stopping_contract.py` with `STOPPING_STATES`, `StoppingContractError`, the three dataclasses, and `classify`. `classify` evaluates, in this order and short-circuiting on the first failure class:

1. `AIMNET2_FAILED` conditions first — empty trajectory raises; any non-finite energy, coordinate, or force gives `NON_FINITE_VALUE`; atom-count change gives `ATOM_COUNT_CHANGED`; repeated-frame or zero-progress over `non_progress_window` gives `OPTIMIZER_NON_PROGRESS`; energy oscillation (sign of `ΔE` alternating across the whole window) gives `OPTIMIZER_OSCILLATION`.
2. `AIMNET2_LIMIT_REACHED` — `wall_seconds > max_wall_seconds` gives `WALL_LIMIT_EXHAUSTED`; final accepted index `>= max_steps` gives `STEP_BUDGET_EXHAUSTED` (strictly-less-than semantics, per `aimnet2-handoff-promotion.md:66`).
3. Otherwise evaluate all predicates on the final accepted step and require every one: `finite`, `fmax` (`max_force_ev_per_a <= fmax_ev_per_a`), `energy_delta_total` (`|ΔE| <= energy_delta_total_ev` for `streak_length` consecutive accepted steps, reset to zero by any violating step), `energy_delta_per_atom` (same streak, `|ΔE| / atom_count <= energy_delta_per_atom_ev`), `step_rms_displacement` (vs. the preceding accepted geometry), `initial_rms_displacement`, `max_single_atom_displacement`, `optimizer_health`, `step_index_below_maximum`. All true gives `AIMNET2_CONVERGED`; any false gives `AIMNET2_LIMIT_REACHED` with the failing predicate names in `predicates`.

Use superposed (Kabsch) alignment for the RMS metrics, since `aimnet2-handoff-promotion.md:34` says "aligned". Keep the existing non-superposed `rmsd` in `phase9b_preopt.py` untouched; it serves a different, stricter purpose there.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.14 -m pytest tests/test_phase9b_stopping_contract.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add src/nhc_deprot_ranker/preparation/phase9b_stopping_contract.py tests/test_phase9b_stopping_contract.py
git commit -m "feat: add AIMNet2 three-state stopping contract state machine"
```

### Task 2: Gate library (shared engine for Blockers 3, 4, 5)

**Files:**
- Create: `src/nhc_deprot_ranker/quantum/phase9b_gate_library.py`
- Test: `tests/test_phase9b_gate_library.py`

**Interfaces:**
- Consumes: nothing from Task 1 (deliberately independent, so both can be built in parallel).
- Produces: `GateResult` (frozen dataclass: `name: str`, `passed: bool`, `measured: float`, `threshold: float`, `units: str`, `reason_code: str | None`); `AbsoluteThresholds` (frozen dataclass: `gradient_max_hartree_per_bohr`, `gradient_rms_hartree_per_bohr`, `endpoint_penalty_kcal`, `label_error_kcal`, `systematic_bias_kcal`, `aligned_rmsd_angstrom`, `c2_n_bond_change_angstrom`, `ring_angle_change_degrees`, `max_single_atom_displacement_angstrom`); `evaluate_parent_gradient(...) -> GateResult`; `evaluate_geometry(...) -> tuple[GateResult, ...]`; `evaluate_endpoint_penalty(...) -> GateResult`; `evaluate_label_error(...) -> tuple[GateResult, ...]`; `evaluate_relative_to_baseline(candidate_metrics, baseline_metrics, *, margin: float) -> tuple[GateResult, ...]`; `REASON_CODES: tuple[str, ...]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_phase9b_gate_library.py
from __future__ import annotations

import pytest

from nhc_deprot_ranker.quantum import phase9b_gate_library as gl

ABSOLUTE = gl.AbsoluteThresholds(
    gradient_max_hartree_per_bohr=7.0e-3,
    gradient_rms_hartree_per_bohr=1.7e-3,
    endpoint_penalty_kcal=2.0,
    label_error_kcal=0.50,
    systematic_bias_kcal=0.25,
    aligned_rmsd_angstrom=0.30,
    c2_n_bond_change_angstrom=0.03,
    ring_angle_change_degrees=3.0,
    max_single_atom_displacement_angstrom=0.80,
)


def test_the_measured_base_model_anchor_passes_the_parent_gradient_gate() -> None:
    """docs/PHASE9B_PARENT_LEVEL_P01_R1_RESULT.json:67-68, base-model anchor."""
    result = gl.evaluate_parent_gradient(
        gradient_max=6.979380253908666e-3,
        gradient_rms=1.6430555132194219e-3,
        thresholds=ABSOLUTE,
    )
    assert result.passed is True
    assert result.units == "hartree_per_bohr"


def test_a_worse_gradient_than_the_base_anchor_fails_closed() -> None:
    result = gl.evaluate_parent_gradient(
        gradient_max=8.0e-3, gradient_rms=1.0e-3, thresholds=ABSOLUTE
    )
    assert result.passed is False
    assert result.reason_code == "PARENT_GRADIENT_FAILED"


def test_signed_label_error_is_preserved_not_absolute() -> None:
    hard, bias = gl.evaluate_label_error(
        signed_errors_kcal={"AAA": -0.40, "BBB": 0.30}, thresholds=ABSOLUTE
    )
    assert hard.passed is True
    assert bias.passed is True
    assert bias.measured == pytest.approx(-0.05)


def test_a_good_mean_cannot_rescue_one_hard_failure() -> None:
    """aimnet2-handoff-promotion.md:141."""
    hard, bias = gl.evaluate_label_error(
        signed_errors_kcal={"AAA": -0.90, "BBB": 0.88}, thresholds=ABSOLUTE
    )
    assert bias.passed is True
    assert hard.passed is False
    assert hard.reason_code == "SIGNED_LABEL_ERROR_FAILED"


def test_endpoint_penalty_keeps_its_sign() -> None:
    result = gl.evaluate_endpoint_penalty(signed_penalty_kcal=2.335952811, thresholds=ABSOLUTE)
    assert result.passed is False
    assert result.measured == pytest.approx(2.335952811)
    assert result.reason_code == "ENDPOINT_PENALTY_FAILED"


def test_relative_gate_requires_the_margin_and_forbids_any_regression() -> None:
    passed = gl.evaluate_relative_to_baseline(
        candidate_metrics={"AAA": 1.00, "BBB": 1.00},
        baseline_metrics={"AAA": 1.20, "BBB": 1.30},
        margin=0.10,
    )
    assert all(result.passed for result in passed)
    regressed = gl.evaluate_relative_to_baseline(
        candidate_metrics={"AAA": 0.50, "BBB": 1.40},
        baseline_metrics={"AAA": 1.20, "BBB": 1.30},
        margin=0.10,
    )
    assert any(not result.passed for result in regressed)


def test_a_missing_threshold_fails_closed_rather_than_defaulting() -> None:
    with pytest.raises(gl.GateLibraryError, match="threshold"):
        gl.evaluate_parent_gradient(gradient_max=1e-3, gradient_rms=1e-4, thresholds=None)


def test_a_non_finite_measurement_fails_closed() -> None:
    result = gl.evaluate_endpoint_penalty(signed_penalty_kcal=float("inf"), thresholds=ABSOLUTE)
    assert result.passed is False
    assert result.reason_code == "NON_FINITE_MEASUREMENT"


def test_reason_codes_cover_the_contract_minimum() -> None:
    """model-generation-contract.md:168-172."""
    for code in (
        "FINAL_TEST_ISOLATION_FAILED",
        "BASELINE_INELIGIBLE",
        "PARENT_GRADIENT_FAILED",
        "GEOMETRY_GATE_FAILED",
        "ENDPOINT_PENALTY_FAILED",
        "SIGNED_LABEL_ERROR_FAILED",
    ):
        assert code in gl.REASON_CODES
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.14 -m pytest tests/test_phase9b_gate_library.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the gate library**

Every `evaluate_*` function returns `GateResult` objects, never raises on a failed gate (a failed gate is data, not an exception), and raises `GateLibraryError` only when a *threshold* is absent — the fail-closed distinction required by `aimnet2-handoff-promotion.md:139-141`. Non-finite measurements produce `passed=False, reason_code="NON_FINITE_MEASUREMENT"`. `evaluate_relative_to_baseline` returns one `GateResult` per candidate key plus one aggregate, and marks the aggregate failed if any per-candidate value regresses, implementing CONFIRM-5 clause (c).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.14 -m pytest tests/test_phase9b_gate_library.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add src/nhc_deprot_ranker/quantum/phase9b_gate_library.py tests/test_phase9b_gate_library.py
git commit -m "feat: add shared AIMNet2 promotion gate library with signed measurements"
```

### Task 3: Candidate-level aggregation (unblocks the aggregation half of Blockers 1 and 3)

**Files:**
- Create: `src/nhc_deprot_ranker/quantum/phase9b_candidate_aggregation.py`
- Modify: `scripts/phase9b_aimnet2_training_dataset.py` (manifest weight audit)
- Test: `tests/test_phase9b_candidate_aggregation.py`
- Test: `tests/test_phase9b_aimnet2_training_dataset.py` (extend)

**Interfaces:**
- Consumes: nothing.
- Produces: `aggregate_by_candidate(frames: Sequence[Mapping[str, object]], *, value_key: str) -> dict[str, float]`; `aggregate_by_candidate_endpoint(frames, *, value_key) -> dict[tuple[str, str], float]`; `weight_audit(frames) -> dict[str, object]` returning per-candidate and per-endpoint effective-weight sums.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_phase9b_candidate_aggregation.py
from __future__ import annotations

import pytest

from nhc_deprot_ranker.quantum import phase9b_candidate_aggregation as agg

FRAMES = [
    {"candidate": "AAA", "endpoint": "cation", "err": 1.0},
    {"candidate": "AAA", "endpoint": "cation", "err": 3.0},
    {"candidate": "AAA", "endpoint": "neutral", "err": 2.0},
    {"candidate": "BBB", "endpoint": "cation", "err": 10.0},
    {"candidate": "BBB", "endpoint": "neutral", "err": 20.0},
]


def test_a_long_trajectory_cannot_dominate_a_short_one() -> None:
    """reference-data-contract.md:90 — no dominance by frame count."""
    result = agg.aggregate_by_candidate(FRAMES, value_key="err")
    assert result["AAA"] == pytest.approx(2.0)   # (mean(1,3)=2 and 2) -> 2.0
    assert result["BBB"] == pytest.approx(15.0)


def test_cation_and_neutral_get_equal_weight_within_a_candidate() -> None:
    """reference-data-contract.md:86-87."""
    audit = agg.weight_audit(FRAMES)
    assert audit["by_candidate"]["AAA"] == pytest.approx(1.0)
    assert audit["by_candidate"]["BBB"] == pytest.approx(1.0)
    assert audit["by_candidate_endpoint"][("AAA", "cation")] == pytest.approx(0.5)
    assert audit["by_candidate_endpoint"][("AAA", "neutral")] == pytest.approx(0.5)


def test_signs_survive_aggregation() -> None:
    frames = [
        {"candidate": "AAA", "endpoint": "cation", "err": -1.0},
        {"candidate": "AAA", "endpoint": "neutral", "err": 1.0},
    ]
    assert agg.aggregate_by_candidate(frames, value_key="err") == {"AAA": pytest.approx(0.0)}


def test_a_frame_missing_candidate_identity_fails_closed() -> None:
    with pytest.raises(agg.AggregationError, match="candidate"):
        agg.aggregate_by_candidate([{"endpoint": "cation", "err": 1.0}], value_key="err")


def test_an_unknown_endpoint_fails_closed() -> None:
    with pytest.raises(agg.AggregationError, match="endpoint"):
        agg.weight_audit([{"candidate": "AAA", "endpoint": "radical", "err": 1.0}])


def test_a_candidate_missing_an_endpoint_fails_closed() -> None:
    with pytest.raises(agg.AggregationError, match="endpoint"):
        agg.weight_audit([{"candidate": "AAA", "endpoint": "cation", "err": 1.0}])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.14 -m pytest tests/test_phase9b_candidate_aggregation.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement aggregation and the weight audit**

`aggregate_by_candidate` computes the per-endpoint mean first, then the mean over the two endpoints, so neither a long trajectory nor an unbalanced endpoint can dominate. `weight_audit` returns per-frame weights summing to `0.5` per endpoint and `1.0` per candidate, satisfying `reference-data-contract.md:86-89`. Both raise `AggregationError` when `candidate` is missing, when `endpoint` is outside `{"cation", "neutral"}`, or when a candidate does not carry both endpoints.

- [ ] **Step 4: Add the weight audit to the dataset manifest**

In `scripts/phase9b_aimnet2_training_dataset.py`, add `"candidate_endpoint_weight_audit": weight_audit(...)` to the `manifest` dict built at `:508`, and add `"candidate"` and `"endpoint"` to a new `"audit_keys"` entry so the evaluator can load them without adding them to the training `x`/`y` lists. Do not change `training_keys` — feeding provenance to the loss is forbidden by `reference-data-contract.md:75`.

- [ ] **Step 5: Extend the dataset test**

```python
# tests/test_phase9b_aimnet2_training_dataset.py — append
def test_manifest_carries_the_candidate_endpoint_weight_audit() -> None:
    """reference-data-contract.md:106 — candidate/endpoint weight audit is a required output."""
    manifest = _assemble_fixture_manifest()  # existing fixture helper
    audit = manifest["candidate_endpoint_weight_audit"]
    assert set(audit) == {"by_candidate", "by_candidate_endpoint"}
    for total in audit["by_candidate"].values():
        assert total == pytest.approx(1.0)


def test_provenance_keys_are_auditable_but_never_trained_on() -> None:
    manifest = _assemble_fixture_manifest()
    assert manifest["training_keys"]["x"] == ["coord", "numbers", "charge"]
    assert manifest["training_keys"]["y"] == ["energy", "forces"]
    assert manifest["audit_keys"] == ["candidate", "endpoint"]
```

- [ ] **Step 6: Run both test files**

Run: `python3.14 -m pytest tests/test_phase9b_candidate_aggregation.py tests/test_phase9b_aimnet2_training_dataset.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/nhc_deprot_ranker/quantum/phase9b_candidate_aggregation.py \
        scripts/phase9b_aimnet2_training_dataset.py \
        tests/test_phase9b_candidate_aggregation.py \
        tests/test_phase9b_aimnet2_training_dataset.py
git commit -m "feat: aggregate AIMNet2 validation metrics by candidate with a weight audit"
```

### Task 4: Freeze the gate artifact (Blockers 3, 4, 5)

**Blocked on:** user ratification of CONFIRM-1 … CONFIRM-6. Do not start this task before the answers exist; writing provisional numbers into a frozen artifact is exactly the failure `aimnet2-handoff-promotion.md:139-141` describes.

**Files:**
- Create: `docs/PHASE9B_AIMNET2_GATE_LIBRARY_V001.json`
- Test: `tests/test_phase9b_gate_library.py` (extend)

**Interfaces:**
- Consumes: `AbsoluteThresholds` and `REASON_CODES` from Task 2.
- Produces: a JSON artifact whose SHA256 is bound by Task 7's V003 config. Top-level keys: `schema`, `science_pilot_only`, `production_accepted`, `absolute_arm`, `relative_arm`, `final_test_arm`, `candidate_grids`, `selection_rules`, `reason_codes`, `efficiency_part_of_promotion_authority`, `maximum_reachable_terminal`, `ratification`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_phase9b_gate_library.py — append
import json
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parents[1] / "docs/PHASE9B_AIMNET2_GATE_LIBRARY_V001.json"


def test_gate_artifact_is_loadable_into_the_absolute_thresholds_dataclass() -> None:
    payload = json.loads(ARTIFACT.read_text())
    thresholds = gl.AbsoluteThresholds(**payload["absolute_arm"])
    assert thresholds.label_error_kcal > 0.0
    assert thresholds.systematic_bias_kcal < thresholds.label_error_kcal


def test_gate_artifact_declares_efficiency_out_of_promotion_authority() -> None:
    """Orchestration forbids speed_benchmark, so efficiency cannot gate promotion."""
    payload = json.loads(ARTIFACT.read_text())
    assert payload["efficiency_part_of_promotion_authority"] is False


def test_gate_artifact_caps_the_reachable_terminal_for_a_two_candidate_cohort() -> None:
    """workflow-contract.md:43 — a 5/2/2 cohort cannot establish general eligibility."""
    payload = json.loads(ARTIFACT.read_text())
    assert payload["maximum_reachable_terminal"] == "FINAL_TEST_ACCEPTED"
    assert payload["single_point_only_eligible"] is False


def test_every_contract_reason_code_appears_in_the_artifact() -> None:
    payload = json.loads(ARTIFACT.read_text())
    assert set(gl.REASON_CODES).issubset(set(payload["reason_codes"]))


def test_no_threshold_is_null_or_placeholder() -> None:
    payload = json.loads(ARTIFACT.read_text())
    for arm in ("absolute_arm", "relative_arm", "final_test_arm"):
        for key, value in payload[arm].items():
            assert value is not None, key
            assert value != "TBD", key


def test_every_threshold_records_its_ratification() -> None:
    payload = json.loads(ARTIFACT.read_text())
    for entry in payload["ratification"]:
        assert entry["confirmed_by_user"] is True
        assert entry["evidence_source"]
        assert entry["chosen_after_seeing_results"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3.14 -m pytest tests/test_phase9b_gate_library.py -k artifact -v`
Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Write the artifact using the ratified numbers**

Transcribe the confirmed CONFIRM-1 … CONFIRM-6 values verbatim. `relative_arm` carries the CONFIRM-5 margin and the no-regression clause. `final_test_arm` carries the CONFIRM-6 shape. `candidate_grids` carries the CONFIRM-2 grids. `ratification` carries one entry per threshold, each naming its evidence source file and line range and asserting `chosen_after_seeing_results: false`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3.14 -m pytest tests/test_phase9b_gate_library.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/PHASE9B_AIMNET2_GATE_LIBRARY_V001.json tests/test_phase9b_gate_library.py
git commit -m "docs: freeze AIMNet2 validation, baseline-eligibility and final-test gate artifact"
```

### Task 5: Freeze the stopping/handoff/promotion artifact (Blocker 6)

**Blocked on:** user ratification of CONFIRM-7 (and CONFIRM-2, whose grids it references).

**Files:**
- Create: `docs/PHASE9B_AIMNET2_STOPPING_CONTRACT_V001.json`
- Test: `tests/test_phase9b_stopping_contract.py` (extend)

**Interfaces:**
- Consumes: `StoppingSettings` field names from Task 1; `candidate_grids` from Task 4.
- Produces: a JSON artifact bound by SHA256 in Task 7. Top-level keys: `schema`, `bound_fields`, `stopping_states`, `stopping_predicates`, `handoff_proof`, `promotion_gates`, `calibration_procedure`, `ratification`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_phase9b_stopping_contract.py — append
import json
from pathlib import Path

ARTIFACT = (
    Path(__file__).resolve().parents[1] / "docs/PHASE9B_AIMNET2_STOPPING_CONTRACT_V001.json"
)


def test_artifact_binds_every_field_group_the_contract_lists() -> None:
    """aimnet2-handoff-promotion.md:22-36."""
    payload = json.loads(ARTIFACT.read_text())
    for field in (
        "model_generation_id",
        "bundle_sha256",
        "endpoint_charge_multiplicity_atom_map_initial_xyz_sha256",
        "optimizer_settings",
        "maximum_steps",
        "wall_limit_seconds",
        "restart_policy",
        "device",
        "dtype",
        "deterministic_settings",
        "external_coulomb_definition",
        "two_body_d3bj_definition",
        "force_stopping_metric",
        "energy_change_rule",
        "displacement_bounds",
        "optimizer_health_rules",
        "structural_gates",
        "applicability_gates",
        "failure_gates",
    ):
        assert field in payload["bound_fields"], field


def test_artifact_lists_the_ten_promotion_gates_in_contract_order() -> None:
    """aimnet2-handoff-promotion.md:126-137."""
    payload = json.loads(ARTIFACT.read_text())
    assert [gate["index"] for gate in payload["promotion_gates"]] == list(range(1, 11))
    assert payload["promotion_gates"][8]["name"] == "one_time_final_test_acceptance"


def test_artifact_forbids_inheriting_base_model_numbers() -> None:
    """aimnet2-handoff-promotion.md:38-41."""
    payload = json.loads(ARTIFACT.read_text())
    procedure = payload["calibration_procedure"]
    assert procedure["inherits_base_model_values"] is False
    assert procedure["calibration_data_scope"] == "development_validation_only"
    assert procedure["final_test_consulted"] is False


def test_calibration_selection_rule_is_deterministic_and_monotone() -> None:
    payload = json.loads(ARTIFACT.read_text())
    procedure = payload["calibration_procedure"]
    assert procedure["selection"] == "tightest_passing_grid_tuple_lexicographic"
    assert procedure["on_no_qualifying_tuple"] == "PROMOTION_BLOCKED"
    assert procedure["sealed_before"] == [
        "validation_geometry_optimization",
        "final_test_payload_read",
    ]


def test_stopping_predicates_require_conjunction_on_one_accepted_step() -> None:
    """aimnet2-handoff-promotion.md:56-67."""
    payload = json.loads(ARTIFACT.read_text())
    assert payload["stopping_predicates"]["combination"] == "all_on_the_same_accepted_step"
    assert payload["stopping_predicates"]["force_gate_may_replace_energy_gate"] is False
    assert payload["stopping_predicates"]["energy_gate_may_replace_force_gate"] is False


def test_handoff_requires_exact_byte_equality() -> None:
    """aimnet2-handoff-promotion.md:88-92."""
    payload = json.loads(ARTIFACT.read_text())
    handoff = payload["handoff_proof"]
    assert handoff["rule"] == "aimnet2_final_xyz_sha256 == p01_input_xyz_sha256"
    for forbidden in ("recenter", "rotate", "round", "reorder", "repair", "minimize", "substitute"):
        assert handoff["forbidden_transforms"][forbidden] is False


def test_grid_keys_match_the_stopping_settings_dataclass_fields() -> None:
    payload = json.loads(ARTIFACT.read_text())
    fields = set(sc.StoppingSettings.__dataclass_fields__)
    assert set(payload["calibration_procedure"]["candidate_grids"]).issubset(fields)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3.14 -m pytest tests/test_phase9b_stopping_contract.py -k artifact -v`
Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Write the artifact**

Populate every `bound_fields` entry from the ratified answers. `promotion_gates` transcribes the ten gates from `aimnet2-handoff-promotion.md:126-137` in order, each with the gate-library function that evaluates it and its reason code. `calibration_procedure` encodes the CONFIRM-7 grids, the lexicographic tightest-passing selection, and the sealing points.

- [ ] **Step 4: Run the tests**

Run: `python3.14 -m pytest tests/test_phase9b_stopping_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/PHASE9B_AIMNET2_STOPPING_CONTRACT_V001.json tests/test_phase9b_stopping_contract.py
git commit -m "docs: freeze AIMNet2 stopping, handoff and promotion contract with calibration procedure"
```

### Task 6: Epoch-zero selection and the `VALIDATION_REJECTED` terminal (Blocker 1)

**Files:**
- Modify: `scripts/phase9b_aimnet2_finetune.py:583-701`
- Test: `tests/test_phase9b_aimnet2_finetune.py` (extend)

**Interfaces:**
- Consumes: `aggregate_by_candidate` from Task 3; `AbsoluteThresholds`, `evaluate_relative_to_baseline`, `REASON_CODES` from Task 2; the gate artifact from Task 4.
- Produces: `select_checkpoint(candidates: Sequence[Checkpoint], *, thresholds, relative_margin) -> Selection`; `Checkpoint` (frozen dataclass: `epoch: int`, `state: dict[str, object] | None`, `metrics: Mapping[str, float]`); `Selection` (frozen dataclass: `epoch: int`, `outcome: str` in `{"VALIDATION_SELECTED","VALIDATION_REJECTED"}`, `rejection_reason_code: str | None`, `gate_results: tuple`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_phase9b_aimnet2_finetune.py — append
def test_epoch_zero_is_a_selection_candidate_numbered_0000() -> None:
    """model-generation-contract.md:26-31 — keep epoch 0 eligible."""
    selection = finetune.select_checkpoint(
        [
            finetune.Checkpoint(epoch=0, state=None, metrics={"AAA": 1.0, "BBB": 1.0}),
            finetune.Checkpoint(epoch=1, state={"w": 1}, metrics={"AAA": 2.0, "BBB": 2.0}),
        ],
        thresholds=_ABSOLUTE,
        relative_margin=0.10,
    )
    assert selection.epoch == 0
    assert selection.outcome == "VALIDATION_REJECTED"


def test_a_checkpoint_that_only_beats_other_epochs_is_not_selected() -> None:
    """The old code compared against math.inf, so epoch 1 always won."""
    selection = finetune.select_checkpoint(
        [
            finetune.Checkpoint(epoch=0, state=None, metrics={"AAA": 1.00, "BBB": 1.00}),
            finetune.Checkpoint(epoch=1, state={"w": 1}, metrics={"AAA": 0.99, "BBB": 0.99}),
            finetune.Checkpoint(epoch=2, state={"w": 2}, metrics={"AAA": 0.98, "BBB": 0.98}),
        ],
        thresholds=_ABSOLUTE,
        relative_margin=0.10,
    )
    assert selection.outcome == "VALIDATION_REJECTED"
    assert selection.epoch == 0


def test_a_checkpoint_clearing_the_margin_on_every_candidate_is_selected() -> None:
    selection = finetune.select_checkpoint(
        [
            finetune.Checkpoint(epoch=0, state=None, metrics={"AAA": 1.00, "BBB": 1.00}),
            finetune.Checkpoint(epoch=1, state={"w": 1}, metrics={"AAA": 0.85, "BBB": 0.80}),
        ],
        thresholds=_ABSOLUTE,
        relative_margin=0.10,
    )
    assert selection.outcome == "VALIDATION_SELECTED"
    assert selection.epoch == 1


def test_one_regressing_candidate_blocks_selection_even_with_a_good_mean() -> None:
    """CONFIRM-5 clause (c); aimnet2-handoff-promotion.md:141."""
    selection = finetune.select_checkpoint(
        [
            finetune.Checkpoint(epoch=0, state=None, metrics={"AAA": 1.00, "BBB": 1.00}),
            finetune.Checkpoint(epoch=1, state={"w": 1}, metrics={"AAA": 0.50, "BBB": 1.10}),
        ],
        thresholds=_ABSOLUTE,
        relative_margin=0.10,
    )
    assert selection.outcome == "VALIDATION_REJECTED"


def test_an_ineligible_baseline_records_BASELINE_INELIGIBLE() -> None:
    """model-generation-contract.md:36-42."""
    selection = finetune.select_checkpoint(
        [
            finetune.Checkpoint(epoch=0, state=None, metrics={"AAA": 99.0, "BBB": 99.0}),
            finetune.Checkpoint(epoch=1, state={"w": 1}, metrics={"AAA": 98.0, "BBB": 98.0}),
        ],
        thresholds=_ABSOLUTE,
        relative_margin=0.10,
    )
    assert selection.outcome == "VALIDATION_REJECTED"
    assert selection.rejection_reason_code == "BASELINE_INELIGIBLE"


def test_validation_rejected_never_produces_a_frozen_bundle() -> None:
    source = SCRIPT.read_text()
    assert '"final_outcome": "MODEL_FROZEN"' not in source
    assert "VALIDATION_REJECTED" in source
    assert "final-tuning produced no selectable validation checkpoint" not in source


def test_validation_rejected_does_not_consume_final_test() -> None:
    """model-generation-contract.md:34-35."""
    source = SCRIPT.read_text()
    assert '"final_test_consumed": False' in source
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.14 -m pytest tests/test_phase9b_aimnet2_finetune.py -v`
Expected: FAIL with `AttributeError: module has no attribute 'select_checkpoint'`.

- [ ] **Step 3: Rewrite the selection path**

In `scripts/phase9b_aimnet2_finetune.py`:

- Add `Checkpoint`, `Selection`, and `select_checkpoint`, importing the gate library and aggregation modules.
- At `:583`, keep `baseline_validation` but also register it as `Checkpoint(epoch=0, state=None, metrics=<candidate-aggregated>)`.
- Replace `_evaluate` (`:352-379`) with a version that loads the `candidate` and `endpoint` audit columns and returns candidate-keyed metrics alongside the existing scalars, so both views are preserved (`reference-data-contract.md:93` keeps frame metrics as diagnostics).
- Replace `:586-588, 613-626` so every improving epoch is appended as a `Checkpoint` and no `math.inf` comparison decides selection.
- Delete the forced-selection raise at `:641-642`.
- After the loop, call `select_checkpoint`. On `VALIDATION_SELECTED`, run the existing export path (`:643-663`) and set `final_outcome: "MODEL_FROZEN"`. On `VALIDATION_REJECTED`, skip export entirely, set `final_outcome: "VALIDATION_REJECTED"`, carry `rejection_reason_code`, and keep `final_test_consumed: False`.
- Order the baseline-eligibility check first, so `BASELINE_INELIGIBLE` is reported when epoch 0 would be the fallback but fails an absolute gate, per `model-generation-contract.md:36-42`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.14 -m pytest tests/test_phase9b_aimnet2_finetune.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/phase9b_aimnet2_finetune.py tests/test_phase9b_aimnet2_finetune.py
git commit -m "feat: make epoch 0 selectable and add the VALIDATION_REJECTED terminal"
```

### Task 7: Clear the readiness block on generation V003

**Blocked on:** Tasks 4 and 5 (their SHA256s are bound here) and CONFIRM-0.

**Coordination:** if `docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json` already exists — produced by `docs/PHASE9B_COHORT_DEADLOCK_RESOLUTION_PLAN.md`, which creates it with `readiness.state = "BLOCKED_BEFORE_TRAINING"` and all six codes intact — this task **amends** that file's `readiness`, `gate_library` and `stopping_contract` blocks and changes nothing else. Do not create a second V003 and do not alter its `data`, `paths`, `supersedes_generation_id`, or split binding. If the file does not exist yet, create it from V002 as described below, using the same generation ID.

**Files:**
- Create or amend: `docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json`
- Modify: `scripts/phase9b_aimnet2_finetune.py:26-31, 105-144` (schema constant and artifact binding)
- Test: `tests/test_phase9b_aimnet2_finetune.py` (extend)

**Interfaces:**
- Consumes: the two frozen artifacts.
- Produces: a config whose `readiness.state` is `"REGISTERED"` with all seven readiness gates `true` and `blocking_reason_codes: []`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_phase9b_aimnet2_finetune.py — append
V003 = ROOT / "docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json"
GATES = ROOT / "docs/PHASE9B_AIMNET2_GATE_LIBRARY_V001.json"
STOPPING = ROOT / "docs/PHASE9B_AIMNET2_STOPPING_CONTRACT_V001.json"


def test_v002_stays_terminal_and_is_never_reopened() -> None:
    """model-generation-contract.md:57, 74-78 — BLOCKED_BEFORE_TRAINING is terminal."""
    config = json.loads(CONFIG.read_text())
    assert config["readiness"]["state"] == "BLOCKED_BEFORE_TRAINING"
    assert config["generation_id"] == "phase9b-aimnet2-nhc-p01-v002"


def test_v003_is_a_new_generation_with_a_new_id_and_output_root() -> None:
    v003 = json.loads(V003.read_text())
    v002 = json.loads(CONFIG.read_text())
    assert v003["generation_id"] == "phase9b-aimnet2-nhc-p01-v003"
    assert v003["generation_id"] != v002["generation_id"]
    assert v003["paths"]["training_root"] != v002["paths"]["training_root"]


def test_v003_clears_every_blocking_reason_code() -> None:
    readiness = json.loads(V003.read_text())["readiness"]
    assert readiness["state"] == "REGISTERED"
    assert readiness["blocking_reason_codes"] == []
    for gate in (
        "final_test_isolation_implemented",
        "final_test_evaluator_scientifically_complete",
        "epoch_zero_selection_implemented",
        "validation_selection_gates_frozen",
        "baseline_eligibility_gates_frozen",
        "final_test_acceptance_gates_frozen",
        "stopping_handoff_promotion_gates_frozen",
    ):
        assert readiness[gate] is True, gate


def test_v003_binds_both_frozen_artifacts_by_sha256() -> None:
    v003 = json.loads(V003.read_text())
    assert v003["gate_library"]["sha256"] == finetune.sha256_bytes(GATES.read_bytes())
    assert v003["stopping_contract"]["sha256"] == finetune.sha256_bytes(STOPPING.read_bytes())


def test_v003_preserves_the_one_shot_and_isolation_boundary() -> None:
    v003 = json.loads(V003.read_text())
    assert v003["single_training_attempt"] is True
    assert v003["retry"] is False
    assert v003["science_pilot_only"] is True
    assert v003["production_accepted"] is False
    for forbidden in ("split_path", "final_test_directory", "final_test_candidates"):
        assert forbidden not in v003["data"]


def test_v003_records_the_unopened_cohort_proof() -> None:
    """model-generation-contract.md:106-109 — an independent access audit, not an assertion."""
    proof = json.loads(V003.read_text())["data"]["sealed_final_test_commitment"]
    assert proof["unopened_audit_receipt_sha256"]
    assert proof["audited_by"] != "training_process"


def test_v003_loads_through_the_frozen_config_loader() -> None:
    config, _ = finetune.load_frozen_config(V003, ROOT)
    assert config["readiness"]["state"] == "REGISTERED"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.14 -m pytest tests/test_phase9b_aimnet2_finetune.py -k v003 -v`
Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Write or amend V003, and extend the loader**

*If the cohort plan's V003 already exists:* change only `readiness` (state `REGISTERED`, all seven gates `true`, `blocking_reason_codes: []`), add the `gate_library` and `stopping_contract` blocks with path plus SHA256, and add `unopened_audit_receipt_sha256` and `audited_by` to `data.sealed_final_test_commitment`. Leave `generation_id`, `supersedes_generation_id`, `data`, `paths`, `base_bundle`, `training_model`, `training`, `environment` and `resource_preflight` byte-identical.

*If it does not exist:* copy V002 verbatim except: `generation_id` becomes `phase9b-aimnet2-nhc-p01-v003`; `schema` becomes `phase9b-aimnet2-model-generation-config-v003`; `paths.training_root` gets a `_v003` suffix; `paths.final_bundle_name` gets a `v003` suffix; `readiness` is fully cleared; `gate_library`, `stopping_contract` and the unopened-cohort proof are added as above.

In both cases: in `phase9b_aimnet2_finetune.py`, bump `CONFIG_SCHEMA` (`:26`) and add verification of both artifact SHA256s inside `load_frozen_config` (`:105-144`), following the existing `training_model` pattern at `:141-143`.

- [ ] **Step 4: Run the full suite**

Run: `python3.14 -m pytest tests/test_phase9b_aimnet2_finetune.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json \
        scripts/phase9b_aimnet2_finetune.py tests/test_phase9b_aimnet2_finetune.py
git commit -m "feat: register AIMNet2 generation v003 with all readiness gates cleared"
```

### Task 8: The intended-use validation route

**Files:**
- Create: `scripts/phase9b_aimnet2_validation_route.py`
- Test: `tests/test_phase9b_validation_route.py`

**Interfaces:**
- Consumes: `classify`/`StoppingSettings` from Task 1; every `evaluate_*` from Task 2; both frozen artifacts.
- Produces: `run_route(*, bundle_path, candidate, endpoint, initial_xyz_path, settings, thresholds, p01_runner) -> RouteResult`; `RouteResult` (frozen dataclass: `candidate: str`, `endpoint: str`, `stopping: StoppingVerdict`, `handoff_sha256_equal: bool`, `p01_energy_hartree: float`, `p01_gradient_max: float`, `p01_gradient_rms: float`, `gate_results: tuple[GateResult, ...]`, `route_state: str`); `P01Runner` Protocol with `single_point(xyz_bytes: bytes, *, charge: int, multiplicity: int) -> Mapping[str, float]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_phase9b_validation_route.py
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/phase9b_aimnet2_validation_route.py"


def _load():
    spec = importlib.util.spec_from_file_location("phase9b_validation_route_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


route = _load()


class _FakeP01:
    """Never real chemistry; the route must be provable without PySCF."""

    def __init__(self, *, gradient_max: float = 6.9e-3) -> None:
        self.seen: list[bytes] = []
        self.gradient_max = gradient_max

    def single_point(self, xyz_bytes: bytes, *, charge: int, multiplicity: int):
        self.seen.append(xyz_bytes)
        return {
            "energy_hartree": -1409.47,
            "gradient_max_hartree_per_bohr": self.gradient_max,
            "gradient_rms_hartree_per_bohr": 1.6e-3,
            "scf_converged": True,
        }


def test_only_converged_may_request_handoff() -> None:
    """aimnet2-handoff-promotion.md:51 — only AIMNET2_CONVERGED may request handoff."""
    runner = _FakeP01()
    result = route.run_route(**route.fixture_kwargs(stopping_state="AIMNET2_LIMIT_REACHED",
                                                    p01_runner=runner))
    assert result.route_state == "ROUTE_BLOCKED"
    assert runner.seen == []


def test_limit_reached_is_never_relabelled_converged() -> None:
    """aimnet2-handoff-promotion.md:54 — do not accept the last frame as converged."""
    result = route.run_route(**route.fixture_kwargs(stopping_state="AIMNET2_LIMIT_REACHED",
                                                    p01_runner=_FakeP01()))
    assert result.stopping.state == "AIMNET2_LIMIT_REACHED"


def test_handoff_transfers_the_exact_bytes_the_optimizer_produced() -> None:
    runner = _FakeP01()
    result = route.run_route(**route.fixture_kwargs(p01_runner=runner))
    assert result.handoff_sha256_equal is True
    assert len(runner.seen) == 1
    assert runner.seen[0] == result.final_xyz_bytes


def test_a_mutated_geometry_between_stages_fails_closed() -> None:
    runner = _FakeP01()
    with pytest.raises(route.RouteError, match="handoff"):
        route.run_route(**route.fixture_kwargs(p01_runner=runner, corrupt_handoff=True))


def test_a_failing_parent_gradient_produces_no_label() -> None:
    """aimnet2-handoff-promotion.md:145-146."""
    result = route.run_route(**route.fixture_kwargs(p01_runner=_FakeP01(gradient_max=9.9e-3)))
    assert result.route_state == "ROUTE_REJECTED"
    assert any(g.reason_code == "PARENT_GRADIENT_FAILED" for g in result.gate_results)
    assert result.label_kcal is None


def test_no_aimnet2_energy_reaches_the_label() -> None:
    """docs/AIMNET2_PROMOTION_GATES.md:38-42 — the most important structural gate."""
    source = SCRIPT.read_text()
    assert "aimnet2_energy" not in source.split("def compute_label")[1]


def test_the_route_never_imports_the_runner_v9_source() -> None:
    source = SCRIPT.read_text()
    assert "runner_v9" not in source
    assert "import pyscf" not in source
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.14 -m pytest tests/test_phase9b_validation_route.py -v`
Expected: FAIL with `FileNotFoundError` on the script path.

- [ ] **Step 3: Implement the route**

`run_route` takes the AIMNet2 trajectory through `classify`; on any state other than `AIMNET2_CONVERGED` it returns `route_state="ROUTE_BLOCKED"` without calling `p01_runner` at all. On `AIMNET2_CONVERGED` it renders the final XYZ, computes its SHA256, calls `p01_runner.single_point` with exactly those bytes, and re-verifies the SHA256 of what it passed against what it rendered — raising `RouteError` on any mismatch, per `aimnet2-handoff-promotion.md:88-92`. It then evaluates every gate family and returns `ROUTE_ACCEPTED` or `ROUTE_REJECTED`. `compute_label` takes only the two P01 electronic energies; the AIMNet2 energy is not in its scope at all. `P01Runner` is a Protocol so no test touches PySCF and no code path imports runner v9. `fixture_kwargs` is a test-support constructor exported by the script for exactly this purpose.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.14 -m pytest tests/test_phase9b_validation_route.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/phase9b_aimnet2_validation_route.py tests/test_phase9b_validation_route.py
git commit -m "feat: add the AIMNet2 intended-use validation route with exact-byte handoff proof"
```

### Task 9: Complete the final-test evaluator (Blocker 2)

**Files:**
- Modify: `scripts/phase9b_aimnet2_final_test.py:97-209`
- Test: `tests/test_phase9b_aimnet2_final_test.py` (extend)

**Interfaces:**
- Consumes: `run_route` from Task 8; the gate library from Task 2; the gate artifact's `final_test_arm` from Task 4.
- Produces: a result whose `final_outcome` is `"FINAL_TEST_ACCEPTED"` or `"FINAL_TEST_REJECTED"`, carrying `rejection_reason_code`, per-candidate signed measurements, and an append-only registry receipt.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_phase9b_aimnet2_final_test.py — append
def test_evaluator_runs_the_intended_use_route_not_a_dataset_loss() -> None:
    """aimnet2-handoff-promotion.md:100-123."""
    source = SCRIPT.read_text()
    assert "run_route" in source
    assert "evaluate_frozen_bundle" not in source


def test_evaluator_measures_every_required_quantity() -> None:
    source = SCRIPT.read_text()
    for field in (
        "p01_gradient_max_hartree_per_bohr",
        "p01_gradient_rms_hartree_per_bohr",
        "aligned_rmsd_angstrom",
        "signed_endpoint_penalty_kcal",
        "signed_label_error_kcal",
        "candidate_success_rate",
        "systematic_direction",
    ):
        assert field in source, field


def test_decision_is_adjudicated_not_a_literal() -> None:
    source = SCRIPT.read_text()
    assert "UNADJUDICATED_THRESHOLDS_NOT_FROZEN" not in source
    assert "FINAL_TEST_ACCEPTED" in source
    assert "FINAL_TEST_REJECTED" in source


def test_threshold_immutability_is_proved_not_asserted() -> None:
    source = SCRIPT.read_text()
    assert '"thresholds_changed": False' not in source
    assert "gate_artifact_sha256_before" in source
    assert "gate_artifact_sha256_after" in source


def test_evaluator_identity_binds_all_three_sources() -> None:
    """model-generation-contract.md:118-125."""
    source = SCRIPT.read_text()
    assert "dataset_helper_sha256" in source
    assert "route_source_sha256" in source
    assert "evaluator_sha256" in source


def test_consumption_is_recorded_in_an_append_only_registry() -> None:
    """model-generation-contract.md:145."""
    source = SCRIPT.read_text()
    assert "consumption_registry" in source
    assert "consumed/historical" in source


def test_an_isolation_failure_writes_an_invalidation_receipt() -> None:
    """model-generation-contract.md:134-139."""
    source = SCRIPT.read_text()
    assert "FINAL_TEST_ISOLATION_FAILED" in source
    assert "isolation_invalidation_receipt" in source
    assert '"evaluator_sha256": "not_applicable"' in source


def test_acceptance_does_not_authorize_single_point_only_promotion() -> None:
    """CONFIRM-6; workflow-contract.md:43."""
    source = SCRIPT.read_text()
    assert '"single_point_only_eligible": False' in source
    assert "PILOT_COHORT_INADEQUATE_FOR_GENERAL_ELIGIBILITY" in source


def test_evaluator_cannot_select_a_checkpoint_or_change_a_threshold() -> None:
    """model-generation-contract.md:142-144."""
    source = SCRIPT.read_text()
    assert "select_checkpoint" not in source
    assert '"checkpoint_selection_changed": False' in source
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.14 -m pytest tests/test_phase9b_aimnet2_final_test.py -v`
Expected: FAIL on every new test.

- [ ] **Step 3: Rewrite `consume_and_evaluate`**

Replace `:173-189` with per-candidate, per-endpoint `run_route` invocations for the frozen bundle and for the unchanged base on identical inputs. Extend the claim at `:130-141` with `dataset_helper_sha256` and `route_source_sha256`, and read the gate artifact SHA256 into `gate_artifact_sha256_before` before any payload read and into `gate_artifact_sha256_after` at the end, failing closed on inequality. Replace the `:192-207` result with candidate-aggregated signed measurements, the adjudicated `final_outcome`, the `rejection_reason_code`, `single_point_only_eligible: False`, and `promotion_blocked_reason: "PILOT_COHORT_INADEQUATE_FOR_GENERAL_ELIGIBILITY"`. Append a `consumption_registry` record outside `output_root` marking both candidates `consumed/historical`. Add the isolation-invalidation branch writing a receipt with `evaluator_sha256: "not_applicable"`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.14 -m pytest tests/test_phase9b_aimnet2_final_test.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/phase9b_aimnet2_final_test.py tests/test_phase9b_aimnet2_final_test.py
git commit -m "feat: complete the final-test evaluator with intended-use route and adjudication"
```

### Task 10: Full-suite regression and readiness proof

**Files:**
- Modify: `tests/test_phase9b_aimnet2_finetune_watch.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_phase9b_aimnet2_finetune_watch.py — append
def test_watch_proceeds_for_a_registered_generation_and_stops_for_a_blocked_one() -> None:
    v002 = json.loads((ROOT / "docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V002.json").read_text())
    v003 = json.loads((ROOT / "docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V003.json").read_text())
    assert v002["readiness"]["state"] == "BLOCKED_BEFORE_TRAINING"
    assert v003["readiness"]["state"] == "REGISTERED"
    assert v003["readiness"]["blocking_reason_codes"] == []
```

- [ ] **Step 2: Run the full suite**

Run: `python3.14 -m pytest tests/ -q`
Expected: PASS with no new failures. Compare against the pre-change baseline; the repository `.venv` interpreter is known to report spurious failures, so use CPython 3.14.

- [ ] **Step 3: Commit**

```bash
git add tests/test_phase9b_aimnet2_finetune_watch.py
git commit -m "test: prove v002 stays blocked while v003 registers cleanly"
```

---

## Part E — Critical path and parallelism

### Dependency graph

```text
CONFIRM-0 ─────────────────────────────────────────────► Task 7
CONFIRM-1..4 ──────────► Task 4 ──┐
CONFIRM-5 ─────────────► Task 4 ──┤
CONFIRM-6 ─────────────► Task 4 ──┤
CONFIRM-2,7 ───────────► Task 5 ──┤
                                  │
Task 1 (stopping machine) ────────┼──► Task 8 (route) ──► Task 9 (final test)
Task 2 (gate library) ────────────┤         ▲
Task 3 (aggregation) ─────────────┴──► Task 6 (epoch 0)  │
                                            │            │
                        Task 4, Task 5 ─────┴────────────┘
                                            │
                                        Task 7 (V003) ──► Task 10
```

### Critical path

The longest chain is:

```text
CONFIRM-2 + CONFIRM-7  →  Task 5 (stopping artifact)  →  Task 8 (route)  →  Task 9 (final-test evaluator)  →  Task 10
```

with `CONFIRM-1..6 → Task 4 → Task 6/Task 7` running just behind it.

**The real critical path starts with the user, not with code.** Tasks 1, 2, 3 and 8 can be written today with zero confirmations, because they take thresholds as parameters. Tasks 4, 5, 6, 7 and 9 cannot start until the CONFIRM answers exist. The blocker ordering by leverage is therefore:

1. **Blocker 6 (structural half)** — root of everything. It defines the stopping states, the predicate conjunction, and the handoff proof that the route in Task 8 executes and that Blockers 2, 3, 4 and 5 all measure against. Nothing downstream is well-defined without it.
2. **Blockers 3 + 4 jointly** — they are the relative and absolute arms of one gate library, and freezing them separately risks the contradiction that forces `PROMOTION_BLOCKED`.
3. **Blocker 5** — the same gate shapes applied once, plus the CONFIRM-6 scope cap.
4. **Blocker 2** — depends on 6 (the route) and 5 (the numbers). Largest single implementation task after Task 1.
5. **Blocker 1** — mechanically independent and can be built early, but its adjudication step waits on Blocker 3.
6. **Blocker 6 (numeric half)** — executes *after* training under the CONFIRM-7 procedure. Not on the pre-training critical path at all.

### What runs in parallel

| Parallel track | Tasks | Preconditions |
| --- | --- | --- |
| A — pure engines | Task 1, Task 2, Task 3 | None. Fully independent of every CONFIRM. Three agents can run these simultaneously. |
| B — artifact freezing | Task 4, Task 5 | CONFIRM answers. Task 4 and Task 5 are independent of each other once the answers exist. |
| C — trainer | Task 6 | Task 2, Task 3 (code); Task 4 (numbers). |
| D — route and evaluator | Task 8, then Task 9 | Task 8 needs Tasks 1 and 2. Task 9 needs Task 8 and Task 4. |

Track A is the whole of the work that can begin before the user answers anything, and it is roughly half the implementation volume. Track B is not implementation at all — it is transcription of ratified decisions. The honest schedule statement is therefore: **the six blockers are gated on seven user decisions, not on compute, and not primarily on engineering time.**

### What is explicitly *not* in this plan

- No training run, no GPU allocation, no server access, no SSH, no process start or stop.
- No change to runner v9, to the production 10-degree gate, to the 71 production labels, or to any public execution gate.
- No modification to `docs/PHASE9B_AIMNET2_MODEL_GENERATION_CONFIG_V002.json` — it is terminal and stays byte-identical.
- No modification to `PHASE_STATUS.md`.
- No cohort change. Shrinking, re-sealing, or re-splitting the candidate registry belongs to `docs/PHASE9B_COHORT_DEADLOCK_RESOLUTION_PLAN.md`; this plan only reads whatever V003 binds.
- No numeric threshold written into any artifact before its CONFIRM entry is ratified.
- No efficiency benchmark, per the orchestration `forbidden` list.

---

## Part F — Self-review against the spec

**Blocker coverage.** `EPOCH_ZERO_SELECTION_NOT_IMPLEMENTED` → Task 6 (with Tasks 2, 3 as prerequisites). `FINAL_TEST_EVALUATOR_INCOMPLETE` → Task 9 (with Task 8). `VALIDATION_SELECTION_GATES_NOT_FROZEN` → Task 4 `relative_arm` + Task 6 `select_checkpoint`. `BASELINE_ELIGIBILITY_GATES_NOT_FROZEN` → Task 4 `absolute_arm` + the `BASELINE_INELIGIBLE` branch in Task 6. `FINAL_TEST_ACCEPTANCE_GATES_NOT_FROZEN` → Task 4 `final_test_arm` + Task 9 adjudication. `STOPPING_HANDOFF_PROMOTION_GATES_NOT_FROZEN` → Task 1 (machine) + Task 5 (artifact) + Task 8 (handoff proof). The readiness flip itself → Task 7.

**Contract coverage.** `aimnet2-handoff-promotion.md` §1 → Tasks 1, 5; §2 → Task 8; §3 → Tasks 8, 9; §4 → Tasks 2, 4, 9; §5 → Task 9 terminal cap. `model-generation-contract.md` §1 → Task 7; §2 → Task 6; §3 → the V002-is-terminal finding and Task 7; §4 → Task 9; §5 → Task 9; §6 → Tasks 2, 9 reason codes. `reference-data-contract.md` §4 → Task 3. `workflow-contract.md` §5 → Part B in its entirety.

**Placeholder scan.** No task contains "TBD", "implement later", "add appropriate error handling", or "similar to Task N". Every test step carries runnable test code; every implementation step names the exact file and line range it edits.

**Type consistency.** `StoppingSettings` field names in Task 1 match the grid keys asserted in Task 5. `AbsoluteThresholds` field names in Task 2 match the `absolute_arm` keys asserted in Task 4. `GateResult.reason_code` values match `REASON_CODES` in Task 2 and the artifact assertion in Task 4. `Checkpoint`/`Selection` in Task 6 consume `AbsoluteThresholds` and `evaluate_relative_to_baseline` exactly as Task 2 defines them. `run_route` in Task 8 returns the `StoppingVerdict` produced by Task 1's `classify`.

**One known gap left open deliberately.** `build_production_optimizer` (`src/nhc_deprot_ranker/preparation/phase9b_preopt.py:327-334`) still raises, and `EXECUTION_AUTHORIZED` (`:29`) stays `False`. Constructing a real AIMNet2/ASE optimizer is a separate authorization and is out of scope here; Task 8 keeps the optimizer behind the existing `PreoptOptimizer` Protocol so every test in this plan runs against a mock with no model, no GPU and no network.
