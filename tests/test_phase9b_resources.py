"""Phase 9B frozen resource budget and capability expectation regressions.

No chemistry, no server, no compute.

The PySCF resource values deliberately reuse Phase 8B's, because Route D and
Route A must share an identical PySCF envelope for the speedup comparison to be
interpretable, and reusing an already-exercised budget avoids introducing an
unvalidated variable. The AIMNet2 stage gets its own separate budget, because
Phase 9A-I measured a real ~20 s first-call compile cost that must be accounted
for rather than hidden inside the PySCF wall-time.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from nhc_deprot_ranker.quantum import two_endpoint as runner
from nhc_deprot_ranker.quantum.phase8b_permit import FROZEN_RESOURCES as PHASE8B_RESOURCES
from nhc_deprot_ranker.quantum.phase9b_resources import (
    AIMNET2_STAGE_BUDGET,
    PHASE9B_CAPABILITY_IDENTITY_KEY,
    PHASE9B_RESOURCES,
    phase9b_resources_payload,
    phase9b_resources_sha256,
)

_PYSCF_KEYS = (
    "worker_count",
    "computational_threads",
    "cpu_affinity",
    "pyscf_max_memory_mb",
    "hard_wall_timeout_seconds",
    "terminate_grace_seconds",
    "stdout_capture_limit_bytes",
    "stderr_capture_limit_bytes",
)


def test_pyscf_envelope_reuses_the_phase8b_values_exactly() -> None:
    """Both routes must share an identical PySCF envelope."""

    for key in _PYSCF_KEYS:
        assert PHASE9B_RESOURCES[key] == PHASE8B_RESOURCES[key], key
    assert PHASE9B_RESOURCES["computational_threads"] == 4
    assert PHASE9B_RESOURCES["cpu_affinity"] == "0-3"
    assert PHASE9B_RESOURCES["pyscf_max_memory_mb"] == 12_000
    assert PHASE9B_RESOURCES["hard_wall_timeout_seconds"] == 7_200


def test_aimnet2_stage_budget_is_separate_and_accounts_for_compile() -> None:
    """9A-I measured ~21.9 s for the first call; the budget must cover it openly."""

    assert AIMNET2_STAGE_BUDGET["stage"] == "aimnet2_preoptimization"
    assert AIMNET2_STAGE_BUDGET["gpu_count"] == 1
    assert AIMNET2_STAGE_BUDGET["ensemble_members"] == 1
    assert AIMNET2_STAGE_BUDGET["ensemble_uncertainty_available"] is False
    assert AIMNET2_STAGE_BUDGET["compile_model"] is False
    assert AIMNET2_STAGE_BUDGET["measured_first_call_seconds"] == 21.9
    compile_allow = AIMNET2_STAGE_BUDGET["compile_allowance_seconds"]
    assert isinstance(compile_allow, int)
    assert compile_allow >= 22, "must cover the measured first-call cost"


def test_aimnet2_budget_is_not_folded_into_the_pyscf_wall_time() -> None:
    """Hiding preoptimization cost inside the PySCF budget would fake the speedup."""

    assert "hard_wall_timeout_seconds" not in AIMNET2_STAGE_BUDGET
    assert (
        PHASE9B_RESOURCES["hard_wall_timeout_seconds"]
        == PHASE8B_RESOURCES["hard_wall_timeout_seconds"]
    )
    assert "aimnet2" not in json.dumps({k: PHASE9B_RESOURCES[k] for k in _PYSCF_KEYS}).lower()


def test_resources_record_the_separate_stage_accounting() -> None:
    assert PHASE9B_RESOURCES["aimnet2_stage_budget"] == AIMNET2_STAGE_BUDGET
    assert PHASE9B_RESOURCES["total_cost_includes_aimnet2_stage"] is True


def test_resources_hash_is_deterministic_and_canonical() -> None:
    first = phase9b_resources_sha256()
    assert first == phase9b_resources_sha256()
    assert len(first) == 64
    expected = hashlib.sha256(
        (
            json.dumps(
                phase9b_resources_payload(),
                sort_keys=True,
                indent=2,
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()
    assert first == expected


def test_phase9b_resources_hash_differs_from_phase8b() -> None:
    """The separate stage budget makes the envelope genuinely different."""

    assert (
        phase9b_resources_sha256() != runner._frozen_resources_sha256()  # pyright: ignore[reportPrivateUsage]
    )


def test_capability_expectation_is_now_registered() -> None:
    registry = runner._CAPABILITY_IDENTITY_EXPECTATIONS  # pyright: ignore[reportPrivateUsage]
    assert PHASE9B_CAPABILITY_IDENTITY_KEY in registry
    assert sorted(registry) == sorted(
        [runner.PHASE8B_CAPABILITY_IDENTITY_KEY, PHASE9B_CAPABILITY_IDENTITY_KEY]
    )


def test_phase9b_expectation_binds_the_candidate_and_its_provenance() -> None:
    from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE

    build = runner._CAPABILITY_IDENTITY_EXPECTATIONS[  # pyright: ignore[reportPrivateUsage]
        PHASE9B_CAPABILITY_IDENTITY_KEY
    ]
    expected = build()
    assert expected.identity_key == PHASE9B_CAPABILITY_IDENTITY_KEY
    assert expected.inchikey == PHASE9B_CANDIDATE.inchikey
    assert expected.electron_count == 160
    assert expected.resources_sha256 == phase9b_resources_sha256()
    assert expected.legacy_atom_map_sha256 == PHASE9B_CANDIDATE.legacy_atom_map_sha256
    assert expected.endpoint_atom_map_sha256 == PHASE9B_CANDIDATE.endpoint_atom_map_sha256
    assert expected.geometry_validation_sha256 == PHASE9B_CANDIDATE.geometry_validation_sha256


def test_phase8b_and_phase9b_expectations_cannot_be_confused() -> None:
    registry = runner._CAPABILITY_IDENTITY_EXPECTATIONS  # pyright: ignore[reportPrivateUsage]
    eight = registry[runner.PHASE8B_CAPABILITY_IDENTITY_KEY]()
    nine = registry[PHASE9B_CAPABILITY_IDENTITY_KEY]()
    assert eight != nine
    assert eight.electron_count == 120
    assert nine.electron_count == 160
    assert eight.inchikey != nine.inchikey
    assert eight.attempt_id != nine.attempt_id
    assert eight.resources_sha256 != nine.resources_sha256


def test_expectation_attempt_id_is_the_direct_route() -> None:
    """One expectation per key, so the key names the route it authorizes."""

    from nhc_deprot_ranker.quantum.phase9b_permit import ROUTE_ATTEMPT_IDS, ROUTE_DIRECT

    build = runner._CAPABILITY_IDENTITY_EXPECTATIONS[  # pyright: ignore[reportPrivateUsage]
        PHASE9B_CAPABILITY_IDENTITY_KEY
    ]
    assert build().attempt_id == ROUTE_ATTEMPT_IDS[ROUTE_DIRECT]


def test_resources_mapping_is_read_only() -> None:
    with pytest.raises(TypeError):
        PHASE9B_RESOURCES["computational_threads"] = 8  # type: ignore[index]
    with pytest.raises(TypeError):
        AIMNET2_STAGE_BUDGET["gpu_count"] = 2  # type: ignore[index]


def test_expectation_record_stays_immutable() -> None:
    build = runner._CAPABILITY_IDENTITY_EXPECTATIONS[  # pyright: ignore[reportPrivateUsage]
        PHASE9B_CAPABILITY_IDENTITY_KEY
    ]
    expected = build()
    with pytest.raises(FrozenInstanceError):
        expected.electron_count = 120  # type: ignore[misc]
    assert replace(expected, electron_count=120).electron_count == 120
    assert build().electron_count == 160


def test_module_declares_no_label_and_imports_no_chemistry() -> None:
    from nhc_deprot_ranker.quantum import phase9b_resources

    assert phase9b_resources.__file__ is not None
    source = Path(phase9b_resources.__file__).read_text(encoding="utf-8").lower()
    for forbidden in ("import pyscf", "import torch", "import aimnet", "627.509474", "kcal"):
        assert forbidden not in source, forbidden
