from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from nhc_deprot_ranker.quantum import process_supervisor as supervisor
from nhc_deprot_ranker.quantum.process_supervisor import (
    TIMEOUT_RETURN_CODE,
    SupervisionPolicy,
    run_supervised,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "process_tree_fixture.py"


def _command(mode: str, *extra: str) -> list[str]:
    return [sys.executable, str(_FIXTURE), mode, *extra]


def _policy(
    *,
    timeout: float = 2.0,
    grace: float = 0.1,
    capture_limit: int = 64 * 1024,
) -> SupervisionPolicy:
    return SupervisionPolicy(
        timeout_seconds=timeout,
        terminate_grace_seconds=grace,
        stream_capture_limit_bytes=capture_limit,
        poll_interval_seconds=0.005,
    )


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _assert_pid_gone(pid: int) -> None:
    deadline = time.monotonic() + 2.0
    while _pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not _pid_exists(pid), f"process {pid} survived supervisor cleanup"


def test_clean_success() -> None:
    result = run_supervised(_command("success"), policy=_policy())

    assert result.outcome == "clean"
    assert result.succeeded is True
    assert result.returncode == 0
    assert result.child_returncode == 0
    assert result.pgid == result.pid
    assert result.error_message is None
    assert result.process_started
    assert result.group_cleanup_confirmed
    assert result.direct_child_reaped
    assert result.safe_to_finalize


def test_nonzero_exit_is_distinct() -> None:
    result = run_supervised(_command("nonzero", "--code", "23"), policy=_policy())

    assert result.outcome == "nonzero"
    assert result.returncode == 23
    assert result.child_returncode == 23
    assert not result.timed_out


def test_stdout_and_stderr_are_drained_independently() -> None:
    result = run_supervised(_command("streams"), policy=_policy())

    assert result.outcome == "clean"
    assert result.stdout == b"stdout-message\n"
    assert result.stderr == b"stderr-message\n"
    assert result.stdout_total_bytes == len(result.stdout)
    assert result.stderr_total_bytes == len(result.stderr)
    assert not result.stdout_truncated
    assert not result.stderr_truncated


def test_output_flood_is_fully_drained_but_bounded_in_memory() -> None:
    byte_count = 512 * 1024
    capture_limit = 4096
    result = run_supervised(
        _command("flood", "--bytes", str(byte_count)),
        policy=_policy(capture_limit=capture_limit),
    )

    assert result.outcome == "clean"
    assert result.stdout_total_bytes == byte_count
    assert result.stderr_total_bytes == byte_count
    assert len(result.stdout) == capture_limit
    assert len(result.stderr) == capture_limit
    assert result.stdout_truncated
    assert result.stderr_truncated


def test_sleep_crossing_deadline_returns_124_and_reaps_child(tmp_path: Path) -> None:
    pid_file = tmp_path / "leader.pid"
    result = run_supervised(
        _command("sleep", "--seconds", "30", "--pid-file", str(pid_file)),
        policy=_policy(timeout=0.2),
    )

    assert result.outcome == "timeout"
    assert result.returncode == TIMEOUT_RETURN_CODE
    assert result.child_returncode is not None
    assert result.timed_out
    assert result.term_sent
    assert result.duration_seconds < 2.0
    assert result.group_cleanup_confirmed
    assert result.direct_child_reaped
    _assert_pid_gone(int(pid_file.read_text(encoding="ascii")))


def test_sigterm_ignoring_child_is_escalated_to_sigkill(tmp_path: Path) -> None:
    pid_file = tmp_path / "leader.pid"
    result = run_supervised(
        _command("ignore-term", "--seconds", "30", "--pid-file", str(pid_file)),
        policy=_policy(timeout=0.2, grace=0.1),
    )

    assert result.outcome == "timeout"
    assert result.returncode == TIMEOUT_RETURN_CODE
    assert result.term_sent
    assert result.kill_sent
    _assert_pid_gone(int(pid_file.read_text(encoding="ascii")))


def test_timeout_kills_leader_and_grandchild_process_group(tmp_path: Path) -> None:
    leader_pid_file = tmp_path / "leader.pid"
    child_pid_file = tmp_path / "child.pid"
    result = run_supervised(
        _command(
            "grandchild",
            "--seconds",
            "30",
            "--pid-file",
            str(leader_pid_file),
            "--child-pid-file",
            str(child_pid_file),
        ),
        policy=_policy(timeout=0.3, grace=0.1),
    )

    assert result.outcome == "timeout"
    assert result.kill_sent
    _assert_pid_gone(int(leader_pid_file.read_text(encoding="ascii")))
    _assert_pid_gone(int(child_pid_file.read_text(encoding="ascii")))


def test_natural_parent_exit_detects_and_cleans_surviving_child(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    result = run_supervised(
        _command(
            "parent-exits-child",
            "--seconds",
            "30",
            "--child-pid-file",
            str(child_pid_file),
        ),
        policy=_policy(),
    )

    assert result.outcome == "orphan_descendants"
    assert result.returncode == 1
    assert result.orphan_descendants_detected
    assert result.term_sent
    _assert_pid_gone(int(child_pid_file.read_text(encoding="ascii")))


def test_spawn_failure_returns_typed_result() -> None:
    result = run_supervised(
        ["/definitely/not/a/phase8a/executable"],
        policy=_policy(),
    )

    assert result.outcome == "spawn_error"
    assert result.returncode == 1
    assert result.child_returncode is None
    assert result.pid is None
    assert result.pgid is None
    assert result.error_message is not None
    assert not result.process_started
    assert result.safe_to_finalize


def test_group_inspection_failure_still_kills_and_reaps_without_safe_cleanup_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "leader.pid"

    def failed_inspection(identity: object) -> tuple[int, ...]:
        del identity
        raise RuntimeError("synthetic group inspection failure")

    monkeypatch.setattr(supervisor, "_live_group_member_pids", failed_inspection)
    result = run_supervised(
        _command("ignore-term", "--seconds", "30", "--pid-file", str(pid_file)),
        policy=_policy(timeout=0.05, grace=0.01),
    )

    assert result.outcome == "supervision_error"
    assert result.returncode == 1
    assert result.kill_sent
    assert result.direct_child_reaped
    assert not result.group_cleanup_confirmed
    assert not result.safe_to_finalize
    assert result.duration_seconds < 2.0
    _assert_pid_gone(int(pid_file.read_text(encoding="ascii")))


def test_delayed_completion_observation_is_fail_closed_as_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_observer = supervisor._child_exit_is_waitable
    first = True

    def delayed_observer(pid: int) -> bool:
        nonlocal first
        if first:
            first = False
            time.sleep(0.08)
        return real_observer(pid)

    monkeypatch.setattr(supervisor, "_child_exit_is_waitable", delayed_observer)
    result = run_supervised(
        _command("sleep", "--seconds", "0.05"),
        policy=_policy(timeout=0.02, grace=0.01),
    )

    assert result.outcome == "timeout"
    assert result.returncode == TIMEOUT_RETURN_CODE
    assert result.timed_out
    assert result.group_cleanup_confirmed
    assert result.direct_child_reaped


def test_malformed_argv_and_policy_are_rejected_before_spawn() -> None:
    for argv in ([], [""], [sys.executable, ""]):
        with pytest.raises(ValueError, match="argv"):
            run_supervised(argv, policy=_policy())
    invalid_policies = (
        {"timeout_seconds": 0.0},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": 1.0, "terminate_grace_seconds": -1.0},
        {"timeout_seconds": 1.0, "stream_capture_limit_bytes": -1},
        {"timeout_seconds": 1.0, "poll_interval_seconds": 0.0},
    )
    for kwargs in invalid_policies:
        with pytest.raises(ValueError):
            SupervisionPolicy(**kwargs)


@pytest.mark.parametrize("iteration", range(12))
def test_deadline_race_repeats_without_supervision_error_or_orphan(iteration: int) -> None:
    del iteration
    result = run_supervised(
        _command("sleep", "--seconds", "0.04"),
        policy=_policy(timeout=0.04, grace=0.05),
    )

    assert result.outcome in {"clean", "timeout"}
    assert result.outcome != "supervision_error"
    assert not result.orphan_descendants_detected
    if result.pid is not None:
        _assert_pid_gone(result.pid)


def test_repeated_fast_exits_leave_no_reported_pid_alive() -> None:
    pids: list[int] = []
    for _ in range(20):
        result = run_supervised(_command("success"), policy=_policy())
        assert result.outcome == "clean"
        assert result.pid is not None
        pids.append(result.pid)

    for pid in pids:
        _assert_pid_gone(pid)
