"""Phase 9B supervisor CLI regressions.

The CLI is the formal entry ``preparation/phase9b_launch.py`` renders argv for.
These tests build a real run root on tmp_path with real request, manifest, and
permit bytes, then prove the CLI accepts exactly the thirteen frozen flags and
refuses every drift. No server, no supervisor, no worker, no AIMNet2, no PySCF,
and no permit is consumed.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from nhc_deprot_ranker.preparation.phase9b_bundle import (
    PAYLOAD_MANIFEST_RELATIVE,
    build_route_payload,
    build_route_request,
)
from nhc_deprot_ranker.preparation.phase9b_launch import (
    ALLOWED_ARGUMENTS,
    SUPERVISOR_ENTRY,
    render_launch_argv,
)
from nhc_deprot_ranker.quantum import phase9b_supervisor as sup
from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE
from nhc_deprot_ranker.quantum.phase9b_permit import (
    CONSUMED_RELATIVE,
    READY_RELATIVE,
    REMOTE_ROOT_RELATIVE,
    REQUEST_RELATIVE,
    ROUTE_ASSISTED,
    ROUTE_ATTEMPT_IDS,
    ROUTE_DIRECT,
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


def _endpoint_xyz(*, hydrogens: int, spacing: float = 1.4) -> bytes:
    """C9 F9 H<n> N3 in the frozen atom order: N1 at 8, C2 at 14, N3 at 15.

    The real Phase 7 coordinates are never committed, so these tests synthesize a
    geometry with the same composition, atom count, atom order, and electron count
    and run the CLI against a profile pinned to *its* digests. What is exercised is
    the CLI's verification logic, not the candidate's coordinates.
    """

    # Hydrogens sit last so removing the proton cannot shift N1 at 8, C2 at 14, or
    # N3 at 15 -- one atom map has to hold for both endpoints.
    order = ["C"] * 8 + ["N"] + ["F"] * 5 + ["C"] + ["N", "N"] + ["F"] * 4 + ["H"] * hydrogens
    lines = [str(len(order)), "phase9b synthetic endpoint"]
    for index, element in enumerate(order):
        lines.append(f"{element} {index * spacing:.6f} {index * spacing / 2:.6f} 0.000000")
    return ("\n".join(lines) + "\n").encode()


_CATION_XYZ = _endpoint_xyz(hydrogens=5)
_NEUTRAL_XYZ = _endpoint_xyz(hydrogens=4)
_CATION_SHA = hashlib.sha256(_CATION_XYZ).hexdigest()
_NEUTRAL_SHA = hashlib.sha256(_NEUTRAL_XYZ).hexdigest()

# The assisted route starts from a preoptimized geometry, so its declared digests
# are computed from those files rather than invented: nothing can hash to a
# hand-written constant.
_PRE_CATION_XYZ = _endpoint_xyz(hydrogens=5, spacing=1.39)
_PRE_NEUTRAL_XYZ = _endpoint_xyz(hydrogens=4, spacing=1.39)
_PRE_C = hashlib.sha256(_PRE_CATION_XYZ).hexdigest()
_PRE_N = hashlib.sha256(_PRE_NEUTRAL_XYZ).hexdigest()

# Identical to the frozen candidate except for the two geometry digests, which
# point at the synthetic files above.
TEST_PROFILE = dataclasses.replace(
    PHASE9B_CANDIDATE, cation_xyz_sha256=_CATION_SHA, neutral_xyz_sha256=_NEUTRAL_SHA
)


def _endpoints(route: str) -> tuple[str, str]:
    if route == ROUTE_DIRECT:
        return _CATION_SHA, _NEUTRAL_SHA
    return _PRE_C, _PRE_N


def _build_root(
    tmp_path: Path,
    route: str,
    *,
    manifest_mutation: dict[str, Any] | None = None,
    place_consumed: bool = False,
    place_ready: bool = True,
) -> tuple[Path, dict[str, str]]:
    """Materialize one route's run root with real bytes, and return the argv values."""

    cation, neutral = _endpoints(route)
    request = build_route_request(
        route=route,
        runner_source_sha256=current_runner_source_sha256(),
        protocol=LOCKED_PROTOCOL,
        cation_xyz_sha256=cation,
        neutral_xyz_sha256=neutral,
        profile=TEST_PROFILE,
    )
    payload = build_route_payload(request, profile=TEST_PROFILE)
    # Any manifest mutation is applied before the permit is rendered, so the digest
    # chain stays internally consistent and the *field* checks are what has to bite.
    manifest_bytes = payload.manifest_bytes
    if manifest_mutation is not None:
        body = json.loads(manifest_bytes.decode())
        body.update(manifest_mutation)
        manifest_bytes = (
            json.dumps(body, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
        ).encode()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    permit_bytes = render_phase9b_permit(
        route=route,
        project_root=tmp_path.as_posix(),
        request_sha256=request.request_sha256,
        runner_source_sha256=current_runner_source_sha256(),
        payload_manifest_sha256=manifest_sha256,
        cation_xyz_sha256=cation,
        neutral_xyz_sha256=neutral,
        resources=phase9b_resources_payload(),
        profile=TEST_PROFILE,
    )
    permit = json.loads(permit_bytes.decode())
    run_root = tmp_path / REMOTE_ROOT_RELATIVE / route
    (run_root / "input" / "xyz").mkdir(parents=True)
    (run_root / "private").mkdir(parents=True)
    (run_root / REQUEST_RELATIVE).write_bytes(request.request_bytes)
    (run_root / PAYLOAD_MANIFEST_RELATIVE).write_bytes(manifest_bytes)
    # The request names these relative to its own directory.
    (run_root / "input" / "xyz" / "cation.xyz").write_bytes(
        _CATION_XYZ if route == ROUTE_DIRECT else _PRE_CATION_XYZ
    )
    (run_root / "input" / "xyz" / "neutral.xyz").write_bytes(
        _NEUTRAL_XYZ if route == ROUTE_DIRECT else _PRE_NEUTRAL_XYZ
    )
    if place_ready:
        (run_root / READY_RELATIVE).write_bytes(permit_bytes)
    if place_consumed:
        (run_root / CONSUMED_RELATIVE).write_bytes(permit_bytes)

    values = {
        "--route": route,
        "--attempt-id": ROUTE_ATTEMPT_IDS[route],
        "--request-path": permit["paths"]["request_path"],
        "--output-root": permit["paths"]["output_root"],
        "--permit-path": permit["paths"]["ready_path"],
        "--expected-request-sha256": request.request_sha256,
        "--expected-payload-manifest-sha256": manifest_sha256,
        "--expected-permit-sha256": hashlib.sha256(permit_bytes).hexdigest(),
        "--expected-runner-source-sha256": current_runner_source_sha256(),
        "--expected-resources-sha256": phase9b_resources_sha256(),
        "--gpu-index": "2",
        "--cpu-affinity": _AFFINITY,
        "--timeout-seconds": str(_TIMEOUT),
    }
    return run_root, values


def _argv(values: dict[str, str], **overrides: str) -> list[str]:
    merged = {**values, **overrides}
    out: list[str] = []
    for flag in sup.REQUIRED_FLAGS:
        out += [flag, merged[flag]]
    return out


def _verify(argv: list[str]) -> sup.VerifiedPhase9BLaunch:
    """Verify against the synthetic profile these fixtures are pinned to."""

    return sup.verify_launch_arguments(sup.parse_supervisor_argv(argv), profile=TEST_PROFILE)


# --- argv contract -----------------------------------------------------------


def test_the_cli_flag_set_is_exactly_what_launch_renders() -> None:
    """One contract, asserted from both ends rather than kept in step by hand."""

    assert sorted(sup.REQUIRED_FLAGS) == sorted(ALLOWED_ARGUMENTS)
    assert sup.CLI_ENTRY == SUPERVISOR_ENTRY


def test_launch_argv_parses_under_the_cli_contract(tmp_path: Path) -> None:
    _, values = _build_root(tmp_path, ROUTE_DIRECT)
    # Reuse the launch renderer's shape: strip the interpreter prefix and parse.
    from nhc_deprot_ranker.preparation import phase9b_launch as lc

    plan = lc.RouteLaunchPlan(
        route=ROUTE_DIRECT,
        attempt_id=values["--attempt-id"],
        final_root="/srv/x/direct",
        staging_root="/srv/x/.staging-direct",
        request_path=values["--request-path"],
        permit_path=values["--permit-path"],
        output_root=values["--output-root"],
        request_sha256=values["--expected-request-sha256"],
        payload_manifest_sha256=values["--expected-payload-manifest-sha256"],
        permit_sha256=values["--expected-permit-sha256"],
        runner_source_sha256=values["--expected-runner-source-sha256"],
        resources_sha256=values["--expected-resources-sha256"],
        registered_files={},
        gpu_index=2,
        cpu_affinity=_AFFINITY,
        timeout_seconds=_TIMEOUT,
    )
    argv = render_launch_argv(plan)
    parsed = sup.parse_supervisor_argv(list(argv[5:]))
    assert parsed.route == ROUTE_DIRECT
    assert parsed.attempt_id == ROUTE_ATTEMPT_IDS[ROUTE_DIRECT]
    assert parsed.gpu_index == 2
    assert parsed.timeout_seconds == _TIMEOUT


def test_a_missing_argument_is_refused(tmp_path: Path) -> None:
    _, values = _build_root(tmp_path, ROUTE_DIRECT)
    full = _argv(values)
    for flag in sup.REQUIRED_FLAGS:
        index = full.index(flag)
        short = full[:index] + full[index + 2 :]
        with pytest.raises(sup.Phase9BArgumentError, match="is missing"):
            sup.parse_supervisor_argv(short)


def test_a_repeated_argument_is_refused(tmp_path: Path) -> None:
    _, values = _build_root(tmp_path, ROUTE_DIRECT)
    with pytest.raises(sup.Phase9BArgumentError, match="repeated"):
        sup.parse_supervisor_argv([*_argv(values), "--route", ROUTE_ASSISTED])


def test_an_unknown_or_abbreviated_argument_is_refused(tmp_path: Path) -> None:
    """argparse would honour ``--rou``; a closed contract must not."""

    _, values = _build_root(tmp_path, ROUTE_DIRECT)
    for hostile in ("--verbose", "--rou", "--route=direct", "--gpu_index"):
        with pytest.raises(sup.Phase9BArgumentError):
            sup.parse_supervisor_argv([*_argv(values), hostile, "x"])


def test_positional_and_free_text_arguments_are_refused(tmp_path: Path) -> None:
    _, values = _build_root(tmp_path, ROUTE_DIRECT)
    with pytest.raises(sup.Phase9BArgumentError, match="positional"):
        sup.parse_supervisor_argv([*_argv(values), "extra"])
    with pytest.raises(sup.Phase9BArgumentError, match="no value"):
        sup.parse_supervisor_argv([*_argv(values)[:-1]])


@pytest.mark.parametrize(
    ("flag", "value", "match"),
    [
        ("--expected-request-sha256", "not-a-digest", "lowercase SHA256"),
        ("--expected-permit-sha256", "A" * 64, "lowercase SHA256"),
        ("--gpu-index", "-1", "non-negative decimal"),
        ("--timeout-seconds", "7200.0", "non-negative decimal"),
        ("--request-path", "relative/path", "normalized absolute"),
        ("--output-root", "/srv/../etc", "dot or traversal"),
        ("--permit-path", "/srv/x\nrm", "control character"),
        ("--route", "", "empty value"),
    ],
)
def test_malformed_values_are_refused(tmp_path: Path, flag: str, value: str, match: str) -> None:
    _, values = _build_root(tmp_path, ROUTE_DIRECT)
    with pytest.raises(sup.Phase9BArgumentError, match=match):
        sup.parse_supervisor_argv(_argv(values, **{flag: value}))


# --- identity verification ---------------------------------------------------


@pytest.mark.parametrize("route", [ROUTE_DIRECT, ROUTE_ASSISTED])
def test_a_consistent_run_root_verifies(tmp_path: Path, route: str) -> None:
    _, values = _build_root(tmp_path, route)
    verified = _verify(_argv(values))
    assert verified.arguments.route == route
    assert verified.permit.route == route
    assert verified.authority.route == route
    assert verified.authority.electron_count == PHASE9B_CANDIDATE.electron_count
    assert verified.payload_manifest_sha256 == values["--expected-payload-manifest-sha256"]


def test_a_wrong_route_or_attempt_pairing_is_refused(tmp_path: Path) -> None:
    _, values = _build_root(tmp_path, ROUTE_DIRECT)
    swapped = _argv(values, **{"--attempt-id": ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED]})
    with pytest.raises(sup.Phase9BSupervisorError, match="does not match its route"):
        _verify(swapped)
    with pytest.raises(sup.Phase9BSupervisorError, match="unknown Phase 9B route"):
        _verify(_argv(values, **{"--route": "up"}))


