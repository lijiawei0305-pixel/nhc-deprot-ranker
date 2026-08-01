# Phase 9B GTHO Neutral Continuation V001

This is a one-shot, non-production exception authorized after the original
`GTHOEAZLMAMKTA-UHFFFAOYSA-N` pure-PySCF route approached its frozen 24-hour
deadline with the cation complete and the neutral optimization still active.

The original attempt remains immutable.  The continuation may start only when
the original controller exits with timeout status 124, its process tree is
gone, the cation optimized geometry and final single-point result are complete,
and exactly one stable geomeTRIC neutral trajectory can supply the last complete
XYZ frame without reserialization.

The continuation runs only:

```text
last complete neutral geometry
-> omegaB97M-D3(BJ)/def2-TZVPP Grid-4 geomeTRIC optimization
-> same-protocol final single point
-> label using the retained completed cation energy
```

Resources remain CPU affinity `0,2-27`, 27 physical threads and 64,000 MB.
The added hard wall budget is 24 hours.  Functional, basis, grid, D3, SCF,
optimizer, charge, multiplicity and atom order do not change.  No automatic
retry or second continuation exists.

The legacy Lane A watcher must be stopped before the timeout because its source
advances after any terminal exit.  A single continuation supervisor becomes the
only Lane A state writer.  It resumes the already preregistered VNY/VPA/RBK
queue only after the continuation closes with exit zero, PASS, finite endpoint
energies and no residual process.  Any continuation or subsequent candidate
failure writes a Lane A terminal and starts no replacement.  Other lanes are
not modified.

This continuation is `science_pilot_only`, never production accepted, creates
no production label or permit, and does not alter runner v9, public execution
gates, VASP files, or the frozen nine-candidate split.
