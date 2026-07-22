from __future__ import annotations

import importlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from nhc_deprot_ranker.data.provenance import sha256_file
from nhc_deprot_ranker.quantum import two_endpoint as runner
from nhc_deprot_ranker.quantum import worker


def _write_xyz(path: Path, atoms: list[tuple[str, float, float, float]]) -> None:
    lines = [str(len(atoms)), "synthetic Phase 8A protocol fixture"]
    lines.extend(f"{element} {x} {y} {z}" for element, x, y, z in atoms)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_request(root: Path, *, execution_authorized: bool = True) -> Path:
    root.mkdir(parents=True)
    _write_xyz(root / "cation.xyz", [("C", 0.0, 0.0, 0.0), ("H", 0.0, 0.0, 1.0)])
    _write_xyz(root / "neutral.xyz", [("C", 0.0, 0.0, 0.1)])
    payload = {
        "schema_version": runner.REQUEST_SCHEMA_VERSION,
        "request_id": "phase8a-protocol-001",
        "inchikey": "IJWCXRPLHNQISE-UHFFFAOYSA-N",
        "execution_authorized": execution_authorized,
        "timeout_seconds": 30,
        "runner_source_sha256": runner.current_runner_source_sha256(),
        "protocol": runner.LOCKED_PROTOCOL,
        "endpoints": {
            "cation": {
                "xyz_path": "cation.xyz",
                "xyz_sha256": sha256_file(root / "cation.xyz"),
                "charge": 1,
                "multiplicity": 1,
            },
            "neutral": {
                "xyz_path": "neutral.xyz",
                "xyz_sha256": sha256_file(root / "neutral.xyz"),
                "charge": 0,
                "multiplicity": 1,
            },
        },
    }
    request_path = root / "request.json"
    request_path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return request_path


class _DeterministicBackend:
    def optimize(
        self,
        *,
        endpoint: runner.EndpointName,
        geometry: runner.XYZGeometry,
        charge: int,
        multiplicity: int,
        strategy: runner.SCFStrategy,
        deadline_monotonic: float,
    ) -> runner.BackendOptimizationResult:
        del charge, multiplicity, strategy, deadline_monotonic
        return runner.BackendOptimizationResult(
            geometry=geometry,
            geometry_converged=True,
            scf_converged=True,
            last_energy_hartree=-100.0 if endpoint == "cation" else -99.0,
        )

    def final_scf(
        self,
        *,
        endpoint: runner.EndpointName,
        geometry: runner.XYZGeometry,
        charge: int,
        multiplicity: int,
        strategy: runner.SCFStrategy,
        deadline_monotonic: float,
    ) -> runner.BackendSCFResult:
        del geometry, charge, multiplicity, strategy, deadline_monotonic
        return runner.BackendSCFResult(
            converged=True,
            energy_hartree=-100.125 if endpoint == "cation" else -99.875,
        )


@dataclass(frozen=True)
class _FakeSupervisionResult:
    outcome: str
    returncode: int | None
    timed_out: bool = False
    term_sent: bool = False
    kill_sent: bool = False
    orphan_descendants_detected: bool = False
    process_started: bool = True
    group_cleanup_confirmed: bool = True
    direct_child_reaped: bool = True
    stdout_truncated: bool = False
    stderr_truncated: bool = False


def _argument_value(argv: Sequence[str], option: str) -> str:
    index = argv.index(option)
    return argv[index + 1]


def test_public_gate_is_before_request_supervisor_import_spawn_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def forbidden_request(path: Path) -> runner.TwoEndpointRequest:
        del path
        calls.append("request")
        raise AssertionError("request must not be read")

    def forbidden_import(name: str, package: str | None = None) -> object:
        del name, package
        calls.append("import")
        raise AssertionError("supervisor or compute module must not be imported")

    monkeypatch.setattr(runner, "load_two_endpoint_request", forbidden_request)
    monkeypatch.setattr(importlib, "import_module", forbidden_import)
    with pytest.raises(runner.ExecutionNotAuthorizedError):
        runner.run_two_endpoint(tmp_path / "missing.json", tmp_path / "output")
    assert calls == []
    assert not (tmp_path / "output").exists()


def test_worker_main_gate_is_before_argv_request_import_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    def closed_gate() -> None:
        events.append("gate")
        raise runner.ExecutionNotAuthorizedError("synthetic closed source gate")

    def forbidden_parse(argv: Sequence[str] | None) -> object:
        del argv
        events.append("argv")
        raise AssertionError("argv must not be inspected")

    monkeypatch.setattr(worker.runner, "_ensure_execution_authorized", closed_gate)
    monkeypatch.setattr(worker, "_parse_arguments", forbidden_parse)
    with pytest.raises(runner.ExecutionNotAuthorizedError):
        worker.main(["--output-root", str(tmp_path / "output")])
    assert events == ["gate"]
    assert not (tmp_path / "output").exists()


