"""Standard-library campaign supervisor for sequential A1 -> handoff -> A2."""

from __future__ import annotations

import hashlib
import os
import select
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, cast

from nhc_deprot_ranker.quantum.linux_guardian import ProcessIdentity, read_process_identity
from nhc_deprot_ranker.quantum.phase9b_campaign_evidence import CampaignEvidenceStore
from nhc_deprot_ranker.quantum.phase9b_campaign_schemas import (
    AssistedCampaignIdentityV1,
    AssistedCampaignTerminalReceiptV1,
    CampaignRuntimeState,
    CampaignScheduleV1,
    GuardianLaunchState,
    StageA1TerminalReceiptV1,
    StageA2TerminalReceiptV1,
    StageAcknowledgementReceiptV1,
    StageCapabilityConsumptionReceiptV1,
    StageName,
    StageRegistrationReceiptV1,
    canonical_json_bytes,
    strict_json_object,
)
from nhc_deprot_ranker.quantum.phase9b_cross_process_handoff import (
    A1HandoffProposalReceiptV1,
    admit_stage_a2,
    verify_a1_handoff,
)
from nhc_deprot_ranker.quantum.phase9b_internal_stage_capability import (
    CampaignSupervisorCapabilityIssuer,
    CapabilityIssueInputs,
    InternalStageCapabilityV1,
    RegisteredProcessIdentity,
    RegistrationExpectation,
    StageAuthorityProfile,
    create_campaign_supervisor_issuer,
    create_release_token,
    issue_internal_stage_capability,
    make_release_frame,
    read_pipe_frame,
    write_pipe_frame,
)
from nhc_deprot_ranker.quantum.process_supervisor import (
    SupervisionPolicy,
    SupervisionResult,
    run_supervised,
)

CAMPAIGN_SUPERVISOR_SCHEMA_VERSION: Final = "nhc-phase9b-campaign-supervisor-v1"
CAMPAIGN_WALL_NS: Final = 7_200_000_000_000
A1_LOCAL_NS: Final = 900_000_000_000
TERMINATION_GRACE_SECONDS: Final = 10.0
REGISTRATION_TIMEOUT_SECONDS: Final = 10.0


class CampaignSupervisorError(RuntimeError):
    """Campaign authority, scheduling, stage, handoff, or evidence failed."""


@dataclass(frozen=True, slots=True)
class CampaignClockDomain:
    clock_type: str
    linux_boot_id_sha256: str
    host_execution_identity_sha256: str
    supervisor_process_start_identity_sha256: str
    monotonic_resolution_ns: int
    clock_domain_digest: str


