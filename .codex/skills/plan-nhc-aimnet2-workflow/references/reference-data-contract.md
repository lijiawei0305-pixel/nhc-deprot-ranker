# Pure-PySCF Reference Data Contract

## Purpose

Use this contract for every dataset intended to train, validate, or finally test
an NHC-specific AIMNet2 generation. Treat every missing identity, writer,
manifest, or frozen threshold as a hard failure.

## 1. Close the reference route

Call a route `pure_pyscf_reference` only when it follows this exact scientific
path:

```text
frozen initial cation/neutral XYZ
-> Parent-Level P01 PySCF/geomeTRIC optimization
-> Parent-Level P01 final single point
```

Do not place AIMNet2 geometry, energy, force, checkpoint, or selection anywhere
in this route. Bind before launch:

- candidate, InChIKey, permanent split, endpoint, atom map, and input XYZ
  SHA256;
- ordered elements, charge, multiplicity, spin, and electron count;
- the complete Parent-Level P01 protocol and its SHA256;
- PySCF, geomeTRIC, dispersion, numerical, resource, fallback, and source
  identities.

Close a route only if the controller exits zero, the route reports `PASS`, both
endpoint optimizations and both final single points complete, all SCF and
geometry convergence flags are literal `true`, no residual process remains,
and immutable endpoint and route manifests bind the exact file set. Keep a
failed, partial, timed-out, or manifest-open route as diagnostic evidence only.
Admit none of its frames.

## 2. Admit frames exactly

Capture each frame at the real P01 analytic-gradient boundary. Require:

- exact evaluated coordinates in Bohr and ordered element identity;
- total P01 energy in Hartree, including the frozen two-body D3(BJ) term;
- complete analytic gradient and `force = -gradient` in Hartree/Bohr;
- candidate, endpoint, frame index, charge, multiplicity, spin, electron count,
  protocol SHA256, geometry SHA256, file SHA256, and canonical SHA256;
- finite values, explicit SCF convergence, frozen collision/connectivity gates,
  and every repository-frozen force gate.

Require contiguous frame indices and exact-set manifest closure. Reject
symlinks, mutable files, atom reordering, identity drift, duplicate ownership,
and cross-split geometry reuse. Include early high-force frames only when they
pass every frozen admission gate. If an extreme-force, collision, connectivity,
or near-duplicate threshold is required but not frozen, fail closed.

## 3. Construct the short-range target

Independently recompute, for every admitted frame, the exact external two-body
D3(BJ) energy and gradient used by Parent-Level P01. Bind implementation,
version, functional, damping parameters, `ATM=false`, units, input geometry, and
output hashes. Require runtime evidence that the source total used the same D3
definition; configuration text alone is insufficient.

Construct targets only as:

```text
E_short = E_P01_total - E_D3
F_short = F_P01_total - F_D3
F_D3    = -gradient_D3
```

Recheck `F_short = -gradient_short`, unit conversions, finite values, and shape
after subtraction. Preserve total, D3, and derived short-range components in
the audit projection. Feed only the registered short-range keys to training.
Require inference to add back the identical external D3 definition, and prove
numerical export parity before accepting a model bundle.

## 4. Prevent split leakage and frame-count dominance

Use InChIKey as the permanent split unit. Keep both endpoints and every frame of
one InChIKey in one split. Fit atomic baselines, normalization statistics,
sampling rules, and all preprocessing from training candidates only.

Make candidate and endpoint balance explicit:

- give each training candidate equal total effective weight;
- give cation and neutral equal total effective weight within each candidate;
- distribute an endpoint's weight across its admitted frames or implement an
  equivalent candidate/endpoint-stratified sampler;
- record per-frame weights and prove their sums by candidate and endpoint;
- never let a longer geomeTRIC trajectory dominate merely by contributing more
  frames.

Aggregate validation and final-test metrics by candidate first. Report frame
metrics only as diagnostics. Audit exact and near duplicates, force and energy
coverage, candidate/endpoint counts, element and charge coverage, and trajectory
lengths before training. Do not invent a bin, clipping, deduplication, or
admission threshold; an absent required threshold blocks dataset closure.

## 5. Required immutable outputs

Close the dataset only with:

```text
source-route manifest set
admitted/rejected-frame ledger with reason codes
D3 projection manifest
candidate/endpoint weight audit
permanent split-registry binding
train and validation dataset manifests
sealed final-test commitment identity
complete dataset manifest and SHA256
```

Do not expose final-test frames or targets to dataset training, checkpoint
selection, or model-generation processes. Follow
`model-generation-contract.md` for final-test sealing and consumption.
