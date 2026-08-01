# Phase 9B science pilot v005 report

## 1. Starting and final source state

| Item | Value |
| --- | --- |
| branch | `agent/phase9b-science-pilot` |
| starting public commit | `07ed918ba8c8f410b91afb2cca8299086bac3573` |
| execution-source and pre-publication head | `9b21236708b6f755335fcd2b11aec69adbf7e3eb` |
| final publication commit | the Git commit containing this report |
| Draft PR | #61 |
| starting worktree | clean |
| candidate | `LBNPGYISTSLAHY-UHFFFAOYSA-N` |
| retained v001 | `INCONCLUSIVE`; private result SHA256 `769e64a20f5035866e2b17895746440c79c06d8b1758a46dff8540cbe5281915` |
| retained v002 | `FAIL under frozen 10-degree gate`; private result SHA256 `b1362a3b1df7ef7ba276bac0c91fd8002fd27123eca37d84a82b937edacd7071` |
| retained v004 | `PASS`, `science_pilot_only`; private result SHA256 `dbb0a66fa937e97a19c947d69d409db9323702ba58666865482db80a76c0621c` |

The two private result roots are ignored evidence, not Git content. The
executable source was frozen at `9b212367...e3eb` before the sole remote driver
invocation; subsequent publication does not change those executed bytes.

## 2. Candidate and endpoint identity

| Endpoint | Charge | Multiplicity | PySCF spin | Atoms | Electrons |
| --- | ---: | ---: | ---: | ---: | ---: |
| cation | +1 | 1 | 0 | 26 | 160 |
| neutral | 0 | 1 | 0 | 25 | 160 |

The atom map remains `C2=14`, `N1=8`, `N3=15`; cation H23 remains attached to
C14 in the frozen input identity. No atom was added, removed, reordered, or
reformatted.

## 3. V004 assisted-result binding

V005 independently read the retained V004 private bytes rather than copying
numbers from a report:

| Evidence | Bytes | SHA256 |
| --- | ---: | --- |
| assisted terminal | 1971 | `dbb0a66fa937e97a19c947d69d409db9323702ba58666865482db80a76c0621c` |
| cation endpoint result | 7024 | `1e881fbf50bc963ab3d23c1fa6942c5ea16d6f63eae9aed5f37b745bd43f1eb0` |
| neutral endpoint result | 7026 | `8e17664f5cadae807ac4f6bba672112f8c5fcaa014e28b98ce3b6cbe00060880` |
| cation run config | 1002 | `fede60870a337253d8a093a8917279dacd967edb361447b5f1b099467e0af729` |
| neutral run config | 1003 | `c6b848e82c94ce8f580961e24461fb2628977da1fa9a18bef2e2bc5bebdbb5de` |

The retained terminal says `PASS`, `science_pilot_only=true`, and
`production_accepted=false`. Endpoint identities, protocol projections,
energies, cycles, wall times, and the `238.8477388721244 kcal/mol` assisted
value all matched.

## 4. Actual code changes

Only these science-pilot files were added after the V004 publication commit:

- `scripts/phase9b_science_pilot_direct_comparison.py`, SHA256
  `9996444612a185e6b1fb5bce5b9ec628a98b0d8d0c79b700191d41e02fed0dd7`;
- `tests/test_phase9b_science_pilot_direct_comparison.py`, SHA256
  `a7db0e7090d15c3caf10d5022696ffb94aa55ed48981fcb6b33cf02209300078`.

The direct wrapper loads the exact V004 single-point engine SHA
`40029ba06bdf7109ab96ea1172c39af1445d1f7ca655dddefabe707bc1c69a73`
and calls its observed backend, `run_single_point`, initial-guess validator,
and frozen deprotonation formula. It does not implement a second RKS/D3/SCF
algorithm. Directed tests passed.

## 5. Production code not changed

The diff from `07ed918...` through the executed source commit contains only the
two science-pilot files above. It does not modify the production runner, any v9
leaf, production shared core, guardian, permit, campaign, Postflight, Phase 8B,
the production 10-degree gate, the public execution gates, or the production
label table.

## 6. Actual server command

The following is the actual foreground driver invocation with only the private
runs root and Conda environment prefix replaced by public placeholders:

