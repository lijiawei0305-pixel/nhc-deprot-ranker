# Phase 8A Report

## Outcome

Phase 8A passed on 2026-07-22. A compute-agnostic POSIX supervisor now enforces a parent-owned hard wall-time over one newly created session/process group, and the dedicated two-endpoint runner has a doubly guarded internal worker protocol. The source-level execution gate remains `false`, so neither the public runner nor the worker can reach PySCF execution in this phase.

The server API preflight passed using import and static inspection only. It confirmed the installed PySCF/geomeTRIC/D3(BJ) interfaces required by the runner and independently proved that the exact Phase 7 result tree and registered source files were unchanged before and after inspection. No molecule, mean-field object, SCF/DFT calculation, geometry optimization, dispersion evaluation or Hessian was created or called.

Machine-readable evidence is `docs/PHASE8A_API_PREFLIGHT_V001.json`, with SHA256 `ba1c74dc919424a439a25f84e6d8b4e2f5a68d8af092aa049484546d8b1787a3`.

## Authorization and documentation order

Phase 7 was merged through PR #7 at `133f8e376d8fdc44b0638a975dfd59fc739a8d3d` before branch `agent/phase8a-hard-timeout-api-preflight` was opened. Before Phase 8A code changes or server access, `AGENT.md`, `PHASE_STATUS.md` and `docs/PHASE8A_IMPLEMENTATION_PLAN.md` froze two authorized actions only:

1. local implementation and no-chemistry testing of a hard process-group wall-time;
2. one read-only class/function/version/signature inspection in the established molecular server environment.

Real DFT, molecule construction, server writes, uploads, scheduler submissions and execution-gate changes remained prohibited throughout.

## Hard wall-time implementation

`process_supervisor.py` accepts only an argv vector and launches with `shell=False`, `start_new_session=True`, closed stdin and independent stdout/stderr pipes. The parent uses a monotonic deadline and leaves the session leader unreaped while any group signal can still be sent, preventing PID/PGID reuse during cleanup.

The supervisor:

- validates that the new group ID equals the owned child PID and differs from PID 0, PID 1 and the caller's group;
- drains stdout and stderr concurrently, retains a bounded prefix and continues draining excess bytes;
- resolves the deadline/exit boundary with non-reaping `waitid(..., WNOWAIT)` observation;
- sends `SIGTERM`, waits a finite grace period, escalates to `SIGKILL`, verifies the group is empty and then reaps the direct child;
- detects a child leader that exits while same-group descendants survive, marks the run failed and cleans that group;
- returns typed clean, nonzero, timeout, spawn, supervision and orphan-descendant outcomes; timeout is exit 124 and every other failure is nonzero.

Completion observed only after the monotonic deadline is classified fail-closed as timeout, even if the child has already exited when the delayed parent resumes. Every result also exposes whether a process was started, whether the group was confirmed empty and whether the direct child was reaped. If group inspection itself fails, the supervisor sends `SIGKILL` to the already verified PGID without trusting that failed inspection and bounds the final wait.

The portable POSIX guarantee is intentionally limited to processes that remain in the newly created session/process group. A deliberately hostile descendant can escape with `setsid`/`setpgid`; terminating arbitrary escaped descendants would require a Linux cgroup or equivalent platform-specific containment. Phase 8A does not claim that stronger property.

## Parent/worker state protocol

The public `run_two_endpoint()` performs the source gate as its first action, before reading the request, importing the supervisor, spawning a process or creating output. The internal worker repeats the source gate before parsing argv or a request, checks the frozen request authorization, repeats the source gate, and only then constructs the lazy backend. `PySCFBackend._load_modules()` retains its own gate before any compute dependency import.

The future authorized path uses one parent-generated attempt ID. The worker writes only to an isolated scratch output root. A zero process exit is not accepted by itself: the parent runs the existing strict resume validator, requires the same attempt ID and exact six-file attempt set, verifies all request/protocol/source/input/output hashes, moves the attempt atomically, and publishes `success.json` followed by `_SUCCESS`.

Timeout, nonzero exit, orphan or invalid worker state is handled only after the supervisor has returned. The parent publishes one atomic `failure.json` attempt and never publishes `_ATTEMPT_SUCCESS`, `success.json` or `_SUCCESS`. If a supervisor raises unexpectedly and therefore cannot prove the group is dead, the parent neither publishes an attempt nor deletes the scratch state.

