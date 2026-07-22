"""Strict private routing policy for the single Phase 8B DFT smoke.

This module contains no deployment or chemistry entry point.  A route file can
authorize creation of the one fixed remote root, but it can never authorize a
quantum worker: that authority belongs only to the path-bound, consumable
Phase 8B permit.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PHASE8B_RUN_RELATIVE = "data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001"
PHASE8B_ENVIRONMENT_RELATIVE = "env/envs/molenv.sh"
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


class Phase8BRemoteConfigError(ValueError):
    """The ignored Phase 8B route is missing, unsafe, or over-authorized."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Phase8BConnectionConfig(_StrictModel):
    """One explicit campus-direct or loopback-SOCKS route."""

    mode: Literal["campus_direct", "socks5_proxy"]
    ssh_alias: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    proxy_host: Literal["127.0.0.1"] = "127.0.0.1"
    proxy_port: int = Field(default=11080, ge=1, le=65535)


def _normalized_absolute_root(value: str) -> str:
    root = PurePosixPath(value)
    if not root.is_absolute() or root == PurePosixPath("/") or ".." in root.parts:
        raise ValueError("project_root must be a specific absolute POSIX path")
    if root.as_posix() != value:
        raise ValueError("project_root must be normalized")
    if any(_SAFE_COMPONENT.fullmatch(part) is None for part in root.parts[1:]):
        raise ValueError("project_root contains an unsafe component")
    return value


def _normalized_phase7_relative(value: str) -> str:
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != value
        or len(relative.parts) != 3
        or relative.parts[:2] != ("data", "runs")
        or not relative.parts[-1].startswith("nhc_deprot_ranker_phase7_smoke_")
    ):
        raise ValueError("phase7_run_relative must identify the registered Phase 7 run")
    if any(_SAFE_COMPONENT.fullmatch(part) is None for part in relative.parts):
        raise ValueError("phase7_run_relative contains an unsafe component")
    return value


class Phase8BRemoteRootConfig(_StrictModel):
    """The established project and two immutable run identities."""

    project_root: str
    environment_relative: Literal["env/envs/molenv.sh"]
    phase7_run_relative: str
    phase8b_run_relative: Literal["data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001"]
    require_new_phase8b_root: Literal[True]

    @field_validator("project_root")
    @classmethod
    def validate_project_root(cls, value: str) -> str:
        return _normalized_absolute_root(value)

    @field_validator("phase7_run_relative")
    @classmethod
    def validate_phase7_run_relative(cls, value: str) -> str:
        return _normalized_phase7_relative(value)

    @property
    def phase7_root(self) -> str:
        return (PurePosixPath(self.project_root) / self.phase7_run_relative).as_posix()

    @property
    def phase8b_root(self) -> str:
        return (PurePosixPath(self.project_root) / self.phase8b_run_relative).as_posix()


class Phase8BTransferPolicy(_StrictModel):
    """Broad or destructive synchronization is never accepted."""

    directed_files_only: Literal[True]
    recursive_copy: Literal[False]
    delete: Literal[False]
    overwrite: Literal[False]


class Phase8BSafetyPolicy(_StrictModel):
    """Route-level bits deliberately cannot authorize quantum execution."""

    read_only_preflight_authorized: Literal[True]
    server_write_authorized: bool
    quantum_execution_authorized: Literal[False]
    consumed_private_permit_required: Literal[True]
    scheduler_submission_authorized: Literal[False]
    second_attempt_authorized: Literal[False]


class Phase8BRemoteConfig(_StrictModel):
    """Ignored coordinates and non-quantum transfer authority."""

    schema_version: Literal["phase8b_remote.v1"]
    connection: Phase8BConnectionConfig
    remote: Phase8BRemoteRootConfig
    transfer: Phase8BTransferPolicy
    safety: Phase8BSafetyPolicy

    @model_validator(mode="after")
    def validate_closed_execution_route(self) -> Phase8BRemoteConfig:
        if self.connection.ssh_alias.startswith("-"):
            raise ValueError("ssh_alias must not look like an option")
        if self.safety.quantum_execution_authorized is not False:
            raise ValueError("the route must never authorize quantum execution")
        return self

    def require_read_only_preflight(self) -> None:
        """Recheck the read-only gate immediately before opening SSH."""

        if self.safety.read_only_preflight_authorized is not True:
            raise Phase8BRemoteConfigError("Phase 8B read-only preflight is not authorized")

    def require_directed_write(self) -> None:
        """Require the separate private bit before mkdir or file transfer."""

        if self.safety.server_write_authorized is not True:
            raise Phase8BRemoteConfigError("Phase 8B server write is not authorized")
        if (
            self.transfer.directed_files_only is not True
            or self.transfer.recursive_copy is not False
            or self.transfer.delete is not False
            or self.transfer.overwrite is not False
        ):
            raise Phase8BRemoteConfigError("Phase 8B transfer policy is unsafe")

    def ssh_options(self) -> tuple[str, ...]:
        """Return fixed passwordless SSH options without invoking a shell."""

        common = (
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "ConnectTimeout=15",
        )
        if self.connection.mode == "campus_direct":
            return common
        proxy = (
            f"ProxyCommand=nc -x {self.connection.proxy_host}:"
            f"{self.connection.proxy_port} -X 5 %h %p"
        )
        return (*common, "-o", proxy)


def load_phase8b_remote_config(path: Path) -> Phase8BRemoteConfig:
    """Load one ignored mapping and reject symlinks, scalars, and extras."""

    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise Phase8BRemoteConfigError("Phase 8B remote config must be a YAML mapping")
    return Phase8BRemoteConfig.model_validate(raw)


__all__ = [
    "PHASE8B_ENVIRONMENT_RELATIVE",
    "PHASE8B_RUN_RELATIVE",
    "Phase8BRemoteConfig",
    "Phase8BRemoteConfigError",
    "load_phase8b_remote_config",
]
