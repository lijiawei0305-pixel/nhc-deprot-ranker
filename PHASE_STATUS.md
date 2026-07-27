# Phase Status

Updated: 2026-07-27

| Phase | Status | Gate |
| --- | --- | --- |
| Phase 0 — legacy audit | Complete | Passed 2026-07-22 |
| Phase 1 — data contract/import | Complete and merged to `main` | Passed 2026-07-22 |
| Phase 2 — baselines | Complete and merged to `main` | Passed 2026-07-22 |
| Phase 3 — hierarchical model | Complete and merged to `main` | Passed 2026-07-22 |
| Phase 4 — model decision | Complete and merged to `main` | Passed 2026-07-22; `raw_xTB_wins` |
| Phase 5 — full scoring/acquisition | Complete and merged to `main` | Passed 2026-07-22 |
| Phase 6 — local DFT execution plan | Complete and merged to `main` | Passed 2026-07-22; PR #6 / `55bfe47` |
| Phase 7 — four-row geometry smoke and dedicated runner | Complete and merged to `main` | Passed 2026-07-22; PR #7 / `133f8e3`; DFT execution prohibited |
| Phase 8A — hard wall-time and read-only API preflight | Complete and merged to `main` | Passed 2026-07-22; PR #8 / `d621ca8`; DFT execution prohibited |
| Phase 8B — single-candidate DFT smoke | Complete with rejected execution incident | Failed closed 2026-07-23; unique attempt consumed; retry prohibited |
| Post-8B local safety closeout | Complete and merged to `main` | Passed 2026-07-26; PR #11 / `927ee26` |
| Phase 9A — AIMNet2 preoptimization audit and design | Complete; documents only | 2026-07-26; no execution, no server, no code |
| Phase 9A-R — read-only AIMNet2 server preflight | Passed with two blocking findings | 2026-07-26; read-only; no install, download, model load, or compute |
| Phase 9A-I — minimal inference characterization | Passed; six single-point calls executed | 2026-07-26; no optimization, no PySCF, no label |
| Phase 9A-S — installed AIMNet source inspection | Incomplete; loader decision unresolved | 2026-07-27; read-only; wrong interpreter probed; server unchanged |
| Phase 9A-S2 — exact interpreter discovery | Inconclusive; two environments match, loader decision unresolved | 2026-07-27; read-only; 1 of 2 SSH used, stopped on ambiguity; server unchanged |
| Phase 9A-S3 — activation-bound source inspection | Inconclusive; mlff.sh binding resolved, loader decision unresolved | 2026-07-27; read-only; 1 of 1 SSH used, stopped on interpreter enumeration; server unchanged |
| Phase 9A-S4 — deduplicated interpreter and source inspection | Passed; loader decision A, source_proven | 2026-07-27; read-only; 1 of 1 SSH used; 16 AIMNet + 25 ASE files read; server unchanged |
| Phase 9B item 8/10 — production execution runtime | Complete; loader, ASE/LBFGS optimizer, trajectory evidence, v8 rebaseline | 2026-07-27; local only; no model, no GPU, no server; eleven gates still false |
| Phase 9B — paired direct / assisted smoke | Framework 8 of 10 complete; execution stopped before any irreversible action | 2026-07-27; no single interpreter carries both the MLFF and PySCF stacks; nothing deployed, placed, consumed, or launched |
| Phase 9B-U1 — dedicated unified environment build and audit | Failed closed; incomplete v001 retained and unusable | 2026-07-27; exact stack installed, but capability harness observed 4 calculator invocations vs 2 expected; no retry; old environments unchanged |
| Phase 9B-U2 — unified environment v002 | Rejected environment; retained and unusable | 2026-07-27; capability counts/native/cache passed, but protected snapshot schema mismatch failed the canonical gate; no retry |
| Phase 9B-U3 — qualified metrology / v003 | Failed before environment creation; retained | 2026-07-27; helper rejected normal Conda Python symlinks as invalid; v003 resources never created |
| Phase 9B-U4 — symlink-aware metrology / v004 | Failed before environment creation; retained | Q4 reached conda evidence then returned `CONDA_EXPLICIT_FAILED` for all six; v004 resources never created |
| Phase 9B-U5 — metadata-native metrology / v005 | Document-first contract in progress | No SSH before PR merge; Q5 must pass all six objects before any v005 resource can exist |

## Current completed work

