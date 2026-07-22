"""Private Phase 7 HPC coordinates with fail-closed transfer policy."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SAFE_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


class Phase7RemoteConfigError(ValueError):
    """The private Phase 7 remote policy is missing or unsafe."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Phase7ConnectionConfig(_StrictModel):
    """One explicitly selected campus-direct or local-SOCKS route."""

    mode: Literal["campus_direct", "socks5_proxy"]
    ssh_alias: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    proxy_host: Literal["127.0.0.1"] = "127.0.0.1"
    proxy_port: int = Field(default=11080, ge=1, le=65535)


class Phase7RemoteRootConfig(_StrictModel):
    """Immutable run directory below the established HPC project root."""

    project_root: str
    run_relative: str
    require_new_run_root: Literal[True]

    @field_validator("project_root")
    @classmethod
    def validate_project_root(cls, value: str) -> str:
        root = PurePosixPath(value)
        if not root.is_absolute() or root == PurePosixPath("/") or ".." in root.parts:
            raise ValueError("project_root must be a specific absolute POSIX path")
        if value != root.as_posix():
            raise ValueError("project_root must be normalized")
        if any(_SAFE_PATH_COMPONENT.fullmatch(part) is None for part in root.parts[1:]):
            raise ValueError("project_root contains an unsafe path component")
        return value

    @field_validator("run_relative")
    @classmethod
    def validate_run_relative(cls, value: str) -> str:
        relative = PurePosixPath(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("run_relative must be a safe relative POSIX path")
        if value != relative.as_posix() or relative.parts[:2] != ("data", "runs"):
            raise ValueError("run_relative must be normalized below data/runs")
        if len(relative.parts) != 3 or not relative.parts[-1].startswith(
            "nhc_deprot_ranker_phase7_smoke_"
        ):
            raise ValueError("run_relative must name one versioned Phase 7 smoke root")
        if any(_SAFE_PATH_COMPONENT.fullmatch(part) is None for part in relative.parts):
            raise ValueError("run_relative contains an unsafe path component")
        return value

    @property
    def run_root(self) -> str:
        return (PurePosixPath(self.project_root) / self.run_relative).as_posix()


class Phase7TransferConfig(_StrictModel):
    """Destructive or broad synchronization is never valid in Phase 7."""

    delete: Literal[False]
    directed_files_only: Literal[True]


class Phase7RemoteConfig(_StrictModel):
    """Ignored local coordinates and authorization for the M2-only smoke."""

    schema_version: Literal["phase7_remote.v1"]
    connection: Phase7ConnectionConfig
    remote: Phase7RemoteRootConfig
    transfer: Phase7TransferConfig
    server_write_authorized: bool
    dft_execution_authorized: Literal[False]

    @model_validator(mode="after")
    def reject_alias_that_looks_like_an_option(self) -> Phase7RemoteConfig:
        if self.connection.ssh_alias.startswith("-"):
            raise ValueError("ssh_alias must not be an option")
        return self

    def require_geometry_write_authorization(self) -> None:
        """Require the explicit private bit before any remote mkdir or transfer."""

        if not self.server_write_authorized:
            raise Phase7RemoteConfigError("Phase 7 server write is not authorized")

    def ssh_options(self) -> tuple[str, ...]:
        """Return fixed SSH options without invoking a shell."""

        common = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=15")
        if self.connection.mode == "campus_direct":
            return common
        proxy = (
            f"ProxyCommand=nc -x {self.connection.proxy_host}:"
            f"{self.connection.proxy_port} -X 5 %h %p"
        )
        return (*common, "-o", proxy)


def load_phase7_remote_config(path: Path) -> Phase7RemoteConfig:
    """Load the ignored Phase 7 coordinates without accepting scalar YAML."""

    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise Phase7RemoteConfigError("Phase 7 remote config must be a YAML mapping")
    return Phase7RemoteConfig.model_validate(raw)
