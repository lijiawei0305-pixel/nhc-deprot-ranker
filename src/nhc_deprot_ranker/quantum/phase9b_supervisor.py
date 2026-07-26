"""Phase 9B supervisor entry for the paired direct / assisted smoke.

``run_phase8b_supervisor`` is bound to the frozen Phase 8B request, attempt,
permit, root, and electron count, so it cannot run any other candidate.  This
module provides the equivalent entry driven by a
:class:`~nhc_deprot_ranker.quantum.phase9b_authority.CandidateProfile`.

Two attempts run under one request: Route D, direct PySCF from the frozen input,
and Route A, PySCF residual optimization from an AIMNet2-preoptimized structure.
Both share identical PySCF settings and resources; a difference between them
invalidates the comparison and is rejected here rather than discovered later.

Supervision itself is **not** reimplemented.  This module delegates to the
existing validated supervised-execution path so there is exactly one copy of the
process, deadline, and reaping logic.  A second copy would be free to drift from
the one that carries the safety proofs.

Like the Phase 9B authority module, this file is deliberately **not** yet listed
in the runner source closure.  Adding both changes ``runner_source_sha256`` and
must happen together with generating the new request, payload manifest, and
one-shot permit.

No chemistry import, no compute, no label.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from nhc_deprot_ranker.quantum.phase9b_authority import (
    PHASE9B_CANDIDATE,
    CandidateProfile,
    Phase9BAuthorityError,
    validate_endpoint_pair,
    validate_profile_self_consistency,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nhc_deprot_ranker.quantum.two_endpoint import TwoEndpointRequest

# Real Phase 9B execution is a separate authorization.  Source-level gate.
EXECUTION_AUTHORIZED: Final[bool] = False

REQUEST_ID: Final = "phase9b-lbnp-paired-smoke-v001"
ROUTE_D_ATTEMPT_ID: Final = "attempt-phase9b-lbnp-direct-v001"
ROUTE_A_ATTEMPT_ID: Final = "attempt-phase9b-lbnp-assisted-v001"
REMOTE_ROOT_RELATIVE: Final = "data/runs/nhc_deprot_ranker_phase9b_paired_smoke_v001"

ROUTE_DIRECT: Final = "direct"
ROUTE_ASSISTED: Final = "assisted"
_ROUTE_ATTEMPTS: Final[dict[str, str]] = {
    ROUTE_DIRECT: ROUTE_D_ATTEMPT_ID,
    ROUTE_ASSISTED: ROUTE_A_ATTEMPT_ID,
}

# Identities of the permanently retired Phase 8B chain.  Never reusable.
_RETIRED_IDENTITIES: Final[frozenset[str]] = frozenset(
    {
        "QXHIEGFUWOLQIJ-UHFFFAOYSA-N",
        "phase8b-qxh-smoke-v001",
        "attempt-phase8b-qxh-v001",
        "data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001",
    }
)


class Phase9BSupervisorError(RuntimeError):
    """The Phase 9B supervisor transaction could not prove its closed scope."""


class Phase9BNotAuthorizedError(Phase9BSupervisorError):
    """Execution was attempted while a gate is closed."""


@dataclass(frozen=True, slots=True)
class Phase9BAuthority:
    """Hash-closed authority for one Phase 9B route."""

    route: str
    request_sha256: str
    runner_source_sha256: str
    protocol_sha256: str
    electron_count: int
    profile: CandidateProfile


class _WorkerLaunchLike(Protocol):
    @property
    def absolute_deadline_ns(self) -> int: ...


class _SupervisedExecutor(Protocol):
    def __call__(
        self,
        request: TwoEndpointRequest,
        output_root: Path,
        *,
        attempt_id: str,
        worker_launch: _WorkerLaunchLike,
    ) -> object: ...


def validate_route_configurations_match(
    direct: Phase9BAuthority, assisted: Phase9BAuthority
) -> None:
    """Both routes must share every setting except the preoptimization stage.

    A configuration difference makes any measured speedup uninterpretable, so it
    is rejected before execution rather than explained afterward.
    """

    if direct.route != ROUTE_DIRECT or assisted.route != ROUTE_ASSISTED:
        raise Phase9BSupervisorError("route labels are not one direct and one assisted")
    if direct.protocol_sha256 != assisted.protocol_sha256:
        raise Phase9BSupervisorError("route PySCF protocols differ")
    if direct.runner_source_sha256 != assisted.runner_source_sha256:
        raise Phase9BSupervisorError("route runner source closures differ")
    if direct.electron_count != assisted.electron_count:
        raise Phase9BSupervisorError("route electron counts differ")
    if direct.profile.inchikey != assisted.profile.inchikey:
        raise Phase9BSupervisorError("routes reference different candidates")
    if direct.request_sha256 == assisted.request_sha256:
        raise Phase9BSupervisorError("routes must be distinct attempts, not one request reused")


def _reject_retired_identity(*values: object) -> None:
    for value in values:
        if isinstance(value, str) and value in _RETIRED_IDENTITIES:
            raise Phase9BNotAuthorizedError(
                "the retired Phase 8B authority chain may never be reused"
            )


def run_phase9b_supervisor(
    request: TwoEndpointRequest,
    output_root: Path,
    *,
    authority: Phase9BAuthority,
    worker_launch: _WorkerLaunchLike,
    profile: CandidateProfile = PHASE9B_CANDIDATE,
    execute: _SupervisedExecutor | None = None,
) -> object:
    """Validate one Phase 9B route, then delegate to supervised execution."""

    from nhc_deprot_ranker.quantum import two_endpoint as runner

    if EXECUTION_AUTHORIZED is not True:
        raise Phase9BNotAuthorizedError("Phase 9B execution is not authorized")
    if runner.EXECUTION_AUTHORIZED is not True:
        raise Phase9BNotAuthorizedError("the runner source execution gate is closed")

    if not isinstance(authority, Phase9BAuthority):
        raise Phase9BNotAuthorizedError("a Phase 9B authority is required")
    if authority.route not in _ROUTE_ATTEMPTS:
        raise Phase9BSupervisorError(f"unknown Phase 9B route: {authority.route}")

    _reject_retired_identity(
        getattr(request, "inchikey", None),
        getattr(request, "request_id", None),
        authority.profile.inchikey,
    )

    validate_profile_self_consistency(profile)
    if authority.profile != profile:
        raise Phase9BSupervisorError("authority profile disagrees with the supplied profile")
    if authority.electron_count != profile.electron_count:
        raise Phase9BSupervisorError("authority electron count disagrees with the profile")

    if authority.request_sha256 != request.request_sha256:
        raise Phase9BNotAuthorizedError("Phase 9B authority disagrees with the request")
    if authority.runner_source_sha256 != request.runner_source_sha256:
        raise Phase9BNotAuthorizedError("Phase 9B authority runner source disagrees")
    if getattr(request, "inchikey", None) != profile.inchikey:
        raise Phase9BSupervisorError("request candidate disagrees with the profile")

    try:
        validate_endpoint_pair(request.cation, request.neutral, profile=profile)
    except Phase9BAuthorityError as exc:
        raise Phase9BSupervisorError(f"endpoint validation failed: {exc}") from exc

    if os.path.lexists(output_root):
        raise Phase9BNotAuthorizedError("Phase 9B output already exists; resume is prohibited")

    executor = execute
    if executor is None:  # pragma: no cover - unreachable while the gate is closed
        raise Phase9BNotAuthorizedError("no production Phase 9B execution path is wired yet")

    return executor(
        request,
        output_root,
        attempt_id=_ROUTE_ATTEMPTS[authority.route],
        worker_launch=worker_launch,
    )


__all__ = [
    "EXECUTION_AUTHORIZED",
    "REMOTE_ROOT_RELATIVE",
    "REQUEST_ID",
    "ROUTE_ASSISTED",
    "ROUTE_A_ATTEMPT_ID",
    "ROUTE_DIRECT",
    "ROUTE_D_ATTEMPT_ID",
    "Phase9BAuthority",
    "Phase9BNotAuthorizedError",
    "Phase9BSupervisorError",
    "run_phase9b_supervisor",
    "validate_route_configurations_match",
]
