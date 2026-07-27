"""Capability-gated GPU-PySCF A2 wrapper over the shared PySCF core."""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Final

from nhc_deprot_ranker.quantum.phase9b_campaign_evidence import CampaignEvidenceStore
from nhc_deprot_ranker.quantum.phase9b_campaign_schemas import (
    StageA2TerminalReceiptV1,
    StageName,
    strict_json_object,
)
from nhc_deprot_ranker.quantum.phase9b_cross_process_handoff import (
    A1HandoffProposalReceiptV1,
    StageA2AdmissionReceiptV1,
    SupervisorHandoffVerificationReceiptV1,
    element_order_sha256,
    parse_xyz_elements,
)
from nhc_deprot_ranker.quantum.phase9b_internal_stage_capability import (
    PHASE9B_A2_STAGE_PROFILE,
    InternalStageCapabilityError,
    InternalStageCapabilityV1,
    run_registered_stage_bootstrap,
)
from nhc_deprot_ranker.quantum.phase9b_shared_pyscf_core import (
    SHARED_TWO_ENDPOINT_PYSCF_CORE,
    AdmittedA1InputProvenance,
    BackendFactory,
    SharedTwoEndpointPySCFCore,
)

if TYPE_CHECKING:  # pragma: no cover
    from nhc_deprot_ranker.quantum.two_endpoint import TwoEndpointRequest

STAGE_A2_ENTRYPOINT_SCHEMA_VERSION: Final = "nhc-phase9b-stage-a2-entrypoint-v1"


class StageA2Error(RuntimeError):
    """A2 authority, durable input, import boundary, or shared core failed."""


@dataclass(frozen=True, slots=True)
class A2DiskInputEvidence:
    endpoint: str
    relative_path: str
    byte_count: int
    disk_bytes_sha256: str
    parser_input_sha256: str
    element_order_sha256: str

    def __post_init__(self) -> None:
        if self.endpoint not in {"cation", "neutral"}:
            raise StageA2Error("unknown A2 endpoint")
        if self.byte_count <= 0 or self.disk_bytes_sha256 != self.parser_input_sha256:
            raise StageA2Error("A2 disk bytes differ from parser input bytes")

    def to_payload(self) -> dict[str, object]:
        return {
            "endpoint": self.endpoint,
            "relative_path": self.relative_path,
            "byte_count": self.byte_count,
            "disk_bytes_sha256": self.disk_bytes_sha256,
            "parser_input_sha256": self.parser_input_sha256,
            "element_order_sha256": self.element_order_sha256,
        }


def _assert_import_isolation() -> None:
    forbidden = {"aimnet", "ase", "torch"}
    imported = {name.split(".", 1)[0] for name in sys.modules}
    overlap = sorted(imported & forbidden)
    if overlap:
        raise StageA2Error(f"A2 process imported forbidden ML packages: {overlap}")


def _read_admitted_endpoint(
    store: CampaignEvidenceStore,
    *,
    endpoint: str,
    expected_sha256: str,
    expected_byte_count: int,
    expected_elements: tuple[str, ...],
) -> tuple[bytes, A2DiskInputEvidence]:
    relative = f"runtime/stage_a1/{endpoint}/output.xyz"
    raw, identity = store.read(relative)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256 or identity.sha256 != expected_sha256:
        raise StageA2Error(f"{endpoint} A2 input digest differs from admission")
    if len(raw) != expected_byte_count or identity.byte_count != expected_byte_count:
        raise StageA2Error(f"{endpoint} A2 input byte count differs from admission")
    elements = parse_xyz_elements(raw)
    if elements != expected_elements:
        raise StageA2Error(f"{endpoint} A2 input atom order differs from A1 proposal")
    # The same immutable bytes object is passed to the shared request parser.
    parser_input = raw
    parser_digest = hashlib.sha256(parser_input).hexdigest()
    return parser_input, A2DiskInputEvidence(
        endpoint=endpoint,
        relative_path=relative,
        byte_count=len(raw),
        disk_bytes_sha256=digest,
        parser_input_sha256=parser_digest,
        element_order_sha256=element_order_sha256(elements),
    )


