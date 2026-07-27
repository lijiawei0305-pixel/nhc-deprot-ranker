"""Regression and mutation tests for Phase 9B-U5 protected metrology."""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from nhc_deprot_ranker.preparation import phase9b_u5_metrology as u5


def _runner(argv: Sequence[str], environment: Mapping[str, str]) -> u5.CommandResult:
    assert Path(argv[0]).is_absolute()
    assert tuple(argv[1:4]) == ("-I", "-B", "-c")
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    return u5.CommandResult(
        0,
        b'{"implementation": "CPython", "version": "3.11.15"}\n',
        b"",
    )


def _record(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "python",
        "version": "3.11.15",
        "build": "h123_0",
        "build_number": 0,
        "channel": "https://repo.example.test/pkgs/main",
        "subdir": "linux-64",
        "fn": "python-3.11.15-h123_0.conda",
        "url": "https://repo.example.test/pkgs/main/python-3.11.15-h123_0.conda",
        "depends": ["openssl >=3", "zlib >=1"],
        "constrains": [],
        "sha256": "a" * 64,
    }
    payload.update(updates)
    return payload


def _write_record(
    root: Path, filename: str = "python-3.11.15-h123_0.json", **updates: object
) -> Path:
    path = root / "conda-meta" / filename
    path.write_text(json.dumps(_record(**updates)), encoding="utf-8")
    return path


def _write_dist(
    root: Path,
    directory: str = "demo_pkg-1.0.dist-info",
    *,
    name: str = "demo-pkg",
    version: str = "1.0",
) -> Path:
    dist = root / "lib" / "python3.11" / "site-packages" / directory
    dist.mkdir(parents=True)
    (dist / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )
    (dist / "RECORD").write_text("demo.py,,\n", encoding="utf-8")
    (dist / "WHEEL").write_text("Wheel-Version: 1.0\n", encoding="utf-8")
    return dist


@pytest.fixture
def conda_env(tmp_path: Path) -> Path:
    root = tmp_path / "env"
    (root / "bin").mkdir(parents=True)
    executable = root / "bin" / "python3.11"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    (root / "bin" / "python3").symlink_to("python3.11")
    (root / "bin" / "python").symlink_to("python3")
    (root / "conda-meta").mkdir()
    (root / "conda-meta" / "history").write_text("# frozen history\n", encoding="utf-8")
    _write_record(root)
    _write_dist(root)
    return root


def _target(root: Path, object_id: str = "project_mlff") -> u5.CaptureTarget:
    return u5.CaptureTarget(object_id, root)


def _capture(root: Path) -> u5.CaptureResultV2:
    return u5.capture_protected_object_snapshot(_target(root), command_runner=_runner)


def test_capture_target_has_no_external_executable_identity(conda_env: Path) -> None:
    target = _target(conda_env)
    assert set(target.__dataclass_fields__) == {"object_id", "root"}


@pytest.mark.parametrize("launcher_kind", ["regular", "one-link", "multi-link"])
def test_valid_launcher_shapes(tmp_path: Path, launcher_kind: str) -> None:
    root = tmp_path / launcher_kind
    (root / "bin").mkdir(parents=True)
    leaf = root / "bin" / "python3.11"
    leaf.write_bytes(b"python")
    leaf.chmod(0o755)
    if launcher_kind == "regular":
        (root / "bin" / "python").write_bytes(b"python")
        (root / "bin" / "python").chmod(0o755)
    elif launcher_kind == "one-link":
        (root / "bin" / "python").symlink_to("python3.11")
    else:
        (root / "bin" / "python3").symlink_to("python3.11")
        (root / "bin" / "python").symlink_to("python3")
    evidence = u5.resolve_environment_python_launcher(_target(root))
    assert evidence.launcher_kind in {"regular", "symlink"}
    assert evidence.resolved_target_inside_root is True
    assert evidence.symlink_depth == {"regular": 0, "one-link": 1, "multi-link": 2}[launcher_kind]


