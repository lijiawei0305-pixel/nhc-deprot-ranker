# Phase 9B execution — stopped before any irreversible action

**Status: `hard_stop_no_single_interpreter`. Nothing was deployed, no permit was
placed or consumed, no process was started, and the server is unchanged.**

The one-shot execution authorization requires, in its section 11, a single exact
interpreter able to run the whole assisted route. That interpreter does not
exist on the compute host.

## What was checked, and how

A read-only probe enumerated every conda environment under the project's env
root, collapsed interpreter names by `(st_dev, st_ino)` **before** counting, and
asked each surviving interpreter to report its own installed distributions
through `importlib.metadata`. Nothing was imported: not `torch`, not `ase`, not
`aimnet`, not `pyscf`. Nothing was written, installed, or downloaded.

`mlff.sh` was re-verified first and had not drifted: 783 bytes, sha256
`9a8ae2b2…e437b6`.

## The finding

```text
environment   python     torch   aimnet  ase     pyscf   geometric  pyscf-dispersion
mlff          3.11.15    2.8.0   0.2.0   3.29.0  absent  absent     absent
aimnet2       3.11.15    2.8.0   0.2.0   3.29.0  absent  absent     absent
mace          3.11.15    2.8.0   absent  3.29.0  absent  absent     absent
gpupyscf      3.11.15    absent  absent  absent  2.13.1  1.1.1      1.5.0
```

**The MLFF stack and the PySCF stack are installed in disjoint environments.**
Every version that is present is exactly the frozen one — `pyscf 2.13.1`,
`geometric 1.1.1`, `pyscf-dispersion 1.5.0` in `gpupyscf`; `torch 2.8.0`,
`aimnet 0.2.0`, `ase 3.29.0` in `mlff`. Nothing has drifted. They simply do not
coexist.

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
3  add the MLFF stack to the gpupyscf environment     same
4  split Route A into two processes with a durable,   a real design change to the
   hash-closed geometry handoff between them          handoff contract and the permit
```

Option 4 is the only one that needs no install, but it is a change to the frozen
handoff contract and to what the assisted permit binds, so it is a design round,
not an execution round.

Full evidence, with versions and digests, is in
`docs/PHASE9B_PRE_EXECUTION_INTERPRETER_AUDIT.json`.
