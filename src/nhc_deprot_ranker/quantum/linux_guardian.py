"""Linux-only process identity and deadline-guardian primitives.

This module deliberately imports only the Python standard library.  It does
not know about requests, chemistry backends, or execution authorization.  The
Phase 8B launcher can therefore use it before any compute dependency imports.
"""

from __future__ import annotations

import ctypes
import os
import re
import select
import signal
import sys
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

_PR_SET_PDEATHSIG: Final = 1
_PR_SET_CHILD_SUBREAPER: Final = 36
_PR_GET_CHILD_SUBREAPER: Final = 37
_START_RELEASE_PREFIX: Final = b"NHC_PHASE8B_RELEASE_V1 "
_START_RELEASE_TOKEN = re.compile(r"[0-9a-f]{64}")
_MAX_START_FRAME_BYTES: Final = len(_START_RELEASE_PREFIX) + 64 + 1

Prctl = Callable[[int, int, int, int, int], int]
AffinityReader = Callable[[int], frozenset[int]]


class GuardianError(RuntimeError):
    """Base class for fail-closed guardian errors."""


class GuardianPlatformError(GuardianError):
    """The required Linux primitive is unavailable."""


class ProcessIdentityError(GuardianError):
    """A process identity is malformed, unavailable, or has changed."""


class AffinityViolationError(GuardianError):
    """A process or thread escaped the frozen CPU affinity."""


class StartupHandshakeError(GuardianError):
    """The worker was not safely released before its absolute deadline."""


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """PID identity that remains meaningful across parent adoption."""

    pid: int
    ppid: int
    pgid: int
    sid: int
    starttime_ticks: int
    state: str
    boot_id: str
    cpus_allowed: frozenset[int]


def parse_cpu_list(raw: str) -> frozenset[int]:
    """Parse Linux ``Cpus_allowed_list`` syntax into an exact set."""

    cpus: set[int] = set()
    text = raw.strip()
    if not text:
        raise ProcessIdentityError("CPU affinity list is empty")
    for item in text.split(","):
        fields = item.split("-", 1)
        try:
            start = int(fields[0])
            stop = start if len(fields) == 1 else int(fields[1])
        except ValueError as exc:
            raise ProcessIdentityError("CPU affinity list is malformed") from exc
        if start < 0 or stop < start:
            raise ProcessIdentityError("CPU affinity range is invalid")
        cpus.update(range(start, stop + 1))
    if not cpus:
        raise ProcessIdentityError("CPU affinity list is empty")
    return frozenset(cpus)


