from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from nhc_deprot_ranker.preparation.phase8b_remote import (
    PHASE8B_RUN_RELATIVE,
    Phase8BRemoteConfigError,
    load_phase8b_remote_config,
)


def _payload() -> dict[str, object]:
    return {
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


def _write(path: Path, payload: object) -> Path:
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    return path


def test_phase8b_route_is_fixed_and_cannot_authorize_quantum(tmp_path: Path) -> None:
    path = _write(tmp_path / "phase8b.yaml", _payload())
    config = load_phase8b_remote_config(path)
    assert config.remote.phase8b_run_relative == PHASE8B_RUN_RELATIVE
    assert config.remote.phase8b_root == f"/srv/project/{PHASE8B_RUN_RELATIVE}"
    assert config.safety.quantum_execution_authorized is False
    config.require_read_only_preflight()
    config.require_directed_write()
    assert "ProxyCommand" not in " ".join(config.ssh_options())


def test_phase8b_proxy_is_loopback_only(tmp_path: Path) -> None:
    payload = _payload()
    connection = payload["connection"]
    assert isinstance(connection, dict)
    connection["mode"] = "socks5_proxy"
    path = _write(tmp_path / "phase8b.yaml", payload)
    options = load_phase8b_remote_config(path).ssh_options()
    assert "ProxyCommand=nc -x 127.0.0.1:11080 -X 5 %h %p" in options


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("remote", "project_root", "/"),
        ("remote", "project_root", "/srv/../escape"),
        ("remote", "environment_relative", "env/envs/xtb.sh"),
        ("remote", "phase7_run_relative", "data/runs/not-phase7"),
        ("remote", "phase8b_run_relative", "data/runs/phase8b-v002"),
        ("remote", "require_new_phase8b_root", False),
        ("transfer", "directed_files_only", False),
        ("transfer", "recursive_copy", True),
        ("transfer", "delete", True),
        ("transfer", "overwrite", True),
        ("safety", "quantum_execution_authorized", True),
        ("safety", "consumed_private_permit_required", False),
        ("safety", "scheduler_submission_authorized", True),
        ("safety", "second_attempt_authorized", True),
    ],
)
def test_phase8b_route_rejects_scope_expansion(
    tmp_path: Path, section: str, field: str, value: object
) -> None:
    payload = _payload()
    nested = payload[section]
    assert isinstance(nested, dict)
    nested[field] = value
    path = _write(tmp_path / "phase8b.yaml", payload)
    with pytest.raises(ValidationError):
        load_phase8b_remote_config(path)


def test_phase8b_write_bit_is_separate_from_preflight(tmp_path: Path) -> None:
    payload = _payload()
    safety = payload["safety"]
    assert isinstance(safety, dict)
    safety["server_write_authorized"] = False
    config = load_phase8b_remote_config(_write(tmp_path / "phase8b.yaml", payload))
    config.require_read_only_preflight()
    with pytest.raises(Phase8BRemoteConfigError, match="server write"):
        config.require_directed_write()


def test_phase8b_route_rejects_symlink_scalar_and_unknown_field(tmp_path: Path) -> None:
    target = _write(tmp_path / "target.yaml", _payload())
    link = tmp_path / "link.yaml"
    link.symlink_to(target)
    with pytest.raises(FileNotFoundError):
        load_phase8b_remote_config(link)

    scalar = _write(tmp_path / "scalar.yaml", "not-a-mapping")
    with pytest.raises(Phase8BRemoteConfigError, match="mapping"):
        load_phase8b_remote_config(scalar)

    payload = _payload()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        load_phase8b_remote_config(_write(tmp_path / "extra.yaml", payload))
