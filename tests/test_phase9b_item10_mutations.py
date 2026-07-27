"""Executable registry for all 32 preregistered Item 10 mutations."""

# ruff: noqa: E501 -- mutation identifiers intentionally retain exact guard names.

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_TEST = ROOT / "tests/test_phase9b_split_process_runtime.py"
LINUX_TEST = ROOT / "tests/test_phase9b_split_process_linux.py"

# Each mutation names the guard test that fails if the mutation is introduced.
# This table is itself regression-tested for exact coverage, so a mutation
# cannot silently disappear from the suite or report.
MUTATION_GUARDS = {
    "01_supervisor_modifies_a1_proposal": "test_handoff_three_receipts_are_immutable_and_exact_byte_closed",
    "02_same_handoff_receipt_written_twice": "test_handoff_three_receipts_are_immutable_and_exact_byte_closed",
    "03_supervisor_claims_permit_consumption": "test_state_ownership_is_source_separated",
    "04_capability_before_registration": "test_capability_is_post_registration_one_shot_stage_and_boot_bound",
    "05_supervisor_stage_pgid_mixed": "test_process_identity_rejects_shared_process_group",
    "06_permit_binds_fake_absolute_deadline": "test_permit_binds_durations_not_absolute_timestamp_and_renderer_stays_false",
    "07_boot_identity_not_checked": "test_capability_is_post_registration_one_shot_stage_and_boot_bound",
    "08_a2_gets_new_7200_seconds": "test_a2_cannot_receive_a_fresh_campaign_budget",
    "09_duplicate_closure_ownership": "test_source_closure_rejects_duplicate_cycle_and_missing_dependency",
    "10_closure_dependency_cycle": "test_source_closure_rejects_duplicate_cycle_and_missing_dependency",
    "11_mixed_generation_leaf": "test_v3_paired_generation_is_non_authorizing_and_mixed_generation_closed",
    "12_request_supplies_interpreter_path": "test_public_profiles_contain_no_private_paths_and_direct_a2_digest_is_one",
    "13_external_launch_a1_or_a2": "test_external_launch_surface_has_guardians_only",
    "14_two_ordinary_assisted_permits": "test_assisted_authority_is_one_campaign_permit",
    "15_internal_capability_replay": "test_capability_is_post_registration_one_shot_stage_and_boot_bound",
    "16_a2_before_a1_reap": "test_linux_real_subprocess_campaign_is_sequential_reaped_and_hash_closed",
    "17_residual_a1_still_starts_a2": "test_linux_real_subprocess_campaign_is_sequential_reaped_and_hash_closed",
    "18_parent_memory_coordinates": "test_a2_rereads_disk_and_passes_same_bytes_to_shared_parser",
    "19_a2_does_not_reread_disk": "test_a2_rereads_disk_and_passes_same_bytes_to_shared_parser",
    "20_output_hash_not_verified": "test_handoff_rejects_modified_reformatted_reordered_and_identity_drift",
    "21_atom_order_charge_mult_not_verified": "test_handoff_rejects_modified_reformatted_reordered_and_identity_drift",
    "22_a1_loads_model_twice": "test_a1_source_has_single_model_load_guard",
    "23_soscf_reruns_a1": "test_v8_direct_characterization_and_shared_core_are_byte_identical",
    "24_a1_imports_pyscf": "test_stage_import_boundaries_are_source_closed",
    "25_a2_imports_aimnet": "test_stage_import_boundaries_are_source_closed",
    "26_pythonpath_stitching": "test_no_runtime_source_uses_pypath_or_exposes_stage_launch_commands",
    "27_direct_a2_different_core": "test_source_closure_is_disjoint_acyclic_and_direct_a2_share_core",
    "28_aimnet_energy_enters_label": "test_shared_core_is_only_label_owner",
    "29_failure_produces_label": "test_campaign_terminal_rejects_label_on_failure",
    "30_extra_evidence_file_accepted": "test_evidence_store_refuses_overwrite_symlink_extra_and_unregistered_path",
    "31_v8_overwritten_not_superseded": "test_v8_supersession_is_append_only_documented",
    "32_real_permit_generated": "test_permit_binds_durations_not_absolute_timestamp_and_renderer_stays_false",
}


def test_mutation_registry_has_exact_32_unique_cases_and_live_guards() -> None:
    assert len(MUTATION_GUARDS) == 32
    assert tuple(MUTATION_GUARDS) == tuple(sorted(MUTATION_GUARDS))
    source = (
        RUNTIME_TEST.read_text(encoding="utf-8")
        + LINUX_TEST.read_text(encoding="utf-8")
        + Path(__file__).read_text(encoding="utf-8")
    )
    tree = ast.parse(source)
    test_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = sorted(set(MUTATION_GUARDS.values()) - test_names)
    assert not missing, missing


