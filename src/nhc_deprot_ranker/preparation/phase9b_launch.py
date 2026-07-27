"""Phase 9B two-route launch control.

Control plane, not runner source.  Like ``phase9b_deploy`` it lives outside
``_RUNNER_SOURCE_RELATIVE_PATHS``, so adding or editing it cannot change
``runner_source_sha256`` and therefore cannot invalidate a frozen request,
payload manifest, or permit.

It **consumes** frozen assets and never rebuilds one.  The permit, the payload,
the deploy plan, the deployment outcome, and the read-only preflight result all
arrive already validated, and are cross-checked against each other before any
remote call is made.

It selects nothing.  GPU index comes from the preflight record, CPU affinity and
timeout from the frozen resource budget, roots and attempt identity from the
permit and deploy plan, route order from ``PHASE9B_RESOURCES["routes"]``.  Every
one of those is cross-validated rather than trusted.

It starts only the guarded Phase 9B supervisor entry, through a structured argv
built from a strict whitelist.  It never imports or calls AIMNet2 or PySCF,
never runs a shell, and never accepts free text.

Both routes are one experiment identity.  If either cannot launch, neither does.
"""

from __future__ import annotations

import hashlib
import json
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final, Protocol, cast

from nhc_deprot_ranker.preparation.phase9b_bundle import (
    PAYLOAD_MANIFEST_RELATIVE,
    RoutePayload,
)
from nhc_deprot_ranker.preparation.phase9b_deploy import (
    DEPLOY_VERIFICATION_SCHEMA_VERSION,
    DeploymentOutcome,
    DeployState,
    DeployVerificationReceipt,
    RoutePlan,
    recomputed_verification_sha256,
)
from nhc_deprot_ranker.preparation.phase9b_permit_stage import (
    PLACEMENT_RECEIPT_SCHEMA_VERSION,
    PermitPlacementReceipt,
    Phase9BPermitStageError,
    observed_permits,
)
from nhc_deprot_ranker.preparation.phase9b_preflight import PreflightResult
from nhc_deprot_ranker.quantum.phase9b_permit import (
    REQUEST_ID,
    REQUEST_RELATIVE,
    ROUTE_ASSISTED,
    ROUTE_ATTEMPT_IDS,
    ROUTE_DIRECT,
    Phase9BPermit,
)
from nhc_deprot_ranker.quantum.phase9b_resources import (
    PHASE9B_RESOURCES,
    phase9b_resources_sha256,
)

# Real launching is a separate authorization.  Source-level gate.
EXECUTION_AUTHORIZED: Final[bool] = False

# v2: the launch target is the guardian, and success requires a verified
# acknowledgement rather than an SSH return code.
LAUNCH_RECEIPT_SCHEMA_VERSION: Final = "phase9b.launch_receipt.v2"
GUARDIAN_LAUNCHED_STATE: Final = "permit_consumed_spawned"

CANDIDATE_INCHIKEY: Final = "LBNPGYISTSLAHY-UHFFFAOYSA-N"

# The only entry that may be started.  Anything else is a bypass.
#
# The launch control plane starts the **guardian**, never the supervisor.  The
# guardian consumes the permit, builds the handshake, spawns the supervisor into
# its own session, and exits promptly with a short acknowledgement.  Starting the
# supervisor directly would bind this bounded SSH call to a 7200 s computation
# and would skip permit consumption entirely.
GUARDIAN_ENTRY: Final = "nhc_deprot_ranker.quantum.phase9b_guardian"
SUPERVISOR_ENTRY: Final = "nhc_deprot_ranker.quantum.phase9b_supervisor"
CAMPAIGN_GUARDIAN_ENTRY_V3: Final = "nhc_deprot_ranker.quantum.phase9b_campaign_guardian"
DIRECT_GUARDIAN_ENTRY_V3: Final = GUARDIAN_ENTRY

# ``-B`` writes no bytecode and ``-s`` drops the user site directory.  ``-I`` is
# deliberately not used here: it implies ``-E``, which would discard the
# PYTHONPATH that resolves the supervisor from the deployed source tree.
_INTERPRETER_PREFIX: Final[tuple[str, ...]] = ("python3", "-B", "-s", "-m", GUARDIAN_ENTRY)

# Structured argv whitelist.  Nothing outside this set may ever be rendered.
ALLOWED_ARGUMENTS: Final[tuple[str, ...]] = (
    "--route",
    "--attempt-id",
    "--request-path",
    "--output-root",
    "--permit-path",
    "--expected-request-sha256",
    "--expected-payload-manifest-sha256",
    "--expected-permit-sha256",
    "--expected-runner-source-sha256",
    "--expected-resources-sha256",
    "--gpu-index",
    "--cpu-affinity",
    "--timeout-seconds",
)

_RETIRED_TOKENS: Final[tuple[str, ...]] = (
    "QXHIEGFUWOLQIJ",
    "phase8b",
    "attempt-phase8b-qxh-v001",
    "phase8b-qxh-smoke-v001",
)

# A deployment is exactly two uploads and one promotion.  Any other count means
# the transaction that produced this outcome was not the registered one.
_EXPECTED_SSH_INVOCATIONS: Final = 3

# Substrings that would turn a launch record into a scientific claim.  Screened
# rather than enumerated so no spelling of a result field slips through.
_FORBIDDEN_RECEIPT_KEY_SUBSTRINGS: Final[tuple[str, ...]] = (
    "energy",
    "energies",
    "force",
    "gradient",
    "converg",
    "label",
    "kcal",
    "hartree",
    "succe",
    "scf",
)

# The acknowledgement window, not the computation window.
LAUNCH_ACKNOWLEDGEMENT_TIMEOUT_SECONDS: Final = 120.0
MAX_LAUNCH_ACKNOWLEDGEMENT_SECONDS: Final = 300.0

