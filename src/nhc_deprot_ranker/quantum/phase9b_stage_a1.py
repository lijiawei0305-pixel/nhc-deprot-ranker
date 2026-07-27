"""Capability-gated MLFF A1 worker: both endpoints, one model load, no PySCF."""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from nhc_deprot_ranker.quantum.phase9b_campaign_evidence import (
    IMMUTABLE_DATA_MODE,
    CampaignEvidenceStore,
)
from nhc_deprot_ranker.quantum.phase9b_campaign_schemas import (
    StageA1TerminalReceiptV1,
    StageName,
)
from nhc_deprot_ranker.quantum.phase9b_cross_process_handoff import (
    A1HandoffProposalReceiptV1,
    EndpointHandoffProposalV1,
    element_order_sha256,
    parse_xyz_elements,
)
from nhc_deprot_ranker.quantum.phase9b_internal_stage_capability import (
    PHASE9B_A1_STAGE_PROFILE,
    InternalStageCapabilityError,
    InternalStageCapabilityV1,
    run_registered_stage_bootstrap,
)

if TYPE_CHECKING:  # pragma: no cover
    from nhc_deprot_ranker.quantum.two_endpoint import EndpointRequest, TwoEndpointRequest

STAGE_A1_ENTRYPOINT_SCHEMA_VERSION: Final = "nhc-phase9b-stage-a1-entrypoint-v1"
ENDPOINT_ORDER: Final = ("cation", "neutral")


class StageA1Error(RuntimeError):
    """A1 authority, optimizer, structure, or evidence failed closed."""


@dataclass(frozen=True, slots=True)
class A1EndpointOutcome:
    endpoint: str
    input_xyz_bytes: bytes
    output_xyz_bytes: bytes
    trajectory_bytes: bytes
    structural_gates_passed: bool
    final_max_force_ev_per_angstrom: float
    optimizer_step_count: int
    calculator_invocation_count: int

    def __post_init__(self) -> None:
        if self.endpoint not in ENDPOINT_ORDER:
            raise StageA1Error("unknown A1 endpoint")
        if not self.input_xyz_bytes or not self.output_xyz_bytes or not self.trajectory_bytes:
            raise StageA1Error("A1 endpoint evidence bytes must be non-empty")
        before = parse_xyz_elements(self.input_xyz_bytes)
        after = parse_xyz_elements(self.output_xyz_bytes)
        if before != after:
            raise StageA1Error("A1 changed endpoint atom order")
        if not self.structural_gates_passed:
            raise StageA1Error("A1 endpoint failed a structural gate")
        if self.final_max_force_ev_per_angstrom < 0:
            raise StageA1Error("A1 final max force is invalid")
        if self.optimizer_step_count < 0 or self.calculator_invocation_count < 0:
            raise StageA1Error("A1 endpoint counts are invalid")


class A1StageRuntime(Protocol):
    """Injected local/mock seam; production implementation remains gate-closed."""

    @property
    def model_load_count(self) -> int: ...

    def load_base_model_once(self) -> None: ...

    def run_endpoint(
        self,
        endpoint: EndpointRequest,
        *,
        deadline_monotonic: float,
    ) -> A1EndpointOutcome: ...


