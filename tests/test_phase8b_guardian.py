from __future__ import annotations

import os
import signal
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from nhc_deprot_ranker.quantum import linux_guardian as guardian
from nhc_deprot_ranker.quantum import worker_bootstrap

_TOKEN = "a" * 64
_CPUS = frozenset({0, 1, 2, 3})


def _identity(
    *,
    pid: int = 5001,
    ppid: int = 4001,
    starttime: int = 123456,
    state: str = "S",
    cpus: frozenset[int] = _CPUS,
) -> guardian.ProcessIdentity:
    return guardian.ProcessIdentity(
        pid=pid,
        ppid=ppid,
        pgid=5001,
        sid=5001,
        starttime_ticks=starttime,
        state=state,
        boot_id="11111111-2222-3333-4444-555555555555",
        cpus_allowed=cpus,
    )


def _write_fake_proc(root: Path, identity: guardian.ProcessIdentity) -> None:
    (root / "sys/kernel/random").mkdir(parents=True)
    (root / "sys/kernel/random/boot_id").write_text(identity.boot_id + "\n", encoding="ascii")
    process_root = root / str(identity.pid)
    process_root.mkdir()
    suffix = [
        identity.state,
        str(identity.ppid),
        str(identity.pgid),
        str(identity.sid),
        *(["0"] * 15),
        str(identity.starttime_ticks),
        "0",
    ]
    (process_root / "stat").write_text(
        f"{identity.pid} (fixture ) name) {' '.join(suffix)}\n",
        encoding="ascii",
    )
    (process_root / "status").write_text("Cpus_allowed_list:\t0-3\n", encoding="ascii")
    task_root = process_root / "task" / str(identity.pid)
    task_root.mkdir(parents=True)
    (task_root / "status").write_text("Cpus_allowed_list:\t0-1,3\n", encoding="ascii")


def test_fake_proc_identity_handles_parentheses_and_starttime(tmp_path: Path) -> None:
    expected = _identity()
    _write_fake_proc(tmp_path, expected)

    observed = guardian.read_process_identity(expected.pid, proc_root=tmp_path)

    assert observed == expected
    assert guardian.read_task_affinities(expected.pid, proc_root=tmp_path) == {
        expected.pid: frozenset({0, 1, 3})
    }
    assert guardian.list_process_group_members(expected, proc_root=tmp_path) == (expected,)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0-3", frozenset({0, 1, 2, 3})),
        ("0-1,3,8-9", frozenset({0, 1, 3, 8, 9})),
    ],
)
def test_cpu_list_parser(raw: str, expected: frozenset[int]) -> None:
    assert guardian.parse_cpu_list(raw) == expected


@pytest.mark.parametrize("raw", ["", "x", "3-1", "-1", "1-"])
def test_cpu_list_parser_fails_closed(raw: str) -> None:
    with pytest.raises(guardian.ProcessIdentityError):
        guardian.parse_cpu_list(raw)


def test_parent_death_signal_is_installed_before_parent_recheck() -> None:
    events: list[tuple[object, ...]] = []

    def fake_prctl(option: int, arg2: int, arg3: int, arg4: int, arg5: int) -> int:
        events.append(("prctl", option, arg2, arg3, arg4, arg5))
        return 0

    def fake_getppid() -> int:
        events.append(("getppid",))
        return 42

    guardian.install_parent_death_signal(42, prctl=fake_prctl, getppid=fake_getppid)

    assert events[0][:3] == ("prctl", 1, signal.SIGKILL)
    assert events[1] == ("getppid",)


def test_parent_change_after_prctl_fails_before_release() -> None:
    with pytest.raises(guardian.StartupHandshakeError, match="parent changed"):
        guardian.install_parent_death_signal(
            42,
            prctl=lambda *_args: 0,
            getppid=lambda: 1,
        )


