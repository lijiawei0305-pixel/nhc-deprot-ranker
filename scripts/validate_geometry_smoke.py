#!/usr/bin/env python3
"""Standalone entry point for the Phase 7 strong geometry validator."""

from __future__ import annotations

try:
    # The remote transfer bundle copies both files into the same tools directory.
    from geometry_validation import main  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - repository/package invocation path
    from nhc_deprot_ranker.preparation.geometry_validation import main


if __name__ == "__main__":
    raise SystemExit(main())
