"""Internal fixed-attempt worker for the parent-supervised quantum runner.

The module imports no chemistry package.  Its ``main`` function repeats the
source-level gate as its first action, before inspecting arguments or requests.
Phase 8A deliberately leaves that gate closed.

Candidate-specific expectations — electron count, CPU affinity, and chain
identity — are no longer hard-coded in the validation flow.  They come from a
:class:`WorkerAuthorityProfile` selected by exact attempt identity from a
source-frozen table in this file, which is itself inside the runner source
closure, so profile values are hash-bound exactly like code.

There is still exactly one live validation path.  The permit loader and exact
authority validator are reached through a profile-supplied adapter, because the
two chains have different signatures; adapting them keeps the worker on one call
path rather than branching on phase.  Compute-capability issue is not yet
parameterized, so the Phase 9B profile stops there rather than at the permit.
"""

from __future__ import annotations

import argparse
import os
import stat
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from nhc_deprot_ranker.quantum import two_endpoint as runner
from nhc_deprot_ranker.quantum.linux_guardian import (
    read_process_identity,
    read_task_affinities,
)
from nhc_deprot_ranker.quantum.phase8b_authority import ExactPhase8BAuthority
from nhc_deprot_ranker.quantum.phase8b_execution import (
    ComputeClaimEvidence,
    IdentityReader,
    TaskAffinityReader,
    load_and_validate_compute_claim_for_worker,
)
from nhc_deprot_ranker.quantum.phase8b_permit import ConsumedPhase8BPermit
from nhc_deprot_ranker.quantum.phase9b_permit import (
    ConsumedPhase9BPermit,
    Phase9BExactAuthority,
)


class _PermitAndAuthorityLoader(Protocol):
    """Normalizes the two chains' differing loader/validator signatures.

    The Phase 8B loader takes no profile or route; the Phase 9B loader requires a
    route. The Phase 8B validator requires the source path list; the Phase 9B
    validator does not. Adapting them here keeps the worker on exactly one call
    path instead of branching on phase in the validation flow.
    """

    def __call__(
        self,
        *,
        consumed_path: Path,
        expected_permit_sha256: str,
        expected_request_sha256: str,
        expected_runner_source_sha256: str,
        expected_payload_manifest_sha256: str,
        request: object,
        output_root: Path,
        attempt_id: str,
    ) -> tuple[object, object]: ...


def _load_phase8b_permit_and_authority(
    *,
    consumed_path: Path,
    expected_permit_sha256: str,
    expected_request_sha256: str,
    expected_runner_source_sha256: str,
    expected_payload_manifest_sha256: str,
    request: object,
    output_root: Path,
    attempt_id: str,
) -> tuple[object, object]:
    from nhc_deprot_ranker.quantum.phase8b_authority import (
        Phase8BRequestLike,
        validate_exact_phase8b_authority,
    )
    from nhc_deprot_ranker.quantum.phase8b_permit import load_consumed_phase8b_permit

    consumed = load_consumed_phase8b_permit(
        consumed_path,
        expected_permit_sha256=expected_permit_sha256,
        expected_request_sha256=expected_request_sha256,
        expected_runner_source_sha256=expected_runner_source_sha256,
        expected_payload_manifest_sha256=expected_payload_manifest_sha256,
    )
    authority = validate_exact_phase8b_authority(
        cast(Phase8BRequestLike, request),
        consumed,
        output_root=output_root,
        attempt_id=attempt_id,
        expected_source_relative_paths=runner._RUNNER_SOURCE_RELATIVE_PATHS,  # pyright: ignore[reportPrivateUsage]
        require_output_absent=False,
    )
    return consumed, authority


