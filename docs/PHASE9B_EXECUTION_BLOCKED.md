# Phase 9B execution — stopped before any irreversible action

**Current status: `hard_stop_no_validated_single_interpreter`. Nothing was
deployed, no permit was placed or consumed, and no Phase 9B route process was
started.**

Phase 9B-U1 subsequently created one new, isolated prefix carrying both package
stacks, but its capability validation failed closed and the prefix is retained
as `failed_incomplete_environment`. It is not an accepted interpreter and may
not be used. All environments that existed before U1 remain unchanged. See
`docs/PHASE9B_UNIFIED_ENVIRONMENT_BUILD_REPORT.md`.

A separately authorized, new-identity U2 environment attempt passed its
document-first gate before any server write. Its plan is
`docs/PHASE9B_UNIFIED_ENVIRONMENT_V002_PLAN.md`. Environment validation alone
did not open the scientific-execution blocker or any public execution gate.

U2 has now completed as `rejected_environment`. Its exact stack, native imports,
frozen four-call capability sequence, cache, weight, and target-after evidence
passed, but the formal protected snapshot gate did not: Stage 0 omitted the
top-level `state` key that Stage 4 emitted. The unchanged physical tree evidence
does not permit a post-hoc canonical-SHA reinterpretation. See
`docs/PHASE9B_UNIFIED_ENVIRONMENT_V002_BUILD_REPORT.md`. No validated single
interpreter therefore exists.

The one-shot execution authorization requires, in its section 11, a single exact
interpreter able to run the whole assisted route. That interpreter does not
exist on the compute host.

## What was checked, and how

The first pass only examined `<REMOTE_PROJECT_ROOT>/env/conda/*` — four
environments. That is not the server, and the conclusion was re-derived on a
proper search before being relied on.

The second pass located environments by **their own markers** rather than by a
guessed layout: every `conda-meta` directory, every `pyvenv.cfg`, and every
`site-packages/{pyscf,aimnet,ase,torch}` directory, across `/home`, `/opt`,
`/usr/local`, `/srv` and `/mnt` to depth 9. Interpreter names were collapsed by
`(st_dev, st_ino)` before counting, and each surviving interpreter reported its
own versions through `importlib.metadata`. Nothing was imported, written,
installed, or downloaded. The walk completed inside its budget: 31,879 nodes in
22.8 s, no truncation.

It was then cross-checked against **conda's own registry**, which is
authoritative regardless of where an environment lives.

```text
environment roots found        14
interpreters probed            27
conda registry entries         11   -- every one of them probed
non-conda virtualenvs found    0
home directories               1
```

## Every environment on the host before Phase 9B-U1

```text
environment                            python    torch        aimnet  ase     pyscf   geom   disp
<SHARED_MINIFORGE_ROOT>                3.13.13   -            -       -       -       -      -
<SHARED_MINIFORGE_ROOT>/envs/cp2kcpu   3.14.6    -            -       -       -       -      -
<SHARED_MINIFORGE_ROOT>/envs/fairchem  3.11.15   2.4.1+cu121  -       3.29.0  -       -      -
<SHARED_MINIFORGE_ROOT>/envs/mlff      3.11.15   -            -       -       -       -      -
<SHARED_MINIFORGE_ROOT>/envs/mlip      3.11.15   2.4.1+cu121  -       3.29.0  -       -      -
<SHARED_MINIFORGE_ROOT>/envs/molecular 3.11.15   -            -       3.28.0  2.13.1  1.1.1  1.5.0
<SHARED_MINIFORGE_ROOT>/envs/periodic  3.11.15   -            -       3.28.0  -       -      -
<REMOTE_HOME>/miniforge3               3.13.13   -            -       -       -       -      -
<REMOTE_HOME>/miniforge3/envs/ff       3.12.13   -            -       -       -       -      -
<REMOTE_PROJECT_ROOT>/env/conda/aimnet2 3.11.15  2.8.0        0.2.0   3.29.0  -       -      -
<REMOTE_PROJECT_ROOT>/env/conda/gpupyscf 3.11.15 -            -       -       2.13.1  1.1.1  1.5.0
<REMOTE_PROJECT_ROOT>/env/conda/mace   3.11.15   2.8.0        -       3.29.0  -       -      -
<REMOTE_PROJECT_ROOT>/env/conda/mlff   3.11.15   2.8.0        0.2.0   3.29.0  -       -      -
```

At the time of this audit, `pyscf` existed in exactly **two** site-packages
trees; `aimnet` in exactly **two**, with no intersection. Phase 9B-U1 later
created an additional prefix containing both, but that new prefix failed its
validation contract and does not supersede this audit with an accepted runtime.

Note the shared `<SHARED_MINIFORGE_ROOT>/envs/mlff` is a different, essentially
empty environment from the project's own `env/conda/mlff` — which is exactly why
`mlff.sh` pins a literal project-internal prefix.

## The closest environment

`<SHARED_MINIFORGE_ROOT>/envs/molecular` is the nearest miss:

```text
has       pyscf 2.13.1, geometric 1.1.1, pyscf-dispersion 1.5.0, ase 3.28.0
missing   torch, aimnet
```

Its ASE is **3.28.0**, not the frozen 3.29.0, so it would need two additions and
one upgrade — not one addition.

## Limits of this search, stated plainly

```text
symlinked directories were not followed, so an environment reachable only
  through a symlink pointing outside the search roots would be missed; its
  real location would still be walked if it lies under one of them
depth was capped at 9 from each search root
a third, deeper gap-closure pass truncated at its 800,000-directory visit cap,
  so its package inventory is partial and is NOT the basis of any conclusion
  here -- it never reached `molecular`
24 directories were unreadable during that truncated pass
```

What is nevertheless settled: conda's own registry lists 11 environments and
every one was probed; the completed walk found `pyscf` in exactly two
site-packages and `aimnet` in exactly two, with no overlap; there is one home
directory and no non-conda virtualenv anywhere.

## Why that is fatal to the paired experiment

Route A runs AIMNet2 preoptimization and then PySCF **inside one guarded worker
process**. That is not an implementation detail: it is what makes the byte-closed
handoff meaningful, and it is what the permit binds. With the two stacks in
separate environments, no interpreter can execute the route.

Route D alone would run — `gpupyscf` carries the complete PySCF stack. It is
deliberately **not** run. A direct-only result is not a paired experiment, and
presenting it as one is explicitly forbidden by section 11.

## What was not done in the blocked execution attempt, on purpose

```text
installing or upgrading a package        forbidden by the authorization
combining two environments on a PYTHONPATH  forbidden; also unsound
running direct alone as a "paired" result   forbidden
waiting, retrying, or relaxing a gate       forbidden
```

The authorization also says this must not be discovered *after* a permit is
consumed. It was found before deploy, before placement, and before launch, so no
permit was spent and no remote root exists.

## Irreversibility of the blocked execution attempt

```text
irreversible action taken     none
permits placed                none
permits consumed              none
remote roots created          none
remote processes started      none
files written on the server   none
public main execution gates   eleven, all false
```

The only remote action in this round was one read-only metadata probe under
`python -I -B` with all four offline flags and `PATH=/usr/bin:/bin`.

## The original safe next action and its outcome

Decide how the assisted route should obtain one interpreter, then re-authorize.
The options are a decision for the project owner, not for this agent, because
each changes the frozen environment identity that Phase 9A-R through 9A-S4
established:

```text
1  create a new environment carrying both stacks      needs an install authorization
                                                      and a fresh environment audit
2  add the PySCF stack to the mlff environment        needs an install authorization;
                                                      changes the audited env identity
2b add torch+aimnet to `molecular` and upgrade its    needs an install authorization;
   ase 3.28.0 to 3.29.0                               two additions and one upgrade
3  add the MLFF stack to the gpupyscf environment     same
4  split Route A into two processes with a durable,   a real design change to the
   hash-closed geometry handoff between them          handoff contract and the permit
```

Option 4 is the only one that needs no install, but it is a change to the frozen
handoff contract and to what the assisted permit binds, so it is a design round,
not an execution round.

The project owner selected option 1 and authorized Phase 9B-U1. The exact
installation completed, but the capability harness observed four calculator
invocations while it expected two, and portable native/cache/endpoint evidence
was not completed. U1 therefore stopped with the new v001 prefix retained and
unusable. The present safe action is again to stop. A retry requires a separately
authorized v002 target and a preregistered resolution of calculator-invocation
versus property-read counting; v001 may not be reused.

Full evidence is in `docs/PHASE9B_SERVER_WIDE_ENVIRONMENT_SEARCH.json` (the
server-wide search this conclusion rests on) and
`docs/PHASE9B_PRE_EXECUTION_INTERPRETER_AUDIT.json` (the earlier,
project-scoped pass, retained for the record).

## U3 qualified-metrology authorization

U1 and U2 remain unusable retained attempts. U3 is separately authorized under
`docs/PHASE9B_UNIFIED_ENVIRONMENT_V003_PLAN.md`, but it cannot create its new
resources until a document-first PR has merged and the six-object read-only
measurement qualification passes. Even a validated v003 would not authorize
Phase 9B science: Unified Environment Identity Integration would remain the
only next stage. Postflight and closed-gate rehearsal are still blocked.

That U3 gate has now run once and failed before environment creation. All six
A/B schema and stable-projection comparisons were internally equal, but the
qualified helper returned `state=invalid` instead of `present` for every
protected object. The v003 resources remained absent and no build or capability
operation began. U3 is retained as `failed_before_environment_creation` and
cannot enter Identity Integration. No validated unified environment exists.

U4 is now authorized only through the staged contract in
`PHASE9B_UNIFIED_ENVIRONMENT_V004_PLAN.md`. Its document-first symlink-aware
helper must merge before any SSH; then one read-only Q4 qualification must pass
all six objects before v004 can exist. This authorization does not unblock
Identity Integration, Postflight, rehearsal, permit, or science.
