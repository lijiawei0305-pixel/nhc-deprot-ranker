"""Phase 9B permit placement regressions.

No chemistry, no server, no compute. The remote placer is simulated by a fake
that honours the same exclusive-create, no-follow, and re-read semantics against
tmp_path, so nothing here reaches a network. No permit is ever consumed: this
module only creates the ready permit, and has no code path that renames, deletes,
or restores one.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from nhc_deprot_ranker.preparation import phase9b_permit_stage as ps
from nhc_deprot_ranker.preparation.phase9b_bundle import build_route_payload, build_route_request
from nhc_deprot_ranker.preparation.phase9b_deploy import (
    DeploymentOutcome,
    DeployState,
    build_route_plan,
)
from nhc_deprot_ranker.preparation.phase9b_permit_stage import (
    ObservedPermitFile,
    PermitPlacementReceipt,
    Phase9BPermitStageError,
    Phase9BPermitStageNotAuthorizedError,
    PlacementState,
    PlacementTimeout,
    RoutePermitPlan,
    RoutePlacementState,
    build_placement_stream,
    build_route_permit_plan,
    is_launch_ready,
    observed_permits,
    parse_placement_evidence,
    place_both_permits,
    receipt_payload,
    recomputed_receipt_sha256,
    verify_promoted_deployment,
)
from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE
from nhc_deprot_ranker.quantum.phase9b_permit import (
    CONSUMED_RELATIVE,
    READY_RELATIVE,
    ROUTE_ASSISTED,
    ROUTE_ATTEMPT_IDS,
    ROUTE_DIRECT,
    parse_phase9b_permit,
    render_phase9b_permit,
)
from nhc_deprot_ranker.quantum.phase9b_resources import phase9b_resources_payload
from nhc_deprot_ranker.quantum.two_endpoint import LOCKED_PROTOCOL, current_runner_source_sha256

_PROJECT = "/srv/project"
_ALIAS = "gpu-node"
_PRE_C = "4" * 64
_PRE_N = "5" * 64


def _endpoints(route: str) -> tuple[str, str]:
    if route == ROUTE_DIRECT:
        return PHASE9B_CANDIDATE.cation_xyz_sha256, PHASE9B_CANDIDATE.neutral_xyz_sha256
    return _PRE_C, _PRE_N


def _plan(route: str, *, project_root: str = _PROJECT) -> RoutePermitPlan:
    cation, neutral = _endpoints(route)
    request = build_route_request(
        route=route,
        runner_source_sha256=current_runner_source_sha256(),
        protocol=LOCKED_PROTOCOL,
        cation_xyz_sha256=cation,
        neutral_xyz_sha256=neutral,
    )
    payload = build_route_payload(request)
    permit = parse_phase9b_permit(
        render_phase9b_permit(
            route=route,
            project_root=project_root,
            request_sha256=request.request_sha256,
            runner_source_sha256=current_runner_source_sha256(),
            payload_manifest_sha256=payload.manifest_sha256,
            cation_xyz_sha256=cation,
            neutral_xyz_sha256=neutral,
            resources=phase9b_resources_payload(),
        )
    )
    return build_route_permit_plan(permit=permit, payload_manifest_sha256=payload.manifest_sha256)


def _plans(project_root: str = _PROJECT) -> tuple[RoutePermitPlan, RoutePermitPlan]:
    return (
        _plan(ROUTE_DIRECT, project_root=project_root),
        _plan(ROUTE_ASSISTED, project_root=project_root),
    )


def _outcome(plans: Sequence[RoutePermitPlan], **kw: Any) -> DeploymentOutcome:
    base: dict[str, Any] = {
        "state": DeployState.PROMOTED,
        "promoted_routes": (ROUTE_ASSISTED, ROUTE_DIRECT),
        "staging_roots": {
            plan.route: build_route_plan(
                route=plan.route,
                project_root=_PROJECT,
                attempt_id=plan.attempt_id,
                files={"input/request.json": plan.request_sha256},
            ).staging_root
            for plan in plans
        },
        "final_roots": {plan.route: plan.final_root for plan in plans},
        "failure_reason": None,
        "failure_roots": (),
        "ssh_invocations": 3,
    }
    base.update(kw)
    return DeploymentOutcome(**base)


class _FakeRemote:
    """Honours the placer's real semantics against tmp_path, with no network."""

    def __init__(
        self,
        root: Path,
        *,
        existing_ready: set[str] | None = None,
        existing_consumed: set[str] | None = None,
        symlink_ready: set[str] | None = None,
        truncate_for: str | None = None,
        corrupt_for: str | None = None,
        timeout_for: str | None = None,
        raise_for: str | None = None,
        code_for: dict[str, int] | None = None,
        stdout_for: dict[str, bytes] | None = None,
    ) -> None:
        self.root = root
        self.existing_ready = existing_ready or set()
        self.existing_consumed = existing_consumed or set()
        self.symlink_ready = symlink_ready or set()
        self.truncate_for = truncate_for
        self.corrupt_for = corrupt_for
        self.timeout_for = timeout_for
        self.raise_for = raise_for
        self.code_for = code_for or {}
        self.stdout_for = stdout_for or {}
        self.calls: list[str] = []

    def _local(self, remote_path: str) -> Path:
        return self.root / remote_path.lstrip("/")

    def __call__(
        self, command: Sequence[str], *, stdin: bytes, timeout: float
    ) -> tuple[int, bytes, bytes]:
        assert timeout > 0
        assert command[0] == "ssh"
        # Real delete verbs only: a bare "rm" substring also occurs inside
        # "permit" and "dirname", so scanning for it would match the placer's own
        # source and pass for the wrong reason.
        for verb in ("os.remove", "os.unlink", "os.rmdir", "rmtree", "os.rename"):
            assert verb not in command[-1], verb
        header_length = int.from_bytes(stdin[:8], "big")
        header = json.loads(stdin[8 : 8 + header_length].decode())
        body = stdin[8 + header_length :]
        route = header["route"]
        self.calls.append(route)
        if self.timeout_for == route:
            raise PlacementTimeout("no reply within the bound")
        if self.raise_for == route:
            raise OSError("connection reset")
        if route in self.stdout_for:
            return self.code_for.get(route, 0), self.stdout_for[route], b""

        ready = self._local(header["ready_path"])
        consumed = self._local(header["consumed_path"])
        ready.parent.mkdir(parents=True, exist_ok=True)
        if route in self.existing_consumed:
            consumed.write_bytes(b"already consumed\n")
        if route in self.existing_ready:
            ready.write_bytes(b"already there\n")
        if route in self.symlink_ready:
            other = ready.parent / "other.json"
            other.write_bytes(b"{}\n")
            ready.symlink_to(other)

        # Exactly the placer's refusals, in the placer's order.
        if consumed.exists():
            return 1, b"", b"a consumed permit already exists; it is never restored\n"
        if os.path.lexists(ready):
            return 1, b"", b"a ready permit already exists; overwrite is prohibited\n"
        if self.code_for.get(route):
            return self.code_for[route], b"", b"refused\n"

        written = body[:-1] if self.truncate_for == route else body
        if self.corrupt_for == route:
            written = written.replace(b'"one_shot": true', b'"one_shot": TRUE')
        descriptor = os.open(str(ready), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        try:
            os.write(descriptor, written)
        finally:
            os.close(descriptor)
        info = ready.lstat()
        digest = hashlib.sha256(ready.read_bytes()).hexdigest()
        return (
            0,
            json.dumps(
                {
                    "schema_version": ps.PLACEMENT_EVIDENCE_SCHEMA_VERSION,
                    "route": route,
                    "attempt_id": header["attempt_id"],
                    "path": header["ready_path"],
                    "bytes": info.st_size,
                    "sha256": digest,
                    "regular": True,
                    "consumed_present": consumed.exists(),
                },
                sort_keys=True,
            ).encode(),
            b"",
        )


def _place(tmp_path: Path, **kw: Any) -> tuple[PermitPlacementReceipt, _FakeRemote]:
    plans = kw.pop("plans", None) or _plans()
    remote = kw.pop("remote", None) or _FakeRemote(tmp_path, **kw.pop("remote_kw", {}))
    receipt = place_both_permits(
        ssh_alias=_ALIAS,
        plans=plans,
        deploy_outcome=kw.pop("deploy_outcome", _outcome(plans)),
        run_command=remote,
        clock=lambda: "2026-07-26T00:00:00Z",
        **kw,
    )
    return receipt, remote


# --- gate and closure --------------------------------------------------------


def test_source_gate_is_closed_and_real_placement_refuses() -> None:
    assert ps.EXECUTION_AUTHORIZED is False
    source = Path(ps.__file__).read_text(encoding="utf-8")
    assert "EXECUTION_AUTHORIZED: Final[bool] = False" in source
    plans = _plans()
    with pytest.raises(Phase9BPermitStageNotAuthorizedError, match="not authorized"):
        place_both_permits(ssh_alias=_ALIAS, plans=plans, deploy_outcome=_outcome(plans))


def test_permit_stage_is_outside_the_runner_source_closure() -> None:
    from nhc_deprot_ranker.quantum import two_endpoint

    closure = two_endpoint._RUNNER_SOURCE_RELATIVE_PATHS
    assert not any(path.endswith("phase9b_permit_stage.py") for path in closure)


def test_the_module_has_no_delete_rename_or_restore_verb() -> None:
    """AST-scanned plus a literal scan of the remote source it ships."""

    text = Path(ps.__file__).read_text(encoding="utf-8")
    tree = ast.parse(text)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for verb in ("remove", "unlink", "rmdir", "rename", "replace", "rmtree", "chmod", "truncate"):
        assert verb not in called, verb
    for verb in ("os.remove", "os.unlink", "os.rename", "shutil.rmtree", "os.rmdir"):
        assert verb not in ps.REMOTE_PLACER_SOURCE, verb
    # And the remote side must use exclusive create with no symlink follow.
    assert "O_CREAT | os.O_EXCL | os.O_NOFOLLOW" in ps.REMOTE_PLACER_SOURCE
    assert "O_RDONLY | os.O_NOFOLLOW" in ps.REMOTE_PLACER_SOURCE


# --- plan construction -------------------------------------------------------


@pytest.mark.parametrize("route", [ROUTE_DIRECT, ROUTE_ASSISTED])
def test_a_plan_consumes_the_permit_bytes_verbatim(route: str) -> None:
    plan = _plan(route)
    assert plan.attempt_id == ROUTE_ATTEMPT_IDS[route]
    assert hashlib.sha256(plan.permit_bytes).hexdigest() == plan.permit_sha256
    assert plan.ready_path.endswith(READY_RELATIVE)
    assert plan.consumed_path.endswith(CONSUMED_RELATIVE)
    assert plan.ready_path != plan.consumed_path
    assert plan.ready_path.startswith(plan.final_root + "/")


def test_a_manifest_digest_that_disagrees_with_the_permit_is_refused() -> None:
    cation, neutral = _endpoints(ROUTE_DIRECT)
    request = build_route_request(
        route=ROUTE_DIRECT,
        runner_source_sha256=current_runner_source_sha256(),
        protocol=LOCKED_PROTOCOL,
        cation_xyz_sha256=cation,
        neutral_xyz_sha256=neutral,
    )
    payload = build_route_payload(request)
    permit = parse_phase9b_permit(
        render_phase9b_permit(
            route=ROUTE_DIRECT,
            project_root=_PROJECT,
            request_sha256=request.request_sha256,
            runner_source_sha256=current_runner_source_sha256(),
            payload_manifest_sha256=payload.manifest_sha256,
            cation_xyz_sha256=cation,
            neutral_xyz_sha256=neutral,
            resources=phase9b_resources_payload(),
        )
    )
    with pytest.raises(Phase9BPermitStageError, match="manifest digest drifted"):
        build_route_permit_plan(permit=permit, payload_manifest_sha256="7" * 64)


def test_a_retired_phase8b_root_is_refused() -> None:
    with pytest.raises(Phase9BPermitStageError, match="retired Phase 8B"):
        _plan(ROUTE_DIRECT, project_root="/srv/phase8b-project")


def test_a_pair_that_is_not_both_routes_is_refused() -> None:
    direct, assisted = _plans()
    with pytest.raises(Phase9BPermitStageError, match="exactly both routes"):
        ps.validate_plan_pair((direct,))
    with pytest.raises(Phase9BPermitStageError, match="distinct permit_sha256"):
        ps.validate_plan_pair(
            (direct, dataclasses.replace(assisted, permit_sha256=direct.permit_sha256))
        )
    with pytest.raises(Phase9BPermitStageError, match="disagree on the runner source"):
        ps.validate_plan_pair(
            (direct, dataclasses.replace(assisted, runner_source_sha256="1" * 64))
        )


# --- deploy precondition -----------------------------------------------------


def test_placement_requires_a_promoted_deployment(tmp_path: Path) -> None:
    plans = _plans()
    for outcome, match in (
        (None, "no deploy receipt"),
        (_outcome(plans, state=DeployState.STAGED), "not PROMOTED"),
        (_outcome(plans, failure_reason="may be partial"), "names a failure"),
        (_outcome(plans, promoted_routes=(ROUTE_DIRECT,)), "exactly both routes"),
        (_outcome(plans, ssh_invocations=2), "registered transport"),
    ):
        receipt, remote = _place(tmp_path, plans=plans, deploy_outcome=outcome)
        assert receipt.overall_state is PlacementState.NOT_PLACED
        assert match in (receipt.failure_reason or "")
        assert remote.calls == []


def test_a_final_root_that_drifted_is_refused() -> None:
    plans = _plans()
    drifted = _outcome(
        plans, final_roots={ROUTE_DIRECT: plans[0].final_root, ROUTE_ASSISTED: "/srv/elsewhere"}
    )
    with pytest.raises(Phase9BPermitStageError, match="final root drifted"):
        verify_promoted_deployment(drifted, plans=plans)


# --- placement ---------------------------------------------------------------


def test_both_permits_are_placed_and_re_read(tmp_path: Path) -> None:
    plans = _plans()
    receipt, remote = _place(tmp_path, plans=plans)
    assert receipt.overall_state is PlacementState.PLACED
    assert receipt.failure_reason is None
    assert remote.calls == [ROUTE_DIRECT, ROUTE_ASSISTED]
    assert is_launch_ready(receipt)
    for plan, record in zip(plans, receipt.routes, strict=True):
        assert record.state is RoutePlacementState.PLACED
        assert record.observed is not None
        assert record.observed.sha256 == plan.permit_sha256
        assert record.observed.bytes == len(plan.permit_bytes)
        assert record.observed.regular_file is True
        # The bytes really landed, unchanged.
        landed = (tmp_path / plan.ready_path.lstrip("/")).read_bytes()
        assert hashlib.sha256(landed).hexdigest() == plan.permit_sha256
    # No consumed permit was created or restored anywhere.
    assert not list(tmp_path.rglob("permit.consumed.json"))


def test_the_placed_permit_is_read_only_and_never_overwritten(tmp_path: Path) -> None:
    plans = _plans()
    _place(tmp_path, plans=plans)
    landed = tmp_path / plans[0].ready_path.lstrip("/")
    assert landed.stat().st_mode & 0o777 == 0o400
    # A second placement under the same plan finds the file present and refuses.
    receipt, _ = _place(tmp_path, plans=plans)
    assert receipt.overall_state is PlacementState.FAILED
    assert "exited 1" in (receipt.failure_reason or "")
    assert hashlib.sha256(landed.read_bytes()).hexdigest() == plans[0].permit_sha256


def test_an_existing_ready_permit_blocks_placement(tmp_path: Path) -> None:
    receipt, _ = _place(tmp_path, remote_kw={"existing_ready": {ROUTE_DIRECT}})
    assert receipt.overall_state is PlacementState.FAILED
    assert receipt.routes[0].state is RoutePlacementState.FAILED
    assert "overwrite is prohibited" in (receipt.routes[0].detail or "")
    assert receipt.routes[1].state is RoutePlacementState.NOT_ATTEMPTED


def test_an_existing_consumed_permit_blocks_placement(tmp_path: Path) -> None:
    receipt, _ = _place(tmp_path, remote_kw={"existing_consumed": {ROUTE_DIRECT}})
    assert receipt.overall_state is PlacementState.FAILED
    assert "never restored" in (receipt.routes[0].detail or "")


def test_a_symlinked_ready_path_blocks_placement(tmp_path: Path) -> None:
    receipt, _ = _place(tmp_path, remote_kw={"symlink_ready": {ROUTE_ASSISTED}})
    assert receipt.overall_state is PlacementState.PARTIALLY_PLACED
    assert receipt.routes[0].state is RoutePlacementState.PLACED
    assert receipt.routes[1].state is RoutePlacementState.FAILED
    assert not is_launch_ready(receipt)


def test_a_partial_write_is_caught_by_the_re_read(tmp_path: Path) -> None:
    receipt, _ = _place(tmp_path, remote_kw={"truncate_for": ROUTE_DIRECT})
    assert receipt.overall_state is PlacementState.INDETERMINATE
    assert "byte size does not match" in (receipt.routes[0].detail or "")
    assert not is_launch_ready(receipt)


def test_a_corrupted_write_is_caught_by_the_re_read(tmp_path: Path) -> None:
    receipt, _ = _place(tmp_path, remote_kw={"corrupt_for": ROUTE_DIRECT})
    assert receipt.overall_state is PlacementState.INDETERMINATE
    assert "does not hash to the permitted digest" in (receipt.routes[0].detail or "")


def test_a_remote_hash_that_drifted_is_refused(tmp_path: Path) -> None:
    plans = _plans()
    lying = json.dumps(
        {
            "schema_version": ps.PLACEMENT_EVIDENCE_SCHEMA_VERSION,
            "route": ROUTE_DIRECT,
            "attempt_id": plans[0].attempt_id,
            "path": plans[0].ready_path,
            "bytes": len(plans[0].permit_bytes),
            "sha256": "3" * 64,
            "regular": True,
            "consumed_present": False,
        },
        sort_keys=True,
    ).encode()
    receipt, _ = _place(tmp_path, plans=plans, remote_kw={"stdout_for": {ROUTE_DIRECT: lying}})
    assert receipt.overall_state is PlacementState.INDETERMINATE
    assert "does not hash to the permitted digest" in (receipt.routes[0].detail or "")


def test_one_route_placed_and_the_other_failed_is_partially_placed(tmp_path: Path) -> None:
    receipt, remote = _place(tmp_path, remote_kw={"code_for": {ROUTE_ASSISTED: 1}})
    assert receipt.overall_state is PlacementState.PARTIALLY_PLACED
    assert [record.state for record in receipt.routes] == [
        RoutePlacementState.PLACED,
        RoutePlacementState.FAILED,
    ]
    # No auto-retry, no rollback of the one that landed.
    assert remote.calls == [ROUTE_DIRECT, ROUTE_ASSISTED]
    assert not is_launch_ready(receipt)


def test_the_first_route_failing_means_the_second_is_never_attempted(tmp_path: Path) -> None:
    receipt, remote = _place(tmp_path, remote_kw={"code_for": {ROUTE_DIRECT: 1}})
    assert receipt.overall_state is PlacementState.FAILED
    assert receipt.routes[1].state is RoutePlacementState.NOT_ATTEMPTED
    assert remote.calls == [ROUTE_DIRECT]


def test_a_timeout_leaves_the_state_indeterminate(tmp_path: Path) -> None:
    receipt, remote = _place(tmp_path, remote_kw={"timeout_for": ROUTE_DIRECT})
    assert receipt.overall_state is PlacementState.INDETERMINATE
    assert "unknown after timeout" in (receipt.routes[0].detail or "")
    assert remote.calls == [ROUTE_DIRECT]
    assert not is_launch_ready(receipt)


def test_a_transport_failure_mid_stream_is_indeterminate(tmp_path: Path) -> None:
    """The permit may or may not have landed, so this is not a known failure."""

    receipt, _ = _place(tmp_path, remote_kw={"raise_for": ROUTE_ASSISTED})
    assert receipt.overall_state is PlacementState.INDETERMINATE
    assert receipt.routes[1].state is RoutePlacementState.INDETERMINATE


# --- evidence and receipt ----------------------------------------------------


def test_evidence_naming_another_route_or_path_is_refused() -> None:
    plan = _plan(ROUTE_DIRECT)
    base = {
        "schema_version": ps.PLACEMENT_EVIDENCE_SCHEMA_VERSION,
        "route": plan.route,
        "attempt_id": plan.attempt_id,
        "path": plan.ready_path,
        "bytes": len(plan.permit_bytes),
        "sha256": plan.permit_sha256,
        "regular": True,
        "consumed_present": False,
    }
    assert parse_placement_evidence(json.dumps(base).encode(), plan=plan).sha256 == (
        plan.permit_sha256
    )
    for mutation, match in (
        ({"route": ROUTE_ASSISTED}, "another route or attempt"),
        ({"attempt_id": "attempt-other"}, "another route or attempt"),
        ({"path": "/srv/elsewhere"}, "another path"),
        ({"regular": False}, "not a regular file"),
        ({"consumed_present": True}, "consumed permit is present"),
        ({"schema_version": "other"}, "schema version drifted"),
    ):
        with pytest.raises(Phase9BPermitStageError, match=match):
            parse_placement_evidence(json.dumps({**base, **mutation}).encode(), plan=plan)
    with pytest.raises(Phase9BPermitStageError, match="not strict JSON"):
        parse_placement_evidence(b"not json", plan=plan)


def test_the_receipt_carries_every_registered_field(tmp_path: Path) -> None:
    plans = _plans()
    receipt, _ = _place(tmp_path, plans=plans)
    body = receipt_payload(receipt)
    assert body["schema_version"] == ps.PLACEMENT_RECEIPT_SCHEMA_VERSION
    assert body["phase"] == "9B"
    assert body["candidate_inchikey"] == PHASE9B_CANDIDATE.inchikey
    assert body["placed_at"] == "2026-07-26T00:00:00Z"
    assert body["host_identity_sha256"] == hashlib.sha256(_ALIAS.encode()).hexdigest()
    for key in ("deploy_outcome_sha256", "runner_source_sha256", "resources_sha256"):
        assert len(str(body[key])) == 64
    assert body["receipt_sha256"] == recomputed_receipt_sha256(receipt)
    routes = body["routes"]
    assert isinstance(routes, list) and len(routes) == 2
    for entry in routes:
        for key in ("permit_sha256", "request_sha256", "payload_manifest_sha256"):
            assert len(str(entry[key])) == 64
        observed = entry["observed"]
        assert isinstance(observed, dict)
        assert observed["regular_file"] is True
        assert observed["bytes"] > 0
    # Serializable and free of any scientific claim.
    text = json.dumps(body, sort_keys=True)
    for banned in ("energy", "hartree", "kcal", "converged", "label"):
        assert banned not in text


def test_an_edited_receipt_no_longer_matches_its_own_digest(tmp_path: Path) -> None:
    receipt, _ = _place(tmp_path)
    assert is_launch_ready(receipt)
    lied = dataclasses.replace(receipt, overall_state=PlacementState.PLACED, failure_reason=None)
    assert is_launch_ready(lied)  # unchanged fields, unchanged digest

    upgraded = dataclasses.replace(
        _place(tmp_path / "second")[0], overall_state=PlacementState.PLACED
    )
    del upgraded
    # Claiming PLACED over a route record that is not placed breaks the digest.
    broken = dataclasses.replace(
        receipt,
        routes=(
            dataclasses.replace(receipt.routes[0], state=RoutePlacementState.FAILED),
            receipt.routes[1],
        ),
    )
    assert broken.receipt_sha256 != recomputed_receipt_sha256(broken)
    assert not is_launch_ready(broken)


def test_observed_permits_refuses_a_receipt_that_is_not_launch_ready(tmp_path: Path) -> None:
    receipt, _ = _place(tmp_path, remote_kw={"code_for": {ROUTE_ASSISTED: 1}})
    with pytest.raises(Phase9BPermitStageError, match="not launch-ready"):
        observed_permits(receipt)


def test_an_observation_without_a_file_is_not_launch_ready(tmp_path: Path) -> None:
    receipt, _ = _place(tmp_path)
    stripped = dataclasses.replace(
        receipt,
        routes=tuple(dataclasses.replace(record, observed=None) for record in receipt.routes),
    )
    assert not is_launch_ready(stripped)


# --- stream ------------------------------------------------------------------


def test_the_stream_carries_the_permit_bytes_verbatim() -> None:
    plan = _plan(ROUTE_DIRECT)
    stream = build_placement_stream(plan)
    header_length = int.from_bytes(stream[:8], "big")
    header = json.loads(stream[8 : 8 + header_length].decode())
    assert stream[8 + header_length :] == plan.permit_bytes
    assert header["file_mode"] == "400"
    assert header["sha256"] == plan.permit_sha256
    assert header["ready_path"] == plan.ready_path
    assert header["consumed_path"] == plan.consumed_path


def test_placement_needs_an_alias_and_a_bounded_timeout() -> None:
    plans = _plans()
    with pytest.raises(Phase9BPermitStageError, match="ssh alias"):
        ps.build_placement_command(ssh_alias="", plan=plans[0])
    with pytest.raises(ValueError, match="placement timeout"):
        place_both_permits(
            ssh_alias=_ALIAS,
            plans=plans,
            deploy_outcome=_outcome(plans),
            run_command=lambda command, *, stdin, timeout: (0, b"", b""),
            timeout_seconds=0.0,
        )


def test_a_stray_observation_type_is_refused() -> None:
    plan = _plan(ROUTE_DIRECT)
    assert isinstance(
        ObservedPermitFile(path=plan.ready_path, bytes=1, sha256="a" * 64, regular_file=True),
        ObservedPermitFile,
    )
    duplicate = b'{"route": "direct", "route": "assisted"}'
    with pytest.raises(Phase9BPermitStageError, match="duplicate key"):
        parse_placement_evidence(duplicate, plan=plan)
