"""Worker authority profile regressions (Option C, step 1).

No chemistry, no server, no compute. These tests pin the parameterization of
the guarded worker: electron count and CPU affinity flow from a source-frozen
profile selected by exact attempt identity, the Phase 8B profile reproduces the
historical constants verbatim, and the Phase 9B profile is registered but
refuses execution until permit and capability wiring exist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nhc_deprot_ranker.quantum import phase9b_authority as p9b_authority
from nhc_deprot_ranker.quantum import phase9b_permit as p9b_permit_module
from nhc_deprot_ranker.quantum import phase9b_supervisor as p9b_supervisor
from nhc_deprot_ranker.quantum import two_endpoint as runner
from nhc_deprot_ranker.quantum import worker
from nhc_deprot_ranker.quantum.worker import (
    PHASE8B_WORKER_PROFILE,
    PHASE9B_DIRECT_WORKER_PROFILE,
    WORKER_AUTHORITY_PROFILES,
    _resolve_worker_profile,
)


def _endpoint_pair(
    *, electron_count: int, hydrogens_neutral: int = 4
) -> tuple[runner.EndpointRequest, runner.EndpointRequest]:
    """Build a C9 F9 N3 pair whose stored counts match the requested electrons."""

    heavy = tuple(["C"] * 9 + ["F"] * 9 + ["N"] * 3)
    neutral_elements = heavy + tuple(["H"] * hydrogens_neutral)
    cation_elements = heavy + tuple(["H"] * (hydrogens_neutral + 1))
    neutral_geometry = runner.XYZGeometry(
        tuple(runner.XYZAtom(e, float(i), 0.0, 0.0) for i, e in enumerate(neutral_elements))
    )
    cation_geometry = runner.XYZGeometry(
        tuple(runner.XYZAtom(e, float(i), 0.0, 0.0) for i, e in enumerate(cation_elements))
    )
    cation = runner.EndpointRequest(
        name="cation",
        xyz_relative_path="cation.xyz",
        xyz_path=Path("cation.xyz"),
        xyz_sha256="0" * 64,
        charge=1,
        multiplicity=1,
        electron_count=electron_count,
        geometry=cation_geometry,
    )
    neutral = runner.EndpointRequest(
        name="neutral",
        xyz_relative_path="neutral.xyz",
        xyz_path=Path("neutral.xyz"),
        xyz_sha256="1" * 64,
        charge=0,
        multiplicity=1,
        electron_count=electron_count,
        geometry=neutral_geometry,
    )
    return cation, neutral


def test_profile_table_holds_exactly_the_three_exact_attempts() -> None:
    """Two exact-attempt Phase 9B profiles, not one profile branching on route."""

    assert len(WORKER_AUTHORITY_PROFILES) == 3
    assert {profile.profile_id for profile in WORKER_AUTHORITY_PROFILES} == {
        "phase8b-qxh-smoke",
        "phase9b-lbnp-direct",
        "phase9b-lbnp-assisted",
    }
    # Each binds exactly one attempt, so no profile can serve two routes.
    for profile in WORKER_AUTHORITY_PROFILES:
        assert len(profile.attempt_ids) == 1
    seen = [profile.attempt_ids[0] for profile in WORKER_AUTHORITY_PROFILES]
    assert len(set(seen)) == 3


def test_phase8b_profile_reproduces_the_historical_constants_verbatim() -> None:
    from nhc_deprot_ranker.quantum.phase8b_authority import FROZEN_ELECTRON_COUNT

    assert PHASE8B_WORKER_PROFILE.request_id == "phase8b-qxh-smoke-v001"
    assert PHASE8B_WORKER_PROFILE.inchikey == "QXHIEGFUWOLQIJ-UHFFFAOYSA-N"
    assert PHASE8B_WORKER_PROFILE.attempt_ids == ("attempt-phase8b-qxh-v001",)
    assert PHASE8B_WORKER_PROFILE.electron_count == FROZEN_ELECTRON_COUNT == 120
    assert PHASE8B_WORKER_PROFILE.allowed_cpus == frozenset({0, 1, 2, 3})


def test_phase9b_profile_agrees_with_authority_and_supervisor_modules() -> None:
    """The profile duplicates closure-external constants; keep them honest."""

    candidate = p9b_authority.PHASE9B_CANDIDATE
    assert PHASE9B_DIRECT_WORKER_PROFILE.inchikey == candidate.inchikey
    assert PHASE9B_DIRECT_WORKER_PROFILE.electron_count == candidate.electron_count == 160
    assert PHASE9B_DIRECT_WORKER_PROFILE.request_id == p9b_supervisor.REQUEST_ID
    assert PHASE9B_DIRECT_WORKER_PROFILE.attempt_ids == (p9b_supervisor.ROUTE_D_ATTEMPT_ID,)
    assert worker.PHASE9B_ASSISTED_WORKER_PROFILE.attempt_ids == (
        p9b_supervisor.ROUTE_A_ATTEMPT_ID,
    )
    # Same request and candidate, different route and different runtime.
    assert (
        worker.PHASE9B_ASSISTED_WORKER_PROFILE.request_id
        == PHASE9B_DIRECT_WORKER_PROFILE.request_id
    )
    assert PHASE9B_DIRECT_WORKER_PROFILE.route != worker.PHASE9B_ASSISTED_WORKER_PROFILE.route
    assert (
        PHASE9B_DIRECT_WORKER_PROFILE.execution_adapter
        is not worker.PHASE9B_ASSISTED_WORKER_PROFILE.execution_adapter
    )


def test_resolver_maps_each_attempt_to_its_profile_and_rejects_unknowns() -> None:
    assert _resolve_worker_profile("attempt-phase8b-qxh-v001") is PHASE8B_WORKER_PROFILE
    assert (
        _resolve_worker_profile(p9b_supervisor.ROUTE_D_ATTEMPT_ID) is PHASE9B_DIRECT_WORKER_PROFILE
    )
    assert (
        _resolve_worker_profile(p9b_supervisor.ROUTE_A_ATTEMPT_ID)
        is worker.PHASE9B_ASSISTED_WORKER_PROFILE
    )
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="no worker authority profile"):
        _resolve_worker_profile("attempt-nowhere")


def test_phase9b_shaped_pair_fails_against_the_phase8b_electron_count() -> None:
    cation, neutral = _endpoint_pair(electron_count=160)
    with pytest.raises(runner.RequestValidationError):
        runner._validate_endpoint_pair_electrons(  # pyright: ignore[reportPrivateUsage]
            cation,
            neutral,
            expected_electron_count=PHASE8B_WORKER_PROFILE.electron_count,
        )


def test_phase9b_pair_passes_against_its_own_profile_count() -> None:
    cation, neutral = _endpoint_pair(electron_count=160)
    result = runner._validate_endpoint_pair_electrons(  # pyright: ignore[reportPrivateUsage]
        cation,
        neutral,
        expected_electron_count=PHASE9B_DIRECT_WORKER_PROFILE.electron_count,
    )
    assert result == 160


def test_phase8b_shaped_pair_fails_against_the_phase9b_electron_count() -> None:
    neutral_geometry = runner.XYZGeometry(
        tuple(runner.XYZAtom("C", float(i), 0.0, 0.0) for i in range(20))
    )
    cation_geometry = runner.XYZGeometry(
        (*neutral_geometry.atoms, runner.XYZAtom("H", 0.0, 1.0, 0.0))
    )
    cation = runner.EndpointRequest(
        name="cation",
        xyz_relative_path="cation.xyz",
        xyz_path=Path("cation.xyz"),
        xyz_sha256="0" * 64,
        charge=1,
        multiplicity=1,
        electron_count=120,
        geometry=cation_geometry,
    )
    neutral = runner.EndpointRequest(
        name="neutral",
        xyz_relative_path="neutral.xyz",
        xyz_path=Path("neutral.xyz"),
        xyz_sha256="1" * 64,
        charge=0,
        multiplicity=1,
        electron_count=120,
        geometry=neutral_geometry,
    )
    with pytest.raises(runner.RequestValidationError):
        runner._validate_endpoint_pair_electrons(  # pyright: ignore[reportPrivateUsage]
            cation,
            neutral,
            expected_electron_count=PHASE9B_DIRECT_WORKER_PROFILE.electron_count,
        )


def _full_argv(attempt_id: str, tmp_path: Path) -> list[str]:
    return [
        "--request-path",
        str(tmp_path / "request.json"),
        "--output-root",
        str(tmp_path / "scratch"),
        "--attempt-id",
        attempt_id,
        "--consumed-permit-path",
        str(tmp_path / "permit.json"),
        "--expected-permit-sha256",
        "a" * 64,
        "--expected-request-sha256",
        "b" * 64,
        "--expected-runner-source-sha256",
        "c" * 64,
        "--expected-payload-manifest-sha256",
        "d" * 64,
        "--expected-transport-inventory-sha256",
        "e" * 64,
        "--compute-claim-path",
        str(tmp_path / "claim.json"),
        "--authorized-output-root",
        str(tmp_path / "authorized"),
        "--absolute-deadline-ns",
        "1000",
        "--release-token",
        "token",
    ]


def _endpoint_pair_120() -> tuple[runner.EndpointRequest, runner.EndpointRequest]:
    """C20 skeleton: recomputes to exactly 120 electrons for both endpoints."""

    neutral_geometry = runner.XYZGeometry(
        tuple(runner.XYZAtom("C", float(i), 0.0, 0.0) for i in range(20))
    )
    cation_geometry = runner.XYZGeometry(
        (*neutral_geometry.atoms, runner.XYZAtom("H", 0.0, 1.0, 0.0))
    )
    cation = runner.EndpointRequest(
        name="cation",
        xyz_relative_path="cation.xyz",
        xyz_path=Path("cation.xyz"),
        xyz_sha256="0" * 64,
        charge=1,
        multiplicity=1,
        electron_count=120,
        geometry=cation_geometry,
    )
    neutral = runner.EndpointRequest(
        name="neutral",
        xyz_relative_path="neutral.xyz",
        xyz_path=Path("neutral.xyz"),
        xyz_sha256="1" * 64,
        charge=0,
        multiplicity=1,
        electron_count=120,
        geometry=neutral_geometry,
    )
    return cation, neutral


class _FakeConsumed9B(p9b_permit_module.ConsumedPhase9BPermit):
    """Satisfies the profile's declared consumed-permit type without file I/O."""

    def __init__(self) -> None:
        pass


