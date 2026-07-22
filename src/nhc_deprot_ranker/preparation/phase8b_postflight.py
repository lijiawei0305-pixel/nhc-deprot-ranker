"""Read-only terminal readback for the one frozen Phase 8B smoke.

The remote inspector is streamed over SSH and uses only the standard library.
This module validates its bounded, path-free summary a second time before that
summary can be retained as portable evidence.  Neither layer writes remotely
or imports a chemistry package.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Final, Protocol, cast

from nhc_deprot_ranker.preparation.phase8b_remote import (
    Phase8BRemoteConfig,
    load_phase8b_remote_config,
)

POSTFLIGHT_SCHEMA_VERSION: Final = "phase8b.remote-postflight.v1"
PORTABLE_POSTFLIGHT_SCHEMA_VERSION: Final = "phase8b.portable-postflight.v1"

_HEREDOC: Final = "__NHC_PHASE8B_POSTFLIGHT_PY__"
_MAX_STDOUT_BYTES: Final = 4 * 1024 * 1024
_MAX_STDERR_BYTES: Final = 64 * 1024
_MAX_INSPECTOR_BYTES: Final = 4 * 1024 * 1024
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
_WORKER_SCRATCH_RE: Final = re.compile(
    r"(?:\.worker-|\.tmp-)attempt-phase8b-qxh-v001-[A-Za-z0-9_.-]+"
)
_FROZEN_INSPECTOR_PATH: Final = (
    Path(__file__).resolve(strict=True).parents[3] / "scripts/phase8b_remote_postflight.py"
)
_FROZEN_INSPECTOR_SHA256: Final = "2c5262b4c52aaf62efd4cfc39d6fbb0dcbd18d063d4e20dd2f657802c9f68cef"

_FROZEN_IDENTITY: Final[dict[str, object]] = {
    "inchikey": "QXHIEGFUWOLQIJ-UHFFFAOYSA-N",
    "request_id": "phase8b-qxh-smoke-v001",
    "attempt_id": "attempt-phase8b-qxh-v001",
}
_FROZEN_RESOURCES: Final[dict[str, object]] = {
    "worker_count": 1,
    "computational_threads": 4,
    "cpu_affinity": "0-3",
    "pyscf_max_memory_mb": 12_000,
    "hard_wall_timeout_seconds": 7_200,
    "terminate_grace_seconds": 10,
    "stdout_capture_limit_bytes": 65_536,
    "stderr_capture_limit_bytes": 65_536,
}
_FROZEN_PROTOCOL_SHA256: Final = "266b06e0d49cb6e3067bcfeb6d62f0712852e96768c4205b49fffcb3df52fe92"
_FROZEN_INPUT_SHA256: Final[dict[str, str]] = {
    "cation_xyz": "097f08ab7c3f265efa8ee36c3fd45d72776c9bdcbd3de503baf8fe91561c12aa",
    "neutral_xyz": "e41e87daca3c7a74383364a427d277df5cf8a0aa70bff015c4cf432455f26bd0",
    "endpoint_atom_map": "0cb13e918f2fa88348affb2385d37e01a75d73376118d18aa4c7647ef4982152",
    "legacy_atom_map": "7766fad207561b79ac8e7278b70eb07c37dcf31d4114b76ad9a9383b235681f8",
}
_GEOMETRY_VALIDATION_SHA256: Final = (
    "35e99683a32e416752014c6e1ecb8121e2bc06d5407911435e5c1250fd639f90"
)
_CLAIM_REQUIRED_OUTCOMES: Final = frozenset(
    {"clean", "worker_guard_failed", "supervisor_nonzero", "cleanup_failed"}
)
_EXPECTED_PHASE7: Final[dict[str, object]] = {
    "file_count": 27,
    "tree_sha256": "9b92a1f453274995661bd262e607239a86f4992bf4cc2809a311207dceadbecb",
}
_EXPECTED_PROJECT_SOURCES: Final[dict[str, str]] = {
    "env/envs/molenv.sh": "e9b3e124f53a10e84c43cfc71a56af3ddd56a86f082610593d2b23ed9692ea6f",
    "scripts/mol/gen_3d.py": "d23c7ad9a6e35948949f6485b53caafb0f3f5705148f642e3a4a30fb589a946a",
    "scripts/mol/structure_gen.py": (
        "a50b50b9967ac9e8203b398fe69f3daebf40a144f37dae8e0aa086e613ad1365"
    ),
}
_EXPECTED_CHECKS: Final[frozenset[str]] = frozenset(
    {
        "permit_ready_absent",
        "permit_consumed_matches",
        "transport_inventory_matches",
        "static_payload_matches",
        "registered_directories_match",
        "phase7_tree_matches",
        "phase7_unchanged",
        "project_sources_match",
        "project_sources_unchanged",
        "receipt_valid",
        "registration_chain_valid",
        "compute_claim_valid",
        "registered_identities_absent",
        "registered_process_groups_absent",
        "single_attempt_only",
        "dynamic_tree_allowed",
        "forbidden_artifacts_absent",
        "terminal_state_valid",
    }
)
_THREAD_ENVIRONMENT: Final[dict[str, str]] = {
    "BLIS_NUM_THREADS": "4",
    "GOTO_NUM_THREADS": "4",
    "MKL_DYNAMIC": "FALSE",
    "MKL_NUM_THREADS": "4",
    "NUMEXPR_NUM_THREADS": "4",
    "OMP_DYNAMIC": "FALSE",
    "OMP_MAX_ACTIVE_LEVELS": "1",
    "OMP_NESTED": "FALSE",
    "OMP_NUM_THREADS": "4",
    "OMP_THREAD_LIMIT": "4",
    "OMP_WAIT_POLICY": "PASSIVE",
    "OPENBLAS_NUM_THREADS": "4",
    "VECLIB_MAXIMUM_THREADS": "4",
}


class Phase8BPostflightError(RuntimeError):
    """Terminal state could not be proved without ambiguity."""


class _CompletedProcessLike(Protocol):
    returncode: int
    stdout: bytes
    stderr: bytes


RunCommand = Callable[..., _CompletedProcessLike]


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _close_fd(descriptor: int | None) -> None:
    if descriptor is None:
        return
    with suppress(OSError):
        os.close(descriptor)


def _read_frozen_inspector(path: Path) -> bytes:
    """Read the one repository inspector through a stable no-follow FD chain."""

    requested = path.absolute()
    expected = _FROZEN_INSPECTOR_PATH.absolute()
    if requested != expected:
        raise Phase8BPostflightError("postflight inspector path is not the frozen repository path")
    directory_fd: int | None = None
    file_fd: int | None = None
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        directory_fd = os.open("/", directory_flags)
        for component in expected.parent.parts[1:]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            observed_directory = os.fstat(next_fd)
            if not stat.S_ISDIR(observed_directory.st_mode):
                _close_fd(next_fd)
                raise Phase8BPostflightError("postflight inspector parent is unsafe")
            _close_fd(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            expected.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_fd,
        )
        opened = os.fstat(file_fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != 0o644
            or opened.st_size <= 0
            or opened.st_size > _MAX_INSPECTOR_BYTES
        ):
            raise Phase8BPostflightError("postflight inspector filesystem identity is unsafe")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(1024 * 1024, _MAX_INSPECTOR_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_INSPECTOR_BYTES:
                raise Phase8BPostflightError("postflight inspector exceeded its byte bound")
        finished = os.fstat(file_fd)
        current = os.stat(expected.name, dir_fd=directory_fd, follow_symlinks=False)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        identity = tuple(getattr(opened, field) for field in stable_fields)
        if (
            tuple(getattr(finished, field) for field in stable_fields) != identity
            or tuple(getattr(current, field) for field in stable_fields) != identity
        ):
            raise Phase8BPostflightError("postflight inspector changed while being read")
        raw = b"".join(chunks)
        if len(raw) != opened.st_size or _sha256(raw) != _FROZEN_INSPECTOR_SHA256:
            raise Phase8BPostflightError("postflight inspector SHA256 drifted")
        return raw
    except Phase8BPostflightError:
        raise
    except OSError as exc:
        raise Phase8BPostflightError("postflight inspector cannot be opened safely") from exc
    finally:
        _close_fd(file_fd)
        _close_fd(directory_fd)


def _strict_json_object(raw: bytes) -> dict[str, object]:
    if not raw or len(raw) > _MAX_STDOUT_BYTES:
        raise Phase8BPostflightError("postflight stdout size is invalid")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Phase8BPostflightError("postflight stdout is not UTF-8") from exc

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase8BPostflightError(f"duplicate postflight key: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        raise Phase8BPostflightError(f"non-finite postflight value: {value}")

    try:
        payload = json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except Phase8BPostflightError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise Phase8BPostflightError("postflight stdout is not strict JSON") from exc
    if not isinstance(payload, dict):
        raise Phase8BPostflightError("postflight stdout must be one JSON object")
    return cast(dict[str, object], payload)


def _exact_keys(value: Mapping[str, object], expected: set[str], *, label: str) -> None:
    if set(value) != expected:
        raise Phase8BPostflightError(f"{label} fields drifted")


def _object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise Phase8BPostflightError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _sha(value: object, *, label: str, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise Phase8BPostflightError(f"{label} must be a lowercase SHA256")
    return value


def _finite(value: object, *, label: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(cast(float, value)):
        raise Phase8BPostflightError(f"{label} must be finite")
    return float(cast(float, value))


def _validate_process_cleanup(value: object, *, terminal_outcome: str) -> None:
    cleanup = _object(value, label="process_cleanup")
    _exact_keys(
        cleanup,
        {
            "receipt_outcome",
            "registered_identity_count",
            "identity_status",
            "group_status",
            "pid_reuse_observed",
            "all_registered_identities_absent",
            "all_registered_groups_absent",
        },
        label="process_cleanup",
    )
    receipt_outcome = cleanup["receipt_outcome"]
    allowed_outcomes = {
        "clean",
        "permit_consumption_failed",
        "authority_failed",
        "spawn_failed",
        "registration_failed",
        "worker_guard_failed",
        "supervisor_nonzero",
        "cleanup_failed",
        "internal_error",
    }
    if receipt_outcome not in allowed_outcomes:
        raise Phase8BPostflightError("guardian receipt outcome drifted")
    if terminal_outcome == "success" and receipt_outcome != "clean":
        raise Phase8BPostflightError("success lacks a clean guardian receipt")
    if terminal_outcome == "failure" and receipt_outcome == "clean":
        raise Phase8BPostflightError("failure cannot carry a clean guardian receipt")
    count = cleanup["registered_identity_count"]
    identities = _object(cleanup["identity_status"], label="identity_status")
    groups = _object(cleanup["group_status"], label="group_status")
    if type(count) is not int or not 1 <= count <= 3:
        raise Phase8BPostflightError("registered identity count is invalid")
    if set(identities) - {"guardian", "supervisor", "worker"} or len(identities) != count:
        raise Phase8BPostflightError("registered identity roles drifted")
    if set(groups) - {"guardian", "supervisor", "worker"} or not groups:
        raise Phase8BPostflightError("registered process-group roles drifted")
    if any(status not in {"absent", "pid_reused"} for status in identities.values()):
        raise Phase8BPostflightError("registered identity absence is unproved")
    if any(status not in {"absent", "reused_after_receipt"} for status in groups.values()):
        raise Phase8BPostflightError("registered process-group absence is unproved")
    reused = any(status == "pid_reused" for status in identities.values()) or any(
        status == "reused_after_receipt" for status in groups.values()
    )
    if cleanup["pid_reuse_observed"] is not reused:
        raise Phase8BPostflightError("PID reuse summary disagrees")
    if (
        cleanup["all_registered_identities_absent"] is not True
        or cleanup["all_registered_groups_absent"] is not True
    ):
        raise Phase8BPostflightError("process cleanup was not proved")


def _validate_runtime(value: object, *, terminal_outcome: str) -> None:
    runtime = _object(value, label="runtime")
    _exact_keys(
        runtime,
        {
            "guardian_receipt_sha256",
            "worker_registration_sha256",
            "guardian_acknowledgement_sha256",
            "compute_claim_sha256",
            "final_success_sha256",
            "final_marker_sha256",
            "provisional_success_sha256",
            "provisional_marker_sha256",
            "result_sha256",
            "failure_sha256",
        },
        label="runtime",
    )
    _sha(runtime["guardian_receipt_sha256"], label="guardian receipt SHA256")
    for name in (
        "worker_registration_sha256",
        "guardian_acknowledgement_sha256",
        "compute_claim_sha256",
        "final_success_sha256",
        "final_marker_sha256",
        "provisional_success_sha256",
        "provisional_marker_sha256",
        "result_sha256",
        "failure_sha256",
    ):
        _sha(runtime[name], label=name, nullable=True)
    if terminal_outcome == "success":
        required = (
            "worker_registration_sha256",
            "guardian_acknowledgement_sha256",
            "compute_claim_sha256",
            "final_success_sha256",
            "final_marker_sha256",
            "provisional_success_sha256",
            "provisional_marker_sha256",
            "result_sha256",
        )
        if any(runtime[name] is None for name in required) or runtime["failure_sha256"] is not None:
            raise Phase8BPostflightError("successful runtime hash closure is incomplete")
    elif runtime["final_success_sha256"] is not None or runtime["final_marker_sha256"] is not None:
        raise Phase8BPostflightError("failed runtime published final acceptance")


def _validate_compute_claim_summary(
    value: object,
    *,
    terminal_outcome: str,
    receipt_outcome: object,
    runtime_value: object,
    transport: dict[str, object],
) -> None:
    runtime = _object(runtime_value, label="runtime")
    if value is None:
        if (
            terminal_outcome == "success"
            or receipt_outcome in _CLAIM_REQUIRED_OUTCOMES
            or runtime["compute_claim_sha256"] is not None
        ):
            raise Phase8BPostflightError("required permanent compute claim is missing")
        return
    claim = _object(value, label="compute_claim")
    _exact_keys(
        claim,
        {
            "schema_version",
            "transaction_id",
            "absolute_deadline_ns",
            "receipt_absolute_deadline_ns",
            "allowed_cpus",
            "release_token_sha256",
            "registration_sha256",
            "acknowledgement_sha256",
            "compute_claim_sha256",
            "receipt_worker_registration_sha256",
            "receipt_compute_claim_sha256",
            "created_monotonic_ns",
            "authority",
            "record_names",
            "request_relative_path",
            "output_relative_path",
            "worker_scratch_name",
        },
        label="compute_claim",
    )
    deadline = claim["absolute_deadline_ns"]
    created = claim["created_monotonic_ns"]
    scratch_name = claim["worker_scratch_name"]
    if (
        claim["schema_version"] != "nhc-phase8b-compute-claim-v1"
        or claim["transaction_id"] != _FROZEN_IDENTITY["attempt_id"]
        or type(deadline) is not int
        or type(created) is not int
        or not 0 < created < deadline
        or deadline - created > 7_200_000_000_000
        or claim["receipt_absolute_deadline_ns"] != deadline
        or claim["allowed_cpus"] != [0, 1, 2, 3]
        or claim["registration_sha256"] != runtime["worker_registration_sha256"]
        or claim["acknowledgement_sha256"] != runtime["guardian_acknowledgement_sha256"]
        or claim["compute_claim_sha256"] != runtime["compute_claim_sha256"]
        or claim["receipt_worker_registration_sha256"] != claim["registration_sha256"]
        or claim["receipt_compute_claim_sha256"] != claim["compute_claim_sha256"]
        or claim["record_names"]
        != {
            "registration": "worker_registration.json",
            "acknowledgement": "guardian_acknowledgement.json",
            "compute_claim": "compute_claim.json",
            "receipt": "guardian_receipt.json",
        }
        or claim["request_relative_path"] != "input/request.json"
        or claim["output_relative_path"] != "runtime/output"
        or not isinstance(scratch_name, str)
        or _WORKER_SCRATCH_RE.fullmatch(scratch_name) is None
    ):
        raise Phase8BPostflightError("compute claim registration, receipt, or path binding drifted")
    for name in (
        "release_token_sha256",
        "registration_sha256",
        "acknowledgement_sha256",
        "compute_claim_sha256",
        "receipt_worker_registration_sha256",
        "receipt_compute_claim_sha256",
    ):
        _sha(claim[name], label=f"compute claim {name}")
    expected_authority: dict[str, object] = {
        "transport_inventory_sha256": transport["inventory_sha256"],
        "payload_manifest_sha256": transport["payload_manifest_sha256"],
        "permit_sha256": transport["permit_sha256"],
        "request_sha256": transport["request_sha256"],
        "runner_source_sha256": transport["runner_source_sha256"],
        "protocol_sha256": _FROZEN_PROTOCOL_SHA256,
        "resources_sha256": _sha256(_canonical_json_bytes(_FROZEN_RESOURCES)),
        "cation_xyz_sha256": _FROZEN_INPUT_SHA256["cation_xyz"],
        "neutral_xyz_sha256": _FROZEN_INPUT_SHA256["neutral_xyz"],
        "endpoint_atom_map_sha256": _FROZEN_INPUT_SHA256["endpoint_atom_map"],
        "legacy_atom_map_sha256": _FROZEN_INPUT_SHA256["legacy_atom_map"],
        "geometry_validation_sha256": _GEOMETRY_VALIDATION_SHA256,
        "electron_count": 120,
        "request_id": _FROZEN_IDENTITY["request_id"],
        "inchikey": _FROZEN_IDENTITY["inchikey"],
        "attempt_id": _FROZEN_IDENTITY["attempt_id"],
    }
    if claim["authority"] != expected_authority:
        raise Phase8BPostflightError("compute claim exact authority drifted")


def _validate_d3(value: object, *, atom_count: int, label: str) -> None:
    d3 = _object(value, label=f"{label}.d3")
    _exact_keys(
        d3,
        {
            "tag",
            "optimization_energy_hook_calls",
            "optimization_gradient_hook_calls",
            "optimization_gradient_shape",
            "final_energy_hook_calls",
            "dispersion_hartree",
            "breakdown_absolute_error_hartree",
            "audit_calls",
            "audit_energy_hartree",
            "audit_gradient_shape",
            "audit_absolute_error_hartree",
            "adapter_version",
        },
        label=f"{label}.d3",
    )
    shape = [atom_count, 3]
    positive_counts = (
        d3["optimization_energy_hook_calls"],
        d3["optimization_gradient_hook_calls"],
        d3["final_energy_hook_calls"],
    )
    if (
        d3["tag"] != "d3bj"
        or any(type(item) is not int or item <= 0 for item in positive_counts)
        or d3["optimization_gradient_shape"] != shape
        or d3["audit_calls"] != 1
        or d3["audit_gradient_shape"] != shape
        or d3["adapter_version"] != "1.5.0"
    ):
        raise Phase8BPostflightError(f"{label} D3(BJ) dynamic evidence drifted")
    dispersion = _finite(d3["dispersion_hartree"], label=f"{label} dispersion")
    audit = _finite(d3["audit_energy_hartree"], label=f"{label} D3 audit")
    breakdown_error = _finite(
        d3["breakdown_absolute_error_hartree"], label=f"{label} D3 breakdown error"
    )
    audit_error = _finite(d3["audit_absolute_error_hartree"], label=f"{label} D3 audit error")
    if dispersion == 0.0 or audit == 0.0 or breakdown_error > 1e-12 or audit_error > 1e-12:
        raise Phase8BPostflightError(f"{label} D3(BJ) arithmetic was not proved")


def _validate_endpoint(value: object, *, name: str) -> float:
    endpoint = _object(value, label=name)
    _exact_keys(
        endpoint,
        {
            "charge",
            "multiplicity",
            "electron_count",
            "atom_count",
            "optimized_xyz_sha256",
            "geometry_converged",
            "optimization_scf_converged",
            "final_scf_converged",
            "optimization_strategy",
            "final_scf_strategy",
            "soscf_budget",
            "soscf_consumed",
            "soscf_stage",
            "optimization_energy_hartree",
            "final_energy_hartree",
            "runtime",
            "d3",
        },
        label=name,
    )
    expected_charge = 1 if name == "cation" else 0
    expected_atom_count = 22 if name == "cation" else 21
    atom_count = endpoint["atom_count"]
    if (
        endpoint["charge"] != expected_charge
        or endpoint["multiplicity"] != 1
        or endpoint["electron_count"] != 120
        or atom_count != expected_atom_count
        or endpoint["geometry_converged"] is not True
        or endpoint["optimization_scf_converged"] is not True
        or endpoint["final_scf_converged"] is not True
        or endpoint["optimization_strategy"] not in {"standard", "soscf"}
        or endpoint["final_scf_strategy"] not in {"standard", "soscf"}
        or endpoint["soscf_budget"] != 1
        or type(endpoint["soscf_consumed"]) is not bool
        or endpoint["soscf_stage"] not in {None, "optimization", "final_scf"}
        or (endpoint["soscf_consumed"] is True) != (endpoint["soscf_stage"] is not None)
    ):
        raise Phase8BPostflightError(f"{name} convergence or retry evidence drifted")
    _sha(endpoint["optimized_xyz_sha256"], label=f"{name} optimized XYZ SHA256")
    _finite(endpoint["optimization_energy_hartree"], label=f"{name} optimization energy")
    final_energy = _finite(endpoint["final_energy_hartree"], label=f"{name} final energy")
    runtime = _object(endpoint["runtime"], label=f"{name}.runtime")
    expected_runtime: dict[str, object] = {
        "compute_threads": 4,
        "thread_environment": _THREAD_ENVIRONMENT,
        "pyscf_threads": 4,
        "molecule_max_memory_mb": 12_000,
        "mean_field_max_memory_mb": 12_000,
        "electron_count": 120,
    }
    if runtime != expected_runtime:
        raise Phase8BPostflightError(f"{name} runtime resource evidence drifted")
    _validate_d3(endpoint["d3"], atom_count=atom_count, label=name)
    return final_energy


def _validate_result(value: object) -> None:
    result = _object(value, label="result")
    _exact_keys(
        result,
        {
            "cation",
            "neutral",
            "electronic_difference_kcal",
            "dft_deprot_electronic_kcal",
            "lower_is_better",
            "hessian_computed",
            "frequency_status",
            "extra_single_points_computed",
            "radical_computed",
            "molden_written",
            "label_quality",
            "supervision",
        },
        label="result",
    )
    cation = _validate_endpoint(result["cation"], name="cation")
    neutral = _validate_endpoint(result["neutral"], name="neutral")
    difference = _finite(result["electronic_difference_kcal"], label="electronic difference")
    label = _finite(result["dft_deprot_electronic_kcal"], label="deprotonation label")
    expected_difference = (neutral - cation) * 627.509474
    if not math.isclose(difference, expected_difference, rel_tol=0.0, abs_tol=1e-12):
        raise Phase8BPostflightError("electronic difference formula drifted")
    if not math.isclose(label, expected_difference - 6.28, rel_tol=0.0, abs_tol=1e-12):
        raise Phase8BPostflightError("deprotonation label formula drifted")
    if (
        result["lower_is_better"] is not True
        or result["hessian_computed"] is not False
        or result["frequency_status"] != "not_computed"
        or result["extra_single_points_computed"] is not False
        or result["radical_computed"] is not False
        or result["molden_written"] is not False
        or result["label_quality"] != "electronic_energy_only"
    ):
        raise Phase8BPostflightError("result scientific boundary drifted")
    supervision = _object(result["supervision"], label="supervision")
    _exact_keys(
        supervision,
        {
            "outcome",
            "public_returncode",
            "child_returncode",
            "duration_seconds",
            "stdout_truncated",
            "stderr_truncated",
            "timed_out",
            "term_sent",
            "kill_sent",
            "orphan_descendants_detected",
            "process_started",
            "group_cleanup_confirmed",
            "direct_child_reaped",
        },
        label="supervision",
    )
    duration = _finite(supervision["duration_seconds"], label="supervision duration")
    expected = {
        "outcome": "clean",
        "public_returncode": 0,
        "child_returncode": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "timed_out": False,
        "term_sent": False,
        "kill_sent": False,
        "orphan_descendants_detected": False,
        "process_started": True,
        "group_cleanup_confirmed": True,
        "direct_child_reaped": True,
    }
    if (
        duration < 0.0
        or duration > 7_200.0
        or any(supervision[name] != expected_value for name, expected_value in expected.items())
    ):
        raise Phase8BPostflightError("supervision was not a clean bounded success")


def _validate_failure(value: object) -> None:
    failure = _object(value, label="failure")
    _exact_keys(
        failure,
        {"receipt_outcome", "error_code", "attempt_failure_stage", "attempt_failure_error_type"},
        label="failure",
    )
    if failure["receipt_outcome"] == "clean":
        raise Phase8BPostflightError("terminal failure has a clean receipt")
    for name in ("error_code", "attempt_failure_stage", "attempt_failure_error_type"):
        value_at_name = failure[name]
        if value_at_name is not None and (
            not isinstance(value_at_name, str) or not value_at_name or len(value_at_name) > 96
        ):
            raise Phase8BPostflightError(f"failure {name} is invalid")


def validate_phase8b_postflight(
    payload: dict[str, object],
    *,
    expected_transport_inventory_sha256: str,
) -> dict[str, object]:
    """Validate one path-free terminal summary and its exact frozen identity."""

    expected_inventory = _sha(
        expected_transport_inventory_sha256,
        label="expected transport inventory SHA256",
    )
    _exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "terminal_outcome",
            "checks",
            "identity",
            "resources",
            "transport",
            "permit",
            "phase7",
            "project_source_sha256",
            "process_cleanup",
            "runtime",
            "compute_claim",
            "result",
            "failure",
            "forbidden",
            "safety",
        },
        label="postflight",
    )
    if payload["schema_version"] != POSTFLIGHT_SCHEMA_VERSION or payload["status"] != "passed":
        raise Phase8BPostflightError("postflight did not pass")
    terminal_outcome = payload["terminal_outcome"]
    if terminal_outcome not in {"success", "failure"}:
        raise Phase8BPostflightError("terminal outcome is invalid")
    checks = _object(payload["checks"], label="checks")
    if set(checks) != _EXPECTED_CHECKS or any(value is not True for value in checks.values()):
        raise Phase8BPostflightError("postflight checks are incomplete or failed")
    if payload["identity"] != _FROZEN_IDENTITY or payload["resources"] != _FROZEN_RESOURCES:
        raise Phase8BPostflightError("frozen identity or resources drifted")

    transport = _object(payload["transport"], label="transport")
    _exact_keys(
        transport,
        {
            "inventory_sha256",
            "payload_manifest_sha256",
            "permit_sha256",
            "request_sha256",
            "runner_source_sha256",
            "protocol_sha256",
            "resources_sha256",
            "transport_tree_sha256",
            "directory_tree_sha256",
            "static_file_count",
        },
        label="transport",
    )
    if transport["inventory_sha256"] != expected_inventory:
        raise Phase8BPostflightError("transport inventory identity drifted")
    for name in (
        "payload_manifest_sha256",
        "permit_sha256",
        "request_sha256",
        "runner_source_sha256",
        "protocol_sha256",
        "resources_sha256",
        "transport_tree_sha256",
        "directory_tree_sha256",
    ):
        _sha(transport[name], label=name)
    if transport["protocol_sha256"] != _FROZEN_PROTOCOL_SHA256 or transport[
        "resources_sha256"
    ] != _sha256(_canonical_json_bytes(_FROZEN_RESOURCES)):
        raise Phase8BPostflightError("transport protocol or resources identity drifted")
    if type(transport["static_file_count"]) is not int or transport["static_file_count"] < 4:
        raise Phase8BPostflightError("static file count is invalid")

    permit = _object(payload["permit"], label="permit")
    if permit != {
        "ready_present": False,
        "consumed_sha256": transport["permit_sha256"],
        "consumed_mode": "0400",
    }:
        raise Phase8BPostflightError("one-shot permit state drifted")
    if payload["phase7"] != _EXPECTED_PHASE7:
        raise Phase8BPostflightError("Phase 7 tree identity drifted")
    if payload["project_source_sha256"] != _EXPECTED_PROJECT_SOURCES:
        raise Phase8BPostflightError("registered project sources drifted")

    process_cleanup = _object(payload["process_cleanup"], label="process_cleanup")
    _validate_process_cleanup(process_cleanup, terminal_outcome=terminal_outcome)
    _validate_runtime(payload["runtime"], terminal_outcome=terminal_outcome)
    _validate_compute_claim_summary(
        payload["compute_claim"],
        terminal_outcome=terminal_outcome,
        receipt_outcome=process_cleanup["receipt_outcome"],
        runtime_value=payload["runtime"],
        transport=transport,
    )
    forbidden = _object(payload["forbidden"], label="forbidden")
    expected_forbidden = {
        "hessian": False,
        "frequency": False,
        "zpe": False,
        "thermal": False,
        "radical": False,
        "molden": False,
        "no_d3": False,
        "extra_single_point": False,
        "scheduler": False,
        "second_attempt": False,
    }
    if forbidden != expected_forbidden:
        raise Phase8BPostflightError("forbidden artifact scan drifted")
    safety = payload["safety"]
    if safety != {
        "read_only": True,
        "remote_file_written": False,
        "remote_file_deleted": False,
        "process_signalled": False,
        "chemistry_imported": False,
        "quantum_execution_started": False,
        "logs_used_as_acceptance_evidence": False,
    }:
        raise Phase8BPostflightError("postflight safety claims drifted")
    if terminal_outcome == "success":
        if payload["failure"] is not None:
            raise Phase8BPostflightError("success unexpectedly contains failure evidence")
        _validate_result(payload["result"])
    else:
        if payload["result"] is not None:
            raise Phase8BPostflightError("failed run exposed an accepted result")
        _validate_failure(payload["failure"])
        failure = _object(payload["failure"], label="failure")
        if failure["receipt_outcome"] != process_cleanup["receipt_outcome"]:
            raise Phase8BPostflightError("failure and guardian receipt outcomes disagree")
    return payload


def _remote_wrapper(
    *,
    inspector_source: bytes,
    config: Phase8BRemoteConfig,
    expected_transport_inventory_sha256: str,
) -> bytes:
    expected_hash = _sha(
        expected_transport_inventory_sha256,
        label="expected transport inventory SHA256",
    )
    try:
        source = inspector_source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Phase8BPostflightError("postflight inspector must be UTF-8") from exc
    if _HEREDOC in source:
        raise Phase8BPostflightError("postflight inspector collides with heredoc marker")
    project = config.remote.project_root
    phase7 = config.remote.phase7_run_relative
    phase8b = config.remote.phase8b_run_relative
    script = f"""set -euo pipefail
