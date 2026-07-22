"""Resolve configured paths without hard-coded legacy roots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nhc_deprot_ranker.config import LegacyConfig, LocatedPath


@dataclass(frozen=True)
class ResolvedSource:
    """A local path or a read-only remote path."""

    location: str
    path: Path
    is_remote: bool
    ssh_alias: str | None = None

    def display(self) -> str:
        """Return a stable user-facing source identifier."""

        return f"ssh://{self.ssh_alias}{self.path}" if self.is_remote else str(self.path)


def resolve_source(config: LegacyConfig, source: LocatedPath) -> ResolvedSource:
    """Resolve a safe relative source path against its configured root."""

    if source.location == "legacy_repo":
        return ResolvedSource(
            location=source.location,
            path=config.legacy_repo.root / source.path,
            is_remote=False,
        )
    if config.source_access.mode != "ssh":
        raise ValueError("remote_root source requires source_access.mode=ssh")
    if config.source_access.remote_root is None or config.source_access.ssh_alias is None:
        raise ValueError("remote source configuration is incomplete")
    return ResolvedSource(
        location=source.location,
        path=config.source_access.remote_root / source.path,
        is_remote=True,
        ssh_alias=config.source_access.ssh_alias,
    )
