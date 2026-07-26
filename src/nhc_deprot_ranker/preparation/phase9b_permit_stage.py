"""Phase 9B one-shot permit placement.

The step between a promoted payload and a launch.  The payload manifest
deliberately excludes the permit — a manifest that covered its own authorization
could not be built before the permit exists, and the permit binds the manifest
hash — so the permit travels on its own, after promotion and before any
supervisor starts.

Control plane, not runner source: this module is outside
``_RUNNER_SOURCE_RELATIVE_PATHS``, so it cannot change ``runner_source_sha256``.

It consumes frozen permit bytes and rebuilds nothing.  It creates each route's
ready permit exclusively, never follows a symlink, re-reads what it wrote and
compares type, byte size, and full SHA256, and returns an immutable receipt.

It never overwrites, never deletes, never rolls back, and never restores a
consumed permit.  If either route cannot be placed, the pair is not launch-ready.
"""

from __future__ import annotations

import hashlib
import json
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final, Protocol, cast

from nhc_deprot_ranker.preparation.phase9b_deploy import (
    DeploymentOutcome,
    DeployState,
)
from nhc_deprot_ranker.quantum.phase9b_permit import (
    REQUEST_ID,
    ROUTE_ASSISTED,
    ROUTE_ATTEMPT_IDS,
    ROUTE_DIRECT,
    Phase9BPermit,
)
from nhc_deprot_ranker.quantum.phase9b_resources import phase9b_resources_sha256

# Real permit placement writes to the server.  Separate authorization.
EXECUTION_AUTHORIZED: Final[bool] = False

PLACEMENT_RECEIPT_SCHEMA_VERSION: Final = "phase9b.permit_placement_receipt.v1"
PLACEMENT_EVIDENCE_SCHEMA_VERSION: Final = "phase9b.permit_placement_evidence.v1"

CANDIDATE_INCHIKEY: Final = "LBNPGYISTSLAHY-UHFFFAOYSA-N"

_READY_MODE: Final = 0o400
_ROOT_MODE: Final = 0o700
_MAX_PERMIT_BYTES: Final = 64 * 1024
_MAX_STDOUT_BYTES: Final = 64 * 1024
_MAX_STDERR_BYTES: Final = 16 * 1024

_RETIRED_TOKENS: Final[tuple[str, ...]] = (
    "QXHIEGFUWOLQIJ",
    "phase8b",
)

_EXPECTED_DEPLOY_SSH_INVOCATIONS: Final = 3


class Phase9BPermitStageError(RuntimeError):
    """Permit placement could not prove its closed, both-routes, one-shot scope."""


class Phase9BPermitStageNotAuthorizedError(Phase9BPermitStageError):
    """A real placement was attempted while the source gate is closed."""


class PlacementTimeout(Exception):
    """Raised by an injected runner when the remote state is unknowable."""


class PlacementState(Enum):
    """Overall state.  Indeterminate is never silently upgraded."""

    NOT_PLACED = "not_placed"
    PLACED = "placed"
    PARTIALLY_PLACED = "partially_placed"
    INDETERMINATE = "indeterminate"
    FAILED = "failed"


class RoutePlacementState(Enum):
    """One route's own state.  Every route always reports one."""

    NOT_ATTEMPTED = "not_attempted"
    PLACED = "placed"
    INDETERMINATE = "indeterminate"
    FAILED = "failed"


class CommandRunner(Protocol):
    """Injectable seam.  Production supplies SSH; tests supply a fake."""

    def __call__(
        self, command: Sequence[str], *, stdin: bytes, timeout: float
    ) -> tuple[int, bytes, bytes]: ...


class Clock(Protocol):
    def __call__(self) -> str: ...


@dataclass(frozen=True, slots=True)
class RoutePermitPlan:
    """One route's frozen permit and the exact path it belongs at."""

    route: str
    attempt_id: str
    final_root: str
    ready_path: str
    consumed_path: str
    permit_bytes: bytes
    permit_sha256: str
    request_sha256: str
    payload_manifest_sha256: str
    runner_source_sha256: str
    resources_sha256: str


