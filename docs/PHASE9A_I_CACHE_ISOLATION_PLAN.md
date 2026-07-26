# Phase 9A-I Cache Isolation Plan

## Why this is a first-class concern

Torch, CUDA, Triton, and related runtimes write caches as a side effect of
ordinary use — kernel autotuning, compiled artifacts, extension builds. On a
**shared account**, an unredirected cache write is not a private inconvenience:
it mutates state other users depend on, and it is invisible unless deliberately
checked.

This phase therefore treats cache writes as an outcome to be proven absent, not
as noise to be tolerated.

## Isolation strategy

All cache-capable environment variables are redirected into one fresh isolated
temporary root created for this attempt:

```text
TORCH_HOME
TORCHINDUCTOR_CACHE_DIR
TRITON_CACHE_DIR
CUDA_CACHE_PATH
XDG_CACHE_HOME
TMPDIR
HF_HOME
```

The isolated root is new, attempt-specific, outside the project source tree,
outside the model weight directory, and outside any shared location.

Writes are permitted **only** inside that root. Prohibited write targets:

```text
the model weight directory
the project source tree
the global Python environment
any shared cache directory
any other user's space
```

## Before-and-after proof

The guard is a snapshot comparison, not an assumption:

1. snapshot every relevant global cache directory before the run — entries,
   byte sizes, and mtimes;
2. redirect the cache variables into the isolated root;
3. run;
4. snapshot the same global directories again;
5. prove global caches, the model file, and the environment are unchanged;
6. enumerate every file actually created inside the isolated root.

Step 6 matters as much as step 5. Knowing what the run *did* write is what makes
the next phase's resource planning honest, and an unexpected artifact there is a
finding rather than a nuisance.

The same before/after technique already proved the Phase 9A-R preflight wrote
nothing, so it is a demonstrated method in this project rather than a new idea.

## Compilation

`compile_model` stays **off** unless the installed version is demonstrated to be
unable to run without it.

Compilation is the largest cache-writing surface available here, it was never
exercised in the Phase 9A-R preflight, and enabling it for speed would trade an
unmeasured side-effect risk for a benefit this phase does not need. A
six-call characterization has no performance requirement.

If compilation turns out to be mandatory, that is recorded as a finding, its
cache footprint is enumerated, and the decision returns to the user rather than
being taken inline.

## Fail-closed rule

If safe isolation cannot be established, the run **stops before the model is
loaded**.

The ordering is deliberate. Once the model is loaded, cache writes may already
have occurred, so a check performed afterward can only report damage. The
isolation must be provable in advance or the attempt does not begin.

Any of the following ends the attempt:

```text
a cache variable cannot be redirected
the isolated root cannot be created
the isolated root is not empty at start
a global cache changes during the run
the model weight file changes
a file appears outside the isolated root
```

## Cleanup

The isolated root and its inventory are retained until the run is recorded, so
that what was written can be audited. Removal happens only after the file
inventory and hashes are captured, and it never deletes anything outside that
root.
