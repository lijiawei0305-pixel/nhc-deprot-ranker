#!/usr/bin/env python3
"""Run the approved Phase 8B read-only server preflight."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nhc_deprot_ranker.preparation.phase8b_preflight import run_phase8b_preflight


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--inspector",
        type=Path,
        default=Path("scripts/phase8b_remote_preflight.py"),
    )
    arguments = parser.parse_args()
    payload = run_phase8b_preflight(
        config_path=arguments.config,
        inspector_path=arguments.inspector,
    )
    print(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
