"""Local-only Phase 7 portable geometry bundle tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import nhc_deprot_ranker.preparation.geometry_bundle as bundle_module
from nhc_deprot_ranker.data.provenance import sha256_file
from nhc_deprot_ranker.preparation.geometry_bundle import (
    GeometryBundleError,
    _build_canonical_input,
    _safe_file,
    prepare_geometry_smoke_bundle,
)

CANONICAL_CSV = """InChIKey,SMILES_cation,SMILES_neutral
IJWCXRPLHNQISE-UHFFFAOYSA-N,COC(=O)c1c([N+](=O)[O-])n(CC(F)(F)F)c[n+]1CC(F)(F)F,COC(=O)C1=C([N+](=O)[O-])N(CC(F)(F)F)[C]N1CC(F)(F)F
LBNPGYISTSLAHY-UHFFFAOYSA-N,N#Cc1c(C(F)(F)F)[n+](CC(F)(F)F)cn1CC(F)(F)F,N#CC1=C(C(F)(F)F)N(CC(F)(F)F)[C]N1CC(F)(F)F
QXHIEGFUWOLQIJ-UHFFFAOYSA-N,N#CCn1c[n+](CC#N)c([N+](=O)[O-])c1[N+](=O)[O-],N#CCN1[C]N(CC#N)C([N+](=O)[O-])=C1[N+](=O)[O-]
HQKHXILTVGYEGE-UHFFFAOYSA-N,O=[N+]([O-])c1c(C(F)(F)F)[n+](CC(F)(F)F)cn1CC(F)(F)F,O=[N+]([O-])C1=C(C(F)(F)F)N(CC(F)(F)F)[C]N1CC(F)(F)F
"""


def _phase6_minimal(tmp_path: Path) -> Path:
    root = tmp_path / "phase6"
    root.mkdir()
    lines = CANONICAL_CSV.splitlines()
    candidate_rows = "\n".join(lines) + "\n"
    (root / "candidates.csv").write_text(candidate_rows, encoding="utf-8", newline="")
    smoke_rows = ["InChIKey,pass_filter"]
    smoke_rows.extend(f"{line.split(',', 1)[0]},True" for line in lines[1:])
    (root / "smoke.csv").write_text("\n".join(smoke_rows) + "\n", encoding="utf-8")
    return root


def _fake_verify_phase6(**_kwargs: Any) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    return (
        {
            "smoke.csv": "0" * 64,
            "candidates.csv": "1" * 64,
            "package_manifest.json": "2" * 64,
        },
        {"gate_status": "passed"},
        {"plan_version": "v001"},
    )


def _prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, dry_run: bool = False
) -> tuple[Path, Any]:
    root = _phase6_minimal(tmp_path)
    evidence = tmp_path / "phase6_evidence.json"
    evidence.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(bundle_module, "_verify_phase6", _fake_verify_phase6)
    output = tmp_path / "geometry_smoke_bundle_vtest"
    result = prepare_geometry_smoke_bundle(
        dft_plan_dir=root,
        dft_plan_evidence_path=evidence,
        geometry_config_path=Path("configs/geometry_smoke.yaml"),
        output_dir=output,
        dry_run=dry_run,
    )
    return output, result


def test_canonical_smoke_join_has_frozen_byte_identity(tmp_path: Path) -> None:
    root = _phase6_minimal(tmp_path)
    config = bundle_module.load_geometry_smoke_config(Path("configs/geometry_smoke.yaml"))
    payload, records = _build_canonical_input(root=root, config=config)
    assert payload == CANONICAL_CSV.encode("utf-8")
    assert len(payload) == 542
    assert bundle_module._sha256_bytes(payload) == (
        "f486f93a2d58fb144c05a7340fd432334eeec46385c9319aca34d2e1b5c4cc87"
    )
    assert [record["InChIKey"] for record in records] == list(config.ordered_keys)


def test_bundle_is_portable_immutable_and_hash_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, result = _prepare(tmp_path, monkeypatch)
    assert result.payload["bundle_created"] is True
    assert result.payload["candidate_rows"] == 4
    assert result.payload["canonical_input_bytes"] == 542
    assert result.payload["geometry_generated"] is False
    assert result.payload["quantum_chemistry_run"] is False
    files = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
    assert files == {
        "_READY_FOR_REMOTE_GEOMETRY",
        "package_manifest.json",
        "input/expected_outputs.csv",
        "input/geometry_request.json",
        "input/smoke_candidates.csv",
        "tools/geometry_validation.py",
        "tools/run_legacy_m2_smoke.sh",
        "tools/validate_geometry_smoke.py",
    }
    assert (output / "input/smoke_candidates.csv").read_bytes() == CANONICAL_CSV.encode()
    assert (output / "tools/geometry_validation.py").read_bytes() == (
        bundle_module.VALIDATOR_CORE.read_bytes()
    )
    assert (output / "tools/validate_geometry_smoke.py").read_bytes() == (
        bundle_module.VALIDATOR_WRAPPER.read_bytes()
    )
    request = json.loads((output / "input/geometry_request.json").read_text())
    assert request["expected_count"] == 4
    assert request["seed"] == 42
    assert request["num_conformers"] == 10
    assert request["parallel"] == 1
    assert [row["inchikey"] for row in request["candidates"]] == request["ordered_keys"]
    manifest = json.loads((output / "package_manifest.json").read_text())
    for name, expected in manifest["output_sha256"].items():
        assert sha256_file(output / name) == expected
    ready = json.loads((output / "_READY_FOR_REMOTE_GEOMETRY").read_text())
    assert ready["package_manifest_sha256"] == sha256_file(output / "package_manifest.json")
    combined = "\n".join(path.read_text() for path in output.rglob("*") if path.is_file())
    assert "/Users/" not in combined
    assert "/home/" not in combined
    assert "ssh_alias" not in combined

    with pytest.raises(FileExistsError, match="immutable output"):
        prepare_geometry_smoke_bundle(
            dft_plan_dir=tmp_path / "phase6",
            dft_plan_evidence_path=tmp_path / "phase6_evidence.json",
            geometry_config_path=Path("configs/geometry_smoke.yaml"),
            output_dir=output,
        )


def test_run_script_contains_only_serial_m2_and_validator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, _result = _prepare(tmp_path, monkeypatch)
    script = (output / "tools/run_legacy_m2_smoke.sh").read_text()
    assert "--num-confs 10" in script
    assert "--parallel 1" in script
    assert 'set +u\nsource "$PROJECT_ROOT/env/envs/molenv.sh"\nset -u' in script
    assert 'export PYTHONPATH="$PROJECT_ROOT"' in script
    assert "export PYTHONDONTWRITEBYTECODE=1" in script
    assert 'python -B "$PROJECT_ROOT/scripts/mol/gen_3d.py"' in script
    assert 'python -B "$RUN_ROOT/tools/validate_geometry_smoke.py"' in script
    assert "gen_3d.py" in script
    assert "validate_geometry_smoke.py" in script
    assert bundle_module.SCRIPT_FORBIDDEN.search(script) is None
    assert "--delete" not in script
    assert "~/.bashrc" not in script


def test_run_script_rejects_out_of_namespace_run_roots_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, _result = _prepare(tmp_path, monkeypatch)
    script = bundle / "tools/run_legacy_m2_smoke.sh"
    project = tmp_path / "project"
    (project / "data/runs").mkdir(parents=True)
    arbitrary = project / "data/runs/arbitrary"
    arbitrary.mkdir()

    for unsafe_root in (project, arbitrary):
        completed = subprocess.run(
            ["bash", str(script), str(project), str(unsafe_root)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 72
        assert "outside the dedicated Phase 7 smoke namespace" in completed.stderr
        assert not (unsafe_root / "m2").exists()
        assert not (unsafe_root / "logs").exists()
        assert not (unsafe_root / "audit").exists()


def test_dry_run_really_validates_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, result = _prepare(tmp_path, monkeypatch, dry_run=True)
    assert result.payload["input_validated"] is True
    assert result.payload["bundle_created"] is False
    assert not output.exists()

    def reject_inputs(**_kwargs: Any) -> Any:
        raise GeometryBundleError("upstream hash mismatch")

    monkeypatch.setattr(bundle_module, "_verify_phase6", reject_inputs)
    with pytest.raises(GeometryBundleError, match="upstream hash mismatch"):
        prepare_geometry_smoke_bundle(
            dft_plan_dir=tmp_path / "phase6",
            dft_plan_evidence_path=tmp_path / "phase6_evidence.json",
            geometry_config_path=Path("configs/geometry_smoke.yaml"),
            output_dir=tmp_path / "still_absent",
            dry_run=True,
        )
    assert not (tmp_path / "still_absent").exists()


def test_canonical_join_rejects_any_smoke_change(tmp_path: Path) -> None:
    root = _phase6_minimal(tmp_path)
    smoke = root / "smoke.csv"
    smoke.write_text(smoke.read_text().replace("IJWCXRPLHNQISE", "AJWCXRPLHNQISE", 1))
    config = bundle_module.load_geometry_smoke_config(Path("configs/geometry_smoke.yaml"))
    with pytest.raises(GeometryBundleError, match="smoke key order changed"):
        _build_canonical_input(root=root, config=config)


def test_safe_registered_file_rejects_traversal_and_symlink(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private\n")
    with pytest.raises(GeometryBundleError, match="unsafe registered path"):
        _safe_file(root, "../outside.txt")
    (root / "linked.txt").symlink_to(outside)
    with pytest.raises(GeometryBundleError, match="symlink"):
        _safe_file(root, "linked.txt")


def test_overwrite_flag_is_never_accepted(tmp_path: Path) -> None:
    with pytest.raises(GeometryBundleError, match="overwrite is prohibited"):
        prepare_geometry_smoke_bundle(
            dft_plan_dir=tmp_path / "unused",
            dft_plan_evidence_path=tmp_path / "unused.json",
            geometry_config_path=Path("configs/geometry_smoke.yaml"),
            output_dir=tmp_path / "unused-output",
            overwrite=True,
        )
