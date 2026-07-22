"""Standard-library bootstrap that releases the fixed worker after handshake."""

from __future__ import annotations

import argparse
import os
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from nhc_deprot_ranker.quantum.linux_guardian import (
    AffinityReader,
    install_parent_death_signal,
    parse_cpu_list,
    perform_preimport_handshake,
    read_process_identity,
    read_task_affinities,
)
from nhc_deprot_ranker.quantum.phase8b_execution import (
    ComputeClaimEvidence,
    IdentityReader,
    TaskAffinityReader,
    load_and_validate_compute_claim_for_worker,
)

_RELEASE_TOKEN_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_FROZEN_WORKER_CPUS: Final = frozenset({0, 1, 2, 3})
_PREIMPORT_PROOF_SEAL: Final = object()


class _BootstrapTarget(Protocol):
    def __call__(
        self,
        arguments: Sequence[str],
        *,
        bootstrap_proof: object,
    ) -> int: ...


class _PreimportHandshakeProof:
    """One-use process-local proof that the bootstrap release completed."""

    __slots__ = (
        "_absolute_deadline_ns",
        "_allowed_cpus",
        "_compute_claim_path",
        "_compute_claim_sha256",
        "_expected_parent_pid",
        "_pid",
        "_release_token",
        "_seal",
    )

    def __init__(
        self,
        *,
        seal: object,
        pid: int,
        expected_parent_pid: int,
        absolute_deadline_ns: int,
        allowed_cpus: frozenset[int],
        release_token: str,
        compute_claim_path: Path,
        compute_claim_sha256: str,
    ) -> None:
        if seal is not _PREIMPORT_PROOF_SEAL:
            raise TypeError("pre-import handshake proofs are issued only by the bootstrap")
        self._seal = seal
        self._pid = pid
        self._expected_parent_pid = expected_parent_pid
        self._absolute_deadline_ns = absolute_deadline_ns
        self._allowed_cpus = allowed_cpus
        self._release_token = release_token
        self._compute_claim_path = compute_claim_path
        self._compute_claim_sha256 = compute_claim_sha256


_LIVE_PREIMPORT_PROOFS: dict[int, _PreimportHandshakeProof] = {}
_CLAIMED_DURABLE_COMPUTE: set[tuple[int, str]] = set()
_CLAIM_LOCK = threading.Lock()


def _issue_preimport_handshake_proof(
    *,
    release_token: str,
    expected_parent_pid: int,
    absolute_deadline_ns: int,
    allowed_cpus: frozenset[int],
    claim_evidence: ComputeClaimEvidence,
) -> _PreimportHandshakeProof:
    if _RELEASE_TOKEN_RE.fullmatch(release_token) is None:
        raise RuntimeError("bootstrap release token identity drifted")
    proof = _PreimportHandshakeProof(
        seal=_PREIMPORT_PROOF_SEAL,
        pid=os.getpid(),
        expected_parent_pid=expected_parent_pid,
        absolute_deadline_ns=absolute_deadline_ns,
        allowed_cpus=allowed_cpus,
        release_token=release_token,
        compute_claim_path=claim_evidence.claim.paths.compute_claim,
        compute_claim_sha256=claim_evidence.compute_claim_sha256,
    )
    _LIVE_PREIMPORT_PROOFS[id(proof)] = proof
    return proof


def _claim_preimport_handshake_proof(
    proof: object,
    *,
    expected_absolute_deadline_ns: int,
    expected_compute_claim_path: Path,
    expected_compute_claim_sha256: str,
) -> tuple[int, int, frozenset[int], str]:
    """Consume one proof and return its PID, parent PID, and CPU binding."""

    if not isinstance(proof, _PreimportHandshakeProof):
        raise RuntimeError("worker lacks a bootstrap-issued pre-import handshake proof")
    registered = _LIVE_PREIMPORT_PROOFS.pop(id(proof), None)
    if registered is not proof or proof._seal is not _PREIMPORT_PROOF_SEAL:
        raise RuntimeError("pre-import handshake proof is forged, stale, or already claimed")
    if proof._pid != os.getpid() or proof._expected_parent_pid != os.getppid():
        raise RuntimeError("pre-import handshake process identity drifted")
    if (
        proof._absolute_deadline_ns != expected_absolute_deadline_ns
        or proof._absolute_deadline_ns <= time.monotonic_ns()
        or proof._compute_claim_path != expected_compute_claim_path
        or proof._compute_claim_sha256 != expected_compute_claim_sha256
    ):
        raise RuntimeError("pre-import handshake deadline drifted or expired")
    if proof._allowed_cpus != _FROZEN_WORKER_CPUS:
        raise RuntimeError("pre-import handshake CPU binding drifted")
    if _RELEASE_TOKEN_RE.fullmatch(proof._release_token) is None:
        raise RuntimeError("pre-import handshake release identity drifted")
    return (
        proof._pid,
        proof._expected_parent_pid,
        proof._allowed_cpus,
        proof._compute_claim_sha256,
    )


