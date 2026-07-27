"""No-chemistry tests for Phase 9B-U4 symlink-aware metrology."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from nhc_deprot_ranker.preparation import phase9b_u3_metrology as u3
from nhc_deprot_ranker.preparation import phase9b_u4_metrology as u4

_SHA = "a" * 64


def _write_executable(path: Path, raw: bytes = b"fake-python") -> None:
    path.write_bytes(raw)
    path.chmod(0o755)


def _environment(
    tmp_path: Path,
    *,
    object_id: str = "project_mlff",
    launcher: str = "multi",
) -> u4.CaptureTarget:
    root = (tmp_path / object_id).resolve()
    (root / "bin").mkdir(parents=True)
    (root / "conda-meta").mkdir()
    info = root / "lib/python3.11/site-packages/torch-2.8.0.dist-info"
    info.mkdir(parents=True)
    (root / "conda-meta/history").write_text("created\n", encoding="utf-8")
    (info / "METADATA").write_text("Name: torch\nVersion: 2.8.0\n", encoding="utf-8")
    (info / "RECORD").write_text("torch.py,,\n", encoding="utf-8")
    if launcher == "regular":
        _write_executable(root / "bin/python")
    elif launcher == "single":
        _write_executable(root / "bin/python3.11")
        (root / "bin/python").symlink_to("python3.11")
    elif launcher == "relative":
        _write_executable(root / "bin/python3.11")
        (root / "bin/python").symlink_to("./python3.11")
    elif launcher == "multi":
        _write_executable(root / "bin/python3.11")
        (root / "bin/python3").symlink_to("python3.11")
        (root / "bin/python").symlink_to("python3")
    else:  # pragma: no cover - fixture contract
        raise ValueError(launcher)
    conda = (tmp_path / "conda").resolve()
    if not conda.exists():
        _write_executable(conda, b"fake-conda")
    return u4.CaptureTarget(object_id, root, conda)


class Runner:
    def __init__(
        self, *, fail: str = "", timeout: str = "", callback: object | None = None
    ) -> None:
        self.fail = fail
        self.timeout = timeout
        self.callback = callback
        self.calls = 0
        self.argvs: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str], _environment: Mapping[str, str]) -> u4.CommandResult:
        self.calls += 1
        self.argvs.append(tuple(argv))
        if callable(self.callback):
            self.callback(self.calls)
        if "platform.python_version" in argv[-1]:
            name = "python"
            stdout = b'{"version":"3.11.15","implementation":"CPython"}\n'
        elif "--explicit" in argv:
            name = "conda"
            stdout = b"@EXPLICIT\npackage-url\n"
        else:
            name = "pip"
            stdout = b"torch==2.8.0\n"
        return u4.CommandResult(
            124 if self.timeout == name else (1 if self.fail == name else 0),
            stdout,
            b"failed" if self.fail == name else b"",
            timed_out=self.timeout == name,
        )


@pytest.mark.parametrize(
    ("launcher", "kind", "depth", "targets"),
    [
        ("regular", "regular", 0, ()),
        ("single", "symlink", 1, ("bin/python3.11",)),
        ("relative", "symlink", 1, ("bin/python3.11",)),
        ("multi", "symlink", 2, ("bin/python3", "bin/python3.11")),
    ],
)
def test_legal_launchers_resolve_inside_root(
    tmp_path: Path,
    launcher: str,
    kind: str,
    depth: int,
    targets: tuple[str, ...],
) -> None:
    target = _environment(tmp_path, launcher=launcher)
    resolution = u4.resolve_environment_python_launcher(target)
    assert resolution.launcher_kind == kind
    assert resolution.symlink_depth == depth
    assert resolution.symlink_chain_relative_targets == targets
    assert resolution.resolved_target_inside_root is True
    assert resolution.resolved_executable.is_absolute()


def test_nonstandard_local_target_names_are_stable(tmp_path: Path) -> None:
    target = _environment(tmp_path, launcher="regular")
    launcher = target.root / "bin/python"
    launcher.rename(target.root / "bin/local-python")
    launcher.symlink_to("local-python")
    first = u4.resolve_environment_python_launcher(target)
    second = u4.resolve_environment_python_launcher(target)
    assert first.symlink_chain_relative_targets == ("bin/local-python",)
    assert first.symlink_chain_digest == second.symlink_chain_digest


def _bare_target(tmp_path: Path) -> u4.CaptureTarget:
    root = (tmp_path / "env").resolve()
    (root / "bin").mkdir(parents=True)
    conda = (tmp_path / "conda").resolve()
    _write_executable(conda)
    return u4.CaptureTarget("project_mlff", root, conda)


def test_dangling_symlink_is_rejected(tmp_path: Path) -> None:
    target = _bare_target(tmp_path)
    (target.root / "bin/python").symlink_to("missing")
    with pytest.raises(u4.LauncherResolutionError) as caught:
        u4.resolve_environment_python_launcher(target)
    assert caught.value.code == u4.PYTHON_SYMLINK_DANGLING


def test_symlink_loop_is_rejected(tmp_path: Path) -> None:
    target = _bare_target(tmp_path)
    (target.root / "bin/python").symlink_to("python3")
    (target.root / "bin/python3").symlink_to("python")
    with pytest.raises(u4.LauncherResolutionError) as caught:
        u4.resolve_environment_python_launcher(target)
    assert caught.value.code == u4.PYTHON_SYMLINK_LOOP


@pytest.mark.parametrize("link", ["/usr/bin/python", "../../outside/python"])
def test_absolute_and_relative_escape_are_rejected(tmp_path: Path, link: str) -> None:
    target = _bare_target(tmp_path)
    (target.root / "bin/python").symlink_to(link)
    with pytest.raises(u4.LauncherResolutionError) as caught:
        u4.resolve_environment_python_launcher(target)
    assert caught.value.code == u4.PYTHON_SYMLINK_ESCAPES_ENV
    assert caught.value.inside_root is False


def test_other_conda_environment_is_rejected(tmp_path: Path) -> None:
    target = _bare_target(tmp_path)
    other = (tmp_path / "other/bin").resolve()
    other.mkdir(parents=True)
    _write_executable(other / "python")
    (target.root / "bin/python").symlink_to(other / "python")
    with pytest.raises(u4.LauncherResolutionError) as caught:
        u4.resolve_environment_python_launcher(target)
    assert caught.value.code == u4.PYTHON_SYMLINK_ESCAPES_ENV


def test_directory_target_is_rejected(tmp_path: Path) -> None:
    target = _bare_target(tmp_path)
    (target.root / "bin/python-dir").mkdir()
    (target.root / "bin/python").symlink_to("python-dir")
    with pytest.raises(u4.LauncherResolutionError) as caught:
        u4.resolve_environment_python_launcher(target)
    assert caught.value.code == u4.PYTHON_TARGET_NOT_REGULAR


def test_non_executable_target_is_rejected(tmp_path: Path) -> None:
    target = _bare_target(tmp_path)
    (target.root / "bin/python").write_bytes(b"not executable")
    with pytest.raises(u4.LauncherResolutionError) as caught:
        u4.resolve_environment_python_launcher(target)
    assert caught.value.code == u4.PYTHON_TARGET_NOT_EXECUTABLE


@pytest.mark.parametrize("mutation", ["target", "inode", "launcher"])
def test_probe_detects_target_inode_and_launcher_drift(tmp_path: Path, mutation: str) -> None:
    target = _environment(tmp_path)
    resolved = target.root / "bin/python3.11"
    logical = target.root / "bin/python"

    def mutate(call: int) -> None:
        if call != 1:
            return
        if mutation in {"target", "inode"}:
            resolved.unlink()
            _write_executable(resolved, b"changed" if mutation == "target" else b"fake-python")
        else:
            logical.unlink()
            logical.symlink_to("python3")

    result = u4.capture_protected_object_snapshot(target, command_runner=Runner(callback=mutate))
    assert result.snapshot.state == "invalid"
    assert result.diagnostic.failure is not None
    assert result.diagnostic.failure.code == u4.PYTHON_IDENTITY_DRIFT


def test_launcher_and_target_are_stable_across_all_probes(tmp_path: Path) -> None:
    runner = Runner()
    result = u4.capture_protected_object_snapshot(_environment(tmp_path), command_runner=runner)
    assert result.snapshot.state == "present"
    assert result.diagnostic.failure is None
    assert len(result.diagnostic.command_evidence) == 3
    assert all(
        row.returncode == 0 and not row.timed_out for row in result.diagnostic.command_evidence
    )
    assert result.snapshot.python_identity.resolved_executable_relative_path == "bin/python3.11"
    assert Path(runner.argvs[0][0]).name == "python3.11"
    assert Path(runner.argvs[2][0]).name == "python3.11"
    assert all(argv[0] not in {"python", "python3"} for argv in runner.argvs)


@pytest.mark.parametrize(
    ("failed", "code"),
    [
        ("python", u4.PYTHON_PROBE_FAILED),
        ("conda", u4.CONDA_EXPLICIT_FAILED),
        ("pip", u4.PIP_FREEZE_FAILED),
    ],
)
def test_each_command_failure_has_specific_evidence(tmp_path: Path, failed: str, code: str) -> None:
    result = u4.capture_protected_object_snapshot(
        _environment(tmp_path), command_runner=Runner(fail=failed)
    )
    assert result.diagnostic.failure is not None
    assert result.diagnostic.failure.code == code
    evidence = result.diagnostic.command_evidence[-1]
    assert evidence.returncode == 1
    assert evidence.stdout_sha256 and evidence.stderr_sha256
    assert evidence.stdout_bytes > 0 and evidence.stderr_bytes > 0


def test_command_timeout_is_recorded_and_rejected(tmp_path: Path) -> None:
    result = u4.capture_protected_object_snapshot(
        _environment(tmp_path), command_runner=Runner(timeout="pip")
    )
    assert result.diagnostic.failure is not None
    assert result.diagnostic.failure.code == u4.PIP_FREEZE_FAILED
    evidence = result.diagnostic.command_evidence[-1]
    assert evidence.timed_out is True
    assert evidence.returncode == 124


def test_history_missing_has_specific_diagnostic(tmp_path: Path) -> None:
    target = _environment(tmp_path)
    (target.root / "conda-meta/history").unlink()
    result = u4.capture_protected_object_snapshot(target, command_runner=Runner())
    assert result.diagnostic.failure is not None
    assert result.diagnostic.failure.code == u4.CONDA_HISTORY_MISSING


def test_tree_permission_error_has_specific_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(_root: Path) -> tuple[int, int, int, str, str]:
        raise PermissionError("denied")

    monkeypatch.setattr(u4, "_tree_identity", denied)
    result = u4.capture_protected_object_snapshot(_environment(tmp_path), command_runner=Runner())
    assert result.diagnostic.failure is not None
    assert result.diagnostic.failure.code == u4.TREE_CAPTURE_FAILED
    assert result.diagnostic.exception_class == "PermissionError"


def test_metadata_parse_error_has_specific_diagnostic(tmp_path: Path) -> None:
    target = _environment(tmp_path)
    metadata = next(target.root.glob("lib/python*/site-packages/*.dist-info/METADATA"))
    metadata.write_text("broken\n", encoding="utf-8")
    result = u4.capture_protected_object_snapshot(target, command_runner=Runner())
    assert result.diagnostic.failure is not None
    assert result.diagnostic.failure.code == u4.DISTRIBUTION_CAPTURE_FAILED


def test_snapshot_schema_error_has_specific_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def invalid(_self: u4.ProtectedObjectSnapshotV3) -> dict[str, object]:
        raise u4.SnapshotSchemaError("synthetic")

    monkeypatch.setattr(u4.ProtectedObjectSnapshotV3, "to_mapping", invalid)
    result = u4.capture_protected_object_snapshot(_environment(tmp_path), command_runner=Runner())
    assert result.diagnostic.failure is not None
    assert result.diagnostic.failure.code == u4.SNAPSHOT_SCHEMA_FAILED


def test_unexpected_exception_is_not_ordinary_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(_root: Path) -> tuple[int, int, int, str, str]:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(u4, "_tree_identity", unexpected)
    result = u4.capture_protected_object_snapshot(_environment(tmp_path), command_runner=Runner())
    assert result.diagnostic.failure is not None
    assert result.diagnostic.failure.code == u4.UNEXPECTED_CAPTURE_EXCEPTION
    assert result.diagnostic.exception_class == "RuntimeError"


def test_every_failure_has_complete_diagnostic(tmp_path: Path) -> None:
    target = _bare_target(tmp_path)
    result = u4.capture_protected_object_snapshot(target, command_runner=Runner())
    failure = result.diagnostic.failure
    assert failure is not None
    assert failure.code and failure.stage and failure.assertion
    assert result.diagnostic.diagnostic_details_digest
    assert result.diagnostic.exception_message_digest


def test_present_capture_has_failure_null(tmp_path: Path) -> None:
    result = u4.capture_protected_object_snapshot(_environment(tmp_path), command_runner=Runner())
    assert result.snapshot.state == "present"
    assert result.diagnostic.to_mapping()["failure"] is None


def test_non_present_diagnostic_cannot_have_empty_failure() -> None:
    with pytest.raises(u4.SnapshotSchemaError, match="requires a specific failure"):
        u4.ProtectedObjectCaptureDiagnosticV1(
            object_id="project_mlff",
            capture_state="invalid",
            failure=None,
            launcher_classification="unknown",
            launcher_relative_path="bin/python",
            symlink_depth=0,
            resolved_target_inside_root=False,
            command_evidence=(),
            exception_class="none",
            exception_message_digest=_SHA,
            diagnostic_details_digest=_SHA,
        )


def test_u3_rejects_but_u4_accepts_same_conda_symlink_fixture(tmp_path: Path) -> None:
    target = _environment(tmp_path)
    old = u3.CaptureTarget(target.object_id, target.root, target.conda_executable)

    def old_runner(argv: Sequence[str], environment: Mapping[str, str]) -> u3.CommandResult:
        value = Runner()(argv, environment)
        return u3.CommandResult(value.returncode, value.stdout, value.stderr)

    old_result = u3.capture_protected_object_snapshot(old, command_runner=old_runner)
    new_result = u4.capture_protected_object_snapshot(target, command_runner=Runner())
    assert old_result.state == "invalid"
    assert new_result.snapshot.state == "present"
    retained = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/PHASE9B_UNIFIED_ENVIRONMENT_V003_MANIFEST.json"
        ).read_bytes()
    )
    assert retained["status"] == "failed_before_environment_creation"


def test_a_b_capture_is_stable_and_observation_metadata_is_excluded(tmp_path: Path) -> None:
    target = _environment(tmp_path)
    first = u4.capture_protected_object_snapshot(target, command_runner=Runner())
    second = u4.capture_protected_object_snapshot(target, command_runner=Runner())
    before = u4.build_observation_receipt(
        first,
        observation_phase="qualification_a",
        attempt_id="attempt-u4",
        observed_at_ns=1,
        observer_pid=10,
    )
    after = u4.build_observation_receipt(
        second,
        observation_phase="qualification_b",
        attempt_id="attempt-u4",
        observed_at_ns=999,
        observer_pid=999,
    )
    assert before.to_mapping() != after.to_mapping()
    assert before.projection_sha256 == after.projection_sha256
    assert u4.compare_observations(before, after).passed is True


def test_symlink_chain_change_changes_projection(tmp_path: Path) -> None:
    target = _environment(tmp_path)
    first = u4.capture_protected_object_snapshot(target, command_runner=Runner())
    logical = target.root / "bin/python"
    logical.unlink()
    logical.symlink_to("python3.11")
    second = u4.capture_protected_object_snapshot(target, command_runner=Runner())
    assert (
        u4.build_stable_projection(first.snapshot).sha256()
        != u4.build_stable_projection(second.snapshot).sha256()
    )


def test_resolved_executable_change_changes_projection(tmp_path: Path) -> None:
    target = _environment(tmp_path)
    first = u4.capture_protected_object_snapshot(target, command_runner=Runner())
    _write_executable(target.root / "bin/python3.11", b"changed executable")
    second = u4.capture_protected_object_snapshot(target, command_runner=Runner())
    assert (
        u4.build_stable_projection(first.snapshot).sha256()
        != u4.build_stable_projection(second.snapshot).sha256()
    )


def test_diagnostic_does_not_enter_projection(tmp_path: Path) -> None:
    result = u4.capture_protected_object_snapshot(_environment(tmp_path), command_runner=Runner())
    before = u4.build_stable_projection(result.snapshot).sha256()
    changed = replace(result.diagnostic, diagnostic_details_digest="b" * 64)
    assert changed.to_mapping() != result.diagnostic.to_mapping()
    assert u4.build_stable_projection(result.snapshot).sha256() == before


def test_observation_receipt_cannot_be_used_as_equality_identity(tmp_path: Path) -> None:
    result = u4.capture_protected_object_snapshot(_environment(tmp_path), command_runner=Runner())
    observation = u4.build_observation_receipt(
        result, observation_phase="qualification_a", attempt_id="attempt-u4"
    )
    with pytest.raises(u4.SnapshotSchemaError, match="typed"):
        u4.compare_observations(  # type: ignore[arg-type]
            observation.to_mapping(), observation.to_mapping()
        )


def test_qualification_requires_all_six_present(tmp_path: Path) -> None:
    targets = [
        _environment(tmp_path, object_id=object_id)
        for object_id in sorted(u4.U4_PROTECTED_OBJECT_IDS)
    ]
    receipt = u4.qualify_measurement_system(
        targets,
        attempt_id="attempt-phase9b-unified-v004",
        helper_source_sha256=_SHA,
        command_runner=Runner(),
        clock_ns=iter(range(1, 13)).__next__,
        observer_pid=7,
    )
    assert receipt.all_passed is True
    assert all(
        row.snapshot_a_state == row.snapshot_b_state == "present" for row in receipt.object_results
    )
    assert all(
        row.diagnostic_a_failure_code == row.diagnostic_b_failure_code == u4.NO_FAILURE
        for row in receipt.object_results
    )


def test_mutation_guards_are_present_in_source() -> None:
    source = Path(u4.__file__).read_text(encoding="utf-8")
    assert "if python.is_symlink()" not in source
    assert "_relative_inside(root, candidate)" in source
    assert "_assert_resolution_stable(target, resolution)" in source
    assert "UNEXPECTED_CAPTURE_EXCEPTION" in source
    assert 'payload.pop("resolved_device")' in source
    assert 'payload.pop("resolved_inode")' in source
    assert "symlink_chain_digest" in source


def test_u4_module_is_outside_runner_source_closure() -> None:
    from nhc_deprot_ranker.quantum import two_endpoint

    assert (
        "nhc_deprot_ranker/preparation/phase9b_u4_metrology.py"
        not in two_endpoint._RUNNER_SOURCE_RELATIVE_PATHS  # pyright: ignore[reportPrivateUsage]
    )


def test_public_u4_failure_is_closed_and_observability_limit_is_retained() -> None:
    repository = Path(__file__).resolve().parents[1]

    def load(name: str) -> dict[str, object]:
        value = json.loads((repository / "docs" / name).read_bytes())
        assert isinstance(value, dict)
        return value

    manifest = load("PHASE9B_UNIFIED_ENVIRONMENT_V004_MANIFEST.json")
    qualification = load("PHASE9B_U4_MEASUREMENT_QUALIFICATION_RECEIPT.json")
    diagnostics = load("PHASE9B_U4_CAPTURE_DIAGNOSTICS.json")
    capability = load("PHASE9B_UNIFIED_ENVIRONMENT_V004_CAPABILITY.json")

    def assert_failed(candidate: dict[str, object]) -> None:
        assert candidate["status"] == "failed_before_environment_creation"
        resources = candidate["resources"]
        assert isinstance(resources, dict)
        assert set(resources.values()) == {"absent", True}
        identity = candidate["identity"]
        assert isinstance(identity, dict)
        assert identity["unified_execution_environment_identity_v4_issued"] is False
        assert identity["environment_canonical_sha256"] is None

    assert_failed(manifest)
    assert qualification["all_passed"] is False
    helper_sha256 = hashlib.sha256(Path(u4.__file__).read_bytes()).hexdigest()
    assert qualification["helper_source_sha256"] == helper_sha256
    rows = qualification["object_results"]
    assert isinstance(rows, list) and len(rows) == 6
    assert all(row["snapshot_a_state"] == row["snapshot_b_state"] == "invalid" for row in rows)
    assert all(
        row["diagnostic_a_failure_code"]
        == row["diagnostic_b_failure_code"]
        == u4.CONDA_EXPLICIT_FAILED
        for row in rows
    )
    assert diagnostics["portable_diagnostic_complete"] is False
    assert diagnostics["failure_stage"] == "not_portable_in_q4_summary"
    assert capability["property_reads"] == 0
    assert capability["aimnet2ase_calculate_calls"] == 0

    mutation = deepcopy(manifest)
    mutation["status"] = "validated"
    with pytest.raises(AssertionError):
        assert_failed(mutation)
