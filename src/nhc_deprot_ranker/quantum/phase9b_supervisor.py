"""Phase 9B supervisor entry for the paired direct / assisted smoke.

``run_phase8b_supervisor`` is bound to the frozen Phase 8B request, attempt,
permit, root, and electron count, so it cannot run any other candidate.  This
module provides the equivalent entry driven by a
:class:`~nhc_deprot_ranker.quantum.phase9b_authority.CandidateProfile`.

Two attempts run under one request: Route D, direct PySCF from the frozen input,
and Route A, PySCF residual optimization from an AIMNet2-preoptimized structure.
Both share identical PySCF settings and resources; a difference between them
invalidates the comparison and is rejected here rather than discovered later.

Supervision itself is **not** reimplemented.  This module delegates to the
existing validated supervised-execution path so there is exactly one copy of the
process, deadline, and reaping logic.  A second copy would be free to drift from
the one that carries the safety proofs.

This file **is** listed in the runner source closure, so every edit here changes
``runner_source_sha256`` and supersedes any request, payload manifest, or permit
built against an earlier closure.

The CLI at the bottom is the formal entry that ``preparation/phase9b_launch.py``
renders argv for.  It accepts exactly the thirteen frozen flags and nothing else,
verifies every identity they assert, prints the minimal supervisor identity the
launch record needs, and then delegates.  It parses, verifies, and delegates;
it does not supervise, time out, reap, act as guardian, run a worker, or touch
chemistry.

No chemistry import, no compute, no label.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final, Protocol, cast

from nhc_deprot_ranker.quantum.phase9b_authority import (
    PHASE9B_CANDIDATE,
    CandidateProfile,
    Phase9BAuthorityError,
    validate_endpoint_pair,
    validate_profile_self_consistency,
)
from nhc_deprot_ranker.quantum.phase9b_permit import (
    OUTPUT_RELATIVE,
    REQUEST_RELATIVE,
    ROUTE_ATTEMPT_IDS,
    Phase9BPermit,
    Phase9BPermitError,
    parse_phase9b_permit,
)
from nhc_deprot_ranker.quantum.phase9b_resources import (
    AIMNET2_STAGE_BUDGET,
    PHASE9B_RESOURCES,
    phase9b_resources_sha256,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nhc_deprot_ranker.quantum.two_endpoint import TwoEndpointRequest

# Real Phase 9B execution is a separate authorization.  Source-level gate.
EXECUTION_AUTHORIZED: Final[bool] = False

REQUEST_ID: Final = "phase9b-lbnp-paired-smoke-v001"
ROUTE_D_ATTEMPT_ID: Final = "attempt-phase9b-lbnp-direct-v001"
ROUTE_A_ATTEMPT_ID: Final = "attempt-phase9b-lbnp-assisted-v001"
REMOTE_ROOT_RELATIVE: Final = "data/runs/nhc_deprot_ranker_phase9b_paired_smoke_v001"

ROUTE_DIRECT: Final = "direct"
ROUTE_ASSISTED: Final = "assisted"
_ROUTE_ATTEMPTS: Final[dict[str, str]] = {
    ROUTE_DIRECT: ROUTE_D_ATTEMPT_ID,
    ROUTE_ASSISTED: ROUTE_A_ATTEMPT_ID,
}

# Identities of the permanently retired Phase 8B chain.  Never reusable.
_RETIRED_IDENTITIES: Final[frozenset[str]] = frozenset(
    {
        "QXHIEGFUWOLQIJ-UHFFFAOYSA-N",
        "phase8b-qxh-smoke-v001",
        "attempt-phase8b-qxh-v001",
        "data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001",
    }
)


class Phase9BSupervisorError(RuntimeError):
    """The Phase 9B supervisor transaction could not prove its closed scope."""


class Phase9BNotAuthorizedError(Phase9BSupervisorError):
    """Execution was attempted while a gate is closed."""


@dataclass(frozen=True, slots=True)
class Phase9BAuthority:
    """Hash-closed authority for one Phase 9B route."""

    route: str
    request_sha256: str
    runner_source_sha256: str
    protocol_sha256: str
    electron_count: int
    profile: CandidateProfile


class _WorkerLaunchLike(Protocol):
    @property
    def absolute_deadline_ns(self) -> int: ...


class _SupervisedExecutor(Protocol):
    def __call__(
        self,
        request: TwoEndpointRequest,
        output_root: Path,
        *,
        attempt_id: str,
        worker_launch: _WorkerLaunchLike,
    ) -> object: ...


def validate_route_configurations_match(
    direct: Phase9BAuthority, assisted: Phase9BAuthority
) -> None:
    """Both routes must share every setting except the preoptimization stage.

    A configuration difference makes any measured speedup uninterpretable, so it
    is rejected before execution rather than explained afterward.
    """

    if direct.route != ROUTE_DIRECT or assisted.route != ROUTE_ASSISTED:
        raise Phase9BSupervisorError("route labels are not one direct and one assisted")
    if direct.protocol_sha256 != assisted.protocol_sha256:
        raise Phase9BSupervisorError("route PySCF protocols differ")
    if direct.runner_source_sha256 != assisted.runner_source_sha256:
        raise Phase9BSupervisorError("route runner source closures differ")
    if direct.electron_count != assisted.electron_count:
        raise Phase9BSupervisorError("route electron counts differ")
    if direct.profile.inchikey != assisted.profile.inchikey:
        raise Phase9BSupervisorError("routes reference different candidates")
    if direct.request_sha256 == assisted.request_sha256:
        raise Phase9BSupervisorError("routes must be distinct attempts, not one request reused")


def _reject_retired_identity(*values: object) -> None:
    for value in values:
        if not isinstance(value, str):
            continue
        if value in _RETIRED_IDENTITIES or any(token in value for token in _RETIRED_TOKENS):
            raise Phase9BNotAuthorizedError(
                "the retired Phase 8B authority chain may never be reused"
            )


def run_phase9b_supervisor(
    request: TwoEndpointRequest,
    output_root: Path,
    *,
    authority: Phase9BAuthority,
    worker_launch: _WorkerLaunchLike,
    profile: CandidateProfile = PHASE9B_CANDIDATE,
    execute: _SupervisedExecutor | None = None,
) -> object:
    """Validate one Phase 9B route, then delegate to supervised execution."""

    from nhc_deprot_ranker.quantum import two_endpoint as runner
    from nhc_deprot_ranker.quantum.two_endpoint import (
        run_phase9b_supervised_execution as runner_execute,
    )

    if EXECUTION_AUTHORIZED is not True:
        raise Phase9BNotAuthorizedError("Phase 9B execution is not authorized")
    if runner.EXECUTION_AUTHORIZED is not True:
        raise Phase9BNotAuthorizedError("the runner source execution gate is closed")

    if not isinstance(authority, Phase9BAuthority):
        raise Phase9BNotAuthorizedError("a Phase 9B authority is required")
    if authority.route not in _ROUTE_ATTEMPTS:
        raise Phase9BSupervisorError(f"unknown Phase 9B route: {authority.route}")

    _reject_retired_identity(
        getattr(request, "inchikey", None),
        getattr(request, "request_id", None),
        authority.profile.inchikey,
    )

    validate_profile_self_consistency(profile)
    if authority.profile != profile:
        raise Phase9BSupervisorError("authority profile disagrees with the supplied profile")
    if authority.electron_count != profile.electron_count:
        raise Phase9BSupervisorError("authority electron count disagrees with the profile")

    if authority.request_sha256 != request.request_sha256:
        raise Phase9BNotAuthorizedError("Phase 9B authority disagrees with the request")
    if authority.runner_source_sha256 != request.runner_source_sha256:
        raise Phase9BNotAuthorizedError("Phase 9B authority runner source disagrees")
    if getattr(request, "inchikey", None) != profile.inchikey:
        raise Phase9BSupervisorError("request candidate disagrees with the profile")

    try:
        validate_endpoint_pair(request.cation, request.neutral, profile=profile)
    except Phase9BAuthorityError as exc:
        raise Phase9BSupervisorError(f"endpoint validation failed: {exc}") from exc

    if os.path.lexists(output_root):
        raise Phase9BNotAuthorizedError("Phase 9B output already exists; resume is prohibited")

    # The production path is the one guarded supervised-execution adapter.  It is
    # resolved here rather than defaulted in the signature so the import stays
    # lazy and the injected seam remains available to tests.
    executor = execute if execute is not None else cast("_SupervisedExecutor", runner_execute)

    return executor(
        request,
        output_root,
        attempt_id=_ROUTE_ATTEMPTS[authority.route],
        worker_launch=worker_launch,
    )


# --- formal CLI entry -------------------------------------------------------
#
# The launch control plane renders exactly these flags, in this order, with one
# value each.  The set is closed: an unknown, repeated, missing, abbreviated, or
# positional argument is a hard stop.
CLI_ENTRY: Final = "nhc_deprot_ranker.quantum.phase9b_supervisor"

SUPERVISOR_IDENTITY_SCHEMA_VERSION: Final = "phase9b.supervisor_identity.v1"

_STRING_FLAGS: Final[tuple[str, ...]] = (
    "--route",
    "--attempt-id",
    "--request-path",
    "--output-root",
    "--permit-path",
    "--cpu-affinity",
)
_SHA256_FLAGS: Final[tuple[str, ...]] = (
    "--expected-request-sha256",
    "--expected-payload-manifest-sha256",
    "--expected-permit-sha256",
    "--expected-runner-source-sha256",
    "--expected-resources-sha256",
)
_INTEGER_FLAGS: Final[tuple[str, ...]] = ("--gpu-index", "--timeout-seconds")
REQUIRED_FLAGS: Final[tuple[str, ...]] = (*_STRING_FLAGS, *_SHA256_FLAGS, *_INTEGER_FLAGS)

_ABSOLUTE_PATH_FLAGS: Final[frozenset[str]] = frozenset(
    {"--request-path", "--output-root", "--permit-path"}
)
PAYLOAD_MANIFEST_RELATIVE: Final = "payload_manifest.json"
_MAX_MANIFEST_BYTES: Final = 64 * 1024

# Recorded by the Phase 9A-R read-only inspection: 8x Tesla V100-SXM2-32GB.
INSPECTED_DEVICE_COUNT: Final = 8

# Substrings of the permanently retired chain.  Exact-identity rejection is not
# enough for paths, where a retired root appears as one component among many.
_RETIRED_TOKENS: Final[tuple[str, ...]] = (
    "QXHIEGFUWOLQIJ",
    "phase8b",
    "phase8b_dft_smoke",
)


class Phase9BArgumentError(Phase9BSupervisorError):
    """The argv did not match the closed thirteen-flag contract."""


@dataclass(frozen=True, slots=True)
class Phase9BLaunchArguments:
    """The thirteen frozen flags, parsed and type-checked but not yet verified."""

    route: str
    attempt_id: str
    request_path: str
    output_root: str
    permit_path: str
    cpu_affinity: str
    expected_request_sha256: str
    expected_payload_manifest_sha256: str
    expected_permit_sha256: str
    expected_runner_source_sha256: str
    expected_resources_sha256: str
    gpu_index: int
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class VerifiedPhase9BLaunch:
    """Every asserted identity, proved against the bytes actually on disk."""

    arguments: Phase9BLaunchArguments
    request: TwoEndpointRequest
    permit: Phase9BPermit
    authority: Phase9BAuthority
    payload_manifest_sha256: str


class _WorkerLaunchFactory(Protocol):
    def __call__(self, *, verified: VerifiedPhase9BLaunch) -> _WorkerLaunchLike: ...


class _TextStream(Protocol):
    def write(self, text: str, /) -> object: ...


def _fail(message: str) -> Phase9BArgumentError:
    return Phase9BArgumentError(message)


def _clean_token(value: str, *, flag: str) -> str:
    if not value:
        raise _fail(f"{flag} has an empty value")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise _fail(f"{flag} contains a control character, newline, or NUL")
    return value


def parse_supervisor_argv(argv: Sequence[str]) -> Phase9BLaunchArguments:
    """Parse the closed flag set.

    Hand-written rather than ``argparse``: argparse accepts unambiguous flag
    abbreviations, so ``--rou direct`` would be honoured.  A launch contract that
    names thirteen exact flags must reject anything that is not one of them.
    """

    values: dict[str, str] = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if not token.startswith("--"):
            raise _fail(f"positional arguments are not accepted: {token!r}")
        if "=" in token:
            raise _fail(f"inline flag values are not accepted: {token!r}")
        if token not in REQUIRED_FLAGS:
            raise _fail(f"argument is not whitelisted: {token}")
        if token in values:
            raise _fail(f"argument repeated: {token}")
        if index + 1 >= len(argv):
            raise _fail(f"argument has no value: {token}")
        values[token] = _clean_token(argv[index + 1], flag=token)
        index += 2

    missing = [flag for flag in REQUIRED_FLAGS if flag not in values]
    if missing:
        raise _fail(f"argument is missing: {missing[0]}")

    for flag in _SHA256_FLAGS:
        candidate = values[flag]
        if len(candidate) != 64 or any(ch not in "0123456789abcdef" for ch in candidate):
            raise _fail(f"{flag} is not a lowercase SHA256")
    integers: dict[str, int] = {}
    for flag in _INTEGER_FLAGS:
        raw = values[flag]
        if not raw.isdigit():
            raise _fail(f"{flag} is not a non-negative decimal integer")
        integers[flag] = int(raw)
    for flag in _ABSOLUTE_PATH_FLAGS:
        candidate = values[flag]
        path = PurePosixPath(candidate)
        if not path.is_absolute() or path.as_posix() != candidate:
            raise _fail(f"{flag} is not a normalized absolute path")
        if any(part in {".", ".."} for part in path.parts):
            raise _fail(f"{flag} contains a dot or traversal segment")

    return Phase9BLaunchArguments(
        route=values["--route"],
        attempt_id=values["--attempt-id"],
        request_path=values["--request-path"],
        output_root=values["--output-root"],
        permit_path=values["--permit-path"],
        cpu_affinity=values["--cpu-affinity"],
        expected_request_sha256=values["--expected-request-sha256"],
        expected_payload_manifest_sha256=values["--expected-payload-manifest-sha256"],
        expected_permit_sha256=values["--expected-permit-sha256"],
        expected_runner_source_sha256=values["--expected-runner-source-sha256"],
        expected_resources_sha256=values["--expected-resources-sha256"],
        gpu_index=integers["--gpu-index"],
        timeout_seconds=integers["--timeout-seconds"],
    )


def _read_manifest(run_root: Path) -> tuple[str, dict[str, object]]:
    path = run_root / PAYLOAD_MANIFEST_RELATIVE
    if path.is_symlink() or not path.is_file():
        raise Phase9BSupervisorError("payload manifest is missing or is not a regular file")
    raw = path.read_bytes()
    if not raw or len(raw) > _MAX_MANIFEST_BYTES:
        raise Phase9BSupervisorError("payload manifest byte size is invalid")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Phase9BSupervisorError("payload manifest is not strict JSON") from exc
    if not isinstance(decoded, dict):
        raise Phase9BSupervisorError("payload manifest must be one JSON object")
    return hashlib.sha256(raw).hexdigest(), cast(dict[str, object], decoded)


def verify_launch_arguments(
    arguments: Phase9BLaunchArguments, *, profile: CandidateProfile = PHASE9B_CANDIDATE
) -> VerifiedPhase9BLaunch:
    """Prove every asserted identity against the bytes on disk, or refuse.

    Nothing asserted on the command line is trusted: each digest is recomputed
    from the file it names, and the route, attempt, roots, device, affinity, and
    wall-time are compared against the permit and the frozen resource budget.
    """

    from nhc_deprot_ranker.quantum.two_endpoint import (
        LOCKED_PROTOCOL_SHA256,
        current_runner_source_sha256,
        load_two_endpoint_request,
    )

    _reject_retired_identity(
        arguments.route, arguments.attempt_id, arguments.request_path, arguments.permit_path
    )
    if arguments.route not in _ROUTE_ATTEMPTS:
        raise Phase9BSupervisorError(f"unknown Phase 9B route: {arguments.route!r}")
    if arguments.attempt_id != ROUTE_ATTEMPT_IDS[arguments.route]:
        raise Phase9BSupervisorError("attempt identity does not match its route")

    validate_profile_self_consistency(profile)

    # The permit is the root of the chain: it names the roots every other path
    # must sit inside, so it is loaded and validated first.
    permit_path = Path(arguments.permit_path)
    if permit_path.is_symlink() or not permit_path.is_file():
        raise Phase9BSupervisorError("ready permit is missing or is not a regular file")
    try:
        permit = parse_phase9b_permit(permit_path.read_bytes(), profile=profile)
    except Phase9BPermitError as exc:
        raise Phase9BSupervisorError(f"ready permit failed validation: {exc}") from exc
    if permit.permit_sha256 != arguments.expected_permit_sha256:
        raise Phase9BNotAuthorizedError("permit bytes do not match the expected permit digest")
    if permit.route != arguments.route or permit.attempt_id != arguments.attempt_id:
        raise Phase9BNotAuthorizedError("the permit authorizes another route or attempt")
    if permit.ready_path != permit_path:
        raise Phase9BNotAuthorizedError("the ready permit is not at its own registered path")

    run_root = permit.run_root
    if permit.request_path != run_root / REQUEST_RELATIVE:
        raise Phase9BNotAuthorizedError("the permit request path is outside its run root")
    if arguments.request_path != permit.request_path.as_posix():
        raise Phase9BNotAuthorizedError("the request path is not the permitted request path")
    if arguments.output_root != permit.output_root.as_posix():
        raise Phase9BNotAuthorizedError("the output root is not the permitted output root")
    if permit.output_root != run_root / OUTPUT_RELATIVE:
        raise Phase9BNotAuthorizedError("the permit output root is outside its run root")
    if permit.consumed_path == permit.ready_path:
        raise Phase9BNotAuthorizedError("the permit ready and consumed paths collide")

    manifest_sha256, manifest = _read_manifest(run_root)
    if manifest_sha256 != arguments.expected_payload_manifest_sha256:
        raise Phase9BNotAuthorizedError("payload manifest digest drifted from the expected value")
    if manifest_sha256 != permit.payload_manifest_sha256:
        raise Phase9BNotAuthorizedError("payload manifest digest drifted from the permit")
    if (
        manifest.get("route") != arguments.route
        or manifest.get("attempt_id") != arguments.attempt_id
        or manifest.get("request_id") != REQUEST_ID
        or manifest.get("inchikey") != profile.inchikey
        or manifest.get("electron_count") != profile.electron_count
        or manifest.get("excludes_permit") is not True
        or manifest.get("label_produced") is not False
    ):
        raise Phase9BNotAuthorizedError("payload manifest identity disagrees with the argv")
    if manifest.get("resources_sha256") != arguments.expected_resources_sha256:
        raise Phase9BNotAuthorizedError("payload manifest resource digest drifted")

    request = load_two_endpoint_request(permit.request_path)
    if request.request_sha256 != arguments.expected_request_sha256:
        raise Phase9BNotAuthorizedError("request bytes do not match the expected request digest")
    if request.request_sha256 != permit.request_sha256:
        raise Phase9BNotAuthorizedError("request digest drifted from the permit")
    if getattr(request, "request_id", None) != REQUEST_ID:
        raise Phase9BNotAuthorizedError("the request carries another request identity")
    if request.protocol_sha256 != LOCKED_PROTOCOL_SHA256:
        raise Phase9BNotAuthorizedError("the request protocol is not the locked protocol")

    # Source identity is recomputed from this process's own files, not read from
    # the request: a request cannot vouch for the code that is about to run.
    actual_source = current_runner_source_sha256()
    if actual_source != arguments.expected_runner_source_sha256:
        raise Phase9BNotAuthorizedError("runner source closure drifted from the expected digest")
    if not actual_source == request.runner_source_sha256 == permit.runner_source_sha256:
        raise Phase9BNotAuthorizedError("runner source digest drifted from the request or permit")
    actual_resources = phase9b_resources_sha256()
    if actual_resources != arguments.expected_resources_sha256:
        raise Phase9BNotAuthorizedError("resource budget drifted from the expected digest")

    frozen_timeout = int(cast(int, PHASE9B_RESOURCES["hard_wall_timeout_seconds"]))
    if arguments.timeout_seconds != frozen_timeout:
        raise Phase9BNotAuthorizedError("the wall-time argument is not the frozen wall-time")
    if request.timeout_seconds != frozen_timeout:
        raise Phase9BNotAuthorizedError("the request wall-time is not the frozen wall-time")
    if arguments.cpu_affinity != str(PHASE9B_RESOURCES["cpu_affinity"]):
        raise Phase9BNotAuthorizedError("the CPU affinity argument is not the frozen affinity")
    # Whether a device is *free* is the read-only preflight's finding; re-deciding
    # it here would be a second selection path.  This bounds the index against the
    # node inspected in Phase 9A-R and confirms the budget still claims one card.
    if not 0 <= arguments.gpu_index < INSPECTED_DEVICE_COUNT:
        raise Phase9BNotAuthorizedError("the GPU index is outside the inspected device range")
    if int(cast(int, AIMNET2_STAGE_BUDGET["gpu_count"])) != 1:
        raise Phase9BNotAuthorizedError("the frozen device budget is not one card")

    try:
        validate_endpoint_pair(request.cation, request.neutral, profile=profile)
    except Phase9BAuthorityError as exc:
        raise Phase9BSupervisorError(f"endpoint validation failed: {exc}") from exc

    authority = Phase9BAuthority(
        route=arguments.route,
        request_sha256=request.request_sha256,
        runner_source_sha256=actual_source,
        protocol_sha256=request.protocol_sha256,
        electron_count=profile.electron_count,
        profile=profile,
    )
    return VerifiedPhase9BLaunch(
        arguments=arguments,
        request=request,
        permit=permit,
        authority=authority,
        payload_manifest_sha256=manifest_sha256,
    )


def supervisor_identity_payload(verified: VerifiedPhase9BLaunch, *, pid: int) -> dict[str, object]:
    """The minimal record the launch control plane reads back from stdout.

    Deliberately minimal and hash-closed: it proves *which* guarded entry started
    under *which* attempt, and nothing about what the computation found.
    """

    arguments = verified.arguments
    identity = hashlib.sha256(
        json.dumps(
            {
                "entry": CLI_ENTRY,
                "route": arguments.route,
                "attempt_id": arguments.attempt_id,
                "request_sha256": arguments.expected_request_sha256,
                "payload_manifest_sha256": verified.payload_manifest_sha256,
                "permit_sha256": arguments.expected_permit_sha256,
                "runner_source_sha256": arguments.expected_runner_source_sha256,
                "resources_sha256": arguments.expected_resources_sha256,
                "pid": pid,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": SUPERVISOR_IDENTITY_SCHEMA_VERSION,
        "supervisor_identity": identity,
        "entry": CLI_ENTRY,
        "route": arguments.route,
        "attempt_id": arguments.attempt_id,
        "pid": pid,
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    worker_launch_factory: _WorkerLaunchFactory | None = None,
    execute: _SupervisedExecutor | None = None,
    stdout: _TextStream | None = None,
    profile: CandidateProfile = PHASE9B_CANDIDATE,
) -> int:
    """Parse, verify, announce, delegate.  Nothing else happens here.

    The worker handshake is **not** constructed here.  Building it is the
    guardian's transaction, and reimplementing it would create a second copy of
    the registration and release logic.  It arrives through an injected factory;
    with no factory wired, this refuses rather than improvising one.
    """

    arguments = parse_supervisor_argv(list(sys.argv[1:] if argv is None else argv))
    verified = verify_launch_arguments(arguments, profile=profile)

    stream: _TextStream = sys.stdout if stdout is None else stdout
    payload = supervisor_identity_payload(verified, pid=os.getpid())
    stream.write(json.dumps(payload, sort_keys=True) + "\n")
    flush = getattr(stream, "flush", None)
    if callable(flush):
        flush()

    if worker_launch_factory is None:
        raise Phase9BNotAuthorizedError(
            "no guarded worker handshake is wired; the Phase 9B guardian transaction must supply it"
        )
    result = run_phase9b_supervisor(
        verified.request,
        Path(arguments.output_root),
        authority=verified.authority,
        worker_launch=worker_launch_factory(verified=verified),
        profile=profile,
        execute=execute,
    )
    return 0 if result is not None else 1


__all__ = [
    "CLI_ENTRY",
    "EXECUTION_AUTHORIZED",
    "PAYLOAD_MANIFEST_RELATIVE",
    "REMOTE_ROOT_RELATIVE",
    "REQUEST_ID",
    "REQUIRED_FLAGS",
    "ROUTE_ASSISTED",
    "ROUTE_A_ATTEMPT_ID",
    "ROUTE_DIRECT",
    "ROUTE_D_ATTEMPT_ID",
    "SUPERVISOR_IDENTITY_SCHEMA_VERSION",
    "Phase9BArgumentError",
    "Phase9BAuthority",
    "Phase9BLaunchArguments",
    "Phase9BNotAuthorizedError",
    "Phase9BSupervisorError",
    "VerifiedPhase9BLaunch",
    "main",
    "parse_supervisor_argv",
    "run_phase9b_supervisor",
    "supervisor_identity_payload",
    "validate_route_configurations_match",
    "verify_launch_arguments",
]


if __name__ == "__main__":  # pragma: no cover - exercised through the frozen argv
    raise SystemExit(main())