def _read_boot_id(proc_root: Path) -> str:
    try:
        boot_id = (proc_root / "sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise ProcessIdentityError("Linux boot identity is unavailable") from exc
    if not boot_id or any(character.isspace() for character in boot_id):
        raise ProcessIdentityError("Linux boot identity is malformed")
    return boot_id


def _cpus_from_status(status_path: Path) -> frozenset[int]:
    try:
        lines = status_path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ProcessIdentityError(f"process status is unavailable: {status_path}") from exc
    values = [
        line.split(":", 1)[1].strip() for line in lines if line.startswith("Cpus_allowed_list:")
    ]
    if len(values) != 1:
        raise ProcessIdentityError("process status must contain one Cpus_allowed_list")
    return parse_cpu_list(values[0])


def read_process_identity(pid: int, *, proc_root: Path = Path("/proc")) -> ProcessIdentity:
    """Read a Linux process identity without relying on names or argv text."""

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("pid must be a positive integer")
    stat_path = proc_root / str(pid) / "stat"
    try:
        raw_stat = stat_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise ProcessIdentityError(f"process stat is unavailable for pid {pid}") from exc

    open_paren = raw_stat.find("(")
    close_paren = raw_stat.rfind(")")
    if open_paren <= 0 or close_paren <= open_paren or close_paren + 2 > len(raw_stat):
        raise ProcessIdentityError("process stat has malformed comm delimiters")
    try:
        stat_pid = int(raw_stat[:open_paren].strip())
    except ValueError as exc:
        raise ProcessIdentityError("process stat has malformed pid") from exc
    if stat_pid != pid:
        raise ProcessIdentityError("process stat pid does not match requested pid")

    # The suffix begins at field 3 (state); starttime is field 22, index 19.
    suffix = raw_stat[close_paren + 1 :].split()
    if len(suffix) <= 19 or len(suffix[0]) != 1:
        raise ProcessIdentityError("process stat is too short")
    try:
        ppid = int(suffix[1])
        pgid = int(suffix[2])
        sid = int(suffix[3])
        starttime_ticks = int(suffix[19])
    except ValueError as exc:
        raise ProcessIdentityError("process stat identity fields are malformed") from exc
    if min(ppid, pgid, sid, starttime_ticks) < 0:
        raise ProcessIdentityError("process stat identity fields are invalid")

    return ProcessIdentity(
        pid=pid,
        ppid=ppid,
        pgid=pgid,
        sid=sid,
        starttime_ticks=starttime_ticks,
        state=suffix[0],
        boot_id=_read_boot_id(proc_root),
        cpus_allowed=_cpus_from_status(proc_root / str(pid) / "status"),
    )


def read_task_affinities(pid: int, *, proc_root: Path = Path("/proc")) -> dict[int, frozenset[int]]:
    """Read the affinity of every currently observable thread for ``pid``."""

    task_root = proc_root / str(pid) / "task"
    try:
        entries = tuple(task_root.iterdir())
    except OSError as exc:
        raise ProcessIdentityError(f"task inventory is unavailable for pid {pid}") from exc
    result: dict[int, frozenset[int]] = {}
    for entry in sorted(entries, key=lambda path: path.name):
        if not entry.name.isdigit():
            continue
        tid = int(entry.name)
        try:
            result[tid] = _cpus_from_status(entry / "status")
        except ProcessIdentityError:
            if not entry.exists():
                continue
            raise
    if not result:
        raise ProcessIdentityError(f"no task affinity is observable for pid {pid}")
    return result


def list_process_group_members(
    registered: ProcessIdentity, *, proc_root: Path = Path("/proc")
) -> tuple[ProcessIdentity, ...]:
    """Return exact-session members of a registered process group."""

    try:
        entries = tuple(proc_root.iterdir())
    except OSError as exc:
        raise ProcessIdentityError("process inventory is unavailable") from exc
    members: list[ProcessIdentity] = []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            observed = read_process_identity(int(entry.name), proc_root=proc_root)
        except ProcessIdentityError:
            continue
        if (
            observed.boot_id == registered.boot_id
            and observed.pgid == registered.pgid
            and observed.sid == registered.sid
        ):
            members.append(observed)
    return tuple(sorted(members, key=lambda identity: identity.pid))


def same_process(expected: ProcessIdentity, observed: ProcessIdentity) -> bool:
    """Compare the non-reusable portion of two process identities."""

    return (
        expected.pid,
        expected.pgid,
        expected.sid,
        expected.starttime_ticks,
        expected.boot_id,
    ) == (
        observed.pid,
        observed.pgid,
        observed.sid,
        observed.starttime_ticks,
        observed.boot_id,
    )


def require_same_process(expected: ProcessIdentity, observed: ProcessIdentity) -> None:
    """Fail closed rather than treating a reused PID as the registered process."""

    if not same_process(expected, observed):
        raise ProcessIdentityError("registered process identity changed")


def require_affinity(
    observed: frozenset[int], allowed: frozenset[int], *, exact: bool = False
) -> None:
    """Require a non-empty affinity inside the frozen CPU ceiling."""

    if not observed or (observed != allowed if exact else not observed.issubset(allowed)):
        raise AffinityViolationError(
            f"CPU affinity {sorted(observed)} escaped frozen set {sorted(allowed)}"
        )


def _linux_prctl(option: int, arg2: int, arg3: int, arg4: int, arg5: int) -> int:
    if not sys.platform.startswith("linux"):
        raise GuardianPlatformError("prctl requires Linux")
    libc = ctypes.CDLL(None, use_errno=True)
    result = int(libc.prctl(option, arg2, arg3, arg4, arg5))
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))
    return result


def install_parent_death_signal(
    expected_parent_pid: int,
    *,
    signal_number: int = signal.SIGKILL,
    prctl: Prctl | None = None,
    getppid: Callable[[], int] = os.getppid,
) -> None:
    """Install PDEATHSIG and close the race by rechecking the parent PID."""

    if expected_parent_pid <= 1:
        raise ValueError("expected_parent_pid must be greater than one")
    if signal_number <= 0:
        raise ValueError("signal_number must be positive")
    call_prctl = _linux_prctl if prctl is None else prctl
    if call_prctl(_PR_SET_PDEATHSIG, int(signal_number), 0, 0, 0) != 0:
        raise GuardianPlatformError("PR_SET_PDEATHSIG failed")
    if getppid() != expected_parent_pid:
        raise StartupHandshakeError("parent changed while installing PDEATHSIG")


def _set_subreaper_default() -> None:
    _linux_prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0)


