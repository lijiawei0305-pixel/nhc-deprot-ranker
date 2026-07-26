"""The consumed Phase 8B routes must stay retired.

These regressions are local and no-chemistry.  They prove that the three
server-facing Phase 8B routes fail closed before doing any input-dependent
work, and that a stale private ``server_write_authorized`` bit cannot revive
them.  They do not connect to a server, construct a molecule, or run a kernel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, NoReturn
from unittest.mock import patch

import pytest
import yaml

from nhc_deprot_ranker.preparation import phase8b_bundle as bundle_module
from nhc_deprot_ranker.preparation import phase8b_deploy as deploy_module
from nhc_deprot_ranker.preparation import phase8b_launch as launch_module
from nhc_deprot_ranker.preparation.phase8b_deploy import (
    Phase8BDeployError,
    deploy_phase8b_bundle,
)
from nhc_deprot_ranker.preparation.phase8b_remote import PHASE8B_RUN_RELATIVE
from nhc_deprot_ranker.quantum import two_endpoint as runner

_RETIRED_ROUTES: Final = (bundle_module, deploy_module, launch_module)


def _stale_authorized_config(path: Path, *, project_root: Path) -> Path:
    """Write a private config whose write bit is still stale-true after the incident."""

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
    return path


def test_every_retired_phase8b_route_holds_the_consumed_latch() -> None:
    """No single-module edit may reopen the retired authority chain."""

    for module in _RETIRED_ROUTES:
        assert module._PRODUCTION_AUTHORIZATION_CONSUMED is True, module.__name__


def test_checked_in_source_execution_gate_is_closed() -> None:
    """The gate must be false in checked-in source, not only at runtime."""

    assert runner.EXECUTION_AUTHORIZED is False
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "EXECUTION_AUTHORIZED: Final[bool] = False" in source
    assert "EXECUTION_AUTHORIZED: Final[bool] = True" not in source


def test_stale_private_write_bit_cannot_revive_deployment(tmp_path: Path) -> None:
    """A stale-true server_write_authorized bit is residue, never authorization."""

    project = (tmp_path / "server-project").resolve()
    (project / "data/runs").mkdir(parents=True)
    config = _stale_authorized_config(tmp_path / "stale.yaml", project_root=project)
    calls = 0

    def forbidden(command: tuple[str, ...], **kwargs: object) -> NoReturn:
        nonlocal calls
        del command, kwargs
        calls += 1
        raise AssertionError("SSH must not be opened by a retired route")

    with (
        patch.object(runner, "EXECUTION_AUTHORIZED", True),
        pytest.raises(Phase8BDeployError, match="has been consumed"),
    ):
        deploy_phase8b_bundle(
            config_path=config,
            bundle_dir=tmp_path / "bundle",
            expected_transport_inventory_sha256="0" * 64,
            run_command=forbidden,
        )
    assert calls == 0
    assert not (project / PHASE8B_RUN_RELATIVE).exists()


def test_deployment_latch_rejects_before_reading_any_input(tmp_path: Path) -> None:
    """The refusal must not depend on a readable config, bundle, or inventory."""

    calls = 0

    def forbidden(command: tuple[str, ...], **kwargs: object) -> NoReturn:
        nonlocal calls
        del command, kwargs
        calls += 1
        raise AssertionError("SSH must not be opened by a retired route")

    with (
        patch.object(runner, "EXECUTION_AUTHORIZED", True),
        pytest.raises(Phase8BDeployError, match="has been consumed"),
    ):
        deploy_phase8b_bundle(
            config_path=tmp_path / "absent.yaml",
            bundle_dir=tmp_path / "absent-bundle",
            expected_transport_inventory_sha256="not-a-sha256",
            run_command=forbidden,
        )
    assert calls == 0


def test_closed_source_gate_is_reported_before_the_consumed_latch(tmp_path: Path) -> None:
    """A closed gate must read as a closed gate, not as a consumed authorization."""

    with pytest.raises(Phase8BDeployError, match="source execution gate is closed"):
        deploy_phase8b_bundle(
            config_path=tmp_path / "absent.yaml",
            bundle_dir=tmp_path / "absent-bundle",
            expected_transport_inventory_sha256="0" * 64,
        )


def test_deployment_latch_survives_an_out_of_range_timeout(tmp_path: Path) -> None:
    """An invalid argument must not preempt the retirement refusal."""

    with (
        patch.object(runner, "EXECUTION_AUTHORIZED", True),
        pytest.raises(Phase8BDeployError, match="has been consumed"),
    ):
        deploy_phase8b_bundle(
            config_path=tmp_path / "absent.yaml",
            bundle_dir=tmp_path / "absent-bundle",
            expected_transport_inventory_sha256="0" * 64,
            timeout_seconds=99_999.0,
        )