- Read the full task specification in `prompt.md`.
- Established repository-wide constraints in `AGENT.md`.
- Confirmed the `legacy_repo.root` current working tree as the primary Phase 0 audit source.
- Restricted the separate server-knowledge worktree to connection/HPC operating knowledge.
- Wrote the scientific scope, Phase 0 execution plan, and pre-execution audit template.
- Verified all 21 required legacy files and recorded their hashes.
- Established the 71-label composition, overlaps, local formula checks, target protocol, historical affine baseline, and feature-shortcut findings.
- Documented a no-write/no-compute server verification plan for the two HPC-only authoritative tables and raw gold endpoints.
- Completed the approved server read-only audit and closed all identified data-source gaps.
- Created the independent Git repository skeleton, MIT license, portable configuration, ignored local source map, package/CLI skeleton, Phase 0 utilities, source manifest, and reports.
- Published the Phase 0 foundation as the public GitHub repository `lijiawei0305-pixel/nhc-deprot-ranker` under MIT.
- Implemented local/SSH read-only streaming import, formula checks, canonical families, label conflict handling, protocol identity, provenance, atomic output, and immutable version enforcement.
- Built and independently verified `data/processed/v001`: 401,856 candidates, 71 labels, 100% fragment coverage, zero formula failures/conflicts, and one label protocol.
- Passed pytest (31), Ruff, mypy, configuration parsing, package build, pre-commit, and private-path checks.
- Merged Phase 1 PR #1 into `main` as `3626b0d` and opened the isolated Phase 2 baseline branch.
- Implemented B0/B1, exact LOOCV, axis-family holdouts, deterministic bootstrap, ranking metrics, immutable results, and auditable figures.
- Built and independently verified `results/baselines_v001`: 71 OOF rows per protocol, historical reproduction passed, 2,000/2,000 bootstrap fits succeeded, and all split/hash checks passed.
- Confirmed B1 improves absolute calibration but does not improve B0 ranking; production promotion remains deferred to Phase 4.
- Merged Phase 2 PR #2 into `main` as `e33e5cf` and opened the isolated Phase 3 branch.
- Re-audited current H1 support: one skeleton, 38 axis-A families (22 singletons), 35 axis-B families (16 singletons), and 71 combined-family singletons.
- Implemented the H1 penalized additive estimator, deterministic finite nested penalty search, train-only preprocessing, zero-effect unknown-family fallback, fixed-penalty paired bootstrap, serialization, manifests, and nine figures.
- Built and independently verified `results/hierarchical_v001`: LOOCV/axis-A/axis-B each cover 71/71 keys, all held-out family contributions are zero, model roundtrip is exact, and 2,000/2,000 bootstrap fits succeeded.
- Recorded provisional H1-vs-B1 evidence without promotion: H1 improves LOOCV MAE from 2.7216 to 2.2373 kcal/mol and Spearman from 0.95708 to 0.97297; Axis-B MAE worsens from 2.7875 to 2.9163 despite improved rank correlations.
- Audited weak family identification: 72/73 active family-effect bootstrap 95% intervals cross zero; this limitation is carried forward to Phase 4.
- Merged Phase 3 PR #3 into `main` as `2571ddc` and opened the isolated Phase 4 branch.
- Audited the frozen promotion evidence and identified the only unresolved scientific policy: numerical definitions for catastrophic held-out-family error and bootstrap family-offset stability.
- Confirmed and froze the conservative Phase 4 family-collapse, conditional sign-stability, and stable head-recall rules in `configs/evaluation.yaml`.
- Implemented the frozen-evidence evaluator, deterministic paired OOF bootstrap, B1/H1 promotion gates, family collapse/stability audits, immutable manifests, CLI, and four figures.
- Built and independently verified `results/decision_v001`: 55 input hashes, 13 runtime files, 180 uncertainty rows, and 6,000/6,000 protocol bootstrap replicates all passed.
- Final decision: `raw_xTB_wins`. B1 failed to improve primary ranking; H1 failed stable head recall, stable improvement over B0, one catastrophic held-out family, and one supported offset-stability gate.
- Selected B0 as the production ranking default and retained B1 as the absolute-calibration companion; H1 was not promoted.
- Merged Phase 4 PR #4 into `main` as `18aae58` and opened the isolated Phase 5 branch.
- Re-audited all 401,856 candidate fields: size is missing for every row; 2,782 rows are outside the labeled xTB range; only 2,316 rows have both axis families seen in training; all raw Top-50 rows are below the labeled xTB range and have at least one unseen axis family.
- Confirmed all 2,000 B1 bootstrap slopes are positive (`0.6259–0.8065`), so B1 companion ranks and Top-K membership are identical to B0 in every replicate.
- Confirmed the dual-track B0/B1 output semantics, Top-100 review table, and 50-candidate acquisition policy with exact quotas `15/13/12/10`.
- Implemented typed Phase 5 configuration, full scoring, B1 coefficient-bootstrap companion intervals, applicability flags, deterministic acquisition, immutable manifests, CLI, and eight audit figures.
- Built and independently verified `results/scoring_v001`: 401,856 unique ranked candidates, exact B0/calibrated rank identity, zero rank shifts, 2,782 baseline extrapolations, explicit size-unavailable status on every row, and no fully in-domain claims.
- Built and independently verified `results/acquisition_v001`: 50 unique unlabeled candidates, zero overlap with 71 labels, exact quotas with no fill, 46 combined families, and a local-only high-fidelity manifest with `submit_hpc=false`.
- Passed 87 pytest tests, Ruff, strict mypy, real output/hash readback, and visual QA; no quantum-chemistry or server/HPC action occurred.
- Authorized Phase 6 only as local planning: audited the legacy no-Hessian interface, confirmed no complete cation/neutral XYZ pair exists for the selected 50, and identified the legacy runner's additional ωB97X-D single-point steps as an execution blocker.
- Implemented strict Phase 6 configuration, upstream evidence/runtime/`_SUCCESS` hash-chain validation, exact 5×10 allocation, four-bucket smoke selection, safe immutable text-only output, CLI, and synthetic failure-path tests.
- Built and independently verified `results/dft_input_plan_v001`: 50/50 unique candidates, zero overlap with 71 labels, exact `15/13/12/10` totals, five ten-row batches, four smoke rows, 15 files, six directories, and zero geometry/executable/symlink artifacts.
- Recorded `geometry_generated=false`, `quantum_chemistry_run=false`, `hessian_computed=false`, `execution_ready=false`, `server_write_authorized=false`, and `submit_hpc=false` throughout the package.
- Preserved both required blockers, `blocked_no_xyz` and `blocked_runner_extra_steps`, and published complete checked-in evidence in `docs/DFT_INPUT_PLAN_V001_MANIFEST.json`.
- Merged Phase 6 PR #6 to `main` at `55bfe47` before opening the isolated Phase 7 branch.
- Received the user decision to use audited legacy M2 for exactly four server-side smoke geometries and to develop a dedicated two-endpoint runner without executing DFT.
- Read the server-knowledge worktree, legacy M2/M4 source, environment/connection rules, and relevant failure skills; prohibited full deploy/`rsync --delete` and froze an isolated, directed-transfer workflow.
- Identified the observed cation-map/neutral-index mismatch risk and required endpoint-specific graph/coordinate validation rather than trusting legacy file existence or exit code.
- Implemented the strict four-row bundle builder, standalone strong geometry validator, ignored remote-route schema, and dedicated guarded two-endpoint runner.
- Created and independently hash-verified the immutable local `geometry_smoke_bundle_v001`: eight registered files, canonical input 542 bytes / `f486f93a...cc87`, package manifest `2c4d776a...6ae9`, no symlinks, private paths, bytecode, geometry, or quantum result.
- Passed 188 local tests, Ruff lint/format, strict mypy, pre-commit, Bash syntax, package build, and an independent Phase 7 safety/science audit. All chemistry adapters were fake or lazy; no RDKit, PySCF, or geomeTRIC execution occurred.
- Used the user-confirmed campus-direct route, passed the corrected read-only server preflight, and recorded Python 3.11.15 / RDKit 2025.03.6 plus exact legacy source hashes before any write.
- Uploaded exactly eight registered bundle files to one new isolated run root with directed transfers and no delete, then ran only legacy M2 at `parallel=1`: 4/4 processed, 4/4 successful, zero failed/skipped/backfilled, and an empty failure log.
- Strongly validated 8 XYZ, 4 legacy maps and 4 corrected endpoint maps; all charges, AddHs sequences, heavy-element sets, one-proton differences, C2 five-membered-ring mappings, coordinates and SHA256 checks passed.
- Downloaded only that run and independently matched 27/27 remote/local files. Validation SHA256 is `35e99683...39f90`; result-tree SHA256 is `644f027e...72ad`; the independent result audit found no blocker.
- Kept the dedicated runner unexecuted with source-level authorization false. No PySCF, xTB, Hessian, legacy M4, extra single point, scheduler or background job ran.
- Merged Phase 7 PR #7 to `main` at `133f8e3` before opening the isolated Phase 8A branch.
- Received user authorization for Phase 8A hard-timeout development and read-only server API compatibility inspection only; real DFT remains unauthorized.
- Implemented a POSIX session/process-group supervisor with fail-closed monotonic deadline, bounded dual-stream draining, TERM/grace/KILL, bounded reap, orphan detection and explicit cleanup/reap proof. No-chemistry tests cover delayed observation, inspection failure, ignored TERM, grandchildren, output flood, spawn/policy errors and repeated no-residual runs.
- Added an isolated `python -I -B` worker bootstrap, eight-file pre-gate source identity, double source/request gates, fixed-attempt scratch isolation and parent-only atomic success/failure publication. `EXECUTION_AUTHORIZED` remains false.
- Completed the campus-direct read-only server API inspection: Python 3.11.15, PySCF 2.13.1, geomeTRIC 1.1.1 and pyscf-dispersion 1.5.0; all 18 static checks passed. The exact 27 Phase 7 files and three registered server sources matched and remained unchanged.
- Recorded portable evidence in `docs/PHASE8A_API_PREFLIGHT_V001.json` and passed 238 tests, Ruff, format, strict mypy for 65 source/script files, pre-commit, build and independent code/evidence audits. No molecule, DFT, optimizer, dispersion, Hessian, server write or job ran.
- Merged Phase 8A PR #8 to `main` at `d621ca8` before opening the isolated Phase 8B planning branch.
- Entered Phase 8B documentation planning only; no Phase 8B source/request/private-quantum/server-write authorization exists or is enabled. Historical Phase 7/8A authorization records are not reused as Phase 8B authority.
- Independently compared the four validated Phase 7 candidates and selected `QXHIEGFUWOLQIJ-UHFFFAOYSA-N` as the lowest-resource infrastructure smoke: 22/21 atoms, 17 heavy atoms, no fluorine, with exact cation/neutral XYZ SHA256 `097f08ab...1c12aa` / `e41e87da...26bd0`. This is not a scientific-best-candidate claim.
- Froze one worker, cation-then-neutral serial execution, 4 computational threads, whole-tree CPU affinity `0-3`, PySCF `max_memory=12000 MB` soft limit, a 7,200-second whole-request hard wall-time, 10-second TERM grace, 64 KiB per captured stream, and exact remote relative root `data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001`.
- Audited the Phase 8A runner and found execution blockers that must be implemented and mock-tested before a real attempt: exact path-bound one-shot permit, irreversible pre-spawn consumption, fixed affinity/thread/memory controls, independent supervisor-death watchdog, explicit retry/error taxonomy, cross-endpoint/electron validation, dynamic D3 energy/gradient evidence, and complete success/failure supervision evidence. Merely changing `EXECUTION_AUTHORIZED` is prohibited.
- Wrote `docs/PHASE8B_IMPLEMENTATION_PLAN.md` with the unique protocol, D3-only zero-SCF diagnostic boundary, fresh resource preflight, isolated directed transfer, one controlled detached supervisor, no-fallback failure semantics, private-result handling, portable evidence contract, and a mandatory second authorization pause. No SSH, server write, molecule, PySCF, geomeTRIC, D3 evaluation, Hessian, worker, or source-gate change occurred.
- Passed 238 tests in the repository virtual environment, pre-commit, diff/portable-path/source-gate scans, and independent candidate, resource, science/D3, process-safety, and document-consistency audits. Audit findings were resolved in the plan; no Critical or High issue remains at the planning gate.
- Merged the Phase 8B planning-only branch as PR #9 at `d5e5f61`, then received explicit authorization for exactly one frozen QXH attempt with no replacement or retry.
- Implemented the one-shot permit, exact authority and source closure, pre-import worker handshake, permanent compute claim, independent Linux guardian, CPU/thread/memory controls, dynamic D3 evidence contract, strict deployment/launch/postflight tooling, and no-chemistry regression coverage.
- Passed the execution preflight, created only the frozen isolated target, transferred the exact 28-file bundle, and issued exactly one launch. The permit was consumed and the compute claim was published; no second launch occurred.
- Rejected the attempt because the immutable guardian receipt recorded `cleanup_failed` and did not bind the permanent compute-claim hash. No cation or neutral endpoint result, accepted SCF energy, dynamic D3 evidence, or deprotonation label exists.
- Determined that a transient `S` to `R` process-state change was incorrectly compared as durable identity drift. Future code now compares only stable identity fields at terminal readback while retaining exact registration/acknowledgement/claim equality.
- Corrected the future postflight reader to accept the registered zero-byte Phase 7 helper log only in the Phase 7 tree. The historical postflight remains incomplete, the immutable receipt remains rejected, and kernel invocation remains `indeterminate`.
- Permanently retired the consumed QXH production bundle and launch routes, passed 556 closed-gate tests, Ruff, strict mypy for 72 source files, pre-commit, compileall, package build, privacy/diff checks, and a final security review with no remaining High, Critical, or Medium issue.
- Published the rejected Phase 8B incident, future-code corrections, and closed-gate verification to `main` at merge commit `7d65f72`.
- Audited the retired authority chain and found the directed deployment route carried neither the source execution gate nor a consumed latch, leaving the mutable private configuration as its only protection; added both checks ahead of the timeout check, configuration load, plan build, permit validation, and any injected command runner.
- Closed the stale `server_write_authorized` bit that survived the consumed attempt in the ignored local Phase 8B configuration; the file remains untracked and uncommitted.
- Added six no-chemistry revival-resistance regressions proving all three retired routes hold the latch simultaneously, the checked-in execution gate is false, a stale `server_write_authorized: true` configuration cannot revive deployment, and refusal precedes every input read and SSH attempt. Mutation-tested by flipping the deployment latch off, which failed four of the six.
- Corrected current-state drift: `PHASE_STATUS.md` listed an already-completed publication as the next action, `AGENT.md` named only the PR #9 planning merge, and `AGENT.md` implied the frozen postflight rejected the attempt after reading the receipt when it had exited earlier at a legitimate zero-byte Phase 7 helper log.
- Passed the closeout gate on CPython 3.14.3: 562 tests, Ruff lint and format, strict mypy for 72 source files, private-path scan, diff check, and an unchanged `docs/PHASE8B_DFT_SMOKE_V001.json` hash. Recorded, rather than fixed, a pre-existing `pre-commit` `UP038` failure in an untouched file caused by the hook pinning ruff `v0.12.4` against the project's `0.15.16`.
- Authorized Phase 9B-U1 as a new-prefix-only installation: completed the document-first plan and a before snapshot over project mlff, project aimnet2, project gpupyscf and shared molecular before any server write.
- Downloaded the exact PySCF 2.13.1, geomeTRIC 1.1.1 and pyscf-dispersion 1.5.0 artifacts from official PyPI/files.pythonhosted.org, re-read all registered SHA256 values, built the geomeTRIC wheel inside the clone, and installed all three offline with `--no-deps`; no model or ensemble member was downloaded.
- Offline-cloned project mlff into the new versioned v001 prefix and preserved Python 3.11.15, torch 2.8.0+cu128, CUDA 12.8, `sm_70`, aimnet 0.2.0 and ASE 3.29.0. PySCF 2.13.1, geomeTRIC 1.1.1 and pyscf-dispersion 1.5.0 are present; `pip check` and independent metadata dependency validation passed with no protected-package drift.
- Failed the unified capability harness closed after both endpoint property reads because the counting adapter observed four calculator invocations while the harness preregistered two. No retry or reinterpretation occurred; native-map, endpoint-payload and global-cache after evidence remained incomplete, so the v001 environment is `failed_incomplete_environment` and unusable.
- Recomputed all four protected-environment snapshots after the failure and proved every before/after SHA identical. Retained the failed prefix, wheelhouse, cache and evidence; ran no optimizer, PySCF kernel/gradient, geomeTRIC, D3 energy or label calculation, and kept all eleven public execution gates false.
- Closed the public U1 evidence with 1282 tests passing three consecutive times, targeted identity tests, Ruff lint/format, strict mypy for 88 source files, compileall, package-wheel build, privacy/diff/gate scans, independent v8 source digest recomputation, frozen Phase 8B artifact verification and a killed/restored document mutation. `pre-commit --all-files` reproduced only the recorded untouched-file Ruff 0.12.4 `UP038` baseline at `tests/test_phase8b_runtime.py:770`.
- Completed the U2 document-first contract as PR #50 before the first server write, froze property-read versus `AIMNet2ASE.calculate()` terminology, and mutation-tested the append-only receipt harness.
- Built the new v002 prefix from a copy-mode offline MLFF clone, newly downloaded all three exact official artifacts, rebuilt geomeTRIC, passed `pip check`, metadata validation, exact package checks, protected-package zero drift and zero v001 hardlinks.
- Persisted both compatible import-order native receipts and acknowledgements, then observed exactly one model load, two wrappers, four property reads and four `AIMNet2ASE.calculate()` entries with finite endpoint results, unchanged coordinates, zero external Internet calls, and no global-cache or target-environment drift.
- Rejected v002 because the before protected snapshot schema omitted `state` while the after schema added `state=present`; all physical tree and critical package evidence matched, but the canonical snapshot SHA contract did not. Retained all v002 resources and evidence without retry, repair, deletion, reuse, v003 creation, scientific execution, or label generation.