@pytest.mark.parametrize(
    ("flag", "match"),
    [
        ("--expected-request-sha256", "expected request digest"),
        ("--expected-payload-manifest-sha256", "drifted from the expected value"),
        ("--expected-permit-sha256", "expected permit digest"),
        ("--expected-runner-source-sha256", "runner source closure drifted"),
        ("--expected-resources-sha256", "resource digest drifted"),
    ],
)
def test_any_asserted_digest_that_drifts_is_refused(tmp_path: Path, flag: str, match: str) -> None:
    _, values = _build_root(tmp_path, ROUTE_DIRECT)
    drifted = _argv(values, **{flag: "9" * 64})
    with pytest.raises(sup.Phase9BNotAuthorizedError, match=match):
        _verify(drifted)


def test_a_path_outside_the_permits_roots_is_refused(tmp_path: Path) -> None:
    run_root, values = _build_root(tmp_path, ROUTE_DIRECT)
    elsewhere = (tmp_path / "elsewhere.json").as_posix()
    with pytest.raises(sup.Phase9BNotAuthorizedError, match="permitted request path"):
        _verify(_argv(values, **{"--request-path": elsewhere}))
    with pytest.raises(sup.Phase9BNotAuthorizedError, match="permitted output root"):
        _verify(_argv(values, **{"--output-root": (run_root / "other").as_posix()}))