def derive_campaign_schedule(
    *,
    supervisor_identity: ProcessIdentity,
    clock_ns: Callable[[], int] = time.monotonic_ns,
    clock_info: object | None = None,
) -> tuple[CampaignClockDomain, CampaignScheduleV1]:
    """Choose the one runtime absolute deadline after capability validation."""

    start = clock_ns()
    if isinstance(start, bool) or not isinstance(start, int) or start <= 0:
        raise CampaignSupervisorError("CLOCK_MONOTONIC returned an invalid start")
    info = time.get_clock_info("monotonic") if clock_info is None else clock_info
    resolution = max(1, int(float(info.resolution) * 1_000_000_000))  # type: ignore[attr-defined]
    boot_digest = hashlib.sha256(supervisor_identity.boot_id.encode("ascii")).hexdigest()
    host_payload = {
        "boot_id_sha256": boot_digest,
        "supervisor_pid": supervisor_identity.pid,
        "supervisor_starttime_ticks": supervisor_identity.starttime_ticks,
        "supervisor_sid": supervisor_identity.sid,
        "supervisor_pgid": supervisor_identity.pgid,
    }
    host_digest = hashlib.sha256(canonical_json_bytes(host_payload)).hexdigest()
    process_start_digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "pid": supervisor_identity.pid,
                "starttime_ticks": supervisor_identity.starttime_ticks,
            }
        )
    ).hexdigest()
    domain_payload = {
        "clock_type": "CLOCK_MONOTONIC",
        "linux_boot_id_sha256": boot_digest,
        "host_execution_identity_sha256": host_digest,
        "supervisor_process_start_identity_sha256": process_start_digest,
        "monotonic_resolution_ns": resolution,
    }
    domain_digest = hashlib.sha256(canonical_json_bytes(domain_payload)).hexdigest()
    absolute = start + CAMPAIGN_WALL_NS
    a1_deadline = min(absolute, start + A1_LOCAL_NS)
    calculation_digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "start_ns": start,
                "wall_limit_ns": CAMPAIGN_WALL_NS,
                "a1_local_limit_ns": A1_LOCAL_NS,
                "absolute_deadline_ns": absolute,
                "a1_deadline_ns": a1_deadline,
            }
        )
    ).hexdigest()
    schedule = CampaignScheduleV1(
        {
            "schema_version": CampaignScheduleV1.SCHEMA_VERSION,
            "campaign_monotonic_start_ns": start,
            "campaign_absolute_deadline_ns": absolute,
            "a1_deadline_ns": a1_deadline,
            "clock_type": "CLOCK_MONOTONIC",
            "linux_boot_id_sha256": boot_digest,
            "host_execution_identity_sha256": host_digest,
            "supervisor_process_start_identity_sha256": process_start_digest,
            "monotonic_resolution_ns": resolution,
            "clock_domain_digest": domain_digest,
            "derived_deadline_calculation_digest": calculation_digest,
        }
    )
    return (
        CampaignClockDomain(
            clock_type="CLOCK_MONOTONIC",
            linux_boot_id_sha256=boot_digest,
            host_execution_identity_sha256=host_digest,
            supervisor_process_start_identity_sha256=process_start_digest,
            monotonic_resolution_ns=resolution,
            clock_domain_digest=domain_digest,
        ),
        schedule,
    )


@dataclass(frozen=True, slots=True)
class StageSubprocessSpec:
    profile: StageAuthorityProfile
    argv_template: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]
    stage_source_sha256: str
    executable_sha256: str
    registration_nonce_sha256: str

    def __post_init__(self) -> None:
        if (
            not self.argv_template
            or "{registration_fd}" not in self.argv_template
            or "{release_fd}" not in self.argv_template
        ):
            raise CampaignSupervisorError("stage argv must carry both inherited pipe descriptors")
        if not self.cwd.is_absolute():
            raise CampaignSupervisorError("stage cwd must be absolute")
        for value in (
            self.stage_source_sha256,
            self.executable_sha256,
            self.registration_nonce_sha256,
        ):
            if len(value) != 64:
                raise CampaignSupervisorError("stage subprocess digest is invalid")


@dataclass(frozen=True, slots=True)
class StageLaunchRequest:
    campaign_id: str
    attempt_id: str
    candidate: str
    spec: StageSubprocessSpec
    issuer: CampaignSupervisorCapabilityIssuer
    issue_inputs: CapabilityIssueInputs
    store: CampaignEvidenceStore


@dataclass(frozen=True, slots=True)
class StageLaunchResult:
    stage: StageName
    supervision: SupervisionResult
    capability: InternalStageCapabilityV1 | None
    registration: StageRegistrationReceiptV1 | None
    acknowledgement: StageAcknowledgementReceiptV1 | None
    label: Mapping[str, object] | None = None

    @property
    def accepted(self) -> bool:
        return (
            self.supervision.succeeded
            and self.supervision.safe_to_finalize
            and self.capability is not None
            and self.registration is not None
            and self.acknowledgement is not None
        )


class StageLauncher(Protocol):
    def __call__(self, request: StageLaunchRequest) -> StageLaunchResult: ...


