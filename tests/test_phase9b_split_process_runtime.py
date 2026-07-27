"""Portable Item 10 regressions.  Fake data only; no chemistry or permit."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from test_phase7_two_endpoint import FakeBackend, _write_request

from nhc_deprot_ranker.data.provenance import sha256_file
from nhc_deprot_ranker.preparation.phase9b_bundle import (
    build_route_payload_v3,
    build_route_request_v3,
    validate_route_parity_v3,
)
from nhc_deprot_ranker.preparation.phase9b_launch import (
    external_launch_entries_v3,
    validate_external_launch_entry_v3,
)
from nhc_deprot_ranker.quantum import phase9b_execution, two_endpoint
from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE
from nhc_deprot_ranker.quantum.phase9b_campaign_evidence import (
    IMMUTABLE_DATA_MODE,
    CampaignEvidenceError,
    CampaignEvidenceStore,
)
from nhc_deprot_ranker.quantum.phase9b_campaign_guardian import (
    CampaignGuardianLaunchPlan,
    CampaignGuardianNotAuthorizedError,
    _assert_permit_matches_plan,
    launch_assisted_campaign_guardian,
)
from nhc_deprot_ranker.quantum.phase9b_campaign_schemas import (
    AssistedCampaignIdentityV1,
    AssistedCampaignPermitV3,
    CampaignScheduleV1,
    CampaignSchemaError,
    StageA1TerminalReceiptV1,
    StageName,
    StageRegistrationReceiptV1,
    canonical_json_bytes,
    canonical_sha256,
    render_non_authorizing_permit,
    strict_json_object,
)
from nhc_deprot_ranker.quantum.phase9b_cross_process_handoff import (
    A1HandoffProposalReceiptV1,
    CrossProcessHandoffError,
    EndpointHandoffProposalV1,
    admit_stage_a2,
    element_order_sha256,
    parse_xyz_elements,
    verify_a1_handoff,
)
from nhc_deprot_ranker.quantum.phase9b_internal_stage_capability import (
    PHASE9B_A1_STAGE_PROFILE,
    PHASE9B_A2_STAGE_PROFILE,
    CapabilityIssueInputs,
    InternalStageCapabilityError,
    RegisteredProcessIdentity,
    RegistrationExpectation,
    consume_release_frame,
    create_campaign_supervisor_issuer,
    create_release_token,
    issue_internal_stage_capability,
    make_release_frame,
)
from nhc_deprot_ranker.quantum.phase9b_interpreter_profiles import (
    CONTROL_PLANE_STABLE_PROFILE_SHA256,
    GPUPYSCF_STABLE_PROFILE,
    MLFF_STABLE_PROFILE,
)
from nhc_deprot_ranker.quantum.phase9b_shared_pyscf_core import (
    SHARED_TWO_ENDPOINT_PYSCF_CORE,
    AdmittedA1InputProvenance,
    FrozenDirectInputProvenance,
    SharedPySCFCoreError,
)
from nhc_deprot_ranker.quantum.phase9b_source_identity import (
    SOURCE_LEAVES,
    SourceClosureError,
    assert_direct_a2_core_parity,
    compute_composite_source_identity,
    validate_source_closure_definitions,
)
from nhc_deprot_ranker.quantum.phase9b_stage_a1 import A1EndpointOutcome, run_stage_a1
from nhc_deprot_ranker.quantum.phase9b_stage_a2 import run_stage_a2

_SHA = "a" * 64


def _profile_assignments() -> dict[str, str]:
    return {
        "control_plane_standard_library": CONTROL_PLANE_STABLE_PROFILE_SHA256,
        "a1_mlff": MLFF_STABLE_PROFILE.sha256(),
        "direct_and_a2_gpupyscf": GPUPYSCF_STABLE_PROFILE.sha256(),
    }


def _source_root() -> Path:
    return Path(two_endpoint.__file__).resolve().parents[2]


def _source_identity():
    return compute_composite_source_identity(
        _source_root(), interpreter_profile_assignments=_profile_assignments()
    )


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def test_v8_direct_characterization_and_shared_core_are_byte_identical(tmp_path: Path) -> None:
    request_path = _write_request(tmp_path / "request")
    request = two_endpoint.load_two_endpoint_request(request_path)
    direct_output = tmp_path / "direct"
    core_output = tmp_path / "core"
    direct_backend = FakeBackend()
    core_backend = FakeBackend()

    assert (
        phase9b_execution.DIRECT_ADAPTER.execute(
            request,
            direct_output,
            capability=object(),
            attempt_id=phase9b_execution.DIRECT_ADAPTER.attempt_id,
            absolute_deadline_monotonic=time.monotonic() + 100.0,
            backend_factory=lambda _capability: direct_backend,
        )
        == 0
    )
    assert (
        SHARED_TWO_ENDPOINT_PYSCF_CORE.execute(
            request,
            core_output,
            capability=object(),
            attempt_id=phase9b_execution.DIRECT_ADAPTER.attempt_id,
            absolute_deadline_monotonic=time.monotonic() + 100.0,
            input_provenance=FrozenDirectInputProvenance(
                route="direct",
                cation_xyz_sha256=request.cation.xyz_sha256,
                neutral_xyz_sha256=request.neutral.xyz_sha256,
            ),
            backend_factory=lambda _capability: core_backend,
        )
        == 0
    )
    assert (
        direct_backend.calls
        == core_backend.calls
        == [
            ("optimize", "cation", "standard"),
            ("final_scf", "cation", "standard"),
            ("optimize", "neutral", "standard"),
            ("final_scf", "neutral", "standard"),
        ]
    )
    assert _tree_bytes(direct_output) == _tree_bytes(core_output)


def test_v3_direct_attempt_resolves_only_to_the_shared_core_adapter() -> None:
    adapter = phase9b_execution.resolve_execution_adapter("attempt-phase9b-lbnp-direct-v003")
    assert adapter is phase9b_execution.DIRECT_V3_ADAPTER
    assert adapter.route == "direct"
    assert adapter.uses_preoptimization is False
    assert adapter.imports_machine_learning_stack is False


def test_shared_core_rejects_parent_memory_or_parser_digest_drift() -> None:
    with pytest.raises(SharedPySCFCoreError, match="parser input"):
        AdmittedA1InputProvenance(
            route="assisted",
            proposal_sha256="1" * 64,
            verification_sha256="2" * 64,
            admission_sha256="3" * 64,
            cation_xyz_sha256="4" * 64,
            neutral_xyz_sha256="5" * 64,
            cation_parser_input_sha256="6" * 64,
            neutral_parser_input_sha256="5" * 64,
        )
        from nhc_deprot_ranker.quantum.phase9b_shared_pyscf_core import validate_input_provenance

        validate_input_provenance(
            AdmittedA1InputProvenance(
                route="assisted",
                proposal_sha256="1" * 64,
                verification_sha256="2" * 64,
                admission_sha256="3" * 64,
                cation_xyz_sha256="4" * 64,
                neutral_xyz_sha256="5" * 64,
                cation_parser_input_sha256="6" * 64,
                neutral_parser_input_sha256="5" * 64,
            )
        )


def test_source_closure_is_disjoint_acyclic_and_direct_a2_share_core() -> None:
    validate_source_closure_definitions()
    identity = _source_identity()
    assert_direct_a2_core_parity(identity)
    owned = [name for leaf in SOURCE_LEAVES for name in leaf.files]
    assert len(owned) == len(set(owned))
    assert len(identity.full_assisted_campaign_source_sha256) == 64


def test_source_closure_rejects_duplicate_cycle_and_missing_dependency() -> None:
    base = list(SOURCE_LEAVES)
    duplicate = replace(base[1], files=tuple(sorted((*base[1].files, base[0].files[0]))))
    with pytest.raises(SourceClosureError, match="duplicate"):
        validate_source_closure_definitions(tuple([base[0], duplicate, *base[2:]]))
    cycle = replace(base[0], dependencies=(base[-1].name,))
    with pytest.raises(SourceClosureError, match="cycle"):
        validate_source_closure_definitions(tuple([cycle, *base[1:]]))
    missing = replace(base[-1], dependencies=("absent_leaf",))
    with pytest.raises(SourceClosureError, match="unknown"):
        validate_source_closure_definitions(tuple([*base[:-1], missing]))


def test_v3_paired_generation_is_non_authorizing_and_mixed_generation_closed() -> None:
    identity = _source_identity()
    requests = {
        route: build_route_request_v3(
            route=route,
            source_identity=identity,
            protocol=two_endpoint.LOCKED_PROTOCOL,
            cation_xyz_sha256=PHASE9B_CANDIDATE.cation_xyz_sha256,
            neutral_xyz_sha256=PHASE9B_CANDIDATE.neutral_xyz_sha256,
        )
        for route in ("direct", "assisted")
    }
    payloads = {
        route: build_route_payload_v3(request, source_identity=identity)
        for route, request in requests.items()
    }
    validate_route_parity_v3(payloads["direct"], payloads["assisted"])
    for route, item in payloads.items():
        request = json.loads(item.request.request_bytes)
        manifest = json.loads(item.manifest_bytes)
        assert request["schema_version"] == "nhc-two-endpoint-request-v3"
        assert request["execution_authorized"] is False
        assert manifest["execution_authorized"] is False
        assert manifest["real_permit_generated"] is False
        assert request["source_closures"]["full_assisted_campaign_source"] == (
            identity.full_assisted_campaign_source_sha256
        )
        assert route == request["preoptimization"]["stage"].replace("aimnet2", "assisted").replace(
            "none", "direct"
        )


def test_strict_records_reject_unknown_duplicate_nonfinite_and_noncanonical() -> None:
    raw = b'{"a":1,"a":2}'
    with pytest.raises(CampaignSchemaError, match="duplicate"):
        strict_json_object(raw, label="fixture")
    with pytest.raises(CampaignSchemaError, match="non-finite"):
        strict_json_object(b'{"a":NaN}', label="fixture")
    terminal_payload = {
        "schema_version": StageA1TerminalReceiptV1.SCHEMA_VERSION,
        "campaign_id": "campaign-v1",
        "attempt_id": "attempt-v1",
        "terminal_state": "accepted",
        "evidence_sha256": "1" * 64,
        "failure": None,
        "unknown": True,
    }
    with pytest.raises(CampaignSchemaError, match="extra"):
        StageA1TerminalReceiptV1(terminal_payload)


def test_permit_binds_durations_not_absolute_timestamp_and_renderer_stays_false() -> None:
    payload = json.loads(
        Path("docs/schemas/phase9b_assisted_campaign_permit_v3.example.json").read_text(
            encoding="utf-8"
        )
    )
    permit = AssistedCampaignPermitV3(payload)
    raw = render_non_authorizing_permit(permit)
    assert AssistedCampaignPermitV3.from_bytes(raw) == permit
    assert "campaign_absolute_deadline_ns" not in payload["campaign"]
    payload["campaign"]["campaign_absolute_deadline_ns"] = 7_200_000_000_000
    with pytest.raises(CampaignSchemaError, match="absolute deadline"):
        AssistedCampaignPermitV3(payload)


def _guardian_plan_from_example(
    tmp_path: Path,
) -> tuple[AssistedCampaignPermitV3, CampaignGuardianLaunchPlan]:
    payload = json.loads(
        Path("docs/schemas/phase9b_assisted_campaign_permit_v3.example.json").read_text(
            encoding="utf-8"
        )
    )
    permit = AssistedCampaignPermitV3(payload)
    campaign = payload["campaign"]
    profiles = payload["interpreter_profiles"]
    identity = AssistedCampaignIdentityV1(
        {
            "schema_version": AssistedCampaignIdentityV1.SCHEMA_VERSION,
            "campaign_id": campaign["campaign_id"],
            "attempt_id": campaign["attempt_id"],
            "candidate": campaign["candidate"],
            "route": "assisted",
            "request_sha256": payload["request_sha256"],
            "manifest_sha256": payload["manifest_sha256"],
            "resources_sha256": canonical_sha256(payload["resources"]),
            "full_source_sha256": payload["source"]["full_assisted_campaign_source_sha256"],
            "mlff_profile_sha256": profiles["a1"]["stable_identity_sha256"],
            "gpupyscf_profile_sha256": profiles["direct_and_a2"]["stable_identity_sha256"],
        }
    )
    plan = CampaignGuardianLaunchPlan(
        campaign_id=campaign["campaign_id"],
        attempt_id=campaign["attempt_id"],
        candidate=campaign["candidate"],
        ready_permit_path=(tmp_path / "private/permit.ready.json").resolve(),
        supervisor_argv_template=("/verified/python", "-m", "supervisor"),
        cwd=tmp_path.resolve(),
        environment={},
        campaign_capability_payload={"synthetic": True},
        campaign_identity=identity,
    )
    return permit, plan


def test_guardian_binds_permit_to_plan_and_closed_gate_has_zero_side_effect(
    tmp_path: Path,
) -> None:
    permit, plan = _guardian_plan_from_example(tmp_path)
    _assert_permit_matches_plan(permit, plan)
    drifted = permit.to_payload()
    drifted["request_sha256"] = "f" * 64
    with pytest.raises(Exception, match="frozen guardian plan"):
        _assert_permit_matches_plan(AssistedCampaignPermitV3(drifted), plan)
    root = (tmp_path / "evidence").resolve()
    with pytest.raises(CampaignGuardianNotAuthorizedError, match="closed"):
        launch_assisted_campaign_guardian(plan, store=CampaignEvidenceStore(root))
    assert not root.exists()
    assert not plan.ready_permit_path.exists()


def test_runtime_schedule_binds_boot_clock_and_exact_7200_seconds() -> None:
    start = 5_000_000_000_000
    schedule = CampaignScheduleV1(
        {
            "schema_version": CampaignScheduleV1.SCHEMA_VERSION,
            "campaign_monotonic_start_ns": start,
            "campaign_absolute_deadline_ns": start + 7_200_000_000_000,
            "a1_deadline_ns": start + 900_000_000_000,
            "clock_type": "CLOCK_MONOTONIC",
            "linux_boot_id_sha256": "1" * 64,
            "host_execution_identity_sha256": "2" * 64,
            "supervisor_process_start_identity_sha256": "3" * 64,
            "monotonic_resolution_ns": 1,
            "clock_domain_digest": "4" * 64,
            "derived_deadline_calculation_digest": "5" * 64,
        }
    )
    assert schedule.to_payload()["campaign_absolute_deadline_ns"] - start == 7_200_000_000_000
    drifted = schedule.to_payload()
    drifted["campaign_absolute_deadline_ns"] = start + 7_200_000_000_001
    with pytest.raises(CampaignSchemaError, match="7200"):
        CampaignScheduleV1(drifted)


def _process(stage_pid: int = 20) -> RegisteredProcessIdentity:
    return RegisteredProcessIdentity(
        supervisor_pid=10,
        supervisor_start_time=100,
        supervisor_session_id=10,
        supervisor_process_group_id=10,
        stage_pid=stage_pid,
        stage_start_time=200,
        stage_session_id=stage_pid,
        stage_process_group_id=stage_pid,
        expected_parent_pid=10,
    )


def _registration(
    stage: StageName, process: RegisteredProcessIdentity
) -> StageRegistrationReceiptV1:
    return StageRegistrationReceiptV1(
        {
            "schema_version": StageRegistrationReceiptV1.SCHEMA_VERSION,
            "campaign_id": "campaign-v1",
            "attempt_id": "attempt-v1",
            "stage": stage.value,
            "process_identity": process.to_payload(),
            "interpreter_executable_sha256": "1" * 64,
            "argv_sha256": "2" * 64,
            "source_sha256": "3" * 64,
            "registration_nonce_sha256": "4" * 64,
        }
    )


def _issue(stage: StageName, *, admission: str | None = None):
    profile = PHASE9B_A1_STAGE_PROFILE if stage is StageName.A1 else PHASE9B_A2_STAGE_PROFILE
    process = _process(20 if stage is StageName.A1 else 30)
    registration = _registration(stage, process)
    expectation = RegistrationExpectation(
        campaign_id="campaign-v1",
        attempt_id="attempt-v1",
        stage_profile=profile,
        process_identity=process,
        interpreter_executable_sha256="1" * 64,
        argv_sha256="2" * 64,
        stage_source_sha256="3" * 64,
    )
    token = create_release_token()
    issuer = create_campaign_supervisor_issuer(hashlib.sha256(token.encode()).hexdigest())
    capability = issue_internal_stage_capability(
        issuer,
        registration=registration,
        expectation=expectation,
        inputs=CapabilityIssueInputs(
            candidate="candidate-v1",
            stable_profile_id="profile-v1",
            stable_profile_sha256="5" * 64,
            private_binding_sha256="6" * 64,
            shared_schema_source_sha256="7" * 64,
            input_identity_sha256="8" * 64,
            output_root_identity_sha256="9" * 64,
            resources_identity_sha256="a" * 64,
            schema_identities_sha256="b" * 64,
            campaign_monotonic_start_ns=1_000_000_000_000,
            campaign_absolute_deadline_ns=8_200_000_000_000,
            stage_deadline_ns=(1_900_000_000_000 if stage is StageName.A1 else 8_200_000_000_000),
            clock_domain_digest="c" * 64,
            linux_boot_id_sha256="d" * 64,
            host_execution_identity_sha256="e" * 64,
            a2_admission_sha256=admission,
        ),
        release_token=token,
    )
    return capability, expectation, token


def test_capability_is_post_registration_one_shot_stage_and_boot_bound() -> None:
    capability, expectation, token = _issue(StageName.A1)
    frame = make_release_frame(capability, token)
    consumed = consume_release_frame(
        frame,
        expected=expectation,
        expected_clock_domain_digest="c" * 64,
        expected_linux_boot_id_sha256="d" * 64,
        now_ns=1_100_000_000_000,
    )
    assert consumed == capability
    with pytest.raises(InternalStageCapabilityError, match="replayed"):
        consume_release_frame(
            frame,
            expected=expectation,
            expected_clock_domain_digest="c" * 64,
            expected_linux_boot_id_sha256="d" * 64,
            now_ns=1_100_000_000_000,
        )
    with pytest.raises(InternalStageCapabilityError, match="boot"):
        consume_release_frame(
            make_release_frame(*_issue(StageName.A1)[::2]),  # type: ignore[arg-type]
            expected=expectation,
            expected_clock_domain_digest="c" * 64,
            expected_linux_boot_id_sha256="f" * 64,
            now_ns=1_100_000_000_000,
        )


def _xyz(elements: tuple[str, ...], comment: str) -> bytes:
    lines = [str(len(elements)), comment]
    lines.extend(f"{element} {index}.0 0.0 0.0" for index, element in enumerate(elements))
    return ("\n".join(lines) + "\n").encode()


def _endpoint_elements() -> tuple[tuple[str, ...], tuple[str, ...]]:
    heavy = tuple(["C"] * 8 + ["N"] + ["F"] * 5 + ["C", "N", "N"] + ["F"] * 4)
    return heavy + ("H",) * 5, heavy + ("H",) * 4


def _handoff_store(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = (tmp_path / "run").resolve()
    store = CampaignEvidenceStore(root)
    endpoint_records: dict[str, EndpointHandoffProposalV1] = {}
    for endpoint, elements in zip(("cation", "neutral"), _endpoint_elements(), strict=True):
        input_raw = _xyz(elements, f"{endpoint} input")
        output_raw = _xyz(elements, f"{endpoint} output")
        trajectory_raw = b'{"synthetic":true}\n'
        input_id = store.write_bytes(
            f"runtime/stage_a1/{endpoint}/input.xyz", input_raw, mode=IMMUTABLE_DATA_MODE
        )
        output_id = store.write_bytes(
            f"runtime/stage_a1/{endpoint}/output.xyz", output_raw, mode=IMMUTABLE_DATA_MODE
        )
        trajectory_id = store.write_bytes(
            f"runtime/stage_a1/{endpoint}/trajectory.jsonl",
            trajectory_raw,
            mode=IMMUTABLE_DATA_MODE,
        )
        charge = 1 if endpoint == "cation" else 0
        receipt_id = store.write_json(
            f"runtime/stage_a1/{endpoint}/preoptimization_receipt.json",
            {
                "endpoint": endpoint,
                "charge": charge,
                "multiplicity": 1,
                "structural_gates_passed": True,
            },
        )
        endpoint_records[endpoint] = EndpointHandoffProposalV1(
            endpoint=endpoint,  # type: ignore[arg-type]
            charge=charge,
            multiplicity=1,
            atom_count=len(elements),
            ordered_elements=elements,
            element_order_sha256=element_order_sha256(elements),
            a1_input_xyz_sha256=input_id.sha256,
            a1_output_xyz_sha256=output_id.sha256,
            a1_output_xyz_byte_count=output_id.byte_count,
            trajectory_sha256=trajectory_id.sha256,
            preoptimization_receipt_sha256=receipt_id.sha256,
            structural_gates_passed=True,
            final_max_force_ev_per_angstrom=0.04,
            optimizer_step_count=1,
            calculator_invocation_count=2,
        )
    proposal = A1HandoffProposalReceiptV1(
        campaign_id="campaign-v1",
        candidate="candidate-v1",
        route="assisted",
        attempt_id="attempt-v1",
        cation=endpoint_records["cation"],
        neutral=endpoint_records["neutral"],
        stage_a1_source_sha256="1" * 64,
        mlff_interpreter_profile_sha256="2" * 64,
        weight_sha256="3" * 64,
        optimizer_protocol_sha256="4" * 64,
    )
    store.write_bytes("runtime/stage_a1/handoff_proposal.json", proposal.canonical_bytes())
    verification = verify_a1_handoff(
        store,
        proposal=proposal,
        proposal_path="runtime/stage_a1/handoff_proposal.json",
        a1_process_tree_absence_sha256="5" * 64,
        supervisor_verifier_source_sha256="6" * 64,
        expected_campaign_id="campaign-v1",
        expected_candidate="candidate-v1",
        expected_attempt_id="attempt-v1",
    )
    admission = admit_stage_a2(
        proposal,
        verification,
        stage_a2_source_sha256="7" * 64,
        gpu_pyscf_interpreter_profile_sha256="8" * 64,
        shared_pyscf_core_source_sha256="9" * 64,
        shared_schema_source_sha256="a" * 64,
        campaign_absolute_deadline_ns=9_000_000_000_000,
        clock_domain_digest="b" * 64,
        now_ns=2_000_000_000_000,
    )
    return store, proposal, verification, admission


def test_handoff_three_receipts_are_immutable_and_exact_byte_closed(tmp_path: Path) -> None:
    store, proposal, verification, admission = _handoff_store(tmp_path)
    assert A1HandoffProposalReceiptV1.from_bytes(proposal.canonical_bytes()) == proposal
    assert verification.verification_outcome == "accepted"
    assert admission.proposal_receipt_sha256 == proposal.sha256()
    assert admission.verification_receipt_sha256 == verification.sha256()
    with pytest.raises(CampaignEvidenceError, match="overwrite"):
        store.write_bytes("runtime/stage_a1/handoff_proposal.json", proposal.canonical_bytes())


def test_handoff_rejects_modified_reformatted_reordered_and_identity_drift(tmp_path: Path) -> None:
    store, proposal, _verification, _admission = _handoff_store(tmp_path)
    drifted = replace(
        proposal,
        cation=replace(proposal.cation, a1_output_xyz_sha256="f" * 64),
    )
    with pytest.raises(CrossProcessHandoffError, match="durable proposal"):
        verify_a1_handoff(
            store,
            proposal=drifted,
            proposal_path="runtime/stage_a1/handoff_proposal.json",
            a1_process_tree_absence_sha256="5" * 64,
            supervisor_verifier_source_sha256="6" * 64,
            expected_campaign_id="campaign-v1",
            expected_candidate="candidate-v1",
            expected_attempt_id="attempt-v1",
        )
    with pytest.raises(CrossProcessHandoffError):
        parse_xyz_elements(b"1\nx\nC 0 0 0\nH 0 0 1\n")


def test_a2_rereads_disk_and_passes_same_bytes_to_shared_parser(tmp_path: Path) -> None:
    request_path = _write_phase9b_request(tmp_path / "request")
    request = two_endpoint.load_two_endpoint_request(request_path)
    store, proposal, verification, admission = _handoff_store(tmp_path / "handoff")
    store.write_bytes("runtime/handoff/verification.json", verification.canonical_bytes())
    store.write_bytes("runtime/handoff/a2_admission.json", admission.canonical_bytes())
    capability, _, _ = _issue(StageName.A2, admission=admission.sha256())

    class FakeCore:
        def __init__(self) -> None:
            self.provenance: AdmittedA1InputProvenance | None = None

        def execute(self, *_args: object, **kwargs: object) -> int:
            self.provenance = cast(AdmittedA1InputProvenance, kwargs["input_provenance"])
            return 0

    core = FakeCore()
    evidence, terminal = run_stage_a2(
        capability=capability,
        request=request,
        store=store,
        proposal=proposal,
        verification=verification,
        admission=admission,
        output_root=tmp_path / "fake-core-output",
        backend_factory=lambda _capability: object(),
        shared_core=core,  # type: ignore[arg-type]
    )
    assert terminal.to_payload()["terminal_state"] == "accepted"
    assert all(item.disk_bytes_sha256 == item.parser_input_sha256 for item in evidence)
    assert core.provenance is not None
    assert core.provenance.cation_xyz_sha256 == evidence[0].disk_bytes_sha256


def _write_phase9b_request(root: Path) -> Path:
    root.mkdir(parents=True)
    cation_elements, neutral_elements = _endpoint_elements()
    (root / "cation.xyz").write_bytes(_xyz(cation_elements, "cation initial"))
    (root / "neutral.xyz").write_bytes(_xyz(neutral_elements, "neutral initial"))
    payload = {
        "schema_version": two_endpoint.REQUEST_SCHEMA_VERSION,
        "request_id": "phase9b-test-request",
        "inchikey": PHASE9B_CANDIDATE.inchikey,
        "execution_authorized": False,
        "timeout_seconds": 7200,
        "runner_source_sha256": two_endpoint.current_runner_source_sha256(),
        "protocol": two_endpoint.LOCKED_PROTOCOL,
        "endpoints": {
            "cation": {
                "xyz_path": "cation.xyz",
                "xyz_sha256": sha256_file(root / "cation.xyz"),
                "charge": 1,
                "multiplicity": 1,
            },
            "neutral": {
                "xyz_path": "neutral.xyz",
                "xyz_sha256": sha256_file(root / "neutral.xyz"),
                "charge": 0,
                "multiplicity": 1,
            },
        },
    }
    path = root / "request.json"
    path.write_bytes(canonical_json_bytes(payload))
    return path


def test_a1_fake_runtime_loads_once_runs_both_and_cation_failure_skips_neutral(
    tmp_path: Path,
) -> None:
    request = two_endpoint.load_two_endpoint_request(_write_phase9b_request(tmp_path / "request"))
    capability, _, _ = _issue(StageName.A1)

    class FakeA1Runtime:
        def __init__(self, *, fail_cation: bool = False) -> None:
            self.loads = 0
            self.calls: list[str] = []
            self.fail_cation = fail_cation

        @property
        def model_load_count(self) -> int:
            return self.loads

        def load_base_model_once(self) -> None:
            self.loads += 1

        def run_endpoint(self, endpoint: object, *, deadline_monotonic: float) -> A1EndpointOutcome:
            del deadline_monotonic
            name = endpoint.name
            self.calls.append(name)
            if name == "cation" and self.fail_cation:
                raise RuntimeError("synthetic cation rejection")
            raw = endpoint.xyz_path.read_bytes()
            return A1EndpointOutcome(
                endpoint=name,
                input_xyz_bytes=raw,
                output_xyz_bytes=raw,
                trajectory_bytes=b'{"synthetic_test_only":true}\n',
                structural_gates_passed=True,
                final_max_force_ev_per_angstrom=0.01,
                optimizer_step_count=1,
                calculator_invocation_count=2,
            )

    accepted_runtime = FakeA1Runtime()
    proposal, terminal = run_stage_a1(
        capability=capability,
        request=request,
        store=CampaignEvidenceStore((tmp_path / "accepted").resolve()),
        runtime=accepted_runtime,
        campaign_id="campaign-v1",
        candidate="candidate-v1",
        stage_a1_source_sha256="1" * 64,
        mlff_interpreter_profile_sha256="2" * 64,
        weight_sha256="3" * 64,
        optimizer_protocol_sha256="4" * 64,
    )
    assert proposal is not None
    assert terminal.to_payload()["terminal_state"] == "accepted"
    assert accepted_runtime.loads == 1
    assert accepted_runtime.calls == ["cation", "neutral"]

    failed_runtime = FakeA1Runtime(fail_cation=True)
    proposal, terminal = run_stage_a1(
        capability=capability,
        request=request,
        store=CampaignEvidenceStore((tmp_path / "rejected").resolve()),
        runtime=failed_runtime,
        campaign_id="campaign-v1",
        candidate="candidate-v1",
        stage_a1_source_sha256="1" * 64,
        mlff_interpreter_profile_sha256="2" * 64,
        weight_sha256="3" * 64,
        optimizer_protocol_sha256="4" * 64,
    )
    assert proposal is None
    assert terminal.to_payload()["terminal_state"] == "rejected_cation"
    assert failed_runtime.loads == 1
    assert failed_runtime.calls == ["cation"]


def test_evidence_store_refuses_overwrite_symlink_extra_and_unregistered_path(
    tmp_path: Path,
) -> None:
    store = CampaignEvidenceStore((tmp_path / "run").resolve())
    store.write_json("runtime/campaign/campaign_identity.json", {"ok": True})
    with pytest.raises(CampaignEvidenceError, match="overwrite"):
        store.write_json("runtime/campaign/campaign_identity.json", {"ok": False})
    with pytest.raises(CampaignEvidenceError, match="outside"):
        store.write_json("runtime/extra.json", {"ok": False})
    extra = store.root / "runtime" / "campaign" / "extra"
    extra.write_text("extra", encoding="utf-8")
    with pytest.raises(CampaignEvidenceError, match="extra"):
        store.assert_no_extra_files()


def test_external_launch_surface_has_guardians_only() -> None:
    assert external_launch_entries_v3() == (
        "nhc_deprot_ranker.quantum.phase9b_guardian",
        "nhc_deprot_ranker.quantum.phase9b_campaign_guardian",
    )
    for forbidden in (
        "nhc_deprot_ranker.quantum.phase9b_stage_a1",
        "nhc_deprot_ranker.quantum.phase9b_stage_a2",
    ):
        with pytest.raises(Exception, match="guardian"):
            validate_external_launch_entry_v3(forbidden)


def test_public_profiles_contain_no_private_paths_and_direct_a2_digest_is_one() -> None:
    for profile in (MLFF_STABLE_PROFILE, GPUPYSCF_STABLE_PROFILE):
        raw = profile.canonical_bytes().decode("ascii")
        assert "/Users/" not in raw
        assert "/home/" not in raw
        assert "prefix" not in raw
    identity = _source_identity()
    leaves = {leaf.name: leaf for leaf in identity.leaves}
    assert (
        leaves["shared_pyscf_core_source"].interpreter_profile_sha256
        == leaves["stage_a2_source"].interpreter_profile_sha256
        == GPUPYSCF_STABLE_PROFILE.sha256()
    )


def test_no_runtime_source_uses_pypath_or_exposes_stage_launch_commands() -> None:
    source_files = [
        path
        for path in (_source_root() / "nhc_deprot_ranker/quantum").glob("phase9b_*.py")
        if path.name
        in {
            "phase9b_campaign_guardian.py",
            "phase9b_campaign_supervisor.py",
            "phase9b_stage_a1.py",
            "phase9b_stage_a2.py",
            "phase9b_internal_stage_capability.py",
        }
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_files)
    forbidden = "PYTHON" + "PATH"
    assert forbidden not in source
    assert "launch-a1" not in source
    assert "launch-a2" not in source


def test_all_public_execution_gates_stay_false_and_labels_remain_71() -> None:
    assignments = []
    for path in Path("src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assignments.extend(
            (path, line)
            for line in text.splitlines()
            if "EXECUTION_AUTHORIZED: Final[bool]" in line
        )
    assert len(assignments) == 11
    assert all("= False" in line for _path, line in assignments)
    labels = Path("data/labels.csv")
    if labels.exists():
        assert len(labels.read_text(encoding="utf-8").splitlines()) - 1 == 71