def test_bootstrap_target_cannot_run_before_exact_pipe_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_fd, write_fd = os.pipe()
    target_started = threading.Event()
    result: list[int] = []
    claim_path = Path("/tmp/phase8b-test-compute-claim.json")
    claim_evidence = SimpleNamespace(
        compute_claim_sha256="c" * 64,
        claim=SimpleNamespace(paths=SimpleNamespace(compute_claim=claim_path)),
    )
    monkeypatch.setattr(
        worker_bootstrap,
        "load_and_validate_compute_claim_for_worker",
        lambda *args, **kwargs: claim_evidence,
    )

    def target(arguments: Sequence[str], *, bootstrap_proof: object) -> int:
        assert bootstrap_proof is not None
        assert tuple(arguments) == ("--synthetic",)
        target_started.set()
        return 17

    thread = threading.Thread(
        target=lambda: result.append(
            worker_bootstrap.bootstrap_worker(
                start_fd=read_fd,
                release_token=_TOKEN,
                expected_parent_pid=42,
                absolute_deadline_ns=time.monotonic_ns() + 2_000_000_000,
                allowed_cpus=_CPUS,
                compute_claim_path=claim_path,
                worker_args=("--synthetic",),
                target=target,
                install_pdeath=lambda parent: None,
                affinity_reader=lambda pid: _CPUS,
            )
        )
    )
    thread.start()
    assert not target_started.wait(0.05)

    guardian.send_start_release(write_fd, token=_TOKEN)
    thread.join(2.0)

    assert not thread.is_alive()
    assert target_started.is_set()
    assert result == [17]


def test_pipe_eof_before_release_never_runs_target() -> None:
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    called = False

    def forbidden_target(arguments: Sequence[str], *, bootstrap_proof: object) -> int:
        del arguments, bootstrap_proof
        nonlocal called
        called = True
        return 0

    with pytest.raises(guardian.StartupHandshakeError, match="closed"):
        worker_bootstrap.bootstrap_worker(
            start_fd=read_fd,
            release_token=_TOKEN,
            expected_parent_pid=42,
            absolute_deadline_ns=time.monotonic_ns() + 1_000_000_000,
            allowed_cpus=_CPUS,
            compute_claim_path=Path("/tmp/unreachable-compute-claim.json"),
            worker_args=(),
            target=forbidden_target,
            install_pdeath=lambda parent: None,
            affinity_reader=lambda pid: _CPUS,
        )
    assert called is False


def test_wrong_release_token_never_runs_target() -> None:
    read_fd, write_fd = os.pipe()
    guardian.send_start_release(write_fd, token="b" * 64)
    with pytest.raises(guardian.StartupHandshakeError, match="invalid"):
        worker_bootstrap.bootstrap_worker(
            start_fd=read_fd,
            release_token=_TOKEN,
            expected_parent_pid=42,
            absolute_deadline_ns=time.monotonic_ns() + 1_000_000_000,
            allowed_cpus=_CPUS,
            compute_claim_path=Path("/tmp/unreachable-compute-claim.json"),
            worker_args=(),
            target=lambda arguments, *, bootstrap_proof: pytest.fail(
                f"unexpected target: {arguments}, {bootstrap_proof}"
            ),
            install_pdeath=lambda parent: None,
            affinity_reader=lambda pid: _CPUS,
        )


def test_expired_absolute_release_deadline_closes_fd_without_reading() -> None:
    closed: list[int] = []
    with pytest.raises(guardian.StartupHandshakeError, match="deadline"):
        guardian.await_start_release(
            91,
            expected_token=_TOKEN,
            absolute_deadline_ns=100,
            clock_ns=lambda: 100,
            wait_readable=lambda fd, timeout: pytest.fail("expired deadline must not wait"),
            read_bytes=lambda fd, size: pytest.fail("expired deadline must not read"),
            close_fd=closed.append,
        )
    assert closed == [91]


def test_affinity_is_checked_before_pipe_read() -> None:
    read_fd, write_fd = os.pipe()
    try:
        with pytest.raises(guardian.AffinityViolationError):
            worker_bootstrap.bootstrap_worker(
                start_fd=read_fd,
                release_token=_TOKEN,
                expected_parent_pid=42,
                absolute_deadline_ns=time.monotonic_ns() + 1_000_000_000,
                allowed_cpus=_CPUS,
                compute_claim_path=Path("/tmp/unreachable-compute-claim.json"),
                worker_args=(),
                target=lambda arguments, *, bootstrap_proof: 0,
                install_pdeath=lambda parent: None,
                affinity_reader=lambda pid: frozenset({0, 4}),
            )
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_bootstrap_permanently_rejects_sequential_reuse_of_same_compute_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_path = Path("/tmp/phase8b-test-sequential-compute-claim.json")
    claim_evidence = SimpleNamespace(
        compute_claim_sha256="d" * 64,
        claim=SimpleNamespace(paths=SimpleNamespace(compute_claim=claim_path)),
    )
    monkeypatch.setattr(
        worker_bootstrap,
        "load_and_validate_compute_claim_for_worker",
        lambda *args, **kwargs: claim_evidence,
    )

    def invoke() -> int:
        read_fd, write_fd = os.pipe()
        guardian.send_start_release(write_fd, token=_TOKEN)
        return worker_bootstrap.bootstrap_worker(
            start_fd=read_fd,
            release_token=_TOKEN,
            expected_parent_pid=42,
            absolute_deadline_ns=time.monotonic_ns() + 1_000_000_000,
            allowed_cpus=_CPUS,
            compute_claim_path=claim_path,
            worker_args=(),
            target=lambda arguments, *, bootstrap_proof: 19,
            install_pdeath=lambda parent: None,
            affinity_reader=lambda pid: _CPUS,
        )

    assert invoke() == 19
    with pytest.raises(RuntimeError, match="already claimed"):
        invoke()