@dataclass(frozen=True, slots=True)
class ObservedPermitFile:
    """What a re-read of the placed permit actually found."""

    path: str
    bytes: int
    sha256: str
    regular_file: bool


@dataclass(frozen=True, slots=True)
class RoutePermitPlacement:
    """One route's placement outcome."""

    route: str
    attempt_id: str
    final_root: str
    permit_sha256: str
    request_sha256: str
    payload_manifest_sha256: str
    observed: ObservedPermitFile | None
    state: RoutePlacementState
    detail: str | None


@dataclass(frozen=True, slots=True)
class PermitPlacementReceipt:
    """Immutable placement record.

    ``receipt_sha256`` covers every other field, so a partially edited receipt is
    detectable.  It is not an authentication of the caller — that would need a
    signing key this project does not have.  What makes the record hard to forge
    usefully is that a consumer cross-checks ``permit_sha256`` against the parsed
    permit bytes, which cannot be changed to match an invented digest.
    """

    schema_version: str
    phase: str
    candidate_inchikey: str
    request_id: str
    host_identity_sha256: str
    placed_at: str
    deploy_outcome_sha256: str
    runner_source_sha256: str
    resources_sha256: str
    routes: tuple[RoutePermitPlacement, ...]
    overall_state: PlacementState
    failure_reason: str | None
    receipt_sha256: str


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
        raise Phase9BPermitStageError(f"{label} must be a lowercase SHA256")
    return value


def _reject_retired(value: str, *, label: str) -> str:
    for token in _RETIRED_TOKENS:
        if token in value:
            raise Phase9BPermitStageError(f"{label} references a retired Phase 8B artifact")
    return value


def _safe_absolute(value: str, *, label: str) -> str:
    if not value.startswith("/") or "\\" in value or "\x00" in value:
        raise Phase9BPermitStageError(f"{label} is not a safe absolute path")
    for character in "*?[]{}$`\"'|&;<>()!~\n\r\t ":
        if character in value:
            raise Phase9BPermitStageError(f"{label} contains a shell-unsafe character")
    if ".." in value or "/./" in value or value.endswith("/"):
        raise Phase9BPermitStageError(f"{label} is not a canonical absolute path")
    return _reject_retired(value, label=label)


def build_route_permit_plan(
    *, permit: Phase9BPermit, payload_manifest_sha256: str
) -> RoutePermitPlan:
    """Fix one route's placement identity from its already-validated permit.

    The permit bytes are the ones ``parse_phase9b_permit`` accepted; they are
    never re-rendered here, so placement cannot quietly change what is authorized.
    """

    route = permit.route
    if route not in ROUTE_ATTEMPT_IDS:
        raise Phase9BPermitStageError(f"unknown Phase 9B route: {route!r}")
    if permit.attempt_id != ROUTE_ATTEMPT_IDS[route]:
        raise Phase9BPermitStageError(f"attempt identity does not match its route: {route}")
    if permit.payload_manifest_sha256 != payload_manifest_sha256:
        raise Phase9BPermitStageError(f"payload manifest digest drifted from the permit: {route}")
    if not permit.raw_bytes or len(permit.raw_bytes) > _MAX_PERMIT_BYTES:
        raise Phase9BPermitStageError(f"permit byte size is invalid: {route}")
    if _sha256_bytes(permit.raw_bytes) != permit.permit_sha256:
        raise Phase9BPermitStageError(f"permit bytes do not hash to their own digest: {route}")

    final_root = _safe_absolute(permit.run_root.as_posix(), label="final_root")
    ready_path = _safe_absolute(permit.ready_path.as_posix(), label="ready_path")
    consumed_path = _safe_absolute(permit.consumed_path.as_posix(), label="consumed_path")
    if ready_path == consumed_path:
        raise Phase9BPermitStageError(f"ready and consumed permit paths collide: {route}")
    for label, path in (("ready_path", ready_path), ("consumed_path", consumed_path)):
        if not path.startswith(f"{final_root}/"):
            raise Phase9BPermitStageError(f"{label} is outside the final root: {route}")
    _reject_retired(permit.attempt_id, label="attempt_id")

    return RoutePermitPlan(
        route=route,
        attempt_id=permit.attempt_id,
        final_root=final_root,
        ready_path=ready_path,
        consumed_path=consumed_path,
        permit_bytes=permit.raw_bytes,
        permit_sha256=_require_sha256(permit.permit_sha256, label="permit_sha256"),
        request_sha256=_require_sha256(permit.request_sha256, label="request_sha256"),
        payload_manifest_sha256=_require_sha256(
            permit.payload_manifest_sha256, label="payload_manifest_sha256"
        ),
        runner_source_sha256=_require_sha256(
            permit.runner_source_sha256, label="runner_source_sha256"
        ),
        resources_sha256=phase9b_resources_sha256(),
    )


