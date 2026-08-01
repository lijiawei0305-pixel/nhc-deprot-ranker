# Server Performance Contract

## Contents

1. Modes and authority
2. CPU topology and resource profiles
3. Immutable scheduling
4. Backpressure and host protection
5. GPU policy
6. Fair measurement and lower bounds
7. Required evidence

## 1. Modes and authority

Declare exactly one mode before assessing or proposing server performance:

- `ISOLATED_BENCHMARK`: calibrate resource scheduling on a frozen workload. Keep its
  evidence separate from scientific acceptance and production evidence. Require
  separate execution authorization; this planning skill must not run it.
- `THROUGHPUT_COLLECTION`: collect preregistered parent-level evidence with one
  already-frozen resource profile. Permit scheduling decisions only; never change a
  candidate, method, threshold, retry policy, model, or scientific output identity.

Transition from ISOLATED_BENCHMARK to THROUGHPUT_COLLECTION only through an
immutable profile-selection receipt. Bind compared workload, repetitions,
warm/cold policy, accepted milestones, raw metrics, selection threshold,
tie-break, uncertainty method and result, topology, software, chosen profile,
rejected profiles, receipt schema, and receipt SHA256. The collection run must
cite that receipt and may not recalibrate in place.

Derive the usable CPU universe as the intersection of:

```text
online CPUs
intersect scheduler allocation
intersect effective cgroup cpuset
intersect process affinity
```

Treat a missing scheduler allocation or exclusivity proof as a shared-host condition.
Never expand beyond the intersection, infer ownership from `nproc`, or require all 112
logical CPUs to be busy. Reserve capacity for the host and observed foreign work under
the frozen shared-host policy.

Bind every conclusion to timestamped scheduler variables, cgroup CPU and memory limits,
`Cpus_allowed_list`, `Mems_allowed_list`, topology, load, and configuration hashes. Stop
with `PLAN_BLOCKED`, `AUDIT_FAIL`, or `INCONCLUSIVE` when those authorities conflict.

## 2. CPU topology and resource profiles

Resolve every logical CPU to `(NUMA node, socket, physical core, SMT sibling set)` from
captured topology evidence. Audit physical-core overlap, not only logical-CPU overlap.

- Allocate one logical sibling per physical core by default.
- Keep simultaneous workers physically disjoint unless an isolated calibration has
  frozen SMT sharing as beneficial.
- Do not treat disjoint logical CPU lists as disjoint resources when they share cores.
- Keep each worker NUMA-local. Bind its CPU set, permitted memory nodes, and memory
  policy. Reject accidental cross-node bundles.
- Preserve a physical-core-only fallback.

Treat the existing result that 54-thread SMT was 5.28% slower than 27 physical threads
as evidence against blind SMT use, not as a universal multi-worker throughput result.
Enable SMT only after `ISOLATED_BENCHMARK` compares aggregate accepted-work throughput
on identical physical cores, inputs, software, and competing worker counts, and meets a
preregistered improvement threshold without numerical drift or worse memory pressure.

Calibrate a bounded set of profiles before `THROUGHPUT_COLLECTION`. Freeze one selected
profile containing at least:

```text
topology and host identity hashes
physical cores per worker and worker count
SMT policy and sibling ownership
NUMA CPU and memory policy
endpoint concurrency
per-worker and aggregate memory budgets
host memory, disk, and inode reserves
backpressure thresholds
benchmark workload and repetition identities
selection metric and tie-break
```

Use warm-up plus repeated measured trials. Vary one declared scheduling dimension at a
time where feasible. Select by accepted-work throughput subject to scientific equality,
tail latency, resource headroom, and fairness gates; never select by raw CPU occupancy.

Freeze the repetition count, uncertainty method, minimum practical throughput
improvement, and tie-break before calibration. If repository authority fails to
provide any one of them, the performance plan is blocked pending confirmation;
do not invent or choose them after viewing trial results.

## 3. Immutable scheduling

Represent collection as one immutable task DAG. Give every task a stable identity,
candidate, endpoint, stage, dependency set, input hashes, protocol hash, and resource
class. Keep the task registry immutable after launch.

Store claims, assignments, starts, results, and terminals as separate append-only,
exclusive-created evidence. Permit a worker to claim only a ready, never-claimed task.
Permit work stealing only from that never-claimed ready set.

Never reassign, reclaim, retry, or replace a claimed task. Treat worker loss or an
ambiguous claim as terminal under the frozen no-retry policy. Do not use mutable leases
to bypass this rule.

Schedule cation and neutral endpoints as independent tasks when the frozen profile
allows endpoint concurrency. Give concurrent endpoints physically disjoint, NUMA-local
resource bundles. Close the candidate barrier only after both endpoint optimizations,
final single points, endpoint manifests, route manifest, process cleanup, and all
scientific gates pass. Never admit, label, or train from one completed endpoint alone.

Treat a lane as an ephemeral resource bundle, not as ownership of a candidate list.
Allow bundle count and width to change only between claims and only as permitted by the
frozen profile and current backpressure state. Never resize or move an active task.

## 4. Backpressure and host protection

Before every new task claim, measure and record:

```text
MemAvailable and effective cgroup memory headroom
memory PSI and I/O PSI
swap use and swap-in/swap-out deltas
OOM or memory-event deltas when available
filesystem free bytes and free inodes
recent bytes per frame/candidate and projected completion footprint
```

Apply both absolute reserves and fractional headroom from the frozen profile. Count all
active workers, runtime overhead, dataset duplication, checkpoints, caches, and foreign
host usage. Treat PySCF `max_memory` as an application hint, not a hard process limit.

