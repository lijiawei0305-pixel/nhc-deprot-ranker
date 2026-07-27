"""No-chemistry qualification tests for Phase 9B-U3 protected metrology."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nhc_deprot_ranker.preparation import phase9b_u3_metrology as u3

_SHA_A = "a" * 64
_SHA_B = "b" * 64


def _snapshot(*, object_id: str = "project_mlff") -> u3.ProtectedObjectSnapshotV2:
    return u3.ProtectedObjectSnapshotV2(
        object_id=object_id,
        state="present",
        object_kind="conda_environment",
        python_identity={
            "executable_sha256": _SHA_A,
            "executable_bytes": 123,
            "version": "3.11.15",
            "implementation": "CPython",
        },
        conda_history_sha256=_SHA_A,
        conda_explicit_sha256=_SHA_A,
        pip_freeze_sha256=_SHA_A,
        critical_distribution_identities=(
            {
                "distribution": "torch",
                "state": "present",
                "version": "2.8.0",
                "metadata_sha256": _SHA_A,
                "record_sha256": _SHA_A,
            },
        ),
        filesystem_entry_count=5,
        regular_file_count=3,
        regular_file_bytes=456,
        tree_digest=_SHA_A,
        mtime_summary_digest=_SHA_A,
    )


def _mapping(**updates: object) -> dict[str, object]:
    payload = _snapshot().to_mapping()
    payload.update(updates)
    return payload


def test_u2_missing_state_is_diagnosed_as_schema_asymmetry() -> None:
    before = _mapping()
    before.pop("state")
    after = _mapping()
    comparison = u3.diagnose_snapshot_pair(before, after)
    assert comparison.passed is False
    assert comparison.failure_code == u3.SCHEMA_ASYMMETRY
    assert comparison.failure_assertion == (
        "protected_before_snapshot_keys == protected_after_snapshot_keys"
    )


def test_present_before_and_after_have_equal_stable_projection() -> None:
    before = _mapping(state="present")
    after = _mapping(state="present")
    comparison = u3.diagnose_snapshot_pair(before, after)
    assert comparison.passed is True
    assert comparison.schema_keyset_equal is True
    assert comparison.projection_keyset_equal is True
    assert comparison.projection_bytes_equal is True
    assert comparison.projection_sha256_equal is True


def test_observation_phase_does_not_enter_projection() -> None:
    snapshot = _snapshot()
    before = u3.build_observation_receipt(
        snapshot,
        observation_phase="protected_before",
        attempt_id="attempt-u3",
        observed_at_ns=1,
        observer_pid=10,
    )
    after = u3.build_observation_receipt(
        snapshot,
        observation_phase="protected_after",
        attempt_id="attempt-u3",
        observed_at_ns=1,
        observer_pid=10,
    )
    assert before.to_mapping() != after.to_mapping()
    assert u3.compare_observations(before, after).passed is True


def test_observation_timestamp_does_not_enter_projection() -> None:
    snapshot = _snapshot()
    first = u3.build_observation_receipt(
        snapshot,
        observation_phase="qualification_a",
        attempt_id="attempt-u3",
        observed_at_ns=1,
    )
    second = u3.build_observation_receipt(
        snapshot,
        observation_phase="qualification_b",
        attempt_id="attempt-u3",
        observed_at_ns=999,
    )
    assert first.projection_sha256 == second.projection_sha256
    assert u3.compare_observations(first, second).passed is True


def test_json_field_order_does_not_change_canonical_projection() -> None:
    normal = _mapping()
    reversed_order = dict(reversed(list(normal.items())))
    left = u3.build_stable_projection(u3.snapshot_from_mapping(normal))
    right = u3.build_stable_projection(u3.snapshot_from_mapping(reversed_order))
    assert left.canonical_bytes() == right.canonical_bytes()
    assert left.sha256() == right.sha256()


def test_nested_key_missing_fails_schema_validation() -> None:
    payload = _mapping()
    python_identity = dict(payload["python_identity"])
    python_identity.pop("implementation")
    payload["python_identity"] = python_identity
    with pytest.raises(u3.SnapshotSchemaError, match="key set mismatch"):
        u3.validate_snapshot_mapping(payload)


def test_unknown_snapshot_key_fails_schema_validation() -> None:
    payload = _mapping(unknown="forbidden")
    with pytest.raises(u3.SnapshotSchemaError, match="key set mismatch"):
        u3.validate_snapshot_mapping(payload)


def test_null_state_fails_schema_validation() -> None:
    payload = _mapping(state=None)
    with pytest.raises(u3.SnapshotSchemaError, match="may not be null"):
        u3.validate_snapshot_mapping(payload)


def test_receipt_sha_cannot_substitute_for_tree_identity() -> None:
    before = _mapping()
    observation = u3.build_observation_receipt(
        _snapshot(), observation_phase="protected_before", attempt_id="attempt-u3"
    )
    after = _mapping(tree_digest=u3.sha256_bytes(u3.canonical_json_bytes(observation.to_mapping())))
    comparison = u3.diagnose_snapshot_pair(before, after)
    assert comparison.passed is False
    assert comparison.failure_code == u3.CONTENT_DRIFT


def test_finally_writer_cannot_enrich_stable_snapshot() -> None:
    enriched = _mapping(observation_phase="protected_after")
    with pytest.raises(u3.SnapshotSchemaError, match="key set mismatch"):
        u3.build_observation_receipt_from_mapping(
            enriched,
            observation_phase="protected_after",
            attempt_id="attempt-u3",
        )


def test_observation_receipts_cannot_be_compared_as_stable_payloads() -> None:
    snapshot = _snapshot()
    before = u3.build_observation_receipt(
        snapshot,
        observation_phase="protected_before",
        attempt_id="attempt-u3",
        observed_at_ns=1,
    )
    after = u3.build_observation_receipt(
        snapshot,
        observation_phase="protected_after",
        attempt_id="attempt-u3",
        observed_at_ns=2,
    )
    mutated_comparison = u3.diagnose_snapshot_pair(before.to_mapping(), after.to_mapping())
    assert mutated_comparison.passed is False
    assert mutated_comparison.failure_code == u3.CAPTURE_FAILURE


def test_retained_u2_fixture_is_asymmetry_and_u2_stays_rejected() -> None:
    repository = Path(__file__).resolve().parents[1]
    fixture = json.loads(
        (repository / "tests/fixtures/phase9b_u2_protected_snapshot_asymmetry.json").read_bytes()
    )
    before = {key: "retained" for key in fixture["before_snapshot_top_level_keys"]}
    after = {key: "retained" for key in fixture["after_snapshot_top_level_keys"]}
    comparison = u3.diagnose_snapshot_pair(before, after)
    assert comparison.failure_code == fixture["expected_failure_code"]
    manifest = json.loads(
        (repository / "docs/PHASE9B_UNIFIED_ENVIRONMENT_V002_MANIFEST.json").read_bytes()
    )
    assert manifest["status"] == fixture["u2_status"] == "rejected_environment"


def _fake_environment(tmp_path: Path, *, object_id: str = "project_mlff") -> u3.CaptureTarget:
    root = (tmp_path / object_id).resolve()
    (root / "bin").mkdir(parents=True)
    (root / "conda-meta").mkdir()
    (root / "lib/python3.11/site-packages/torch-2.8.0.dist-info").mkdir(parents=True)
    (root / "bin/python").write_bytes(b"fake-python")
    (root / "conda-meta/history").write_text("created\n", encoding="utf-8")
    info = root / "lib/python3.11/site-packages/torch-2.8.0.dist-info"
    (info / "METADATA").write_text("Name: torch\nVersion: 2.8.0\n", encoding="utf-8")
    (info / "RECORD").write_text("torch.py,,\n", encoding="utf-8")
    conda = (tmp_path / "conda").resolve()
    conda.write_bytes(b"fake-conda")
    return u3.CaptureTarget(object_id, root, conda)


def _runner(argv: list[str] | tuple[str, ...], _environment: object) -> u3.CommandResult:
    if "platform.python_version" in argv[-1]:
        return u3.CommandResult(0, b'{"version":"3.11.15","implementation":"CPython"}\n', b"")
    if "--explicit" in argv:
        return u3.CommandResult(0, b"@EXPLICIT\npackage-url\n", b"")
    return u3.CommandResult(0, b"torch==2.8.0\n", b"")


def test_same_object_captured_twice_has_exact_stable_equality(tmp_path: Path) -> None:
    target = _fake_environment(tmp_path)
    first = u3.capture_protected_object_snapshot(target, command_runner=_runner)
    second = u3.capture_protected_object_snapshot(target, command_runner=_runner)
    comparison = u3.diagnose_snapshot_pair(first.to_mapping(), second.to_mapping())
    assert first.state == second.state == "present"
    assert comparison.passed is True


def test_measurement_qualification_uses_exact_pairwise_identity(tmp_path: Path) -> None:
    targets = [
        _fake_environment(tmp_path, object_id=object_id)
        for object_id in sorted(u3.U3_PROTECTED_OBJECT_IDS)
    ]
    receipt = u3.qualify_measurement_system(
        targets,
        attempt_id="attempt-phase9b-unified-v003",
        helper_source_sha256=_SHA_B,
        command_runner=_runner,
        clock_ns=iter(range(1, 13)).__next__,
        observer_pid=100,
    )
    assert receipt.all_passed is True
    assert receipt.server_write_performed_between_captures is False
    assert all(row.comparison.passed for row in receipt.object_results)


def test_measurement_qualification_rejects_partial_object_set(tmp_path: Path) -> None:
    with pytest.raises(u3.SnapshotSchemaError, match="frozen U3"):
        u3.qualify_measurement_system(
            [_fake_environment(tmp_path)],
            attempt_id="attempt-phase9b-unified-v003",
            helper_source_sha256=_SHA_B,
            command_runner=_runner,
        )


def test_target_lifecycle_does_not_compare_absent_to_present() -> None:
    receipt = u3.TargetEnvironmentLifecycleReceiptV1(
        initial_state="absent",
        post_build_state="present",
        post_capability_state="present",
        post_build_projection_sha256=_SHA_A,
        post_capability_projection_sha256=_SHA_A,
        post_build_post_capability_equal=True,
    )
    assert receipt.to_mapping()["post_build_post_capability_equal"] is True
    with pytest.raises(u3.SnapshotSchemaError, match="initial state"):
        u3.TargetEnvironmentLifecycleReceiptV1(
            initial_state="present",
            post_build_state="present",
            post_capability_state="present",
            post_build_projection_sha256=_SHA_A,
            post_capability_projection_sha256=_SHA_A,
            post_build_post_capability_equal=True,
        )


def test_parent_finally_failure_has_nonempty_structured_assertion() -> None:
    after = _mapping(tree_digest=_SHA_B)
    comparison = u3.diagnose_snapshot_pair(_mapping(), after)
    failure = u3.terminal_failure_from_comparison(comparison, stage="protected_after_comparison")
    terminal = u3.build_terminal_receipt(terminal_status="rejected_environment", failure=failure)
    payload = terminal.to_mapping()
    assert payload["failure"]["code"] == u3.CONTENT_DRIFT
    assert payload["failure"]["assertion"]


def test_failure_code_and_assertion_must_exist_together() -> None:
    with pytest.raises(u3.SnapshotSchemaError, match="code"):
        u3.TerminalFailureV1("", "stage", "assertion", (), _SHA_A)
    with pytest.raises(u3.SnapshotSchemaError, match="stage and assertion"):
        u3.TerminalFailureV1(u3.CONTENT_DRIFT, "stage", "", (), _SHA_A)
    with pytest.raises(u3.SnapshotSchemaError, match="requires structured failure"):
        u3.build_terminal_receipt(terminal_status="rejected_environment", failure=None)


def test_successful_terminal_receipt_has_failure_null() -> None:
    terminal = u3.build_terminal_receipt(terminal_status="validated", failure=None)
    assert terminal.to_mapping()["failure"] is None
    failure = u3.TerminalFailureV1(
        u3.CONTENT_DRIFT, "stage", "assertion", ("project_mlff",), _SHA_A
    )
    with pytest.raises(u3.SnapshotSchemaError, match="failure=null"):
        u3.build_terminal_receipt(terminal_status="validated", failure=failure)


def test_u3_metrology_is_outside_runner_source_closure() -> None:
    from nhc_deprot_ranker.quantum import two_endpoint

    assert (
        "nhc_deprot_ranker/preparation/phase9b_u3_metrology.py"
        not in two_endpoint._RUNNER_SOURCE_RELATIVE_PATHS  # pyright: ignore[reportPrivateUsage]
    )
