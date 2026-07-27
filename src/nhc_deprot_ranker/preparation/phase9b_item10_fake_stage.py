"""Linux subprocess fixture for Item 10; imports no chemistry packages.

This module is outside every v9 executable source leaf and can never be selected
by a production request, permit, guardian, or launch adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from nhc_deprot_ranker.quantum.phase9b_campaign_evidence import (
    IMMUTABLE_DATA_MODE,
    CampaignEvidenceStore,
)
from nhc_deprot_ranker.quantum.phase9b_campaign_schemas import (
    StageA1TerminalReceiptV1,
    StageA2TerminalReceiptV1,
    StageCapabilityConsumptionReceiptV1,
    canonical_json_bytes,
)
from nhc_deprot_ranker.quantum.phase9b_cross_process_handoff import (
    A1HandoffProposalReceiptV1,
    EndpointHandoffProposalV1,
    StageA2AdmissionReceiptV1,
    SupervisorHandoffVerificationReceiptV1,
    element_order_sha256,
    parse_xyz_elements,
)
from nhc_deprot_ranker.quantum.phase9b_internal_stage_capability import (
    PHASE9B_A1_STAGE_PROFILE,
    PHASE9B_A2_STAGE_PROFILE,
    InternalStageCapabilityV1,
    run_registered_stage_bootstrap,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-kind", required=True, choices=("a1", "a2"))
    parser.add_argument("--registration-fd", required=True, type=int)
    parser.add_argument("--release-fd", required=True, type=int)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--supervisor-pid", required=True, type=int)
    parser.add_argument("--supervisor-start-time", required=True, type=int)
    parser.add_argument("--supervisor-session-id", required=True, type=int)
    parser.add_argument("--supervisor-process-group-id", required=True, type=int)
    parser.add_argument("--stage-source-sha256", required=True)
    parser.add_argument("--registration-nonce-sha256", required=True)
    parser.add_argument("--clock-domain-digest", required=True)
    parser.add_argument("--linux-boot-id-sha256", required=True)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--fixture-path", required=True, type=Path)
    return parser


def _consume(
    capability: InternalStageCapabilityV1,
    store: CampaignEvidenceStore,
    stage_prefix: str,
) -> None:
    payload = capability.to_payload()
    process_sha = hashlib.sha256(canonical_json_bytes(payload["process_identity"])).hexdigest()
    receipt = StageCapabilityConsumptionReceiptV1(
        {
            "schema_version": StageCapabilityConsumptionReceiptV1.SCHEMA_VERSION,
            "campaign_id": capability.campaign_id,
            "attempt_id": capability.attempt_id,
            "stage": capability.stage.value,
            "registration_sha256": capability.registration_receipt_sha256,
            "capability_sha256": capability.sha256(),
            "release_token_sha256": capability.release_token_sha256,
            "consumer_process_identity_sha256": process_sha,
            "consumed_once": True,
        }
    )
    store.write_bytes(
        f"runtime/{stage_prefix}/capability_consumption.json", receipt.canonical_bytes()
    )


def _run_a1(
    values: argparse.Namespace,
    capability: InternalStageCapabilityV1,
    fixture: dict[str, object],
) -> int:
    store = CampaignEvidenceStore(values.evidence_root)
    _consume(capability, store, "stage_a1")
    endpoints: dict[str, EndpointHandoffProposalV1] = {}
    fixture_endpoints = fixture["endpoints"]
    assert isinstance(fixture_endpoints, dict)
    for endpoint in ("cation", "neutral"):
        item = fixture_endpoints[endpoint]
        assert isinstance(item, dict)
        input_raw = str(item["input_xyz"]).encode("utf-8")
        output_raw = str(item["output_xyz"]).encode("utf-8")
        trajectory_raw = (
            json.dumps(
                {"endpoint": endpoint, "frame": 0, "synthetic_test_only": True},
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        input_identity = store.write_bytes(
            f"runtime/stage_a1/{endpoint}/input.xyz", input_raw, mode=IMMUTABLE_DATA_MODE
        )
        output_identity = store.write_bytes(
            f"runtime/stage_a1/{endpoint}/output.xyz", output_raw, mode=IMMUTABLE_DATA_MODE
        )
        trajectory_identity = store.write_bytes(
            f"runtime/stage_a1/{endpoint}/trajectory.jsonl",
            trajectory_raw,
            mode=IMMUTABLE_DATA_MODE,
        )
        charge = 1 if endpoint == "cation" else 0
        receipt_identity = store.write_json(
            f"runtime/stage_a1/{endpoint}/preoptimization_receipt.json",
            {
                "schema_version": "nhc-phase9b-a1-preoptimization-receipt-v1",
                "campaign_id": values.campaign_id,
                "attempt_id": values.attempt_id,
                "endpoint": endpoint,
                "charge": charge,
                "multiplicity": 1,
                "structural_gates_passed": True,
                "model_load_count": 1,
                "synthetic_test_only": True,
            },
        )
        elements = parse_xyz_elements(output_raw)
        endpoints[endpoint] = EndpointHandoffProposalV1(
            endpoint=endpoint,
            charge=charge,
            multiplicity=1,
            atom_count=len(elements),
            ordered_elements=elements,
            element_order_sha256=element_order_sha256(elements),
            a1_input_xyz_sha256=input_identity.sha256,
            a1_output_xyz_sha256=output_identity.sha256,
            a1_output_xyz_byte_count=output_identity.byte_count,
            trajectory_sha256=trajectory_identity.sha256,
            preoptimization_receipt_sha256=receipt_identity.sha256,
            structural_gates_passed=True,
            final_max_force_ev_per_angstrom=0.04,
            optimizer_step_count=1,
            calculator_invocation_count=2,
        )
    proposal = A1HandoffProposalReceiptV1(
        campaign_id=values.campaign_id,
        candidate=values.candidate,
        route="assisted",
        attempt_id=values.attempt_id,
        cation=endpoints["cation"],
        neutral=endpoints["neutral"],
        stage_a1_source_sha256=capability.stage_source_sha256,
        mlff_interpreter_profile_sha256=capability.stable_profile_sha256,
        weight_sha256=str(fixture["weight_sha256"]),
        optimizer_protocol_sha256=str(fixture["optimizer_protocol_sha256"]),
    )
    proposal_identity = store.write_bytes(
        "runtime/stage_a1/handoff_proposal.json", proposal.canonical_bytes()
    )
    terminal = StageA1TerminalReceiptV1(
        {
            "schema_version": StageA1TerminalReceiptV1.SCHEMA_VERSION,
            "campaign_id": values.campaign_id,
            "attempt_id": values.attempt_id,
            "terminal_state": "accepted",
            "evidence_sha256": proposal_identity.sha256,
            "failure": None,
        }
    )
    store.write_bytes("runtime/stage_a1/terminal.json", terminal.canonical_bytes())
    return 0


def _run_a2(values: argparse.Namespace, capability: InternalStageCapabilityV1) -> int:
    store = CampaignEvidenceStore(values.evidence_root)
    _consume(capability, store, "stage_a2")
    proposal_raw, _ = store.read("runtime/stage_a1/handoff_proposal.json")
    verification_raw, _ = store.read("runtime/handoff/verification.json")
    admission_raw, _ = store.read("runtime/handoff/a2_admission.json")
    proposal = A1HandoffProposalReceiptV1.from_bytes(proposal_raw)
    verification = SupervisorHandoffVerificationReceiptV1.from_bytes(verification_raw)
    admission = StageA2AdmissionReceiptV1.from_bytes(admission_raw)
    if capability.a2_admission_sha256 != admission.sha256():
        return 2
    if verification.proposal_receipt_sha256 != proposal.sha256():
        return 2
    for endpoint, expected_sha, expected_size in (
        ("cation", admission.cation_xyz_sha256, admission.cation_xyz_byte_count),
        ("neutral", admission.neutral_xyz_sha256, admission.neutral_xyz_byte_count),
    ):
        raw, identity = store.read(f"runtime/stage_a1/{endpoint}/output.xyz")
        if hashlib.sha256(raw).hexdigest() != expected_sha or len(raw) != expected_size:
            return 2
        if identity.sha256 != expected_sha:
            return 2
    store.write_json(
        "runtime/stage_a2/route_result.json",
        {
            "schema_version": "nhc-phase9b-stage-a2-route-result-v1",
            "status": "accepted",
            "source": "shared_pyscf_core",
            "dft_deprot_electronic_kcal": 123.456,
            "synthetic_test_only": True,
        },
    )
    terminal = StageA2TerminalReceiptV1(
        {
            "schema_version": StageA2TerminalReceiptV1.SCHEMA_VERSION,
            "campaign_id": values.campaign_id,
            "attempt_id": values.attempt_id,
            "terminal_state": "accepted",
            "evidence_sha256": admission.sha256(),
            "failure": None,
        }
    )
    store.write_bytes("runtime/stage_a2/terminal.json", terminal.canonical_bytes())
    return 0


def main() -> int:
    values = _parser().parse_args()
    profile = PHASE9B_A1_STAGE_PROFILE if values.stage_kind == "a1" else PHASE9B_A2_STAGE_PROFILE
    capability = run_registered_stage_bootstrap(
        profile=profile,
        campaign_id=values.campaign_id,
        attempt_id=values.attempt_id,
        registration_fd=values.registration_fd,
        release_fd=values.release_fd,
        supervisor_pid=values.supervisor_pid,
        supervisor_start_time=values.supervisor_start_time,
        supervisor_session_id=values.supervisor_session_id,
        supervisor_process_group_id=values.supervisor_process_group_id,
        stage_source_sha256=values.stage_source_sha256,
        argv=tuple(sys.orig_argv[1:]),
        registration_nonce_sha256=values.registration_nonce_sha256,
        clock_domain_digest=values.clock_domain_digest,
        linux_boot_id_sha256=values.linux_boot_id_sha256,
    )
    fixture = json.loads(values.fixture_path.read_text(encoding="utf-8"))
    if values.stage_kind == "a1":
        return _run_a1(values, capability, fixture)
    return _run_a2(values, capability)


if __name__ == "__main__":
    raise SystemExit(main())