def _format_stage_argv(
    template: tuple[str, ...],
    registration_fd: int,
    release_fd: int,
    request: StageLaunchRequest,
) -> tuple[str, ...]:
    process = read_process_identity(os.getpid())
    replacements = {
        "{registration_fd}": str(registration_fd),
        "{release_fd}": str(release_fd),
        "{campaign_id}": request.campaign_id,
        "{attempt_id}": request.attempt_id,
        "{candidate}": request.candidate,
        "{supervisor_pid}": str(process.pid),
        "{supervisor_start_time}": str(process.starttime_ticks),
        "{supervisor_session_id}": str(process.sid),
        "{supervisor_process_group_id}": str(process.pgid),
        "{stage_source_sha256}": request.spec.stage_source_sha256,
        "{registration_nonce_sha256}": request.spec.registration_nonce_sha256,
        "{clock_domain_digest}": request.issue_inputs.clock_domain_digest,
        "{linux_boot_id_sha256}": request.issue_inputs.linux_boot_id_sha256,
    }

    def render(part: str) -> str:
        result = part
        for token, value in replacements.items():
            result = result.replace(token, value)
        if "{" in result or "}" in result:
            raise CampaignSupervisorError("stage argv contains an unresolved template token")
        return result

    return tuple(render(part) for part in template)


