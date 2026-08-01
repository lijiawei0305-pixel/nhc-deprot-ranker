# Phase 9B science pilot v004 report

## 1. Starting state

| Item | Value |
| --- | --- |
| starting branch | `agent/phase9b-science-pilot` |
| starting public commit | `d12e96e31fae2338cb204f94264c80571f386364` |
| execution source commit | `e2bc8413aa929a343b9ca6ed7d29792828a1d67c` |
| Draft PR | #61 |
| candidate | `LBNPGYISTSLAHY-UHFFFAOYSA-N` |
| v001 result | `INCONCLUSIVE`, SHA256 `769e64a2...1915` |
| v002 result | `FAIL under frozen 10-degree gate`, SHA256 `b1362a3b...d7071` |
| retained AIMNet2 | aimnet 0.2.0; `aimnet2_wb97m_d3_0.pt`; SHA256 `f0f7c054...24e28`; not rerun |
| execution environment | Python 3.11.15, PySCF 2.13.1, geomeTRIC 1.1.1, pyscf-dispersion 1.5.0 |

The worktree was clean before v004 edits. No production runner or v9 source file
was modified.

The retained v002 AIMNet2 endpoints were already converged: cation used 54 steps
with final Fmax `0.045105 eV/Å`; neutral used 64 steps with final Fmax
`0.044275 eV/Å`. v004 did not invoke AIMNet2.

## 2. Corrected Stage A adjudication

The sole review bug was convention handling. A signed planar torsion may be near
0 or plus/minus 180 degrees. v004 keeps the raw value and uses distance to the
set `{0, +/-180}`. The existing 30-degree review heuristic was not changed.

| Metric | Initial | Final | Delta/observation | Criterion | Outcome |
| --- | ---: | ---: | ---: | --- | --- |
| aligned RMSD | — | 0.604592 Å | — | <=1.0 Å | pass |
| max displacement | — | 1.170238 Å | F13 | <=2.5 Å | pass |
| connectivity | 25 bonds | 25 bonds | +0 / -0 | exact | pass |
| shortest pair | 1.096000 Å | 1.081625 Å | -0.014375 Å | >=0.20 Å | pass |
| C2-N1 | 1.454191 Å | 1.362710 Å | -0.091481 Å | frozen bond gate | pass |
| C2-N3 | 1.452501 Å | 1.355208 Å | -0.097293 Å | frozen bond gate | pass |
| N1-C2-N3 | 114.828608° | 102.462533° | -12.366075° | production <=10° | fail, unchanged |
| ring RMS out-of-plane | 0.020469 Å | 0.003564 Å | more planar | diagnostic | pass |
| max out-of-plane | 0.028964 Å | 0.004896 Å | more planar | diagnostic | pass |
| C2 plane height | 0.070760 Å | 0.012483 Å | closer to plane | diagnostic | pass |
| max corrected planarity deviation | 5.088289° | 0.933197° | more planar | <=30° | pass |
| largest ring/side-chain torsion change | — | 44.330364° | no flip | <120° | pass |

All five ring angles and bonds are in the corrected review artifact. Atom count,
element order, atom order, connectivity, one-component status, collision checks,
ring identity, C2 continuity, and cation-minus-H23 mapping pass.

```text
Stage A = SAME_BASIN_LIKELY
```

This supports preserved topology and continuous local relaxation; it is not a
mathematical proof of a single potential-energy basin.

## 3. The 10-degree gate

The 10-degree gate first appeared in commit `dfcc14d4...ebde` in
`phase9b_preopt.py`. It is a mutation-frozen conservative engineering heuristic,
not a literature- or candidate-validated physical basin boundary. v004 did not
change it, and v002 remains failed under it.

## 4. Code and tests

Implementation/source changes were confined to science-pilot files:

- `phase9b_science_pilot_geometry_review.py`: corrected signed-torsion distance;
- `test_phase9b_science_pilot_geometry_review.py`: planar 0/plus-minus-180,
  boundary, reversal, puckering, and read-only regressions;
- `phase9b_science_pilot_pyscf_continuation.py`: isolated one-shot, exact-byte,
  final-SCF-only continuation;
- `test_phase9b_science_pilot_pyscf_continuation.py`: identity, handoff, spin,
  formula, fallback, initial-guess, failure, and no-optimizer tests.

