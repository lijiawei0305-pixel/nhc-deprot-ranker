#!/usr/bin/env python3
"""Commit and send the sole frozen Phase 8B guardian launch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nhc_deprot_ranker.preparation.phase8b_launch import launch_phase8b_smoke


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--transport-inventory-sha256", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    arguments = parser.parse_args()
    evidence = launch_phase8b_smoke(
        config_path=arguments.config,
        bundle_dir=arguments.bundle,
        expected_transport_inventory_sha256=arguments.transport_inventory_sha256,
        timeout_seconds=arguments.timeout_seconds,
    )
    print(json.dumps(evidence, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