def test_a_permit_read_from_another_path_is_refused(tmp_path: Path) -> None:
    run_root, values = _build_root(tmp_path, ROUTE_DIRECT)
    copy = run_root / "private" / "copy.json"
    copy.write_bytes((run_root / READY_RELATIVE).read_bytes())
    with pytest.raises(sup.Phase9BNotAuthorizedError, match="not at its own registered path"):
        _verify(_argv(values, **{"--permit-path": copy.as_posix()}))


def test_a_missing_permit_or_symlinked_permit_is_refused(tmp_path: Path) -> None:
    run_root, values = _build_root(tmp_path, ROUTE_DIRECT, place_ready=False)
    with pytest.raises(sup.Phase9BSupervisorError, match="ready permit is missing"):
        _verify(_argv(values))
    target = run_root / "private" / "real.json"
    target.write_bytes(b"{}\n")
    (run_root / READY_RELATIVE).symlink_to(target)
    with pytest.raises(sup.Phase9BSupervisorError, match="ready permit is missing"):
        _verify(_argv(values))


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ({"route": ROUTE_ASSISTED}, "disagrees with the argv"),
        ({"attempt_id": "attempt-other"}, "disagrees with the argv"),
        ({"request_id": "another-request"}, "disagrees with the argv"),
        ({"label_produced": True}, "disagrees with the argv"),
        ({"excludes_permit": False}, "disagrees with the argv"),
        ({"electron_count": 120}, "disagrees with the argv"),
    ],
)
def test_a_manifest_that_disagrees_with_the_argv_is_refused(
    tmp_path: Path, mutation: dict[str, Any], match: str
) -> None:
    _, values = _build_root(tmp_path, ROUTE_DIRECT, manifest_mutation=mutation)
    with pytest.raises(sup.Phase9BNotAuthorizedError, match=match):
        _verify(_argv(values))


