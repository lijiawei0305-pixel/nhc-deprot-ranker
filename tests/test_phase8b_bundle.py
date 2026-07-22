"""Synthetic, no-chemistry tests for the deterministic Phase 8B bundle."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from nhc_deprot_ranker.preparation import phase8b_bundle as bundle_module
from nhc_deprot_ranker.preparation.phase8b_bundle import (
    ArtifactSpec,
    Phase8BBundleError,
    Phase8BBundleNotAuthorizedError,
    _canonical_runner_source_sha256,
    _prepare_phase8b_bundle,
    prepare_phase8b_bundle,
)
from nhc_deprot_ranker.quantum import phase8b_authority as authority_module
from nhc_deprot_ranker.quantum import two_endpoint as runner


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class _Inputs:
    phase7: Path
    phase8a: Path
    source_root: Path
    source_paths: tuple[str, ...]
    source_schema: str
    source_sha256: str
    artifacts: tuple[ArtifactSpec, ...]
    phase7_inventory_sha256: str
    phase7_success_sha256: str
    phase8a_sha256: str
    remote_project_root: str


def _make_inputs(tmp_path: Path) -> _Inputs:
    phase7 = (tmp_path / "phase7").resolve()
    phase7.mkdir(parents=True)
    registered: dict[str, str] = {}
    artifact_specs: list[ArtifactSpec] = []

    phase7_templates = [
        item
        for item in bundle_module.FROZEN_ARTIFACTS
        if item.source == "phase7" and item.source_relative != "remote_inventory.json"
    ]
    for index, item in enumerate(phase7_templates, start=1):
        raw = f"synthetic Phase 7 artifact {index}: {item.source_relative}\n".encode()
        path = phase7 / item.source_relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        registered[item.source_relative] = _sha256(raw)
        artifact_specs.append(replace(item, expected_sha256=_sha256(raw)))

    inventory_raw = _json_bytes(
        {
            "schema_version": "phase7.remote_inventory.v1",
            "validation_status": "passed",
            "remote_local_hash_match": True,
            "quantum_chemistry_run": False,
            "hessian_computed": False,
            "remote_mirror_file_count": len(registered),
            "validated_candidates": 4,
            "result_tree_sha256": "b" * 64,
            "output_sha256": registered,
        }
    )
    inventory_path = phase7 / "remote_inventory.json"
    inventory_path.write_bytes(inventory_raw)
    inventory_sha256 = _sha256(inventory_raw)
    inventory_template = next(
        item
        for item in bundle_module.FROZEN_ARTIFACTS
        if item.source == "phase7" and item.source_relative == "remote_inventory.json"
    )
    artifact_specs.append(replace(inventory_template, expected_sha256=inventory_sha256))

    success_raw = _json_bytes(
        {
            "schema_version": "phase7.geometry_smoke_success.v1",
            "status": "geometry_smoke_passed",
            "remote_inventory_sha256": inventory_sha256,
            "remote_mirror_file_count": len(registered),
            "validated_candidates": 4,
            "quantum_chemistry_run": False,
            "hessian_computed": False,
            "dedicated_runner_run": False,
            "submit_hpc": False,
        }
    )
    (phase7 / "_GEOMETRY_SMOKE_SUCCESS").write_bytes(success_raw)

    phase8a_payload = {
        "schema_version": "phase8a.api_preflight.v1",
        "phase": "8A",
        "status": "passed",
        "safety": {
            "read_only": True,
            "molecule_constructed": False,
            "compute_kernel_called": False,
            "optimizer_called": False,
            "dispersion_evaluated": False,
            "hessian_computed": False,
            "server_file_written": False,
        },
        "acceptance": {"passed": True},
        "versions": {
            "geometric": "synthetic",
            "pyscf": "synthetic",
            "pyscf_dispersion": "synthetic",
            "python": "synthetic",
        },
    }
    phase8a_raw = _json_bytes(phase8a_payload)
    phase8a = (tmp_path / "PHASE8A_API_PREFLIGHT_V001.json").resolve()
    phase8a.write_bytes(phase8a_raw)
    phase8a_template = next(
        item for item in bundle_module.FROZEN_ARTIFACTS if item.source == "phase8a"
    )
    artifact_specs.append(replace(phase8a_template, expected_sha256=_sha256(phase8a_raw)))

    # Preserve the production destination order even though fixture bytes differ.
    spec_by_destination = {item.destination_relative: item for item in artifact_specs}
    artifacts = tuple(
        spec_by_destination[item.destination_relative] for item in bundle_module.FROZEN_ARTIFACTS
    )

    source_root = (tmp_path / "source").resolve()
    source_paths = ("synthetic/__init__.py", "synthetic/runner.py")
    source_bytes = {
        source_paths[0]: b'"""synthetic package"""\n',
        source_paths[1]: b"VALUE = 'synthetic runner'\n",
    }
    for name, raw in source_bytes.items():
        path = source_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    source_schema = "synthetic-runner-source-v1"
    source_sha256 = _canonical_runner_source_sha256(
        source_bytes,
        schema_version=source_schema,
        ordered_paths=source_paths,
    )
    return _Inputs(
        phase7=phase7,
        phase8a=phase8a,
        source_root=source_root,
        source_paths=source_paths,
        source_schema=source_schema,
        source_sha256=source_sha256,
        artifacts=artifacts,
        phase7_inventory_sha256=inventory_sha256,
        phase7_success_sha256=_sha256(success_raw),
        phase8a_sha256=_sha256(phase8a_raw),
        remote_project_root="/srv/nhc-project",
    )


def _synthetic_permit_renderer(
    *,
    project_root: str,
    request_sha256: str,
    runner_source_sha256: str,
    payload_manifest_sha256: str,
) -> bytes:
    return _json_bytes(
        {
            "schema_version": "synthetic-private-permit-v1",
            "project_root": project_root,
            "request_sha256": request_sha256,
            "runner_source_sha256": runner_source_sha256,
            "payload_manifest_sha256": payload_manifest_sha256,
            "one_shot": True,
        }
    )


def _build(
    inputs: _Inputs,
    output: Path,
    **overrides: Any,
) -> bundle_module.Phase8BBundleResult:
    arguments: dict[str, Any] = {
        "phase7_result_dir": inputs.phase7,
        "phase8a_evidence_path": inputs.phase8a,
        "source_root": inputs.source_root,
        "source_relative_paths": inputs.source_paths,
        "runner_source_schema_version": inputs.source_schema,
        "expected_runner_source_sha256": inputs.source_sha256,
        "protocol": {"method": "synthetic", "hessian_computed": False},
        "remote_project_root": inputs.remote_project_root,
        "output_dir": output,
        "artifacts": inputs.artifacts,
        "expected_phase7_inventory_sha256": inputs.phase7_inventory_sha256,
        "expected_phase7_success_sha256": inputs.phase7_success_sha256,
        "expected_phase8a_evidence_sha256": inputs.phase8a_sha256,
        "require_production_identity": False,
        "permit_renderer": _synthetic_permit_renderer,
    }
    arguments.update(overrides)
    with (
        patch.object(runner, "EXECUTION_AUTHORIZED", True),
        patch.object(bundle_module, "_PRODUCTION_AUTHORIZATION_CONSUMED", False),
    ):
        return _prepare_phase8b_bundle(**arguments)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_public_builder_rejects_closed_source_gate_before_any_write(tmp_path: Path) -> None:
    output = tmp_path / "must-not-exist"
    with pytest.raises(Phase8BBundleNotAuthorizedError, match="gate is closed"):
        prepare_phase8b_bundle(
            phase7_result_dir=tmp_path / "missing-phase7",
            phase8a_evidence_path=tmp_path / "missing-phase8a.json",
            source_root=tmp_path / "missing-source",
            remote_project_root="/srv/nhc-project",
            output_dir=output,
        )
    assert not output.exists()


def test_private_builder_has_no_caller_supplied_execution_gate() -> None:
    assert "source_gate_authorized" not in inspect.signature(_prepare_phase8b_bundle).parameters


def test_consumed_production_authority_cannot_be_reopened_by_gate_patch(tmp_path: Path) -> None:
    output = tmp_path / "must-not-exist"
    with (
        patch.object(runner, "EXECUTION_AUTHORIZED", True),
        pytest.raises(Phase8BBundleNotAuthorizedError, match="has been consumed"),
    ):
        prepare_phase8b_bundle(
            phase7_result_dir=tmp_path / "missing-phase7",
            phase8a_evidence_path=tmp_path / "missing-phase8a.json",
            source_root=tmp_path / "missing-source",
            remote_project_root="/srv/nhc-project",
            output_dir=output,
        )
    assert not output.exists()


def test_consumed_latch_blocks_private_bundle_seam_before_inputs_and_renderer(
    tmp_path: Path,
) -> None:
    output = tmp_path / "must-not-exist"
    renderer_called = False

    def forbidden_renderer(**kwargs: str) -> bytes:
        nonlocal renderer_called
        del kwargs
        renderer_called = True
        raise AssertionError("permit renderer must remain unreachable")

    with (
        patch.object(runner, "EXECUTION_AUTHORIZED", True),
        pytest.raises(Phase8BBundleNotAuthorizedError, match="has been consumed"),
    ):
        _prepare_phase8b_bundle(
            phase7_result_dir=tmp_path / "missing-phase7",
            phase8a_evidence_path=tmp_path / "missing-phase8a.json",
            source_root=tmp_path / "missing-source",
            source_relative_paths=(),
            runner_source_schema_version="unreachable",
            expected_runner_source_sha256="unreachable",
            protocol={},
            remote_project_root="/srv/nhc-project",
            output_dir=output,
            artifacts=(),
            expected_phase7_inventory_sha256="unreachable",
            expected_phase7_success_sha256="unreachable",
            expected_phase8a_evidence_sha256="unreachable",
            require_production_identity=False,
            permit_renderer=forbidden_renderer,
        )
    assert renderer_called is False
    assert not output.exists()


def test_production_required_source_set_is_inside_runner_hash_closure() -> None:
    from nhc_deprot_ranker.quantum import two_endpoint as runner

    assert bundle_module._REQUIRED_FINAL_SOURCE_FILES.issubset(  # pyright: ignore[reportPrivateUsage]
        runner._RUNNER_SOURCE_RELATIVE_PATHS  # pyright: ignore[reportPrivateUsage]
    )


def test_synthetic_bundle_is_deterministic_exact_and_acyclic(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path / "inputs")
    first = tmp_path / "bundle-one"
    second = tmp_path / "bundle-two"
    result = _build(inputs, first)
    repeated = _build(inputs, second)
    assert _tree_bytes(first) == _tree_bytes(second)
    assert result.request_sha256 == repeated.request_sha256
    assert result.payload_manifest_sha256 == repeated.payload_manifest_sha256
    assert result.permit_sha256 == repeated.permit_sha256
    assert result.transport_inventory_sha256 == repeated.transport_inventory_sha256

    files = _tree_bytes(first)
    payload = json.loads(files["payload_manifest.json"])
    permit = json.loads(files["private/permit.ready.json"])
    inventory = json.loads(files["transport_inventory.json"])
    request = json.loads(files["input/request.json"])

    assert request["execution_authorized"] is True
    assert request["request_id"] == bundle_module.FROZEN_REQUEST_ID
    assert request["inchikey"] == bundle_module.FROZEN_INCHIKEY
    assert request["runner_source_sha256"] == result.runner_source_sha256
    assert request["timeout_seconds"] == 7_200
    assert payload["identity"]["request_sha256"] == result.request_sha256
    assert permit["payload_manifest_sha256"] == result.payload_manifest_sha256
    assert inventory["payload_manifest_sha256"] == result.payload_manifest_sha256
    assert inventory["permit_sha256"] == result.permit_sha256
    assert payload["schema_version"] == bundle_module.PAYLOAD_MANIFEST_SCHEMA_VERSION
    assert inventory["schema_version"] == bundle_module.TRANSPORT_INVENTORY_SCHEMA_VERSION
    assert payload["directories"] == inventory["directories"]
    directory_modes = {
        name: int(entry["mode"], 8) for name, entry in inventory["directories"].items()
    }
    assert inventory["directory_tree_sha256"] == bundle_module._directory_tree_sha256(
        directory_modes
    )
    assert payload["directory_tree_sha256"] == inventory["directory_tree_sha256"]

    payload_names = set(payload["files"])
    assert "payload_manifest.json" not in payload_names
    assert "private/permit.ready.json" not in payload_names
    assert "transport_inventory.json" not in payload_names
    assert set(inventory["files"]) == set(files) - {"transport_inventory.json"}
    assert "transport_inventory" not in files["private/permit.ready.json"].decode()
    assert (
        "permit.ready"
        not in files["payload_manifest.json"].decode().split('"excluded_from_manifest"', 1)[0]
    )
    assert "payload_manifest" not in files["input/request.json"].decode()

    evidence_names = {name for name in files if name.startswith("evidence/")}
    map_names = {name for name in files if name.startswith("input/maps/")}
    assert len(evidence_names | map_names) == 8
    assert len({name for name in files if name.startswith("input/xyz/")}) == 2
    assert result.file_count == len(files)
    assert first.stat().st_mode & 0o777 == 0o700
    assert (first / "private").stat().st_mode & 0o777 == 0o700
    assert (first / "runtime").is_dir()
    assert not list((first / "runtime").iterdir())
    assert (first / "runtime").stat().st_mode & 0o777 == 0o700
    assert (first / "private/permit.ready.json").stat().st_mode & 0o777 == 0o600

    actual_directories = {"."} | {
        path.relative_to(first).as_posix() for path in first.rglob("*") if path.is_dir()
    }
    assert actual_directories == set(inventory["directories"])
    for name, entry in inventory["directories"].items():
        directory = first if name == "." else first / name
        assert directory.stat().st_mode & 0o777 == int(entry["mode"], 8)

    for name, entry in inventory["files"].items():
        assert _sha256(files[name]) == entry["sha256"]
        assert len(files[name]) == entry["bytes"]


def test_real_permit_api_forms_the_middle_hash_layer(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path / "inputs")
    output = tmp_path / "bundle"
    result = _build(inputs, output, permit_renderer=bundle_module.render_phase8b_permit)
    permit = json.loads((output / "private/permit.ready.json").read_text())
    inventory = json.loads((output / "transport_inventory.json").read_text())
    assert permit["identity"]["payload_manifest_sha256"] == result.payload_manifest_sha256
    assert permit["identity"]["request_sha256"] == result.request_sha256
    assert permit["identity"]["runner_source_sha256"] == result.runner_source_sha256
    assert inventory["permit_sha256"] == result.permit_sha256


def test_runtime_validator_rehashes_the_complete_untouched_transport_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _make_inputs(tmp_path / "inputs")
    output = tmp_path / "bundle"
    result = _build(inputs, output)
    artifact_hashes = {item.destination_relative: item.expected_sha256 for item in inputs.artifacts}
    manifest = json.loads((output / "payload_manifest.json").read_text())
    monkeypatch.setattr(authority_module, "_FROZEN_ARTIFACT_SHA256", artifact_hashes)
    monkeypatch.setattr(
        authority_module,
        "FROZEN_PROTOCOL_SHA256",
        manifest["identity"]["protocol_sha256"],
    )
    identity = authority_module.validate_phase8b_transport_bundle(
        output.resolve(),
        expected_transport_inventory_sha256=result.transport_inventory_sha256,
        expected_source_relative_paths=inputs.source_paths,
    )
    assert identity.request_sha256 == result.request_sha256
    assert identity.runner_source_sha256 == result.runner_source_sha256
    assert identity.payload_manifest_sha256 == result.payload_manifest_sha256

    drifted = output / "evidence/phase8a_api_preflight.json"
    drifted.write_bytes(drifted.read_bytes() + b"drift\n")
    drifted.chmod(0o640)
    with pytest.raises(authority_module.Phase8BAuthorityError, match="SHA256"):
        authority_module.validate_phase8b_transport_bundle(
            output.resolve(),
            expected_transport_inventory_sha256=result.transport_inventory_sha256,
            expected_source_relative_paths=inputs.source_paths,
        )


@pytest.mark.parametrize("mutation", ["drift", "extra", "missing", "symlink"])
def test_phase7_mirror_drift_is_rejected_atomically(tmp_path: Path, mutation: str) -> None:
    inputs = _make_inputs(tmp_path / "inputs")
    first_artifact = next(
        item
        for item in inputs.artifacts
        if item.source == "phase7" and item.source_relative != "remote_inventory.json"
    )
    target = inputs.phase7 / first_artifact.source_relative
    if mutation == "drift":
        target.write_bytes(target.read_bytes() + b"drift\n")
    elif mutation == "extra":
        (inputs.phase7 / "unexpected.txt").write_text("unexpected\n")
    elif mutation == "missing":
        target.unlink()
    else:
        outside = tmp_path / "outside.txt"
        outside.write_text("outside\n")
        target.unlink()
        target.symlink_to(outside)
    output = tmp_path / "bundle"
    with pytest.raises(Phase8BBundleError, match="Phase 7"):
        _build(inputs, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".bundle.tmp-*"))


def test_phase8a_and_source_hash_drift_are_rejected(tmp_path: Path) -> None:
    evidence_inputs = _make_inputs(tmp_path / "evidence-inputs")
    evidence_inputs.phase8a.write_bytes(evidence_inputs.phase8a.read_bytes() + b"drift\n")
    with pytest.raises(Phase8BBundleError, match="Phase 8A evidence SHA256"):
        _build(evidence_inputs, tmp_path / "evidence-bundle")

    source_inputs = _make_inputs(tmp_path / "source-inputs")
    (source_inputs.source_root / source_inputs.source_paths[-1]).write_text("drift = True\n")
    with pytest.raises(Phase8BBundleError, match="runner source closure SHA256"):
        _build(source_inputs, tmp_path / "source-bundle")


def test_existing_output_is_immutable_and_not_inspected(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path / "inputs")
    output = tmp_path / "bundle"
    output.mkdir()
    sentinel = output / "user.txt"
    sentinel.write_text("preserve me\n")
    with pytest.raises(FileExistsError, match="already exists"):
        _build(inputs, output)
    assert sentinel.read_text() == "preserve me\n"


def test_failure_after_hash_layers_leaves_no_output_or_temporary_tree(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path / "inputs")
    output = tmp_path / "bundle"

    def fail_permit(**_kwargs: str) -> bytes:
        raise RuntimeError("synthetic permit failure")

    with pytest.raises(RuntimeError, match="permit failure"):
        _build(inputs, output, permit_renderer=fail_permit)
    assert not output.exists()
    assert not list(tmp_path.glob(".bundle.tmp-*"))


def test_source_path_traversal_and_symlink_output_parent_are_rejected(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path / "inputs")
    with pytest.raises(Phase8BBundleError, match="canonical relative path"):
        _build(
            inputs,
            tmp_path / "traversal-bundle",
            source_relative_paths=("../outside.py",),
            expected_runner_source_sha256="f" * 64,
        )

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(Phase8BBundleError, match="output parent"):
        _build(inputs, linked_parent / "bundle")
    assert not (real_parent / "bundle").exists()


@pytest.mark.parametrize("mutation", ["extra", "missing", "runtime_mode", "root_mode"])
def test_bundle_validator_rejects_directory_set_and_mode_drift(
    tmp_path: Path, mutation: str
) -> None:
    inputs = _make_inputs(tmp_path / "inputs")
    output = tmp_path / "bundle"
    result = _build(inputs, output)
    if mutation == "extra":
        (output / "unexpected").mkdir(mode=0o750)
    elif mutation == "missing":
        (output / "runtime").rmdir()
    elif mutation == "runtime_mode":
        (output / "runtime").chmod(0o750)
    else:
        output.chmod(0o750)
    with pytest.raises(Phase8BBundleError, match=r"directory|root mode"):
        bundle_module._validate_bundle_tree(
            output,
            expected_inventory_sha256=result.transport_inventory_sha256,
        )
