"""The one-shot permit consumption transaction, in exactly one copy.

Extracted verbatim in behaviour from the audited Phase 8B implementation so both
authority chains share the race-critical code rather than each carrying a copy.
Phase 8B's own consumption delegates here, and its existing regressions prove the
behaviour did not move.

The linearization point is the successful ``O_EXCL`` creation of the consumed
record.  Everything about how that is reached matters:

``O_DIRECTORY | O_NOFOLLOW`` on the private directory, then every subsequent
operation relative to that descriptor, so the path cannot be swapped underneath
between checks.  ``O_NOFOLLOW`` on the ready file, a device/inode recheck after
validation, and ``O_CREAT | O_EXCL | O_NOFOLLOW`` for the consumed file.

There is deliberately **no rename**.  A check-then-rename pair is racy no matter
how the check is written; exclusive create is atomic, and the kernel decides who
wins.  Nothing below the linearization point can restore the ready permit, and
this module contains no code that could.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_MAX_PERMIT_BYTES: Final = 64 * 1024


class OneShotPermitError(RuntimeError):
    """The one-shot permit transaction could not be completed safely."""


class OneShotPermitValidationError(OneShotPermitError):
    """The permit's bytes, ownership, mode, or layout failed validation."""


class OneShotPermitConsumedError(OneShotPermitError):
    """The permit is already consumed, or lost the consume race."""


@dataclass(frozen=True, slots=True)
class PermitErrors:
    """The caller's own exception types, so error identity stays chain-specific."""

    error: type[Exception]
    validation: type[Exception]
    consumed: type[Exception]


@dataclass(frozen=True, slots=True)
class ConsumedPermitBytes:
    """What crossed the irreversible point, and the digests proving it."""

    raw_bytes: bytes
    permit_sha256: str
    consumed_sha256: str
    validation_result: object


def _read_fd(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, 1 << 16)
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_PERMIT_BYTES:
            raise OneShotPermitValidationError("permit byte size exceeds its bound")
        chunks.append(chunk)
    if total == 0:
        raise OneShotPermitValidationError("permit is empty")
    return b"".join(chunks)


def _validate_owned_regular_stat(
    observed: os.stat_result, *, label: str, expected_mode: int, errors: PermitErrors
) -> None:
    # Messages match the audited Phase 8B originals verbatim; a reworded refusal
    # would change what its regressions assert without changing behaviour.
    if not stat.S_ISREG(observed.st_mode):
        raise errors.validation(f"{label} is not a regular file")
    if observed.st_uid != os.geteuid():
        raise errors.validation(f"{label} is not owned by the current user")
    if stat.S_IMODE(observed.st_mode) != expected_mode:
        raise errors.validation(f"{label} mode must be {expected_mode:04o}")
    if observed.st_nlink != 1:
        raise errors.validation(f"{label} must have exactly one hard link")


