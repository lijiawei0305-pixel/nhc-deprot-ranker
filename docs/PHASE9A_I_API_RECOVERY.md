# Phase 9A-I API Recovery Audit

Performed before writing any production AIMNet2 adapter, to establish what the
Phase 9A-I run actually called rather than guessing from online documentation.

**Result: one decisive detail is not recoverable.** The production loader is
therefore not written in this round.

## What was searched

```text
git log --all -S "AIMNet2ASE("            planning docs only, no execution code
git log --all -S "load_model" -- src/     no execution code
working tree, including gitignored paths  no results/phase9a_i_* record
results/CLAUDE_HANDOFF_20260726.md        does not record the call
src/.../phase9a_i_inference.py            build_production_calculator is a stub:
                                          "no production calculator construction
                                           path exists yet"
local .venv                               aimnet is not installed; the package
                                          exists only on the server
```

Unlike Phase 9A-R, which committed `REMOTE_INSPECTOR_SOURCE` verbatim, the Phase
9A-I run carried its inference script inline over SSH and **that string was never
committed**. Nothing in the repository, in the ignored local records, or in the
registered evidence contains it.

## What IS recoverable, and is authoritative

Introspected from the real installed `aimnet 0.2.0` during Phase 9A-R and
recorded in `docs/PHASE9A_R_AIMNET2_PREFLIGHT_V001.json`:

```text
AIMNet2ASE(self, base_calc: AIMNet2Calculator | str = 'aimnet2',
           charge=0, mult=1, validate_species: bool = True)

AIMNet2Calculator(self, model: str | torch.nn.Module = 'aimnet2',
                  nb_threshold: int = 120,
                  needs_coulomb: bool | None = None,
                  needs_dispersion: bool | None = None,
                  device: str | None = None,
                  compile_model: bool = False,
                  compile_kwargs: dict | None = None,
                  train: bool = False,
                  ensemble_member: int = 0,
                  revision: str | None = None,
                  token: str | None = None)
```

Import path, recorded in `docs/AIMNET2_MODEL_IDENTITY.md`:

```text
from aimnet.calculators import AIMNet2ASE
```

Facts measured by the six calls, recorded in
`docs/PHASE9A_I_RESULT_V001.json`:

```text
loaded_from                        explicit_local_path
registry_string_used               false
compile_model                      false
device                             cuda:0
ensemble_member                    0
energy unit                        eV
forces unit                        eV/A, dtype float32
confirmed_by                       ase_calculator_interface
implemented_properties             energy, forces, free_energy, charges,
                                   stress, dipole_moment
implemented_species attribute      not exposed
atoms_info_charge_or_spin_present  false
elements confirmed empirically     C F H N, under validate_species=True
```

`atoms_info_charge_or_spin_present: false` is a real constraint: charge and spin
were **not** carried on `Atoms.info`, so they must come from the calculator
construction, which the `AIMNet2ASE` signature supports.

## The 10 audit questions

| # | Question | Answer |
|---|---|---|
| 1 | How the model was built from an explicit local `.pt` | **NOT RECOVERABLE** — see below |
| 2 | Import path | `from aimnet.calculators import AIMNet2ASE` |
| 3 | `AIMNet2ASE` signature | recovered verbatim, above |
| 4 | Where `charge`/`mult` enter | at `AIMNet2ASE` construction; not via `Atoms.info` |
| 5 | Base calculator then endpoint wrapper? | Yes — the signature takes `base_calc: AIMNet2Calculator`, so one calculator can back two wrappers |
| 6 | How energy/forces are read | the ASE interface; `implemented_properties` lists `energy` and `forces` |
| 7 | `compile_model=False`? | Yes, recorded — though 9A-I also proved it does **not** prevent a `torch.compile` cache |
| 8 | How `device` is passed | `AIMNet2Calculator(device=...)`, recorded as `cuda:0` |
| 9 | How ASE `LBFGS` should be used | **not established by 9A-I** — it ran no optimizer at all (`geometry_optimizations: 0`) |
| 10 | Any temporary compatibility patch | **UNANSWERABLE** — the script does not exist |

## The blocking ambiguity

`AIMNet2Calculator.model` is typed `str | torch.nn.Module`. The evidence records
that the weight came from an explicit local path and that no registry string was
used, but **not which of these two mechanisms carried it**:

```text
(a) AIMNet2Calculator(model="/abs/path/aimnet2_wb97m_d3_0.pt", device="cuda:0",
                      compile_model=False, ensemble_member=0)

(b) module = <torch.load or an aimnet helper>("/abs/path/aimnet2_wb97m_d3_0.pt")
    AIMNet2Calculator(model=module, device="cuda:0",
                      compile_model=False, ensemble_member=0)
```

This is not a stylistic difference. Every safeguard in this phase exists because
`model='aimnet2'` can resolve against a remote hub. If the `str` branch treats
**every** string as a registry key rather than checking for a filesystem path,
then choosing (a) would trigger exactly the hub lookup the whole design forbids —
on a shared account, offline flags set, with a permit already consumed.

Choosing between (a) and (b) from the prose in
`docs/PHASE9A_I_MODEL_WEIGHT_CLOSURE.md` would be an inference, not a recovered
fact. The instruction for this round is explicit that an unrecoverable API means
stop, and this is that case.

## Attempted and not resolved: Phase 9A-S

Phase 9A-S was authorized and executed on 2026-07-27 to settle this by reading
the installed source. It did not settle it. Two read-only SSH invocations were
used; the second ran cleanly and proved the server unchanged, but probed the
login interpreter rather than the `mlff` environment, so no `aimnet` source was
located. The ambiguity below therefore stands unchanged.

What 9A-S did establish: the weight is at `<AIMNET_CACHE_ROOT>/aimnet2_wb97m_d3_0.pt`
at exactly 8836941 bytes, the aimnet cache holds that file and nothing else, and
**no Hugging Face cache exists on the account at all** -- so whatever Phase 9A-I
did, it populated no hub cache. Details in
`docs/PHASE9A_S_INSTALLED_SOURCE_INSPECTION.md`.

## What would resolve it, cheaply and read-only

Any one of these settles it. All are read-only and load no model:

```text
1  inspect(aimnet.calculators.AIMNet2Calculator.__init__) source on the server,
   reading the branch that handles a `str` model
2  the aimnet 0.2.0 wheel or sdist for that same source, fetched anywhere
3  the shell history or job record of the Phase 9A-I run, if it survives
4  a one-line read-only SSH inspection printing the source of that branch
```

Option 4 is the smallest, and is the same class of action as the Phase 9A-R
preflight that has already been authorized and executed once. It needs its own
authorization; it is not requested implicitly here.

## Note on question 9

Phase 9A-I ran **no optimizer**: `geometry_optimizations: 0`. So the ASE `LBFGS`
usage cannot be recovered from 9A-I either, because it was never exercised. The
frozen optimizer contract (LBFGS, fmax 0.05 eV/A, 200 steps, 900 s) comes from
the Phase 9B plan, not from a measurement.

Unlike the loader, the LBFGS adapter can be written against the stable public ASE
API without guessing at a vendor-specific surface — `ase.optimize.LBFGS(atoms)`
with `run(fmax=..., steps=...)` and `attach()` is documented, long-stable, and
was already assumed by the frozen contract. It is the **AIMNet2 loader** alone
that is blocked.
