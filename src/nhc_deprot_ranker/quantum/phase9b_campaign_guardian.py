"""Gate-closed one-shot guardian for the assisted split-process campaign."""

from __future__ import annotations

import hashlib
import os
import select
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from nhc_deprot_ranker.quantum.one_shot_permit import (
    PermitErrors,
    consume_one_shot_permit,
)
from nhc_deprot_ranker.quantum.phase9b_campaign_evidence import CampaignEvidenceStore
from nhc_deprot_ranker.quantum.phase9b_campaign_schemas import (
    AssistedCampaignPermitV3,
    GuardianLaunchReceiptV2,
    GuardianLaunchState,
    canonical_json_bytes,
    strict_json_object,
)
from nhc_deprot_ranker.quantum.phase9b_internal_stage_capability import (
    read_pipe_frame,
    write_pipe_frame,
)

CAMPAIGN_GUARDIAN_SCHEMA_VERSION: Final = "nhc-phase9b-assisted-campaign-guardian-v1"
READY_PERMIT_NAME: Final = "permit.ready.json"
CONSUMED_PERMIT_NAME: Final = "permit.consumed.json"
PERMIT_MODE: Final = 0o400
ACK_TIMEOUT_SECONDS: Final = 60.0


class CampaignGuardianError(RuntimeError):
    """The campaign guardian failed before or after permit consumption."""


class CampaignGuardianNotAuthorizedError(CampaignGuardianError):
    """A source/public gate remains closed."""


class CampaignGuardianPermitValidationError(CampaignGuardianError):
    pass


class CampaignGuardianPermitConsumedError(CampaignGuardianError):
    pass


@dataclass(frozen=True, slots=True)
class CampaignGuardianLaunchPlan:
    campaign_id: str
    attempt_id: str
    candidate: str
    ready_permit_path: Path
    supervisor_argv_template: tuple[str, ...]
    cwd: Path
    environment: dict[str, str]
    campaign_capability_payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class SpawnedCampaignSupervisor:
    pid: int
    process_group_id: int
    session_id: int


def _validate_authorizing_permit(raw: bytes) -> AssistedCampaignPermitV3:
    payload = strict_json_object(raw, label="assisted campaign permit")
    permit = AssistedCampaignPermitV3(payload)
    if permit.canonical_bytes() != raw:
        raise CampaignGuardianPermitValidationError("campaign permit bytes are noncanonical")
    authorization = permit.to_payload()["authorization"]
    if not isinstance(authorization, dict):
        raise CampaignGuardianPermitValidationError("campaign permit authorization is invalid")
    if (
        authorization["execution_authorized"] is not True
        or authorization["permit_consumption_authorized"] is not True
        or authorization["label_authorized"] is not True
    ):
        raise CampaignGuardianPermitValidationError("non-authorizing permit cannot be consumed")
    return permit


def _public_execution_gates_open() -> bool:
    # Reuse existing reviewed gates; Item 10 creates no twelfth gate assignment.
    from nhc_deprot_ranker.quantum import phase9b_guardian, two_endpoint

    return (
        phase9b_guardian.EXECUTION_AUTHORIZED is True and two_endpoint.EXECUTION_AUTHORIZED is True
    )


