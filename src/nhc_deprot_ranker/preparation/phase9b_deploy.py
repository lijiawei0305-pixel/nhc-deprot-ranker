"""Phase 9B directed two-route deployment control.

This module is **control plane**, not runner source.  It is deliberately outside
``_RUNNER_SOURCE_RELATIVE_PATHS``, exactly as ``phase8b_deploy`` is, so adding or
editing it cannot change ``runner_source_sha256`` and therefore cannot invalidate
a frozen request, payload manifest, or permit.  It reads the manifest; it never
rebuilds one.

It performs no SSH itself.  The command runner is injected, so every test drives a
fake and nothing here reaches a network.  It opens no gate, starts no worker,
supervisor, AIMNet2, or PySCF, loads no weight, selects no GPU, consumes no
permit, and produces no scientific result or label.

Deployment is one transaction over both routes:

    verify local payload      paths, regular-file type, byte size, full SHA256,
                              and the exact registered set in both directions
    verify roots absent       both final roots and both staging roots
    stage                     one directed stream per route into a fresh
                              attempt-unique staging root, exclusive-create only
    verify remote             per-file relative path, type, size, SHA256, total
                              count, and no extra files
    promote                   only after BOTH routes verify

Nothing is promoted until both routes have verified.  A route that fails leaves
its staging root in place and named in the failure record: the module never
re-uploads to the same path, never overwrites, and never auto-retries.
"""

from __future__ import annotations

import hashlib
import json
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Final, Protocol, cast

from nhc_deprot_ranker.quantum.phase9b_permit import (
    REMOTE_ROOT_RELATIVE,
    ROUTE_ASSISTED,
    ROUTE_DIRECT,
)
from nhc_deprot_ranker.quantum.phase9b_source_identity import (
    CompositeSourceIdentityV9,
    SourceClosureError,
    validate_source_closure_definitions,
)

# Real deployment is a separate authorization.  Source-level gate.
EXECUTION_AUTHORIZED: Final[bool] = False

DEPLOY_STREAM_SCHEMA_VERSION: Final = "phase9b.directed-deploy-stream.v1"
DEPLOY_EVIDENCE_SCHEMA_VERSION: Final = "phase9b.directed-deploy-evidence.v1"
# v2 adds the per-route verified hash closure to the outcome, so a downstream
# step consumes proof instead of a caller-supplied mapping.
DEPLOY_OUTCOME_SCHEMA_VERSION: Final = "phase9b.directed-deploy-outcome.v2"
DEPLOY_VERIFICATION_SCHEMA_VERSION: Final = "phase9b.directed-deploy-verification.v1"

# Names that would let a Phase 8B artifact enter a Phase 9B deployment.
_RETIRED_TOKENS: Final[tuple[str, ...]] = (
    "QXHIEGFUWOLQIJ",
    "phase8b",
    "nhc_deprot_ranker_phase8b_dft_smoke_v001",
)

_MAX_FILES: Final = 64
_MAX_FILE_BYTES: Final = 16 * 1024 * 1024
_MAX_TRANSFER_BYTES: Final = 64 * 1024 * 1024
_MAX_STDOUT_BYTES: Final = 1024 * 1024
_MAX_STDERR_BYTES: Final = 64 * 1024
_FILE_MODE: Final = 0o640
_ROOT_MODE: Final = 0o700


class Phase9BDeployError(RuntimeError):
    """The directed deployment could not prove or preserve its closed scope."""


class Phase9BDeployNotAuthorizedError(Phase9BDeployError):
    """A real deployment was attempted while the source gate is closed."""


class DeployState(Enum):
    """The transaction's states.  Promotion is reachable only from VERIFIED."""

    PLANNED = "planned"
    LOCAL_VERIFIED = "local_verified"
    ROOTS_ABSENT = "roots_absent"
    STAGED = "staged"
    REMOTE_VERIFIED = "remote_verified"
    PROMOTED = "promoted"
    FAILED = "failed"


class CommandRunner(Protocol):
    """Injectable seam.  Production supplies SSH; tests supply a fake."""

    def __call__(
        self, command: Sequence[str], *, stdin: bytes, timeout: float
    ) -> tuple[int, bytes, bytes]: ...


