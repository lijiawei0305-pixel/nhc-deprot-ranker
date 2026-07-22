from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
import yaml

from nhc_deprot_ranker.preparation import phase8b_postflight as postflight_module
from nhc_deprot_ranker.preparation.phase8b_postflight import (
    PORTABLE_POSTFLIGHT_SCHEMA_VERSION,
    Phase8BPostflightError,
    phase8b_postflight_command,
    portable_phase8b_postflight,
    run_phase8b_postflight,
    validate_phase8b_postflight,
)
from nhc_deprot_ranker.preparation.phase8b_remote import load_phase8b_remote_config

_INVENTORY_SHA = "a" * 64
_HASH = "b" * 64
_PROTOCOL_SHA = "266b06e0d49cb6e3067bcfeb6d62f0712852e96768c4205b49fffcb3df52fe92"
_INPUT_SHA = {
    "cation_xyz": "097f08ab7c3f265efa8ee36c3fd45d72776c9bdcbd3de503baf8fe91561c12aa",
    "neutral_xyz": "e41e87daca3c7a74383364a427d277df5cf8a0aa70bff015c4cf432455f26bd0",
    "endpoint_atom_map": "0cb13e918f2fa88348affb2385d37e01a75d73376118d18aa4c7647ef4982152",
    "legacy_atom_map": "7766fad207561b79ac8e7278b70eb07c37dcf31d4114b76ad9a9383b235681f8",
}
_GEOMETRY_SHA = "35e99683a32e416752014c6e1ecb8121e2bc06d5407911435e5c1250fd639f90"


