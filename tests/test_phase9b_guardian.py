"""Phase 9B guardian transaction regressions.

No server, no AIMNet2, no PySCF, no energies, no labels. Permits are real bytes
on tmp_path and the consumption transaction is the shipped one, so "irreversibly
consumed" is a fact here rather than a fake's assertion. The spawn seam is
injected for the transaction tests, and separately the *shipped* spawn path is
executed for real against a trivial child so the detachment semantics under test
are the ones that ship.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from nhc_deprot_ranker.preparation.phase9b_bundle import (
    PAYLOAD_MANIFEST_RELATIVE,
    build_route_payload,
    build_route_request,
)
from nhc_deprot_ranker.quantum import phase9b_guardian as gd
from nhc_deprot_ranker.quantum import phase9b_supervisor as sup
from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE
from nhc_deprot_ranker.quantum.phase9b_guardian import (
    ConsumptionState,
    GuardianState,
    Phase9BGuardianError,
    Phase9BGuardianNotAuthorizedError,
    SpawnedProcess,
    await_spawn_acknowledgement,
    build_supervisor_argv,
    build_worker_handshake_binding,
    consumption_receipt_payload,
    consumption_receipt_sha256,
    launch_receipt_payload,
    launch_receipt_sha256,
    run_phase9b_guardian,
    supervisor_environment,
    validate_capability_reach,
    write_receipt_exclusively,
)
from nhc_deprot_ranker.quantum.phase9b_permit import (
    CONSUMED_RELATIVE,
    READY_RELATIVE,
    REMOTE_ROOT_RELATIVE,
    REQUEST_RELATIVE,
    ROUTE_ASSISTED,
    ROUTE_ATTEMPT_IDS,
    ROUTE_DIRECT,
    Phase9BPermitConsumedError,
    Phase9BPermitValidationError,
    consume_phase9b_permit,
    render_phase9b_permit,
)
from nhc_deprot_ranker.quantum.phase9b_resources import (
    PHASE9B_RESOURCES,
    phase9b_resources_payload,
    phase9b_resources_sha256,
)
from nhc_deprot_ranker.quantum.two_endpoint import (
    LOCKED_PROTOCOL,
    current_runner_source_sha256,
)

_TIMEOUT = int(PHASE9B_RESOURCES["hard_wall_timeout_seconds"])  # type: ignore[call-overload]
_AFFINITY = str(PHASE9B_RESOURCES["cpu_affinity"])
_READY_MODE = 0o400


def _endpoint_xyz(*, hydrogens: int, spacing: float = 1.4) -> bytes:
    order = ["C"] * 8 + ["N"] + ["F"] * 5 + ["C"] + ["N", "N"] + ["F"] * 4 + ["H"] * hydrogens
    lines = [str(len(order)), "phase9b synthetic endpoint"]
    for index, element in enumerate(order):
        lines.append(f"{element} {index * spacing:.6f} {index * spacing / 2:.6f} 0.000000")
    return ("\n".join(lines) + "\n").encode()


_CATION_XYZ = _endpoint_xyz(hydrogens=5)
_NEUTRAL_XYZ = _endpoint_xyz(hydrogens=4)
TEST_PROFILE = dataclasses.replace(
    PHASE9B_CANDIDATE,
    cation_xyz_sha256=hashlib.sha256(_CATION_XYZ).hexdigest(),
    neutral_xyz_sha256=hashlib.sha256(_NEUTRAL_XYZ).hexdigest(),
)


def _build_route(
    tmp_path: Path,
    route: str,
    *,
    place_ready: bool = True,
    place_consumed: bool = False,
    ready_mode: int = _READY_MODE,
    ready_bytes: bytes | None = None,
    symlink_ready: bool = False,
) -> tuple[Path, dict[str, str]]:
    """Materialize one route's run root with real request, manifest, and permit."""

    request = build_route_request(
        route=route,
        runner_source_sha256=current_runner_source_sha256(),
        protocol=LOCKED_PROTOCOL,
        cation_xyz_sha256=TEST_PROFILE.cation_xyz_sha256,
        neutral_xyz_sha256=TEST_PROFILE.neutral_xyz_sha256,
        profile=TEST_PROFILE,
    )
    payload = build_route_payload(request, profile=TEST_PROFILE)
    permit_bytes = render_phase9b_permit(
        route=route,
        project_root=tmp_path.as_posix(),
        request_sha256=request.request_sha256,
        runner_source_sha256=current_runner_source_sha256(),
        payload_manifest_sha256=payload.manifest_sha256,
        cation_xyz_sha256=TEST_PROFILE.cation_xyz_sha256,
        neutral_xyz_sha256=TEST_PROFILE.neutral_xyz_sha256,
        resources=phase9b_resources_payload(),
        profile=TEST_PROFILE,
    )
    permit = json.loads(permit_bytes.decode())
    run_root = tmp_path / REMOTE_ROOT_RELATIVE / route
    (run_root / "input" / "xyz").mkdir(parents=True)
    (run_root / "private").mkdir(parents=True)
    (run_root / REQUEST_RELATIVE).write_bytes(request.request_bytes)
    (run_root / PAYLOAD_MANIFEST_RELATIVE).write_bytes(payload.manifest_bytes)
    (run_root / "input" / "xyz" / "cation.xyz").write_bytes(_CATION_XYZ)
    (run_root / "input" / "xyz" / "neutral.xyz").write_bytes(_NEUTRAL_XYZ)

    ready = run_root / READY_RELATIVE
    if symlink_ready:
        target = run_root / "private" / "elsewhere.json"
        target.write_bytes(permit_bytes)
        ready.symlink_to(target)
    elif place_ready:
        ready.write_bytes(ready_bytes if ready_bytes is not None else permit_bytes)
        ready.chmod(ready_mode)
    if place_consumed:
        consumed = run_root / CONSUMED_RELATIVE
        consumed.write_bytes(permit_bytes)
        consumed.chmod(0o400)

    values = {
        "--route": route,
        "--attempt-id": ROUTE_ATTEMPT_IDS[route],
        "--request-path": permit["paths"]["request_path"],
        "--output-root": permit["paths"]["output_root"],
        "--permit-path": permit["paths"]["ready_path"],
        "--expected-request-sha256": request.request_sha256,
        "--expected-payload-manifest-sha256": payload.manifest_sha256,
        "--expected-permit-sha256": hashlib.sha256(permit_bytes).hexdigest(),
        "--expected-runner-source-sha256": current_runner_source_sha256(),
        "--expected-resources-sha256": phase9b_resources_sha256(),
        "--gpu-index": "2",
        "--cpu-affinity": _AFFINITY,
        "--timeout-seconds": str(_TIMEOUT),
    }
    return run_root, values


