"""The Phase 9B guardian transaction.

The only entry the launch control plane may start on the server.  It is what
Phase 8B's ``phase8b_runtime guardian`` mode is for that chain: it consumes the
one-shot permit, builds the worker handshake, starts the guarded supervisor, and
gets out of the way.

The fixed order, and nothing may be reordered:

```text
parse and verify the closed argv
-> verify the execution gates
-> verify request / manifest / permit / source / resources
-> verify the ready permit exists and no consumed permit exists
-> irreversibly consume the ready permit          <- linearization point
-> build and verify the Phase 9B worker handshake
-> establish evidence / log / output roots
-> spawn the guarded supervisor into its own session
-> obtain a verifiable spawn acknowledgement
-> write, fsync, and re-read the guardian launch receipt
-> return the minimal identity JSON and exit promptly
```

**Nothing spawns before consumption, and nothing restores a permit after it.**
There is no retry, no resume, no rollback, no backfill, and no restoration. If
consumption succeeds and the spawn then fails, the attempt is still spent; that
is recorded as a terminal state, not as something to try again.

The guardian does not supervise.  Timeouts, process-tree cleanup, and reaping
remain the supervisor's single copy; this module owns controlled consumption, the
handshake, and the launch transaction only.

It exits promptly so the bounded SSH call that started it returns in seconds,
while the supervisor keeps running for up to the frozen wall-time in its own
session.  That is what makes a short launch acknowledgement possible.

No chemistry import, no compute, no label.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, cast

from nhc_deprot_ranker.quantum.phase9b_authority import (
    PHASE9B_CANDIDATE,
    CandidateProfile,
)
from nhc_deprot_ranker.quantum.phase9b_permit import (
    CONSUMED_RELATIVE,
    READY_RELATIVE,
    ROUTE_ATTEMPT_IDS,
    ConsumedPhase9BPermit,
    Phase9BPermitConsumedError,
    Phase9BPermitError,
    consume_phase9b_permit,
)
from nhc_deprot_ranker.quantum.phase9b_resources import (
    PHASE9B_RESOURCES,
    phase9b_resources_sha256,
)
from nhc_deprot_ranker.quantum.phase9b_supervisor import (
    CLI_ENTRY as SUPERVISOR_ENTRY,
)
from nhc_deprot_ranker.quantum.phase9b_supervisor import (
    REQUIRED_FLAGS,
    Phase9BLaunchArguments,
    VerifiedPhase9BLaunch,
    parse_supervisor_argv,
    verify_launch_arguments,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

# Real guardian execution is a separate authorization.  Source-level gate.
EXECUTION_AUTHORIZED: Final[bool] = False

GUARDIAN_ENTRY: Final = "nhc_deprot_ranker.quantum.phase9b_guardian"

PERMIT_CONSUMPTION_RECEIPT_SCHEMA_VERSION: Final = "nhc-phase9b-permit-consumption-v1"
GUARDIAN_LAUNCH_RECEIPT_SCHEMA_VERSION: Final = "nhc-phase9b-guardian-launch-v1"
GUARDIAN_ACKNOWLEDGEMENT_SCHEMA_VERSION: Final = "phase9b.guardian_acknowledgement.v1"

EVIDENCE_RELATIVE: Final = "runtime/evidence"
LOG_RELATIVE: Final = "runtime/logs"
CONSUMPTION_RECEIPT_RELATIVE: Final = "runtime/evidence/permit_consumption.json"
LAUNCH_RECEIPT_RELATIVE: Final = "runtime/evidence/guardian_launch.json"
SUPERVISOR_STDOUT_RELATIVE: Final = "runtime/logs/supervisor.stdout.jsonl"
SUPERVISOR_STDERR_RELATIVE: Final = "runtime/logs/supervisor.stderr.log"

_ROOT_MODE: Final = 0o700
_RECEIPT_MODE: Final = 0o400
_LOG_MODE: Final = 0o600

# The acknowledgement window covers verification, consumption, spawn, and the
# supervisor printing its identity.  It never covers the computation.
ACKNOWLEDGEMENT_TIMEOUT_SECONDS: Final = 60.0
_ACK_POLL_SECONDS: Final = 0.05
_MAX_ACK_BYTES: Final = 64 * 1024


class Phase9BGuardianError(RuntimeError):
    """The guardian transaction could not prove its closed scope."""


class Phase9BGuardianNotAuthorizedError(Phase9BGuardianError):
    """A real guardian transaction was attempted while a gate is closed."""


class ConsumptionState(Enum):
    """The permit's own state.  ``indeterminate`` is never upgraded."""

    NOT_CONSUMED = "not_consumed"
    CONSUMED = "consumed"
    INDETERMINATE = "indeterminate"
    FAILED = "failed"