def test_a_missing_manifest_is_refused(tmp_path: Path) -> None:
    run_root, values = _build_root(tmp_path, ROUTE_DIRECT)
    (run_root / PAYLOAD_MANIFEST_RELATIVE).unlink()
    with pytest.raises(sup.Phase9BSupervisorError, match="payload manifest is missing"):
        _verify(_argv(values))


@pytest.mark.parametrize(
    ("flag", "value", "match"),
    [
        ("--timeout-seconds", "3600", "not the frozen wall-time"),
        ("--cpu-affinity", "0-7", "not the frozen affinity"),
        ("--gpu-index", "99", "outside the inspected device range"),
    ],
)
def test_resource_drift_is_refused(tmp_path: Path, flag: str, value: str, match: str) -> None:
    _, values = _build_root(tmp_path, ROUTE_DIRECT)
    with pytest.raises(sup.Phase9BNotAuthorizedError, match=match):
        _verify(_argv(values, **{flag: value}))


def test_a_phase8b_artifact_in_the_argv_is_refused(tmp_path: Path) -> None:
    _, values = _build_root(tmp_path, ROUTE_DIRECT)
    hostile = _argv(values, **{"--attempt-id": "attempt-phase8b-qxh-v001"})
    with pytest.raises(sup.Phase9BNotAuthorizedError, match="retired Phase 8B"):
        _verify(hostile)


