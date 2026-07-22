# Phase 8B Single-Candidate DFT Smoke Plan

## Decision and authorization boundary

Phase 8A was merged to `main` by PR #8 at merge commit
`d621ca8b3db6816a5de895812af1cea2bef651d9`. This Phase 8B document freezes the
smallest useful real-DFT smoke, but it does not authorize that smoke.

The present planning branch may only read existing repository evidence and the
local server operating notes. It must not connect to the server, create a remote
directory, upload a file, construct a PySCF molecule, import a local chemistry
stack, run the worker, or change an execution gate. In particular:

```text
EXECUTION_AUTHORIZED = false
request.execution_authorized = false / not yet generated
private quantum_execution_authorized = false
server_write_authorized = false
```

After this plan is reviewed and merged, work stops for a second explicit user
decision. Only an instruction that clearly authorizes the exact frozen smoke
may permit the implementation, isolated deployment, and one real attempt. A
generic “continue” or “enter Phase 8B” is not that execution authorization.

## Planning verdict

The first real smoke will use exactly one of the four Phase 7 candidates:

```text
InChIKey: QXHIEGFUWOLQIJ-UHFFFAOYSA-N
request_id: phase8b-qxh-smoke-v001
attempt_id: attempt-phase8b-qxh-v001
endpoints: cation, then neutral
candidate replacement: prohibited
second attempt: prohibited
```

This is an infrastructure-smoke decision, not a claim that QXH is the best
scientific candidate. All four Phase 7 geometry pairs passed the same strong
validator. QXH is the smallest system (22 cation atoms, 21 neutral atoms, 17
heavy atoms in either endpoint) and contains no fluorine. It therefore provides
the lowest nominal first-smoke cost while still exercising both charges,
geomeTRIC, D3(BJ), final SCF, the hard timeout, and atomic publication.

The alternatives are larger: IJWC has 30/29 atoms, LBNP 26/25, and HQKH 27/26.
QXH comes from the `chemical_family_diversity` bucket, has production rank 11,
acquisition order 29, and medium suggested priority. Its registered family is
`Cyanomethyl|Cyanomethyl` / `NO2|NO2`. It retains `baseline_extrapolation`,
`unseen_axis_a`, `high_uncertainty`, and unavailable-size limitations. A success
cannot validate ranking quality, larger or fluorine-rich molecules, the cutoff
bucket, or the uncertain/OOD bucket.

## Frozen input identity

The only executable coordinate inputs are the ignored, immutable Phase 7
result files below. Coordinates stay outside Git; only their identities and
portable validation facts may be tracked.

| Endpoint | Charge / multiplicity | Atoms | Phase 7 relative path | SHA256 |
| --- | --- | ---: | --- | --- |
| cation | `+1 / 1` | 22 | `m2/xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_cation.xyz` | `097f08ab7c3f265efa8ee36c3fd45d72776c9bdcbd3de503baf8fe91561c12aa` |
| neutral | `0 / 1` | 21 | `m2/xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_neutral.xyz` | `e41e87daca3c7a74383364a427d277df5cf8a0aa70bff015c4cf432455f26bd0` |

Required supporting identities are:

| Evidence | SHA256 |
| --- | --- |
| corrected endpoint map | `0cb13e918f2fa88348affb2385d37e01a75d73376118d18aa4c7647ef4982152` |
| legacy atom map | `7766fad207561b79ac8e7278b70eb07c37dcf31d4114b76ad9a9383b235681f8` |
| Phase 7 geometry validation | `35e99683a32e416752014c6e1ecb8121e2bc06d5407911435e5c1250fd639f90` |
| Phase 7 package manifest | `2c4d776ab009a1c265d080dc55392fc7cdf38137a62200fa4b67a38f79746ae9` |
| four-candidate canonical CSV | `f486f93a2d58fb144c05a7340fd432334eeec46385c9319aca34d2e1b5c4cc87` |
| Phase 7 geometry request | `9993105e2a542d6abd1b8bf735640fb5bf3e9fd078bbb6ccc604e21768a5b5ef` |