def run_stage_a2(
    *,
    capability: InternalStageCapabilityV1,
    request: TwoEndpointRequest,
    store: CampaignEvidenceStore,
    proposal: A1HandoffProposalReceiptV1,
    verification: SupervisorHandoffVerificationReceiptV1,
    admission: StageA2AdmissionReceiptV1,
    output_root: Path,
    backend_factory: BackendFactory | None = None,
    shared_core: SharedTwoEndpointPySCFCore = SHARED_TWO_ENDPOINT_PYSCF_CORE,
) -> tuple[tuple[A2DiskInputEvidence, A2DiskInputEvidence], StageA2TerminalReceiptV1]:
    """Re-read admitted XYZ bytes, parse those bytes, and invoke one shared core."""

    if capability.stage is not StageName.A2:
        raise InternalStageCapabilityError("A2 entrypoint received another stage capability")
    if capability.a2_admission_sha256 != admission.sha256():
        raise StageA2Error("A2 capability refers to another admission")
    if admission.proposal_receipt_sha256 != proposal.sha256():
        raise StageA2Error("A2 admission refers to another proposal")
    if admission.verification_receipt_sha256 != verification.sha256():
        raise StageA2Error("A2 admission refers to another verification")
    if verification.verification_outcome != "accepted":
        raise StageA2Error("A2 cannot consume a rejected handoff")
    if capability.stage_deadline_ns != capability.campaign_absolute_deadline_ns:
        raise StageA2Error("A2 must receive only the remaining campaign deadline")
    _assert_import_isolation()

    cation_raw, cation_evidence = _read_admitted_endpoint(
        store,
        endpoint="cation",
        expected_sha256=admission.cation_xyz_sha256,
        expected_byte_count=admission.cation_xyz_byte_count,
        expected_elements=proposal.cation.ordered_elements,
    )
    neutral_raw, neutral_evidence = _read_admitted_endpoint(
        store,
        endpoint="neutral",
        expected_sha256=admission.neutral_xyz_sha256,
        expected_byte_count=admission.neutral_xyz_byte_count,
        expected_elements=proposal.neutral.ordered_elements,
    )

    # Standard-library parsing and all admission checks happen before this lazy
    # import boundary.  No coordinate object crosses from A1 or supervisor.
    from nhc_deprot_ranker.quantum import two_endpoint as runner

    cation_geometry = runner._parse_xyz(cation_raw, label="A2 cation XYZ")  # pyright: ignore[reportPrivateUsage]
    neutral_geometry = runner._parse_xyz(neutral_raw, label="A2 neutral XYZ")  # pyright: ignore[reportPrivateUsage]
    rebound = replace(
        request,
        cation=replace(
            request.cation,
            xyz_path=store.root / "runtime/stage_a1/cation/output.xyz",
            xyz_sha256=cation_evidence.disk_bytes_sha256,
            geometry=cation_geometry,
        ),
        neutral=replace(
            request.neutral,
            xyz_path=store.root / "runtime/stage_a1/neutral/output.xyz",
            xyz_sha256=neutral_evidence.disk_bytes_sha256,
            geometry=neutral_geometry,
        ),
    )
    provenance = AdmittedA1InputProvenance(
        route="assisted",
        proposal_sha256=proposal.sha256(),
        verification_sha256=verification.sha256(),
        admission_sha256=admission.sha256(),
        cation_xyz_sha256=cation_evidence.disk_bytes_sha256,
        neutral_xyz_sha256=neutral_evidence.disk_bytes_sha256,
        cation_parser_input_sha256=cation_evidence.parser_input_sha256,
        neutral_parser_input_sha256=neutral_evidence.parser_input_sha256,
    )
    if backend_factory is None:
        # A real backend remains behind the existing reviewed public source gate.
        runner._ensure_execution_authorized()  # pyright: ignore[reportPrivateUsage]
    exit_code = shared_core.execute(
        rebound,
        output_root,
        capability=capability,
        attempt_id=capability.attempt_id,
        absolute_deadline_monotonic=capability.campaign_absolute_deadline_ns / 1_000_000_000,
        input_provenance=provenance,
        backend_factory=backend_factory,
    )
    if exit_code == 0:
        state = "accepted"
        failure = None
        core_result_path = output_root / "attempts" / capability.attempt_id / "result.json"
        if core_result_path.is_file() and not core_result_path.is_symlink():
            core_result = strict_json_object(
                core_result_path.read_bytes(), label="shared PySCF core result"
            )
            label = core_result.get("dft_deprot_electronic_kcal")
            if not isinstance(label, int | float):
                raise StageA2Error("shared PySCF core result omitted its label")
            store.write_json(
                "runtime/stage_a2/route_result.json",
                {
                    "schema_version": "nhc-phase9b-stage-a2-route-result-v1",
                    "status": "accepted",
                    "source": "shared_pyscf_core",
                    "dft_deprot_electronic_kcal": label,
                    "synthetic_test_only": False,
                },
            )
    else:
        state = "rejected_cation"
        failure = {
            "code": "a2_shared_core_rejected",
            "stage": "shared_pyscf_core",
            "exit_code": exit_code,
            "details_sha256": hashlib.sha256(str(exit_code).encode("ascii")).hexdigest(),
        }
    evidence_digest = hashlib.sha256(
        b"".join(
            (
                cation_evidence.disk_bytes_sha256.encode("ascii"),
                neutral_evidence.disk_bytes_sha256.encode("ascii"),
                admission.sha256().encode("ascii"),
            )
        )
    ).hexdigest()
    terminal = StageA2TerminalReceiptV1(
        {
            "schema_version": StageA2TerminalReceiptV1.SCHEMA_VERSION,
            "campaign_id": capability.campaign_id,
            "attempt_id": capability.attempt_id,
            "terminal_state": state,
            "evidence_sha256": evidence_digest,
            "failure": failure,
        }
    )
    store.write_bytes("runtime/stage_a2/terminal.json", terminal.canonical_bytes())
    _assert_import_isolation()
    return (cation_evidence, neutral_evidence), terminal


