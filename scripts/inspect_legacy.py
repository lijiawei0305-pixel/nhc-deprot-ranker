#!/usr/bin/env python3
"""Direct wrapper for the Phase 0 legacy source-plan command."""

from __future__ import annotations

import sys

from nhc_deprot_ranker.cli import run

if __name__ == "__main__":
    raise SystemExit(run(["audit-legacy", *sys.argv[1:]]))
