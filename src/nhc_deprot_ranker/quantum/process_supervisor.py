"""Small POSIX process-tree supervisor with a hard wall-time.

The supervisor deliberately has no chemistry dependencies.  It starts one
argv-only child in a fresh session, continuously drains both output pipes, and
keeps the process-group leader unreaped until every required group signal has
been sent.  Keeping the leader unreaped prevents its PID/process-group ID from
being reused during cleanup.
"""

from __future__ import annotations

import math
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Final, Literal, cast

SupervisionOutcome = Literal[
    "clean",
    "nonzero",
    "timeout",
    "spawn_error",
    "supervision_error",
    "orphan_descendants",
]

TIMEOUT_RETURN_CODE: Final[int] = 124
SUPERVISION_FAILURE_RETURN_CODE: Final[int] = 1
_READ_SIZE: Final[int] = 64 * 1024
_KILL_WAIT_SECONDS: Final[float] = 5.0
_FINAL_WAIT_SECONDS: Final[float] = 5.0
_READER_JOIN_SECONDS: Final[float] = 5.0


@dataclass(frozen=True, slots=True)
class SupervisionPolicy:
    """Bounds used while supervising one process group."""

    timeout_seconds: float
    terminate_grace_seconds: float = 5.0
    stream_capture_limit_bytes: int = 1024 * 1024
    poll_interval_seconds: float = 0.01
    absolute_deadline_monotonic: float | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0.0:
            raise ValueError("timeout_seconds must be finite and greater than zero")
        if not math.isfinite(self.terminate_grace_seconds) or self.terminate_grace_seconds < 0.0:
            raise ValueError("terminate_grace_seconds must be finite and non-negative")
        if self.stream_capture_limit_bytes < 0:
            raise ValueError("stream_capture_limit_bytes must be non-negative")
        if not math.isfinite(self.poll_interval_seconds) or self.poll_interval_seconds <= 0.0:
            raise ValueError("poll_interval_seconds must be finite and greater than zero")
        if self.absolute_deadline_monotonic is not None and (
            not math.isfinite(self.absolute_deadline_monotonic)
            or self.absolute_deadline_monotonic <= 0.0
        ):
            raise ValueError("absolute_deadline_monotonic must be finite and greater than zero")


@dataclass(frozen=True, slots=True)
class SupervisionResult:
    """Complete, bounded observation of one supervised invocation."""

    outcome: SupervisionOutcome
    returncode: int | None
    child_returncode: int | None
    stdout: bytes
    stderr: bytes
    stdout_total_bytes: int
    stderr_total_bytes: int
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool
    term_sent: bool
    kill_sent: bool
    orphan_descendants_detected: bool
    process_started: bool
    group_cleanup_confirmed: bool
    direct_child_reaped: bool
    duration_seconds: float
    pid: int | None
    pgid: int | None
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        """Whether the child exited zero without timeout or descendants."""

        return self.outcome == "clean" and self.group_cleanup_confirmed and self.direct_child_reaped

    @property
    def safe_to_finalize(self) -> bool:
        """Whether no child can still mutate caller-owned scratch state."""

        return not self.process_started or (
            self.group_cleanup_confirmed and self.direct_child_reaped
        )


@dataclass(slots=True)
class _Capture:
    limit: int
    chunks: list[bytes] = field(default_factory=list)
    total_bytes: int = 0
    error_message: str | None = None

    def drain(self, stream: BinaryIO) -> None:
        try:
            while True:
                chunk = stream.read(_READ_SIZE)
                if not chunk:
                    return
                self.total_bytes += len(chunk)
                retained = sum(len(item) for item in self.chunks)
                remaining = self.limit - retained
                if remaining > 0:
                    self.chunks.append(chunk[:remaining])
        except (OSError, ValueError) as exc:
            self.error_message = f"{type(exc).__name__}: {exc}"

    @property
    def data(self) -> bytes:
        return b"".join(self.chunks)

    @property
    def truncated(self) -> bool:
        return self.total_bytes > len(self.data)


