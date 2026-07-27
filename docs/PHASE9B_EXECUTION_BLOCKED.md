# Phase 9B execution — stopped before any irreversible action

**Status: `hard_stop_no_single_interpreter`. Nothing was deployed, no permit was
placed or consumed, no process was started, and the server is unchanged.**

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

## Every environment on the host

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

`pyscf` exists in exactly **two** site-packages trees; `aimnet` in exactly
**two**. **The two sets do not intersect.** No environment anywhere on the host
carries both stacks.

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

## What was not done, on purpose

```text
installing or upgrading a package        forbidden by the authorization
combining two environments on a PYTHONPATH  forbidden; also unsound
running direct alone as a "paired" result   forbidden
waiting, retrying, or relaxing a gate       forbidden
```

The authorization also says this must not be discovered *after* a permit is
consumed. It was found before deploy, before placement, and before launch, so no
permit was spent and no remote root exists.

## Irreversibility

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

## The single safe next action

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

Full evidence is in `docs/PHASE9B_SERVER_WIDE_ENVIRONMENT_SEARCH.json` (the
server-wide search this conclusion rests on) and
`docs/PHASE9B_PRE_EXECUTION_INTERPRETER_AUDIT.json` (the earlier,
project-scoped pass, retained for the record).