def launch_registered_stage_subprocess(request: StageLaunchRequest) -> StageLaunchResult:
    """Spawn one fresh-session stage, then registration -> capability -> release."""

    registration_read, registration_write = os.pipe()
    release_read, release_write = os.pipe()
    os.set_inheritable(registration_write, True)
    os.set_inheritable(release_read, True)
    argv = _format_stage_argv(
        request.spec.argv_template,
        registration_write,
        release_read,
        request,
    )
    registered_argv_sha256 = hashlib.sha256(canonical_json_bytes(list(argv[1:]))).hexdigest()
    capability: InternalStageCapabilityV1 | None = None
    registration: StageRegistrationReceiptV1 | None = None
    acknowledgement: StageAcknowledgementReceiptV1 | None = None
    callback_error: BaseException | None = None
    release_token = create_release_token()
    stage_prefix = "stage_a1" if request.spec.profile.stage is StageName.A1 else "stage_a2"

    def on_started(pid: int, pgid: int) -> None:
        nonlocal capability, registration, acknowledgement, callback_error
        try:
            ready, _, _ = select.select([registration_read], [], [], REGISTRATION_TIMEOUT_SECONDS)
            if not ready:
                raise CampaignSupervisorError("stage registration timed out")
            raw = read_pipe_frame(registration_read)
            registration = StageRegistrationReceiptV1.from_bytes(raw)
            payload = registration.to_payload()
            process = RegisteredProcessIdentity.from_payload(payload["process_identity"])
            if process.stage_pid != pid or process.stage_process_group_id != pgid:
                raise CampaignSupervisorError(
                    "registered child PID/PGID differs from spawned child"
                )
            current = read_process_identity(os.getpid())
            if (
                process.supervisor_pid != current.pid
                or process.supervisor_start_time != current.starttime_ticks
                or process.supervisor_session_id != current.sid
                or process.supervisor_process_group_id != current.pgid
                or process.expected_parent_pid != current.pid
            ):
                raise CampaignSupervisorError("stage registered another supervisor identity")
            expectation = RegistrationExpectation(
                campaign_id=request.campaign_id,
                attempt_id=request.attempt_id,
                stage_profile=request.spec.profile,
                process_identity=process,
                interpreter_executable_sha256=request.spec.executable_sha256,
                argv_sha256=registered_argv_sha256,
                stage_source_sha256=request.spec.stage_source_sha256,
            )
            capability = issue_internal_stage_capability(
                request.issuer,
                registration=registration,
                expectation=expectation,
                inputs=request.issue_inputs,
                release_token=release_token,
            )
            registration_identity = request.store.write_bytes(
                f"runtime/{stage_prefix}/process_registration.json", raw
            )
            request.store.write_json(
                f"runtime/{stage_prefix}/capability_digest.json",
                {
                    "schema_version": "nhc-phase9b-capability-digest-v1",
                    "stage": request.spec.profile.stage.value,
                    "capability_sha256": capability.sha256(),
                    "release_token_sha256": capability.release_token_sha256,
                    "replayable_capability_persisted": False,
                    "raw_release_token_persisted": False,
                },
            )
            acknowledgement = StageAcknowledgementReceiptV1(
                {
                    "schema_version": StageAcknowledgementReceiptV1.SCHEMA_VERSION,
                    "campaign_id": request.campaign_id,
                    "attempt_id": request.attempt_id,
                    "stage": request.spec.profile.stage.value,
                    "registration_sha256": registration_identity.sha256,
                    "capability_sha256": capability.sha256(),
                    "release_token_sha256": capability.release_token_sha256,
                    "accepted": True,
                }
            )
            request.store.write_bytes(
                f"runtime/{stage_prefix}/acknowledgement.json",
                acknowledgement.canonical_bytes(),
            )
            write_pipe_frame(release_write, make_release_frame(capability, release_token))
        except BaseException as exc:
            callback_error = exc
        finally:
            for descriptor in (registration_read, release_write):
                with suppress(OSError):
                    os.close(descriptor)

    try:
        result = run_supervised(
            argv,
            policy=SupervisionPolicy(
                timeout_seconds=max(
                    0.001,
                    (request.issue_inputs.stage_deadline_ns - time.monotonic_ns()) / 1_000_000_000,
                ),
                terminate_grace_seconds=TERMINATION_GRACE_SECONDS,
                stream_capture_limit_bytes=64 * 1024,
                absolute_deadline_monotonic=request.issue_inputs.stage_deadline_ns / 1_000_000_000,
            ),
            cwd=request.spec.cwd,
            env=request.spec.environment,
            pass_fds=(registration_write, release_read),
            on_process_started=on_started,
        )
    finally:
        for descriptor in (registration_write, release_read, registration_read, release_write):
            with suppress(OSError):
                os.close(descriptor)
    if callback_error is not None:
        raise CampaignSupervisorError(
            f"stage registration/capability release failed: {type(callback_error).__name__}"
        ) from callback_error
    label: Mapping[str, object] | None = None
    if result.succeeded and capability is not None:
        consumption_raw, _ = request.store.read(
            f"runtime/{stage_prefix}/capability_consumption.json"
        )
        consumption = StageCapabilityConsumptionReceiptV1.from_bytes(consumption_raw)
        consumed_payload = consumption.to_payload()
        if (
            consumed_payload["capability_sha256"] != capability.sha256()
            or consumed_payload["release_token_sha256"] != capability.release_token_sha256
        ):
            raise CampaignSupervisorError("stage capability-consumption receipt drifted")
        if request.spec.profile.stage is StageName.A2:
            result_raw, _ = request.store.read("runtime/stage_a2/route_result.json")
            route_result = strict_json_object(result_raw, label="A2 route result")
            if (
                set(route_result)
                != {
                    "schema_version",
                    "status",
                    "source",
                    "dft_deprot_electronic_kcal",
                    "synthetic_test_only",
                }
                or route_result["status"] != "accepted"
            ):
                raise CampaignSupervisorError("A2 route-result evidence drifted")
            label = route_result
    return StageLaunchResult(
        stage=request.spec.profile.stage,
        supervision=result,
        capability=capability,
        registration=registration,
        acknowledgement=acknowledgement,
        label=label,
    )


@dataclass(frozen=True, slots=True)
class CampaignRuntimeInputs:
    campaign_identity: AssistedCampaignIdentityV1
    campaign_capability_sha256: str
    candidate: str
    request_id: str
    attempt_id: str
    request_sha256: str
    manifest_sha256: str
    resources_sha256: str
    full_source_sha256: str
    shared_schema_source_sha256: str
    shared_pyscf_core_source_sha256: str
    campaign_control_source_sha256: str
    stage_a1_source_sha256: str
    stage_a2_source_sha256: str
    mlff_stable_profile_id: str
    mlff_stable_profile_sha256: str
    mlff_private_binding_sha256: str
    gpupyscf_stable_profile_id: str
    gpupyscf_stable_profile_sha256: str
    gpupyscf_private_binding_sha256: str
    input_identity_sha256: str
    output_root_identity_sha256: str
    schema_identities_sha256: str
    weight_sha256: str
    optimizer_protocol_sha256: str


