from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase9b_science_pilot_direct_comparison.py"
V004_ENGINE = ROOT / "scripts" / "phase9b_science_pilot_pyscf_continuation.py"


def _load_direct() -> Any:
    spec = importlib.util.spec_from_file_location(
        "phase9b_science_pilot_direct_comparison_test", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_v004(direct: Any) -> Any:
    return direct.load_exact_module(
        V004_ENGINE,
        module_name="phase9b_science_pilot_v004_test_engine",
        expected_sha256=direct.V004_CONTINUATION_SHA256,
    )


def _protocol_config(endpoint: str) -> dict[str, object]:
    charge = 1 if endpoint == "cation" else 0
    return {
        "protocol_kind": "frozen_final_scf_slice_single_point",
        "parent_protocol_reference_only": "production final_scf slice",
        "method": "B3LYP",
        "basis": "def2-SVP",
        "dispersion": "D3(BJ)",
        "d3_owner_setting": "mf.disp=d3bj",
        "grid_level": 3,
        "scf_conv_tol": 1.0e-9,
        "standard_max_cycles": 100,
        "soscf_max_cycles": 200,
        "soscf_policy": "once_only_after_typed_scf_nonconvergence",
        "initial_guess_policy": "project_does_not_override_or_pass_dm0",
        "geometry_optimization": False,
        "geometry_optimizer_invoked": False,
        "charge": charge,
        "multiplicity": 1,
        "spin": 0,
        "electron_count": 160,
        "threads": 4,
        "max_memory_mb": 12000,
        "cpu_affinity": [0, 1, 2, 3],
        "deadline_monotonic": 123.0,
        "handoff_sha256": "a" * 64,
    }


def _xyz(elements: tuple[str, ...]) -> bytes:
    lines = [str(len(elements)), "science_pilot_only synthetic exact-byte fixture"]
    lines.extend(f"{element} {index}.0 0.0 0.0" for index, element in enumerate(elements))
    return ("\n".join(lines) + "\n").encode()


def test_protocol_projection_matches_and_rejects_drift() -> None:
    direct = _load_direct()
    assisted = _protocol_config("cation")
    candidate = {
        **assisted,
        "deadline_monotonic": 999.0,
        "handoff_sha256": "b" * 64,
        "geometry_provenance": "frozen_initial",
    }

    direct.compare_protocol(direct=candidate, assisted=assisted, endpoint="cation")
    assert direct.protocol_projection(candidate) == direct.protocol_projection(assisted)

    changed = dict(candidate)
    changed["scf_conv_tol"] = 1.0e-8
    with pytest.raises(direct.ProtocolMismatchError, match="protocol mismatch"):
        direct.compare_protocol(direct=changed, assisted=assisted, endpoint="cation")

    missing = dict(candidate)
    del missing["d3_owner_setting"]
    with pytest.raises(direct.ProtocolMismatchError, match="missing protocol fields"):
        direct.protocol_projection(missing)


def test_comparison_preserves_sign_and_unavailable() -> None:
    direct = _load_direct()
    direct_endpoints = {
        "cation": {"energy_hartree": -10.0, "scf_cycles": 10, "wall_seconds": 20.0},
        "neutral": {
            "energy_hartree": -8.0,
            "scf_cycles": "unavailable",
            "wall_seconds": 40.0,
        },
    }
    assisted_endpoints = {
        "cation": {"energy_hartree": -11.0, "scf_cycles": 8, "wall_seconds": 10.0},
        "neutral": {"energy_hartree": -7.5, "scf_cycles": 9, "wall_seconds": 80.0},
    }

    endpoints, label = direct.calculate_comparison(
        direct_endpoints=direct_endpoints,
        assisted_endpoints=assisted_endpoints,
        direct_label=100.0,
        assisted_label=90.0,
    )

    cation = endpoints["cation"]
    neutral = endpoints["neutral"]
    assert cation["energy_shift_assisted_minus_direct_hartree"] == -1.0
    assert cation["cycle_delta_assisted_minus_direct"] == -2
    assert cation["wall_delta_assisted_minus_direct_seconds"] == -10.0
    assert cation["wall_ratio_direct_over_assisted"] == 2.0
    assert neutral["energy_shift_assisted_minus_direct_hartree"] == 0.5
    assert neutral["cycle_delta_assisted_minus_direct"] == "unavailable"
    assert neutral["wall_delta_assisted_minus_direct_seconds"] == 40.0
    assert neutral["wall_ratio_direct_over_assisted"] == 0.5
    assert label["label_delta_assisted_minus_direct_kcal_per_mol"] == -10.0


def test_cation_must_complete_before_neutral_and_label_requires_both() -> None:
    direct = _load_direct()
    direct.validate_endpoint_start(endpoint="cation", completed=())
    with pytest.raises(direct.DirectComparisonError, match="exactly once in order"):
        direct.validate_endpoint_start(endpoint="neutral", completed=())
    direct.validate_endpoint_start(endpoint="neutral", completed=("cation",))
    with pytest.raises(direct.DirectComparisonError, match="exactly once in order"):
        direct.validate_endpoint_start(endpoint="cation", completed=("cation",))


def test_handoff_and_protocol_failures_are_fail_not_environment_inconclusive() -> None:
    direct = _load_direct()
    fallback = SimpleNamespace(_failure_outcome=lambda _module, _exc: "INCONCLUSIVE")
    assert (
        direct.classify_runtime_failure(
            v004=fallback,
            two_endpoint=object(),
            exc=direct.DirectHandoffError("changed bytes"),
        )
        == "FAIL"
    )
    assert (
        direct.classify_runtime_failure(
            v004=fallback,
            two_endpoint=object(),
            exc=direct.ProtocolMismatchError("changed protocol"),
        )
        == "FAIL"
    )
    assert (
        direct.classify_runtime_failure(
            v004=fallback,
            two_endpoint=object(),
            exc=RuntimeError("environment unavailable"),
        )
        == "INCONCLUSIVE"
    )


@pytest.mark.parametrize(
    ("endpoint", "elements"),
    [
        (
            "cation",
            (
                "N",
                "C",
                "C",
                "C",
                "C",
                "F",
                "F",
                "F",
                "N",
                "C",
                "C",
                "F",
                "F",
                "F",
                "C",
                "N",
                "C",
                "C",
                "F",
                "F",
                "F",
                "H",
                "H",
                "H",
                "H",
                "H",
            ),
        ),
        (
            "neutral",
            (
                "N",
                "C",
                "C",
                "C",
                "C",
                "F",
                "F",
                "F",
                "N",
                "C",
                "C",
                "F",
                "F",
                "F",
                "C",
                "N",
                "C",
                "C",
                "F",
                "F",
                "F",
                "H",
                "H",
                "H",
                "H",
            ),
        ),
    ],
)
def test_direct_input_is_exact_bytes_with_frozen_atom_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    elements: tuple[str, ...],
) -> None:
    direct = _load_direct()
    v004 = _load_v004(direct)
    monkeypatch.syspath_prepend(str(ROOT / "src"))
    from nhc_deprot_ranker.quantum import two_endpoint

    raw = _xyz(elements)
    source = tmp_path / "retained_v002" / "input" / f"{endpoint}_initial.xyz"
    evidence = tmp_path / "v005" / "input" / f"{endpoint}_initial.xyz"
    parser_input = tmp_path / "v005" / "pyscf" / endpoint / "input.xyz"
    source.parent.mkdir(parents=True)
    evidence.parent.mkdir(parents=True)
    parser_input.parent.mkdir(parents=True)
    source.write_bytes(raw)
    monkeypatch.setitem(direct.DIRECT_BYTES, endpoint, len(raw))
    monkeypatch.setitem(direct.DIRECT_SHA256, endpoint, direct.sha256_bytes(raw))

    parser_raw, geometry, receipt = direct.validate_and_copy_input(
        v004=v004,
        two_endpoint=two_endpoint,
        endpoint=endpoint,
        source=source,
        evidence_copy=evidence,
        parser_input=parser_input,
    )

    assert source.read_bytes() == evidence.read_bytes() == parser_input.read_bytes() == parser_raw
    assert tuple(atom.element for atom in geometry.atoms) == elements
    assert receipt["source_sha256"] == receipt["copied_input_sha256"]
    assert receipt["copied_input_sha256"] == receipt["parser_input_sha256"]
    assert receipt["source_byte_count"] == receipt["parser_input_byte_count"] == len(raw)
    assert receipt["atom_order_sha256"] == direct.ATOM_ORDER_SHA256[endpoint]
    assert receipt["charge"] == direct.CHARGES[endpoint]
    assert receipt["multiplicity"] == 1
    assert receipt["spin"] == 0
    assert receipt["electron_count"] == 160


