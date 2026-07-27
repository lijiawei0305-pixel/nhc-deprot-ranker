from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
V8_SHA256 = "5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2"

DESIGN_DOCS = (
    "PHASE9B_SPLIT_PROCESS_RUNTIME_PLAN.md",
    "PHASE9B_SPLIT_PROCESS_AUTHORITY_CHAIN.md",
    "PHASE9B_INTERNAL_STAGE_CAPABILITY_CONTRACT.md",
    "PHASE9B_CROSS_PROCESS_HANDOFF_CONTRACT.md",
    "PHASE9B_CAMPAIGN_SUPERVISOR_STATE_MACHINE.md",
    "PHASE9B_SPLIT_PROCESS_FAILURE_SEMANTICS.md",
    "PHASE9B_SPLIT_PROCESS_EVIDENCE_TREE.md",
    "PHASE9B_DIRECT_ASSISTED_PYSCF_PARITY.md",
    "PHASE9B_SPLIT_PROCESS_SOURCE_IDENTITY_PLAN.md",
    "PHASE9B_SPLIT_PROCESS_IMPLEMENTATION_PLAN.md",
    "PHASE9B_SPLIT_PROCESS_TEST_PLAN.md",
    "PHASE9B_SPLIT_PROCESS_REACHABILITY_AUDIT.md",
    "PHASE9B_UNIFIED_ENVIRONMENT_STRATEGY_CLOSEOUT.md",
)

SCHEMA_EXAMPLES = (
    "phase9b_assisted_campaign_permit_v3.example.json",
    "phase9b_internal_stage_capability_v1.example.json",
    "phase9b_cross_process_handoff_v1.example.json",
    "phase9b_campaign_terminal_v1.example.json",
)


def _read(name: str) -> str:
    return (ROOT / "docs" / name).read_text(encoding="utf-8")


def test_design_documents_exist_and_freeze_one_campaign() -> None:
    combined = "\n".join(_read(name) for name in DESIGN_DOCS)
    for phrase in (
        "closed_after_u5",
        "frozen_attempt_policy",
        "observed_but_no_validated_identity",
        "AssistedCampaignPermitV3",
        "InternalStageCapabilityV1",
        "CrossProcessPySCFHandoffReceiptV1",
        "StageA2AdmissionReceiptV1",
        "DirectAssistedPySCFParityContractV1",
        "campaign_absolute_deadline",
        "base model",
        "one model load",
        "A2",
        "re-reads",
        "no overlap",
    ):
        assert phrase in combined
    assert "no further unified-environment attempt" in combined
    assert "two ordinary assisted permits" in combined


def test_item_numbering_and_v8_boundary_are_consistent() -> None:
    status = (ROOT / "PHASE_STATUS.md").read_text(encoding="utf-8")
    plan = _read("PHASE9B_SPLIT_PROCESS_RUNTIME_PLAN.md")
    identity = _read("PHASE9B_SPLIT_PROCESS_SOURCE_IDENTITY_PLAN.md")
    for text in (status, plan):
        assert "9/12" in text
        assert "10/12" in text
        assert "11/12" in text
        assert "12/12" in text
    for text in (status, identity):
        assert V8_SHA256 in text
        assert "superseded_before_execution" in text
    assert "no v9 hash" in identity