@pytest.mark.parametrize(
    ("setup", "code"),
    [
        ("dangling", u5.PYTHON_SYMLINK_DANGLING),
        ("loop", u5.PYTHON_SYMLINK_LOOP),
        ("absolute_escape", u5.PYTHON_SYMLINK_ESCAPES_ENV),
        ("relative_escape", u5.PYTHON_SYMLINK_ESCAPES_ENV),
        ("directory", u5.PYTHON_TARGET_NOT_REGULAR),
        ("not_executable", u5.PYTHON_TARGET_NOT_EXECUTABLE),
    ],
)
def test_invalid_launcher_shapes(tmp_path: Path, setup: str, code: str) -> None:
    root = tmp_path / "env"
    (root / "bin").mkdir(parents=True)
    launcher = root / "bin" / "python"
    if setup == "dangling":
        launcher.symlink_to("missing")
    elif setup == "loop":
        launcher.symlink_to("python3")
        (root / "bin" / "python3").symlink_to("python")
    elif setup == "absolute_escape":
        launcher.symlink_to("/usr/bin/python")
    elif setup == "relative_escape":
        launcher.symlink_to("../../outside/python")
    elif setup == "directory":
        launcher.mkdir()
    else:
        launcher.write_bytes(b"python")
        launcher.chmod(0o644)
    with pytest.raises(u5.StageCaptureError) as raised:
        u5.resolve_environment_python_launcher(_target(root))
    assert raised.value.code == code


def test_launcher_to_another_environment_is_escape(tmp_path: Path) -> None:
    root, other = tmp_path / "one", tmp_path / "two"
    (root / "bin").mkdir(parents=True)
    (other / "bin").mkdir(parents=True)
    external = other / "bin" / "python"
    external.write_bytes(b"python")
    external.chmod(0o755)
    (root / "bin" / "python").symlink_to(external)
    with pytest.raises(u5.StageCaptureError) as raised:
        u5.resolve_environment_python_launcher(_target(root))
    assert raised.value.code == u5.PYTHON_SYMLINK_ESCAPES_ENV


def test_probe_identity_drift_is_rejected(conda_env: Path) -> None:
    target = _target(conda_env)
    launcher = u5.resolve_environment_python_launcher(target)

    def drift_runner(argv: Sequence[str], environment: Mapping[str, str]) -> u5.CommandResult:
        leaf = conda_env / "bin" / "python3.11"
        leaf.write_bytes(b"changed")
        leaf.chmod(0o755)
        return _runner(argv, environment)

    with pytest.raises(u5.StageCaptureError) as raised:
        u5.capture_python_probe(target, launcher, drift_runner)
    assert raised.value.code == u5.PYTHON_IDENTITY_DRIFT
    assert isinstance(raised.value.partial_evidence, u5.PythonProbeEvidence)


def test_probe_failure_keeps_command_and_disk_evidence(conda_env: Path) -> None:
    def failed_runner(argv: Sequence[str], environment: Mapping[str, str]) -> u5.CommandResult:
        return u5.CommandResult(7, b"partial", b"registered failure")

    capture = u5.capture_protected_object_snapshot(_target(conda_env), command_runner=failed_runner)
    assert capture.snapshot.state == "invalid"
    assert capture.snapshot.failure is not None
    assert capture.snapshot.failure.code == u5.PYTHON_PROBE_FAILED
    assert capture.snapshot.launcher_evidence is not None
    assert capture.snapshot.python_probe_evidence is not None
    assert capture.snapshot.python_probe_evidence.returncode == 7
    assert capture.snapshot.conda_meta_evidence is not None
    assert capture.snapshot.distribution_evidence is not None
    assert capture.snapshot.tree_evidence is not None


def test_normal_conda_metadata_inventory(conda_env: Path) -> None:
    inventory = u5.capture_conda_prefix_inventory(conda_env)
    assert inventory["record_count"] == 1
    assert inventory["history_line_count"] == 1
    assert len(str(inventory["raw_record_set_sha256"])) == 64
    assert len(str(inventory["normalized_record_set_sha256"])) == 64


def test_multiple_record_order_is_canonical(conda_env: Path) -> None:
    _write_record(conda_env, "aaa-1-0.json", name="aaa", version="1")
    inventory = u5.capture_conda_prefix_inventory(conda_env)
    rows = inventory["records"]
    assert isinstance(rows, list)
    assert [row["record_filename"] for row in rows] == sorted(
        row["record_filename"] for row in rows
    )