_MAX_STDOUT_BYTES: Final = 256 * 1024
_MAX_STDERR_BYTES: Final = 64 * 1024
_MAX_ANNOTATIONS: Final = 16


class Phase9BLaunchError(RuntimeError):
    """The launch could not prove its closed, two-route, one-shot scope."""


class Phase9BLaunchNotAuthorizedError(Phase9BLaunchError):
    """A real launch was attempted while the source gate is closed."""


class LaunchTimeout(Exception):
    """Raised by an injected runner when the remote state is unknowable."""


class LaunchState(Enum):
    """Overall transaction state.  Indeterminate is never silently upgraded."""

    NOT_LAUNCHED = "not_launched"
    LAUNCHED = "launched"
    PARTIALLY_LAUNCHED = "partially_launched"
    INDETERMINATE = "indeterminate"
    FAILED = "failed"


class RouteLaunchState(Enum):
    """One route's own state.  Every route always reports one."""

    NOT_ATTEMPTED = "not_attempted"
    LAUNCHED = "launched"
    INDETERMINATE = "indeterminate"
    FAILED = "failed"


class NextAction(Enum):
    """What a human may do next.  Retry, rollback, and backfill are absent."""

    PROCEED_TO_POSTFLIGHT = "proceed_to_postflight"
    STOP_AND_REPORT = "stop_and_report"


class CommandRunner(Protocol):
    """Injectable seam.  Production supplies SSH; tests supply a fake."""

    def __call__(self, command: Sequence[str], *, timeout: float) -> tuple[int, bytes, bytes]: ...


class Clock(Protocol):
    def __call__(self) -> str: ...


@dataclass(frozen=True, slots=True)
class RouteLaunchPlan:
    """One route's frozen launch identity.  Every field is consumed, not chosen."""

    route: str
    attempt_id: str
    final_root: str
    staging_root: str
    request_path: str
    permit_path: str
    output_root: str
    request_sha256: str
    payload_manifest_sha256: str
    permit_sha256: str
    runner_source_sha256: str
    resources_sha256: str
    registered_files: Mapping[str, tuple[str, int]]
    gpu_index: int
    cpu_affinity: str
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class RouteLaunchRecord:
    """One route's launch outcome.  Carries no scientific field."""

    route: str
    attempt_id: str
    final_root: str
    request_sha256: str
    payload_manifest_sha256: str
    permit_sha256: str
    argv_sha256: str
    redacted_argv: tuple[str, ...]
    ssh_returncode: int | None
    stdout_sha256: str | None
    stderr_sha256: str | None
    supervisor_identity: str | None
    supervisor_pid: int | None
    state: RouteLaunchState
    detail: str | None


@dataclass(frozen=True, slots=True)
class LaunchReceipt:
    """Immutable launch record.  It says what was started, never what was found."""

    schema_version: str
    phase: str
    candidate_inchikey: str
    request_id: str
    host_identity_sha256: str
    started_at: str
    deploy_outcome_sha256: str
    deploy_verification_sha256: str
    preflight_receipt_sha256: str
    placement_receipt_sha256: str
    resources_sha256: str
    runner_source_sha256: str
    routes: tuple[RouteLaunchRecord, ...]
    overall_state: LaunchState
    failure_reason: str | None
    scientific_result_present: bool = False


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _require_sha256(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise Phase9BLaunchError(f"{label} must be a lowercase SHA256")
    return value


def _reject_retired(value: str, *, label: str) -> str:
    for token in _RETIRED_TOKENS:
        if token in value:
            raise Phase9BLaunchError(f"{label} references a retired Phase 8B artifact: {token}")
    return value


def frozen_route_order() -> tuple[str, ...]:
    """Route order is frozen in the resource budget, never chosen at launch."""

    routes = PHASE9B_RESOURCES["routes"]
    order = tuple(str(route) for route in cast(Sequence[object], routes))
    if order != (ROUTE_DIRECT, ROUTE_ASSISTED):
        raise Phase9BLaunchError("the frozen route order drifted")
    return order


def validate_argument_value(value: object, *, label: str) -> str:
    """Structured field to argv token: refuse anything a shell could reinterpret."""

    if isinstance(value, bool) or not isinstance(value, str | int):
        raise Phase9BLaunchError(f"{label} must be a string or integer")
    text = str(value)
    if not text:
        raise Phase9BLaunchError(f"{label} is empty")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in text):
        raise Phase9BLaunchError(f"{label} contains a control character, newline, or NUL")
    for character in "*?[]{}$`\"'|&;<>()!~\\ \t":
        if character in text:
            raise Phase9BLaunchError(f"{label} contains a shell-unsafe character")
    if ".." in text:
        raise Phase9BLaunchError(f"{label} contains a path traversal segment")
    return text


def verified_files_for_route(
    verification: DeployVerificationReceipt | None, *, route: str
) -> Mapping[str, tuple[str, int]]:
    """Read one route's proved hash closure out of the deploy receipt.

    Byte sizes are no longer accepted as a caller-supplied mapping: they come from
    the receipt the deployment produced when it recomputed every file, and the
    receipt's own digest is rechecked so a partially edited table is caught.
    """

    if verification is None:
        raise Phase9BLaunchError("the deploy receipt carries no verified hash closure")
    if verification.schema_version != DEPLOY_VERIFICATION_SCHEMA_VERSION:
        raise Phase9BLaunchError("the deploy verification schema version drifted")
    if verification.receipt_sha256 != recomputed_verification_sha256(verification):
        raise Phase9BLaunchError("the deploy verification receipt digest does not match its body")
    members = verification.routes.get(route)
    if not members:
        raise Phase9BLaunchError(f"the deploy receipt verified no files for route: {route}")
    table: dict[str, tuple[str, int]] = {}
    for member, entry in members.items():
        if type(entry.bytes) is not int or entry.bytes <= 0:
            raise Phase9BLaunchError(f"verified byte size is invalid: {member}")
        table[member] = (_require_sha256(entry.sha256, label=f"verified {member}"), entry.bytes)
    return table


