# Current Test Report

The current release gate covers Phases 0–6 local planning and is recorded in `PHASE6_TEST_REPORT.md`.

At the pre-publication code gate, 106 pytest tests passed together with Ruff lint/format and strict mypy over 54 source/script files. The suite is synthetic and independent of production Parquet files, geometry/quantum-chemistry packages, and HPC.

The Phase 6 real-result release audit separately verified the frozen 50-row unique unlabeled acquisition, zero overlap with 71 labels, exact 5×10 batching, `15/13/12/10` totals, four-bucket smoke identity, 15/15 checked-in output hashes, 13/13 package outputs, 18/18 package inputs, and a strict text-only filesystem allowlist. No geometry, quantum computation, connection, transfer, server write, or job submission occurred.

Historical per-phase test environments, wheel hashes, and behavior coverage remain available in `PHASE1_TEST_REPORT.md` through `PHASE6_TEST_REPORT.md`.
