"""Immutable exact-tree evidence primitives for a split-process campaign."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from nhc_deprot_ranker.quantum.phase9b_campaign_schemas import (
    CampaignEvidenceManifestV1,
    CampaignSchemaError,
    canonical_json_bytes,
)

MAX_EVIDENCE_FILE_BYTES: Final = 8 * 1024 * 1024
PRIVATE_DIRECTORY_MODE: Final = 0o700
PRIVATE_RECORD_MODE: Final = 0o600
IMMUTABLE_DATA_MODE: Final = 0o400

# Production allowed set.  Endpoint optimization/final subtrees are represented
# by their immutable terminal receipts during Item 10; Item 11 Postflight is not
# implemented here.
CAMPAIGN_ALLOWED_PATHS: Final[frozenset[str]] = frozenset(
    {
        "runtime/campaign/campaign_identity.json",
        "runtime/campaign/campaign_ack.json",
        "runtime/campaign/campaign_schedule.json",
        "runtime/campaign/campaign_terminal.json",
        "runtime/campaign/guardian_launch.json",
        "runtime/stage_a1/identity.json",
        "runtime/stage_a1/capability_digest.json",
        "runtime/stage_a1/process_registration.json",
        "runtime/stage_a1/acknowledgement.json",
        "runtime/stage_a1/capability_consumption.json",
        "runtime/stage_a1/cation/input.xyz",
        "runtime/stage_a1/cation/output.xyz",
        "runtime/stage_a1/cation/trajectory.jsonl",
        "runtime/stage_a1/cation/preoptimization_receipt.json",
        "runtime/stage_a1/neutral/input.xyz",
        "runtime/stage_a1/neutral/output.xyz",
        "runtime/stage_a1/neutral/trajectory.jsonl",
        "runtime/stage_a1/neutral/preoptimization_receipt.json",
        "runtime/stage_a1/handoff_proposal.json",
        "runtime/stage_a1/terminal.json",
        "runtime/handoff/verification.json",
        "runtime/handoff/a2_admission.json",
        "runtime/stage_a2/identity.json",
        "runtime/stage_a2/capability_digest.json",
        "runtime/stage_a2/process_registration.json",
        "runtime/stage_a2/acknowledgement.json",
        "runtime/stage_a2/capability_consumption.json",
        "runtime/stage_a2/cation/input.xyz",
        "runtime/stage_a2/cation/endpoint_result.json",
        "runtime/stage_a2/neutral/input.xyz",
        "runtime/stage_a2/neutral/endpoint_result.json",
        "runtime/stage_a2/route_result.json",
        "runtime/stage_a2/terminal.json",
        "runtime/evidence/permit_consumption.json",
        "runtime/evidence/process_tree.json",
        "runtime/evidence/route_terminal.json",
        "runtime/evidence/evidence_manifest.json",
    }
)


class CampaignEvidenceError(RuntimeError):
    """Evidence path, bytes, durability, or exact-tree identity failed."""


@dataclass(frozen=True, slots=True)
class DurableFileIdentity:
    relative_path: str
    sha256: str
    byte_count: int
    mode: int
    device: int
    inode: int

    def manifest_payload(self) -> dict[str, object]:
        return {
            "sha256": self.sha256,
            "byte_count": self.byte_count,
            "mode": f"{self.mode:04o}",
        }


def _safe_relative(relative_path: str) -> PurePosixPath:
    if not isinstance(relative_path, str) or not relative_path or "\x00" in relative_path:
        raise CampaignEvidenceError("evidence relative path is invalid")
    path = PurePosixPath(relative_path)
    if path.is_absolute() or path.as_posix() != relative_path:
        raise CampaignEvidenceError("evidence path must be normalized and relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise CampaignEvidenceError("evidence path contains a dot segment")
    return path


def _ensure_private_directory(path: Path) -> None:
    if path.exists():
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise CampaignEvidenceError(f"evidence parent is not a real directory: {path.name}")
        return
    path.mkdir(mode=PRIVATE_DIRECTORY_MODE)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise CampaignEvidenceError("created evidence parent identity is invalid")


def durable_exclusive_write(
    root: Path,
    relative_path: str,
    raw: bytes,
    *,
    mode: int = PRIVATE_RECORD_MODE,
    max_bytes: int = MAX_EVIDENCE_FILE_BYTES,
    allowed_paths: frozenset[str] = CAMPAIGN_ALLOWED_PATHS,
) -> DurableFileIdentity:
    """Exclusive/no-follow write, fsync, re-read, and stat-stability proof."""

    relative = _safe_relative(relative_path)
    if relative_path not in allowed_paths:
        raise CampaignEvidenceError(f"path is outside the frozen evidence tree: {relative_path}")
    if not isinstance(raw, bytes) or not raw or len(raw) > max_bytes:
        raise CampaignEvidenceError("evidence bytes violate their bound")
    if mode not in {PRIVATE_RECORD_MODE, IMMUTABLE_DATA_MODE}:
        raise CampaignEvidenceError("evidence mode is not registered")
    if not root.is_absolute():
        raise CampaignEvidenceError("evidence root must be absolute")
    _ensure_private_directory(root)
    parent = root
    for component in relative.parts[:-1]:
        parent = parent / component
        _ensure_private_directory(parent)
    destination = root.joinpath(*relative.parts)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow == 0:
        raise CampaignEvidenceError("O_NOFOLLOW is required for evidence writes")
    fd = os.open(destination, flags | nofollow, mode)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise CampaignEvidenceError("evidence write made no progress")
            view = view[written:]
        os.fsync(fd)
        before = os.fstat(fd)
    finally:
        os.close(fd)
    directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    read_fd = os.open(destination, os.O_RDONLY | nofollow)
    try:
        reread = b""
        while len(reread) <= max_bytes:
            chunk = os.read(read_fd, min(64 * 1024, max_bytes + 1 - len(reread)))
            if not chunk:
                break
            reread += chunk
        after = os.fstat(read_fd)
    finally:
        os.close(read_fd)
    if reread != raw:
        raise CampaignEvidenceError("evidence reread differs from written bytes")
    if (before.st_dev, before.st_ino, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise CampaignEvidenceError("evidence identity drifted during durable write")
    observed_mode = stat.S_IMODE(after.st_mode)
    if not stat.S_ISREG(after.st_mode) or after.st_nlink != 1 or observed_mode != mode:
        raise CampaignEvidenceError("evidence file type/link/mode is invalid")
    return DurableFileIdentity(
        relative_path=relative_path,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_count=len(raw),
        mode=observed_mode,
        device=after.st_dev,
        inode=after.st_ino,
    )


def safe_read_exact_file(
    root: Path,
    relative_path: str,
    *,
    max_bytes: int = MAX_EVIDENCE_FILE_BYTES,
    allowed_paths: frozenset[str] = CAMPAIGN_ALLOWED_PATHS,
) -> tuple[bytes, DurableFileIdentity]:
    relative = _safe_relative(relative_path)
    if relative_path not in allowed_paths:
        raise CampaignEvidenceError("read path is outside the frozen evidence tree")
    path = root.joinpath(*relative.parts)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow == 0:
        raise CampaignEvidenceError("O_NOFOLLOW is required for evidence reads")
    fd = os.open(path, os.O_RDONLY | nofollow)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise CampaignEvidenceError("evidence read target is not a regular single-link file")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise CampaignEvidenceError("evidence read target exceeds its size bound")
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise CampaignEvidenceError("evidence changed during read")
    raw = b"".join(chunks)
    return raw, DurableFileIdentity(
        relative_path=relative_path,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_count=len(raw),
        mode=stat.S_IMODE(after.st_mode),
        device=after.st_dev,
        inode=after.st_ino,
    )


class CampaignEvidenceStore:
    """Append-only evidence store with an exact allowed path registry."""

    __slots__ = ("_files", "_root")

    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise CampaignEvidenceError("campaign evidence root must be absolute")
        self._root = root
        self._files: dict[str, DurableFileIdentity] = {}

    @property
    def root(self) -> Path:
        return self._root

    @property
    def identities(self) -> tuple[DurableFileIdentity, ...]:
        return tuple(self._files[name] for name in sorted(self._files))

    def write_bytes(
        self, relative_path: str, raw: bytes, *, mode: int = PRIVATE_RECORD_MODE
    ) -> DurableFileIdentity:
        if relative_path in self._files:
            raise CampaignEvidenceError("evidence store refuses overwrite")
        identity = durable_exclusive_write(self._root, relative_path, raw, mode=mode)
        self._files[relative_path] = identity
        return identity

    def write_json(self, relative_path: str, payload: object) -> DurableFileIdentity:
        return self.write_bytes(relative_path, canonical_json_bytes(payload))

    def read(self, relative_path: str) -> tuple[bytes, DurableFileIdentity]:
        raw, observed = safe_read_exact_file(self._root, relative_path)
        registered = self._files.get(relative_path)
        if registered is not None and (
            registered.sha256,
            registered.byte_count,
            registered.device,
            registered.inode,
        ) != (
            observed.sha256,
            observed.byte_count,
            observed.device,
            observed.inode,
        ):
            raise CampaignEvidenceError("registered evidence identity drifted")
        if registered is None:
            # A stage process owns its immutable files.  The supervisor adopts
            # only files it explicitly verifies; unread extras still fail the
            # final exact-tree comparison.
            self._files[relative_path] = observed
        return raw, observed

    def build_manifest(
        self,
        *,
        campaign_id: str,
        attempt_id: str,
        terminal_classification: str,
    ) -> CampaignEvidenceManifestV1:
        files = {
            name: identity.manifest_payload()
            for name, identity in sorted(self._files.items())
            if name != "runtime/evidence/evidence_manifest.json"
        }
        try:
            return CampaignEvidenceManifestV1(
                {
                    "schema_version": CampaignEvidenceManifestV1.SCHEMA_VERSION,
                    "campaign_id": campaign_id,
                    "attempt_id": attempt_id,
                    "terminal_classification": terminal_classification,
                    "files": files,
                }
            )
        except CampaignSchemaError as exc:
            raise CampaignEvidenceError("evidence manifest failed schema validation") from exc

    def assert_no_extra_files(self) -> None:
        actual: set[str] = set()
        if not self._root.exists():
            raise CampaignEvidenceError("campaign evidence root is absent")
        for path in self._root.rglob("*"):
            if path.is_symlink():
                raise CampaignEvidenceError("symlink exists in campaign evidence tree")
            if path.is_file():
                actual.add(path.relative_to(self._root).as_posix())
        expected = set(self._files)
        if actual != expected:
            raise CampaignEvidenceError(
                f"campaign evidence file set drifted; extra={sorted(actual - expected)}, "
                f"missing={sorted(expected - actual)}"
            )


__all__ = [
    "CAMPAIGN_ALLOWED_PATHS",
    "IMMUTABLE_DATA_MODE",
    "MAX_EVIDENCE_FILE_BYTES",
    "PRIVATE_RECORD_MODE",
    "CampaignEvidenceError",
    "CampaignEvidenceStore",
    "DurableFileIdentity",
    "durable_exclusive_write",
    "safe_read_exact_file",
]
