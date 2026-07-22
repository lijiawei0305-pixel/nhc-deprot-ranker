from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from nhc_deprot_ranker.preparation import phase8b_preflight as preflight_module
from nhc_deprot_ranker.preparation.phase8b_preflight import (
    Phase8BPreflightError,
    phase8b_preflight_command,
    portable_phase8b_preflight,
    run_phase8b_preflight,
    validate_phase8b_preflight,
)
from nhc_deprot_ranker.preparation.phase8b_remote import load_phase8b_remote_config

INSPECTOR = Path(__file__).resolve().parents[1] / "scripts/phase8b_remote_preflight.py"


def _config(path: Path) -> Path:
    payload = {
        "schema_version": "phase8b_remote.v1",
        "connection": {
            "mode": "campus_direct",
            "ssh_alias": "synthetic-hpc",
            "proxy_host": "127.0.0.1",
            "proxy_port": 11080,
        },
        "remote": {
            "project_root": "/srv/project",
            "environment_relative": "env/envs/molenv.sh",
            "phase7_run_relative": "data/runs/nhc_deprot_ranker_phase7_smoke_fixture",
            "phase8b_run_relative": ("data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001"),
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
            "server_write_authorized": False,
            "quantum_execution_authorized": False,
            "consumed_private_permit_required": True,
            "scheduler_submission_authorized": False,
            "second_attempt_authorized": False,
        },
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    return path


def _payload() -> dict[str, object]:
    checks = {
        "phase7_exact_file_count": True,
        "phase7_tree_matches": True,
        "project_sources_match": True,
        "installed_sources_match": True,
        "function_sources_match": True,
        "versions_match": True,
        "nproc_sufficient": True,
        "load1_sufficient": True,
        "load5_sufficient": True,
        "memory_sufficient": True,
        "disk_sufficient": True,
        "taskset_available": True,
        "fixed_cpus_online": True,
        "target_absent": True,
        "no_conflicting_process": True,
        "phase7_unchanged": True,
        "project_sources_unchanged": True,
    }
    return {
        "schema_version": "phase8b.remote-preflight.v1",
        "status": "passed",
        "checks": checks,
        "versions": {
            "python": "3.11.15",
            "pyscf": "2.13.1",
            "geometric": "1.1.1",
            "pyscf_dispersion": "1.5.0",
        },
        "phase7": dict(preflight_module._EXPECTED_PHASE7),  # pyright: ignore[reportPrivateUsage]
        "project_source_sha256": dict(  # pyright: ignore[reportPrivateUsage]
            preflight_module._EXPECTED_PROJECT_SOURCE_SHA256
        ),
        "installed_source_sha256": dict(  # pyright: ignore[reportPrivateUsage]
            preflight_module._EXPECTED_INSTALLED_SOURCE_SHA256
        ),
        "function_source_sha256": dict(  # pyright: ignore[reportPrivateUsage]
            preflight_module._EXPECTED_FUNCTION_SOURCE_SHA256
        ),
        "resources": {
            "nproc": 112,
            "load1": 1.0,
            "load5": 2.0,
            "memory_available_kib": 64 * 1024 * 1024,
            "disk_available_bytes": 100 * 1024**3,
            "online_cpus": list(range(112)),
            "fixed_cpus": [0, 1, 2, 3],
        },
        "processes": {
            "current_uid_process_count": 10,
            "conflict_pids": [],
            "top_rss": [{"pid": 123, "rss_kib": 100, "cwd_under_project": False}],
        },
        "safety": {
            "read_only": True,
            "molecule_constructed": False,
            "kernel_called": False,
            "gradient_called": False,
            "dispersion_evaluated": False,
            "hessian_called": False,
            "target_created": False,
        },
    }


@dataclass
class _Completed:
    returncode: int
    stdout: bytes
    stderr: bytes = b""


def _canonical(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def test_phase8b_preflight_validates_and_sanitizes_ephemeral_processes() -> None:
    payload = _payload()
    assert validate_phase8b_preflight(payload) is payload
    portable = portable_phase8b_preflight(payload)
    assert portable["processes"] == {
        "current_uid_process_count": 10,
        "conflict_count": 0,
        "rss_snapshot_recorded": True,
    }


def test_phase8b_preflight_command_is_fixed_argv(tmp_path: Path) -> None:
    config = load_phase8b_remote_config(_config(tmp_path / "config.yaml"))
    assert phase8b_preflight_command(config) == (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ConnectTimeout=15",
        "synthetic-hpc",
        "bash",
        "-s",
    )


def test_phase8b_preflight_streams_one_read_only_wrapper(tmp_path: Path) -> None:
    config_path = _config(tmp_path / "config.yaml")
    seen: dict[str, object] = {}

    def fake_run(command: tuple[str, ...], **kwargs: object) -> _Completed:
        seen["command"] = command
        seen.update(kwargs)
        return _Completed(
            returncode=0,
            stdout=_canonical(_payload()),
        )

    result = run_phase8b_preflight(
        config_path=config_path,
        inspector_path=INSPECTOR,
        run_command=fake_run,
    )
    assert result["status"] == "passed"
    wrapper = seen["input"]
    assert isinstance(wrapper, bytes)
    assert b"PYTHONDONTWRITEBYTECODE=1" in wrapper
    assert b'source "$environment_relative"' in wrapper
    assert b"python -I -B -" in wrapper
    assert b"mkdir" not in wrapper
    assert b"rsync" not in wrapper


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("status", "failed"), "failed"),
        (("versions", {}), "versions"),
        (("safety", {}), "safety"),
    ],
)
def test_phase8b_preflight_rejects_failed_or_drifted_evidence(
    mutation: tuple[str, object], message: str
) -> None:
    payload = _payload()
    payload[mutation[0]] = mutation[1]
    with pytest.raises(Phase8BPreflightError, match=message):
        validate_phase8b_preflight(payload)