def test_empty_record_set_fails(conda_env: Path) -> None:
    for path in (conda_env / "conda-meta").glob("*.json"):
        path.unlink()
    with pytest.raises(u5.StageCaptureError) as raised:
        u5.capture_conda_prefix_inventory(conda_env)
    assert raised.value.code == u5.CONDA_RECORD_SET_EMPTY


@pytest.mark.parametrize("kind", ["missing", "symlink", "regular"])
def test_conda_meta_directory_shape_is_validated(conda_env: Path, kind: str) -> None:
    meta = conda_env / "conda-meta"
    retained = conda_env / "retained-meta"
    meta.rename(retained)
    if kind == "symlink":
        meta.symlink_to(retained, target_is_directory=True)
        expected = u5.CONDA_META_DIRECTORY_INVALID
    elif kind == "regular":
        meta.write_text("not a directory", encoding="utf-8")
        expected = u5.CONDA_META_DIRECTORY_INVALID
    else:
        expected = u5.CONDA_META_DIRECTORY_MISSING
    with pytest.raises(u5.StageCaptureError) as raised:
        u5.capture_conda_prefix_inventory(conda_env)
    assert raised.value.code == expected


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (b"{not-json", u5.CONDA_RECORD_INVALID),
        (
            b'{"name":"a","name":"b","version":"1","build":"0","build_number":0}',
            u5.CONDA_RECORD_INVALID,
        ),
        (b"\xff", u5.CONDA_RECORD_INVALID),
        (b'{"name":"a","version":"1","build":"0","build_number":NaN}', u5.CONDA_RECORD_INVALID),
    ],
)
def test_invalid_conda_record_bytes(conda_env: Path, mutation: bytes, code: str) -> None:
    record = next((conda_env / "conda-meta").glob("*.json"))
    record.write_bytes(mutation)
    with pytest.raises(u5.StageCaptureError) as raised:
        u5.capture_conda_prefix_inventory(conda_env)
    assert raised.value.code == code


@pytest.mark.parametrize("missing", ["name", "version", "build", "build_number"])
def test_required_conda_record_fields(conda_env: Path, missing: str) -> None:
    record = next((conda_env / "conda-meta").glob("*.json"))
    payload = _record()
    del payload[missing]
    record.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(u5.StageCaptureError) as raised:
        u5.capture_conda_prefix_inventory(conda_env)
    assert raised.value.code == u5.CONDA_RECORD_REQUIRED_FIELD_MISSING


@pytest.mark.parametrize(
    ("field", "value"),
    [("name", 3), ("version", None), ("build", []), ("build_number", True), ("depends", "x")],
)
def test_conda_record_field_types(conda_env: Path, field: str, value: object) -> None:
    record = next((conda_env / "conda-meta").glob("*.json"))
    record.write_text(json.dumps(_record(**{field: value})), encoding="utf-8")
    with pytest.raises(u5.StageCaptureError) as raised:
        u5.capture_conda_prefix_inventory(conda_env)
    assert raised.value.code == u5.CONDA_RECORD_FIELD_TYPE_INVALID


def test_history_missing_and_symlink_are_distinct_failures(conda_env: Path) -> None:
    history = conda_env / "conda-meta" / "history"
    history.unlink()
    with pytest.raises(u5.StageCaptureError) as missing:
        u5.capture_conda_prefix_inventory(conda_env)
    assert missing.value.code == u5.CONDA_HISTORY_MISSING
    target = conda_env / "history-real"
    target.write_text("history", encoding="utf-8")
    history.symlink_to(target)
    with pytest.raises(u5.StageCaptureError) as invalid:
        u5.capture_conda_prefix_inventory(conda_env)
    assert invalid.value.code == u5.CONDA_HISTORY_INVALID


