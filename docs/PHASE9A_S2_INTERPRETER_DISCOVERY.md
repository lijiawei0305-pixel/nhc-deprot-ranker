# Phase 9A-S2 — Exact MLFF Interpreter Discovery

**Result: `ambiguous_match`. Stopped after one SSH invocation, as required.**

Attempt `phase9a-s2-v001`. Phase 9A-S remains
`inconclusive_due_to_inspection_error` and is not modified.

## Local validation first

Section 六 of the authorization required the remote script to be exercised
locally before it was ever sent. It was: a harness built a simulated project and
home tree with fake interpreters answering the standard-library probe, and
covered thirty checks across seven scenarios — unique match, zero matches,
multiple matches, a partial version match, `PackageNotFoundError`, a
non-executable candidate, and specifically the `PosixPath + str` precedence error
that crashed Phase 9A-S.

The harness caught one real bug before any SSH: overlapping globs (`envs/*.sh`
and `*/*.sh`) listed each environment script twice, which would have misreported
how many exist. Fixed, re-validated, then sent.

## What the single invocation found

Eight candidate interpreters in bounded directories, four of them real
interpreters and four `python3.11-config` shims. Their own
`importlib.metadata` reports:

```text
<AIMNET2_ENV_ROOT>/bin/python3.11    3.11.15  aimnet 0.2.0  ase 3.29.0  torch 2.8.0
<MLFF_ENV_ROOT>/bin/python3.11       3.11.15  aimnet 0.2.0  ase 3.29.0  torch 2.8.0
<GPUPYSCF_ENV>/bin/python3.11        3.11.15  aimnet absent ase absent  torch absent
<MACE_ENV>/bin/python3.11            3.11.15  aimnet absent ase 3.29.0  torch 2.8.0
```

**Two environments carry the required stack, not one.** The authorization is
explicit that multiple matches means stop without spending the second SSH on a
guess, so the second invocation was not used.

## Why the authorized criteria matched zero

The required combination named `torch 2.8.0+cu128`.
`importlib.metadata.version("torch")` returns the **public** version `2.8.0`; the
`+cu128` local version segment lives in `torch.__version__`, which is only
reachable by importing torch — forbidden in this phase. So the strict
four-way match returned zero, and the ambiguity is visible only on the three
observable versions.

This is a defect in my matching criterion, not in the server. A future probe can
discriminate read-only by reading the torch `.dist-info` metadata or the
installed `torch/version.py` text, neither of which imports anything.

## Provenance, recorded but deliberately not used as a tie-breaker

The environment directory holds twenty-six scripts, including a legacy
AIMNet2 inspection line:

```text
install_aimnet2_d022.sh          finalize_aimnet2_d022.sh
download_aimnet2_models_d023.sh  inspect_aimnet2_models_d024a.sh
inspect_aimnet2_yaml_d024b1.sh   inspect_aimnet2_model_d024b2a.sh
inspect_aimnet2_model_d024b2a2.sh ... d024b2a3r2.sh
aimnet2.sh   mlff.sh   mace.sh   molenv.sh   gpupyscf via install_gpupyscf.sh
```

`inspect_aimnet2_model_d024b2a.sh` (34412 bytes, sha256 `67eaad24…`) pins
`PYTHON_BIN=<AIMNET2_ENV_ROOT>/bin/python` and a **different weight family**:
`aimnet2_2025_b973c_d3_{0..3}.pt`, 8839102 bytes each, in
`<REMOTE_PROJECT_ROOT>/env/model-cache/aimnet2-2025`. Our candidate weight is
`aimnet2_wb97m_d3_0.pt`, 8836941 bytes, in `<AIMNET_CACHE_ROOT>`. Different
family, different member count, different directory.

Phase 9A-R recorded activation as `project_explicit_mlff_env_script`, which points
at `mlff.sh`. So the two matching environments plausibly have different
provenance — `aimnet2` for the legacy D-022/D-023/D-024 line, `mlff` for Phase 9A.

**That reasoning is not used to break the tie.** It is an inference from prose and
file naming, and the authorization forbids proceeding on a guess. It is recorded
because it makes the next attempt cheap and well-targeted.

## An unexpected and material finding

The same script's status schema declares:

```text
mode=CPU_MEMBER0_MANUAL_EXACT_CLASSES_STRICT_STATE_DICT
weights_only_enforced=true
weights_only_false_fallback=false
official_load_model_called=false
```

The legacy line deliberately did **not** call the official loader. It constructed
exact classes and loaded a strict state dict by hand, under
`TORCH_FORCE_WEIGHTS_ONLY_LOAD=1`, with `AIMNET_MODEL_DOWNLOAD_AUTHORIZED=0` and
`AIMNET_CACHE_DIR` pointed at a non-existent path to make any download attempt
fail loudly.

That is directly relevant to the A-versus-B question for Phase 9B, and it leans
towards B — but it describes a *different* environment and a *different* weight
family than Phase 9A-I used, so it does not answer what Phase 9A-I did. It is
recorded as a lead, not as the answer.

## Server invariance

```text
cache before == cache after     true
files created                   none
mtimes changed                  none
bytecode written                none
third-party modules imported    none
network connections             none
```

Every candidate was probed with `-I -B`, all four offline flags set, and a
`PATH` limited to `/usr/bin:/bin`. The login interpreter drove the search only;
every version reported came from the candidate's own metadata.

> **Followed by Phase 9A-S3**, which resolved this ambiguity from the byte
> identity and static content of `mlff.sh` rather than from package versions,
> and then stopped one stage later on a separate enumeration defect. The
> result recorded on this page is unchanged. See
> `docs/PHASE9A_S3_ACTIVATION_BOUND_INSPECTION.md`.

## Next minimal test

One read-only invocation that:

```text
1  discriminates the two environments without importing torch, by reading
   torch/version.py text or the torch .dist-info METADATA under each
2  cross-checks the result against which environment `mlff.sh` activates
3  if and only if exactly one carries torch 2.8.0+cu128 AND is the one mlff.sh
   activates, proceeds under that interpreter's absolute path
4  reads aimnet/calculators/*.py and ase/optimize/{lbfgs,optimize}.py by
   importlib.metadata location, AST-analyses them, and snapshots before/after
```

It needs its own authorization and is not requested implicitly here.

## What did not change

```text
runner source schema        v7
runner_source_sha256        d7060a31...9c22
v7 request/manifest/permit  prepared_not_authorized
execution gates             eleven, all false
production loader           not written
identity rebaseline         none
real computation            none
```