def _get_subreaper_default() -> bool:
    if not sys.platform.startswith("linux"):
        raise GuardianPlatformError("subreaper requires Linux")
    value = ctypes.c_int(0)
    libc = ctypes.CDLL(None, use_errno=True)
    result = int(libc.prctl(_PR_GET_CHILD_SUBREAPER, ctypes.byref(value), 0, 0, 0))
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))
    return value.value == 1


def enable_child_subreaper(
    *,
    setter: Callable[[], None] = _set_subreaper_default,
    getter: Callable[[], bool] = _get_subreaper_default,
) -> None:
    """Enable and verify adoption of descendants after supervisor death."""

    setter()
    if not getter():
        raise GuardianPlatformError("PR_SET_CHILD_SUBREAPER did not take effect")


def start_release_frame(token: str) -> bytes:
    """Build the only accepted pre-import release frame."""

    if _START_RELEASE_TOKEN.fullmatch(token) is None:
        raise ValueError("release token must be exactly 64 lowercase hexadecimal characters")
    return _START_RELEASE_PREFIX + token.encode("ascii") + b"\n"


def _wait_readable(fd: int, timeout_seconds: float) -> bool:
    readable, _, _ = select.select([fd], [], [], timeout_seconds)
    return bool(readable)


def await_start_release(
    read_fd: int,
    *,
    expected_token: str,
    absolute_deadline_ns: int,
    clock_ns: Callable[[], int] = time.monotonic_ns,
    wait_readable: Callable[[int, float], bool] = _wait_readable,
    read_bytes: Callable[[int, int], bytes] = os.read,
    close_fd: Callable[[int], None] = os.close,
) -> None:
    """Wait for one exact frame and EOF, closing ``read_fd`` on every path."""

    if read_fd < 0:
        raise ValueError("read_fd must be non-negative")
    if absolute_deadline_ns <= 0:
        raise ValueError("absolute_deadline_ns must be positive")
    expected = start_release_frame(expected_token)
    received = bytearray()
    try:
        while True:
            remaining_ns = absolute_deadline_ns - clock_ns()
            if remaining_ns <= 0:
                raise StartupHandshakeError("pre-import release deadline expired")
            try:
                ready = wait_readable(read_fd, remaining_ns / 1_000_000_000)
            except InterruptedError:
                continue
            if not ready:
                continue
            try:
                chunk = read_bytes(read_fd, _MAX_START_FRAME_BYTES + 1 - len(received))
            except InterruptedError:
                continue
            if not chunk:
                if bytes(received) != expected:
                    raise StartupHandshakeError("release pipe closed without the exact frame")
                return
            received.extend(chunk)
            if len(received) > _MAX_START_FRAME_BYTES or not expected.startswith(received):
                raise StartupHandshakeError("pre-import release frame is invalid")
    finally:
        with suppress(OSError):
            close_fd(read_fd)


def send_start_release(
    write_fd: int,
    *,
    token: str,
    write_bytes: Callable[[int, bytes], int] = os.write,
    close_fd: Callable[[int], None] = os.close,
) -> None:
    """Write one release frame completely and close the unique write end."""

    frame = start_release_frame(token)
    offset = 0
    try:
        while offset < len(frame):
            written = write_bytes(write_fd, frame[offset:])
            if written <= 0:
                raise StartupHandshakeError("release pipe write made no progress")
            offset += written
    finally:
        with suppress(OSError):
            close_fd(write_fd)


def _sched_getaffinity(pid: int) -> frozenset[int]:
    getaffinity = getattr(os, "sched_getaffinity", None)
    if getaffinity is None:
        raise GuardianPlatformError("sched_getaffinity requires Linux")
    return frozenset(getaffinity(pid))


def perform_preimport_handshake(
    read_fd: int,
    *,
    expected_token: str,
    expected_parent_pid: int,
    absolute_deadline_ns: int,
    allowed_cpus: frozenset[int],
    install_pdeath: Callable[[int], None] = install_parent_death_signal,
    affinity_reader: AffinityReader = _sched_getaffinity,
    clock_ns: Callable[[], int] = time.monotonic_ns,
) -> None:
    """Contain parent death and verify release before compute imports."""

    install_pdeath(expected_parent_pid)
    require_affinity(affinity_reader(0), allowed_cpus, exact=True)
    await_start_release(
        read_fd,
        expected_token=expected_token,
        absolute_deadline_ns=absolute_deadline_ns,
        clock_ns=clock_ns,
    )
    if clock_ns() >= absolute_deadline_ns:
        raise StartupHandshakeError("absolute deadline expired during release")
    require_affinity(affinity_reader(0), allowed_cpus, exact=True)