def _canonical(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _config(path: Path) -> Path:
    payload = {
        "schema_version": "phase8b_remote.v1",
        "connection": {
            "mode": "campus_direct",
            "ssh_alias": "synthetic-hpc",
            "proxy_host": "127.0.0.1",
            "proxy_port": 11080,
        },
        "remote": {
            "project_root": "/srv/project",
            "environment_relative": "env/envs/molenv.sh",
            "phase7_run_relative": "data/runs/nhc_deprot_ranker_phase7_smoke_fixture",
            "phase8b_run_relative": "data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001",
            "require_new_phase8b_root": True,
        },
        "transfer": {
            "directed_files_only": True,
            "recursive_copy": False,
            "delete": False,
            "overwrite": False,
        },
        "safety": {
            "read_only_preflight_authorized": True,
            "server_write_authorized": True,
            "quantum_execution_authorized": False,
            "consumed_private_permit_required": True,
            "scheduler_submission_authorized": False,
            "second_attempt_authorized": False,
        },
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    return path


def _real_inspector() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts/phase8b_remote_postflight.py"


def _thread_environment() -> dict[str, str]:
    return {
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


def _endpoint(*, charge: int, atom_count: int, energy: float) -> dict[str, object]:
    return {
        "charge": charge,
        "multiplicity": 1,
        "electron_count": 120,
        "atom_count": atom_count,
        "optimized_xyz_sha256": _HASH,
        "geometry_converged": True,
        "optimization_scf_converged": True,
        "final_scf_converged": True,
        "optimization_strategy": "standard",
        "final_scf_strategy": "standard",
        "soscf_budget": 1,
        "soscf_consumed": False,
        "soscf_stage": None,
        "optimization_energy_hartree": energy + 0.01,
        "final_energy_hartree": energy,
        "runtime": {
            "compute_threads": 4,
            "thread_environment": _thread_environment(),
            "pyscf_threads": 4,
            "molecule_max_memory_mb": 12_000,
            "mean_field_max_memory_mb": 12_000,
            "electron_count": 120,
        },
        "d3": {
            "tag": "d3bj",
            "optimization_energy_hook_calls": 2,
            "optimization_gradient_hook_calls": 2,
            "optimization_gradient_shape": [atom_count, 3],
            "final_energy_hook_calls": 1,
            "dispersion_hartree": -0.01,
            "breakdown_absolute_error_hartree": 0.0,
            "audit_calls": 1,
            "audit_energy_hartree": -0.01,
            "audit_gradient_shape": [atom_count, 3],
            "audit_absolute_error_hartree": 0.0,
            "adapter_version": "1.5.0",
        },
    }


def _checks() -> dict[str, bool]:
    return {
        name: True
        for name in {
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
    }


def _base_payload(*, terminal_outcome: str = "success") -> dict[str, object]:
    resources = {
        "worker_count": 1,
        "computational_threads": 4,
        "cpu_affinity": "0-3",
        "pyscf_max_memory_mb": 12_000,
        "hard_wall_timeout_seconds": 7_200,
        "terminate_grace_seconds": 10,
        "stdout_capture_limit_bytes": 65_536,
        "stderr_capture_limit_bytes": 65_536,
    }
    runtime: dict[str, object] = {
        "guardian_receipt_sha256": _HASH,
        "worker_registration_sha256": _HASH,
        "guardian_acknowledgement_sha256": _HASH,
        "compute_claim_sha256": _HASH,
        "final_success_sha256": _HASH,
        "final_marker_sha256": _HASH,
        "provisional_success_sha256": _HASH,
        "provisional_marker_sha256": _HASH,
        "result_sha256": _HASH,
        "failure_sha256": None,
    }
    process_cleanup = {
        "receipt_outcome": "clean",
        "registered_identity_count": 3,
        "identity_status": {
            "guardian": "absent",
            "supervisor": "absent",
            "worker": "absent",
        },
        "group_status": {
            "guardian": "absent",
            "supervisor": "absent",
            "worker": "absent",
        },
        "pid_reuse_observed": False,
        "all_registered_identities_absent": True,
        "all_registered_groups_absent": True,
    }
    cation = _endpoint(charge=1, atom_count=22, energy=-100.0)
    neutral = _endpoint(charge=0, atom_count=21, energy=-99.5)
    difference = 0.5 * 627.509474
    result: dict[str, object] | None = {
        "cation": cation,
        "neutral": neutral,
        "electronic_difference_kcal": difference,
        "dft_deprot_electronic_kcal": difference - 6.28,
        "lower_is_better": True,
        "hessian_computed": False,
        "frequency_status": "not_computed",
        "extra_single_points_computed": False,
        "radical_computed": False,
        "molden_written": False,
        "label_quality": "electronic_energy_only",
        "supervision": {
            "outcome": "clean",
            "public_returncode": 0,
            "child_returncode": 0,
            "duration_seconds": 100.0,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timed_out": False,
            "term_sent": False,
            "kill_sent": False,
            "orphan_descendants_detected": False,
            "process_started": True,
            "group_cleanup_confirmed": True,
            "direct_child_reaped": True,
        },
    }
    failure: dict[str, object] | None = None
    if terminal_outcome == "failure":
        process_cleanup["receipt_outcome"] = "authority_failed"
        process_cleanup["registered_identity_count"] = 1
        process_cleanup["identity_status"] = {"guardian": "absent"}
        process_cleanup["group_status"] = {"guardian": "absent"}
        for name in (
            "worker_registration_sha256",
            "guardian_acknowledgement_sha256",
            "compute_claim_sha256",
            "final_success_sha256",
            "final_marker_sha256",
            "provisional_success_sha256",
            "provisional_marker_sha256",
            "result_sha256",
        ):
            runtime[name] = None
        result = None
        failure = {
            "receipt_outcome": "authority_failed",
            "error_code": "SyntheticAuthorityError",
            "attempt_failure_stage": None,
            "attempt_failure_error_type": None,
        }
    compute_claim: dict[str, object] | None = None
    if terminal_outcome == "success":
        compute_claim = {
            "schema_version": "nhc-phase8b-compute-claim-v1",
            "transaction_id": "attempt-phase8b-qxh-v001",
            "absolute_deadline_ns": 7_201_000_000_000,
            "receipt_absolute_deadline_ns": 7_201_000_000_000,
            "allowed_cpus": [0, 1, 2, 3],
            "release_token_sha256": _HASH,
            "registration_sha256": _HASH,
            "acknowledgement_sha256": _HASH,
            "compute_claim_sha256": _HASH,
            "receipt_worker_registration_sha256": _HASH,
            "receipt_compute_claim_sha256": _HASH,
            "created_monotonic_ns": 1_400_000_000,
            "authority": {
                "transport_inventory_sha256": _INVENTORY_SHA,
                "payload_manifest_sha256": _HASH,
                "permit_sha256": _HASH,
                "request_sha256": _HASH,
                "runner_source_sha256": _HASH,
                "protocol_sha256": _PROTOCOL_SHA,
                "resources_sha256": _sha(_canonical(resources)),
                "cation_xyz_sha256": _INPUT_SHA["cation_xyz"],
                "neutral_xyz_sha256": _INPUT_SHA["neutral_xyz"],
                "endpoint_atom_map_sha256": _INPUT_SHA["endpoint_atom_map"],
                "legacy_atom_map_sha256": _INPUT_SHA["legacy_atom_map"],
                "geometry_validation_sha256": _GEOMETRY_SHA,
                "electron_count": 120,
                "request_id": "phase8b-qxh-smoke-v001",
                "inchikey": "QXHIEGFUWOLQIJ-UHFFFAOYSA-N",
                "attempt_id": "attempt-phase8b-qxh-v001",
            },
            "record_names": {
                "registration": "worker_registration.json",
                "acknowledgement": "guardian_acknowledgement.json",
                "compute_claim": "compute_claim.json",
                "receipt": "guardian_receipt.json",
            },
            "request_relative_path": "input/request.json",
            "output_relative_path": "runtime/output",
            "worker_scratch_name": ".worker-attempt-phase8b-qxh-v001-synthetic",
        }
    return {
        "schema_version": "phase8b.remote-postflight.v1",
        "status": "passed",
        "terminal_outcome": terminal_outcome,
        "checks": _checks(),
        "identity": {
            "inchikey": "QXHIEGFUWOLQIJ-UHFFFAOYSA-N",
            "request_id": "phase8b-qxh-smoke-v001",
            "attempt_id": "attempt-phase8b-qxh-v001",
        },
        "resources": resources,
        "transport": {
            "inventory_sha256": _INVENTORY_SHA,
            "payload_manifest_sha256": _HASH,
            "permit_sha256": _HASH,
            "request_sha256": _HASH,
            "runner_source_sha256": _HASH,
            "protocol_sha256": _PROTOCOL_SHA,
            "resources_sha256": _sha(_canonical(resources)),
            "transport_tree_sha256": _HASH,
            "directory_tree_sha256": _HASH,
            "static_file_count": 20,
        },
        "permit": {
            "ready_present": False,
            "consumed_sha256": _HASH,
            "consumed_mode": "0400",
        },
        "phase7": {
            "file_count": 27,
            "tree_sha256": "9b92a1f453274995661bd262e607239a86f4992bf4cc2809a311207dceadbecb",
        },
        "project_source_sha256": {
            "env/envs/molenv.sh": (
                "e9b3e124f53a10e84c43cfc71a56af3ddd56a86f082610593d2b23ed9692ea6f"
            ),
            "scripts/mol/gen_3d.py": (
                "d23c7ad9a6e35948949f6485b53caafb0f3f5705148f642e3a4a30fb589a946a"
            ),
            "scripts/mol/structure_gen.py": (
                "a50b50b9967ac9e8203b398fe69f3daebf40a144f37dae8e0aa086e613ad1365"
            ),
        },
        "process_cleanup": process_cleanup,
        "runtime": runtime,
        "compute_claim": compute_claim,
        "result": result,
        "failure": failure,
        "forbidden": {
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
        },
        "safety": {
            "read_only": True,
            "remote_file_written": False,
            "remote_file_deleted": False,
            "process_signalled": False,
            "chemistry_imported": False,
            "quantum_execution_started": False,
            "logs_used_as_acceptance_evidence": False,
        },
    }


@dataclass
class _Completed:
    returncode: int
    stdout: bytes
    stderr: bytes = b""


def test_validator_accepts_success_and_emits_path_free_portable_evidence() -> None:
    payload = _base_payload()
    assert (
        validate_phase8b_postflight(
            payload,
            expected_transport_inventory_sha256=_INVENTORY_SHA,
        )
        is payload
    )
    portable = portable_phase8b_postflight(
        payload,
        expected_transport_inventory_sha256=_INVENTORY_SHA,
    )
    assert portable["schema_version"] == PORTABLE_POSTFLIGHT_SCHEMA_VERSION
    assert portable["postflight_sha256"] == _sha(_canonical(payload))
    serialized = json.dumps(portable)
    assert "/srv/" not in serialized
    assert "guardian.log" not in serialized
    assert '"pid"' not in serialized


def test_validator_accepts_honest_terminal_failure_without_final_marker() -> None:
    payload = _base_payload(terminal_outcome="failure")
    validated = validate_phase8b_postflight(
        payload,
        expected_transport_inventory_sha256=_INVENTORY_SHA,
    )
    assert validated["terminal_outcome"] == "failure"
    assert validated["result"] is None


def test_validator_accepts_late_failure_with_permanent_compute_claim() -> None:
    payload = _base_payload(terminal_outcome="failure")
    payload["compute_claim"] = _base_payload()["compute_claim"]
    runtime = cast(dict[str, object], payload["runtime"])
    runtime["worker_registration_sha256"] = _HASH
    runtime["guardian_acknowledgement_sha256"] = _HASH
    runtime["compute_claim_sha256"] = _HASH
    cleanup = cast(dict[str, object], payload["process_cleanup"])
    cleanup["receipt_outcome"] = "supervisor_nonzero"
    cleanup["registered_identity_count"] = 3
    cleanup["identity_status"] = {
        "guardian": "absent",
        "supervisor": "absent",
        "worker": "absent",
    }
    cleanup["group_status"] = {
        "guardian": "absent",
        "supervisor": "absent",
        "worker": "absent",
    }
    failure = cast(dict[str, object], payload["failure"])
    failure["receipt_outcome"] = "supervisor_nonzero"
    failure["error_code"] = "SyntheticSupervisorNonzero"
    validated = validate_phase8b_postflight(
        payload,
        expected_transport_inventory_sha256=_INVENTORY_SHA,
    )
    assert validated["compute_claim"] is not None


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("formula", "formula"),
        ("ready", "permit"),
        ("d3", "D3"),
        ("claim", "compute claim"),
        ("final_on_failure", "final acceptance"),
    ],
)
def test_validator_rejects_scientific_or_terminal_drift(mutation: str, message: str) -> None:
    payload = _base_payload(
        terminal_outcome="failure" if mutation == "final_on_failure" else "success"
    )
    if mutation == "formula":
        cast(dict[str, object], payload["result"])["dft_deprot_electronic_kcal"] = 1.0
    elif mutation == "ready":
        cast(dict[str, object], payload["permit"])["ready_present"] = True
    elif mutation == "d3":
        result = cast(dict[str, object], payload["result"])
        endpoint = cast(dict[str, object], result["cation"])
        cast(dict[str, object], endpoint["d3"])["audit_calls"] = 2
    elif mutation == "claim":
        payload["compute_claim"] = None
    else:
        cast(dict[str, object], payload["runtime"])["final_marker_sha256"] = _HASH
    with pytest.raises(Phase8BPostflightError, match=message):
        validate_phase8b_postflight(
            payload,
            expected_transport_inventory_sha256=_INVENTORY_SHA,
        )


def test_postflight_command_and_wrapper_are_read_only_and_do_not_source_environment(
    tmp_path: Path,
) -> None:
    config_path = _config(tmp_path / "config.yaml")
    config = load_phase8b_remote_config(config_path)
    assert phase8b_postflight_command(config) == (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ConnectTimeout=15",
        "synthetic-hpc",
        "bash",
        "-s",
    )
    inspector = _real_inspector()
    seen: dict[str, object] = {}

    def fake_run(command: tuple[str, ...], **kwargs: object) -> _Completed:
        seen["command"] = command
        seen.update(kwargs)
        return _Completed(0, _canonical(_base_payload()))

    result = run_phase8b_postflight(
        config_path=config_path,
        inspector_path=inspector,
        expected_transport_inventory_sha256=_INVENTORY_SHA,
        run_command=fake_run,
    )
    assert result["terminal_outcome"] == "success"
    wrapper = seen["input"]
    assert isinstance(wrapper, bytes)
    shell = wrapper.split(b"<<'__NHC_PHASE8B_POSTFLIGHT_PY__'", maxsplit=1)[0]
    assert b"python3 -I -B - --inspect-server" in shell
    assert b"PYTHONDONTWRITEBYTECODE=1" in shell
    assert b"source " not in shell
    assert b"molenv" not in shell
    assert b"mkdir" not in shell
    assert b"rm " not in shell


def test_launcher_rejects_noncanonical_duplicate_nonzero_and_stderr(tmp_path: Path) -> None:
    config = _config(tmp_path / "config.yaml")
    inspector = _real_inspector()

    cases = (
        (_Completed(0, json.dumps(_base_payload()).encode()), "canonical"),
        (_Completed(0, b'{"x":1,"x":2}\n'), "duplicate"),
        (_Completed(2, _canonical(_base_payload())), "nonzero"),
        (_Completed(2, b""), "nonzero"),
        (_Completed(0, b""), "empty stdout"),
        (_Completed(0, _canonical(_base_payload()), b"unexpected"), "stderr"),
    )
    for completed, message in cases:

        def fake_run(
            command: tuple[str, ...],
            *,
            _completed: _Completed = completed,
            **kwargs: object,
        ) -> _Completed:
            del command, kwargs
            return _completed

        with pytest.raises(Phase8BPostflightError, match=message):
            run_phase8b_postflight(
                config_path=config,
                inspector_path=inspector,
                expected_transport_inventory_sha256=_INVENTORY_SHA,
                run_command=fake_run,
            )


def test_launcher_rejects_alternate_or_replaced_inspector_before_ssh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path / "config.yaml")
    alternate = tmp_path / "alternate.py"
    alternate.write_bytes(_real_inspector().read_bytes())
    alternate.chmod(0o644)
    called = False

    def fake_run(command: tuple[str, ...], **kwargs: object) -> _Completed:
        nonlocal called
        del command, kwargs
        called = True
        return _Completed(0, _canonical(_base_payload()))

    with pytest.raises(Phase8BPostflightError, match="frozen repository path"):
        run_phase8b_postflight(
            config_path=config,
            inspector_path=alternate,
            expected_transport_inventory_sha256=_INVENTORY_SHA,
            run_command=fake_run,
        )
    assert called is False

    monkeypatch.setattr(postflight_module, "_FROZEN_INSPECTOR_PATH", alternate)
    alternate.write_bytes(_real_inspector().read_bytes() + b"# replaced\n")
    alternate.chmod(0o644)
    with pytest.raises(Phase8BPostflightError, match="SHA256 drifted"):
        run_phase8b_postflight(
            config_path=config,
            inspector_path=alternate,
            expected_transport_inventory_sha256=_INVENTORY_SHA,
            run_command=fake_run,
        )
    assert called is False

    alternate.unlink()
    alternate.symlink_to(_real_inspector())
    with pytest.raises(Phase8BPostflightError, match="cannot be opened safely"):
        run_phase8b_postflight(
            config_path=config,
            inspector_path=alternate,
            expected_transport_inventory_sha256=_INVENTORY_SHA,
            run_command=fake_run,
        )
    assert called is False


def _load_inspector() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts/phase8b_remote_postflight.py"
    spec = importlib.util.spec_from_file_location("phase8b_remote_postflight_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: Path, name: str, raw: bytes, mode: int) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def test_phase7_tree_accepts_a_known_zero_byte_manifest_file(tmp_path: Path) -> None:
    inspector = _load_inspector()
    phase7 = tmp_path / "phase7"
    phase7.mkdir()
    _write(phase7, "artifact.txt", b"phase7\n", 0o640)
    _write(phase7, "m2/gen_3d_failed.log", b"", 0o640)
    expected_mapping = {
        "artifact.txt": _sha(b"phase7\n"),
        "m2/gen_3d_failed.log": _sha(b""),
    }
    expected_raw = json.dumps(
        expected_mapping,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")

    assert inspector._phase7_tree(phase7) == (  # pyright: ignore[reportPrivateUsage]
        2,
        _sha(expected_raw),
    )


def _synthetic_terminal_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ModuleType, Path, str, str]:
    inspector = _load_inspector()
    project = (tmp_path / "project").resolve()
    project.mkdir(mode=0o700)
    phase7_relative = "data/runs/nhc_deprot_ranker_phase7_smoke_fixture"
    phase7 = project / phase7_relative
    phase7.mkdir(parents=True)
    _write(phase7, "artifact.txt", b"phase7\n", 0o640)
    phase7_identity = inspector._phase7_tree(phase7)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(inspector, "EXPECTED_PHASE7_FILE_COUNT", phase7_identity[0])
    monkeypatch.setattr(inspector, "EXPECTED_PHASE7_TREE_SHA256", phase7_identity[1])

    source_name = "registered/source.txt"
    _write(project, source_name, b"registered source\n", 0o640)
    source_hash = _sha((project / source_name).read_bytes())
    monkeypatch.setattr(inspector, "EXPECTED_PROJECT_SOURCE_SHA256", {source_name: source_hash})
    monkeypatch.setattr(inspector, "RUNNER_SOURCE_PATHS", frozenset({"pkg.py"}))

    run_relative = cast(str, inspector.EXPECTED_PHASE8B_RELATIVE)
    run_root = project / run_relative
    run_root.mkdir(parents=True, mode=0o700)
    run_root.chmod(0o700)
    cation_raw = b"2\ncation\nC 0 0 0\nH 0 0 1\n"
    neutral_raw = b"1\nneutral\nC 0 0 0\n"
    input_hashes = {
        "cation_xyz": _sha(cation_raw),
        "neutral_xyz": _sha(neutral_raw),
        "endpoint_atom_map": "1" * 64,
        "legacy_atom_map": "2" * 64,
    }
    monkeypatch.setattr(inspector, "FROZEN_INPUT_SHA256", input_hashes)
    protocol = {"synthetic": "locked"}
    protocol_hash = _sha(_canonical(protocol))
    monkeypatch.setattr(inspector, "FROZEN_PROTOCOL_SHA256", protocol_hash)
    source_raw = b"# synthetic source\n"
    runner_source_sha = "3" * 64
    request = {
        "schema_version": "nhc-two-endpoint-request-v1",
        "request_id": inspector.FROZEN_IDENTITY["request_id"],
        "inchikey": inspector.FROZEN_IDENTITY["inchikey"],
        "execution_authorized": True,
        "timeout_seconds": 7_200,
        "runner_source_sha256": runner_source_sha,
        "protocol": protocol,
        "endpoints": {
            "cation": {
                "xyz_path": "xyz/cation.xyz",
                "xyz_sha256": input_hashes["cation_xyz"],
                "charge": 1,
                "multiplicity": 1,
            },
            "neutral": {
                "xyz_path": "xyz/neutral.xyz",
                "xyz_sha256": input_hashes["neutral_xyz"],
                "charge": 0,
                "multiplicity": 1,
            },
        },
    }
    request_raw = _canonical(request)
    staged = {
        "input/request.json": request_raw,
        "input/xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_cation.xyz": cation_raw,
        "input/xyz/QXHIEGFUWOLQIJ-UHFFFAOYSA-N_neutral.xyz": neutral_raw,
        "src/pkg.py": source_raw,
    }
    staged_entries = {
        name: {"sha256": _sha(raw), "bytes": len(raw), "mode": "0640"}
        for name, raw in staged.items()
    }
    directories = {
        ".": {"mode": "0700"},
        "input": {"mode": "0750"},
        "input/xyz": {"mode": "0750"},
        "private": {"mode": "0700"},
        "runtime": {"mode": "0700"},
        "src": {"mode": "0750"},
    }
    payload = {
        "schema_version": "phase8b.payload_manifest.v2",
        "bundle_version": "phase8b-dft-smoke-v001",
        "identity": {
            **inspector.FROZEN_IDENTITY,
            "request_sha256": _sha(request_raw),
            "runner_source_sha256": runner_source_sha,
            "protocol_sha256": protocol_hash,
            "endpoint_order": ["cation", "neutral"],
        },
        "resources": inspector.FROZEN_RESOURCES,
        "source_relative_paths": ["pkg.py"],
        "artifact_sha256": {},
        "files": staged_entries,
        "payload_tree_sha256": inspector._file_tree_sha(  # pyright: ignore[reportPrivateUsage]
            staged_entries
        ),
        "directories": directories,
        "directory_tree_sha256": inspector._directory_tree_sha(  # pyright: ignore[reportPrivateUsage]
            directories
        ),
        "excluded_from_manifest": [
            "payload_manifest.json",
            "private/permit.ready.json",
            "transport_inventory.json",
        ],
    }
    payload_raw = _canonical(payload)
    permit = {
        "schema_version": "nhc-phase8b-private-permit-v1",
        "authorization": {
            "one_shot": True,
            "server_write_authorized": True,
            "quantum_execution_authorized": True,
            "candidate_replacement_authorized": False,
            "second_attempt_authorized": False,
            "resume_authorized": False,
        },
        "identity": {
            **inspector.FROZEN_IDENTITY,
            "endpoint_order": ["cation", "neutral"],
            "protocol_sha256": protocol_hash,
            "request_sha256": _sha(request_raw),
            "runner_source_sha256": runner_source_sha,
            "payload_manifest_sha256": _sha(payload_raw),
            "input_sha256": input_hashes,
        },
        "resources": inspector.FROZEN_RESOURCES,
        "paths": {
            "project_root": project.as_posix(),
            "run_root": run_root.as_posix(),
            "request_path": (run_root / "input/request.json").as_posix(),
            "output_root": (run_root / "runtime/output").as_posix(),
            "payload_manifest_path": (run_root / "payload_manifest.json").as_posix(),
            "permit_ready_path": (run_root / "private/permit.ready.json").as_posix(),
            "permit_consumed_path": (run_root / "private/permit.consumed.json").as_posix(),
            "run_relative": run_relative,
            "request_relative": "input/request.json",
            "output_relative": "runtime/output",
            "payload_manifest_relative": "payload_manifest.json",
            "permit_ready_relative": "private/permit.ready.json",
            "permit_consumed_relative": "private/permit.consumed.json",
        },
    }
    permit_raw = _canonical(permit)
    transfer_entries = {
        **staged_entries,
        "payload_manifest.json": {
            "sha256": _sha(payload_raw),
            "bytes": len(payload_raw),
            "mode": "0640",
        },
        "private/permit.ready.json": {
            "sha256": _sha(permit_raw),
            "bytes": len(permit_raw),
            "mode": "0600",
        },
    }
    inventory = {
        "schema_version": "phase8b.transport_inventory.v2",
        "bundle_version": "phase8b-dft-smoke-v001",
        "payload_manifest_sha256": _sha(payload_raw),
        "permit_sha256": _sha(permit_raw),
        "files": transfer_entries,
        "transport_tree_sha256": inspector._file_tree_sha(  # pyright: ignore[reportPrivateUsage]
            transfer_entries
        ),
        "directories": directories,
        "directory_tree_sha256": inspector._directory_tree_sha(  # pyright: ignore[reportPrivateUsage]
            directories
        ),
        "excluded_from_inventory": ["transport_inventory.json"],
    }
    inventory_raw = _canonical(inventory)
    inventory_sha = _sha(inventory_raw)
    for directory, entry in directories.items():
        path = run_root if directory == "." else run_root / directory
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(int(entry["mode"], 8))
    for name, raw in staged.items():
        _write(run_root, name, raw, 0o640)
    _write(run_root, "payload_manifest.json", payload_raw, 0o640)
    _write(run_root, "transport_inventory.json", inventory_raw, 0o640)
    _write(run_root, "private/permit.consumed.json", permit_raw, 0o400)

    boot_id = "synthetic-boot-id"
    identity = {
        "pid": 2_000_000_000,
        "ppid": 1,
        "pgid": 2_000_000_000,
        "sid": 2_000_000_000,
        "starttime_ticks": 2,
        "state": "S",
        "boot_id": boot_id,
        "cpus_allowed": [0, 1, 2, 3],
    }
    receipt = {
        "schema_version": "nhc-phase8b-guardian-receipt-v1",
        "transaction_id": inspector.FROZEN_IDENTITY["attempt_id"],
        "permit_sha256": _sha(permit_raw),
        "absolute_deadline_ns": 7_201_000_000_000,
        "started_monotonic_ns": 1_000_000_000,
        "finished_monotonic_ns": 2_000_000_000,
        "outcome": "authority_failed",
        "error_code": "SyntheticAuthorityError",
        "authority_validated": False,
        "acknowledgement_published": False,
        "worker_registration_sha256": None,
        "compute_claim_sha256": None,
        "supervisor_returncode": None,
        "guardian": identity,
        "supervisor": None,
        "worker": None,
        "worker_guardian_result": None,
        "supervisor_guardian_result": None,
    }
    _write(run_root, "private/guardian_receipt.json", _canonical(receipt), 0o600)
    monkeypatch.setattr(
        inspector,
        "_process_absence",
        lambda identities, *, finished_monotonic_ns: (
            {role: "absent" for role in identities},
            {role: "absent" for role in identities},
            False,
        ),
    )
    monkeypatch.chdir(project)
    return inspector, run_root, phase7_relative, inventory_sha


def _publish_synthetic_compute_claim(inspector: ModuleType, run_root: Path) -> Path:
    inventory = cast(
        dict[str, object],
        json.loads((run_root / "transport_inventory.json").read_text(encoding="utf-8")),
    )
    payload = cast(
        dict[str, object],
        json.loads((run_root / "payload_manifest.json").read_text(encoding="utf-8")),
    )
    payload_identity = cast(dict[str, object], payload["identity"])
    permit_sha = _sha((run_root / "private/permit.consumed.json").read_bytes())
    absolute_deadline_ns = 7_201_000_000_000
    release_token_sha = "4" * 64
    boot_id = "synthetic-boot-id"

    def identity(pid: int, ppid: int, starttime_ticks: int) -> dict[str, object]:
        return {
            "pid": pid,
            "ppid": ppid,
            "pgid": pid,
            "sid": pid,
            "starttime_ticks": starttime_ticks,
            "state": "S",
            "boot_id": boot_id,
            "cpus_allowed": [0, 1, 2, 3],
        }

    guardian = identity(2_000_000_000, 1, 2)
    supervisor = identity(2_000_000_001, 2_000_000_000, 3)
    worker = identity(2_000_000_002, 2_000_000_001, 4)
    registration = {
        "schema_version": "nhc-phase8b-worker-registration-v1",
        "transaction_id": inspector.FROZEN_IDENTITY["attempt_id"],
        "absolute_deadline_ns": absolute_deadline_ns,
        "allowed_cpus": [0, 1, 2, 3],
        "release_token_sha256": release_token_sha,
        "created_monotonic_ns": 1_200_000_000,
        "guardian": guardian,
        "supervisor": supervisor,
        "worker": worker,
    }
    registration_raw = _canonical(registration)
    registration_sha = _sha(registration_raw)
    acknowledgement = {
        "schema_version": "nhc-phase8b-guardian-ack-v1",
        "transaction_id": inspector.FROZEN_IDENTITY["attempt_id"],
        "absolute_deadline_ns": absolute_deadline_ns,
        "registration_sha256": registration_sha,
        "release_token_sha256": release_token_sha,
        "created_monotonic_ns": 1_300_000_000,
        "guardian": guardian,
        "supervisor": supervisor,
        "worker": worker,
    }
    acknowledgement_raw = _canonical(acknowledgement)
    acknowledgement_sha = _sha(acknowledgement_raw)
    project_root = run_root.parents[2]
    claim = {
        "schema_version": "nhc-phase8b-compute-claim-v1",
        "transaction_id": inspector.FROZEN_IDENTITY["attempt_id"],
        "absolute_deadline_ns": absolute_deadline_ns,
        "allowed_cpus": [0, 1, 2, 3],
        "release_token_sha256": release_token_sha,
        "registration_sha256": registration_sha,
        "acknowledgement_sha256": acknowledgement_sha,
        "created_monotonic_ns": 1_400_000_000,
        "authority": {
            "transport_inventory_sha256": _sha(
                (run_root / "transport_inventory.json").read_bytes()
            ),
            "payload_manifest_sha256": inventory["payload_manifest_sha256"],
            "permit_sha256": permit_sha,
            "request_sha256": payload_identity["request_sha256"],
            "runner_source_sha256": payload_identity["runner_source_sha256"],
            "protocol_sha256": inspector.FROZEN_PROTOCOL_SHA256,
            "resources_sha256": _sha(_canonical(inspector.FROZEN_RESOURCES)),
            "cation_xyz_sha256": inspector.FROZEN_INPUT_SHA256["cation_xyz"],
            "neutral_xyz_sha256": inspector.FROZEN_INPUT_SHA256["neutral_xyz"],
            "endpoint_atom_map_sha256": inspector.FROZEN_INPUT_SHA256["endpoint_atom_map"],
            "legacy_atom_map_sha256": inspector.FROZEN_INPUT_SHA256["legacy_atom_map"],
            "geometry_validation_sha256": (
                "35e99683a32e416752014c6e1ecb8121e2bc06d5407911435e5c1250fd639f90"
            ),
            "electron_count": 120,
            "request_id": inspector.FROZEN_IDENTITY["request_id"],
            "inchikey": inspector.FROZEN_IDENTITY["inchikey"],
            "attempt_id": inspector.FROZEN_IDENTITY["attempt_id"],
            "project_root": project_root.as_posix(),
            "run_root": run_root.as_posix(),
            "request_path": (run_root / "input/request.json").as_posix(),
            "output_root": (run_root / "runtime/output").as_posix(),
        },
        "paths": {
            "registration": (run_root / "private/worker_registration.json").as_posix(),
            "acknowledgement": (run_root / "private/guardian_acknowledgement.json").as_posix(),
            "compute_claim": (run_root / "private/compute_claim.json").as_posix(),
            "receipt": (run_root / "private/guardian_receipt.json").as_posix(),
        },
        "worker_scratch_path": (
            run_root / "runtime/.worker-attempt-phase8b-qxh-v001-synthetic"
        ).as_posix(),
        "guardian": guardian,
        "supervisor": supervisor,
        "worker": worker,
    }
    claim_raw = _canonical(claim)
    receipt = {
        "schema_version": "nhc-phase8b-guardian-receipt-v1",
        "transaction_id": inspector.FROZEN_IDENTITY["attempt_id"],
        "permit_sha256": permit_sha,
        "absolute_deadline_ns": absolute_deadline_ns,
        "started_monotonic_ns": 1_000_000_000,
        "finished_monotonic_ns": 2_000_000_000,
        "outcome": "supervisor_nonzero",
        "error_code": "SyntheticSupervisorNonzero",
        "authority_validated": True,
        "acknowledgement_published": True,
        "worker_registration_sha256": registration_sha,
        "compute_claim_sha256": _sha(claim_raw),
        "supervisor_returncode": 1,
        "guardian": guardian,
        "supervisor": supervisor,
        "worker": worker,
        "worker_guardian_result": {
            "outcome": "clean",
            "trigger": "process_exit",
            "term_sent": False,
            "kill_sent": False,
            "group_cleanup_confirmed": True,
            "duration_ns": 100_000_000,
            "error_message": None,
        },
        "supervisor_guardian_result": None,
    }
    _write(run_root, "private/worker_registration.json", registration_raw, 0o600)
    _write(run_root, "private/guardian_acknowledgement.json", acknowledgement_raw, 0o600)
    claim_path = run_root / "private/compute_claim.json"
    _write(run_root, "private/compute_claim.json", claim_raw, 0o600)
    _write(run_root, "private/guardian_receipt.json", _canonical(receipt), 0o600)
    return claim_path


def test_remote_inspector_accepts_terminal_failure_without_any_log_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inspector, run_root, phase7_relative, inventory_sha = _synthetic_terminal_tree(
        tmp_path, monkeypatch
    )
    assert not list(run_root.glob("private/*.log"))
    payload = inspector.inspect_server(
        phase7_relative,
        inspector.EXPECTED_PHASE8B_RELATIVE,
        inventory_sha,
    )
    assert payload["terminal_outcome"] == "failure"
    assert payload["result"] is None
    assert payload["safety"]["logs_used_as_acceptance_evidence"] is False
    assert payload["process_cleanup"]["identity_status"] == {"guardian": "absent"}


@pytest.mark.parametrize(
    "empty_name",
    [
        "private/guardian_receipt.json",
        "runtime/output/attempts/attempt-phase8b-qxh-v001/failure.json",
    ],
)
def test_remote_inspector_rejects_empty_coordination_and_dynamic_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    empty_name: str,
) -> None:
    inspector, run_root, phase7_relative, inventory_sha = _synthetic_terminal_tree(
        tmp_path, monkeypatch
    )
    _write(run_root, empty_name, b"", 0o600)

    with pytest.raises(RuntimeError, match="file identity or size is unsafe"):
        inspector.inspect_server(
            phase7_relative,
            inspector.EXPECTED_PHASE8B_RELATIVE,
            inventory_sha,
        )


def test_remote_inspector_binds_permanent_compute_claim_and_rejects_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inspector, run_root, phase7_relative, inventory_sha = _synthetic_terminal_tree(
        tmp_path, monkeypatch
    )
    claim_path = _publish_synthetic_compute_claim(inspector, run_root)
    payload = inspector.inspect_server(
        phase7_relative,
        inspector.EXPECTED_PHASE8B_RELATIVE,
        inventory_sha,
    )
    assert payload["terminal_outcome"] == "failure"
    assert payload["runtime"]["compute_claim_sha256"] == _sha(claim_path.read_bytes())
    assert (
        payload["compute_claim"]["authority"]["request_sha256"]
        == (
            json.loads((run_root / "payload_manifest.json").read_text(encoding="utf-8"))[
                "identity"
            ]["request_sha256"]
        )
    )
    assert payload["process_cleanup"]["registered_identity_count"] == 3

    claim = cast(dict[str, object], json.loads(claim_path.read_text(encoding="utf-8")))
    authority = cast(dict[str, object], claim["authority"])
    authority["request_sha256"] = "5" * 64
    _write(run_root, "private/compute_claim.json", _canonical(claim), 0o600)
    with pytest.raises(RuntimeError, match="compute claim exact authority drifted"):
        inspector.inspect_server(
            phase7_relative,
            inspector.EXPECTED_PHASE8B_RELATIVE,
            inventory_sha,
        )


def test_remote_inspector_accepts_receipt_state_transition_across_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inspector, run_root, phase7_relative, inventory_sha = _synthetic_terminal_tree(
        tmp_path, monkeypatch
    )
    _publish_synthetic_compute_claim(inspector, run_root)
    receipt_path = run_root / "private/guardian_receipt.json"
    receipt = cast(dict[str, object], json.loads(receipt_path.read_text(encoding="utf-8")))
    guardian = cast(dict[str, object], receipt["guardian"])
    guardian["state"] = "R"
    _write(run_root, "private/guardian_receipt.json", _canonical(receipt), 0o600)

    payload = inspector.inspect_server(
        phase7_relative,
        inspector.EXPECTED_PHASE8B_RELATIVE,
        inventory_sha,
    )
    assert payload["terminal_outcome"] == "failure"
    assert payload["runtime"]["compute_claim_sha256"] is not None


def test_remote_inspector_rejects_receipt_stable_identity_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inspector, run_root, phase7_relative, inventory_sha = _synthetic_terminal_tree(
        tmp_path, monkeypatch
    )
    _publish_synthetic_compute_claim(inspector, run_root)
    receipt_path = run_root / "private/guardian_receipt.json"
    receipt = cast(dict[str, object], json.loads(receipt_path.read_text(encoding="utf-8")))
    guardian = cast(dict[str, object], receipt["guardian"])
    guardian["starttime_ticks"] = 99
    _write(run_root, "private/guardian_receipt.json", _canonical(receipt), 0o600)

    with pytest.raises(RuntimeError, match="stable identities disagree"):
        inspector.inspect_server(
            phase7_relative,
            inspector.EXPECTED_PHASE8B_RELATIVE,
            inventory_sha,
        )


def test_remote_inspector_does_not_reconstruct_null_receipt_claim_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inspector, run_root, phase7_relative, inventory_sha = _synthetic_terminal_tree(
        tmp_path, monkeypatch
    )
    _publish_synthetic_compute_claim(inspector, run_root)
    receipt_path = run_root / "private/guardian_receipt.json"
    receipt = cast(dict[str, object], json.loads(receipt_path.read_text(encoding="utf-8")))
    receipt["compute_claim_sha256"] = None
    _write(run_root, "private/guardian_receipt.json", _canonical(receipt), 0o600)

    with pytest.raises(RuntimeError, match="receipt compute claim hash drifted"):
        inspector.inspect_server(
            phase7_relative,
            inspector.EXPECTED_PHASE8B_RELATIVE,
            inventory_sha,
        )


def test_remote_inspector_rejects_reappeared_ready_permit_and_second_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inspector, run_root, phase7_relative, inventory_sha = _synthetic_terminal_tree(
        tmp_path, monkeypatch
    )
    consumed = (run_root / "private/permit.consumed.json").read_bytes()
    _write(run_root, "private/permit.ready.json", consumed, 0o600)
    with pytest.raises(RuntimeError, match="ready permit"):
        inspector.inspect_server(
            phase7_relative,
            inspector.EXPECTED_PHASE8B_RELATIVE,
            inventory_sha,
        )
    (run_root / "private/permit.ready.json").unlink()
    second = run_root / "runtime/output/attempts/attempt-phase8b-qxh-v002"
    second.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="second attempt"):
        inspector.inspect_server(
            phase7_relative,
            inspector.EXPECTED_PHASE8B_RELATIVE,
            inventory_sha,
        )


