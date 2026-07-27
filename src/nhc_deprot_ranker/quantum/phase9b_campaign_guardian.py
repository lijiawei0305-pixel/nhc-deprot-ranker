"""Gate-closed one-shot guardian for the assisted split-process campaign."""

from __future__ import annotations

import argparse
import hashlib
import os
import select
import stat
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from nhc_deprot_ranker.quantum.one_shot_permit import (
    PermitErrors,
    consume_one_shot_permit,
)
from nhc_deprot_ranker.quantum.phase9b_campaign_evidence import CampaignEvidenceStore
from nhc_deprot_ranker.quantum.phase9b_campaign_schemas import (
    AssistedCampaignIdentityV1,
    AssistedCampaignPermitV3,
    GuardianLaunchReceiptV2,
    GuardianLaunchState,
    canonical_json_bytes,
    canonical_sha256,
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
    campaign_identity: AssistedCampaignIdentityV1

    def __post_init__(self) -> None:
        identity = self.campaign_identity.to_payload()
        if (
            identity["campaign_id"] != self.campaign_id
            or identity["attempt_id"] != self.attempt_id
            or identity["candidate"] != self.candidate
        ):
            raise CampaignGuardianError("guardian plan/campaign identity drifted")


@dataclass(frozen=True, slots=True)
class SpawnedCampaignSupervisor:
    pid: int
    process_group_id: int
    session_id: int


def _read_private_bootstrap(path: Path) -> tuple[CampaignGuardianLaunchPlan, Path]:
    if not path.is_absolute():
        raise CampaignGuardianError("guardian private bootstrap path must be absolute")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow == 0:
        raise CampaignGuardianError("O_NOFOLLOW is required")
    fd = os.open(path, os.O_RDONLY | nofollow)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise CampaignGuardianError("guardian private bootstrap must be a regular file")
        if info.st_size <= 0 or info.st_size > 1024 * 1024:
            raise CampaignGuardianError("guardian private bootstrap size is invalid")
        raw = b""
        while len(raw) <= 1024 * 1024:
            chunk = os.read(fd, min(64 * 1024, 1024 * 1024 + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
    finally:
        os.close(fd)
    payload = strict_json_object(raw, label="campaign guardian private bootstrap")
    if canonical_json_bytes(payload) != raw or set(payload) != {
        "schema_version",
        "campaign_identity",
        "ready_permit_path",
        "supervisor_argv_template",
        "cwd",
        "environment",
        "campaign_capability_payload",
        "evidence_root",
    }:
        raise CampaignGuardianError("guardian private bootstrap is noncanonical or malformed")
    if payload["schema_version"] != "nhc-phase9b-campaign-guardian-bootstrap-v1":
        raise CampaignGuardianError("guardian private bootstrap schema drifted")
    identity_payload = payload["campaign_identity"]
    argv = payload["supervisor_argv_template"]
    environment = payload["environment"]
    capability = payload["campaign_capability_payload"]
    if (
        not isinstance(identity_payload, dict)
        or not isinstance(argv, list)
        or not argv
        or any(not isinstance(item, str) or not item for item in argv)
        or not isinstance(environment, dict)
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in environment.items()
        )
        or ("PYTHON" + "PATH") in environment
        or not isinstance(capability, dict)
    ):
        raise CampaignGuardianError("guardian private bootstrap content is invalid")
    identity = AssistedCampaignIdentityV1(identity_payload)
    identity_body = identity.to_payload()
    plan = CampaignGuardianLaunchPlan(
        campaign_id=str(identity_body["campaign_id"]),
        attempt_id=str(identity_body["attempt_id"]),
        candidate=str(identity_body["candidate"]),
        ready_permit_path=Path(cast(str, payload["ready_permit_path"])),
        supervisor_argv_template=tuple(cast(list[str], argv)),
        cwd=Path(cast(str, payload["cwd"])),
        environment=cast(dict[str, str], environment),
        campaign_capability_payload=cast(dict[str, object], capability),
        campaign_identity=identity,
    )
    evidence_root = Path(cast(str, payload["evidence_root"]))
    if (
        not plan.ready_permit_path.is_absolute()
        or not plan.cwd.is_absolute()
        or not evidence_root.is_absolute()
    ):
        raise CampaignGuardianError("guardian private bootstrap path binding is invalid")
    return plan, evidence_root


def _assert_permit_matches_plan(
    permit: AssistedCampaignPermitV3, plan: CampaignGuardianLaunchPlan
) -> None:
    payload = permit.to_payload()
    campaign = payload["campaign"]
    source = payload["source"]
    profiles = payload["interpreter_profiles"]
    if (
        not isinstance(campaign, dict)
        or not isinstance(source, dict)
        or not isinstance(profiles, dict)
    ):
        raise CampaignGuardianPermitValidationError("campaign permit sections drifted")
    identity = plan.campaign_identity.to_payload()
    if (
        campaign["campaign_id"] != identity["campaign_id"]
        or campaign["attempt_id"] != identity["attempt_id"]
        or campaign["candidate"] != identity["candidate"]
        or payload["request_sha256"] != identity["request_sha256"]
        or payload["manifest_sha256"] != identity["manifest_sha256"]
        or canonical_sha256(payload["resources"]) != identity["resources_sha256"]
        or source["full_assisted_campaign_source_sha256"] != identity["full_source_sha256"]
        or profiles["a1"]["stable_identity_sha256"] != identity["mlff_profile_sha256"]
        or profiles["direct_and_a2"]["stable_identity_sha256"]
        != identity["gpupyscf_profile_sha256"]
    ):
        raise CampaignGuardianPermitValidationError(
            "campaign permit differs from the frozen guardian plan"
        )


def _validate_authorizing_permit(
    raw: bytes, *, plan: CampaignGuardianLaunchPlan
) -> AssistedCampaignPermitV3:
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
    _assert_permit_matches_plan(permit, plan)
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
        validate=lambda raw: _validate_authorizing_permit(raw, plan=plan),
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


def main(argv: list[str] | None = None) -> int:
    """Strict external entry: one private bootstrap path, no stage/interpreter flags."""

    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--private-bootstrap-path", required=True)
    arguments = parser.parse_args(argv)
    plan, evidence_root = _read_private_bootstrap(
        Path(arguments.private_bootstrap_path).resolve(strict=False)
    )
    spawned, receipt = launch_assisted_campaign_guardian(
        plan,
        store=CampaignEvidenceStore(evidence_root),
    )
    print(
        canonical_json_bytes(
            {
                "campaign_id": plan.campaign_id,
                "attempt_id": plan.attempt_id,
                "supervisor_pid": spawned.pid,
                "guardian_launch_receipt_sha256": receipt.sha256(),
            }
        ).decode("ascii"),
        end="",
    )
    return 0


__all__ = [
    "CAMPAIGN_GUARDIAN_SCHEMA_VERSION",
    "CampaignGuardianError",
    "CampaignGuardianLaunchPlan",
    "CampaignGuardianNotAuthorizedError",
    "CampaignGuardianPermitConsumedError",
    "CampaignGuardianPermitValidationError",
    "SpawnedCampaignSupervisor",
    "_assert_permit_matches_plan",
    "launch_assisted_campaign_guardian",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - production entry remains gate closed
    raise SystemExit(main())