def validate_plan_pair(plans: Sequence[RoutePermitPlan]) -> tuple[RoutePermitPlan, ...]:
    """Both routes are one experiment identity, with distinct permits and roots."""

    if len(plans) != 2 or {plan.route for plan in plans} != {ROUTE_DIRECT, ROUTE_ASSISTED}:
        raise Phase9BPermitStageError("a placement transaction covers exactly both routes")
    for label in ("attempt_id", "final_root", "ready_path", "permit_sha256", "request_sha256"):
        if len({getattr(plan, label) for plan in plans}) != 2:
            raise Phase9BPermitStageError(f"the two routes must carry distinct {label} values")
    if len({plan.runner_source_sha256 for plan in plans}) != 1:
        raise Phase9BPermitStageError("the two routes disagree on the runner source closure")
    if len({plan.resources_sha256 for plan in plans}) != 1:
        raise Phase9BPermitStageError("the two routes disagree on the resource budget")
    by_route = {plan.route: plan for plan in plans}
    return (by_route[ROUTE_DIRECT], by_route[ROUTE_ASSISTED])


def verify_promoted_deployment(
    outcome: DeploymentOutcome | None, *, plans: Sequence[RoutePermitPlan]
) -> str:
    """A permit is placed only into a final root that deploy actually promoted."""

    if outcome is None:
        raise Phase9BPermitStageError("no deploy receipt was supplied")
    if outcome.state is not DeployState.PROMOTED:
        raise Phase9BPermitStageError(f"deploy is not PROMOTED: {outcome.state.value}")
    if outcome.failure_reason is not None or outcome.failure_roots:
        raise Phase9BPermitStageError("the deploy receipt claims promotion but names a failure")
    if sorted(outcome.promoted_routes) != sorted((ROUTE_DIRECT, ROUTE_ASSISTED)):
        raise Phase9BPermitStageError("the deploy receipt does not promote exactly both routes")
    if outcome.ssh_invocations != _EXPECTED_DEPLOY_SSH_INVOCATIONS:
        raise Phase9BPermitStageError("the deploy receipt does not record the registered transport")
    for plan in plans:
        if outcome.final_roots.get(plan.route) != plan.final_root:
            raise Phase9BPermitStageError(f"the final root drifted for route: {plan.route}")
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