@dataclass(slots=True)
class ProductionA1StageRuntime:
    """Adapter over the existing loader, endpoint wrappers, LBFGS, and gates."""

    weight_path: Path
    gpu_index: int
    monotonic: object = time.monotonic
    _base_model: object | None = None
    _optimizer: object | None = None
    _model_load_count: int = 0

    @property
    def model_load_count(self) -> int:
        return self._model_load_count

    def load_base_model_once(self) -> None:
        if self._model_load_count != 0 or self._base_model is not None:
            raise StageA1Error("AIMNet2 base model may load exactly once")
        # Lazy import is after internal capability consumption in the entrypoint.
        from nhc_deprot_ranker.quantum.phase9b_aimnet2_runtime import (
            build_production_assisted_runtime,
        )

        loader, optimizer = build_production_assisted_runtime(monotonic=self.monotonic)  # type: ignore[arg-type]
        self._base_model = loader(weight_path=self.weight_path, device=f"cuda:{self.gpu_index}")
        self._optimizer = optimizer
        self._model_load_count = 1

    def run_endpoint(
        self,
        endpoint: EndpointRequest,
        *,
        deadline_monotonic: float,
    ) -> A1EndpointOutcome:
        if self._base_model is None or self._optimizer is None or self._model_load_count != 1:
            raise StageA1Error("A1 endpoint cannot run before its one model load")
        from nhc_deprot_ranker.quantum.phase9b_aimnet2_runtime import (
            FMAX_EV_PER_ANGSTROM,
            MAX_STEPS,
            TerminalState,
            parse_xyz,
            render_xyz,
            serialize_trajectory,
            validate_structure,
        )

        input_bytes = endpoint.xyz_path.read_bytes()
        if hashlib.sha256(input_bytes).hexdigest() != endpoint.xyz_sha256:
            raise StageA1Error(f"{endpoint.name} input bytes differ from request")
        elements, coordinates = parse_xyz(input_bytes)
        calculator = self._base_model.calculator_for(  # type: ignore[attr-defined]
            charge=endpoint.charge,
            multiplicity=endpoint.multiplicity,
        )
        outcome = self._optimizer.optimize(  # type: ignore[attr-defined]
            calculator=calculator,
            coordinates=coordinates,
            elements=elements,
            fmax=FMAX_EV_PER_ANGSTROM,
            max_steps=MAX_STEPS,
            deadline_monotonic=deadline_monotonic,
        )
        if outcome.terminal_state is not TerminalState.CONVERGED or not outcome.converged:
            raise StageA1Error(f"{endpoint.name} AIMNet2 preoptimization was not accepted")
        validation = validate_structure(
            endpoint=endpoint.name,
            elements_before=elements,
            before=coordinates,
            elements_after=elements,
            after=outcome.coordinates,
        )
        output = render_xyz(
            elements,
            outcome.coordinates,
            comment=f"phase9b A1 {endpoint.name}; not a validated minimum",
        )
        return A1EndpointOutcome(
            endpoint=endpoint.name,
            input_xyz_bytes=input_bytes,
            output_xyz_bytes=output,
            trajectory_bytes=serialize_trajectory(outcome.trajectory),
            structural_gates_passed=validation.all_gates_passed,
            final_max_force_ev_per_angstrom=outcome.final_max_force,
            optimizer_step_count=outcome.steps,
            calculator_invocation_count=outcome.calculator_invocations,
        )


def _assert_import_isolation() -> None:
    forbidden = {"pyscf", "geometric", "pyscf_dispersion"}
    imported = {name.split(".", 1)[0] for name in sys.modules}
    overlap = sorted(imported & forbidden)
    if overlap:
        raise StageA1Error(f"A1 process imported forbidden PySCF packages: {overlap}")


def _preoptimization_payload(
    *,
    campaign_id: str,
    attempt_id: str,
    endpoint: EndpointRequest,
    outcome: A1EndpointOutcome,
) -> dict[str, object]:
    return {
        "schema_version": "nhc-phase9b-a1-preoptimization-receipt-v1",
        "campaign_id": campaign_id,
        "attempt_id": attempt_id,
        "endpoint": endpoint.name,
        "charge": endpoint.charge,
        "multiplicity": endpoint.multiplicity,
        "input_xyz_sha256": hashlib.sha256(outcome.input_xyz_bytes).hexdigest(),
        "output_xyz_sha256": hashlib.sha256(outcome.output_xyz_bytes).hexdigest(),
        "output_xyz_byte_count": len(outcome.output_xyz_bytes),
        "trajectory_sha256": hashlib.sha256(outcome.trajectory_bytes).hexdigest(),
        "structural_gates_passed": outcome.structural_gates_passed,
        "final_max_force_ev_per_angstrom": outcome.final_max_force_ev_per_angstrom,
        "optimizer_step_count": outcome.optimizer_step_count,
        "calculator_invocation_count": outcome.calculator_invocation_count,
        "pyscf_calls": 0,
        "label_produced": False,
    }


