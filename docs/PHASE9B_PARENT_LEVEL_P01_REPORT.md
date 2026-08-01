# Phase 9B Parent-Level Benchmark P01 Report

## 1. Outcome and source state

Final classification:

```text
INCONCLUSIVE — 本轮没有获得足够的parent-level证据
```

The parent-method audit reached its fixed `7190 s` wall boundary before the
level-4 grid and finite-difference gates closed.  Per the pre-compute boundary,
Group A, Group B and the assisted-only extension were not started.

| Item | Value |
| --- | --- |
| branch | `agent/phase9b-science-pilot` |
| starting commit | `40c1ccd0b352026f8031c8dc254337e8e0e6cdc0` |
| audit/benchmark source commit | `0e37ed2d8daece40ef70f7ebfa9c29a5520d7e0d` |
| publication commit | the commit containing this report |
| starting/final worktree | clean before work; publication worktree verified separately |
| candidate | `LBNPGYISTSLAHY-UHFFFAOYSA-N` |
| endpoint identity | cation `+1/1/spin 0/26 atoms`; neutral `0/1/spin 0/25 atoms`; both 160 electrons |

Frozen inputs remained byte-identical:

```text
cation  543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286
neutral af9c30640801eec3ab27538a33204186849303dd57592ca5c93320ec1390f4b8
```

## 2. AIMNet2 parent identity

The retained weight is:

```text
aimnet2_wb97m_d3_0.pt
8836941 bytes
f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28
```

The peer-reviewed AIMNet2 description states that the approximately 20 million
reference configurations were evaluated at `omegaB97M-D3/def2-TZVPP`, that
dispersion was removed from the DFT labels used for training, and that an
explicit two-body D3 term was added in the final model.  The installed AIMNet
0.2.0 source and official model configuration agree on rational/BJ parameters:

```text
s6 = 1.0
s8 = 0.3908
a1 = 0.566
a2 = 3.128
ATM = false
```

Sources:

- Chemical Science article: <https://doi.org/10.1039/D4SC08572H>
- official model configuration: <https://huggingface.co/isayevlab/aimnet2-wb97m-d3/blob/main/config.json>

Installed source identities:

```text
calculator.py  4f50f2f22cbb1698a00a2328a9d8cb0a430b8a8c672ca88aeed195e924f38841
lr.py          fe31354eede1dc4d8042ff5f0faab8d1b719b03a347e2227e2c7cdd912ac076f
```

The independent AIMNet D3 evaluation on the frozen cation AIMNet geometry
completed with finite gradients:

```text
D3 energy = -0.042863715440034866 Eh
two body  = true
ATM       = false
```

## 3. PySCF mapping audit

The server installation was read back rather than inferred from method names:

| Component | Actual identity | Match |
| --- | --- | --- |
| Python | 3.11.15 | yes |
| PySCF | 2.13.1 | yes |
| pyscf-dispersion | 1.5.0 | yes |
| geomeTRIC | 1.1.1 | yes |
| LibXC | 7.0.0 | observed |
| public alias | `wb97m-d3bj` | expected |
| LibXC base | ID 531, `HYB_MGGA_XC_WB97M_V` | expected semilocal/exchange part |
| VV10 | explicitly disabled by PySCF alias parsing | match; no double counting |
| D3 method | `wb97m`, rational/BJ damping | match |
| ATM | false | match |
| basis | `def2-TZVPP` | match |

PySCF parses:

```text
wb97m-d3bj -> (xc=wb97m-v, nlc=false, dispersion=d3bj)
```

It therefore does not silently add the VV10 nonlocal term from
`omegaB97M-V`.  The explicit D3 path logged:

```text
Parameters: xc=wb97m, version=d3bj, atm=False
```

`/usr/bin/orca` was inspected and identified as the Orca screen reader version
46.1, not the ORCA quantum-chemistry package.  It was not used.

## 4. Runtime implementation and grid audit

The fixed geometry was the existing AIMNet cation final XYZ:

```text
ea796a5c81504184382b965d57c588c74968a09de8942148d3d9cbadf70a7774
```

### Grid level 3

```text
grid points                 346168
SCF status                  converged
SCF cycles                  13 plus one extra convergence cycle
total energy                -1409.47384591833 Eh
analytic gradient           complete and finite
gradient RMS                0.0016396694610228003 Eh/Bohr
gradient maximum            0.006971401 Eh/Bohr
D3 energy/gradient path     executed, finite, ATM=false
```

The implementation advanced past the independent D3 energy/gradient and
five-term reconstruction checks.  However, their exact structured numeric
payload was only scheduled for publication after both grid levels.  The later
timeout therefore left no independently reconstructable PySCF D3 numeric
receipt.  This is reported as missing evidence, not inferred as a pass from
source control flow.

### Grid level 4

```text
grid points                 679168
status                      timeout during standard SCF
last complete cycle         11
last non-terminal energy    -1409.47383054465 Eh
analytic gradient           not run
finite-difference check     not run
```

The incomplete level-4 energy is not compared with the converged level-3
energy as a grid-sensitivity result.  No final grid was frozen.

