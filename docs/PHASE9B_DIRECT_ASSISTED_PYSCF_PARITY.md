# Phase 9B Direct/Assisted PySCF Parity Contract

## `DirectAssistedPySCFParityContractV1`

Direct and assisted A2 must call one shared, strongly typed PySCF execution core.
The implementation may wrap that core for authority and evidence, but it may not
copy or fork the chemistry algorithm.

| Field | Direct | Assisted A2 | Rule |
| --- | --- | --- | --- |
| candidate / endpoints | frozen LBNP pair | same | equal |
| original Phase 7 XYZ | frozen bytes | same parent bytes | equal provenance |
| PySCF input XYZ | original bytes | admitted A1 output bytes | only allowed scientific difference |
| atom order | frozen | preserved and hash-closed | equal ordered elements |
| charge/multiplicity | +1/1, 0/1 | +1/1, 0/1 | equal |
| electron count | 160 | 160 | equal |
| endpoint order | cation, neutral | cation, neutral | equal |
| functional / basis | B3LYP-D3(BJ) / def2-SVP | same | equal |
| grid, SCF, geometry | frozen protocol | same shared object | equal |
| threads / affinity / memory | 4 / `0-3` / 12000 MB | same | equal |
| standard -> SOSCF behavior | shared core | shared core | equal; not a route retry |
| D3 evidence | shared core | shared core | equal |
| final label formula | PySCF electronic energies only | same | equal |

The direct wrapper supplies frozen initial XYZ bytes; A2 supplies only the bytes
independently accepted by `StageA2AdmissionReceiptV1`. After entry, both use the
same parser, Mole construction, residual optimizer, SCF progression, D3
evidence, endpoint schemas, failure classification, and label function.

AIMNet2 energy, forces, or convergence values cannot enter the shared core's
energy fields or label. A1 acceptance changes only the starting coordinates.
Process splitting, import startup, handoff verification, and GPU accounting are
execution overhead and must be included in assisted total wall time, not treated
as a scientific parameter or removed from the performance comparison.

## Performance comparison

Direct reports guardian/worker startup, PySCF wall, CPU core-seconds, SCF cycles,
and energy/gradient calls. Assisted reports guardian and campaign startup, A1
startup/model load/preoptimization, handoff verification, A2 startup/PySCF,
terminal evidence, total wall, CPU core-seconds, GPU-seconds, SCF cycles, and
energy/gradient calls. Comparing assisted PySCF time alone to direct total time
is invalid. An A1 failure with no PySCF has no speedup measurement.