def run_stage_a1(
    *,
    capability: InternalStageCapabilityV1,
    request: TwoEndpointRequest,
    store: CampaignEvidenceStore,
    runtime: A1StageRuntime,
    campaign_id: str,
    candidate: str,
    stage_a1_source_sha256: str,
    mlff_interpreter_profile_sha256: str,
    weight_sha256: str,
    optimizer_protocol_sha256: str,
) -> tuple[A1HandoffProposalReceiptV1 | None, StageA1TerminalReceiptV1]:
    """Run cation then neutral once; only two successes produce a proposal."""

    if capability.stage is not StageName.A1:
        raise InternalStageCapabilityError("A1 entrypoint received another stage capability")
    if capability.campaign_id != campaign_id or capability.candidate != candidate:
        raise StageA1Error("A1 campaign/candidate identity drifted")
    _assert_import_isolation()
    if runtime.model_load_count != 0:
        raise StageA1Error("A1 runtime was already used")
    runtime.load_base_model_once()
    if runtime.model_load_count != 1:
        raise StageA1Error("A1 runtime did not load exactly one base model")

    endpoint_proposals: dict[str, EndpointHandoffProposalV1] = {}
    failure: dict[str, object] | None = None
    for endpoint_name in ENDPOINT_ORDER:
        endpoint = request.cation if endpoint_name == "cation" else request.neutral
        try:
            outcome = runtime.run_endpoint(
                endpoint,
                deadline_monotonic=capability.stage_deadline_ns / 1_000_000_000,
            )
            input_identity = store.write_bytes(
                f"runtime/stage_a1/{endpoint_name}/input.xyz",
                outcome.input_xyz_bytes,
                mode=IMMUTABLE_DATA_MODE,
            )
            output_identity = store.write_bytes(
                f"runtime/stage_a1/{endpoint_name}/output.xyz",
                outcome.output_xyz_bytes,
                mode=IMMUTABLE_DATA_MODE,
            )
            trajectory_identity = store.write_bytes(
                f"runtime/stage_a1/{endpoint_name}/trajectory.jsonl",
                outcome.trajectory_bytes,
                mode=IMMUTABLE_DATA_MODE,
            )
            receipt_payload = _preoptimization_payload(
                campaign_id=campaign_id,
                attempt_id=capability.attempt_id,
                endpoint=endpoint,
                outcome=outcome,
            )
            receipt_identity = store.write_json(
                f"runtime/stage_a1/{endpoint_name}/preoptimization_receipt.json",
                receipt_payload,
            )
            elements = parse_xyz_elements(outcome.output_xyz_bytes)
            endpoint_proposals[endpoint_name] = EndpointHandoffProposalV1(
                endpoint=endpoint_name,
                charge=endpoint.charge,
                multiplicity=endpoint.multiplicity,
                atom_count=len(elements),
                ordered_elements=elements,
                element_order_sha256=element_order_sha256(elements),
                a1_input_xyz_sha256=input_identity.sha256,
                a1_output_xyz_sha256=output_identity.sha256,
                a1_output_xyz_byte_count=output_identity.byte_count,
                trajectory_sha256=trajectory_identity.sha256,
                preoptimization_receipt_sha256=receipt_identity.sha256,
                structural_gates_passed=outcome.structural_gates_passed,
                final_max_force_ev_per_angstrom=outcome.final_max_force_ev_per_angstrom,
                optimizer_step_count=outcome.optimizer_step_count,
                calculator_invocation_count=outcome.calculator_invocation_count,
            )
        except Exception as exc:
            failure = {
                "code": f"a1_{endpoint_name}_rejected",
                "stage": endpoint_name,
                "exception_class": type(exc).__name__,
                "details_sha256": hashlib.sha256(str(exc).encode("utf-8")).hexdigest(),
            }
            break

    if failure is not None:
        state = "rejected_cation" if failure["stage"] == "cation" else "rejected_neutral"
        terminal = StageA1TerminalReceiptV1(
            {
                "schema_version": StageA1TerminalReceiptV1.SCHEMA_VERSION,
                "campaign_id": campaign_id,
                "attempt_id": capability.attempt_id,
                "terminal_state": state,
                "evidence_sha256": None,
                "failure": failure,
            }
        )
        store.write_bytes("runtime/stage_a1/terminal.json", terminal.canonical_bytes())
        return None, terminal

    proposal = A1HandoffProposalReceiptV1(
        campaign_id=campaign_id,
        candidate=candidate,
        route="assisted",
        attempt_id=capability.attempt_id,
        cation=endpoint_proposals["cation"],
        neutral=endpoint_proposals["neutral"],
        stage_a1_source_sha256=stage_a1_source_sha256,
        mlff_interpreter_profile_sha256=mlff_interpreter_profile_sha256,
        weight_sha256=weight_sha256,
        optimizer_protocol_sha256=optimizer_protocol_sha256,
    )
    proposal_identity = store.write_bytes(
        "runtime/stage_a1/handoff_proposal.json", proposal.canonical_bytes()
    )
    terminal = StageA1TerminalReceiptV1(
        {
            "schema_version": StageA1TerminalReceiptV1.SCHEMA_VERSION,
            "campaign_id": campaign_id,
            "attempt_id": capability.attempt_id,
            "terminal_state": "accepted",
            "evidence_sha256": proposal_identity.sha256,
            "failure": None,
        }
    )
    store.write_bytes("runtime/stage_a1/terminal.json", terminal.canonical_bytes())
    _assert_import_isolation()
    return proposal, terminal