def _load_phase9b_permit_and_authority(
    *,
    consumed_path: Path,
    expected_permit_sha256: str,
    expected_request_sha256: str,
    expected_runner_source_sha256: str,
    expected_payload_manifest_sha256: str,
    request: object,
    output_root: Path,
    attempt_id: str,
) -> tuple[object, object]:
    from nhc_deprot_ranker.quantum.phase9b_permit import (
        ROUTE_ATTEMPT_IDS,
        Phase9BRequestLike,
        load_consumed_phase9b_permit,
        validate_exact_phase9b_authority,
    )

    routes = [route for route, ident in ROUTE_ATTEMPT_IDS.items() if ident == attempt_id]
    if len(routes) != 1:
        raise runner.ExecutionNotAuthorizedError(
            "Phase 9B attempt identity does not name exactly one route"
        )
    consumed = load_consumed_phase9b_permit(
        consumed_path,
        expected_route=routes[0],
        expected_permit_sha256=expected_permit_sha256,
        expected_request_sha256=expected_request_sha256,
        expected_runner_source_sha256=expected_runner_source_sha256,
        expected_payload_manifest_sha256=expected_payload_manifest_sha256,
    )
    authority = validate_exact_phase9b_authority(
        cast(Phase9BRequestLike, request),
        consumed,
        output_root=output_root,
        attempt_id=attempt_id,
        require_output_absent=False,
    )
    return consumed, authority


class _ReloadPermitAndAuthority(Protocol):
    """Re-reads and re-validates from an already-consumed permit object."""

    def __call__(
        self, *, consumed: object, request: object, output_root: Path, attempt_id: str
    ) -> tuple[object, object]: ...


def _reload_phase8b_permit_and_authority(
    *, consumed: object, request: object, output_root: Path, attempt_id: str
) -> tuple[object, object]:
    if not isinstance(consumed, ConsumedPhase8BPermit):
        raise runner.ExecutionNotAuthorizedError("Phase 8B reload received a foreign permit")
    permit = consumed.permit
    return _load_phase8b_permit_and_authority(
        consumed_path=consumed.consumed_path,
        expected_permit_sha256=permit.permit_sha256,
        expected_request_sha256=permit.request_sha256,
        expected_runner_source_sha256=permit.runner_source_sha256,
        expected_payload_manifest_sha256=permit.payload_manifest_sha256,
        request=request,
        output_root=output_root,
        attempt_id=attempt_id,
    )


def _reload_phase9b_permit_and_authority(
    *, consumed: object, request: object, output_root: Path, attempt_id: str
) -> tuple[object, object]:
    if not isinstance(consumed, ConsumedPhase9BPermit):
        raise runner.ExecutionNotAuthorizedError("Phase 9B reload received a foreign permit")
    permit = consumed.permit
    return _load_phase9b_permit_and_authority(
        consumed_path=consumed.consumed_path,
        expected_permit_sha256=permit.permit_sha256,
        expected_request_sha256=permit.request_sha256,
        expected_runner_source_sha256=permit.runner_source_sha256,
        expected_payload_manifest_sha256=permit.payload_manifest_sha256,
        request=request,
        output_root=output_root,
        attempt_id=attempt_id,
    )


@dataclass(frozen=True)
class WorkerAuthorityProfile:
    """Source-frozen, candidate-specific expectations for one authority chain.

    Values are data, but they live inside the runner source closure, so editing
    them changes ``runner_source_sha256`` exactly as editing code would.
    """

    profile_id: str
    request_id: str
    inchikey: str
    attempt_ids: tuple[str, ...]
    electron_count: int
    allowed_cpus: frozenset[int]
    load_permit_and_authority: _PermitAndAuthorityLoader
    consumed_permit_type: type
    authority_type: type
    capability_identity_key: str
    reload_permit_and_authority: _ReloadPermitAndAuthority
    uses_frozen_worker_match: bool