```bash
env -u PYTHONHOME -u PYTHONPATH -u PYTHONSTARTUP \
  PYTHONDONTWRITEBYTECODE=1 \
  CUDA_VISIBLE_DEVICES= \
  timeout --signal=TERM --kill-after=10s 7190s \
  taskset -c 0-3 <GPUPYSCF_ENV>/bin/python -I -B \
  <RUNS_ROOT>/science_pilot_lbn_direct_sp_v005/driver/scripts/phase9b_science_pilot_direct_comparison.py \
  --root <RUNS_ROOT>/science_pilot_lbn_direct_sp_v005 \
  --v002-root <RUNS_ROOT>/science_pilot_lbn_v002 \
  --v004-root <RUNS_ROOT>/science_pilot_lbn_pyscf_v004 \
  --source-root <RUNS_ROOT>/science_pilot_lbn_direct_sp_v005/driver/src \
  --source-commit 9b21236708b6f755335fcd2b11aec69adbf7e3eb \
  --direct-source-sha256 9996444612a185e6b1fb5bce5b9ec628a98b0d8d0c79b700191d41e02fed0dd7 \
  --expected-executable-sha256 24a07a0a383fd666309acf92ad4e913dd372b3f2d4592d60f1f2f0ca7138fc61
```

The new root had first passed `test ! -e`. There was one root, one driver
invocation, no retry, and no v006 attempt. The internal deadline was 7170
seconds inside the 7190-second TERM limit and 10-second kill grace.

## 7. Exact-byte direct handoff

| Endpoint | Source SHA256 | Source bytes | PySCF input SHA256 | Parser SHA256 | Atom order | Charge | Mult | Spin | Status |
| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: | --- |
| cation | `543c6944...d286` | 1075 | `543c6944...d286` | `543c6944...d286` | preserved | +1 | 1 | 0 | PASS |
| neutral | `af9c3064...f4b8` | 1036 | `af9c3064...f4b8` | `af9c3064...f4b8` | preserved | 0 | 1 | 0 | PASS |

Every source, evidence copy, PySCF input, and parser byte sequence is equal.
All are regular, non-symlink, single-link files. Atom-order SHA256 values are
`eb7439be...3f4a` and `8a81d92d...5380` respectively.

## 8. Direct PySCF endpoint results

Both endpoints used the same gas-phase RKS B3LYP-D3(BJ)/def2-SVP final-SCF-only
slice as V004: grid 3, `conv_tol=1e-9`, four threads, 12000 MB, observed PySCF
`minao` initial guess, no `dm0`, standard max 100 cycles, and only the frozen
typed-nonconvergence SOSCF fallback up to 200 cycles. Neither endpoint required
SOSCF.

| Endpoint | Geometry provenance | Charge | Mult | Spin | SCF | Cycles | Wall (s) | Energy (Eh) | D3 (Eh) |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| cation | frozen initial | +1 | 1 | 0 | converged | 12 | 67.530844 | -1407.5048562130542 | -0.04847829087188403 |
| neutral | frozen initial | 0 | 1 | 0 | converged | 12 | 120.186166 | -1407.0717319613400 | -0.04803336143861741 |

The five-term energy reconstruction and independent D3 energy audit each had
zero absolute error. Audit gradients were finite with shapes `(26,3)` and
`(25,3)`. Directly measured process CPU deltas were cation
`242.676597 s` user / `9.215023 s` system and neutral `452.085092 s` user /
`7.115072 s` system. Raw stdout and stderr were saved; all four are empty under
the frozen `verbose=0` path.

## 9. Direct deprotonation electronic energy

```text
E_cation_direct  = -1407.5048562130542 Eh
E_neutral_direct = -1407.0717319613400 Eh
Delta E_direct   = 0.4331242517141618 Eh

direct electronic difference
  = Delta E_direct * 627.509474
  = 271.7895713697973 kcal/mol

direct dft_deprot_electronic
  = 271.7895713697973 - 6.28
  = 265.5095713697973 kcal/mol
```

This is a gas-phase electronic-energy difference on the original frozen
geometries. AIMNet2 energy is not an input. It is not a geometry-optimized
production label, Gibbs free energy, pKa, solution acidity, or experimental
acidity.

## 10. Assisted endpoint and label reference