def main(argv: list[str] | None = None) -> int:
    """Internal-only A1 entrypoint; an inherited capability is mandatory."""

    parser = argparse.ArgumentParser(prog="nhc-phase9b-stage-a1")
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
    parser.add_argument("--request-path", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--weight-path", required=True, type=Path)
    parser.add_argument("--gpu-index", required=True, type=int)
    parser.add_argument("--weight-sha256", required=True)
    parser.add_argument("--optimizer-protocol-sha256", required=True)
    values = parser.parse_args(argv)
    registered_argv = tuple(sys.orig_argv[1:] if argv is None else [sys.argv[0], *argv])
    capability = run_registered_stage_bootstrap(
        profile=PHASE9B_A1_STAGE_PROFILE,
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
    store = CampaignEvidenceStore(values.evidence_root.resolve(strict=True))
    runtime = ProductionA1StageRuntime(
        weight_path=values.weight_path,
        gpu_index=values.gpu_index,
    )
    proposal, terminal = run_stage_a1(
        capability=capability,
        request=request,
        store=store,
        runtime=runtime,
        campaign_id=values.campaign_id,
        candidate=values.candidate,
        stage_a1_source_sha256=capability.stage_source_sha256,
        mlff_interpreter_profile_sha256=capability.stable_profile_sha256,
        weight_sha256=values.weight_sha256,
        optimizer_protocol_sha256=values.optimizer_protocol_sha256,
    )
    del proposal
    return 0 if terminal.to_payload()["terminal_state"] == "accepted" else 1


__all__ = [
    "STAGE_A1_ENTRYPOINT_SCHEMA_VERSION",
    "A1EndpointOutcome",
    "A1StageRuntime",
    "ProductionA1StageRuntime",
    "StageA1Error",
    "main",
    "run_stage_a1",
]


if __name__ == "__main__":  # pragma: no cover - subprocess entrypoint
    raise SystemExit(main())