# --- identity output and delegation -----------------------------------------


def test_identity_json_is_exactly_what_launch_reads_back(tmp_path: Path) -> None:
    _, values = _build_root(tmp_path, ROUTE_DIRECT)
    verified = _verify(_argv(values))
    payload = sup.supervisor_identity_payload(verified, pid=4242)
    assert payload["entry"] == SUPERVISOR_ENTRY
    assert payload["route"] == ROUTE_DIRECT
    assert payload["attempt_id"] == ROUTE_ATTEMPT_IDS[ROUTE_DIRECT]
    assert payload["pid"] == 4242
    assert isinstance(payload["supervisor_identity"], str)
    assert len(str(payload["supervisor_identity"])) == 64
    # The launch side accepts exactly this shape.
    from nhc_deprot_ranker.preparation import phase9b_launch as lc
    from nhc_deprot_ranker.preparation.phase9b_launch import _parse_supervisor_evidence

    plan = lc.RouteLaunchPlan(
        route=ROUTE_DIRECT,
        attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
        final_root="/srv/x/direct",
        staging_root="/srv/x/.s",
        request_path=values["--request-path"],
        permit_path=values["--permit-path"],
        output_root=values["--output-root"],
        request_sha256=values["--expected-request-sha256"],
        payload_manifest_sha256=values["--expected-payload-manifest-sha256"],
        permit_sha256=values["--expected-permit-sha256"],
        runner_source_sha256=values["--expected-runner-source-sha256"],
        resources_sha256=values["--expected-resources-sha256"],
        registered_files={},
        gpu_index=2,
        cpu_affinity=_AFFINITY,
        timeout_seconds=_TIMEOUT,
    )
    identity, pid = _parse_supervisor_evidence(json.dumps(payload).encode(), plan=plan)
    assert identity == payload["supervisor_identity"]
    assert pid == 4242


def test_identity_is_bound_to_the_route_and_never_shared(tmp_path: Path) -> None:
    direct = sup.supervisor_identity_payload(
        _verify(_argv(_build_root(tmp_path / "d", ROUTE_DIRECT)[1])), pid=1
    )
    assisted = sup.supervisor_identity_payload(
        _verify(_argv(_build_root(tmp_path / "a", ROUTE_ASSISTED)[1])), pid=1
    )
    assert direct["supervisor_identity"] != assisted["supervisor_identity"]


def test_main_announces_then_refuses_without_a_wired_handshake(tmp_path: Path) -> None:
    """The identity is printed before delegation, and delegation is not improvised."""

    _, values = _build_root(tmp_path, ROUTE_DIRECT)
    stream = io.StringIO()
    with pytest.raises(sup.Phase9BNotAuthorizedError, match="no guarded worker handshake"):
        sup.main(_argv(values), stdout=stream, profile=TEST_PROFILE)
    printed = json.loads(stream.getvalue())
    assert printed["entry"] == SUPERVISOR_ENTRY
    assert printed["route"] == ROUTE_DIRECT


def test_main_refuses_before_printing_when_an_identity_drifts(tmp_path: Path) -> None:
    _, values = _build_root(tmp_path, ROUTE_DIRECT)
    stream = io.StringIO()
    with pytest.raises(sup.Phase9BNotAuthorizedError):
        sup.main(
            _argv(values, **{"--expected-permit-sha256": "8" * 64}),
            stdout=stream,
            profile=TEST_PROFILE,
        )
    assert stream.getvalue() == ""


