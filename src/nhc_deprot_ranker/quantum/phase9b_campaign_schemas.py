"""Strict, portable schemas for the Phase 9B split-process campaign.

This module is deliberately standard-library-only.  Records are immutable,
reject unknown or duplicate fields, serialize canonically, and never accept a
v8 shape as v9.  Runtime-private interpreter bindings live in the companion
profile module and never enter these public payloads.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import ClassVar, Final, Self, cast

SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_RECORD_BYTES: Final = 256 * 1024


class CampaignSchemaError(ValueError):
    """A campaign schema is malformed, noncanonical, or mixed-generation."""


class AttemptLifecycleState(StrEnum):
    PLANNED = "PLANNED"
    PERMIT_VALIDATED = "PERMIT_VALIDATED"
    PERMIT_CONSUMED = "PERMIT_CONSUMED"
    GUARDIAN_SPAWN_ATTEMPTED = "GUARDIAN_SPAWN_ATTEMPTED"
    CAMPAIGN_SUPERVISOR_SPAWNED = "CAMPAIGN_SUPERVISOR_SPAWNED"
    CAMPAIGN_ACKNOWLEDGED = "CAMPAIGN_ACKNOWLEDGED"
    A1_RUNNING = "A1_RUNNING"
    A1_TERMINAL = "A1_TERMINAL"
    HANDOFF_TERMINAL = "HANDOFF_TERMINAL"
    A2_RUNNING = "A2_RUNNING"
    A2_TERMINAL = "A2_TERMINAL"
    ROUTE_TERMINAL = "ROUTE_TERMINAL"


class GuardianLaunchState(StrEnum):
    NOT_STARTED = "not_started"
    PERMIT_VALIDATED = "permit_validated"
    PERMIT_CONSUMED = "permit_consumed"
    SUPERVISOR_SPAWNED = "supervisor_spawned"
    SUPERVISOR_SPAWN_FAILED = "supervisor_spawn_failed"
    ACKNOWLEDGED = "acknowledged"
    ACK_FAILED = "ack_failed"
    INDETERMINATE = "indeterminate"


class CampaignRuntimeState(StrEnum):
    CAPABILITY_VALIDATED = "campaign_capability_validated"
    ACKNOWLEDGED = "campaign_acknowledged"
    A1_REGISTRATION_WAITING = "a1_registration_waiting"
    A1_RUNNING = "a1_running"
    A1_ACCEPTED = "a1_terminal_accepted"
    A1_REJECTED = "a1_terminal_rejected"
    HANDOFF_VERIFYING = "handoff_verifying"
    HANDOFF_ACCEPTED = "handoff_accepted"
    HANDOFF_REJECTED = "handoff_rejected"
    A2_REGISTRATION_WAITING = "a2_registration_waiting"
    A2_RUNNING = "a2_running"
    A2_ACCEPTED = "a2_terminal_accepted"
    A2_REJECTED = "a2_terminal_rejected"
    ROUTE_ACCEPTED = "route_accepted"
    ROUTE_REJECTED = "route_rejected"
    INDETERMINATE = "indeterminate"


class StageName(StrEnum):
    A1 = "aimnet2_preoptimization"
    A2 = "pyscf_residual_optimization"


class RouteOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INDETERMINATE = "indeterminate"
    NO_LABEL = "no_label"


def require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise CampaignSchemaError(f"{label} must be a lowercase SHA256")
    return value


def require_id(value: object, label: str) -> str:
    if not isinstance(value, str) or SAFE_ID_RE.fullmatch(value) is None:
        raise CampaignSchemaError(f"{label} must be a bounded safe identifier")
    return value


def require_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CampaignSchemaError(f"{label} must be an integer >= {minimum}")
    return value


def _reject_nonfinite(value: str) -> object:
    raise CampaignSchemaError(f"non-finite JSON number is forbidden: {value}")


def strict_json_object(
    raw: bytes, *, label: str, max_bytes: int = MAX_RECORD_BYTES
) -> dict[str, object]:
    if not raw or len(raw) > max_bytes:
        raise CampaignSchemaError(f"{label} byte size is invalid")

    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise CampaignSchemaError(f"{label} contains duplicate key: {key}")
            result[key] = value
        return result

    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs_hook,
            parse_constant=_reject_nonfinite,
        )
    except CampaignSchemaError:
        raise
    except (UnicodeDecodeError, ValueError) as exc:
        raise CampaignSchemaError(f"{label} must be strict UTF-8 JSON") from exc
    if not isinstance(parsed, dict):
        raise CampaignSchemaError(f"{label} must be one JSON object")
    return cast(dict[str, object], parsed)


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float) and not math.isfinite(value):
        raise CampaignSchemaError("non-finite values are forbidden")
    return value


def canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(_plain(payload), sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def require_exact_keys(payload: Mapping[str, object], keys: frozenset[str], label: str) -> None:
    actual = set(payload)
    if actual != set(keys):
        raise CampaignSchemaError(
            f"{label} fields mismatch; missing={sorted(set(keys) - actual)}, "
            f"extra={sorted(actual - set(keys))}"
        )


@dataclass(frozen=True, slots=True)
class StrictCampaignRecord:
    """Base for named schema wrappers with exact top-level keys."""

    payload: Mapping[str, object]
    SCHEMA_VERSION: ClassVar[str] = ""
    REQUIRED_KEYS: ClassVar[frozenset[str]] = frozenset()

    def __post_init__(self) -> None:
        plain = _plain(self.payload)
        if not isinstance(plain, dict):
            raise CampaignSchemaError("record payload must be an object")
        require_exact_keys(plain, self.REQUIRED_KEYS, self.SCHEMA_VERSION)
        if plain.get("schema_version") != self.SCHEMA_VERSION:
            raise CampaignSchemaError(f"{self.SCHEMA_VERSION} schema_version drifted")
        self.validate_payload(plain)
        object.__setattr__(self, "payload", cast(Mapping[str, object], _freeze(plain)))

    def validate_payload(self, payload: Mapping[str, object]) -> None:
        del payload

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        payload = strict_json_object(raw, label=cls.SCHEMA_VERSION)
        record = cls(payload)
        if record.canonical_bytes() != raw:
            raise CampaignSchemaError(f"{cls.SCHEMA_VERSION} bytes are not canonical")
        return record

    def to_payload(self) -> dict[str, object]:
        plain = _plain(self.payload)
        assert isinstance(plain, dict)
        return plain

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload)

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class AttemptLifecycleEventV1(StrictCampaignRecord):
    SCHEMA_VERSION: ClassVar = "nhc-phase9b-attempt-lifecycle-event-v1"
    REQUIRED_KEYS: ClassVar = frozenset(
        {"schema_version", "campaign_id", "attempt_id", "state", "source_receipt_sha256"}
    )

    def validate_payload(self, payload: Mapping[str, object]) -> None:
        require_id(payload["campaign_id"], "campaign_id")
        require_id(payload["attempt_id"], "attempt_id")
        try:
            AttemptLifecycleState(cast(str, payload["state"]))
        except (TypeError, ValueError) as exc:
            raise CampaignSchemaError("invalid attempt lifecycle state") from exc
        require_sha256(payload["source_receipt_sha256"], "source_receipt_sha256")


@dataclass(frozen=True, slots=True)
class GuardianLaunchReceiptV2(StrictCampaignRecord):
    SCHEMA_VERSION: ClassVar = "nhc-phase9b-guardian-launch-receipt-v2"
    REQUIRED_KEYS: ClassVar = frozenset(
        {
            "schema_version",
            "campaign_id",
            "attempt_id",
            "state",
            "permit_sha256",
            "permit_consumption_sha256",
            "supervisor_registration_sha256",
            "acknowledgement_sha256",
            "failure",
        }
    )

    def validate_payload(self, payload: Mapping[str, object]) -> None:
        require_id(payload["campaign_id"], "campaign_id")
        require_id(payload["attempt_id"], "attempt_id")
        try:
            state = GuardianLaunchState(cast(str, payload["state"]))
        except (TypeError, ValueError) as exc:
            raise CampaignSchemaError("invalid guardian launch state") from exc
        require_sha256(payload["permit_sha256"], "permit_sha256")
        for field in (
            "permit_consumption_sha256",
            "supervisor_registration_sha256",
            "acknowledgement_sha256",
        ):
            value = payload[field]
            if value is not None:
                require_sha256(value, field)
        failure = payload["failure"]
        if state in {GuardianLaunchState.ACKNOWLEDGED, GuardianLaunchState.SUPERVISOR_SPAWNED}:
            if failure is not None:
                raise CampaignSchemaError("successful guardian state cannot carry failure")
        elif state not in {
            GuardianLaunchState.NOT_STARTED,
            GuardianLaunchState.PERMIT_VALIDATED,
            GuardianLaunchState.PERMIT_CONSUMED,
        } and not isinstance(failure, Mapping):
            raise CampaignSchemaError("failed guardian state requires structured failure")


@dataclass(frozen=True, slots=True)
class AssistedCampaignIdentityV1(StrictCampaignRecord):
    SCHEMA_VERSION: ClassVar = "nhc-phase9b-assisted-campaign-identity-v1"
    REQUIRED_KEYS: ClassVar = frozenset(
        {
            "schema_version",
            "campaign_id",
            "attempt_id",
            "candidate",
            "route",
            "request_sha256",
            "manifest_sha256",
            "resources_sha256",
            "full_source_sha256",
            "mlff_profile_sha256",
            "gpupyscf_profile_sha256",
        }
    )

    def validate_payload(self, payload: Mapping[str, object]) -> None:
        for field in ("campaign_id", "attempt_id", "candidate"):
            require_id(payload[field], field)
        if payload["route"] != "assisted":
            raise CampaignSchemaError("campaign identity route must be assisted")
        for field in self.REQUIRED_KEYS - {
            "schema_version",
            "campaign_id",
            "attempt_id",
            "candidate",
            "route",
        }:
            require_sha256(payload[field], field)


@dataclass(frozen=True, slots=True)
class AssistedCampaignPermitV3(StrictCampaignRecord):
    SCHEMA_VERSION: ClassVar = "nhc-phase9b-assisted-campaign-permit-v3"
    REQUIRED_KEYS: ClassVar = frozenset(
        {
            "schema_version",
            "authorization",
            "campaign",
            "inputs",
            "source",
            "interpreter_profiles",
            "resources",
            "schema_identities",
            "evidence",
            "request_sha256",
            "manifest_sha256",
        }
    )

    def validate_payload(self, payload: Mapping[str, object]) -> None:
        authorization = payload["authorization"]
        campaign = payload["campaign"]
        if not isinstance(authorization, Mapping) or not isinstance(campaign, Mapping):
            raise CampaignSchemaError("permit authorization/campaign must be objects")
        require_exact_keys(
            authorization,
            frozenset(
                {
                    "execution_authorized",
                    "permit_consumption_authorized",
                    "label_authorized",
                    "one_shot",
                    "retry_authorized",
                    "resume_authorized",
                    "fallback_authorized",
                }
            ),
            "permit.authorization",
        )
        if authorization["one_shot"] is not True:
            raise CampaignSchemaError("campaign permit must be one-shot")
        for flag in (
            "retry_authorized",
            "resume_authorized",
            "fallback_authorized",
        ):
            if authorization[flag] is not False:
                raise CampaignSchemaError(f"{flag} must be false")
        require_int(campaign.get("campaign_wall_limit_seconds"), "campaign wall", minimum=1)
        require_int(campaign.get("a1_local_limit_seconds"), "A1 local limit", minimum=1)
        require_int(campaign.get("termination_grace_seconds"), "termination grace")
        if "campaign_absolute_deadline_ns" in campaign:
            raise CampaignSchemaError("a permit cannot bind a runtime absolute deadline")
        if campaign.get("campaign_wall_limit_seconds") != 7200:
            raise CampaignSchemaError("campaign wall limit must be 7200 seconds")
        if campaign.get("a1_local_limit_seconds") != 900:
            raise CampaignSchemaError("A1 local limit must be 900 seconds")
        if campaign.get("termination_grace_seconds") != 10:
            raise CampaignSchemaError("termination grace must be 10 seconds")
        require_exact_keys(
            campaign,
            frozenset(
                {
                    "campaign_id",
                    "candidate",
                    "route",
                    "attempt_id",
                    "remote_root_identity_sha256",
                    "topology",
                    "endpoint_order",
                    "schedule",
                    "campaign_wall_limit_seconds",
                    "a1_local_limit_seconds",
                    "termination_grace_seconds",
                }
            ),
            "permit.campaign",
        )
        for field in ("campaign_id", "candidate", "attempt_id"):
            require_id(campaign[field], f"campaign.{field}")
        if (
            campaign["route"] != "assisted"
            or campaign["topology"] != "split_process_campaign"
            or campaign["endpoint_order"] != ["cation", "neutral"]
            or campaign["schedule"]
            != [
                "aimnet2_preoptimization",
                "handoff_verification",
                "pyscf_residual_optimization",
            ]
        ):
            raise CampaignSchemaError("campaign topology/schedule drifted")
        require_sha256(campaign["remote_root_identity_sha256"], "remote root identity")
        inputs = payload["inputs"]
        if not isinstance(inputs, Mapping):
            raise CampaignSchemaError("permit inputs must be an object")
        require_exact_keys(
            inputs,
            frozenset({"cation", "neutral", "electron_count", "atom_map_sha256"}),
            "permit.inputs",
        )
        if inputs["electron_count"] != 160:
            raise CampaignSchemaError("permit electron count drifted")
        require_sha256(inputs["atom_map_sha256"], "atom_map_sha256")
        for endpoint, charge, atom_count in (("cation", 1, 26), ("neutral", 0, 25)):
            endpoint_payload = inputs[endpoint]
            if not isinstance(endpoint_payload, Mapping):
                raise CampaignSchemaError(f"permit {endpoint} input must be an object")
            require_exact_keys(
                endpoint_payload,
                frozenset(
                    {
                        "xyz_sha256",
                        "xyz_byte_count",
                        "atom_count",
                        "element_order_sha256",
                        "charge",
                        "multiplicity",
                    }
                ),
                f"permit.inputs.{endpoint}",
            )
            if (
                endpoint_payload["charge"] != charge
                or endpoint_payload["multiplicity"] != 1
                or endpoint_payload["atom_count"] != atom_count
            ):
                raise CampaignSchemaError(f"permit {endpoint} state/atom count drifted")
            require_int(endpoint_payload["xyz_byte_count"], f"{endpoint} XYZ bytes", minimum=1)
            require_sha256(endpoint_payload["xyz_sha256"], f"{endpoint} XYZ SHA256")
            require_sha256(
                endpoint_payload["element_order_sha256"], f"{endpoint} element-order SHA256"
            )
        source = payload["source"]
        expected_source = {
            "campaign_control_source_sha256",
            "shared_pyscf_core_source_sha256",
            "shared_schema_source_sha256",
            "stage_a1_source_sha256",
            "stage_a2_source_sha256",
            "full_assisted_campaign_source_sha256",
            "closure_dependency_edges_sha256",
            "deployment_inventory_sha256",
        }
        if not isinstance(source, Mapping):
            raise CampaignSchemaError("permit source must be an object")
        require_exact_keys(source, frozenset(expected_source), "permit.source")
        for field in expected_source:
            require_sha256(source[field], field)
        profiles = payload["interpreter_profiles"]
        if not isinstance(profiles, Mapping) or set(profiles) != {"a1", "direct_and_a2"}:
            raise CampaignSchemaError("permit interpreter profile set drifted")
        for role, profile in profiles.items():
            if not isinstance(profile, Mapping):
                raise CampaignSchemaError(f"permit interpreter profile is invalid: {role}")
            required_profile = {
                "logical_profile_id",
                "python_version",
                "package_versions",
                "executable_content_sha256",
                "activation_script_sha256",
                "runtime_capabilities",
                "sanitized_environment_identity_sha256",
                "stable_identity_sha256",
            }
            require_exact_keys(profile, frozenset(required_profile), f"permit.profile.{role}")
            require_id(profile["logical_profile_id"], f"profile.{role}.id")
            if profile["python_version"] != "3.11.15":
                raise CampaignSchemaError("permit interpreter Python drifted")
            for field in required_profile & {
                "executable_content_sha256",
                "activation_script_sha256",
                "sanitized_environment_identity_sha256",
                "stable_identity_sha256",
            }:
                require_sha256(profile[field], f"profile.{role}.{field}")
            if not isinstance(profile["package_versions"], Mapping) or not isinstance(
                profile["runtime_capabilities"], list
            ):
                raise CampaignSchemaError("permit interpreter profile projection drifted")
        schema_identities = payload["schema_identities"]
        if not isinstance(schema_identities, Mapping) or set(schema_identities) != {
            "admission",
            "campaign_terminal",
            "handoff_proposal",
            "handoff_verification",
            "internal_stage_capability",
        }:
            raise CampaignSchemaError("permit schema identity set drifted")
        if any(not isinstance(value, str) or not value for value in schema_identities.values()):
            raise CampaignSchemaError("permit schema identity is invalid")
        evidence = payload["evidence"]
        if not isinstance(evidence, Mapping) or set(evidence) != {
            "evidence_schema_set_sha256",
            "evidence_tree_identity_sha256",
        }:
            raise CampaignSchemaError("permit evidence identity set drifted")
        for field, value in evidence.items():
            require_sha256(value, f"evidence.{field}")
        if not isinstance(payload["resources"], Mapping) or not payload["resources"]:
            raise CampaignSchemaError("permit resources must be a non-empty object")
        for field in ("request_sha256", "manifest_sha256"):
            require_sha256(payload[field], field)


@dataclass(frozen=True, slots=True)
class DirectRoutePermitV3(StrictCampaignRecord):
    """Direct member of the same v3 paired generation."""

    SCHEMA_VERSION: ClassVar = "nhc-phase9b-direct-route-permit-v3"
    REQUIRED_KEYS: ClassVar = frozenset(
        {
            "schema_version",
            "authorization",
            "identity",
            "inputs",
            "source",
            "interpreter_profile",
            "resources",
            "request_sha256",
            "manifest_sha256",
        }
    )

    def validate_payload(self, payload: Mapping[str, object]) -> None:
        authorization = payload["authorization"]
        identity = payload["identity"]
        if not isinstance(authorization, Mapping) or not isinstance(identity, Mapping):
            raise CampaignSchemaError("direct permit sections must be objects")
        if authorization.get("one_shot") is not True:
            raise CampaignSchemaError("direct permit must be one-shot")
        for flag in ("retry_authorized", "resume_authorized", "fallback_authorized"):
            if authorization.get(flag) is not False:
                raise CampaignSchemaError(f"direct permit {flag} must be false")
        if identity.get("route") != "direct" or identity.get("topology") != "single_stage_pyscf":
            raise CampaignSchemaError("direct permit topology drifted")
        for field in ("request_sha256", "manifest_sha256"):
            require_sha256(payload[field], field)


def render_non_authorizing_permit(record: AssistedCampaignPermitV3 | DirectRoutePermitV3) -> bytes:
    """Render documentation/test bytes only; refuses any real authority flags."""

    payload = record.to_payload()
    authorization = payload["authorization"]
    if not isinstance(authorization, dict):
        raise CampaignSchemaError("permit authorization must be an object")
    for field in ("execution_authorized", "permit_consumption_authorized", "label_authorized"):
        if authorization.get(field) is not False:
            raise CampaignSchemaError("Item 10 renderer cannot create real permit authority")
    return record.canonical_bytes()


@dataclass(frozen=True, slots=True)
class StageRegistrationReceiptV1(StrictCampaignRecord):
    SCHEMA_VERSION: ClassVar = "nhc-phase9b-stage-registration-v1"
    REQUIRED_KEYS: ClassVar = frozenset(
        {
            "schema_version",
            "campaign_id",
            "attempt_id",
            "stage",
            "process_identity",
            "interpreter_executable_sha256",
            "argv_sha256",
            "source_sha256",
            "registration_nonce_sha256",
        }
    )

    def validate_payload(self, payload: Mapping[str, object]) -> None:
        for field in ("campaign_id", "attempt_id"):
            require_id(payload[field], field)
        try:
            StageName(cast(str, payload["stage"]))
        except (TypeError, ValueError) as exc:
            raise CampaignSchemaError("invalid registration stage") from exc
        process = payload["process_identity"]
        if not isinstance(process, Mapping):
            raise CampaignSchemaError("process_identity must be an object")
        require_exact_keys(
            process,
            frozenset(
                {
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
            ),
            "registration.process_identity",
        )
        for field, value in process.items():
            require_int(value, f"process_identity.{field}", minimum=1)
        if process["expected_parent_pid"] != process["supervisor_pid"]:
            raise CampaignSchemaError("registered stage parent must be the supervisor")
        if process["stage_session_id"] != process["stage_pid"]:
            raise CampaignSchemaError("stage must lead its own session")
        if process["stage_process_group_id"] != process["stage_pid"]:
            raise CampaignSchemaError("stage must lead its own process group")
        for field in (
            "interpreter_executable_sha256",
            "argv_sha256",
            "source_sha256",
            "registration_nonce_sha256",
        ):
            require_sha256(payload[field], field)


@dataclass(frozen=True, slots=True)
class StageAcknowledgementReceiptV1(StrictCampaignRecord):
    SCHEMA_VERSION: ClassVar = "nhc-phase9b-stage-acknowledgement-v1"
    REQUIRED_KEYS: ClassVar = frozenset(
        {
            "schema_version",
            "campaign_id",
            "attempt_id",
            "stage",
            "registration_sha256",
            "capability_sha256",
            "release_token_sha256",
            "accepted",
        }
    )

    def validate_payload(self, payload: Mapping[str, object]) -> None:
        for field in ("campaign_id", "attempt_id"):
            require_id(payload[field], field)
        try:
            StageName(cast(str, payload["stage"]))
        except (TypeError, ValueError) as exc:
            raise CampaignSchemaError("invalid acknowledgement stage") from exc
        for field in ("registration_sha256", "capability_sha256", "release_token_sha256"):
            require_sha256(payload[field], field)
        if payload["accepted"] is not True:
            raise CampaignSchemaError("durable stage acknowledgement must be accepted")


@dataclass(frozen=True, slots=True)
class StageCapabilityConsumptionReceiptV1(StrictCampaignRecord):
    SCHEMA_VERSION: ClassVar = "nhc-phase9b-stage-capability-consumption-v1"
    REQUIRED_KEYS: ClassVar = frozenset(
        {
            "schema_version",
            "campaign_id",
            "attempt_id",
            "stage",
            "registration_sha256",
            "capability_sha256",
            "release_token_sha256",
            "consumer_process_identity_sha256",
            "consumed_once",
        }
    )

    def validate_payload(self, payload: Mapping[str, object]) -> None:
        for field in ("campaign_id", "attempt_id"):
            require_id(payload[field], field)
        try:
            StageName(cast(str, payload["stage"]))
        except (TypeError, ValueError) as exc:
            raise CampaignSchemaError("invalid capability-consumption stage") from exc
        for field in (
            "registration_sha256",
            "capability_sha256",
            "release_token_sha256",
            "consumer_process_identity_sha256",
        ):
            require_sha256(payload[field], field)
        if payload["consumed_once"] is not True:
            raise CampaignSchemaError("stage capability must be consumed once")


class _TerminalRecord(StrictCampaignRecord):
    TERMINAL_STATES: ClassVar[frozenset[str]] = frozenset()

    def validate_payload(self, payload: Mapping[str, object]) -> None:
        for field in ("campaign_id", "attempt_id"):
            require_id(payload[field], field)
        state = payload["terminal_state"]
        if not isinstance(state, str) or state not in self.TERMINAL_STATES:
            raise CampaignSchemaError("unknown terminal_state")
        evidence = payload["evidence_sha256"]
        if evidence is not None:
            require_sha256(evidence, "evidence_sha256")
        failure = payload["failure"]
        if state == "accepted" and failure is not None:
            raise CampaignSchemaError("accepted terminal cannot carry failure")
        if state != "accepted" and not isinstance(failure, Mapping):
            raise CampaignSchemaError("non-accepted terminal requires structured failure")


@dataclass(frozen=True, slots=True)
class StageA1TerminalReceiptV1(_TerminalRecord):
    SCHEMA_VERSION: ClassVar = "nhc-phase9b-stage-a1-terminal-v1"
    REQUIRED_KEYS: ClassVar = frozenset(
        {
            "schema_version",
            "campaign_id",
            "attempt_id",
            "terminal_state",
            "evidence_sha256",
            "failure",
        }
    )
    TERMINAL_STATES: ClassVar = frozenset(
        {
            "accepted",
            "rejected_cation",
            "rejected_neutral",
            "timeout",
            "process_failed",
            "evidence_failed",
            "indeterminate",
        }
    )


@dataclass(frozen=True, slots=True)
class StageA2TerminalReceiptV1(_TerminalRecord):
    SCHEMA_VERSION: ClassVar = "nhc-phase9b-stage-a2-terminal-v1"
    REQUIRED_KEYS: ClassVar = StageA1TerminalReceiptV1.REQUIRED_KEYS
    TERMINAL_STATES: ClassVar = frozenset(
        {
            "accepted",
            "rejected_cation",
            "rejected_neutral",
            "d3_failed",
            "timeout",
            "process_failed",
            "evidence_failed",
            "indeterminate",
        }
    )


@dataclass(frozen=True, slots=True)
class AssistedCampaignTerminalReceiptV1(StrictCampaignRecord):
    SCHEMA_VERSION: ClassVar = "nhc-phase9b-assisted-campaign-terminal-v1"
    REQUIRED_KEYS: ClassVar = frozenset(
        {
            "schema_version",
            "campaign_id",
            "attempt_id",
            "candidate",
            "route",
            "guardian_launch_state",
            "campaign_runtime_state",
            "route_outcome",
            "schedule_sha256",
            "evidence_manifest_sha256",
            "a1_terminal_sha256",
            "handoff_verification_sha256",
            "a2_admission_sha256",
            "a2_terminal_sha256",
            "label",
            "failure",
        }
    )

    def validate_payload(self, payload: Mapping[str, object]) -> None:
        for field in ("campaign_id", "attempt_id", "candidate"):
            require_id(payload[field], field)
        if payload["route"] != "assisted":
            raise CampaignSchemaError("campaign terminal route must be assisted")
        try:
            GuardianLaunchState(cast(str, payload["guardian_launch_state"]))
            CampaignRuntimeState(cast(str, payload["campaign_runtime_state"]))
            outcome = RouteOutcome(cast(str, payload["route_outcome"]))
        except (TypeError, ValueError) as exc:
            raise CampaignSchemaError("campaign terminal enum is invalid") from exc
        require_sha256(payload["schedule_sha256"], "schedule_sha256")
        require_sha256(payload["evidence_manifest_sha256"], "evidence_manifest_sha256")
        for field in (
            "a1_terminal_sha256",
            "handoff_verification_sha256",
            "a2_admission_sha256",
            "a2_terminal_sha256",
        ):
            if payload[field] is not None:
                require_sha256(payload[field], field)
        if outcome is RouteOutcome.ACCEPTED:
            if payload["failure"] is not None or not isinstance(payload["label"], Mapping):
                raise CampaignSchemaError("accepted route requires label and null failure")
        else:
            if payload["label"] is not None or not isinstance(payload["failure"], Mapping):
                raise CampaignSchemaError("non-accepted route requires null label and failure")


@dataclass(frozen=True, slots=True)
class CampaignEvidenceManifestV1(StrictCampaignRecord):
    SCHEMA_VERSION: ClassVar = "nhc-phase9b-campaign-evidence-manifest-v1"
    REQUIRED_KEYS: ClassVar = frozenset(
        {"schema_version", "campaign_id", "attempt_id", "terminal_classification", "files"}
    )

    def validate_payload(self, payload: Mapping[str, object]) -> None:
        for field in ("campaign_id", "attempt_id", "terminal_classification"):
            require_id(payload[field], field)
        files = payload["files"]
        if not isinstance(files, Mapping):
            raise CampaignSchemaError("evidence manifest files must be an object")
        for path, identity in files.items():
            if not isinstance(path, str) or path.startswith("/") or ".." in path.split("/"):
                raise CampaignSchemaError("evidence manifest path is unsafe")
            if not isinstance(identity, Mapping):
                raise CampaignSchemaError("evidence file identity must be an object")
            require_exact_keys(identity, frozenset({"sha256", "byte_count", "mode"}), path)
            require_sha256(identity["sha256"], f"{path}.sha256")
            require_int(identity["byte_count"], f"{path}.byte_count")
            if identity["mode"] not in {"0400", "0600"}:
                raise CampaignSchemaError("evidence mode must be 0400 or 0600")


@dataclass(frozen=True, slots=True)
class DirectAssistedPySCFParityContractV1(StrictCampaignRecord):
    SCHEMA_VERSION: ClassVar = "nhc-phase9b-direct-assisted-pyscf-parity-v1"
    REQUIRED_KEYS: ClassVar = frozenset(
        {
            "schema_version",
            "shared_core_sha256",
            "equal_fields",
            "only_allowed_difference",
            "aimnet2_values_enter_label",
        }
    )

    def validate_payload(self, payload: Mapping[str, object]) -> None:
        require_sha256(payload["shared_core_sha256"], "shared_core_sha256")
        equal = payload["equal_fields"]
        if not isinstance(equal, Sequence) or isinstance(equal, str) or not equal:
            raise CampaignSchemaError("parity equal_fields must be a non-empty list")
        if payload["only_allowed_difference"] != "input_geometry_provenance":
            raise CampaignSchemaError("the sole parity difference is input provenance")
        if payload["aimnet2_values_enter_label"] is not False:
            raise CampaignSchemaError("AIMNet2 values must not enter the label")


@dataclass(frozen=True, slots=True)
class CampaignResourcesV2(StrictCampaignRecord):
    SCHEMA_VERSION: ClassVar = "nhc-phase9b-campaign-resources-v2"
    REQUIRED_KEYS: ClassVar = frozenset(
        {"schema_version", "campaign", "stage_a1", "handoff", "stage_a2"}
    )

    def validate_payload(self, payload: Mapping[str, object]) -> None:
        campaign = payload["campaign"]
        a1 = payload["stage_a1"]
        a2 = payload["stage_a2"]
        if not all(isinstance(item, Mapping) for item in (campaign, a1, payload["handoff"], a2)):
            raise CampaignSchemaError("campaign resource sections must be objects")
        assert isinstance(campaign, Mapping) and isinstance(a1, Mapping) and isinstance(a2, Mapping)
        if campaign.get("wall_limit_seconds") != 7200:
            raise CampaignSchemaError("campaign wall limit must be 7200")
        if a1.get("local_limit_seconds") != 900 or a1.get("gpu_count") != 1:
            raise CampaignSchemaError("A1 budget drifted")
        if a2.get("new_wall_limit_seconds") is not None:
            raise CampaignSchemaError("A2 may not receive a fresh wall limit")
        if a2.get("computational_threads") != 4 or a2.get("max_memory_mb") != 12000:
            raise CampaignSchemaError("A2 PySCF envelope drifted")


@dataclass(frozen=True, slots=True)
class CampaignScheduleV1(StrictCampaignRecord):
    SCHEMA_VERSION: ClassVar = "nhc-phase9b-campaign-schedule-v1"
    REQUIRED_KEYS: ClassVar = frozenset(
        {
            "schema_version",
            "campaign_monotonic_start_ns",
            "campaign_absolute_deadline_ns",
            "a1_deadline_ns",
            "clock_type",
            "linux_boot_id_sha256",
            "host_execution_identity_sha256",
            "supervisor_process_start_identity_sha256",
            "monotonic_resolution_ns",
            "clock_domain_digest",
            "derived_deadline_calculation_digest",
        }
    )

    def validate_payload(self, payload: Mapping[str, object]) -> None:
        start = require_int(payload["campaign_monotonic_start_ns"], "campaign start", minimum=1)
        end = require_int(payload["campaign_absolute_deadline_ns"], "campaign deadline", minimum=1)
        a1 = require_int(payload["a1_deadline_ns"], "A1 deadline", minimum=1)
        if end - start != 7_200_000_000_000:
            raise CampaignSchemaError("campaign deadline must derive from the 7200-second limit")
        if a1 != min(end, start + 900_000_000_000):
            raise CampaignSchemaError("A1 deadline derivation drifted")
        if payload["clock_type"] != "CLOCK_MONOTONIC":
            raise CampaignSchemaError("campaign clock must be CLOCK_MONOTONIC")
        require_int(payload["monotonic_resolution_ns"], "monotonic resolution", minimum=1)
        for field in self.REQUIRED_KEYS - {
            "schema_version",
            "campaign_monotonic_start_ns",
            "campaign_absolute_deadline_ns",
            "a1_deadline_ns",
            "clock_type",
            "monotonic_resolution_ns",
        }:
            require_sha256(payload[field], field)


__all__ = [
    "MAX_RECORD_BYTES",
    "AssistedCampaignIdentityV1",
    "AssistedCampaignPermitV3",
    "AssistedCampaignTerminalReceiptV1",
    "AttemptLifecycleEventV1",
    "AttemptLifecycleState",
    "CampaignEvidenceManifestV1",
    "CampaignResourcesV2",
    "CampaignRuntimeState",
    "CampaignScheduleV1",
    "CampaignSchemaError",
    "DirectAssistedPySCFParityContractV1",
    "DirectRoutePermitV3",
    "GuardianLaunchReceiptV2",
    "GuardianLaunchState",
    "RouteOutcome",
    "StageA1TerminalReceiptV1",
    "StageA2TerminalReceiptV1",
    "StageAcknowledgementReceiptV1",
    "StageCapabilityConsumptionReceiptV1",
    "StageName",
    "StageRegistrationReceiptV1",
    "StrictCampaignRecord",
    "canonical_json_bytes",
    "canonical_sha256",
    "render_non_authorizing_permit",
    "require_exact_keys",
    "require_id",
    "require_int",
    "require_sha256",
    "strict_json_object",
]