Pause new claims when any gate fails or disk runway cannot cover the admitted active
work plus reserve. Let active work continue under its existing deadline; do not kill,
resize, or retry it as a backpressure mechanism. Require recovery across the frozen
number of consecutive samples before admitting more work. Never invent a threshold
during collection.

Protect VASP and unrelated workloads. Never signal their processes, change their
affinity, claim their observed CPUs or GPUs, traverse or modify their private run data,
or delete, compress, move, or inspect `WAVECAR` or `CHGCAR` to obtain capacity. Treat
their resource occupancy as unavailable capacity.

## 5. GPU policy

Run parent-level PySCF on CPU. Do not infer GPU execution from an interpreter or
environment name. Use a GPU implementation for parent-level work only after separate
method-equivalence evidence and protocol authorization freeze its implementation,
precision, numerical tolerances, and result identity.

Use GPU for AIMNet2 work only within the frozen model and determinism policy. Before a
measured steady-state benchmark, run one preregistered warm batch with the same model,
species support, precision, and representative atom-count class. Synchronize CUDA,
record compilation/model-load/warm-up time separately, and begin measurement only after
the warm batch passes finite-output and identity gates. Apply the same cold-start or
warm-start rule to every compared profile.

Record GPU utilization over time, active fraction, peak and free memory, samples/s,
atoms/s, batch latency, host-to-device wait, and OOM/throttle events. Do not equate an
idle GPU with permission to alter the PySCF protocol, weaken exclusivity, or start an
unregistered task.

## 6. Fair measurement and lower bounds

Compare profiles only on identical task/input/protocol/software/hardware hashes and the
same terminal acceptance gates. Include failed and timed-out resource consumption in
denominators; count only accepted work in throughput numerators. Separate cold-start,
warm-up, steady-state, and end-to-end measurements.

Report at least:

- accepted candidates, endpoints, and frames per wall-hour and per physical-core-hour;
- total CPU seconds divided by unique allocated physical-core-seconds;
- makespan, endpoint wall time, queue wait, barrier wait, and tail-idle time;
- p50/p95 task latency when sample count supports them;
- SMT sibling occupancy and aggregate SMT throughput gain;
- peak aggregate RSS, minimum memory headroom, PSI, swap, major faults, and OOM events;
- bytes per accepted frame/candidate, write rate, free-space and inode runway;
- GPU metrics required above for AIMNet2.

Never use logical-CPU count as physical capacity. Never combine overlapping workers into
independent core-hours. Report unavailable metrics as `unavailable`, not zero.

Claim a speed ratio only when both profiles reach the same frozen milestone. If the
slower profile times out after observed monotonic wall time `T_observed` and the faster
profile reaches that milestone in `T_fast`, report only the directional lower bound
`speedup > T_observed / T_fast`; do not report a point estimate or extrapolated finish.
If milestones, workloads, warm state, or terminal evidence differ, report no speedup.
Do not derive a lower bound from log age, file mtime, process existence, or an unfinished
fraction whose equivalence was not preregistered.

## 7. Required evidence

Return the mode, usable-CPU intersection, topology hash, physical-core overlap matrix,
SMT and NUMA decisions, calibrated/frozen profile identity, immutable task/claim state,
backpressure samples, metric definitions, raw numerator/denominator values, confidence
limits where justified, and every unavailable measurement.

Separate observation from inference. State exactly which evidence supports a profile
selection and which claims remain unmeasured. Performance readiness never authorizes
benchmark execution, chemistry, training, retry, candidate replacement, production
acceptance, or production label insertion.

Use scripts/audit_resource_plan.py for a deterministic static topology/plan
check when its JSON input contract can be satisfied. Use
scripts/summarize_runtime_metrics.py only on measured receipts; its output does
not upgrade THROUGHPUT_COLLECTION timing into an isolated speed claim.

The static audit expects topology.cpus rows with cpu/socket/core/node/online,
optional scheduler_cpu_list, cgroup_cpu_list, and affinity_cpu_list, plus
memory_safe_mb. Its plan contains mode, smt_policy, require_numa_local, and
concurrent allocations with task_id, cpu_list, and max_memory_mb. A
calibrated_logical plan must also supply the frozen aggregate SMT calibration.
Its minimum_improvement_percent must exactly equal the preregistered value in
the benchmark configuration or profile-selection receipt.

CPU lists are JSON arrays of unique non-negative integers, never range strings.
For calibrated_logical, smt_calibration requires accepted=true,
aggregate_workload=true, improvement_percent, and
minimum_improvement_percent. An ISOLATED_BENCHMARK plan also requires:

~~~text
benchmark.routes_concurrent = false
benchmark.equal_resources = true
benchmark.background_load = isolated
benchmark.repetitions = positive integer
benchmark.uncertainty_method = non-empty string
benchmark.minimum_improvement_percent = non-negative number
benchmark.tie_break = non-empty string
~~~

A THROUGHPUT_COLLECTION plan requires profile_selection_receipt with non-empty
schema, selected_profile_id, workload_identity, warm_cold_policy, accepted
milestones, raw metrics, rejected profile IDs, repetitions, uncertainty method
and result, minimum improvement, and tie-break. Receipt, topology, and software
identities must be lowercase 64-character SHA256 values.

The helper returns only a static resource-plan audit. Its AUDIT_PASS does not
claim benchmark readiness, collection authority, scientific acceptance, or a
speedup; timing_claim remains not_evaluated_by_static_resource_audit.

The runtime summarizer expects one record per unique candidate/endpoint attempt
with measured wall seconds and allocated physical cores. Supply CPU, queue,
GPU, RSS, accepted-frame, observation-window, and tail-idle fields only when
directly measured; use unavailable rather than estimates.