| Endpoint | Geometry provenance | Charge | Mult | Spin | SCF | Cycles | Wall (s) | Energy (Eh) | D3 (Eh) |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| cation | AIMNet2 preoptimized | +1 | 1 | 0 | converged | 12 | 76.150117 | -1407.5280546795084 | -0.05010632135688259 |
| neutral | AIMNet2 preoptimized | 0 | 1 | 0 | converged | 12 | 123.846131 | -1407.1374187623970 | -0.04812221393523744 |

The retained assisted deprotonation value is
`238.8477388721244 kcal/mol`. V005 did not rerun either assisted endpoint.

## 11. Signed endpoint energy differences

The registered direction is `assisted - direct`:

| Endpoint | Direct energy (Eh) | Assisted energy (Eh) | Shift (Eh) | Shift (kcal/mol) |
| --- | ---: | ---: | ---: | ---: |
| cation | -1407.5048562130542 | -1407.5280546795084 | -0.023198466454232403 | -14.557257482302019 |
| neutral | -1407.0717319613400 | -1407.1374187623970 | -0.06568680105692692 | -41.219089979974854 |

Both assisted-input single-point energies are lower numerically, but this does
not establish greater accuracy, a global minimum, or an optimization energy.

## 12. SCF-cycle comparison

| Endpoint | Direct cycles | Assisted cycles | Assisted - direct |
| --- | ---: | ---: | ---: |
| cation | 12 | 12 | 0 |
| neutral | 12 | 12 | 0 |

For this candidate and fixed single-point protocol, preoptimization did not
change the observed cycle count.

## 13. Wall-time comparison

| Endpoint | Direct wall (s) | Assisted wall (s) | Assisted - direct (s) |
| --- | ---: | ---: | ---: |
| cation | 67.530844 | 76.150117 | +8.619272 |
| neutral | 120.186166 | 123.846131 | +3.659965 |

These are endpoint SCF wall observations, not end-to-end AIMNet2 costs.

## 14. Wall ratios

The defined ratio is `direct wall / assisted wall`:

| Endpoint | Ratio |
| --- | ---: |
| cation | 0.886812092964848 |
| neutral | 0.9704474841978368 |

The direct single points happened to be faster in wall time while taking the
same number of SCF cycles. This one-run observation cannot be generalized to
batch behavior and is not a PySCF geometry-optimization speedup.

## 15. Signed label difference

| Direct label (kcal/mol) | Assisted label (kcal/mol) | Assisted - direct (kcal/mol) |
| ---: | ---: | ---: |
| 265.5095713697973 | 238.8477388721244 | -26.66183249767289 |

The sign is retained: the assisted-input electronic deprotonation value is
`26.66183249767289 kcal/mol` lower than the direct frozen-input value under the
same formula.

## 16. Geometry-change context

| Endpoint | Aligned RMSD (Å) | Max displacement (Å) | C2-N1 change (Å) | C2-N3 change (Å) | N1-C2-N3 change | Connectivity |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| cation | 0.221190 | 0.482299, F5 | -0.008796 | -0.014209 | +1.473158° | unchanged |
| neutral | 0.604592 | 1.170238, F13 | -0.091481 | -0.097293 | -12.366075° | unchanged |

The cation passed the retained v002 frozen structural gates. The corrected
neutral review remains `SAME_BASIN_LIKELY`, while v002 itself remains failed
under the unchanged production 10-degree gate. The energy shifts are associated
with different input geometries, but two fixed-geometry single points cannot
identify a global minimum.

## 17. Checkpoints and manifest stability

PySCF created two normal temporary checkpoints. The driver recorded their
name digests and byte identities under `driver/runtime_tmp`, marked them
ephemeral, and excluded all `driver/` paths from the durable manifest. Both
checkpoints disappeared after interpreter exit as expected.

The independent read-only post-exit audit verified all 19 declared durable
files by existence, type, byte count, SHA256, mode, and link count; it found
zero mismatches and zero remaining checkpoint files. The terminal was written
last and binds the preterminal durable manifest SHA256
`6ca07832dbab16baed2dd6751ed39edf3e3490fd11df78cf05347701002f6b92`.

```text
full_manifest_post_exit_stable = true
evidence_grade = non-production science pilot
```

Manifest stability does not promote this result into production evidence.

## 18. Evidence paths and SHA256