Targeted tests passed (`33 passed`), the portable full suite passed with the two
existing platform skips, Ruff passed, strict mypy passed, and compileall passed.

No production runner, v9 leaf, guardian, permit, campaign, Postflight, Phase 8B,
public gate, or production-label file changed. `AGENT.md` and `PHASE_STATUS.md`
were updated only to record the pilot result and current next-action boundary.

## 5. Actual execution commands

The public report redacts only the private project prefix. The executed Stage A
command was:

```bash
python -I -B scripts/phase9b_science_pilot_geometry_review.py \
  --pilot-root results/science_pilot_lbn_v002
```

The remote driver was run once, in the foreground, through the exact environment
launcher:

```bash
env -u PYTHONHOME -u PYTHONPATH -u PYTHONSTARTUP \
  PYTHONDONTWRITEBYTECODE=1 \
  timeout --signal=TERM --kill-after=10s 7190s \
  taskset -c 0-3 <GPUPYSCF_ENV>/bin/python -I -B \
  <V004_ROOT>/driver/scripts/phase9b_science_pilot_pyscf_continuation.py \
  --root <V004_ROOT> \
  --v002-root <RUNS_ROOT>/science_pilot_lbn_v002 \
  --source-root <V004_ROOT>/driver/src \
  --source-commit e2bc8413aa929a343b9ca6ed7d29792828a1d67c \
  --continuation-source-sha256 40029ba06bdf7109ab96ea1172c39af1445d1f7ca655dddefabe707bc1c69a73 \
  --expected-executable-sha256 24a07a0a383fd666309acf92ad4e913dd372b3f2d4592d60f1f2f0ca7138fc61
```

There was one v004 root creation and one driver invocation. No calculation retry
or alternate environment was used.

## 6. Exact-byte handoff

| Endpoint | Source SHA256 | Bytes | Parser SHA256 | Charge | Multiplicity | Spin | Status |
| --- | --- | ---: | --- | ---: | ---: | ---: | --- |
| cation | `ea796a5c...7774` | 1181 | `ea796a5c...7774` | +1 | 1 | 0 | PASS |
| neutral | `c40ca77b...bc93` | 1133 | `c40ca77b...bc93` | 0 | 1 | 0 | PASS |

For both endpoints, retained v002 source bytes, v004 evidence copy, and bytes
passed to the XYZ parser are exactly equal. No coordinate object was serialized
back to XYZ, and v002 source link counts remain one.

## 7. PySCF single-point results

The continuation used the frozen production backend's final-SCF slice only:
gas-phase RKS B3LYP-D3(BJ)/def2-SVP, grid 3, tolerance `1e-9`, four threads,
12000 MB, standard max 100 cycles, with the existing typed-only one-time SOSCF
fallback available. It did not call geomeTRIC or any geometry optimizer.

| Endpoint | Charge | Mult | Spin | SCF | Cycles | Strategy | Energy (Eh) | D3 (Eh) | Wall | Status |
| --- | ---: | ---: | ---: | --- | ---: | --- | ---: | ---: | ---: | --- |
| cation | +1 | 1 | 0 | converged | 12 | standard | -1407.5280546795084 | -0.0501063213569 | 76.150 s | PASS |
| neutral | 0 | 1 | 0 | converged | 12 | standard | -1407.1374187623970 | -0.0481222139352 | 123.846 s | PASS |

Both used the observed, unmodified PySCF `minao` initial guess with no `dm0`.
Each D3 hook executed once; the five-component SCF total reconstructed exactly,
and an independent `B3LYP/d3bj/atm=false/grad=true` audit matched with zero
absolute energy error and finite `(26,3)` / `(25,3)` gradients. Raw endpoint
stdout and stderr were durably saved; all four were empty because `verbose=0`
and no warning occurred.

## 8. Deprotonation electronic energy

```text
E_cation  = -1407.5280546795084 Eh
E_neutral = -1407.1374187623970 Eh
Delta E   = 0.3906359171114673 Eh

electronic_difference_kcal
  = Delta E * 627.509474
  = 245.1277388721244 kcal/mol

dft_deprot_electronic_kcal
  = electronic_difference_kcal - 6.28
  = 238.8477388721244 kcal/mol
```

