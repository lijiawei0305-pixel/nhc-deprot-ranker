"""The AIMNet2-to-PySCF handoff contract, inside the runner source closure.

Route A is **one** guarded transaction:

```text
frozen Phase 7 initial XYZ
  -> AIMNet2 preoptimization        (inside the route, under the permit)
  -> structural validation gates
  -> byte-identical handoff
  -> PySCF residual optimization
```

The preoptimized geometry is a runtime intermediate.  It is produced, validated,
written, and hash-closed *inside* the route, so a permit cannot be asked to bind
a digest that does not exist when the permit is rendered.  That circularity is
what this module removes.

Everything the permit must bind about the AIMNet2 stage lives here, in the
closure, so it is hash-bound like code: the local weight digest, the optimizer
protocol, the structural gates, and the handoff rule itself.  The control-plane
preoptimizer imports these rather than defining its own copies.

The handoff rule is deliberately the strongest available: the bytes PySCF reads
must be **the same bytes** AIMNet2 wrote.  Not an equivalent geometry, not a
re-serialization, not a reordered file.  Anything else would let a silent edit
between the stages pass unnoticed, and the whole point of Route A is that only the
starting geometry differs from Route D.

No chemistry import, no compute, no label.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final

HANDOFF_SCHEMA_VERSION: Final = "nhc-phase9b-pyscf-handoff-v1"
PREOPTIMIZATION_SCHEMA_VERSION: Final = "nhc-phase9b-aimnet2-preoptimization-v2"
TRAJECTORY_SCHEMA_VERSION: Final = "nhc-phase9b-aimnet2-trajectory-v1"

# The single local ensemble member.  Members _1.._3 are absent and may not be
# downloaded; see docs/PHASE9B_SINGLE_MEMBER_SAFEGUARDS.md.
AIMNET2_WEIGHT_FILENAME: Final = "aimnet2_wb97m_d3_0.pt"
AIMNET2_WEIGHT_SHA256: Final = "f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28"
AIMNET2_WEIGHT_BYTES: Final = 8836941

AIMNET2_OPTIMIZER_PROTOCOL: Final[Mapping[str, object]] = MappingProxyType(
    {
        "optimizer": "LBFGS",
        "energy_unit": "eV",
        "forces_unit": "eV/A",
        "fmax_ev_per_angstrom": 0.05,
        "max_steps": 200,
        "max_walltime_seconds": 900,
        "cell": None,
        "periodic": False,
        "constraints": [],
        "ensemble_members": 1,
        "ensemble_uncertainty_available": False,
        "compile_model": False,
        "deterministic_single_member": True,
        # Bound here so the permit closes over how the model is obtained, not
        # only over what is run.  Proved from installed source in Phase 9A-S4.
        "loader_decision": "A",
        "loader_evidence_grade": "source_proven",
        "loader_evidence_phase": "9A-S4",
        "model_path_must_be_absolute": True,
        "model_registry_alias_allowed": False,
        "huggingface_allowed": False,
        "revision_or_token_used": False,
        "manual_load_model_call": False,
        "extra_eval_call": False,
        "validate_species": True,
        "base_model_loads_per_route": 1,
        "endpoint_wrappers_per_route": 2,
        # ASE 3.29.0's own LBFGS defaults, pinned so a library default drift is a
        # receipt mismatch rather than a silently different method.
        "lbfgs_restart": None,
        "lbfgs_trajectory": None,
        "lbfgs_maxstep_default": None,
        "lbfgs_memory_default": 100,
        "lbfgs_damping_default": 1.0,
        "lbfgs_alpha_default": 70.0,
        "lbfgs_use_line_search_default": False,
        "deadline_checked_at": ["start", "evaluation_boundary", "step_observer"],
    }
)

AIMNET2_STRUCTURAL_GATES: Final[Mapping[str, object]] = MappingProxyType(
    {
        "max_total_rmsd_angstrom": 1.0,
        "rmsd_alignment": "none",
        "max_single_atom_displacement_angstrom": 2.5,
        "max_c2_n_bond_change_angstrom": 0.15,
        "max_ring_angle_change_degrees": 10.0,
        "proton_identity_tracked_by": "host_heavy_atom_index",
        "atom_order_must_be_preserved": True,
        "atom_count_must_be_preserved": True,
        "connectivity_must_be_preserved": True,
    }
)

HANDOFF_CONTRACT: Final[Mapping[str, object]] = MappingProxyType(
    {
        "rule": "pyscf_input_bytes_must_equal_aimnet2_output_bytes",
        "comparison": "byte_identity",
        "reserialization_allowed": False,
        "manual_edit_allowed": False,
        "atom_reordering_allowed": False,
        "regeneration_allowed": False,
        "external_preparation_step_allowed": False,
        "charge_and_multiplicity_must_be_preserved": True,
    }
)


class HandoffError(RuntimeError):
    """The AIMNet2-to-PySCF handoff could not be proved closed."""


class PreoptimizationState(Enum):
    """The preoptimization stage's own terminal states."""

    NOT_RUN = "not_run"
    CONVERGED = "converged"
    NOT_CONVERGED = "not_converged"
    GATE_FAILED = "gate_failed"
    FAILED = "failed"


