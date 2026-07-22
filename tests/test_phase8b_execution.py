from __future__ import annotations

import ast
import os
import signal
import stat
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from nhc_deprot_ranker.quantum import phase8b_execution as execution
from nhc_deprot_ranker.quantum.linux_guardian import GuardianResult, ProcessIdentity

_TOKEN = "a" * 64
_PERMIT_SHA256 = "b" * 64
_CPUS = frozenset({0, 1, 2, 3})
_TRANSACTION_ID = execution.FROZEN_TRANSACTION_ID
_BOOT_ID = "11111111-2222-3333-4444-555555555555"


def _identity(
    pid: int,
    *,
    ppid: int,
    starttime_ticks: int | None = None,
    cpus: frozenset[int] = _CPUS,
    state: str = "S",
) -> ProcessIdentity:
    return ProcessIdentity(
        pid=pid,
        ppid=ppid,
        pgid=pid,
        sid=pid,
        starttime_ticks=pid * 100 if starttime_ticks is None else starttime_ticks,
        state=state,
        boot_id=_BOOT_ID,
        cpus_allowed=cpus,
    )


def _hierarchy(*, guardian_pid: int = 101) -> tuple[ProcessIdentity, ...]:
    guardian = _identity(guardian_pid, ppid=2)
    supervisor = _identity(202, ppid=guardian.pid)
    worker = _identity(303, ppid=supervisor.pid)
    return guardian, supervisor, worker


def _paths(tmp_path: Path) -> execution.TransactionPaths:
    private = tmp_path / "run/private"
    private.mkdir(parents=True, mode=0o700)
    private.chmod(0o700)
    return execution.TransactionPaths(
        registration=private / "worker_registration.json",
        acknowledgement=private / "guardian_acknowledgement.json",
        compute_claim=private / "compute_claim.json",
        receipt=private / "guardian_receipt.json",
    )


def _claim_authority(paths: execution.TransactionPaths) -> execution.ComputeClaimAuthority:
    run_root = paths.private_directory.parent
    project_root = run_root.parent
    return execution.ComputeClaimAuthority(
        transport_inventory_sha256="1" * 64,
        payload_manifest_sha256="2" * 64,
        permit_sha256=_PERMIT_SHA256,
        request_sha256="3" * 64,
        runner_source_sha256="4" * 64,
        protocol_sha256="5" * 64,
        resources_sha256="6" * 64,
        cation_xyz_sha256="7" * 64,
        neutral_xyz_sha256="8" * 64,
        endpoint_atom_map_sha256="9" * 64,
        legacy_atom_map_sha256="c" * 64,
        geometry_validation_sha256="d" * 64,
        electron_count=execution.FROZEN_ELECTRON_COUNT,
        request_id=execution.FROZEN_REQUEST_ID,
        inchikey=execution.FROZEN_INCHIKEY,
        attempt_id=_TRANSACTION_ID,
        project_root=project_root,
        run_root=run_root,
        request_path=run_root / "input/request.json",
        output_root=run_root / "runtime/output",
    )


def _worker_scratch(paths: execution.TransactionPaths, *, suffix: str = "fixture") -> Path:
    scratch = paths.private_directory.parent / "runtime" / f".worker-{_TRANSACTION_ID}-{suffix}"
    scratch.mkdir(parents=True, mode=0o700)
    scratch.chmod(0o700)
    return scratch


def _publish_claim(
    paths: execution.TransactionPaths,
    *,
    created_ns: int = 120,
    scratch: Path | None = None,
) -> execution.ComputeClaimEvidence:
    registration = execution.read_registration(paths.registration)
    acknowledgement = execution.read_acknowledgement(paths.acknowledgement)
    claim = execution.make_compute_claim(
        authority=_claim_authority(paths),
        paths=paths,
        worker_scratch_path=_worker_scratch(paths) if scratch is None else scratch,
        registration=registration,
        acknowledgement=acknowledgement,
        clock_ns=lambda: created_ns,
    )
    execution.write_compute_claim(paths.compute_claim, claim)
    return execution.read_compute_claim(paths.compute_claim)


def _registration(
    hierarchy: tuple[ProcessIdentity, ...], *, created_ns: int = 10
) -> execution.WorkerRegistration:
    guardian, supervisor, worker = hierarchy
    return execution.make_registration(
        transaction_id=_TRANSACTION_ID,
        absolute_deadline_ns=1_000,
        allowed_cpus=_CPUS,
        release_token=_TOKEN,
        guardian=guardian,
        supervisor=supervisor,
        worker=worker,
        clock_ns=lambda: created_ns,
    )


def _task_affinities(pid: int) -> dict[int, frozenset[int]]:
    return {pid: _CPUS}


def _clean_guardian_result() -> GuardianResult:
    return GuardianResult(
        outcome="clean",
        trigger=None,
        term_sent=False,
        kill_sent=False,
        group_cleanup_confirmed=True,
        duration_ns=7,
        error_message=None,
    )


def _forbidden_final_acceptance(
    context: execution.FinalAcceptanceContext,
) -> execution.PublishedFinalAcceptance:
    pytest.fail(f"final acceptance must be unreachable: {context.transaction_id}")


def test_execution_module_import_closure_is_chemistry_free() -> None:
    source_path = Path(execution.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    local_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("nhc_deprot_ranker")
    }
    assert local_imports == {"nhc_deprot_ranker.quantum.linux_guardian"}
    source = source_path.read_text(encoding="utf-8").lower()
    assert "import pyscf" not in source
    assert "import geometric" not in source