def test_unknown_and_ignored_conda_fields_are_bound(conda_env: Path) -> None:
    record = next((conda_env / "conda-meta").glob("*.json"))
    record.write_text(
        json.dumps(
            _record(
                mystery={"value": 1},
                prefix="/private/prefix",
                cache_path="/private/cache/pkg",
                url="https://user:secret@example.test/private/pkg.conda",
            )
        ),
        encoding="utf-8",
    )
    inventory = u5.capture_conda_prefix_inventory(conda_env)
    rows = inventory["records"]
    assert isinstance(rows, list)
    normalized = rows[0]["normalized_projection"]
    assert normalized["unknown_field_names"] == ["mystery"]
    assert normalized["ignored_field_names"] == ["cache_path", "prefix"]
    rendered = json.dumps(normalized)
    assert "secret" not in rendered and "/private/prefix" not in rendered


def test_conda_raw_normalized_filename_and_history_changes_are_detected(
    conda_env: Path,
) -> None:
    first = u5.capture_conda_prefix_inventory(conda_env)
    record = next((conda_env / "conda-meta").glob("*.json"))
    record.write_text(json.dumps(_record(version="3.11.16")), encoding="utf-8")
    second = u5.capture_conda_prefix_inventory(conda_env)
    assert first["raw_record_set_sha256"] != second["raw_record_set_sha256"]
    assert first["normalized_record_set_sha256"] != second["normalized_record_set_sha256"]
    renamed = record.with_name("renamed.json")
    record.rename(renamed)
    third = u5.capture_conda_prefix_inventory(conda_env)
    assert second["record_filename_set_sha256"] != third["record_filename_set_sha256"]
    (conda_env / "conda-meta" / "history").write_text("changed\n", encoding="utf-8")
    fourth = u5.capture_conda_prefix_inventory(conda_env)
    assert third["history_sha256"] != fourth["history_sha256"]


def test_distribution_inventory_normal_and_optional_states(conda_env: Path) -> None:
    inventory = u5.capture_python_distribution_inventory(conda_env)
    assert inventory["all_distribution_count"] == 1
    row = inventory["distributions"][0]
    assert row["canonical_name"] == "demo-pkg"
    assert row["record"]["state"] == "present"
    assert row["installer"]["state"] == "absent"
    assert any(
        critical["canonical_name"] == "torch" and critical["state"] == "absent"
        for critical in inventory["critical_distribution_projection"]
    )


def test_distribution_direct_url_and_inventory_drift(conda_env: Path) -> None:
    dist = next(conda_env.glob("lib/python*/site-packages/*.dist-info"))
    first = u5.capture_python_distribution_inventory(conda_env)
    (dist / "direct_url.json").write_text('{"url":"file:///private"}', encoding="utf-8")
    second = u5.capture_python_distribution_inventory(conda_env)
    assert first["all_distribution_inventory_sha256"] != second["all_distribution_inventory_sha256"]
    assert second["distributions"][0]["direct_url"]["state"] == "present"


def test_duplicate_normalized_distribution_names_are_reported(conda_env: Path) -> None:
    _write_dist(conda_env, "demo_pkg-2.0.dist-info", name="Demo.Pkg", version="2.0")
    inventory = u5.capture_python_distribution_inventory(conda_env)
    assert inventory["duplicate_name_report"] == [
        {
            "canonical_name": "demo-pkg",
            "versions": ["1.0", "2.0"],
            "directory_names": ["demo_pkg-1.0.dist-info", "demo_pkg-2.0.dist-info"],
        }
    ]


def test_missing_record_is_allowed(conda_env: Path) -> None:
    record = next(conda_env.glob("lib/python*/site-packages/*.dist-info/RECORD"))
    record.unlink()
    inventory = u5.capture_python_distribution_inventory(conda_env)
    assert inventory["distributions"][0]["record"]["state"] == "absent"


@pytest.mark.parametrize("kind", ["invalid", "symlink"])
def test_invalid_distribution_metadata(conda_env: Path, kind: str) -> None:
    metadata = next(conda_env.glob("lib/python*/site-packages/*.dist-info/METADATA"))
    metadata.unlink()
    if kind == "invalid":
        metadata.write_bytes(b"\xff")
        expected = u5.DISTRIBUTION_METADATA_INVALID
    else:
        target = metadata.parent / "real-metadata"
        target.write_text("Name: x\nVersion: 1\n", encoding="utf-8")
        metadata.symlink_to(target)
        expected = u5.DISTRIBUTION_METADATA_SYMLINK
    with pytest.raises(u5.StageCaptureError) as raised:
        u5.capture_python_distribution_inventory(conda_env)
    assert raised.value.code == expected