class _FakeAuthority9B(p9b_permit_module.Phase9BExactAuthority):
    """Satisfies the profile's declared authority type."""

    def __init__(self) -> None:
        pass


def test_each_profile_carries_its_own_capability_identity_key() -> None:
    assert PHASE8B_WORKER_PROFILE.capability_identity_key == "phase8b-qxh-smoke"
    assert PHASE9B_DIRECT_WORKER_PROFILE.capability_identity_key == "phase9b-lbnp-paired-smoke"
    assert (
        PHASE8B_WORKER_PROFILE.capability_identity_key
        != PHASE9B_DIRECT_WORKER_PROFILE.capability_identity_key
    )
    registry = runner._CAPABILITY_IDENTITY_EXPECTATIONS  # pyright: ignore[reportPrivateUsage]
    for profile in WORKER_AUTHORITY_PROFILES:
        assert profile.capability_identity_key in registry


def test_only_phase8b_uses_the_frozen_worker_match() -> None:
    """Phase 9B's validator checks the frozen constants inline instead."""

    assert PHASE8B_WORKER_PROFILE.uses_frozen_worker_match is True
    assert PHASE9B_DIRECT_WORKER_PROFILE.uses_frozen_worker_match is False


def test_each_profile_reloads_through_its_own_chain() -> None:
    assert (
        PHASE8B_WORKER_PROFILE.reload_permit_and_authority
        is worker._reload_phase8b_permit_and_authority
    )
    assert (
        PHASE9B_DIRECT_WORKER_PROFILE.reload_permit_and_authority
        is worker._reload_phase9b_permit_and_authority
    )