@pytest.mark.parametrize(
    ("section", "mutation", "message"),
    [
        ("checks", ("phase7_tree_matches", None), "checks"),
        ("checks", ("unexpected", True), "checks"),
        ("phase7", ("tree_sha256", "a" * 64), "Phase 7"),
        ("project_source_sha256", ("env/envs/molenv.sh", "b" * 64), "project source"),
        ("installed_source_sha256", ("pyscf.scf.hf", "c" * 64), "installed source"),
        ("function_source_sha256", ("geometric_kernel", "d" * 64), "function source"),
        ("resources", ("nproc", True), "CPU evidence"),
        ("resources", ("memory_available_kib", True), "CPU evidence"),
    ],
)
def test_phase8b_preflight_rejects_omitted_extra_or_fabricated_gate_fact(
    section: str,
    mutation: tuple[str, object | None],
    message: str,
) -> None:
    payload = _payload()
    target = payload[section]
    assert isinstance(target, dict)
    key, value = mutation
    if value is None:
        target.pop(key)
    else:
        target[key] = value
    with pytest.raises(Phase8BPreflightError, match=message):
        validate_phase8b_preflight(payload)


def test_phase8b_preflight_binds_the_reviewed_inspector_before_ssh(tmp_path: Path) -> None:
    config_path = _config(tmp_path / "config.yaml")
    replacement = tmp_path / "inspector.py"
    replacement.write_bytes(INSPECTOR.read_bytes())
    called = False

    def forbidden(command: tuple[str, ...], **kwargs: object) -> _Completed:
        nonlocal called
        del command, kwargs
        called = True
        raise AssertionError("SSH must not run for an alternate inspector path")

    with pytest.raises(Phase8BPreflightError, match="path drifted"):
        run_phase8b_preflight(
            config_path=config_path,
            inspector_path=replacement,
            run_command=forbidden,
        )
    assert called is False


def test_bound_inspector_rejects_same_path_byte_replacement(tmp_path: Path) -> None:
    replacement = tmp_path / "phase8b_remote_preflight.py"
    replacement.write_bytes(INSPECTOR.read_bytes())
    expected_hash = preflight_module._FROZEN_INSPECTOR_SHA256  # pyright: ignore[reportPrivateUsage]
    assert (
        preflight_module._read_bound_inspector(  # pyright: ignore[reportPrivateUsage]
            replacement,
            expected_path=replacement,
            expected_sha256=expected_hash,
        )
        == INSPECTOR.read_bytes()
    )
    replacement.write_text("print('replacement')\n", encoding="utf-8")
    with pytest.raises(Phase8BPreflightError, match="SHA256 drifted"):
        preflight_module._read_bound_inspector(  # pyright: ignore[reportPrivateUsage]
            replacement,
            expected_path=replacement,
            expected_sha256=expected_hash,
        )


def test_phase8b_preflight_rejects_nonzero_and_duplicate_json(tmp_path: Path) -> None:
    config_path = _config(tmp_path / "config.yaml")

    def nonzero(command: tuple[str, ...], **kwargs: object) -> _Completed:
        del command, kwargs
        return _Completed(
            returncode=2,
            stdout=_canonical(_payload()),
        )

    with pytest.raises(Phase8BPreflightError, match="nonzero"):
        run_phase8b_preflight(
            config_path=config_path,
            inspector_path=INSPECTOR,
            run_command=nonzero,
        )

    def duplicate(command: tuple[str, ...], **kwargs: object) -> _Completed:
        del command, kwargs
        return _Completed(returncode=0, stdout=b'{"x":1,"x":2}\n')

    with pytest.raises(Phase8BPreflightError, match="duplicate"):
        run_phase8b_preflight(
            config_path=config_path,
            inspector_path=INSPECTOR,
            run_command=duplicate,
        )