@dataclass(frozen=True, slots=True)
class RoutePlan:
    """One route's registered files and its two attempt-unique roots."""

    route: str
    attempt_id: str
    staging_root: str
    final_root: str
    files: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class VerifiedFile:
    """One registered file as recomputed from the bytes actually on disk."""

    sha256: str
    bytes: int


@dataclass(frozen=True, slots=True)
class DeployVerificationReceipt:
    """The hash closure this deployment actually verified, per route.

    Downstream steps consume this instead of being handed a bare size mapping.
    ``receipt_sha256`` covers every other field, so a partially edited table is
    detectable; what makes it hard to forge usefully is that a consumer compares
    each entry against the permit's own request and manifest digests, which
    cannot be changed to match an invented value.
    """

    schema_version: str
    routes: Mapping[str, Mapping[str, VerifiedFile]]
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class DeploymentOutcome:
    """The transaction result.  A failure names every root it touched."""

    state: DeployState
    promoted_routes: tuple[str, ...]
    staging_roots: Mapping[str, str]
    final_roots: Mapping[str, str]
    failure_reason: str | None
    failure_roots: tuple[str, ...]
    ssh_invocations: int
    # v2 addition.  ``None`` on any outcome that never reached verification, so a
    # failed deployment cannot hand downstream a hash closure it never proved.
    verification: DeployVerificationReceipt | None = None


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
        raise Phase9BDeployError(f"{label} must be a lowercase SHA256")
    return value


def validate_relative_member(value: object, *, label: str) -> str:
    """Strict canonical relative POSIX path with no traversal or shell surface."""

    if not isinstance(value, str) or not value:
        raise Phase9BDeployError(f"{label} is empty")
    if any(character in value for character in "\\\x00"):
        raise Phase9BDeployError(f"{label} contains a backslash or NUL")
    # Anything the shell could reinterpret is refused outright rather than quoted
    # and hoped for: the remote side never sees a shell-expanded member name.
    for character in "*?[]{}$`\"'|&;<>()!~\n\r\t ":
        if character in value:
            raise Phase9BDeployError(f"{label} contains a shell-unsafe character")
    relative = PurePosixPath(value)
    if relative.is_absolute() or relative.as_posix() != value:
        raise Phase9BDeployError(f"{label} is not a canonical relative path")
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise Phase9BDeployError(f"{label} contains a traversal or dot segment")
    return value


def validate_absolute_root(value: object, *, label: str) -> str:
    """Strict canonical absolute POSIX root with no traversal or shell surface."""

    if not isinstance(value, str) or not value.startswith("/"):
        raise Phase9BDeployError(f"{label} is not an absolute path")
    if any(character in value for character in "\\\x00"):
        raise Phase9BDeployError(f"{label} contains a backslash or NUL")
    for character in "*?[]{}$`\"'|&;<>()!~\n\r\t ":
        if character in value:
            raise Phase9BDeployError(f"{label} contains a shell-unsafe character")
    path = PurePosixPath(value)
    if path.as_posix() != value or any(part in {".", ".."} for part in path.parts):
        raise Phase9BDeployError(f"{label} is not a canonical absolute path")
    for token in _RETIRED_TOKENS:
        if token in value:
            raise Phase9BDeployError(f"{label} references a retired Phase 8B artifact: {token}")
    return value