@dataclass(frozen=True, slots=True)
class _GroupIdentity:
    leader_pid: int
    pgid: int


class _SupervisionFailure(RuntimeError):
    pass


def _child_exit_is_waitable(pid: int) -> bool:
    """Observe child exit without reaping the process-group leader."""

    flags = os.WEXITED | os.WNOHANG | os.WNOWAIT
    waitid = getattr(os, "waitid", None)
    if waitid is None:
        raise _SupervisionFailure("POSIX waitid with WNOWAIT is required")
    typed_waitid = cast(Callable[[int, int, int], object | None], waitid)
    try:
        return typed_waitid(os.P_PID, pid, flags) is not None
    except InterruptedError:
        return False
    except ChildProcessError as exc:
        raise _SupervisionFailure("child became non-waitable before final reap") from exc


def _validate_group_identity(pid: int) -> _GroupIdentity:
    caller_pgid = os.getpgrp()
    if pid <= 1 or pid == caller_pgid:
        raise _SupervisionFailure(f"unsafe process-group leader pid: {pid}")
    try:
        observed_pgid = os.getpgid(pid)
    except ProcessLookupError:
        # A very short-lived child can become a zombie before this check on
        # Darwin.  Popen returned only after its start_new_session operation,
        # and the unreaped PID cannot be reused, so pid remains the safe PGID.
        if not _child_exit_is_waitable(pid):
            raise _SupervisionFailure("child disappeared before PGID validation") from None
        observed_pgid = pid
    if observed_pgid != pid:
        raise _SupervisionFailure(
            f"fresh-session PGID mismatch: expected {pid}, observed {observed_pgid}"
        )
    if observed_pgid in {0, 1, caller_pgid}:
        raise _SupervisionFailure(f"refusing unsafe process group: {observed_pgid}")
    return _GroupIdentity(leader_pid=pid, pgid=observed_pgid)


