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

from nhc_deprot_ranker.quantum import phase8b_permit as permit_module
from nhc_deprot_ranker.quantum import phase9b_authority as p9b_authority
from nhc_deprot_ranker.quantum import phase9b_supervisor as p9b_supervisor
from nhc_deprot_ranker.quantum import two_endpoint as runner
from nhc_deprot_ranker.quantum import worker
from nhc_deprot_ranker.quantum.worker import (
    PHASE8B_WORKER_PROFILE,
    PHASE9B_WORKER_PROFILE,
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


def test_profile_table_holds_exactly_the_two_known_chains() -> None:
    assert WORKER_AUTHORITY_PROFILES == (PHASE8B_WORKER_PROFILE, PHASE9B_WORKER_PROFILE)
    all_attempts = [a for p in WORKER_AUTHORITY_PROFILES for a in p.attempt_ids]
    assert len(all_attempts) == len(set(all_attempts)), "attempt ids must be globally unique"


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
    assert PHASE9B_WORKER_PROFILE.inchikey == candidate.inchikey
    assert PHASE9B_WORKER_PROFILE.electron_count == candidate.electron_count == 160
    assert PHASE9B_WORKER_PROFILE.request_id == p9b_supervisor.REQUEST_ID
    assert PHASE9B_WORKER_PROFILE.attempt_ids == (
        p9b_supervisor.ROUTE_D_ATTEMPT_ID,
        p9b_supervisor.ROUTE_A_ATTEMPT_ID,
    )


def test_resolver_maps_each_attempt_to_its_profile_and_rejects_unknowns() -> None:
    assert _resolve_worker_profile("attempt-phase8b-qxh-v001") is PHASE8B_WORKER_PROFILE
    assert _resolve_worker_profile(p9b_supervisor.ROUTE_D_ATTEMPT_ID) is PHASE9B_WORKER_PROFILE
    assert _resolve_worker_profile(p9b_supervisor.ROUTE_A_ATTEMPT_ID) is PHASE9B_WORKER_PROFILE
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
        expected_electron_count=PHASE9B_WORKER_PROFILE.electron_count,
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
            expected_electron_count=PHASE9B_WORKER_PROFILE.electron_count,
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


class _FakeRequest:
    execution_authorized = True


def test_unwired_phase9b_profile_refuses_before_any_permit_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runner, "EXECUTION_AUTHORIZED", True)
    monkeypatch.setattr(runner, "load_two_endpoint_request", lambda path: _FakeRequest())

    def _bomb(*args: object, **kwargs: object) -> object:
        raise AssertionError("permit must not be read for an unwired profile")

    monkeypatch.setattr(permit_module, "load_consumed_phase8b_permit", _bomb)
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="not wired for execution"):
        worker.main(_full_argv(p9b_supervisor.ROUTE_D_ATTEMPT_ID, tmp_path))


def test_unknown_attempt_refuses_before_any_permit_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runner, "EXECUTION_AUTHORIZED", True)
    monkeypatch.setattr(runner, "load_two_endpoint_request", lambda path: _FakeRequest())

    def _bomb(*args: object, **kwargs: object) -> object:
        raise AssertionError("permit must not be read for an unknown attempt")

    monkeypatch.setattr(permit_module, "load_consumed_phase8b_permit", _bomb)
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="no worker authority profile"):
        worker.main(_full_argv("attempt-nowhere", tmp_path))


def test_phase8b_attempt_still_reaches_the_permit_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Profile resolution must not block the historical live path."""

    monkeypatch.setattr(runner, "EXECUTION_AUTHORIZED", True)
    monkeypatch.setattr(runner, "load_two_endpoint_request", lambda path: _FakeRequest())

    class _Marker(RuntimeError):
        pass

    def _reached(*args: object, **kwargs: object) -> object:
        raise _Marker("PERMIT_STAGE_REACHED")

    monkeypatch.setattr(permit_module, "load_consumed_phase8b_permit", _reached)
    with pytest.raises(_Marker, match="PERMIT_STAGE_REACHED"):
        worker.main(_full_argv("attempt-phase8b-qxh-v001", tmp_path))


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
