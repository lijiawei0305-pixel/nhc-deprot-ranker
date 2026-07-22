"""Internal fixed-attempt worker for the parent-supervised quantum runner.

The module imports no chemistry package.  Its ``main`` function repeats the
source-level gate as its first action, before inspecting arguments or requests.
Phase 8A deliberately leaves that gate closed.
"""

from __future__ import annotations

import argparse
import os
import stat
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from nhc_deprot_ranker.quantum import two_endpoint as runner
from nhc_deprot_ranker.quantum.linux_guardian import (
    read_process_identity,
    read_task_affinities,
)
from nhc_deprot_ranker.quantum.phase8b_execution import (
    ComputeClaimEvidence,
    IdentityReader,
    TaskAffinityReader,
    load_and_validate_compute_claim_for_worker,
)


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
) -> None:
    from nhc_deprot_ranker.quantum.phase8b_authority import ExactPhase8BAuthority
    from nhc_deprot_ranker.quantum.phase8b_permit import ConsumedPhase8BPermit

    if not isinstance(consumed, ConsumedPhase8BPermit) or not isinstance(
        authority, ExactPhase8BAuthority
    ):
        raise runner.ExecutionNotAuthorizedError("worker compute claim authority type drifted")
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
    from nhc_deprot_ranker.quantum.phase8b_authority import (
        Phase8BRequestLike,
        validate_exact_phase8b_authority,
    )
    from nhc_deprot_ranker.quantum.phase8b_permit import load_consumed_phase8b_permit

    consumed = load_consumed_phase8b_permit(
        consumed_path,
        expected_permit_sha256=permit_sha256,
        expected_request_sha256=request_sha256,
        expected_runner_source_sha256=runner_source_sha256,
        expected_payload_manifest_sha256=payload_manifest_sha256,
    )
    runner._validate_frozen_120_electron_pair(  # pyright: ignore[reportPrivateUsage]
        request.cation, request.neutral
    )
    exact_authority = validate_exact_phase8b_authority(
        cast(Phase8BRequestLike, request),
        consumed,
        output_root=authorized_output_root,
        attempt_id=arguments.attempt_id,
        expected_source_relative_paths=runner._RUNNER_SOURCE_RELATIVE_PATHS,  # pyright: ignore[reportPrivateUsage]
        require_output_absent=False,
    )
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
        expected_allowed_cpus=frozenset({0, 1, 2, 3}),
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
    )
    runner._ensure_execution_authorized()  # pyright: ignore[reportPrivateUsage]
    compute_capability = runner._issue_phase8b_compute_capability(  # pyright: ignore[reportPrivateUsage]
        request=request,
        consumed=consumed,
        authority=exact_authority,
        bootstrap_proof=bootstrap_proof,
        output_root=authorized_output_root,
        attempt_id=arguments.attempt_id,
        absolute_deadline_ns=absolute_deadline_ns,
        compute_claim_evidence=claim_evidence,
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
