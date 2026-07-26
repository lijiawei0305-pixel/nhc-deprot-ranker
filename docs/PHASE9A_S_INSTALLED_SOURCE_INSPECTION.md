# Phase 9A-S — Installed AIMNet 0.2.0 Source Inspection

**Status: incomplete. The loader decision is `unresolved`.**

The inspection ran read-only and left the server unchanged, but it probed the
wrong interpreter, so it located no `aimnet` source. The blocking question is
therefore still open and no production loader was written.

## What was authorized and what was used

```text
authorized     at most two SSH invocations, read-only
used           two
  1  connectivity and discovery   -- crashed on a local bug in my own script
                                     before printing (PosixPath + str precedence
                                     in a cache-root expression).  Connectivity
                                     was proved by the remote traceback; no data
                                     was returned.
  2  formal read                  -- ran cleanly to completion, proved the server
                                     unchanged, and found no aimnet distribution
```

Both scripts were standard-library only, sent over stdin so nothing was
interpolated into a shell command, and run under `python -I -B` with all four
offline flags set. The second script was compiled and executed locally first, so
the failure was not a syntax or logic error.

## Why it found nothing

```text
interpreter probed   python 3.12.3      (the login shell's python3)
aimnet               PackageNotFoundError
ase                  PackageNotFoundError
torch                PackageNotFoundError
```

Phase 9A-R recorded the AIMNet2 stack at **python 3.11.15**, reached through
`"activation": "project_explicit_mlff_env_script"` — the project's own `mlff`
environment script, never `~/.bashrc`. The committed records name the *molecular*
environment script relative path but not the `mlff` one, so the second call
defaulted to the login interpreter and looked in an environment that has never
held these packages.

This is a targeting error on my part, not a finding about the server.

## What WAS established

Read-only facts, all from the clean second invocation:

```text
weight located        <AIMNET_CACHE_ROOT>/aimnet2_wb97m_d3_0.pt
weight bytes          8836941        matches the registered size exactly
aimnet cache          1 file, 8836941 bytes    (the weight, and nothing else)
torch hub cache       2 files, 109872 bytes
triton cache          1 file, 26560 bytes
nv ComputeCache       682 files, 26405248 bytes
huggingface cache     does not exist
inductor cache        does not exist
```

The absent Hugging Face cache is itself informative: whatever Phase 9A-I did, it
populated no hub cache.

## Server invariance

Snapshots were taken before and after every read **inside the same process**, so
the proof covers exactly the window in which anything was touched:

```text
cache before == cache after            true
weight before == weight after          true
source before == source after          true
third-party modules imported           none  (empty list, asserted from sys.modules)
isolated mode                          true
bytecode writing disabled              true
HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE / HF_DATASETS_OFFLINE / PYTHONDONTWRITEBYTECODE
                                       all set before the interpreter started
```

No file was created, no mtime changed, no bytecode was written, no cache was
populated, no model was opened, no GPU context was created, and no network
connection was made. The full record is in
`docs/PHASE9A_S_SOURCE_FILE_MANIFEST.json`.

## The twenty questions

All twenty remain unanswered by source, because no source was read. They are not
restated as guesses here. What is already authoritative from Phase 9A-R
introspection is recorded in `docs/PHASE9A_I_API_RECOVERY.md`: both constructor
signatures verbatim, the import path, and the measured device, member, units, and
element coverage.

Per the rule for this phase:

```text
loader_decision                        unresolved
production loader                      not written
guessing between A and B               refused
```

## The next minimal test

One read-only SSH invocation, with the interpreter located rather than assumed.
The script should:

```text
1  enumerate <REMOTE_PROJECT_ROOT>/env/envs/*.sh to find the mlff activation
   script by listing, not by guessing its name
2  read that script to extract the interpreter path, without sourcing it
3  invoke that interpreter with -I -B and the same four offline flags
4  use importlib.metadata only -- never `import aimnet`
5  locate, hash, read, and AST-analyse aimnet/calculators/*.py plus the helpers
   its calls reach, and ase/optimize/lbfgs.py and optimize.py
6  snapshot caches, weights, and sources before and after, in one process
```

If step 2 cannot extract an interpreter path without sourcing the script, an
acceptable alternative is to run the activation script in a subshell and have it
exec `python -I -B -` — the activation itself is what Phase 9A-R already did, and
it modifies no state.

That single call answers all twenty questions or proves them unanswerable. It
needs its own authorization; it is not requested implicitly here.

## What did not change

```text
runner source schema        v7, unchanged
runner_source_sha256        d7060a31...9c22, unchanged
v7 request/manifest/permit  prepared_not_authorized, unchanged
execution gates             eleven, all false
identity rebaseline         none
real computation            none
```