# Standard library only.  Exclusive create, no symlink follow, no overwrite, no
# delete, no rename, no shell.  It refuses if either the ready or the consumed
# permit already exists, then re-reads what it wrote and prints canonical
# evidence.  There is no code path here that removes or restores a permit.
REMOTE_PLACER_SOURCE: Final = r"""import hashlib, json, os, sys
hdr_len = int.from_bytes(sys.stdin.buffer.read(8), "big")
header = json.loads(sys.stdin.buffer.read(hdr_len).decode("utf-8"))
body = sys.stdin.buffer.read(int(header["bytes"]))
if len(body) != int(header["bytes"]) or sys.stdin.buffer.read(1):
    raise SystemExit("permit stream length mismatch")
final_root = header["final_root"]
ready = header["ready_path"]
consumed = header["consumed_path"]
if not os.path.isdir(final_root) or os.path.islink(final_root):
    raise SystemExit("final root is not a promoted directory")
if os.path.lexists(consumed):
    raise SystemExit("a consumed permit already exists; it is never restored")
if os.path.lexists(ready):
    raise SystemExit("a ready permit already exists; overwrite is prohibited")
parent = os.path.dirname(ready)
if not os.path.isdir(parent):
    os.makedirs(parent, mode=int(header["root_mode"], 8), exist_ok=False)
elif os.path.islink(parent):
    raise SystemExit("permit directory is a symlink")
fd = os.open(ready, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
             int(header["file_mode"], 8))
try:
    os.write(fd, body)
    os.fsync(fd)
finally:
    os.close(fd)
st = os.lstat(ready)
digest = hashlib.sha256()
rfd = os.open(ready, os.O_RDONLY | os.O_NOFOLLOW)
try:
    while True:
        chunk = os.read(rfd, 1 << 20)
        if not chunk:
            break
        digest.update(chunk)
finally:
    os.close(rfd)
print(json.dumps({"schema_version": "phase9b.permit_placement_evidence.v1",
                  "route": header["route"], "attempt_id": header["attempt_id"],
                  "path": ready, "bytes": st.st_size, "sha256": digest.hexdigest(),
                  "regular": bool(st.st_mode & 0o100000) and not os.path.islink(ready),
                  "consumed_present": os.path.lexists(consumed)}, sort_keys=True))
"""


def build_placement_stream(plan: RoutePermitPlan) -> bytes:
    """Header plus the exact permit bytes, in one deterministic frame."""

    header = _canonical_json_bytes(
        {
            "route": plan.route,
            "attempt_id": plan.attempt_id,
            "final_root": plan.final_root,
            "ready_path": plan.ready_path,
            "consumed_path": plan.consumed_path,
            "bytes": len(plan.permit_bytes),
            "sha256": plan.permit_sha256,
            "file_mode": f"{_READY_MODE:o}",
            "root_mode": f"{_ROOT_MODE:o}",
        }
    )
    return len(header).to_bytes(8, "big") + header + plan.permit_bytes


def build_placement_command(*, ssh_alias: str, plan: RoutePermitPlan) -> tuple[str, ...]:
    """One bounded SSH call carrying one route's permit on stdin."""

    if not ssh_alias:
        raise Phase9BPermitStageError("permit placement needs an ssh alias")
    _safe_absolute(plan.ready_path, label="ready_path")
    return (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ConnectTimeout=15",
        ssh_alias,
        "exec python3 -I -B -c " + shlex.quote(REMOTE_PLACER_SOURCE),
    )


def parse_placement_evidence(raw: bytes, *, plan: RoutePermitPlan) -> ObservedPermitFile:
    """Accept the re-read observation only if it matches the frozen permit exactly."""

    if not raw or len(raw) > _MAX_STDOUT_BYTES:
        raise Phase9BPermitStageError("placement evidence byte size is invalid")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        seen: dict[str, object] = {}
        for key, value in pairs:
            if key in seen:
                raise Phase9BPermitStageError(f"placement evidence has a duplicate key: {key}")
            seen[key] = value
        return seen

    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except Phase9BPermitStageError:
        raise
    except (UnicodeDecodeError, ValueError) as exc:
        raise Phase9BPermitStageError("placement evidence is not strict JSON") from exc
    if not isinstance(decoded, dict):
        raise Phase9BPermitStageError("placement evidence must be one JSON object")
    evidence = cast(dict[str, object], decoded)

    if evidence.get("schema_version") != PLACEMENT_EVIDENCE_SCHEMA_VERSION:
        raise Phase9BPermitStageError("placement evidence schema version drifted")
    if evidence.get("route") != plan.route or evidence.get("attempt_id") != plan.attempt_id:
        raise Phase9BPermitStageError("placement evidence names another route or attempt")
    if evidence.get("path") != plan.ready_path:
        raise Phase9BPermitStageError("placement evidence names another path")
    if evidence.get("regular") is not True:
        raise Phase9BPermitStageError("the placed permit is not a regular file")
    if evidence.get("consumed_present") is not False:
        raise Phase9BPermitStageError("a consumed permit is present after placement")
    observed_bytes = evidence.get("bytes")
    if type(observed_bytes) is not int or observed_bytes != len(plan.permit_bytes):
        raise Phase9BPermitStageError("the placed permit byte size does not match")
    digest = _require_sha256(evidence.get("sha256"), label="placement sha256")
    if digest != plan.permit_sha256:
        raise Phase9BPermitStageError("the placed permit does not hash to the permitted digest")
    return ObservedPermitFile(
        path=plan.ready_path, bytes=observed_bytes, sha256=digest, regular_file=True
    )


