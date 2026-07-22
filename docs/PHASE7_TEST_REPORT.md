# Phase 7 Test Report

## Gate result

Passed. Local code, portable bundle, remote geometry output and downloaded readback satisfied the Phase 7 test contract. No test imported or executed local RDKit, PySCF or geomeTRIC.

## Local automated tests

The final local suite reported:

```text
188 passed
Ruff lint: passed
Ruff format check: passed
mypy strict: passed for 57 source files
pre-commit: passed
git diff --check: passed
Bash syntax: passed
uv package build: passed
```

The package build emitted only the existing setuptools warning that the table form of `project.license` is deprecated for a future setuptools release. It did not affect the build or Phase 7 artifacts.

The Phase 7 tests cover:

- strict geometry config and frozen four-key order;
- the 542-byte canonical input and full Phase 6 evidence/package hash chain;
- immutable bundle creation, dry-run non-writing behavior, exact portable file set and no private coordinates;
- generated wrapper namespace checks, Conda nounset handling, bytecode suppression, serial M2-only behavior and rejection before writing to an unsafe run root;
- strict XYZ/JSON parsing, finite coordinates, collision bounds, charge and atom-order checks through a fake chemistry adapter;
- endpoint graph mapping, nitro exclusion through the shared five-membered-ring rule and corrected map output;
- remote configuration route, authorization, no-delete policy and shell-metacharacter rejection;
- public runner rejection before lazy imports, fixed protocol and source/input hashes;
- D3(BJ) activation across boolean/string PySCF API forms and explicit geomeTRIC kernel convergence through fully fake modules;
- final-SCF convergence, one recorded SOSCF retry, finite values, atom order, locked label formula and safety flags;
- atomic attempt success/failure, no cross-attempt endpoint reuse and strict resume rejection for duplicate keys, NaN, extra files, hash drift and re-signed identity drift.

## Real Phase 6 dry-run and bundle checks

The real Phase 6 result was verified before bundle creation. Dry-run validated all upstream files and wrote nothing. The actual bundle then independently passed:

- exact eight-file set and zero symlinks;
- canonical input size 542 and SHA256 `f486f93a2d58fb144c05a7340fd432334eeec46385c9319aca34d2e1b5c4cc87`;
- package-manifest SHA256 `2c4d776ab009a1c265d080dc55392fc7cdf38137a62200fa4b67a38f79746ae9`;
- every registered output SHA256;
- ready-marker pointer;
- owner-executable permission only on the M2 wrapper;
- Bash parsing and private-path/IP scan;
- no `__pycache__`, bytecode or forbidden calculation command.

## Server preflight and runtime checks

The passing combined preflight verified the direct campus route, real project/run parents, absent target, writable isolated namespace, molecular environment, ETKDGv3, runtime versions, disk, memory, CPU count and exact legacy source hashes.

The first read-only probe stopped before all checks because the deployed tree did not retain the local audited Git commit object. No server write had occurred. The corrected preflight recorded that fact and used the exact two-file SHA256 identity, which is the code actually executed.

Before M2, the server independently verified all eight transferred files against their local hashes. The synchronous wrapper reported:

```text
total=4
processed=4
success=4
failed=0
skipped=0
parallel=1
```

The failure log was zero bytes, and no fallback warning appeared in the captured M2 log.

## Strong geometry validation

The HPC validator reported `passed` for 4/4 candidates and exactly 12 core files. Per candidate it verified the cation charge +1, neutral charge 0, exact AddHs element sequence, equal heavy-element multiset, one-proton difference, valid legacy C/N/N indices, independently derived neutral C2, finite coordinate extrema and minimum interatomic distance.

The report produced four corrected endpoint maps and declared:

```text
force_field_convergence = unavailable_legacy_m2
geometry_quality = initial_force_field_geometry
quantum_chemistry_run = false
hessian_computed = false
replacement_candidate_used = false
```

## Remote/local readback audit

Only the isolated run was downloaded. A fresh server hash inventory and fresh local hash inventory contained 27 files each and matched exactly. The validation report SHA256 was `35e99683a32e416752014c6e1ecb8121e2bc06d5407911435e5c1250fd639f90`; the combined path-and-hash tree identity was `644f027e276902dc1ab105f02f08864967f69ae87dc8883f608f5e4d17a372ad`.

An independent read-only result audit then verified:

- 14 strict JSON files with duplicate-key and non-finite-number rejection;
- 27/27 remote-mirror SHA256 values and the inventory/success/manifest pointer chain;
- exact four-key order, request positions 1–4 and no replacement;
- 12/12 core files and 4/4 corrected endpoint maps;
- eight XYZ files by independent non-chemical syntax, atom-line, finite-coordinate and extrema recomputation;
- zero symlinks, zero bytecode, zero extra outputs and an empty failure log;
- exact legacy file bytes/hashes and all no-quantum/no-Hessian flags.

The Mac did not repeat RDKit chemistry validation. It verified bytes, strict schemas, hashes, finite XYZ syntax and report consistency only, preserving the server-only chemistry boundary.

## Residual test boundary

No real test has executed the dedicated PySCF adapter. That is intentional. The source-level authorization guard is false, and the current deadline checks cannot interrupt a compute call that hangs. Phase 8 must add a process- or signal-level hard wall timeout, retest the adapter against the actual server API and obtain explicit user authorization before any real DFT smoke.