def _write_assisted_fixture(root: Path, direct: Any) -> None:
    result = {
        "final_outcome": "PASS",
        "handoff_status": "PASS",
        "science_pilot_only": True,
        "production_accepted": False,
        "deprotonation": {
            "value_kcal_per_mol": direct.EXPECTED_ASSISTED_LABEL,
            "aimnet2_energy_used": False,
        },
    }
    (root / "pyscf" / "cation").mkdir(parents=True)
    (root / "pyscf" / "neutral").mkdir(parents=True)
    (root / "result.json").write_bytes(direct.canonical_json(result))
    for endpoint in direct.ENDPOINTS:
        expected = direct.EXPECTED_ASSISTED[endpoint]
        endpoint_payload = {
            "status": "success",
            "scf_converged": True,
            "selected_strategy": "standard",
            "energy_hartree": expected["energy_hartree"],
            "scf_cycles": expected["scf_cycles"],
            "wall_seconds": expected["wall_seconds"],
            "charge": direct.CHARGES[endpoint],
            "multiplicity": direct.MULTIPLICITIES[endpoint],
            "spin": direct.SPINS[endpoint],
            "interpreter": {
                "before": {
                    "environment_root": "fixture-env",
                    "logical_launcher": "fixture-env/bin/python",
                    "resolved_executable": "fixture-env/bin/python3.11",
                    "resolved_executable_bytes": 25409784,
                    "resolved_executable_sha256": direct.EXPECTED_EXECUTABLE_SHA256,
                    "resolved_inside_environment_root": True,
                },
                "after": {
                    "environment_root": "fixture-env",
                    "logical_launcher": "fixture-env/bin/python",
                    "resolved_executable": "fixture-env/bin/python3.11",
                    "resolved_executable_bytes": 25409784,
                    "resolved_executable_sha256": direct.EXPECTED_EXECUTABLE_SHA256,
                    "resolved_inside_environment_root": True,
                },
                "python_version": "3.11.15",
            },
        }
        endpoint_root = root / "pyscf" / endpoint
        (endpoint_root / "endpoint_result.json").write_bytes(
            direct.canonical_json(endpoint_payload)
        )
        (endpoint_root / "run_config.json").write_bytes(
            direct.canonical_json(_protocol_config(endpoint))
        )
        (endpoint_root / "input.xyz").write_bytes(f"{endpoint} assisted bytes\n".encode())