def consume_one_shot_permit(
    ready_path: Path,
    *,
    ready_relative_name: str,
    consumed_relative_name: str,
    ready_mode: int,
    consumed_mode: int,
    validate: Callable[[bytes], object],
    errors: PermitErrors,
) -> ConsumedPermitBytes:
    """Validate and irreversibly consume one permit.  Never restores it.

    ``validate`` receives the exact bytes read under ``O_NOFOLLOW`` and raises the
    caller's own error on any mismatch; whatever it returns is handed back so the
    caller keeps its chain-specific layout record.  It runs **before** the
    linearization point, so a rejected permit is never consumed.
    """

    if not ready_path.is_absolute() or ready_path.name != ready_relative_name:
        raise errors.validation("ready_path must be the exact absolute permit path")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise errors.validation("platform lacks required no-follow directory flags")
    if ready_relative_name == consumed_relative_name:
        raise errors.validation("ready and consumed permit names collide")

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        directory_fd = os.open(ready_path.parent, directory_flags)
    except OSError as exc:
        raise errors.validation("permit directory cannot be opened safely") from exc

    ready_fd: int | None = None
    try:
        # Already consumed is a refusal, not a retry.
        try:
            os.stat(consumed_relative_name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise errors.consumed("the one-shot permit is already consumed")

        try:
            ready_fd = os.open(
                ready_relative_name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
        except FileNotFoundError as exc:
            try:
                os.stat(consumed_relative_name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                raise errors.validation("ready permit disappeared before validation") from exc
            raise errors.consumed("the one-shot permit lost the consume race") from exc
        except OSError as exc:
            # A symlink at the ready path lands here: O_NOFOLLOW refuses to open it.
            raise errors.validation("ready permit cannot be opened safely") from exc

        opened_stat = os.fstat(ready_fd)
        _validate_owned_regular_stat(
            opened_stat, label="ready permit", expected_mode=ready_mode, errors=errors
        )
        try:
            raw = _read_fd(ready_fd)
        except OneShotPermitValidationError as exc:
            raise errors.validation(str(exc)) from exc

        validation_result = validate(raw)

        # The file that was validated must still be the file at that name.
        try:
            current_stat = os.stat(ready_relative_name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            try:
                os.stat(consumed_relative_name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                raise errors.validation("ready permit disappeared during validation") from exc
            raise errors.consumed("the one-shot permit lost the consume race") from exc
        if (current_stat.st_dev, current_stat.st_ino) != (opened_stat.st_dev, opened_stat.st_ino):
            raise errors.validation("ready permit changed during validation")

        # --- linearization point ------------------------------------------------
        try:
            consumed_fd = os.open(
                consumed_relative_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                ready_mode,
                dir_fd=directory_fd,
            )
        except FileExistsError as exc:
            raise errors.consumed("the one-shot permit lost the consume race") from exc
        except OSError as exc:
            raise errors.error("consumed permit could not be created safely") from exc
        # Past this point the attempt is spent.  No branch below restores ready.

        try:
            view = memoryview(raw)
            written = 0
            while written < len(view):
                count = os.write(consumed_fd, view[written:])
                if count <= 0:
                    raise errors.error("consumed permit write made no progress")
                written += count
            os.fchmod(consumed_fd, consumed_mode)
            os.fsync(consumed_fd)
        finally:
            os.close(consumed_fd)
        os.fsync(directory_fd)

        # If unlink or fsync fails here, ready and consumed coexist and every
        # reader treats that as consumed.  Fail-closed, never restored.
        os.unlink(ready_relative_name, dir_fd=directory_fd)
        os.fsync(directory_fd)
        try:
            os.stat(ready_relative_name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise errors.error("ready permit still exists after consumption")

        consumed_stat = os.stat(consumed_relative_name, dir_fd=directory_fd, follow_symlinks=False)
        _validate_owned_regular_stat(
            consumed_stat, label="consumed permit", expected_mode=consumed_mode, errors=errors
        )
        consumed_read_fd = os.open(
            consumed_relative_name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_fd,
        )
        try:
            consumed_raw = _read_fd(consumed_read_fd)
        finally:
            os.close(consumed_read_fd)
        if consumed_raw != raw:
            raise errors.error("consumed permit bytes changed after fsync")
        if consumed_stat.st_size != len(raw):
            raise errors.error("consumed permit byte size changed after fsync")

        digest = hashlib.sha256(raw).hexdigest()
        return ConsumedPermitBytes(
            raw_bytes=raw,
            permit_sha256=digest,
            consumed_sha256=hashlib.sha256(consumed_raw).hexdigest(),
            validation_result=validation_result,
        )
    finally:
        if ready_fd is not None:
            os.close(ready_fd)
        os.close(directory_fd)


__all__ = [
    "ConsumedPermitBytes",
    "OneShotPermitConsumedError",
    "OneShotPermitError",
    "OneShotPermitValidationError",
    "PermitErrors",
    "consume_one_shot_permit",
]
