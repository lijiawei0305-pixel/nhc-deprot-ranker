# Phase 9B Split-Process Test and Mutation Plan

All Item 10 tests are local or mock-backed. Production gates remain false.

## Authority and isolation

- consume one campaign permit once; never restore it;
- prove A1/A2 cannot obtain ordinary permits or be launched externally;
- prove only the campaign supervisor can issue a stage capability;
- reject A2 capability before A1 acceptance and handoff admission;
- reject cross-attempt, cross-stage, cross-parent, replayed, and expired capability;
- reject request/CLI/environment attempts to select an adapter or interpreter;
- prove A1 argv uses only the exact MLFF executable and A2 only the exact
  GPU-PySCF executable;
- reject `PYTHONPATH` composition;
- fail A1 on PySCF/geometric/dispersion imports and A2 on torch/aimnet/ASE imports.

## Process and deadline

- supervisor survives A1 and starts A2 only after A1 reap and admission;
- prove A1/A2 non-overlap and reject a residual A1 process;
- exercise A1 timeout, A2 timeout, supervisor death, PID reuse, child reaping,
  exact-group TERM, grace, KILL, orphan detection, spawn and ack failure;
- prove A1 uses min(campaign deadline, local 900 seconds) and A2 receives only
  the campaign remainder, never a new 7200 seconds.

## Handoff and science

- accept exact bytes and reject modified or reserialized XYZ, atom reorder,
  charge/multiplicity drift, endpoint swap, candidate/source drift, extra file,
  receipt mismatch, and parent-memory coordinate substitution;
- prove A2 performs its own no-follow disk read and parser-input digest;
- load the mock base model once; run cation/neutral preoptimization once;
- exercise every structural gate and prove AIMNet2 energy cannot reach label;
- prove direct and A2 call the same PySCF core with equal protocol fields;
- prove SOSCF cannot rerun A1, cation PySCF failure skips neutral, and a label
  requires both accepted endpoints.

## Evidence and partial terminals

- verify exclusive create, no overwrite, fsync/re-read hashes, byte caps, exact
  path manifests, and direct absence of A1 evidence;
- validate each campaign terminal and every permitted intermediate terminal tree;
- exercise evidence failure, handoff rejection, A2 admission failure,
  indeterminate state, no retry and no permit restoration.

## Required mutations

The suite must kill mutations that introduce two ordinary assisted permits;
external A2 launch; A2-before-A1 or stage overlap; A2 with residual A1 process;
parent-memory coordinates; no A2 disk read; missing output-hash,
charge/multiplicity or atom-order validation; second model load; A1 rerun on
SOSCF; A1 PySCF import; A2 AIMNet import; `PYTHONPATH` composition; a fresh A2
7200 seconds; permit restoration; replayable capability; divergent direct/A2
PySCF cores; AIMNet2 energy in the label; label after failure; extra evidence
files; overwritten rather than superseded v8 identity; or Postflight that checks
A2 without A1.