def _receipt_body(
    *,
    host_identity_sha256: str,
    placed_at: str,
    deploy_outcome_sha256: str,
    runner_source_sha256: str,
    resources_sha256: str,
    routes: Sequence[RoutePermitPlacement],
    overall_state: PlacementState,
    failure_reason: str | None,
) -> dict[str, object]:
    return {
        "schema_version": PLACEMENT_RECEIPT_SCHEMA_VERSION,
        "phase": "9B",
        "candidate_inchikey": CANDIDATE_INCHIKEY,
        "request_id": REQUEST_ID,
        "host_identity_sha256": host_identity_sha256,
        "placed_at": placed_at,
        "deploy_outcome_sha256": deploy_outcome_sha256,
        "runner_source_sha256": runner_source_sha256,
        "resources_sha256": resources_sha256,
        "overall_state": overall_state.value,
        "failure_reason": failure_reason,
        "routes": [
            {
                "route": record.route,
                "attempt_id": record.attempt_id,
                "final_root": record.final_root,
                "permit_sha256": record.permit_sha256,
                "request_sha256": record.request_sha256,
                "payload_manifest_sha256": record.payload_manifest_sha256,
                "state": record.state.value,
                "detail": record.detail,
                "observed": None
                if record.observed is None
                else {
                    "path": record.observed.path,
                    "bytes": record.observed.bytes,
                    "sha256": record.observed.sha256,
                    "regular_file": record.observed.regular_file,
                },
            }
            for record in routes
        ],
    }


def receipt_payload(receipt: PermitPlacementReceipt) -> dict[str, object]:
    """Canonical serialization, including the receipt's own digest."""

    body = _receipt_body(
        host_identity_sha256=receipt.host_identity_sha256,
        placed_at=receipt.placed_at,
        deploy_outcome_sha256=receipt.deploy_outcome_sha256,
        runner_source_sha256=receipt.runner_source_sha256,
        resources_sha256=receipt.resources_sha256,
        routes=receipt.routes,
        overall_state=receipt.overall_state,
        failure_reason=receipt.failure_reason,
    )
    body["receipt_sha256"] = receipt.receipt_sha256
    return body


def recomputed_receipt_sha256(receipt: PermitPlacementReceipt) -> str:
    """Recompute the digest over every field except the digest itself."""

    return _sha256_bytes(
        _canonical_json_bytes(
            _receipt_body(
                host_identity_sha256=receipt.host_identity_sha256,
                placed_at=receipt.placed_at,
                deploy_outcome_sha256=receipt.deploy_outcome_sha256,
                runner_source_sha256=receipt.runner_source_sha256,
                resources_sha256=receipt.resources_sha256,
                routes=receipt.routes,
                overall_state=receipt.overall_state,
                failure_reason=receipt.failure_reason,
            )
        )
    )