The existing validation records endpoint charges, matching heavy-element
multisets, the one C2-proton difference, matching endpoint-specific indices
`C2=4, N1=3, N3=5`, and minimum interatomic distances of
1.087779561 Å / 1.094998256 Å. The provenance remains
`initial_force_field_geometry` with
`force_field_convergence=unavailable_legacy_m2`; it is not evidence of a local
minimum or guaranteed DFT convergence.

Before PySCF can import, the future request builder must re-read the exact
Phase 7 hash closure and prove from the registered element sequences, charges,
and endpoint maps that:

- the heavy-atom ordering is the same across endpoints;
- neutral differs by only the C2 proton;
- the two endpoints contain the same number of electrons;
- that electron count is even and the locked RKS singlet is consistent;
- neither XYZ, map, validation report, or manifest has drifted.

No geometry regeneration, atom reordering, alternative conformer, or candidate
fallback is allowed. For the frozen files the independently recomputed count is
120 electrons in each endpoint; execution must reproduce that exact value.

## Frozen scientific protocol

The unique permitted scientific path is:

```text
cation initial XYZ
  -> RKS B3LYP-D3(BJ)/def2-SVP, grid level 3
  -> geomeTRIC optimization, maxsteps 100
  -> final RKS B3LYP-D3(BJ)/def2-SVP electronic energy

neutral initial XYZ
  -> RKS B3LYP-D3(BJ)/def2-SVP, grid level 3
  -> geomeTRIC optimization, maxsteps 100
  -> final RKS B3LYP-D3(BJ)/def2-SVP electronic energy
```

Both endpoints are gas-phase singlets. SCF convergence tolerance is `1e-9`.
Standard SCF uses at most 100 cycles. Only a standard-SCF convergence failure
may trigger one same-protocol SOSCF/Newton retry with at most 200 cycles. A
geometry failure, D3 failure, timeout, resource failure, non-finite value, or
any other exception does not permit a retry or protocol change. If cation
fails, neutral is not started. If neutral fails, the whole candidate fails.

The current adapter does not yet enforce that distinction reliably:
`final_scf` wraps any kernel exception as `SCFConvergenceError`, while the
optimization path infers an SCF failure from exception-message text. Phase 8B
must replace that ambiguous classification with an explicit, tested failure
taxonomy before execution; D3, memory/resource, timeout, geometry, and unknown
errors must propagate without entering SOSCF.

The accepted label is strictly:

```text
electronic_difference_kcal = (E_neutral - E_cation) * 627.509474
dft_deprot_electronic_kcal = electronic_difference_kcal - 6.28
lower_is_better = true
label_quality = electronic_energy_only
```

No Hessian, frequency, imaginary-frequency count, ZPE, entropy, thermal
correction, Gibbs label, radical, unrestricted calculation, solvent, density
fitting, ωB97X-D/def2-TZVP calculation, Molden file, population analysis,
orbital property, or other electronic single point is allowed. A successful
geometry is not called a frequency-confirmed minimum.

## Dynamic D3(BJ) proof

Phase 8A established API availability, not runtime use. Merely setting
`mf.disp = "d3bj"` and checking `do_disp()` is insufficient for Phase 8B.
The future implementation must collect the following evidence from the same
authorized endpoint work:

1. Every standard or SOSCF mean field retains `disp == "d3bj"` and reports the
   D3(BJ) dispersion tag.
2. The optimization observes the actual dispersion-gradient hook. Its call
   count must be greater than zero, and every returned array must have exact
   shape `natm x 3` with finite values.
3. The final SCF must leave a finite, nonzero
   `scf_summary["dispersion"]`, and the stored total electronic energy must be
   the already dispersion-inclusive PySCF total. Instrumentation must record at
   least one final-SCF dispersion-energy hook call, and the finite numeric
   `scf_summary` components, including dispersion exactly once, must reproduce
   the returned total within `1e-12` Hartree.
