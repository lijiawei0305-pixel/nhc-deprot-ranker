# One-Shot Progress Audit

## 1. Keep the snapshot bounded

Perform one read-only snapshot. Resolve the private SSH alias, run root, active
stage identity, and its current claim/terminal binding from ignored/private
configuration. Resolve lane plan, full protocol, model generation, and broader
manifests only for FULL_PROGRESS_AUDIT or an applicable anomaly. If connection
identity is unavailable or conflicting, return INCONCLUSIVE and one blocking
question.

Do not load the full workflow authority unless an observed condition requires it. Use [evidence-routing.md](evidence-routing.md) to escalate only the affected stage.

Allowed remote actions are observation only: process, affinity/topology, CPU/memory/pressure, disk/inode, GPU, stable file identity, hashes, logs, JSON, and manifest reads. Never redirect output remotely, create a file, signal a process, invoke a scheduler, or enter a chemistry/model executable.

Treat an explicit short or token-saving request as
`QUICK_ACTIVE_STAGE`. Inspect only process identity and CPU-time
delta, the active stage's durable progress marker, its terminal/claim identity,
deadline, memory headroom, and disk/inode runway. Inspect GPU only for a GPU
stage, training state only for a training question, and full queue/topology only
when the request or an anomaly requires them. Mark other observations
`not_applicable` rather than expanding the audit.

Use `FULL_PROGRESS_AUDIT` only when the user requests the whole workflow or
when a quick observation exposes an identity, topology, queue, final-test, or
resource anomaly that requires escalation. QUICK_ACTIVE_STAGE takes precedence
over the broader checklists below.

## 2. Observe process and resource progress

For FULL_PROGRESS_AUDIT or an applicable anomaly escalation, record for the
affected controller, worker, training, and evaluation processes:

- PID/PPID/SID, elapsed and CPU time, state, RSS, command digest, and affinity;
- assigned logical CPUs, unique physical cores, SMT-sibling collisions, NUMA nodes, and actual threads;
- load, available memory, memory pressure, swap activity, major faults, disk bytes/inodes, and projected runway when measurable;
- GPU identity projection, memory, utilization, active processes, and VASP occupancy without disturbing them.

Take a second sample 10–30 seconds later only when needed to measure CPU-time, step, cycle, frame, or byte-count deltas. Thread count is not utilization. CPU wall multiplied by threads is not measured CPU time. GPU allocation wall is not utilization.

## 3. Observe scientific progress

For each candidate endpoint in the selected quick or full scope, report the
last independently verified:

- route/stage identity and terminal state;
- geomeTRIC step, SCF cycle, energy/gradient/force trend, or AIMNet2 accepted step;
- convergence criteria and finite-value/structure checks;
- output/manifest closure;
- elapsed time, hard deadline remainder, and an ETA range only when enough comparable observations exist.

Do not call a long SCF stalled from log silence alone. Require process CPU-time and durable progress evidence. Separate environment/resource failure from numerical/scientific failure.

CPU-time growth proves active computation, not durable scientific advancement.
When CPU time grows but no durable step/cycle/frame change is observable,
report that distinction explicitly. Do not call it stalled unless a
repository-frozen stall criterion is met. If no such criterion exists, do not
invent a duration; use WARNING when a separate frozen risk gate is known to
fail, otherwise use INCONCLUSIVE for the durable-progress claim.

For AIMNet2, report Fmax and recent accepted-step energy changes, but do not infer AIMNET2_CLOSE_TO_PURE_PYSCF or SINGLE_POINT_ONLY_ELIGIBLE without their parent-level validation evidence.

## 4. Audit evidence closure

For any claimed frame or terminal, verify regular/no-follow identity where available, schema, candidate, endpoint, atom count/order, charge/multiplicity/spin, finite coordinates/energy/gradient/force, force equals negative gradient, hashes, exact file set, and manifest linkage.

Count frames as training-eligible only after the reference-data admission contract passes. Logs, mtime, a live PID, or a zero exit alone are not closure.

## 5. Audit queues and model state

For FULL_PROGRESS_AUDIT or an applicable queue/model anomaly, report:

- candidates and endpoints completed, active, never-claimed, failed, and closed;
- permanent split counts and final-test sealed/consumed status;
- immutable task DAG claims and whether idle workers may claim never-claimed work;
- dataset audit/freeze, training generation/checkpoint, validation, model freeze, and promotion state;
- current performance mode and whether its timing claims remain valid.

Idle capacity is not permission to add a candidate. A final-test file visible to training is CRITICAL even if it was not used in a loss calculation.

## 6. Use one status

- HEALTHY: durable scientific progress is advancing and no frozen gate is violated.
- WARNING: the process is active or durable work advances, but a frozen
  resource, deadline, disk-runway, imbalance, or evidence-closure risk needs
  attention.
- CRITICAL: identity, split, final-test, structure, hash, manifest, process, or scientific gate is explicitly violated.
- TERMINAL: all expected work has a structured terminal; describe its terminal result separately.
- INCONCLUSIVE: required observation or authority is unavailable or contradictory.

CRITICAL takes precedence over TERMINAL when a supposedly terminal route has invalid evidence. INCONCLUSIVE is for missing observation, not a known failure.

Apply disk, inode, memory, and deadline warnings only from thresholds and
sampling windows resolved through current authority. A raw percentage without
its frozen threshold does not determine status.

For an anomaly give the observation, severity, likely cause, and exactly one next read-only check or separately authorized action. Keep ordinary progress reports conversational; archive only when explicitly requested.