def _argv(values: Mapping[str, str], **overrides: str) -> list[str]:
    merged = {**values, **overrides}
    out: list[str] = []
    for flag in sup.REQUIRED_FLAGS:
        out += [flag, merged[flag]]
    return out


def _arguments(values: Mapping[str, str], **overrides: str) -> sup.Phase9BLaunchArguments:
    return sup.parse_supervisor_argv(_argv(values, **overrides))


class _FakeSpawn:
    """Writes the supervisor's identity line the way the real supervisor would."""

    def __init__(
        self,
        *,
        pid: int = 4242,
        group: int | None = None,
        raise_error: Exception | None = None,
        identity_override: dict[str, Any] | None = None,
        write_identity: bool = True,
    ) -> None:
        self.pid = pid
        self.group = pid if group is None else group
        self.raise_error = raise_error
        self.identity_override = identity_override or {}
        self.write_identity = write_identity
        self.calls: list[tuple[str, ...]] = []
        self.env: dict[str, str] = {}

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        stdout_path: Path,
        stderr_path: Path,
    ) -> SpawnedProcess:
        del cwd
        self.calls.append(tuple(argv))
        self.env = dict(env)
        if self.raise_error is not None:
            raise self.raise_error
        stderr_path.write_bytes(b"")
        if self.write_identity:
            flags = dict(zip(argv[5::2], argv[6::2], strict=True))
            payload: dict[str, Any] = {
                "schema_version": sup.SUPERVISOR_IDENTITY_SCHEMA_VERSION,
                "supervisor_identity": "a" * 64,
                "entry": sup.CLI_ENTRY,
                "route": flags["--route"],
                "attempt_id": flags["--attempt-id"],
                "pid": self.pid,
            }
            payload.update(self.identity_override)
            stdout_path.write_bytes(json.dumps(payload, sort_keys=True).encode() + b"\n")
        else:
            stdout_path.write_bytes(b"")
        return SpawnedProcess(pid=self.pid, process_group_id=self.group, session_id=self.group)


@pytest.fixture
def _open_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    from nhc_deprot_ranker.quantum import two_endpoint

    monkeypatch.setattr(gd, "EXECUTION_AUTHORIZED", True)
    monkeypatch.setattr(two_endpoint, "EXECUTION_AUTHORIZED", True)


def _run(values: Mapping[str, str], tmp_path: Path, **kw: Any) -> gd.GuardianOutcome:
    params: dict[str, Any] = {
        "host_identity": "gpu-node",
        "project_root": tmp_path,
        "profile": TEST_PROFILE,
        "spawn": _FakeSpawn(),
        "clock": lambda: "2026-07-26T00:00:00Z",
        "monotonic": lambda: 0.0,
        "sleep": lambda _seconds: None,
    }
    params.update(kw)
    return run_phase9b_guardian(_arguments(values), **params)


