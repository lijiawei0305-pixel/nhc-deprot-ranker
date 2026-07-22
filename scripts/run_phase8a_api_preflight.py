#!/usr/bin/env python3
"""Launch the approved Phase 8A read-only server API inspection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nhc_deprot_ranker.preparation.phase8a_preflight import run_phase8a_preflight


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--inspector",
        type=Path,
        default=Path("scripts/phase8a_api_preflight.py"),
    )
    args = parser.parse_args()
    payload = run_phase8a_preflight(config_path=args.config, inspector_path=args.inspector)
    print(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