def test_registration_ack_and_claim_are_canonical_exclusive_private_records(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    registration = _registration(_hierarchy())

    registration_hash = execution.write_registration(paths.registration, registration)
    acknowledgement = execution.make_acknowledgement(registration, clock_ns=lambda: 20)
    execution.write_acknowledgement(paths.acknowledgement, acknowledgement)
    claim = execution.make_compute_claim(
        authority=_claim_authority(paths),
        paths=paths,
        worker_scratch_path=_worker_scratch(paths),
        registration=registration,
        acknowledgement=acknowledgement,
        clock_ns=lambda: 30,
    )
    claim_hash = execution.write_compute_claim(paths.compute_claim, claim)

    assert execution.read_registration(paths.registration) == registration
    assert execution.read_acknowledgement(paths.acknowledgement) == acknowledgement
    assert execution.read_compute_claim(paths.compute_claim) == execution.ComputeClaimEvidence(
        claim,
        claim_hash,
    )
    assert registration_hash == execution.registration_sha256(registration)
    assert stat.S_IMODE(paths.registration.stat().st_mode) == 0o600
    assert stat.S_IMODE(paths.acknowledgement.stat().st_mode) == 0o600
    assert stat.S_IMODE(paths.compute_claim.stat().st_mode) == 0o600
    with pytest.raises(execution.ExecutionRecordError, match="already exists"):
        execution.write_registration(paths.registration, registration)
    with pytest.raises(execution.ExecutionRecordError, match="already exists"):
        execution.write_compute_claim(paths.compute_claim, claim)


def test_noncanonical_or_extended_registration_is_rejected() -> None:
    raw = execution.registration_bytes(_registration(_hierarchy()))
    with pytest.raises(execution.ExecutionRecordError, match="canonical"):
        execution.parse_registration(raw.replace(b"  ", b" ", 1))
    with pytest.raises(execution.ExecutionRecordError, match="fields drifted"):
        execution.parse_registration(raw.replace(b'"worker":', b'"extension": 1, "worker":'))


def test_registration_rejects_parent_boot_and_session_drift() -> None:
    guardian, supervisor, worker = _hierarchy()
    with pytest.raises(execution.ExecutionIdentityError, match="parent"):
        _registration((guardian, replace(supervisor, ppid=999), worker))
    with pytest.raises(execution.ExecutionIdentityError, match="boot"):
        _registration((guardian, supervisor, replace(worker, boot_id="other-boot")))
    with pytest.raises(execution.ExecutionIdentityError, match="session"):
        _registration((guardian, supervisor, replace(worker, sid=supervisor.sid)))


def test_live_validation_binds_starttime_and_exact_task_affinity() -> None:
    hierarchy = _hierarchy()
    guardian, supervisor, worker = hierarchy
    registration = _registration(hierarchy)

    with pytest.raises(execution.ExecutionIdentityError, match="PID/starttime"):
        execution.validate_registration_observation(
            registration,
            expected_transaction_id=registration.transaction_id,
            expected_absolute_deadline_ns=registration.absolute_deadline_ns,
            expected_allowed_cpus=_CPUS,
            expected_release_token_sha256=registration.release_token_sha256,
            observed_guardian=guardian,
            observed_supervisor=supervisor,
            observed_worker=replace(worker, starttime_ticks=worker.starttime_ticks + 1),
            guardian_task_affinities=_task_affinities(guardian.pid),
            supervisor_task_affinities=_task_affinities(supervisor.pid),
            worker_task_affinities=_task_affinities(worker.pid),
        )

    with pytest.raises(execution.ExecutionIdentityError, match="task affinity"):
        execution.validate_registration_observation(
            registration,
            expected_transaction_id=registration.transaction_id,
            expected_absolute_deadline_ns=registration.absolute_deadline_ns,
            expected_allowed_cpus=_CPUS,
            expected_release_token_sha256=registration.release_token_sha256,
            observed_guardian=guardian,
            observed_supervisor=supervisor,
            observed_worker=worker,
            guardian_task_affinities=_task_affinities(guardian.pid),
            supervisor_task_affinities=_task_affinities(supervisor.pid),
            worker_task_affinities={worker.pid: frozenset({0, 1})},
        )


def test_private_directory_mode_and_stale_records_fail_before_use(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.private_directory.chmod(0o750)
    with pytest.raises(execution.ExecutionRecordError, match="mode drifted"):
        execution.require_fresh_transaction_paths(paths)

    paths.private_directory.chmod(0o700)
    paths.registration.symlink_to(paths.private_directory / "missing")
    with pytest.raises(execution.ExecutionRecordError, match="stale"):
        execution.require_fresh_transaction_paths(paths)

    real_private = tmp_path / "real-private"
    real_private.mkdir(mode=0o700)
    linked_private = tmp_path / "linked-private"
    linked_private.symlink_to(real_private, target_is_directory=True)
    linked_paths = execution.TransactionPaths(
        (linked_private / "registration.json").absolute(),
        (linked_private / "ack.json").absolute(),
        (linked_private / "claim.json").absolute(),
        (linked_private / "receipt.json").absolute(),
    )
    with pytest.raises(execution.ExecutionRecordError, match="traverses a symlink"):
        execution.require_fresh_transaction_paths(linked_paths)


def test_supervisor_releases_only_after_durable_exact_ack(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    guardian = _identity(101, ppid=2)
    supervisor = _identity(os.getpid(), ppid=guardian.pid)
    worker = _identity(303, ppid=supervisor.pid)
    identities = {item.pid: item for item in (guardian, supervisor, worker)}
    read_fd, write_fd = os.pipe()
    events: list[str] = []
    now_ns = 10
    scratch = _worker_scratch(paths)

    def publish_ack(_seconds: float) -> None:
        nonlocal now_ns
        events.append("ack")
        registration = execution.read_registration(paths.registration)
        acknowledgement = execution.make_acknowledgement(registration, clock_ns=lambda: 30)
        execution.write_acknowledgement(paths.acknowledgement, acknowledgement)
        now_ns = 40

    registration = execution.supervisor_register_and_release(
        paths=paths,
        transaction_id=_TRANSACTION_ID,
        absolute_deadline_ns=1_000,
        allowed_cpus=_CPUS,
        release_token=_TOKEN,
        guardian=guardian,
        worker_pid=worker.pid,
        worker_scratch_path=scratch,
        claim_authority=_claim_authority(paths),
        release_write_fd=write_fd,
        identity_reader=lambda pid: identities[pid],
        task_affinity_reader=_task_affinities,
        clock_ns=lambda: now_ns,
        sleep=publish_ack,
        poll_interval_ns=1,
        send_release=lambda fd, *, token: (
            events.append("release"),
            execution.send_start_release(fd, token=token),
        )[-1],
    )

    assert registration.worker == worker
    assert events == ["ack", "release"]
    assert execution.read_compute_claim(paths.compute_claim).claim.worker_scratch_path == scratch
    assert os.read(read_fd, 4096) == execution.start_release_frame(_TOKEN)
    os.close(read_fd)


def test_wrong_ack_never_releases_worker_and_pipe_closes(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    guardian = _identity(101, ppid=2)
    supervisor = _identity(os.getpid(), ppid=guardian.pid)
    worker = _identity(303, ppid=supervisor.pid)
    identities = {item.pid: item for item in (guardian, supervisor, worker)}
    read_fd, write_fd = os.pipe()
    scratch = _worker_scratch(paths)

    def publish_wrong_ack(_seconds: float) -> None:
        registration = execution.read_registration(paths.registration)
        acknowledgement = execution.make_acknowledgement(registration, clock_ns=lambda: 30)
        execution.write_acknowledgement(
            paths.acknowledgement,
            replace(acknowledgement, registration_sha256="f" * 64),
        )

    with pytest.raises(execution.ExecutionIdentityError, match="binding drifted"):
        execution.supervisor_register_and_release(
            paths=paths,
            transaction_id=_TRANSACTION_ID,
            absolute_deadline_ns=1_000,
            allowed_cpus=_CPUS,
            release_token=_TOKEN,
            guardian=guardian,
            worker_pid=worker.pid,
            worker_scratch_path=scratch,
            claim_authority=_claim_authority(paths),
            release_write_fd=write_fd,
            identity_reader=lambda pid: identities[pid],
            task_affinity_reader=_task_affinities,
            clock_ns=lambda: 10,
            sleep=publish_wrong_ack,
            poll_interval_ns=1,
        )
    assert os.read(read_fd, 1) == b""
    assert not paths.compute_claim.exists()
    os.close(read_fd)


def test_release_failure_keeps_permanent_claim_and_closes_worker_pipe(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    guardian = _identity(101, ppid=2)
    supervisor = _identity(os.getpid(), ppid=guardian.pid)
    worker = _identity(303, ppid=supervisor.pid)
    identities = {item.pid: item for item in (guardian, supervisor, worker)}
    read_fd, write_fd = os.pipe()
    scratch = _worker_scratch(paths)
    now_ns = 10

    def publish_ack(_seconds: float) -> None:
        nonlocal now_ns
        registration = execution.read_registration(paths.registration)
        acknowledgement = execution.make_acknowledgement(registration, clock_ns=lambda: 30)
        execution.write_acknowledgement(paths.acknowledgement, acknowledgement)
        now_ns = 40

    with pytest.raises(RuntimeError, match="synthetic release failure"):
        execution.supervisor_register_and_release(
            paths=paths,
            transaction_id=_TRANSACTION_ID,
            absolute_deadline_ns=1_000,
            allowed_cpus=_CPUS,
            release_token=_TOKEN,
            guardian=guardian,
            worker_pid=worker.pid,
            worker_scratch_path=scratch,
            claim_authority=_claim_authority(paths),
            release_write_fd=write_fd,
            identity_reader=lambda pid: identities[pid],
            task_affinity_reader=_task_affinities,
            clock_ns=lambda: now_ns,
            sleep=publish_ack,
            poll_interval_ns=1,
            send_release=lambda fd, *, token: (_ for _ in ()).throw(
                RuntimeError("synthetic release failure")
            ),
        )

    evidence = execution.read_compute_claim(paths.compute_claim)
    assert evidence.claim.worker_scratch_path == scratch
    assert os.read(read_fd, 1) == b""
    os.close(read_fd)


def _durable_worker_chain(
    paths: execution.TransactionPaths,
) -> tuple[tuple[ProcessIdentity, ...], execution.ComputeClaimEvidence]:
    hierarchy = _hierarchy()
    registration = _registration(hierarchy)
    execution.write_registration(paths.registration, registration)
    acknowledgement = execution.make_acknowledgement(registration, clock_ns=lambda: 20)
    execution.write_acknowledgement(paths.acknowledgement, acknowledgement)
    return hierarchy, _publish_claim(paths, created_ns=30)


@pytest.mark.parametrize("replaced_record", ["acknowledgement", "compute_claim"])
def test_worker_rejects_ack_or_claim_replacement_during_double_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replaced_record: str,
) -> None:
    paths = _paths(tmp_path)
    hierarchy, evidence = _durable_worker_chain(paths)
    _guardian, supervisor, worker = hierarchy
    identities = {item.pid: item for item in hierarchy}
    target_path = getattr(paths, replaced_record)
    replacement_path = paths.private_directory / f"replacement-{replaced_record}.json"
    original_reader: Callable[[Path], object]
    if replaced_record == "acknowledgement":
        replacement_acknowledgement = replace(
            execution.read_acknowledgement(paths.acknowledgement),
            created_monotonic_ns=21,
        )
        replacement_path.write_bytes(execution.acknowledgement_bytes(replacement_acknowledgement))
        original_reader = execution.read_acknowledgement
    else:
        replacement_claim = replace(evidence.claim, created_monotonic_ns=31)
        replacement_path.write_bytes(execution.compute_claim_bytes(replacement_claim))
        original_reader = execution.read_compute_claim
    replacement_path.chmod(0o600)
    calls = 0

    def replacing_reader(path: Path) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            os.replace(replacement_path, target_path)
        return original_reader(path)

    monkeypatch.setattr(execution, f"read_{replaced_record}", replacing_reader)
    with pytest.raises(execution.ExecutionRecordError, match="changed during worker validation"):
        execution.load_and_validate_compute_claim_for_worker(
            paths.compute_claim,
            release_token=_TOKEN,
            expected_parent_pid=supervisor.pid,
            expected_absolute_deadline_ns=1_000,
            expected_allowed_cpus=_CPUS,
            current_worker_pid=worker.pid,
            identity_reader=lambda pid: identities[pid],
            task_affinity_reader=_task_affinities,
            clock_ns=lambda: 50,
        )


def test_worker_rejects_pid_reuse_after_compute_claim(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    hierarchy, _evidence = _durable_worker_chain(paths)
    guardian, supervisor, worker = hierarchy
    identities = {
        guardian.pid: guardian,
        supervisor.pid: supervisor,
        worker.pid: replace(worker, starttime_ticks=worker.starttime_ticks + 1),
    }

    with pytest.raises(execution.ExecutionIdentityError, match="PID/starttime"):
        execution.load_and_validate_compute_claim_for_worker(
            paths.compute_claim,
            release_token=_TOKEN,
            expected_parent_pid=supervisor.pid,
            expected_absolute_deadline_ns=1_000,
            expected_allowed_cpus=_CPUS,
            current_worker_pid=worker.pid,
            identity_reader=lambda pid: identities[pid],
            task_affinity_reader=_task_affinities,
            clock_ns=lambda: 50,
        )


def test_guardian_refuses_pid_reuse_before_ack(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    guardian, supervisor, worker = _hierarchy()
    registration = _registration((guardian, supervisor, worker))
    execution.write_registration(paths.registration, registration)
    identities = {
        guardian.pid: guardian,
        supervisor.pid: supervisor,
        worker.pid: replace(worker, starttime_ticks=worker.starttime_ticks + 1),
    }

    with pytest.raises(execution.ExecutionIdentityError, match="PID/starttime"):
        execution.guardian_acknowledge_registration(
            paths=paths,
            transaction_id=registration.transaction_id,
            absolute_deadline_ns=registration.absolute_deadline_ns,
            allowed_cpus=_CPUS,
            release_token=_TOKEN,
            guardian=guardian,
            supervisor=supervisor,
            supervisor_exited=lambda: False,
            identity_reader=lambda pid: identities[pid],
            task_affinity_reader=_task_affinities,
            clock_ns=lambda: 20,
            sleep=lambda seconds: None,
        )
    assert not paths.acknowledgement.exists()


class _FakeProcess:
    def __init__(self, pid: int, returncode: int = 0) -> None:
        self.pid = pid
        self.returncode = returncode
        self.wait_calls: list[float | None] = []

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        return self.returncode


def test_wait_reap_accepts_already_exited_supervisor_before_proc_validation() -> None:
    process = _FakeProcess(202, returncode=0)

    result = execution._wait_reap(
        process,
        deadline_ns=1_000,
        poll_interval_ns=10,
        clock_ns=lambda: 100,
        validate_known_processes=lambda: pytest.fail(
            "an already waitable supervisor must be reaped before /proc validation"
        ),
    )

    assert result == 0
    assert process.wait_calls == [0.0]


def test_outer_transaction_consumes_before_spawn_and_writes_clean_receipt(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    guardian = _identity(os.getpid(), ppid=os.getppid())
    supervisor = _identity(20_202, ppid=guardian.pid)
    worker = _identity(20_303, ppid=supervisor.pid)
    identities = {item.pid: item for item in (guardian, supervisor, worker)}
    events: list[str] = []
    process = _FakeProcess(supervisor.pid)
    authority = object()
    validated_authority = object()
    final_success = tmp_path / "success.json"
    final_marker = tmp_path / "_SUCCESS"

    def consume() -> execution.ConsumedPermitEvidence:
        events.append("consume")
        return execution.ConsumedPermitEvidence(_PERMIT_SHA256, authority)

    def validate(observed: object) -> object:
        assert observed is authority
        events.append("authority")
        return validated_authority

    def spawn(context: execution.GuardianLaunchContext) -> _FakeProcess:
        assert events[-1] == "authority"
        events.append("spawn")
        registration = execution.make_registration(
            transaction_id=context.transaction_id,
            absolute_deadline_ns=context.absolute_deadline_ns,
            allowed_cpus=context.policy.allowed_cpus,
            release_token=context.release_token,
            guardian=context.guardian,
            supervisor=supervisor,
            worker=worker,
            clock_ns=lambda: 110,
        )
        execution.write_registration(context.paths.registration, registration)
        return process

    def publish(
        context: execution.FinalAcceptanceContext,
    ) -> execution.PublishedFinalAcceptance:
        assert events[-1] == "reap"
        assert paths.receipt.exists()
        assert context.guardian_receipt_sha256 == execution._sha256_bytes(
            paths.receipt.read_bytes()
        )
        assert context.worker_registration_sha256 == execution.registration_sha256(
            execution.read_registration(paths.registration)
        )
        assert (
            context.compute_claim_sha256
            == execution.read_compute_claim(paths.compute_claim).compute_claim_sha256
        )
        assert context.permit_sha256 == _PERMIT_SHA256
        assert context.consumed_authority is authority
        assert context.validated_authority is validated_authority
        success_bytes = b'{"status":"accepted"}\n'
        marker_bytes = b'{"status":"phase8b_complete"}\n'
        final_success.write_bytes(success_bytes)
        assert not final_marker.exists()
        final_marker.write_bytes(marker_bytes)
        events.append("final")
        return execution.PublishedFinalAcceptance(
            execution._sha256_bytes(success_bytes),
            execution._sha256_bytes(marker_bytes),
        )

    def guard_clean(*args: object, **kwargs: object) -> GuardianResult:
        del args, kwargs
        if not paths.compute_claim.exists():
            _publish_claim(paths)
        return _clean_guardian_result()

    result = execution.run_guardian_transaction(
        transaction_id=_TRANSACTION_ID,
        paths=paths,
        release_token=_TOKEN,
        consume_permit=consume,
        recover_consumed_permit=lambda: None,
        validate_consumed_authority=validate,
        spawn_supervisor=spawn,
        publish_final_acceptance=publish,
        identity_reader=lambda pid: identities[pid],
        task_affinity_reader=_task_affinities,
        child_exited_without_reap=lambda pid: False,
        enable_subreaper=lambda: events.append("subreaper"),
        guard_group=guard_clean,
        clock_ns=lambda: 100,
        sleep=lambda seconds: None,
        reap_adopted_children=lambda: events.append("reap"),
    )

    assert events == ["subreaper", "consume", "authority", "spawn", "reap", "final"]
    assert result.receipt.succeeded
    assert result.receipt.authority_validated
    assert result.receipt.acknowledgement_published
    assert result.receipt.worker == worker
    assert (
        result.receipt.compute_claim_sha256
        == execution.read_compute_claim(paths.compute_claim).compute_claim_sha256
    )
    assert result.final_acceptance == execution.PublishedFinalAcceptance(
        execution._sha256_bytes(final_success.read_bytes()),
        execution._sha256_bytes(final_marker.read_bytes()),
    )
    assert result.receipt_sha256 == execution._sha256_bytes(paths.receipt.read_bytes())
    assert process.wait_calls
    assert stat.S_IMODE(paths.receipt.stat().st_mode) == 0o600


def test_terminal_claim_accepts_transient_guardian_and_supervisor_state_changes(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    guardian = _identity(os.getpid(), ppid=os.getppid(), state="R")
    supervisor = _identity(20_202, ppid=guardian.pid, state="R")
    registered_guardian = replace(guardian, state="S")
    registered_supervisor = replace(supervisor, state="S")
    worker = _identity(20_303, ppid=supervisor.pid)
    identities = {item.pid: item for item in (guardian, supervisor, worker)}
    process = _FakeProcess(supervisor.pid)
    final_calls = 0

    def spawn(context: execution.GuardianLaunchContext) -> _FakeProcess:
        registration = execution.make_registration(
            transaction_id=context.transaction_id,
            absolute_deadline_ns=context.absolute_deadline_ns,
            allowed_cpus=context.policy.allowed_cpus,
            release_token=context.release_token,
            guardian=registered_guardian,
            supervisor=registered_supervisor,
            worker=worker,
            clock_ns=lambda: 110,
        )
        execution.write_registration(context.paths.registration, registration)
        return process

    def guard_clean(*args: object, **kwargs: object) -> GuardianResult:
        del args, kwargs
        if not paths.compute_claim.exists():
            _publish_claim(paths)
        return _clean_guardian_result()

    def publish(
        context: execution.FinalAcceptanceContext,
    ) -> execution.PublishedFinalAcceptance:
        nonlocal final_calls
        final_calls += 1
        assert (
            context.compute_claim_sha256
            == execution.read_compute_claim(paths.compute_claim).compute_claim_sha256
        )
        return execution.PublishedFinalAcceptance("1" * 64, "2" * 64)

    result = execution.run_guardian_transaction(
        transaction_id=_TRANSACTION_ID,
        paths=paths,
        release_token=_TOKEN,
        consume_permit=lambda: execution.ConsumedPermitEvidence(_PERMIT_SHA256, object()),
        recover_consumed_permit=lambda: None,
        validate_consumed_authority=lambda authority: {"validated": True},
        spawn_supervisor=spawn,
        publish_final_acceptance=publish,
        identity_reader=lambda pid: identities[pid],
        task_affinity_reader=_task_affinities,
        child_exited_without_reap=lambda pid: False,
        enable_subreaper=lambda: None,
        guard_group=guard_clean,
        clock_ns=lambda: 100,
        sleep=lambda seconds: None,
        reap_adopted_children=lambda: None,
    )

    assert result.receipt.outcome == "clean"
    assert result.receipt.compute_claim_sha256 is not None
    assert result.receipt.guardian.state == "R"
    assert result.receipt.supervisor is not None
    assert result.receipt.supervisor.state == "R"
    assert final_calls == 1


def test_terminal_claim_rejects_stable_supervisor_starttime_drift(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    guardian = _identity(os.getpid(), ppid=os.getppid(), state="R")
    supervisor = _identity(20_202, ppid=guardian.pid, state="R")
    registered_guardian = replace(guardian, state="S")
    registered_supervisor = replace(
        supervisor,
        state="S",
        starttime_ticks=supervisor.starttime_ticks + 1,
    )
    worker = _identity(20_303, ppid=supervisor.pid)
    process = _FakeProcess(supervisor.pid)
    supervisor_reads = 0

    def identity_reader(pid: int) -> ProcessIdentity:
        nonlocal supervisor_reads
        if pid == guardian.pid:
            return guardian
        if pid == worker.pid:
            return worker
        assert pid == supervisor.pid
        supervisor_reads += 1
        return supervisor if supervisor_reads == 1 else registered_supervisor

    def spawn(context: execution.GuardianLaunchContext) -> _FakeProcess:
        registration = execution.make_registration(
            transaction_id=context.transaction_id,
            absolute_deadline_ns=context.absolute_deadline_ns,
            allowed_cpus=context.policy.allowed_cpus,
            release_token=context.release_token,
            guardian=registered_guardian,
            supervisor=registered_supervisor,
            worker=worker,
            clock_ns=lambda: 110,
        )
        execution.write_registration(context.paths.registration, registration)
        return process

    def guard_clean(*args: object, **kwargs: object) -> GuardianResult:
        del args, kwargs
        if not paths.compute_claim.exists():
            _publish_claim(paths)
        return _clean_guardian_result()

    result = execution.run_guardian_transaction(
        transaction_id=_TRANSACTION_ID,
        paths=paths,
        release_token=_TOKEN,
        consume_permit=lambda: execution.ConsumedPermitEvidence(_PERMIT_SHA256, object()),
        recover_consumed_permit=lambda: None,
        validate_consumed_authority=lambda authority: {"validated": True},
        spawn_supervisor=spawn,
        publish_final_acceptance=_forbidden_final_acceptance,
        identity_reader=identity_reader,
        task_affinity_reader=_task_affinities,
        child_exited_without_reap=lambda pid: False,
        enable_subreaper=lambda: None,
        guard_group=guard_clean,
        clock_ns=lambda: 100,
        sleep=lambda seconds: None,
        reap_adopted_children=lambda: None,
    )

    assert result.receipt.outcome == "cleanup_failed"
    assert result.receipt.error_code == "ExecutionIdentityError"
    assert result.receipt.compute_claim_sha256 is None
    assert result.final_acceptance is None
    assert supervisor_reads == 2
    assert result.receipt.supervisor == supervisor
    assert (
        execution.read_compute_claim(paths.compute_claim).claim.supervisor == registered_supervisor
    )


def test_outer_transaction_rejects_final_acceptance_at_absolute_deadline(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    guardian = _identity(os.getpid(), ppid=os.getppid())
    supervisor = _identity(20_202, ppid=guardian.pid)
    worker = _identity(20_303, ppid=supervisor.pid)
    identities = {item.pid: item for item in (guardian, supervisor, worker)}
    process = _FakeProcess(supervisor.pid)
    deadline_reached = False
    expected_deadline = 100 + execution.TransactionPolicy().timeout_ns

    def clock() -> int:
        return expected_deadline if deadline_reached else 100

    def spawn(context: execution.GuardianLaunchContext) -> _FakeProcess:
        registration = execution.make_registration(
            transaction_id=context.transaction_id,
            absolute_deadline_ns=context.absolute_deadline_ns,
            allowed_cpus=context.policy.allowed_cpus,
            release_token=context.release_token,
            guardian=context.guardian,
            supervisor=supervisor,
            worker=worker,
            clock_ns=lambda: 110,
        )
        execution.write_registration(context.paths.registration, registration)
        return process

    def reap() -> None:
        nonlocal deadline_reached
        deadline_reached = True

    def guard_clean(*args: object, **kwargs: object) -> GuardianResult:
        del args, kwargs
        if not paths.compute_claim.exists():
            _publish_claim(paths)
        return _clean_guardian_result()

    result = execution.run_guardian_transaction(
        transaction_id=_TRANSACTION_ID,
        paths=paths,
        release_token=_TOKEN,
        consume_permit=lambda: execution.ConsumedPermitEvidence(_PERMIT_SHA256, object()),
        recover_consumed_permit=lambda: None,
        validate_consumed_authority=lambda authority: {"validated": True},
        spawn_supervisor=spawn,
        publish_final_acceptance=_forbidden_final_acceptance,
        identity_reader=lambda pid: identities[pid],
        task_affinity_reader=_task_affinities,
        child_exited_without_reap=lambda pid: False,
        enable_subreaper=lambda: None,
        guard_group=guard_clean,
        clock_ns=clock,
        sleep=lambda seconds: None,
        reap_adopted_children=reap,
    )

    assert result.receipt.outcome == "cleanup_failed"
    assert result.receipt.error_code == "absolute_deadline_exceeded"
    assert result.final_acceptance is None


def test_permit_failure_prevents_spawn_and_creates_no_receipt(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    guardian = _identity(os.getpid(), ppid=os.getppid())
    spawned = False

    def forbidden_spawn(context: execution.GuardianLaunchContext) -> _FakeProcess:
        del context
        nonlocal spawned
        spawned = True
        return _FakeProcess(202)

    with pytest.raises(RuntimeError, match="permit rejected"):
        execution.run_guardian_transaction(
            transaction_id=_TRANSACTION_ID,
            paths=paths,
            release_token=_TOKEN,
            consume_permit=lambda: (_ for _ in ()).throw(RuntimeError("permit rejected")),
            recover_consumed_permit=lambda: None,
            validate_consumed_authority=lambda authority: pytest.fail(
                f"authority validation must be unreachable: {authority}"
            ),
            spawn_supervisor=forbidden_spawn,
            publish_final_acceptance=_forbidden_final_acceptance,
            identity_reader=lambda pid: guardian,
            task_affinity_reader=_task_affinities,
            enable_subreaper=lambda: None,
            clock_ns=lambda: 100,
        )
    assert spawned is False
    assert not paths.receipt.exists()


def test_post_linearization_consume_error_recovers_and_writes_failure_receipt(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    guardian = _identity(os.getpid(), ppid=os.getppid())
    authority = {"consumed": True}
    recovered = execution.ConsumedPermitEvidence(_PERMIT_SHA256, authority)
    spawned = False
    validated = False

    def forbidden_spawn(context: execution.GuardianLaunchContext) -> _FakeProcess:
        del context
        nonlocal spawned
        spawned = True
        return _FakeProcess(202)

    def forbidden_validate(observed: object) -> None:
        del observed
        nonlocal validated
        validated = True

    result = execution.run_guardian_transaction(
        transaction_id=_TRANSACTION_ID,
        paths=paths,
        release_token=_TOKEN,
        consume_permit=lambda: (_ for _ in ()).throw(
            execution.ExecutionRecordError("failure after O_EXCL")
        ),
        recover_consumed_permit=lambda: recovered,
        validate_consumed_authority=forbidden_validate,
        spawn_supervisor=forbidden_spawn,
        publish_final_acceptance=_forbidden_final_acceptance,
        identity_reader=lambda pid: guardian,
        task_affinity_reader=_task_affinities,
        enable_subreaper=lambda: None,
        clock_ns=lambda: 100,
        reap_adopted_children=lambda: None,
    )

    assert spawned is False
    assert validated is False
    assert result.receipt.outcome == "permit_consumption_failed"
    assert result.receipt.permit_sha256 == _PERMIT_SHA256
    assert result.receipt.authority_validated is False
    assert paths.receipt.exists()


def test_authority_crosscheck_failure_after_consumption_is_receipted_without_spawn(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    guardian = _identity(os.getpid(), ppid=os.getppid())
    spawned = False

    def forbidden_spawn(context: execution.GuardianLaunchContext) -> _FakeProcess:
        del context
        nonlocal spawned
        spawned = True
        return _FakeProcess(202)

    result = execution.run_guardian_transaction(
        transaction_id=_TRANSACTION_ID,
        paths=paths,
        release_token=_TOKEN,
        consume_permit=lambda: execution.ConsumedPermitEvidence(_PERMIT_SHA256, {"consumed": True}),
        recover_consumed_permit=lambda: None,
        validate_consumed_authority=lambda authority: (_ for _ in ()).throw(
            execution.ExecutionIdentityError("request/source/payload drift")
        ),
        spawn_supervisor=forbidden_spawn,
        publish_final_acceptance=_forbidden_final_acceptance,
        identity_reader=lambda pid: guardian,
        task_affinity_reader=_task_affinities,
        enable_subreaper=lambda: None,
        clock_ns=lambda: 100,
        reap_adopted_children=lambda: None,
    )

    assert spawned is False
    assert result.receipt.outcome == "authority_failed"
    assert result.receipt.authority_validated is False
    assert result.receipt.acknowledgement_published is False
    assert paths.receipt.exists()
    assert not (tmp_path / "_SUCCESS").exists()


def test_spawn_failure_after_consumption_is_terminal_and_receipted(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    guardian = _identity(os.getpid(), ppid=os.getppid())
    consume_calls = 0

    def consume() -> execution.ConsumedPermitEvidence:
        nonlocal consume_calls
        consume_calls += 1
        return execution.ConsumedPermitEvidence(_PERMIT_SHA256, object())

    result = execution.run_guardian_transaction(
        transaction_id=_TRANSACTION_ID,
        paths=paths,
        release_token=_TOKEN,
        consume_permit=consume,
        recover_consumed_permit=lambda: None,
        validate_consumed_authority=lambda authority: {"validated": True},
        spawn_supervisor=lambda context: (_ for _ in ()).throw(
            execution.SupervisorLaunchError("synthetic")
        ),
        publish_final_acceptance=_forbidden_final_acceptance,
        identity_reader=lambda pid: guardian,
        task_affinity_reader=_task_affinities,
        enable_subreaper=lambda: None,
        clock_ns=lambda: 100,
        reap_adopted_children=lambda: None,
    )

    assert consume_calls == 1
    assert result.receipt.outcome == "spawn_failed"
    assert result.receipt.error_code == "SupervisorLaunchError"
    assert paths.receipt.exists()


def test_missing_registration_cleans_supervisor_and_records_failure(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    guardian = _identity(os.getpid(), ppid=os.getppid())
    supervisor = _identity(20_202, ppid=guardian.pid)
    identities = {guardian.pid: guardian, supervisor.pid: supervisor}
    process = _FakeProcess(supervisor.pid, returncode=17)
    guard_calls: list[int] = []

    def guard(identity: ProcessIdentity, **kwargs: object) -> GuardianResult:
        del kwargs
        guard_calls.append(identity.pid)
        return GuardianResult(
            outcome="abort",
            trigger="abort",
            term_sent=True,
            kill_sent=False,
            group_cleanup_confirmed=True,
            duration_ns=1,
            error_message=None,
        )

    result = execution.run_guardian_transaction(
        transaction_id=_TRANSACTION_ID,
        paths=paths,
        release_token=_TOKEN,
        consume_permit=lambda: execution.ConsumedPermitEvidence(_PERMIT_SHA256, object()),
        recover_consumed_permit=lambda: None,
        validate_consumed_authority=lambda authority: {"validated": True},
        spawn_supervisor=lambda context: process,
        publish_final_acceptance=_forbidden_final_acceptance,
        identity_reader=lambda pid: identities[pid],
        task_affinity_reader=_task_affinities,
        child_exited_without_reap=lambda pid: True,
        enable_subreaper=lambda: None,
        guard_group=guard,
        clock_ns=lambda: 100,
        sleep=lambda seconds: None,
        reap_adopted_children=lambda: None,
    )

    assert result.receipt.outcome == "registration_failed"
    assert result.receipt.acknowledgement_published is False
    assert result.receipt.supervisor_returncode == 17
    assert guard_calls == [supervisor.pid]


def test_worker_guard_continuously_checks_guardian_and_supervisor_affinity(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    guardian = _identity(os.getpid(), ppid=os.getppid())
    supervisor = _identity(20_202, ppid=guardian.pid)
    worker = _identity(20_303, ppid=supervisor.pid)
    identities = {item.pid: item for item in (guardian, supervisor, worker)}
    process = _FakeProcess(supervisor.pid, returncode=17)
    guarded: list[int] = []

    def spawn(context: execution.GuardianLaunchContext) -> _FakeProcess:
        registration = execution.make_registration(
            transaction_id=context.transaction_id,
            absolute_deadline_ns=context.absolute_deadline_ns,
            allowed_cpus=context.policy.allowed_cpus,
            release_token=context.release_token,
            guardian=context.guardian,
            supervisor=supervisor,
            worker=worker,
            clock_ns=lambda: 110,
        )
        execution.write_registration(context.paths.registration, registration)
        return process

    def guard(identity: ProcessIdentity, **kwargs: object) -> GuardianResult:
        guarded.append(identity.pid)
        if identity.pid == worker.pid:
            identities[supervisor.pid] = replace(supervisor, cpus_allowed=frozenset({0, 4}))
            abort_requested = kwargs["abort_requested"]
            assert callable(abort_requested)
            assert abort_requested()
        return GuardianResult(
            outcome="abort",
            trigger="abort",
            term_sent=True,
            kill_sent=False,
            group_cleanup_confirmed=True,
            duration_ns=1,
            error_message=None,
        )

    result = execution.run_guardian_transaction(
        transaction_id=_TRANSACTION_ID,
        paths=paths,
        release_token=_TOKEN,
        consume_permit=lambda: execution.ConsumedPermitEvidence(_PERMIT_SHA256, object()),
        recover_consumed_permit=lambda: None,
        validate_consumed_authority=lambda authority: {"validated": True},
        spawn_supervisor=spawn,
        publish_final_acceptance=_forbidden_final_acceptance,
        identity_reader=lambda pid: identities[pid],
        task_affinity_reader=lambda pid: {pid: identities[pid].cpus_allowed},
        child_exited_without_reap=lambda pid: False,
        enable_subreaper=lambda: None,
        guard_group=guard,
        clock_ns=lambda: 100,
        sleep=lambda seconds: None,
        reap_adopted_children=lambda: None,
    )

    assert result.receipt.outcome == "worker_guard_failed"
    assert result.receipt.error_code == "ExecutionIdentityError"
    assert result.final_acceptance is None
    assert guarded == [worker.pid, supervisor.pid]


@pytest.mark.parametrize("stale_record", ["receipt", "compute_claim"])
def test_stale_coordination_state_is_rejected_before_permit_consumption(
    tmp_path: Path,
    stale_record: str,
) -> None:
    paths = _paths(tmp_path)
    stale_path = getattr(paths, stale_record)
    stale_path.write_text("stale", encoding="ascii")
    stale_path.chmod(0o600)
    consumed = False

    def consume() -> execution.ConsumedPermitEvidence:
        nonlocal consumed
        consumed = True
        return execution.ConsumedPermitEvidence(_PERMIT_SHA256, object())

    with pytest.raises(execution.ExecutionRecordError, match="stale"):
        execution.run_guardian_transaction(
            transaction_id=_TRANSACTION_ID,
            paths=paths,
            release_token=_TOKEN,
            consume_permit=consume,
            recover_consumed_permit=lambda: None,
            validate_consumed_authority=lambda authority: {"validated": True},
            spawn_supervisor=lambda context: _FakeProcess(202),
            publish_final_acceptance=_forbidden_final_acceptance,
        )
    assert consumed is False


def test_clean_receipt_is_rejected_at_exact_absolute_deadline() -> None:
    guardian, supervisor, worker = _hierarchy()
    receipt = execution.GuardianReceipt(
        transaction_id=_TRANSACTION_ID,
        permit_sha256=_PERMIT_SHA256,
        absolute_deadline_ns=100,
        started_monotonic_ns=10,
        finished_monotonic_ns=100,
        outcome="clean",
        error_code=None,
        authority_validated=True,
        acknowledgement_published=True,
        worker_registration_sha256="e" * 64,
        compute_claim_sha256="f" * 64,
        supervisor_returncode=0,
        guardian=guardian,
        supervisor=supervisor,
        worker=worker,
        worker_guardian_result=_clean_guardian_result(),
        supervisor_guardian_result=None,
    )

    with pytest.raises(execution.ExecutionRecordError, match="lacks success evidence"):
        execution.receipt_bytes(receipt)


def test_frozen_policy_rejects_any_resource_widening() -> None:
    execution.ensure_frozen_policy(execution.TransactionPolicy())
    with pytest.raises(execution.Phase8BExecutionError, match="drifted"):
        execution.ensure_frozen_policy(execution.TransactionPolicy(timeout_ns=1))
    with pytest.raises(execution.Phase8BExecutionError, match="drifted"):
        execution.ensure_frozen_policy(
            execution.TransactionPolicy(allowed_cpus=frozenset({0, 1, 2, 3, 4}))
        )


def test_outer_transaction_rejects_nonfrozen_attempt_before_permit(tmp_path: Path) -> None:
    consumed = False

    def consume() -> execution.ConsumedPermitEvidence:
        nonlocal consumed
        consumed = True
        return execution.ConsumedPermitEvidence(_PERMIT_SHA256, object())

    with pytest.raises(execution.Phase8BExecutionError, match="identity drifted"):
        execution.run_guardian_transaction(
            transaction_id="attempt-phase8b-other-v001",
            paths=_paths(tmp_path),
            release_token=_TOKEN,
            consume_permit=consume,
            recover_consumed_permit=lambda: None,
            validate_consumed_authority=lambda authority: object(),
            spawn_supervisor=lambda context: _FakeProcess(202),
            publish_final_acceptance=_forbidden_final_acceptance,
        )
    assert consumed is False


def test_spawn_helper_is_shell_free_new_session_and_parent_contained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guardian, _, _ = _hierarchy()
    context = execution.GuardianLaunchContext(
        transaction_id=_TRANSACTION_ID,
        paths=execution.TransactionPaths(
            Path("/tmp/private/reg"),
            Path("/tmp/private/ack"),
            Path("/tmp/private/claim"),
            Path("/tmp/private/receipt"),
        ),
        policy=execution.TransactionPolicy(),
        absolute_deadline_ns=100,
        release_token=_TOKEN,
        guardian=guardian,
    )
    captured: dict[str, object] = {}

    def fake_popen(argv: tuple[str, ...], **kwargs: object) -> _FakeProcess:
        captured["argv"] = argv
        captured.update(kwargs)
        return _FakeProcess(202)

    monkeypatch.setattr(execution.subprocess, "Popen", fake_popen)
    process = execution.spawn_supervisor_command(context, ("python", "-I", "entry.py"))

    assert process.pid == 202
    assert captured["shell"] is False
    assert captured["start_new_session"] is True
    assert callable(captured["preexec_fn"])
    assert captured["close_fds"] is True
    assert signal.SIGKILL > 0  # documents the PDEATHSIG primitive's fixed signal family