Private mirror root: `results/science_pilot_lbn_direct_sp_v005/`.

| Relative path | SHA256 |
| --- | --- |
| `input/cation_initial.xyz` | `543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286` |
| `input/neutral_initial.xyz` | `af9c30640801eec3ab27538a33204186849303dd57592ca5c93320ec1390f4b8` |
| `input/input_manifest.json` | `26d5591a3ae54a83d534b9817a46ededeaa05dcc435e05176e1ba8a9425306f4` |
| `handoff/cation_handoff.json` | `af668ec8819f6da5ba6db4997ae36c7aab8b6d42973ab459d5cd5d92fe01b46b` |
| `handoff/neutral_handoff.json` | `1228a7adb0cca12e7282172e9f7f6a747ab75dd3e4c21a667edbe41b1cbd9830` |
| `pyscf/cation/input.xyz` | `543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286` |
| `pyscf/cation/run_config.json` | `87898dd9771bfb2cd820560093f6891422f642e6e54539d1cd2c2f34da72d7cc` |
| `pyscf/cation/stdout` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `pyscf/cation/stderr` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `pyscf/cation/endpoint_result.json` | `a0110b20495cfbc8408642a561adf4bd736849603920689d16da674b9600ff2d` |
| `pyscf/neutral/input.xyz` | `af9c30640801eec3ab27538a33204186849303dd57592ca5c93320ec1390f4b8` |
| `pyscf/neutral/run_config.json` | `977958bef5c755e0b3c591c2bd3955cc804a1968fd1064e2aa9efbc4d752e196` |
| `pyscf/neutral/stdout` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `pyscf/neutral/stderr` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `pyscf/neutral/endpoint_result.json` | `a8e3cff0d7f35aae9ba121ad4327a98051ab3e18918270622b8fabf2c2ca64f9` |
| `comparison/assisted_result_binding.json` | `807ba7f52a165059cd319c262635f8ec95d57e88feaef91600a49896a6ac11db` |
| `comparison/endpoint_comparison.json` | `a0d048a8d81a692f79e17aa80866eeef5e6329c74dcf652cdb0bf4fe023f0be1` |
| `comparison/label_comparison.json` | `560ab08d869e01998c19428d0448c5e3caf4f29f375bfa1b806679eca21a0d87` |
| `comparison/geometry_context.json` | `c0b098639905042608aa2f1240ffed58f5aa5c9aab0ff087625eaf9219341b66` |
| `file_manifest.json` | `6ca07832dbab16baed2dd6751ed39edf3e3490fd11df78cf05347701002f6b92` |
| `result.json` | `5b115a86341554e71c4f5ab491935a0777e735059fb39a0e7d132be20e0e554f` |

Driver source, deployment archive, and ephemeral runtime files are outside the
durable scientific manifest by design.

## 19. AIMNet2 was not run

`aimnet2_rerun=false`. V005 neither loaded the model nor used a GPU. Assisted
numbers and geometries were read from frozen V002/V004 evidence only.

## 20. PySCF geometry optimization was not run

`pyscf_geometry_optimization=false`. No geomeTRIC kernel, Hessian, frequency,
ZPE, thermal correction, solvent model, or geometry optimization was invoked.

## 21. No second candidate

`second_candidate=false` and `batch=false`. Exactly one candidate and two
endpoints were evaluated.

## 22. No production permit

No production permit was generated, placed, consumed, or restored. No guardian,
campaign, deployment, or production launch path was used.

## 23. Public execution gates

All 11 public execution gates remain false.

## 24. Production labels

No pilot value was inserted into production data. The production high-fidelity
label count remains 71.

## 25. Final conclusion

```text
PASS — 同一候选原始冻结几何与AIMNet2预优化几何的PySCF单点对照已完成
```

Both frozen-initial single points converged under the same protocol as the
retained assisted reference, the exact-byte handoffs passed, the signed
comparison was closed, and raw evidence was saved. The conclusion is limited to
SCF behavior and single-point electronic energies for this candidate. It is not
evidence for an AIMNet2-vs-PySCF geometry-optimization speedup.

## 26. Only next step

根据本次同候选对照结果，决定是否值得对第二个候选进行同样的小规模
science-pilot 复现；本轮不得自动启动第二候选。
