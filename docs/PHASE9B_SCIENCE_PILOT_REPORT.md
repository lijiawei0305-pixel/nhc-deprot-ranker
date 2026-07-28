# Phase 9B one-shot science pilot report

## Scope and outcome

This was one isolated, non-production `science_pilot_only` attempt for
`LBNPGYISTSLAHY-UHFFFAOYSA-N`. It did not consume a permit, enter a campaign,
open a public execution gate, or write a production label.

The outcome is **INCONCLUSIVE**. The cation AIMNet2 optimization genuinely ran
and converged, but a source-level structural-validator defect rejected the
unchanged C2 proton before the neutral endpoint or PySCF could start. The run
was stopped at that boundary and was not retried.

## Blocker classification

| Item | Class | Reason |
| --- | --- | --- |
| Frozen XYZ, charge/multiplicity, atom order and atom map | A | Required for this scientific calculation |
| Local AIMNet2 weight and real V100 execution | A | Required for this scientific calculation |
| Exact AIMNet2-to-PySCF bytes and frozen PySCF protocol | A | Required for this scientific calculation |
| Guardian, permit, PID-reuse proof, campaign manifest, Postflight and v10 | B | Production controls, not needed by this pilot |
| GPU availability and numerical convergence | C | Could only be resolved at runtime |
| Correctness of the proton-host structural predicate | C → A | Runtime exposed a science-validation implementation defect |

## Frozen scientific definition

The target remains the gas-phase electronic-energy quantity, not Gibbs free
energy, pKa, solution acidity, or experimental thermodynamics:

```text
electronic_difference_kcal =
    (E_neutral_PySCF - E_cation_PySCF) * 627.509474

dft_deprot_electronic_kcal =
    electronic_difference_kcal - 6.28
```

The frozen PySCF path would have been B3LYP-D3(BJ)/def2-SVP geomeTRIC residual
optimization followed by a fresh same-method final SCF. It was not reached.

## Actual repository changes

- `scripts/phase9b_science_pilot.py` — isolated two-interpreter pilot entry;
  reuses the AIMNet2 optimizer and PySCF scientific backend primitives without
  invoking production authority or writers.
- `tests/test_phase9b_science_pilot.py` — freezes the candidate, formula,
  exact-byte/same-inode handoff, failure classification, and closed production
  gates.
- `docs/PHASE9B_SCIENCE_PILOT_RESULT.json` — sanitized portable result.
- this report.

No runner leaf, production request, manifest, resource, permit, public gate,
Phase status, or production label table was modified.

## Execution environment

| Component | Observed identity |
| --- | --- |
| Python | 3.11.15 |
| AIMNet | 0.2.0 |
| ASE | 3.29.0 |
| Torch | 2.8.0 metadata / 2.8.0+cu128 runtime |
| CUDA | 12.8 |
| GPU | exact Tesla V100-SXM2-32GB, sm_70 |
| Weight | `aimnet2_wb97m_d3_0.pt`, 8,836,941 bytes, `f0f7c054...24e28` |
| PySCF environment probe | Python 3.11.15, PySCF 2.13.1, geomeTRIC 1.1.1, pyscf-dispersion 1.5.0 |

The executed pilot source commit was
`bb65d4c1a25849a59c73645b7584f95b24b84056`; the pilot script SHA256 was
`fcacb5e998133f4ad9ac8da0a8b76675a2eddd51d8bf2e305e3bdeb70fa10e81`.

## AIMNet2 result

| Endpoint | Charge | Mult | Steps | Max force before | Max force after | Wall | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| cation | +1 | 1 | 54 | 2.600473 eV/Å | 0.045105 eV/Å | 23.570 s | optimization converged; rejected by incorrect proton-host predicate |
| neutral | 0 | 1 | — | — | — | — | not started |

The cation energy changed from `-38353.04313401915 eV` to
`-38353.81999675751 eV`. The trajectory contains 55 frames and ends at
calculator invocation 56. `base_model_forward_calls` remains `unmeasured`.

All measurable structural gates passed:

- atom count and order unchanged;
- index-preserving connectivity unchanged, with no added or removed bonds;
- acidic H index 23 remained bonded to C2 index 14 before and after;
- RMSD 0.221195 Å;
- maximum displacement 0.480061 Å;
- C2–N1/C2–N3 changes 0.008796/0.014209 Å;
- N1–C2–N3 angle change 1.473158°;
- minimum pair distance 1.073003 Å;
- maximum absolute coordinate 4.401204 Å.

The rejection came from the current runtime predicate that requires a cation
proton host in `{N1, N3}`. The frozen science contract instead requires the
acidic proton to remain on its **original** heavy atom, and Phase 7 identifies
this candidate as a one-C2-proton pair. Both initial and final geometries place
the acidic proton on C2. This is an implementation defect, not observed proton
migration and not an AIMNet2 numerical failure.

## PySCF and handoff

| Endpoint | Charge | Mult | SCF | Cycles | Energy | Time | Status |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| cation | +1 | 1 | not run | — | — | — | stopped before handoff |
| neutral | 0 | 1 | not run | — | — | — | stopped before handoff |

No AIMNet2-to-PySCF handoff was created. No PySCF import, geomeTRIC
optimization, SCF kernel, D3 calculation, or label calculation occurred in the
pilot execution.

## Evidence

The complete private tree is retained at:

```text
<REMOTE_PROJECT_ROOT>/data/runs/science_pilot_lbn_v001/
```

Key portable identities:

| Evidence | SHA256 |
| --- | --- |
| cation initial XYZ | `543c6944233b...f3d286` |
| neutral initial XYZ | `af9c30640801...90f4b8` |
| cation AIMNet2 final XYZ | `ea796a5c8150...a7774` |
| cation trajectory | `0ebacfff83f0...6580` |
| cation stdout | `2ea65bb8d5f4...8250` |
| cation stderr (empty) | `e3b0c44298fc...b855` |
| private result | `769e64a20f50...1915` |

The private tree was also mirrored locally under the ignored `results/`
namespace. Private absolute paths, host identity, account identity and raw
traceback paths are not published.

## Final decision and next step

```text
INCONCLUSIVE — the cation AIMNet2 calculation converged, but the one-shot
chain stopped at a confirmed proton-host validator implementation defect before
neutral AIMNet2 and PySCF.
```

The only next step is a narrowly reviewed correction of the science-pilot
cation proton-host predicate so it binds the original C2 host, followed by a
separately authorized new one-shot pilot. Do not create v10, add a candidate,
or start a batch.