def test_main_delegates_to_the_guarded_supervisor_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nhc_deprot_ranker.quantum import two_endpoint

    monkeypatch.setattr(sup, "EXECUTION_AUTHORIZED", True)
    monkeypatch.setattr(two_endpoint, "EXECUTION_AUTHORIZED", True)
    _, values = _build_root(tmp_path, ROUTE_ASSISTED)
    seen: dict[str, object] = {}

    class _Launch:
        absolute_deadline_ns = 1

    def factory(*, verified: sup.VerifiedPhase9BLaunch) -> _Launch:
        seen["route"] = verified.arguments.route
        return _Launch()

    def executor(
        request: object, output_root: Path, *, attempt_id: str, worker_launch: object
    ) -> str:
        del request, output_root, worker_launch
        seen["attempt_id"] = attempt_id
        return "delegated"

    assert (
        sup.main(
            _argv(values),
            worker_launch_factory=factory,
            execute=executor,
            stdout=io.StringIO(),
            profile=TEST_PROFILE,
        )
        == 0
    )
    assert seen == {"route": ROUTE_ASSISTED, "attempt_id": ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED]}


# --- the CLI reimplements nothing -------------------------------------------


def test_the_cli_reimplements_no_supervision_or_backend_logic() -> None:
    """AST-scanned: docstrings may name these, executable code may not."""

    tree = ast.parse(Path(sup.__file__).read_text(encoding="utf-8"))
    banned_modules = {
        "torch",
        "ase",
        "aimnet",
        "pyscf",
        "geometric",
        "subprocess",
        "signal",
        "resource",
        "select",
        "socket",
        "fcntl",
        "threading",
        "multiprocessing",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & banned_modules)

    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } | {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    # No process, signal, or reaping primitives: supervision stays in one place.
    for primitive in ("fork", "kill", "killpg", "waitpid", "waitid", "setsid", "pipe", "execv"):
        assert primitive not in called


def test_the_source_gate_is_still_closed() -> None:
    assert sup.EXECUTION_AUTHORIZED is False
    source = Path(sup.__file__).read_text(encoding="utf-8")
    assert "EXECUTION_AUTHORIZED: Final[bool] = False" in source


def test_a_permit_for_the_other_route_at_this_path_is_refused(tmp_path: Path) -> None:
    """The argv can be self-consistent while the permit file is the wrong one.

    The route/attempt pairing check passes here, so what has to bite is the
    comparison of the argv against the *permit's own* declared route.
    """

    direct_root, direct_values = _build_root(tmp_path / "d", ROUTE_DIRECT)
    assisted_root, _ = _build_root(tmp_path / "a", ROUTE_ASSISTED)
    # Swap the assisted route's permit bytes into the direct route's ready path.
    foreign = (assisted_root / READY_RELATIVE).read_bytes()
    (direct_root / READY_RELATIVE).unlink()
    (direct_root / READY_RELATIVE).write_bytes(foreign)
    argv = _argv(
        direct_values,
        **{"--expected-permit-sha256": hashlib.sha256(foreign).hexdigest()},
    )
    with pytest.raises(sup.Phase9BNotAuthorizedError, match="another route or attempt"):
        _verify(argv)


def test_the_adapter_refuses_an_attempt_that_is_not_a_phase9b_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Driven directly: the Phase 8B attempt must not reach the Phase 9B adapter."""

    from nhc_deprot_ranker.quantum import two_endpoint
    from nhc_deprot_ranker.quantum.phase8b_permit import FROZEN_ATTEMPT_ID

    monkeypatch.setattr(two_endpoint, "EXECUTION_AUTHORIZED", True)
    for attempt in (FROZEN_ATTEMPT_ID, "attempt-anything-else"):
        with pytest.raises(
            two_endpoint.ExecutionNotAuthorizedError, match="not a registered Phase 9B route"
        ):
            two_endpoint.run_phase9b_supervised_execution(
                None,  # type: ignore[arg-type]
                Path("/nonexistent"),
                attempt_id=attempt,
                worker_launch=None,  # type: ignore[arg-type]
            )
    # And a real route gets past that check, failing later on the handshake type.
    with pytest.raises(
        two_endpoint.ExecutionNotAuthorizedError, match="guarded worker launch handshake"
    ):
        two_endpoint.run_phase9b_supervised_execution(
            None,  # type: ignore[arg-type]
            Path("/nonexistent"),
            attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED],
            worker_launch=None,  # type: ignore[arg-type]
        )
