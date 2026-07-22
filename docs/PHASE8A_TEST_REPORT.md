# Phase 8A Test Report

## Gate result

Passed. Local process containment, parent/worker state publication and portable server evidence satisfied the Phase 8A contract. Local tests used only standard-library process fixtures and fake backends; no local chemistry dependency was imported or executed.

## Local automated tests

The final local suite reported:

```text
238 passed
Ruff lint: passed
Ruff format check: passed
mypy strict: passed for 65 source/script files in an isolated Python 3.11 environment
pre-commit: passed
git diff --check: passed
package build: passed
```

The three existing test warnings are NumPy/joblib deprecation warnings in Phase 3 model roundtrip tests and are unrelated to Phase 8A.

The initial all-source mypy invocation used the resident Python 3.13 environment with NumPy 2.5.1 while the project target is Python 3.11; that third-party stub uses Python 3.12+ type-alias syntax and cannot be parsed as 3.11. The authoritative check therefore used an isolated Python 3.11 dependency resolution and passed all 65 source and script files without weakening mypy configuration.

The package build emitted only the existing setuptools warning about the future deprecation of the table form of `project.license` and produced both sdist and wheel.

## Supervisor tests

Twenty-five dedicated supervisor cases, including repeated boundary cases, covered:

- clean and explicit nonzero exits;
- independent stdout/stderr capture;
- output larger than each retention limit without pipe deadlock;
- a direct child exceeding its deadline;
- a child that ignores `SIGTERM` and requires `SIGKILL`;
- a child and sleeping grandchild in the same group;
- a direct parent that exits while its child survives;
- spawn failure;
- malformed argv and invalid policy values before spawn;
- a delayed parent observing completion only after the hard deadline, which fails closed as timeout;
- process-group inspection failure, which still forces `SIGKILL` and a bounded direct-child reap but withholds safe-cleanup proof;
- twelve deadline/exit race repetitions;
- twenty repeated fast exits with no created PID left alive.

The suite was run twice during implementation and again in the integrated suite. Timeout returned 124; spawn, supervision, orphan and other failures were nonzero. Tests inspected only fixture PIDs they created and used no process-name scan or broad kill.

## Runner and worker tests

The protocol tests proved:

- the public gate precedes request reads, dynamic supervisor import, process creation and output creation;
- the worker gate precedes argv and request parsing, and a false request gate precedes backend construction;
- the runner identity changes when any of the eight pre-gate import-chain files changes, and the isolated bootstrap discards inherited module-search overrides;
- a harmless fake worker remains isolated until the parent validates and publishes the exact six success files;
- timeout and nonzero outcomes publish only one failure envelope after supervisor return;
- a zero exit with invalid scratch state becomes a protocol failure rather than success;
- unconfirmed process-group cleanup cannot publish an attempt or delete worker scratch, even when paired with a timeout flag;
- all existing Phase 7 request, backend, atomic state, retry, resume, tamper and cross-attempt tests continue to pass.

No test opened the source gate or invoked the real worker module as a subprocess. Fake backends contained no PySCF, geomeTRIC or molecular operation.

## Static inspector and configuration tests

The Phase 8A private configuration rejects unknown fields, non-loopback proxies, unsafe roots, any alternate environment script, server-write authorization and quantum-execution authorization. The launcher uses an SSH argv without a local shell and streams a bytecode-disabled read-only wrapper; it contains no remote mkdir, redirection to a server file, upload or scheduler command.

An AST test rejects calls to molecule/mean-field constructors, `build`, SCF/DFT/optimization/dispersion/Hessian methods and file-writing helpers in the remote inspector. The checked-in evidence is reloaded as strict JSON, rejects duplicate/non-finite values and private coordinates, contains exactly 18 true acceptance checks and records the 27-file Phase 7 integrity result.

## Server read-only verification

The final static preflight passed all 18 checks. It recorded the installed versions and function signatures, source hashes for the geomeTRIC and D3 adapter entry points, public RKS factory behavior, the implementation-class relationship, D3(BJ) support tables and SCF helper aliases.

Before and after import/inspection, the Phase 7 directory contained exactly the registered 27 files with canonical tree SHA256 `9b92a1f453274995661bd262e607239a86f4992bf4cc2809a311207dceadbecb`. The three registered server source hashes also matched before and after. Safety flags explicitly record no molecule, mean field, kernel, optimizer, dispersion, Hessian or server write.

## Residual boundary

The tests do not claim containment of a deliberately escaped `setsid` descendant and do not dynamically validate D3(BJ) energy/gradient inclusion. No real PySCF adapter call has run. Both limits are explicit inputs to a future Phase 8B decision, which remains unauthorized.