class GuardianState(Enum):
    """The launch transaction's terminal states."""

    NOT_STARTED = "not_started"
    PERMIT_CONSUMED_SPAWNED = "permit_consumed_spawned"
    PERMIT_CONSUMED_SPAWN_FAILED = "permit_consumed_spawn_failed"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class PermitConsumptionReceipt:
    """Proof of the irreversible point, written before any spawn is attempted."""

    schema_version: str
    phase: str
    candidate_inchikey: str
    route: str
    attempt_id: str
    ready_path: str
    consumed_path: str
    permit_sha256: str
    consumed_sha256: str
    request_sha256: str
    payload_manifest_sha256: str
    runner_source_sha256: str
    resources_sha256: str
    host_identity_sha256: str
    consumed_at: str
    state: ConsumptionState
    failure_reason: str | None
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class SpawnedProcess:
    """What was actually started, as observed rather than as claimed."""

    pid: int
    process_group_id: int
    session_id: int


@dataclass(frozen=True, slots=True)
class GuardianLaunchReceipt:
    """The launch record.  It says what was started, never what was computed."""

    schema_version: str
    phase: str
    route: str
    attempt_id: str
    guardian_identity: str
    supervisor_entry: str
    supervisor_pid: int | None
    supervisor_process_group_id: int | None
    supervisor_session_id: int | None
    argv_sha256: str
    request_sha256: str
    payload_manifest_sha256: str
    permit_sha256: str
    runner_source_sha256: str
    resources_sha256: str
    output_root: str
    evidence_root: str
    log_root: str
    consumption_receipt_sha256: str
    spawned_at: str
    acknowledged_at: str | None
    state: GuardianState
    failure_reason: str | None
    receipt_sha256: str


