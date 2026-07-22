#!/usr/bin/env python3
"""Direct wrapper for electronic label formula validation."""

from __future__ import annotations

import sys

from nhc_deprot_ranker.cli import run

if __name__ == "__main__":
    raise SystemExit(run(["validate-labels", *sys.argv[1:]]))