# --- gates -------------------------------------------------------------------


def test_the_source_gate_is_closed_and_a_real_transaction_refuses(tmp_path: Path) -> None:
    assert gd.EXECUTION_AUTHORIZED is False
    source = Path(gd.__file__).read_text(encoding="utf-8")
    assert "EXECUTION_AUTHORIZED: Final[bool] = False" in source
    _, values = _build_route(tmp_path, ROUTE_DIRECT)
    with pytest.raises(Phase9BGuardianNotAuthorizedError, match="not authorized"):
        run_phase9b_guardian(
            _arguments(values), host_identity="h", project_root=tmp_path, profile=TEST_PROFILE
        )


def test_the_guardian_is_inside_the_runner_source_closure() -> None:
    from nhc_deprot_ranker.quantum import two_endpoint

    closure = two_endpoint._RUNNER_SOURCE_RELATIVE_PATHS
    assert "nhc_deprot_ranker/quantum/phase9b_guardian.py" in closure


def test_the_guardian_reimplements_no_supervision() -> None:
    """It consumes, hands off, spawns.  Timeouts and reaping stay elsewhere."""

    tree = ast.parse(Path(gd.__file__).read_text(encoding="utf-8"))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for primitive in ("killpg", "waitpid", "waitid", "wait", "terminate", "send_signal"):
        assert primitive not in called, primitive
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"torch", "ase", "aimnet", "pyscf", "signal"})


# --- argv --------------------------------------------------------------------


def test_missing_repeated_and_unknown_argv_are_refused(tmp_path: Path) -> None:
    _, values = _build_route(tmp_path, ROUTE_DIRECT)
    full = _argv(values)
    with pytest.raises(sup.Phase9BArgumentError, match="is missing"):
        sup.parse_supervisor_argv(full[:-2])
    with pytest.raises(sup.Phase9BArgumentError, match="repeated"):
        sup.parse_supervisor_argv([*full, "--route", ROUTE_ASSISTED])
    with pytest.raises(sup.Phase9BArgumentError, match="not whitelisted"):
        sup.parse_supervisor_argv([*full, "--force", "1"])


# --- permit preconditions ----------------------------------------------------


def test_a_missing_ready_permit_stops_before_consumption(_open_gates: None, tmp_path: Path) -> None:
    _, values = _build_route(tmp_path, ROUTE_DIRECT, place_ready=False)
    spawn = _FakeSpawn()
    with pytest.raises(sup.Phase9BSupervisorError, match="ready permit is missing"):
        _run(values, tmp_path, spawn=spawn)
    assert spawn.calls == []


def test_an_existing_consumed_permit_stops_before_consumption(
    _open_gates: None, tmp_path: Path
) -> None:
    _, values = _build_route(tmp_path, ROUTE_DIRECT, place_consumed=True)
    spawn = _FakeSpawn()
    with pytest.raises(Phase9BGuardianError, match="never restored"):
        _run(values, tmp_path, spawn=spawn)
    assert spawn.calls == []


def test_consumption_is_irreversible_and_leaves_no_ready_permit(tmp_path: Path) -> None:
    run_root, values = _build_route(tmp_path, ROUTE_DIRECT)
    ready = run_root / READY_RELATIVE
    consumed_path = run_root / CONSUMED_RELATIVE
    assert ready.is_file() and not consumed_path.exists()

    consumed = consume_phase9b_permit(
        ready,
        expected_permit_sha256=values["--expected-permit-sha256"],
        expected_request_sha256=values["--expected-request-sha256"],
        expected_runner_source_sha256=values["--expected-runner-source-sha256"],
        expected_payload_manifest_sha256=values["--expected-payload-manifest-sha256"],
        profile=TEST_PROFILE,
    )
    assert not ready.exists()
    assert consumed_path.is_file()
    assert consumed_path.stat().st_mode & 0o777 == 0o400
    assert consumed.consumed_sha256 == values["--expected-permit-sha256"]
    assert hashlib.sha256(consumed_path.read_bytes()).hexdigest() == consumed.consumed_sha256


