# Phase 9A-R — Read-Only AIMNet2 Server Preflight Report

## Outcome

The preflight **passed**. AIMNet2, torch, and ase are installed and importable on
the target host, the calculator accepts total charge and multiplicity
explicitly, and one model weight is present and hashed.

Two blocking findings were recorded. Neither is a failure of the inspection;
both are facts the plan must now accommodate.

This report establishes what exists. It does not evaluate the model, does not
measure anything, and authorizes nothing.

## Authorization boundary for this round

The user authorized exactly one read-only server preflight. Performed: host and
interpreter facts, GPU presence, package import and version inspection, torch
capability queries, API signature inspection, weight enumeration and hashing,
and a cache-mutation guard.

Not performed, and prohibited throughout: installing, upgrading, downloading a
weight, populating a cache, loading a model, constructing an ASE `Atoms` with a
calculator, evaluating energy or forces, running any optimization, constructing
a PySCF `Mole`, calling any compute kernel, writing to the server, modifying the
environment, or creating bytecode.

Two SSH invocations were used: one reachability check and one inspection.
Campus-direct succeeded; the SOCKS5 fallback was not needed.

Machine evidence: `docs/PHASE9A_R_AIMNET2_PREFLIGHT_V001.json`.

## Side-effect guard

The largest risk in this inspection was that importing the package or touching
the registry would silently fetch a weight. The guard was set before anything
was imported — `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `HF_DATASETS_OFFLINE`,
`PYTHONDONTWRITEBYTECODE=1`, and `python -I -B` — and the weight cache was
snapshotted before and after.

```text
cache before == cache after     (identical filename, byte size, and mtime)
download detected               no
new bytecode detected           no
```

The inspection changed nothing on the server.

## Environment, verified live

```text
kernel        Linux 6.17.0-35-generic
logical CPUs  112
python        3.11.15
torch         2.8.0+cu128    CUDA 12.8    8 devices visible
ase           3.29.0
aimnet        0.2.0
accelerator   8x Tesla V100-SXM2-32GB, Volta sm_70
```

`sm_70` is present in the torch architecture list, so the Volta constraint that
governs this stack is satisfied. This confirms the stale 2026-07-14 legacy
record still holds today; it is no longer an assumption.

The host is shared and other users' GPU jobs are currently running. Any future
work must not disturb them, and must not assume a free device.

## API surface

```text
AIMNet2ASE(base_calc='aimnet2', charge=0, mult=1, validate_species=True)
AIMNet2Calculator(model='aimnet2', nb_threshold=120, needs_coulomb=None,
                  needs_dispersion=None, device=None, compile_model=False,
                  compile_kwargs=None, train=False, ensemble_member=0,
                  revision=None, token=None)
```

Three facts follow directly.

**Charge handling is solved.** The ASE calculator accepts `charge` and `mult` at
construction. The cation can be built with `charge=+1, mult=1` and the neutral
with `charge=0, mult=1`, explicitly, with nothing inferred from filenames. This
was the single most dangerous silent-failure mode in the design, and the
interface supports doing it correctly.

**Ensembling is supported by the API but not by the assets.** An
`ensemble_member: int = 0` parameter exists, so the code path is real. The
weights are the problem — see below.

**There is a live download surface.** `revision` and `token` parameters mean the
default model string can trigger a remote fetch. Nothing downloaded during this
inspection because offline mode was pinned first. Any future run must pin
offline mode and an explicit local weight path rather than relying on the
default `'aimnet2'` string.

## Weights

```text
present:
  aimnet2_wb97m_d3_0.pt
    bytes  8,836,941
    sha256 f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28

absent:
  aimnet2_wb97m_d3_1
  aimnet2_wb97m_d3_2
  aimnet2_wb97m_d3_3
```

This confirms Phase 9A Finding 7 from live evidence rather than from stale
notes. Exactly one ensemble member exists locally, and downloading the other
three is prohibited.

## Blocking finding 1 — the ensemble is incomplete

`docs/AIMNET2_MODEL_IDENTITY.md` froze two permitted ensemble strategies.
Neither survives contact with the assets:

- **Strategy A**, ensemble-mean optimization, requires four members. Not
  available.
- **Strategy B**, single-member optimization with ensemble validation, requires
  the other members to validate against. There is nothing to disagree with, so
  the disagreement diagnostic collapses to nothing.

This matters more than it might appear. Per-atom ensemble disagreement at the
C2 carbene centre was the designed early-warning signal for the one chemistry
this model is least likely to have seen. Without it, that signal is gone, and
the only remaining check on carbene distortion is structural validation plus
whatever the PySCF residual optimization has to undo.

The design does not silently degrade to a third strategy. This is a user
decision, stated below.

## Blocking finding 2 — the default model string can fetch

Recorded so it cannot be forgotten: any future implementation must construct the
calculator from an explicit local weight path with offline mode pinned, and must
verify the weight SHA256 against
`f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28` before use.
A default-string construction is a prohibited download path, not a convenience.

## Deliberately not established

Three facts were left unmeasured because measuring them would have crossed the
read-only boundary:

```text
declared element coverage    requires loading the checkpoint
energy output unit           requires an evaluation
force output unit            requires an evaluation
deterministic-mode support   requires an evaluation
```

Element coverage is therefore still `expected_sufficient_pending_verification`.
The legacy record and the published documentation both indicate eV and eV/Å for
the ASE interface, but this preflight did not confirm it by measurement, and the
handoff contract continues to require explicit, verified conversion.

Establishing these needs a minimal, separately authorized inference test — one
small molecule, one energy call — which is a different authorization from this
one because it runs the model.

## What this changes

The environment question from `docs/NEXT_PHASE_AUTHORIZATION.md` is partly
answered. The `mlff` environment exists, activates through the project's own
explicit script without touching `~/.bashrc`, and holds a working stack. Whether
this project is *permitted* to use it for production work remains a policy
decision, unchanged by this inspection.

The route is not blocked on missing software. It is constrained by a
single-member ensemble.

## Scientific position, unchanged

Nothing here produces a geometry, an energy, or a label. Phase 8B remains a
rejected execution incident with zero endpoints and zero DFT labels; the
high-fidelity label count remains **71**. The legacy project's recorded median
**1.10x** preoptimization speedup remains the best available prior for what
Phase 9B would measure, and non-promotion remains a likely and legitimate
outcome.

A passing preflight is not a scientific result. It only means the experiment is
physically possible to attempt.

## Next gate

Phase 9B requires a new authority chain and separate explicit authorization, and
should not be requested until the user resolves the ensemble question:

1. proceed with a single deterministic member, accepting that no ensemble
   uncertainty and no C2 disagreement signal will exist;
2. treat the incomplete ensemble as a blocker and stop the AIMNet2 route here;
3. authorize a separate, minimal inference test first, to measure units, element
   coverage, and determinism on one small molecule before committing to a paired
   two-endpoint smoke.