def launch_assisted_campaign_guardian(
    plan: CampaignGuardianLaunchPlan,
    *,
    store: CampaignEvidenceStore,
) -> tuple[SpawnedCampaignSupervisor, GuardianLaunchReceiptV2]:
    """Consume once, spawn/ack one supervisor, write receipt, and return promptly."""

    # No pipe, timestamp, filesystem write, or spawn occurs before this check.
    if not _public_execution_gates_open():
        raise CampaignGuardianNotAuthorizedError("assisted campaign public gates are closed")

    errors = PermitErrors(
        error=CampaignGuardianError,
        validation=CampaignGuardianPermitValidationError,
        consumed=CampaignGuardianPermitConsumedError,
    )
    consumed = consume_one_shot_permit(
        plan.ready_permit_path,
        ready_relative_name=READY_PERMIT_NAME,
        consumed_relative_name=CONSUMED_PERMIT_NAME,
        ready_mode=PERMIT_MODE,
        consumed_mode=PERMIT_MODE,
        validate=_validate_authorizing_permit,
        errors=errors,
    )
    permit = consumed.validation_result
    if not isinstance(permit, AssistedCampaignPermitV3):
        raise CampaignGuardianError("consumed campaign permit validation result drifted")
    consumption = store.write_json(
        "runtime/evidence/permit_consumption.json",
        {
            "schema_version": "nhc-phase9b-campaign-permit-consumption-v1",
            "campaign_id": plan.campaign_id,
            "attempt_id": plan.attempt_id,
            "permit_sha256": consumed.permit_sha256,
            "consumed_sha256": consumed.consumed_sha256,
            "one_shot": True,
            "restored": False,
        },
    )

    capability_read, capability_write = os.pipe()
    ack_read, ack_write = os.pipe()
    os.set_inheritable(capability_read, True)
    os.set_inheritable(ack_write, True)
    argv = tuple(
        part.replace("{campaign_capability_fd}", str(capability_read)).replace(
            "{campaign_ack_fd}", str(ack_write)
        )
        for part in plan.supervisor_argv_template
    )
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            argv,
            shell=False,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            pass_fds=(capability_read, ack_write),
            cwd=plan.cwd,
            env=plan.environment,
        )
        os.close(capability_read)
        os.close(ack_write)
        write_pipe_frame(capability_write, canonical_json_bytes(plan.campaign_capability_payload))
        os.close(capability_write)
        ready, _, _ = select.select([ack_read], [], [], ACK_TIMEOUT_SECONDS)
        if not ready:
            raise CampaignGuardianError("campaign supervisor acknowledgement timed out")
        ack_raw = read_pipe_frame(ack_read)
        ack = strict_json_object(ack_raw, label="campaign supervisor acknowledgement")
        if ack != {
            "schema_version": "nhc-phase9b-campaign-supervisor-ack-v1",
            "campaign_id": plan.campaign_id,
            "attempt_id": plan.attempt_id,
            "acknowledged": True,
        }:
            raise CampaignGuardianError("campaign supervisor acknowledgement drifted")
        observed = SpawnedCampaignSupervisor(
            pid=process.pid,
            process_group_id=os.getpgid(process.pid),
            session_id=os.getsid(process.pid),
        )
        if observed.process_group_id != process.pid or observed.session_id != process.pid:
            raise CampaignGuardianError("campaign supervisor does not lead its session/group")
        receipt = GuardianLaunchReceiptV2(
            {
                "schema_version": GuardianLaunchReceiptV2.SCHEMA_VERSION,
                "campaign_id": plan.campaign_id,
                "attempt_id": plan.attempt_id,
                "state": GuardianLaunchState.ACKNOWLEDGED.value,
                "permit_sha256": consumed.permit_sha256,
                "permit_consumption_sha256": consumption.sha256,
                "supervisor_registration_sha256": hashlib.sha256(
                    canonical_json_bytes(
                        {
                            "pid": observed.pid,
                            "pgid": observed.process_group_id,
                            "sid": observed.session_id,
                            "argv_sha256": hashlib.sha256(
                                canonical_json_bytes(list(argv))
                            ).hexdigest(),
                        }
                    )
                ).hexdigest(),
                "acknowledgement_sha256": hashlib.sha256(ack_raw).hexdigest(),
                "failure": None,
            }
        )
        store.write_bytes("runtime/campaign/guardian_launch.json", receipt.canonical_bytes())
        return observed, receipt
    except BaseException:
        # Permit remains consumed.  There is no restore and no second spawn.
        if process is not None and process.poll() is None:
            with suppress(OSError):
                os.killpg(process.pid, 15)
        raise
    finally:
        for descriptor in (capability_read, capability_write, ack_read, ack_write):
            with suppress(OSError):
                os.close(descriptor)


__all__ = [
    "CAMPAIGN_GUARDIAN_SCHEMA_VERSION",
    "CampaignGuardianError",
    "CampaignGuardianLaunchPlan",
    "CampaignGuardianNotAuthorizedError",
    "CampaignGuardianPermitConsumedError",
    "CampaignGuardianPermitValidationError",
    "SpawnedCampaignSupervisor",
    "launch_assisted_campaign_guardian",
]