## Current boundary

Phase 0–8A, the Phase 8B planning gate, and the rejected Phase 8B incident are
all complete and merged. The rejected incident, its future-code corrections,
and its closed-gate verification were published to `main` by merge commit
`7d65f72`; that publication is done and is no longer pending.

The only authorized Phase 8B QXH attempt was consumed and rejected at the
execution protocol layer. Its permit, attempt identity, bundle, and remote root
are permanently unusable. No acceptable DFT endpoint or label was produced, and
the source execution gate is false.

A local safety closeout follows the incident publication. It is local only and
is planned in `docs/PHASE8B_CLOSEOUT_PLAN.md`: current-state document
corrections, closing the stale private `server_write_authorized` bit, adding
the missing source gate and consumed latch to the directed deployment route,
revival-resistance regressions, and a scope-matched quality gate. It connects
to no server, runs no chemistry, and opens no execution gate.

The user selected the third forward option — a wholly new calculation phase —
and froze AIMNet2 as the structure preoptimization model. Phase 9A delivered the
read-only audit and the document-first design for that pipeline:

```text
SMILES -> RDKit ETKDGv3 -> MMFF94 (UFF on exception)
       -> cation and neutral endpoints
       -> AIMNet2 geometry preoptimization
       -> PySCF B3LYP-D3(BJ)/def2-SVP residual final optimization
       -> final electronic energies -> deprotonation electronic-energy label
```