def test_a_second_consumption_of_the_same_permit_is_refused(tmp_path: Path) -> None:
    run_root, values = _build_route(tmp_path, ROUTE_DIRECT)
    ready = run_root / READY_RELATIVE
    kw = {
        "expected_permit_sha256": values["--expected-permit-sha256"],
        "expected_request_sha256": values["--expected-request-sha256"],
        "expected_runner_source_sha256": values["--expected-runner-source-sha256"],
        "expected_payload_manifest_sha256": values["--expected-payload-manifest-sha256"],
        "profile": TEST_PROFILE,
    }
    consume_phase9b_permit(ready, **kw)  # type: ignore[arg-type]
    # Re-place a ready permit by hand: consumption must still refuse.
    ready.write_bytes((run_root / CONSUMED_RELATIVE).read_bytes())
    ready.chmod(_READY_MODE)
    with pytest.raises(Phase9BPermitConsumedError, match="already consumed"):
        consume_phase9b_permit(ready, **kw)  # type: ignore[arg-type]


def test_consumption_refuses_a_symlink_without_following_it(tmp_path: Path) -> None:
    run_root, values = _build_route(tmp_path, ROUTE_DIRECT, place_ready=False, symlink_ready=True)
    with pytest.raises(Phase9BPermitValidationError, match="cannot be opened safely"):
        consume_phase9b_permit(
            run_root / READY_RELATIVE,
            expected_permit_sha256=values["--expected-permit-sha256"],
            expected_request_sha256=values["--expected-request-sha256"],
            expected_runner_source_sha256=values["--expected-runner-source-sha256"],
            expected_payload_manifest_sha256=values["--expected-payload-manifest-sha256"],
            profile=TEST_PROFILE,
        )
    assert not (run_root / CONSUMED_RELATIVE).exists()


def test_consumption_refuses_a_drifted_digest_without_consuming(tmp_path: Path) -> None:
    run_root, values = _build_route(tmp_path, ROUTE_DIRECT)
    with pytest.raises(Phase9BPermitValidationError, match="differs from the expected"):
        consume_phase9b_permit(
            run_root / READY_RELATIVE,
            expected_permit_sha256="9" * 64,
            expected_request_sha256=values["--expected-request-sha256"],
            expected_runner_source_sha256=values["--expected-runner-source-sha256"],
            expected_payload_manifest_sha256=values["--expected-payload-manifest-sha256"],
            profile=TEST_PROFILE,
        )
    assert (run_root / READY_RELATIVE).is_file()
    assert not (run_root / CONSUMED_RELATIVE).exists()


def test_the_shipped_primitive_uses_exclusive_create_and_never_renames() -> None:
    from nhc_deprot_ranker.quantum import one_shot_permit

    source = Path(one_shot_permit.__file__).read_text(encoding="utf-8")
    assert "os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW" in source
    assert "os.O_DIRECTORY | os.O_NOFOLLOW" in source
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    # A check-then-rename pair would be racy; exclusive create is atomic.
    assert "rename" not in called
    assert "replace" not in called
    assert "unlink" in called  # the ready file is removed, never restored


# --- the handshake -----------------------------------------------------------


def _consumed_for(tmp_path: Path, route: str) -> tuple[Any, sup.VerifiedPhase9BLaunch, Any]:
    run_root, values = _build_route(tmp_path, route)
    arguments = _arguments(values)
    verified = sup.verify_launch_arguments(arguments, profile=TEST_PROFILE)
    consumed = consume_phase9b_permit(
        run_root / READY_RELATIVE,
        expected_permit_sha256=values["--expected-permit-sha256"],
        expected_request_sha256=values["--expected-request-sha256"],
        expected_runner_source_sha256=values["--expected-runner-source-sha256"],
        expected_payload_manifest_sha256=values["--expected-payload-manifest-sha256"],
        profile=TEST_PROFILE,
    )
    return arguments, verified, consumed


@pytest.mark.parametrize("route", [ROUTE_DIRECT, ROUTE_ASSISTED])
def test_both_routes_build_a_handshake_and_reach_a_capability(tmp_path: Path, route: str) -> None:
    """Neither route may be unable to obtain its own capability."""

    _, verified, consumed = _consumed_for(tmp_path / route, route)
    binding = build_worker_handshake_binding(
        verified=verified, consumed=consumed, profile=TEST_PROFILE
    )
    assert binding.route == route
    assert binding.attempt_id == ROUTE_ATTEMPT_IDS[route]
    assert binding.electron_count == TEST_PROFILE.electron_count
    assert binding.resources_sha256 == phase9b_resources_sha256()
    assert binding.cpu_affinity == _AFFINITY
    assert binding.timeout_seconds == _TIMEOUT
    validate_capability_reach(binding)