def main(argv: list[str] | None = None) -> int:
    """Internal-only A2 entrypoint; no public A2 launcher exists."""

    parser = argparse.ArgumentParser(prog="nhc-phase9b-stage-a2")
    parser.add_argument("--registration-fd", required=True, type=int)
    parser.add_argument("--release-fd", required=True, type=int)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--supervisor-pid", required=True, type=int)
    parser.add_argument("--supervisor-start-time", required=True, type=int)
    parser.add_argument("--supervisor-session-id", required=True, type=int)
    parser.add_argument("--supervisor-process-group-id", required=True, type=int)
    parser.add_argument("--stage-source-sha256", required=True)
    parser.add_argument("--registration-nonce-sha256", required=True)
    parser.add_argument("--clock-domain-digest", required=True)
    parser.add_argument("--linux-boot-id-sha256", required=True)
    parser.add_argument("--request-path", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--proposal-path", required=True, type=Path)
    parser.add_argument("--verification-path", required=True, type=Path)
    parser.add_argument("--admission-path", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    values = parser.parse_args(argv)
    registered_argv = tuple(sys.orig_argv[1:] if argv is None else [sys.argv[0], *argv])
    capability = run_registered_stage_bootstrap(
        profile=PHASE9B_A2_STAGE_PROFILE,
        campaign_id=values.campaign_id,
        attempt_id=values.attempt_id,
        registration_fd=values.registration_fd,
        release_fd=values.release_fd,
        supervisor_pid=values.supervisor_pid,
        supervisor_start_time=values.supervisor_start_time,
        supervisor_session_id=values.supervisor_session_id,
        supervisor_process_group_id=values.supervisor_process_group_id,
        stage_source_sha256=values.stage_source_sha256,
        argv=registered_argv,
        registration_nonce_sha256=values.registration_nonce_sha256,
        clock_domain_digest=values.clock_domain_digest,
        linux_boot_id_sha256=values.linux_boot_id_sha256,
    )
    from nhc_deprot_ranker.quantum import two_endpoint

    request = two_endpoint.load_two_endpoint_request(values.request_path)
    proposal = A1HandoffProposalReceiptV1.from_bytes(values.proposal_path.read_bytes())
    verification = SupervisorHandoffVerificationReceiptV1.from_bytes(
        values.verification_path.read_bytes()
    )
    admission = StageA2AdmissionReceiptV1.from_bytes(values.admission_path.read_bytes())
    store = CampaignEvidenceStore(values.evidence_root.resolve(strict=True))
    _, terminal = run_stage_a2(
        capability=capability,
        request=request,
        store=store,
        proposal=proposal,
        verification=verification,
        admission=admission,
        output_root=values.output_root,
    )
    return 0 if terminal.to_payload()["terminal_state"] == "accepted" else 1


__all__ = [
    "STAGE_A2_ENTRYPOINT_SCHEMA_VERSION",
    "A2DiskInputEvidence",
    "StageA2Error",
    "main",
    "run_stage_a2",
]


if __name__ == "__main__":  # pragma: no cover - subprocess entrypoint
    raise SystemExit(main())
