"""Phase 9B AIMNet2-to-PySCF handoff regressions.

No chemistry, no server, no compute, no AIMNet2, no PySCF. The preoptimization
receipt is constructed from bytes; what is under test is whether the handoff can
be proved closed, and whether PySCF is allowed to start.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from nhc_deprot_ranker.quantum import phase9b_handoff as hf
from nhc_deprot_ranker.quantum.phase9b_handoff import (
    AIMNET2_WEIGHT_SHA256,
    Aimnet2PreoptimizationReceipt,
    HandoffError,
    HandoffState,
    PreoptimizationState,
    StructuralValidation,
    aimnet2_optimizer_protocol_sha256,
    aimnet2_structural_gates_sha256,
    atom_order_sha256,
    build_preoptimization_receipt,
    close_pyscf_handoff,
    handoff_contract_sha256,
    handoff_receipt_payload,
    handoff_receipt_sha256,
    preoptimization_receipt_payload,
    preoptimization_receipt_sha256,
    preoptimization_stage_sha256,
    pyscf_may_start,
)
from nhc_deprot_ranker.quantum.phase9b_permit import ROUTE_ASSISTED, ROUTE_ATTEMPT_IDS

_ATTEMPT = ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED]
_REQUEST = "1" * 64
_SOURCE = "2" * 64


def _xyz(*, spacing: float = 1.4, elements: tuple[str, ...] | None = None) -> bytes:
    order = elements or ("C", "N", "C", "N", "H", "H")
    lines = [str(len(order)), "endpoint"]
    for index, element in enumerate(order):
        lines.append(f"{element} {index * spacing:.6f} 0.000000 0.000000")
    return ("\n".join(lines) + "\n").encode()


def _validation(**kw: object) -> StructuralValidation:
    base: dict[str, object] = {
        "total_rmsd_angstrom": 0.31,
        "max_single_atom_displacement_angstrom": 0.62,
        "c2_n1_bond_change_angstrom": 0.02,
        "c2_n3_bond_change_angstrom": 0.03,
        "ring_angle_change_degrees": 1.4,
        "atom_count_preserved": True,
        "atom_order_preserved": True,
        "connectivity_preserved": True,
        "proton_host_index_preserved": True,
        "all_gates_passed": True,
    }
    base.update(kw)
    return StructuralValidation(**base)  # type: ignore[arg-type]


def _preopt(
    *,
    input_xyz: bytes | None = None,
    output_xyz: bytes | None = None,
    endpoint: str = "cation",
    charge: int = 1,
    state: PreoptimizationState = PreoptimizationState.CONVERGED,
    validation: StructuralValidation | None = None,
) -> Aimnet2PreoptimizationReceipt:
    return build_preoptimization_receipt(
        route=ROUTE_ASSISTED,
        attempt_id=_ATTEMPT,
        endpoint=endpoint,
        charge=charge,
        multiplicity=1,
        input_xyz=input_xyz if input_xyz is not None else _xyz(),
        output_xyz=output_xyz if output_xyz is not None else _xyz(spacing=1.38),
        optimizer_steps=41,
        energy_evaluations=44,
        force_evaluations=44,
        initial_max_force_ev_per_angstrom=1.82,
        final_max_force_ev_per_angstrom=0.041,
        wall_time_seconds=63.5,
        isolated_cache_bytes_written=10_485_760,
        validation=validation if validation is not None else _validation(),
        state=state,
    )


def _close(
    preopt: Aimnet2PreoptimizationReceipt,
    *,
    output_xyz: bytes | None = None,
    pyscf_xyz: bytes | None = None,
) -> hf.PySCFHandoffReceipt:
    produced = output_xyz if output_xyz is not None else _xyz(spacing=1.38)
    return close_pyscf_handoff(
        preoptimization=preopt,
        aimnet2_output_xyz=produced,
        pyscf_input_xyz=pyscf_xyz if pyscf_xyz is not None else produced,
        request_sha256=_REQUEST,
        runner_source_sha256=_SOURCE,
    )


# --- the frozen stage identity ----------------------------------------------


def test_the_stage_identity_is_deterministic_and_hash_closed() -> None:
    assert preoptimization_stage_sha256() == preoptimization_stage_sha256()
    for digest in (
        aimnet2_optimizer_protocol_sha256(),
        aimnet2_structural_gates_sha256(),
        handoff_contract_sha256(),
        preoptimization_stage_sha256(),
    ):
        assert len(digest) == 64
    assert (
        len(
            {
                aimnet2_optimizer_protocol_sha256(),
                aimnet2_structural_gates_sha256(),
                handoff_contract_sha256(),
            }
        )
        == 3
    )


def test_the_handoff_contract_forbids_every_alternative_to_byte_identity() -> None:
    contract = hf.handoff_contract_payload()
    assert contract["comparison"] == "byte_identity"
    for forbidden in (
        "reserialization_allowed",
        "manual_edit_allowed",
        "atom_reordering_allowed",
        "regeneration_allowed",
        "external_preparation_step_allowed",
    ):
        assert contract[forbidden] is False


def test_the_module_imports_no_backend() -> None:
    tree = ast.parse(Path(hf.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"torch", "ase", "aimnet", "pyscf", "numpy"})


# --- atom order --------------------------------------------------------------


def test_atom_order_ignores_coordinates_and_catches_reordering() -> None:
    """Coordinates are supposed to move; the order is not."""

    assert atom_order_sha256(_xyz()) == atom_order_sha256(_xyz(spacing=1.38))
    swapped = atom_order_sha256(_xyz(elements=("N", "C", "C", "N", "H", "H")))
    assert swapped != atom_order_sha256(_xyz())


@pytest.mark.parametrize(
    "raw",
    [b"", b"1\n", b"notanumber\ncomment\nC 0 0 0\n", b"5\ncomment\nC 0 0 0\n", b"\xff\xfe"],
)
def test_malformed_xyz_is_refused(raw: bytes) -> None:
    with pytest.raises(HandoffError):
        atom_order_sha256(raw)


# --- the closed path ---------------------------------------------------------


def test_a_clean_handoff_closes_and_lets_pyscf_start() -> None:
    preopt = _preopt()
    handoff = _close(preopt)
    assert handoff.state is HandoffState.CLOSED
    assert handoff.failure_reason is None
    assert handoff.aimnet2_output_xyz_sha256 == handoff.pyscf_input_xyz_sha256
    assert handoff.atom_count == 6
    assert handoff.preoptimization_receipt_sha256 == preopt.receipt_sha256
    assert handoff.receipt_sha256 == handoff_receipt_sha256(handoff)
    assert pyscf_may_start(handoff)


def test_the_preoptimization_receipt_records_every_registered_field() -> None:
    body = preoptimization_receipt_payload(_preopt())
    assert body["schema_version"] == hf.PREOPTIMIZATION_SCHEMA_VERSION
    assert body["weight_sha256"] == AIMNET2_WEIGHT_SHA256
    assert body["optimizer_protocol_sha256"] == aimnet2_optimizer_protocol_sha256()
    assert body["structural_gates_sha256"] == aimnet2_structural_gates_sha256()
    for key in (
        "input_xyz_sha256",
        "output_xyz_sha256",
        "input_atom_order_sha256",
        "output_atom_order_sha256",
    ):
        assert len(str(body[key])) == 64
    for key in ("optimizer_steps", "energy_evaluations", "force_evaluations"):
        assert isinstance(body[key], int)
    validation = body["validation"]
    assert isinstance(validation, dict)
    assert validation["all_gates_passed"] is True
    assert body["isolated_cache_bytes_written"] == 10_485_760
    assert body["receipt_sha256"] == preoptimization_receipt_sha256(_preopt())
    # Serializable, and no PySCF result or label anywhere.
    text = json.dumps(body, sort_keys=True)
    for banned in ("hartree", "kcal", "dft_deprot", "scf", "label"):
        assert banned not in text


# --- every reason PySCF must not start ---------------------------------------


def test_a_geometry_edited_between_the_stages_is_refused() -> None:
    """The heart of the contract: same bytes, or no PySCF."""

    preopt = _preopt()
    produced = _xyz(spacing=1.38)
    edited = produced.replace(b"1.380000", b"1.380001")
    assert edited != produced
    handoff = _close(preopt, output_xyz=produced, pyscf_xyz=edited)
    assert handoff.state is HandoffState.REFUSED
    assert "not the AIMNet2 output bytes" in (handoff.failure_reason or "")
    assert not pyscf_may_start(handoff)


def test_a_reserialized_geometry_is_refused_even_if_equivalent() -> None:
    preopt = _preopt()
    produced = _xyz(spacing=1.38)
    reserialized = produced.replace(b" 0.000000 0.000000", b"  0.0  0.0")
    handoff = _close(preopt, output_xyz=produced, pyscf_xyz=reserialized)
    assert handoff.state is HandoffState.REFUSED
    assert not pyscf_may_start(handoff)


def test_output_bytes_that_disagree_with_the_receipt_are_refused() -> None:
    preopt = _preopt()
    other = _xyz(spacing=1.31)
    handoff = _close(preopt, output_xyz=other, pyscf_xyz=other)
    assert handoff.state is HandoffState.REFUSED
    assert "do not match its own receipt" in (handoff.failure_reason or "")


def test_atom_reordering_between_the_stages_is_refused() -> None:
    reordered = _xyz(spacing=1.38, elements=("N", "C", "C", "N", "H", "H"))
    preopt = _preopt(output_xyz=reordered)
    # The receipt itself records the reordered order, so the gate that bites is
    # the structural one: order preservation is a preregistered gate.
    broken = _preopt(output_xyz=reordered, validation=_validation(atom_order_preserved=False))
    handoff = close_pyscf_handoff(
        preoptimization=broken,
        aimnet2_output_xyz=reordered,
        pyscf_input_xyz=reordered,
        request_sha256=_REQUEST,
        runner_source_sha256=_SOURCE,
    )
    assert handoff.state is HandoffState.REFUSED
    assert "atom order was not preserved" in (handoff.failure_reason or "")
    assert preopt.output_atom_order_sha256 != preopt.input_atom_order_sha256


@pytest.mark.parametrize(
    ("gate", "match"),
    [
        ("all_gates_passed", "a structural validation gate failed"),
        ("atom_count_preserved", "atom count was not preserved"),
        ("connectivity_preserved", "connectivity was not preserved"),
        ("proton_host_index_preserved", "proton host index was not preserved"),
    ],
)
def test_a_failed_structural_gate_stops_pyscf(gate: str, match: str) -> None:
    handoff = _close(_preopt(validation=_validation(**{gate: False})))
    assert handoff.state is HandoffState.REFUSED
    assert match in (handoff.failure_reason or "")
    assert not pyscf_may_start(handoff)


@pytest.mark.parametrize(
    "state",
    [
        PreoptimizationState.NOT_RUN,
        PreoptimizationState.NOT_CONVERGED,
        PreoptimizationState.GATE_FAILED,
        PreoptimizationState.FAILED,
    ],
)
def test_an_unconverged_preoptimization_stops_pyscf(state: PreoptimizationState) -> None:
    handoff = _close(_preopt(state=state))
    assert handoff.state is HandoffState.REFUSED
    assert "did not converge" in (handoff.failure_reason or "")


@pytest.mark.parametrize(
    ("endpoint", "charge"),
    [("cation", 0), ("cation", 2), ("neutral", 1), ("neutral", -1)],
)
def test_charge_or_multiplicity_drift_stops_pyscf(endpoint: str, charge: int) -> None:
    handoff = _close(_preopt(endpoint=endpoint, charge=charge))
    assert handoff.state is HandoffState.REFUSED
    assert "charge or multiplicity drifted" in (handoff.failure_reason or "")


def test_an_edited_preoptimization_receipt_is_refused() -> None:
    """Its digest covers the fields the handoff relies on."""

    preopt = _preopt()
    lied = dataclasses.replace(preopt, state=PreoptimizationState.CONVERGED, optimizer_steps=9999)
    assert lied.receipt_sha256 != preoptimization_receipt_sha256(lied)
    handoff = _close(lied)
    assert handoff.state is HandoffState.REFUSED
    assert "digest does not match its body" in (handoff.failure_reason or "")


def test_an_unknown_endpoint_is_refused() -> None:
    with pytest.raises(HandoffError, match="unknown endpoint"):
        _preopt(endpoint="dication")


# --- the gate itself ---------------------------------------------------------


def test_the_pyscf_gate_refuses_a_forged_or_absent_handoff() -> None:
    assert not pyscf_may_start(None)
    good = _close(_preopt())
    assert pyscf_may_start(good)

    # A genuinely refused handoff carries a *valid* digest, so the gate cannot
    # rely on the digest check alone to stop it.
    refused = _close(_preopt(state=PreoptimizationState.FAILED))
    assert refused.receipt_sha256 == handoff_receipt_sha256(refused)
    assert not pyscf_may_start(refused)

    for broken in (
        dataclasses.replace(good, state=HandoffState.REFUSED),
        dataclasses.replace(good, failure_reason="anything"),
        dataclasses.replace(good, receipt_sha256="0" * 64),
        dataclasses.replace(good, handoff_contract_sha256="1" * 64),
        dataclasses.replace(good, pyscf_input_xyz_sha256="2" * 64),
        dataclasses.replace(good, schema_version="other"),
    ):
        assert not pyscf_may_start(broken)


def test_a_refused_handoff_still_produces_an_auditable_record() -> None:
    handoff = _close(_preopt(state=PreoptimizationState.FAILED))
    body = handoff_receipt_payload(handoff)
    assert body["state"] == "refused"
    assert body["failure_reason"]
    assert body["receipt_sha256"] == handoff_receipt_sha256(handoff)
    assert body["handoff_contract_sha256"] == handoff_contract_sha256()


def test_the_receipts_carry_no_scientific_result() -> None:
    for body in (
        preoptimization_receipt_payload(_preopt()),
        handoff_receipt_payload(_close(_preopt())),
    ):
        text = json.dumps(body, sort_keys=True).lower()
        for banned in ("hartree", "kcal", "electronic_energy", "deprot", "converged_energy"):
            assert banned not in text


def test_the_output_digest_is_the_bytes_that_were_produced() -> None:
    produced = _xyz(spacing=1.38)
    preopt = _preopt(output_xyz=produced)
    assert preopt.output_xyz_sha256 == hashlib.sha256(produced).hexdigest()
    assert preopt.input_xyz_sha256 == hashlib.sha256(_xyz()).hexdigest()
    assert preopt.input_xyz_sha256 != preopt.output_xyz_sha256