class SpawnSupervisor(Protocol):
    """Injectable seam.  Production spawns a real detached session."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        stdout_path: Path,
        stderr_path: Path,
    ) -> SpawnedProcess: ...


class Clock(Protocol):
    def __call__(self) -> str: ...


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _consumption_body(receipt: PermitConsumptionReceipt) -> dict[str, object]:
    return {
        "schema_version": receipt.schema_version,
        "phase": receipt.phase,
        "candidate_inchikey": receipt.candidate_inchikey,
        "route": receipt.route,
        "attempt_id": receipt.attempt_id,
        "ready_path": receipt.ready_path,
        "consumed_path": receipt.consumed_path,
        "permit_sha256": receipt.permit_sha256,
        "consumed_sha256": receipt.consumed_sha256,
        "request_sha256": receipt.request_sha256,
        "payload_manifest_sha256": receipt.payload_manifest_sha256,
        "runner_source_sha256": receipt.runner_source_sha256,
        "resources_sha256": receipt.resources_sha256,
        "host_identity_sha256": receipt.host_identity_sha256,
        "consumed_at": receipt.consumed_at,
        "state": receipt.state.value,
        "failure_reason": receipt.failure_reason,
    }


def _launch_body(receipt: GuardianLaunchReceipt) -> dict[str, object]:
    return {
        "schema_version": receipt.schema_version,
        "phase": receipt.phase,
        "route": receipt.route,
        "attempt_id": receipt.attempt_id,
        "guardian_identity": receipt.guardian_identity,
        "supervisor_entry": receipt.supervisor_entry,
        "supervisor_pid": receipt.supervisor_pid,
        "supervisor_process_group_id": receipt.supervisor_process_group_id,
        "supervisor_session_id": receipt.supervisor_session_id,
        "argv_sha256": receipt.argv_sha256,
        "request_sha256": receipt.request_sha256,
        "payload_manifest_sha256": receipt.payload_manifest_sha256,
        "permit_sha256": receipt.permit_sha256,
        "runner_source_sha256": receipt.runner_source_sha256,
        "resources_sha256": receipt.resources_sha256,
        "output_root": receipt.output_root,
        "evidence_root": receipt.evidence_root,
        "log_root": receipt.log_root,
        "consumption_receipt_sha256": receipt.consumption_receipt_sha256,
        "spawned_at": receipt.spawned_at,
        "acknowledged_at": receipt.acknowledged_at,
        "state": receipt.state.value,
        "failure_reason": receipt.failure_reason,
    }


def consumption_receipt_sha256(receipt: PermitConsumptionReceipt) -> str:
    return _sha256_bytes(_canonical_json_bytes(_consumption_body(receipt)))


def launch_receipt_sha256(receipt: GuardianLaunchReceipt) -> str:
    return _sha256_bytes(_canonical_json_bytes(_launch_body(receipt)))


def consumption_receipt_payload(receipt: PermitConsumptionReceipt) -> dict[str, object]:
    body = _consumption_body(receipt)
    body["receipt_sha256"] = receipt.receipt_sha256
    return body


def launch_receipt_payload(receipt: GuardianLaunchReceipt) -> dict[str, object]:
    body = _launch_body(receipt)
    body["receipt_sha256"] = receipt.receipt_sha256
    return body


# --- filesystem primitives ---------------------------------------------------


def _make_private_directory(path: Path) -> None:
    """Exclusive create, no symlink follow, private mode.  Never reuses a root."""

    if path.is_symlink():
        raise Phase9BGuardianError(f"root path is a symlink: {path}")
    try:
        path.mkdir(mode=_ROOT_MODE, parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise Phase9BGuardianError(f"root already exists; resume is prohibited: {path}") from exc
    except OSError as exc:
        raise Phase9BGuardianError(f"root could not be created safely: {path}") from exc


def write_receipt_exclusively(path: Path, raw: bytes, *, mode: int = _RECEIPT_MODE) -> str:
    """Write, fsync, re-read, and return the digest of what is on disk.

    Exclusive create so a receipt is never overwritten, and the re-read is what
    makes "the receipt landed" a fact rather than an assumption.
    """

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags, mode)
    except FileExistsError as exc:
        raise Phase9BGuardianError(f"receipt already exists: {path}") from exc
    except OSError as exc:
        raise Phase9BGuardianError(f"receipt could not be created safely: {path}") from exc
    try:
        view = memoryview(raw)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise Phase9BGuardianError("receipt write made no progress")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    reread = path.read_bytes()
    if reread != raw:
        raise Phase9BGuardianError(f"receipt bytes changed after fsync: {path}")
    return _sha256_bytes(reread)


# --- worker handshake --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkerHandshakeBinding:
    """Everything the Phase 9B worker handshake is bound to, in one record."""

    route: str
    attempt_id: str
    request_sha256: str
    payload_manifest_sha256: str
    permit_sha256: str
    runner_source_sha256: str
    resources_sha256: str
    inchikey: str
    electron_count: int
    cation_xyz_sha256: str
    neutral_xyz_sha256: str
    output_root: str
    cpu_affinity: str
    gpu_index: int
    timeout_seconds: int
    capability_identity_key: str


def build_worker_handshake_binding(
    *,
    verified: VerifiedPhase9BLaunch,
    consumed: ConsumedPhase9BPermit,
    profile: CandidateProfile = PHASE9B_CANDIDATE,
) -> WorkerHandshakeBinding:
    """Bind the handshake to this route, and refuse every cross-pairing.

    A direct handshake carrying an assisted permit, or the reverse, is the
    failure this exists to make impossible.
    """

    from nhc_deprot_ranker.quantum.two_endpoint import _PHASE9B_CAPABILITY_IDENTITY_KEY

    arguments = verified.arguments
    permit = consumed.permit
    if permit.route != arguments.route:
        raise Phase9BGuardianError("the consumed permit is for another route")
    if permit.attempt_id != arguments.attempt_id:
        raise Phase9BGuardianError("the consumed permit is for another attempt")
    if arguments.attempt_id != ROUTE_ATTEMPT_IDS[arguments.route]:
        raise Phase9BGuardianError("attempt identity does not match its route")
    if permit.request_sha256 != verified.request.request_sha256:
        raise Phase9BGuardianError("the consumed permit names another request")
    if permit.payload_manifest_sha256 != verified.payload_manifest_sha256:
        raise Phase9BGuardianError("the consumed permit names another payload manifest")
    if permit.runner_source_sha256 != arguments.expected_runner_source_sha256:
        raise Phase9BGuardianError("the consumed permit names another source closure")
    if consumed.consumed_sha256 != permit.permit_sha256:
        raise Phase9BGuardianError("the consumed record is not the permit that was validated")
    if permit.cation_xyz_sha256 != profile.cation_xyz_sha256:
        raise Phase9BGuardianError("the permit cation geometry is not the frozen initial one")
    if permit.neutral_xyz_sha256 != profile.neutral_xyz_sha256:
        raise Phase9BGuardianError("the permit neutral geometry is not the frozen initial one")
    if verified.authority.electron_count != profile.electron_count:
        raise Phase9BGuardianError("electron count disagrees with the candidate profile")
    if arguments.output_root != permit.output_root.as_posix():
        raise Phase9BGuardianError("the output root is not the permitted output root")
    if arguments.cpu_affinity != str(PHASE9B_RESOURCES["cpu_affinity"]):
        raise Phase9BGuardianError("CPU affinity is not the frozen affinity")
    if arguments.timeout_seconds != int(cast(int, PHASE9B_RESOURCES["hard_wall_timeout_seconds"])):
        raise Phase9BGuardianError("wall-time is not the frozen wall-time")

    return WorkerHandshakeBinding(
        route=arguments.route,
        attempt_id=arguments.attempt_id,
        request_sha256=permit.request_sha256,
        payload_manifest_sha256=permit.payload_manifest_sha256,
        permit_sha256=permit.permit_sha256,
        runner_source_sha256=permit.runner_source_sha256,
        resources_sha256=phase9b_resources_sha256(),
        inchikey=profile.inchikey,
        electron_count=profile.electron_count,
        cation_xyz_sha256=profile.cation_xyz_sha256,
        neutral_xyz_sha256=profile.neutral_xyz_sha256,
        output_root=arguments.output_root,
        cpu_affinity=arguments.cpu_affinity,
        gpu_index=arguments.gpu_index,
        timeout_seconds=arguments.timeout_seconds,
        capability_identity_key=_PHASE9B_CAPABILITY_IDENTITY_KEY,
    )


def validate_capability_reach(binding: WorkerHandshakeBinding) -> None:
    """Prove this route's attempt can actually obtain a compute capability.

    Checked here rather than discovered inside the worker after the permit is
    already spent.
    """

    from nhc_deprot_ranker.quantum.two_endpoint import _CAPABILITY_IDENTITY_EXPECTATIONS

    build = _CAPABILITY_IDENTITY_EXPECTATIONS.get(binding.capability_identity_key)
    if build is None:
        raise Phase9BGuardianError("no frozen capability expectation for this chain")
    expected = build()
    if binding.attempt_id not in expected.attempt_ids:
        raise Phase9BGuardianError(
            f"the capability expectation does not cover this attempt: {binding.attempt_id}"
        )
    if binding.inchikey != expected.inchikey or binding.electron_count != expected.electron_count:
        raise Phase9BGuardianError("the capability expectation names another candidate")
    if binding.resources_sha256 != expected.resources_sha256:
        raise Phase9BGuardianError("the capability expectation names another resource budget")


# --- detached spawn ----------------------------------------------------------


def spawn_detached_supervisor(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> SpawnedProcess:
    """Start the supervisor in its own session, with every stream accounted for.

    Structured rather than a shell trick: no ``&``, no ``nohup``, no free text.
    ``start_new_session=True`` makes the child a session and process-group leader,
    so it survives this guardian exiting and the SSH channel closing, and so the
    supervisor's own process-tree cleanup governs a group that contains only it
    and its descendants.

    stdin is ``/dev/null`` — a computation that reads stdin would otherwise block
    forever once SSH disconnects. stdout and stderr are exclusive-created files
    inside the frozen log root, so runtime output is durable evidence rather than
    something that dies with the channel. ``close_fds`` leaves the child nothing
    else inherited.
    """

    stdout_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    out_fd = os.open(stdout_path, stdout_flags, _LOG_MODE)
    err_fd: int | None = None
    devnull_fd: int | None = None
    try:
        err_fd = os.open(stderr_path, stdout_flags, _LOG_MODE)
        devnull_fd = os.open(os.devnull, os.O_RDONLY | os.O_CLOEXEC)
        try:
            process = subprocess.Popen(
                list(argv),
                cwd=str(cwd),
                env=dict(env),
                stdin=devnull_fd,
                stdout=out_fd,
                stderr=err_fd,
                close_fds=True,
                start_new_session=True,
                shell=False,
            )
        except OSError as exc:
            raise Phase9BGuardianError(f"supervisor spawn failed: {exc}") from exc
    finally:
        os.close(out_fd)
        if err_fd is not None:
            os.close(err_fd)
        if devnull_fd is not None:
            os.close(devnull_fd)

    pid = process.pid
    try:
        group = os.getpgid(pid)
        session = os.getsid(pid)
    except (OSError, AttributeError) as exc:
        # The child may exist; its identity is simply unreadable.  Unknown, not
        # failed, and never something to respawn.
        raise Phase9BGuardianError(f"spawned process identity is unreadable: {exc}") from exc
    if group != pid or session != pid:
        raise Phase9BGuardianError("the spawned process is not its own session leader")
    return SpawnedProcess(pid=pid, process_group_id=group, session_id=session)


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:  # pragma: no cover - platform-specific
        return exc.errno != errno.ESRCH
    return True


def await_spawn_acknowledgement(
    stdout_path: Path,
    *,
    spawned: SpawnedProcess,
    binding: WorkerHandshakeBinding,
    deadline_seconds: float = ACKNOWLEDGEMENT_TIMEOUT_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Read the supervisor's own identity line back, or refuse to claim a launch.

    A zero exit code proves nothing here — the guardian never sees one, because
    the supervisor is still running. What proves the launch is the supervisor
    naming itself: its entry, route, attempt, and PID, written by the process
    that holds them.

    That also closes the PID-reuse question as far as it can be closed. A
    recycled PID belonging to some unrelated process could not have written this
    file, and the guardian additionally requires the observed session leader to
    be that same PID.
    """

    started = monotonic()
    while True:
        if stdout_path.exists() and stdout_path.stat().st_size > 0:
            raw = stdout_path.read_bytes()[:_MAX_ACK_BYTES]
            line = raw.split(b"\n", 1)[0]
            if line:
                try:
                    decoded = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, ValueError) as exc:
                    raise Phase9BGuardianError(
                        "the supervisor's first output line is not strict JSON"
                    ) from exc
                if not isinstance(decoded, dict):
                    raise Phase9BGuardianError("the supervisor identity must be one JSON object")
                evidence = cast(dict[str, object], decoded)
                if evidence.get("entry") != SUPERVISOR_ENTRY:
                    raise Phase9BGuardianError("the started process is not the guarded supervisor")
                if evidence.get("route") != binding.route:
                    raise Phase9BGuardianError("the supervisor is bound to another route")
                if evidence.get("attempt_id") != binding.attempt_id:
                    raise Phase9BGuardianError("the supervisor is bound to another attempt")
                identity = evidence.get("supervisor_identity")
                if not isinstance(identity, str) or len(identity) != 64:
                    raise Phase9BGuardianError("the supervisor named no usable identity")
                if evidence.get("pid") != spawned.pid:
                    raise Phase9BGuardianError(
                        "the supervisor's own PID differs from the spawned PID"
                    )
                return evidence
        if monotonic() - started >= deadline_seconds:
            raise Phase9BGuardianError(
                "no supervisor acknowledgement within the bound; remote state unknown"
            )
        if not _process_alive(spawned.pid) and not stdout_path.exists():
            raise Phase9BGuardianError("the spawned supervisor exited before acknowledging")
        sleep(_ACK_POLL_SECONDS)


