# Phase 9B science pilot v006 report

## 1. Source state, candidate, and retained history

| Item | Value |
| --- | --- |
| branch | `agent/phase9b-science-pilot` |
| starting public commit | `cc8174a09a49883a4291aebb9c29cdf3eed6d3eb` |
| chemistry execution source head | `f8d54e4a2192bd361072bbb19f0e0a32299f4e4b` |
| final publication commit | the Git commit containing this report |
| Draft PR | #61 |
| starting worktree | clean |
| candidate | `LBNPGYISTSLAHY-UHFFFAOYSA-N` |
| benchmark type | one candidate, one run per route, paired, non-production |

The endpoint identities remained cation `+1`, multiplicity `1`, spin `0`, 26
atoms, 160 electrons and neutral `0`, multiplicity `1`, spin `0`, 25 atoms,
160 electrons. The frozen map remained `C2=14`, `N1=8`, `N3=15`, with cation
H23 bonded to C14. Both routes began from the exact cation SHA256
`543c6944...d286` and neutral SHA256 `af9c3064...f4b8` bytes.

Historical results were not changed: v001 remains `INCONCLUSIVE`; v002 remains
`FAIL under frozen 10-degree gate`; v004 remains the successful
AIMNet2-assisted single-point continuation; v005 remains the successful
frozen-initial single-point control.

## 2. Frozen route definitions

Route A was:

```text
frozen initial XYZ
-> AIMNet2/ASE LBFGS (fmax 0.05 eV/A, max 200)
-> exact-byte handoff
-> B3LYP-D3(BJ)/def2-SVP final single points
-> pilot-only electronic label
```

Route B was:

```text
same frozen initial XYZ
-> B3LYP-D3(BJ)/def2-SVP geomeTRIC optimization
-> final single point under the same protocol
-> pilot-only electronic label if both endpoints complete
```

The common PySCF projection was gas-phase RKS, grid level 3,
`conv_tol=1e-9`, `minao`, no `dm0`, standard max 100 cycles with the already
frozen typed-nonconvergence SOSCF policy, four threads on cores 0-3, and 12000
MB. Route B did not use AIMNet2 or a GPU. No parameter was relaxed after either
route began.

V005 is not the main acceleration baseline: it compared two fixed-geometry
single-point pairs. It found raw single points `187.717010 s` versus AIMNet2
optimization plus assisted single points `226.584248 s`. V006 instead includes
the high-level geometry optimization that Route B would actually need.

## 3. Code changes and production exclusions

V006 added the science-pilot-only timing orchestrator and its directed tests,
and added AIMNet2 model-load/total-wall fields to the pre-existing pilot
summary. After the authorized timeout, the same orchestrator gained a
`finalize-partial` command that performs no chemistry: it seals the completed
Route A, completed Route B cation, neutral partial trajectory, timeout status,
comparison lower bounds, and post-exit manifests. Its SHA256 is
`231ab710...edd`; the chemistry execution copy used SHA256
`06294c8b...a58`.

The partial finalizer also excludes `runtime_tmp` and its own final-manifest
file from the durable manifest while retaining checkpoint diagnostics. Directed
tests cover timing direction, timeout bounds, GNU-time status parsing,
geomeTRIC last-step extraction, and manifest self-exclusion.

No production runner file, v9 leaf, production shared core, guardian, permit,
campaign, Postflight, public gate, production 10-degree gate, or production
label table was modified.

## 4. Actual execution commands

The public projection below preserves the actual argv and resource controls;
only the already-private run and environment prefixes are replaced.

Route A was launched once by an argv-based controller:

```bash
/usr/bin/time -f %e -o <RUN_ROOT>/assisted/route_elapsed_seconds_authoritative \
  timeout --signal=TERM --kill-after=10s 7190s \
  taskset -c 0-3 \
  env -u PYTHONHOME -u PYTHONPATH -u PYTHONSTARTUP \
    PYTHONDONTWRITEBYTECODE=1 \
  <GPUPYSCF_ENV>/bin/python -I -B \
  <RUN_ROOT>/driver/execution_source/phase9b_science_pilot_timing_benchmark.py \
  assisted-controller \
  --root <RUN_ROOT>/assisted \
  --aimnet-root <RUN_ROOT>/assisted/aimnet_stage/science_pilot_lbn_v002 \
  --repo <RUN_ROOT>/driver/repo \
  --source-commit f8d54e4a2192bd361072bbb19f0e0a32299f4e4b \
  --mlff-python <MLFF_ENV>/bin/python \
  --gpupyscf-python <GPUPYSCF_ENV>/bin/python \
  --weight <LOCAL_WEIGHT>/aimnet2_wb97m_d3_0.pt \
  --gpu-index 1 \
  --gpu-uuid <SELECTED_V100_UUID>
```

An earlier outer-shell redirection failed before an interpreter, model, or
chemistry process started. It is retained as `failed_before_route_start`, is
not counted as a route attempt, and was not retried chemically.

After the pre-registered 60-second idle, Route B was launched once:

```bash
/usr/bin/time -f %e -o <RUN_ROOT>/pyscf_only/route_elapsed_seconds \
  timeout --signal=TERM --kill-after=10s 7190s \
  taskset -c 0-3 \
  env -u PYTHONHOME -u PYTHONPATH -u PYTHONSTARTUP \
    PYTHONDONTWRITEBYTECODE=1 \
  <GPUPYSCF_ENV>/bin/python -I -B \
  <RUN_ROOT>/driver/execution_source/phase9b_science_pilot_timing_benchmark.py \
  pyscf-worker \
  --route pyscf_only \
  --root <RUN_ROOT>/pyscf_only \
  --source-root <RUN_ROOT>/driver/repo/src \
  --pilot-helper <RUN_ROOT>/driver/repo/scripts/phase9b_science_pilot.py \
  --v004-helper <RUN_ROOT>/driver/repo/scripts/phase9b_science_pilot_pyscf_continuation.py \
  --cation-input <V002_ROOT>/input/cation_initial.xyz \
  --neutral-input <V002_ROOT>/input/neutral_initial.xyz
```

It ended once with GNU `timeout` status 124 and authoritative wall
`7190.06 s`. No extension, restart, fallback, or second attempt occurred. A
post-exit `finalize-partial` invocation wrote only immutable JSON/manifest and
copied the already-created neutral trajectory bytes into the durable subtree;
it did not import or run the chemistry stack.

## 5. Pre-registered order and system snapshots

The order was Route A, fixed 60-second idle, then Route B. Both snapshots have
the same hostname digest `3a9a2411...9ec6`, boot digest `2e67ba04...a4e0`, CPU
model Intel Xeon Platinum 8173M, interpreter hashes, and selected V100 identity
digest. The selected V100 had 5 MB reported occupancy before each route.

| Snapshot | Available memory | Load average (1/5/15 min) |
| --- | --- | --- |
| before Route A | 232262088 kB | 2.419 / 2.367 / 2.309 |
| before Route B | 232480480 kB | 3.139 / 3.886 / 3.088 |

These observations are reported, not used for post-hoc timing correction.

## 6. Route A results

### AIMNet2

| Endpoint | Steps | Calculator calls | Initial Fmax | Final Fmax | Wall s | Final XYZ SHA256 | Status |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| cation | 54 | 56 | 2.600473 | 0.045105 | 23.702986 | `ea796a5c...7774` | converged |
| neutral | 64 | 66 | 5.767974 | 0.044275 | 2.891521 | `c40ca77b...bc93` | numerically converged; admitted by unchanged v004 review |

The base model loaded once in `9.975236 s`; the complete AIMNet2 subprocess
wall was `36.703092 s`. This is allocated GPU wall, not measured GPU
utilization. Neutral still fails the unchanged production 10-degree gate; V006
does not reclassify v002 or change that gate.

### Assisted PySCF final single points

