"""No-chemistry tests for the one-shot Phase 8B private permit."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from nhc_deprot_ranker.quantum import phase8b_permit as permit_module
from nhc_deprot_ranker.quantum.phase8b_permit import (
    FROZEN_ATTEMPT_ID,
    FROZEN_CONSUMED_RELATIVE,
    FROZEN_INCHIKEY,
    FROZEN_READY_RELATIVE,
    FROZEN_REQUEST_ID,
    FROZEN_RESOURCES,
    ConsumedPhase8BPermit,
    Phase8BPermitConsumedError,
    Phase8BPermitError,
    Phase8BPermitValidationError,
    consume_phase8b_permit,
    load_consumed_phase8b_permit,
    render_phase8b_permit,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class _Fixture:
    project_root: Path
    run_root: Path
    ready_path: Path
    consumed_path: Path
    request_sha256: str
    runner_source_sha256: str
    payload_manifest_sha256: str
    permit_sha256: str

    def consume(self) -> ConsumedPhase8BPermit:
        return consume_phase8b_permit(
            self.ready_path,
            expected_permit_sha256=self.permit_sha256,
            expected_request_sha256=self.request_sha256,
            expected_runner_source_sha256=self.runner_source_sha256,
            expected_payload_manifest_sha256=self.payload_manifest_sha256,
        )

    def load_consumed(
        self,
        *,
        expected_permit_sha256: str | None = None,
    ) -> ConsumedPhase8BPermit:
        return load_consumed_phase8b_permit(
            self.consumed_path,
            expected_permit_sha256=expected_permit_sha256 or self.permit_sha256,
            expected_request_sha256=self.request_sha256,
            expected_runner_source_sha256=self.runner_source_sha256,
            expected_payload_manifest_sha256=self.payload_manifest_sha256,
        )


def _write_public(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(0o640)
    return _sha256(payload)


def _make_fixture(tmp_path: Path) -> _Fixture:
    project_root = (tmp_path / "project").resolve()
    run_root = project_root / permit_module.FROZEN_RUN_RELATIVE
    run_root.mkdir(parents=True)
    run_root.chmod(0o700)
    (run_root / "private").mkdir(mode=0o700)
    (run_root / "runtime").mkdir(mode=0o750)

    request_sha256 = _write_public(run_root / "input/request.json", b'{"request": "fixed"}\n')
    payload_manifest_sha256 = _write_public(
        run_root / "payload_manifest.json", b'{"payload": "fixed"}\n'
    )
    runner_source_sha256 = "a" * 64
    permit_bytes = render_phase8b_permit(
        project_root=project_root.as_posix(),
        request_sha256=request_sha256,
        runner_source_sha256=runner_source_sha256,
        payload_manifest_sha256=payload_manifest_sha256,
    )
    ready_path = run_root / FROZEN_READY_RELATIVE
    ready_path.write_bytes(permit_bytes)
    ready_path.chmod(0o600)
    return _Fixture(
        project_root=project_root,
        run_root=run_root,
        ready_path=ready_path,
        consumed_path=run_root / FROZEN_CONSUMED_RELATIVE,
        request_sha256=request_sha256,
        runner_source_sha256=runner_source_sha256,
        payload_manifest_sha256=payload_manifest_sha256,
        permit_sha256=_sha256(permit_bytes),
    )


def _replace_permit(fixture: _Fixture, payload: dict[str, object]) -> _Fixture:
    raw = (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode()
    fixture.ready_path.write_bytes(raw)
    fixture.ready_path.chmod(0o600)
    return replace(fixture, permit_sha256=_sha256(raw))


def test_render_is_deterministic_and_binds_exact_scope(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    first = fixture.ready_path.read_bytes()
    second = render_phase8b_permit(
        project_root=fixture.project_root.as_posix(),
        request_sha256=fixture.request_sha256,
        runner_source_sha256=fixture.runner_source_sha256,
        payload_manifest_sha256=fixture.payload_manifest_sha256,
    )
    assert first == second
    payload = json.loads(first)
    assert payload["identity"]["inchikey"] == FROZEN_INCHIKEY
    assert payload["identity"]["request_id"] == FROZEN_REQUEST_ID
    assert payload["identity"]["attempt_id"] == FROZEN_ATTEMPT_ID
    assert payload["identity"]["endpoint_order"] == ["cation", "neutral"]
    assert payload["resources"] == FROZEN_RESOURCES
    assert payload["authorization"] == {
        "candidate_replacement_authorized": False,
        "one_shot": True,
        "quantum_execution_authorized": True,
        "resume_authorized": False,
        "second_attempt_authorized": False,
        "server_write_authorized": True,
    }
    assert "created_at" not in first.decode()


def test_consume_preserves_bytes_and_removes_ready(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    original = fixture.ready_path.read_bytes()
    result = fixture.consume()
    assert result.consumed_path == fixture.consumed_path
    assert result.consumed_sha256 == fixture.permit_sha256
    assert result.permit.raw_bytes == original
    assert result.permit.runner_source_sha256 == fixture.runner_source_sha256
    assert not fixture.ready_path.exists()
    assert fixture.consumed_path.read_bytes() == original
    assert fixture.consumed_path.stat().st_mode & 0o777 == 0o400
    assert fixture.consumed_path.stat().st_nlink == 1


def test_consumed_permit_can_be_loaded_repeatedly_after_output_creation(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)
    consumed = fixture.consume()
    consumed.permit.output_root.mkdir(mode=0o750)

    first = fixture.load_consumed()
    second = fixture.load_consumed()

    assert first == second == consumed
    assert first.permit.output_root.is_dir()
    assert not fixture.ready_path.exists()
    assert fixture.consumed_path.read_bytes() == consumed.permit.raw_bytes


def test_consumed_loader_rejects_reappeared_ready_permit(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    original = fixture.ready_path.read_bytes()
    fixture.consume()
    fixture.ready_path.write_bytes(original)
    fixture.ready_path.chmod(0o600)

    with pytest.raises(Phase8BPermitValidationError, match="ready permit must be absent"):
        fixture.load_consumed()

    assert fixture.ready_path.read_bytes() == original
    assert fixture.consumed_path.is_file()


def test_consumed_loader_requires_canonical_exact_bytes_and_hash(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    fixture.consume()
    payload = json.loads(fixture.consumed_path.read_bytes())
    noncanonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    fixture.consumed_path.chmod(0o600)
    fixture.consumed_path.write_bytes(noncanonical)
    fixture.consumed_path.chmod(0o400)

    with pytest.raises(Phase8BPermitValidationError, match="canonical"):
        fixture.load_consumed(expected_permit_sha256=_sha256(noncanonical))
    with pytest.raises(Phase8BPermitValidationError):
        fixture.load_consumed()


def test_consumed_loader_revalidates_exact_identity_and_bound_files(tmp_path: Path) -> None:
    identity_fixture = _make_fixture(tmp_path / "identity")
    identity_fixture.consume()
    payload = json.loads(identity_fixture.consumed_path.read_bytes())
    payload["identity"]["attempt_id"] = "attempt-phase8b-qxh-v002"
    mutated = (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode()
    identity_fixture.consumed_path.chmod(0o600)
    identity_fixture.consumed_path.write_bytes(mutated)
    identity_fixture.consumed_path.chmod(0o400)
    with pytest.raises(Phase8BPermitValidationError, match="identity"):
        identity_fixture.load_consumed(expected_permit_sha256=_sha256(mutated))

    request_fixture = _make_fixture(tmp_path / "request")
    request_fixture.consume()
    request_path = request_fixture.run_root / "input/request.json"
    request_path.write_bytes(request_path.read_bytes() + b"drift\n")
    request_path.chmod(0o640)
    with pytest.raises(Phase8BPermitValidationError, match="request SHA256 drifted"):
        request_fixture.load_consumed()


def test_consumed_symlink_wrong_mode_hardlink_and_owner_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    symlink_fixture = _make_fixture(tmp_path / "symlink")
    symlink_result = symlink_fixture.consume()
    outside = tmp_path / "outside-consumed.json"
    outside.write_bytes(symlink_result.permit.raw_bytes)
    outside.chmod(0o400)
    symlink_fixture.consumed_path.unlink()
    symlink_fixture.consumed_path.symlink_to(outside)
    with pytest.raises(Phase8BPermitValidationError, match="opened safely"):
        symlink_fixture.load_consumed()

    mode_fixture = _make_fixture(tmp_path / "mode")
    mode_fixture.consume()
    mode_fixture.consumed_path.chmod(0o600)
    with pytest.raises(Phase8BPermitValidationError, match="mode"):
        mode_fixture.load_consumed()

    link_fixture = _make_fixture(tmp_path / "hardlink")
    link_fixture.consume()
    os.link(link_fixture.consumed_path, link_fixture.consumed_path.with_name("permit.copy.json"))
    with pytest.raises(Phase8BPermitValidationError, match="hard link"):
        link_fixture.load_consumed()

    owner_fixture = _make_fixture(tmp_path / "owner")
    owner_fixture.consume()
    monkeypatch.setattr(permit_module.os, "geteuid", lambda: os.getuid() + 1)
    with pytest.raises(Phase8BPermitValidationError, match="owned"):
        owner_fixture.load_consumed()


def test_second_call_and_spawn_failure_cannot_reuse_permit(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    consumed = fixture.consume()

    def synthetic_spawn_failure() -> None:
        assert consumed is not None
        raise RuntimeError("synthetic spawn failure after permit consumption")

    with pytest.raises(RuntimeError, match="spawn failure"):
        synthetic_spawn_failure()
    with pytest.raises(Phase8BPermitConsumedError, match="already consumed"):
        fixture.consume()
    assert not fixture.ready_path.exists()
    assert fixture.consumed_path.is_file()


def test_two_concurrent_consumers_have_exactly_one_winner(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)

    def attempt() -> str:
        try:
            fixture.consume()
        except Phase8BPermitError:
            return "rejected"
        return "consumed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(lambda _index: attempt(), range(2)))
    assert outcomes == ["consumed", "rejected"]
    assert not fixture.ready_path.exists()
    assert fixture.consumed_path.is_file()


def test_copied_bundle_is_rejected_before_consumption(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path / "original")
    copied_project = (tmp_path / "copy/project").resolve()
    copied_run = copied_project / permit_module.FROZEN_RUN_RELATIVE
    copied_run.parent.mkdir(parents=True)
    shutil.copytree(fixture.run_root, copied_run)
    copied_run.chmod(0o700)
    (copied_run / "private").chmod(0o700)
    copied_ready = copied_run / FROZEN_READY_RELATIVE

    with pytest.raises(Phase8BPermitValidationError, match="copied"):
        consume_phase8b_permit(
            copied_ready,
            expected_permit_sha256=fixture.permit_sha256,
            expected_request_sha256=fixture.request_sha256,
            expected_runner_source_sha256=fixture.runner_source_sha256,
            expected_payload_manifest_sha256=fixture.payload_manifest_sha256,
        )
    assert copied_ready.is_file()
    assert not (copied_run / FROZEN_CONSUMED_RELATIVE).exists()


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("identity", "inchikey", "IJWCXRPLHNQISE-UHFFFAOYSA-N", "identity"),
        ("identity", "request_id", "phase8b-other", "identity"),
        ("identity", "attempt_id", "attempt-phase8b-other", "identity"),
        ("identity", "endpoint_order", ["neutral", "cation"], "identity"),
        ("resources", "computational_threads", 5, "resources"),
        ("resources", "hard_wall_timeout_seconds", 7_201, "resources"),
        ("authorization", "second_attempt_authorized", True, "authorization"),
        ("authorization", "resume_authorized", True, "authorization"),
    ],
)
def test_exact_identity_resource_and_authorization_drift_is_rejected(
    tmp_path: Path,
    section: str,
    field: str,
    value: object,
    message: str,
) -> None:
    fixture = _make_fixture(tmp_path)
    payload = json.loads(fixture.ready_path.read_text())
    payload[section][field] = value
    fixture = _replace_permit(fixture, payload)
    with pytest.raises(Phase8BPermitValidationError, match=message):
        fixture.consume()
    assert fixture.ready_path.is_file()
    assert not fixture.consumed_path.exists()


@pytest.mark.parametrize(
    "expected_field",
    [
        "expected_permit_sha256",
        "expected_request_sha256",
        "expected_runner_source_sha256",
        "expected_payload_manifest_sha256",
    ],
)
def test_external_hash_binding_drift_is_rejected(tmp_path: Path, expected_field: str) -> None:
    fixture = _make_fixture(tmp_path)
    arguments = {
        "expected_permit_sha256": fixture.permit_sha256,
        "expected_request_sha256": fixture.request_sha256,
        "expected_runner_source_sha256": fixture.runner_source_sha256,
        "expected_payload_manifest_sha256": fixture.payload_manifest_sha256,
    }
    arguments[expected_field] = "f" * 64
    with pytest.raises(Phase8BPermitValidationError):
        consume_phase8b_permit(fixture.ready_path, **arguments)
    assert fixture.ready_path.is_file()
    assert not fixture.consumed_path.exists()


def test_bound_request_or_manifest_byte_drift_is_rejected(tmp_path: Path) -> None:
    for relative in ("input/request.json", "payload_manifest.json"):
        fixture = _make_fixture(tmp_path / relative.replace("/", "-"))
        path = fixture.run_root / relative
        path.write_bytes(path.read_bytes() + b"drift\n")
        path.chmod(0o640)
        with pytest.raises(Phase8BPermitValidationError, match="SHA256 drifted"):
            fixture.consume()
        assert fixture.ready_path.is_file()
        assert not fixture.consumed_path.exists()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b'{"schema_version": "a", "schema_version": "b"}\n', "duplicate"),
        (b'{"schema_version": NaN}\n', "non-finite"),
        (b'{"schema_version": Infinity}\n', "non-finite"),
    ],
)
def test_duplicate_and_nonfinite_json_are_rejected(
    tmp_path: Path, raw: bytes, message: str
) -> None:
    fixture = _make_fixture(tmp_path)
    fixture.ready_path.write_bytes(raw)
    fixture.ready_path.chmod(0o600)
    with pytest.raises(Phase8BPermitValidationError, match=message):
        consume_phase8b_permit(
            fixture.ready_path,
            expected_permit_sha256=_sha256(raw),
            expected_request_sha256=fixture.request_sha256,
            expected_runner_source_sha256=fixture.runner_source_sha256,
            expected_payload_manifest_sha256=fixture.payload_manifest_sha256,
        )
    assert not fixture.consumed_path.exists()


def test_ready_symlink_wrong_mode_hardlink_and_owner_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    symlink_fixture = _make_fixture(tmp_path / "symlink")
    outside = tmp_path / "outside-permit.json"
    outside.write_bytes(symlink_fixture.ready_path.read_bytes())
    outside.chmod(0o600)
    symlink_fixture.ready_path.unlink()
    symlink_fixture.ready_path.symlink_to(outside)
    with pytest.raises(Phase8BPermitValidationError, match="opened safely"):
        symlink_fixture.consume()

    mode_fixture = _make_fixture(tmp_path / "mode")
    mode_fixture.ready_path.chmod(0o640)
    with pytest.raises(Phase8BPermitValidationError, match="mode"):
        mode_fixture.consume()

    link_fixture = _make_fixture(tmp_path / "hardlink")
    os.link(link_fixture.ready_path, link_fixture.ready_path.with_name("permit.copy.json"))
    with pytest.raises(Phase8BPermitValidationError, match="hard link"):
        link_fixture.consume()

    owner_fixture = _make_fixture(tmp_path / "owner")
    monkeypatch.setattr(permit_module.os, "geteuid", lambda: os.getuid() + 1)
    with pytest.raises(Phase8BPermitValidationError, match="owned"):
        owner_fixture.consume()


def test_preexisting_consumed_state_is_fail_closed(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    fixture.consumed_path.write_bytes(fixture.ready_path.read_bytes())
    fixture.consumed_path.chmod(0o400)
    with pytest.raises(Phase8BPermitConsumedError, match="already consumed"):
        fixture.consume()
    assert fixture.ready_path.is_file()
    assert fixture.consumed_path.is_file()


def test_unlink_failure_after_linearization_stays_consumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _make_fixture(tmp_path)
    real_unlink = permit_module.os.unlink

    def fail_ready_unlink(path: str, *, dir_fd: int | None = None) -> None:
        if path == Path(FROZEN_READY_RELATIVE).name:
            raise OSError("synthetic unlink failure")
        real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(permit_module.os, "unlink", fail_ready_unlink)
    with pytest.raises(OSError, match="synthetic unlink failure"):
        fixture.consume()
    assert fixture.ready_path.is_file()
    assert fixture.consumed_path.is_file()
    with pytest.raises(Phase8BPermitConsumedError, match="already consumed"):
        fixture.consume()
