# Phase 9B handoff — context for the next agent

This is a cold-start briefing. Read it, then read `AGENT.md` and
`PHASE_STATUS.md`, which remain the authoritative constraints. Everything below
is true as of merge commit on `main` after PR #47.

---

## 1. What this project is

`nhc-deprot-ranker` ranks NHC precursors by deprotonation electronic energy.
There are 401,856 candidates with a cheap xTB descriptor and **71** high-fidelity
DFT labels. Phase 4 decided `raw_xTB_wins`: B0 is the production ranking model.

**Phase 9B** is a single-candidate *paired smoke experiment*, not production
work. It asks one question:

> Does an AIMNet2 machine-learning preoptimization before PySCF make the DFT
> geometry optimization cheaper, without changing the answer?

Two routes run the same candidate from the **same frozen initial geometry**:

```text
Route D (direct)    initial geometry -> PySCF optimization -> final SCF
Route A (assisted)  initial geometry -> AIMNet2 preoptimization -> PySCF -> final SCF
```

Both use an identical PySCF envelope. The only experimental difference is the
AIMNet2 stage.

**Standing prior, do not lose it:** the legacy project measured a median
**1.10×** speedup for this exact route on the same hardware and chemistry
(n=12) and closed it as a dead end, because the starting geometry was never the
bottleneck. **Non-promotion is the likely and acceptable outcome.** Do not tune
anything to make the result look better.

---

## 2. Current state

Items 1–8 of 10 are complete and merged. Items 9 and 10 are **not started**.
The real execution is **blocked** (section 6 below).

```text
1/10  preparation/phase9b_preopt.py       AIMNet2 preoptimization contract  complete
2/10  preparation/phase9b_bundle.py       request and payload manifest      complete
3/10  preparation/phase9b_preflight.py    read-only environment recheck     complete
4/10  preparation/phase9b_deploy.py       directed two-route deployment     complete
5/10  preparation/phase9b_launch.py       two-route guardian launch         complete
6/10  pre-launch integration closure      CLI, adapter, permit stage        complete
7/10  quantum/phase9b_guardian.py         guardian, transport, handoff      complete
8/10  execution runtime closure           production loader + optimizer     complete
9/10  preparation/phase9b_postflight.py   evidence harvest and acceptance   NOT STARTED
10/10 closed-gate full-chain rehearsal    dry run and final freeze          NOT STARTED
```

Frozen identities as of now:

```text
runner source schema      nhc-two-endpoint-runner-source-v8
runner_source_sha256      5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2
closure files             23
AIMNet2 runtime schema    nhc-phase9b-aimnet2-runtime-v2
trajectory schema         nhc-phase9b-aimnet2-trajectory-v1
preoptimization receipt   nhc-phase9b-aimnet2-preoptimization-v2
resources_sha256          0fec2c1914f413a2762e1fafc7daa9900551981b5af72897746864edffac7df8
direct request            acc22c67ba07e245ae001211cfb34038eeb486c3a4fbccdefdf6991b35d66635
direct manifest           906b1f39982107218fec079150851b9d14a4d9a3e4d43bf401c2dec00ed3afa9
assisted request          b74cd3b7e433059ea5d5a9ae213917766a236f4a2c72ef97e3edc9fe6298bef1
assisted manifest         d23b12f9d7b31c6e6bd19665cf847e1f45ab6ec8825ff86a84e560fcf1f56081
state                     prepared_not_authorized
execution gates           eleven, ALL FALSE
tests                     1282 passing
production labels         71 (unchanged; no Phase 9B label exists)
```

Phase 9B-U1 was attempted after this framework freeze. A new v001 prefix was
offline-cloned from project MLFF and populated with the exact PySCF stack, but
the capability harness observed four calculator invocations against two
expected and failed before all portable validation evidence was committed. The
prefix and wheelhouse are retained as `failed_incomplete_environment`; they may
not be deleted, repaired, retried or reused. All four pre-existing environments
were proven byte-metadata unchanged. The v8 source identity above did not move,
all gates remain false, and Items 9/10 and 10/10 remain not started.