Runner identity was upgraded from one-file hashing to a canonical, length-delimited SHA256 over the complete eight-file pre-gate local import chain: the top-level, data and quantum package initializers; constants and provenance utilities; and `two_endpoint.py`, `worker.py` and `process_supervisor.py`. The worker starts through a fixed `python -I -B` bootstrap, inserts only the exact source root, discards inherited Python path/home/startup settings and fixes its working directory to that source root. This closes the earlier gaps in which a request did not bind the worker, timeout implementation or package import chain and a caller working directory could shadow the intended module.

## Read-only server preflight

The ignored `configs/phase8a.local.yaml` was derived from the established Phase 7 route. Its type schema fixes `read_only=true`, `server_write_authorized=false` and `quantum_execution_authorized=false`. The user had confirmed the Mac was on the WHUT campus network, so the passwordless campus-direct route was used.

The launcher sent a non-persistent inspector over SSH stdin, explicitly entered the existing project root, sourced only `env/envs/molenv.sh`, set `PYTHONDONTWRITEBYTECODE=1`, limited thread environment variables to one, and invoked `python -B`. It created no remote file or directory and deployed no code file.

The first static contract treated the public `pyscf.dft.RKS` symbol as a class and failed closed. A portable diagnostic exposed only the failed logical check name. Inspection of the actual installed API and upstream source showed that public `dft.RKS` is a callable factory while `pyscf.dft.rks.RKS` is the implementation class. The corrected contract therefore requires the public callable and its `mol` parameter plus an SCF-subclass implementation class, without instantiating either. Three read-only attempts were made in total; the first two failed only this overstrict static assumption, and the third passed all 18 checks.

The final environment and API facts were:

- Python `3.11.15`, PySCF `2.13.1`, geomeTRIC `1.1.1`, pyscf-dispersion `1.5.0`;
- `geometric_solver.kernel(method, assert_convergence=True, ..., maxsteps=100, **kwargs)` exists and its installed source returns `(convergence, molecule)`;
- `geometric_solver.optimize` exists but its installed source selects element 1 and discards the convergence flag, so the runner correctly retains `kernel`;
- public `dft.RKS(mol, xc='LDA,VWN')` is callable and the implementation class derives from `SCF`;
- static `SCF.do_disp`, `SCF.get_dispersion` and `SCF.newton` hooks exist, with the dispersion aliases matching the installed helper functions;
- both the SCF supported-version table and the D3 adapter damping map contain `d3bj`;
- `DFTD3Dispersion.__init__(self, mol, xc, version='d3bj', atm=False)` exists.

The exact 27 Phase 7 files matched the registered canonical path/hash tree before inspection and remained identical afterward. The registered `molenv.sh`, legacy `gen_3d.py` and `structure_gen.py` hashes also matched and remained unchanged. The original Phase 7 reported tree identity remains `644f027e276902dc1ab105f02f08864967f69ae87dc8883f608f5e4d17a372ad`.

## Scientific interpretation and limitations

This phase proves static compatibility and process containment readiness, not a quantum-chemistry result. In particular, import/signature/source inspection cannot prove that assigning `mf.disp='d3bj'` contributes the expected D3(BJ) energy and gradient in a real calculation. It also cannot prove convergence for any candidate. Those are dynamic facts and remain blocked behind a separately reviewed Phase 8B smoke.

The four Phase 7 geometries remain initial force-field geometries only. No endpoint was optimized, no electronic energy or label was produced, and the other 46 planned candidates still lack generated geometries.

## Files changed

Tracked Phase 8A changes include the documentation gate, strict read-only configuration and launcher, static inspector and evidence, generic process supervisor, internal worker, runner publication protocol, harmless process fixtures, tests and this report. Private server coordinates remain only in ignored `configs/phase8a.local.yaml`; no runtime chemistry result was added.

## Gate conclusion and next action

The Phase 8A hard wall-time and static API compatibility gates pass. `EXECUTION_AUTHORIZED` remains false and Phase 8B is stopped. Any real DFT smoke requires a new explicit user decision covering the exact candidates/endpoints, resource and thread limits, remote run root, timeout, dynamic D3(BJ) acceptance and failure/cleanup policy.