| Endpoint | Charge | Mult | Spin | SCF | Cycles | Wall s | Energy Eh | D3 Eh |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| cation | +1 | 1 | 0 | converged | 12 | 68.011475 | -1407.5280546795138 | -0.0501063213569 |
| neutral | 0 | 1 | 0 | converged | 12 | 123.874677 | -1407.1374187623978 | -0.0481222139352 |

The complete Route A authoritative wall was `235.90 s`; the internal PySCF
worker wall was `192.052879 s`, and the residual startup/handoff/parsing/evidence
overhead was `7.144029 s`. The assisted frozen-formula value is
`238.847738874978 kcal/mol`.

## 7. Route B results and timeout

| Endpoint | Geometry optimizer | Geometry steps | Geometry wall s | Final SCF cycles | Final SCF wall s | Endpoint wall s | Status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cation | geomeTRIC | 28 | 3777.975027 | 12 | 129.350269 | 3907.332003 | complete |
| neutral | geomeTRIC | last printed step 17 | unavailable (interrupted) | not run | not run | unavailable | timeout during optimization |

The completed cation energy is `-1407.531777257272 Eh`, with D3 contribution
`-0.0501756551964542 Eh`. It used 28 observed D3 energy and gradient hook calls.
Its process user/system CPU times were `14583.394720 s` and `284.412286 s`.
The backend does not durably expose cumulative optimization SCF cycles, so that
field is `unavailable`, not zero.

At the hard cutoff, neutral's last printed geomeTRIC observation was Step 17,
energy `-1407.1447765721 Eh`, gradient RMS/max
`6.766e-4 / 1.861e-3`. These values are an incomplete optimization observation,
not a final geometry, final single-point energy, or label. The raw stderr and
25,028-byte partial trajectory are retained. Neutral final single point was not
started.

## 8. Timing comparison

### Endpoint timing

| Endpoint | Route | Geometry wall s | Final SP wall s | Endpoint compute wall s | Complete |
| --- | --- | ---: | ---: | ---: | --- |
| cation | AIMNet2-assisted | 23.702986 | 68.011475 | 91.714461 | yes |
| cation | PySCF-only | 3777.975027 | 129.350269 | 3907.332003 | yes |
| neutral | AIMNet2-assisted | 2.891521 | 123.874677 | 126.766198 | yes |
| neutral | PySCF-only | incomplete | not run | unavailable | no |

The cation-only compute ratio is `3907.332003 / 91.714461 = 42.603227x`.
It excludes Route A's shared model load and route overhead; the primary route
bound below includes them.

### Main route result

| Metric | AIMNet2-assisted | PySCF-only | Difference / ratio |
| --- | ---: | ---: | --- |
| end-to-end total | 235.90 s | > 7190.06 s to complete | minimum saved 6954.16 s |
| percent time saved | n/a | incomplete | > 96.719082% |
| speedup (`PySCF-only / assisted`) | 1.0 reference | incomplete | > 30.479271x |

The inequalities are conservative lower bounds. An exact speedup, complete
neutral endpoint ratio, PySCF-only label, and label delta do not exist because
Route B did not complete.

## 9. PySCF compute burden

| Route | PySCF geometry steps | PySCF final SCF cycles | Cumulative optimization SCF cycles | PySCF wall | GPU wall allocation |
| --- | ---: | ---: | --- | --- | --- |
| assisted | 0 | 24 | not applicable | 192.052879 s | 36.703092 s AIMNet2 allocation |
| PySCF-only | cation 28; neutral last printed 17 | cation 12; neutral not run | unavailable | > 7190.06 s route observation | none |

The neutral last-step number is from structured geomeTRIC stderr and is not
misrepresented as a wrapper call count. Actual GPU utilization is unavailable.
No wall-time-times-thread estimate is reported as CPU time.

## 10. Energy, label, and geometry comparison

| Route | Cation final energy Eh | Neutral final energy Eh | Deprotonation value kcal/mol |
| --- | ---: | ---: | ---: |
| AIMNet2-assisted | -1407.5280546795138 | -1407.1374187623978 | 238.847738874978 |
| PySCF-only | -1407.531777257272 | unavailable | unavailable |

