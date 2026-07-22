# Phase 8A Hard Wall-Time and API Preflight Plan

## Decision and authorization boundary

The user approved the recommended Phase 8A after Phase 7. This phase may:

1. implement and mock-test a POSIX process-group supervisor that can enforce a real wall-clock timeout for the dedicated two-endpoint runner;
2. perform one read-only HPC preflight that imports and inspects the installed PySCF, geomeTRIC and dispersion APIs without constructing a molecule or invoking a compute kernel.

Phase 8A does not authorize DFT. The source-level execution gate and every private execution flag remain false. No cation or neutral endpoint may be optimized or evaluated, including the four Phase 7 smoke geometries. Enabling the gate or running a real worker is Phase 8B and requires a new explicit user decision.

Phase 7 was merged to `main` through PR #7 at merge commit `133f8e376d8fdc44b0638a975dfd59fc739a8d3d` before this branch was created.

## Frozen inputs

Phase 8A reads only:

```text
AGENT.md
docs/PHASE7_IMPLEMENTATION_PLAN.md
docs/PHASE7_REPORT.md
docs/PHASE7_TEST_REPORT.md
docs/GEOMETRY_SMOKE_V001_MANIFEST.json
src/nhc_deprot_ranker/quantum/two_endpoint.py
tests/test_phase7_two_endpoint.py
```

The ignored Phase 7 geometries may be used only for hash/path fixture identities. They must not be parsed by RDKit, converted to PySCF molecules or passed to the runner. Phase 1–7 data, models, results and remote artifacts are immutable.

## Problem statement

The Phase 7 runner has monotonic deadline checks immediately before and after backend calls. Those checks detect that a completed call exceeded its deadline, but they cannot interrupt a PySCF SCF or geomeTRIC optimization that never returns. Calling that mechanism a hard timeout would be incorrect.

The Phase 8A solution must put the future compute worker in a separate POSIX session/process group and keep deadline authority in a parent process that imports no compute dependency. On timeout, the parent must terminate and reap the entire process group. A child cannot extend, disable or override its wall time.

## Supervisor contract

The implementation will add a compute-agnostic supervisor with these invariants:

- launch with an argument vector and `shell=false`;
- create a new session/process group and prove the group ID belongs to the launched child before signaling it;
- keep the deadline in the parent using `time.monotonic()`;
- capture stdout and stderr concurrently while retaining at most a configured byte limit for each stream and continuing to drain excess output;
- on timeout, send `SIGTERM` to the dedicated group, wait a bounded grace interval, send `SIGKILL` if any group member remains, and always `wait()`/reap the direct child;
- after normal or abnormal parent exit, check for surviving group descendants; any survivor changes the outcome to failure and is terminated through the same bounded sequence;
- never signal PID 0, PID 1, the caller's group, an unverified/reused group, a negative user-supplied identifier or any process outside the newly created group;
- return one typed result describing exit code, timeout, signal escalation, durations, truncation and captured output without claiming application success;
- return exit code 124 for a hard timeout and nonzero for spawn, orphan, signal or child failures.

The supervisor is POSIX-only by design because both supported execution environments are macOS and Linux. Unsupported platforms fail closed.

## Runner and worker integration

The future real path will be parent-supervised only:

```text
run_two_endpoint
  -> source gate check (parent; false in Phase 8A)
  -> strict request/input/source validation (no PySCF import)
  -> create fixed attempt identity
  -> launch internal worker in a new process group
  -> enforce hard wall time and reap the group
  -> accept only a hash-complete same-attempt success state
```

The internal worker repeats the source gate and frozen-request authorization checks before lazy-importing PySCF. It has no public option to weaken the protocol. The parent never imports PySCF, geomeTRIC or dispersion modules.

Phase 8A may refactor the attempt temporary-directory prefix so a killed worker's partial state is unambiguously tied to the fixed attempt ID. A timeout must produce an atomic attempt-scoped supervisor failure envelope after the group is dead. It may preserve bounded diagnostics, but it must not publish `_SUCCESS`, combine endpoints across attempts, silently resume partial output or delete an unrelated path.

The existing exact success file set and strict resume contract remain authoritative. Tests may invoke private integration seams with harmless worker fixtures; the public gate stays false and rejects before spawning any worker.

## No-chemistry process tests

All local hard-timeout tests use the current Python interpreter and tiny standard-library fixtures. They must cover:

