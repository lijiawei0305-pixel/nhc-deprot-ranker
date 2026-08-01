# RBK throughput continuation v001

## Authorization and scope

This is a user-authorized, non-production `THROUGHPUT_COLLECTION` continuation
for the one pre-registered and never-claimed candidate
`RBKFFSUUCLDQER-UHFFFAOYSA-N`.  It is not a retry or replacement for the
timed-out `CLXFIGGGSODORK-UHFFFAOYSA-N` route, does not add a candidate, and
does not reopen the failed nine-candidate training cohort.

The route uses the frozen Parent-Level P01 pure-PySCF path only:

```text
frozen cation/neutral input XYZ
-> P01 PySCF/geomeTRIC optimization
-> P01 final single points
-> immutable route evidence
```

It must not start AIMNet2 training, consume final-test data, create a production
label, retry any route, use xTB/GFN/DFTB/MMFF/UFF, or change the production
runner, v9, public gates, or the 71 production labels.

## Frozen identity

- candidate: `RBKFFSUUCLDQER-UHFFFAOYSA-N`
- split: `train` (diagnostic only; current cohort remains blocked by CLX timeout)
- P01 protocol SHA256:
  `227c22a527e567bc4de873ab743fe9f493779eccbb1a698d2913c87695ebf87a`
- cation: 38 atoms, input SHA256
  `6d3b2d2678b30f5f90b1e140467f6261c9832191f3417eeeb102fb740f4d6f15`
- neutral: 37 atoms, input SHA256
  `653ae4c33b6a0a234529c9203b55087be6655c9d2b167d928a7bfa733fb5b385`
- resource bundle: logical CPUs `28-55`, 28 threads, `64000 MB` PySCF limit
- route hard wall limit: `86400 s`; no retry or continuation is authorized

## Preflight and terminal rule

Before launch, require a new result root, regular non-symlink input files with
the hashes above, one-second idle observation for CPUs `28-55`, adequate memory
and disk headroom, and no sustained swap-in/out activity.  The existing P01
driver writes the route's immutable assignment, process result, endpoint/route
manifests, and terminal evidence under a new RBK result root.

This continuation is explicitly excluded from isolated benchmark timing claims.
It is diagnostic P01 reference collection only.  Any nonzero controller exit,
missing terminal evidence, non-convergence, timeout, or manifest failure remains
terminal and is not retried.
