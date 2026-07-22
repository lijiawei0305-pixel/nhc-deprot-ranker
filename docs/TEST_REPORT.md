# Current Test Report

The current release gate covers Phases 0–5 and is recorded in `PHASE5_TEST_REPORT.md`.

At the pre-publication code gate, 87 pytest tests passed together with Ruff lint/format and strict mypy over 50 package source files. The suite is synthetic and independent of production Parquet files, quantum-chemistry packages, and HPC.

The local real-result release audit separately verified all 401,856 full-score rows and unique keys, exact B0 rank identity, Top-100 identity, deterministic Top-K fields, zero rank shift, applicability flags, the 50-row unique unlabeled acquisition batch, exact `15/13/12/10` quotas, all checked-in hashes, and eight figures. No external computation or server action occurred.

Historical per-phase test environments, wheel hashes, and behavior coverage remain available in `PHASE1_TEST_REPORT.md` through `PHASE5_TEST_REPORT.md`.
