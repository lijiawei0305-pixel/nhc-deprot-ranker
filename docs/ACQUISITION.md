# Acquisition Specification

Status: specification only; Phase 0 does not select or submit calculations.

`nhc-deprot acquire` will rank already-scored candidates for a future high-fidelity batch. It never starts PySCF or submits an HPC job.

The score combines configured contributions for predicted Top-K probability, uncertainty, absolute rank shift, family novelty, cutoff proximity, and diversity. Quotas are read from YAML and default to:

- predicted top region: 30%;
- cutoff region: 25%;
- family diversity: 25%;
- uncertain/OOD/conflict: 20%.

Outputs are `acquisition_candidates.csv` and `high_fidelity_batch_manifest.json`, with reasons, priority, prediction interval, family, xTB/calibrated ranks, and provenance. Duplicate InChIKeys or already-labeled candidates are excluded with explicit counts.

The manifest is an interoperability artifact for the read-only legacy workflow. Generating it does not authorize copying it to the server or running calculations.
