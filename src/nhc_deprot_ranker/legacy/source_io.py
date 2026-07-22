"""Read local or SSH-hosted legacy sources without remote writes."""

from __future__ import annotations

import contextlib
import shlex
import subprocess
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import IO

from nhc_deprot_ranker.data.provenance import sha256_file
from nhc_deprot_ranker.legacy.paths import ResolvedSource


class SourceAccessError(RuntimeError):
    """A configured source could not be read safely."""


@dataclass(frozen=True)
class SourceMetadata:
    """Stable source identity without private absolute paths."""

    source_id: str
    sha256: str
    size_bytes: int
    transport: str

    def to_dict(self) -> dict[str, str | int]:
        """Return a JSON-compatible mapping."""

        return asdict(self)


class SourceReader:
    """Read-only source transport with cached metadata."""

    def __init__(self) -> None:
        self._metadata_cache: dict[str, SourceMetadata] = {}

    def metadata(self, source: ResolvedSource) -> SourceMetadata:
        """Return size and SHA256 without modifying the source."""

        cached = self._metadata_cache.get(source.source_id)
        if cached is not None:
            return cached
        if source.is_remote:
            metadata = self._remote_metadata(source)
        else:
            if not source.path.is_file():
                raise FileNotFoundError(source.path)
            metadata = SourceMetadata(
                source_id=source.source_id,
                sha256=sha256_file(source.path),
                size_bytes=source.path.stat().st_size,
                transport="local",
            )
        self._metadata_cache[source.source_id] = metadata
        return metadata

    @contextlib.contextmanager
    def open_text(self, source: ResolvedSource) -> Iterator[IO[str]]:
        """Open UTF-8 text locally or stream it through `ssh cat`."""

        if not source.is_remote:
            if not source.path.is_file():
                raise FileNotFoundError(source.path)
            with source.path.open("r", encoding="utf-8", newline="") as stream:
                yield stream
            return
        if source.ssh_alias is None:
            raise SourceAccessError("remote source has no SSH alias")
        remote_command = f"cat -- {shlex.quote(str(source.path))}"
        process = subprocess.Popen(
            [*self._ssh_prefix(source.ssh_alias), remote_command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        if (
            process.stdout is None or process.stderr is None
        ):  # pragma: no cover - subprocess invariant
            process.kill()
            raise SourceAccessError("failed to open SSH pipes")
        original_error: BaseException | None = None
        try:
            yield process.stdout
        except BaseException as exc:
            original_error = exc
            process.terminate()
            raise
        finally:
            process.stdout.close()
            stderr = process.stderr.read()
            return_code = process.wait()
            process.stderr.close()
            if original_error is None and return_code != 0:
                raise SourceAccessError(
                    f"SSH source read failed ({source.source_id}, rc={return_code}): "
                    f"{stderr.strip()}"
                )

    def _remote_metadata(self, source: ResolvedSource) -> SourceMetadata:
        if source.ssh_alias is None:
            raise SourceAccessError("remote source has no SSH alias")
        quoted = shlex.quote(str(source.path))
        command = f"stat -c '%s' -- {quoted} && sha256sum -- {quoted}"
        completed = subprocess.run(
            [*self._ssh_prefix(source.ssh_alias), command],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if completed.returncode != 0:
            raise SourceAccessError(
                f"SSH metadata failed ({source.source_id}, rc={completed.returncode}): "
                f"{completed.stderr.strip()}"
            )
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if len(lines) != 2:
            raise SourceAccessError(f"unexpected metadata response for {source.source_id}: {lines}")
        try:
            size = int(lines[0])
        except ValueError as exc:
            raise SourceAccessError(
                f"invalid remote size for {source.source_id}: {lines[0]}"
            ) from exc
        digest = lines[1].split(maxsplit=1)[0]
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise SourceAccessError(f"invalid remote SHA256 for {source.source_id}: {digest}")
        return SourceMetadata(
            source_id=source.source_id,
            sha256=digest,
            size_bytes=size,
            transport="ssh-readonly",
        )

    @staticmethod
    def _ssh_prefix(alias: str) -> list[str]:
        """Return the non-interactive read-only SSH command prefix."""

        return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", alias]
