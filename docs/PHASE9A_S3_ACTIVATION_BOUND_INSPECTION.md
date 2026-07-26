# Phase 9A-S3 — MLFF-Activation-Bound Installed-Source Inspection

**Status: `inconclusive`. The loader decision is still `unresolved`.**

Attempt `phase9a-s3-v001`, one authorized SSH invocation, one used. Phase 9A-S
stays `inconclusive_due_to_inspection_error` and Phase 9A-S2 stays
`ambiguous_match`; neither is modified.

The call did settle the provenance question that blocked Phase 9A-S2, and it
stopped one stage later, on a defect in my own interpreter enumeration.

## What the activation script binds

`mlff.sh` was located by listing the registered environment-script directory —
exactly one candidate — and authenticated before it was parsed:

```text
path            <REMOTE_PROJECT_ROOT>/env/envs/mlff.sh
bytes           783
mode            -rw-r--r--
regular file    yes
symlink         no
sha256          9a8ae2b2fff81b317ef2569af51f9fa374b071551dfa4cb3e2948fe598e437b6
```

It was **never sourced**. Static text analysis alone resolved the binding:

```text
line 13   conda activate "<MLFF_ENV_ROOT>"     literal quoted absolute prefix
```

```text
distinct environment roots      1
dynamic path computation        none
command substitution            none
install / download / write      none
unfrozen shell variables        none
unclassified binding lines      none
venv activation                 none
blocking conditions             none
```

So the primary provenance rule in section 1 is satisfied by measurement:
`mlff.sh` binds exactly one environment root, and it binds it with a literal
path written in the authenticated file itself. **Phase 9A-S2's ambiguity is
resolved** — not by comparing package versions, which were identical in two
environments, but by the byte identity and static content of the activation
script, which names one of them and not the other.

## One caveat, recorded rather than buried

`mlff.sh` sources one script outside the registered directory:

```text
<CONDA_DISTRIBUTION_ROOT>/etc/profile.d/conda.sh
bytes    2479
sha256   c25916625c93f3c2...
regular file, not a symlink
```

A conda activation script has to source that file to define the `conda` shell
function at all. It supplies the mechanism; the target is the literal prefix on
line 13 of `mlff.sh`. So the binding does not consume anything from it, and the
inspector did not treat it as blocking — but it is authenticated by stat and
digest, and reported here rather than silently absorbed, because a modified
`conda.sh` could in principle redefine `conda`. A reviewer who wants the strict
reading of section 5 can overrule the classification on this evidence.

## Where it stopped

```text
stage       interpreter enumeration
found       <MLFF_ENV_ROOT>/bin/python3.1
            <MLFF_ENV_ROOT>/bin/python3.11
outcome     two names matched, so the inspector refused to choose and stopped
```

The glob `python3.*` matched two *names*, and the count was taken before any
deduplication. A conda `bin/` carries `python`, `python3`, `python3.1` and
`python3.11` as links onto one real binary, so this is two names for one file,
not two interpreters.

The server is not ambiguous here. **My enumeration was.** This is the same class
of error as Phase 9A-S2's `+cu128` criterion: the stop rule fired correctly on a
condition my own code manufactured.

Phase 9A-S2's registered receipt already shows what the deduplicated count is:
it enumerated the same directories with the broader glob `python3*` and
deduplicated by realpath *before* counting, and recorded exactly two survivors
per environment — the interpreter and its `-config` shim. Had `python3.1` been a
distinct file, it would have recorded three. That is an inference from an
earlier receipt, not a Phase 9A-S3 measurement, so it does not lift this attempt
out of `inconclusive`.

The fix is one line of ordering: deduplicate candidates by `(device, inode)`
before counting, require the survivor to be a regular file, and record the
realpath of every rejected name.

## What was therefore not established

```text
stages not reached     version probe, torch local version, seven-point gate,
                       aimnet source, ase source
activation_bound_unique_match   false (never evaluated)
aimnet source files read        0
ase source files read           0
twenty source questions         0 answered
ase interface questions         0 answered
loader_decision                 unresolved
production constructor          none
```

Under section 10 the conclusion grade can only be `source_proven` or
`unresolved`. It is `unresolved`. No loader was written and no A-versus-B choice
was made.

## Server invariance

```text
activation script before == after     true
traced scripts before == after        true
sources before == after               true
caches before == after                true
installed packages before == after    true
__pycache__ count before == after     true
weight stat before == after           true
third-party modules imported          none
```

Weights were stat-ed only: content was never opened and no digest was
recomputed. `aimnet2_wb97m_d3_0.pt` remains 8836941 bytes, matching the
registered size. Nothing was created, no mtime changed, no bytecode was written,
no GPU was touched, and no network connection was made. The inspector ran under
`-I -B` with all four offline flags and `PATH=/usr/bin:/bin`.

## Local validation, before the call

The authorization required the inspector to be compiled, AST-parsed, and
actually executed against simulated trees first. It was: **103 checks over 18
scenarios**, covering unique binding, absent script, symlinked script, content
drift, missing bound path, multiple bound environments, dynamic path
computation, unfrozen shell state, an install action in the script, missing
interpreter, interpreter realpath escaping the environment root, package version
mismatch, python version mismatch, missing `torch/version.py`, a wrong local
version segment, missing AIMNet source, and cross-module call-chain closure —
plus three structural proofs: that no default interpreter can ever be
substituted, that identical versions cannot select the environment, and that
every unresolved state stops before any AIMNet source is read.

That harness found a real defect before anything was sent: the cache
before/after snapshot compared different key sets once the package roots became
known, which would have made the `__pycache__` proof vacuous on the real run. It
was split into two same-keyed snapshot pairs. That is why the invariance table
above means something.

It did not catch the `python3.1` case, because the simulated environments were
built with a single interpreter name. A simulated `bin/` mirroring a real
conda layout would have caught it.

## What did not change

```text
runner source schema        v7
runner_source_sha256        d7060a31...9c22
v7 identities               prepared_not_authorized
execution gates             eleven, all false
production loader           not implemented
identity rebaseline         none
real computation            none
```