def build_route_launch_plan(
    *,
    permit: Phase9BPermit,
    payload: RoutePayload,
    deploy_plan: RoutePlan,
    deploy_outcome: DeploymentOutcome,
    preflight: PreflightResult,
) -> RouteLaunchPlan:
    """Fold four already-validated records into one launch identity, or refuse.

    Nothing here is rebuilt or defaulted: every value is taken from a frozen
    record and every overlap between records is compared.
    """

    route = permit.route
    if route not in ROUTE_ATTEMPT_IDS:
        raise Phase9BLaunchError(f"unknown Phase 9B route: {route!r}")
    if payload.request.route != route or deploy_plan.route != route:
        raise Phase9BLaunchError("permit, payload, and deploy plan disagree on the route")

    attempt = ROUTE_ATTEMPT_IDS[route]
    if permit.attempt_id != attempt or payload.request.attempt_id != attempt:
        raise Phase9BLaunchError(f"attempt identity does not match its route: {route}")
    if deploy_plan.attempt_id != attempt:
        raise Phase9BLaunchError(f"deploy plan carries another attempt identity: {route}")

    # The hashes the supervisor will be told to expect must already agree across
    # every record that states them.  A drift anywhere stops the launch.
    if permit.request_sha256 != payload.request.request_sha256:
        raise Phase9BLaunchError(f"request hash drifted between permit and payload: {route}")
    if permit.payload_manifest_sha256 != payload.manifest_sha256:
        raise Phase9BLaunchError(f"payload manifest hash drifted from the permit: {route}")

    final_root = _reject_retired(deploy_plan.final_root, label="final_root")
    staging_root = _reject_retired(deploy_plan.staging_root, label="staging_root")
    if final_root != permit.run_root.as_posix():
        raise Phase9BLaunchError(f"deploy final root is not the permit's run root: {route}")
    if staging_root == final_root:
        raise Phase9BLaunchError(f"staging and final roots collide: {route}")

    request_path = _reject_retired(permit.request_path.as_posix(), label="request_path")
    output_root = _reject_retired(permit.output_root.as_posix(), label="output_root")
    permit_path = _reject_retired(permit.ready_path.as_posix(), label="permit_path")
    if request_path != f"{final_root}/{REQUEST_RELATIVE}":
        raise Phase9BLaunchError(f"the permit's request path is outside the final root: {route}")
    for label, path in (("output_root", output_root), ("permit_path", permit_path)):
        if not path.startswith(f"{final_root}/"):
            raise Phase9BLaunchError(f"{label} is outside the final root: {route}")
    _reject_retired(attempt, label="attempt_id")

    verified = verified_files_for_route(deploy_outcome.verification, route=route)
    if set(verified) != set(deploy_plan.files):
        raise Phase9BLaunchError(f"verified file set differs from the registered set: {route}")
    registered: dict[str, tuple[str, int]] = {}
    for member, digest in sorted(deploy_plan.files.items()):
        proved, size = verified[member]
        if proved != digest:
            raise Phase9BLaunchError(f"the verified hash differs from the registered one: {member}")
        registered[member] = (_require_sha256(digest, label=f"registered {member}"), size)

    # The two files whose hashes the supervisor re-checks must be present in the
    # deployed set, and must be the exact bytes the permit names.
    if registered.get(REQUEST_RELATIVE, ("", 0))[0] != permit.request_sha256:
        raise Phase9BLaunchError(f"the deployed request is not the permitted request: {route}")
    if registered.get(PAYLOAD_MANIFEST_RELATIVE, ("", 0))[0] != permit.payload_manifest_sha256:
        raise Phase9BLaunchError(f"the deployed manifest is not the permitted manifest: {route}")
    # The permit is never part of the payload; a deployed permit would mean the
    # one-shot secret travelled with the bundle.
    for member in registered:
        if "permit" in member:
            raise Phase9BLaunchError(f"the deployed payload contains a permit file: {member}")

    if preflight.wrote_nothing is not True:
        raise Phase9BLaunchError("the preflight record does not prove it wrote nothing")
    if type(preflight.selected_gpu_index) is not int or preflight.selected_gpu_index < 0:
        raise Phase9BLaunchError("the preflight record carries no usable GPU index")
    if preflight.free_gpu_count < int(cast(int, PHASE9B_RESOURCES["worker_count"])):
        raise Phase9BLaunchError("the frozen device budget is no longer satisfied")

    return RouteLaunchPlan(
        route=route,
        attempt_id=attempt,
        final_root=final_root,
        staging_root=staging_root,
        request_path=request_path,
        permit_path=permit_path,
        output_root=output_root,
        request_sha256=_require_sha256(permit.request_sha256, label="request_sha256"),
        payload_manifest_sha256=_require_sha256(
            permit.payload_manifest_sha256, label="payload_manifest_sha256"
        ),
        permit_sha256=_require_sha256(permit.permit_sha256, label="permit_sha256"),
        runner_source_sha256=_require_sha256(
            permit.runner_source_sha256, label="runner_source_sha256"
        ),
        resources_sha256=phase9b_resources_sha256(),
        registered_files=registered,
        gpu_index=preflight.selected_gpu_index,
        cpu_affinity=str(PHASE9B_RESOURCES["cpu_affinity"]),
        timeout_seconds=int(cast(int, PHASE9B_RESOURCES["hard_wall_timeout_seconds"])),
    )


