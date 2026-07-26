"""Phase 9B supervisor regressions.

No chemistry, no server, no compute, no real supervision. Every test asserts
fail-closed behaviour or route-parity enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from nhc_deprot_ranker.quantum import phase9b_supervisor as supervisor
from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE
from nhc_deprot_ranker.quantum.phase9b_supervisor import (
    ROUTE_ASSISTED,
    ROUTE_DIRECT,
    Phase9BAuthority,
    Phase9BNotAuthorizedError,
    Phase9BSupervisorError,
    run_phase9b_supervisor,
    validate_route_configurations_match,
)

_SRC = "a" * 64
_PROTO = "b" * 64


@dataclass(frozen=True)
class _Atom:
    element: str


@dataclass(frozen=True)
class _Geometry:
    atoms: tuple[_Atom, ...]


@dataclass(frozen=True)
class _Endpoint:
    geometry: _Geometry
    charge: int
    multiplicity: int = 1


@dataclass(frozen=True)
class _Request:
    request_sha256: str
    runner_source_sha256: str
    inchikey: str
    cation: _Endpoint
    neutral: _Endpoint


@dataclass(frozen=True)
class _Launch:
    absolute_deadline_ns: int = 1_000


def _elements(hydrogens: int) -> tuple[str, ...]:
    heavy = ["C"] * 8 + ["N"] + ["F"] * 5 + ["C"] + ["N"] + ["N"] + ["F"] * 4
    return tuple(heavy + ["H"] * hydrogens)


def _endpoint(hydrogens: int, charge: int) -> _Endpoint:
    return _Endpoint(_Geometry(tuple(_Atom(e) for e in _elements(hydrogens))), charge=charge)


def _request(sha: str = "c" * 64, inchikey: str | None = None) -> _Request:
    return _Request(
        request_sha256=sha,
        runner_source_sha256=_SRC,
        inchikey=inchikey or PHASE9B_CANDIDATE.inchikey,
        cation=_endpoint(5, 1),
        neutral=_endpoint(4, 0),
    )


def _authority(route: str = ROUTE_DIRECT, sha: str = "c" * 64) -> Phase9BAuthority:
    return Phase9BAuthority(
        route=route,
        request_sha256=sha,
        runner_source_sha256=_SRC,
        protocol_sha256=_PROTO,
        electron_count=PHASE9B_CANDIDATE.electron_count,
        profile=PHASE9B_CANDIDATE,
    )


def _run(**kw: Any) -> object:
    params: dict[str, Any] = {
        "request": _request(),
        "output_root": Path("/nonexistent/p9b/out"),
        "authority": _authority(),
        "worker_launch": _Launch(),
    }
    params.update(kw)
    request = params.pop("request")
    output_root = params.pop("output_root")
    return run_phase9b_supervisor(request, output_root, **params)


def test_source_gate_is_closed_in_checked_in_source() -> None:
    assert supervisor.EXECUTION_AUTHORIZED is False
    source = Path(supervisor.__file__).read_text(encoding="utf-8")
    assert "EXECUTION_AUTHORIZED: Final[bool] = False" in source


def test_execution_refuses_while_the_gate_is_closed() -> None:
    with pytest.raises(Phase9BNotAuthorizedError, match="not authorized"):
        _run()


def test_gate_refuses_before_touching_the_filesystem(tmp_path: Path) -> None:
    """A closed gate must not depend on any input being readable."""

    existing = tmp_path / "already-there"
    existing.mkdir()
    with pytest.raises(Phase9BNotAuthorizedError, match="not authorized"):
        _run(output_root=existing)


def test_retired_phase8b_identities_are_permanently_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervisor, "EXECUTION_AUTHORIZED", True)
    from nhc_deprot_ranker.quantum import two_endpoint

    monkeypatch.setattr(two_endpoint, "EXECUTION_AUTHORIZED", True)
    with pytest.raises(Phase9BNotAuthorizedError, match="retired"):
        _run(request=_request(inchikey="QXHIEGFUWOLQIJ-UHFFFAOYSA-N"))


@pytest.fixture
def _open_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    from nhc_deprot_ranker.quantum import two_endpoint

    monkeypatch.setattr(supervisor, "EXECUTION_AUTHORIZED", True)
    monkeypatch.setattr(two_endpoint, "EXECUTION_AUTHORIZED", True)


def test_request_hash_disagreement_fails_closed(_open_gates: None) -> None:
    with pytest.raises(Phase9BNotAuthorizedError, match="disagrees with the request"):
        _run(authority=_authority(sha="d" * 64))


def test_runner_source_disagreement_fails_closed(_open_gates: None) -> None:
    bad = replace(_authority(), runner_source_sha256="e" * 64)
    with pytest.raises(Phase9BNotAuthorizedError, match="runner source disagrees"):
        _run(authority=bad)


def test_electron_count_disagreement_fails_closed(_open_gates: None) -> None:
    bad = replace(_authority(), electron_count=120)
    with pytest.raises(Phase9BSupervisorError, match="electron count"):
        _run(authority=bad)


def test_unknown_route_fails_closed(_open_gates: None) -> None:
    with pytest.raises(Phase9BSupervisorError, match="unknown Phase 9B route"):
        _run(authority=_authority(route="sideways"))


def test_existing_output_root_blocks_resume(_open_gates: None, tmp_path: Path) -> None:
    existing = tmp_path / "out"
    existing.mkdir()
    with pytest.raises(Phase9BNotAuthorizedError, match="resume is prohibited"):
        _run(output_root=existing)


def test_bad_endpoint_pair_fails_closed(_open_gates: None) -> None:
    broken = replace(_request(), neutral=_endpoint(3, 0))
    with pytest.raises(Phase9BSupervisorError, match="endpoint validation failed"):
        _run(request=broken)


def test_default_executor_is_the_one_guarded_adapter(_open_gates: None) -> None:
    """``execute=None`` now resolves to the real path instead of a dead end.

    The adapter itself refuses this fake worker launch, which is the point: the
    default is a guarded production path, not an unwired hole. Both gates are
    open in this fixture, so what stops it is the adapter's own validation.
    """

    from nhc_deprot_ranker.quantum import two_endpoint

    with pytest.raises(
        two_endpoint.ExecutionNotAuthorizedError, match="guarded worker launch handshake"
    ):
        _run()


def test_delegation_carries_the_route_specific_attempt_id(_open_gates: None) -> None:
    seen: dict[str, object] = {}

    def fake(request: object, output_root: Path, *, attempt_id: str, worker_launch: object) -> str:
        seen.update(attempt_id=attempt_id, output_root=output_root, worker_launch=worker_launch)
        del request
        return "delegated"

    assert _run(execute=fake) == "delegated"
    direct_attempt = seen["attempt_id"]
    assert direct_attempt == supervisor.ROUTE_D_ATTEMPT_ID

    seen.clear()
    _run(authority=_authority(route=ROUTE_ASSISTED), execute=fake)
    assisted_attempt = seen["attempt_id"]
    assert assisted_attempt == supervisor.ROUTE_A_ATTEMPT_ID
    # The two asserts above already pin each route to a distinct constant.


def test_route_parity_accepts_two_matched_distinct_attempts() -> None:
    validate_route_configurations_match(
        _authority(ROUTE_DIRECT, sha="c" * 64), _authority(ROUTE_ASSISTED, sha="f" * 64)
    )


def test_route_parity_rejects_differing_protocols() -> None:
    assisted = replace(_authority(ROUTE_ASSISTED, sha="f" * 64), protocol_sha256="9" * 64)
    with pytest.raises(Phase9BSupervisorError, match="protocols differ"):
        validate_route_configurations_match(_authority(ROUTE_DIRECT), assisted)


def test_route_parity_rejects_differing_runner_sources() -> None:
    assisted = replace(_authority(ROUTE_ASSISTED, sha="f" * 64), runner_source_sha256="9" * 64)
    with pytest.raises(Phase9BSupervisorError, match="runner source closures differ"):
        validate_route_configurations_match(_authority(ROUTE_DIRECT), assisted)


def test_route_parity_rejects_one_request_reused_as_both_routes() -> None:
    with pytest.raises(Phase9BSupervisorError, match="distinct attempts"):
        validate_route_configurations_match(
            _authority(ROUTE_DIRECT, sha="c" * 64), _authority(ROUTE_ASSISTED, sha="c" * 64)
        )


def test_route_parity_rejects_swapped_or_duplicated_labels() -> None:
    with pytest.raises(Phase9BSupervisorError, match="route labels"):
        validate_route_configurations_match(
            _authority(ROUTE_ASSISTED, sha="c" * 64), _authority(ROUTE_DIRECT, sha="f" * 64)
        )


def test_phase9b_modules_are_hash_bound_in_the_runner_source_closure() -> None:
    """The supervisor entry is hash-bound like the Phase 8B entry it parallels.

    run_phase8b_supervisor lives in two_endpoint.py, which is inside the closure,
    so the Phase 9B supervisor entry must be bound too, or its content could
    change without changing runner_source_sha256.
    """

    from nhc_deprot_ranker.quantum import two_endpoint

    closure = two_endpoint._RUNNER_SOURCE_RELATIVE_PATHS  # pyright: ignore[reportPrivateUsage]
    assert "nhc_deprot_ranker/quantum/phase9b_supervisor.py" in closure
    assert "nhc_deprot_ranker/quantum/phase9b_authority.py" in closure
    assert "nhc_deprot_ranker/quantum/phase9b_permit.py" in closure
    assert "nhc_deprot_ranker/quantum/phase9b_resources.py" in closure


def test_supervision_logic_is_delegated_not_reimplemented() -> None:
    """One copy of the process, deadline, and reaping logic, not two."""

    source = Path(supervisor.__file__).read_text(encoding="utf-8")
    for forbidden in ("SIGKILL", "waitid", "setsid", "killpg", "Popen", "fork"):
        assert forbidden not in source, forbidden


def test_module_declares_no_label_and_imports_no_chemistry() -> None:
    source = Path(supervisor.__file__).read_text(encoding="utf-8").lower()
    for forbidden in ("import pyscf", "import torch", "import aimnet", "627.509474", "kcal"):
        assert forbidden not in source, forbidden