def test_a_crossed_handshake_and_permit_is_refused(tmp_path: Path) -> None:
    """direct handshake + assisted permit, and the reverse."""

    _, direct_verified, direct_consumed = _consumed_for(tmp_path / "d", ROUTE_DIRECT)
    _, assisted_verified, assisted_consumed = _consumed_for(tmp_path / "a", ROUTE_ASSISTED)
    with pytest.raises(Phase9BGuardianError, match="another route"):
        build_worker_handshake_binding(
            verified=direct_verified, consumed=assisted_consumed, profile=TEST_PROFILE
        )
    with pytest.raises(Phase9BGuardianError, match="another route"):
        build_worker_handshake_binding(
            verified=assisted_verified, consumed=direct_consumed, profile=TEST_PROFILE
        )


def test_an_unregistered_attempt_cannot_reach_a_capability(tmp_path: Path) -> None:
    _, verified, consumed = _consumed_for(tmp_path, ROUTE_DIRECT)
    binding = build_worker_handshake_binding(
        verified=verified, consumed=consumed, profile=TEST_PROFILE
    )
    for broken, match in (
        (dataclasses.replace(binding, attempt_id="attempt-phase8b-qxh-v001"), "does not cover"),
        (dataclasses.replace(binding, attempt_id="attempt-unregistered"), "does not cover"),
        (dataclasses.replace(binding, capability_identity_key="nope"), "no frozen capability"),
        (dataclasses.replace(binding, electron_count=120), "another candidate"),
        (dataclasses.replace(binding, resources_sha256="3" * 64), "another resource budget"),
    ):
        with pytest.raises(Phase9BGuardianError, match=match):
            validate_capability_reach(broken)


# --- the full transaction ----------------------------------------------------


@pytest.mark.parametrize("route", [ROUTE_DIRECT, ROUTE_ASSISTED])
def test_a_clean_transaction_consumes_then_spawns_then_acknowledges(
    _open_gates: None, tmp_path: Path, route: str
) -> None:
    root = tmp_path / route
    run_root, values = _build_route(root, route)
    spawn = _FakeSpawn(pid=4242)
    outcome = _run(values, root, spawn=spawn)

    assert outcome.consumption.state is ConsumptionState.CONSUMED
    assert outcome.launch.state is GuardianState.PERMIT_CONSUMED_SPAWNED
    assert outcome.launch.failure_reason is None
    assert outcome.launch.supervisor_pid == 4242
    assert outcome.launch.supervisor_process_group_id == 4242
    assert outcome.launch.supervisor_entry == sup.CLI_ENTRY

    # The permit really crossed the irreversible point.
    assert not (run_root / READY_RELATIVE).exists()
    assert (run_root / CONSUMED_RELATIVE).is_file()

    # Both receipts landed and re-read clean.
    consumption_path = run_root / gd.CONSUMPTION_RECEIPT_RELATIVE
    launch_path = run_root / gd.LAUNCH_RECEIPT_RELATIVE
    assert json.loads(consumption_path.read_bytes())["state"] == "consumed"
    assert json.loads(launch_path.read_bytes())["state"] == "permit_consumed_spawned"
    assert outcome.launch.receipt_sha256 == launch_receipt_sha256(outcome.launch)
    assert outcome.consumption.receipt_sha256 == consumption_receipt_sha256(outcome.consumption)

    # And the acknowledgement is what the launch control plane reads.
    ack = outcome.acknowledgement
    assert ack["entry"] == gd.GUARDIAN_ENTRY
    assert ack["supervisor_entry"] == sup.CLI_ENTRY
    assert ack["route"] == route
    assert ack["state"] == "permit_consumed_spawned"
    assert ack["permit_sha256"] == values["--expected-permit-sha256"]


def test_the_supervisor_is_spawned_only_after_the_permit_is_consumed(
    _open_gates: None, tmp_path: Path
) -> None:
    """Ordering is the whole point: nothing spawns on an unspent permit."""

    run_root, values = _build_route(tmp_path, ROUTE_DIRECT)
    observed: list[bool] = []

    def spy(argv: Sequence[str], **kw: Any) -> SpawnedProcess:
        observed.append((run_root / CONSUMED_RELATIVE).is_file())
        return _FakeSpawn()(argv, **kw)

    _run(values, tmp_path, spawn=spy)
    assert observed == [True]


def test_a_spawn_failure_after_consumption_is_terminal(_open_gates: None, tmp_path: Path) -> None:
    run_root, values = _build_route(tmp_path, ROUTE_DIRECT)
    outcome = _run(
        values, tmp_path, spawn=_FakeSpawn(raise_error=Phase9BGuardianError("no such executable"))
    )
    assert outcome.launch.state is GuardianState.PERMIT_CONSUMED_SPAWN_FAILED
    assert "spawn failed" in (outcome.launch.failure_reason or "")
    # The attempt is spent, and stays spent.
    assert not (run_root / READY_RELATIVE).exists()
    assert (run_root / CONSUMED_RELATIVE).is_file()
    assert outcome.consumption.state is ConsumptionState.CONSUMED