---

## 3. The frozen science — never change any of this

Candidate `LBNPGYISTSLAHY-UHFFFAOYSA-N`.

```text
cation      charge +1, multiplicity 1
neutral     charge  0, multiplicity 1
electrons   160 both endpoints
atom map    C2_carbene = 14,  N1 = 8,  N3 = 15
```

**The atom map is 14/8/15. Phase 8B's 3/4/5 belongs to a different molecule and
must never be used here.**

Read the digests from `phase9b_authority.PHASE9B_CANDIDATE`; do not retype them.

Method, identical on both routes:

```text
gas phase, B3LYP, D3(BJ), def2-SVP, grid level 3, geomeTRIC,
geometry_maxsteps 100, scf_conv_tol 1.0e-9,
no Hessian, no frequency, no ZPE, no thermal correction
```

Label:

```text
electronic_difference_kcal = (E_neutral_hartree - E_cation_hartree) * 627.509474
dft_deprot_electronic_kcal = electronic_difference_kcal - 6.28
lower_is_better = true
```

Recompute tolerance for a fresh runner is `abs_tol = 1e-12`. The `0.02 kcal/mol`
tolerance is **ingest-only** and must not be reused here.

**An AIMNet2 energy may never enter the label.** It may only reach the
optimizer, the trajectory, finiteness checks, the preoptimization receipt, and
performance diagnostics.

AIMNet2 is frozen to member `_0` of `aimnet2_wb97m_d3`, 8,836,941 bytes, sha256
`f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28`. Members
`_1`–`_3` do not exist locally and may not be downloaded, so ensemble
uncertainty is recorded as `unavailable_single_member` and never as a
repeatability figure.

---

## 4. The security model — the part that is easiest to break

This is not ceremony. Read `docs/PHASE9B_AUTHORITY_CHAIN.md` before touching any
of it.

**Fail-closed source gates.** There are eleven
`EXECUTION_AUTHORIZED: Final[bool] = False` constants in `src/`. They are read
by a function that takes no argument and reads no environment variable. Opening
one means editing source, which moves `runner_source_sha256` and invalidates
every prepared identity. That is deliberate.

- Never add `authorized=True`, `skip_gate=True`, or an env-var override.
- Never monkeypatch a gated function and then claim the production path is tested.

**One-shot permits.** A permit is consumed by an unrepeatable filesystem
transaction: `O_DIRECTORY|O_NOFOLLOW` dir_fd, `O_NOFOLLOW` on the ready file, a
dev/ino recheck, then `O_CREAT|O_EXCL|O_NOFOLLOW` as the linearization point.
**There is no rename** — check-then-rename is racy. A consumed permit is never
restored, never retried, never revived.

**Byte-closed handoff.** PySCF's input bytes must equal AIMNet2's output bytes,
proved by reading them back off disk. `pyscf_may_start()` is the only door into
PySCF and is reached only after a durable preoptimization receipt and a closed
handoff receipt exist for that endpoint.

**Route ordering.** Cation runs first. If any cation stage fails, neutral never
starts and no label is produced.

**Phase 8B is permanently unusable.** Its QXH candidate, request, attempt,
permit, bundle and remote root were consumed and rejected. Never revive them,
never reuse their identities, and keep the frozen Phase 8B artifact hashes
unchanged.

---

## 5. What Items 9 and 10 must be

### Item 9/10 — `preparation/phase9b_postflight.py`

A **read-only control plane** that decides whether a route is `accepted`,
`rejected`, `running`, or `indeterminate`. It should default to staying outside
the runner source closure; if it genuinely needs to change the closure or an
evidence schema, say so and re-baseline honestly rather than silently keeping
the v8 identity.

Two modes:

```text
observe_once        read current state; running is NOT a failure
wait_until_terminal bounded read-only wait; no kill, no spawn, no retry;
                    a dropped connection returns indeterminate
```

