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
from collections.abc import Mapping, Sequence
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
    build_verification_receipt,
)
from nhc_deprot_ranker.preparation.phase9b_launch import (
    ALLOWED_ARGUMENTS,
    GUARDIAN_ENTRY,
    SUPERVISOR_ENTRY,
    LaunchState,
    LaunchTimeout,
    NextAction,
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
    verify_permit_placement,
)
from nhc_deprot_ranker.preparation.phase9b_permit_stage import (
    PLACEMENT_RECEIPT_SCHEMA_VERSION,
    ObservedPermitFile,
    PermitPlacementReceipt,
    PlacementState,
    RoutePermitPlacement,
    RoutePlacementState,
    recomputed_receipt_sha256,
)
from nhc_deprot_ranker.preparation.phase9b_preflight import PreflightResult
from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE
from nhc_deprot_ranker.quantum.phase9b_permit import (
    REQUEST_ID,
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
    """Both routes start from the same frozen Phase 7 initial geometry.

    Route A's preoptimized structure is produced inside the route at runtime, so
    it is never a build-time input and never a permit binding.
    """

    del route
    return PHASE9B_CANDIDATE.cation_xyz_sha256, PHASE9B_CANDIDATE.neutral_xyz_sha256


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


def _deploy_side(
    route: str,
) -> tuple[RoutePayload, RoutePlan, dict[str, int]]:
    payload = _payload(route)
    deploy_plan, sizes = _deploy_plan(route, payload)
    return payload, deploy_plan, sizes


def _promoted_outcome(**kw: Any) -> DeploymentOutcome:
    """A PROMOTED deployment carrying the hash closure it actually verified."""

    deploy_plans: list[RoutePlan] = []
    sizes_by_route: dict[str, dict[str, int]] = {}
    for route in (ROUTE_DIRECT, ROUTE_ASSISTED):
        _, deploy_plan, sizes = _deploy_side(route)
        deploy_plans.append(deploy_plan)
        sizes_by_route[route] = sizes
    base: dict[str, Any] = {
        "state": DeployState.PROMOTED,
        "promoted_routes": (ROUTE_ASSISTED, ROUTE_DIRECT),
        "staging_roots": {plan.route: plan.staging_root for plan in deploy_plans},
        "final_roots": {plan.route: plan.final_root for plan in deploy_plans},
        "failure_reason": None,
        "failure_roots": (),
        "ssh_invocations": 3,
        "verification": build_verification_receipt(
            plans=deploy_plans, verified_sizes=sizes_by_route
        ),
    }
    base.update(kw)
    return DeploymentOutcome(**base)


def _outcome_matching(plan: RoutePlan, *, sizes: Mapping[str, int]) -> DeploymentOutcome:
    """A deploy receipt that agrees with an *altered* plan.

    Used where the point is a guard downstream of the set comparison: it models a
    deployment that verified exactly the tampered file set, so the later check is
    the one that has to bite.
    """

    other = ROUTE_ASSISTED if plan.route == ROUTE_DIRECT else ROUTE_DIRECT
    _, other_plan, other_sizes = _deploy_side(other)
    return _promoted_outcome(
        verification=build_verification_receipt(
            plans=[plan, other_plan],
            verified_sizes={plan.route: dict(sizes), other: other_sizes},
        )
    )


def _plan(
    route: str,
    *,
    preflight: PreflightResult | None = None,
    outcome: DeploymentOutcome | None = None,
) -> lc.RouteLaunchPlan:
    payload, deploy_plan, _ = _deploy_side(route)
    return build_route_launch_plan(
        permit=_permit(route, payload),
        payload=payload,
        deploy_plan=deploy_plan,
        deploy_outcome=outcome if outcome is not None else _promoted_outcome(),
        preflight=preflight or _preflight(),
    )


def _plans(preflight: PreflightResult | None = None) -> tuple[lc.RouteLaunchPlan, ...]:
    return (_plan(ROUTE_DIRECT, preflight=preflight), _plan(ROUTE_ASSISTED, preflight=preflight))


def _outcome(plans: Sequence[lc.RouteLaunchPlan], **kw: Any) -> DeploymentOutcome:
    del plans
    return _promoted_outcome(**kw)


def _placement(plans: Sequence[lc.RouteLaunchPlan], **overrides: Any) -> PermitPlacementReceipt:
    """A launch-ready placement receipt whose digest is recomputed, not asserted."""

    records = tuple(
        RoutePermitPlacement(
            route=plan.route,
            attempt_id=plan.attempt_id,
            final_root=plan.final_root,
            permit_sha256=plan.permit_sha256,
            request_sha256=plan.request_sha256,
            payload_manifest_sha256=plan.payload_manifest_sha256,
            observed=ObservedPermitFile(
                path=plan.permit_path,
                bytes=900,
                sha256=plan.permit_sha256,
                regular_file=True,
            ),
            state=RoutePlacementState.PLACED,
            detail=None,
        )
        for plan in plans
    )
    base: dict[str, Any] = {
        "schema_version": PLACEMENT_RECEIPT_SCHEMA_VERSION,
        "phase": "9B",
        "candidate_inchikey": PHASE9B_CANDIDATE.inchikey,
        "request_id": REQUEST_ID,
        "host_identity_sha256": hashlib.sha256(_ALIAS.encode()).hexdigest(),
        "placed_at": "2026-07-26T00:00:00Z",
        "deploy_outcome_sha256": "b" * 64,
        "runner_source_sha256": plans[0].runner_source_sha256,
        "resources_sha256": plans[0].resources_sha256,
        "routes": records,
        "overall_state": PlacementState.PLACED,
        "failure_reason": None,
        "receipt_sha256": "0" * 64,
    }
    base.update(overrides)
    draft = PermitPlacementReceipt(**base)
    if "receipt_sha256" in overrides:
        return draft
    # Recompute so the fixture is internally consistent by construction; a test
    # that wants a forged receipt overrides the digest explicitly.
    return dataclasses.replace(draft, receipt_sha256=recomputed_receipt_sha256(draft))


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
        permits: dict[str, str] | None = None,
    ) -> None:
        self.codes = codes or {}
        self.timeout_for = timeout_for
        self.raise_for = raise_for
        self.identity_for = identity_for or {}
        self.stdout_for = stdout_for or {}
        self.permits: dict[str, str] = permits or {}
        self.commands: list[tuple[str, ...]] = []

    def _argv_of(self, command: Sequence[str]) -> dict[str, str]:
        """Re-parse the remote string the way a shell would, and read the flags.

        The fake answers with the permit digest the argv actually names, exactly
        as a guardian would report the permit it consumed.
        """

        tokens = shlex.split(command[-1].split("&& exec ", 1)[1])
        assert tokens[:5] == ["python3", "-B", "-s", "-m", GUARDIAN_ENTRY]
        rest = tokens[5:]
        return dict(zip(rest[::2], rest[1::2], strict=True))

    def __call__(self, command: Sequence[str], *, timeout: float) -> tuple[int, bytes, bytes]:
        assert timeout > 0
        self.commands.append(tuple(command))
        flags = self._argv_of(command)
        route = flags["--route"]
        if self.timeout_for == route:
            raise LaunchTimeout("no reply within the bound")
        if self.raise_for == route:
            raise OSError("connection reset")
        if route in self.stdout_for:
            return self.codes.get(route, 0), self.stdout_for[route], b""
        pid = 4242 if route == ROUTE_DIRECT else 4243
        evidence: dict[str, Any] = {
            "schema_version": "phase9b.guardian_acknowledgement.v1",
            "entry": GUARDIAN_ENTRY,
            "supervisor_entry": SUPERVISOR_ENTRY,
            "route": route,
            "attempt_id": ROUTE_ATTEMPT_IDS[route],
            "guardian_identity": f"guardian-{route}-0001",
            "supervisor_pid": pid,
            "supervisor_process_group_id": pid,
            "state": "permit_consumed_spawned",
            "permit_sha256": self.permits.get(route, flags["--expected-permit-sha256"]),
            "consumption_receipt_sha256": "c" * 64,
            "launch_receipt_sha256": "d" * 64,
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
        "placement": _placement(plans),
        "run_command": _FakeSsh(permits={p.route: p.permit_sha256 for p in plans}),
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
            placement=_placement(plans),
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
    deploy_plan, _ = _deploy_plan(ROUTE_DIRECT, payload)
    permit = _permit(ROUTE_DIRECT, payload)

    drifted_request = dataclasses.replace(permit, request_sha256="9" * 64)
    with pytest.raises(Phase9BLaunchError, match="request hash drifted"):
        build_route_launch_plan(
            permit=drifted_request,
            payload=payload,
            deploy_plan=deploy_plan,
            deploy_outcome=_promoted_outcome(),
            preflight=_preflight(),
        )

    drifted_manifest = dataclasses.replace(permit, payload_manifest_sha256="8" * 64)
    with pytest.raises(Phase9BLaunchError, match="payload manifest hash drifted"):
        build_route_launch_plan(
            permit=drifted_manifest,
            payload=payload,
            deploy_plan=deploy_plan,
            deploy_outcome=_promoted_outcome(),
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
            deploy_outcome=_outcome_matching(tampered, sizes=sizes),
            preflight=_preflight(),
        )


def test_a_forged_or_absent_deploy_verification_is_refused() -> None:
    """Launch no longer accepts a caller-supplied size map at all."""

    payload = _payload(ROUTE_DIRECT)
    deploy_plan, _ = _deploy_plan(ROUTE_DIRECT, payload)
    permit = _permit(ROUTE_DIRECT, payload)

    def build(outcome: DeploymentOutcome) -> lc.RouteLaunchPlan:
        return build_route_launch_plan(
            permit=permit,
            payload=payload,
            deploy_plan=deploy_plan,
            deploy_outcome=outcome,
            preflight=_preflight(),
        )

    with pytest.raises(Phase9BLaunchError, match="no verified hash closure"):
        build(_promoted_outcome(verification=None))

    honest = _promoted_outcome()
    assert honest.verification is not None
    forged_digest = dataclasses.replace(honest.verification, receipt_sha256="9" * 64)
    with pytest.raises(Phase9BLaunchError, match="digest does not match its body"):
        build(_promoted_outcome(verification=forged_digest))

    # An edited size table no longer agrees with the receipt's own digest.
    edited = dict(honest.verification.routes[ROUTE_DIRECT])
    edited[REQUEST_RELATIVE] = dataclasses.replace(edited[REQUEST_RELATIVE], bytes=1)
    tampered = dataclasses.replace(
        honest.verification,
        routes={**honest.verification.routes, ROUTE_DIRECT: edited},
    )
    with pytest.raises(Phase9BLaunchError, match="digest does not match its body"):
        build(_promoted_outcome(verification=tampered))

    # And a receipt that verified a different file set is refused outright.
    dropped = {
        member: entry
        for member, entry in honest.verification.routes[ROUTE_DIRECT].items()
        if member != REQUEST_RELATIVE
    }
    short = build_verification_receipt(
        plans=[dataclasses.replace(deploy_plan, files={m: e.sha256 for m, e in dropped.items()})],
        verified_sizes={ROUTE_DIRECT: {m: e.bytes for m, e in dropped.items()}},
    )
    with pytest.raises(Phase9BLaunchError, match="differs from the registered set"):
        build(_promoted_outcome(verification=short))


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
            deploy_outcome=_outcome_matching(
                leaked, sizes={**sizes, "private/permit.ready.json": 900}
            ),
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
            deploy_outcome=_outcome_matching(retired, sizes=sizes),
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
    deploy_plan, _ = _deploy_plan(ROUTE_DIRECT, payload)
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
                deploy_outcome=_promoted_outcome(),
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


@pytest.mark.parametrize(
    "state",
    [
        PlacementState.NOT_PLACED,
        PlacementState.PARTIALLY_PLACED,
        PlacementState.INDETERMINATE,
        PlacementState.FAILED,
    ],
)
def test_a_placement_that_is_not_fully_placed_never_launches(state: PlacementState) -> None:
    plans = _plans()
    fake = _FakeSsh()
    receipt = _launch(
        plans=plans, placement=_placement(plans, overall_state=state), run_command=fake
    )
    assert receipt.overall_state is LaunchState.NOT_LAUNCHED
    assert "not launch-ready" in (receipt.failure_reason or "")
    assert fake.commands == []


def test_a_missing_placement_receipt_never_launches() -> None:
    fake = _FakeSsh()
    receipt = _launch(placement=None, run_command=fake)
    assert receipt.overall_state is LaunchState.NOT_LAUNCHED
    assert "no permit placement receipt" in (receipt.failure_reason or "")
    assert fake.commands == []


def test_a_forged_placement_receipt_is_refused() -> None:
    """The strongest guarantee in the chain is no longer a caller's boolean."""

    plans = _plans()

    # A hand-set digest no longer matches the body it claims to cover.
    with pytest.raises(Phase9BLaunchError, match="not launch-ready"):
        verify_permit_placement(_placement(plans, receipt_sha256="1" * 64), plans=plans)

    # Claiming a permit landed without any observation is refused.
    stripped = tuple(
        dataclasses.replace(record, observed=None) for record in _placement(plans).routes
    )
    with pytest.raises(Phase9BLaunchError, match="not launch-ready"):
        verify_permit_placement(_placement(plans, routes=stripped), plans=plans)

    # And an observation naming a different permit digest cannot be substituted,
    # because the plan's digest comes from the permit bytes themselves.
    swapped = list(_placement(plans).routes)
    assert swapped[0].observed is not None
    swapped[0] = dataclasses.replace(
        swapped[0], observed=dataclasses.replace(swapped[0].observed, sha256="2" * 64)
    )
    with pytest.raises(Phase9BLaunchError, match="not the permitted bytes"):
        verify_permit_placement(_placement(plans, routes=tuple(swapped)), plans=plans)


def test_a_placement_made_against_another_closure_is_refused() -> None:
    plans = _plans()
    with pytest.raises(Phase9BLaunchError, match="another source closure"):
        verify_permit_placement(_placement(plans, runner_source_sha256="3" * 64), plans=plans)


def test_a_route_already_launched_is_never_launched_again() -> None:
    fake = _FakeSsh()
    receipt = _launch(already_launched=(ROUTE_DIRECT,), run_command=fake)
    assert receipt.overall_state is LaunchState.NOT_LAUNCHED
    assert "already launched" in (receipt.failure_reason or "")
    assert fake.commands == []
    assert {record.state for record in receipt.routes} == {RouteLaunchState.NOT_ATTEMPTED}


# --- structured argv ---------------------------------------------------------


def test_canonical_argv_is_whitelisted_and_starts_only_the_guardian() -> None:
    argv = render_launch_argv(_plan(ROUTE_DIRECT))
    assert argv[:5] == ("python3", "-B", "-s", "-m", GUARDIAN_ENTRY)
    flags = argv[5::2]
    assert sorted(flags) == sorted(ALLOWED_ARGUMENTS)
    assert len(set(flags)) == len(ALLOWED_ARGUMENTS)
    command = build_launch_command(ssh_alias=_ALIAS, project_root=_PROJECT, argv=argv)
    assert command[0] == "ssh" and "BatchMode=yes" in command
    assert GUARDIAN_ENTRY in command[-1]
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
    with pytest.raises(Phase9BLaunchError, match="guarded Phase 9B guardian entry"):
        build_launch_command(
            ssh_alias=_ALIAS,
            project_root=_PROJECT,
            argv=("python3", "-B", "-s", "-m", "pyscf.tools.run", *argv[5:]),
        )
    assert "--unregistered" not in ALLOWED_ARGUMENTS


def test_recorded_argv_is_redacted_of_absolute_paths() -> None:
    receipt = _launch()
    for record in receipt.routes:
        assert record.redacted_argv[:5] == ("python3", "-B", "-s", "-m", GUARDIAN_ENTRY)
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
    assert all(record.supervisor_identity is not None for record in receipt.routes)
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
        {"supervisor_entry": "nhc_deprot_ranker.quantum.worker"},
        {"guardian_identity": ""},
        {"supervisor_pid": 0},
        {"supervisor_pid": None},
        {"supervisor_process_group_id": 9999},
        {"state": "permit_consumed_spawn_failed"},
        {"state": "indeterminate"},
        {"permit_sha256": "e" * 64},
        {"consumption_receipt_sha256": "short"},
        {"launch_receipt_sha256": None},
    ],
)
def test_a_wrong_guardian_acknowledgement_is_indeterminate(evidence: dict[str, Any]) -> None:
    plans = _plans()
    fake = _FakeSsh(
        identity_for={ROUTE_DIRECT: evidence},
        permits={plan.route: plan.permit_sha256 for plan in plans},
    )
    receipt = _launch(plans=plans, run_command=fake)
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