@pytest.mark.parametrize(
    ("live_boot_id", "observed_starttime"),
    [("new-boot-id", 2), ("registered-boot-id", 99)],
)
def test_process_absence_handles_reboot_and_pid_group_reuse(
    monkeypatch: pytest.MonkeyPatch,
    live_boot_id: str,
    observed_starttime: int,
) -> None:
    inspector = _load_inspector()

    class _FakeStat:
        st_uid = inspector.os.geteuid()

    class _FakeProcEntry:
        name = "300"

        @staticmethod
        def stat() -> _FakeStat:
            return _FakeStat()

    class _FakePath:
        def __init__(self, value: object) -> None:
            self.value = str(value)

        def read_text(self, *, encoding: str) -> str:
            assert self.value == "/proc/sys/kernel/random/boot_id"
            assert encoding == "ascii"
            return live_boot_id + "\n"

        def iterdir(self) -> list[_FakeProcEntry]:
            assert self.value == "/proc"
            return [_FakeProcEntry()]

    monkeypatch.setattr(inspector, "Path", _FakePath)
    monkeypatch.setattr(
        inspector,
        "_proc_stat",
        lambda pid: (500, observed_starttime) if pid == 100 else (500, 300),
    )
    monkeypatch.setattr(inspector.os, "sysconf", lambda name: 100)
    identities = {
        "guardian": {
            "pid": 100,
            "ppid": 1,
            "pgid": 500,
            "sid": 100,
            "starttime_ticks": 2,
            "state": "S",
            "boot_id": "registered-boot-id",
            "cpus_allowed": [0, 1, 2, 3],
        }
    }
    identity_status, group_status, reused = inspector._process_absence(  # pyright: ignore[reportPrivateUsage]
        identities,
        finished_monotonic_ns=2_000_000_000,
    )
    assert identity_status == {"guardian": "pid_reused"}
    assert group_status == {"guardian": "reused_after_receipt"}
    assert reused is True