It must consume the whole chain — preflight receipt, deploy outcome and
verification, placement receipt, launch receipt, request, payload manifest,
consumed permit, runner source and resources digests, guardian receipts,
supervisor identity, worker registration, acknowledgement, compute claim,
process-supervisor terminal evidence, and the route's output tree — and check:

- **authority**: ready permit absent, consumed permit present and exact, all
  digests match, exactly one attempt, no Phase 8B artifact
- **process**: process group terminal, child reaped, no orphan descendant, no
  registered PID remains, no second process tree
- **file tree**: registered payload unchanged, only the allowed dynamic tree, no
  symlink, no extra result, bounded sizes, every retained file digested
- **direct route**: must have *no* AIMNet2 trajectory, cache, preoptimization
  receipt, handoff receipt, or ML import evidence
- **assisted route**: must have both endpoints' input/output XYZ, both
  trajectory v1 JSONL, both runtime v2 receipts, both handoff receipts, cache
  observation, weight identity, charge/mult evidence, structural gates, and
  `handoff source bytes == PySCF input bytes`
- **PySCF per endpoint**: optimization SCF converged, geometry converged, final
  SCF converged, finite energy, D3(BJ) hooks and breakdown, resource evidence,
  final XYZ, result digest
- **label**: only when both endpoints of a route are accepted; recompute at
  `1e-12`; prove no AIMNet2 energy entered it

Output at minimum: portable postflight JSON, per-route evidence manifests, a
paired comparison JSON, and a human-readable report. **Never write into the
production label table.**

### Item 10/10 — `preparation/phase9b_campaign.py`

A closed-gate orchestrator that only calls existing verified components. It must
not itself implement SSH, permit consumption, guardian, supervisor, worker,
AIMNet2, or PySCF.

```text
PLANNED -> LOCAL_VERIFIED -> PREFLIGHT_PASSED -> DEPLOYED -> PERMITS_PLACED
-> DIRECT_LAUNCHED -> DIRECT_TERMINAL -> ASSISTED_RESOURCE_RECHECKED
-> ASSISTED_LAUNCHED -> ASSISTED_TERMINAL -> POSTFLIGHT_COMPLETE
```

Failure terminals: `FAILED_BEFORE_IRREVERSIBLE_ACTION`,
`DIRECT_PERMIT_CONSUMED_FAILED`, `DIRECT_INDETERMINATE`, `ASSISTED_NOT_LAUNCHED`,
`ASSISTED_PERMIT_CONSUMED_FAILED`, `ASSISTED_INDETERMINATE`,
`POSTFLIGHT_REJECTED`.

**The campaign schedule is a contract, not an implementation detail.** It needs a
schema version, a canonical SHA256, a schedule receipt, and cross-validation from
launch and postflight:

```text
route_schedule                    sequential_nonoverlapping
route_order                       direct_then_assisted
same_cpu_affinity_reused          true
route_overlap                     forbidden
```

Both routes use CPU affinity `0-3`, so **running them concurrently would poison
the wall-time comparison**. The existing `launch_both_routes()` cannot express
this; add a `launch_route_once()` or an orchestrator rather than deleting the
existing fail-closed behaviour, and never call the guardian directly to bypass
launch validation.

Rehearse with mock SSH, the fake module stack, temp dirs and controlled
subprocesses: success/success, direct timeout then assisted success, direct
provenance failure blocking assisted, partial deploy, partial placement, launch
indeterminate on either route, postflight corruption, no route overlap, GPU
recheck, no retry, no resume, no permit restoration, no label on one endpoint.

---

## 6. Why the real execution is blocked

A one-shot execution authorization was granted and its pre-execution audit
failed. **No interpreter anywhere on the compute host can run the assisted
route.**

```text
pyscf  present in exactly 2 site-packages trees
aimnet present in exactly 2 site-packages trees
intersection                                     empty
```

Route A must run AIMNet2 and then PySCF **inside one guarded worker process**,
because that is what the byte-closed handoff and the assisted permit bind.

