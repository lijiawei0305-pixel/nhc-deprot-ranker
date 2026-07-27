"""Generic post-registration authority handshake for both campaign stages.

The core has no stage-specific branches.  Frozen :class:`StageAuthorityProfile`
instances supply differences, while one comparison, frame parser, token
consumer, and process-identity validator protect A1 and A2 alike.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

from nhc_deprot_ranker.quantum.phase9b_campaign_schemas import (
    CampaignSchemaError,
    StageName,
    StageRegistrationReceiptV1,
    canonical_json_bytes,
    require_id,
    require_int,
    require_sha256,
    strict_json_object,
)

INTERNAL_STAGE_CAPABILITY_SCHEMA_VERSION: Final = "nhc-phase9b-internal-stage-capability-v1"
STAGE_AUTHORITY_PROFILE_SCHEMA_VERSION: Final = "nhc-phase9b-stage-authority-profile-v1"
MAX_FRAME_BYTES: Final = 128 * 1024


class InternalStageCapabilityError(RuntimeError):
    """An internal stage authority or one-shot release failed closed."""


@dataclass(frozen=True, slots=True)
class StageAuthorityProfile:
    profile_id: str
    stage: StageName
    allowed_import_roots: tuple[str, ...]
    forbidden_import_roots: tuple[str, ...]
    requires_admission: bool

    def __post_init__(self) -> None:
        require_id(self.profile_id, "stage profile_id")
        if not self.allowed_import_roots or not self.forbidden_import_roots:
            raise CampaignSchemaError("stage import policies must be non-empty")
        if set(self.allowed_import_roots) & set(self.forbidden_import_roots):
            raise CampaignSchemaError("allowed and forbidden imports overlap")


@dataclass(frozen=True, slots=True)
class HandshakeAuthorityProfile:
    """Generic adapter shape shared without changing Phase 8B durable bytes."""

    profile_id: str
    authority_kind: str
    registration_schema_version: str
    acknowledgement_schema_version: str
    one_shot_release: bool
    process_identity_required: bool

    def __post_init__(self) -> None:
        require_id(self.profile_id, "handshake profile_id")
        require_id(self.authority_kind, "authority_kind")
        if not self.registration_schema_version or not self.acknowledgement_schema_version:
            raise CampaignSchemaError("handshake schema versions must be non-empty")
        if not self.one_shot_release or not self.process_identity_required:
            raise CampaignSchemaError("handshake profiles cannot weaken release/process checks")


Phase8BWorkerProfile: Final = HandshakeAuthorityProfile(
    profile_id="phase8b-worker-profile",
    authority_kind="ordinary_worker",
    registration_schema_version="nhc-phase8b-worker-registration-v1",
    acknowledgement_schema_version="nhc-phase8b-guardian-ack-v1",
    one_shot_release=True,
    process_identity_required=True,
)
Phase9BDirectWorkerProfile: Final = HandshakeAuthorityProfile(
    profile_id="phase9b-direct-worker-profile",
    authority_kind="ordinary_worker",
    registration_schema_version="nhc-phase8b-worker-registration-v1",
    acknowledgement_schema_version="nhc-phase8b-guardian-ack-v1",
    one_shot_release=True,
    process_identity_required=True,
)
Phase9BA1StageProfile: Final = HandshakeAuthorityProfile(
    profile_id="phase9b-a1-stage-profile",
    authority_kind="internal_campaign_stage",
    registration_schema_version="nhc-phase9b-stage-registration-v1",
    acknowledgement_schema_version="nhc-phase9b-stage-acknowledgement-v1",
    one_shot_release=True,
    process_identity_required=True,
)
Phase9BA2StageProfile: Final = HandshakeAuthorityProfile(
    profile_id="phase9b-a2-stage-profile",
    authority_kind="internal_campaign_stage",
    registration_schema_version="nhc-phase9b-stage-registration-v1",
    acknowledgement_schema_version="nhc-phase9b-stage-acknowledgement-v1",
    one_shot_release=True,
    process_identity_required=True,
)


PHASE9B_A1_STAGE_PROFILE: Final = StageAuthorityProfile(
    profile_id="phase9b-a1-stage-v1",
    stage=StageName.A1,
    allowed_import_roots=("aimnet", "ase", "torch"),
    forbidden_import_roots=("geometric", "pyscf", "pyscf_dispersion"),
    requires_admission=False,
)
PHASE9B_A2_STAGE_PROFILE: Final = StageAuthorityProfile(
    profile_id="phase9b-a2-stage-v1",
    stage=StageName.A2,
    allowed_import_roots=("geometric", "pyscf", "pyscf_dispersion"),
    forbidden_import_roots=("aimnet", "ase", "torch"),
    requires_admission=True,
)


@dataclass(frozen=True, slots=True)
class RegisteredProcessIdentity:
    supervisor_pid: int
    supervisor_start_time: int
    supervisor_session_id: int
    supervisor_process_group_id: int
    stage_pid: int
    stage_start_time: int
    stage_session_id: int
    stage_process_group_id: int
    expected_parent_pid: int

    def __post_init__(self) -> None:
        for name, value in self.to_payload().items():
            require_int(value, name, minimum=1)
        if self.expected_parent_pid != self.supervisor_pid:
            raise InternalStageCapabilityError("stage parent is not the campaign supervisor")
        if self.stage_session_id != self.stage_pid or self.stage_process_group_id != self.stage_pid:
            raise InternalStageCapabilityError("stage must lead its own session and process group")
        if self.stage_process_group_id == self.supervisor_process_group_id:
            raise InternalStageCapabilityError("supervisor and stage process groups must differ")

    def to_payload(self) -> dict[str, int]:
        return {
            "supervisor_pid": self.supervisor_pid,
            "supervisor_start_time": self.supervisor_start_time,
            "supervisor_session_id": self.supervisor_session_id,
            "supervisor_process_group_id": self.supervisor_process_group_id,
            "stage_pid": self.stage_pid,
            "stage_start_time": self.stage_start_time,
            "stage_session_id": self.stage_session_id,
            "stage_process_group_id": self.stage_process_group_id,
            "expected_parent_pid": self.expected_parent_pid,
        }

    @classmethod
    def from_payload(cls, payload: object) -> RegisteredProcessIdentity:
        if not isinstance(payload, dict):
            raise InternalStageCapabilityError("process_identity must be an object")
        expected = {
            "supervisor_pid",
            "supervisor_start_time",
            "supervisor_session_id",
            "supervisor_process_group_id",
            "stage_pid",
            "stage_start_time",
            "stage_session_id",
            "stage_process_group_id",
            "expected_parent_pid",
        }
        if set(payload) != expected:
            raise InternalStageCapabilityError("process identity fields drifted")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in payload.values()):
            raise InternalStageCapabilityError("process identity values must be integers")
        return cls(**cast(dict[str, int], payload))


@dataclass(frozen=True, slots=True)
class RegistrationExpectation:
    campaign_id: str
    attempt_id: str
    stage_profile: StageAuthorityProfile
    process_identity: RegisteredProcessIdentity
    interpreter_executable_sha256: str
    argv_sha256: str
    stage_source_sha256: str

    def __post_init__(self) -> None:
        require_id(self.campaign_id, "campaign_id")
        require_id(self.attempt_id, "attempt_id")
        for label, value in (
            ("interpreter_executable_sha256", self.interpreter_executable_sha256),
            ("argv_sha256", self.argv_sha256),
            ("stage_source_sha256", self.stage_source_sha256),
        ):
            require_sha256(value, label)


def validate_stage_registration(
    registration: StageRegistrationReceiptV1,
    expectation: RegistrationExpectation,
) -> None:
    """One exact registration comparison shared by A1 and A2."""

    payload = registration.to_payload()
    comparisons = {
        "campaign_id": expectation.campaign_id,
        "attempt_id": expectation.attempt_id,
        "stage": expectation.stage_profile.stage.value,
        "process_identity": expectation.process_identity.to_payload(),
        "interpreter_executable_sha256": expectation.interpreter_executable_sha256,
        "argv_sha256": expectation.argv_sha256,
        "source_sha256": expectation.stage_source_sha256,
    }
    for field, expected in comparisons.items():
        if payload[field] != expected:
            raise InternalStageCapabilityError(f"stage registration mismatch: {field}")


@dataclass(frozen=True, slots=True)
class InternalStageCapabilityV1:
    capability_id: str
    campaign_id: str
    attempt_id: str
    candidate: str
    route: Literal["assisted"]
    stage: StageName
    process_identity: RegisteredProcessIdentity
    registration_receipt_sha256: str
    stable_profile_id: str
    stable_profile_sha256: str
    private_binding_sha256: str
    stage_argv_sha256: str
    stage_source_sha256: str
    shared_schema_source_sha256: str
    input_identity_sha256: str
    output_root_identity_sha256: str
    resources_identity_sha256: str
    schema_identities_sha256: str
    campaign_monotonic_start_ns: int
    campaign_absolute_deadline_ns: int
    stage_deadline_ns: int
    clock_domain_digest: str
    linux_boot_id_sha256: str
    host_execution_identity_sha256: str
    release_token_sha256: str
    a2_admission_sha256: str | None

    def __post_init__(self) -> None:
        for field in (
            "capability_id",
            "campaign_id",
            "attempt_id",
            "candidate",
            "stable_profile_id",
        ):
            require_id(getattr(self, field), field)
        if self.route != "assisted":
            raise InternalStageCapabilityError("internal stage capability route must be assisted")
        for field in (
            "registration_receipt_sha256",
            "stable_profile_sha256",
            "private_binding_sha256",
            "stage_argv_sha256",
            "stage_source_sha256",
            "shared_schema_source_sha256",
            "input_identity_sha256",
            "output_root_identity_sha256",
            "resources_identity_sha256",
            "schema_identities_sha256",
            "clock_domain_digest",
            "linux_boot_id_sha256",
            "host_execution_identity_sha256",
            "release_token_sha256",
        ):
            require_sha256(getattr(self, field), field)
        if self.a2_admission_sha256 is not None:
            require_sha256(self.a2_admission_sha256, "a2_admission_sha256")
        if self.stage is StageName.A1 and self.a2_admission_sha256 is not None:
            raise InternalStageCapabilityError("A1 capability cannot bind A2 admission")
        if self.stage is StageName.A2 and self.a2_admission_sha256 is None:
            raise InternalStageCapabilityError("A2 capability requires durable admission")
        start = require_int(self.campaign_monotonic_start_ns, "campaign start", minimum=1)
        campaign_end = require_int(
            self.campaign_absolute_deadline_ns, "campaign deadline", minimum=1
        )
        stage_end = require_int(self.stage_deadline_ns, "stage deadline", minimum=1)
        if campaign_end - start != 7_200_000_000_000:
            raise InternalStageCapabilityError("campaign deadline derivation drifted")
        if not start < stage_end <= campaign_end:
            raise InternalStageCapabilityError("stage deadline escapes campaign deadline")
        if self.stage is StageName.A1 and stage_end != min(campaign_end, start + 900_000_000_000):
            raise InternalStageCapabilityError("A1 local deadline drifted")

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": INTERNAL_STAGE_CAPABILITY_SCHEMA_VERSION,
            "capability_id": self.capability_id,
            "campaign_id": self.campaign_id,
            "attempt_id": self.attempt_id,
            "candidate": self.candidate,
            "route": self.route,
            "stage": self.stage.value,
            "process_identity": self.process_identity.to_payload(),
            "registration_receipt_sha256": self.registration_receipt_sha256,
            "interpreter": {
                "stable_profile_id": self.stable_profile_id,
                "stable_profile_sha256": self.stable_profile_sha256,
                "private_binding_sha256": self.private_binding_sha256,
            },
            "source": {
                "stage_source_sha256": self.stage_source_sha256,
                "shared_schema_source_sha256": self.shared_schema_source_sha256,
            },
            "stage_argv_sha256": self.stage_argv_sha256,
            "input_identity_sha256": self.input_identity_sha256,
            "output_root_identity_sha256": self.output_root_identity_sha256,
            "resources_identity_sha256": self.resources_identity_sha256,
            "schema_identities_sha256": self.schema_identities_sha256,
            "clock": {
                "clock_type": "CLOCK_MONOTONIC",
                "campaign_monotonic_start_ns": self.campaign_monotonic_start_ns,
                "campaign_absolute_deadline_ns": self.campaign_absolute_deadline_ns,
                "stage_deadline_ns": self.stage_deadline_ns,
                "clock_domain_digest": self.clock_domain_digest,
                "linux_boot_id_sha256": self.linux_boot_id_sha256,
                "host_execution_identity_sha256": self.host_execution_identity_sha256,
            },
            "release_token_sha256": self.release_token_sha256,
            "a2_admission_sha256": self.a2_admission_sha256,
            "authorization": {
                "one_shot": True,
                "external_construction_authorized": False,
                "retry_authorized": False,
            },
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_payload())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @classmethod
    def from_bytes(cls, raw: bytes) -> InternalStageCapabilityV1:
        payload = strict_json_object(
            raw, label="internal stage capability", max_bytes=MAX_FRAME_BYTES
        )
        required = {
            "schema_version",
            "capability_id",
            "campaign_id",
            "attempt_id",
            "candidate",
            "route",
            "stage",
            "process_identity",
            "registration_receipt_sha256",
            "interpreter",
            "source",
            "stage_argv_sha256",
            "input_identity_sha256",
            "output_root_identity_sha256",
            "resources_identity_sha256",
            "schema_identities_sha256",
            "clock",
            "release_token_sha256",
            "a2_admission_sha256",
            "authorization",
        }
        if (
            set(payload) != required
            or payload["schema_version"] != INTERNAL_STAGE_CAPABILITY_SCHEMA_VERSION
        ):
            raise InternalStageCapabilityError("internal capability fields/schema drifted")
        interpreter = payload["interpreter"]
        source = payload["source"]
        clock = payload["clock"]
        authorization = payload["authorization"]
        if not all(isinstance(item, dict) for item in (interpreter, source, clock, authorization)):
            raise InternalStageCapabilityError("internal capability section is not an object")
        assert isinstance(interpreter, dict) and isinstance(source, dict)
        assert isinstance(clock, dict) and isinstance(authorization, dict)
        if set(interpreter) != {
            "stable_profile_id",
            "stable_profile_sha256",
            "private_binding_sha256",
        }:
            raise InternalStageCapabilityError("interpreter capability fields drifted")
        if set(source) != {"stage_source_sha256", "shared_schema_source_sha256"}:
            raise InternalStageCapabilityError("source capability fields drifted")
        if (
            set(clock)
            != {
                "clock_type",
                "campaign_monotonic_start_ns",
                "campaign_absolute_deadline_ns",
                "stage_deadline_ns",
                "clock_domain_digest",
                "linux_boot_id_sha256",
                "host_execution_identity_sha256",
            }
            or clock["clock_type"] != "CLOCK_MONOTONIC"
        ):
            raise InternalStageCapabilityError("clock capability fields drifted")
        if authorization != {
            "one_shot": True,
            "external_construction_authorized": False,
            "retry_authorized": False,
        }:
            raise InternalStageCapabilityError("capability authorization drifted")
        try:
            capability = cls(
                capability_id=str(payload["capability_id"]),
                campaign_id=str(payload["campaign_id"]),
                attempt_id=str(payload["attempt_id"]),
                candidate=str(payload["candidate"]),
                route=payload["route"],  # type: ignore[arg-type]
                stage=StageName(cast(str, payload["stage"])),
                process_identity=RegisteredProcessIdentity.from_payload(
                    payload["process_identity"]
                ),
                registration_receipt_sha256=str(payload["registration_receipt_sha256"]),
                stable_profile_id=str(interpreter["stable_profile_id"]),
                stable_profile_sha256=str(interpreter["stable_profile_sha256"]),
                private_binding_sha256=str(interpreter["private_binding_sha256"]),
                stage_argv_sha256=str(payload["stage_argv_sha256"]),
                stage_source_sha256=str(source["stage_source_sha256"]),
                shared_schema_source_sha256=str(source["shared_schema_source_sha256"]),
                input_identity_sha256=str(payload["input_identity_sha256"]),
                output_root_identity_sha256=str(payload["output_root_identity_sha256"]),
                resources_identity_sha256=str(payload["resources_identity_sha256"]),
                schema_identities_sha256=str(payload["schema_identities_sha256"]),
                campaign_monotonic_start_ns=int(clock["campaign_monotonic_start_ns"]),
                campaign_absolute_deadline_ns=int(clock["campaign_absolute_deadline_ns"]),
                stage_deadline_ns=int(clock["stage_deadline_ns"]),
                clock_domain_digest=str(clock["clock_domain_digest"]),
                linux_boot_id_sha256=str(clock["linux_boot_id_sha256"]),
                host_execution_identity_sha256=str(clock["host_execution_identity_sha256"]),
                release_token_sha256=str(payload["release_token_sha256"]),
                a2_admission_sha256=(
                    None
                    if payload["a2_admission_sha256"] is None
                    else str(payload["a2_admission_sha256"])
                ),
            )
        except (TypeError, ValueError) as exc:
            raise InternalStageCapabilityError("internal capability values are invalid") from exc
        if capability.canonical_bytes() != raw:
            raise InternalStageCapabilityError("internal capability is not canonical")
        return capability


class CampaignSupervisorCapabilityIssuer:
    """Process-local issuer obtained only after campaign-capability validation."""

    __slots__ = ("_campaign_capability_sha256", "_issued", "_seal")

    def __init__(self, campaign_capability_sha256: str, seal: object) -> None:
        if seal is not _ISSUER_SEAL:
            raise TypeError("campaign supervisor issuers are not publicly constructible")
        require_sha256(campaign_capability_sha256, "campaign_capability_sha256")
        self._campaign_capability_sha256 = campaign_capability_sha256
        self._issued: set[StageName] = set()
        self._seal = seal


_ISSUER_SEAL: Final = object()
_CONSUMED_RELEASES: set[tuple[int, str, str]] = set()


def create_campaign_supervisor_issuer(
    campaign_capability_sha256: str,
) -> CampaignSupervisorCapabilityIssuer:
    """Called by the supervisor only after its campaign capability is validated."""

    return CampaignSupervisorCapabilityIssuer(campaign_capability_sha256, _ISSUER_SEAL)


@dataclass(frozen=True, slots=True)
class CapabilityIssueInputs:
    candidate: str
    stable_profile_id: str
    stable_profile_sha256: str
    private_binding_sha256: str
    shared_schema_source_sha256: str
    input_identity_sha256: str
    output_root_identity_sha256: str
    resources_identity_sha256: str
    schema_identities_sha256: str
    campaign_monotonic_start_ns: int
    campaign_absolute_deadline_ns: int
    stage_deadline_ns: int
    clock_domain_digest: str
    linux_boot_id_sha256: str
    host_execution_identity_sha256: str
    a2_admission_sha256: str | None


def issue_internal_stage_capability(
    issuer: CampaignSupervisorCapabilityIssuer,
    *,
    registration: StageRegistrationReceiptV1,
    expectation: RegistrationExpectation,
    inputs: CapabilityIssueInputs,
    release_token: str,
) -> InternalStageCapabilityV1:
    """Issue once, and only after exact registration verification."""

    if (
        not isinstance(issuer, CampaignSupervisorCapabilityIssuer)
        or issuer._seal is not _ISSUER_SEAL
    ):
        raise InternalStageCapabilityError("invalid campaign supervisor issuer")
    validate_stage_registration(registration, expectation)
    stage = expectation.stage_profile.stage
    if stage in issuer._issued:
        raise InternalStageCapabilityError("this stage capability was already issued")
    require_sha256(release_token, "release_token")
    release_digest = hashlib.sha256(release_token.encode("ascii")).hexdigest()
    capability_id = hashlib.sha256(
        canonical_json_bytes(
            {
                "campaign_capability_sha256": issuer._campaign_capability_sha256,
                "registration_sha256": registration.sha256(),
                "stage": stage.value,
                "release_token_sha256": release_digest,
            }
        )
    ).hexdigest()
    capability = InternalStageCapabilityV1(
        capability_id=capability_id,
        campaign_id=expectation.campaign_id,
        attempt_id=expectation.attempt_id,
        candidate=inputs.candidate,
        route="assisted",
        stage=stage,
        process_identity=expectation.process_identity,
        registration_receipt_sha256=registration.sha256(),
        stable_profile_id=inputs.stable_profile_id,
        stable_profile_sha256=inputs.stable_profile_sha256,
        private_binding_sha256=inputs.private_binding_sha256,
        stage_argv_sha256=expectation.argv_sha256,
        stage_source_sha256=expectation.stage_source_sha256,
        shared_schema_source_sha256=inputs.shared_schema_source_sha256,
        input_identity_sha256=inputs.input_identity_sha256,
        output_root_identity_sha256=inputs.output_root_identity_sha256,
        resources_identity_sha256=inputs.resources_identity_sha256,
        schema_identities_sha256=inputs.schema_identities_sha256,
        campaign_monotonic_start_ns=inputs.campaign_monotonic_start_ns,
        campaign_absolute_deadline_ns=inputs.campaign_absolute_deadline_ns,
        stage_deadline_ns=inputs.stage_deadline_ns,
        clock_domain_digest=inputs.clock_domain_digest,
        linux_boot_id_sha256=inputs.linux_boot_id_sha256,
        host_execution_identity_sha256=inputs.host_execution_identity_sha256,
        release_token_sha256=release_digest,
        a2_admission_sha256=inputs.a2_admission_sha256,
    )
    issuer._issued.add(stage)
    return capability


def make_release_frame(capability: InternalStageCapabilityV1, release_token: str) -> bytes:
    require_sha256(release_token, "release_token")
    if hashlib.sha256(release_token.encode("ascii")).hexdigest() != capability.release_token_sha256:
        raise InternalStageCapabilityError("release token does not match capability")
    frame = canonical_json_bytes(
        {
            "capability": json.loads(capability.canonical_bytes()),
            "release_token": release_token,
        }
    )
    if len(frame) > MAX_FRAME_BYTES:
        raise InternalStageCapabilityError("release frame exceeds its byte bound")
    return frame


def consume_release_frame(
    raw: bytes,
    *,
    expected: RegistrationExpectation,
    expected_clock_domain_digest: str,
    expected_linux_boot_id_sha256: str,
    now_ns: int | None = None,
) -> InternalStageCapabilityV1:
    """Validate and process-locally consume one capability/token frame."""

    payload = strict_json_object(raw, label="stage release frame", max_bytes=MAX_FRAME_BYTES)
    if set(payload) != {"capability", "release_token"}:
        raise InternalStageCapabilityError("release frame fields drifted")
    capability_payload = payload["capability"]
    token = payload["release_token"]
    if not isinstance(capability_payload, dict) or not isinstance(token, str):
        raise InternalStageCapabilityError("release frame types drifted")
    capability = InternalStageCapabilityV1.from_bytes(canonical_json_bytes(capability_payload))
    if capability.stage is not expected.stage_profile.stage:
        raise InternalStageCapabilityError("capability stage differs from registered stage")
    if capability.process_identity != expected.process_identity:
        raise InternalStageCapabilityError("capability process identity differs from registration")
    if capability.registration_receipt_sha256 == "":  # pragma: no cover - type guard
        raise InternalStageCapabilityError("capability registration identity is empty")
    if capability.stage_argv_sha256 != expected.argv_sha256:
        raise InternalStageCapabilityError("capability argv differs from registration")
    if capability.stage_source_sha256 != expected.stage_source_sha256:
        raise InternalStageCapabilityError("capability source differs from registration")
    if capability.clock_domain_digest != expected_clock_domain_digest:
        raise InternalStageCapabilityError("capability clock domain was replayed")
    if capability.linux_boot_id_sha256 != expected_linux_boot_id_sha256:
        raise InternalStageCapabilityError("capability boot identity was replayed")
    require_sha256(token, "release_token")
    if hashlib.sha256(token.encode("ascii")).hexdigest() != capability.release_token_sha256:
        raise InternalStageCapabilityError("release token digest mismatch")
    observed_now = time.monotonic_ns() if now_ns is None else now_ns
    if observed_now >= capability.stage_deadline_ns:
        raise InternalStageCapabilityError("stage capability expired")
    key = (os.getpid(), capability.capability_id, capability.release_token_sha256)
    if key in _CONSUMED_RELEASES:
        raise InternalStageCapabilityError("stage capability/token was replayed")
    _CONSUMED_RELEASES.add(key)
    return capability


def create_release_token() -> str:
    return secrets.token_hex(32)


def write_pipe_frame(fd: int, raw: bytes) -> None:
    if fd < 0 or not raw or len(raw) > MAX_FRAME_BYTES:
        raise InternalStageCapabilityError("pipe frame arguments are invalid")
    frame = len(raw).to_bytes(4, "big") + raw
    view = memoryview(frame)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise InternalStageCapabilityError("pipe write made no progress")
        view = view[written:]


def read_pipe_frame(fd: int) -> bytes:
    if fd < 0:
        raise InternalStageCapabilityError("pipe fd is invalid")

    def read_exact(count: int) -> bytes:
        chunks: list[bytes] = []
        remaining = count
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                raise InternalStageCapabilityError("pipe frame ended early")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    size = int.from_bytes(read_exact(4), "big")
    if size <= 0 or size > MAX_FRAME_BYTES:
        raise InternalStageCapabilityError("pipe frame size is invalid")
    return read_exact(size)


def _linux_starttime_ticks(pid: int, *, proc_root: os.PathLike[str] | str = "/proc") -> int:
    try:
        raw = (Path(proc_root) / str(pid) / "stat").read_text(encoding="ascii")
    except OSError as exc:
        raise InternalStageCapabilityError("Linux process start identity is unavailable") from exc
    close = raw.rfind(")")
    fields = raw[close + 2 :].split()
    try:
        return int(fields[19])
    except (IndexError, ValueError) as exc:
        raise InternalStageCapabilityError("Linux process start identity is malformed") from exc


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise InternalStageCapabilityError("stage executable identity is unavailable") from exc
    return digest.hexdigest()


def run_registered_stage_bootstrap(
    *,
    profile: StageAuthorityProfile,
    campaign_id: str,
    attempt_id: str,
    registration_fd: int,
    release_fd: int,
    supervisor_pid: int,
    supervisor_start_time: int,
    supervisor_session_id: int,
    supervisor_process_group_id: int,
    stage_source_sha256: str,
    argv: tuple[str, ...],
    registration_nonce_sha256: str,
    clock_domain_digest: str,
    linux_boot_id_sha256: str,
    now_ns: int | None = None,
) -> InternalStageCapabilityV1:
    """Register a fresh-session bootstrap, block for release, and consume once.

    A1/A2 entrypoints pass their compile-time profile; no request or environment
    value selects it.  The returned capability is the sole proof allowing the
    caller to cross its compute-import boundary.
    """

    require_sha256(stage_source_sha256, "stage_source_sha256")
    require_sha256(registration_nonce_sha256, "registration_nonce_sha256")
    pid = os.getpid()
    process = RegisteredProcessIdentity(
        supervisor_pid=supervisor_pid,
        supervisor_start_time=supervisor_start_time,
        supervisor_session_id=supervisor_session_id,
        supervisor_process_group_id=supervisor_process_group_id,
        stage_pid=pid,
        stage_start_time=_linux_starttime_ticks(pid),
        stage_session_id=os.getsid(pid),
        stage_process_group_id=os.getpgid(pid),
        expected_parent_pid=os.getppid(),
    )
    executable = os.path.realpath(sys.executable)
    argv_digest = hashlib.sha256(canonical_json_bytes(list(argv))).hexdigest()
    registration = StageRegistrationReceiptV1(
        {
            "schema_version": StageRegistrationReceiptV1.SCHEMA_VERSION,
            "campaign_id": campaign_id,
            "attempt_id": attempt_id,
            "stage": profile.stage.value,
            "process_identity": process.to_payload(),
            "interpreter_executable_sha256": _file_sha256(executable),
            "argv_sha256": argv_digest,
            "source_sha256": stage_source_sha256,
            "registration_nonce_sha256": registration_nonce_sha256,
        }
    )
    write_pipe_frame(registration_fd, registration.canonical_bytes())
    os.close(registration_fd)
    release_raw = read_pipe_frame(release_fd)
    os.close(release_fd)
    expectation = RegistrationExpectation(
        campaign_id=campaign_id,
        attempt_id=attempt_id,
        stage_profile=profile,
        process_identity=process,
        interpreter_executable_sha256=_file_sha256(executable),
        argv_sha256=argv_digest,
        stage_source_sha256=stage_source_sha256,
    )
    return consume_release_frame(
        release_raw,
        expected=expectation,
        expected_clock_domain_digest=clock_domain_digest,
        expected_linux_boot_id_sha256=linux_boot_id_sha256,
        now_ns=now_ns,
    )


__all__ = [
    "INTERNAL_STAGE_CAPABILITY_SCHEMA_VERSION",
    "MAX_FRAME_BYTES",
    "PHASE9B_A1_STAGE_PROFILE",
    "PHASE9B_A2_STAGE_PROFILE",
    "CampaignSupervisorCapabilityIssuer",
    "CapabilityIssueInputs",
    "HandshakeAuthorityProfile",
    "InternalStageCapabilityError",
    "InternalStageCapabilityV1",
    "Phase8BWorkerProfile",
    "Phase9BA1StageProfile",
    "Phase9BA2StageProfile",
    "Phase9BDirectWorkerProfile",
    "RegisteredProcessIdentity",
    "RegistrationExpectation",
    "StageAuthorityProfile",
    "consume_release_frame",
    "create_campaign_supervisor_issuer",
    "create_release_token",
    "issue_internal_stage_capability",
    "make_release_frame",
    "read_pipe_frame",
    "run_registered_stage_bootstrap",
    "validate_stage_registration",
    "write_pipe_frame",
]
