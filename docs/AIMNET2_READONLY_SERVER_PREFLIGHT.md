# AIMNet2 Read-Only Server Preflight Plan

## Status

This document is a **plan only**. Phase 9A writes it; Phase 9A does not execute
it. Executing it is Phase 9A-R and requires separate, explicit user
authorization naming a read-only server inspection.

Nothing in this file is authorization for SSH, a server write, a model
download, a dependency install, or any inference.

## Purpose

Establish, from the real environment rather than from memory or model naming
conventions, whether an AIMNet2 preoptimization stage is physically possible on
the target machine, and record the exact identity of every asset it would use.

The preflight answers questions of fact. It does not evaluate the model, does
not benchmark it, and cannot promote it.

## Why this cannot be assumed

`AGENT.md` prohibits installing or upgrading dependencies on the server. The
entire AIMNet2 route therefore depends on assets that must already exist. A
model name is not evidence that weights exist; an import that succeeds is not
evidence that a specific ensemble member is present; and a weight file present
on disk is not evidence that it matches the published checkpoint.

The preflight must produce identity, not plausibility.

## Hard prohibitions during preflight

The following are forbidden for the entire inspection, without exception:

```text
install a package
upgrade a package
download a model weight
populate or warm any cache
construct an ASE Atoms object and attach a calculator
load a model onto GPU
evaluate an energy
evaluate forces
run any geometry optimization
construct a PySCF Mole
call any SCF, gradient, or optimizer kernel
write anything into the project tree
modify the environment
create bytecode
```

If a plain `import` of any inspected package would itself trigger a network
fetch, a weight download, or a cache write, the inspection **stops there** and
reports that fact. It does not proceed by allowing the side effect. Prevention
is attempted first via environment variables that disable network and bytecode
(`PYTHONDONTWRITEBYTECODE=1`, offline/hub-offline flags appropriate to the
installed stack); if prevention cannot be proven in advance, the import is not
performed.

## Environment discipline

Consistent with the existing server rules:

- enter the project root explicitly;
- source only the project's explicit environment script;
- never source `~/.bashrc`;
- set `PYTHONDONTWRITEBYTECODE=1`;
- use `python -I -B` for any inspection process.

## Inspection A — host and interpreter facts

```text
hostname
whoami
pwd
python --version
which python
which uv
which conda
nvidia-smi
```

`nvidia-smi` is read-only and is used to record device presence, driver, and
whether other users' jobs are occupying the GPUs. Its output must not be used
to justify starting work; Phase 9A-R starts nothing.

## Inspection B — package presence and identity

Read-only import and attribute inspection, no object construction:

```text
import torch
import ase
import aimnet
```

For each, record:

```text
package version
package filesystem path
```

For `torch` additionally record, without allocating a device context:

```text
torch.version.cuda
torch.cuda.is_available()
torch.cuda.device_count()
```

`torch.cuda.is_available()` is a capability query. If the installed stack makes
even that call allocate a context, it is skipped and reported as
`not_inspected_to_avoid_side_effect`.

If `import aimnet` fails, that is a complete and acceptable result. It means
the AIMNet2 route is blocked on this host, and the correct output is a blocked
report, not a workaround.

## Inspection C — model registry and weights

Record, without loading any model:

```text
model registry names available
weight cache path
weight filenames
weight byte sizes
weight SHA256
model version strings
declared element coverage
charge input mechanism
energy output unit
force output unit
CPU support
GPU support
deterministic-mode support
ensemble mean energy support
ensemble mean force support
member disagreement availability
license
```

The priority target is the official `wB97M-D3` family and its four ensemble
members:

```text
aimnet2-wb97m-d3_0
aimnet2-wb97m-d3_1
aimnet2-wb97m-d3_2
aimnet2-wb97m-d3_3
```

Their presence must be established from the filesystem and registry, never from
the name alone.

### If a different official weight is present

Record exactly what exists, compute its SHA256, and report the difference from
the priority target. **Do not substitute it and proceed.** Model choice is
frozen at AIMNet2; the specific weight is not yet frozen, and selecting it is a
user decision made after seeing the audit.

### If no weight is present

Report `weights_absent`. Do not download. A missing weight blocks Phase 9B and
is resolved by a user decision, not by acquisition during an inspection.

## Inspection D — API surface

Determine, by signature inspection only (`inspect.signature`, docstrings,
module attributes — never by calling):

- the documented entry point for constructing a calculator;
- the exact parameter name and type by which **total molecular charge** is
  supplied;
- whether multiplicity or spin is accepted at all;
- the units of returned energy and forces;
- whether an ensemble-mean interface exists, or whether ensembling must be done
  by the caller over individual members.

The charge mechanism is the single most important API fact for this project,
because the cation and neutral endpoints differ only by charge and one proton.
An interface that silently defaults to neutral would compute the wrong surface
for every cation, and the error would be invisible in the output geometry.

## Recorded output

The preflight produces one portable, checked-in evidence file containing only
non-private facts: versions, model identities, hashes, element coverage,
capability booleans, and pass/fail per check.

Private absolute paths, host identifiers, account names, PIDs, raw logs, and
molecular coordinates stay in the gitignored local area and never enter tracked
files.

## Fail-closed semantics

Any of the following ends the preflight with a blocked report, and none may be
worked around:

- a nonzero exit from any inspected command;
- an import that triggers a download or cache write;
- an absent package;
- an absent or unreadable weight;
- a weight whose SHA256 cannot be computed;
- a registry that does not expose the element coverage or charge mechanism;
- any drift from the recorded Phase 7 or Phase 8B server state;
- any output that would require writing to the project tree to obtain.

A blocked preflight is a successful preflight. It has established a fact.

## What the preflight cannot do

It cannot promote AIMNet2, cannot authorize Phase 9B, cannot establish that the
model is accurate for this chemistry, and cannot establish that the two-stage
pipeline is faster. Those require the Phase 9B paired smoke and its own
authorization.
