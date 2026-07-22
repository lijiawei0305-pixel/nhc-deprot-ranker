"""Typed YAML configuration for legacy source discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class StrictModel(BaseModel):
    """Forbid unreviewed configuration keys."""

    model_config = ConfigDict(extra="forbid")


class LegacyRepoConfig(StrictModel):
    """Local legacy source-code checkout metadata."""

    root: Path
    expected_remote: str
    expected_commit: str | None = None


class SourceAccessConfig(StrictModel):
    """Read-only source transport."""

    mode: Literal["local", "ssh"] = "local"
    ssh_alias: str | None = None
    remote_root: Path | None = None
    read_only: bool = True

    @model_validator(mode="after")
    def validate_access(self) -> SourceAccessConfig:
        """Require explicit SSH coordinates and prohibit writable legacy access."""

        if not self.read_only:
            raise ValueError("legacy source access must remain read_only")
        if self.mode == "ssh" and (not self.ssh_alias or self.remote_root is None):
            raise ValueError("ssh mode requires ssh_alias and remote_root")
        return self


class LocatedPath(StrictModel):
    """A source path anchored at the local legacy or remote root."""

    location: Literal["legacy_repo", "remote_root"]
    path: Path

    @field_validator("path")
    @classmethod
    def require_relative_path(cls, value: Path) -> Path:
        """Keep portable source paths relative to their declared root."""

        if value.is_absolute() or ".." in value.parts:
            raise ValueError("located source path must be a safe relative path")
        return value


class CandidateSources(StrictModel):
    """Legacy candidate inputs."""

    xtb_crude_csv: LocatedPath
    xtb_reduced_csv: LocatedPath
    v3_graph_csv: LocatedPath
    v4_new_only_csv: LocatedPath
    descriptors_parquet: LocatedPath


class LabelSource(LocatedPath):
    """One traceable high-fidelity source."""

    source_group: Literal["gold", "blind_round1", "blind_round2"]
    type: Literal["electronic_energy"]


class LabelSources(StrictModel):
    """Configured high-fidelity label inputs."""

    sources: list[LabelSource]

    @field_validator("sources")
    @classmethod
    def unique_source_groups(cls, value: list[LabelSource]) -> list[LabelSource]:
        """Reject ambiguous repeated group declarations."""

        groups = [source.source_group for source in value]
        if len(groups) != len(set(groups)):
            raise ValueError("label source_group values must be unique")
        return value


class LegacyConfig(StrictModel):
    """Top-level Phase 0 legacy configuration."""

    legacy_repo: LegacyRepoConfig
    source_access: SourceAccessConfig
    candidates: CandidateSources
    labels: LabelSources


def load_legacy_config(path: Path) -> LegacyConfig:
    """Load and validate a legacy YAML configuration."""

    if not path.is_file():
        raise FileNotFoundError(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"configuration must contain a YAML mapping: {path}")
    return LegacyConfig.model_validate(raw)