def place_both_permits(
    *,
    ssh_alias: str,
    plans: Sequence[RoutePermitPlan],
    deploy_outcome: DeploymentOutcome | None,
    run_command: CommandRunner | None = None,
    clock: Clock | None = None,
    timeout_seconds: float = 120.0,
) -> PermitPlacementReceipt:
    """Place both routes' ready permits, or leave the pair not launch-ready.

    There is no retry, no rollback, and no backfill.  A failure after the first
    permit landed is reported as ``partially_placed``; an unknowable remote state
    is reported as ``indeterminate``.  Neither is launch-ready.
    """

    if run_command is None and EXECUTION_AUTHORIZED is not True:
        raise Phase9BPermitStageNotAuthorizedError("real permit placement is not authorized")
    if run_command is None:  # pragma: no cover - unreachable while the gate is closed
        raise Phase9BPermitStageNotAuthorizedError("no production placement runner is wired")
    if not 0.0 < timeout_seconds <= 600.0:
        raise ValueError("placement timeout must be in (0, 600]")

    stamp = clock() if clock is not None else "1970-01-01T00:00:00Z"
    host_hash = _sha256_bytes(ssh_alias.encode("utf-8"))
    ordered = validate_plan_pair(plans)

    def receipt(
        *,
        records: Sequence[RoutePermitPlacement],
        state: PlacementState,
        reason: str | None,
        deploy_hash: str = "",
    ) -> PermitPlacementReceipt:
        done = {record.route: record for record in records}
        full = tuple(
            done.get(
                plan.route,
                RoutePermitPlacement(
                    route=plan.route,
                    attempt_id=plan.attempt_id,
                    final_root=plan.final_root,
                    permit_sha256=plan.permit_sha256,
                    request_sha256=plan.request_sha256,
                    payload_manifest_sha256=plan.payload_manifest_sha256,
                    observed=None,
                    state=RoutePlacementState.NOT_ATTEMPTED,
                    detail="not attempted",
                ),
            )
            for plan in ordered
        )
        digest = _sha256_bytes(
            _canonical_json_bytes(
                _receipt_body(
                    host_identity_sha256=host_hash,
                    placed_at=stamp,
                    deploy_outcome_sha256=deploy_hash,
                    runner_source_sha256=ordered[0].runner_source_sha256,
                    resources_sha256=ordered[0].resources_sha256,
                    routes=full,
                    overall_state=state,
                    failure_reason=reason,
                )
            )
        )
        return PermitPlacementReceipt(
            schema_version=PLACEMENT_RECEIPT_SCHEMA_VERSION,
            phase="9B",
            candidate_inchikey=CANDIDATE_INCHIKEY,
            request_id=REQUEST_ID,
            host_identity_sha256=host_hash,
            placed_at=stamp,
            deploy_outcome_sha256=deploy_hash,
            runner_source_sha256=ordered[0].runner_source_sha256,
            resources_sha256=ordered[0].resources_sha256,
            routes=full,
            overall_state=state,
            failure_reason=reason,
            receipt_sha256=digest,
        )

    try:
        deploy_hash = verify_promoted_deployment(deploy_outcome, plans=ordered)
        prepared = [
            (
                plan,
                build_placement_command(ssh_alias=ssh_alias, plan=plan),
                build_placement_stream(plan),
            )
            for plan in ordered
        ]
    except Phase9BPermitStageError as exc:
        return receipt(records=(), state=PlacementState.NOT_PLACED, reason=str(exc))

    records: list[RoutePermitPlacement] = []
    failure: str | None = None
    stopped = False

    def record_for(
        plan: RoutePermitPlan,
        *,
        state: RoutePlacementState,
        observed: ObservedPermitFile | None = None,
        detail: str | None = None,
    ) -> RoutePermitPlacement:
        return RoutePermitPlacement(
            route=plan.route,
            attempt_id=plan.attempt_id,
            final_root=plan.final_root,
            permit_sha256=plan.permit_sha256,
            request_sha256=plan.request_sha256,
            payload_manifest_sha256=plan.payload_manifest_sha256,
            observed=observed,
            state=state,
            detail=detail,
        )

    for plan, command, stream in prepared:
        try:
            code, stdout, stderr = run_command(command, stdin=stream, timeout=timeout_seconds)
        except PlacementTimeout as exc:
            # The permit may or may not exist remotely.  Never guess, never retry,
            # and above all never delete to "clean up".
            records.append(
                record_for(
                    plan,
                    state=RoutePlacementState.INDETERMINATE,
                    detail=f"remote state unknown after timeout: {exc}",
                )
            )
            failure = f"placement state indeterminate for {plan.route}: {exc}"
            stopped = True
            break
        except Exception as exc:  # any transport failure is a closed failure
            records.append(
                record_for(
                    plan,
                    state=RoutePlacementState.INDETERMINATE,
                    detail=f"transport failed with the stream in flight: {exc}",
                )
            )
            failure = f"transport failed for {plan.route}: {exc}"
            stopped = True
            break

        if len(stdout) > _MAX_STDOUT_BYTES or len(stderr) > _MAX_STDERR_BYTES:
            records.append(
                record_for(
                    plan,
                    state=RoutePlacementState.INDETERMINATE,
                    detail="placement output exceeded its bound; remote state unread",
                )
            )
            failure = f"placement output exceeded its bound for {plan.route}"
            stopped = True
            break
        if code != 0 or stderr:
            detail = stderr.decode("utf-8", errors="replace").strip()[:200]
            records.append(
                record_for(
                    plan,
                    state=RoutePlacementState.FAILED,
                    detail=f"placement exited {code}: {detail}",
                )
            )
            failure = f"placement exited {code} for {plan.route}"
            stopped = True
            break

        try:
            observed = parse_placement_evidence(stdout, plan=plan)
        except Phase9BPermitStageError as exc:
            # It exited zero but did not prove what landed, so the state is
            # unknown rather than known-failed.
            records.append(
                record_for(plan, state=RoutePlacementState.INDETERMINATE, detail=str(exc))
            )
            failure = f"unverified placement for {plan.route}: {exc}"
            stopped = True
            break

        records.append(record_for(plan, state=RoutePlacementState.PLACED, observed=observed))

    placed = [record for record in records if record.state is RoutePlacementState.PLACED]
    indeterminate = any(record.state is RoutePlacementState.INDETERMINATE for record in records)

    if indeterminate:
        overall = PlacementState.INDETERMINATE
    elif stopped and placed:
        overall = PlacementState.PARTIALLY_PLACED
    elif stopped:
        overall = PlacementState.FAILED
    elif len(placed) == len(ordered):
        overall = PlacementState.PLACED
    else:  # pragma: no cover - structural guard; the loop leaves no third path
        overall = PlacementState.FAILED
        failure = failure or "not every route produced a placement record"

    return receipt(records=records, state=overall, reason=failure, deploy_hash=deploy_hash)