def test_a_launch_timeout_may_not_span_the_computation() -> None:
    """Launch waits for a guardian acknowledgement, never for the science.

    A bound anywhere near the frozen wall-time would mean the SSH channel was
    holding the computation open, which is the design the guardian replaced.
    """

    plans = _plans()
    wall_time = float(PHASE9B_RESOURCES["hard_wall_timeout_seconds"])  # type: ignore[arg-type]
    assert wall_time > lc.MAX_LAUNCH_ACKNOWLEDGEMENT_SECONDS
    assert lc.LAUNCH_ACKNOWLEDGEMENT_TIMEOUT_SECONDS <= lc.MAX_LAUNCH_ACKNOWLEDGEMENT_SECONDS

    for bad in (0.0, -1.0, lc.MAX_LAUNCH_ACKNOWLEDGEMENT_SECONDS + 1.0, wall_time, 7200.0):
        with pytest.raises(ValueError, match="timeout"):
            _launch(plans=plans, timeout_seconds=bad)


def test_launch_starts_the_guardian_and_never_the_supervisor() -> None:
    fake = _FakeSsh()
    receipt = _launch(run_command=fake)
    assert receipt.overall_state is LaunchState.LAUNCHED
    for command in fake.commands:
        remote = command[-1]
        assert GUARDIAN_ENTRY in remote
        assert f"-m {SUPERVISOR_ENTRY}" not in remote
        for backend in ("aimnet", "pyscf", "torch"):
            assert backend not in remote