def test_v004_assisted_reference_binds_raw_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    direct = _load_direct()
    v004 = _load_v004(direct)
    root = tmp_path / direct.V004_ROOT_NAME
    _write_assisted_fixture(root, direct)

    result_raw = (root / "result.json").read_bytes()
    monkeypatch.setattr(direct, "V004_RESULT_SHA256", direct.sha256_bytes(result_raw))
    for endpoint in direct.ENDPOINTS:
        endpoint_root = root / "pyscf" / endpoint
        monkeypatch.setitem(
            direct.V004_ENDPOINT_SHA256,
            endpoint,
            direct.sha256_bytes((endpoint_root / "endpoint_result.json").read_bytes()),
        )
        monkeypatch.setitem(
            direct.V004_RUN_CONFIG_SHA256,
            endpoint,
            direct.sha256_bytes((endpoint_root / "run_config.json").read_bytes()),
        )
        monkeypatch.setitem(
            direct.ASSISTED_INPUT_SHA256,
            endpoint,
            direct.sha256_bytes((endpoint_root / "input.xyz").read_bytes()),
        )

    bound = direct.load_assisted_reference(v004=v004, v004_root=root)

    assert bound["result"]["final_outcome"] == "PASS"
    assert bound["endpoint_payloads"]["cation"]["energy_hartree"] == pytest.approx(
        -1407.5280546795084
    )
    assert bound["endpoint_payloads"]["neutral"]["scf_cycles"] == 12
    assert bound["evidence"]["result"]["sha256"] == direct.sha256_bytes(result_raw)

    with (root / "result.json").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(direct.DirectComparisonError, match="bound evidence identity drifted"):
        direct.load_assisted_reference(v004=v004, v004_root=root)