def build_route_plan(
    *,
    route: str,
    project_root: str,
    attempt_id: str,
    files: Mapping[str, str],
) -> RoutePlan:
    """Fix one route's registered file set and its two attempt-unique roots."""

    if route not in {ROUTE_DIRECT, ROUTE_ASSISTED}:
        raise Phase9BDeployError(f"unknown Phase 9B route: {route!r}")
    root = validate_absolute_root(project_root, label="project_root")
    if not attempt_id or any(token in attempt_id for token in _RETIRED_TOKENS):
        raise Phase9BDeployError("attempt id is empty or references a retired chain")
    if not files:
        raise Phase9BDeployError("a route must register at least one file")
    if len(files) > _MAX_FILES:
        raise Phase9BDeployError("registered file count exceeds its bound")

    registered: dict[str, str] = {}
    for name, digest in files.items():
        member = validate_relative_member(name, label="registered file path")
        registered[member] = _require_sha256(digest, label=f"registered sha256 {member}")

    base = f"{root}/{REMOTE_ROOT_RELATIVE}/{route}"
    # The staging root is namespaced by attempt so it cannot collide with any
    # other attempt, and it is a sibling of the final root so promotion is a
    # same-directory rename.
    staging = f"{root}/{REMOTE_ROOT_RELATIVE}/.staging-{attempt_id}-{route}"
    return RoutePlan(
        route=route,
        attempt_id=attempt_id,
        staging_root=validate_absolute_root(staging, label="staging_root"),
        final_root=validate_absolute_root(base, label="final_root"),
        files=dict(sorted(registered.items())),
    )