# --- the transaction ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GuardianOutcome:
    """Both receipts plus the acknowledgement the SSH caller receives."""

    consumption: PermitConsumptionReceipt
    launch: GuardianLaunchReceipt
    acknowledgement: dict[str, object]


def _acknowledgement(
    *, launch: GuardianLaunchReceipt, consumption: PermitConsumptionReceipt
) -> dict[str, object]:
    return {
        "schema_version": GUARDIAN_ACKNOWLEDGEMENT_SCHEMA_VERSION,
        "entry": GUARDIAN_ENTRY,
        "route": launch.route,
        "attempt_id": launch.attempt_id,
        "guardian_identity": launch.guardian_identity,
        "supervisor_entry": launch.supervisor_entry,
        "supervisor_pid": launch.supervisor_pid,
        "supervisor_process_group_id": launch.supervisor_process_group_id,
        "state": launch.state.value,
        "permit_sha256": launch.permit_sha256,
        "consumption_receipt_sha256": consumption.receipt_sha256,
        "launch_receipt_sha256": launch.receipt_sha256,
    }


def run_phase9b_guardian(
    arguments: Phase9BLaunchArguments,
    *,
    host_identity: str,
    project_root: Path,
    profile: CandidateProfile = PHASE9B_CANDIDATE,
    spawn: SpawnSupervisor | None = None,
    clock: Clock | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    acknowledgement_timeout_seconds: float = ACKNOWLEDGEMENT_TIMEOUT_SECONDS,
) -> GuardianOutcome:
    """Run the fixed guardian transaction exactly once.  Never retries."""

    from nhc_deprot_ranker.quantum import two_endpoint as runner

    if EXECUTION_AUTHORIZED is not True:
        raise Phase9BGuardianNotAuthorizedError("Phase 9B guardian execution is not authorized")
    if runner.EXECUTION_AUTHORIZED is not True:
        raise Phase9BGuardianNotAuthorizedError("the runner source execution gate is closed")
    if spawn is None:  # pragma: no cover - unreachable while the gates are closed
        raise Phase9BGuardianNotAuthorizedError("no production spawn path is wired")
    if not 0.0 < acknowledgement_timeout_seconds <= 600.0:
        raise ValueError("the acknowledgement timeout must be in (0, 600]")

    stamp = clock() if clock is not None else "1970-01-01T00:00:00Z"
    host_hash = _sha256_bytes(host_identity.encode("utf-8"))

    # 1-3. Verify every identity the argv asserts, before touching the permit.
    verified = verify_launch_arguments(arguments, profile=profile)
    run_root = verified.permit.run_root
    ready_path = run_root / READY_RELATIVE
    consumed_path = run_root / CONSUMED_RELATIVE

    # 4. The ready permit must exist and no consumed permit may.
    if consumed_path.exists() or consumed_path.is_symlink():
        raise Phase9BGuardianError("a consumed permit already exists; it is never restored")
    if not ready_path.is_file() or ready_path.is_symlink():
        raise Phase9BGuardianError("no ready permit is in place for this route")

    # 5. The linearization point.  Nothing below can restore the permit.
    try:
        consumed = consume_phase9b_permit(
            ready_path,
            expected_permit_sha256=arguments.expected_permit_sha256,
            expected_request_sha256=arguments.expected_request_sha256,
            expected_runner_source_sha256=arguments.expected_runner_source_sha256,
            expected_payload_manifest_sha256=arguments.expected_payload_manifest_sha256,
            profile=profile,
        )
    except Phase9BPermitConsumedError as exc:
        raise Phase9BGuardianError(f"the permit was already spent: {exc}") from exc
    except Phase9BPermitError as exc:
        raise Phase9BGuardianError(f"permit consumption refused: {exc}") from exc

    consumption = _build_consumption_receipt(
        arguments=arguments,
        verified=verified,
        consumed=consumed,
        host_hash=host_hash,
        stamp=stamp,
        profile=profile,
    )

    # From here on, every failure is terminal.  The attempt is spent.
    evidence_root = run_root / EVIDENCE_RELATIVE
    log_root = run_root / LOG_RELATIVE
    output_root = Path(arguments.output_root)

    def terminal(
        state: GuardianState, reason: str, spawned: SpawnedProcess | None = None
    ) -> GuardianOutcome:
        launch = _build_launch_receipt(
            arguments=arguments,
            binding=None,
            consumption=consumption,
            spawned=spawned,
            evidence_root=evidence_root,
            log_root=log_root,
            output_root=output_root,
            stamp=stamp,
            acknowledged_at=None,
            state=state,
            failure_reason=reason,
        )
        _try_write(evidence_root, LAUNCH_RECEIPT_RELATIVE, run_root, launch_receipt_payload(launch))
        return GuardianOutcome(
            consumption=consumption,
            launch=launch,
            acknowledgement=_acknowledgement(launch=launch, consumption=consumption),
        )

    # 6. Establish the roots, then persist the consumption receipt.
    try:
        _make_private_directory(evidence_root)
        _make_private_directory(log_root)
        _make_private_directory(output_root)
        write_receipt_exclusively(
            run_root / CONSUMPTION_RECEIPT_RELATIVE,
            _canonical_json_bytes(consumption_receipt_payload(consumption)),
        )
    except Phase9BGuardianError as exc:
        return terminal(GuardianState.PERMIT_CONSUMED_SPAWN_FAILED, str(exc))

    # 7. Build and verify the handshake.
    try:
        binding = build_worker_handshake_binding(
            verified=verified, consumed=consumed, profile=profile
        )
        validate_capability_reach(binding)
    except Phase9BGuardianError as exc:
        return terminal(GuardianState.PERMIT_CONSUMED_SPAWN_FAILED, str(exc))

    # 8. Spawn into an independent session.
    argv = build_supervisor_argv(arguments)
    try:
        spawned = spawn(
            argv,
            cwd=project_root,
            env=supervisor_environment(project_root=project_root, binding=binding),
            stdout_path=run_root / SUPERVISOR_STDOUT_RELATIVE,
            stderr_path=run_root / SUPERVISOR_STDERR_RELATIVE,
        )
    except Phase9BGuardianError as exc:
        return terminal(GuardianState.PERMIT_CONSUMED_SPAWN_FAILED, f"spawn failed: {exc}")
    except Exception as exc:  # the process may or may not exist
        return terminal(GuardianState.INDETERMINATE, f"spawn state unknown: {exc}")

    # 9. Obtain a verifiable acknowledgement.
    try:
        evidence = await_spawn_acknowledgement(
            run_root / SUPERVISOR_STDOUT_RELATIVE,
            spawned=spawned,
            binding=binding,
            deadline_seconds=acknowledgement_timeout_seconds,
            monotonic=monotonic,
            sleep=sleep,
        )
    except Phase9BGuardianError as exc:
        # It may be running.  Never kill it, never respawn, never claim success.
        return terminal(GuardianState.INDETERMINATE, str(exc), spawned=spawned)

    # 10. Write, fsync, and re-read the launch receipt.
    launch = _build_launch_receipt(
        arguments=arguments,
        binding=binding,
        consumption=consumption,
        spawned=spawned,
        evidence_root=evidence_root,
        log_root=log_root,
        output_root=output_root,
        stamp=stamp,
        acknowledged_at=stamp,
        state=GuardianState.PERMIT_CONSUMED_SPAWNED,
        failure_reason=None,
        guardian_identity=str(evidence["supervisor_identity"]),
    )
    try:
        written = write_receipt_exclusively(
            run_root / LAUNCH_RECEIPT_RELATIVE,
            _canonical_json_bytes(launch_receipt_payload(launch)),
        )
    except Phase9BGuardianError as exc:
        # The supervisor is running but the record did not land.  Unknown.
        return terminal(GuardianState.INDETERMINATE, f"receipt write failed: {exc}", spawned)
    if written != _sha256_bytes(_canonical_json_bytes(launch_receipt_payload(launch))):
        return terminal(GuardianState.INDETERMINATE, "launch receipt digest drifted", spawned)

    return GuardianOutcome(
        consumption=consumption,
        launch=launch,
        acknowledgement=_acknowledgement(launch=launch, consumption=consumption),
    )