def test_durable_manifest_excludes_driver_checkpoint_and_rejects_extra(
    tmp_path: Path,
) -> None:
    direct = _load_direct()
    v004 = _load_v004(direct)
    root = tmp_path / direct.ROOT_NAME
    (root / "input").mkdir(parents=True)
    runtime = root / "driver" / "runtime_tmp"
    runtime.mkdir(parents=True)
    (root / "driver" / "source.py").write_bytes(b"driver source\n")
    checkpoint = runtime / "tmp-pyscf-checkpoint"
    checkpoint.write_bytes(b"ephemeral checkpoint\n")
    neutral_checkpoint = runtime / "tmp-pyscf-neutral-checkpoint"
    neutral_checkpoint.write_bytes(b"ephemeral neutral checkpoint\n")
    durable = root / "input" / "cation_initial.xyz"
    durable.write_bytes(b"durable xyz\n")

    manifest = direct.durable_manifest(
        v004=v004,
        root=root,
        required_paths={"input/cation_initial.xyz"},
    )

    assert [item["relative_path"] for item in manifest["files"]] == ["input/cation_initial.xyz"]
    assert manifest["ephemeral_runtime_files_included"] is False
    diagnostic = direct.checkpoint_diagnostic(
        v004=v004,
        runtime_root=runtime,
        backend=SimpleNamespace(
            initial_guess_evidence={
                "cation:standard": {"owners": [{"chkfile_before": True, "chkfile_after": True}]}
            }
        ),
        created_by_endpoint={
            "cation": {checkpoint.name},
            "neutral": {neutral_checkpoint.name},
        },
    )
    assert diagnostic["ephemeral_checkpoint_created"] is True
    assert diagnostic["ephemeral_checkpoint_expected_to_disappear"] is True
    assert diagnostic["durable_manifest_includes_checkpoint"] is False
    assert len(diagnostic["files_observed_before_exit"]) == 2

    (root / "unexpected.json").write_bytes(b"{}\n")
    with pytest.raises(direct.DirectComparisonError, match="exact path set mismatch"):
        direct.durable_manifest(
            v004=v004,
            root=root,
            required_paths={"input/cation_initial.xyz"},
        )


def test_post_exit_audit_binds_terminal_and_reports_checkpoint_stability(
    tmp_path: Path,
) -> None:
    direct = _load_direct()
    v004 = _load_v004(direct)
    root = tmp_path / direct.ROOT_NAME
    (root / "input").mkdir(parents=True)
    runtime = root / "driver" / "runtime_tmp"
    runtime.mkdir(parents=True)
    (root / "input" / "cation_initial.xyz").write_bytes(b"durable bytes\n")
    manifest_receipt = v004.write_json_new(
        root / "file_manifest.json",
        direct.durable_manifest(
            v004=v004,
            root=root,
            required_paths={"input/cation_initial.xyz"},
        ),
    )
    v004.write_json_new(
        root / "result.json",
        {
            "evidence_bindings": {
                "durable_preterminal_manifest_sha256": manifest_receipt["sha256"],
                "durable_preterminal_manifest_bytes": manifest_receipt["bytes"],
            }
        },
    )

    audit = direct.audit_post_exit_evidence(v004=v004, root=root)
    assert audit["full_manifest_post_exit_stable"] is True
    assert audit["ephemeral_runtime_file_count_after_exit"] == 0

    (runtime / "checkpoint").write_bytes(b"ephemeral\n")
    audit_with_checkpoint = direct.audit_post_exit_evidence(v004=v004, root=root)
    assert audit_with_checkpoint["full_manifest_post_exit_stable"] is False
    assert audit_with_checkpoint["ephemeral_runtime_file_count_after_exit"] == 1


