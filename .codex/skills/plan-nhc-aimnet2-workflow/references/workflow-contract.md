# Workflow State Contract

## 1. Freeze the scientific identity

Bind the repository, candidate pool, frozen input XYZ, endpoint charge/multiplicity/spin, atom map, label formula, parent-level protocol, software environment, base AIMNet2 weight, and every relevant SHA256 before planning downstream work.

Read the exact scientific definition from repository authority. Never recreate the label formula or parent method from memory. AIMNet2 energy is an optimization signal only and never enters the parent-level label.

## 2. Use one explicit lifecycle

Plan and audit these states in order:

~~~text
REFERENCE_COLLECTION
-> REFERENCE_AUDIT
-> DATASET_FREEZE
-> MODEL_TRAINING
-> FRAME_VALIDATION
-> STOPPING_CONTRACT_CALIBRATION
-> PRECONDITIONER_VALIDATION
-> GEOMETRY_VALIDATION
-> PARENT_GRADIENT_VALIDATION
-> LABEL_VALIDATION
-> MODEL_FREEZE
-> FINAL_TEST_ONCE
-> SINGLE_POINT_ONLY_PROMOTION
~~~

No state authorizes its successor. Every transition requires immutable input identities, a unique writer, independently recomputable evidence, a terminal classification, and one exact next permitted action.

`PRECONDITIONER_VALIDATION` may terminate with a mandatory full parent-level
optimization route and `single_point_only_eligible=false`. It does not have to
continue to `SINGLE_POINT_ONLY_PROMOTION`; that later route is a separate,
strictly stronger scientific claim.

Within `PRECONDITIONER_VALIDATION`, the first successful parent energy and
analytic gradient are an observation of the continuing full optimization, not
a separate static route. `HANDOFF_CALIBRATION_PASS` and
`HANDOFF_CALIBRATION_MISS` both advance within that same optimization;
`FAILED_PARENT_HANDOFF` stops it. Only final profile `GAU` convergence plus the
required final single point closes as `FINAL_PARENT_GAU_CONVERGED`.

Use these routed contracts:

- Reference collection, frame admission, D3 targets, splits, and balancing: [reference-data-contract.md](reference-data-contract.md)
- Training lineage, checkpoint selection, final-test isolation, and model generations: [model-generation-contract.md](model-generation-contract.md)
- AIMNet2 stopping, geometry/gradient/label validation, and promotion: [aimnet2-handoff-promotion.md](aimnet2-handoff-promotion.md)
- Server allocation, concurrency, throughput, and benchmark validity: [server-performance-contract.md](server-performance-contract.md)

## 3. Freeze cohorts without overstating them

Resolve the candidate pool and permanent split registry through their manifests and hashes. Apply exact candidate, element, charge, multiplicity, electron, cation/neutral XYZ, atom-map, prior-label, active-work, and split-overlap gates.

Use deterministic, family-aware diversity selection. Cover size, rigidity, substitution, halogens where available, initial-force range, and electronic/steric variation. Break a true tie lexicographically by InChIKey. Do not use final-test outcomes or hidden xTB ranks.

A 5 train / 2 validation / 2 final-test cohort is a pilot cohort. It can test mechanics and expose large failures, but it cannot establish a general stopping rule, general single-point-only eligibility, or statistical performance across the NHC domain. Accumulate permanently assigned cohorts; never move an InChIKey between splits.

## 4. Separate scientific acceptance from server utilization

Choose scientific gates first. Among configurations that satisfy the frozen scientific gates, select the fastest resource and stopping profile using evidence from the appropriate performance mode.

Do not tune scientific thresholds to fill CPUs, reduce queue time, or make a benchmark pass. Do not weaken reference quality to increase frame count. Throughput counts only accepted candidates and admitted frames.

## 5. Define gates before executable work

For each state, specify:

- exact immutable inputs and source identities;
- writer and reader ownership;
- deterministic transformation;
- required output schema and hashes;
- acceptance, rejection, timeout, and environment-failure states;
- forbidden fallbacks and retries;
- evidence closure and cleanup checks;
- next permitted action.

If a required numeric threshold has no frozen authority, present an evidence-backed calibration design and request confirmation. Do not invent a threshold or consume final-test data to choose it.

## 6. Preserve the no-retry and no-substitution rules

An attempted candidate or model generation is never silently replaced. Failed, partial, timed-out, manifest-open, or structurally invalid work remains diagnostic and is not admitted as reference data.

Work stealing may claim only never-claimed tasks. It must not restart, resume, reassign, or replace claimed work. Candidate closure requires both endpoint terminals and their shared identity barrier.

## 7. Close the workflow honestly

Planning completion means only that architecture and gates are frozen. Model training remains blocked until reference and dataset audits pass. Final test remains blocked until one model is frozen. SINGLE_POINT_ONLY_PROMOTION remains blocked until the complete handoff contract passes on an adequate unopened final-test cohort.

If any state lacks a production writer, isolated final-test evaluator, acceptance threshold, immutable receipt, or independently recomputable reader, return a blocked or failed audit rather than a provisional promotion.