def test_missing_distribution_metadata_is_specific(conda_env: Path) -> None:
    metadata = next(conda_env.glob("lib/python*/site-packages/*.dist-info/METADATA"))
    metadata.unlink()
    with pytest.raises(u5.StageCaptureError) as raised:
        u5.capture_python_distribution_inventory(conda_env)
    assert raised.value.code == u5.DISTRIBUTION_METADATA_MISSING


def test_tree_identity_is_layered_and_non_following(conda_env: Path) -> None:
    outside = conda_env.parent / "outside"
    outside.mkdir()
    (outside / "secret").write_text("not followed", encoding="utf-8")
    (conda_env / "external-dir").symlink_to(outside)
    tree = u5.capture_tree_identity(conda_env)
    assert tree["symlink_count"] >= 3
    assert tree["full_hash_threshold_bytes"] == u5.TREE_FULL_HASH_THRESHOLD_BYTES
    assert len(str(tree["tree_structure_digest"])) == 64
    assert len(str(tree["tree_content_identity_digest"])) == 64


@pytest.mark.parametrize("failing_stage", ["conda", "distribution", "tree"])
def test_partial_evidence_is_never_replaced_by_sentinel(
    conda_env: Path, failing_stage: str
) -> None:
    def fail(path: Path) -> Mapping[str, object]:
        code = {
            "conda": u5.CONDA_RECORD_INVALID,
            "distribution": u5.DISTRIBUTION_CAPTURE_FAILED,
            "tree": u5.TREE_CAPTURE_FAILED,
        }[failing_stage]
        raise u5.StageCaptureError(code, failing_stage, "frozen test assertion")

    kwargs: dict[str, object] = {"command_runner": _runner}
    kwargs[
        {
            "conda": "conda_capturer",
            "distribution": "distribution_capturer",
            "tree": "tree_capturer",
        }[failing_stage]
    ] = fail
    capture = u5.capture_protected_object_snapshot(_target(conda_env), **kwargs)  # type: ignore[arg-type]
    snapshot = capture.snapshot
    assert snapshot.launcher_evidence is not None
    assert snapshot.python_probe_evidence is not None
    if failing_stage != "conda":
        assert snapshot.conda_meta_evidence is not None
    if failing_stage == "tree":
        assert snapshot.distribution_evidence is not None
    assert capture.diagnostic["portable_evidence_complete"] is True
    assert snapshot.failure is not None
    assert all(
        getattr(snapshot.failure, field)
        for field in ("code", "stage", "assertion", "object_id", "details_digest")
    )


def test_present_snapshot_and_ab_projection_are_exact(conda_env: Path) -> None:
    first = _capture(conda_env)
    second = _capture(conda_env)
    assert first.snapshot.state == second.snapshot.state == "present"
    assert first.snapshot.failure is second.snapshot.failure is None
    observation_a = u5.build_observation_receipt(
        first,
        observation_phase="qualification_a",
        attempt_id="u5-q",
        observed_at_ns=1,
        observer_pid=1,
    )
    observation_b = u5.build_observation_receipt(
        second,
        observation_phase="qualification_b",
        attempt_id="u5-q",
        observed_at_ns=2,
        observer_pid=99,
    )
    comparison = u5.compare_observations(observation_a, observation_b)
    assert observation_a.to_mapping() != observation_b.to_mapping()
    assert observation_a.projection.canonical_bytes() == observation_b.projection.canonical_bytes()
    assert comparison.passed


def test_arbitrary_mapping_order_does_not_change_canonical_bytes() -> None:
    left = {"a": 1, "b": {"x": 2, "y": 3}}
    right = {"b": {"y": 3, "x": 2}, "a": 1}
    assert u5.canonical_json_bytes(left) == u5.canonical_json_bytes(right)