@dataclass(frozen=True, slots=True)
class _Arguments:
    start_fd: int
    release_token: str
    expected_parent_pid: int
    absolute_deadline_ns: int
    allowed_cpus: frozenset[int]
    compute_claim_path: Path
    worker_args: tuple[str, ...]


def _parse_arguments(argv: Sequence[str] | None) -> _Arguments:
    parser = argparse.ArgumentParser(
        prog="nhc-deprot-phase8b-worker-bootstrap",
        description="internal pre-import worker bootstrap",
    )
    parser.add_argument("--start-fd", required=True, type=int)
    parser.add_argument("--release-token", required=True)
    parser.add_argument("--expected-parent-pid", required=True, type=int)
    parser.add_argument("--absolute-deadline-ns", required=True, type=int)
    parser.add_argument("--allowed-cpus", required=True)
    parser.add_argument("--compute-claim-path", required=True, type=Path)
    parser.add_argument("worker_args", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(argv)
    worker_args = tuple(parsed.worker_args)
    if worker_args[:1] == ("--",):
        worker_args = worker_args[1:]
    return _Arguments(
        start_fd=parsed.start_fd,
        release_token=parsed.release_token,
        expected_parent_pid=parsed.expected_parent_pid,
        absolute_deadline_ns=parsed.absolute_deadline_ns,
        allowed_cpus=parse_cpu_list(parsed.allowed_cpus),
        compute_claim_path=parsed.compute_claim_path,
        worker_args=worker_args,
    )


def bootstrap_worker(
    *,
    start_fd: int,
    release_token: str,
    expected_parent_pid: int,
    absolute_deadline_ns: int,
    allowed_cpus: frozenset[int],
    compute_claim_path: Path,
    worker_args: Sequence[str],
    target: _BootstrapTarget,
    install_pdeath: Callable[[int], None] = install_parent_death_signal,
    affinity_reader: AffinityReader | None = None,
    identity_reader: IdentityReader = read_process_identity,
    task_affinity_reader: TaskAffinityReader = read_task_affinities,
    clock_ns: Callable[[], int] = time.monotonic_ns,
) -> int:
    """Run ``target`` only after the parent/watchdog release is proven."""

    if affinity_reader is None:
        perform_preimport_handshake(
            start_fd,
            expected_token=release_token,
            expected_parent_pid=expected_parent_pid,
            absolute_deadline_ns=absolute_deadline_ns,
            allowed_cpus=allowed_cpus,
            install_pdeath=install_pdeath,
            clock_ns=clock_ns,
        )
    else:
        perform_preimport_handshake(
            start_fd,
            expected_token=release_token,
            expected_parent_pid=expected_parent_pid,
            absolute_deadline_ns=absolute_deadline_ns,
            allowed_cpus=allowed_cpus,
            install_pdeath=install_pdeath,
            affinity_reader=affinity_reader,
            clock_ns=clock_ns,
        )
    claim_evidence = load_and_validate_compute_claim_for_worker(
        compute_claim_path,
        release_token=release_token,
        expected_parent_pid=expected_parent_pid,
        expected_absolute_deadline_ns=absolute_deadline_ns,
        expected_allowed_cpus=allowed_cpus,
        identity_reader=identity_reader,
        task_affinity_reader=task_affinity_reader,
        clock_ns=clock_ns,
    )
    claim_key = (os.getpid(), claim_evidence.compute_claim_sha256)
    with _CLAIM_LOCK:
        if claim_key in _CLAIMED_DURABLE_COMPUTE:
            raise RuntimeError("durable compute claim is already claimed by this worker")
        _CLAIMED_DURABLE_COMPUTE.add(claim_key)
    proof = _issue_preimport_handshake_proof(
        release_token=release_token,
        expected_parent_pid=expected_parent_pid,
        absolute_deadline_ns=absolute_deadline_ns,
        allowed_cpus=allowed_cpus,
        claim_evidence=claim_evidence,
    )
    try:
        return target(tuple(worker_args), bootstrap_proof=proof)
    finally:
        _LIVE_PREIMPORT_PROOFS.pop(id(proof), None)


def _run_fixed_worker(arguments: Sequence[str], *, bootstrap_proof: object) -> int:
    # This is intentionally the first import of the worker module.  It is
    # reached only after ``perform_preimport_handshake`` succeeds.
    from nhc_deprot_ranker.quantum import worker

    return worker.main(arguments, bootstrap_proof=bootstrap_proof)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse chemistry-free metadata, complete handshake, then import worker."""

    arguments = _parse_arguments(argv)
    return bootstrap_worker(
        start_fd=arguments.start_fd,
        release_token=arguments.release_token,
        expected_parent_pid=arguments.expected_parent_pid,
        absolute_deadline_ns=arguments.absolute_deadline_ns,
        allowed_cpus=arguments.allowed_cpus,
        compute_claim_path=arguments.compute_claim_path,
        worker_args=arguments.worker_args,
        target=_run_fixed_worker,
    )


if __name__ == "__main__":  # pragma: no cover - invoked by the fixed supervisor
    raise SystemExit(main())