def test_worker_request_gate_is_before_backend_construction_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_path = _write_request(tmp_path / "request", execution_authorized=False)
    monkeypatch.setattr(worker.runner, "_ensure_execution_authorized", lambda: None)

    def forbidden_backend() -> object:
        raise AssertionError("backend must not be constructed")

    monkeypatch.setattr(worker.runner, "PySCFBackend", forbidden_backend)
    output = tmp_path / "output"
    with pytest.raises(runner.ExecutionNotAuthorizedError):
        worker.main(
            [
                "--request-path",
                str(request_path),
                "--output-root",
                str(output),
                "--attempt-id",
                "attempt-request-gate",
            ]
        )
    assert not output.exists()


def test_runner_source_hash_canonically_binds_full_pre_gate_import_chain() -> None:
    source_root = Path(runner.__file__).resolve().parents[2]
    names = (
        "nhc_deprot_ranker/__init__.py",
        "nhc_deprot_ranker/constants.py",
        "nhc_deprot_ranker/data/__init__.py",
        "nhc_deprot_ranker/data/provenance.py",
        "nhc_deprot_ranker/quantum/__init__.py",
        "nhc_deprot_ranker/quantum/two_endpoint.py",
        "nhc_deprot_ranker/quantum/worker.py",
        "nhc_deprot_ranker/quantum/process_supervisor.py",
    )
    sources = {name: (source_root / name).read_bytes() for name in names}
    baseline = runner._canonical_runner_source_sha256(  # pyright: ignore[reportPrivateUsage]
        sources
    )
    assert baseline == runner.current_runner_source_sha256()
    for name in names:
        mutated = dict(sources)
        mutated[name] += b"\n# synthetic source drift\n"
        assert (
            runner._canonical_runner_source_sha256(  # pyright: ignore[reportPrivateUsage]
                mutated
            )
            != baseline
        )
    with pytest.raises(ValueError, match="exact canonical file set"):
        runner._canonical_runner_source_sha256(  # pyright: ignore[reportPrivateUsage]
            {**sources, "unexpected.py": b"pass\n"}
        )


