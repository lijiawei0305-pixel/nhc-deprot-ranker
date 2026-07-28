# Phase 9B science pilot v004 plan

## Scope

This is a one-candidate, non-production continuation. It reuses the exact
retained v002 XYZ bytes, does not rerun AIMNet2, and does not change the v002
terminal or production 10-degree gate.

Stage A writes a new `review_v004` evidence tree. Stage B is reachable only if
its immutable classification is exactly `SAME_BASIN_LIKELY`; otherwise no SSH
or PySCF continuation root is created.

## Sole Stage A correction

The signed torsion is normalized to `[-180, 180]`. Planarity is measured as:

```text
min(abs(phi), abs(180 - abs(phi)))
```

Evidence retains the raw signed value, normalized signed value, and corrected
planarity deviation. The existing 30-degree review heuristic is unchanged.
All other v003 review logic, input hashes, atom indices, connectivity rules,
and geometric thresholds remain unchanged.

## Conditional Stage B

If Stage A is `SAME_BASIN_LIKELY`, Stage B creates only the fresh
`science_pilot_lbn_pyscf_v004` root. It binary-copies the retained cation and
neutral AIMNet2 final XYZ, proves source/copy/parser byte equality, and runs
cation then neutral single-point final-SCF calculations.

The science-pilot single point is the frozen final-SCF slice of the repository
PySCF protocol: gas-phase fresh RKS, B3LYP-D3(BJ)/def2-SVP, grid level 3,
`conv_tol=1e-9`, 12000 MB, four threads, standard `max_cycle=100`, with the
repository's one typed non-convergence standard-to-SOSCF transition to
`max_cycle=200`. No geometry optimization or geomeTRIC call is allowed.

The project does not explicitly set an initial-guess field or pass `dm0` in the
frozen final-SCF path. Stage B therefore must not invent one: it records the
actual PySCF mean-field `init_guess` value before `kernel()` and refuses any
other parameter change.

D3(BJ) must use the frozen `mf.disp="d3bj"` owner path and retain the independent
`DFTD3Dispersion(..., xc="B3LYP", version="d3bj", atm=False)` energy/gradient
audit. AIMNet2 energy is excluded from the label formula.
