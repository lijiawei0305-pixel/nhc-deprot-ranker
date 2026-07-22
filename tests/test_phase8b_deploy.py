from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from nhc_deprot_ranker.preparation import phase8b_bundle as bundle_module
from nhc_deprot_ranker.preparation import phase8b_deploy as deploy_module
from nhc_deprot_ranker.preparation.phase8b_deploy import (
    DEPLOY_EVIDENCE_SCHEMA_VERSION,
    Phase8BDeployError,
    deploy_phase8b_bundle,
    phase8b_deploy_command,
)
from nhc_deprot_ranker.preparation.phase8b_remote import (
    PHASE8B_RUN_RELATIVE,
    load_phase8b_remote_config,
)
from nhc_deprot_ranker.quantum.phase8b_permit import render_phase8b_permit


def _canonical(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _config(path: Path, *, project_root: Path, write_authorized: bool = True) -> Path:
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
            "server_write_authorized": write_authorized,
            "quantum_execution_authorized": False,
            "consumed_private_permit_required": True,
            "scheduler_submission_authorized": False,
            "second_attempt_authorized": False,
        },
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
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
    stdout: bytes
    stderr: bytes = b""


def _local_receiver(
    remote_root: Path,
) -> tuple[dict[str, object], Callable[..., _Completed]]:
    seen: dict[str, object] = {}

    def run(command: tuple[str, ...], **kwargs: object) -> _Completed:
        seen["command"] = command
        seen.update(kwargs)
        stream = kwargs["input"]
        assert isinstance(stream, bytes)
        inventory_sha = command[-1].rsplit(" ", maxsplit=1)[-1]
        completed = subprocess.run(
            (
                sys.executable,
                "-I",
                "-B",
                "-c",
                deploy_module._REMOTE_RECEIVER_SOURCE,  # pyright: ignore[reportPrivateUsage]
                remote_root.as_posix(),
                inventory_sha,
            ),
            input=stream,
            capture_output=True,
            timeout=30.0,
            check=False,
        )
        return _Completed(completed.returncode, completed.stdout, completed.stderr)

    return seen, run


def _tree(root: Path) -> dict[str, tuple[int, bytes]]:
    return {
        path.relative_to(root).as_posix(): (stat.S_IMODE(path.stat().st_mode), path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }


def test_command_is_one_fixed_ssh_argv_without_copy_or_execution_tools(tmp_path: Path) -> None:
    project = (tmp_path / "server-project").resolve()
    project.mkdir()
    config = load_phase8b_remote_config(_config(tmp_path / "config.yaml", project_root=project))
    command = phase8b_deploy_command(
        config,
        expected_transport_inventory_sha256="a" * 64,
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
    assert command[-1].startswith("exec python3 -I -B -c ")
    assert project.as_posix() in command[-1]
    forbidden = ("rsync", "scp", "sftp", "rm ", "rmtree", "pyscf", "geometric")
    assert not any(token in command[-1] for token in forbidden)


def test_directed_receiver_creates_exact_tree_and_rereads_canonical_evidence(
    tmp_path: Path,
) -> None:
    project = (tmp_path / "server-project").resolve()
    remote_parent = project / "data/runs"
    remote_parent.mkdir(parents=True)
    bundle = (tmp_path / "bundle").resolve()
    inventory_sha = _write_bundle(bundle, project_root=project)
    config = _config(tmp_path / "config.yaml", project_root=project)
    remote_root = project / PHASE8B_RUN_RELATIVE
    seen, runner = _local_receiver(remote_root)

    evidence = deploy_phase8b_bundle(
        config_path=config,
        bundle_dir=bundle,
        expected_transport_inventory_sha256=inventory_sha,
        run_command=runner,
    )

    assert evidence["schema_version"] == DEPLOY_EVIDENCE_SCHEMA_VERSION
    assert evidence["status"] == "deployed_and_revalidated"
    assert evidence["transport_inventory_sha256"] == inventory_sha
    assert evidence["safety"] == {
        "root_created": True,
        "exclusive_create_only": True,
        "nofollow_required": True,
        "overwrite_attempted": False,
        "delete_attempted": False,
        "cleanup_attempted": False,
        "chemistry_imported": False,
        "quantum_execution_started": False,
    }
    assert _tree(remote_root) == _tree(bundle)
    assert stat.S_IMODE(remote_root.stat().st_mode) == 0o700
    assert isinstance(seen["input"], bytes)
    assert len(seen["input"]) < deploy_module._MAX_TRANSFER_BYTES


def test_existing_remote_root_is_never_overwritten_deleted_or_retried(tmp_path: Path) -> None:
    project = (tmp_path / "server-project").resolve()
    (project / "data/runs").mkdir(parents=True)
    bundle = (tmp_path / "bundle").resolve()
    inventory_sha = _write_bundle(bundle, project_root=project)
    config = _config(tmp_path / "config.yaml", project_root=project)
    remote_root = project / PHASE8B_RUN_RELATIVE
    _, runner = _local_receiver(remote_root)
    deploy_phase8b_bundle(
        config_path=config,
        bundle_dir=bundle,
        expected_transport_inventory_sha256=inventory_sha,
        run_command=runner,
    )
    before = _tree(remote_root)
    calls = 0

    def counted(command: tuple[str, ...], **kwargs: object) -> _Completed:
        nonlocal calls
        calls += 1
        return runner(command, **kwargs)

    with pytest.raises(Phase8BDeployError, match="already exists"):
        deploy_phase8b_bundle(
            config_path=config,
            bundle_dir=bundle,
            expected_transport_inventory_sha256=inventory_sha,
            run_command=counted,
        )
    assert calls == 1
    assert _tree(remote_root) == before


def test_closed_write_gate_and_local_hash_drift_stop_before_ssh(tmp_path: Path) -> None:
    project = (tmp_path / "server-project").resolve()
    (project / "data/runs").mkdir(parents=True)
    bundle = (tmp_path / "bundle").resolve()
    inventory_sha = _write_bundle(bundle, project_root=project)
    calls = 0

    def forbidden(command: tuple[str, ...], **kwargs: object) -> _Completed:
        nonlocal calls
        del command, kwargs
        calls += 1
        raise AssertionError("SSH must not be opened")

    with pytest.raises(ValueError, match="server write"):
        deploy_phase8b_bundle(
            config_path=_config(
                tmp_path / "closed.yaml",
                project_root=project,
                write_authorized=False,
            ),
            bundle_dir=bundle,
            expected_transport_inventory_sha256=inventory_sha,
            run_command=forbidden,
        )
    with pytest.raises(Phase8BDeployError, match="bundle validation failed"):
        deploy_phase8b_bundle(
            config_path=_config(tmp_path / "open.yaml", project_root=project),
            bundle_dir=bundle,
            expected_transport_inventory_sha256="f" * 64,
            run_command=forbidden,
        )
    assert calls == 0


def test_receiver_rejects_trailing_bytes_and_preserves_partial_root(tmp_path: Path) -> None:
    project = (tmp_path / "server-project").resolve()
    (project / "data/runs").mkdir(parents=True)
    bundle = (tmp_path / "bundle").resolve()
    inventory_sha = _write_bundle(bundle, project_root=project)
    config = load_phase8b_remote_config(_config(tmp_path / "config.yaml", project_root=project))
    plan = deploy_module._build_plan(  # pyright: ignore[reportPrivateUsage]
        config=config,
        bundle_dir=bundle,
        expected_transport_inventory_sha256=inventory_sha,
    )
    remote_root = project / PHASE8B_RUN_RELATIVE
    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            "-B",
            "-c",
            deploy_module._REMOTE_RECEIVER_SOURCE,  # pyright: ignore[reportPrivateUsage]
            remote_root.as_posix(),
            inventory_sha,
        ),
        input=plan.stream + b"unexpected",
        capture_output=True,
        timeout=30.0,
        check=False,
    )
    assert completed.returncode != 0
    assert b"trailing bytes" in completed.stderr
    assert remote_root.is_dir()
    assert _tree(remote_root) == _tree(bundle)