@dataclass(frozen=True, slots=True)
class CampaignExecutionPlan:
    a1_spec: StageSubprocessSpec
    a2_spec: StageSubprocessSpec


def _process_absence_digest(result: SupervisionResult) -> str:
    if (
        not result.safe_to_finalize
        or not result.group_cleanup_confirmed
        or not result.direct_child_reaped
    ):
        raise CampaignSupervisorError("stage process tree is not proven absent")
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "pid": result.pid,
                "pgid": result.pgid,
                "group_cleanup_confirmed": result.group_cleanup_confirmed,
                "direct_child_reaped": result.direct_child_reaped,
                "orphan_descendants_detected": result.orphan_descendants_detected,
            }
        )
    ).hexdigest()


def _terminal_from_store(
    store: CampaignEvidenceStore,
    path: str,
    cls: type[StageA1TerminalReceiptV1] | type[StageA2TerminalReceiptV1],
) -> StageA1TerminalReceiptV1 | StageA2TerminalReceiptV1:
    raw, _ = store.read(path)
    return cls.from_bytes(raw)


def run_assisted_campaign(
    *,
    inputs: CampaignRuntimeInputs,
    plan: CampaignExecutionPlan,
    store: CampaignEvidenceStore,
    launcher: StageLauncher = launch_registered_stage_subprocess,
    identity_reader: Callable[[int], ProcessIdentity] = read_process_identity,
    clock_ns: Callable[[], int] = time.monotonic_ns,
) -> AssistedCampaignTerminalReceiptV1:
    """One long-lived supervisor owns A1, verification, A2, and route terminal."""

    identity = inputs.campaign_identity.to_payload()
    if (
        identity["attempt_id"] != inputs.attempt_id
        or identity["request_sha256"] != inputs.request_sha256
        or identity["full_source_sha256"] != inputs.full_source_sha256
    ):
        raise CampaignSupervisorError("campaign capability/identity binding drifted")
    supervisor_identity = identity_reader(os.getpid())
    domain, schedule = derive_campaign_schedule(
        supervisor_identity=supervisor_identity,
        clock_ns=clock_ns,
    )
    store.write_bytes(
        "runtime/campaign/campaign_identity.json",
        inputs.campaign_identity.canonical_bytes(),
    )
    store.write_bytes("runtime/campaign/campaign_schedule.json", schedule.canonical_bytes())
    store.write_json(
        "runtime/campaign/campaign_ack.json",
        {
            "schema_version": "nhc-phase9b-campaign-ack-v1",
            "campaign_capability_sha256": inputs.campaign_capability_sha256,
            "campaign_identity_sha256": inputs.campaign_identity.sha256(),
            "supervisor_process_start_identity_sha256": (
                domain.supervisor_process_start_identity_sha256
            ),
            "acknowledged": True,
        },
    )
    issuer = create_campaign_supervisor_issuer(inputs.campaign_capability_sha256)
    schedule_payload = schedule.to_payload()
    campaign_start = cast(int, schedule_payload["campaign_monotonic_start_ns"])
    campaign_deadline = cast(int, schedule_payload["campaign_absolute_deadline_ns"])
    a1_deadline = cast(int, schedule_payload["a1_deadline_ns"])
    a1_inputs = CapabilityIssueInputs(
        candidate=inputs.candidate,
        stable_profile_id=inputs.mlff_stable_profile_id,
        stable_profile_sha256=inputs.mlff_stable_profile_sha256,
        private_binding_sha256=inputs.mlff_private_binding_sha256,
        shared_schema_source_sha256=inputs.shared_schema_source_sha256,
        input_identity_sha256=inputs.input_identity_sha256,
        output_root_identity_sha256=inputs.output_root_identity_sha256,
        resources_identity_sha256=inputs.resources_sha256,
        schema_identities_sha256=inputs.schema_identities_sha256,
        campaign_monotonic_start_ns=campaign_start,
        campaign_absolute_deadline_ns=campaign_deadline,
        stage_deadline_ns=a1_deadline,
        clock_domain_digest=domain.clock_domain_digest,
        linux_boot_id_sha256=domain.linux_boot_id_sha256,
        host_execution_identity_sha256=domain.host_execution_identity_sha256,
        a2_admission_sha256=None,
    )
    a1_launch = launcher(
        StageLaunchRequest(
            campaign_id=str(identity["campaign_id"]),
            attempt_id=inputs.attempt_id,
            candidate=inputs.candidate,
            spec=plan.a1_spec,
            issuer=issuer,
            issue_inputs=a1_inputs,
            store=store,
        )
    )
    if not a1_launch.accepted:
        return _write_rejected_campaign_terminal(
            inputs=inputs,
            store=store,
            schedule=schedule,
            runtime_state=CampaignRuntimeState.A1_REJECTED,
            failure_code="a1_process_failed",
            a1_terminal_sha256=None,
            verification_sha256=None,
            admission_sha256=None,
            a2_terminal_sha256=None,
        )
    a1_end_ns = clock_ns()
    absence_digest = _process_absence_digest(a1_launch.supervision)
    a1_terminal = _terminal_from_store(
        store, "runtime/stage_a1/terminal.json", StageA1TerminalReceiptV1
    )
    assert isinstance(a1_terminal, StageA1TerminalReceiptV1)
    if a1_terminal.to_payload()["terminal_state"] != "accepted":
        return _write_rejected_campaign_terminal(
            inputs=inputs,
            store=store,
            schedule=schedule,
            runtime_state=CampaignRuntimeState.A1_REJECTED,
            failure_code=str(a1_terminal.to_payload()["terminal_state"]),
            a1_terminal_sha256=a1_terminal.sha256(),
            verification_sha256=None,
            admission_sha256=None,
            a2_terminal_sha256=None,
        )
    proposal_raw, _ = store.read("runtime/stage_a1/handoff_proposal.json")
    proposal = A1HandoffProposalReceiptV1.from_bytes(proposal_raw)
    handoff_start_ns = clock_ns()
    if handoff_start_ns < a1_end_ns:
        raise CampaignSupervisorError("handoff began before A1 ended")
    verification = verify_a1_handoff(
        store,
        proposal=proposal,
        proposal_path="runtime/stage_a1/handoff_proposal.json",
        a1_process_tree_absence_sha256=absence_digest,
        supervisor_verifier_source_sha256=inputs.campaign_control_source_sha256,
        expected_campaign_id=str(identity["campaign_id"]),
        expected_candidate=inputs.candidate,
        expected_attempt_id=inputs.attempt_id,
    )
    store.write_bytes("runtime/handoff/verification.json", verification.canonical_bytes())
    if verification.verification_outcome != "accepted":
        return _write_rejected_campaign_terminal(
            inputs=inputs,
            store=store,
            schedule=schedule,
            runtime_state=CampaignRuntimeState.HANDOFF_REJECTED,
            failure_code="handoff_rejected",
            a1_terminal_sha256=a1_terminal.sha256(),
            verification_sha256=verification.sha256(),
            admission_sha256=None,
            a2_terminal_sha256=None,
        )
    admission_time = clock_ns()
    admission = admit_stage_a2(
        proposal,
        verification,
        stage_a2_source_sha256=inputs.stage_a2_source_sha256,
        gpu_pyscf_interpreter_profile_sha256=inputs.gpupyscf_stable_profile_sha256,
        shared_pyscf_core_source_sha256=inputs.shared_pyscf_core_source_sha256,
        shared_schema_source_sha256=inputs.shared_schema_source_sha256,
        campaign_absolute_deadline_ns=campaign_deadline,
        clock_domain_digest=domain.clock_domain_digest,
        now_ns=admission_time,
    )
    store.write_bytes("runtime/handoff/a2_admission.json", admission.canonical_bytes())
    a2_inputs = CapabilityIssueInputs(
        candidate=inputs.candidate,
        stable_profile_id=inputs.gpupyscf_stable_profile_id,
        stable_profile_sha256=inputs.gpupyscf_stable_profile_sha256,
        private_binding_sha256=inputs.gpupyscf_private_binding_sha256,
        shared_schema_source_sha256=inputs.shared_schema_source_sha256,
        input_identity_sha256=inputs.input_identity_sha256,
        output_root_identity_sha256=inputs.output_root_identity_sha256,
        resources_identity_sha256=inputs.resources_sha256,
        schema_identities_sha256=inputs.schema_identities_sha256,
        campaign_monotonic_start_ns=campaign_start,
        campaign_absolute_deadline_ns=campaign_deadline,
        stage_deadline_ns=campaign_deadline,
        clock_domain_digest=domain.clock_domain_digest,
        linux_boot_id_sha256=domain.linux_boot_id_sha256,
        host_execution_identity_sha256=domain.host_execution_identity_sha256,
        a2_admission_sha256=admission.sha256(),
    )
    a2_launch = launcher(
        StageLaunchRequest(
            campaign_id=str(identity["campaign_id"]),
            attempt_id=inputs.attempt_id,
            candidate=inputs.candidate,
            spec=plan.a2_spec,
            issuer=issuer,
            issue_inputs=a2_inputs,
            store=store,
        )
    )
    if not a2_launch.accepted:
        return _write_rejected_campaign_terminal(
            inputs=inputs,
            store=store,
            schedule=schedule,
            runtime_state=CampaignRuntimeState.A2_REJECTED,
            failure_code="a2_process_failed",
            a1_terminal_sha256=a1_terminal.sha256(),
            verification_sha256=verification.sha256(),
            admission_sha256=admission.sha256(),
            a2_terminal_sha256=None,
        )
    a2_start_ns = admission_time
    if a2_start_ns < handoff_start_ns or a2_start_ns < a1_end_ns:
        raise CampaignSupervisorError("A1 and A2 process windows overlap")
    _process_absence_digest(a2_launch.supervision)
    a2_terminal = _terminal_from_store(
        store, "runtime/stage_a2/terminal.json", StageA2TerminalReceiptV1
    )
    assert isinstance(a2_terminal, StageA2TerminalReceiptV1)
    if a2_terminal.to_payload()["terminal_state"] != "accepted":
        return _write_rejected_campaign_terminal(
            inputs=inputs,
            store=store,
            schedule=schedule,
            runtime_state=CampaignRuntimeState.A2_REJECTED,
            failure_code=str(a2_terminal.to_payload()["terminal_state"]),
            a1_terminal_sha256=a1_terminal.sha256(),
            verification_sha256=verification.sha256(),
            admission_sha256=admission.sha256(),
            a2_terminal_sha256=a2_terminal.sha256(),
        )
    if a2_launch.label is None:
        return _write_rejected_campaign_terminal(
            inputs=inputs,
            store=store,
            schedule=schedule,
            runtime_state=CampaignRuntimeState.INDETERMINATE,
            failure_code="a2_label_evidence_missing",
            a1_terminal_sha256=a1_terminal.sha256(),
            verification_sha256=verification.sha256(),
            admission_sha256=admission.sha256(),
            a2_terminal_sha256=a2_terminal.sha256(),
        )
    return _write_campaign_terminal(
        inputs=inputs,
        store=store,
        schedule=schedule,
        runtime_state=CampaignRuntimeState.ROUTE_ACCEPTED,
        route_outcome="accepted",
        label=dict(a2_launch.label),
        failure=None,
        a1_terminal_sha256=a1_terminal.sha256(),
        verification_sha256=verification.sha256(),
        admission_sha256=admission.sha256(),
        a2_terminal_sha256=a2_terminal.sha256(),
    )