def validate_plan_pair(plans: Sequence[RouteLaunchPlan]) -> tuple[RouteLaunchPlan, ...]:
    """Both routes are one experiment identity.  Returns them in frozen order."""

    if len(plans) != 2 or {plan.route for plan in plans} != {ROUTE_DIRECT, ROUTE_ASSISTED}:
        raise Phase9BLaunchError("a launch transaction covers exactly both routes")
    if len({plan.attempt_id for plan in plans}) != 2:
        raise Phase9BLaunchError("the two routes must carry distinct attempt identities")
    if len({plan.final_root for plan in plans}) != 2:
        raise Phase9BLaunchError("the two routes must use distinct final roots")
    if len({plan.permit_sha256 for plan in plans}) != 2:
        raise Phase9BLaunchError("the two routes must hold distinct one-shot permits")
    # The two routes differ only by geometry and attempt identity, and both of
    # those are inside the request and the manifest, so those digests must differ.
    # A shared one would mean a route is running the other's inputs.
    if len({plan.request_sha256 for plan in plans}) != 2:
        raise Phase9BLaunchError("the two routes must carry distinct request identities")
    if len({plan.payload_manifest_sha256 for plan in plans}) != 2:
        raise Phase9BLaunchError("the two routes must carry distinct payload manifests")

    shared: dict[str, set[object]] = {
        "runner_source_sha256": {plan.runner_source_sha256 for plan in plans},
        "resources_sha256": {plan.resources_sha256 for plan in plans},
        "cpu_affinity": {plan.cpu_affinity for plan in plans},
        "timeout_seconds": {plan.timeout_seconds for plan in plans},
        "gpu_index": {plan.gpu_index for plan in plans},
    }
    for label, values in shared.items():
        if len(values) != 1:
            raise Phase9BLaunchError(f"the two routes disagree on a frozen field: {label}")

    by_route = {plan.route: plan for plan in plans}
    return tuple(by_route[route] for route in frozen_route_order())


def render_launch_argv(plan: RouteLaunchPlan) -> tuple[str, ...]:
    """Build the canonical argv from structured fields and the whitelist only."""

    fields: list[tuple[str, object]] = [
        ("--route", plan.route),
        ("--attempt-id", plan.attempt_id),
        ("--request-path", plan.request_path),
        ("--output-root", plan.output_root),
        ("--permit-path", plan.permit_path),
        ("--expected-request-sha256", plan.request_sha256),
        ("--expected-payload-manifest-sha256", plan.payload_manifest_sha256),
        ("--expected-permit-sha256", plan.permit_sha256),
        ("--expected-runner-source-sha256", plan.runner_source_sha256),
        ("--expected-resources-sha256", plan.resources_sha256),
        ("--gpu-index", plan.gpu_index),
        ("--cpu-affinity", plan.cpu_affinity),
        ("--timeout-seconds", plan.timeout_seconds),
    ]
    seen: set[str] = set()
    argv: list[str] = list(_INTERPRETER_PREFIX)
    for flag, value in fields:
        if flag not in ALLOWED_ARGUMENTS:
            raise Phase9BLaunchError(f"argument is not whitelisted: {flag}")
        if flag in seen:
            raise Phase9BLaunchError(f"argument repeated: {flag}")
        seen.add(flag)
        argv.append(flag)
        argv.append(validate_argument_value(value, label=flag))
    missing = sorted(set(ALLOWED_ARGUMENTS) - seen)
    if missing:
        raise Phase9BLaunchError(f"argv is missing a whitelisted argument: {missing[0]}")
    return tuple(argv)


def redact_argv(argv: Sequence[str]) -> tuple[str, ...]:
    """Keep the shape auditable without recording private absolute paths."""

    return tuple("<PATH>" if token.startswith("/") else token for token in argv)


def build_launch_command(
    *, ssh_alias: str, project_root: str, argv: Sequence[str]
) -> tuple[str, ...]:
    """One bounded SSH call.  No shell metacharacters, no free text, no extras."""

    if not ssh_alias:
        raise Phase9BLaunchError("launch needs an ssh alias")
    if not project_root.startswith("/") or " " in project_root or "\\" in project_root:
        raise Phase9BLaunchError("launch needs a safe absolute project root")
    _reject_retired(project_root, label="project_root")
    if tuple(argv[: len(_INTERPRETER_PREFIX)]) != _INTERPRETER_PREFIX:
        raise Phase9BLaunchError("only the guarded Phase 9B guardian entry may be started")
    if len(argv) != len(_INTERPRETER_PREFIX) + 2 * len(ALLOWED_ARGUMENTS):
        raise Phase9BLaunchError("the launch argv carries an unexpected argument count")
    remote = " && ".join(
        (
            f"cd {shlex.quote(project_root)}",
            "export PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 "
            "TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1",
            "exec " + " ".join(shlex.quote(token) for token in argv),
        )
    )
    return (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ConnectTimeout=15",
        ssh_alias,
        remote,
    )


def deploy_outcome_digest(outcome: DeploymentOutcome) -> str:
    """Canonical digest of the deployment record this launch is bound to."""

    return _sha256_bytes(
        _canonical_json_bytes(
            {
                "state": outcome.state.value,
                "promoted_routes": sorted(outcome.promoted_routes),
                "staging_roots": dict(sorted(outcome.staging_roots.items())),
                "final_roots": dict(sorted(outcome.final_roots.items())),
                "failure_reason": outcome.failure_reason,
                "failure_roots": sorted(outcome.failure_roots),
                "ssh_invocations": outcome.ssh_invocations,
            }
        )
    )


