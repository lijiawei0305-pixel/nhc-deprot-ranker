# Phase 9A-I — Minimal AIMNet2 Inference Characterization Report

## Outcome

**Passed.** All six single-point evaluations completed. The local weight loaded
offline from an explicit path, both endpoints ran with explicitly supplied
charge, the interface returned eV and eV/Å, and repeated evaluation reproduced
far inside the preregistered tolerance.

No geometry optimization ran. No PySCF ran. No label was produced.

Machine evidence: `docs/PHASE9A_I_RESULT_V001.json`.

## Authorization boundary

Authorized scope was exactly six energy-and-force calls on one frozen candidate.
Executed: 2 endpoints × 3 repeats = 6 energy evaluations and 6 force
evaluations, in 3 clean processes, on one free GPU, using two SSH invocations
(pre-run check, then the run).

Not performed: any optimizer step, coordinate modification, PySCF, geomeTRIC,
xTB, MMFF, UFF, Hessian, frequencies, MD, training, fine-tuning, weight
download, dependency install or upgrade, global environment modification, weight
modification, or label creation.

## Inputs were read in place, not uploaded

The Phase 7 geometry already exists on the server from the Phase 7 run. Both
endpoint files were read **read-only in place**, and their SHA256 values matched
the tracked manifest exactly:

```text
cation   543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286   26 atoms
neutral  af9c30640801eec3ab27538a33204186849303dd57592ca5c93320ec1390f4b8   25 atoms
```

No file was uploaded, so this phase performed **no server write outside its own
isolated temporary root**.

## Results

```text
cation   E = -38353.043134138  /  -38353.043133900  /  -38353.043133900  eV
neutral  E = -38341.635253578  /  -38341.635253697  /  -38341.635253697  eV
```

| Quantity | Cation | Neutral | Tolerance | Pass |
| --- | --- | --- | --- | --- |
| energy spread | 2.38e-7 eV | 1.19e-7 eV | 1e-4 eV | yes |
| force-component spread | 0.0 eV/Å | 0.0 eV/Å | 1e-4 eV/Å | yes |
| force-norm spread | 0.0 eV/Å | 0.0 eV/Å | 1e-4 eV/Å | yes |
| max abs force component | 2.225370 eV/Å | 5.731652 eV/Å | — | — |
| max atomic force norm | 2.600473 eV/Å | 5.767974 eV/Å | — | — |

Energy spread is roughly three orders of magnitude inside the preregistered
tolerance. Forces were identical across all three processes.

Bitwise identity was **not** observed and was **not** required: process 1
differs from processes 2 and 3 in the last bits of the energy only. This is the
behaviour the determinism contract anticipated when it declined to demand
bitwise equality, and the tolerance was fixed before any number existed.

Every call satisfied: finite energy, forces shaped `(N, 3)`, all force
components finite, atom count and order preserved, and **input coordinates
byte-identical before and after**. No exceptions and no warnings.

## The two endpoint energies must not be compared

The cation and neutral differ in atomic composition — the cation carries one
extra proton — so their absolute energies share no common reference. The
roughly 11.4 eV difference between them is **not** a deprotonation energy and
must never be reported, plotted, or stored as one.

The only legitimate deprotonation energy in this project comes from PySCF
B3LYP-D3(BJ)/def2-SVP endpoint energies through the frozen formula. No AIMNet2
number may enter it.

## Cache isolation earned its keep

This is the most operationally important finding of the run.

Despite `compile_model=False`, the run wrote **66 files totalling 9,966,538
bytes**, and a large share of them are TorchInductor artifacts — compiled
kernels, `aotautograd` entries, and `fxgraph` cache entries. AIMNet2 exercises
`torch.compile` internally regardless of that flag.

Every one of those bytes landed inside the attempt-specific isolated root
because `TORCHINDUCTOR_CACHE_DIR`, `TRITON_CACHE_DIR`, `CUDA_CACHE_PATH`,
`TORCH_HOME`, `XDG_CACHE_HOME`, `HF_HOME`, and `TMPDIR` were redirected before
any import.

