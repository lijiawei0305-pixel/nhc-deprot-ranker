#!/usr/bin/env python3
"""Validate the common JSON contract for an archived workflow report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

STATUS_BY_MODE = {
    "complete_plan": {"PLAN_READY", "PLAN_BLOCKED", "INCONCLUSIVE"},
    "stage_audit": {"AUDIT_PASS", "AUDIT_FAIL", "INCONCLUSIVE"},
    "progress": {
        "HEALTHY",
        "WARNING",
        "CRITICAL",
        "TERMINAL",
        "INCONCLUSIVE",
    },
    "performance_plan": {"PLAN_READY", "PLAN_BLOCKED", "INCONCLUSIVE"},
    "performance_audit": {"AUDIT_PASS", "AUDIT_FAIL", "INCONCLUSIVE"},
}
GATE_STATUSES = {"PASS", "FAIL", "BLOCKED", "INCONCLUSIVE", "NOT_APPLICABLE"}
REQUIRED_TOP_LEVEL = {
    "schema",
    "mode",
    "status",
    "timestamp",
    "git_identity",
    "worktree_state",
    "scope",
    "assumptions",
    "inputs_and_sha256",
    "candidate_and_split_summary",
    "protocol_identity",
    "environment_model_config_result_identities",
    "gates",
    "findings",
    "blockers",
    "required_user_decisions",
    "read_only_commands",
    "privacy_redactions",
    "next_permitted_action",
}
REQUIRED_GATE_FIELDS = {
    "id",
    "stage",
    "status",
    "criterion",
    "observations",
    "evidence",
    "missing",
    "impact",
    "next_permitted_action",
}


def validate_report(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["report root must be a JSON object"]

    missing_top = sorted(REQUIRED_TOP_LEVEL - set(value))
    if missing_top:
        errors.append(f"missing top-level fields: {missing_top}")

    mode = value.get("mode")
    status = value.get("status")
    if mode not in STATUS_BY_MODE:
        errors.append(f"unsupported mode: {mode!r}")
    elif status not in STATUS_BY_MODE[mode]:
        errors.append(f"status {status!r} is invalid for mode {mode!r}")

    for field in (
        "assumptions",
        "gates",
        "findings",
        "blockers",
        "required_user_decisions",
        "privacy_redactions",
    ):
        if field in value and not isinstance(value[field], list):
            errors.append(f"{field} must be a list")

    gates = value.get("gates")
    if isinstance(gates, list):
        gate_ids: set[str] = set()
        for index, gate in enumerate(gates):
            label = f"gates[{index}]"
            if not isinstance(gate, dict):
                errors.append(f"{label} must be an object")
                continue
            missing_gate = sorted(REQUIRED_GATE_FIELDS - set(gate))
            if missing_gate:
                errors.append(f"{label} missing fields: {missing_gate}")
            gate_id = gate.get("id")
            if not isinstance(gate_id, str) or not gate_id:
                errors.append(f"{label}.id must be a non-empty string")
            elif gate_id in gate_ids:
                errors.append(f"duplicate gate id: {gate_id}")
            else:
                gate_ids.add(gate_id)
            if gate.get("status") not in GATE_STATUSES:
                errors.append(f"{label}.status is invalid")
            for list_field in ("observations", "evidence", "missing"):
                if list_field in gate and not isinstance(gate[list_field], list):
                    errors.append(f"{label}.{list_field} must be a list")

    positive_status = status in {"PLAN_READY", "AUDIT_PASS", "HEALTHY"}
    if positive_status and isinstance(gates, list):
        bad = [
            gate.get("id", f"index-{index}")
            for index, gate in enumerate(gates)
            if isinstance(gate, dict) and gate.get("status") not in {"PASS", "NOT_APPLICABLE"}
        ]
        if bad:
            errors.append(f"positive top-level status conflicts with gates: {bad}")

    next_action = value.get("next_permitted_action")
    if "next_permitted_action" in value and (
        not isinstance(next_action, str) or not next_action.strip()
    ):
        errors.append("next_permitted_action must be a non-empty string")
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        with args.report.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "INVALID", "errors": [str(exc)]}, sort_keys=True))
        return 2
    errors = validate_report(value)
    print(
        json.dumps(
            {
                "schema": "nhc_aimnet2_workflow_report_validation_v1",
                "status": "VALID" if not errors else "INVALID",
                "errors": errors,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