def preflight_digest(preflight: PreflightResult) -> str:
    """Canonical digest of the read-only preflight this launch is bound to."""

    return _sha256_bytes(
        _canonical_json_bytes(
            {
                "torch_version": preflight.torch_version,
                "ase_version": preflight.ase_version,
                "aimnet_version": preflight.aimnet_version,
                "pyscf_version": preflight.pyscf_version,
                "geometric_version": preflight.geometric_version,
                "dispersion_version": preflight.dispersion_version,
                "weight_sha256": preflight.weight_sha256,
                "selected_gpu_index": preflight.selected_gpu_index,
                "free_gpu_count": preflight.free_gpu_count,
                "memory_available_kib": preflight.memory_available_kib,
                "disk_available_bytes": preflight.disk_available_bytes,
                "wrote_nothing": preflight.wrote_nothing,
            }
        )
    )


def verify_deploy_outcome(
    outcome: DeploymentOutcome | None, *, plans: Sequence[RouteLaunchPlan]
) -> str:
    """Prove both routes promoted, intact, and identical to what will be launched."""

    if outcome is None:
        raise Phase9BLaunchError("no deploy receipt was supplied")
    if outcome.state is not DeployState.PROMOTED:
        raise Phase9BLaunchError(f"deploy is not PROMOTED: {outcome.state.value}")
    # A record that claims promotion while still naming a failure is contradictory.
    # ``deploy_both_routes`` reports a possibly partial promotion exactly this way,
    # so a partial deployment can never be read as launchable.
    if outcome.failure_reason is not None or outcome.failure_roots:
        raise Phase9BLaunchError("the deploy receipt claims promotion but names a failure")
    if sorted(outcome.promoted_routes) != sorted((ROUTE_DIRECT, ROUTE_ASSISTED)):
        raise Phase9BLaunchError("the deploy receipt does not promote exactly both routes")
    if outcome.ssh_invocations != _EXPECTED_SSH_INVOCATIONS:
        raise Phase9BLaunchError(
            f"the deploy receipt records {outcome.ssh_invocations} SSH calls, not two uploads "
            "and one promotion"
        )
    if set(outcome.final_roots) != {ROUTE_DIRECT, ROUTE_ASSISTED}:
        raise Phase9BLaunchError("the deploy receipt does not name both final roots")
    if set(outcome.staging_roots) != {ROUTE_DIRECT, ROUTE_ASSISTED}:
        raise Phase9BLaunchError("the deploy receipt does not name both staging roots")

    for plan in plans:
        if outcome.final_roots[plan.route] != plan.final_root:
            raise Phase9BLaunchError(f"the final root drifted for route: {plan.route}")
        if outcome.staging_roots[plan.route] != plan.staging_root:
            raise Phase9BLaunchError(f"the staging root drifted for route: {plan.route}")
        if not plan.registered_files:
            raise Phase9BLaunchError(f"no verified files for route: {plan.route}")
    return deploy_outcome_digest(outcome)


def verify_permit_placement(
    placement: PermitPlacementReceipt | None, *, plans: Sequence[RouteLaunchPlan]
) -> str:
    """One-shot: launch reads the permit-stage receipt, never a caller's booleans.

    An earlier revision took a ``ready_present``/``consumed_present`` pair straight
    from the caller, which made the strongest guarantee in the chain an act of
    trust.  Now the observation comes from the module that actually created the
    file and re-read it, and every field is cross-checked against the permit
    digest carried in the launch plan — a value derived from permit bytes, so it
    cannot be set to match an invented receipt.
    """

    if placement is None:
        raise Phase9BLaunchError("no permit placement receipt was supplied")
    if placement.schema_version != PLACEMENT_RECEIPT_SCHEMA_VERSION:
        raise Phase9BLaunchError("the permit placement schema version drifted")
    try:
        observed = observed_permits(placement)
    except Phase9BPermitStageError as exc:
        raise Phase9BLaunchError(f"permit placement is not launch-ready: {exc}") from exc
    if placement.request_id != REQUEST_ID:
        raise Phase9BLaunchError("the placement receipt names another request identity")

    for plan in plans:
        entry = observed.get(plan.route)
        if entry is None:
            raise Phase9BLaunchError(f"no placed permit was observed for route: {plan.route}")
        if entry.regular_file is not True:
            raise Phase9BLaunchError(f"the placed permit is not a regular file: {plan.route}")
        if entry.path != plan.permit_path:
            raise Phase9BLaunchError(f"the placed permit is at another path: {plan.route}")
        if entry.sha256 != plan.permit_sha256:
            raise Phase9BLaunchError(f"the placed permit is not the permitted bytes: {plan.route}")
        record = next(item for item in placement.routes if item.route == plan.route)
        if record.attempt_id != plan.attempt_id or record.final_root != plan.final_root:
            raise Phase9BLaunchError(f"the placement receipt names another attempt: {plan.route}")
        if record.request_sha256 != plan.request_sha256:
            raise Phase9BLaunchError(f"the placement receipt names another request: {plan.route}")
        if record.payload_manifest_sha256 != plan.payload_manifest_sha256:
            raise Phase9BLaunchError(f"the placement receipt names another manifest: {plan.route}")
    if placement.runner_source_sha256 != plans[0].runner_source_sha256:
        raise Phase9BLaunchError("the placement receipt was made against another source closure")
    return placement.receipt_sha256


def next_action_for(receipt: LaunchReceipt) -> NextAction:
    """Only two actions exist.  Retry, rollback, and backfill are not among them."""

    if receipt.overall_state is LaunchState.LAUNCHED:
        return NextAction.PROCEED_TO_POSTFLIGHT
    return NextAction.STOP_AND_REPORT