class HandoffState(Enum):
    """Only ``closed`` permits PySCF to start."""

    NOT_ATTEMPTED = "not_attempted"
    CLOSED = "closed"
    REFUSED = "refused"


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    return value


def aimnet2_optimizer_protocol_payload() -> dict[str, object]:
    plain = _plain(AIMNET2_OPTIMIZER_PROTOCOL)
    if not isinstance(plain, dict):  # pragma: no cover - structural guard
        raise HandoffError("the optimizer protocol must normalize to one JSON object")
    return plain


def aimnet2_structural_gates_payload() -> dict[str, object]:
    plain = _plain(AIMNET2_STRUCTURAL_GATES)
    if not isinstance(plain, dict):  # pragma: no cover - structural guard
        raise HandoffError("the structural gates must normalize to one JSON object")
    return plain


def handoff_contract_payload() -> dict[str, object]:
    plain = _plain(HANDOFF_CONTRACT)
    if not isinstance(plain, dict):  # pragma: no cover - structural guard
        raise HandoffError("the handoff contract must normalize to one JSON object")
    return plain


def aimnet2_optimizer_protocol_sha256() -> str:
    return hashlib.sha256(_canonical_json_bytes(aimnet2_optimizer_protocol_payload())).hexdigest()


def aimnet2_structural_gates_sha256() -> str:
    return hashlib.sha256(_canonical_json_bytes(aimnet2_structural_gates_payload())).hexdigest()


def handoff_contract_sha256() -> str:
    return hashlib.sha256(_canonical_json_bytes(handoff_contract_payload())).hexdigest()


