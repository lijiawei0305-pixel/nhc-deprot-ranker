"""Phase 9B launch regressions.

No chemistry, no server, no compute, no permit consumption. Every remote call,
supervisor identity, PID, and network fault is driven through an injected fake,
so nothing here reaches a network or starts a process. Every enumerated failure
mode in the launch contract is exercised.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from nhc_deprot_ranker.preparation import phase9b_launch as lc
from nhc_deprot_ranker.preparation.phase9b_bundle import (
    PAYLOAD_MANIFEST_RELATIVE,
    RoutePayload,
    build_route_payload,
    build_route_request,
)
from nhc_deprot_ranker.preparation.phase9b_deploy import (
    DeploymentOutcome,
    DeployState,
    RoutePlan,
    build_route_plan,
)
from nhc_deprot_ranker.preparation.phase9b_launch import (
    ALLOWED_ARGUMENTS,
    SUPERVISOR_ENTRY,
    LaunchState,
    LaunchTimeout,
    NextAction,
    PermitPresence,
    Phase9BLaunchError,
    Phase9BLaunchNotAuthorizedError,
    RouteLaunchState,
    build_launch_command,
    build_route_launch_plan,
    launch_both_routes,
    next_action_for,
    receipt_payload,
    redact_argv,
    render_launch_argv,
    validate_argument_value,
    validate_plan_pair,
    verify_deploy_outcome,
    verify_permit_unconsumed,
)
from nhc_deprot_ranker.preparation.phase9b_preflight import PreflightResult
from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE
from nhc_deprot_ranker.quantum.phase9b_permit import (
    REQUEST_RELATIVE,
    ROUTE_ASSISTED,
    ROUTE_ATTEMPT_IDS,
    ROUTE_DIRECT,
    Phase9BPermit,
    parse_phase9b_permit,
    render_phase9b_permit,
)
from nhc_deprot_ranker.quantum.phase9b_resources import (
    PHASE9B_RESOURCES,
    phase9b_resources_payload,
)
from nhc_deprot_ranker.quantum.two_endpoint import LOCKED_PROTOCOL, current_runner_source_sha256

_PROJECT = "/srv/project"
_ALIAS = "gpu-node"
_PRE_C = "4" * 64
_PRE_N = "5" * 64
_XYZ_MEMBERS = ("xyz/cation.xyz", "xyz/neutral.xyz")


def _endpoints(route: str) -> tuple[str, str]:
    if route == ROUTE_DIRECT:
        return PHASE9B_CANDIDATE.cation_xyz_sha256, PHASE9B_CANDIDATE.neutral_xyz_sha256
    return _PRE_C, _PRE_N


def _payload(route: str) -> RoutePayload:
    cation, neutral = _endpoints(route)
    return build_route_payload(
        build_route_request(
            route=route,
            runner_source_sha256=current_runner_source_sha256(),
            protocol=LOCKED_PROTOCOL,
            cation_xyz_sha256=cation,
            neutral_xyz_sha256=neutral,
        )
    )


def _permit(route: str, payload: RoutePayload) -> Phase9BPermit:
    cation, neutral = _endpoints(route)
    return parse_phase9b_permit(
        render_phase9b_permit(
            route=route,
            project_root=_PROJECT,
            request_sha256=payload.request.request_sha256,
            runner_source_sha256=current_runner_source_sha256(),
            payload_manifest_sha256=payload.manifest_sha256,
            cation_xyz_sha256=cation,
            neutral_xyz_sha256=neutral,
            resources=phase9b_resources_payload(),
        )
    )


def _deploy_plan(route: str, payload: RoutePayload) -> tuple[RoutePlan, dict[str, int]]:
    files = {
        REQUEST_RELATIVE: payload.request.request_sha256,
        PAYLOAD_MANIFEST_RELATIVE: payload.manifest_sha256,
    }
    sizes = {
        REQUEST_RELATIVE: len(payload.request.request_bytes),
        PAYLOAD_MANIFEST_RELATIVE: len(payload.manifest_bytes),
    }
    for index, member in enumerate(_XYZ_MEMBERS):
        files[member] = hashlib.sha256(f"{route}-{member}".encode()).hexdigest()
        sizes[member] = 128 + index
    plan = build_route_plan(
        route=route,
        project_root=_PROJECT,
        attempt_id=ROUTE_ATTEMPT_IDS[route],
        files=files,
    )
    return plan, sizes


def _preflight(**kw: Any) -> PreflightResult:
    base: dict[str, Any] = {
        "torch_version": "2.4.1",
        "ase_version": "3.23.0",
        "aimnet_version": "1.1.0",
        "pyscf_version": "2.6.2",
        "geometric_version": "1.0.2",
        "dispersion_version": "1.2.0",
        "weight_sha256": "f" * 64,
        "selected_gpu_index": 2,
        "free_gpu_count": 3,
        "memory_available_kib": 64 * 1024 * 1024,
        "disk_available_bytes": 512 * 1024**3,
        "wrote_nothing": True,
    }
    base.update(kw)
    return PreflightResult(**base)


def _plan(route: str, *, preflight: PreflightResult | None = None) -> lc.RouteLaunchPlan:
    payload = _payload(route)
    deploy_plan, sizes = _deploy_plan(route, payload)
    return build_route_launch_plan(
        permit=_permit(route, payload),
        payload=payload,
        deploy_plan=deploy_plan,
        verified_sizes=sizes,
        preflight=preflight or _preflight(),
    )


def _plans(preflight: PreflightResult | None = None) -> tuple[lc.RouteLaunchPlan, ...]:
    return (_plan(ROUTE_DIRECT, preflight=preflight), _plan(ROUTE_ASSISTED, preflight=preflight))


def _outcome(plans: Sequence[lc.RouteLaunchPlan], **kw: Any) -> DeploymentOutcome:
    base: dict[str, Any] = {
        "state": DeployState.PROMOTED,
        "promoted_routes": tuple(sorted(plan.route for plan in plans)),
        "staging_roots": {plan.route: plan.staging_root for plan in plans},
        "final_roots": {plan.route: plan.final_root for plan in plans},
        "failure_reason": None,
        "failure_roots": (),
        "ssh_invocations": 3,
    }
    base.update(kw)
    return DeploymentOutcome(**base)


def _presence(plans: Sequence[lc.RouteLaunchPlan], **kw: Any) -> dict[str, PermitPresence]:
    out = {
        plan.route: PermitPresence(
            ready_present=True, consumed_present=False, ready_sha256=plan.permit_sha256
        )
        for plan in plans
    }
    for route, override in kw.items():
        out[route] = override
    return out


class _FakeSsh:
    """Simulates one supervisor start per route, with no network and no shell."""

    def __init__(
        self,
        *,
        codes: dict[str, int] | None = None,
        timeout_for: str | None = None,
        raise_for: str | None = None,
        identity_for: dict[str, dict[str, Any]] | None = None,
        stdout_for: dict[str, bytes] | None = None,
    ) -> None:
        self.codes = codes or {}
        self.timeout_for = timeout_for
        self.raise_for = raise_for
        self.identity_for = identity_for or {}
        self.stdout_for = stdout_for or {}
        self.commands: list[tuple[str, ...]] = []

    def _route_of(self, command: Sequence[str]) -> str:
        """Re-parse the remote string the way a shell would, and read --route."""

        tokens = shlex.split(command[-1].split("&& exec ", 1)[1])
        assert tokens[:5] == ["python3", "-B", "-s", "-m", SUPERVISOR_ENTRY]
        return tokens[tokens.index("--route") + 1]

    def __call__(self, command: Sequence[str], *, timeout: float) -> tuple[int, bytes, bytes]:
        assert timeout > 0
        self.commands.append(tuple(command))
        route = self._route_of(command)
        if self.timeout_for == route:
            raise LaunchTimeout("no reply within the bound")
        if self.raise_for == route:
            raise OSError("connection reset")
        if route in self.stdout_for:
            return self.codes.get(route, 0), self.stdout_for[route], b""
        evidence: dict[str, Any] = {
            "supervisor_identity": f"supervisor-{route}-0001",
            "attempt_id": ROUTE_ATTEMPT_IDS[route],
            "route": route,
            "entry": SUPERVISOR_ENTRY,
            "pid": 4242 if route == ROUTE_DIRECT else 4243,
        }
        evidence.update(self.identity_for.get(route, {}))
        return self.codes.get(route, 0), json.dumps(evidence).encode(), b""


def _launch(**kw: Any) -> lc.LaunchReceipt:
    plans = kw.pop("plans", None) or _plans()
    params: dict[str, Any] = {
        "ssh_alias": _ALIAS,
        "project_root": _PROJECT,
        "plans": plans,
        "deploy_outcome": _outcome(plans),
        "preflight": _preflight(),
        "permit_presence": _presence(plans),
        "run_command": _FakeSsh(),
        "clock": lambda: "2026-07-26T00:00:00Z",
    }
    params.update(kw)
    return launch_both_routes(**params)


# --- source gate and closure -------------------------------------------------


def test_source_gate_is_closed_and_a_real_launch_refuses() -> None:
    assert lc.EXECUTION_AUTHORIZED is False
    source = Path(lc.__file__).read_text(encoding="utf-8")
    assert "EXECUTION_AUTHORIZED: Final[bool] = False" in source
    plans = _plans()
    with pytest.raises(Phase9BLaunchNotAuthorizedError, match="not authorized"):
        launch_both_routes(
            ssh_alias=_ALIAS,
            project_root=_PROJECT,
            plans=plans,
            deploy_outcome=_outcome(plans),
            preflight=_preflight(),
            permit_presence=_presence(plans),
        )


def test_launch_module_is_outside_the_runner_source_closure() -> None:
    from nhc_deprot_ranker.quantum import two_endpoint

    closure = two_endpoint._RUNNER_SOURCE_RELATIVE_PATHS
    assert "preparation/phase9b_launch.py" not in closure
    assert not any(path.endswith("phase9b_launch.py") for path in closure)


def test_launch_never_imports_or_calls_a_compute_backend() -> None:
    """AST-scanned: docstrings legitimately name the backends, code must not."""

    tree = ast.parse(Path(lc.__file__).read_text(encoding="utf-8"))
    banned = {"torch", "ase", "aimnet", "aimnet2", "pyscf", "geometric", "dftd3", "subprocess"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & banned)
    identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert not (identifiers & banned)


# --- deploy receipt proof obligations ---------------------------------------


def test_missing_deploy_receipt_is_not_launched() -> None:
    fake = _FakeSsh()
    receipt = _launch(deploy_outcome=None, run_command=fake)
    assert receipt.overall_state is LaunchState.NOT_LAUNCHED
    assert receipt.failure_reason is not None and "no deploy receipt" in receipt.failure_reason
    assert fake.commands == []


@pytest.mark.parametrize(
    "state", [DeployState.STAGED, DeployState.REMOTE_VERIFIED, DeployState.FAILED]
)
def test_deploy_that_is_not_promoted_is_not_launched(state: DeployState) -> None:
    plans = _plans()
    fake = _FakeSsh()
    receipt = _launch(plans=plans, deploy_outcome=_outcome(plans, state=state), run_command=fake)
    assert receipt.overall_state is LaunchState.NOT_LAUNCHED
    assert "not PROMOTED" in (receipt.failure_reason or "")
    assert fake.commands == []


def test_possibly_partial_promotion_is_not_launched() -> None:
    plans = _plans()
    partial = _outcome(
        plans,
        state=DeployState.FAILED,
        promoted_routes=(),
        failure_reason="promotion failed and may be partial: 1 ",
        failure_roots=tuple(plan.final_root for plan in plans),
    )
    fake = _FakeSsh()
    assert _launch(plans=plans, deploy_outcome=partial, run_command=fake).overall_state is (
        LaunchState.NOT_LAUNCHED
    )
    # And a receipt that claims promotion while still naming a failure is refused.
    contradictory = _outcome(plans, failure_reason="promotion failed and may be partial")
    with pytest.raises(Phase9BLaunchError, match="claims promotion but names a failure"):
        verify_deploy_outcome(contradictory, plans=plans)
    assert fake.commands == []


def test_final_root_drift_is_not_launched() -> None:
    plans = _plans()
    drifted = _outcome(
        plans,
        final_roots={
            ROUTE_DIRECT: plans[0].final_root,
            ROUTE_ASSISTED: f"{plans[1].final_root}-other",
        },
    )
    fake = _FakeSsh()
    receipt = _launch(plans=plans, deploy_outcome=drifted, run_command=fake)
    assert receipt.overall_state is LaunchState.NOT_LAUNCHED
    assert "final root drifted" in (receipt.failure_reason or "")
    assert fake.commands == []


def test_a_deploy_with_a_single_route_or_wrong_call_count_is_refused() -> None:
    plans = _plans()
    with pytest.raises(Phase9BLaunchError, match="exactly both routes"):
        verify_deploy_outcome(_outcome(plans, promoted_routes=(ROUTE_DIRECT,)), plans=plans)
    with pytest.raises(Phase9BLaunchError, match="SSH calls"):
        verify_deploy_outcome(_outcome(plans, ssh_invocations=2), plans=plans)


# --- frozen identity cross-validation ---------------------------------------


def test_request_payload_and_permit_hashes_must_agree() -> None:
    payload = _payload(ROUTE_DIRECT)
    deploy_plan, sizes = _deploy_plan(ROUTE_DIRECT, payload)
    permit = _permit(ROUTE_DIRECT, payload)

    drifted_request = dataclasses.replace(permit, request_sha256="9" * 64)
    with pytest.raises(Phase9BLaunchError, match="request hash drifted"):
        build_route_launch_plan(
            permit=drifted_request,
            payload=payload,
            deploy_plan=deploy_plan,
            verified_sizes=sizes,
            preflight=_preflight(),
        )

    drifted_manifest = dataclasses.replace(permit, payload_manifest_sha256="8" * 64)
    with pytest.raises(Phase9BLaunchError, match="payload manifest hash drifted"):
        build_route_launch_plan(
            permit=drifted_manifest,
            payload=payload,
            deploy_plan=deploy_plan,
            verified_sizes=sizes,
            preflight=_preflight(),
        )


def test_a_deployed_file_whose_hash_drifted_is_refused() -> None:
    payload = _payload(ROUTE_DIRECT)
    deploy_plan, sizes = _deploy_plan(ROUTE_DIRECT, payload)
    tampered = dataclasses.replace(
        deploy_plan, files={**deploy_plan.files, REQUEST_RELATIVE: "7" * 64}
    )
    with pytest.raises(Phase9BLaunchError, match="not the permitted request"):
        build_route_launch_plan(
            permit=_permit(ROUTE_DIRECT, payload),
            payload=payload,
            deploy_plan=tampered,
            verified_sizes=sizes,
            preflight=_preflight(),
        )


def test_a_missing_or_invalid_byte_size_is_refused() -> None:
    payload = _payload(ROUTE_DIRECT)
    deploy_plan, sizes = _deploy_plan(ROUTE_DIRECT, payload)
    permit = _permit(ROUTE_DIRECT, payload)
    short = {member: size for member, size in sizes.items() if member != REQUEST_RELATIVE}
    with pytest.raises(Phase9BLaunchError, match="differs from the registered set"):
        build_route_launch_plan(
            permit=permit,
            payload=payload,
            deploy_plan=deploy_plan,
            verified_sizes=short,
            preflight=_preflight(),
        )
    with pytest.raises(Phase9BLaunchError, match="byte size is invalid"):
        build_route_launch_plan(
            permit=permit,
            payload=payload,
            deploy_plan=deploy_plan,
            verified_sizes={**sizes, REQUEST_RELATIVE: 0},
            preflight=_preflight(),
        )


def test_a_deployed_permit_file_is_refused() -> None:
    payload = _payload(ROUTE_DIRECT)
    deploy_plan, sizes = _deploy_plan(ROUTE_DIRECT, payload)
    leaked = dataclasses.replace(
        deploy_plan,
        files={**deploy_plan.files, "private/permit.ready.json": "6" * 64},
    )
    with pytest.raises(Phase9BLaunchError, match="contains a permit file"):
        build_route_launch_plan(
            permit=_permit(ROUTE_DIRECT, payload),
            payload=payload,
            deploy_plan=leaked,
            verified_sizes={**sizes, "private/permit.ready.json": 900},
            preflight=_preflight(),
        )


def test_a_retired_phase8b_artifact_is_refused() -> None:
    payload = _payload(ROUTE_DIRECT)
    deploy_plan, sizes = _deploy_plan(ROUTE_DIRECT, payload)
    retired = dataclasses.replace(
        deploy_plan, final_root="/srv/project/data/runs/nhc_phase8b_qxh_smoke/direct"
    )
    with pytest.raises(Phase9BLaunchError, match="retired Phase 8B artifact"):
        build_route_launch_plan(
            permit=_permit(ROUTE_DIRECT, payload),
            payload=payload,
            deploy_plan=retired,
            verified_sizes=sizes,
            preflight=_preflight(),
        )
    with pytest.raises(Phase9BLaunchError, match="retired Phase 8B artifact"):
        build_launch_command(
            ssh_alias=_ALIAS,
            project_root="/srv/phase8b-project",
            argv=render_launch_argv(_plan(ROUTE_DIRECT)),
        )


def test_a_launch_plan_never_selects_gpu_cpu_or_timeout() -> None:
    plan = _plan(ROUTE_DIRECT, preflight=_preflight(selected_gpu_index=5))
    assert plan.gpu_index == 5
    assert plan.cpu_affinity == PHASE9B_RESOURCES["cpu_affinity"]
    assert plan.timeout_seconds == PHASE9B_RESOURCES["hard_wall_timeout_seconds"]


def test_resource_or_host_drift_is_refused() -> None:
    payload = _payload(ROUTE_DIRECT)
    deploy_plan, sizes = _deploy_plan(ROUTE_DIRECT, payload)
    permit = _permit(ROUTE_DIRECT, payload)
    for preflight, message in (
        (_preflight(wrote_nothing=False), "wrote nothing"),
        (_preflight(selected_gpu_index=-1), "no usable GPU index"),
        (_preflight(free_gpu_count=0), "device budget"),
    ):
        with pytest.raises(Phase9BLaunchError, match=message):
            build_route_launch_plan(
                permit=permit,
                payload=payload,
                deploy_plan=deploy_plan,
                verified_sizes=sizes,
                preflight=preflight,
            )


def test_routes_that_disagree_on_a_frozen_field_are_refused() -> None:
    direct, assisted = _plans()
    with pytest.raises(Phase9BLaunchError, match="disagree on a frozen field: gpu_index"):
        validate_plan_pair((direct, dataclasses.replace(assisted, gpu_index=direct.gpu_index + 1)))
    with pytest.raises(Phase9BLaunchError, match="disagree on a frozen field: cpu_affinity"):
        validate_plan_pair((direct, dataclasses.replace(assisted, cpu_affinity="0-7")))
    with pytest.raises(Phase9BLaunchError, match="distinct one-shot permits"):
        validate_plan_pair(
            (direct, dataclasses.replace(assisted, permit_sha256=direct.permit_sha256))
        )
    with pytest.raises(Phase9BLaunchError, match="distinct request identities"):
        validate_plan_pair(
            (direct, dataclasses.replace(assisted, request_sha256=direct.request_sha256))
        )
    with pytest.raises(Phase9BLaunchError, match="distinct payload manifests"):
        validate_plan_pair(
            (
                direct,
                dataclasses.replace(
                    assisted, payload_manifest_sha256=direct.payload_manifest_sha256
                ),
            )
        )


# --- one-shot semantics ------------------------------------------------------


def test_a_consumed_permit_never_launches() -> None:
    plans = _plans()
    consumed = _presence(
        plans,
        **{
            ROUTE_ASSISTED: PermitPresence(
                ready_present=False, consumed_present=True, ready_sha256=None
            )
        },
    )
    fake = _FakeSsh()
    receipt = _launch(plans=plans, permit_presence=consumed, run_command=fake)
    assert receipt.overall_state is LaunchState.NOT_LAUNCHED
    assert "already consumed" in (receipt.failure_reason or "")
    assert fake.commands == []


def test_a_missing_or_mismatched_ready_permit_never_launches() -> None:
    plans = _plans()
    with pytest.raises(Phase9BLaunchError, match="no ready permit"):
        verify_permit_unconsumed(
            _presence(
                plans,
                **{
                    ROUTE_DIRECT: PermitPresence(
                        ready_present=False, consumed_present=False, ready_sha256=None
                    )
                },
            ),
            plans=plans,
        )
    with pytest.raises(Phase9BLaunchError, match="not the permitted bytes"):
        verify_permit_unconsumed(
            _presence(
                plans,
                **{
                    ROUTE_DIRECT: PermitPresence(
                        ready_present=True, consumed_present=False, ready_sha256="0" * 64
                    )
                },
            ),
            plans=plans,
        )
    with pytest.raises(Phase9BLaunchError, match="no permit state"):
        verify_permit_unconsumed({}, plans=plans)


def test_a_route_already_launched_is_never_launched_again() -> None:
    fake = _FakeSsh()
    receipt = _launch(already_launched=(ROUTE_DIRECT,), run_command=fake)
    assert receipt.overall_state is LaunchState.NOT_LAUNCHED
    assert "already launched" in (receipt.failure_reason or "")
    assert fake.commands == []
    assert {record.state for record in receipt.routes} == {RouteLaunchState.NOT_ATTEMPTED}


# --- structured argv ---------------------------------------------------------


def test_canonical_argv_is_whitelisted_and_starts_only_the_supervisor() -> None:
    argv = render_launch_argv(_plan(ROUTE_DIRECT))
    assert argv[:5] == ("python3", "-B", "-s", "-m", SUPERVISOR_ENTRY)
    flags = argv[5::2]
    assert sorted(flags) == sorted(ALLOWED_ARGUMENTS)
    assert len(set(flags)) == len(ALLOWED_ARGUMENTS)
    command = build_launch_command(ssh_alias=_ALIAS, project_root=_PROJECT, argv=argv)
    assert command[0] == "ssh" and "BatchMode=yes" in command
    assert SUPERVISOR_ENTRY in command[-1]
    for backend in ("aimnet", "pyscf", "torch", "bash", "sh -c"):
        assert backend not in command[-1]


@pytest.mark.parametrize(
    "hostile",
    [
        "/srv/$(id)/run",
        "/srv/`id`/run",
        "/srv/run;rm -rf /",
        "/srv/run\nmalicious",
        "/srv/run\x00",
        "/srv/../../etc/run",
        "/srv/run|tee",
        "/srv/run&background",
        "/srv/*/run",
        "/srv/~root/run",
        "/srv/run\x07",
    ],
)
def test_command_injection_is_refused_before_any_call(hostile: str) -> None:
    with pytest.raises(Phase9BLaunchError):
        validate_argument_value(hostile, label="--request-path")
    plan = dataclasses.replace(_plan(ROUTE_DIRECT), request_path=hostile)
    with pytest.raises(Phase9BLaunchError):
        render_launch_argv(plan)


def test_a_non_whitelisted_or_extra_argument_is_refused() -> None:
    plan = _plan(ROUTE_DIRECT)
    argv = render_launch_argv(plan)
    with pytest.raises(Phase9BLaunchError, match="unexpected argument count"):
        build_launch_command(
            ssh_alias=_ALIAS, project_root=_PROJECT, argv=(*argv, "--unregistered", "1")
        )
    with pytest.raises(Phase9BLaunchError, match="guarded Phase 9B supervisor entry"):
        build_launch_command(
            ssh_alias=_ALIAS,
            project_root=_PROJECT,
            argv=("python3", "-B", "-s", "-m", "pyscf.tools.run", *argv[5:]),
        )
    assert "--unregistered" not in ALLOWED_ARGUMENTS


def test_recorded_argv_is_redacted_of_absolute_paths() -> None:
    receipt = _launch()
    for record in receipt.routes:
        assert record.redacted_argv[:5] == ("python3", "-B", "-s", "-m", SUPERVISOR_ENTRY)
        assert not any(token.startswith("/") for token in record.redacted_argv)
        assert "<PATH>" in record.redacted_argv
    assert redact_argv(("/srv/x", "plain")) == ("<PATH>", "plain")


# --- two-route transaction ---------------------------------------------------


def test_both_routes_launch_in_the_frozen_order_and_report_distinct_identities() -> None:
    fake = _FakeSsh()
    receipt = _launch(run_command=fake)
    assert receipt.overall_state is LaunchState.LAUNCHED
    assert [record.route for record in receipt.routes] == [ROUTE_DIRECT, ROUTE_ASSISTED]
    assert len(fake.commands) == 2
    identities = {record.supervisor_identity for record in receipt.routes}
    assert len(identities) == 2 and None not in identities
    assert {record.supervisor_pid for record in receipt.routes} == {4242, 4243}
    assert {record.attempt_id for record in receipt.routes} == set(ROUTE_ATTEMPT_IDS.values())
    assert next_action_for(receipt) is NextAction.PROCEED_TO_POSTFLIGHT


def test_a_launch_transaction_covering_one_route_is_refused() -> None:
    direct, _ = _plans()
    with pytest.raises(Phase9BLaunchError, match="exactly both routes"):
        validate_plan_pair((direct,))
    with pytest.raises(Phase9BLaunchError, match="exactly both routes"):
        _launch(plans=(direct,))


def test_direct_launched_then_assisted_failed_is_partially_launched() -> None:
    fake = _FakeSsh(codes={ROUTE_ASSISTED: 1})
    receipt = _launch(run_command=fake)
    assert receipt.overall_state is LaunchState.PARTIALLY_LAUNCHED
    states = {record.route: record.state for record in receipt.routes}
    assert states[ROUTE_DIRECT] is RouteLaunchState.LAUNCHED
    assert states[ROUTE_ASSISTED] is RouteLaunchState.FAILED
    # No auto-retry, no rollback, no backfill.
    assert len(fake.commands) == 2
    assert next_action_for(receipt) is NextAction.STOP_AND_REPORT


def test_direct_failed_means_assisted_is_never_started() -> None:
    fake = _FakeSsh(codes={ROUTE_DIRECT: 1})
    receipt = _launch(run_command=fake)
    assert receipt.overall_state is LaunchState.FAILED
    states = {record.route: record.state for record in receipt.routes}
    assert states[ROUTE_DIRECT] is RouteLaunchState.FAILED
    assert states[ROUTE_ASSISTED] is RouteLaunchState.NOT_ATTEMPTED
    assert len(fake.commands) == 1


def test_transport_failure_on_the_second_route_is_partially_launched() -> None:
    receipt = _launch(run_command=_FakeSsh(raise_for=ROUTE_ASSISTED))
    assert receipt.overall_state is LaunchState.PARTIALLY_LAUNCHED
    assert "transport failed" in (receipt.failure_reason or "")


# --- unknown remote state ----------------------------------------------------


def test_ssh_timeout_with_unknown_remote_state_is_indeterminate() -> None:
    fake = _FakeSsh(timeout_for=ROUTE_DIRECT)
    receipt = _launch(run_command=fake)
    assert receipt.overall_state is LaunchState.INDETERMINATE
    assert "indeterminate" in (receipt.failure_reason or "")
    states = {record.route: record.state for record in receipt.routes}
    assert states[ROUTE_DIRECT] is RouteLaunchState.INDETERMINATE
    assert states[ROUTE_ASSISTED] is RouteLaunchState.NOT_ATTEMPTED
    assert len(fake.commands) == 1
    assert next_action_for(receipt) is NextAction.STOP_AND_REPORT


def test_a_timeout_after_one_route_launched_stays_indeterminate() -> None:
    receipt = _launch(run_command=_FakeSsh(timeout_for=ROUTE_ASSISTED))
    # Indeterminate dominates: one route is known started, the other is unknown.
    assert receipt.overall_state is LaunchState.INDETERMINATE


@pytest.mark.parametrize(
    "evidence",
    [
        {"attempt_id": ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED]},
        {"route": ROUTE_ASSISTED},
        {"entry": "nhc_deprot_ranker.quantum.worker"},
        {"supervisor_identity": ""},
        {"pid": 0},
    ],
)
def test_a_wrong_supervisor_identity_is_indeterminate(evidence: dict[str, Any]) -> None:
    fake = _FakeSsh(identity_for={ROUTE_DIRECT: evidence})
    receipt = _launch(run_command=fake)
    assert receipt.overall_state is LaunchState.INDETERMINATE
    assert receipt.routes[0].state is RouteLaunchState.INDETERMINATE
    assert len(fake.commands) == 1


def test_unparseable_launch_evidence_is_indeterminate() -> None:
    receipt = _launch(run_command=_FakeSsh(stdout_for={ROUTE_DIRECT: b"not json"}))
    assert receipt.overall_state is LaunchState.INDETERMINATE
    assert "not strict JSON" in (receipt.routes[0].detail or "")


def test_oversized_launch_output_is_indeterminate() -> None:
    payload = json.dumps({"pad": "x" * (300 * 1024)}).encode()
    receipt = _launch(run_command=_FakeSsh(stdout_for={ROUTE_DIRECT: payload}))
    assert receipt.overall_state is LaunchState.INDETERMINATE
    assert "exceeded its bound" in (receipt.routes[0].detail or "")


# --- receipt schema ----------------------------------------------------------


def test_receipt_carries_the_registered_evidence_and_no_result_field() -> None:
    receipt = _launch()
    body = receipt_payload(receipt)
    assert body["schema_version"] == lc.LAUNCH_RECEIPT_SCHEMA_VERSION
    assert body["phase"] == "9B"
    assert body["candidate_inchikey"] == PHASE9B_CANDIDATE.inchikey
    assert body["scientific_result_present"] is False
    assert body["overall_state"] == "launched"
    assert body["host_identity_sha256"] == hashlib.sha256(_ALIAS.encode()).hexdigest()
    assert body["started_at"] == "2026-07-26T00:00:00Z"
    for key in (
        "deploy_outcome_sha256",
        "preflight_receipt_sha256",
        "resources_sha256",
        "runner_source_sha256",
    ):
        assert isinstance(body[key], str) and len(str(body[key])) == 64
    routes = body["routes"]
    assert isinstance(routes, list) and len(routes) == 2
    for entry in routes:
        for key in (
            "request_sha256",
            "payload_manifest_sha256",
            "permit_sha256",
            "argv_sha256",
            "stdout_sha256",
            "stderr_sha256",
        ):
            assert len(str(entry[key])) == 64
        assert entry["ssh_returncode"] == 0
    # Per-route identities are distinct: neither route can be reading the other's.
    for key in ("request_sha256", "payload_manifest_sha256", "permit_sha256", "argv_sha256"):
        assert len({entry[key] for entry in routes}) == 2
    # Serializable, and free of every banned result field.
    text = json.dumps(body, sort_keys=True)
    for banned in ("hartree", "kcal", "dft_deprot", "scf_converged", "aimnet2_energy"):
        assert banned not in text


@pytest.mark.parametrize(
    "field",
    [
        "cation_energy_hartree",
        "aimnet2_forces",
        "scf_converged",
        "geometry_converged",
        "dft_deprot_electronic_kcal",
        "label",
        "computation_succeeded",
    ],
)
def test_a_receipt_annotation_naming_a_result_is_refused(field: str) -> None:
    receipt = _launch()
    with pytest.raises(Phase9BLaunchError, match="must not carry a result field"):
        receipt_payload(receipt, annotations={field: 1.0})


def test_a_receipt_annotation_may_not_shadow_a_registered_field() -> None:
    receipt = _launch()
    with pytest.raises(Phase9BLaunchError, match="may not shadow"):
        receipt_payload(receipt, annotations={"overall_state": "launched"})
    assert receipt_payload(receipt, annotations={"operator": "on-call"})["annotations"] == {
        "operator": "on-call"
    }


def test_every_terminal_state_still_reports_both_routes() -> None:
    for runner, expected in (
        (_FakeSsh(), LaunchState.LAUNCHED),
        (_FakeSsh(codes={ROUTE_ASSISTED: 1}), LaunchState.PARTIALLY_LAUNCHED),
        (_FakeSsh(codes={ROUTE_DIRECT: 1}), LaunchState.FAILED),
        (_FakeSsh(timeout_for=ROUTE_DIRECT), LaunchState.INDETERMINATE),
    ):
        receipt = _launch(run_command=runner)
        assert receipt.overall_state is expected
        body = receipt_payload(receipt)
        routes = body["routes"]
        assert isinstance(routes, list)
        assert [entry["route"] for entry in routes] == [ROUTE_DIRECT, ROUTE_ASSISTED]
        assert all(entry["final_root"] for entry in routes)
