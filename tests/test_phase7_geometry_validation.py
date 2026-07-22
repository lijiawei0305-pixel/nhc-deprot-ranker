"""Synthetic tests for the Phase 7 strong geometry validator.

The suite injects a fake chemistry adapter.  It never imports or executes RDKit and never
generates, optimizes, or otherwise computes molecular geometry.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from nhc_deprot_ranker.preparation import geometry_validation as geometry


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _graph(
    *, endpoint: str, formal_charge: int | None = None, symbols: tuple[str, ...] | None = None
) -> geometry.MoleculeGraph:
    if endpoint == "cation":
        default_symbols = ("N", "C", "N", "C", "C", "H", "H", "H")
        neighbors = (
            (1, 4),
            (0, 2, 5),
            (1, 3),
            (2, 4, 6),
            (0, 3, 7),
            (1,),
            (3,),
            (4,),
        )
        charge = 1
    else:
        default_symbols = ("N", "C", "N", "C", "C", "H", "H")
        neighbors = (
            (1, 4),
            (0, 2),
            (1, 3),
            (2, 4, 5),
            (0, 3, 6),
            (3,),
            (4,),
        )
        charge = 0
    return geometry.MoleculeGraph(
        atom_symbols=symbols or default_symbols,
        formal_charge=charge if formal_charge is None else formal_charge,
        neighbors=neighbors,
        five_membered_rings=((0, 1, 2, 3, 4),),
    )


class FakeChemistryAdapter:
    """Return deterministic hydrogen-explicit graphs for synthetic SMILES tokens."""

    version = "fake-chemistry-1.0"

    def __init__(
        self,
        *,
        cation_graph: geometry.MoleculeGraph | None = None,
        neutral_graph: geometry.MoleculeGraph | None = None,
    ) -> None:
        self.cation_graph = cation_graph or _graph(endpoint="cation")
        self.neutral_graph = neutral_graph or _graph(endpoint="neutral")

    def graph_from_smiles(self, smiles: str) -> geometry.MoleculeGraph:
        if smiles.startswith("cation-"):
            return self.cation_graph
        if smiles.startswith("neutral-"):
            return self.neutral_graph
        raise AssertionError(f"unexpected synthetic SMILES: {smiles}")


def _xyz(symbols: tuple[str, ...]) -> str:
    lines = [str(len(symbols)), "synthetic fixture; not a computed geometry"]
    lines.extend(
        f"{symbol} {index * 1.25:.6f} 0.000000 0.000000" for index, symbol in enumerate(symbols)
    )
    return "\n".join(lines) + "\n"


def _make_fixture(root: Path) -> dict[str, Path]:
    input_dir = root / "input"
    xyz_dir = root / "m2" / "xyz"
    legacy_root = root / "legacy"
    legacy_scripts = legacy_root / "scripts" / "mol"
    input_dir.mkdir(parents=True)
    xyz_dir.mkdir(parents=True)
    legacy_scripts.mkdir(parents=True)

    candidates = [
        {
            "inchikey": key,
            "smiles_cation": f"cation-{position}",
            "smiles_neutral": f"neutral-{position}",
        }
        for position, key in enumerate(geometry.PHASE7_SMOKE_KEYS, start=1)
    ]
    csv_lines = ["InChIKey,SMILES_cation,SMILES_neutral"]
    csv_lines.extend(
        f"{candidate['inchikey']},{candidate['smiles_cation']},{candidate['smiles_neutral']}"
        for candidate in candidates
    )
    input_path = input_dir / "smoke_candidates.csv"
    input_path.write_text("\n".join(csv_lines) + "\n", encoding="utf-8")

    gen_3d = legacy_scripts / "gen_3d.py"
    structure_gen = legacy_scripts / "structure_gen.py"
    gen_3d.write_text("# synthetic registered gen_3d source\n", encoding="utf-8")
    structure_gen.write_text("# synthetic registered structure source\n", encoding="utf-8")
    request: dict[str, Any] = {
        "schema_version": "phase7.geometry_request.v1",
        "request_id": "synthetic-phase7-smoke",
        "expected_count": 4,
        "ordered_keys": list(geometry.PHASE7_SMOKE_KEYS),
        "seed": 42,
        "num_conformers": 10,
        "parallel": 1,
        "embedding_method": "ETKDGv3",
        "use_random_coords": False,
        "force_field_primary": "MMFF94",
        "force_field_fallback": "UFF",
        "geometry_quality": "initial_force_field_geometry",
        "force_field_convergence": "unavailable_legacy_m2",
        "candidates": candidates,
        "input_csv": {
            "name": input_path.name,
            "sha256": _sha256(input_path),
            "bytes": input_path.stat().st_size,
            "rows": 4,
            "columns": list(geometry.INPUT_COLUMNS),
        },
        "legacy": {
            "commit": "1" * 40,
            "gen_3d": {"path": "scripts/mol/gen_3d.py", "sha256": _sha256(gen_3d)},
            "structure_gen": {
                "path": "scripts/mol/structure_gen.py",
                "sha256": _sha256(structure_gen),
            },
        },
        "expected_outputs": [
            {
                "inchikey": key,
                "cation_xyz": f"{key}_cation.xyz",
                "neutral_xyz": f"{key}_neutral.xyz",
                "legacy_atom_map": f"{key}_atom_map.json",
            }
            for key in geometry.PHASE7_SMOKE_KEYS
        ],
        "execution_scope": {
            "operation": "legacy_m2_initial_geometry_only",
            "candidate_scope": "exact_preregistered_smoke_four",
            "synchronous": True,
            "scheduler_submission": False,
        },
        "prohibitions": [
            "no_candidate_replacement_or_backfill",
            "no_xTB",
            "no_PySCF",
            "no_Hessian",
            "no_legacy_M4",
            "no_dedicated_runner_execution",
        ],
    }
    request_path = input_dir / "geometry_request.json"
    request_path.write_text(_json_text(request), encoding="utf-8")

    for key in geometry.PHASE7_SMOKE_KEYS:
        (xyz_dir / f"{key}_cation.xyz").write_text(
            _xyz(_graph(endpoint="cation").atom_symbols), encoding="utf-8"
        )
        (xyz_dir / f"{key}_neutral.xyz").write_text(
            _xyz(_graph(endpoint="neutral").atom_symbols), encoding="utf-8"
        )
        (xyz_dir / f"{key}_atom_map.json").write_text(
            _json_text({"C2_carbene": 1, "N1": 0, "N3": 2}), encoding="utf-8"
        )
    return {
        "request": request_path,
        "input": input_path,
        "xyz_dir": xyz_dir,
        "output_dir": root / "audit",
        "legacy_root": legacy_root,
    }


def _validate(paths: dict[str, Path], adapter: FakeChemistryAdapter | None = None) -> Any:
    return geometry.validate_geometry_smoke(
        request_path=paths["request"],
        input_path=paths["input"],
        xyz_dir=paths["xyz_dir"],
        chemistry_adapter=adapter or FakeChemistryAdapter(),
        legacy_root=paths["legacy_root"],
    )


def _run(paths: dict[str, Path], adapter: FakeChemistryAdapter | None = None) -> int:
    return geometry.run_geometry_validation(
        request_path=paths["request"],
        input_path=paths["input"],
        xyz_dir=paths["xyz_dir"],
        output_dir=paths["output_dir"],
        chemistry_adapter=adapter or FakeChemistryAdapter(),
        legacy_root=paths["legacy_root"],
    )


def test_phase7_passes_exact_four_keys_and_twelve_core_files(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    result = _validate(paths)

    assert result.report["validation_status"] == "passed"
    assert result.report["ordered_keys"] == list(geometry.PHASE7_SMOKE_KEYS)
    assert result.report["core_file_count"] == 12
    assert len(result.report["core_output_sha256"]) == 12
    assert result.report["runtime_versions"]["rdkit"] == "fake-chemistry-1.0"
    assert set(result.endpoint_maps) == set(geometry.PHASE7_SMOKE_KEYS)
    for endpoint_map in result.endpoint_maps.values():
        assert endpoint_map["cation"] == {"C2_carbene": 1, "N1": 0, "N3": 2}
        assert endpoint_map["neutral"] == {"C2_carbene": 1, "N1": 0, "N3": 2}


def test_phase7_run_writes_strict_atomic_report_and_corrected_maps(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    assert _run(paths) == 0

    report_path = paths["output_dir"] / "geometry_validation.json"
    raw = report_path.read_text(encoding="utf-8")
    assert "NaN" not in raw and "Infinity" not in raw
    report = json.loads(raw, parse_constant=lambda value: pytest.fail(value))
    assert report["validation_status"] == "passed"
    assert len(report["endpoint_atom_map_sha256"]) == 4
    maps = sorted((paths["output_dir"] / "endpoint_atom_maps").glob("*.json"))
    assert len(maps) == 4
    assert {path.name: _sha256(path) for path in maps} == report["endpoint_atom_map_sha256"]


def test_phase7_refuses_to_overwrite_success_report(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    assert _run(paths) == 0
    report = paths["output_dir"] / "geometry_validation.json"
    before = report.read_bytes()

    assert _run(paths) == 2
    assert report.read_bytes() == before


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("8\ncomment\nN 0 0 0\n", "line count"),
        ("8\ncomment\nN 0 0\n", "line count"),
        (None, "unrecognized element"),
        (None, "non-finite coordinate"),
        (None, "coordinate bound"),
        (None, "colliding atoms"),
    ],
)
def test_phase7_rejects_malformed_xyz(
    tmp_path: Path, replacement: str | None, message: str
) -> None:
    paths = _make_fixture(tmp_path)
    target = paths["xyz_dir"] / f"{geometry.PHASE7_SMOKE_KEYS[0]}_cation.xyz"
    if replacement is not None:
        target.write_text(replacement, encoding="utf-8")
    else:
        lines = target.read_text(encoding="utf-8").splitlines()
        if message == "unrecognized element":
            lines[2] = "Xx 0.0 0.0 0.0"
        elif message == "non-finite coordinate":
            lines[2] = "N nan 0.0 0.0"
        elif message == "coordinate bound":
            lines[2] = "N 101.0 0.0 0.0"
        else:
            lines[3] = lines[2].replace("N ", "C ", 1)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(geometry.GeometryValidationError, match=message):
        _validate(paths)


@pytest.mark.parametrize(
    ("atom_map", "message"),
    [
        ({"C2_carbene": 1, "N1": 0}, "exactly"),
        ({"C2_carbene": True, "N1": 0, "N3": 2}, "exact integer"),
        ({"C2_carbene": 99, "N1": 0, "N3": 2}, "out of range"),
        ({"C2_carbene": 1, "N1": 0, "N3": 0}, "distinct"),
        ({"C2_carbene": 0, "N1": 1, "N3": 2}, "wrong element"),
    ],
)
def test_phase7_rejects_invalid_legacy_atom_map(
    tmp_path: Path, atom_map: dict[str, object], message: str
) -> None:
    paths = _make_fixture(tmp_path)
    target = paths["xyz_dir"] / f"{geometry.PHASE7_SMOKE_KEYS[0]}_atom_map.json"
    target.write_text(_json_text(atom_map), encoding="utf-8")

    with pytest.raises(geometry.GeometryValidationError, match=message):
        _validate(paths)


def test_phase7_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    target = paths["xyz_dir"] / f"{geometry.PHASE7_SMOKE_KEYS[0]}_atom_map.json"
    target.write_text('{"C2_carbene": 1, "N1": 0, "N1": 2, "N3": 2}\n', encoding="utf-8")

    with pytest.raises(geometry.GeometryValidationError, match="duplicate key"):
        _validate(paths)


def test_phase7_rejects_symlink_and_extra_core_file(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    target = paths["xyz_dir"] / f"{geometry.PHASE7_SMOKE_KEYS[0]}_atom_map.json"
    external = tmp_path / "external.json"
    external.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    target.unlink()
    target.symlink_to(external)
    with pytest.raises(geometry.GeometryValidationError, match="symlink"):
        _validate(paths)

    target.unlink()
    target.write_text(external.read_text(encoding="utf-8"), encoding="utf-8")
    (paths["xyz_dir"] / "extra.xyz").write_text("1\nextra\nH 0 0 0\n", encoding="utf-8")
    with pytest.raises(geometry.GeometryValidationError, match="exactly the 12"):
        _validate(paths)


def test_phase7_rejects_unsafe_legacy_path_and_hash_drift(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    request = json.loads(paths["request"].read_text(encoding="utf-8"))
    request["legacy"]["gen_3d"]["path"] = "../gen_3d.py"
    paths["request"].write_text(_json_text(request), encoding="utf-8")
    with pytest.raises(geometry.GeometryValidationError, match="safe relative"):
        _validate(paths)

    paths = _make_fixture(tmp_path / "hash")
    paths["input"].write_text(paths["input"].read_text() + "\n", encoding="utf-8")
    with pytest.raises(geometry.GeometryValidationError, match="SHA256 mismatch"):
        _validate(paths)


@pytest.mark.parametrize(
    ("adapter", "message"),
    [
        (
            FakeChemistryAdapter(cation_graph=_graph(endpoint="cation", formal_charge=0)),
            "cation formal charge",
        ),
        (
            FakeChemistryAdapter(neutral_graph=_graph(endpoint="neutral", formal_charge=1)),
            "neutral formal charge",
        ),
        (
            FakeChemistryAdapter(
                neutral_graph=_graph(
                    endpoint="neutral", symbols=("N", "C", "N", "C", "O", "H", "H")
                )
            ),
            "neutral XYZ elements/order",
        ),
        (
            FakeChemistryAdapter(
                neutral_graph=replace(
                    _graph(endpoint="neutral"),
                    atom_symbols=("N", "C", "N", "C", "C", "H", "H", "H"),
                    neighbors=_graph(endpoint="cation").neighbors,
                )
            ),
            "neutral XYZ elements/order",
        ),
    ],
)
def test_phase7_rejects_endpoint_chemistry_mismatches(
    tmp_path: Path, adapter: FakeChemistryAdapter, message: str
) -> None:
    paths = _make_fixture(tmp_path)
    with pytest.raises(geometry.GeometryValidationError, match=message):
        _validate(paths, adapter)


def test_phase7_rejects_heavy_element_multiset_mismatch(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    neutral_graph = _graph(endpoint="neutral", symbols=("N", "C", "N", "C", "O", "H", "H"))
    neutral_xyz = paths["xyz_dir"] / f"{geometry.PHASE7_SMOKE_KEYS[0]}_neutral.xyz"
    neutral_xyz.write_text(_xyz(neutral_graph.atom_symbols), encoding="utf-8")

    with pytest.raises(geometry.GeometryValidationError, match="heavy-atom element multisets"):
        _validate(paths, FakeChemistryAdapter(neutral_graph=neutral_graph))


def test_phase7_rejects_more_than_one_hydrogen_difference(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    neutral_graph = replace(
        _graph(endpoint="neutral"),
        atom_symbols=_graph(endpoint="cation").atom_symbols,
        neighbors=_graph(endpoint="cation").neighbors,
    )
    neutral_xyz = paths["xyz_dir"] / f"{geometry.PHASE7_SMOKE_KEYS[0]}_neutral.xyz"
    neutral_xyz.write_text(_xyz(neutral_graph.atom_symbols), encoding="utf-8")

    with pytest.raises(geometry.GeometryValidationError, match="exactly one proton"):
        _validate(paths, FakeChemistryAdapter(neutral_graph=neutral_graph))


def test_phase7_neutral_c2_requires_shared_five_membered_ring() -> None:
    graph = geometry.MoleculeGraph(
        atom_symbols=("N", "C", "N", "C", "C", "H", "H", "C", "N", "N"),
        formal_charge=0,
        neighbors=(
            (1, 4),
            (0, 2),
            (1, 3),
            (2, 4, 5),
            (0, 3, 6),
            (3,),
            (4,),
            (8, 9),
            (7,),
            (7,),
        ),
        five_membered_rings=((0, 1, 2, 3, 4),),
    )
    geometry._validate_graph(graph, description="synthetic neutral")
    assert geometry._derive_ring_map(graph, require_c2_hydrogens=0) == {
        "C2_carbene": 1,
        "N1": 0,
        "N3": 2,
    }


def test_phase7_failure_is_nonzero_and_report_is_strict_json(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    target = paths["xyz_dir"] / f"{geometry.PHASE7_SMOKE_KEYS[0]}_cation.xyz"
    target.write_text(target.read_text().replace("0.000000", "nan", 1), encoding="utf-8")

    assert _run(paths) == 1
    report_path = paths["output_dir"] / "geometry_validation.json"
    raw = report_path.read_text(encoding="utf-8")
    assert "NaN" not in raw and "Infinity" not in raw
    report = json.loads(raw, parse_constant=lambda value: pytest.fail(value))
    assert report["validation_status"] == "failed"
    assert not (paths["output_dir"] / "endpoint_atom_maps").exists()


def test_phase7_injected_adapter_never_loads_rdkit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _make_fixture(tmp_path)

    def forbidden_loader() -> geometry.ChemistryAdapter:
        raise AssertionError("RDKit loader must not run in local synthetic tests")

    monkeypatch.setattr(geometry, "_load_rdkit_adapter", forbidden_loader)
    assert _validate(paths).report["validation_status"] == "passed"


def test_phase7_standalone_wrapper_imports_from_its_tools_directory(tmp_path: Path) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    source_root = Path(__file__).resolve().parents[1]
    module_source = source_root / "src/nhc_deprot_ranker/preparation/geometry_validation.py"
    wrapper_source = source_root / "scripts/validate_geometry_smoke.py"
    (tools_dir / "geometry_validation.py").write_bytes(module_source.read_bytes())
    (tools_dir / "validate_geometry_smoke.py").write_bytes(wrapper_source.read_bytes())
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"

    completed = subprocess.run(
        [sys.executable, str(tools_dir / "validate_geometry_smoke.py"), "--help"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "--request" in completed.stdout