Phase 9A ran no AIMNet2, no PySCF, no force field, and no server command, wrote
no implementation code, and opened no gate.

Phase 9A-R was authorized and executed as a read-only inspection. It passed:
torch `2.8.0+cu128` with `sm_70`, ase `3.29.0`, and aimnet `0.2.0` are installed
on 8x Tesla V100-SXM2-32GB, and the calculator accepts total charge and
multiplicity explicitly. The weight cache was byte- and mtime-identical before
and after, so the inspection changed nothing.

Two findings were recorded and both are now handled rather than open. Only
ensemble member `_0` exists locally (`aimnet2_wb97m_d3_0.pt`, SHA256
`f0f7c054...4e28`); members `_1`, `_2`, and `_3` are absent and may not be
downloaded, and the single-member safeguards are frozen. Separately, the
calculator's default model string exposes a remote-fetch path, which is why the
production loader must use an explicit local path and why the exact mechanism for
doing so has to be recovered rather than guessed.

The Phase 9B implementation plan was re-baselined twice — from six components to
eight, then to ten — as building each item surfaced real integration gaps: the
launch argv had no CLI to parse it, the supervisor's production execution path
was unwired (`execute=None`), nothing placed the one-shot permit, and the
production AIMNet2 adapters were refusal stubs. Eight of ten are now built, all
with their source gates closed:

```text
1/10  preparation/phase9b_preopt.py      AIMNet2 preoptimization contract  complete
2/10  preparation/phase9b_bundle.py      request and payload manifest      complete
3/10  preparation/phase9b_preflight.py   read-only environment recheck     complete
4/10  preparation/phase9b_deploy.py      directed two-route deployment     complete
5/10  preparation/phase9b_launch.py      two-route guardian launch         complete
6/10  pre-launch integration closure     CLI, adapter, permit stage        complete
7/10  quantum/phase9b_guardian.py        guardian, transport, handoff      complete
8/10  execution runtime closure          production loader, optimizer,     complete
                                         trajectory evidence, v8 rebaseline
9/10  preparation/phase9b_postflight.py  evidence harvest and acceptance   not started
10/10 closed-gate full-chain rehearsal   dry run and final freeze          not started
```

Item 8/10 is complete as of PR #45. The production AIMNet2 loader and the
production ASE/LBFGS optimizer are implemented; neither is a refusal stub.

```text
runner source schema        nhc-two-endpoint-runner-source-v8
runner_source_sha256        5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2
AIMNet2 runtime schema      nhc-phase9b-aimnet2-runtime-v2
trajectory schema           nhc-phase9b-aimnet2-trajectory-v1
production loader           A, source_proven from installed source in Phase 9A-S4
AseLBFGSOptimizer           implemented
execution gates             eleven, all false
real model or PySCF run     none
Phase 9B state              prepared_not_authorized
```