PHASE8B_WORKER_PROFILE = WorkerAuthorityProfile(
    profile_id="phase8b-qxh-smoke",
    request_id="phase8b-qxh-smoke-v001",
    inchikey="QXHIEGFUWOLQIJ-UHFFFAOYSA-N",
    attempt_ids=("attempt-phase8b-qxh-v001",),
    electron_count=120,
    allowed_cpus=frozenset({0, 1, 2, 3}),
    load_permit_and_authority=_load_phase8b_permit_and_authority,
    consumed_permit_type=ConsumedPhase8BPermit,
    authority_type=ExactPhase8BAuthority,
    capability_identity_key="phase8b-qxh-smoke",
    reload_permit_and_authority=_reload_phase8b_permit_and_authority,
    # Phase 8B's validator does not check the frozen constants itself.
    uses_frozen_worker_match=True,
)

# Registered for identity closure only; execution refuses until the Phase 9B
# permit and capability wiring exist.  The CPU set repeats the shared-host
# envelope; the final resource freeze happens in the Phase 9B execution request,
# and changing it here is a closure-visible source edit by construction.
PHASE9B_WORKER_PROFILE = WorkerAuthorityProfile(
    profile_id="phase9b-lbnp-paired-smoke",
    request_id="phase9b-lbnp-paired-smoke-v001",
    inchikey="LBNPGYISTSLAHY-UHFFFAOYSA-N",
    attempt_ids=(
        "attempt-phase9b-lbnp-direct-v001",
        "attempt-phase9b-lbnp-assisted-v001",
    ),
    electron_count=160,
    allowed_cpus=frozenset({0, 1, 2, 3}),
    load_permit_and_authority=_load_phase9b_permit_and_authority,
    consumed_permit_type=ConsumedPhase9BPermit,
    authority_type=Phase9BExactAuthority,
    capability_identity_key="phase9b-lbnp-paired-smoke",
    reload_permit_and_authority=_reload_phase9b_permit_and_authority,
    # Phase 9B's validator checks the frozen constants inline; parity with the
    # Phase 8B match was verified item by item before this was set to False.
    uses_frozen_worker_match=False,
)

WORKER_AUTHORITY_PROFILES: tuple[WorkerAuthorityProfile, ...] = (
    PHASE8B_WORKER_PROFILE,
    PHASE9B_WORKER_PROFILE,
)


def _resolve_worker_profile(attempt_id: str) -> WorkerAuthorityProfile:
    """Exact, unique attempt-identity match; anything else fails closed."""

    matches = [
        profile for profile in WORKER_AUTHORITY_PROFILES if attempt_id in profile.attempt_ids
    ]
    if len(matches) != 1:
        raise runner.ExecutionNotAuthorizedError(
            "no worker authority profile matches the requested attempt"
        )
    return matches[0]


@dataclass(frozen=True)
class _WorkerArguments:
    request_path: Path
    output_root: Path
    attempt_id: str
    consumed_permit_path: Path | None
    expected_permit_sha256: str | None
    expected_request_sha256: str | None
    expected_runner_source_sha256: str | None
    expected_payload_manifest_sha256: str | None
    expected_transport_inventory_sha256: str | None
    compute_claim_path: Path | None
    authorized_output_root: Path | None
    absolute_deadline_ns: int | None
    release_token: str | None