```text
external wall               7190.02 s
exit status                 124
stderr bytes                0
residual audit process      none
```

This is an environment/resource-time limitation, not evidence that
omegaB97M-D3(BJ), def2-TZVPP, D3, the molecule, or PySCF failed scientifically.

## 5. Frozen route definitions and why they did not start

The intended groups remained:

```text
Group A:
same frozen initial XYZ
-> AIMNet2 LBFGS
-> exact-byte handoff
-> parent-level final single points

Group B:
same frozen initial XYZ
-> parent-level PySCF/geomeTRIC geometry optimization
-> same parent-level final single points
```

An original-geometry single point was never substituted for Group B.  Because
the mandatory method/grid audit did not pass, starting either formal route
would have violated the audit-first boundary.

## 6. Code changes

Only science-pilot files were added:

```text
scripts/phase9b_parent_level_protocol_audit.py
scripts/phase9b_parent_level_paired_benchmark.py
tests/test_phase9b_parent_level_p01.py
```

The benchmark adapter reuses the existing AIMNet2 entry point, geometry review,
typed PySCF backend and V006 evidence helpers.  It does not modify the
production runner or shared core.

No production runner, v9 leaf, guardian, permit, campaign, Postflight, public
gate, production ten-degree gate, historical v001-v006 evidence, or production
label table was modified.

## 7. Actual compute commands

The following is the public, path-sanitized projection of the commands that
actually ran.  `<SSH_ALIAS>`, `<MLFF_ENV>`, `<GPUPYSCF_ENV>`, `<REMOTE_RUN_ROOT>`
and `<V006_REMOTE_ROOT>` replace only private host bindings; the unredacted
argv is retained with the private evidence.

AIMNet external D3 audit:

```bash
ssh <SSH_ALIAS> 'env -u PYTHONHOME -u PYTHONPATH -u PYTHONSTARTUP \
  PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  timeout --signal=TERM --kill-after=10s 300s taskset -c 0-3 \
  <MLFF_ENV>/bin/python -I -B \
  <REMOTE_RUN_ROOT>/driver/repo/scripts/phase9b_parent_level_protocol_audit.py \
  aimnet-d3-audit \
  --root <REMOTE_RUN_ROOT>/protocol_audit \
  --xyz <V006_REMOTE_ROOT>/assisted/input/cation_aimnet2_final.xyz \
  --xyz-sha256 ea796a5c81504184382b965d57c588c74968a09de8942148d3d9cbadf70a7774'
```

PySCF implementation/grid audit:

```bash
ssh <SSH_ALIAS> 'root=<REMOTE_RUN_ROOT>/protocol_audit; \
  /usr/bin/time -f %e -o "$root/pyscf_audit_elapsed" \
  timeout --signal=TERM --kill-after=10s 7190s taskset -c 0-3 \
  env -u PYTHONHOME -u PYTHONPATH -u PYTHONSTARTUP PYTHONDONTWRITEBYTECODE=1 \
  <GPUPYSCF_ENV>/bin/python -I -B \
  <REMOTE_RUN_ROOT>/driver/repo/scripts/phase9b_parent_level_protocol_audit.py \
  pyscf-audit --root "$root" \
  --xyz <V006_REMOTE_ROOT>/assisted/input/cation_aimnet2_final.xyz \
  --xyz-sha256 ea796a5c81504184382b965d57c588c74968a09de8942148d3d9cbadf70a7774 \
  > "$root/pyscf_audit_stdout" 2> "$root/pyscf_audit_stderr"'
```

Group A and Group B have no execution command because they were not started.

## 8. Evidence

Private local mirror:

```text
results/phase9b_parent_level_p01/
```

| Evidence | SHA256 |
| --- | --- |
| AIMNet D3 identity | `b401355843fe6a2d229232ad0610ed87d4de5711fb61e80b7270a0c3e9ab5041` |
| PySCF audit stdout | `2ff49ccb56bbb79a160c93bc59baca688a99ecde59919db87e0d55d7c6e55802` |
| PySCF audit stderr | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| PySCF elapsed/exit record | `b04c4793fd0d1435541d7d12434e68d78ce4bcead5d215135cd023e16ee8421c` |
| audit source | `d2ddeaffeddf29875f8cf6426dd2b89d8cc29c6721ed04b2d1114277ec1a37b3` |
| paired benchmark source | `6c10e4f941115747aa631550369ff8d2f3923687750b172e96df42cfbeed0463` |

## 9. Retained state

```text
Group A                         not started
Group B                         not started
assisted extension              not started
second Pure PySCF candidate     none
retry                           none
new parent-level label          none
production permit               none
production accepted             false
public execution gates          11/11 false
production labels               71
historical v001-v006            unchanged
```

## 10. Only next step

Only resolve the single resource/method-audit gap: decide whether to authorize
one continuation of the same fixed-geometry level-4 grid/gradient audit with a
larger explicit budget or more CPU resources.  Do not start Group A, Group B,
an extension cohort, production, or a second candidate.