def test_bootstrap_lock_allows_only_one_concurrent_claimant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_path = Path("/tmp/phase8b-test-concurrent-compute-claim.json")
    claim_evidence = SimpleNamespace(
        compute_claim_sha256="e" * 64,
        claim=SimpleNamespace(paths=SimpleNamespace(compute_claim=claim_path)),
    )
    monkeypatch.setattr(
        worker_bootstrap,
        "load_and_validate_compute_claim_for_worker",
        lambda *args, **kwargs: claim_evidence,
    )
    target_calls: list[int] = []
    results: list[int] = []
    errors: list[BaseException] = []
    start = threading.Barrier(3)

    def target(arguments: Sequence[str], *, bootstrap_proof: object) -> int:
        del arguments, bootstrap_proof
        target_calls.append(1)
        return 23

    def invoke() -> None:
        read_fd, write_fd = os.pipe()
        guardian.send_start_release(write_fd, token=_TOKEN)
        start.wait()
        try:
            result = worker_bootstrap.bootstrap_worker(
                start_fd=read_fd,
                release_token=_TOKEN,
                expected_parent_pid=42,
                absolute_deadline_ns=time.monotonic_ns() + 1_000_000_000,
                allowed_cpus=_CPUS,
                compute_claim_path=claim_path,
                worker_args=(),
                target=target,
                install_pdeath=lambda parent: None,
                affinity_reader=lambda pid: _CPUS,
            )
            results.append(result)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=invoke) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(2.0)

    assert all(not thread.is_alive() for thread in threads)
    assert results == [23]
    assert target_calls == [1]
    assert len(errors) == 1
    assert "already claimed" in str(errors[0])


@dataclass
class _FakeClock:
    now_ns: int = 0

    def __call__(self) -> int:
        return self.now_ns

    def sleep(self, seconds: float) -> None:
        self.now_ns += max(1, int(seconds * 1_000_000_000))


def test_absolute_deadline_terms_then_kills_exact_group() -> None:
    clock = _FakeClock()
    leader = _identity()
    signals: list[tuple[int, int]] = []
    alive = True

    def send(pgid: int, signal_number: int) -> None:
        nonlocal alive
        signals.append((pgid, signal_number))
        if signal_number == signal.SIGKILL:
            alive = False

    result = guardian.guard_process_group(
        leader,
        policy=guardian.GuardianPolicy(
            absolute_deadline_ns=10,
            allowed_cpus=_CPUS,
            terminate_grace_ns=20,
            kill_wait_ns=20,
            poll_interval_ns=5,
        ),
        read_identity=lambda pid: leader,
        list_members=lambda identity: (leader,) if alive else (),
        task_affinities=lambda pid: {pid: _CPUS},
        send_group_signal=send,
        clock_ns=clock,
        sleep=clock.sleep,
    )

    assert result.outcome == "deadline"
    assert result.group_cleanup_confirmed
    assert signals == [(leader.pgid, signal.SIGTERM), (leader.pgid, signal.SIGKILL)]


def test_affinity_expansion_triggers_immediate_cleanup() -> None:
    clock = _FakeClock()
    leader = _identity(cpus=frozenset({0, 4}))
    alive = True
    signals: list[int] = []

    def send(pgid: int, signal_number: int) -> None:
        del pgid
        nonlocal alive
        signals.append(signal_number)
        alive = False

    result = guardian.guard_process_group(
        leader,
        policy=guardian.GuardianPolicy(
            absolute_deadline_ns=1_000,
            allowed_cpus=_CPUS,
            terminate_grace_ns=10,
            poll_interval_ns=5,
        ),
        read_identity=lambda pid: leader,
        list_members=lambda identity: (leader,) if alive else (),
        task_affinities=lambda pid: {pid: leader.cpus_allowed},
        send_group_signal=send,
        clock_ns=clock,
        sleep=clock.sleep,
    )

    assert result.outcome == "affinity_violation"
    assert result.term_sent
    assert not result.kill_sent
    assert result.group_cleanup_confirmed
    assert signals == [signal.SIGTERM]