def test_reload_adapters_reject_a_foreign_permit() -> None:
    for reload in (
        worker._reload_phase8b_permit_and_authority,
        worker._reload_phase9b_permit_and_authority,
    ):
        with pytest.raises(runner.ExecutionNotAuthorizedError, match="foreign permit"):
            reload(
                consumed=object(),
                request=object(),
                output_root=Path("/nonexistent"),
                attempt_id="attempt-phase8b-qxh-v001",
            )


def test_worker_source_no_longer_hard_codes_the_phase8b_constants() -> None:
    source = Path(worker.__file__).read_text(encoding="utf-8")
    assert "_validate_frozen_120_electron_pair" not in source
    # The literal CPU set may appear only in profile definitions, never at the
    # claim-validation call site.
    assert "expected_allowed_cpus=frozenset" not in source
    assert "expected_allowed_cpus=profile.allowed_cpus" in source
    assert "expected_electron_count=profile.electron_count" in source


def test_profiles_live_inside_the_runner_source_closure() -> None:
    """Profile data must be hash-bound, not editable outside the closure."""

    closure = runner._RUNNER_SOURCE_RELATIVE_PATHS  # pyright: ignore[reportPrivateUsage]
    assert "nhc_deprot_ranker/quantum/worker.py" in closure
    assert "class WorkerAuthorityProfile" in Path(worker.__file__).read_text(encoding="utf-8")