Without that redirection this run would have written roughly ten megabytes of
compiled artifacts into a **shared account's** global cache. The isolation plan
was not defensive paperwork; it prevented a real side effect.

Proof, before versus after:

```text
aimnet cache        1 file,   8,836,941 bytes   unchanged
torch cache         2 files,    109,872 bytes   unchanged
triton cache        1 file,      26,560 bytes   unchanged
nv cache          682 files, 26,405,248 bytes   unchanged
huggingface cache   absent before and after
model weight        bytes and SHA256 unchanged
download detected   no
```

The isolated root was inventoried and then removed.

## GPU discipline

GPU state was re-read immediately before the run rather than reused from the
Phase 9A-R observation. Two devices were occupied by other users' jobs; one free
device was selected and used. No job was preempted, no second device was tried,
and there was no background waiting.

## Element coverage is only partially established

The calculator exposed no `implemented_species` attribute under any inspected
name, so a full coverage enumeration was **not** obtained.

What was established is narrower and empirical: with `validate_species=True` in
force, the model accepted and evaluated `C`, `F`, `H`, and `N`. That covers this
candidate and all four Phase 7 smoke candidates, but it says nothing about `O`,
`S`, `Cl`, or `Br`, which the 71 labels, the 50 acquisition candidates, and the
full 401,856-candidate pool require.

Coverage for those elements remains unverified and must not be assumed from
published documentation.

## An observation worth carrying forward

The neutral endpoint shows a maximum force component of **5.73 eV/Å** against
the cation's **2.23 eV/Å** — roughly 2.6 times larger on the endpoint that
carries the singlet carbene.

Both values are large, which is expected: these are MMFF94 force-field
geometries evaluated on a quantum-chemical surface, and large residual force is
exactly the gap a preoptimizer would close. The asymmetry is the interesting
part, and it is consistent with a force field describing a divalent carbene
centre poorly.

This is a single observation on a single molecule. It is **not** evidence about
AIMNet2's accuracy at the carbene, and it is recorded as a hypothesis to test in
Phase 9B, not as a finding.

## What this run proves

```text
the local _0 weight loads offline from an explicit path
C, F, H, N run under validate_species=True
cation charge +1 and neutral charge 0 pass through explicitly
the energy and force interface works and returns eV and eV/A
single-point inference reproduces within 2.4e-7 eV on this hardware
offline mode plus an explicit path fully blocked downloading
inference writes substantial cache, and redirection contains it
```

## What this run does not prove

```text
AIMNet2 is accurate for NHC geometry
the C2 carbene centre is inside its training domain
AIMNet2 preoptimization is faster than direct PySCF
both routes reach the same local minimum
element coverage beyond C, F, H, N
readiness for batch production
any ensemble uncertainty
any new high-fidelity label
```

With one ensemble member there is **no ensemble uncertainty**. The
reproducibility measured here is single-member repeatability and must never be
presented as an uncertainty estimate.

## Scientific position, unchanged

Phase 8B remains a rejected execution incident with zero endpoints and zero DFT
labels. High-fidelity labels remain **71**. The legacy project's recorded median
**1.10x** preoptimization speedup remains the best available prior for what
Phase 9B would measure, and non-promotion remains a likely and legitimate
outcome.

A passing interface characterization is not a scientific result.

## Next gate

Phase 9B requires a new document-first plan, a new
candidate/request/attempt/root/permit authority chain, and separate explicit
authorization. Because only one ensemble member exists, the Phase 9B plan must
additionally carry stricter structural integrity checks, explicit C2/N1/N3 bond
checks, proton identity and migration checks, maximum step and maximum
displacement gates, the direct-PySCF control, residual-step and basin
comparison, and an explicit record that no ensemble uncertainty exists.