Phase 9B-U1 later produced a prefix containing both installed stacks, but that
prefix failed its capability validation and is not an accepted interpreter.
The current blocker is therefore `no_validated_single_interpreter`, not the
continued physical absence of both package trees from one prefix. See
`docs/PHASE9B_UNIFIED_ENVIRONMENT_BUILD_REPORT.md`.

The search covered the whole host, not just the project: environments were
located by their own `conda-meta` and `pyvenv.cfg` markers across `/home`,
`/opt`, `/usr/local`, `/srv` and `/mnt` to depth 9, cross-checked against
conda's own registry — 14 environment roots, 27 interpreters, 11 registry
entries, all probed. Full table and stated search limits are in
`docs/PHASE9B_SERVER_WIDE_ENVIRONMENT_SEARCH.json` and
`docs/PHASE9B_EXECUTION_BLOCKED.md`.

The nearest miss is a shared `molecular` environment carrying pyscf 2.13.1,
geometric 1.1.1, pyscf-dispersion 1.5.0 and **ase 3.28.0** — but no torch and no
aimnet, and its ASE is not the frozen 3.29.0.

**Nothing irreversible happened.** No deploy, no permit placed or consumed, no
remote root, no process. Route D alone was deliberately not run: a direct-only
result is not a paired experiment.

Resolving this is a **project-owner decision**, not an agent decision, because
every option changes the environment identity that Phase 9A-R through 9A-S4
established:

```text
1  build a new environment carrying both stacks   needs install authorization
2  add the PySCF stack to the project mlff env    needs install authorization
2b add torch+aimnet to `molecular`, upgrade its   needs install authorization;
   ase 3.28.0 to 3.29.0                           two additions and one upgrade
3  add the MLFF stack to gpupyscf                 needs install authorization
4  split Route A into two processes with a        no install, but a real change
   durable hash-closed geometry handoff           to the handoff contract and to
                                                  what the assisted permit binds
```

Option 4 needs no install but is a design round, not an execution round.

**Do not pick one of these yourself. Do not install anything. Do not combine two
environments on one `PYTHONPATH`. Do not run Route D alone and present it as a
paired experiment.**

---

## 7. Hard rules

Never:

- commit private absolute paths, server addresses, hostnames, account names,
  PIDs, credentials, permit contents, molecular coordinates, or local config to
  public Git — public files use `<REMOTE_PROJECT_ROOT>`, `<REMOTE_HOME>`,
  `<REMOTE_USER>`, `<MLFF_ENV_ROOT>`, `<AIMNET_CACHE_ROOT>` and similar
- use `git reset --hard`, `git checkout --`, force push, or history rewriting
- delete superseded identities or failure evidence — they are marked
  `superseded_before_execution` and preserved
- `source ~/.bashrc`, full-repo deploy, `rsync --delete`, remote overwrite or
  delete
- run quantum chemistry on the development machine
- install, upgrade, or download anything on the server
- retry, resume, or restore a consumed permit
- relax a gate, widen a resource, or change a threshold to make something pass

The legacy repo at the path in `configs/legacy.local.yaml` is **read-only**.

---

## 8. Verification

```bash
PYTHONPATH=src /usr/local/bin/python3.14 -m pytest        # 1282 passing
/usr/local/bin/python3.14 -m ruff check src tests
/usr/local/bin/python3.14 -m ruff format --check src tests
/usr/local/bin/python3.14 -m mypy src                     # clean baseline
```

**Use CPython 3.14 explicitly.** The repo `.venv` is 3.11.15 and lacks
`os.waitid(..., WNOWAIT)`, which produces 26 false failures.

### One unreproduced test failure, recorded rather than swept up

While preparing this handoff, **one** run out of twenty-four reported
`1 failed, 1281 passed`. It did not reproduce in the twenty-three runs that
followed, and its name was not captured because the loop printed only the
summary line. There is no `pytest-randomly` or `pytest-xdist` plugin installed,
so collection order is deterministic; the likely candidates are the
timing-sensitive process-supervisor, `waitid`, and one-shot-permit race tests.

It has **not** been skipped, xfailed, or deleted, and it should not be. When you
run the triple gate, capture the `FAILED` lines rather than just the summary:

```bash
for i in 1 2 3; do
  out=$(PYTHONPATH=src /usr/local/bin/python3.14 -m pytest 2>&1)
  echo "$out" | grep -E '^FAILED' ; echo "$out" | tail -1
done
```

If you catch it, the name plus the assertion is enough to fix it properly. Treat
a race in that area as a real defect in the guard, not as noise — the permit
consumption path is exactly where a rare interleaving matters most.

Every gate-closed PR must pass: pytest three times, targeted tests, mutation
tests, ruff lint, ruff format, compileall, mypy with no new errors,
`git diff --check`, a private-path/credential/hostname scan, an execution-gate
scan (eleven, all false), the frozen Phase 8B artifact hashes, and an
**independent** recomputation of the source closure — reimplement the digest
algorithm rather than calling the module.

---

## 9. Traps that have already cost time here

Each of these was a real defect found in this codebase. They recur.

**Naive substring assertions that match their own text.** `"rm" not in command`
matched inside the word "permit"; `"nohup" not in source` matched a docstring
that disclaimed using nohup. Scan **executable code with docstrings stripped**,
via AST, and look for real verbs (`os.remove`, `os.unlink`).

**Counting before deduplicating.** An interpreter scan counted *names* and saw
`python3.1` and `python3.11` as two interpreters; they are one binary. Collapse
by `(st_dev, st_ino)` **before** any count.

**Assuming a version string is observable.** `importlib.metadata.version("torch")`
returns `2.8.0`; the `+cu128` local segment only exists in `torch.__version__`.
A match criterion written against `2.8.0+cu128` silently matches nothing.

**Before/after snapshots over different key sets.** A cache invariance check
compared dicts whose keys differed once package roots became known, so the
`__pycache__` proof was vacuous. Same key set on both sides, always.

**A guard that never executes.** An `O_EXCL` was preceded by an existence check
that always fired first, so replacing `O_EXCL` with `O_TRUNC` changed nothing
observable. Test the linearization point by creating the conflict *inside* the
validation callback.

**Comparing the wrong tuple.** `_proton_hosts` returns `(hydrogen, host)` pairs;
comparing them against bare indices made the gate pass everything. mypy's
`comparison-overlap` caught it.

**Mutation testing is the standard here, not an extra.** Flip or delete each
guard, prove its own test fails, restore byte-identically, clear `__pycache__`,
re-run. In the last round 6 of 28 mutations survived the first pass and every
survivor was a genuine coverage gap.

---

## 10. Where the evidence is

```text
docs/PHASE9B_AUTHORITY_CHAIN.md                  the permit and identity model
docs/PHASE9B_IDENTITY_REBASELINE.md              v4..v8 generations, all preserved
docs/PHASE9B_EXECUTION_RUNTIME_CLOSURE.md        the production adapter, in detail
docs/PHASE9B_EXECUTION_REACHABILITY.md           what is reachable behind the gates
docs/PHASE9B_AIMNET2_SMOKE_PLAN.md               the frozen experiment
docs/PHASE9B_EXECUTION_BLOCKED.md                why execution stopped
docs/PHASE9B_SERVER_WIDE_ENVIRONMENT_SEARCH.json the environment evidence
docs/PHASE9A_S4_DEDUPLICATED_SOURCE_INSPECTION.md how the loader was proved
docs/PHASE9A_I_REPORT.md                         the six real inference calls
docs/AIMNET2_PROMOTION_GATES.md                  C1..C11, E1, E2
docs/AIMNET2_FAILURE_TAXONOMY.md                 failure codes
tests/fake_ml_stack.py                           strict fake torch/ase/aimnet
tests/test_phase9b_production_runtime.py         55 tests over the real adapter
```

`docs/PHASE9A_S4_DEDUPLICATED_SOURCE_INSPECTION.md` is worth reading in full
before touching the loader: it records, with line numbers, why an absolute local
path never reaches the registry or Hugging Face, why scheme B was rejected, and
why `.eval()` must **not** be added.