def test_each_profile_declares_the_types_its_own_chain_produces() -> None:
    """Caught by mutation testing: a wrong type here is latent until capability
    wiring, because the type gate lives in the claim validator the Phase 9B path
    does not yet reach. Assert it directly so it cannot rot.
    """

    from nhc_deprot_ranker.quantum.phase8b_authority import ExactPhase8BAuthority
    from nhc_deprot_ranker.quantum.phase8b_permit import ConsumedPhase8BPermit
    from nhc_deprot_ranker.quantum.phase9b_permit import (
        ConsumedPhase9BPermit,
        Phase9BExactAuthority,
    )

    assert PHASE8B_WORKER_PROFILE.consumed_permit_type is ConsumedPhase8BPermit
    assert PHASE8B_WORKER_PROFILE.authority_type is ExactPhase8BAuthority
    assert PHASE9B_DIRECT_WORKER_PROFILE.consumed_permit_type is ConsumedPhase9BPermit
    assert PHASE9B_DIRECT_WORKER_PROFILE.authority_type is Phase9BExactAuthority

    eight = {PHASE8B_WORKER_PROFILE.consumed_permit_type, PHASE8B_WORKER_PROFILE.authority_type}
    nine = {
        PHASE9B_DIRECT_WORKER_PROFILE.consumed_permit_type,
        PHASE9B_DIRECT_WORKER_PROFILE.authority_type,
    }
    assert not eight & nine, "the two chains must not share a permit or authority type"


def test_each_profile_dispatches_to_its_own_loader() -> None:
    assert (
        PHASE8B_WORKER_PROFILE.load_permit_and_authority
        is worker._load_phase8b_permit_and_authority
    )
    assert (
        PHASE9B_DIRECT_WORKER_PROFILE.load_permit_and_authority
        is worker._load_phase9b_permit_and_authority
    )


def test_phase9b_adapter_rejects_an_attempt_id_outside_the_route_table(tmp_path: Path) -> None:
    """Defence in depth: the resolver normally filters these out first, but the
    adapter must not index blindly if a future profile lists an unmapped attempt.
    """

    with pytest.raises(runner.ExecutionNotAuthorizedError, match="exactly one route"):
        worker._load_phase9b_permit_and_authority(
            consumed_path=tmp_path / "permit.json",
            expected_permit_sha256="a" * 64,
            expected_request_sha256="b" * 64,
            expected_runner_source_sha256="c" * 64,
            expected_payload_manifest_sha256="d" * 64,
            request=object(),
            output_root=tmp_path / "out",
            attempt_id="attempt-not-a-phase9b-route",
        )
