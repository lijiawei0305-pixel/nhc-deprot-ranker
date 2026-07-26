# Phase 9A-S2 — Installed Source Inspection

**Not performed.** The phase stopped at interpreter discovery with
`ambiguous_match`, and the authorization forbids spending the second SSH
invocation on a guess.

Two environments carry python 3.11.15, aimnet 0.2.0, and ase 3.29.0. The
`+cu128` local version segment that would separate them is not observable
without importing torch, which this phase forbids. Details and the next minimal
test are in `docs/PHASE9A_S2_INTERPRETER_DISCOVERY.md`.

## Consequences

```text
source files read                   0
AIMNet2Calculator.__init__ branch   unresolved
local path vs registry precedence   unresolved
.pt loading helper                  unresolved
network risk on the local branch    unresolved
A versus B for Phase 9B             unresolved
production constructor expression   none
ASE LBFGS static interface          unresolved
```

The twenty required source conclusions are not restated here as guesses. What is
already authoritative from Phase 9A-R introspection — both constructor signatures
verbatim, the import path, and the measured device, member, units, and element
coverage — remains in `docs/PHASE9A_I_API_RECOVERY.md`.

## One lead, recorded not acted on

A legacy server script in the *other* matching environment declares
`official_load_model_called=false` and
`mode=CPU_MEMBER0_MANUAL_EXACT_CLASSES_STRICT_STATE_DICT`, i.e. that line loaded
a strict state dict into hand-constructed classes rather than calling the
official loader. That leans towards option B, but it concerns a different
environment and a different weight family than Phase 9A-I used, so it is a lead
for the next inspection rather than an answer.
