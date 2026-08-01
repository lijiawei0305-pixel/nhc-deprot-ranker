from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "PHASE9B_AIMNET2_PRECONDITIONER_CONTRACT_V001.json"
GAU_LOOSE = ROOT / "docs" / "PHASE9B_AIMNET2_GAU_LOOSE_V001.yaml"


def _contract() -> dict[str, object]:
    return cast(dict[str, object], json.loads(CONTRACT.read_text(encoding="utf-8")))


def test_preconditioner_stopping_and_mandatory_parent_optimization() -> None:
    payload = _contract()
    stopping = payload["aimnet2_preoptimization"]
    assert isinstance(stopping, dict)
    assert stopping["role"] == "preconditioner_for_parent_pyscf_optimization"
    assert stopping["optimizer"] == "ASE_LBFGS"
    assert stopping["fmax_eV_A"] == 0.10
    assert stopping["max_steps"] == 100
    assert stopping["energy_change"] == "required_by_GAU_LOOSE"

    handoff = payload["handoff"]
    assert isinstance(handoff, dict)
    assert handoff["next_stage"] == "full_parent_level_pyscf_geometric_optimization"
    assert handoff["single_point_only"] is False
    assert handoff["single_point_only_eligible"] is False

    gau_loose = yaml.safe_load(GAU_LOOSE.read_text(encoding="utf-8"))
    assert gau_loose["aimnet2_surface_convergence"]["require_all_five"] is True
    assert gau_loose["parent_final_convergence"]["profile"] == "GAU"
    identity = payload["gau_loose_contract"]
    assert isinstance(identity, dict)
    assert identity["sha256"] == hashlib.sha256(GAU_LOOSE.read_bytes()).hexdigest()
    ready = payload["preconditioner_ready_requires"]
    assert isinstance(ready, list)
    assert {
        "gau_loose_energy_change_pass",
        "gau_loose_gradient_rms_pass",
        "gau_loose_gradient_max_pass",
        "gau_loose_displacement_rms_pass",
        "gau_loose_displacement_max_pass",
    } <= set(ready)


def test_preconditioner_contract_separates_all_three_baselines() -> None:
    baselines = _contract()["comparison_baselines"]
    assert isinstance(baselines, dict)
    assert len(set(baselines.values())) == 4
    assert baselines["fine_tuned_model"] == "epoch_0000_unchanged_base_aimnet2"
    assert baselines["parent_gradient"] == "same_endpoint_frozen_initial_geometry"


def test_preconditioner_contract_does_not_overclaim_readiness() -> None:
    payload = _contract()
    readiness = payload["threshold_readiness"]
    assert isinstance(readiness, dict)
    assert readiness["state"] == "BLOCKED_BEFORE_TRAINING"
    assert payload["maximum_reachable_terminal"] == "FINAL_TEST_ACCEPTED"
    forbidden = payload["claims_forbidden"]
    assert isinstance(forbidden, list)
    assert "single_point_only_eligible" in forbidden
    assert "pyscf_geometry_optimization_may_be_skipped" in forbidden


def test_skill_distinguishes_preconditioner_from_single_point_promotion() -> None:
    skill = (ROOT / ".codex" / "skills" / "plan-nhc-aimnet2-workflow" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    handoff = (
        ROOT
        / ".codex"
        / "skills"
        / "plan-nhc-aimnet2-workflow"
        / "references"
        / "aimnet2-handoff-promotion.md"
    ).read_text(encoding="utf-8")
    assert "AIMNET2_PRECONDITIONER_READY" in skill
    assert "PRECONDITIONER_FULL_PARENT_OPT" in handoff
    assert "single_point_only_eligible` remains\nfalse" in handoff