def test_a_spawn_that_never_acknowledges_is_indeterminate(
    _open_gates: None, tmp_path: Path
) -> None:
    run_root, values = _build_route(tmp_path, ROUTE_DIRECT)
    clock = iter([0.0, 0.0, 1000.0, 2000.0, 3000.0])
    outcome = _run(
        values,
        tmp_path,
        spawn=_FakeSpawn(write_identity=False),
        monotonic=lambda: next(clock, 9999.0),
    )
    assert outcome.launch.state is GuardianState.INDETERMINATE
    assert "unknown" in (outcome.launch.failure_reason or "")
    assert outcome.launch.supervisor_pid == 4242
    assert (run_root / CONSUMED_RELATIVE).is_file()


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"entry": "nhc_deprot_ranker.quantum.worker"}, "not the guarded supervisor"),
        ({"route": ROUTE_ASSISTED}, "another route"),
        ({"attempt_id": "attempt-other"}, "another attempt"),
        ({"supervisor_identity": "short"}, "no usable identity"),
        ({"pid": 9999}, "differs from the spawned PID"),
    ],
)
def test_a_forged_supervisor_identity_is_indeterminate(
    _open_gates: None, tmp_path: Path, override: dict[str, Any], match: str
) -> None:
    """A PID the supervisor did not claim cannot be passed off as a launch."""

    _, values = _build_route(tmp_path, ROUTE_DIRECT)
    outcome = _run(values, tmp_path, spawn=_FakeSpawn(identity_override=override))
    assert outcome.launch.state is GuardianState.INDETERMINATE
    assert match in (outcome.launch.failure_reason or "")


def test_a_spawned_process_that_is_not_its_own_session_leader_is_refused(
    _open_gates: None, tmp_path: Path
) -> None:
    """PID reuse and stray adoption both show up here."""

    _, values = _build_route(tmp_path, ROUTE_DIRECT)
    outcome = _run(values, tmp_path, spawn=_FakeSpawn(pid=4242, group=1))
    assert outcome.launch.state is GuardianState.INDETERMINATE


def test_the_transaction_never_retries_or_restores(_open_gates: None, tmp_path: Path) -> None:
    run_root, values = _build_route(tmp_path, ROUTE_DIRECT)
    spawn = _FakeSpawn(raise_error=Phase9BGuardianError("boom"))
    _run(values, tmp_path, spawn=spawn)
    assert len(spawn.calls) == 1
    assert not (run_root / READY_RELATIVE).exists()

    # A second transaction on the same route now refuses outright: the ready
    # permit is gone and the consumed one is never restored.
    with pytest.raises(sup.Phase9BSupervisorError, match="ready permit is missing"):
        _run(values, tmp_path, spawn=_FakeSpawn())


def test_the_module_offers_no_retry_resume_or_restore_entry() -> None:
    tree = ast.parse(Path(gd.__file__).read_text(encoding="utf-8"))
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    for banned in ("retry", "resume", "rollback", "restore", "backfill", "respawn"):
        assert not any(banned in name for name in names), banned


# --- environment and argv the guardian hands the supervisor ------------------


def test_the_supervisor_environment_is_closed_and_pins_the_device(tmp_path: Path) -> None:
    _, verified, consumed = _consumed_for(tmp_path, ROUTE_DIRECT)
    binding = build_worker_handshake_binding(
        verified=verified, consumed=consumed, profile=TEST_PROFILE
    )
    env = supervisor_environment(project_root=tmp_path, binding=binding)
    assert env["CUDA_VISIBLE_DEVICES"] == "2"
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["OMP_NUM_THREADS"] == str(PHASE9B_RESOURCES["computational_threads"])
    assert "LD_PRELOAD" not in env
    assert set(env) == {
        "PATH",
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
        "HF_DATASETS_OFFLINE",
        "CUDA_VISIBLE_DEVICES",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
    }


def test_the_guardian_starts_the_supervisor_and_nothing_else(tmp_path: Path) -> None:
    _, values = _build_route(tmp_path, ROUTE_DIRECT)
    argv = build_supervisor_argv(_arguments(values))
    assert argv[1:5] == ("-B", "-s", "-m", sup.CLI_ENTRY)
    assert sorted(argv[5::2]) == sorted(sup.REQUIRED_FLAGS)
    for backend in ("pyscf", "aimnet", "torch", "bash", "sh"):
        assert backend not in argv[4]


# --- receipts ----------------------------------------------------------------


