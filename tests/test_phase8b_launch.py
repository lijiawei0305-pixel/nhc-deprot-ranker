from __future__ import annotations

import ast
import hashlib
import inspect
import json
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from nhc_deprot_ranker.preparation import phase8b_bundle as bundle_module
from nhc_deprot_ranker.preparation import phase8b_launch as launch_module
from nhc_deprot_ranker.preparation.phase8b_launch import (
    LAUNCH_INVOCATION_SCHEMA_VERSION,
    LAUNCH_OUTCOME_SCHEMA_VERSION,
    Phase8BLaunchError,
    _launch_phase8b_smoke,
    launch_phase8b_smoke,
    phase8b_launch_command,
)
from nhc_deprot_ranker.preparation.phase8b_remote import (
    PHASE8B_RUN_RELATIVE,
    load_phase8b_remote_config,
)
from nhc_deprot_ranker.quantum import two_endpoint as runner
from nhc_deprot_ranker.quantum.phase8b_permit import render_phase8b_permit


def _canonical(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _config(path: Path, *, project_root: Path) -> Path:
    payload = {
        "schema_version": "phase8b_remote.v1",
        "connection": {
            "mode": "campus_direct",
            "ssh_alias": "synthetic-hpc",
            "proxy_host": "127.0.0.1",
            "proxy_port": 11080,
        },
        "remote": {
            "project_root": project_root.as_posix(),
            "environment_relative": "env/envs/molenv.sh",
            "phase7_run_relative": "data/runs/nhc_deprot_ranker_phase7_smoke_fixture",
            "phase8b_run_relative": PHASE8B_RUN_RELATIVE,
            "require_new_phase8b_root": True,
        },
        "transfer": {
            "directed_files_only": True,
            "recursive_copy": False,
            "delete": False,
            "overwrite": False,
        },
        "safety": {
            "read_only_preflight_authorized": True,
            "server_write_authorized": True,
            "quantum_execution_authorized": False,
            "consumed_private_permit_required": True,
            "scheduler_submission_authorized": False,
            "second_attempt_authorized": False,
        },
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)
    return path


def _write_bundle(root: Path, *, project_root: Path) -> str:
    request_raw = _canonical({"synthetic": "request"})
    payload_files = {"input/request.json": request_raw}
    payload_modes = {"input/request.json": 0o640}
    directory_modes = bundle_module._directory_modes_for_files(  # pyright: ignore[reportPrivateUsage]
        (
            *payload_files,
            "payload_manifest.json",
            "private/permit.ready.json",
            "transport_inventory.json",
        )
    )
    payload = {
        "schema_version": bundle_module.PAYLOAD_MANIFEST_SCHEMA_VERSION,
        "bundle_version": bundle_module.BUNDLE_VERSION,
        "identity": {
            "request_sha256": _sha256(request_raw),
            "runner_source_sha256": "a" * 64,
        },
        "resources": {},
        "source_relative_paths": [],
        "artifact_sha256": {},
        "files": bundle_module._file_entries(  # pyright: ignore[reportPrivateUsage]
            payload_files, payload_modes
        ),
        "payload_tree_sha256": bundle_module._tree_sha256(  # pyright: ignore[reportPrivateUsage]
            payload_files, payload_modes
        ),
        "directories": bundle_module._directory_entries(  # pyright: ignore[reportPrivateUsage]
            directory_modes
        ),
        "directory_tree_sha256": bundle_module._directory_tree_sha256(  # pyright: ignore[reportPrivateUsage]
            directory_modes
        ),
        "excluded_from_manifest": [
            "payload_manifest.json",
            "private/permit.ready.json",
            "transport_inventory.json",
        ],
    }
    payload_raw = _canonical(payload)
    permit_raw = render_phase8b_permit(
        project_root=project_root.as_posix(),
        request_sha256=_sha256(request_raw),
        runner_source_sha256="a" * 64,
        payload_manifest_sha256=_sha256(payload_raw),
    )
    transfer_files = {
        **payload_files,
        "payload_manifest.json": payload_raw,
        "private/permit.ready.json": permit_raw,
    }
    transfer_modes = {
        "input/request.json": 0o640,
        "payload_manifest.json": 0o640,
        "private/permit.ready.json": 0o600,
    }
    inventory = {
        "schema_version": bundle_module.TRANSPORT_INVENTORY_SCHEMA_VERSION,
        "bundle_version": bundle_module.BUNDLE_VERSION,
        "payload_manifest_sha256": _sha256(payload_raw),
        "permit_sha256": _sha256(permit_raw),
        "files": bundle_module._file_entries(  # pyright: ignore[reportPrivateUsage]
            transfer_files, transfer_modes
        ),
        "transport_tree_sha256": bundle_module._tree_sha256(  # pyright: ignore[reportPrivateUsage]
            transfer_files, transfer_modes
        ),
        "directories": bundle_module._directory_entries(  # pyright: ignore[reportPrivateUsage]
            directory_modes
        ),
        "directory_tree_sha256": bundle_module._directory_tree_sha256(  # pyright: ignore[reportPrivateUsage]
            directory_modes
        ),
        "excluded_from_inventory": ["transport_inventory.json"],
    }
    inventory_raw = _canonical(inventory)
    all_files = {**transfer_files, "transport_inventory.json": inventory_raw}
    all_modes = {**transfer_modes, "transport_inventory.json": 0o640}
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    for name, mode in sorted(
        directory_modes.items(),
        key=lambda item: (len(Path(item[0]).parts), item[0]),
    ):
        if name == ".":
            continue
        directory = root / name
        directory.mkdir()
        directory.chmod(mode)
    for name, raw in all_files.items():
        path = root / name
        path.write_bytes(raw)
        path.chmod(all_modes[name])
    return _sha256(inventory_raw)


@dataclass
class _Completed:
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""


def _fixture(tmp_path: Path) -> tuple[Path, Path, str, Path, Path]:
    project = (tmp_path / "project").resolve()
    project.mkdir()
    config = _config((tmp_path / "phase8b.yaml").resolve(), project_root=project)
    bundle = (tmp_path / "bundle").resolve()
    inventory_sha256 = _write_bundle(bundle, project_root=project)
    private = (tmp_path / "private").resolve()
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    return (
        config,
        bundle,
        inventory_sha256,
        private / "launch.invocation.json",
        private / "launch.outcome.json",
    )


def _launch(
    fixture: tuple[Path, Path, str, Path, Path],
    *,
    run_command: object,
    source_gate_authorized: bool = True,
) -> dict[str, object]:
    config, bundle, inventory_sha256, invocation, outcome = fixture
    with (
        patch.object(runner, "EXECUTION_AUTHORIZED", source_gate_authorized),
        patch.object(launch_module, "_PRODUCTION_AUTHORIZATION_CONSUMED", False),
    ):
        return _launch_phase8b_smoke(
            config_path=config,
            bundle_dir=bundle,
            expected_transport_inventory_sha256=inventory_sha256,
            invocation_path=invocation,
            outcome_path=outcome,
            runner_source_sha256="a" * 64,
            require_production_identity=False,
            thread_environment=runner.THREAD_ENVIRONMENT,
            timeout_seconds=30.0,
            create_private_directory=False,
            clock_ns=lambda: 123,
            run_command=run_command,  # type: ignore[arg-type]
        )


def test_launch_command_is_one_fixed_detached_ssh_argv(tmp_path: Path) -> None:
    project = (tmp_path / "project").resolve()
    project.mkdir()
    config = load_phase8b_remote_config(_config(tmp_path / "config.yaml", project_root=project))
    command, remote_hash, script_hash = phase8b_launch_command(
        config,
        expected_transport_inventory_sha256="a" * 64,
        thread_environment=runner.THREAD_ENVIRONMENT,
    )
    assert command[:7] == (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ConnectTimeout=15",
    )
    assert command[-2] == "synthetic-hpc"
    remote = command[-1]
    assert 'source "$environment_relative"' in remote
    assert "setsid -f taskset -c 0-3 python -I -B" in remote
    assert "</dev/null >/dev/null 2>&1" in remote
    assert "~/.bashrc" not in remote
    assert not any(token in remote for token in ("sbatch", "qsub", "nohup", " &", "rsync"))
    assert len(remote_hash) == len(script_hash) == 64
    for name, value in runner.THREAD_ENVIRONMENT.items():
        assert f"export {name}={value}" in remote


def test_production_launch_has_no_command_injection_and_one_popen_site() -> None:
    assert "run_command" not in inspect.signature(launch_phase8b_smoke).parameters
    assert "source_gate_authorized" not in inspect.signature(_launch_phase8b_smoke).parameters
    source_path = Path(inspect.getsourcefile(launch_phase8b_smoke) or "")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    popen_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr == "Popen"
    ]
    assert len(popen_calls) == 1