def is_launch_ready(receipt: PermitPlacementReceipt) -> bool:
    """Only a fully placed, digest-consistent pair is launch-ready."""

    return (
        receipt.overall_state is PlacementState.PLACED
        and receipt.failure_reason is None
        and len(receipt.routes) == 2
        and all(record.state is RoutePlacementState.PLACED for record in receipt.routes)
        and all(record.observed is not None for record in receipt.routes)
        and receipt.receipt_sha256 == recomputed_receipt_sha256(receipt)
    )


def observed_permits(receipt: PermitPlacementReceipt) -> Mapping[str, ObservedPermitFile]:
    """The observation table a launch consumes instead of a caller's booleans."""

    if not is_launch_ready(receipt):
        raise Phase9BPermitStageError("the placement receipt is not launch-ready")
    table: dict[str, ObservedPermitFile] = {}
    for record in receipt.routes:
        if record.observed is None:  # pragma: no cover - excluded by is_launch_ready
            raise Phase9BPermitStageError(f"no observation for route: {record.route}")
        table[record.route] = record.observed
    return table


__all__ = [
    "CANDIDATE_INCHIKEY",
    "EXECUTION_AUTHORIZED",
    "PLACEMENT_EVIDENCE_SCHEMA_VERSION",
    "PLACEMENT_RECEIPT_SCHEMA_VERSION",
    "REMOTE_PLACER_SOURCE",
    "Clock",
    "CommandRunner",
    "ObservedPermitFile",
    "PermitPlacementReceipt",
    "Phase9BPermitStageError",
    "Phase9BPermitStageNotAuthorizedError",
    "PlacementState",
    "PlacementTimeout",
    "RoutePermitPlacement",
    "RoutePermitPlan",
    "RoutePlacementState",
    "build_placement_command",
    "build_placement_stream",
    "build_route_permit_plan",
    "is_launch_ready",
    "observed_permits",
    "parse_placement_evidence",
    "place_both_permits",
    "receipt_payload",
    "recomputed_receipt_sha256",
    "validate_plan_pair",
    "verify_promoted_deployment",
]