def test_thread_affinity_expansion_also_triggers_cleanup() -> None:
    clock = _FakeClock()
    leader = _identity()
    alive = True

    def send(pgid: int, signal_number: int) -> None:
        del pgid, signal_number
        nonlocal alive
        alive = False

    result = guardian.guard_process_group(
        leader,
        policy=guardian.GuardianPolicy(
            absolute_deadline_ns=1_000,
            allowed_cpus=_CPUS,
            poll_interval_ns=5,
        ),
        read_identity=lambda pid: leader,
        list_members=lambda identity: (leader,) if alive else (),
        task_affinities=lambda pid: {pid: frozenset({0, 4})},
        send_group_signal=send,
        clock_ns=clock,
        sleep=clock.sleep,
    )

    assert result.outcome == "affinity_violation"
    assert result.group_cleanup_confirmed


def test_starttime_mismatch_never_signals_reused_pid() -> None:
    clock = _FakeClock(now_ns=10)
    registered = _identity()
    reused = _identity(starttime=registered.starttime_ticks + 1)
    signal_calls: list[tuple[int, int]] = []

    result = guardian.guard_process_group(
        registered,
        policy=guardian.GuardianPolicy(
            absolute_deadline_ns=10,
            allowed_cpus=_CPUS,
            poll_interval_ns=5,
        ),
        read_identity=lambda pid: reused,
        list_members=lambda identity: (registered,),
        task_affinities=lambda pid: {pid: _CPUS},
        send_group_signal=lambda pgid, sig: signal_calls.append((pgid, sig)),
        clock_ns=clock,
        sleep=clock.sleep,
    )

    assert result.outcome == "identity_mismatch"
    assert result.group_cleanup_confirmed is False
    assert signal_calls == []


def test_guardian_refuses_its_own_process_group_before_signal() -> None:
    caller_group = os.getpgrp()
    unsafe = guardian.ProcessIdentity(
        pid=caller_group,
        ppid=os.getppid(),
        pgid=caller_group,
        sid=caller_group,
        starttime_ticks=1,
        state="S",
        boot_id="11111111-2222-3333-4444-555555555555",
        cpus_allowed=_CPUS,
    )
    with pytest.raises(guardian.ProcessIdentityError, match="unsafe"):
        guardian.guard_process_group(
            unsafe,
            policy=guardian.GuardianPolicy(
                absolute_deadline_ns=1,
                allowed_cpus=_CPUS,
            ),
            send_group_signal=lambda pgid, sig: pytest.fail("must not signal"),
        )


def test_abort_request_cleans_before_deadline() -> None:
    clock = _FakeClock()
    leader = _identity()
    alive = True

    def send(pgid: int, signal_number: int) -> None:
        del pgid, signal_number
        nonlocal alive
        alive = False

    result = guardian.guard_process_group(
        leader,
        policy=guardian.GuardianPolicy(
            absolute_deadline_ns=10_000,
            allowed_cpus=_CPUS,
            poll_interval_ns=5,
        ),
        read_identity=lambda pid: leader,
        list_members=lambda identity: (leader,) if alive else (),
        task_affinities=lambda pid: {pid: _CPUS},
        send_group_signal=send,
        abort_requested=lambda: True,
        clock_ns=clock,
        sleep=clock.sleep,
    )

    assert result.outcome == "abort"
    assert result.duration_ns < 10_000
    assert result.group_cleanup_confirmed


def test_group_disappearance_observed_at_deadline_is_not_accepted_as_clean() -> None:
    clock = _FakeClock(now_ns=10)
    leader = _identity()

    result = guardian.guard_process_group(
        leader,
        policy=guardian.GuardianPolicy(
            absolute_deadline_ns=10,
            allowed_cpus=_CPUS,
            poll_interval_ns=5,
        ),
        read_identity=lambda pid: leader,
        list_members=lambda identity: (),
        task_affinities=lambda pid: {pid: _CPUS},
        send_group_signal=lambda pgid, sig: pytest.fail("empty group must not be signaled"),
        clock_ns=clock,
        sleep=clock.sleep,
    )

    assert result.outcome == "deadline"
    assert result.trigger == "deadline"
    assert result.group_cleanup_confirmed
    assert not result.term_sent
    assert not result.kill_sent


def test_subreaper_setter_is_verified_without_linux_dependency() -> None:
    events: list[str] = []
    guardian.enable_child_subreaper(
        setter=lambda: events.append("set"),
        getter=lambda: events.append("get") or True,
    )
    assert events == ["set", "get"]
