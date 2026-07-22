"""Fail-closed configuration for the read-only Phase 8A API preflight."""

from __future__ import annotations

import json
import math
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SAFE_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")
_IPV4 = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
_REMOTE_HEREDOC = "__NHC_PHASE8A_READONLY_INSPECTOR__"
_EVIDENCE_TOP_LEVEL = {
    "schema_version",
    "phase",
    "generated_at_utc",
    "status",
    "safety",
    "versions",
    "imports",
    "phase7_integrity",
    "geometric",
    "scf",
    "dispersion",
    "acceptance",
}
_EXPECTED_ACCEPTANCE_CHECKS = {
    "d3_adapter_is_class",
    "d3_adapter_signature_has_required_parameters",
    "d3bj_in_adapter_damping_map",
    "d3bj_in_scf_supported_versions",
    "geometric_kernel_has_required_parameters",
    "geometric_kernel_returns_pair",
    "geometric_optimize_discards_flag",
    "newton_function_is_static_only",
    "phase7_exact_file_count",
    "phase7_registered_tree_matches",
    "phase7_tree_unchanged",
    "public_rks_is_callable",
    "public_rks_signature_has_mol",
    "registered_sources_match",
    "registered_sources_unchanged",
    "rks_implementation_is_scf_subclass",
    "scf_dispersion_aliases_match",
    "scf_static_hooks_callable",
}
_EXPECTED_IMPORTS = {
    "dft",
    "dft_rks_implementation",
    "dftd3_adapter",
    "geometric",
    "geometric_solver",
    "newton_ah",
    "pyscf",
    "scf_dispersion",
    "scf_hf",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PHASE7_CANONICAL_TREE = "9b92a1f453274995661bd262e607239a86f4992bf4cc2809a311207dceadbecb"
_PHASE7_REPORTED_TREE = "644f027e276902dc1ab105f02f08864967f69ae87dc8883f608f5e4d17a372ad"


class Phase8APreflightConfigError(ValueError):
    """The private Phase 8A route is missing or is not strictly read-only."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Phase8AConnectionConfig(_StrictModel):
    """One passwordless campus-direct or loopback-SOCKS route."""

    mode: Literal["campus_direct", "socks5_proxy"]
    ssh_alias: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    proxy_host: Literal["127.0.0.1"] = "127.0.0.1"
    proxy_port: int = Field(default=11080, ge=1, le=65535)


class Phase8ARemoteConfig(_StrictModel):
    """Existing server locations that Phase 8A may only read."""

    project_root: str
    environment_relative: Literal["env/envs/molenv.sh"]
    phase7_run_relative: str

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

    @field_validator("phase7_run_relative")
    @classmethod
    def validate_phase7_run_relative(cls, value: str) -> str:
        relative = PurePosixPath(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("phase7_run_relative must be a safe relative POSIX path")
        if (
            value != relative.as_posix()
            or len(relative.parts) != 3
            or relative.parts[:2] != ("data", "runs")
            or not relative.parts[-1].startswith("nhc_deprot_ranker_phase7_smoke_")
        ):
            raise ValueError("phase7_run_relative must name one Phase 7 smoke root")
        if any(_SAFE_PATH_COMPONENT.fullmatch(part) is None for part in relative.parts):
            raise ValueError("phase7_run_relative contains an unsafe path component")
        return value


class Phase8ASafetyConfig(_StrictModel):
    """Literal safety bits; none can be promoted by a private file."""

    api_preflight_authorized: Literal[True]
    read_only: Literal[True]
    server_write_authorized: Literal[False]
    quantum_execution_authorized: Literal[False]


class Phase8APreflightConfig(_StrictModel):
    """Ignored coordinates for one static, read-only server inspection."""

    schema_version: Literal["phase8a_api_preflight.v1"]
    connection: Phase8AConnectionConfig
    remote: Phase8ARemoteConfig
    safety: Phase8ASafetyConfig

    @model_validator(mode="after")
    def reject_option_like_alias(self) -> Phase8APreflightConfig:
        if self.connection.ssh_alias.startswith("-"):
            raise ValueError("ssh_alias must not be an option")
        return self

    def require_read_only_preflight(self) -> None:
        """Recheck every safety bit immediately before opening SSH."""

        if (
            self.safety.api_preflight_authorized is not True
            or self.safety.read_only is not True
            or self.safety.server_write_authorized is not False
            or self.safety.quantum_execution_authorized is not False
        ):
            raise Phase8APreflightConfigError("Phase 8A is not a read-only API preflight")

    def ssh_options(self) -> tuple[str, ...]:
        """Return fixed passwordless SSH options without invoking a shell locally."""

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


def load_phase8a_preflight_config(path: Path) -> Phase8APreflightConfig:
    """Load an ignored mapping and reject symlinks, scalars and unknown fields."""

    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise Phase8APreflightConfigError("Phase 8A preflight config must be a YAML mapping")
    config = Phase8APreflightConfig.model_validate(raw)
    config.require_read_only_preflight()
    return config


def _strict_json_object(raw: bytes) -> dict[str, object]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Phase8APreflightConfigError("preflight stdout is not UTF-8") from exc

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase8APreflightConfigError(f"duplicate evidence key: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        raise Phase8APreflightConfigError(f"non-finite evidence number: {value}")

    try:
        payload = json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise Phase8APreflightConfigError("preflight stdout is not one strict JSON value") from exc
    if not isinstance(payload, dict):
        raise Phase8APreflightConfigError("preflight evidence must be a JSON object")
    return cast(dict[str, object], payload)


def _walk_evidence_strings(value: object) -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, dict):
        for key, child in value.items():
            strings.append(str(key))
            strings.extend(_walk_evidence_strings(child))
    elif isinstance(value, list):
        for child in value:
            strings.extend(_walk_evidence_strings(child))
    elif isinstance(value, float) and not math.isfinite(value):
        raise Phase8APreflightConfigError("preflight evidence contains a non-finite number")
    return strings


def validate_phase8a_evidence(
    payload: dict[str, object], *, private_values: tuple[str, ...] = ()
) -> None:
    """Validate acceptance and reject private server coordinates in tracked evidence."""

    if set(payload) != _EVIDENCE_TOP_LEVEL:
        raise Phase8APreflightConfigError("preflight evidence fields drifted")
    if (
        payload.get("schema_version") != "phase8a.api_preflight.v1"
        or payload.get("phase") != "8A"
        or payload.get("status") != "passed"
    ):
        raise Phase8APreflightConfigError("preflight did not pass the Phase 8A schema")
    generated_at = payload.get("generated_at_utc")
    if not isinstance(generated_at, str):
        raise Phase8APreflightConfigError("preflight generated_at_utc is invalid")
    try:
        parsed_generated_at = datetime.fromisoformat(generated_at)
    except ValueError as exc:
        raise Phase8APreflightConfigError("preflight generated_at_utc is invalid") from exc
    if parsed_generated_at.tzinfo is None or parsed_generated_at.utcoffset() != UTC.utcoffset(None):
        raise Phase8APreflightConfigError("preflight generated_at_utc must be UTC")
    safety = payload.get("safety")
    expected_safety = {
        "read_only": True,
        "module_imports_only": True,
        "molecule_constructed": False,
        "mean_field_constructed": False,
        "compute_kernel_called": False,
        "optimizer_called": False,
        "dispersion_evaluated": False,
        "hessian_computed": False,
        "server_file_written": False,
    }
    if safety != expected_safety:
        raise Phase8APreflightConfigError("preflight safety declaration drifted")
    acceptance = payload.get("acceptance")
    if (
        not isinstance(acceptance, dict)
        or set(acceptance) != {"checks", "passed"}
        or acceptance.get("passed") is not True
    ):
        raise Phase8APreflightConfigError("preflight acceptance did not pass")
    checks = acceptance.get("checks")
    if (
        not isinstance(checks, dict)
        or set(checks) != _EXPECTED_ACCEPTANCE_CHECKS
        or any(type(value) is not bool or value is not True for value in checks.values())
    ):
        raise Phase8APreflightConfigError("preflight acceptance check set or values drifted")
    versions = payload.get("versions")
    if not isinstance(versions, dict) or any(
        not isinstance(versions.get(name), str) or not versions[name]
        for name in ("python", "pyscf", "geometric", "pyscf_dispersion")
    ):
        raise Phase8APreflightConfigError("preflight versions are incomplete")
    if set(versions) != {"python", "pyscf", "geometric", "pyscf_dispersion"}:
        raise Phase8APreflightConfigError("preflight version fields drifted")
    imports = payload.get("imports")
    if (
        not isinstance(imports, dict)
        or set(imports) != _EXPECTED_IMPORTS
        or any(value is not True for value in imports.values())
    ):
        raise Phase8APreflightConfigError("preflight import evidence drifted")
    integrity = payload.get("phase7_integrity")
    expected_integrity = {
        "before_after_match": True,
        "canonical_tree_sha256": _PHASE7_CANONICAL_TREE,
        "registered_file_count": 27,
        "registered_sources_before_after_match": True,
        "registered_sources_match": True,
        "reported_phase7_tree_sha256": _PHASE7_REPORTED_TREE,
    }
    if integrity != expected_integrity:
        raise Phase8APreflightConfigError("Phase 7 integrity evidence drifted")
    geometric = payload.get("geometric")
    if not isinstance(geometric, dict) or set(geometric) != {
        "kernel_returns_convergence_pair",
        "kernel_signature",
        "kernel_source_sha256",
        "optimize_discards_convergence_flag",
        "optimize_signature",
        "optimize_source_sha256",
    }:
        raise Phase8APreflightConfigError("geomeTRIC evidence fields drifted")
    if (
        geometric["kernel_returns_convergence_pair"] is not True
        or geometric["optimize_discards_convergence_flag"] is not True
        or not isinstance(geometric["kernel_signature"], str)
        or "assert_convergence" not in geometric["kernel_signature"]
        or "maxsteps=100" not in geometric["kernel_signature"]
        or not isinstance(geometric["optimize_signature"], str)
        or not isinstance(geometric["kernel_source_sha256"], str)
        or _SHA256.fullmatch(geometric["kernel_source_sha256"]) is None
        or not isinstance(geometric["optimize_source_sha256"], str)
        or _SHA256.fullmatch(geometric["optimize_source_sha256"]) is None
    ):
        raise Phase8APreflightConfigError("geomeTRIC evidence values drifted")
    scf = payload.get("scf")
    if not isinstance(scf, dict) or set(scf) != {
        "do_disp_alias_matches",
        "do_disp_signature",
        "get_dispersion_alias_matches",
        "get_dispersion_signature",
        "newton_function_signature",
        "newton_signature",
        "public_rks_is_callable",
        "public_rks_signature",
        "rks_implementation_is_scf_subclass",
    }:
        raise Phase8APreflightConfigError("SCF evidence fields drifted")
    if (
        scf["do_disp_alias_matches"] is not True
        or scf["get_dispersion_alias_matches"] is not True
        or scf["public_rks_is_callable"] is not True
        or scf["rks_implementation_is_scf_subclass"] is not True
        or any(
            not isinstance(scf[name], str) or not scf[name]
            for name in (
                "do_disp_signature",
                "get_dispersion_signature",
                "newton_function_signature",
                "newton_signature",
                "public_rks_signature",
            )
        )
        or "mol" not in scf["public_rks_signature"]
    ):
        raise Phase8APreflightConfigError("SCF evidence values drifted")
    dispersion = payload.get("dispersion")
    if not isinstance(dispersion, dict) or set(dispersion) != {
        "adapter_class",
        "adapter_damping_keys",
        "adapter_init_signature",
        "adapter_source_sha256",
        "d3bj_supported",
        "supported_versions",
    }:
        raise Phase8APreflightConfigError("dispersion evidence fields drifted")
    supported_versions = dispersion["supported_versions"]
    damping_keys = dispersion["adapter_damping_keys"]
    if (
        dispersion["adapter_class"] != "pyscf.dispersion.dftd3.DFTD3Dispersion"
        or dispersion["d3bj_supported"] is not True
        or not isinstance(supported_versions, list)
        or "d3bj" not in supported_versions
        or not isinstance(damping_keys, list)
        or "d3bj" not in damping_keys
        or not isinstance(dispersion["adapter_init_signature"], str)
        or not all(
            name in dispersion["adapter_init_signature"] for name in ("mol", "xc", "version='d3bj'")
        )
        or not isinstance(dispersion["adapter_source_sha256"], str)
        or _SHA256.fullmatch(dispersion["adapter_source_sha256"]) is None
    ):
        raise Phase8APreflightConfigError("dispersion evidence values drifted")
    strings = _walk_evidence_strings(payload)
    sensitive = tuple(value for value in private_values if value)
    for value in strings:
        if any(secret in value for secret in sensitive):
            raise Phase8APreflightConfigError("preflight evidence contains a private coordinate")
        if _IPV4.search(value) or "/Users/" in value or "/home/" in value or "@" in value:
            raise Phase8APreflightConfigError("preflight evidence contains a host-like coordinate")


def _portable_failed_checks(
    raw: bytes, *, private_values: tuple[str, ...]
) -> tuple[str, ...] | None:
    """Extract only safe logical check names from a failed remote JSON object."""

    try:
        payload = _strict_json_object(raw)
    except Phase8APreflightConfigError:
        return None
    if (
        payload.get("schema_version") != "phase8a.api_preflight.v1"
        or payload.get("phase") != "8A"
        or set(payload) != _EVIDENCE_TOP_LEVEL
    ):
        return None
    sensitive = tuple(value for value in private_values if value)
    for value in _walk_evidence_strings(payload):
        if (
            any(secret in value for secret in sensitive)
            or _IPV4.search(value)
            or "/Users/" in value
            or "/home/" in value
            or "@" in value
        ):
            return None
    acceptance = payload.get("acceptance")
    if not isinstance(acceptance, dict):
        return None
    checks = acceptance.get("checks")
    if not isinstance(checks, dict) or any(type(value) is not bool for value in checks.values()):
        return None
    failed = tuple(
        sorted(
            key
            for key, value in checks.items()
            if isinstance(key, str)
            and re.fullmatch(r"[a-z0-9_]+", key) is not None
            and value is False
        )
    )
    return failed or None


def _remote_wrapper(inspector_source: bytes) -> bytes:
    try:
        source = inspector_source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Phase8APreflightConfigError("inspector source is not UTF-8") from exc
    if _REMOTE_HEREDOC in source:
        raise Phase8APreflightConfigError("inspector source collides with its heredoc marker")
    wrapper = f"""set -euo pipefail
project_root=$1
environment_relative=$2
phase7_run_relative=$3
cd -- "$project_root"
test -f "$environment_relative"
test -d "$phase7_run_relative"
set +u
source "$environment_relative" >/dev/null 2>&1
set -u
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
python -B - "$phase7_run_relative" <<'{_REMOTE_HEREDOC}'
{source}
{_REMOTE_HEREDOC}
"""
    return wrapper.encode("utf-8")


def run_phase8a_preflight(
    *,
    config_path: Path,
    inspector_path: Path,
    timeout_seconds: float = 120.0,
) -> dict[str, object]:
    """Run the one synchronous SSH inspection and return portable evidence only."""

    config = load_phase8a_preflight_config(config_path)
    config.require_read_only_preflight()
    if not inspector_path.is_file() or inspector_path.is_symlink():
        raise FileNotFoundError(inspector_path)
    argv = (
        "ssh",
        *config.ssh_options(),
        config.connection.ssh_alias,
        "bash",
        "-s",
        "--",
        config.remote.project_root,
        config.remote.environment_relative,
        config.remote.phase7_run_relative,
    )
    try:
        completed = subprocess.run(
            argv,
            input=_remote_wrapper(inspector_path.read_bytes()),
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise Phase8APreflightConfigError("read-only SSH preflight timed out") from exc
    if completed.returncode != 0:
        failed_checks = _portable_failed_checks(
            completed.stdout,
            private_values=(
                config.connection.ssh_alias,
                config.remote.project_root,
                config.remote.phase7_run_relative,
            ),
        )
        if failed_checks is not None:
            names = ", ".join(failed_checks)
            raise Phase8APreflightConfigError(f"read-only SSH preflight failed checks: {names}")
        raise Phase8APreflightConfigError(
            f"read-only SSH preflight failed with exit code {completed.returncode}"
        )
    payload = _strict_json_object(completed.stdout)
    validate_phase8a_evidence(
        payload,
        private_values=(
            config.connection.ssh_alias,
            config.remote.project_root,
            config.remote.phase7_run_relative,
        ),
    )
    return payload