def test_direct_wrapper_reuses_v004_engine_and_has_no_chemistry_duplicate() -> None:
    direct = _load_direct()
    source = SCRIPT.read_text()
    tree = ast.parse(source)
    attribute_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert direct.sha256_bytes(V004_ENGINE.read_bytes()) == direct.V004_CONTINUATION_SHA256
    assert "build_observed_backend" in attribute_calls
    assert "run_single_point" in attribute_calls
    assert "compute_deprotonation" in attribute_calls
    assert {"RKS", "M", "_call_scf", "final_scf", "optimize"}.isdisjoint(attribute_calls)
    assert {"aimnet", "torch", "ase"}.isdisjoint(imported_roots)
    assert "geometric_solver.kernel" not in source
    assert '"aimnet2_rerun": False' in source
    assert '"pyscf_geometry_optimization": False' in source
    assert '"production_accepted": False' in source


def test_retained_v002_and_v004_private_bytes_are_unchanged_when_present() -> None:
    direct = _load_direct()
    v002_root = ROOT / "results/science_pilot_lbn_v002"
    v004_root = ROOT / "results/science_pilot_lbn_pyscf_v004"
    expected = {
        v002_root / "result.json": direct.V002_RESULT_SHA256,
        v002_root / "input/cation_initial.xyz": direct.DIRECT_SHA256["cation"],
        v002_root / "input/neutral_initial.xyz": direct.DIRECT_SHA256["neutral"],
        v002_root / "aimnet2/cation/final.xyz": direct.ASSISTED_INPUT_SHA256["cation"],
        v002_root / "aimnet2/neutral/final.xyz": direct.ASSISTED_INPUT_SHA256["neutral"],
        v004_root / "result.json": direct.V004_RESULT_SHA256,
        v004_root / "pyscf/cation/endpoint_result.json": direct.V004_ENDPOINT_SHA256["cation"],
        v004_root / "pyscf/neutral/endpoint_result.json": direct.V004_ENDPOINT_SHA256["neutral"],
        v004_root / "pyscf/cation/run_config.json": direct.V004_RUN_CONFIG_SHA256["cation"],
        v004_root / "pyscf/neutral/run_config.json": direct.V004_RUN_CONFIG_SHA256["neutral"],
    }
    observed = 0
    for path, digest in expected.items():
        if path.is_file():
            assert direct.sha256_bytes(path.read_bytes()) == digest
            observed += 1
    # The private pilot roots are present in the authorized local worktree; this
    # assertion prevents a silently vacuous history check during the real pilot.
    if v002_root.is_dir():
        assert observed == len(expected)


def test_frozen_public_identities_match_current_science_pilot_contract() -> None:
    direct = _load_direct()
    v002 = json.loads((ROOT / "docs/PHASE9B_SCIENCE_PILOT_V002_RESULT.json").read_text())
    v004 = json.loads((ROOT / "docs/PHASE9B_SCIENCE_PILOT_V004_RESULT.json").read_text())

    assert v002["inputs"]["cation"]["sha256"] == direct.DIRECT_SHA256["cation"]
    assert v002["inputs"]["neutral"]["sha256"] == direct.DIRECT_SHA256["neutral"]
    assert v004["scientific_feasibility"] == "PASS"
    assert v004["production_accepted"] is False
    assert v004["evidence"]["private_result_sha256"] == direct.V004_RESULT_SHA256
    assert v004["deprotonation"]["value_kcal_per_mol"] == direct.EXPECTED_ASSISTED_LABEL
