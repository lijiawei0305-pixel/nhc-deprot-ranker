#!/usr/bin/env python3
"""Read-only static audit for a topology-aware workflow resource plan."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

MODES = {"ISOLATED_BENCHMARK", "THROUGHPUT_COLLECTION"}
SMT_POLICIES = {"physical_only", "calibrated_logical"}


class InputError(ValueError):
    """Raised when an audit input is malformed."""


def _load_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise InputError(f"{path}: root must be a JSON object")
    return value


def _cpu_set(value: Any, field: str) -> set[int]:
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in value
    ):
        raise InputError(f"{field} must be a list of non-negative integer CPU IDs")
    if len(value) != len(set(value)):
        raise InputError(f"{field} contains duplicate CPU IDs")
    return set(value)


def _positive_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise InputError(f"{field} must be finite and greater than zero")
    return result


def _check(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    criterion: str,
    observations: dict[str, Any],
) -> None:
    checks.append(
        {
            "id": check_id,
            "status": "PASS" if passed else "FAIL",
            "criterion": criterion,
            "observations": observations,
        }
    )


def audit_resource_plan(topology: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Audit a resource plan without changing local or remote state."""

    rows = topology.get("cpus")
    if not isinstance(rows, list) or not rows:
        raise InputError("topology.cpus must be a non-empty list")

    cpu_rows: dict[int, dict[str, int]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise InputError(f"topology.cpus[{index}] must be an object")
        try:
            cpu = int(row["cpu"])
            socket = int(row["socket"])
            core = int(row["core"])
            node = int(row["node"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InputError(
                f"topology.cpus[{index}] requires integer cpu/socket/core/node"
            ) from exc
        if cpu < 0 or cpu in cpu_rows:
            raise InputError("topology CPU IDs must be unique and non-negative")
        if bool(row.get("online", True)):
            cpu_rows[cpu] = {
                "cpu": cpu,
                "socket": socket,
                "core": core,
                "node": node,
            }

    if not cpu_rows:
        raise InputError("topology has no online CPUs")

    online = set(cpu_rows)
    constraints: dict[str, set[int]] = {}
    for field in (
        "scheduler_cpu_list",
        "cgroup_cpu_list",
        "affinity_cpu_list",
    ):
        raw = topology.get(field)
        if raw is not None:
            constraints[field] = _cpu_set(raw, f"topology.{field}")

    allowed = set(online)
    for constrained in constraints.values():
        allowed &= constrained
    if not allowed:
        raise InputError("scheduler/cgroup/affinity intersection is empty")

    unknown_allowed = allowed - online
    if unknown_allowed:
        raise InputError(f"allowed CPU IDs missing from topology: {unknown_allowed}")

    mode = plan.get("mode")
    if mode not in MODES:
        raise InputError(f"plan.mode must be one of {sorted(MODES)}")
    smt_policy = plan.get("smt_policy", "physical_only")
    if smt_policy not in SMT_POLICIES:
        raise InputError(f"plan.smt_policy must be one of {sorted(SMT_POLICIES)}")

    checks: list[dict[str, Any]] = []
    _check(
        checks,
        "authorized_cpu_intersection",
        True,
        "allocations must remain inside scheduler, cgroup, and affinity intersection",
        {
            "allowed_cpu_list": sorted(allowed),
            "constraint_sources": sorted(constraints),
        },
    )

    calibration = plan.get("smt_calibration")
    smt_calibrated = False
    if smt_policy == "calibrated_logical":
        improvement = (
            calibration.get("improvement_percent") if isinstance(calibration, dict) else None
        )
        minimum_improvement = (
            calibration.get("minimum_improvement_percent")
            if isinstance(calibration, dict)
            else None
        )
        improvement_value: float | None = None
        if isinstance(improvement, (int, float)) and not isinstance(improvement, bool):
            candidate_improvement = float(improvement)
            if math.isfinite(candidate_improvement):
                improvement_value = candidate_improvement
        minimum_value: float | None = None
        if isinstance(minimum_improvement, (int, float)) and not isinstance(
            minimum_improvement, bool
        ):
            candidate_minimum = float(minimum_improvement)
            if math.isfinite(candidate_minimum) and candidate_minimum >= 0:
                minimum_value = candidate_minimum
        source = (
            plan.get("benchmark")
            if mode == "ISOLATED_BENCHMARK"
            else plan.get("profile_selection_receipt")
        )
        expected_minimum = (
            source.get("minimum_improvement_percent") if isinstance(source, dict) else None
        )
        expected_value: float | None = None
        if isinstance(expected_minimum, (int, float)) and not isinstance(expected_minimum, bool):
            candidate_expected = float(expected_minimum)
            if math.isfinite(candidate_expected) and candidate_expected >= 0:
                expected_value = candidate_expected
        smt_calibrated = bool(
            isinstance(calibration, dict)
            and calibration.get("accepted") is True
            and calibration.get("aggregate_workload") is True
            and improvement_value is not None
            and minimum_value is not None
            and expected_value is not None
            and minimum_value == expected_value
            and improvement_value >= minimum_value
        )
        _check(
            checks,
            "aggregate_smt_calibration",
            smt_calibrated,
            (
                "logical siblings require an aggregate workload calibration "
                "meeting its preregistered minimum improvement"
            ),
            {"smt_calibration": calibration or "unavailable"},
        )

    memory_safe_mb = _positive_number(topology.get("memory_safe_mb"), "topology.memory_safe_mb")
    allocations = plan.get("allocations")
    if not isinstance(allocations, list) or not allocations:
        raise InputError("plan.allocations must be a non-empty list")

    task_ids: set[str] = set()
    logical_owners: dict[int, list[str]] = defaultdict(list)
    physical_owners: dict[tuple[int, int], list[tuple[str, int]]] = defaultdict(list)
    total_memory_mb = 0.0
    allocation_summary: list[dict[str, Any]] = []

    for index, allocation in enumerate(allocations):
        if not isinstance(allocation, dict):
            raise InputError(f"plan.allocations[{index}] must be an object")
        task_id = allocation.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id in task_ids:
            raise InputError("allocation task_id values must be unique non-empty strings")
        task_ids.add(task_id)
        cpus = _cpu_set(allocation.get("cpu_list"), f"allocation {task_id}.cpu_list")
        if not cpus:
            raise InputError(f"allocation {task_id} has an empty CPU list")
        outside = cpus - allowed
        _check(
            checks,
            f"{task_id}:authorized_cpus",
            not outside,
            "task CPU list must be a subset of the authorized intersection",
            {"cpu_list": sorted(cpus), "outside_allowed": sorted(outside)},
        )
        if outside:
            continue

        max_memory_mb = _positive_number(
            allocation.get("max_memory_mb"),
            f"allocation {task_id}.max_memory_mb",
        )
        total_memory_mb += max_memory_mb
        nodes = sorted({cpu_rows[cpu]["node"] for cpu in cpus})
        physical = {(cpu_rows[cpu]["socket"], cpu_rows[cpu]["core"]) for cpu in cpus}
        for cpu in cpus:
            logical_owners[cpu].append(task_id)
            key = (cpu_rows[cpu]["socket"], cpu_rows[cpu]["core"])
            physical_owners[key].append((task_id, cpu))

        require_numa_local = bool(plan.get("require_numa_local", True))
        _check(
            checks,
            f"{task_id}:numa_locality",
            not require_numa_local or len(nodes) == 1,
            "each allocation must remain NUMA-local unless explicitly disabled",
            {"nodes": nodes, "require_numa_local": require_numa_local},
        )
        allocation_summary.append(
            {
                "task_id": task_id,
                "logical_cpus": len(cpus),
                "physical_cores": len(physical),
                "nodes": nodes,
                "max_memory_mb": max_memory_mb,
            }
        )

    logical_overlap = {
        str(cpu): owners for cpu, owners in logical_owners.items() if len(owners) > 1
    }
    _check(
        checks,
        "logical_cpu_exclusivity",
        not logical_overlap,
        "concurrent allocations must not share a logical CPU",
        {"overlap": logical_overlap},
    )

    sibling_overlap = {
        f"{socket}:{core}": [{"task_id": task_id, "cpu": cpu} for task_id, cpu in owners]
        for (socket, core), owners in physical_owners.items()
        if len(owners) > 1
    }
    sibling_allowed = smt_policy == "calibrated_logical" and smt_calibrated
    _check(
        checks,
        "physical_core_exclusivity",
        not sibling_overlap or sibling_allowed,
        "SMT siblings may be shared only after an accepted aggregate calibration",
        {
            "smt_policy": smt_policy,
            "physical_core_overlap": sibling_overlap,
        },
    )

    _check(
        checks,
        "concurrent_memory_budget",
        total_memory_mb <= memory_safe_mb,
        "sum of concurrent max_memory_mb must not exceed memory_safe_mb",
        {
            "planned_memory_mb": total_memory_mb,
            "memory_safe_mb": memory_safe_mb,
        },
    )

    if mode == "ISOLATED_BENCHMARK":
        benchmark = plan.get("benchmark")
        benchmark_ok = bool(
            isinstance(benchmark, dict)
            and benchmark.get("routes_concurrent") is False
            and benchmark.get("equal_resources") is True
            and benchmark.get("background_load") == "isolated"
            and isinstance(benchmark.get("repetitions"), int)
            and not isinstance(benchmark.get("repetitions"), bool)
            and benchmark.get("repetitions", 0) > 0
            and isinstance(benchmark.get("uncertainty_method"), str)
            and bool(benchmark.get("uncertainty_method"))
            and isinstance(benchmark.get("minimum_improvement_percent"), (int, float))
            and not isinstance(benchmark.get("minimum_improvement_percent"), bool)
            and math.isfinite(float(benchmark["minimum_improvement_percent"]))
            and float(benchmark["minimum_improvement_percent"]) >= 0
            and isinstance(benchmark.get("tie_break"), str)
            and bool(benchmark.get("tie_break"))
        )
        _check(
            checks,
            "benchmark_comparability",
            benchmark_ok,
            (
                "isolated benchmarks require sequential routes, equal resources, "
                "and isolated background load"
            ),
            {"benchmark": benchmark or "unavailable"},
        )
    else:
        receipt = plan.get("profile_selection_receipt")
        receipt_ok = bool(
            isinstance(receipt, dict)
            and isinstance(receipt.get("schema"), str)
            and bool(receipt.get("schema"))
            and isinstance(receipt.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"])
            and isinstance(receipt.get("selected_profile_id"), str)
            and bool(receipt.get("selected_profile_id"))
            and isinstance(receipt.get("workload_identity"), str)
            and bool(receipt.get("workload_identity"))
            and isinstance(receipt.get("warm_cold_policy"), str)
            and bool(receipt.get("warm_cold_policy"))
            and isinstance(receipt.get("accepted_milestones"), list)
            and bool(receipt.get("accepted_milestones"))
            and isinstance(receipt.get("raw_metrics"), dict)
            and bool(receipt.get("raw_metrics"))
            and isinstance(receipt.get("topology_sha256"), str)
            and bool(re.fullmatch(r"[0-9a-f]{64}", receipt["topology_sha256"]))
            and isinstance(receipt.get("software_sha256"), str)
            and bool(re.fullmatch(r"[0-9a-f]{64}", receipt["software_sha256"]))
            and isinstance(receipt.get("rejected_profile_ids"), list)
            and isinstance(receipt.get("repetitions"), int)
            and not isinstance(receipt.get("repetitions"), bool)
            and receipt.get("repetitions", 0) > 0
            and isinstance(receipt.get("uncertainty_method"), str)
            and bool(receipt.get("uncertainty_method"))
            and receipt.get("uncertainty_result") is not None
            and isinstance(receipt.get("minimum_improvement_percent"), (int, float))
            and not isinstance(receipt.get("minimum_improvement_percent"), bool)
            and math.isfinite(float(receipt["minimum_improvement_percent"]))
            and float(receipt["minimum_improvement_percent"]) >= 0
            and isinstance(receipt.get("tie_break"), str)
            and bool(receipt.get("tie_break"))
        )
        _check(
            checks,
            "profile_selection_receipt",
            receipt_ok,
            ("throughput collection requires a complete immutable profile-selection receipt"),
            {"profile_selection_receipt": receipt or "unavailable"},
        )

    physical_all = {(row["socket"], row["core"]) for row in cpu_rows.values()}
    physical_allowed = {(cpu_rows[cpu]["socket"], cpu_rows[cpu]["core"]) for cpu in allowed}
    failed = [item for item in checks if item["status"] == "FAIL"]
    return {
        "schema": "nhc_aimnet2_resource_plan_audit_v1",
        "status": "AUDIT_FAIL" if failed else "AUDIT_PASS",
        "mode": mode,
        "resource_summary": {
            "system_logical": len(online),
            "system_physical": len(physical_all),
            "allowed_logical": len(allowed),
            "allowed_physical": len(physical_allowed),
            "allowed_cpu_list": sorted(allowed),
            "memory_safe_mb": memory_safe_mb,
        },
        "allocations": allocation_summary,
        "checks": checks,
        "failed_check_ids": [item["id"] for item in failed],
        "audit_scope": "static_resource_plan_only",
        "timing_claim": "not_evaluated_by_static_resource_audit",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = audit_resource_plan(
            _load_object(args.topology),
            _load_object(args.plan),
        )
    except (InputError, OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "schema": "nhc_aimnet2_resource_plan_audit_v1",
                    "status": "INCONCLUSIVE",
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "AUDIT_PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