def _screen_key(key: str, *, where: str) -> str:
    lowered = key.lower()
    for token in _FORBIDDEN_RECEIPT_KEY_SUBSTRINGS:
        if token in lowered:
            raise Phase9BLaunchError(
                f"a launch receipt must not carry a result field: {where}.{key}"
            )
    return key


def receipt_payload(
    receipt: LaunchReceipt, *, annotations: Mapping[str, object] | None = None
) -> dict[str, object]:
    """Serialize for postflight, refusing any scientific field by name.

    ``annotations`` is the only caller-extensible part, and it is screened: the
    launch record states what was started, and postflight alone may state what
    was computed.
    """

    payload: dict[str, object] = {
        "schema_version": receipt.schema_version,
        "phase": receipt.phase,
        "candidate_inchikey": receipt.candidate_inchikey,
        "request_id": receipt.request_id,
        "host_identity_sha256": receipt.host_identity_sha256,
        "started_at": receipt.started_at,
        "deploy_outcome_sha256": receipt.deploy_outcome_sha256,
        "deploy_verification_sha256": receipt.deploy_verification_sha256,
        "preflight_receipt_sha256": receipt.preflight_receipt_sha256,
        "placement_receipt_sha256": receipt.placement_receipt_sha256,
        "resources_sha256": receipt.resources_sha256,
        "runner_source_sha256": receipt.runner_source_sha256,
        "overall_state": receipt.overall_state.value,
        "failure_reason": receipt.failure_reason,
        "scientific_result_present": False,
        "routes": [
            {
                "route": record.route,
                "attempt_id": record.attempt_id,
                "final_root": record.final_root,
                "request_sha256": record.request_sha256,
                "payload_manifest_sha256": record.payload_manifest_sha256,
                "permit_sha256": record.permit_sha256,
                "argv_sha256": record.argv_sha256,
                "redacted_argv": list(record.redacted_argv),
                "ssh_returncode": record.ssh_returncode,
                "stdout_sha256": record.stdout_sha256,
                "stderr_sha256": record.stderr_sha256,
                "supervisor_identity": record.supervisor_identity,
                "supervisor_pid": record.supervisor_pid,
                "state": record.state.value,
                "detail": record.detail,
            }
            for record in receipt.routes
        ],
    }
    if annotations:
        if len(annotations) > _MAX_ANNOTATIONS:
            raise Phase9BLaunchError("too many launch annotations")
        screened: dict[str, object] = {}
        for key, value in annotations.items():
            if not isinstance(key, str) or not key:
                raise Phase9BLaunchError("launch annotation keys must be non-empty strings")
            if key in payload:
                raise Phase9BLaunchError(f"a launch annotation may not shadow a field: {key}")
            screened[_screen_key(key, where="annotations")] = value
        payload["annotations"] = screened
    return payload


def _record(
    plan: RouteLaunchPlan,
    *,
    argv_sha256: str,
    redacted_argv: tuple[str, ...],
    state: RouteLaunchState,
    ssh_returncode: int | None = None,
    stdout_sha256: str | None = None,
    stderr_sha256: str | None = None,
    supervisor_identity: str | None = None,
    supervisor_pid: int | None = None,
    detail: str | None = None,
) -> RouteLaunchRecord:
    return RouteLaunchRecord(
        route=plan.route,
        attempt_id=plan.attempt_id,
        final_root=plan.final_root,
        request_sha256=plan.request_sha256,
        payload_manifest_sha256=plan.payload_manifest_sha256,
        permit_sha256=plan.permit_sha256,
        argv_sha256=argv_sha256,
        redacted_argv=redacted_argv,
        ssh_returncode=ssh_returncode,
        stdout_sha256=stdout_sha256,
        stderr_sha256=stderr_sha256,
        supervisor_identity=supervisor_identity,
        supervisor_pid=supervisor_pid,
        state=state,
        detail=detail,
    )


def _parse_supervisor_evidence(stdout: bytes, *, plan: RouteLaunchPlan) -> tuple[str, int | None]:
    """The guardian must prove what it consumed and what it started.

    A zero exit code is never enough. What counts is the guardian naming its own
    entry, the route and attempt it consumed the permit for, the state it reached,
    and the supervisor PID it observed -- all of which only the process that ran
    the transaction can supply.
    """

    try:
        decoded = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Phase9BLaunchError("launch evidence is not strict JSON") from exc
    if not isinstance(decoded, dict):
        raise Phase9BLaunchError("launch evidence must be one JSON object")
    evidence = cast(dict[str, object], decoded)
    if evidence.get("entry") != GUARDIAN_ENTRY:
        raise Phase9BLaunchError("the started process is not the guarded guardian entry")
    if evidence.get("supervisor_entry") != SUPERVISOR_ENTRY:
        raise Phase9BLaunchError("the guardian did not start the guarded supervisor entry")
    if evidence.get("attempt_id") != plan.attempt_id:
        raise Phase9BLaunchError("the guardian is bound to another attempt identity")
    if evidence.get("route") != plan.route:
        raise Phase9BLaunchError("the guardian is bound to another route")
    if evidence.get("permit_sha256") != plan.permit_sha256:
        raise Phase9BLaunchError("the guardian consumed another permit")
    if evidence.get("state") != GUARDIAN_LAUNCHED_STATE:
        raise Phase9BLaunchError(
            f"the guardian did not reach a launched state: {evidence.get('state')}"
        )
    for key in ("consumption_receipt_sha256", "launch_receipt_sha256"):
        digest = evidence.get(key)
        if not isinstance(digest, str) or len(digest) != 64:
            raise Phase9BLaunchError(f"the guardian named no usable {key}")
    identity = evidence.get("guardian_identity")
    if not isinstance(identity, str) or not identity:
        raise Phase9BLaunchError("launch evidence names no guardian identity")
    pid = evidence.get("supervisor_pid")
    if pid is None:
        raise Phase9BLaunchError("the guardian reported no supervisor process identity")
    if type(pid) is not int or pid <= 0:
        raise Phase9BLaunchError("launch evidence carries an invalid process identity")
    group = evidence.get("supervisor_process_group_id")
    if type(group) is not int or group != pid:
        raise Phase9BLaunchError("the supervisor is not its own process-group leader")
    return identity, pid