def _parse_arguments(argv: Sequence[str] | None) -> _WorkerArguments:
    parser = argparse.ArgumentParser(
        prog="nhc-deprot-two-endpoint-worker",
        description="internal fixed-attempt worker; invoke only through the parent supervisor",
    )
    parser.add_argument("--request-path", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--consumed-permit-path", type=Path)
    parser.add_argument("--expected-permit-sha256")
    parser.add_argument("--expected-request-sha256")
    parser.add_argument("--expected-runner-source-sha256")
    parser.add_argument("--expected-payload-manifest-sha256")
    parser.add_argument("--expected-transport-inventory-sha256")
    parser.add_argument("--compute-claim-path", type=Path)
    parser.add_argument("--authorized-output-root", type=Path)
    parser.add_argument("--absolute-deadline-ns", type=int)
    parser.add_argument("--release-token")
    parsed = parser.parse_args(argv)
    return _WorkerArguments(
        request_path=parsed.request_path,
        output_root=parsed.output_root,
        attempt_id=parsed.attempt_id,
        consumed_permit_path=parsed.consumed_permit_path,
        expected_permit_sha256=parsed.expected_permit_sha256,
        expected_request_sha256=parsed.expected_request_sha256,
        expected_runner_source_sha256=parsed.expected_runner_source_sha256,
        expected_payload_manifest_sha256=parsed.expected_payload_manifest_sha256,
        expected_transport_inventory_sha256=parsed.expected_transport_inventory_sha256,
        compute_claim_path=parsed.compute_claim_path,
        authorized_output_root=parsed.authorized_output_root,
        absolute_deadline_ns=parsed.absolute_deadline_ns,
        release_token=parsed.release_token,
    )


def _require_phase8b_arguments(
    arguments: _WorkerArguments,
) -> tuple[Path, str, str, str, str, str, Path, Path, int, str]:
    values = (
        arguments.consumed_permit_path,
        arguments.expected_permit_sha256,
        arguments.expected_request_sha256,
        arguments.expected_runner_source_sha256,
        arguments.expected_payload_manifest_sha256,
        arguments.expected_transport_inventory_sha256,
        arguments.compute_claim_path,
        arguments.authorized_output_root,
        arguments.absolute_deadline_ns,
        arguments.release_token,
    )
    if any(value is None for value in values):
        raise runner.ExecutionNotAuthorizedError(
            "worker requires the complete consumed Phase 8B authority"
        )
    return (
        arguments.consumed_permit_path,
        arguments.expected_permit_sha256,
        arguments.expected_request_sha256,
        arguments.expected_runner_source_sha256,
        arguments.expected_payload_manifest_sha256,
        arguments.expected_transport_inventory_sha256,
        arguments.compute_claim_path,
        arguments.authorized_output_root,
        arguments.absolute_deadline_ns,
        arguments.release_token,
    )  # type: ignore[return-value]


def _validate_worker_scratch(path: Path, *, authorized_output_root: Path, attempt_id: str) -> None:
    if (
        not path.is_absolute()
        or path.is_symlink()
        or path.parent != authorized_output_root.parent
        or not path.name.startswith(f".worker-{attempt_id}-")
    ):
        raise runner.ExecutionNotAuthorizedError("worker scratch escaped the fixed runtime root")
    file_stat = path.stat()
    if (
        not stat.S_ISDIR(file_stat.st_mode)
        or file_stat.st_uid != os.geteuid()
        or stat.S_IMODE(file_stat.st_mode) != 0o700
        or any(path.iterdir())
    ):
        raise runner.ExecutionNotAuthorizedError("worker scratch identity or initial state drifted")


def _validate_worker_compute_claim(
    evidence: ComputeClaimEvidence,
    *,
    request: runner.TwoEndpointRequest,
    consumed: object,
    authority: object,
    expected_transport_inventory_sha256: str,
    expected_payload_manifest_sha256: str,
    expected_permit_sha256: str,
    expected_request_sha256: str,
    expected_runner_source_sha256: str,
    authorized_output_root: Path,
    worker_scratch_path: Path,
    compute_claim_path: Path,
    attempt_id: str,
    profile: WorkerAuthorityProfile,
) -> None:
    # Profile-driven gate: catches objects from the wrong authority chain, which a
    # concrete check alone would let through when the profile disagrees.
    if not isinstance(consumed, profile.consumed_permit_type) or not isinstance(
        authority, profile.authority_type
    ):
        raise runner.ExecutionNotAuthorizedError("worker compute claim authority type drifted")
    # This function body still reads Phase 8B-shaped fields, so it genuinely
    # requires that shape today.  Stated explicitly rather than assumed.
    if not isinstance(consumed, ConsumedPhase8BPermit) or not isinstance(
        authority, ExactPhase8BAuthority
    ):
        raise runner.ExecutionNotAuthorizedError(
            "compute claim validation still requires the Phase 8B object shape"
        )
    claim = evidence.claim
    bound = claim.authority
    permit = consumed.permit
    expected_paths = {
        "registration": permit.run_root / "private/worker_registration.json",
        "acknowledgement": permit.run_root / "private/guardian_acknowledgement.json",
        "compute_claim": permit.run_root / "private/compute_claim.json",
        "receipt": permit.run_root / "private/guardian_receipt.json",
    }
    if (
        claim.paths.registration != expected_paths["registration"]
        or claim.paths.acknowledgement != expected_paths["acknowledgement"]
        or claim.paths.compute_claim != expected_paths["compute_claim"]
        or claim.paths.receipt != expected_paths["receipt"]
        or claim.paths.compute_claim != compute_claim_path
        or claim.worker_scratch_path != worker_scratch_path
        or bound.transport_inventory_sha256 != expected_transport_inventory_sha256
        or not (
            bound.payload_manifest_sha256
            == authority.payload_manifest_sha256
            == expected_payload_manifest_sha256
        )
        or not (bound.permit_sha256 == authority.permit_sha256 == expected_permit_sha256)
        or not (bound.request_sha256 == authority.request_sha256 == request.request_sha256)
        or bound.request_sha256 != expected_request_sha256
        or not (
            bound.runner_source_sha256
            == authority.runner_source_sha256
            == request.runner_source_sha256
        )
        or bound.runner_source_sha256 != expected_runner_source_sha256
        or bound.protocol_sha256 != request.protocol_sha256
        or bound.resources_sha256 != authority.resources_sha256
        or bound.cation_xyz_sha256 != request.cation.xyz_sha256
        or bound.neutral_xyz_sha256 != request.neutral.xyz_sha256
        or bound.endpoint_atom_map_sha256 != authority.endpoint_atom_map_sha256
        or bound.legacy_atom_map_sha256 != authority.legacy_atom_map_sha256
        or bound.geometry_validation_sha256 != authority.geometry_validation_sha256
        or bound.electron_count != authority.electron_count
        or not (bound.request_id == authority.request_id == request.request_id)
        or not (bound.inchikey == authority.inchikey == request.inchikey)
        or not (bound.attempt_id == authority.attempt_id == attempt_id)
        or bound.project_root != permit.project_root
        or bound.run_root != permit.run_root
        or not (bound.request_path == permit.request_path == request.request_path)
        or not (bound.output_root == permit.output_root == authorized_output_root)
        or consumed.consumed_sha256 != bound.permit_sha256
    ):
        raise runner.ExecutionNotAuthorizedError(
            "durable compute claim differs from consumed request/bundle/path authority"
        )


def main(
    argv: Sequence[str] | None = None,
    *,
    bootstrap_proof: object | None = None,
    identity_reader: IdentityReader = read_process_identity,
    task_affinity_reader: TaskAffinityReader = read_task_affinities,
    clock_ns: Callable[[], int] = time.monotonic_ns,
) -> int:
    """Execute one guarded attempt; the authorization check must stay first."""

    runner._ensure_execution_authorized()  # pyright: ignore[reportPrivateUsage]
    arguments = _parse_arguments(argv)
    request = runner.load_two_endpoint_request(arguments.request_path)
    if request.execution_authorized is not True:
        raise runner.ExecutionNotAuthorizedError(
            "frozen request does not authorize worker execution"
        )
    (
        consumed_path,
        permit_sha256,
        request_sha256,
        runner_source_sha256,
        payload_manifest_sha256,
        transport_inventory_sha256,
        compute_claim_path,
        authorized_output_root,
        absolute_deadline_ns,
        release_token,
    ) = _require_phase8b_arguments(arguments)
    profile = _resolve_worker_profile(arguments.attempt_id)
    runner._validate_endpoint_pair_electrons(  # pyright: ignore[reportPrivateUsage]
        request.cation,
        request.neutral,
        expected_electron_count=profile.electron_count,
    )
    consumed, exact_authority = profile.load_permit_and_authority(
        consumed_path=consumed_path,
        expected_permit_sha256=permit_sha256,
        expected_request_sha256=request_sha256,
        expected_runner_source_sha256=runner_source_sha256,
        expected_payload_manifest_sha256=payload_manifest_sha256,
        request=request,
        output_root=authorized_output_root,
        attempt_id=arguments.attempt_id,
    )
    # Chain-correct guard: an adapter returning the other chain's objects fails
    # closed here rather than reaching capability issue.
    if not isinstance(consumed, profile.consumed_permit_type) or not isinstance(
        exact_authority, profile.authority_type
    ):
        raise runner.ExecutionNotAuthorizedError(
            "adapter returned objects from a different authority chain"
        )
    # The gate above proves the chain; cast to the shared shape the capability
    # binds, which both chains' authority records satisfy structurally.
    capability_authority = cast(runner.CapabilityAuthorityLike, exact_authority)
    _validate_worker_scratch(
        arguments.output_root,
        authorized_output_root=authorized_output_root,
        attempt_id=arguments.attempt_id,
    )
    claim_evidence = load_and_validate_compute_claim_for_worker(
        compute_claim_path,
        release_token=release_token,
        expected_parent_pid=os.getppid(),
        expected_absolute_deadline_ns=absolute_deadline_ns,
        expected_allowed_cpus=profile.allowed_cpus,
        identity_reader=identity_reader,
        task_affinity_reader=task_affinity_reader,
        clock_ns=clock_ns,
    )
    _validate_worker_compute_claim(
        claim_evidence,
        request=request,
        consumed=consumed,
        authority=exact_authority,
        expected_transport_inventory_sha256=transport_inventory_sha256,
        expected_payload_manifest_sha256=payload_manifest_sha256,
        expected_permit_sha256=permit_sha256,
        expected_request_sha256=request_sha256,
        expected_runner_source_sha256=runner_source_sha256,
        authorized_output_root=authorized_output_root,
        worker_scratch_path=arguments.output_root,
        compute_claim_path=compute_claim_path,
        attempt_id=arguments.attempt_id,
        profile=profile,
    )
    runner._ensure_execution_authorized()  # pyright: ignore[reportPrivateUsage]
    compute_capability = runner._issue_guarded_compute_capability(  # pyright: ignore[reportPrivateUsage]
        request=request,
        consumed=consumed,
        authority=capability_authority,
        bootstrap_proof=bootstrap_proof,
        output_root=authorized_output_root,
        attempt_id=arguments.attempt_id,
        absolute_deadline_ns=absolute_deadline_ns,
        compute_claim_evidence=claim_evidence,
        consumed_permit_type=profile.consumed_permit_type,
        authority_type=profile.authority_type,
        identity_key=profile.capability_identity_key,
        allowed_cpus=profile.allowed_cpus,
        reload_permit_and_authority=profile.reload_permit_and_authority,
        extra_authority_match=(
            runner._authority_matches_frozen_worker  # pyright: ignore[reportPrivateUsage]
            if profile.uses_frozen_worker_match
            else None
        ),
    )
    try:
        runner._execute_validated_request(  # pyright: ignore[reportPrivateUsage]
            request,
            arguments.output_root,
            backend=runner.PySCFBackend(compute_capability),
            attempt_id=arguments.attempt_id,
            absolute_deadline_monotonic=absolute_deadline_ns / 1_000_000_000,
        )
    except runner.TwoEndpointRunError as error:
        return error.exit_code
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised only by the supervisor
    raise SystemExit(main())
