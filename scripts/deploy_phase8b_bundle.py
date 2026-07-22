#!/usr/bin/env python3
"""Deploy one frozen Phase 8B bundle without launching quantum work."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nhc_deprot_ranker.preparation.phase8b_deploy import deploy_phase8b_bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--transport-inventory-sha256", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    arguments = parser.parse_args()
    evidence = deploy_phase8b_bundle(
        config_path=arguments.config,
        bundle_dir=arguments.bundle,
        expected_transport_inventory_sha256=arguments.transport_inventory_sha256,
        timeout_seconds=arguments.timeout_seconds,
    )
    print(json.dumps(evidence, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