def _try_write(
    evidence_root: Path, relative: str, run_root: Path, payload: dict[str, object]
) -> None:
    """Best-effort terminal-record write.  Never masks the failure it records."""

    try:
        if not evidence_root.is_dir():
            return
        write_receipt_exclusively(run_root / relative, _canonical_json_bytes(payload))
    except (Phase9BGuardianError, OSError):
        return


def _build_consumption_receipt(
    *,
    arguments: Phase9BLaunchArguments,
    verified: VerifiedPhase9BLaunch,
    consumed: ConsumedPhase9BPermit,
    host_hash: str,
    stamp: str,
    profile: CandidateProfile,
) -> PermitConsumptionReceipt:
    draft = PermitConsumptionReceipt(
        schema_version=PERMIT_CONSUMPTION_RECEIPT_SCHEMA_VERSION,
        phase="9B",
        candidate_inchikey=profile.inchikey,
        route=arguments.route,
        attempt_id=arguments.attempt_id,
        ready_path=consumed.permit.ready_path.as_posix(),
        consumed_path=consumed.consumed_path.as_posix(),
        permit_sha256=consumed.permit.permit_sha256,
        consumed_sha256=consumed.consumed_sha256,
        request_sha256=verified.request.request_sha256,
        payload_manifest_sha256=verified.payload_manifest_sha256,
        runner_source_sha256=arguments.expected_runner_source_sha256,
        resources_sha256=phase9b_resources_sha256(),
        host_identity_sha256=host_hash,
        consumed_at=stamp,
        state=ConsumptionState.CONSUMED,
        failure_reason=None,
        receipt_sha256="",
    )
    return replace(draft, receipt_sha256=consumption_receipt_sha256(draft))