GuardianOutcome = Literal[
    "clean",
    "deadline",
    "abort",
    "affinity_violation",
    "identity_mismatch",
    "cleanup_failed",
]


@dataclass(frozen=True, slots=True)
class GuardianPolicy:
    """One absolute process-group deadline and its bounded cleanup windows."""

    absolute_deadline_ns: int
    allowed_cpus: frozenset[int]
    terminate_grace_ns: int = 10_000_000_000
    kill_wait_ns: int = 5_000_000_000
    poll_interval_ns: int = 100_000_000

    def __post_init__(self) -> None:
        values = (
            self.absolute_deadline_ns,
            self.terminate_grace_ns,
            self.kill_wait_ns,
            self.poll_interval_ns,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise TypeError("guardian timing values must be integer nanoseconds")
        if self.absolute_deadline_ns <= 0:
            raise ValueError("absolute_deadline_ns must be positive")
        if self.terminate_grace_ns < 0 or self.kill_wait_ns < 0:
            raise ValueError("cleanup windows must be non-negative")
        if self.poll_interval_ns <= 0:
            raise ValueError("poll_interval_ns must be positive")
        if not self.allowed_cpus:
            raise ValueError("allowed_cpus must not be empty")


@dataclass(frozen=True, slots=True)
class GuardianResult:
    """Bounded outcome of monitoring one registered process group."""

    outcome: GuardianOutcome
    trigger: str | None
    term_sent: bool
    kill_sent: bool
    group_cleanup_confirmed: bool
    duration_ns: int
    error_message: str | None = None


def _never_abort() -> bool:
    return False


def _send_group_signal(pgid: int, signal_number: int) -> None:
    os.killpg(pgid, signal_number)


def guard_process_group(
    registered: ProcessIdentity,
    *,
    policy: GuardianPolicy,
    proc_root: Path = Path("/proc"),
    read_identity: Callable[[int], ProcessIdentity] | None = None,
    list_members: Callable[[ProcessIdentity], tuple[ProcessIdentity, ...]] | None = None,
    task_affinities: Callable[[int], Mapping[int, frozenset[int]]] | None = None,
    send_group_signal: Callable[[int, int], None] = _send_group_signal,
    abort_requested: Callable[[], bool] = _never_abort,
    clock_ns: Callable[[], int] = time.monotonic_ns,
    sleep: Callable[[float], None] = time.sleep,
    forbidden_pgids: frozenset[int] = frozenset(),
) -> GuardianResult:
    """Monitor and, when triggered, clean one exact registered process group.

    The caller must keep the process-group leader unreaped until this function
    confirms the group empty.  This makes the leader PID unavailable for reuse
    during the validation-to-signal interval.
    """

    if registered.pid <= 1 or registered.pid != registered.pgid or registered.pid != registered.sid:
        raise ProcessIdentityError("guardian requires a safe session/process-group leader")
    unsafe_groups = {0, 1, os.getpgrp(), *forbidden_pgids}
    if registered.pgid in unsafe_groups:
        raise ProcessIdentityError("registered process group is unsafe to signal")
    reader = (
        (lambda pid: read_process_identity(pid, proc_root=proc_root))
        if read_identity is None
        else read_identity
    )
    member_reader = (
        (lambda identity: list_process_group_members(identity, proc_root=proc_root))
        if list_members is None
        else list_members
    )
    affinity_reader = (
        (lambda pid: read_task_affinities(pid, proc_root=proc_root))
        if task_affinities is None
        else task_affinities
    )
    started_ns = clock_ns()

    def result(
        outcome: GuardianOutcome,
        *,
        trigger: str | None,
        term_sent: bool,
        kill_sent: bool,
        cleanup: bool,
        error: str | None = None,
    ) -> GuardianResult:
        return GuardianResult(
            outcome=outcome,
            trigger=trigger,
            term_sent=term_sent,
            kill_sent=kill_sent,
            group_cleanup_confirmed=cleanup,
            duration_ns=max(0, clock_ns() - started_ns),
            error_message=error,
        )

    def live_members() -> tuple[ProcessIdentity, ...]:
        members = member_reader(registered)
        for member in members:
            if member.boot_id != registered.boot_id or (
                member.pgid,
                member.sid,
            ) != (registered.pgid, registered.sid):
                raise ProcessIdentityError("process-group inventory crossed identity boundary")
        return tuple(member for member in members if member.state.upper() != "Z")

    def validate_leader() -> ProcessIdentity:
        observed = reader(registered.pid)
        require_same_process(registered, observed)
        return observed

    def validate_affinities(members: tuple[ProcessIdentity, ...]) -> None:
        for member in members:
            require_affinity(member.cpus_allowed, policy.allowed_cpus)
            for observed in affinity_reader(member.pid).values():
                require_affinity(observed, policy.allowed_cpus)

    trigger: GuardianOutcome | None = None
    while trigger is None:
        try:
            members = live_members()
            if not members:
                if clock_ns() >= policy.absolute_deadline_ns:
                    return result(
                        "deadline",
                        trigger="deadline",
                        term_sent=False,
                        kill_sent=False,
                        cleanup=True,
                    )
                return result(
                    "clean",
                    trigger=None,
                    term_sent=False,
                    kill_sent=False,
                    cleanup=True,
                )
            validate_leader()
            validate_affinities(members)
        except AffinityViolationError:
            trigger = "affinity_violation"
            break
        except ProcessIdentityError as exc:
            return result(
                "identity_mismatch",
                trigger="identity_mismatch",
                term_sent=False,
                kill_sent=False,
                cleanup=False,
                error=str(exc),
            )
        now_ns = clock_ns()
        if abort_requested():
            trigger = "abort"
        elif now_ns >= policy.absolute_deadline_ns:
            trigger = "deadline"
        else:
            sleep(min(policy.poll_interval_ns, policy.absolute_deadline_ns - now_ns) / 1e9)

    term_sent = False
    kill_sent = False
    try:
        validate_leader()
        send_group_signal(registered.pgid, signal.SIGTERM)
        term_sent = True
    except (OSError, ProcessIdentityError) as exc:
        try:
            if not live_members():
                return result(
                    trigger,
                    trigger=trigger,
                    term_sent=term_sent,
                    kill_sent=False,
                    cleanup=True,
                )
        except ProcessIdentityError:
            pass
        outcome: GuardianOutcome = (
            "identity_mismatch" if isinstance(exc, ProcessIdentityError) else "cleanup_failed"
        )
        return result(
            outcome,
            trigger=trigger,
            term_sent=term_sent,
            kill_sent=False,
            cleanup=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    grace_deadline = clock_ns() + policy.terminate_grace_ns
    while clock_ns() < grace_deadline:
        try:
            if not live_members():
                return result(
                    trigger,
                    trigger=trigger,
                    term_sent=term_sent,
                    kill_sent=False,
                    cleanup=True,
                )
            validate_leader()
        except ProcessIdentityError as exc:
            return result(
                "identity_mismatch",
                trigger=trigger,
                term_sent=term_sent,
                kill_sent=False,
                cleanup=False,
                error=str(exc),
            )
        sleep(min(policy.poll_interval_ns, grace_deadline - clock_ns()) / 1e9)

    try:
        if not live_members():
            return result(
                trigger,
                trigger=trigger,
                term_sent=term_sent,
                kill_sent=False,
                cleanup=True,
            )
        validate_leader()
        send_group_signal(registered.pgid, signal.SIGKILL)
        kill_sent = True
    except (OSError, ProcessIdentityError) as exc:
        outcome = "identity_mismatch" if isinstance(exc, ProcessIdentityError) else "cleanup_failed"
        return result(
            outcome,
            trigger=trigger,
            term_sent=term_sent,
            kill_sent=kill_sent,
            cleanup=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    kill_deadline = clock_ns() + policy.kill_wait_ns
    while clock_ns() < kill_deadline:
        try:
            if not live_members():
                return result(
                    trigger,
                    trigger=trigger,
                    term_sent=term_sent,
                    kill_sent=kill_sent,
                    cleanup=True,
                )
            validate_leader()
        except ProcessIdentityError as exc:
            return result(
                "identity_mismatch",
                trigger=trigger,
                term_sent=term_sent,
                kill_sent=kill_sent,
                cleanup=False,
                error=str(exc),
            )
        sleep(min(policy.poll_interval_ns, kill_deadline - clock_ns()) / 1e9)
    try:
        cleanup_confirmed = not live_members()
    except ProcessIdentityError as exc:
        return result(
            "identity_mismatch",
            trigger=trigger,
            term_sent=term_sent,
            kill_sent=kill_sent,
            cleanup=False,
            error=str(exc),
        )
    return result(
        trigger if cleanup_confirmed else "cleanup_failed",
        trigger=trigger,
        term_sent=term_sent,
        kill_sent=kill_sent,
        cleanup=cleanup_confirmed,
        error=None if cleanup_confirmed else "registered process group survived SIGKILL",
    )
