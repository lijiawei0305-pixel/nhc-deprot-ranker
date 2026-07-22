"""Private Phase 7 route and server-write policy tests."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from nhc_deprot_ranker.preparation.remote_config import (
    Phase7RemoteConfigError,
    load_phase7_remote_config,
)


def test_example_is_safe_and_not_write_authorized() -> None:
    config = load_phase7_remote_config(Path("configs/phase7.example.yaml"))
    assert config.remote.run_root.endswith(
        "/data/runs/nhc_deprot_ranker_phase7_smoke_v001_20260722"
    )
    assert config.transfer.delete is False
    assert config.dft_execution_authorized is False
    with pytest.raises(Phase7RemoteConfigError, match="not authorized"):
        config.require_geometry_write_authorization()


def test_proxy_route_is_rendered_without_credentials(tmp_path: Path) -> None:
    raw = yaml.safe_load(Path("configs/phase7.example.yaml").read_text(encoding="utf-8"))
    raw["connection"]["mode"] = "socks5_proxy"
    raw["server_write_authorized"] = True
    path = tmp_path / "phase7.local.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    config = load_phase7_remote_config(path)
    config.require_geometry_write_authorization()
    options = config.ssh_options()
    assert any("ProxyCommand=nc -x 127.0.0.1:11080" in value for value in options)
    assert not any("password" in value.lower() for value in options)


@pytest.mark.parametrize(
    "run_relative",
    [
        "../data/runs/nhc_deprot_ranker_phase7_smoke_v001_20260722",
        "/data/runs/nhc_deprot_ranker_phase7_smoke_v001_20260722",
        "data/runs/unscoped",
        "data/runs/nhc_deprot_ranker_phase7_smoke_v001/extra",
    ],
)
def test_unsafe_or_unscoped_remote_root_is_rejected(tmp_path: Path, run_relative: str) -> None:
    raw = yaml.safe_load(Path("configs/phase7.example.yaml").read_text(encoding="utf-8"))
    raw["remote"]["run_relative"] = run_relative
    path = tmp_path / "phase7.local.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_phase7_remote_config(path)


def test_delete_cannot_be_enabled(tmp_path: Path) -> None:
    raw = yaml.safe_load(Path("configs/phase7.example.yaml").read_text(encoding="utf-8"))
    raw["transfer"]["delete"] = True
    path = tmp_path / "phase7.local.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_phase7_remote_config(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_root", "/path/to/hpc project"),
        ("project_root", "/path/to/$(touch-x)"),
        ("project_root", "/path/to/hpc;touch-x"),
        ("project_root", "/path/to/hpc\nnext"),
        ("run_relative", "data/runs/nhc_deprot_ranker_phase7_smoke_v001;touch-x"),
        ("run_relative", "data/runs/nhc_deprot_ranker_phase7_smoke_v001 next"),
    ],
)
def test_remote_paths_reject_shell_metacharacters(tmp_path: Path, field: str, value: str) -> None:
    raw = yaml.safe_load(Path("configs/phase7.example.yaml").read_text(encoding="utf-8"))
    raw["remote"][field] = value
    path = tmp_path / "phase7.local.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValidationError, match="unsafe path component"):
        load_phase7_remote_config(path)