def _build_launch_receipt(
    *,
    arguments: Phase9BLaunchArguments,
    binding: WorkerHandshakeBinding | None,
    consumption: PermitConsumptionReceipt,
    spawned: SpawnedProcess | None,
    evidence_root: Path,
    log_root: Path,
    output_root: Path,
    stamp: str,
    acknowledged_at: str | None,
    state: GuardianState,
    failure_reason: str | None,
    guardian_identity: str = "",
) -> GuardianLaunchReceipt:
    del binding
    argv = build_supervisor_argv(arguments)
    draft = GuardianLaunchReceipt(
        schema_version=GUARDIAN_LAUNCH_RECEIPT_SCHEMA_VERSION,
        phase="9B",
        route=arguments.route,
        attempt_id=arguments.attempt_id,
        guardian_identity=guardian_identity,
        supervisor_entry=SUPERVISOR_ENTRY,
        supervisor_pid=None if spawned is None else spawned.pid,
        supervisor_process_group_id=None if spawned is None else spawned.process_group_id,
        supervisor_session_id=None if spawned is None else spawned.session_id,
        argv_sha256=_sha256_bytes(_canonical_json_bytes(list(argv))),
        request_sha256=arguments.expected_request_sha256,
        payload_manifest_sha256=arguments.expected_payload_manifest_sha256,
        permit_sha256=arguments.expected_permit_sha256,
        runner_source_sha256=arguments.expected_runner_source_sha256,
        resources_sha256=arguments.expected_resources_sha256,
        output_root=output_root.as_posix(),
        evidence_root=evidence_root.as_posix(),
        log_root=log_root.as_posix(),
        consumption_receipt_sha256=consumption.receipt_sha256,
        spawned_at=stamp,
        acknowledged_at=acknowledged_at,
        state=state,
        failure_reason=failure_reason,
        receipt_sha256="",
    )
    return replace(draft, receipt_sha256=launch_receipt_sha256(draft))