- immediate clean exit;
- explicit nonzero exit;
- child output on both streams;
- output beyond each retention limit without a pipe deadlock;
- direct child sleep beyond the deadline;
- child that ignores `SIGTERM` and therefore requires `SIGKILL`;
- child that creates a sleeping grandchild in the same group;
- direct parent exit while a descendant retains the group and pipe descriptors;
- spawn failure and malformed argument vectors;
- deadline/exit race at the timeout boundary;
- repeated runs proving no relevant PID or PGID survives;
- public runner rejection before process creation or lazy compute imports;
- timeout evidence that cannot be interpreted as endpoint success.

Tests must use explicit short deadlines and bounded grace periods. They may inspect only the PIDs they created. No broad `pkill`, process-name match, shell pipeline, remote process or chemistry dependency is permitted.

## Read-only HPC API preflight

The user most recently confirmed the Mac is on the WHUT campus network. Connection coordinates remain in an ignored Phase 8A private configuration. The preflight uses the passwordless direct route and one molecular environment only.

The remote script will:

1. resolve and verify the project root and molecular environment script;
2. set `PYTHONPATH` and `PYTHONDONTWRITEBYTECODE=1`, temporarily disable nounset only while sourcing `molenv.sh`, and invoke `python -B`;
3. import PySCF, geomeTRIC, the PySCF geometric solver, SCF dispersion helpers and the D3 adapter;
4. record Python and distribution versions;
5. use `inspect.signature`, class attributes and module constants to verify:
   - `geometric_solver.kernel` exposes `assert_convergence` and `maxsteps` and is the convergence-returning API;
   - `geometric_solver.optimize` exists but is not the runner's accepted convergence API;
   - D3(BJ) appears in the installed supported dispersion versions;
   - `SCF.do_disp`, `SCF.newton`, `dft.RKS` and the D3 adapter entry point exist;
6. verify the Phase 7 relevant source/result hashes and file counts are unchanged before and after the inspection;
7. emit one strict JSON object to stdout and exit.

The script must not instantiate `Mole`, RKS or UKS; call `Mole.build`, SCF/DFT/gradient/dispersion kernels, `geometric_solver.kernel`, `optimize`, `newton` on an object, or any Hessian/frequency function. It writes no remote file, uploads no code, submits no process and installs nothing.

Tracked evidence records only logical API names, versions, booleans, signatures and hashes. It must not contain the SSH alias, host, user, project path, IP, identity path or credentials.

## Planned artifacts

Tracked implementation:

```text
src/nhc_deprot_ranker/quantum/process_supervisor.py
src/nhc_deprot_ranker/quantum/worker.py
src/nhc_deprot_ranker/quantum/two_endpoint.py
src/nhc_deprot_ranker/preparation/phase8a_preflight.py
scripts/phase8a_api_preflight.py
scripts/run_phase8a_api_preflight.py
tests/fixtures/process_tree_fixture.py
tests/test_phase8a_process_supervisor.py
tests/test_phase8a_worker_protocol.py
tests/test_phase8a_api_preflight_script.py
tests/test_phase8a_preflight_config.py
configs/phase8a.example.yaml
```

Tracked evidence and reports:

```text
docs/PHASE8A_API_PREFLIGHT_V001.json
docs/PHASE8A_IMPLEMENTATION_PLAN.md
docs/PHASE8A_REPORT.md
docs/PHASE8A_TEST_REPORT.md
```

Private coordinates live only in ignored `configs/phase8a.local.yaml`. No remote result directory is created in Phase 8A.

## Test and execution order

1. Update `AGENT.md`, this plan and `PHASE_STATUS.md` before code or server access.
2. Audit the current runner state machine, POSIX process semantics and installed-server API expectations.
3. Add strict Phase 8A configuration with server-write and quantum-execution authorization fixed false.
4. Implement the generic process supervisor and harmless process-tree fixtures.
5. Integrate a doubly guarded internal worker path without enabling it.
6. Run targeted and full local tests, Ruff, format, strict mypy, pre-commit, package build and private-coordinate scans.
7. Reconfirm the ignored private route, then run the single read-only HPC API inspection.
8. Validate the returned strict JSON locally without importing compute dependencies; write checked-in evidence and reports.
9. Perform independent code/process and evidence audits, rerun all gates, publish through a PR and merge only after review.

## Acceptance and mandatory stop

Phase 8A passes only if process-tree timeout tests prove TERM/grace/KILL/reap behavior, the public execution gate remains closed, the read-only server API contract matches the runner's assumptions, all Phase 7 artifacts remain unchanged, and no chemistry calculation or server write occurred.

After Phase 8A, the project stops again. API compatibility and timeout readiness do not authorize a DFT smoke. Phase 8B requires a separate plan and explicit user permission defining the number of candidates/endpoints, resource limits, run directory and acceptance criteria.