def test_state_ownership_is_source_separated() -> None:
    guardian = (ROOT / "src/nhc_deprot_ranker/quantum/phase9b_campaign_guardian.py").read_text()
    supervisor = (ROOT / "src/nhc_deprot_ranker/quantum/phase9b_campaign_supervisor.py").read_text()
    assert "consume_one_shot_permit" in guardian
    assert "consume_one_shot_permit" not in supervisor
    assert "PERMIT_CONSUMED" not in supervisor


def test_process_identity_rejects_shared_process_group() -> None:
    from nhc_deprot_ranker.quantum.phase9b_internal_stage_capability import (
        InternalStageCapabilityError,
        RegisteredProcessIdentity,
    )

    with pytest.raises(InternalStageCapabilityError, match="process groups must differ"):
        RegisteredProcessIdentity(
            supervisor_pid=20,
            supervisor_start_time=100,
            supervisor_session_id=20,
            supervisor_process_group_id=10,
            stage_pid=10,
            stage_start_time=200,
            stage_session_id=10,
            stage_process_group_id=10,
            expected_parent_pid=20,
        )


def test_a2_cannot_receive_a_fresh_campaign_budget() -> None:
    source = (
        ROOT / "src/nhc_deprot_ranker/quantum/phase9b_internal_stage_capability.py"
    ).read_text()
    assert "stage_end <= campaign_end" in source
    assert "campaign_end - start != 7_200_000_000_000" in source
    assert (
        "stage_deadline_ns=campaign_deadline"
        in (ROOT / "src/nhc_deprot_ranker/quantum/phase9b_campaign_supervisor.py").read_text()
    )


def test_assisted_authority_is_one_campaign_permit() -> None:
    guardian = (ROOT / "src/nhc_deprot_ranker/quantum/phase9b_campaign_guardian.py").read_text()
    supervisor = (ROOT / "src/nhc_deprot_ranker/quantum/phase9b_campaign_supervisor.py").read_text()
    assert guardian.count("consume_one_shot_permit(") == 1
    assert "ordinary permit" not in supervisor.lower()
    assert "issue_internal_stage_capability" in supervisor


def test_a1_source_has_single_model_load_guard() -> None:
    source = (ROOT / "src/nhc_deprot_ranker/quantum/phase9b_stage_a1.py").read_text()
    assert "load_base_model_once" in source
    assert "runtime.model_load_count != 0" in source
    assert "runtime.model_load_count != 1" in source


def test_stage_import_boundaries_are_source_closed() -> None:
    a1 = (ROOT / "src/nhc_deprot_ranker/quantum/phase9b_stage_a1.py").read_text()
    a2 = (ROOT / "src/nhc_deprot_ranker/quantum/phase9b_stage_a2.py").read_text()
    assert 'forbidden = {"pyscf", "geometric", "pyscf_dispersion"}' in a1
    assert 'forbidden = {"aimnet", "ase", "torch"}' in a2
    assert "from pyscf" not in a1
    assert "from aimnet" not in a2


def test_shared_core_is_only_label_owner() -> None:
    a1 = (ROOT / "src/nhc_deprot_ranker/quantum/phase9b_stage_a1.py").read_text()
    core = (ROOT / "src/nhc_deprot_ranker/quantum/phase9b_shared_pyscf_core.py").read_text()
    assert "dft_deprot_electronic_kcal" not in a1
    assert "_execute_validated_request" in core


def test_campaign_terminal_rejects_label_on_failure() -> None:
    from nhc_deprot_ranker.quantum.phase9b_campaign_schemas import (
        AssistedCampaignTerminalReceiptV1,
        CampaignSchemaError,
    )

    with pytest.raises(CampaignSchemaError, match="null label"):
        AssistedCampaignTerminalReceiptV1(
            {
                "schema_version": AssistedCampaignTerminalReceiptV1.SCHEMA_VERSION,
                "campaign_id": "campaign-v1",
                "attempt_id": "attempt-v1",
                "candidate": "candidate-v1",
                "route": "assisted",
                "guardian_launch_state": "acknowledged",
                "campaign_runtime_state": "route_rejected",
                "route_outcome": "rejected",
                "schedule_sha256": "1" * 64,
                "evidence_manifest_sha256": "2" * 64,
                "a1_terminal_sha256": None,
                "handoff_verification_sha256": None,
                "a2_admission_sha256": None,
                "a2_terminal_sha256": None,
                "label": {"forbidden": True},
                "failure": {"classification": "failed"},
            }
        )


def test_v8_supersession_is_append_only_documented() -> None:
    identity = (ROOT / "docs/PHASE9B_IDENTITY_REBASELINE.md").read_text()
    manifest = (ROOT / "docs/PHASE9B_RUNNER_SOURCE_V9_MANIFEST.json").read_text()
    v8 = "5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2"
    assert v8 in identity and v8 in manifest
    assert "superseded_before_execution" in identity
    assert '"deployed": false' in manifest
    assert '"permit_consumed": false' in manifest