def _write_rejected_campaign_terminal(
    *,
    inputs: CampaignRuntimeInputs,
    store: CampaignEvidenceStore,
    schedule: CampaignScheduleV1,
    runtime_state: CampaignRuntimeState,
    failure_code: str,
    a1_terminal_sha256: str | None,
    verification_sha256: str | None,
    admission_sha256: str | None,
    a2_terminal_sha256: str | None,
) -> AssistedCampaignTerminalReceiptV1:
    failure = {
        "classification": failure_code,
        "stage": runtime_state.value,
        "details_sha256": hashlib.sha256(failure_code.encode("utf-8")).hexdigest(),
    }
    return _write_campaign_terminal(
        inputs=inputs,
        store=store,
        schedule=schedule,
        runtime_state=runtime_state,
        route_outcome="rejected",
        label=None,
        failure=failure,
        a1_terminal_sha256=a1_terminal_sha256,
        verification_sha256=verification_sha256,
        admission_sha256=admission_sha256,
        a2_terminal_sha256=a2_terminal_sha256,
    )


def _write_campaign_terminal(
    *,
    inputs: CampaignRuntimeInputs,
    store: CampaignEvidenceStore,
    schedule: CampaignScheduleV1,
    runtime_state: CampaignRuntimeState,
    route_outcome: str,
    label: Mapping[str, object] | None,
    failure: Mapping[str, object] | None,
    a1_terminal_sha256: str | None,
    verification_sha256: str | None,
    admission_sha256: str | None,
    a2_terminal_sha256: str | None,
) -> AssistedCampaignTerminalReceiptV1:
    # Hash-closed acyclic order: terminal binds the immutable preterminal set;
    # the final manifest, written after terminal, binds terminal itself.
    preterminal_manifest = store.build_manifest(
        campaign_id=str(inputs.campaign_identity.to_payload()["campaign_id"]),
        attempt_id=inputs.attempt_id,
        terminal_classification=route_outcome,
    )
    terminal = AssistedCampaignTerminalReceiptV1(
        {
            "schema_version": AssistedCampaignTerminalReceiptV1.SCHEMA_VERSION,
            "campaign_id": str(inputs.campaign_identity.to_payload()["campaign_id"]),
            "attempt_id": inputs.attempt_id,
            "candidate": inputs.candidate,
            "route": "assisted",
            "guardian_launch_state": GuardianLaunchState.ACKNOWLEDGED.value,
            "campaign_runtime_state": runtime_state.value,
            "route_outcome": route_outcome,
            "schedule_sha256": schedule.sha256(),
            "evidence_manifest_sha256": preterminal_manifest.sha256(),
            "a1_terminal_sha256": a1_terminal_sha256,
            "handoff_verification_sha256": verification_sha256,
            "a2_admission_sha256": admission_sha256,
            "a2_terminal_sha256": a2_terminal_sha256,
            "label": None if label is None else dict(label),
            "failure": None if failure is None else dict(failure),
        }
    )
    store.write_bytes("runtime/campaign/campaign_terminal.json", terminal.canonical_bytes())
    store.write_bytes("runtime/evidence/route_terminal.json", terminal.canonical_bytes())
    final_manifest = store.build_manifest(
        campaign_id=str(inputs.campaign_identity.to_payload()["campaign_id"]),
        attempt_id=inputs.attempt_id,
        terminal_classification=route_outcome,
    )
    store.write_bytes("runtime/evidence/evidence_manifest.json", final_manifest.canonical_bytes())
    store.assert_no_extra_files()
    return terminal


__all__ = [
    "A1_LOCAL_NS",
    "CAMPAIGN_SUPERVISOR_SCHEMA_VERSION",
    "CAMPAIGN_WALL_NS",
    "TERMINATION_GRACE_SECONDS",
    "CampaignClockDomain",
    "CampaignExecutionPlan",
    "CampaignRuntimeInputs",
    "CampaignSupervisorError",
    "StageLaunchRequest",
    "StageLaunchResult",
    "StageLauncher",
    "StageSubprocessSpec",
    "derive_campaign_schedule",
    "launch_registered_stage_subprocess",
    "run_assisted_campaign",
]