def test_noncanonical_or_oversized_remote_evidence_is_rejected(tmp_path: Path) -> None:
    project = (tmp_path / "server-project").resolve()
    (project / "data/runs").mkdir(parents=True)
    bundle = (tmp_path / "bundle").resolve()
    inventory_sha = _write_bundle(bundle, project_root=project)
    config = _config(tmp_path / "config.yaml", project_root=project)

    def noncanonical(command: tuple[str, ...], **kwargs: object) -> _Completed:
        del command, kwargs
        return _Completed(0, _canonical({"status": "invented"}))

    with pytest.raises(Phase8BDeployError, match="differs"):
        deploy_phase8b_bundle(
            config_path=config,
            bundle_dir=bundle,
            expected_transport_inventory_sha256=inventory_sha,
            run_command=noncanonical,
        )

    def oversized(command: tuple[str, ...], **kwargs: object) -> _Completed:
        del command, kwargs
        return _Completed(0, b"x" * (deploy_module._MAX_STDOUT_BYTES + 1))

    with pytest.raises(Phase8BDeployError, match="stdout exceeded"):
        deploy_phase8b_bundle(
            config_path=config,
            bundle_dir=bundle,
            expected_transport_inventory_sha256=inventory_sha,
            run_command=oversized,
        )


def test_deploy_source_has_no_quantum_launch_or_chemistry_dependency() -> None:
    source = Path(deploy_module.__file__).read_text(encoding="utf-8")
    assert "run_phase8b_supervisor" not in source
    assert "consume_phase8b_permit" not in source
    assert "import pyscf" not in source
    assert "import geometric" not in source
    assert "os.unlink" not in source
    assert "os.remove" not in source
    assert "shutil.rmtree" not in source
    assert 'quantum_execution_started": False' in source


def test_default_bounded_runner_transfers_stdin_and_caps_stdout() -> None:
    completed = deploy_module._bounded_run(  # pyright: ignore[reportPrivateUsage]
        (
            sys.executable,
            "-c",
            "import sys; raw=sys.stdin.buffer.read(); sys.stdout.buffer.write(raw[::-1])",
        ),
        input=b"directed",
        timeout=5.0,
    )
    assert completed.returncode == 0
    assert completed.stdout == b"detcerid"
    assert completed.stderr == b""

    with pytest.raises(Phase8BDeployError, match="stdout exceeded"):
        deploy_module._bounded_run(  # pyright: ignore[reportPrivateUsage]
            (
                sys.executable,
                "-c",
                f"import sys; sys.stdout.buffer.write(b'x'*{deploy_module._MAX_STDOUT_BYTES + 1})",
            ),
            input=b"",
            timeout=5.0,
        )
