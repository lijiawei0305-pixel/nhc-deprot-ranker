# Phase 9B Parent-Level P01-R1 Plan

P01-R1 is a one-candidate, non-production continuation.  It first discovers the
effective scheduler, cgroup, affinity, topology, load and memory boundaries.  A
formal parent-level route may start only after a full fixed-geometry grid-4 SCF,
analytic gradient, independent D3 audit and grid-3/grid-4 comparison pass.

The observed host has 112 logical CPUs / 56 physical cores, no scheduler job,
no CPU quota, full process affinity, multiple login sessions and three active
single-core VASP processes.  It is therefore `NODE_NOT_CONFIRMED_EXCLUSIVE`.
The preregistered shared-node policy uses only socket 0, excludes active physical
cores, and leaves socket 1 untouched.  Physical and SMT variants of that same
core set are compared by one grid-4 SCF cycle; SMT is selected only if it is at
least 5% faster with numerically identical partial energy.  Otherwise physical
cores are used.

The audit recomputes a converged grid-3 density on the same geometry and parent
method, saves its exact identity, then supplies it as `dm0` to grid 4.  Grid 4
must independently meet `conv_tol=1e-9` and produce finite energy, analytic
gradient and two-body D3(BJ) energy/gradient with ATM and VV10 disabled.  No
post-hoc grid threshold is introduced; a successful comparison freezes grid 4.

Only after `protocol_lock.json` exists may Group A and Group B run sequentially
on the same CPU list, thread count, memory and parent protocol.  There is no
retry, rescue method, second candidate, batch, production permit, gate change or
production label insertion.

## Terminal forward link

The resource and grid stages completed: 27 physical threads on CPU list
`0,2-27` were selected, grid 4 converged with finite energy/gradient/D3, and
`protocol_lock.json` froze grid 4. The one Group A attempt then stopped before
the first AIMNet2 trajectory frame because NVRTC rejected the length of its
private temporary directory. The no-retry rule prevented a short-path rerun,
and Group B did not start. The final P01-R1 state is `INCONCLUSIVE`; see
`PHASE9B_PARENT_LEVEL_P01_R1_RESULT.json` and
`PHASE9B_PARENT_LEVEL_P01_R1_REPORT.md`.