Item 7 also resolved a contract contradiction the plan had carried since Phase
9A. Route A was specified to start from the same frozen Phase 7 geometry as
Route D, yet its request and permit were built to declare the *preoptimized*
geometry -- a file that only exists after the route runs. The permit therefore
depended on its own execution. Under the single-transaction design both routes
bind the frozen initial structure, and the assisted permit binds the AIMNet2
*stage* instead: weight digest, optimizer protocol, structural gates, and handoff
contract. Both routes' identities are now concrete; neither is pending.

Item 6 closed the three gaps and two more found while closing them. The guarded
worker could not have run the assisted route at all: the capability identity
expectation carried a single attempt id pinned to the direct route, and the
pre-import handshake gate compared against Phase 8B's frozen attempt. Both are
now registries. Item 8 was added because Phase 9B has no analogue of
`phase8b_runtime`'s guardian mode, which is what consumes the permit and builds
the worker handshake; the supervisor CLI takes that handshake through an injected
factory and refuses when none is wired.

Items 6 and 7 both edited the runner source closure, so it has been re-frozen
twice:

```text
runner source schema   v4 -> v5 -> v6
runner_source_sha256   2059b35d...52c -> c914afe3...ea8 -> 72125b67...0de3
closure files          18 -> 21
request schema         nhc-two-endpoint-request-v2 (Phase 8B stays v1)
permit schema          nhc-phase9b-private-permit-v2
resources_sha256       0fec2c19...7df8 (unchanged throughout)
```

