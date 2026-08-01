# Phase 9B science pilot v002 report

## Outcome

**FAIL** — the corrected one-shot reached both real AIMNet2 endpoint
optimizations. Cation passed every frozen gate. Neutral numerically converged,
but its N1–C2–N3 angle changed by `12.366075°`, exceeding the preregistered
`10°` structural limit. The pilot stopped before handoff and PySCF, without a
retry or threshold change.

This is a `science_pilot_only` result. It is not a production accepted run and
produced no label.

## v001 retained result

v001 remains **INCONCLUSIVE** with private result SHA256
`769e64a20f5035866e2b17895746440c79c06d8b1758a46dff8540cbe5281915`.
Its failure was the pilot validator's incorrect assumption that the cation
proton must be hosted by N1 or N3. It was not an AIMNet2 failure, candidate
failure, or PySCF failure.

The v002 pilot-only correction derives the H23 host from the frozen input and
requires that exact host atom index after optimization. It records:

```text
initial H23 host = C2 index 14
final H23 host   = C2 index 14
identity         = preserved
```

Migration to N1, N3, or any other atom fails. Production runner source and v9
were not changed.

## Repository changes

- `scripts/phase9b_science_pilot.py`: v002 root identity and input-derived
  proton-host preservation; no production authority path.
- `tests/test_phase9b_science_pilot.py`: one minimal
  `test_proton_host_identity_preserved` covering C2 retention, N migration, and
  migration elsewhere.
- this report and the v002 portable result.

No guardian, permit, campaign, Postflight, v10, production request, execution
gate, or label table changed.

## Execution identity

| Component | Identity |
| --- | --- |
| Candidate | `LBNPGYISTSLAHY-UHFFFAOYSA-N` |
| Pilot source commit | `f6c173e1843f34c1b80b99dc1b5bf2fd946430cf` |
| Pilot script SHA256 | `b38aa93008f744551c2dec352214c1bcc53f71e3ceddfcfe0e5e73ce15a04a55` |
| Python | 3.11.15 |
| AIMNet / ASE | 0.2.0 / 3.29.0 |
| Torch / CUDA | 2.8.0+cu128 / 12.8 |
| GPU | Tesla V100-SXM2-32GB, sm_70 |
| Weight | `aimnet2_wb97m_d3_0.pt`, 8,836,941 bytes, `f0f7c054...24e28` |

## AIMNet2 results

| Endpoint | Charge | Mult | Steps | Initial max force | Final max force | Wall | Outcome |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| cation | +1 | 1 | 54 | 2.600473 eV/Å | 0.045105 eV/Å | 23.700 s | PASS |
| neutral | 0 | 1 | 64 | 5.767974 eV/Å | 0.044275 eV/Å | 2.888 s | FAIL — ring-angle gate |

Cation loaded the corrected identity gate and passed with H23 still hosted by
C2 index 14. The base model loaded once; two independent endpoint wrappers were
used. `AIMNet2ASE.calculate()` counts were 56 and 66. The uninstrumented
base-model forward count remains `unmeasured`.

Neutral retained atom count, element order, connectivity and hydrogen hosts.
All numeric gates except one passed:

| Neutral structure metric | Observed | Limit | Result |
| --- | ---: | ---: | --- |
| RMSD | 0.604637 Å | ≤1.0 Å | pass |
| Maximum displacement | 1.171685 Å | ≤2.5 Å | pass |
| C2–N1 change | 0.091481 Å | ≤0.15 Å | pass |
| C2–N3 change | 0.097293 Å | ≤0.15 Å | pass |
| N1–C2–N3 angle change | 12.366075° | ≤10° | **fail** |
| Minimum pair distance | 1.081625 Å | ≥0.20 Å | pass |
| Maximum absolute coordinate | 4.373513 Å | ≤100 Å | pass |

No threshold was changed after observing the result.

## Handoff and PySCF

Handoff status: `not_run`.

| Endpoint | PySCF status | SCF cycles | Energy | Wall |
| --- | --- | ---: | ---: | ---: |
| cation | not started | — | — | — |
| neutral | not started | — | — | — |

The contract requires both AIMNet2 endpoints to pass before any PySCF work.
Consequently no PySCF input hardlink, geomeTRIC optimization, SCF kernel, D3
calculation, or deprotonation value was produced.

## Frozen formula

```text
electronic_difference_kcal =
    (E_neutral_PySCF - E_cation_PySCF) * 627.509474

dft_deprot_electronic_kcal =
    electronic_difference_kcal - 6.28
```

Unit: `kcal/mol`. Value: unavailable because PySCF did not start. This target
is a gas-phase electronic-energy quantity, not Gibbs free energy, pKa, or
solution acidity.

## Evidence

The untouched v001 root and new v002 root are separately retained. The v002
private root is represented publicly as:

```text
<REMOTE_PROJECT_ROOT>/data/runs/science_pilot_lbn_v002/
```

| Evidence | SHA256 |
| --- | --- |
| cation final XYZ | `ea796a5c8150...a7774` |
| neutral final XYZ | `c40ca77bce9d...46bc93` |
| cation trajectory | `5dc766d6320a...861d9f` |
| neutral trajectory | `5265e2760e72...1e62ff` |
| AIMNet2 summary | `aa2ab560e496...54baf` |
| private result | `b1362a3b1df7...cd7071` |

The private tree is also mirrored under the ignored local `results/`
namespace. No private absolute path, account, hostname, GPU UUID, or raw
traceback is published.

## Final decision and next step

```text
FAIL — neutral AIMNet2 relaxation exceeded the frozen N1–C2–N3 angle-change
gate, so the AIMNet2 → PySCF chain was correctly stopped before PySCF.
```

The only next step is a read-only scientific review of the neutral optimized
geometry and the preregistered 10° basin-preservation criterion. Do not loosen
the threshold or run another attempt without a separate authorization.
