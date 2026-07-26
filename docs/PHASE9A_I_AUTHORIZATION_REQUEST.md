# Phase 9A-I Authorization Request

## What is being requested

Authorization to execute **exactly six** AIMNet2 single-point evaluations —
three repeats of one frozen cation and three of the matching frozen neutral —
on one candidate, using one existing local weight.

Nothing else is requested. This is not authorization for Phase 9B.

## Exactly what would run

```text
candidate  LBNPGYISTSLAHY-UHFFFAOYSA-N
cation     26 atoms, C9 F9 H5 N3, charge +1, mult 1
neutral    25 atoms, C9 F9 H4 N3, charge  0, mult 1

weight     aimnet2_wb97m_d3_0.pt
           8836941 bytes
           sha256 f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28

processes  3 clean Python processes
calls      6 energy evaluations, 6 force evaluations
optimizer  none
PySCF      none
labels     none
GPU        exactly one currently free device
```

Input geometry hashes, reverified immediately before use:

```text
cation   543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286
neutral  af9c30640801eec3ab27538a33204186849303dd57592ca5c93320ec1390f4b8
```

## What would not run

```text
geometry optimization      any optimizer step
coordinate modification    PySCF        geomeTRIC
xTB                        MMFF / UFF   Hessian
frequencies                MD           training or fine-tuning
weight download            dependency install or upgrade
global environment change  weight modification
any scientific label
```

## Safety properties before the model loads

The attempt stops **before loading the model** if any of these cannot be
established in advance:

- offline flags and `PYTHONDONTWRITEBYTECODE` set prior to every import;
- the weight verified by existence, regular-file status, non-symlink status,
  exact byte size, and complete SHA256;
- all cache-capable variables redirected into a fresh, empty, attempt-specific
  isolated root;
- global caches snapshotted;
- exactly one free GPU with sufficient memory identified.

The ordering is the safety property. A check performed after loading could only
report damage that had already occurred.

## Proof obligations afterward

```text
global caches unchanged
model weight byte size and SHA256 unchanged
environment unchanged
no download occurred
every file created inside the isolated root enumerated
input coordinates identical before and after every call
```

## Residual risks, stated plainly

**A shared host.** Other users' jobs were running at preflight. The run takes one
free GPU or fails closed; it never preempts and never waits in the background.

**A live download surface.** The calculator constructor exposes `revision` and
`token`. Mitigated by supplying an explicit local path and never a model name,
with offline flags as a second line of defence.

**Cache side effects.** Torch, CUDA, and Triton write caches during normal use.
Mitigated by redirection into the isolated root plus before/after snapshots. If
isolation cannot be proven, the run does not start.

**One ensemble member.** No uncertainty estimate is available. This phase makes
no ensemble claim, and single-member reproducibility must never be reported as
ensemble uncertainty.

**Carbene domain.** The neutral endpoint is a singlet carbene, which
general-purpose organic training sets under-represent. This phase does not test
accuracy and cannot resolve that concern; it only establishes that the interface
runs.

## What the result will and will not settle

Settled by a pass: offline local loading, actual element support, working charge
propagation, real units and shapes, and measured single-point reproducibility.

Not settled: accuracy for NHC chemistry, whether C2 is in the training domain,
whether preoptimization is faster than direct PySCF, whether both routes reach
the same minimum, readiness for production, any uncertainty estimate, or any new
label.

Phase 8B remains failed closed. High-fidelity labels remain **71**. The legacy
project's recorded median **1.10x** preoptimization speedup remains the best
available prior for Phase 9B, and non-promotion remains a likely and legitimate
outcome.

## The single question

> Authorize exactly six AIMNet2 single-point energy-and-force evaluations —
> three repeats each of the frozen `LBNPGYISTSLAHY-UHFFFAOYSA-N` cation and
> neutral — using the verified local weight `aimnet2_wb97m_d3_0.pt`, on one free
> GPU, with cache isolation proven in advance, and with no optimization, no
> PySCF, and no label produced?

Answering yes authorizes this phase only. Phase 9B requires its own plan, its
own authority chain, and its own separate authorization.