Every superseded generation is `superseded_before_execution` — never deployed,
never launched, never consumed, and not deleted. Both routes' final identities
are recorded in `docs/PHASE9B_IDENTITY_REBASELINE.md`.

The launch control plane now starts the **guardian**, never the supervisor. The
guardian consumes the permit irreversibly, builds the worker handshake, spawns
the supervisor into its own session with stdout and stderr redirected into the
frozen evidence tree, verifies the spawned identity, writes and re-reads its
receipts, and exits. The bounded SSH call therefore waits seconds for an
acknowledgement rather than hours for a computation.

No module has been run against a server: each takes an injected runner or spawn
seam and refuses a real invocation while its `EXECUTION_AUTHORIZED` is false.
There are **eleven** such gates and all eleven are false.

> **Handing this to another agent?** Start with
> `docs/HANDOFF_PHASE9B_FOR_NEXT_AGENT.md` — a cold-start briefing covering the
> frozen science, the authority model, what items 9 and 10 must be, why the real
> execution is blocked, and the traps this codebase has already surfaced.

## Next action

**Phase 9B scientific execution remains stopped, fail-closed, before any irreversible action.**

Phase 9B-U1 has completed as a fail-closed infrastructure attempt. Its v001
prefix and wheelhouse are retained failure evidence and may not be deleted,
repaired, retried or reused. The exact package installation passed, but the
capability harness observed four calculator invocations against a preregistered
expectation of two; portable native-map, endpoint and global-cache-after
evidence was therefore incomplete and the environment was not validated.

Phase 9B-U2 is complete with terminal status `rejected_environment`. Its
calculator-count, native, cache, weight, target, and endpoint evidence is
complete, but the formal protected snapshot comparison failed because Stage 0
omitted a top-level `state` field which Stage 4 added. The physical tree and
critical-package evidence matched; the preregistered canonical snapshot SHA did
not, and was not repaired or reinterpreted. The full outcome is
`docs/PHASE9B_UNIFIED_ENVIRONMENT_V002_BUILD_REPORT.md`.

