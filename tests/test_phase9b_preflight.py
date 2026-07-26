"""Phase 9B preflight regressions.

No chemistry, no server, no compute. The command runner is injected, so nothing
here opens SSH. Every gate is driven to failure individually.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from nhc_deprot_ranker.preparation import phase9b_preflight as pf
from nhc_deprot_ranker.preparation.phase9b_preflight import (
    Phase9BPreflightError,
    Phase9BPreflightNotAuthorizedError,
    build_preflight_command,
    evaluate_preflight,
    run_preflight,
)

_MEM = 64 * 1024 * 1024
_DISK = 50 * 1024 * 1024 * 1024


def _payload(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": pf.PREFLIGHT_SCHEMA_VERSION,
        "torch_version": pf.EXPECTED_TORCH_VERSION,
        "torch_sm70": True,
        "ase_version": pf.EXPECTED_ASE_VERSION,
        "aimnet_version": pf.EXPECTED_AIMNET_VERSION,
        "weight_sha256": pf.EXPECTED_WEIGHT_SHA256,
        "weight_bytes": pf.EXPECTED_WEIGHT_BYTES,
        "pyscf_version": "2.13.1",
        "geometric_version": "1.1.1",
        "dispersion_version": "1.5.0",
        "free_gpu_indices": [2, 0, 5],
        "memory_available_kib": _MEM,
        "disk_available_bytes": _DISK,
        "direct_root_absent": True,
        "assisted_root_absent": True,
        "wrote_nothing": True,
    }
    base.update(kw)
    return base


class _FakeRunner:
    """Typed stand-in for the SSH runner; records every invocation."""

    def __init__(
        self, payload: dict[str, Any] | None = None, *, code: int = 0, err: bytes = b""
    ) -> None:
        self.payload = payload
        self.code = code
        self.err = err
        self.calls: list[Sequence[str]] = []

    def __call__(self, command: Sequence[str], *, timeout: float) -> tuple[int, bytes, bytes]:
        del timeout
        self.calls.append(command)
        body = json.dumps(self.payload if self.payload is not None else _payload(), sort_keys=True)
        return self.code, body.encode(), self.err


def _runner(
    payload: dict[str, Any] | None = None, *, code: int = 0, err: bytes = b""
) -> _FakeRunner:
    return _FakeRunner(payload, code=code, err=err)


def test_source_gate_is_closed_and_a_real_run_refuses() -> None:
    assert pf.EXECUTION_AUTHORIZED is False
    source = Path(pf.__file__).read_text(encoding="utf-8")
    assert "EXECUTION_AUTHORIZED: Final[bool] = False" in source
    with pytest.raises(Phase9BPreflightNotAuthorizedError, match="read-only authorization"):
        run_preflight(ssh_alias="host", project_root="/srv/project")


def test_command_is_one_bounded_batchmode_ssh_invocation() -> None:
    command = build_preflight_command(ssh_alias="host", project_root="/srv/project")
    assert command[0] == "ssh"
    assert "BatchMode=yes" in command
    assert "IdentitiesOnly=yes" in command
    assert command[-2] == "host"
    remote = command[-1]
    assert "python3 -I -B -c" in remote
    assert "PYTHONDONTWRITEBYTECODE=1" in remote
    assert "HF_HUB_OFFLINE=1" in remote


def test_command_contains_no_write_or_compute_verb() -> None:
    remote = build_preflight_command(ssh_alias="host", project_root="/srv/project")[-1]
    for forbidden in (
        "mkdir",
        "rsync",
        "scp",
        " rm ",
        "--delete",
        "sbatch",
        "nohup",
        "setsid",
        "kernel(",
        "optimize(",
    ):
        assert forbidden not in remote, forbidden


def test_remote_inspector_never_writes_or_loads_a_model() -> None:
    source = pf.REMOTE_INSPECTOR_SOURCE
    for forbidden in ("mkdir", 'open(weight, "w"', "AIMNet2ASE", "AIMNet2Calculator", "gto.M"):
        assert forbidden not in source, forbidden
    assert 'open(weight, "rb")' in source, "the weight is read, never written"


def test_bad_alias_or_relative_root_fails_closed() -> None:
    with pytest.raises(Phase9BPreflightError, match="ssh alias and an absolute"):
        build_preflight_command(ssh_alias="", project_root="/srv")
    with pytest.raises(Phase9BPreflightError, match="ssh alias and an absolute"):
        build_preflight_command(ssh_alias="host", project_root="relative/path")


def test_a_passing_payload_yields_a_result() -> None:
    result = evaluate_preflight(_payload())
    assert result.wrote_nothing is True
    assert result.free_gpu_count == 3
    assert result.selected_gpu_index == 0, "lowest free index, chosen deterministically"


def test_missing_or_extra_keys_fail_closed() -> None:
    short = _payload()
    del short["torch_sm70"]
    with pytest.raises(Phase9BPreflightError, match="missing keys"):
        evaluate_preflight(short)
    wide = _payload(surprise=1)
    with pytest.raises(Phase9BPreflightError, match="unexpected keys"):
        evaluate_preflight(wide)


def test_schema_drift_fails_closed() -> None:
    with pytest.raises(Phase9BPreflightError, match="schema version drifted"):
        evaluate_preflight(_payload(schema_version="phase9b.readonly_preflight.v0"))


def test_unproven_write_freedom_fails_closed() -> None:
    with pytest.raises(Phase9BPreflightError, match="wrote nothing"):
        evaluate_preflight(_payload(wrote_nothing=False))


@pytest.mark.parametrize(
    "key",
    [
        "torch_version",
        "ase_version",
        "aimnet_version",
        "pyscf_version",
        "geometric_version",
        "dispersion_version",
    ],
)
def test_each_version_drift_fails_closed(key: str) -> None:
    with pytest.raises(Phase9BPreflightError, match=f"{key} drifted"):
        evaluate_preflight(_payload(**{key: "9.9.9"}))


def test_losing_volta_support_fails_closed() -> None:
    """torch 2.11+ dropped sm_70; upgrading past it would strand the V100 stack."""

    with pytest.raises(Phase9BPreflightError, match="Volta"):
        evaluate_preflight(_payload(torch_sm70=False))


def test_weight_drift_fails_closed() -> None:
    with pytest.raises(Phase9BPreflightError, match="weight SHA256 drifted"):
        evaluate_preflight(_payload(weight_sha256="f" * 64))
    with pytest.raises(Phase9BPreflightError, match="weight byte size drifted"):
        evaluate_preflight(_payload(weight_bytes=1))


def test_an_absent_weight_fails_closed() -> None:
    """The inspector reports None rather than inventing a hash."""

    with pytest.raises(Phase9BPreflightError, match="weight SHA256 drifted"):
        evaluate_preflight(_payload(weight_sha256=None, weight_bytes=0))


def test_either_existing_route_root_fails_closed() -> None:
    with pytest.raises(Phase9BPreflightError, match="direct route root already exists"):
        evaluate_preflight(_payload(direct_root_absent=False))
    with pytest.raises(Phase9BPreflightError, match="assisted route root already exists"):
        evaluate_preflight(_payload(assisted_root_absent=False))


def test_no_free_gpu_fails_closed_rather_than_waiting() -> None:
    with pytest.raises(Phase9BPreflightError, match="no free GPU"):
        evaluate_preflight(_payload(free_gpu_indices=[]))


def test_malformed_gpu_list_fails_closed() -> None:
    with pytest.raises(Phase9BPreflightError, match="malformed"):
        evaluate_preflight(_payload(free_gpu_indices="0,1"))
    with pytest.raises(Phase9BPreflightError, match="malformed"):
        evaluate_preflight(_payload(free_gpu_indices=[0, "1"]))


def test_resource_floors_are_enforced() -> None:
    with pytest.raises(Phase9BPreflightError, match="memory is below"):
        evaluate_preflight(_payload(memory_available_kib=1024))
    with pytest.raises(Phase9BPreflightError, match="disk is below"):
        evaluate_preflight(_payload(disk_available_bytes=1024))


def test_gpu_requirement_comes_from_the_frozen_stage_budget() -> None:
    from nhc_deprot_ranker.quantum.phase9b_resources import AIMNET2_STAGE_BUDGET

    assert AIMNET2_STAGE_BUDGET["gpu_count"] == 1
    evaluate_preflight(_payload(free_gpu_indices=[7]))


def test_injected_runner_drives_the_whole_path() -> None:
    runner = _runner()
    result = run_preflight(ssh_alias="host", project_root="/srv/project", run_command=runner)
    assert result.selected_gpu_index == 0
    assert len(runner.calls) == 1, "exactly one bounded invocation"


def test_nonzero_exit_and_unexpected_stderr_fail_closed() -> None:
    with pytest.raises(Phase9BPreflightError, match="exited nonzero"):
        run_preflight(ssh_alias="host", project_root="/srv/project", run_command=_runner(code=3))
    with pytest.raises(Phase9BPreflightError, match="unexpected stderr"):
        run_preflight(
            ssh_alias="host", project_root="/srv/project", run_command=_runner(err=b"warn")
        )


def test_noncanonical_stdout_fails_closed() -> None:
    def duplicate(command: Sequence[str], *, timeout: float) -> tuple[int, bytes, bytes]:
        del command, timeout
        return 0, b'{"schema_version": "a", "schema_version": "b"}', b""

    with pytest.raises(Phase9BPreflightError, match="duplicate preflight key"):
        run_preflight(ssh_alias="host", project_root="/srv/project", run_command=duplicate)

    def not_json(command: Sequence[str], *, timeout: float) -> tuple[int, bytes, bytes]:
        del command, timeout
        return 0, b"not json", b""

    with pytest.raises(Phase9BPreflightError, match="not strict JSON"):
        run_preflight(ssh_alias="host", project_root="/srv/project", run_command=not_json)

    def empty(command: Sequence[str], *, timeout: float) -> tuple[int, bytes, bytes]:
        del command, timeout
        return 0, b"", b""

    with pytest.raises(Phase9BPreflightError, match="stdout size is invalid"):
        run_preflight(ssh_alias="host", project_root="/srv/project", run_command=empty)


def test_out_of_range_timeout_is_rejected() -> None:
    with pytest.raises(ValueError, match="timeout must be in"):
        run_preflight(
            ssh_alias="host",
            project_root="/srv/project",
            run_command=_runner(),
            timeout_seconds=9_999.0,
        )


def test_module_declares_no_label_and_imports_no_chemistry() -> None:
    """Parse real imports rather than scanning text.

    REMOTE_INSPECTOR_SOURCE legitimately contains "import torch" as the *remote*
    script's body, so a substring scan would flag the string literal that exists
    precisely to keep those imports on the far side of the SSH boundary.
    """

    import ast

    tree = ast.parse(Path(pf.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for forbidden in ("pyscf", "torch", "aimnet", "ase", "rdkit"):
        assert forbidden not in imported, forbidden

    source = Path(pf.__file__).read_text(encoding="utf-8").lower()
    for forbidden in ("627.509474", "dft_deprot", "kcal"):
        assert forbidden not in source, forbidden


def test_the_only_model_imports_live_in_the_remote_script_string() -> None:
    """Those imports must happen on the server, never in this process."""

    assert "import torch" in pf.REMOTE_INSPECTOR_SOURCE
    assert 'importlib.import_module("aimnet")' not in pf.REMOTE_INSPECTOR_SOURCE
    assert 'ver("aimnet")' in pf.REMOTE_INSPECTOR_SOURCE


def test_module_is_outside_the_runner_source_closure() -> None:
    from nhc_deprot_ranker.quantum import two_endpoint

    closure = two_endpoint._RUNNER_SOURCE_RELATIVE_PATHS  # pyright: ignore[reportPrivateUsage]
    assert not any("phase9b_preflight" in member for member in closure)
