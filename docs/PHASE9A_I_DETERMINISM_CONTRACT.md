# Phase 9A-I Determinism Contract

## What is being measured

Whether six single-point evaluations — three repeats of one frozen cation and
three of one frozen neutral — reproduce closely enough for the model to be
usable as a preoptimizer.

The tolerances below are **preregistered**. They are fixed before any number
exists, and no result may be used to adjust them afterward.

## Bitwise identity is not required

Bitwise reproducibility is not demanded, for a stated reason rather than as a
convenience.

GPU floating-point reduction order is not guaranteed stable across launches.
Non-deterministic kernel selection, autotuning, and atomics can each perturb the
last bits of a sum without indicating any defect. Requiring bitwise equality
would therefore convert normal, correct GPU behaviour into a spurious failure,
and would tempt a later run to disable it after the fact — exactly the kind of
post-hoc threshold change this project forbids.

What matters for a preoptimizer is that repeated evaluations agree far more
tightly than the physical effects being modelled.

## Preregistered tolerances

For three repeats of an identical input:

```text
energy spread                    <= 1e-4 eV
force component spread           <= 1e-4 eV/A
force norm spread                <= 1e-4 eV/A
bitwise identity required        no
```

"Spread" is `max - min` across the three repeats.

### Why 1e-4

The scale is set by what the model must resolve, not by what floating point can
achieve.

The geomeTRIC convergence threshold recorded in the legacy audit is roughly
`0.015-0.023 eV/A`, and the legacy fine-tuned model's near-minimum force error
was about `0.088 eV/A`. A run-to-run irreproducibility of `1e-4 eV/A` is more
than two orders of magnitude below the convergence threshold and nearly three
below the model's own accuracy. It is therefore comfortably negligible for
optimization while still being tight enough to expose a genuine
non-determinism problem such as uninitialized memory, a race, or a changing
device.

A tolerance chosen to be merely "achievable" would prove nothing. This one is
chosen to be irrelevant to the physics and still diagnostic.

## Cross-process repetition

The three repeats should run in **three independent clean Python processes**,
each computing one cation and one neutral in turn.

Repeating inside a single process would mostly re-measure caching: the second
call could return a memoized result, reuse a warm autotune selection, or share
allocator state, and would agree closely for reasons unrelated to determinism.
Separate processes test what actually matters — that a fresh process on the same
machine, same weight, and same input reproduces the result.

## Reported quantities

Reported separately, never pooled:

```text
cation  energy spread
cation  maximum force-component spread
neutral energy spread
neutral maximum force-component spread
```

Pooling cation and neutral would hide an endpoint-specific problem, and the
neutral is the endpoint carrying the carbene centre — the one most likely to
misbehave.

## Fail-closed conditions

Any of the following fails the phase:

```text
any exception
any NaN or Inf in energy or forces
forces shape drift from (N, 3)
atom count or atom order drift
charge or multiplicity drift
input coordinates changed by the call
any spread above its preregistered tolerance
```

Outlier results are **not** removed before declaring success. If one of three
repeats disagrees, that is the finding. Discarding it and reporting the
remaining two would manufacture a determinism claim the data does not support.

## What a pass means

A pass means the local weight loads offline, the selected elements run, charge
passes through correctly, the energy and force interface works, and repeated
single-point evaluation reproduces within the stated tolerance on this hardware.

It does not mean the model is accurate for NHC chemistry, that the C2 carbene
centre is in its training domain, that preoptimization will be faster than
direct PySCF, or that any uncertainty estimate exists. With one ensemble member
there is **no ensemble uncertainty**, and single-member reproducibility must
never be presented as one.
