---
name: plan-nhc-aimnet2-workflow
description: Plan and audit the repository-specific nhc-deprot-ranker workflow for NHC cohort selection, parent-level PySCF/geomeTRIC reference generation, AIMNet2 fine-tuning, AIMNet2-as-preconditioner validation, stopping-rule calibration, optional single-point-only promotion, progress inspection, and CPU/GPU/memory/disk performance planning. Use for complete workflow plans, stage readiness, split or leakage audits, model-generation reviews, one-shot read-only progress checks, runtime/ETA/capacity/bottleneck questions, benchmark design, and requests to automate or execute work that first require a frozen gated plan. Never use it by itself to execute chemistry, train models, control processes, or mutate a server.
---

# Plan NHC AIMNet2 Workflow

## Route before loading evidence

1. Infer the mode from an explicit request:
   - workflow plan;
   - stage audit;
   - one-shot progress snapshot;
   - performance plan or performance-readiness audit.
2. Read [references/evidence-routing.md](references/evidence-routing.md), then load only the authority and reference sections required for that mode and stage.
3. Resolve authoritative artifacts through config, manifest, and SHA256 bindings. Never choose “latest” by mtime or filename sorting.
4. Separate facts into:
   - discoverable facts: inspect them before asking;
   - evidence-backed recommendations: explain the trade-off and recommend one;
   - user-owned choices: ask one focused question only when a non-discoverable choice blocks further work.
5. Do not ask the user to choose a mode already made explicit. Do not require a second approval when the user already requested a named artifact and collision/version checks pass.

Use Chinese for explanations and questions. Preserve exact English schema names, status values, commands, methods, and units.

## Select the contract

- For an end-to-end plan or any scientific/model stage, read [references/workflow-contract.md](references/workflow-contract.md) and the references it routes to.
- For a live status request, read [references/progress-audit.md](references/progress-audit.md). Keep it lightweight unless an observed anomaly requires a deeper contract.
- For resource allocation, throughput, ETA, scaling, bottleneck, benchmark, CPU/GPU, memory, disk, or scheduler questions, read [references/server-performance-contract.md](references/server-performance-contract.md).
- For an archived artifact, read [references/report-schema.md](references/report-schema.md). A conversational snapshot does not require JSON.

Prefer the bundled read-only helpers when their input contracts apply:

- [scripts/audit_resource_plan.py](scripts/audit_resource_plan.py) checks scheduler/cgroup/affinity intersection, physical-core/SMT overlap, NUMA locality, and concurrent memory.
- [scripts/summarize_runtime_metrics.py](scripts/summarize_runtime_metrics.py) derives measured throughput and efficiency without filling missing values.
- [scripts/validate_workflow_report.py](scripts/validate_workflow_report.py) validates an archived JSON report before delivery.

## Preserve scientific meaning

- Use the repository-frozen deprotonation electronic-energy definition. Do not call it Gibbs free energy, pKa, solution acidity, or experimental enthalpy.
- Treat pure parent-level PySCF/geomeTRIC as a protocol-level reference, not experimental truth.
- Keep AIMNet2 energy out of the downstream label formula.
- Distinguish `AIMNET2_PRECONDITIONER_READY`, `AIMNET2_CLOSE_TO_PURE_PYSCF`,
  and `SINGLE_POINT_ONLY_ELIGIBLE`. `AIMNET2_PRECONDITIONER_READY` may be
  defined by the frozen AIMNet2 `GAU_LOOSE` profile plus chemical-identity
  gates when the mandatory next stage is a full parent-level geometry optimization. It
  never means parent-level convergence and never authorizes a parent-level
  single-point-only route.
- Resolve three baselines separately: compare parent gradient against the same
  frozen initial geometry, fine-tuned AIMNet2 against epoch 0/base AIMNet2, and
  assisted full-parent optimization cost against pure parent optimization from
  the same frozen initial bytes. Never collapse these into “epoch 0 or initial”.
- For the active preconditioner route, treat AIMNet2 `GAU_LOOSE` as all five
  geomeTRIC-style quantities on the AIMNet2 surface: energy change, gradient
  RMS, gradient maximum, displacement RMS, and displacement maximum. The first
  successful parent energy/analytic gradient from the continuing full
  optimization has no preceding parent step, so it is only
  `PARENT_GAU_LOOSE_GRADIENT_CHECK`, never complete parent `GAU_LOOSE`.
- Classify a valid first parent gradient as `HANDOFF_CALIBRATION_PASS` or
  `HANDOFF_CALIBRATION_MISS`; both continue the same full PySCF/geomeTRIC
  optimization to `FINAL_PARENT_GAU_CONVERGED` and a final single point.
  Invalid SCF, gradients, identity, geometry, charge/multiplicity, or topology
  are `FAILED_PARENT_HANDOFF` and stop.
- Treat missing production writers, thresholds, identities, manifests, or final-test isolation as blockers. Do not infer acceptance from source code, logs, mtime, or process-local state.
- Preserve signed energy and label differences and exact units.

## Optimize the correct server objective

- Scientific acceptance gates take precedence over utilization.
- In ISOLATED_BENCHMARK mode, preserve isolation and equal-resource comparability; concurrent background load invalidates strict wall-time claims.
- In THROUGHPUT_COLLECTION mode, optimize accepted reference throughput rather than visual CPU occupancy. Use physical-core, SMT-sibling, NUMA, memory, pressure, disk, and active-workload evidence.
- Never assume all 112 logical CPUs are faster than physical-core allocation. Require an aggregate calibration before enabling SMT siblings.
- Never kill, pause, or displace unrelated user work. Idle capacity is not authority to add an unregistered candidate.

## Enforce the planning boundary

This skill is read-only and design-only. It may inspect local files and, when private connection authority exists, take one bounded read-only SSH snapshot. It must not:

- start, stop, signal, resume, retry, restart, or schedule a process;
- run PySCF, geomeTRIC, AIMNet2 inference/training, xTB, GFN, DFTB, MMFF, or UFF;
- write to a server, alter an environment, or generate a live permit;
- delete, move, rename, clean, or overwrite unrelated user data;
- modify production runner, v9, guardian, campaign, Postflight, gates, or label tables;
- consume final-test data or promote a model;
- establish recurring monitoring under a one-shot request.

For an execution request, return the frozen plan, readiness gates, missing authority, and exact next permitted action. Actual execution requires separate authorization and an execution-capable workflow.

## Report traceably

Follow [references/report-schema.md](references/report-schema.md) when an artifact is requested. Bind claims to Git identity, worktree state, input/protocol/config/model/result hashes, and explicit assumptions. Use unavailable, not_run, and not_applicable accurately; never turn an unmeasured field into zero.

Public artifacts must redact SSH aliases, host/user/IP identities, private absolute paths, GPU UUIDs, credentials, and private process bindings. Keep Markdown and JSON semantically identical when both are requested.
