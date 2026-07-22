# Phase 0 Execution Plan

## 1. Objective

Create an independent, documentation-led repository skeleton and produce an evidence-backed audit of the legacy Part 1 data, scientific target, family definitions, DFT labels, historical baselines, and execution environment. Phase 0 ends before model training.

## 2. Confirmed source policy

- Primary legacy snapshot: current working tree at `<LEGACY_LOCAL_ROOT>` (`legacy_repo.root` in the ignored local config), including its uncommitted files.
- Provenance rule: record Git HEAD and branch separately from working-tree modifications; never describe uncommitted content as part of the HEAD commit.
- Server-knowledge source: `<SERVER_KNOWLEDGE_WORKTREE>`, read only and used only for connection/HPC operating knowledge unless the user expands scope.
- GitHub repository: `https://github.com/lijiawei0305-pixel/nhc-predictor`, read only. The local working tree takes precedence for files that are more complete, with explicit provenance.
- Destination: this independent repository (`<NEW_REPO_ROOT>`) only.

## 3. Required legacy evidence

The audit must locate and inspect every path below in the primary legacy snapshot:

```text
doc/claude/science-decisions.md
config/surrogate/target_a.yaml
scripts/surrogate/fragment_features.py
scripts/surrogate/small_sample.py
scripts/surrogate/improvements/step4_multifidelity/delta_learning.py
scripts/surrogate/improvements/step4_multifidelity/run_multifidelity.py
scripts/surrogate/improvements/README.md
scripts/post/apply_gas_proton_to_delta_e_deprot.py
scripts/mol/dft_runner.py
scripts/mol/dft_batch.py
reports/part1-blind-round2-2026-07-09/blind_round2_preregistration.md
reports/part1-blind-round2-2026-07-09/deltaE_final.csv
reports/part1-blind-round2-2026-07-09/analyze_round2_results.py
reports/part1-small-train-big-predict-2026-07-09/README.md
reports/part1-small-train-big-predict-2026-07-09/stbp_learning_curve.py
reports/part1-masquerade-trap-breaking-2026-07-12/README.md
reports/part1-masquerade-trap-breaking-2026-07-12/load_data.py
reports/part1-masquerade-trap-breaking-2026-07-12/literature_support.md
reports/part1-masquerade-trap-breaking-2026-07-12/C_clean_model.py
reports/part1-masquerade-trap-breaking-2026-07-12/skeptic_S1_check.py
reports/part1-masquerade-trap-breaking-2026-07-12/skeptic_S3_check.py
```

Additional local files may be inspected when required to resolve paths, definitions, label provenance, or family lookup sources. Each extra source must be listed in the audit.

## 4. Execution sequence

### Step 0A — provenance inventory

Record branch, HEAD SHA, remote, working-tree status, relevant Python/dependency declarations, and the existence and SHA256 of required source files. Identify which required files differ from HEAD or are untracked.

### Step 0B — target and protocol trace

Trace `delta_e_deprot_kcal` from producer code through post-processing and reports. Establish units, proton constant, ranking direction, DFT method/basis/dispersion, optimizer, convergence criteria, and Hessian acceptance behavior from code and data rather than naming conventions.

### Step 0C — candidate table discovery

Resolve the full xTB candidate table and the supporting graph/fragment/descriptor sources. For each candidate input, record:

- path and SHA256;
- physical row count and parsed row count;
- columns and dtypes relevant to the contract;
- InChIKey null, duplicate, and uniqueness statistics;
- xTB target null/non-finite statistics and range;
- fragment and skeleton availability;
- N1/N3 and C4/C5 symmetry proportions;
- join coverage between candidate and fragment sources.

Large files are read in a memory-conscious way. No source data is modified or copied.

### Step 0D — high-fidelity label discovery

Identify all gold, blind-round-1, and blind-round-2 sources actually used by legacy analysis code. For each source, record schema, row count, unique InChIKeys, duplicate keys, missingness, endpoint electronic-energy availability, stored label availability, convergence, Hessian status, and stated theory protocol.

Across sources, compute exact key overlaps and compare coincident labels. Where endpoint energies exist, recompute the target with factor `627.509474` and proton constant `-6.28`; deviations greater than `0.02 kcal/mol` are hard failures. Protocol consistency is assessed from actual metadata/code and unresolved fields remain explicit.

### Step 0E — historical model evidence

Inspect the old delta-learning, affine-calibration, small-sample, blind-round, size-extrapolation, and masquerade analyses. Determine:

- why legacy delta learning fixes the effective xTB slope at 1;
- historical raw-xTB and affine results and the exact split/data context;
- which features were judged source-related or highly collinear;
- what can be migrated as an algorithmic idea or test;
- what is prohibited from migration as data, artifact, leakage, or unsupported conclusion.

No historical result is promoted to a new-project performance claim.

### Step 0F — repository skeleton and configuration

After the audit plan and scientific scope exist, create the Phase 0 subset of the requested skeleton, including `.gitignore`, `README.md`, `pyproject.toml`, config examples/local path config, package/test placeholders, and required empty data/model/result directories. The local path file is ignored before it is created.

### Step 0G — report and gate

Fill `docs/LEGACY_AUDIT.md` with evidence and produce Phase 0 status/reproducibility/test reports. Run only lightweight checks. Phase 0 is marked pass only if all stop conditions in `AGENT.md` are satisfied; otherwise it remains blocked with exact missing evidence.

## 5. Audit implementation rules

- All commands are non-mutating with respect to both legacy worktrees and the server.
- Tabular checks use streaming/chunking when useful and report parsing failures.
- Hashes cover the bytes actually inspected.
- Counts are reproducible from checked-in audit commands or scripts.
- Filename inference alone cannot establish skeleton, protocol, or label meaning.
- Dirty-worktree files are identified explicitly.
- No server connection is required for local data audit. If later needed to resolve source-of-truth facts, ask before connecting.

## 6. Deliverables

Phase 0 targets:

- repository skeleton;
- `docs/SCIENCE_SCOPE.md`;
- completed `docs/LEGACY_AUDIT.md`;
- `configs/legacy.example.yaml` and ignored `configs/legacy.local.yaml`;
- initial data/config contracts needed to express discovered sources;
- legacy commit/worktree and input SHA256 manifest;
- `PHASE_STATUS.md` plus Phase 0 audit/test/reproducibility reporting.

Documents for later phases may be created as clearly marked specifications, but no later-phase implementation begins.

## 7. Stop and confirmation points

Ask the user before:

- deciding among conflicting plausible candidate or label sources when code does not establish authority;
- choosing a software license;
- connecting to the server for any reason;
- performing any server write or job operation;
- entering Phase 1.
