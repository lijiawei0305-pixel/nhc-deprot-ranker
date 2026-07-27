"""Public stable interpreter identities and private host-local realizations."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from nhc_deprot_ranker.quantum.phase9b_campaign_schemas import (
    CampaignSchemaError,
    canonical_json_bytes,
    require_id,
    require_sha256,
)

INTERPRETER_STABLE_SCHEMA_VERSION: Final = "nhc-phase9b-interpreter-stable-identity-v1"
INTERPRETER_PRIVATE_SCHEMA_VERSION: Final = "nhc-phase9b-interpreter-private-binding-v1"


@dataclass(frozen=True, slots=True)
class InterpreterProfileStableIdentityV1:
    """Portable identity allowed in requests, manifests, and permit schemas."""

    logical_profile_id: str
    python_version: str
    package_versions: tuple[tuple[str, str], ...]
    executable_content_sha256: str
    activation_script_sha256: str
    runtime_capabilities: tuple[str, ...]
    sanitized_environment_identity_sha256: str

    def __post_init__(self) -> None:
        require_id(self.logical_profile_id, "logical_profile_id")
        if self.python_version != "3.11.15":
            raise CampaignSchemaError("Phase 9B interpreter Python must be 3.11.15")
        if (
            not self.package_versions
            or tuple(sorted(self.package_versions)) != self.package_versions
        ):
            raise CampaignSchemaError("package versions must be a non-empty sorted tuple")
        if len({name for name, _ in self.package_versions}) != len(self.package_versions):
            raise CampaignSchemaError("package version names must be unique")
        for name, version in self.package_versions:
            require_id(name, "package name")
            if not version or len(version) > 64:
                raise CampaignSchemaError("package version is invalid")
        for label, value in (
            ("executable_content_sha256", self.executable_content_sha256),
            ("activation_script_sha256", self.activation_script_sha256),
            ("sanitized_environment_identity_sha256", self.sanitized_environment_identity_sha256),
        ):
            require_sha256(value, label)
        if (
            not self.runtime_capabilities
            or tuple(sorted(set(self.runtime_capabilities))) != self.runtime_capabilities
        ):
            raise CampaignSchemaError("runtime capabilities must be unique and sorted")

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": INTERPRETER_STABLE_SCHEMA_VERSION,
            "logical_profile_id": self.logical_profile_id,
            "python_version": self.python_version,
            "package_versions": dict(self.package_versions),
            "executable_content_sha256": self.executable_content_sha256,
            "activation_script_sha256": self.activation_script_sha256,
            "runtime_capabilities": list(self.runtime_capabilities),
            "sanitized_environment_identity_sha256": self.sanitized_environment_identity_sha256,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_payload())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class InterpreterProfilePrivateBindingV1:
    """Host-local path/inode realization; forbidden from public Git payloads."""

    stable_profile_sha256: str
    prefix: Path
    executable: Path
    executable_device: int
    executable_inode: int
    executable_content_sha256: str
    host_execution_identity_sha256: str

    def __post_init__(self) -> None:
        for label, value in (
            ("stable_profile_sha256", self.stable_profile_sha256),
            ("executable_content_sha256", self.executable_content_sha256),
            ("host_execution_identity_sha256", self.host_execution_identity_sha256),
        ):
            require_sha256(value, label)
        if not self.prefix.is_absolute() or not self.executable.is_absolute():
            raise CampaignSchemaError("private interpreter binding paths must be absolute")
        try:
            self.executable.relative_to(self.prefix)
        except ValueError as exc:
            raise CampaignSchemaError("private executable must remain inside its prefix") from exc
        if self.executable_device < 0 or self.executable_inode <= 0:
            raise CampaignSchemaError("private executable device/inode is invalid")

    def private_payload(self) -> dict[str, object]:
        return {
            "schema_version": INTERPRETER_PRIVATE_SCHEMA_VERSION,
            "stable_profile_sha256": self.stable_profile_sha256,
            "prefix": os.fspath(self.prefix),
            "executable": os.fspath(self.executable),
            "executable_device": self.executable_device,
            "executable_inode": self.executable_inode,
            "executable_content_sha256": self.executable_content_sha256,
            "host_execution_identity_sha256": self.host_execution_identity_sha256,
        }

    def sha256(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.private_payload())).hexdigest()


ProfileRole = Literal["a1_mlff", "direct_and_a2_gpupyscf"]


def _registered_digest(label: str) -> str:
    """Opaque portable expectation; private preflight must realize it exactly."""

    return hashlib.sha256(label.encode("ascii")).hexdigest()


MLFF_STABLE_PROFILE: Final = InterpreterProfileStableIdentityV1(
    logical_profile_id="phase9b-mlff-stable-v1",
    python_version="3.11.15",
    package_versions=(
        ("aimnet", "0.2.0"),
        ("ase", "3.29.0"),
        ("torch-runtime", "2.8.0+cu128"),
    ),
    # The stable generation freezes an opaque content expectation.  Its private
    # host binding remains absent in public Git and must prove the same digest
    # during a separately authorized real preflight.
    executable_content_sha256=_registered_digest("phase9b-mlff-python-3.11.15-content-v1"),
    activation_script_sha256="9a8ae2b2fff81b317ef2569af51f9fa374b071551dfa4cb3e2948fe598e437b6",
    runtime_capabilities=("cuda-12.8", "sm_70"),
    sanitized_environment_identity_sha256=_registered_digest(
        "phase9b-project-mlff-sanitized-environment-v1"
    ),
)

GPUPYSCF_STABLE_PROFILE: Final = InterpreterProfileStableIdentityV1(
    logical_profile_id="phase9b-gpupyscf-stable-v1",
    python_version="3.11.15",
    package_versions=(
        ("geometric", "1.1.1"),
        ("pyscf", "2.13.1"),
        ("pyscf-dispersion", "1.5.0"),
    ),
    executable_content_sha256=_registered_digest("phase9b-gpupyscf-python-3.11.15-content-v1"),
    activation_script_sha256=_registered_digest(
        "phase9b-gpupyscf-direct-executable-no-activation-v1"
    ),
    runtime_capabilities=("d3bj", "pyscf-residual-optimization"),
    sanitized_environment_identity_sha256=_registered_digest(
        "phase9b-project-gpupyscf-sanitized-environment-v1"
    ),
)


def validate_private_binding(
    stable: InterpreterProfileStableIdentityV1,
    private: InterpreterProfilePrivateBindingV1,
    *,
    stat_result: os.stat_result | None = None,
) -> None:
    """Prove one private absolute path realizes one portable stable profile."""

    if private.stable_profile_sha256 != stable.sha256():
        raise CampaignSchemaError("private binding refers to another stable profile")
    if private.executable_content_sha256 != stable.executable_content_sha256:
        raise CampaignSchemaError("private executable content differs from stable identity")
    observed = stat_result if stat_result is not None else private.executable.stat()
    if not private.executable.is_file() or not os.access(private.executable, os.X_OK):
        raise CampaignSchemaError("private interpreter executable is not regular/executable")
    if observed.st_dev != private.executable_device or observed.st_ino != private.executable_inode:
        raise CampaignSchemaError("private interpreter device/inode drifted")


def ensure_role_compatibility(
    role: ProfileRole, profile: InterpreterProfileStableIdentityV1
) -> None:
    packages = dict(profile.package_versions)
    if role == "a1_mlff":
        expected = {"aimnet": "0.2.0", "ase": "3.29.0", "torch-runtime": "2.8.0+cu128"}
        capabilities = {"cuda-12.8", "sm_70"}
    else:
        expected = {"geometric": "1.1.1", "pyscf": "2.13.1", "pyscf-dispersion": "1.5.0"}
        capabilities = {"d3bj", "pyscf-residual-optimization"}
    if any(packages.get(name) != version for name, version in expected.items()):
        raise CampaignSchemaError(f"{role} package projection drifted")
    if not capabilities.issubset(profile.runtime_capabilities):
        raise CampaignSchemaError(f"{role} runtime capabilities drifted")


__all__ = [
    "GPUPYSCF_STABLE_PROFILE",
    "INTERPRETER_PRIVATE_SCHEMA_VERSION",
    "INTERPRETER_STABLE_SCHEMA_VERSION",
    "MLFF_STABLE_PROFILE",
    "InterpreterProfilePrivateBindingV1",
    "InterpreterProfileStableIdentityV1",
    "ProfileRole",
    "ensure_role_compatibility",
    "validate_private_binding",
]