4. Once per endpoint, at the already accepted final geometry, the D3 adapter
   must re-evaluate only the D3 energy and gradient as a zero-SCF audit. The D3
   energy must match `scf_summary["dispersion"]` within `1e-12` Hartree and the
   gradient must be finite with shape `natm x 3`. This diagnostic is not a
   no-D3 comparison, does not evaluate an electronic wavefunction, is not used
   as a second label, and must never be added to the total energy again.
5. The result and resume schemas must record the dispersion tag, energy
   component, energy/gradient-hook counts, finite/shape checks, arithmetic and
   audit agreement, and the installed adapter version for both endpoints.

This contract follows the version-locked PySCF behavior: the official
[SCF dispersion implementation](https://raw.githubusercontent.com/pyscf/pyscf/v2.13.1/pyscf/scf/dispersion.py)
stores the D3 contribution in `scf_summary`, and the official
[gradient implementation](https://raw.githubusercontent.com/pyscf/pyscf/v2.13.1/pyscf/grad/rhf.py)
adds the dispersion gradient when dispersion is active. Execution still has to
prove those paths dynamically on the installed server environment.

## Frozen resource and timeout envelope

The smoke is one worker and the endpoints run strictly in cation-then-neutral
order. No endpoint or candidate parallelism is allowed.

| Control | Frozen value |
| --- | ---: |
| worker count | 1 |
| computational thread settings | 4 |
| whole-tree CPU affinity | logical CPUs `0-3` |
| PySCF `max_memory` | 12,000 MB |
| whole-request hard wall-time | 7,200 s |
| TERM grace before KILL | 10 s |
| retained stdout | 65,536 bytes |
| retained stderr | 65,536 bytes |
| external observation envelope | 7,320 s |

Before the worker or PySCF imports, the parent must replace inherited values
with:

```text
OMP_NUM_THREADS=4
OMP_THREAD_LIMIT=4
OMP_MAX_ACTIVE_LEVELS=1
OMP_NESTED=FALSE
OMP_DYNAMIC=FALSE
OMP_WAIT_POLICY=PASSIVE
OPENBLAS_NUM_THREADS=4
MKL_NUM_THREADS=4
MKL_DYNAMIC=FALSE
GOTO_NUM_THREADS=4
BLIS_NUM_THREADS=4
NUMEXPR_NUM_THREADS=4
VECLIB_MAXIMUM_THREADS=4
```

After PySCF imports, the worker calls and verifies `pyscf.lib.num_threads(4)`.
The molecule is constructed with `max_memory=12000`, and the observed value is
recorded. This is a PySCF internal soft limit, not an OS-level RSS hard cap; the
report must not describe it otherwise. Memory exhaustion is a failure, never a
reason to enlarge the value in place.

The detached supervisor is launched under `taskset -c 0-3`, so the supervisor,
worker, native threads, and any descendants inherit a four-logical-CPU OS
affinity ceiling. The independent watchdog verifies every known process and
thread remains inside `0-3`, records `Cpus_allowed_list` and NLWP, and fails the
attempt on expansion. This CPU affinity is the hard compute cap; the thread
environment remains an additional library-level control. If CPUs `0-3` are not
online or `taskset` is unavailable, preflight stops rather than choosing a new
CPU set.

The 7,200-second supervisor deadline covers worker bootstrap, imports, both
endpoints, the allowed in-attempt SOSCF paths, diagnostics, and worker writes.
TERM/KILL cleanup and parent-side validation/publication occur after that
deadline, so read-only monitoring may continue to 7,320 seconds. An outer shell
`timeout` must not kill the supervisor early.

## Required implementation before execution

The Phase 8A runner must not be enabled unchanged. The implementation subphase,
still with fake backends and a closed public gate, must first add and test:

- exact source-level permission binding the one InChIKey, request ID, attempt
  ID, both XYZ hashes, exact remote relative root, resolved request/output
  paths, 7,200-second timeout, and unique protocol; a global boolean plus any
  structurally valid request is too broad;
- a private one-shot permit with those same identities and the final source,
  request, wrapper, and payload-manifest hashes. The payload manifest excludes
  the permit and outer transport inventory, avoiding any circular hash. The
  parent must atomically consume the permit with no-follow/exclusive-create
  semantics before spawn; consumption is
  irreversible on success, failure, spawn error, or timeout, and a second call
  must reject before PySCF import;
- all fixed thread variables, PySCF thread verification, inherited whole-tree
  CPU affinity `0-3`, and 12,000 MB molecule memory setting, all included in
  request/source hash closure;
- cross-endpoint electron count, element order, map, and C2-proton validation;
- explicit backend failure classification so only a proved standard-SCF
  non-convergence condition can trigger SOSCF; message substrings or a generic
  kernel exception must not authorize a retry;
- dynamic D3 energy/gradient telemetry without a no-D3 electronic calculation;
- success and resume schemas that validate all resource, D3, convergence, and
  supervisor fields;
- success evidence containing supervisor duration, PID/PGID identity,
  return codes, stream byte counts/hashes/truncation, group cleanup, and direct
  child reap;
- a server-side, chemistry-free deadline watchdog independent of the
  supervisor. A start handshake must keep the worker before PySCF import until
  the verified PID, PGID, Linux `/proc/<pid>/stat` start time, fixed affinity,
  and watchdog acknowledgement are durably registered. Parent-death signaling
  closes the registration race; after release, the watchdog enforces the same
  absolute deadline and exact-group cleanup if the supervisor crashes;
- failure publication that retains a bounded, same-attempt worker failure
  diagnosis after cleanup is proved, without publishing partial endpoint
  success or deleting unverified scratch;
- a deterministic request/bundle builder and a server wrapper whose exact file
  inventory is hashed before deployment.

All implementation tests use fake backends or standard-library process
fixtures. Tests must prove that request/environment/config overrides cannot
increase resources, change the candidate, add a second attempt, bypass dynamic
D3 fields, misclassify D3/resource/timeout/geometry/unknown errors as SCF
non-convergence, weaken convergence, or publish mixed-attempt results. They
must also prove that a consumed permit cannot be restored or copied to another
root/output, the worker cannot pass its pre-import handshake without a live
registered watchdog, and a deliberately SIGKILLed supervisor leaves no worker
or grandchild after the independent deadline. PID reuse/start-time mismatch
must fail without signaling an unrelated process. The generic source and
private execution gates remain false until the final separately authorized
execution-bundle preparation.

## Fresh read-only server preflight

The Mac is currently on the WHUT campus network, so the future private
configuration selects the campus-direct route. A failed direct connection is
handled according to the local server notes; repeated reconnects are forbidden.
If local DNS returns `198.18.x.x`, it is treated as Clash/sing-box fake IP and
is not used to diagnose public DNS, Cloudflare, Nginx, HTTPS, or the server.

Immediately before any server write, one combined read-only preflight must
verify all of the following:

- the resolved project root and molecular environment script match the private
  configuration; only `molenv.sh` is sourced, never `.bashrc` or another stack;
- Python 3.11.15, PySCF 2.13.1, geomeTRIC 1.1.1, and
  pyscf-dispersion 1.5.0 still match the Phase 8A evidence;
- the installed `scf/hf.py`, `scf/dispersion.py`, `grad/rhf.py`,
  `grad/dispersion.py`, D3 adapter and geomeTRIC API sources, the exact 27
  Phase 7 files, the QXH inputs, endpoint maps, and validation evidence match
  their registered hashes;
- `nproc >= 8`;
- `taskset` exists and online logical CPUs include the exact set `0-3`;
- both `load1` and `load5` are no greater than `0.75 * nproc`;
- `MemAvailable >= 32 GiB`;
- the target filesystem has at least 20 GiB available;
- the current-user process inventory, `/proc/<pid>/cwd` attribution, RSS-sorted
  snapshot, and exact request/run-root search show no conflicting or residual
  Phase 8B process;
- the exact Phase 8B run root does not exist and neither its parent nor any
  transfer destination is a symlink;
- no molecule is constructed and no kernel, gradient, optimizer, dispersion
  evaluation, or Hessian API is invoked during preflight.

Any mismatch stops before `mkdir`. Values are not relaxed and the run is not
renamed to v002.

## Remote isolation, transfer, and launch

The only permitted remote relative root is:

```text
data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001
```

It will contain one manifest-closed request bundle, private logs, the one output
root, and audit state. It must not reuse or alter the Phase 7 run. Transfers use
explicit source and full destination paths for each registered file. Full-repo
deployment, `rsync --delete`, symlinks, package installation, environment
changes, and scheduler submission are prohibited.

After transfer, every source, request, XYZ, wrapper, and manifest is rehashed at
its actual destination. Every project-owned module used by the executable path
must belong to the exact source closure; standard-library and external runtime
imports are allowed only through the version/API/source identities registered
for the server environment. The frozen request is generated only after final
execution-source hashes exist, so it can bind those hashes without placeholders.

Bundle identity is an acyclic two-layer construction. First, an immutable
payload manifest hashes the executable source, wrappers, request, XYZ inputs,
maps, and protocol evidence, explicitly excluding the private permit and outer
inventory. Second, the permit binds that payload-manifest hash plus its exact
resolved paths and authorization fields. Finally, a transport inventory hashes
the payload manifest and permit for transfer/readback; the permit does not bind
the transport inventory. No file hashes itself and no two artifacts bind each
other cyclically.

The ignored private permit additionally binds the resolved concrete run root,
request path, output root, candidate/request/attempt, input/protocol/resource
identities, and all final payload hashes represented by the payload manifest.
Immediately before spawn, the parent
atomically transitions `permit.ready` to a non-reusable consumed state using
exclusive/no-follow semantics. The bytes and hash remain auditable, but no
ready permit remains. A copied bundle, different path, pre-existing consumed
state, or second invocation rejects before compute imports. Postflight must
prove that the permit is consumed and no reusable authorization file exists.

The local server rules require an hours-scale task to survive SSH or Mac
disconnects. After the second explicit authorization and all gates pass, the
only allowed launch is one self-contained, non-scheduler `setsid` invocation
with stdin detached and explicit log redirection. It records its exact PID/SID,
request, attempt, and run-root identity. The parent supervisor still creates and
owns the worker's separate verified process group. A separate chemistry-free
watchdog session records and validates supervisor/worker PID, PGID, session,
Linux process start time, and affinity against the consumed permit. No generic
background job, second attempt, broad `pkill`, or process-name kill is allowed.

The worker starts behind a pre-import handshake and Linux parent-death signal.
It cannot proceed until the supervisor has durably registered its verified
identity and the independent watchdog has acknowledged it. If the supervisor
dies during that race, the worker exits without chemistry. After release, the
watchdog uses the registered PGID plus process start-time checks to enforce the
same absolute deadline and bounded TERM/KILL cleanup even if the supervisor is
SIGKILLed. It never signals by name, argv substring, PID 0/1, an unverified
reused PID, the caller's group, or an unrelated session.

Monitoring is read-only and low frequency. It never drives progress. On timeout
the supervisor performs TERM, 10-second grace, KILL if required, bounded reap,
and process-group absence checks; the independent watchdog is the fail-safe for
supervisor death or hang. If group cleanup and direct-child reap cannot be
proved, no success/failure publication or scratch deletion is allowed and
execution stops for manual exact-PID/PGID/start-time audit.

## Success, failure, and evidence contract

A successful Phase 8B smoke requires all of these facts simultaneously:

- exact candidate/request/attempt, input, protocol, source, environment, and
  resource identities match;
- the one-shot permit was atomically consumed before spawn, matches the exact
  resolved paths, and no reusable permit remains;
- preflight gates passed before the run root was created;
- cation and neutral each explicitly report geomeTRIC convergence, final
  optimization SCF convergence, final same-method SCF convergence, finite
  energies, finite coordinates, and unchanged atom-element order;
- every D3 dynamic condition above passed;
- the label independently recomputes from the two final energies and the
  `-6.28 kcal/mol` proton constant;
- the exact success file set is hash-closed and contains no symlink or unknown
  file;
- supervisor outcome is clean, duration is within 7,200 seconds, the process
  group is empty, the direct child is reaped, and neither captured stream was
  truncated;
- watchdog/handshake identities and start times match, every process/thread
  stayed within CPU affinity `0-3`, and postflight finds no supervisor, worker,
  descendant, or watchdog process for the exact run;
- the remote inventory contains no Hessian, frequency, ZPE, thermal, radical,
  Molden, density-fitting, ωB97X-D/def2-TZVP, extra-single-point, scheduler, or
  second-attempt artifact;
- the Phase 7 tree and registered server sources are unchanged after execution.

If any item fails, no `_SUCCESS`, `success.json`, or label is accepted. A safe
failure publishes one atomic `failure.json` for the fixed attempt only after
group cleanup/reap proof. The failure records stage, bounded diagnosis,
supervision, D3/resource state reached, and all identities; it does not expose a
partial endpoint as a result. No candidate substitution, timeout increase,
memory increase, manual protocol tweak, root rename, or automatic rerun occurs.
The consumed permit stays consumed even when spawn or execution fails.

The exact remote run is downloaded into a new ignored local result tree and
independently rehashed. Raw coordinates, captured logs, private connection data,
and concrete remote/local paths remain ignored. Checked-in evidence may contain
only portable identities, versions, counts, convergence/D3/resource booleans,
energies and the derived electronic label, file hashes, and the honest outcome.

Planned later artifacts are:

```text
docs/PHASE8B_DFT_SMOKE_V001.json
docs/PHASE8B_REPORT.md
docs/PHASE8B_TEST_REPORT.md
configs/phase8b.example.yaml
```

The private route and authorization remain in ignored
`configs/phase8b.local.yaml`; coordinate/result bundles remain under ignored
`results/`.

## Ordered execution gates

After the second explicit authorization, the work order is fixed:

1. update `AGENT.md` again to record that exact authorization;
2. implement the generic blockers above with source/private/request gates false;
3. pass targeted and full pytest, Ruff lint/format, strict mypy, pre-commit,
   package build, forbidden-compute scans, and independent code/science audits;
4. make the final local execution-source change that enables only the frozen
   candidate/request/attempt/protocol/resource/path permit, then rerun all
   no-chemistry tests and independent audits on those exact bytes;
5. freeze the resulting source hashes; only then generate the true request,
   build the permit-excluding payload manifest, generate the ignored private
   one-shot permit that binds that payload manifest, and finally build the
   outer transport inventory that records the permit. Independently hash-check
   every layer. No executable byte may change after this point;
6. perform the single fresh read-only server preflight;
7. create the exact new root, transfer only registered final files, and rehash
   them at their actual destinations. No gate or source is edited remotely;
8. atomically consume the path-bound permit, complete the watchdog/worker
   handshake, and launch the one fixed attempt;
9. monitor read-only through the bounded envelope, run postflight, and download
   only the exact run;
10. independently validate all hashes and acceptance criteria, close all local
    execution gates, write portable evidence/reports, rerun local quality
    gates, and publish through review;
11. stop. Expansion to another candidate, model ingestion, or any subsequent
    phase requires a new decision.

## Planning-phase acceptance and mandatory stop

This documentation phase passes when the candidate, inputs, scientific scope,
dynamic D3 proof, resources, hard timeout, exact remote root, one-attempt
semantics, implementation blockers, deployment safety, and success/failure
evidence are all unambiguous; independent audits find no blocker; and all
execution gates remain false.

The mandatory next action is to merge this planning-only change and ask the
user whether to authorize the exact QXH smoke described here. No server or
chemistry action may occur before that answer.