def test_schema_examples_are_json_and_non_authorizing() -> None:
    schema_root = ROOT / "docs" / "schemas"
    for name in SCHEMA_EXAMPLES:
        payload = json.loads((schema_root / name).read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        assert isinstance(payload.get("schema_version"), str)
    permit = json.loads((schema_root / SCHEMA_EXAMPLES[0]).read_text(encoding="utf-8"))
    assert permit["authorization"]["execution_authorized"] is False
    assert permit["authorization"]["one_shot"] is True
    assert permit["authorization"]["retry_authorized"] is False


def _permit_example_holds_contract(payload: dict[str, object]) -> bool:
    authorization = payload.get("authorization")
    campaign = payload.get("campaign")
    profiles = payload.get("profiles")
    source = payload.get("source")
    if not all(isinstance(value, dict) for value in (authorization, campaign, profiles, source)):
        return False
    assert isinstance(authorization, dict)
    assert isinstance(campaign, dict)
    assert isinstance(profiles, dict)
    assert isinstance(source, dict)
    return (
        authorization.get("execution_authorized") is False
        and authorization.get("one_shot") is True
        and authorization.get("retry_authorized") is False
        and authorization.get("resume_authorized") is False
        and campaign.get("schedule")
        == [
            "aimnet2_preoptimization",
            "handoff_verification",
            "pyscf_residual_optimization",
        ]
        and campaign.get("deadline_seconds") == 7200
        and profiles.get("stage_a1") == "phase9b-mlff-profile-v1"
        and profiles.get("stage_a2") == "phase9b-gpupyscf-profile-v1"
        and set(source)
        == {
            "campaign_control_source_sha256",
            "full_assisted_campaign_source_sha256",
            "shared_pyscf_core_source_sha256",
            "shared_schema_source_sha256",
            "stage_a1_source_sha256",
            "stage_a2_source_sha256",
        }
    )


def test_permit_example_mutations_fail_closed() -> None:
    path = ROOT / "docs" / "schemas" / SCHEMA_EXAMPLES[0]
    original = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    assert _permit_example_holds_contract(original)
    mutations: list[dict[str, object]] = []
    for section, key, value in (
        ("authorization", "one_shot", False),
        ("authorization", "retry_authorized", True),
        ("campaign", "deadline_seconds", 8100),
        ("profiles", "stage_a2", "phase9b-mlff-profile-v1"),
    ):
        mutated = copy.deepcopy(original)
        cast(dict[str, object], mutated[section])[key] = value
        mutations.append(mutated)
    missing_handoff = copy.deepcopy(original)
    cast(dict[str, object], missing_handoff["campaign"])["schedule"] = [
        "aimnet2_preoptimization",
        "pyscf_residual_optimization",
    ]
    mutations.append(missing_handoff)
    missing_source = copy.deepcopy(original)
    del cast(dict[str, object], missing_source["source"])["stage_a2_source_sha256"]
    mutations.append(missing_source)
    assert all(not _permit_example_holds_contract(mutated) for mutated in mutations)


def test_all_public_execution_gates_remain_false() -> None:
    assignments: list[tuple[Path, bool]] = []
    for path in sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AnnAssign | ast.Assign):
                continue
            names: list[str] = []
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.append(node.target.id)
            elif isinstance(node, ast.Assign):
                names.extend(target.id for target in node.targets if isinstance(target, ast.Name))
            if "EXECUTION_AUTHORIZED" in names:
                is_false = isinstance(node.value, ast.Constant) and node.value.value is False
                assignments.append((path, is_false))
    assert len(assignments) == 11
    assert all(is_false for _path, is_false in assignments)


def test_design_does_not_expose_stage_launch_or_second_deadline() -> None:
    plan = _read("PHASE9B_SPLIT_PROCESS_RUNTIME_PLAN.md")
    capability = _read("PHASE9B_INTERNAL_STAGE_CAPABILITY_CONTRACT.md")
    implementation = _read("PHASE9B_SPLIT_PROCESS_IMPLEMENTATION_PLAN.md")
    assert "no external `launch-a1` or `launch-a2`" in capability
    assert "A2 receives the remaining campaign time, never a fresh 7200 seconds" in plan
    assert "exposing no public stage launch" in implementation


def test_production_label_count_remains_71() -> None:
    status = (ROOT / "PHASE_STATUS.md").read_text(encoding="utf-8")
    agent = (ROOT / "AGENT.md").read_text(encoding="utf-8")
    assert "production high-fidelity label count is 71" in status
    assert "生产标签持续 71" in agent