For cation, assisted minus PySCF-only is `+0.00372257775825 Eh`, or
`+2.33595281101 kcal/mol`. This does not establish accuracy or a global
minimum.

| Cation geometry metric | Result |
| --- | ---: |
| aligned RMSD | 0.250871 A |
| maximum displacement | 0.582139 A (atom 18) |
| connectivity | equal |
| C2-N1, assisted / PySCF-only | 1.332122 / 1.340984 A |
| C2-N3, assisted / PySCF-only | 1.325191 / 1.334715 A |
| N1-C2-N3, assisted / PySCF-only | 108.929358 / 108.968774 deg |
| ring RMS out-of-plane, assisted / PySCF-only | 0.004727 / 0.003287 A |

Atoms were not rematched. Neutral final geometry comparison is unavailable.

The only calculated label uses
`((E_neutral - E_cation) * 627.509474) - 6.28`; AIMNet2 energies do not enter.
It is a frozen-protocol gas-phase electronic value, not Gibbs free energy, pKa,
solution acidity, experimental deprotonation enthalpy, or production acceptance.

## 11. Checkpoints, manifests, and evidence

Runtime temporary files were observed and retained diagnostically after the
forced timeout, but `runtime_tmp` is excluded from the durable final manifest.
The neutral partial trajectory was copied byte-for-byte into the durable
optimization subtree and hash-verified. Route manifests and the top-level
manifest were built after process exit. Recomputing the top-level manifest after
writing it produced identical content:

```text
full_manifest_post_exit_stable = true
evidence grade = non-production
```

| Evidence | SHA256 |
| --- | --- |
| benchmark config | `1290d6cc...3208` |
| before-assisted snapshot | `ffd90a9a...bf38` |
| before-PySCF-only snapshot | `a3a7ef83...0749` |
| assisted result | `f192ea3c...052f` |
| PySCF-only partial result | `623b47cb...ee1` |
| cation endpoint result | `1e9c94e2...0b06` |
| neutral stderr | `4109a65f...e23` |
| neutral partial trajectory | `d3198840...c32` |
| timing comparison | `81d888c2...762f` |
| geometry comparison | `c6601f43...c6f6` |
| private terminal | `4426e111...98bb` |
| private final manifest | `1178c123...58a` |

The ignored local mirror is
`results/science_pilot_lbn_timing_v006/`. The private remote root and absolute
environment paths are intentionally omitted from public Git.

## 12. Quality gates

- 44 directed science-pilot tests passed;
- the full portable suite passed: 1,534 passed and two retained platform skips
  out of 1,536 collected tests;
- Ruff lint and format, compileall, JSON validation, `git diff --check`, and the
  package sdist/wheel build passed;
- strict mypy passed for the modified orchestrator. The repository-wide strict
  run retains one pre-existing error in `phase8b_remote_preflight.py`; V006
  introduced no mypy error;
- independent manifest audit verified 557/557 durable files, no mismatches,
  extras, missing files, or symlinks;
- the v9 and paired-generation files were unchanged; the paired generation
  still records zero open public gates, no real permit, zero new labels, and 71
  production labels.

## 13. Retained production state and conclusion

- AIMNet2 ran only for Route A; there was no second candidate or batch.
- No production permit was generated or consumed.
- No production campaign, Postflight, or runner was invoked.
- The production runner and v9 identities remain unchanged.
- All 11 public execution gates remain false.
- No production label was inserted; the production count remains 71.

Final classification:

```text
PARTIAL_PASS — PySCF-only路线未在冻结预算内完成，
已获得AIMNet2-assisted相对时间优势的保守下界
```

This single-candidate, single-run benchmark is not statistically significant
and is not generalized to a screening campaign.

The only next step is to inspect the PySCF-only route's last completed step and
accumulated compute burden, then decide whether a separately authorized budget
extension for this same candidate is worthwhile. This run did not extend or
restart it.