The v002 prefix, wheelhouse, cache, logs, traces and receipts are retained and
may not be deleted, repaired, retried or reused. No validated unified
environment identity exists, so Unified Environment Identity Integration,
Postflight, and the closed-gate rehearsal may not begin.

Phase 9B-U3 was authorized as a new attempt with a qualified measurement
schema, not as a retry or repair of U2. Its document-first contract merged as
PR #52. The subsequent read-only six-object A/B qualification failed before
environment creation: every schema/projection equality was true, but the one
capture helper returned stable `state=invalid` observations rather than the
required `present`. The v003 prefix, wheelhouse, and cache remained absent
before and after; no artifact was downloaded and no build/import/capability
gate ran. U3 is terminal `failed_before_environment_creation` and may not be
fixed, rerun, or reused. The retained outcome is in
`docs/PHASE9B_UNIFIED_ENVIRONMENT_V003_BUILD_REPORT.md`.

No validated unified environment exists. Identity Integration, Postflight,
closed-gate rehearsal, and Phase 9B science remain blocked. All public
execution gates remain false.

Phase 9B-U4 is separately authorized as a new metrology implementation and new
identity. Code inspection confirms U3 rejected `bin/python` symlinks before all
probes and collapsed later failures into the same reason-free invalid sentinel;
the retained U3 public evidence cannot by itself distinguish those branches.
U4 adds root-contained symlink-chain authentication and explicit capture
diagnostics. Its document-first PR must merge before any SSH. Only one later
read-only Q4 qualification may determine whether new v004 resources can be
created.

The document-first contract merged as PR #54. The one read-only Q4 call then
failed all six A/B captures with the registered code
`CONDA_EXPLICIT_FAILED`; each pair was stable and root-contained but had
`state=invalid`, not `present`. The v004 prefix, wheelhouse, and cache remained
absent before and after. No build, artifact, import, native, capability, cache,
GPU, endpoint, or scientific gate ran. U4 is terminal
`failed_before_environment_creation` and cannot be repaired or rerun.

Phase 9B-U5 is a newly authorized helper/schema/qualification/attempt, not a
U4 repair. U4's exact CLI subfailure remains unresolved because its portable
receipt omitted command-level details; U5 does not guess it. Instead, protected
identity is derived directly from stable launcher/Python, `conda-meta`, all
`dist-info`, and tree bytes. The document-first PR must merge before any SSH.
Only one later no-write/no-CLI Q5 A/B qualification may unlock v005 creation.
All six must be present and exactly stable; failure is terminal and no U6 may be
created.

A one-shot execution authorization was granted and its section 11 pre-execution
audit failed: at that time there was no single interpreter on the compute host
that could run the assisted route. The audited pre-U1 MLFF and PySCF stacks
lived in disjoint conda environments.

The search covers the whole host, not just the project: environments were found
by their own `conda-meta` and `pyvenv.cfg` markers across `/home`, `/opt`,
`/usr/local`, `/srv` and `/mnt`, cross-checked against conda's own registry.
**14 environment roots, 27 interpreters, 11 registry entries — all probed.**

```text
pyscf  present in exactly 2 site-packages   (molecular, gpupyscf)
aimnet present in exactly 2 site-packages   (mlff, aimnet2)
intersection                                 empty
```

The nearest miss is the shared `molecular` environment: pyscf 2.13.1, geometric
1.1.1, pyscf-dispersion 1.5.0 and ase **3.28.0**, but no torch and no aimnet.

Every pre-U1 version was exactly the frozen one; nothing had drifted. U1 later
created a new prefix containing both package sets, but that prefix failed its
capability validation and is unusable. Route A still has no accepted interpreter.

Nothing was deployed, no permit was placed or consumed, and no Phase 9B route
process was started. U1 wrote only its isolated environment/wheelhouse/evidence
trees and ran its bounded compatibility smokes. Route D alone was deliberately
not run: a direct-only result is not a paired experiment.

The reasoning, the options, and the single safe next action are in
`docs/PHASE9B_EXECUTION_BLOCKED.md`; the evidence is in
`docs/PHASE9B_SERVER_WIDE_ENVIRONMENT_SEARCH.json`.

Items 9/10 — postflight and the closed-gate full-chain rehearsal — remain not
started and were explicitly forbidden in U1. They are not authorized next work.

## High-fidelity production labels

71. Unchanged. No Phase 9B smoke label exists, and none may enter the production
table without a separate data-contract acceptance.
