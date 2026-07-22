"""Phase 8A private route and immutable read-only policy tests."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from nhc_deprot_ranker.preparation.phase8a_preflight import (
    Phase8APreflightConfigError,
    load_phase8a_preflight_config,
    run_phase8a_preflight,
    validate_phase8a_evidence,
)


def _example() -> dict[str, object]:
    raw = yaml.safe_load(Path("configs/phase8a.example.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def test_example_is_strictly_read_only_and_campus_direct() -> None:
    config = load_phase8a_preflight_config(Path("configs/phase8a.example.yaml"))
    assert config.connection.mode == "campus_direct"
    assert config.remote.environment_relative == "env/envs/molenv.sh"
    assert config.safety.api_preflight_authorized is True
    assert config.safety.server_write_authorized is False
    assert config.safety.quantum_execution_authorized is False
    assert "BatchMode=yes" in config.ssh_options()


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("safety", "server_write_authorized", True),
        ("safety", "quantum_execution_authorized", True),
        ("safety", "read_only", False),
        ("safety", "api_preflight_authorized", False),
        ("remote", "environment_relative", "env/envs/xtb.sh"),
        ("remote", "project_root", "/path/with space/project"),
        ("remote", "phase7_run_relative", "data/runs/not-phase7"),
    ],
)
def test_unsafe_authority_environment_or_path_is_rejected(
    tmp_path: Path, section: str, field: str, value: object
) -> None:
    raw = _example()
    nested = raw[section]
    assert isinstance(nested, dict)
    nested[field] = value
    path = tmp_path / "phase8a.local.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_phase8a_preflight_config(path)


def test_proxy_route_is_loopback_only_and_fixed(tmp_path: Path) -> None:
    raw = _example()
    connection = raw["connection"]
    assert isinstance(connection, dict)
    connection["mode"] = "socks5_proxy"
    path = tmp_path / "phase8a.local.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    config = load_phase8a_preflight_config(path)
    assert any("ProxyCommand=nc -x 127.0.0.1:11080" in item for item in config.ssh_options())

    connection["proxy_host"] = "198.18.0.1"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_phase8a_preflight_config(path)


def _passing_evidence() -> dict[str, object]:
    payload = json.loads(Path("docs/PHASE8A_API_PREFLIGHT_V001.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_evidence_validation_rejects_failed_checks_and_private_coordinates() -> None:
    payload = _passing_evidence()
    validate_phase8a_evidence(payload, private_values=("private-alias",))
    acceptance = payload["acceptance"]
    assert isinstance(acceptance, dict)
    acceptance["checks"] = {"all": False}
    with pytest.raises(Phase8APreflightConfigError, match="check"):
        validate_phase8a_evidence(payload)
    passing_acceptance = _passing_evidence()["acceptance"]
    assert isinstance(passing_acceptance, dict)
    acceptance["checks"] = passing_acceptance["checks"]
    payload["generated_at_utc"] = "not-a-timestamp"
    with pytest.raises(Phase8APreflightConfigError, match="generated_at"):
        validate_phase8a_evidence(payload)

    payload = _passing_evidence()
    versions = payload["versions"]
    assert isinstance(versions, dict)
    versions["python"] = "private-alias"
    with pytest.raises(Phase8APreflightConfigError, match="private"):
        validate_phase8a_evidence(payload, private_values=("private-alias",))

    payload = _passing_evidence()
    acceptance = payload["acceptance"]
    assert isinstance(acceptance, dict)
    acceptance["extra"] = True
    with pytest.raises(Phase8APreflightConfigError, match="acceptance"):
        validate_phase8a_evidence(payload)

    payload = _passing_evidence()
    imports = payload["imports"]
    assert isinstance(imports, dict)
    imports["pyscf"] = False
    with pytest.raises(Phase8APreflightConfigError, match="import"):
        validate_phase8a_evidence(payload)

    payload = _passing_evidence()
    integrity = payload["phase7_integrity"]
    assert isinstance(integrity, dict)
    integrity["before_after_match"] = False
    with pytest.raises(Phase8APreflightConfigError, match="integrity"):
        validate_phase8a_evidence(payload)

    for section, message in (
        ("geometric", "geomeTRIC"),
        ("scf", "SCF"),
        ("dispersion", "dispersion"),
    ):
        payload = _passing_evidence()
        payload[section] = {}
        with pytest.raises(Phase8APreflightConfigError, match=message):
            validate_phase8a_evidence(payload)


def test_launcher_uses_argv_streaming_and_never_writes_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _example()
    config_path = tmp_path / "phase8a.local.yaml"
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    inspector = tmp_path / "inspector.py"
    inspector.write_text("print('placeholder')\n", encoding="utf-8")
    evidence = _passing_evidence()
    observed: dict[str, object] = {}

    def fake_run(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        observed["argv"] = argv
        observed.update(kwargs)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=(json.dumps(evidence, sort_keys=True) + "\n").encode(),
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_phase8a_preflight(config_path=config_path, inspector_path=inspector)
    assert result == evidence
    argv = observed["argv"]
    assert isinstance(argv, tuple)
    assert argv[0] == "ssh"
    assert "bash" in argv and "-s" in argv
    assert observed["check"] is False
    streamed = observed["input"]
    assert isinstance(streamed, bytes)
    assert b"PYTHONDONTWRITEBYTECODE=1" in streamed
    assert b"python -B -" in streamed
    assert b"mkdir" not in streamed
    assert b"> /" not in streamed


def test_launcher_reports_only_portable_failed_check_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _example()
    config_path = tmp_path / "phase8a.local.yaml"
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    inspector = tmp_path / "inspector.py"
    inspector.write_text("print('placeholder')\n", encoding="utf-8")
    evidence = _passing_evidence()
    evidence["status"] = "failed"
    acceptance = evidence["acceptance"]
    assert isinstance(acceptance, dict)
    acceptance["checks"] = {"safe_static_check": False}
    acceptance["passed"] = False

    def fake_run(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        del kwargs
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout=(json.dumps(evidence, sort_keys=True) + "\n").encode(),
            stderr=b"private remote traceback is never surfaced",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(Phase8APreflightConfigError, match="safe_static_check"):
        run_phase8a_preflight(config_path=config_path, inspector_path=inspector)


def test_checked_in_preflight_evidence_is_portable_and_fully_accepted() -> None:
    payload = json.loads(Path("docs/PHASE8A_API_PREFLIGHT_V001.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    validate_phase8a_evidence(payload)
    acceptance = payload["acceptance"]
    assert isinstance(acceptance, dict)
    checks = acceptance["checks"]
    assert isinstance(checks, dict)
    assert len(checks) == 18
    integrity = payload["phase7_integrity"]
    assert isinstance(integrity, dict)
    assert integrity["registered_file_count"] == 27
    assert integrity["before_after_match"] is True