def test_observation_receipt_cannot_be_compared_as_identity(conda_env: Path) -> None:
    capture = _capture(conda_env)
    observation = u5.build_observation_receipt(
        capture,
        observation_phase="qualification_a",
        attempt_id="u5-q",
        observed_at_ns=1,
        observer_pid=1,
    )
    with pytest.raises(u5.SnapshotSchemaError):
        u5.compare_observations(observation.to_mapping(), observation)  # type: ignore[arg-type]


def test_symlink_chain_and_executable_changes_enter_projection(conda_env: Path) -> None:
    first = _capture(conda_env)
    (conda_env / "bin" / "python").unlink()
    (conda_env / "bin" / "python").symlink_to("python3.11")
    second = _capture(conda_env)
    left = u5.ProtectedObjectIdentityProjectionV3.from_snapshot(first.snapshot)
    right = u5.ProtectedObjectIdentityProjectionV3.from_snapshot(second.snapshot)
    assert left.sha256 != right.sha256
    (conda_env / "bin" / "python3.11").write_bytes(b"different executable")
    (conda_env / "bin" / "python3.11").chmod(0o755)
    third = _capture(conda_env)
    assert (
        right.sha256 != u5.ProtectedObjectIdentityProjectionV3.from_snapshot(third.snapshot).sha256
    )


def test_static_mutations_cannot_reintroduce_external_package_manager() -> None:
    source = Path(u5.__file__).read_text(encoding="utf-8")
    prohibited = (
        "import " + "conda",
        "import " + "pip",
        "micromamba",
        "mamba",
        "source activate",
        "conda" + " list --explicit",
        "pip" + " freeze",
    )
    assert all(value not in source for value in prohibited)
    assert "conda_executable" not in source
    assert source.count("subprocess.run(") == 1
    assert '"-I", "-B", "-c"' in source
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert imported <= {
        "__future__",
        "collections",
        "dataclasses",
        "email",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "re",
        "stat",
        "subprocess",
        "time",
        "typing",
        "urllib",
    }


def test_u4_cli_failure_fixture_is_retained_and_irrelevant() -> None:
    repository = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (repository / "docs/PHASE9B_UNIFIED_ENVIRONMENT_V004_MANIFEST.json").read_text()
    )
    assert manifest["status"] == "failed_before_environment_creation"
    assert manifest["qualification"]["failure_code"] == "CONDA_EXPLICIT_FAILED"
    assert u5.CONDA_META_DIRECTORY_MISSING != "CONDA_EXPLICIT_FAILED"


def test_failure_mutation_cannot_be_promoted_to_present(conda_env: Path) -> None:
    failed = u5.capture_protected_object_snapshot(
        _target(conda_env),
        command_runner=lambda argv, environment: u5.CommandResult(2, b"", b"failed"),
    )
    assert failed.snapshot.failure is not None
    mutation = replace(failed.snapshot, state="present")
    with pytest.raises(u5.SnapshotSchemaError):
        u5._validate_snapshot(mutation)  # pyright: ignore[reportPrivateUsage]


def test_projection_excludes_observation_and_diagnostic_fields(conda_env: Path) -> None:
    capture = _capture(conda_env)
    projection = u5.ProtectedObjectIdentityProjectionV3.from_snapshot(capture.snapshot).to_mapping()
    rendered = json.dumps(projection)
    for forbidden in ("timestamp", "observer_pid", "attempt_id", "diagnostic", "exception"):
        assert forbidden not in rendered


def test_module_is_outside_frozen_runner_source_closure() -> None:
    from nhc_deprot_ranker.quantum import two_endpoint as runner

    assert (
        "nhc_deprot_ranker/preparation/phase9b_u5_metrology.py"
        not in runner._RUNNER_SOURCE_RELATIVE_PATHS  # pyright: ignore[reportPrivateUsage]
    )


def test_qualification_requires_exact_six_object_set(conda_env: Path) -> None:
    helper_sha = hashlib.sha256(Path(u5.__file__).read_bytes()).hexdigest()
    with pytest.raises(u5.SnapshotSchemaError):
        u5.qualify_measurement_system(
            [_target(conda_env)],
            attempt_id="u5-q",
            helper_source_sha256=helper_sha,
            command_runner=_runner,
        )


