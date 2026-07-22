#!/usr/bin/env python3
"""Build the frozen Phase 8B transfer bundle after the source gate opens."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from nhc_deprot_ranker.preparation.phase8b_bundle import prepare_phase8b_bundle


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase7-result", required=True, type=Path)
    parser.add_argument("--phase8a-evidence", required=True, type=Path)
    parser.add_argument("--remote-project-root", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    repository_root = Path(__file__).resolve().parents[1]
    result = prepare_phase8b_bundle(
        # ``absolute`` is lexical: the production builder gets to check its
        # source gate before any input existence/read validation.
        phase7_result_dir=arguments.phase7_result.absolute(),
        phase8a_evidence_path=arguments.phase8a_evidence.absolute(),
        source_root=(repository_root / "src").absolute(),
        remote_project_root=str(arguments.remote_project_root),
        output_dir=arguments.output.absolute(),
    )
    print(
        json.dumps(
            {
                "schema_version": "phase8b.bundle_cli.v1",
                "output_dir": str(result.output_dir),
                "request_sha256": result.request_sha256,
                "runner_source_sha256": result.runner_source_sha256,
                "payload_manifest_sha256": result.payload_manifest_sha256,
                "permit_sha256": result.permit_sha256,
                "transport_inventory_sha256": result.transport_inventory_sha256,
                "file_count": result.file_count,
            },
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