def launch_both_routes(
    *,
    ssh_alias: str,
    project_root: str,
    plans: Sequence[RouteLaunchPlan],
    deploy_outcome: DeploymentOutcome | None,
    preflight: PreflightResult,
    placement: PermitPlacementReceipt | None,
    already_launched: Sequence[str] = (),
    run_command: CommandRunner | None = None,
    clock: Clock | None = None,
    timeout_seconds: float = LAUNCH_ACKNOWLEDGEMENT_TIMEOUT_SECONDS,
) -> LaunchReceipt:
    """Start both routes as one experiment identity, or start neither.

    There is no retry, no rollback, and no backfill.  A failure after the first
    route started is reported as ``partially_launched``; an unknowable remote
    state is reported as ``indeterminate``.  Both are terminal.
    """

    if run_command is None and EXECUTION_AUTHORIZED is not True:
        raise Phase9BLaunchNotAuthorizedError("a real Phase 9B launch is not authorized")
    if run_command is None:  # pragma: no cover - unreachable while the gate is closed
        raise Phase9BLaunchNotAuthorizedError("no production launch runner is wired")
    # This bound covers guardian verification, permit consumption, supervisor
    # spawn, and the acknowledgement round trip -- never the computation, which
    # runs for up to the frozen wall-time in its own session after the guardian
    # has exited.  A bound anywhere near the wall-time would mean the SSH channel
    # was holding the computation open, which is the design this replaces.
    if not 0.0 < timeout_seconds <= MAX_LAUNCH_ACKNOWLEDGEMENT_SECONDS:
        raise ValueError(
            "the launch acknowledgement timeout must be in "
            f"(0, {MAX_LAUNCH_ACKNOWLEDGEMENT_SECONDS}]"
        )
    if timeout_seconds >= float(cast(int, PHASE9B_RESOURCES["hard_wall_timeout_seconds"])):
        raise ValueError("the launch timeout must not span the computation wall-time")

    stamp = clock() if clock is not None else "1970-01-01T00:00:00Z"
    host_hash = _sha256_bytes(ssh_alias.encode("utf-8"))
    ordered = validate_plan_pair(plans)

    def receipt(
        *,
        records: Sequence[RouteLaunchRecord],
        state: LaunchState,
        reason: str | None,
        deploy_hash: str = "",
        verification_hash: str = "",
        preflight_hash: str = "",
        placement_hash: str = "",
    ) -> LaunchReceipt:
        done = {record.route: record for record in records}
        # Every route always reports its own identity and its own actual state,
        # including the one that was never attempted.
        full = tuple(
            done.get(
                plan.route,
                _record(
                    plan,
                    argv_sha256="",
                    redacted_argv=(),
                    state=RouteLaunchState.NOT_ATTEMPTED,
                    detail="not attempted",
                ),
            )
            for plan in ordered
        )
        return LaunchReceipt(
            schema_version=LAUNCH_RECEIPT_SCHEMA_VERSION,
            phase="9B",
            candidate_inchikey=CANDIDATE_INCHIKEY,
            request_id=REQUEST_ID,
            host_identity_sha256=host_hash,
            started_at=stamp,
            deploy_outcome_sha256=deploy_hash,
            deploy_verification_sha256=verification_hash,
            preflight_receipt_sha256=preflight_hash,
            placement_receipt_sha256=placement_hash,
            resources_sha256=ordered[0].resources_sha256,
            runner_source_sha256=ordered[0].runner_source_sha256,
            routes=full,
            overall_state=state,
            failure_reason=reason,
        )

    for route in already_launched:
        if route in {plan.route for plan in ordered}:
            return receipt(
                records=(),
                state=LaunchState.NOT_LAUNCHED,
                reason=f"route already launched under this permit: {route}",
            )

    try:
        deploy_hash = verify_deploy_outcome(deploy_outcome, plans=ordered)
        preflight_hash = preflight_digest(preflight)
        placement_hash = verify_permit_placement(placement, plans=ordered)
        verification = deploy_outcome.verification if deploy_outcome is not None else None
        verification_hash = "" if verification is None else verification.receipt_sha256
        # Both commands are rendered before either is issued, so a rejected argv
        # stops the transaction rather than leaving one route already started.
        prepared = [
            (
                plan,
                argv,
                build_launch_command(ssh_alias=ssh_alias, project_root=project_root, argv=argv),
            )
            for plan, argv in ((plan, render_launch_argv(plan)) for plan in ordered)
        ]
    except Phase9BLaunchError as exc:
        return receipt(records=(), state=LaunchState.NOT_LAUNCHED, reason=str(exc))

    records: list[RouteLaunchRecord] = []
    failure: str | None = None
    stopped = False

    for plan, argv, command in prepared:
        argv_hash = _sha256_bytes(_canonical_json_bytes(list(argv)))
        redacted = redact_argv(argv)
        try:
            code, stdout, stderr = run_command(command, timeout=timeout_seconds)
        except LaunchTimeout as exc:
            # The remote may or may not have started.  Never guess, never retry.
            records.append(
                _record(
                    plan,
                    argv_sha256=argv_hash,
                    redacted_argv=redacted,
                    state=RouteLaunchState.INDETERMINATE,
                    detail=f"remote state unknown after timeout: {exc}",
                )
            )
            failure = f"launch state indeterminate for {plan.route}: {exc}"
            stopped = True
            break
        except Exception as exc:  # any transport failure is a closed failure
            records.append(
                _record(
                    plan,
                    argv_sha256=argv_hash,
                    redacted_argv=redacted,
                    state=RouteLaunchState.FAILED,
                    detail=f"transport failed: {exc}",
                )
            )
            failure = f"transport failed for {plan.route}: {exc}"
            stopped = True
            break

        if len(stdout) > _MAX_STDOUT_BYTES or len(stderr) > _MAX_STDERR_BYTES:
            records.append(
                _record(
                    plan,
                    argv_sha256=argv_hash,
                    redacted_argv=redacted,
                    ssh_returncode=code,
                    state=RouteLaunchState.INDETERMINATE,
                    detail="launch output exceeded its bound; remote state unread",
                )
            )
            failure = f"launch output exceeded its bound for {plan.route}"
            stopped = True
            break

        stdout_hash = _sha256_bytes(stdout)
        stderr_hash = _sha256_bytes(stderr)
        if code != 0:
            records.append(
                _record(
                    plan,
                    argv_sha256=argv_hash,
                    redacted_argv=redacted,
                    ssh_returncode=code,
                    stdout_sha256=stdout_hash,
                    stderr_sha256=stderr_hash,
                    state=RouteLaunchState.FAILED,
                    detail=f"launch exited {code}",
                )
            )
            failure = f"launch exited {code} for {plan.route}"
            stopped = True
            break

        try:
            identity, pid = _parse_supervisor_evidence(stdout, plan=plan)
        except Phase9BLaunchError as exc:
            # The call returned zero but did not prove what it started, so the
            # remote state is unknown rather than known-failed.
            records.append(
                _record(
                    plan,
                    argv_sha256=argv_hash,
                    redacted_argv=redacted,
                    ssh_returncode=code,
                    stdout_sha256=stdout_hash,
                    stderr_sha256=stderr_hash,
                    state=RouteLaunchState.INDETERMINATE,
                    detail=str(exc),
                )
            )
            failure = f"unverified supervisor identity for {plan.route}: {exc}"
            stopped = True
            break

        records.append(
            _record(
                plan,
                argv_sha256=argv_hash,
                redacted_argv=redacted,
                ssh_returncode=code,
                stdout_sha256=stdout_hash,
                stderr_sha256=stderr_hash,
                supervisor_identity=identity,
                supervisor_pid=pid,
                state=RouteLaunchState.LAUNCHED,
            )
        )

    launched = [record for record in records if record.state is RouteLaunchState.LAUNCHED]
    indeterminate = any(record.state is RouteLaunchState.INDETERMINATE for record in records)

    if indeterminate:
        overall = LaunchState.INDETERMINATE
    elif stopped and launched:
        overall = LaunchState.PARTIALLY_LAUNCHED
    elif stopped:
        overall = LaunchState.FAILED
    elif len(launched) == len(ordered):
        overall = LaunchState.LAUNCHED
    else:  # pragma: no cover - structural guard; the loop leaves no third path
        overall = LaunchState.FAILED
        failure = failure or "not every route produced a launch record"

    return receipt(
        records=records,
        state=overall,
        reason=failure,
        deploy_hash=deploy_hash,
        verification_hash=verification_hash,
        preflight_hash=preflight_hash,
        placement_hash=placement_hash,
    )