def test_the_receipts_carry_every_registered_field(_open_gates: None, tmp_path: Path) -> None:
    _, values = _build_route(tmp_path, ROUTE_DIRECT)
    outcome = _run(values, tmp_path)

    consumption = consumption_receipt_payload(outcome.consumption)
    assert consumption["schema_version"] == gd.PERMIT_CONSUMPTION_RECEIPT_SCHEMA_VERSION
    for key in (
        "phase",
        "candidate_inchikey",
        "route",
        "attempt_id",
        "ready_path",
        "consumed_path",
        "permit_sha256",
        "consumed_sha256",
        "request_sha256",
        "payload_manifest_sha256",
        "runner_source_sha256",
        "resources_sha256",
        "host_identity_sha256",
        "consumed_at",
        "state",
        "receipt_sha256",
    ):
        assert key in consumption, key
    assert consumption["failure_reason"] is None

    launch = launch_receipt_payload(outcome.launch)
    assert launch["schema_version"] == gd.GUARDIAN_LAUNCH_RECEIPT_SCHEMA_VERSION
    for key in (
        "route",
        "attempt_id",
        "guardian_identity",
        "supervisor_entry",
        "supervisor_pid",
        "supervisor_process_group_id",
        "supervisor_session_id",
        "argv_sha256",
        "request_sha256",
        "payload_manifest_sha256",
        "permit_sha256",
        "runner_source_sha256",
        "resources_sha256",
        "output_root",
        "evidence_root",
        "log_root",
        "consumption_receipt_sha256",
        "spawned_at",
        "acknowledged_at",
        "state",
        "receipt_sha256",
    ):
        assert key in launch, key

    text = json.dumps({**consumption, **launch}, sort_keys=True).lower()
    for banned in ("hartree", "kcal", "energy", "force", "converged", "label", "scf"):
        assert banned not in text


def test_a_receipt_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    digest = write_receipt_exclusively(path, b"{}\n")
    assert digest == hashlib.sha256(b"{}\n").hexdigest()
    with pytest.raises(Phase9BGuardianError, match="already exists"):
        write_receipt_exclusively(path, b'{"other": 1}\n')
    assert path.read_bytes() == b"{}\n"


# --- the shipped spawn path, executed for real -------------------------------


