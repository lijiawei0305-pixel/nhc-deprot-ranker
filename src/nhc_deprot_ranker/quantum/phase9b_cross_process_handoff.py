"""Three immutable receipts close the A1-to-A2 durable XYZ handoff."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Final, Literal, cast

from nhc_deprot_ranker.quantum.phase9b_campaign_evidence import (
    CampaignEvidenceStore,
)
from nhc_deprot_ranker.quantum.phase9b_campaign_schemas import (
    canonical_json_bytes,
    require_id,
    require_int,
    require_sha256,
    strict_json_object,
)

A1_HANDOFF_PROPOSAL_SCHEMA_VERSION: Final = "nhc-phase9b-a1-handoff-proposal-v1"
SUPERVISOR_HANDOFF_VERIFICATION_SCHEMA_VERSION: Final = (
    "nhc-phase9b-supervisor-handoff-verification-v1"
)
STAGE_A2_ADMISSION_SCHEMA_VERSION: Final = "nhc-phase9b-stage-a2-admission-v1"
MAX_XYZ_BYTES: Final = 2 * 1024 * 1024
ENDPOINTS: Final = ("cation", "neutral")


class CrossProcessHandoffError(RuntimeError):
    """The immutable handoff chain is incomplete or does not match disk bytes."""


def _receipt_digest(payload_without_digest: dict[str, object]) -> str:
    if "receipt_sha256" in payload_without_digest:
        raise CrossProcessHandoffError("receipt digest payload must exclude receipt_sha256")
    return hashlib.sha256(canonical_json_bytes(payload_without_digest)).hexdigest()


def _with_receipt_digest(payload: dict[str, object]) -> dict[str, object]:
    result = dict(payload)
    result["receipt_sha256"] = _receipt_digest(payload)
    return result


def _verify_receipt_digest(payload: dict[str, object]) -> str:
    digest = require_sha256(payload.get("receipt_sha256"), "receipt_sha256")
    unsigned = dict(payload)
    del unsigned["receipt_sha256"]
    if _receipt_digest(unsigned) != digest:
        raise CrossProcessHandoffError("receipt canonical digest mismatch")
    return digest


def _strict_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CrossProcessHandoffError(f"{label} must be an integer")
    return value


def _strict_float(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CrossProcessHandoffError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise CrossProcessHandoffError(f"{label} must be finite")
    return result


def parse_xyz_elements(raw: bytes) -> tuple[str, ...]:
    """Parse only atom count/order; never reserialize or interpret coordinates."""

    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise CrossProcessHandoffError("XYZ must be strict UTF-8") from exc
    if len(lines) < 3 or "\x00" in raw.decode("utf-8"):
        raise CrossProcessHandoffError("XYZ is structurally invalid")
    try:
        count = int(lines[0].strip())
    except ValueError as exc:
        raise CrossProcessHandoffError("XYZ atom count is invalid") from exc
    if count <= 0 or count > 1000 or len(lines) != count + 2:
        raise CrossProcessHandoffError("XYZ line count differs from atom count")
    elements: list[str] = []
    for line in lines[2:]:
        fields = line.split()
        if len(fields) != 4 or not fields[0] or len(fields[0]) > 2:
            raise CrossProcessHandoffError("XYZ atom line is invalid")
        try:
            coordinates = tuple(float(value) for value in fields[1:])
        except ValueError as exc:
            raise CrossProcessHandoffError("XYZ coordinate is invalid") from exc
        if not all(math.isfinite(value) for value in coordinates):
            raise CrossProcessHandoffError("XYZ coordinate is non-finite")
        elements.append(fields[0])
    return tuple(elements)


def element_order_sha256(elements: tuple[str, ...]) -> str:
    return hashlib.sha256(canonical_json_bytes(list(elements))).hexdigest()


@dataclass(frozen=True, slots=True)
class EndpointHandoffProposalV1:
    endpoint: Literal["cation", "neutral"]
    charge: int
    multiplicity: int
    atom_count: int
    ordered_elements: tuple[str, ...]
    element_order_sha256: str
    a1_input_xyz_sha256: str
    a1_output_xyz_sha256: str
    a1_output_xyz_byte_count: int
    trajectory_sha256: str
    preoptimization_receipt_sha256: str
    structural_gates_passed: bool
    final_max_force_ev_per_angstrom: float
    optimizer_step_count: int
    calculator_invocation_count: int

    def __post_init__(self) -> None:
        expected_charge = 1 if self.endpoint == "cation" else 0
        if (
            self.endpoint not in ENDPOINTS
            or self.charge != expected_charge
            or self.multiplicity != 1
        ):
            raise CrossProcessHandoffError("endpoint charge/multiplicity drifted")
        if self.atom_count != len(self.ordered_elements) or self.atom_count <= 0:
            raise CrossProcessHandoffError("endpoint atom count/order drifted")
        if element_order_sha256(self.ordered_elements) != self.element_order_sha256:
            raise CrossProcessHandoffError("endpoint element-order digest drifted")
        for label, value in (
            ("element_order_sha256", self.element_order_sha256),
            ("a1_input_xyz_sha256", self.a1_input_xyz_sha256),
            ("a1_output_xyz_sha256", self.a1_output_xyz_sha256),
            ("trajectory_sha256", self.trajectory_sha256),
            ("preoptimization_receipt_sha256", self.preoptimization_receipt_sha256),
        ):
            require_sha256(value, label)
        require_int(self.a1_output_xyz_byte_count, "output XYZ byte count", minimum=1)
        require_int(self.optimizer_step_count, "optimizer step count")
        require_int(self.calculator_invocation_count, "calculator invocation count")
        if not self.structural_gates_passed:
            raise CrossProcessHandoffError("proposal may contain only structurally accepted output")
        if (
            not math.isfinite(self.final_max_force_ev_per_angstrom)
            or self.final_max_force_ev_per_angstrom < 0
        ):
            raise CrossProcessHandoffError("final max force must be finite and non-negative")

    def to_payload(self) -> dict[str, object]:
        return {
            "endpoint": self.endpoint,
            "charge": self.charge,
            "multiplicity": self.multiplicity,
            "atom_count": self.atom_count,
            "ordered_elements": list(self.ordered_elements),
            "element_order_sha256": self.element_order_sha256,
            "a1_input_xyz_sha256": self.a1_input_xyz_sha256,
            "a1_output_xyz_sha256": self.a1_output_xyz_sha256,
            "a1_output_xyz_byte_count": self.a1_output_xyz_byte_count,
            "trajectory_sha256": self.trajectory_sha256,
            "preoptimization_receipt_sha256": self.preoptimization_receipt_sha256,
            "structural_gates_passed": self.structural_gates_passed,
            "final_max_force_ev_per_angstrom": self.final_max_force_ev_per_angstrom,
            "optimizer_step_count": self.optimizer_step_count,
            "calculator_invocation_count": self.calculator_invocation_count,
        }

    @classmethod
    def from_payload(cls, payload: object) -> EndpointHandoffProposalV1:
        if not isinstance(payload, dict):
            raise CrossProcessHandoffError("endpoint proposal must be an object")
        keys = {
            "endpoint",
            "charge",
            "multiplicity",
            "atom_count",
            "ordered_elements",
            "element_order_sha256",
            "a1_input_xyz_sha256",
            "a1_output_xyz_sha256",
            "a1_output_xyz_byte_count",
            "trajectory_sha256",
            "preoptimization_receipt_sha256",
            "structural_gates_passed",
            "final_max_force_ev_per_angstrom",
            "optimizer_step_count",
            "calculator_invocation_count",
        }
        if set(payload) != keys or not isinstance(payload["ordered_elements"], list):
            raise CrossProcessHandoffError("endpoint proposal fields drifted")
        values = cast(dict[str, object], payload)
        try:
            return cls(
                endpoint=values["endpoint"],  # type: ignore[arg-type]
                charge=_strict_int(values["charge"], "charge"),
                multiplicity=_strict_int(values["multiplicity"], "multiplicity"),
                atom_count=_strict_int(values["atom_count"], "atom_count"),
                ordered_elements=tuple(
                    str(item) for item in cast(list[object], values["ordered_elements"])
                ),
                element_order_sha256=str(values["element_order_sha256"]),
                a1_input_xyz_sha256=str(values["a1_input_xyz_sha256"]),
                a1_output_xyz_sha256=str(values["a1_output_xyz_sha256"]),
                a1_output_xyz_byte_count=_strict_int(
                    values["a1_output_xyz_byte_count"], "output byte count"
                ),
                trajectory_sha256=str(values["trajectory_sha256"]),
                preoptimization_receipt_sha256=str(values["preoptimization_receipt_sha256"]),
                structural_gates_passed=values["structural_gates_passed"] is True,
                final_max_force_ev_per_angstrom=_strict_float(
                    values["final_max_force_ev_per_angstrom"], "final max force"
                ),
                optimizer_step_count=_strict_int(
                    values["optimizer_step_count"], "optimizer step count"
                ),
                calculator_invocation_count=_strict_int(
                    values["calculator_invocation_count"], "calculator invocation count"
                ),
            )
        except (TypeError, ValueError) as exc:
            raise CrossProcessHandoffError("endpoint proposal value type drifted") from exc


@dataclass(frozen=True, slots=True)
class A1HandoffProposalReceiptV1:
    campaign_id: str
    candidate: str
    route: Literal["assisted"]
    attempt_id: str
    cation: EndpointHandoffProposalV1
    neutral: EndpointHandoffProposalV1
    stage_a1_source_sha256: str
    mlff_interpreter_profile_sha256: str
    weight_sha256: str
    optimizer_protocol_sha256: str
    no_pyscf_assertion: bool = True

    def __post_init__(self) -> None:
        for field, value in (
            ("campaign_id", self.campaign_id),
            ("candidate", self.candidate),
            ("attempt_id", self.attempt_id),
        ):
            require_id(value, field)
        if (
            self.route != "assisted"
            or self.cation.endpoint != "cation"
            or self.neutral.endpoint != "neutral"
        ):
            raise CrossProcessHandoffError("proposal route/endpoint order drifted")
        if not self.no_pyscf_assertion:
            raise CrossProcessHandoffError("A1 proposal must assert that PySCF did not run")
        for field, value in (
            ("stage_a1_source_sha256", self.stage_a1_source_sha256),
            ("mlff_interpreter_profile_sha256", self.mlff_interpreter_profile_sha256),
            ("weight_sha256", self.weight_sha256),
            ("optimizer_protocol_sha256", self.optimizer_protocol_sha256),
        ):
            require_sha256(value, field)

    def unsigned_payload(self) -> dict[str, object]:
        return {
            "schema_version": A1_HANDOFF_PROPOSAL_SCHEMA_VERSION,
            "campaign_id": self.campaign_id,
            "candidate": self.candidate,
            "route": self.route,
            "attempt_id": self.attempt_id,
            "endpoints": {"cation": self.cation.to_payload(), "neutral": self.neutral.to_payload()},
            "stage_a1_source_sha256": self.stage_a1_source_sha256,
            "mlff_interpreter_profile_sha256": self.mlff_interpreter_profile_sha256,
            "weight_sha256": self.weight_sha256,
            "optimizer_protocol_sha256": self.optimizer_protocol_sha256,
            "no_pyscf_assertion": self.no_pyscf_assertion,
            "immutable": True,
        }

    def to_payload(self) -> dict[str, object]:
        return _with_receipt_digest(self.unsigned_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_payload())

    def sha256(self) -> str:
        return cast(str, self.to_payload()["receipt_sha256"])

    @classmethod
    def from_bytes(cls, raw: bytes) -> A1HandoffProposalReceiptV1:
        payload = strict_json_object(raw, label="A1 handoff proposal")
        required = {
            "schema_version",
            "campaign_id",
            "candidate",
            "route",
            "attempt_id",
            "endpoints",
            "stage_a1_source_sha256",
            "mlff_interpreter_profile_sha256",
            "weight_sha256",
            "optimizer_protocol_sha256",
            "no_pyscf_assertion",
            "immutable",
            "receipt_sha256",
        }
        if (
            set(payload) != required
            or payload["schema_version"] != A1_HANDOFF_PROPOSAL_SCHEMA_VERSION
        ):
            raise CrossProcessHandoffError("A1 proposal schema/fields drifted")
        _verify_receipt_digest(payload)
        endpoints = payload["endpoints"]
        if not isinstance(endpoints, dict) or set(endpoints) != set(ENDPOINTS):
            raise CrossProcessHandoffError("A1 proposal endpoints drifted")
        receipt = cls(
            campaign_id=str(payload["campaign_id"]),
            candidate=str(payload["candidate"]),
            route=payload["route"],  # type: ignore[arg-type]
            attempt_id=str(payload["attempt_id"]),
            cation=EndpointHandoffProposalV1.from_payload(endpoints["cation"]),
            neutral=EndpointHandoffProposalV1.from_payload(endpoints["neutral"]),
            stage_a1_source_sha256=str(payload["stage_a1_source_sha256"]),
            mlff_interpreter_profile_sha256=str(payload["mlff_interpreter_profile_sha256"]),
            weight_sha256=str(payload["weight_sha256"]),
            optimizer_protocol_sha256=str(payload["optimizer_protocol_sha256"]),
            no_pyscf_assertion=payload["no_pyscf_assertion"] is True,
        )
        if payload["immutable"] is not True or receipt.canonical_bytes() != raw:
            raise CrossProcessHandoffError("A1 proposal is not immutable canonical bytes")
        return receipt


@dataclass(frozen=True, slots=True)
class FileObservationV1:
    sha256: str
    byte_count: int
    mode: str
    no_follow: bool
    regular_single_link: bool
    size_cap_accepted: bool

    def __post_init__(self) -> None:
        require_sha256(self.sha256, "file observation sha256")
        require_int(self.byte_count, "file observation byte_count", minimum=1)
        if self.mode not in {"0400", "0600"}:
            raise CrossProcessHandoffError("handoff file mode is invalid")
        if not (self.no_follow and self.regular_single_link and self.size_cap_accepted):
            raise CrossProcessHandoffError("handoff file safety check failed")

    def to_payload(self) -> dict[str, object]:
        return {
            "sha256": self.sha256,
            "byte_count": self.byte_count,
            "mode": self.mode,
            "no_follow": self.no_follow,
            "regular_single_link": self.regular_single_link,
            "size_cap_accepted": self.size_cap_accepted,
        }


@dataclass(frozen=True, slots=True)
class SupervisorHandoffVerificationReceiptV1:
    proposal_receipt_sha256: str
    supervisor_verifier_source_sha256: str
    a1_process_tree_absence_sha256: str
    file_observations: tuple[tuple[str, FileObservationV1], ...]
    exact_file_set_accepted: bool
    proposal_matches_disk: bool
    atom_order_equal: bool
    charge_multiplicity_equal: bool
    candidate_attempt_equal: bool
    structural_gates_accepted: bool
    verification_outcome: Literal["accepted", "rejected"]

    def __post_init__(self) -> None:
        for field, value in (
            ("proposal_receipt_sha256", self.proposal_receipt_sha256),
            ("supervisor_verifier_source_sha256", self.supervisor_verifier_source_sha256),
            ("a1_process_tree_absence_sha256", self.a1_process_tree_absence_sha256),
        ):
            require_sha256(value, field)
        names = tuple(name for name, _ in self.file_observations)
        if tuple(sorted(names)) != names or len(set(names)) != len(names):
            raise CrossProcessHandoffError("handoff file observations must be unique and sorted")
        accepted = all(
            (
                self.exact_file_set_accepted,
                self.proposal_matches_disk,
                self.atom_order_equal,
                self.charge_multiplicity_equal,
                self.candidate_attempt_equal,
                self.structural_gates_accepted,
            )
        )
        if (self.verification_outcome == "accepted") != accepted:
            raise CrossProcessHandoffError("verification outcome differs from checks")

    def unsigned_payload(self) -> dict[str, object]:
        return {
            "schema_version": SUPERVISOR_HANDOFF_VERIFICATION_SCHEMA_VERSION,
            "proposal_receipt_sha256": self.proposal_receipt_sha256,
            "supervisor_verifier_source_sha256": self.supervisor_verifier_source_sha256,
            "a1_process_tree_absence_sha256": self.a1_process_tree_absence_sha256,
            "exact_file_set_accepted": self.exact_file_set_accepted,
            "file_observations": {
                name: observation.to_payload() for name, observation in self.file_observations
            },
            "identity_checks": {
                "proposal_matches_disk": self.proposal_matches_disk,
                "atom_order_equal": self.atom_order_equal,
                "charge_multiplicity_equal": self.charge_multiplicity_equal,
                "candidate_attempt_equal": self.candidate_attempt_equal,
                "structural_gates_accepted": self.structural_gates_accepted,
            },
            "verification_outcome": self.verification_outcome,
            "immutable": True,
        }

    def to_payload(self) -> dict[str, object]:
        return _with_receipt_digest(self.unsigned_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_payload())

    def sha256(self) -> str:
        return cast(str, self.to_payload()["receipt_sha256"])

    @classmethod
    def from_bytes(cls, raw: bytes) -> SupervisorHandoffVerificationReceiptV1:
        payload = strict_json_object(raw, label="supervisor handoff verification")
        required = {
            "schema_version",
            "proposal_receipt_sha256",
            "supervisor_verifier_source_sha256",
            "a1_process_tree_absence_sha256",
            "exact_file_set_accepted",
            "file_observations",
            "identity_checks",
            "verification_outcome",
            "immutable",
            "receipt_sha256",
        }
        if (
            set(payload) != required
            or payload["schema_version"] != SUPERVISOR_HANDOFF_VERIFICATION_SCHEMA_VERSION
        ):
            raise CrossProcessHandoffError("verification schema/fields drifted")
        _verify_receipt_digest(payload)
        observations = payload["file_observations"]
        checks = payload["identity_checks"]
        if not isinstance(observations, dict) or not isinstance(checks, dict):
            raise CrossProcessHandoffError("verification sections must be objects")
        if set(checks) != {
            "proposal_matches_disk",
            "atom_order_equal",
            "charge_multiplicity_equal",
            "candidate_attempt_equal",
            "structural_gates_accepted",
        }:
            raise CrossProcessHandoffError("verification identity-check fields drifted")
        parsed: list[tuple[str, FileObservationV1]] = []
        for name, item in sorted(observations.items()):
            if not isinstance(item, dict) or set(item) != {
                "sha256",
                "byte_count",
                "mode",
                "no_follow",
                "regular_single_link",
                "size_cap_accepted",
            }:
                raise CrossProcessHandoffError("file observation fields drifted")
            parsed.append(
                (
                    name,
                    FileObservationV1(
                        sha256=str(item["sha256"]),
                        byte_count=int(item["byte_count"]),
                        mode=str(item["mode"]),
                        no_follow=item["no_follow"] is True,
                        regular_single_link=item["regular_single_link"] is True,
                        size_cap_accepted=item["size_cap_accepted"] is True,
                    ),
                )
            )
        receipt = cls(
            proposal_receipt_sha256=str(payload["proposal_receipt_sha256"]),
            supervisor_verifier_source_sha256=str(payload["supervisor_verifier_source_sha256"]),
            a1_process_tree_absence_sha256=str(payload["a1_process_tree_absence_sha256"]),
            file_observations=tuple(parsed),
            exact_file_set_accepted=payload["exact_file_set_accepted"] is True,
            proposal_matches_disk=checks["proposal_matches_disk"] is True,
            atom_order_equal=checks["atom_order_equal"] is True,
            charge_multiplicity_equal=checks["charge_multiplicity_equal"] is True,
            candidate_attempt_equal=checks["candidate_attempt_equal"] is True,
            structural_gates_accepted=checks["structural_gates_accepted"] is True,
            verification_outcome=payload["verification_outcome"],  # type: ignore[arg-type]
        )
        if payload["immutable"] is not True or receipt.canonical_bytes() != raw:
            raise CrossProcessHandoffError("verification is not immutable canonical bytes")
        return receipt


@dataclass(frozen=True, slots=True)
class StageA2AdmissionReceiptV1:
    proposal_receipt_sha256: str
    verification_receipt_sha256: str
    cation_xyz_sha256: str
    cation_xyz_byte_count: int
    neutral_xyz_sha256: str
    neutral_xyz_byte_count: int
    stage_a2_source_sha256: str
    gpu_pyscf_interpreter_profile_sha256: str
    shared_pyscf_core_source_sha256: str
    shared_schema_source_sha256: str
    campaign_absolute_deadline_ns: int
    clock_domain_digest: str
    remaining_budget_ns: int
    admission_outcome: Literal["accepted"] = "accepted"

    def __post_init__(self) -> None:
        for field, value in (
            ("proposal_receipt_sha256", self.proposal_receipt_sha256),
            ("verification_receipt_sha256", self.verification_receipt_sha256),
            ("cation_xyz_sha256", self.cation_xyz_sha256),
            ("neutral_xyz_sha256", self.neutral_xyz_sha256),
            ("stage_a2_source_sha256", self.stage_a2_source_sha256),
            ("gpu_pyscf_interpreter_profile_sha256", self.gpu_pyscf_interpreter_profile_sha256),
            ("shared_pyscf_core_source_sha256", self.shared_pyscf_core_source_sha256),
            ("shared_schema_source_sha256", self.shared_schema_source_sha256),
            ("clock_domain_digest", self.clock_domain_digest),
        ):
            require_sha256(value, field)
        require_int(self.cation_xyz_byte_count, "cation byte count", minimum=1)
        require_int(self.neutral_xyz_byte_count, "neutral byte count", minimum=1)
        require_int(self.campaign_absolute_deadline_ns, "campaign deadline", minimum=1)
        require_int(self.remaining_budget_ns, "remaining budget", minimum=1)
        if self.remaining_budget_ns > 7_200_000_000_000:
            raise CrossProcessHandoffError("A2 remaining budget exceeds campaign limit")
        if self.admission_outcome != "accepted":
            raise CrossProcessHandoffError("only accepted handoff produces A2 admission")

    def unsigned_payload(self) -> dict[str, object]:
        return {
            "schema_version": STAGE_A2_ADMISSION_SCHEMA_VERSION,
            "proposal_receipt_sha256": self.proposal_receipt_sha256,
            "verification_receipt_sha256": self.verification_receipt_sha256,
            "admitted_endpoints": {
                "cation": {
                    "xyz_sha256": self.cation_xyz_sha256,
                    "xyz_byte_count": self.cation_xyz_byte_count,
                },
                "neutral": {
                    "xyz_sha256": self.neutral_xyz_sha256,
                    "xyz_byte_count": self.neutral_xyz_byte_count,
                },
            },
            "stage_a2_source_sha256": self.stage_a2_source_sha256,
            "gpu_pyscf_interpreter_profile_sha256": self.gpu_pyscf_interpreter_profile_sha256,
            "shared_pyscf_core_source_sha256": self.shared_pyscf_core_source_sha256,
            "shared_schema_source_sha256": self.shared_schema_source_sha256,
            "campaign_absolute_deadline_ns": self.campaign_absolute_deadline_ns,
            "clock_domain_digest": self.clock_domain_digest,
            "remaining_budget_ns": self.remaining_budget_ns,
            "admission_outcome": self.admission_outcome,
            "immutable": True,
        }

    def to_payload(self) -> dict[str, object]:
        return _with_receipt_digest(self.unsigned_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_payload())

    def sha256(self) -> str:
        return cast(str, self.to_payload()["receipt_sha256"])

    @classmethod
    def from_bytes(cls, raw: bytes) -> StageA2AdmissionReceiptV1:
        payload = strict_json_object(raw, label="stage A2 admission")
        required = {
            "schema_version",
            "proposal_receipt_sha256",
            "verification_receipt_sha256",
            "admitted_endpoints",
            "stage_a2_source_sha256",
            "gpu_pyscf_interpreter_profile_sha256",
            "shared_pyscf_core_source_sha256",
            "shared_schema_source_sha256",
            "campaign_absolute_deadline_ns",
            "clock_domain_digest",
            "remaining_budget_ns",
            "admission_outcome",
            "immutable",
            "receipt_sha256",
        }
        if (
            set(payload) != required
            or payload["schema_version"] != STAGE_A2_ADMISSION_SCHEMA_VERSION
        ):
            raise CrossProcessHandoffError("A2 admission schema/fields drifted")
        _verify_receipt_digest(payload)
        endpoints = payload["admitted_endpoints"]
        if not isinstance(endpoints, dict) or set(endpoints) != set(ENDPOINTS):
            raise CrossProcessHandoffError("A2 admission endpoints drifted")
        cation = endpoints["cation"]
        neutral = endpoints["neutral"]
        if (
            not isinstance(cation, dict)
            or not isinstance(neutral, dict)
            or set(cation) != {"xyz_sha256", "xyz_byte_count"}
            or set(neutral) != {"xyz_sha256", "xyz_byte_count"}
        ):
            raise CrossProcessHandoffError("A2 admitted endpoint fields drifted")
        receipt = cls(
            proposal_receipt_sha256=str(payload["proposal_receipt_sha256"]),
            verification_receipt_sha256=str(payload["verification_receipt_sha256"]),
            cation_xyz_sha256=str(cation["xyz_sha256"]),
            cation_xyz_byte_count=_strict_int(cation["xyz_byte_count"], "cation byte count"),
            neutral_xyz_sha256=str(neutral["xyz_sha256"]),
            neutral_xyz_byte_count=_strict_int(neutral["xyz_byte_count"], "neutral byte count"),
            stage_a2_source_sha256=str(payload["stage_a2_source_sha256"]),
            gpu_pyscf_interpreter_profile_sha256=str(
                payload["gpu_pyscf_interpreter_profile_sha256"]
            ),
            shared_pyscf_core_source_sha256=str(payload["shared_pyscf_core_source_sha256"]),
            shared_schema_source_sha256=str(payload["shared_schema_source_sha256"]),
            campaign_absolute_deadline_ns=_strict_int(
                payload["campaign_absolute_deadline_ns"], "campaign deadline"
            ),
            clock_domain_digest=str(payload["clock_domain_digest"]),
            remaining_budget_ns=_strict_int(payload["remaining_budget_ns"], "remaining budget"),
            admission_outcome=payload["admission_outcome"],  # type: ignore[arg-type]
        )
        if payload["immutable"] is not True or receipt.canonical_bytes() != raw:
            raise CrossProcessHandoffError("A2 admission is not immutable canonical bytes")
        return receipt


def verify_a1_handoff(
    store: CampaignEvidenceStore,
    *,
    proposal: A1HandoffProposalReceiptV1,
    proposal_path: str,
    a1_process_tree_absence_sha256: str,
    supervisor_verifier_source_sha256: str,
    expected_campaign_id: str,
    expected_candidate: str,
    expected_attempt_id: str,
) -> SupervisorHandoffVerificationReceiptV1:
    """Independently re-read proposal, endpoint bytes, trajectories, and receipts."""

    require_sha256(a1_process_tree_absence_sha256, "A1 process-tree absence proof")
    raw_proposal, proposal_identity = store.read(proposal_path)
    observed_proposal = A1HandoffProposalReceiptV1.from_bytes(raw_proposal)
    if proposal_identity.sha256 != hashlib.sha256(raw_proposal).hexdigest():
        raise CrossProcessHandoffError("proposal file identity mismatch")
    if observed_proposal != proposal:
        raise CrossProcessHandoffError("proposal object differs from durable proposal bytes")
    identity_equal = (
        proposal.campaign_id == expected_campaign_id
        and proposal.candidate == expected_candidate
        and proposal.attempt_id == expected_attempt_id
    )
    observations: list[tuple[str, FileObservationV1]] = []
    atom_order_equal = True
    proposal_matches = True
    structural_gates = True
    charge_mult_equal = True
    for endpoint_name, endpoint in (("cation", proposal.cation), ("neutral", proposal.neutral)):
        input_path = f"runtime/stage_a1/{endpoint_name}/input.xyz"
        output_path = f"runtime/stage_a1/{endpoint_name}/output.xyz"
        trajectory_path = f"runtime/stage_a1/{endpoint_name}/trajectory.jsonl"
        receipt_path = f"runtime/stage_a1/{endpoint_name}/preoptimization_receipt.json"
        _input_raw, input_identity = store.read(input_path)
        output_raw, output_identity = store.read(output_path)
        _trajectory_raw, trajectory_identity = store.read(trajectory_path)
        receipt_raw, receipt_identity = store.read(receipt_path)
        elements = parse_xyz_elements(output_raw)
        atom_order_equal &= (
            elements == endpoint.ordered_elements
            and element_order_sha256(elements) == endpoint.element_order_sha256
        )
        proposal_matches &= (
            input_identity.sha256 == endpoint.a1_input_xyz_sha256
            and output_identity.sha256 == endpoint.a1_output_xyz_sha256
            and output_identity.byte_count == endpoint.a1_output_xyz_byte_count
            and trajectory_identity.sha256 == endpoint.trajectory_sha256
            and receipt_identity.sha256 == endpoint.preoptimization_receipt_sha256
        )
        receipt_payload = strict_json_object(
            receipt_raw, label=f"{endpoint_name} preoptimization receipt"
        )
        structural_gates &= receipt_payload.get("structural_gates_passed") is True
        charge_mult_equal &= (
            receipt_payload.get("endpoint") == endpoint_name
            and receipt_payload.get("charge") == endpoint.charge
            and receipt_payload.get("multiplicity") == endpoint.multiplicity
        )
        for path, identity in (
            (input_path, input_identity),
            (output_path, output_identity),
            (trajectory_path, trajectory_identity),
            (receipt_path, receipt_identity),
        ):
            observations.append(
                (
                    path.removeprefix("runtime/stage_a1/"),
                    FileObservationV1(
                        sha256=identity.sha256,
                        byte_count=identity.byte_count,
                        mode=f"{identity.mode:04o}",
                        no_follow=True,
                        regular_single_link=True,
                        size_cap_accepted=True,
                    ),
                )
            )
    accepted = (
        atom_order_equal
        and proposal_matches
        and structural_gates
        and charge_mult_equal
        and identity_equal
    )
    return SupervisorHandoffVerificationReceiptV1(
        proposal_receipt_sha256=proposal.sha256(),
        supervisor_verifier_source_sha256=supervisor_verifier_source_sha256,
        a1_process_tree_absence_sha256=a1_process_tree_absence_sha256,
        file_observations=tuple(sorted(observations)),
        exact_file_set_accepted=True,
        proposal_matches_disk=proposal_matches,
        atom_order_equal=atom_order_equal,
        charge_multiplicity_equal=charge_mult_equal,
        candidate_attempt_equal=identity_equal,
        structural_gates_accepted=structural_gates,
        verification_outcome="accepted" if accepted else "rejected",
    )


def admit_stage_a2(
    proposal: A1HandoffProposalReceiptV1,
    verification: SupervisorHandoffVerificationReceiptV1,
    *,
    stage_a2_source_sha256: str,
    gpu_pyscf_interpreter_profile_sha256: str,
    shared_pyscf_core_source_sha256: str,
    shared_schema_source_sha256: str,
    campaign_absolute_deadline_ns: int,
    clock_domain_digest: str,
    now_ns: int,
) -> StageA2AdmissionReceiptV1:
    if verification.verification_outcome != "accepted":
        raise CrossProcessHandoffError("rejected handoff cannot produce A2 admission")
    if verification.proposal_receipt_sha256 != proposal.sha256():
        raise CrossProcessHandoffError("verification refers to another A1 proposal")
    remaining = campaign_absolute_deadline_ns - now_ns
    if remaining <= 0:
        raise CrossProcessHandoffError("campaign deadline expired before A2 admission")
    return StageA2AdmissionReceiptV1(
        proposal_receipt_sha256=proposal.sha256(),
        verification_receipt_sha256=verification.sha256(),
        cation_xyz_sha256=proposal.cation.a1_output_xyz_sha256,
        cation_xyz_byte_count=proposal.cation.a1_output_xyz_byte_count,
        neutral_xyz_sha256=proposal.neutral.a1_output_xyz_sha256,
        neutral_xyz_byte_count=proposal.neutral.a1_output_xyz_byte_count,
        stage_a2_source_sha256=stage_a2_source_sha256,
        gpu_pyscf_interpreter_profile_sha256=gpu_pyscf_interpreter_profile_sha256,
        shared_pyscf_core_source_sha256=shared_pyscf_core_source_sha256,
        shared_schema_source_sha256=shared_schema_source_sha256,
        campaign_absolute_deadline_ns=campaign_absolute_deadline_ns,
        clock_domain_digest=clock_domain_digest,
        remaining_budget_ns=remaining,
    )


__all__ = [
    "A1_HANDOFF_PROPOSAL_SCHEMA_VERSION",
    "STAGE_A2_ADMISSION_SCHEMA_VERSION",
    "SUPERVISOR_HANDOFF_VERIFICATION_SCHEMA_VERSION",
    "A1HandoffProposalReceiptV1",
    "CrossProcessHandoffError",
    "EndpointHandoffProposalV1",
    "FileObservationV1",
    "StageA2AdmissionReceiptV1",
    "SupervisorHandoffVerificationReceiptV1",
    "admit_stage_a2",
    "element_order_sha256",
    "parse_xyz_elements",
    "verify_a1_handoff",
]