The subtracted correction magnitude is `6.28 kcal/mol`, equivalent to the frozen
gas-proton constant `-6.28 kcal/mol`. `lower_is_better=true`. AIMNet2 energy was
not used. This is a gas-phase
electronic-energy science-pilot value under the frozen formula; it is not Gibbs
free energy, pKa, solution acidity, or experimental deprotonation enthalpy. It
also omits the production protocol's residual PySCF geometry optimization, so it
is not a production high-fidelity label.

## 9. Evidence and post-exit audit

| Evidence | SHA256 |
| --- | --- |
| corrected Stage A result | `f8f5cd80...f86e` |
| geometry review binding | `59194071...350e` |
| cation handoff | `40d14b1e...112` |
| neutral handoff | `c228fa88...915` |
| cation endpoint result | `1e881fbf...eb0` |
| neutral endpoint result | `8e17664f...880` |
| private terminal result | `dbb0a66f...621c` |
| private file manifest | `0df46f78...7c8f` |

The private local mirror paths and identities are:

| Path | SHA256 |
| --- | --- |
| `results/science_pilot_lbn_v002/review_v004/review_result.json` | `f8f5cd80...f86e` |
| `results/science_pilot_lbn_pyscf_v004/input/cation_aimnet2_final.xyz` | `ea796a5c...7774` |
| `results/science_pilot_lbn_pyscf_v004/input/neutral_aimnet2_final.xyz` | `c40ca77b...bc93` |
| `results/science_pilot_lbn_pyscf_v004/handoff/cation_handoff.json` | `40d14b1e...112` |
| `results/science_pilot_lbn_pyscf_v004/handoff/neutral_handoff.json` | `c228fa88...915` |
| `results/science_pilot_lbn_pyscf_v004/pyscf/cation/stdout` | `e3b0c442...b855` |
| `results/science_pilot_lbn_pyscf_v004/pyscf/cation/stderr` | `e3b0c442...b855` |
| `results/science_pilot_lbn_pyscf_v004/pyscf/cation/endpoint_result.json` | `1e881fbf...eb0` |
| `results/science_pilot_lbn_pyscf_v004/pyscf/neutral/stdout` | `e3b0c442...b855` |
| `results/science_pilot_lbn_pyscf_v004/pyscf/neutral/stderr` | `e3b0c442...b855` |
| `results/science_pilot_lbn_pyscf_v004/pyscf/neutral/endpoint_result.json` | `8e17664f...880` |
| `results/science_pilot_lbn_pyscf_v004/result.json` | `dbb0a66f...621c` |
| `results/science_pilot_lbn_pyscf_v004/file_manifest.json` | `0df46f78...7c8f` |

All required input, handoff, run-config, stdout, stderr, endpoint-result, review,
and terminal files are present and independently hash-verified. A post-exit
audit found that the manifest had observed two PySCF auto-generated temporary
checkpoint files before interpreter shutdown; PySCF removed them at exit. The
other 18 declared files match. This is a pilot manifest timing/scope defect: the
manifest incorrectly included normal ephemeral checkpoints before exit. Their
bytes cannot be independently reread after exit. Required science evidence is
complete, but full manifest closure is incomplete; the original manifest must
not be represented as a stable exact post-exit tree.

## 10. Historical and production state

- v001 is unchanged and remains `INCONCLUSIVE`;
- v002 frozen result/input/final XYZ bytes and terminal are unchanged; additive
  review evidence does not reclassify its `FAIL under frozen 10-degree gate`;
- the production 10-degree gate is unchanged;
- AIMNet2 was not rerun;
- production runner v9 is unchanged;
- all 11 public execution gates remain false;
- no production permit/campaign was used;
- no production label was inserted; the production count remains 71.

## 11. Final conclusion

```text
PASS — AIMNet2 → PySCF 最小科学链路已真实跑通
```

This proves feasibility for one candidate and two endpoint single points. It
does not prove batch stability, production acceptance, or a geometry-optimization
speedup. It is non-production and final-SCF-only; the full post-exit manifest is
not stable for the two disclosed ephemeral checkpoint entries.

The only next step is one cation/neutral PySCF single-point comparison on this
same candidate's original frozen geometries, limited to SCF convergence, cycles,
and wall time. It requires separate authorization; no second candidate or batch
is allowed.