def test_the_shipped_spawn_detaches_into_its_own_session(tmp_path: Path) -> None:
    """Runs the real spawn helper against a trivial child, not a fake.

    A fake that reimplemented ``start_new_session`` would keep passing if the real
    helper stopped detaching. This starts a genuine child and reads its session
    from the OS.
    """

    child = tmp_path / "child.py"
    child.write_text(
        "import json, os, sys\n"
        "print(json.dumps({'pid': os.getpid(), 'pgid': os.getpgid(0), "
        "'sid': os.getsid(0), 'stdin_isatty': sys.stdin.isatty()}), flush=True)\n",
        encoding="utf-8",
    )
    stdout_path = tmp_path / "out.jsonl"
    stderr_path = tmp_path / "err.log"
    spawned = gd.spawn_detached_supervisor(
        [sys.executable, "-I", "-B", str(child)],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    assert spawned.pid == spawned.process_group_id == spawned.session_id
    assert spawned.session_id != os.getsid(0)
    for _ in range(200):
        if stdout_path.stat().st_size:
            break
        subprocess.run([sys.executable, "-c", "pass"], check=False)  # yield
    observed = json.loads(stdout_path.read_text().splitlines()[0])
    assert observed["pid"] == spawned.pid
    assert observed["pgid"] == observed["sid"] == spawned.pid
    # stdin is /dev/null, so a child that reads it cannot block forever.
    assert observed["stdin_isatty"] is False
    assert stderr_path.read_bytes() == b""
    assert stdout_path.stat().st_mode & 0o777 == 0o600


def test_the_shipped_spawn_refuses_to_reuse_a_log_path(tmp_path: Path) -> None:
    stdout_path = tmp_path / "out.jsonl"
    stdout_path.write_bytes(b"previous run\n")
    with pytest.raises(FileExistsError):
        gd.spawn_detached_supervisor(
            [sys.executable, "-c", "pass"],
            cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin"},
            stdout_path=stdout_path,
            stderr_path=tmp_path / "err.log",
        )
    assert stdout_path.read_bytes() == b"previous run\n"


def test_the_shipped_spawn_reports_a_missing_executable_as_a_failure(tmp_path: Path) -> None:
    with pytest.raises(Phase9BGuardianError, match="spawn failed"):
        gd.spawn_detached_supervisor(
            [str(tmp_path / "does-not-exist")],
            cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin"},
            stdout_path=tmp_path / "out.jsonl",
            stderr_path=tmp_path / "err.log",
        )


def _without_docstrings(tree: ast.Module) -> ast.Module:
    """Drop every docstring so a prose mention cannot satisfy a code scan."""

    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return ast.fix_missing_locations(tree)


def test_the_shipped_spawn_uses_no_shell_and_no_background_shortcut() -> None:
    source = Path(gd.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Popen"
        ):
            keywords = {kw.arg for kw in node.keywords}
            assert "shell" in keywords and "start_new_session" in keywords
            assert {"stdin", "stdout", "stderr", "close_fds", "cwd", "env"} <= keywords
    # Scan executable code only: the module docstring names these shortcuts in
    # order to say it does not use them, and a naive substring scan would match
    # its own prose and pass for the wrong reason.
    stripped = ast.unparse(_without_docstrings(tree))
    for shortcut in ("nohup", "setsid", "disown", "os.system", "shell=True"):
        assert shortcut not in stripped, shortcut


def test_the_acknowledgement_reader_refuses_non_json_and_times_out(tmp_path: Path) -> None:
    stdout_path = tmp_path / "out.jsonl"
    binding_source = _consumed_for(tmp_path / "r", ROUTE_DIRECT)
    binding = build_worker_handshake_binding(
        verified=binding_source[1], consumed=binding_source[2], profile=TEST_PROFILE
    )
    spawned = SpawnedProcess(pid=os.getpid(), process_group_id=os.getpid(), session_id=os.getpid())

    stdout_path.write_bytes(b"not json\n")
    with pytest.raises(Phase9BGuardianError, match="not strict JSON"):
        await_spawn_acknowledgement(
            stdout_path,
            spawned=spawned,
            binding=binding,
            deadline_seconds=1.0,
            monotonic=lambda: 0.0,
            sleep=lambda _s: None,
        )

    empty = tmp_path / "empty.jsonl"
    empty.write_bytes(b"")
    ticks = iter([0.0, 5.0])
    with pytest.raises(Phase9BGuardianError, match="remote state unknown"):
        await_spawn_acknowledgement(
            empty,
            spawned=spawned,
            binding=binding,
            deadline_seconds=1.0,
            monotonic=lambda: next(ticks, 99.0),
            sleep=lambda _s: None,
        )


def test_the_spawn_is_refused_if_no_consumed_permit_is_on_disk(
    _open_gates: None, tmp_path: Path
) -> None:
    """The ordering guard, driven directly rather than inferred from line order."""

    run_root, values = _build_route(tmp_path, ROUTE_DIRECT)
    spawn = _FakeSpawn()

    real_consume = consume_phase9b_permit

    def consume_then_remove(ready_path: Path, **kw: Any) -> Any:
        consumed = real_consume(ready_path, **kw)
        # Simulate the consumed record vanishing between consumption and spawn.
        (run_root / CONSUMED_RELATIVE).unlink()
        return consumed

    import unittest.mock

    with unittest.mock.patch.object(gd, "consume_phase9b_permit", consume_then_remove):
        outcome = _run(values, tmp_path, spawn=spawn)
    assert outcome.launch.state is GuardianState.PERMIT_CONSUMED_SPAWN_FAILED
    assert "no consumed permit is on disk" in (outcome.launch.failure_reason or "")
    assert spawn.calls == []


def test_exclusive_create_wins_a_consume_race(tmp_path: Path) -> None:
    """O_EXCL is the linearization point, not the earlier existence check.

    A racing consumer that creates the consumed record after this one has already
    checked must still lose. Simulated by creating it inside the validation
    callback, which runs between the check and the exclusive create.
    """

    from nhc_deprot_ranker.quantum import one_shot_permit as osp

    private = tmp_path / "private"
    private.mkdir()
    ready = private / "permit.ready.json"
    ready.write_bytes(b'{"x": 1}\n')
    ready.chmod(0o400)
    consumed = private / "permit.consumed.json"

    class _Errors(RuntimeError):
        pass

    class _Consumed(_Errors):
        pass

    def racing_validate(raw: bytes) -> object:
        # Another consumer wins the race right here.
        consumed.write_bytes(raw)
        consumed.chmod(0o400)
        return None

    with pytest.raises(_Consumed, match="lost the consume race"):
        osp.consume_one_shot_permit(
            ready,
            ready_relative_name="permit.ready.json",
            consumed_relative_name="permit.consumed.json",
            ready_mode=0o400,
            consumed_mode=0o400,
            validate=racing_validate,
            errors=osp.PermitErrors(error=_Errors, validation=_Errors, consumed=_Consumed),
        )
    # The loser did not overwrite the winner's record, and did not restore ready.
    assert consumed.read_bytes() == b'{"x": 1}\n'
    assert ready.is_file()
