"""Frozen Phase 9B resource budget.

The PySCF envelope deliberately **reuses the Phase 8B values verbatim**.  Two
reasons, both about interpretability rather than convenience:

- Route D and Route A must share an identical PySCF envelope, or any measured
  speedup is uninterpretable;
- reusing a budget that was already exercised in a real attempt avoids
  introducing an unvalidated variable alongside the one being tested.

The AIMNet2 preoptimization stage gets its **own separate budget**.  Phase 9A-I
measured a real first-call cost of 21.9 s, dominated by ``torch.compile``, against
1.6 s and 0.2 s for later calls.  Folding that into the PySCF wall-time would
hide preoptimization cost inside the number being compared, which is exactly the
accounting error `docs/PHASE9B_SINGLE_MEMBER_SAFEGUARDS.md` forbids.  Keeping it
separate makes ``total_assisted_time`` auditable.

This module holds data only.  It grants nothing, and it is deliberately not yet
in the runner source closure.

No chemistry import, no compute, no label.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from nhc_deprot_ranker.quantum.phase8b_permit import FROZEN_RESOURCES as _PHASE8B_RESOURCES

PHASE9B_CAPABILITY_IDENTITY_KEY: Final = "phase9b-lbnp-paired-smoke"

# Measured in Phase 9A-I on one free V100, six single-point calls in three clean
# processes.  Recorded here so the allowance has a stated basis rather than a
# guessed margin.
_MEASURED_FIRST_CALL_SECONDS: Final = 21.9

AIMNET2_STAGE_BUDGET: Final[Mapping[str, object]] = MappingProxyType(
    {
        "stage": "aimnet2_preoptimization",
        "gpu_count": 1,
        "gpu_selection_rule": "single_currently_free_device_or_fail_closed",
        "ensemble_members": 1,
        "ensemble_uncertainty_available": False,
        "compile_model": False,
        "measured_first_call_seconds": _MEASURED_FIRST_CALL_SECONDS,
        # Covers the measured compile cost with a small margin; it is a fixed
        # per-process cost, not a per-step one.
        "compile_allowance_seconds": 60,
        "max_preopt_walltime_seconds": 900,
        "cache_isolation_required": True,
        "isolated_cache_variables": (
            "TORCHINDUCTOR_CACHE_DIR",
            "TRITON_CACHE_DIR",
            "CUDA_CACHE_PATH",
            "TORCH_HOME",
            "XDG_CACHE_HOME",
            "HF_HOME",
            "TMPDIR",
        ),
    }
)

PHASE9B_RESOURCES: Final[Mapping[str, object]] = MappingProxyType(
    {
        # PySCF envelope, identical to Phase 8B so the two routes are comparable.
        "worker_count": _PHASE8B_RESOURCES["worker_count"],
        "computational_threads": _PHASE8B_RESOURCES["computational_threads"],
        "cpu_affinity": _PHASE8B_RESOURCES["cpu_affinity"],
        "pyscf_max_memory_mb": _PHASE8B_RESOURCES["pyscf_max_memory_mb"],
        "hard_wall_timeout_seconds": _PHASE8B_RESOURCES["hard_wall_timeout_seconds"],
        "terminate_grace_seconds": _PHASE8B_RESOURCES["terminate_grace_seconds"],
        "stdout_capture_limit_bytes": _PHASE8B_RESOURCES["stdout_capture_limit_bytes"],
        "stderr_capture_limit_bytes": _PHASE8B_RESOURCES["stderr_capture_limit_bytes"],
        # Separate stage accounting; never merged into the PySCF wall-time.
        "aimnet2_stage_budget": AIMNET2_STAGE_BUDGET,
        "total_cost_includes_aimnet2_stage": True,
        "routes": ("direct", "assisted"),
        "identical_pyscf_envelope_across_routes": True,
    }
)


def _normalize(value: object) -> object:
    """Recursively convert read-only views and tuples into plain JSON types.

    ``MappingProxyType`` is not JSON serializable, so the digest needs an explicit
    canonical form rather than relying on the mapping objects themselves.
    """

    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_normalize(item) for item in value]
    return value


def phase9b_resources_payload() -> dict[str, object]:
    """The frozen budget as plain JSON types, exactly as hashed."""

    normalized = _normalize(PHASE9B_RESOURCES)
    if not isinstance(normalized, dict):  # pragma: no cover - structural guard
        raise TypeError("Phase 9B resources must normalize to one JSON object")
    return normalized


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def phase9b_resources_sha256() -> str:
    """Canonical digest of the frozen Phase 9B resource budget."""

    return hashlib.sha256(_canonical_json_bytes(phase9b_resources_payload())).hexdigest()


__all__ = [
    "AIMNET2_STAGE_BUDGET",
    "PHASE9B_CAPABILITY_IDENTITY_KEY",
    "PHASE9B_RESOURCES",
    "phase9b_resources_payload",
    "phase9b_resources_sha256",
]