def verify_local_payload(plan: RoutePlan, *, bundle_dir: Path) -> dict[str, int]:
    """Re-verify every registered file, and refuse any unregistered one.

    Hashes are recomputed rather than trusted: the manifest states what should be
    uploaded, and this proves the bytes on disk still match it.
    """

    if not bundle_dir.is_absolute() or bundle_dir.is_symlink():
        raise Phase9BDeployError("bundle directory must be an absolute real path")
    if not bundle_dir.is_dir():
        raise Phase9BDeployError("bundle directory does not exist")

    sizes: dict[str, int] = {}
    for member, expected in plan.files.items():
        path = bundle_dir / member
        for parent in (path, *path.parents):
            if parent == bundle_dir:
                break
            if parent.is_symlink():
                raise Phase9BDeployError(f"registered path traverses a symlink: {member}")
        try:
            info = path.lstat()
        except OSError as exc:
            raise Phase9BDeployError(f"registered file is missing: {member}") from exc
        if not path.is_file() or path.is_symlink():
            raise Phase9BDeployError(f"registered path is not a regular file: {member}")
        if info.st_size <= 0 or info.st_size > _MAX_FILE_BYTES:
            raise Phase9BDeployError(f"registered file byte size is invalid: {member}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise Phase9BDeployError(f"local file hash drifted: {member}")
        sizes[member] = info.st_size

    # No directory-level sync: anything present but unregistered is a hard stop.
    present = {
        entry.relative_to(bundle_dir).as_posix()
        for entry in bundle_dir.rglob("*")
        if entry.is_file() or entry.is_symlink()
    }
    unregistered = sorted(present - set(plan.files))
    if unregistered:
        raise Phase9BDeployError(f"bundle holds an unregistered file: {unregistered[0]}")
    if sum(sizes.values()) > _MAX_TRANSFER_BYTES:
        raise Phase9BDeployError("total transfer size exceeds its bound")
    return sizes


def build_deploy_stream(plan: RoutePlan, *, bundle_dir: Path, sizes: Mapping[str, int]) -> bytes:
    """Header plus length-prefixed bodies, in one deterministic order."""

    header = {
        "schema_version": DEPLOY_STREAM_SCHEMA_VERSION,
        "route": plan.route,
        "attempt_id": plan.attempt_id,
        "staging_root": plan.staging_root,
        "final_root": plan.final_root,
        "file_mode": f"{_FILE_MODE:04o}",
        "root_mode": f"{_ROOT_MODE:04o}",
        "files": {
            member: {"sha256": plan.files[member], "bytes": sizes[member]} for member in plan.files
        },
    }
    raw = _canonical_json_bytes(header)
    parts = [len(raw).to_bytes(8, "big"), raw]
    for member in plan.files:
        body = (bundle_dir / member).read_bytes()
        if len(body) != sizes[member]:
            raise Phase9BDeployError(f"file changed size during streaming: {member}")
        parts.append(len(body).to_bytes(8, "big"))
        parts.append(body)
    return b"".join(parts)


# Standard library only.  Exclusive-create for every file and directory, no
# overwrite, no delete, no symlink follow, no shell.  It re-reads and hashes what
# it wrote, scans for extras, and prints canonical evidence.
REMOTE_RECEIVER_SOURCE: Final = r"""import hashlib, json, os, sys
def read_exact(n):
    buf = b""
    while len(buf) < n:
        chunk = sys.stdin.buffer.read(n - len(buf))
        if not chunk:
            raise SystemExit("truncated stream")
        buf += chunk
    return buf
hdr_len = int.from_bytes(read_exact(8), "big")
header = json.loads(read_exact(hdr_len).decode("utf-8"))
staging = header["staging_root"]
if os.path.lexists(staging):
    raise SystemExit("staging root already exists")
if os.path.lexists(header["final_root"]):
    raise SystemExit("final root already exists")
os.makedirs(staging, mode=int(header["root_mode"], 8), exist_ok=False)
written = {}
for member, entry in sorted(header["files"].items()):
    target = os.path.join(staging, member)
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, mode=int(header["root_mode"], 8), exist_ok=False)
    body = read_exact(int.from_bytes(read_exact(8), "big"))
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 int(header["file_mode"], 8))
    try:
        os.write(fd, body)
        os.fsync(fd)
    finally:
        os.close(fd)
    st = os.lstat(target)
    with open(target, "rb") as fh:
        h = hashlib.sha256()
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    written[member] = {"sha256": h.hexdigest(), "bytes": st.st_size,
                       "regular": bool(st.st_mode & 0o100000) and not os.path.islink(target)}
if sys.stdin.buffer.read(1):
    raise SystemExit("trailing bytes")
seen = []
for base, dirs, names in os.walk(staging):
    for name in names:
        seen.append(os.path.relpath(os.path.join(base, name), staging))
print(json.dumps({"schema_version": "phase9b.directed-deploy-evidence.v1",
                  "route": header["route"], "attempt_id": header["attempt_id"],
                  "staging_root": staging, "written": written,
                  "present": sorted(seen), "promoted": False}, sort_keys=True))
"""

REMOTE_PROMOTER_SOURCE: Final = r"""import json, os, sys
pairs = json.loads(sys.argv[1])
done = []
for staging, final in pairs:
    if not os.path.isdir(staging):
        raise SystemExit("staging root missing: " + staging)
    if os.path.lexists(final):
        raise SystemExit("final root already exists: " + final)
    os.rename(staging, final)
    done.append(final)
print(json.dumps({"promoted": done}, sort_keys=True))
"""


def _verification_body(routes: Mapping[str, Mapping[str, VerifiedFile]]) -> dict[str, object]:
    return {
        "schema_version": DEPLOY_VERIFICATION_SCHEMA_VERSION,
        "routes": {
            route: {
                member: {"sha256": entry.sha256, "bytes": entry.bytes}
                for member, entry in sorted(members.items())
            }
            for route, members in sorted(routes.items())
        },
    }


def build_verification_receipt(
    *, plans: Sequence[RoutePlan], verified_sizes: Mapping[str, Mapping[str, int]]
) -> DeployVerificationReceipt:
    """Fold each route's recomputed hashes and byte sizes into one receipt."""

    routes: dict[str, Mapping[str, VerifiedFile]] = {}
    for plan in plans:
        sizes = verified_sizes.get(plan.route)
        if sizes is None or set(sizes) != set(plan.files):
            raise Phase9BDeployError(
                f"verified size set differs from the registered set: {plan.route}"
            )
        members: dict[str, VerifiedFile] = {}
        for member, digest in sorted(plan.files.items()):
            size = sizes[member]
            if type(size) is not int or size <= 0:
                raise Phase9BDeployError(f"verified byte size is invalid: {member}")
            members[member] = VerifiedFile(
                sha256=_require_sha256(digest, label=f"registered sha256 {member}"), bytes=size
            )
        routes[plan.route] = members
    return DeployVerificationReceipt(
        schema_version=DEPLOY_VERIFICATION_SCHEMA_VERSION,
        routes=routes,
        receipt_sha256=hashlib.sha256(
            _canonical_json_bytes(_verification_body(routes))
        ).hexdigest(),
    )


def recomputed_verification_sha256(receipt: DeployVerificationReceipt) -> str:
    """Recompute the digest over every field except the digest itself."""

    return hashlib.sha256(_canonical_json_bytes(_verification_body(receipt.routes))).hexdigest()


def build_upload_command(*, ssh_alias: str, plan: RoutePlan) -> tuple[str, ...]:
    """One bounded SSH call carrying one route's stream on stdin."""

    if not ssh_alias:
        raise Phase9BDeployError("deployment needs an ssh alias")
    validate_absolute_root(plan.staging_root, label="staging_root")
    return (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ConnectTimeout=15",
        ssh_alias,
        "exec python3 -I -B -c " + shlex.quote(REMOTE_RECEIVER_SOURCE),
    )


def build_promote_command(*, ssh_alias: str, plans: Sequence[RoutePlan]) -> tuple[str, ...]:
    """One bounded SSH call that renames both staging roots into place."""

    if not ssh_alias:
        raise Phase9BDeployError("promotion needs an ssh alias")
    pairs = [[plan.staging_root, plan.final_root] for plan in plans]
    return (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ConnectTimeout=15",
        ssh_alias,
        "exec python3 -I -B -c "
        + shlex.quote(REMOTE_PROMOTER_SOURCE)
        + " "
        + shlex.quote(json.dumps(pairs, sort_keys=True, separators=(",", ":"))),
    )


def _strict_json_object(raw: bytes, *, label: str) -> dict[str, object]:
    if not raw or len(raw) > _MAX_STDOUT_BYTES:
        raise Phase9BDeployError(f"{label} byte size is invalid")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        seen: dict[str, object] = {}
        for key, value in pairs:
            if key in seen:
                raise Phase9BDeployError(f"{label} contains duplicate key: {key}")
            seen[key] = value
        return seen

    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except Phase9BDeployError:
        raise
    except (UnicodeDecodeError, ValueError) as exc:
        raise Phase9BDeployError(f"{label} is not strict JSON") from exc
    if not isinstance(decoded, dict):
        raise Phase9BDeployError(f"{label} must be one JSON object")
    return cast(dict[str, object], decoded)


def verify_remote_evidence(raw: bytes, *, plan: RoutePlan, sizes: Mapping[str, int]) -> None:
    """Per-file path, type, size, and hash, plus the exact set in both directions."""

    payload = _strict_json_object(raw, label="deploy evidence")
    if payload.get("schema_version") != DEPLOY_EVIDENCE_SCHEMA_VERSION:
        raise Phase9BDeployError("deploy evidence schema drifted")
    if payload.get("route") != plan.route or payload.get("attempt_id") != plan.attempt_id:
        raise Phase9BDeployError("deploy evidence identity drifted")
    if payload.get("staging_root") != plan.staging_root:
        raise Phase9BDeployError("deploy evidence staging root drifted")
    if payload.get("promoted") is not False:
        raise Phase9BDeployError("upload must not promote; promotion is a separate step")

    written = payload.get("written")
    if not isinstance(written, dict):
        raise Phase9BDeployError("deploy evidence written set is malformed")
    if set(written) != set(plan.files):
        raise Phase9BDeployError("remote written set differs from the registered set")
    for member, expected in plan.files.items():
        entry = written[member]
        if not isinstance(entry, dict):
            raise Phase9BDeployError(f"remote entry is malformed: {member}")
        if entry.get("regular") is not True:
            raise Phase9BDeployError(f"remote file is not a regular file: {member}")
        if entry.get("bytes") != sizes[member]:
            raise Phase9BDeployError(f"remote byte size differs: {member}")
        if entry.get("sha256") != expected:
            raise Phase9BDeployError(f"remote hash differs: {member}")

    present = payload.get("present")
    if not isinstance(present, list) or sorted(cast(list[str], present)) != sorted(plan.files):
        raise Phase9BDeployError("remote tree holds an extra or missing file")


def deploy_both_routes(
    *,
    ssh_alias: str,
    plans: Sequence[RoutePlan],
    bundle_dirs: Mapping[str, Path],
    run_command: CommandRunner | None = None,
    timeout_seconds: float = 300.0,
) -> DeploymentOutcome:
    """Deploy both routes as one transaction, or fail closed naming every root."""

    if run_command is None and EXECUTION_AUTHORIZED is not True:
        raise Phase9BDeployNotAuthorizedError("a real Phase 9B deployment is not authorized")
    if run_command is None:  # pragma: no cover - unreachable while the gate is closed
        raise Phase9BDeployNotAuthorizedError("no production deployment runner is wired")
    if not 0.0 < timeout_seconds <= 900.0:
        raise ValueError("deployment timeout must be in (0, 900]")
    if len(plans) != 2 or {plan.route for plan in plans} != {ROUTE_DIRECT, ROUTE_ASSISTED}:
        raise Phase9BDeployError("a deployment transaction covers exactly both routes")
    if len({plan.staging_root for plan in plans}) != 2:
        raise Phase9BDeployError("the two routes must use distinct staging roots")
    if len({plan.final_root for plan in plans}) != 2:
        raise Phase9BDeployError("the two routes must use distinct final roots")

    staging = {plan.route: plan.staging_root for plan in plans}
    final = {plan.route: plan.final_root for plan in plans}
    invocations = 0

    def failed(reason: str, roots: Sequence[str]) -> DeploymentOutcome:
        return DeploymentOutcome(
            state=DeployState.FAILED,
            promoted_routes=(),
            staging_roots=staging,
            final_roots=final,
            failure_reason=reason,
            failure_roots=tuple(roots),
            ssh_invocations=invocations,
        )

    verified_sizes: dict[str, Mapping[str, int]] = {}
    try:
        for plan in plans:
            bundle_dir = bundle_dirs.get(plan.route)
            if bundle_dir is None:
                raise Phase9BDeployError(f"no bundle directory for route: {plan.route}")
            verified_sizes[plan.route] = verify_local_payload(plan, bundle_dir=bundle_dir)
    except Phase9BDeployError as exc:
        return failed(f"local verification failed: {exc}", [])

    # Upload both routes before promoting either.  A single successful upload is
    # never grounds for treating the transaction as launchable.
    for plan in plans:
        sizes = verified_sizes[plan.route]
        stream = build_deploy_stream(plan, bundle_dir=bundle_dirs[plan.route], sizes=sizes)
        command = build_upload_command(ssh_alias=ssh_alias, plan=plan)
        invocations += 1
        try:
            code, stdout, stderr = run_command(command, stdin=stream, timeout=timeout_seconds)
        except Exception as exc:
            return failed(f"transport failed for {plan.route}: {exc}", [plan.staging_root])
        if len(stderr) > _MAX_STDERR_BYTES:
            return failed(f"stderr exceeded its bound for {plan.route}", [plan.staging_root])
        if code != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()[:200]
            return failed(f"upload exited {code} for {plan.route}: {detail}", [plan.staging_root])
        if stderr:
            return failed(f"unexpected stderr for {plan.route}", [plan.staging_root])
        try:
            verify_remote_evidence(stdout, plan=plan, sizes=sizes)
        except Phase9BDeployError as exc:
            return failed(
                f"remote verification failed for {plan.route}: {exc}", [plan.staging_root]
            )

    command = build_promote_command(ssh_alias=ssh_alias, plans=plans)
    invocations += 1
    try:
        code, stdout, stderr = run_command(command, stdin=b"", timeout=timeout_seconds)
    except Exception as exc:
        return failed(f"promotion transport failed: {exc}", [plan.staging_root for plan in plans])
    if code != 0 or stderr:
        detail = stderr.decode("utf-8", errors="replace").strip()[:200]
        # Promotion renames two directories, so it cannot be one atomic step.  If
        # the second fails after the first succeeded, the first stays promoted and
        # is named here: rolling it back would mean a destructive remote delete,
        # which this module never performs.
        return failed(
            f"promotion failed and may be partial: {code} {detail}",
            [*(plan.staging_root for plan in plans), *(plan.final_root for plan in plans)],
        )
    promoted = _strict_json_object(stdout, label="promotion evidence").get("promoted")
    expected = [plan.final_root for plan in plans]
    if not isinstance(promoted, list) or sorted(cast(list[str], promoted)) != sorted(expected):
        return failed(
            "promotion evidence does not name exactly both final roots",
            [*(plan.staging_root for plan in plans), *expected],
        )
    return DeploymentOutcome(
        state=DeployState.PROMOTED,
        promoted_routes=tuple(sorted(plan.route for plan in plans)),
        staging_roots=staging,
        final_roots=final,
        failure_reason=None,
        failure_roots=(),
        ssh_invocations=invocations,
        # Only a promoted transaction carries the hash closure; every failure path
        # above leaves it None, so nothing downstream can read proof into a failure.
        verification=build_verification_receipt(plans=plans, verified_sizes=verified_sizes),
    )


@dataclass(frozen=True, slots=True)
class CompositeDeploymentValidationV3:
    generation: str
    full_source_sha256: str
    deployment_inventory_sha256: str
    direct_manifest_sha256: str
    assisted_manifest_sha256: str
    atomic_inventory_complete: bool
    deployed: bool = False


def validate_composite_deployment_v3(
    *,
    source_identity: CompositeSourceIdentityV9,
    direct_manifest: bytes,
    assisted_manifest: bytes,
) -> CompositeDeploymentValidationV3:
    """Validate the one atomic v3 inventory locally; never deploy it."""

    try:
        validate_source_closure_definitions()
    except SourceClosureError as exc:
        raise Phase9BDeployError("v9 closure DAG is invalid") from exc
    direct = _strict_json_object(direct_manifest, label="direct v3 manifest")
    assisted = _strict_json_object(assisted_manifest, label="assisted v3 manifest")
    for route, payload in ((ROUTE_DIRECT, direct), (ROUTE_ASSISTED, assisted)):
        if (
            payload.get("schema_version") != "phase9b.payload_manifest.v3"
            or payload.get("generation") != "phase9b-split-process-v003"
            or payload.get("route") != route
            or payload.get("execution_authorized") is not False
            or payload.get("real_permit_generated") is not False
        ):
            raise Phase9BDeployError(f"{route} v3 manifest identity drifted")
        closures = payload.get("source_closures")
        if not isinstance(closures, dict):
            raise Phase9BDeployError(f"{route} source closure payload is missing")
        if (
            closures.get("full_assisted_campaign_source")
            != source_identity.full_assisted_campaign_source_sha256
        ):
            raise Phase9BDeployError(f"{route} carries a mixed source generation")
    return CompositeDeploymentValidationV3(
        generation="phase9b-split-process-v003",
        full_source_sha256=source_identity.full_assisted_campaign_source_sha256,
        deployment_inventory_sha256=source_identity.deployment_inventory_sha256,
        direct_manifest_sha256=hashlib.sha256(direct_manifest).hexdigest(),
        assisted_manifest_sha256=hashlib.sha256(assisted_manifest).hexdigest(),
        atomic_inventory_complete=True,
        deployed=False,
    )


__all__ = [
    "DEPLOY_EVIDENCE_SCHEMA_VERSION",
    "DEPLOY_OUTCOME_SCHEMA_VERSION",
    "DEPLOY_STREAM_SCHEMA_VERSION",
    "DEPLOY_VERIFICATION_SCHEMA_VERSION",
    "EXECUTION_AUTHORIZED",
    "REMOTE_PROMOTER_SOURCE",
    "REMOTE_RECEIVER_SOURCE",
    "CommandRunner",
    "CompositeDeploymentValidationV3",
    "DeployState",
    "DeployVerificationReceipt",
    "DeploymentOutcome",
    "Phase9BDeployError",
    "Phase9BDeployNotAuthorizedError",
    "RoutePlan",
    "VerifiedFile",
    "build_deploy_stream",
    "build_promote_command",
    "build_route_plan",
    "build_upload_command",
    "build_verification_receipt",
    "deploy_both_routes",
    "recomputed_verification_sha256",
    "validate_absolute_root",
    "validate_composite_deployment_v3",
    "validate_relative_member",
    "verify_local_payload",
    "verify_remote_evidence",
]