def _live_group_member_pids(identity: _GroupIdentity) -> tuple[int, ...]:
    """Return non-zombie members while leaving the child leader unreaped."""

    try:
        completed = subprocess.run(
            ["ps", "-A", "-o", "pid=", "-o", "pgid=", "-o", "stat="],
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            close_fds=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _SupervisionFailure(f"could not inspect process group: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise _SupervisionFailure(
            f"process-group inspection failed with {completed.returncode}: {detail}"
        )

    members: list[int] = []
    for raw_line in completed.stdout.decode("ascii", errors="replace").splitlines():
        fields = raw_line.split(None, 2)
        if len(fields) != 3:
            continue
        raw_pid, raw_pgid, state = fields
        try:
            member_pid = int(raw_pid)
            member_pgid = int(raw_pgid)
        except ValueError:
            continue
        if member_pgid != identity.pgid or state.upper().startswith("Z"):
            continue
        members.append(member_pid)
    return tuple(sorted(members))


def _send_group_signal(identity: _GroupIdentity, sig: signal.Signals) -> bool:
    if (
        identity.leader_pid <= 1
        or identity.pgid != identity.leader_pid
        or identity.pgid in {0, 1, os.getpgrp()}
    ):
        raise _SupervisionFailure("process-group identity failed pre-signal safety check")
    try:
        os.killpg(identity.pgid, sig)
    except ProcessLookupError:
        return False
    except PermissionError as exc:
        raise _SupervisionFailure(
            f"permission denied signaling process group {identity.pgid}"
        ) from exc
    return True


def _terminate_group(
    identity: _GroupIdentity,
    *,
    grace_seconds: float,
    poll_interval_seconds: float,
) -> tuple[bool, bool, bool]:
    term_sent = _send_group_signal(identity, signal.SIGTERM)
    grace_deadline = time.monotonic() + grace_seconds
    while time.monotonic() < grace_deadline:
        if not _live_group_member_pids(identity):
            return term_sent, False, True
        time.sleep(min(poll_interval_seconds, max(0.0, grace_deadline - time.monotonic())))
    if not _live_group_member_pids(identity):
        return term_sent, False, True
    kill_sent = _send_group_signal(identity, signal.SIGKILL)
    kill_deadline = time.monotonic() + _KILL_WAIT_SECONDS
    while time.monotonic() < kill_deadline:
        if not _live_group_member_pids(identity):
            return term_sent, kill_sent, True
        time.sleep(min(poll_interval_seconds, max(0.0, kill_deadline - time.monotonic())))
    survivors = _live_group_member_pids(identity)
    if survivors:
        raise _SupervisionFailure("process group survived SIGKILL")
    return term_sent, kill_sent, True


def _confirm_group_empty(identity: _GroupIdentity, *, poll_interval_seconds: float) -> bool:
    """Bound the post-KILL observation without sending another signal."""

    deadline = time.monotonic() + _KILL_WAIT_SECONDS
    while time.monotonic() < deadline:
        if not _live_group_member_pids(identity):
            return True
        time.sleep(min(poll_interval_seconds, max(0.0, deadline - time.monotonic())))
    if _live_group_member_pids(identity):
        raise _SupervisionFailure("process group survived fallback SIGKILL")
    return True


def _start_reader(*, stream: BinaryIO, capture: _Capture, name: str) -> threading.Thread:
    thread = threading.Thread(
        target=capture.drain,
        args=(stream,),
        name=name,
        daemon=False,
    )
    thread.start()
    return thread


def _format_exception(
    exception_type: type[BaseException],
    exception: BaseException,
    traceback: TracebackType | None,
) -> str:
    del exception_type, traceback
    return f"{type(exception).__name__}: {exception}"


def run_supervised(
    argv: Sequence[str],
    *,
    policy: SupervisionPolicy,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    pass_fds: tuple[int, ...] = (),
    on_process_started: Callable[[int, int], None] | None = None,
) -> SupervisionResult:
    """Run ``argv`` in a fresh process group and enforce ``policy``.

    Spawn and supervision failures are represented in the returned value; the
    function does not turn them into child exit codes.  Invalid caller input is
    rejected before spawning.
    """

    if not isinstance(policy, SupervisionPolicy):
        raise TypeError("policy must be a SupervisionPolicy")
    if os.name != "posix":
        raise RuntimeError("process-group supervision requires POSIX")
    command = tuple(argv)
    if not command or any(not isinstance(part, str) or not part for part in command):
        raise ValueError("argv must be a non-empty sequence of non-empty strings")
    if not isinstance(pass_fds, tuple):
        raise TypeError("pass_fds must be a tuple")
    if any(isinstance(fd, bool) or not isinstance(fd, int) or fd < 0 for fd in pass_fds):
        raise ValueError("pass_fds must contain only non-negative integers")
    if len(set(pass_fds)) != len(pass_fds):
        raise ValueError("pass_fds must not contain duplicates")
    if on_process_started is not None and not callable(on_process_started):
        raise TypeError("on_process_started must be callable")
    normalized_cwd = None if cwd is None else str(Path(cwd))
    normalized_env = None if env is None else dict(env)

    started_at = time.monotonic()
    deadline = (
        started_at + policy.timeout_seconds
        if policy.absolute_deadline_monotonic is None
        else policy.absolute_deadline_monotonic
    )
    stdout_capture = _Capture(policy.stream_capture_limit_bytes)
    stderr_capture = _Capture(policy.stream_capture_limit_bytes)
    process: subprocess.Popen[bytes] | None = None
    identity: _GroupIdentity | None = None
    stdout_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    child_returncode: int | None = None
    timed_out = False
    term_sent = False
    kill_sent = False
    orphan_detected = False
    group_cleanup_confirmed = False
    direct_child_reaped = False
    supervision_message: str | None = None

    try:
        process = subprocess.Popen(
            command,
            shell=False,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            pass_fds=pass_fds,
            cwd=normalized_cwd,
            env=normalized_env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return SupervisionResult(
            outcome="spawn_error",
            returncode=SUPERVISION_FAILURE_RETURN_CODE,
            child_returncode=None,
            stdout=b"",
            stderr=b"",
            stdout_total_bytes=0,
            stderr_total_bytes=0,
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
            term_sent=False,
            kill_sent=False,
            orphan_descendants_detected=False,
            process_started=False,
            group_cleanup_confirmed=False,
            direct_child_reaped=False,
            duration_seconds=time.monotonic() - started_at,
            pid=None,
            pgid=None,
            error_message=f"{type(exc).__name__}: {exc}",
        )

    try:
        identity = _validate_group_identity(process.pid)
        if process.stdout is None or process.stderr is None:
            raise _SupervisionFailure("Popen did not create both output pipes")
        stdout_thread = _start_reader(
            stream=cast(BinaryIO, process.stdout),
            capture=stdout_capture,
            name=f"supervisor-stdout-{process.pid}",
        )
        stderr_thread = _start_reader(
            stream=cast(BinaryIO, process.stderr),
            capture=stderr_capture,
            name=f"supervisor-stderr-{process.pid}",
        )
        if on_process_started is not None:
            on_process_started(identity.leader_pid, identity.pgid)

        while True:
            child_exit_waitable = _child_exit_is_waitable(process.pid)
            observed_at = time.monotonic()
            remaining = deadline - observed_at
            if remaining <= 0.0:
                # Fail closed when completion was not observed before the hard
                # deadline; a delayed parent cannot prove an earlier child exit.
                timed_out = True
                if child_exit_waitable:
                    late_members = _live_group_member_pids(identity)
                    late_descendants = tuple(
                        pid for pid in late_members if pid != identity.leader_pid
                    )
                    if late_descendants:
                        term_sent, kill_sent, group_cleanup_confirmed = _terminate_group(
                            identity,
                            grace_seconds=policy.terminate_grace_seconds,
                            poll_interval_seconds=policy.poll_interval_seconds,
                        )
                    elif late_members:
                        raise _SupervisionFailure("late waitable leader was still reported as live")
                    else:
                        group_cleanup_confirmed = True
                else:
                    term_sent, kill_sent, group_cleanup_confirmed = _terminate_group(
                        identity,
                        grace_seconds=policy.terminate_grace_seconds,
                        poll_interval_seconds=policy.poll_interval_seconds,
                    )
                break
            if child_exit_waitable:
                break
            time.sleep(min(policy.poll_interval_seconds, remaining))

        if not timed_out:
            live_members = _live_group_member_pids(identity)
            descendants = tuple(pid for pid in live_members if pid != identity.leader_pid)
            if descendants:
                orphan_detected = True
                term_sent, kill_sent, group_cleanup_confirmed = _terminate_group(
                    identity,
                    grace_seconds=policy.terminate_grace_seconds,
                    poll_interval_seconds=policy.poll_interval_seconds,
                )
            elif live_members:
                raise _SupervisionFailure("waitable leader was still reported as live")
            else:
                group_cleanup_confirmed = True
    except BaseException as exc:
        supervision_message = _format_exception(type(exc), exc, exc.__traceback__)
        try:
            if identity is not None:
                sent_kill = _send_group_signal(identity, signal.SIGKILL)
                kill_sent = kill_sent or sent_kill
                group_cleanup_confirmed = _confirm_group_empty(
                    identity,
                    poll_interval_seconds=policy.poll_interval_seconds,
                )
            else:
                # The PID is owned by this Popen object but its group was not
                # verified, so only a direct child signal is safe.
                try:
                    os.kill(process.pid, signal.SIGKILL)
                    kill_sent = True
                except ProcessLookupError:
                    pass
        except BaseException as cleanup_exc:
            supervision_message += f"; cleanup failed: {type(cleanup_exc).__name__}: {cleanup_exc}"
    finally:
        # A timeout from wait() does not reap, so one last verified KILL remains
        # safe.  Once wait() succeeds, no further group signal is sent.
        try:
            child_returncode = process.wait(timeout=_FINAL_WAIT_SECONDS)
            direct_child_reaped = True
        except subprocess.TimeoutExpired:
            group_cleanup_confirmed = False
            if supervision_message is None:
                supervision_message = "direct child did not exit before final wait deadline"
            else:
                supervision_message += "; direct child did not exit before final wait deadline"
            try:
                if identity is not None:
                    sent_kill = _send_group_signal(identity, signal.SIGKILL)
                    kill_sent = kill_sent or sent_kill
                else:
                    os.kill(process.pid, signal.SIGKILL)
                    kill_sent = True
                child_returncode = process.wait(timeout=_FINAL_WAIT_SECONDS)
                direct_child_reaped = True
            except BaseException as exc:
                supervision_message += f"; final kill/reap failed: {type(exc).__name__}: {exc}"
        except BaseException as exc:
            if supervision_message is None:
                supervision_message = f"wait failed: {type(exc).__name__}: {exc}"
            else:
                supervision_message += f"; wait failed: {type(exc).__name__}: {exc}"

        # Once the entire group is gone the readers reach EOF and must finish
        # draining kernel pipe buffers before the parent closes its handles.
        reader_pairs = (
            (stdout_thread, process.stdout),
            (stderr_thread, process.stderr),
        )
        for thread, stream in reader_pairs:
            if thread is None:
                continue
            thread.join(_READER_JOIN_SECONDS)
            if thread.is_alive():
                if supervision_message is None:
                    supervision_message = "output reader did not finish after process cleanup"
                else:
                    supervision_message += "; output reader did not finish after process cleanup"
                if stream is not None:
                    with suppress(OSError):
                        os.close(stream.fileno())
                thread.join(_READER_JOIN_SECONDS)
                if thread.is_alive():
                    if supervision_message is None:
                        supervision_message = "output reader could not be stopped"
                    else:
                        supervision_message += "; output reader could not be stopped"
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                with suppress(OSError):
                    stream.close()

    capture_errors = tuple(
        message
        for message in (stdout_capture.error_message, stderr_capture.error_message)
        if message is not None
    )
    if capture_errors:
        joined_errors = "; ".join(capture_errors)
        if supervision_message is None:
            supervision_message = f"output capture failed: {joined_errors}"
        else:
            supervision_message += f"; output capture failed: {joined_errors}"

    if supervision_message is not None:
        outcome: SupervisionOutcome = "supervision_error"
        public_returncode: int | None = SUPERVISION_FAILURE_RETURN_CODE
    elif timed_out:
        outcome = "timeout"
        public_returncode = TIMEOUT_RETURN_CODE
    elif orphan_detected:
        outcome = "orphan_descendants"
        public_returncode = SUPERVISION_FAILURE_RETURN_CODE
    elif child_returncode == 0:
        outcome = "clean"
        public_returncode = 0
    else:
        outcome = "nonzero"
        public_returncode = child_returncode

    return SupervisionResult(
        outcome=outcome,
        returncode=public_returncode,
        child_returncode=child_returncode,
        stdout=stdout_capture.data,
        stderr=stderr_capture.data,
        stdout_total_bytes=stdout_capture.total_bytes,
        stderr_total_bytes=stderr_capture.total_bytes,
        stdout_truncated=stdout_capture.truncated,
        stderr_truncated=stderr_capture.truncated,
        timed_out=timed_out,
        term_sent=term_sent,
        kill_sent=kill_sent,
        orphan_descendants_detected=orphan_detected,
        process_started=True,
        group_cleanup_confirmed=group_cleanup_confirmed,
        direct_child_reaped=direct_child_reaped,
        duration_seconds=time.monotonic() - started_at,
        pid=process.pid,
        pgid=None if identity is None else identity.pgid,
        error_message=supervision_message,
    )


__all__ = [
    "SUPERVISION_FAILURE_RETURN_CODE",
    "TIMEOUT_RETURN_CODE",
    "SupervisionOutcome",
    "SupervisionPolicy",
    "SupervisionResult",
    "run_supervised",
]
