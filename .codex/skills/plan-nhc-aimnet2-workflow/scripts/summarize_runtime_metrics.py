#!/usr/bin/env python3
"""Summarize measured workflow throughput without inventing missing metrics."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


class InputError(ValueError):
    """Raised when runtime observations are malformed."""


def _load_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise InputError("runtime input root must be an object")
    return value


def _number(
    value: Any,
    field: str,
    *,
    positive: bool = False,
    optional: bool = False,
) -> float | None:
    if value in (None, "unavailable"):
        if optional:
            return None
        raise InputError(f"{field} is required")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        raise InputError(f"{field} has an invalid value")
    return result


def _available_ratio(numerator: float | None, denominator: float | None) -> Any:
    if numerator is None or denominator is None or denominator <= 0:
        return "unavailable"
    return numerator / denominator


def summarize_runtime_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    mode = payload.get("mode")
    if mode not in {"ISOLATED_BENCHMARK", "THROUGHPUT_COLLECTION"}:
        raise InputError("mode must be ISOLATED_BENCHMARK or THROUGHPUT_COLLECTION")
    runs = payload.get("runs")
    if not isinstance(runs, list) or not runs:
        raise InputError("runs must be a non-empty list")

    seen_tasks: set[str] = set()
    seen_candidate_endpoints: set[tuple[str, str]] = set()
    candidate_endpoints: dict[str, dict[str, str]] = defaultdict(dict)
    accepted_frames = 0
    allocated_core_seconds = 0.0
    measured_cpu_seconds = 0.0
    cpu_complete = True
    queue_wait_total = 0.0
    queue_complete = True
    gpu_active_total = 0.0
    gpu_allocated_total = 0.0
    gpu_complete = True
    peak_rss_values: list[float] = []
    pass_runs = 0

    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            raise InputError(f"runs[{index}] must be an object")
        task_id = run.get("task_id")
        candidate = run.get("candidate_id")
        endpoint = run.get("endpoint")
        outcome = run.get("outcome")
        if not isinstance(task_id, str) or not task_id or task_id in seen_tasks:
            raise InputError("task_id values must be unique non-empty strings")
        if not isinstance(candidate, str) or not candidate:
            raise InputError(f"{task_id}: candidate_id is required")
        if endpoint not in {"cation", "neutral"}:
            raise InputError(f"{task_id}: endpoint must be cation or neutral")
        if outcome not in {"PASS", "FAIL", "TIMEOUT", "INCONCLUSIVE"}:
            raise InputError(f"{task_id}: unsupported outcome")
        candidate_endpoint = (candidate, endpoint)
        if candidate_endpoint in seen_candidate_endpoints:
            raise InputError(
                f"{task_id}: duplicate candidate/endpoint observation violates no-retry accounting"
            )
        seen_tasks.add(task_id)
        seen_candidate_endpoints.add(candidate_endpoint)
        candidate_endpoints[candidate][endpoint] = outcome
        if outcome == "PASS":
            pass_runs += 1

        wall = _number(run.get("wall_seconds"), f"{task_id}.wall_seconds", positive=True)
        cores = _number(
            run.get("allocated_physical_cores"),
            f"{task_id}.allocated_physical_cores",
            positive=True,
        )
        assert wall is not None and cores is not None
        allocated_core_seconds += wall * cores

        frames = run.get("accepted_frames", 0)
        if isinstance(frames, bool) or not isinstance(frames, int) or frames < 0:
            raise InputError(f"{task_id}.accepted_frames must be a non-negative integer")
        accepted_frames += frames

        user_cpu = _number(
            run.get("cpu_user_seconds"),
            f"{task_id}.cpu_user_seconds",
            optional=True,
        )
        system_cpu = _number(
            run.get("cpu_system_seconds"),
            f"{task_id}.cpu_system_seconds",
            optional=True,
        )
        if user_cpu is None or system_cpu is None:
            cpu_complete = False
        else:
            measured_cpu_seconds += user_cpu + system_cpu

        queue_wait = _number(
            run.get("queue_wait_seconds"),
            f"{task_id}.queue_wait_seconds",
            optional=True,
        )
        if queue_wait is None:
            queue_complete = False
        else:
            queue_wait_total += queue_wait

        gpu_active = _number(
            run.get("gpu_active_seconds"),
            f"{task_id}.gpu_active_seconds",
            optional=True,
        )
        gpu_allocated = _number(
            run.get("gpu_allocated_seconds"),
            f"{task_id}.gpu_allocated_seconds",
            optional=True,
        )
        if gpu_active is None or gpu_allocated is None:
            gpu_complete = False
        else:
            gpu_active_total += gpu_active
            gpu_allocated_total += gpu_allocated

        peak_rss = _number(
            run.get("peak_rss_bytes"),
            f"{task_id}.peak_rss_bytes",
            optional=True,
        )
        if peak_rss is not None:
            peak_rss_values.append(peak_rss)

    pass_candidates = sum(
        endpoints.get("cation") == "PASS" and endpoints.get("neutral") == "PASS"
        for endpoints in candidate_endpoints.values()
    )
    observation_window = _number(
        payload.get("observation_window_seconds"),
        "observation_window_seconds",
        positive=True,
        optional=True,
    )
    core_hours = allocated_core_seconds / 3600.0
    cpu_seconds_value: Any = measured_cpu_seconds if cpu_complete else "unavailable"
    queue_value: Any = queue_wait_total if queue_complete else "unavailable"
    gpu_active_fraction: Any = (
        _available_ratio(gpu_active_total, gpu_allocated_total) if gpu_complete else "unavailable"
    )
    candidates_per_day: Any = (
        pass_candidates / (observation_window / 86400.0)
        if observation_window is not None
        else "unavailable"
    )
    tail_idle = _number(
        payload.get("tail_idle_seconds"),
        "tail_idle_seconds",
        optional=True,
    )

    warnings: list[str] = []
    if not cpu_complete:
        warnings.append("cpu_time_incomplete")
    if not queue_complete:
        warnings.append("queue_wait_incomplete")
    if not gpu_complete:
        warnings.append("gpu_activity_incomplete")
    if mode == "THROUGHPUT_COLLECTION":
        warnings.append("wall_time_not_an_isolated_speedup_claim")

    return {
        "schema": "nhc_aimnet2_runtime_metrics_v1",
        "mode": mode,
        "runs": len(runs),
        "pass_runs": pass_runs,
        "candidate_count": len(candidate_endpoints),
        "pass_candidates": pass_candidates,
        "accepted_frames": accepted_frames,
        "allocated_physical_core_hours": core_hours,
        "measured_cpu_seconds": cpu_seconds_value,
        "physical_core_efficiency": (
            measured_cpu_seconds / allocated_core_seconds
            if cpu_complete and allocated_core_seconds > 0
            else "unavailable"
        ),
        "accepted_frames_per_core_hour": (
            accepted_frames / core_hours if core_hours > 0 else "unavailable"
        ),
        "pass_candidates_per_day": candidates_per_day,
        "queue_wait_seconds_total": queue_value,
        "tail_idle_seconds": (tail_idle if tail_idle is not None else "unavailable"),
        "peak_rss_bytes": max(peak_rss_values) if peak_rss_values else "unavailable",
        "gpu_active_fraction": gpu_active_fraction,
        "warnings": warnings,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = summarize_runtime_metrics(_load_object(args.input))
    except (InputError, OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "schema": "nhc_aimnet2_runtime_metrics_v1",
                    "status": "INCONCLUSIVE",
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