project_root={project!r}
phase7_relative={phase7!r}
phase8b_relative={phase8b!r}
inventory_sha256={expected_hash!r}
test -d "$project_root"
test ! -L "$project_root"
cd "$project_root"
export PYTHONDONTWRITEBYTECODE=1
exec python3 -I -B - --inspect-server \
  "$phase7_relative" "$phase8b_relative" "$inventory_sha256" <<'{_HEREDOC}'
{source}
{_HEREDOC}
"""
    return script.encode("utf-8")


def phase8b_postflight_command(config: Phase8BRemoteConfig) -> tuple[str, ...]:
    """Return the fixed SSH argv; the read-only inspector is supplied on stdin."""

    return (
        "ssh",
        *config.ssh_options(),
        config.connection.ssh_alias,
        "bash",
        "-s",
    )


def run_phase8b_postflight(
    *,
    config_path: Path,
    inspector_path: Path,
    expected_transport_inventory_sha256: str,
    timeout_seconds: float = 300.0,
    run_command: RunCommand | None = None,
) -> dict[str, object]:
    """Run one bounded read-only SSH collection and validate its canonical JSON."""

    if timeout_seconds <= 0.0 or timeout_seconds > 600.0:
        raise ValueError("postflight timeout must be in (0, 600]")
    config = load_phase8b_remote_config(config_path)
    config.require_read_only_preflight()
    inspector_source = _read_frozen_inspector(inspector_path)
    wrapper = _remote_wrapper(
        inspector_source=inspector_source,
        config=config,
        expected_transport_inventory_sha256=expected_transport_inventory_sha256,
    )
    command_runner = cast(RunCommand, subprocess.run) if run_command is None else run_command
    try:
        completed = command_runner(
            phase8b_postflight_command(config),
            input=wrapper,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise Phase8BPostflightError("Phase 8B SSH postflight could not run") from exc
    if len(completed.stdout) > _MAX_STDOUT_BYTES:
        raise Phase8BPostflightError("postflight stdout exceeded its bound")
    if len(completed.stderr) > _MAX_STDERR_BYTES:
        raise Phase8BPostflightError("postflight stderr exceeded its bound")
    if completed.returncode != 0:
        raise Phase8BPostflightError(f"Phase 8B postflight exited nonzero: {completed.returncode}")
    if completed.stderr:
        raise Phase8BPostflightError("Phase 8B postflight produced unexpected stderr")
    if not completed.stdout:
        raise Phase8BPostflightError("Phase 8B postflight produced empty stdout")
    payload = _strict_json_object(completed.stdout)
    if completed.stdout != _canonical_json_bytes(payload):
        raise Phase8BPostflightError("postflight stdout is not canonical JSON")
    validated = validate_phase8b_postflight(
        payload,
        expected_transport_inventory_sha256=expected_transport_inventory_sha256,
    )
    return validated


def portable_phase8b_postflight(
    payload: dict[str, object],
    *,
    expected_transport_inventory_sha256: str,
) -> dict[str, object]:
    """Wrap the already path/PID/log-free terminal summary in a portable envelope."""

    validated = validate_phase8b_postflight(
        payload,
        expected_transport_inventory_sha256=expected_transport_inventory_sha256,
    )
    evidence: dict[str, object] = {
        "schema_version": PORTABLE_POSTFLIGHT_SCHEMA_VERSION,
        "postflight": validated,
        "postflight_sha256": _sha256(_canonical_json_bytes(validated)),
    }
    return evidence


__all__ = [
    "PORTABLE_POSTFLIGHT_SCHEMA_VERSION",
    "POSTFLIGHT_SCHEMA_VERSION",
    "Phase8BPostflightError",
    "phase8b_postflight_command",
    "portable_phase8b_postflight",
    "run_phase8b_postflight",
    "validate_phase8b_postflight",
]
