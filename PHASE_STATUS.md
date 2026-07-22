# Phase Status

Updated: 2026-07-23

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

## Current boundary

Phase 0–8A and the Phase 8B planning gate are complete and merged. The only
authorized Phase 8B QXH attempt was consumed and rejected at the execution
protocol layer. Its permit, attempt identity, bundle, and remote root are
permanently unusable. No acceptable DFT endpoint or label was produced, and
the source execution gate is false.

## Next action

Publish the rejected Phase 8B incident, future-code corrections, and closed-gate
verification to `main`, then stop. Any new calculation requires a separate
document-first plan, a new candidate/attempt/root/permit authority chain, and
new explicit user authorization. No model or dataset ingestion may occur from
this rejected attempt.
