# Phase 8B Test Report

## Gate result

The software verification described below passed within its stated scopes, but
the only authorized Phase 8B execution attempt is rejected. Passing local tests
does not repair the immutable receipt, produce endpoint results, establish a
kernel-invocation fact, or authorize a retry.

## Confirmed results

The following results were recorded from actual commands. The suites overlap
and their counts must not be added together.

| Verification scope | Confirmed result | Interpretation |
| --- | ---: | --- |
| Pre-execution closed-gate full suite | `542 passed` | authoritative full local gate before the one authorized launch |
| Execution subsystem targeted suite | `30 passed` | registration, acknowledgement, claim, receipt, cleanup, and final-publication protocol |
| Current postflight suite | `22 passed` | read-only terminal validation and incident regressions |
| Expanded Phase 8B targeted suite | `113 passed` | postflight, preflight, remote preflight, deploy, execution, and runtime tests |

The latest targeted quality checks also reported:

```text
Ruff format check: passed for the three postflight files
Ruff lint: passed for the three postflight files
mypy strict: passed for the three postflight files
py_compile: passed for the three postflight files
git diff --check: passed for the three postflight files
```

These targeted checks are not a substitute for the final repository-wide
verification reserved below.

## Pre-execution closed-gate coverage

The confirmed `542 passed` full suite ran while the execution path was closed.
It established the local implementation gate before the single authorized
launch. Its coverage included the existing scientific formula, request and
bundle identity, source closure, process containment, permit, deployment,
preflight, runtime publication, and no-compute gate tests.

This result proves that the closed-gate repository satisfied its local test
contract at that point. It does not prove any remote chemistry result.

## Execution protocol regressions

The `30 passed` execution subset covers the permanent compute-authority chain
and terminal publication rules, including:

- exclusive registration, acknowledgement, claim, and receipt records;
- exact transaction, deadline, release-token hash, authority, and path binding;
- stable process identity, reuse detection, hierarchy, affinity, and cleanup;
- claim publication before worker compute authority;
- one-shot permit behavior and stale-record rejection;
- fail-closed receipt outcomes and final-acceptance withholding;
- mandatory claim binding for clean terminal acceptance.

These tests use local process and record fixtures. They do not invoke a quantum
backend.

## Postflight incident regressions

The current `22 passed` postflight suite includes the following incident-specific
cases:

- receipt and registration states may differ between `S` and `R` only when
  every stable identity field agrees;
- stable start-time or other identity drift is rejected;
- acknowledgement and compute claim identities remain exact registration
  matches;
- a valid durable claim is not used to reconstruct a null claim hash in an
  immutable receipt;
- reboot and process/group reuse are distinguished from an original live
  process;
- a registered zero-byte Phase 7 helper log participates in the frozen tree
  hash;
- empty coordination records and empty dynamic failure records remain rejected;
- alternate, replaced, or symbolic-link inspector sources are rejected before
  command execution;
- noncanonical JSON, duplicate keys, nonzero exits, unexpected standard error,
  and empty standard output fail closed;
- a reappeared ready permit and any second-attempt artifact are rejected;
- internal logs are not used as acceptance evidence.

The expanded `113 passed` suite ran these postflight cases together with Phase
8B preflight, remote-preflight-script, deployment, execution, and runtime tests.

## Local interpreter capability note

An additional diagnostic run used the repository's older macOS CPython 3.11.15
virtual environment. That interpreter does not expose `os.waitid`, so the
supervisor deliberately failed closed and the run ended with `524 passed, 26
failed`; every failure was in the process-supervisor suite. The same suite
passed `29 passed` with the current local CPython 3.14.3, which exposes the
required `waitid(..., WNOWAIT)` primitive. The deployed Linux CPython 3.11.15
also passed the preflight capability check. This diagnostic is not counted as
the final repository-wide gate and is retained here rather than hidden.

## Incident interpretation boundary

No test result changes the execution evidence:

- the immutable receipt remains `cleanup_failed`;
- its compute-claim hash remains null;
- no endpoint result exists;
- no final acceptance exists;
- kernel invocation remains `indeterminate`;
- the consumed attempt must not be rerun.

The historical frozen postflight did not complete because its file helper
rejected a legitimate zero-byte Phase 7 file before reading the receipt. The
new regression test demonstrates the corrected future read behavior; it does
not create a historical postflight payload or a successful result.

## Final repository-wide verification

The final closed-gate repository verification completed with the current local
CPython 3.14.3 interpreter:

```text
FINAL_FULL_PYTEST_RESULT: 556 passed
FINAL_RUFF_LINT_RESULT: passed
FINAL_RUFF_FORMAT_RESULT: passed; 128 files formatted
FINAL_MYPY_RESULT: passed; strict mode, 72 source files
FINAL_COMPILEALL_RESULT: passed
FINAL_PRE_COMMIT_RESULT: passed; all hooks
FINAL_PACKAGE_BUILD_RESULT: passed; sdist and wheel
FINAL_PRIVATE_PATH_SCAN_RESULT: passed
FINAL_DIFF_CHECK_RESULT: passed
```

The package build emitted the existing setuptools warning that the TOML-table
form of `project.license` is deprecated for a future setuptools release. It did
not affect either artifact. The complete suite remained no-chemistry locally;
it did not connect to the server or invoke a quantum backend.

An independent final security review found no remaining High, Critical, or
Medium issue. Its only initial Low finding was closed by direct private-seam
tests proving that the consumed latch rejects before input reads, permit
rendering, local launch-record creation, or an injected command runner.

## Privacy and test boundary

This report includes no private absolute path, server coordinate, account,
process identifier, raw log, credential, molecular coordinate, or runtime
secret. The separate machine record is rejected evidence, not a portable
postflight or portable incident result. All postflight incident-regression
tests are local and no-chemistry; they do not connect to a server or execute a
real quantum kernel.
