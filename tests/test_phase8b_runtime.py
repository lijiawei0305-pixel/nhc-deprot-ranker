"""No-chemistry contract tests for the Phase 8B production entry point."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nhc_deprot_ranker.preparation import phase8b_bundle
from nhc_deprot_ranker.quantum import phase8b_runtime as runtime
from nhc_deprot_ranker.quantum import two_endpoint as runner
from nhc_deprot_ranker.quantum import worker
from nhc_deprot_ranker.quantum.linux_guardian import ProcessIdentity
from nhc_deprot_ranker.quantum.phase8b_authority import (
    ExactPhase8BAuthority,
    Phase8BBundleIdentity,
)
from nhc_deprot_ranker.quantum.phase8b_execution import (
    FROZEN_ALLOWED_CPUS,
    FinalAcceptanceContext,
    GuardianLaunchContext,
    TransactionPolicy,
)
from nhc_deprot_ranker.quantum.phase8b_permit import FROZEN_ATTEMPT_ID

_HASHES = tuple(character * 64 for character in "abcdef")
_TRANSPORT_SHA256, _PAYLOAD_SHA256, _PERMIT_SHA256, _REQUEST_SHA256, _SOURCE_SHA256, _AUX_SHA256 = (
    _HASHES
)


def _bundle_identity() -> Phase8BBundleIdentity:
    return Phase8BBundleIdentity(
        transport_inventory_sha256=_TRANSPORT_SHA256,
        payload_manifest_sha256=_PAYLOAD_SHA256,
        permit_sha256=_PERMIT_SHA256,
        request_sha256=_REQUEST_SHA256,
        runner_source_sha256=_SOURCE_SHA256,
    )


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_production_runtime_is_inside_both_exact_source_closures() -> None:
    runtime_relative = "nhc_deprot_ranker/quantum/phase8b_runtime.py"
    assert runtime_relative in runner._RUNNER_SOURCE_RELATIVE_PATHS  # pyright: ignore[reportPrivateUsage]
    assert runtime_relative in phase8b_bundle._REQUIRED_FINAL_SOURCE_FILES  # pyright: ignore[reportPrivateUsage]

    tree = ast.parse(Path(runtime.__file__).read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("nhc_deprot_ranker")
    }
    assert imported_modules == {
        "nhc_deprot_ranker.quantum",
        "nhc_deprot_ranker.quantum.linux_guardian",
        "nhc_deprot_ranker.quantum.phase8b_authority",
        "nhc_deprot_ranker.quantum.phase8b_execution",
        "nhc_deprot_ranker.quantum.phase8b_permit",
    }
    lowered_source = Path(runtime.__file__).read_text(encoding="utf-8").lower()
    assert "import pyscf" not in lowered_source
    assert "import geometric" not in lowered_source


def test_obsolete_generic_route_rejects_even_after_gate_opens_before_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_request_read(path: Path) -> runner.TwoEndpointRequest:
        pytest.fail(f"generic route inspected a request: {path}")

    monkeypatch.setattr(runner, "EXECUTION_AUTHORIZED", True)
    monkeypatch.setattr(runner, "load_two_endpoint_request", forbidden_request_read)
    output = tmp_path / "output"
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="generic two-endpoint"):
        runner.run_two_endpoint(tmp_path / "request.json", output)
    assert not output.exists()


@pytest.mark.parametrize(
    "missing_option",
    [
        "--consumed-permit-path",
        "--expected-permit-sha256",
        "--expected-request-sha256",
        "--expected-runner-source-sha256",
        "--expected-payload-manifest-sha256",
        "--expected-transport-inventory-sha256",
        "--authorized-output-root",
        "--absolute-deadline-ns",
        "--compute-claim-path",
        "--release-token",
    ],
)
def test_worker_requires_every_exact_authority_argument_before_backend_or_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_option: str,
) -> None:
    events: list[str] = []

    def fake_request(path: Path) -> SimpleNamespace:
        del path
        events.append("request")
        return SimpleNamespace(execution_authorized=True)

    def forbidden_backend(*args: object, **kwargs: object) -> object:
        del args, kwargs
        events.append("backend")
        raise AssertionError("backend construction must remain unreachable")

    monkeypatch.setattr(worker.runner, "_ensure_execution_authorized", lambda: None)
    monkeypatch.setattr(worker.runner, "load_two_endpoint_request", fake_request)
    monkeypatch.setattr(worker.runner, "PySCFBackend", forbidden_backend)
    output = tmp_path / "scratch"
    options = {
        "--request-path": str(tmp_path / "request.json"),
        "--output-root": str(output),
        "--attempt-id": FROZEN_ATTEMPT_ID,
        "--consumed-permit-path": str(tmp_path / "private/permit.consumed.json"),
        "--expected-permit-sha256": _PERMIT_SHA256,
        "--expected-request-sha256": _REQUEST_SHA256,
        "--expected-runner-source-sha256": _SOURCE_SHA256,
        "--expected-payload-manifest-sha256": _PAYLOAD_SHA256,
        "--expected-transport-inventory-sha256": _TRANSPORT_SHA256,
        "--authorized-output-root": str(tmp_path / "output"),
        "--absolute-deadline-ns": "999999999999999999",
        "--compute-claim-path": str(tmp_path / "private/compute_claim.json"),
        "--release-token": _AUX_SHA256,
    }
    argv = [
        value
        for option, value in options.items()
        if option != missing_option
        for value in (option, value)
    ]
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="complete consumed Phase 8B"):
        worker.main(argv)
    assert events == ["request"]
    assert not output.exists()


def test_supervisor_main_uses_bound_hashes_without_revalidating_consumed_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = (tmp_path / "run").resolve()
    run_root.mkdir()
    observed: dict[str, object] = {}

    def forbidden_transport_validation(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("consumed transport tree cannot pass untouched-tree validation")

    def fake_supervisor(**kwargs: object) -> int:
        observed.update(kwargs)
        return 17

    monkeypatch.setattr(
        runtime,
        "validate_phase8b_transport_bundle",
        forbidden_transport_validation,
    )
    monkeypatch.setattr(runtime, "_run_supervisor", fake_supervisor)
    result = runtime.main(
        [
            "supervisor",
            "--run-root",
            str(run_root),
            "--transport-inventory-sha256",
            _TRANSPORT_SHA256,
            "--expected-payload-manifest-sha256",
            _PAYLOAD_SHA256,
            "--expected-permit-sha256",
            _PERMIT_SHA256,
            "--expected-request-sha256",
            _REQUEST_SHA256,
            "--expected-runner-source-sha256",
            _SOURCE_SHA256,
            "--absolute-deadline-ns",
            "999999999999999999",
            "--release-token",
            _AUX_SHA256,
            "--guardian-pid",
            "4242",
        ]
    )
    assert result == 17
    assert observed["run_root"] == run_root
    assert observed["bundle"] == _bundle_identity()


@pytest.mark.parametrize(
    "option",
    [
        "--transport-inventory-sha256",
        "--expected-payload-manifest-sha256",
        "--expected-permit-sha256",
        "--expected-request-sha256",
        "--expected-runner-source-sha256",
        "--release-token",
    ],
)
def test_supervisor_cli_rejects_every_malformed_hash_before_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    option: str,
) -> None:
    run_root = (tmp_path / "run").resolve()
    run_root.mkdir()
    argv = [
        "supervisor",
        "--run-root",
        str(run_root),
        "--transport-inventory-sha256",
        _TRANSPORT_SHA256,
        "--expected-payload-manifest-sha256",
        _PAYLOAD_SHA256,
        "--expected-permit-sha256",
        _PERMIT_SHA256,
        "--expected-request-sha256",
        _REQUEST_SHA256,
        "--expected-runner-source-sha256",
        _SOURCE_SHA256,
        "--absolute-deadline-ns",
        "999999999999999999",
        "--release-token",
        _AUX_SHA256,
        "--guardian-pid",
        "4242",
    ]
    argv[argv.index(option) + 1] = "A" * 64
    monkeypatch.setattr(
        runtime,
        "_run_supervisor",
        lambda **kwargs: pytest.fail(f"runtime reached with {kwargs}"),
    )
    with pytest.raises(SystemExit, match="2"):
        runtime.main(argv)


def test_partial_supervisor_log_open_closes_first_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "run"
    private = run_root / "private"
    private.mkdir(parents=True)
    stderr_path = private / "supervisor.stderr.log"
    stderr_path.write_bytes(b"stale")
    stderr_path.chmod(0o600)
    real_open = os.open
    real_close = os.close
    opened_stdout: list[int] = []
    closed: list[int] = []

    def tracking_open(
        path: os.PathLike[str] | str, flags: int, *args: object, **kwargs: object
    ) -> int:
        descriptor = real_open(path, flags, *args, **kwargs)
        if Path(path).name == "supervisor.stdout.log":
            opened_stdout.append(descriptor)
        return descriptor

    def tracking_close(descriptor: int) -> None:
        closed.append(descriptor)
        real_close(descriptor)

    monkeypatch.setattr(runtime.os, "open", tracking_open)
    monkeypatch.setattr(runtime.os, "close", tracking_close)
    with pytest.raises(runtime.SupervisorLaunchError, match="stderr log could not be created"):
        runtime._open_supervisor_logs(run_root)  # pyright: ignore[reportPrivateUsage]
    assert len(opened_stdout) == 1
    assert opened_stdout[0] in closed
    with pytest.raises(OSError):
        os.fstat(opened_stdout[0])


def test_guardian_log_is_not_created_when_untouched_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = (tmp_path / "run").resolve()
    run_root.mkdir()
    log_path = run_root / "private/guardian.log"
    guardian_pid = 31_337
    monkeypatch.setattr(runtime.runner, "_ensure_execution_authorized", lambda: None)
    monkeypatch.setattr(runtime.os, "getpid", lambda: guardian_pid)
    monkeypatch.setattr(runtime.os, "getsid", lambda pid: guardian_pid)
    monkeypatch.setattr(runtime.os, "getpgrp", lambda: guardian_pid)
    monkeypatch.setattr(
        runtime.os,
        "sched_getaffinity",
        lambda pid: FROZEN_ALLOWED_CPUS,
        raising=False,
    )
    monkeypatch.setattr(runtime, "require_affinity", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runtime,
        "validate_phase8b_transport_bundle",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            runtime.Phase8BRuntimeError("synthetic transport failure")
        ),
    )
    with pytest.raises(runtime.Phase8BRuntimeError, match="synthetic transport failure"):
        runtime._run_guardian(  # pyright: ignore[reportPrivateUsage]
            run_root=run_root,
            transport_inventory_sha256=_TRANSPORT_SHA256,
        )
    assert not log_path.exists()


def test_failed_guardian_path_passes_hash_bound_supervisor_argv_and_never_publishes_final_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_root = (tmp_path / "run").resolve()
    private = run_root / "private"
    private.mkdir(parents=True, mode=0o700)
    private.chmod(0o700)
    bundle = _bundle_identity()
    events: list[str] = []
    spawned_argv: list[str] = []
    guardian_pid = 31_337
    guardian = ProcessIdentity(
        pid=guardian_pid,
        ppid=2,
        pgid=guardian_pid,
        sid=guardian_pid,
        starttime_ticks=123_456,
        state="S",
        boot_id="11111111-2222-3333-4444-555555555555",
        cpus_allowed=FROZEN_ALLOWED_CPUS,
    )
    fake_permit = SimpleNamespace(
        request_path=run_root / "input/request.json",
        output_root=run_root / "runtime/output",
        run_root=run_root,
        consumed_path=run_root / "private/permit.consumed.json",
    )
    consumed = SimpleNamespace(consumed_sha256=_PERMIT_SHA256, permit=fake_permit)
    validated_authority = object()

    monkeypatch.setattr(
        runtime.runner,
        "_ensure_execution_authorized",
        lambda: events.append("gate"),
    )
    monkeypatch.setattr(runtime.os, "getpid", lambda: guardian_pid)
    monkeypatch.setattr(runtime.os, "getsid", lambda pid: guardian_pid)
    monkeypatch.setattr(runtime.os, "getpgrp", lambda: guardian_pid)
    monkeypatch.setattr(
        runtime.os,
        "sched_getaffinity",
        lambda pid: FROZEN_ALLOWED_CPUS,
        raising=False,
    )
    monkeypatch.setattr(
        runtime,
        "require_affinity",
        lambda *args, **kwargs: events.append("affinity"),
    )

    def validate_transport(*args: object, **kwargs: object) -> Phase8BBundleIdentity:
        del args, kwargs
        events.append("transport")
        return bundle

    def consume_permit(*args: object, **kwargs: object) -> SimpleNamespace:
        del args, kwargs
        assert not (private / "guardian.log").exists()
        assert not (private / "supervisor.stdout.log").exists()
        assert not (private / "supervisor.stderr.log").exists()
        events.append("consume")
        return consumed

    def validate_session(session: object, *, require_output_absent: bool) -> object:
        assert isinstance(session, runtime._AuthoritySession)  # pyright: ignore[reportPrivateUsage]
        assert require_output_absent is True
        assert not (private / "guardian.log").exists()
        assert not (private / "supervisor.stdout.log").exists()
        assert not (private / "supervisor.stderr.log").exists()
        events.append("authority")
        return validated_authority

    def spawn_command(
        context: GuardianLaunchContext,
        argv: tuple[str, ...],
        **kwargs: object,
    ) -> SimpleNamespace:
        del context, kwargs
        assert (private / "guardian.log").is_file()
        assert (private / "supervisor.stdout.log").is_file()
        assert (private / "supervisor.stderr.log").is_file()
        events.append("spawn")
        spawned_argv.extend(argv)
        raise OSError("synthetic supervisor launch failure")

    def redirect_guardian(run_path: Path) -> None:
        assert run_path == run_root
        assert not (private / "supervisor.stdout.log").exists()
        assert not (private / "supervisor.stderr.log").exists()
        guardian_log = private / "guardian.log"
        guardian_log.write_bytes(b"")
        guardian_log.chmod(0o600)
        events.append("guardian_log")

    def failed_transaction(**kwargs: Any) -> SimpleNamespace:
        events.append("transaction")
        evidence = kwargs["consume_permit"]()
        assert evidence.permit_sha256 == _PERMIT_SHA256
        assert kwargs["validate_consumed_authority"](evidence.authority) is validated_authority
        launch = GuardianLaunchContext(
            transaction_id=kwargs["transaction_id"],
            paths=kwargs["paths"],
            policy=TransactionPolicy(),
            absolute_deadline_ns=999_999_999_999_999_999,
            release_token=kwargs["release_token"],
            guardian=guardian,
        )
        with pytest.raises(runtime.SupervisorLaunchError, match="supervisor spawn failed"):
            kwargs["spawn_supervisor"](launch)
        return SimpleNamespace(
            receipt=SimpleNamespace(outcome="spawn_failed"),
            receipt_sha256=_AUX_SHA256,
            final_acceptance=None,
        )

    monkeypatch.setattr(runtime, "validate_phase8b_transport_bundle", validate_transport)
    monkeypatch.setattr(runtime, "consume_phase8b_permit", consume_permit)
    monkeypatch.setattr(runtime, "_load_exact_session", validate_session)
    monkeypatch.setattr(runtime, "_redirect_guardian_log", redirect_guardian)
    monkeypatch.setattr(runtime, "spawn_supervisor_command", spawn_command)
    monkeypatch.setattr(runtime, "run_guardian_transaction", failed_transaction)

    assert (
        runtime._run_guardian(  # pyright: ignore[reportPrivateUsage]
            run_root=run_root,
            transport_inventory_sha256=_TRANSPORT_SHA256,
        )
        == 1
    )
    assert events == [
        "gate",
        "affinity",
        "transport",
        "transaction",
        "consume",
        "authority",
        "guardian_log",
        "spawn",
    ]
    expected_hash_options = {
        "--transport-inventory-sha256": _TRANSPORT_SHA256,
        "--expected-payload-manifest-sha256": _PAYLOAD_SHA256,
        "--expected-permit-sha256": _PERMIT_SHA256,
        "--expected-request-sha256": _REQUEST_SHA256,
        "--expected-runner-source-sha256": _SOURCE_SHA256,
    }
    for option, value in expected_hash_options.items():
        index = spawned_argv.index(option)
        assert spawned_argv[index + 1] == value
    assert not (run_root / "runtime/output/success.json").exists()
    assert not (run_root / "runtime/output/_SUCCESS").exists()
    receipt_output = capsys.readouterr().out
    assert '"final_acceptance": null' in receipt_output
    assert f'"transport_inventory_sha256": "{_TRANSPORT_SHA256}"' in receipt_output


def _final_acceptance_fixture(
    tmp_path: Path,
) -> tuple[runtime._AuthoritySession, FinalAcceptanceContext, dict[str, bytes]]:  # pyright: ignore[reportPrivateUsage]
    output_root = tmp_path / "output"
    (output_root / "attempts").mkdir(parents=True)
    (output_root / "supervisor_success.json").write_bytes(b"provisional\n")
    (output_root / "_SUPERVISOR_SUCCESS").write_bytes(b"provisional marker\n")
    run_root = tmp_path / "run"
    consumed_path = run_root / "private/permit.consumed.json"
    request = SimpleNamespace(
        cation=SimpleNamespace(xyz_sha256="1" * 64),
        neutral=SimpleNamespace(xyz_sha256="2" * 64),
    )
    exact = ExactPhase8BAuthority(
        request_sha256=_REQUEST_SHA256,
        runner_source_sha256=_SOURCE_SHA256,
        permit_sha256=_PERMIT_SHA256,
        payload_manifest_sha256=_PAYLOAD_SHA256,
        endpoint_atom_map_sha256="3" * 64,
        legacy_atom_map_sha256="4" * 64,
        geometry_validation_sha256="5" * 64,
        electron_count=120,
        request_id="phase8b-qxh-smoke-v001",
        inchikey="QXHIEGFUWOLQIJ-UHFFFAOYSA-N",
        attempt_id=FROZEN_ATTEMPT_ID,
        project_root=str(tmp_path),
        run_root=str(run_root),
        request_path=str(run_root / "input/request.json"),
        output_root=str(output_root),
        resources_sha256="6" * 64,
    )
    consumed = SimpleNamespace(
        consumed_sha256=_PERMIT_SHA256,
        permit=SimpleNamespace(
            consumed_path=consumed_path,
            output_root=output_root,
            run_root=run_root,
        ),
    )
    session = runtime._AuthoritySession(  # pyright: ignore[reportPrivateUsage]
        consumed=consumed,
        bundle=_bundle_identity(),
        request=request,
        exact=exact,
    )
    supervisor_success_raw = b"supervisor success\n"
    supervisor_marker_raw = runtime._canonical_json_bytes(  # pyright: ignore[reportPrivateUsage]
        {
            "schema_version": runner.SUPERVISOR_SUCCESS_SCHEMA_VERSION,
            "supervisor_success_sha256": _sha256(supervisor_success_raw),
        }
    )
    bound_bytes = {
        "supervisor success": supervisor_success_raw,
        "supervisor success marker": supervisor_marker_raw,
        "guardian receipt": b"guardian receipt\n",
        "worker registration": b"worker registration\n",
        "compute claim": b"compute claim\n",
    }
    compute_claim_sha256 = _sha256(bound_bytes["compute claim"])
    context = FinalAcceptanceContext(
        transaction_id=FROZEN_ATTEMPT_ID,
        permit_sha256=_PERMIT_SHA256,
        worker_registration_sha256=_sha256(bound_bytes["worker registration"]),
        compute_claim_sha256=compute_claim_sha256,
        guardian_receipt=SimpleNamespace(
            outcome="clean",
            supervisor_returncode=0,
            worker_guardian_result=SimpleNamespace(group_cleanup_confirmed=True),
            compute_claim_sha256=compute_claim_sha256,
        ),
        guardian_receipt_sha256=_sha256(bound_bytes["guardian receipt"]),
        consumed_authority=session,
        validated_authority=exact,
    )
    return session, context, bound_bytes


def _provisional_result() -> SimpleNamespace:
    return SimpleNamespace(
        attempt_id=FROZEN_ATTEMPT_ID,
        result_relative_path=f"attempts/{FROZEN_ATTEMPT_ID}/result.json",
        result_sha256="7" * 64,
        cation_energy_hartree=-1.0,
        neutral_energy_hartree=-2.0,
        electronic_difference_kcal=-627.5,
        dft_deprot_electronic_kcal=688.8,
    )


def test_exact_file_read_rejects_path_replacement_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = (tmp_path / "record.json").resolve()
    target.write_bytes(b'{"status":"first"}\n')
    target.chmod(0o600)
    real_read = os.read
    replaced = False

    def replacing_read(descriptor: int, count: int) -> bytes:
        nonlocal replaced
        chunk = real_read(descriptor, count)
        if chunk and not replaced:
            replacement = target.with_name("replacement.json")
            replacement.write_bytes(b'{"status":"second"}\n')
            replacement.chmod(0o600)
            os.replace(replacement, target)
            replaced = True
        return chunk

    monkeypatch.setattr(runtime.os, "read", replacing_read)
    with pytest.raises(runtime.Phase8BRuntimeError, match="changed while being read"):
        runtime._read_exact_file(  # pyright: ignore[reportPrivateUsage]
            target,
            expected_mode=0o600,
            label="synthetic record",
        )


def test_exact_file_read_rejects_intermediate_directory_symlink(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    target = real_parent / "record.json"
    target.write_bytes(b'{"status":"first"}\n')
    target.chmod(0o600)
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(runtime.Phase8BRuntimeError, match="parent cannot be opened safely"):
        runtime._read_exact_file(  # pyright: ignore[reportPrivateUsage]
            linked_parent / "record.json",
            expected_mode=0o600,
            label="synthetic record",
        )


def test_final_acceptance_rejects_exact_reread_marker_hash_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, context, bound_bytes = _final_acceptance_fixture(tmp_path)
    bound_bytes["supervisor success marker"] = runtime._canonical_json_bytes(  # pyright: ignore[reportPrivateUsage]
        {
            "schema_version": runner.SUPERVISOR_SUCCESS_SCHEMA_VERSION,
            "supervisor_success_sha256": "0" * 64,
        }
    )
    monkeypatch.setattr(
        runtime,
        "load_consumed_phase8b_permit",
        lambda *args, **kwargs: session.consumed,
    )
    monkeypatch.setattr(runtime.runner, "_resume_if_valid", lambda **kwargs: _provisional_result())
    monkeypatch.setattr(
        runtime,
        "_read_exact_file",
        lambda path, *, expected_mode, label: bound_bytes[label],
    )
    monkeypatch.setattr(
        runtime,
        "_exclusive_write",
        lambda *args, **kwargs: pytest.fail("final files must not be written"),
    )
    with pytest.raises(runtime.Phase8BRuntimeError, match="marker hash mismatch"):
        runtime._publish_final_acceptance(  # pyright: ignore[reportPrivateUsage]
            context,
            session=session,
        )


def test_final_acceptance_rejects_consistently_replaced_provisional_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, context, bound_bytes = _final_acceptance_fixture(tmp_path)
    monkeypatch.setattr(
        runtime,
        "load_consumed_phase8b_permit",
        lambda *args, **kwargs: session.consumed,
    )

    def mutate_pair_during_validation(**kwargs: object) -> SimpleNamespace:
        del kwargs
        replacement_success = b"replacement supervisor success\n"
        bound_bytes["supervisor success"] = replacement_success
        bound_bytes["supervisor success marker"] = runtime._canonical_json_bytes(  # pyright: ignore[reportPrivateUsage]
            {
                "schema_version": runner.SUPERVISOR_SUCCESS_SCHEMA_VERSION,
                "supervisor_success_sha256": _sha256(replacement_success),
            }
        )
        return _provisional_result()

    monkeypatch.setattr(runtime.runner, "_resume_if_valid", mutate_pair_during_validation)
    monkeypatch.setattr(
        runtime,
        "_read_exact_file",
        lambda path, *, expected_mode, label: bound_bytes[label],
    )
    monkeypatch.setattr(
        runtime,
        "_exclusive_write",
        lambda *args, **kwargs: pytest.fail("final files must not be written"),
    )
    with pytest.raises(runtime.Phase8BRuntimeError, match="snapshot changed"):
        runtime._publish_final_acceptance(  # pyright: ignore[reportPrivateUsage]
            context,
            session=session,
        )


def test_final_success_records_transport_inventory_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, context, bound_bytes = _final_acceptance_fixture(tmp_path)
    writes: dict[str, bytes] = {}
    monkeypatch.setattr(
        runtime,
        "load_consumed_phase8b_permit",
        lambda *args, **kwargs: session.consumed,
    )
    monkeypatch.setattr(runtime.runner, "_resume_if_valid", lambda **kwargs: _provisional_result())
    monkeypatch.setattr(
        runtime,
        "_read_exact_file",
        lambda path, *, expected_mode, label: bound_bytes[label],
    )

    def capture_write(path: Path, raw: bytes, *, mode: int) -> str:
        assert mode == 0o600
        writes[path.name] = raw
        return _sha256(raw)

    monkeypatch.setattr(runtime, "_exclusive_write", capture_write)
    runtime._publish_final_acceptance(  # pyright: ignore[reportPrivateUsage]
        context,
        session=session,
    )
    success = json.loads(writes["success.json"])
    assert success["transport_inventory_sha256"] == _TRANSPORT_SHA256
    assert success["guardian"]["compute_claim_sha256"] == context.compute_claim_sha256
    assert set(writes) == {"success.json", "_SUCCESS"}


def test_final_success_write_failure_never_creates_acceptance_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, context, bound_bytes = _final_acceptance_fixture(tmp_path)
    writes: list[Path] = []

    monkeypatch.setattr(
        runtime,
        "load_consumed_phase8b_permit",
        lambda *args, **kwargs: session.consumed,
    )
    monkeypatch.setattr(
        runtime.runner,
        "_resume_if_valid",
        lambda **kwargs: _provisional_result(),
    )
    monkeypatch.setattr(
        runtime,
        "_read_exact_file",
        lambda path, *, expected_mode, label: bound_bytes[label],
    )

    def fail_first_write(path: Path, raw: bytes, *, mode: int) -> str:
        del raw, mode
        writes.append(path)
        raise runtime.Phase8BRuntimeError("synthetic success write failure")

    monkeypatch.setattr(runtime, "_exclusive_write", fail_first_write)
    with pytest.raises(runtime.Phase8BRuntimeError, match="synthetic success write failure"):
        runtime._publish_final_acceptance(  # pyright: ignore[reportPrivateUsage]
            context,
            session=session,
        )
    assert writes == [session.consumed.permit.output_root / "success.json"]
    assert not (session.consumed.permit.output_root / "_SUCCESS").exists()


def test_final_acceptance_implementation_mentions_marker_only_after_success_write() -> None:
    source = ast.parse(Path(runtime.__file__).read_text(encoding="utf-8"))
    function = next(
        node
        for node in source.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == runtime._publish_final_acceptance.__name__  # pyright: ignore[reportPrivateUsage]
    )
    writes = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_exclusive_write"
    ]
    assert len(writes) == 2
    assert isinstance(writes[0].args[0], ast.Name)
    assert writes[0].args[0].id == "success_path"
    assert isinstance(writes[1].args[0], ast.Name)
    assert writes[1].args[0].id == "marker_path"