def external_launch_entries_v3() -> tuple[str, str]:
    """Only externally reachable v3 launch targets; stages are intentionally absent."""

    return (DIRECT_GUARDIAN_ENTRY_V3, CAMPAIGN_GUARDIAN_ENTRY_V3)


def validate_external_launch_entry_v3(entry: str) -> str:
    if entry not in external_launch_entries_v3():
        raise Phase9BLaunchError("v3 external launch may target only a route guardian")
    if entry.endswith("stage_a1") or entry.endswith("stage_a2"):
        raise Phase9BLaunchError("internal stage entrypoints are not externally launchable")
    return entry


__all__ = [
    "ALLOWED_ARGUMENTS",
    "CAMPAIGN_GUARDIAN_ENTRY_V3",
    "CANDIDATE_INCHIKEY",
    "DIRECT_GUARDIAN_ENTRY_V3",
    "EXECUTION_AUTHORIZED",
    "GUARDIAN_ENTRY",
    "LAUNCH_ACKNOWLEDGEMENT_TIMEOUT_SECONDS",
    "LAUNCH_RECEIPT_SCHEMA_VERSION",
    "MAX_LAUNCH_ACKNOWLEDGEMENT_SECONDS",
    "SUPERVISOR_ENTRY",
    "Clock",
    "CommandRunner",
    "LaunchReceipt",
    "LaunchState",
    "LaunchTimeout",
    "NextAction",
    "Phase9BLaunchError",
    "Phase9BLaunchNotAuthorizedError",
    "RouteLaunchPlan",
    "RouteLaunchRecord",
    "RouteLaunchState",
    "build_launch_command",
    "build_route_launch_plan",
    "deploy_outcome_digest",
    "external_launch_entries_v3",
    "frozen_route_order",
    "launch_both_routes",
    "next_action_for",
    "preflight_digest",
    "receipt_payload",
    "redact_argv",
    "render_launch_argv",
    "validate_argument_value",
    "validate_external_launch_entry_v3",
    "validate_plan_pair",
    "verified_files_for_route",
    "verify_deploy_outcome",
    "verify_permit_placement",
]