def preoptimization_stage_sha256() -> str:
    """One digest over everything the permit binds about the AIMNet2 stage."""

    return hashlib.sha256(
        _canonical_json_bytes(
            {
                "schema_version": PREOPTIMIZATION_SCHEMA_VERSION,
                "weight_filename": AIMNET2_WEIGHT_FILENAME,
                "weight_sha256": AIMNET2_WEIGHT_SHA256,
                "weight_bytes": AIMNET2_WEIGHT_BYTES,
                "optimizer_protocol_sha256": aimnet2_optimizer_protocol_sha256(),
                "structural_gates_sha256": aimnet2_structural_gates_sha256(),
                "handoff_contract_sha256": handoff_contract_sha256(),
                "trajectory_schema_version": TRAJECTORY_SCHEMA_VERSION,
            }
        )
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class StructuralValidation:
    """Every preregistered gate's measured value and verdict."""

    total_rmsd_angstrom: float
    max_single_atom_displacement_angstrom: float
    c2_n1_bond_change_angstrom: float
    c2_n3_bond_change_angstrom: float
    ring_angle_change_degrees: float
    atom_count_preserved: bool
    atom_order_preserved: bool
    connectivity_preserved: bool
    proton_host_index_preserved: bool
    all_gates_passed: bool


@dataclass(frozen=True, slots=True)
class Aimnet2PreoptimizationReceipt:
    """What the AIMNet2 stage did to one endpoint, and whether it may hand off.

    Carries AIMNet2 energies and forces only as *counts and extrema* needed to
    judge convergence and structural integrity.  It is not a scientific result:
    the label is computed from PySCF electronic energies alone, and an AIMNet2
    energy never enters it.
    """

    schema_version: str
    route: str
    attempt_id: str
    endpoint: str
    charge: int
    multiplicity: int
    input_xyz_sha256: str
    output_xyz_sha256: str
    input_atom_order_sha256: str
    output_atom_order_sha256: str
    weight_sha256: str
    optimizer_protocol_sha256: str
    structural_gates_sha256: str
    optimizer_steps: int
    energy_evaluations: int
    force_evaluations: int
    calculator_invocations: int
    initial_max_force_ev_per_angstrom: float
    final_max_force_ev_per_angstrom: float
    initial_energy_ev: float
    final_energy_ev: float
    wall_time_seconds: float
    isolated_cache_bytes_written: int
    trajectory_schema_version: str
    trajectory_frames: int
    trajectory_sha256: str
    terminal_state: str
    validation: StructuralValidation
    state: PreoptimizationState
    failure_reason: str | None
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class PySCFHandoffReceipt:
    """Proof that PySCF's input bytes are the bytes AIMNet2 wrote."""

    schema_version: str
    route: str
    attempt_id: str
    endpoint: str
    charge: int
    multiplicity: int
    aimnet2_output_xyz_sha256: str
    pyscf_input_xyz_sha256: str
    atom_order_sha256: str
    atom_count: int
    request_sha256: str
    runner_source_sha256: str
    preoptimization_receipt_sha256: str
    handoff_contract_sha256: str
    state: HandoffState
    failure_reason: str | None
    receipt_sha256: str


def _validation_payload(validation: StructuralValidation) -> dict[str, object]:
    return {
        "total_rmsd_angstrom": validation.total_rmsd_angstrom,
        "max_single_atom_displacement_angstrom": (validation.max_single_atom_displacement_angstrom),
        "c2_n1_bond_change_angstrom": validation.c2_n1_bond_change_angstrom,
        "c2_n3_bond_change_angstrom": validation.c2_n3_bond_change_angstrom,
        "ring_angle_change_degrees": validation.ring_angle_change_degrees,
        "atom_count_preserved": validation.atom_count_preserved,
        "atom_order_preserved": validation.atom_order_preserved,
        "connectivity_preserved": validation.connectivity_preserved,
        "proton_host_index_preserved": validation.proton_host_index_preserved,
        "all_gates_passed": validation.all_gates_passed,
    }


def _preopt_body(receipt: Aimnet2PreoptimizationReceipt) -> dict[str, object]:
    return {
        "schema_version": receipt.schema_version,
        "route": receipt.route,
        "attempt_id": receipt.attempt_id,
        "endpoint": receipt.endpoint,
        "charge": receipt.charge,
        "multiplicity": receipt.multiplicity,
        "input_xyz_sha256": receipt.input_xyz_sha256,
        "output_xyz_sha256": receipt.output_xyz_sha256,
        "input_atom_order_sha256": receipt.input_atom_order_sha256,
        "output_atom_order_sha256": receipt.output_atom_order_sha256,
        "weight_sha256": receipt.weight_sha256,
        "optimizer_protocol_sha256": receipt.optimizer_protocol_sha256,
        "structural_gates_sha256": receipt.structural_gates_sha256,
        "optimizer_steps": receipt.optimizer_steps,
        "energy_evaluations": receipt.energy_evaluations,
        "force_evaluations": receipt.force_evaluations,
        "calculator_invocations": receipt.calculator_invocations,
        "initial_max_force_ev_per_angstrom": receipt.initial_max_force_ev_per_angstrom,
        "final_max_force_ev_per_angstrom": receipt.final_max_force_ev_per_angstrom,
        "initial_energy_ev": receipt.initial_energy_ev,
        "final_energy_ev": receipt.final_energy_ev,
        "wall_time_seconds": receipt.wall_time_seconds,
        "isolated_cache_bytes_written": receipt.isolated_cache_bytes_written,
        "trajectory_schema_version": receipt.trajectory_schema_version,
        "trajectory_frames": receipt.trajectory_frames,
        "trajectory_sha256": receipt.trajectory_sha256,
        "terminal_state": receipt.terminal_state,
        "validation": _validation_payload(receipt.validation),
        "state": receipt.state.value,
        "failure_reason": receipt.failure_reason,
    }


def _handoff_body(receipt: PySCFHandoffReceipt) -> dict[str, object]:
    return {
        "schema_version": receipt.schema_version,
        "route": receipt.route,
        "attempt_id": receipt.attempt_id,
        "endpoint": receipt.endpoint,
        "charge": receipt.charge,
        "multiplicity": receipt.multiplicity,
        "aimnet2_output_xyz_sha256": receipt.aimnet2_output_xyz_sha256,
        "pyscf_input_xyz_sha256": receipt.pyscf_input_xyz_sha256,
        "atom_order_sha256": receipt.atom_order_sha256,
        "atom_count": receipt.atom_count,
        "request_sha256": receipt.request_sha256,
        "runner_source_sha256": receipt.runner_source_sha256,
        "preoptimization_receipt_sha256": receipt.preoptimization_receipt_sha256,
        "handoff_contract_sha256": receipt.handoff_contract_sha256,
        "state": receipt.state.value,
        "failure_reason": receipt.failure_reason,
    }


def preoptimization_receipt_sha256(receipt: Aimnet2PreoptimizationReceipt) -> str:
    return hashlib.sha256(_canonical_json_bytes(_preopt_body(receipt))).hexdigest()


def handoff_receipt_sha256(receipt: PySCFHandoffReceipt) -> str:
    return hashlib.sha256(_canonical_json_bytes(_handoff_body(receipt))).hexdigest()


def preoptimization_receipt_payload(receipt: Aimnet2PreoptimizationReceipt) -> dict[str, object]:
    body = _preopt_body(receipt)
    body["receipt_sha256"] = receipt.receipt_sha256
    return body


def handoff_receipt_payload(receipt: PySCFHandoffReceipt) -> dict[str, object]:
    body = _handoff_body(receipt)
    body["receipt_sha256"] = receipt.receipt_sha256
    return body


def atom_order_sha256(xyz_bytes: bytes) -> str:
    """Digest of the element symbols in file order, coordinates excluded.

    Atom order is the invariant the whole pipeline depends on, and it must be
    checkable independently of the coordinates that are supposed to change.
    """

    try:
        text = xyz_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HandoffError("XYZ bytes are not UTF-8") from exc
    lines = text.splitlines()
    if len(lines) < 3:
        raise HandoffError("XYZ file is too short to carry a geometry")
    try:
        count = int(lines[0].strip())
    except ValueError as exc:
        raise HandoffError("XYZ atom count is not an integer") from exc
    body = lines[2 : 2 + count]
    if len(body) != count or count <= 0:
        raise HandoffError("XYZ atom count disagrees with the number of atom lines")
    symbols: list[str] = []
    for index, line in enumerate(body):
        fields = line.split()
        if len(fields) < 4:
            raise HandoffError(f"XYZ atom line {index} is malformed")
        symbols.append(fields[0])
    return hashlib.sha256(
        _canonical_json_bytes({"atom_count": count, "elements": symbols})
    ).hexdigest()


def build_preoptimization_receipt(
    *,
    route: str,
    attempt_id: str,
    endpoint: str,
    charge: int,
    multiplicity: int,
    input_xyz: bytes,
    output_xyz: bytes,
    optimizer_steps: int,
    energy_evaluations: int,
    force_evaluations: int,
    initial_max_force_ev_per_angstrom: float,
    final_max_force_ev_per_angstrom: float,
    wall_time_seconds: float,
    isolated_cache_bytes_written: int,
    validation: StructuralValidation,
    state: PreoptimizationState,
    trajectory_sha256: str,
    trajectory_frames: int,
    calculator_invocations: int,
    initial_energy_ev: float,
    final_energy_ev: float,
    terminal_state: str,
    failure_reason: str | None = None,
) -> Aimnet2PreoptimizationReceipt:
    """Close the preoptimization record over the bytes actually produced."""

    if endpoint not in {"cation", "neutral"}:
        raise HandoffError(f"unknown endpoint: {endpoint!r}")
    draft = Aimnet2PreoptimizationReceipt(
        schema_version=PREOPTIMIZATION_SCHEMA_VERSION,
        route=route,
        attempt_id=attempt_id,
        endpoint=endpoint,
        charge=charge,
        multiplicity=multiplicity,
        input_xyz_sha256=hashlib.sha256(input_xyz).hexdigest(),
        output_xyz_sha256=hashlib.sha256(output_xyz).hexdigest(),
        input_atom_order_sha256=atom_order_sha256(input_xyz),
        output_atom_order_sha256=atom_order_sha256(output_xyz),
        weight_sha256=AIMNET2_WEIGHT_SHA256,
        optimizer_protocol_sha256=aimnet2_optimizer_protocol_sha256(),
        structural_gates_sha256=aimnet2_structural_gates_sha256(),
        optimizer_steps=optimizer_steps,
        energy_evaluations=energy_evaluations,
        force_evaluations=force_evaluations,
        calculator_invocations=calculator_invocations,
        initial_max_force_ev_per_angstrom=initial_max_force_ev_per_angstrom,
        final_max_force_ev_per_angstrom=final_max_force_ev_per_angstrom,
        initial_energy_ev=initial_energy_ev,
        final_energy_ev=final_energy_ev,
        wall_time_seconds=wall_time_seconds,
        isolated_cache_bytes_written=isolated_cache_bytes_written,
        trajectory_schema_version=TRAJECTORY_SCHEMA_VERSION,
        trajectory_frames=trajectory_frames,
        trajectory_sha256=trajectory_sha256,
        terminal_state=terminal_state,
        validation=validation,
        state=state,
        failure_reason=failure_reason,
        receipt_sha256="",
    )
    from dataclasses import replace

    return replace(draft, receipt_sha256=preoptimization_receipt_sha256(draft))


def close_pyscf_handoff(
    *,
    preoptimization: Aimnet2PreoptimizationReceipt,
    aimnet2_output_xyz: bytes,
    pyscf_input_xyz: bytes,
    request_sha256: str,
    runner_source_sha256: str,
) -> PySCFHandoffReceipt:
    """Prove the handoff, or refuse it.  PySCF may start only on ``closed``.

    Every refusal below is a reason PySCF must not run: the label would then be
    computed from a geometry no receipt accounts for.
    """

    from dataclasses import replace

    def refuse(reason: str) -> PySCFHandoffReceipt:
        draft = PySCFHandoffReceipt(
            schema_version=HANDOFF_SCHEMA_VERSION,
            route=preoptimization.route,
            attempt_id=preoptimization.attempt_id,
            endpoint=preoptimization.endpoint,
            charge=preoptimization.charge,
            multiplicity=preoptimization.multiplicity,
            aimnet2_output_xyz_sha256=preoptimization.output_xyz_sha256,
            pyscf_input_xyz_sha256=hashlib.sha256(pyscf_input_xyz).hexdigest(),
            atom_order_sha256=preoptimization.output_atom_order_sha256,
            atom_count=0,
            request_sha256=request_sha256,
            runner_source_sha256=runner_source_sha256,
            preoptimization_receipt_sha256=preoptimization.receipt_sha256,
            handoff_contract_sha256=handoff_contract_sha256(),
            state=HandoffState.REFUSED,
            failure_reason=reason,
            receipt_sha256="",
        )
        return replace(draft, receipt_sha256=handoff_receipt_sha256(draft))

    # The preoptimization record must itself be internally consistent.
    if preoptimization.receipt_sha256 != preoptimization_receipt_sha256(preoptimization):
        return refuse("the preoptimization receipt digest does not match its body")
    if preoptimization.state is not PreoptimizationState.CONVERGED:
        return refuse(f"preoptimization did not converge: {preoptimization.state.value}")
    if not preoptimization.validation.all_gates_passed:
        return refuse("a structural validation gate failed")
    for label, passed in (
        ("atom count", preoptimization.validation.atom_count_preserved),
        ("atom order", preoptimization.validation.atom_order_preserved),
        ("connectivity", preoptimization.validation.connectivity_preserved),
        ("proton host index", preoptimization.validation.proton_host_index_preserved),
    ):
        if not passed:
            return refuse(f"{label} was not preserved")

    # The bytes AIMNet2 wrote must be the bytes it recorded writing.
    if hashlib.sha256(aimnet2_output_xyz).hexdigest() != preoptimization.output_xyz_sha256:
        return refuse("the AIMNet2 output bytes do not match its own receipt")
    # And the bytes PySCF is about to read must be those same bytes.
    if pyscf_input_xyz != aimnet2_output_xyz:
        return refuse("the PySCF input bytes are not the AIMNet2 output bytes")
    order = atom_order_sha256(pyscf_input_xyz)
    if order != preoptimization.output_atom_order_sha256:
        return refuse("the atom order changed between AIMNet2 and PySCF")
    if order == preoptimization.input_atom_order_sha256 and (
        preoptimization.input_atom_order_sha256 != preoptimization.output_atom_order_sha256
    ):  # pragma: no cover - unreachable while both orders are compared above
        return refuse("atom order bookkeeping is inconsistent")
    if preoptimization.endpoint == "cation" and (
        preoptimization.charge != 1 or preoptimization.multiplicity != 1
    ):
        return refuse("cation charge or multiplicity drifted")
    if preoptimization.endpoint == "neutral" and (
        preoptimization.charge != 0 or preoptimization.multiplicity != 1
    ):
        return refuse("neutral charge or multiplicity drifted")

    count = int(pyscf_input_xyz.decode("utf-8").splitlines()[0].strip())
    draft = PySCFHandoffReceipt(
        schema_version=HANDOFF_SCHEMA_VERSION,
        route=preoptimization.route,
        attempt_id=preoptimization.attempt_id,
        endpoint=preoptimization.endpoint,
        charge=preoptimization.charge,
        multiplicity=preoptimization.multiplicity,
        aimnet2_output_xyz_sha256=preoptimization.output_xyz_sha256,
        pyscf_input_xyz_sha256=hashlib.sha256(pyscf_input_xyz).hexdigest(),
        atom_order_sha256=order,
        atom_count=count,
        request_sha256=request_sha256,
        runner_source_sha256=runner_source_sha256,
        preoptimization_receipt_sha256=preoptimization.receipt_sha256,
        handoff_contract_sha256=handoff_contract_sha256(),
        state=HandoffState.CLOSED,
        failure_reason=None,
        receipt_sha256="",
    )
    return replace(draft, receipt_sha256=handoff_receipt_sha256(draft))


def pyscf_may_start(handoff: PySCFHandoffReceipt | None) -> bool:
    """The single gate PySCF is allowed to consult."""

    return (
        handoff is not None
        and handoff.schema_version == HANDOFF_SCHEMA_VERSION
        and handoff.state is HandoffState.CLOSED
        and handoff.failure_reason is None
        and handoff.aimnet2_output_xyz_sha256 == handoff.pyscf_input_xyz_sha256
        and handoff.handoff_contract_sha256 == handoff_contract_sha256()
        and handoff.receipt_sha256 == handoff_receipt_sha256(handoff)
    )


__all__ = [
    "AIMNET2_OPTIMIZER_PROTOCOL",
    "AIMNET2_STRUCTURAL_GATES",
    "AIMNET2_WEIGHT_BYTES",
    "AIMNET2_WEIGHT_FILENAME",
    "AIMNET2_WEIGHT_SHA256",
    "HANDOFF_CONTRACT",
    "HANDOFF_SCHEMA_VERSION",
    "PREOPTIMIZATION_SCHEMA_VERSION",
    "TRAJECTORY_SCHEMA_VERSION",
    "Aimnet2PreoptimizationReceipt",
    "HandoffError",
    "HandoffState",
    "PreoptimizationState",
    "PySCFHandoffReceipt",
    "StructuralValidation",
    "aimnet2_optimizer_protocol_payload",
    "aimnet2_optimizer_protocol_sha256",
    "aimnet2_structural_gates_payload",
    "aimnet2_structural_gates_sha256",
    "atom_order_sha256",
    "build_preoptimization_receipt",
    "close_pyscf_handoff",
    "handoff_contract_payload",
    "handoff_contract_sha256",
    "handoff_receipt_payload",
    "handoff_receipt_sha256",
    "preoptimization_receipt_payload",
    "preoptimization_receipt_sha256",
    "preoptimization_stage_sha256",
    "pyscf_may_start",
]