def test_private_launch_cannot_use_real_ssh_outside_fixed_production_route(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    config, bundle, inventory_sha256, invocation, outcome = fixture
    with (
        patch.object(runner, "EXECUTION_AUTHORIZED", True),
        patch.object(launch_module, "_PRODUCTION_AUTHORIZATION_CONSUMED", False),
        pytest.raises(Phase8BLaunchError, match="fixed production route"),
    ):
        _launch_phase8b_smoke(
            config_path=config,
            bundle_dir=bundle,
            expected_transport_inventory_sha256=inventory_sha256,
            invocation_path=invocation,
            outcome_path=outcome,
            runner_source_sha256="a" * 64,
            require_production_identity=False,
            thread_environment=runner.THREAD_ENVIRONMENT,
            timeout_seconds=30.0,
            create_private_directory=False,
            run_command=None,
        )
    assert not invocation.exists()
    assert not outcome.exists()


def test_consumed_launch_authority_cannot_be_reopened_by_gate_patch(tmp_path: Path) -> None:
    with (
        patch.object(runner, "EXECUTION_AUTHORIZED", True),
        pytest.raises(Phase8BLaunchError, match="has been consumed"),
    ):
        launch_phase8b_smoke(
            config_path=tmp_path / "missing-config.yaml",
            bundle_dir=tmp_path / "missing-bundle",
            expected_transport_inventory_sha256="a" * 64,
        )


def test_consumed_latch_blocks_private_launch_seam_before_runner_or_records(
    tmp_path: Path,
) -> None:
    invocation = tmp_path / "launch.invocation.json"
    outcome = tmp_path / "launch.outcome.json"
    runner_called = False

    def forbidden_runner(*args: object, **kwargs: object) -> _Completed:
        nonlocal runner_called
        del args, kwargs
        runner_called = True
        raise AssertionError("launch runner must remain unreachable")

    with (
        patch.object(runner, "EXECUTION_AUTHORIZED", True),
        pytest.raises(Phase8BLaunchError, match="has been consumed"),
    ):
        _launch_phase8b_smoke(
            config_path=tmp_path / "missing-config.yaml",
            bundle_dir=tmp_path / "missing-bundle",
            expected_transport_inventory_sha256="unreachable",
            invocation_path=invocation,
            outcome_path=outcome,
            runner_source_sha256="unreachable",
            require_production_identity=False,
            thread_environment={},
            timeout_seconds=-1.0,
            create_private_directory=False,
            run_command=forbidden_runner,
        )
    assert runner_called is False
    assert not invocation.exists()
    assert not outcome.exists()


def test_closed_source_gate_rejects_before_record_or_ssh(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    called = False

    def forbidden(*args: object, **kwargs: object) -> _Completed:
        nonlocal called
        del args, kwargs
        called = True
        raise AssertionError("SSH must remain closed")

    with pytest.raises(Phase8BLaunchError, match="source execution gate is closed"):
        _launch(fixture, run_command=forbidden, source_gate_authorized=False)
    assert called is False
    assert not fixture[3].exists()
    assert not fixture[4].exists()


def test_success_commits_private_records_before_exactly_one_ssh(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    calls = 0

    def success(command: tuple[str, ...], **kwargs: object) -> _Completed:
        nonlocal calls
        calls += 1
        assert fixture[3].is_file()
        assert not fixture[4].exists()
        assert kwargs == {"timeout": 30.0}
        assert command[0] == "ssh"
        return _Completed(0)

    evidence = _launch(fixture, run_command=success)
    assert calls == 1
    assert evidence["status"] == "ssh_returned_zero"
    assert evidence["retry_authorized"] is False
    assert stat.S_IMODE(fixture[3].stat().st_mode) == 0o600
    assert stat.S_IMODE(fixture[4].stat().st_mode) == 0o600
    invocation = json.loads(fixture[3].read_text(encoding="utf-8"))
    outcome = json.loads(fixture[4].read_text(encoding="utf-8"))
    assert invocation["schema_version"] == LAUNCH_INVOCATION_SCHEMA_VERSION
    assert invocation["retry_authorized"] is False
    assert outcome["schema_version"] == LAUNCH_OUTCOME_SCHEMA_VERSION
    assert outcome["status"] == "ssh_returned_zero"


def test_second_call_is_rejected_without_second_ssh(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    calls = 0

    def success(*args: object, **kwargs: object) -> _Completed:
        nonlocal calls
        del args, kwargs
        calls += 1
        return _Completed(0)

    _launch(fixture, run_command=success)
    with pytest.raises(Phase8BLaunchError, match="cannot be retried"):
        _launch(fixture, run_command=success)
    assert calls == 1


def test_failed_ssh_writes_terminal_outcome_and_permanently_blocks_retry(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    calls = 0

    def failed(*args: object, **kwargs: object) -> _Completed:
        nonlocal calls
        del args, kwargs
        calls += 1
        return _Completed(255, stderr=b"synthetic network failure")

    with pytest.raises(Phase8BLaunchError, match="did not return"):
        _launch(fixture, run_command=failed)
    outcome = json.loads(fixture[4].read_text(encoding="utf-8"))
    assert outcome["status"] == "ssh_call_failed"
    assert outcome["retry_authorized"] is False
    with pytest.raises(Phase8BLaunchError, match="cannot be retried"):
        _launch(fixture, run_command=failed)
    assert calls == 1


def test_concurrent_calls_linearize_to_one_ssh_invocation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    calls = 0

    def success(*args: object, **kwargs: object) -> _Completed:
        nonlocal calls
        del args, kwargs
        with lock:
            calls += 1
        entered.set()
        assert release.wait(timeout=5.0)
        return _Completed(0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_launch, fixture, run_command=success)
        assert entered.wait(timeout=5.0)
        second = pool.submit(_launch, fixture, run_command=success)
        with pytest.raises(Phase8BLaunchError, match="cannot be retried"):
            second.result(timeout=5.0)
        release.set()
        assert first.result(timeout=5.0)["status"] == "ssh_returned_zero"
    assert calls == 1


def test_bundle_or_private_config_drift_rejects_before_invocation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture[0].chmod(0o644)
    called = False

    def forbidden(*args: object, **kwargs: object) -> _Completed:
        nonlocal called
        del args, kwargs
        called = True
        raise AssertionError("SSH must not run")

    with pytest.raises(Phase8BLaunchError, match="config identity or mode"):
        _launch(fixture, run_command=forbidden)
    assert called is False
    assert not fixture[3].exists()