def build_supervisor_argv(arguments: Phase9BLaunchArguments) -> tuple[str, ...]:
    """The argv the guardian starts, rebuilt from the arguments it verified."""

    values: dict[str, str] = {
        "--route": arguments.route,
        "--attempt-id": arguments.attempt_id,
        "--request-path": arguments.request_path,
        "--output-root": arguments.output_root,
        "--permit-path": arguments.permit_path,
        "--expected-request-sha256": arguments.expected_request_sha256,
        "--expected-payload-manifest-sha256": arguments.expected_payload_manifest_sha256,
        "--expected-permit-sha256": arguments.expected_permit_sha256,
        "--expected-runner-source-sha256": arguments.expected_runner_source_sha256,
        "--expected-resources-sha256": arguments.expected_resources_sha256,
        "--gpu-index": str(arguments.gpu_index),
        "--cpu-affinity": arguments.cpu_affinity,
        "--timeout-seconds": str(arguments.timeout_seconds),
    }
    argv: list[str] = [sys.executable, "-B", "-s", "-m", SUPERVISOR_ENTRY]
    for flag in REQUIRED_FLAGS:
        argv.append(flag)
        argv.append(values[flag])
    return tuple(argv)


def supervisor_environment(
    *, project_root: Path, binding: WorkerHandshakeBinding
) -> dict[str, str]:
    """A closed environment.  Nothing is inherited implicitly."""

    return {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(project_root / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "CUDA_VISIBLE_DEVICES": str(binding.gpu_index),
        "OMP_NUM_THREADS": str(PHASE9B_RESOURCES["computational_threads"]),
        "MKL_NUM_THREADS": str(PHASE9B_RESOURCES["computational_threads"]),
        "OPENBLAS_NUM_THREADS": str(PHASE9B_RESOURCES["computational_threads"]),
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    host_identity: str = "guardian",
    project_root: Path | None = None,
    spawn: SpawnSupervisor | None = None,
    stdout: object | None = None,
    profile: CandidateProfile = PHASE9B_CANDIDATE,
) -> int:
    """Parse, run the transaction, print the acknowledgement, exit promptly."""

    arguments = parse_supervisor_argv(list(sys.argv[1:] if argv is None else argv))
    root = project_root if project_root is not None else Path.cwd()
    outcome = run_phase9b_guardian(
        arguments,
        host_identity=host_identity,
        project_root=root,
        profile=profile,
        spawn=spawn if spawn is not None else spawn_detached_supervisor,
    )
    stream = sys.stdout if stdout is None else stdout
    write = cast(Callable[[str], object], stream.write)  # type: ignore[union-attr]
    write(json.dumps(outcome.acknowledgement, sort_keys=True) + "\n")
    flush = getattr(stream, "flush", None)
    if callable(flush):
        flush()
    return 0 if outcome.launch.state is GuardianState.PERMIT_CONSUMED_SPAWNED else 1


__all__ = [
    "ACKNOWLEDGEMENT_TIMEOUT_SECONDS",
    "CONSUMPTION_RECEIPT_RELATIVE",
    "EXECUTION_AUTHORIZED",
    "GUARDIAN_ACKNOWLEDGEMENT_SCHEMA_VERSION",
    "GUARDIAN_ENTRY",
    "GUARDIAN_LAUNCH_RECEIPT_SCHEMA_VERSION",
    "LAUNCH_RECEIPT_RELATIVE",
    "PERMIT_CONSUMPTION_RECEIPT_SCHEMA_VERSION",
    "SUPERVISOR_STDERR_RELATIVE",
    "SUPERVISOR_STDOUT_RELATIVE",
    "ConsumptionState",
    "GuardianLaunchReceipt",
    "GuardianOutcome",
    "GuardianState",
    "PermitConsumptionReceipt",
    "Phase9BGuardianError",
    "Phase9BGuardianNotAuthorizedError",
    "SpawnSupervisor",
    "SpawnedProcess",
    "WorkerHandshakeBinding",
    "await_spawn_acknowledgement",
    "build_supervisor_argv",
    "build_worker_handshake_binding",
    "consumption_receipt_payload",
    "consumption_receipt_sha256",
    "launch_receipt_payload",
    "launch_receipt_sha256",
    "main",
    "run_phase9b_guardian",
    "spawn_detached_supervisor",
    "supervisor_environment",
    "validate_capability_reach",
    "write_receipt_exclusively",
]