def test_mock_supervised_worker_is_parent_validated_then_published_as_exact_six_files(
    tmp_path: Path,
) -> None:
    request_path = _write_request(tmp_path / "request")
    request = runner.load_two_endpoint_request(request_path)
    output = tmp_path / "output"
    attempt_id = "attempt-supervised-success"
    seen: dict[str, object] = {}

    def fake_supervisor(
        argv: Sequence[str],
        *,
        policy: object,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> _FakeSupervisionResult:
        seen.update({"argv": list(argv), "policy": policy, "cwd": cwd, "env": env})
        worker_request = runner.load_two_endpoint_request(
            Path(_argument_value(argv, "--request-path"))
        )
        worker_output = Path(_argument_value(argv, "--output-root"))
        worker_attempt = _argument_value(argv, "--attempt-id")
        runner._execute_validated_request(  # pyright: ignore[reportPrivateUsage]
            worker_request,
            worker_output,
            backend=_DeterministicBackend(),
            attempt_id=worker_attempt,
        )
        assert not (output / "_SUCCESS").exists()
        assert not (output / "attempts" / attempt_id).exists()
        return _FakeSupervisionResult(outcome="clean", returncode=0)

    policy = object()
    result = runner._execute_supervised_request(  # pyright: ignore[reportPrivateUsage]
        request,
        output,
        run_supervised=fake_supervisor,
        supervision_policy=policy,
        attempt_id=attempt_id,
        python_executable="/synthetic/python",
    )
    assert result.attempt_id == attempt_id
    assert result.resumed is False
    assert {path.name for path in output.iterdir()} == {"_SUCCESS", "success.json", "attempts"}
    attempt = output / "attempts" / attempt_id
    assert {path.name for path in attempt.iterdir()} == {
        "_ATTEMPT_SUCCESS",
        "cation.json",
        "cation.optimized.xyz",
        "neutral.json",
        "neutral.optimized.xyz",
        "result.json",
    }
    assert seen["policy"] is policy
    assert seen["cwd"] == Path(runner.__file__).resolve().parents[2]
    assert seen["argv"][0] == "/synthetic/python"  # type: ignore[index]
    assert seen["argv"][1:4] == ["-I", "-B", "-c"]  # type: ignore[index]
    environment = seen["env"]
    assert isinstance(environment, dict)
    assert "PYTHONPATH" not in environment
    assert "PYTHONHOME" not in environment
    assert "PYTHONSTARTUP" not in environment
    assert not list(tmp_path.glob(f".worker-{attempt_id}-*"))


@pytest.mark.parametrize(
    ("supervision", "error_type", "exit_code"),
    [
        (
            _FakeSupervisionResult(
                outcome="timeout",
                returncode=124,
                timed_out=True,
                term_sent=True,
                kill_sent=True,
            ),
            "HardWallTimeoutError",
            124,
        ),
        (
            _FakeSupervisionResult(outcome="nonzero", returncode=7),
            "WorkerExitError",
            1,
        ),
    ],
)
def test_timeout_and_nonzero_publish_only_atomic_failure_after_supervisor_returns(
    tmp_path: Path,
    supervision: _FakeSupervisionResult,
    error_type: str,
    exit_code: int,
) -> None:
    request_path = _write_request(tmp_path / "request")
    request = runner.load_two_endpoint_request(request_path)
    output = tmp_path / "output"
    attempt_id = "attempt-supervised-failure"
    returned = False

    def fake_supervisor(
        argv: Sequence[str],
        *,
        policy: object,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> _FakeSupervisionResult:
        del policy, cwd, env
        worker_output = Path(_argument_value(argv, "--output-root"))
        (worker_output / "partial-endpoint.dat").write_text("partial\n", encoding="utf-8")
        assert not (output / "attempts" / attempt_id).exists()
        nonlocal returned
        returned = True
        return supervision

    with pytest.raises(runner.TwoEndpointRunError) as exc_info:
        runner._execute_supervised_request(  # pyright: ignore[reportPrivateUsage]
            request,
            output,
            run_supervised=fake_supervisor,
            supervision_policy=object(),
            attempt_id=attempt_id,
        )
    assert returned is True
    assert exc_info.value.exit_code == exit_code
    attempt = output / "attempts" / attempt_id
    assert {path.name for path in attempt.iterdir()} == {"failure.json"}
    failure = json.loads((attempt / "failure.json").read_text(encoding="utf-8"))
    assert failure["error_type"] == error_type
    assert failure["exit_code"] == exit_code
    assert failure["supervision"]["outcome"] == supervision.outcome
    assert not (output / "_SUCCESS").exists()
    assert not (output / "success.json").exists()
    assert not list(tmp_path.glob(f".worker-{attempt_id}-*"))


def test_clean_exit_with_invalid_worker_state_is_protocol_failure_not_success(
    tmp_path: Path,
) -> None:
    request_path = _write_request(tmp_path / "request")
    request = runner.load_two_endpoint_request(request_path)
    output = tmp_path / "output"
    attempt_id = "attempt-invalid-worker-state"

    def fake_supervisor(
        argv: Sequence[str],
        *,
        policy: object,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> _FakeSupervisionResult:
        del policy, cwd, env
        worker_output = Path(_argument_value(argv, "--output-root"))
        (worker_output / "untrusted-success.txt").write_text("success\n", encoding="utf-8")
        return _FakeSupervisionResult(outcome="clean", returncode=0)

    with pytest.raises(runner.TwoEndpointRunError) as exc_info:
        runner._execute_supervised_request(  # pyright: ignore[reportPrivateUsage]
            request,
            output,
            run_supervised=fake_supervisor,
            supervision_policy=object(),
            attempt_id=attempt_id,
        )
    assert exc_info.value.exit_code == 1
    attempt = output / "attempts" / attempt_id
    assert {path.name for path in attempt.iterdir()} == {"failure.json"}
    failure = json.loads((attempt / "failure.json").read_text(encoding="utf-8"))
    assert failure["error_type"] == "WorkerProtocolError"
    assert not (output / "_SUCCESS").exists()


def test_unconfirmed_cleanup_never_publishes_or_removes_worker_scratch(
    tmp_path: Path,
) -> None:
    request_path = _write_request(tmp_path / "request")
    request = runner.load_two_endpoint_request(request_path)
    output = tmp_path / "output"
    attempt_id = "attempt-unconfirmed-cleanup"

    def unsafe_supervisor(
        argv: Sequence[str],
        *,
        policy: object,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> _FakeSupervisionResult:
        del policy, cwd, env
        worker_output = Path(_argument_value(argv, "--output-root"))
        (worker_output / "still-owned-by-unconfirmed-worker.dat").write_text(
            "partial\n", encoding="utf-8"
        )
        return _FakeSupervisionResult(
            outcome="supervision_error",
            returncode=1,
            timed_out=True,
            kill_sent=True,
            group_cleanup_confirmed=False,
            direct_child_reaped=True,
        )

    with pytest.raises(runner.TwoEndpointRunError) as exc_info:
        runner._execute_supervised_request(  # pyright: ignore[reportPrivateUsage]
            request,
            output,
            run_supervised=unsafe_supervisor,
            supervision_policy=object(),
            attempt_id=attempt_id,
        )
    assert exc_info.value.exit_code == 1
    assert exc_info.value.attempt_dir is None
    assert not (output / "_SUCCESS").exists()
    assert not (output / "success.json").exists()
    assert not (output / "attempts" / attempt_id).exists()
    scratch = list(tmp_path.glob(f".worker-{attempt_id}-*"))
    assert len(scratch) == 1
    assert (scratch[0] / "still-owned-by-unconfirmed-worker.dat").is_file()