def test_capture_diagnostic_present_has_null_failure(conda_env: Path) -> None:
    capture = _capture(conda_env)
    assert capture.diagnostic["capture_state"] == "present"
    assert capture.diagnostic["failure"] is None
    assert capture.diagnostic["portable_evidence_complete"] is True


def test_unknown_exception_is_not_ordinary_invalid(conda_env: Path) -> None:
    def explode(path: Path) -> Mapping[str, object]:
        raise RuntimeError("unregistered")

    capture = u5.capture_protected_object_snapshot(
        _target(conda_env), command_runner=_runner, tree_capturer=explode
    )
    assert capture.snapshot.failure is not None
    assert capture.snapshot.failure.code == u5.UNEXPECTED_CAPTURE_EXCEPTION
    assert capture.snapshot.failure.stage == "tree_capture"
    assert capture.snapshot.failure.exception_class == "RuntimeError"


def test_relative_paths_only_in_portable_snapshot(conda_env: Path) -> None:
    capture = _capture(conda_env)
    rendered = json.dumps(capture.snapshot.to_mapping(portable=True))
    assert str(conda_env) not in rendered
    launcher = capture.snapshot.launcher_evidence
    assert launcher is not None
    assert launcher.resolved_executable_relative_path == "bin/python3.11"


def test_tree_change_changes_projection(conda_env: Path) -> None:
    first = _capture(conda_env)
    (conda_env / "new-small-config.txt").write_text("new", encoding="utf-8")
    second = _capture(conda_env)
    left = u5.ProtectedObjectIdentityProjectionV3.from_snapshot(first.snapshot)
    right = u5.ProtectedObjectIdentityProjectionV3.from_snapshot(second.snapshot)
    assert left.sha256 != right.sha256


def test_conda_raw_change_cannot_be_hidden_by_unknown_field_policy(conda_env: Path) -> None:
    first = _capture(conda_env)
    record = next((conda_env / "conda-meta").glob("*.json"))
    payload = json.loads(record.read_text())
    payload["unknown_new_field"] = "value"
    record.write_text(json.dumps(payload), encoding="utf-8")
    second = _capture(conda_env)
    left = u5.ProtectedObjectIdentityProjectionV3.from_snapshot(first.snapshot).to_mapping()
    right = u5.ProtectedObjectIdentityProjectionV3.from_snapshot(second.snapshot).to_mapping()
    assert left["conda_raw_inventory_sha256"] != right["conda_raw_inventory_sha256"]


def test_distribution_change_cannot_be_ignored(conda_env: Path) -> None:
    first = _capture(conda_env)
    metadata = next(conda_env.glob("lib/python*/site-packages/*.dist-info/METADATA"))
    metadata.write_text("Metadata-Version: 2.1\nName: demo-pkg\nVersion: 1.1\n", encoding="utf-8")
    second = _capture(conda_env)
    left = u5.ProtectedObjectIdentityProjectionV3.from_snapshot(first.snapshot).to_mapping()
    right = u5.ProtectedObjectIdentityProjectionV3.from_snapshot(second.snapshot).to_mapping()
    assert left["distribution_inventory_sha256"] != right["distribution_inventory_sha256"]


def test_same_helper_source_is_bound_into_qualification_receipt() -> None:
    helper_sha = hashlib.sha256(Path(u5.__file__).read_bytes()).hexdigest()
    receipt = u5.MeasurementQualificationReceiptV3("u5-q", helper_sha, (), False).to_mapping()
    assert receipt["helper_source_sha256"] == helper_sha
    assert receipt["package_manager_cli_invocations"] == 0


def test_all_public_execution_gates_remain_false() -> None:
    repository = Path(__file__).resolve().parents[1]
    gate_files = sorted((repository / "artifacts/phase9b").glob("*.json"))
    gate_values: list[bool] = []
    for path in gate_files:
        payload = json.loads(path.read_text())
        if isinstance(payload, dict) and "execution_gates" in payload:
            gates = payload["execution_gates"]
            if isinstance(gates, dict):
                gate_values.extend(value for value in gates.values() if isinstance(value, bool))
    assert not any(gate_values)
