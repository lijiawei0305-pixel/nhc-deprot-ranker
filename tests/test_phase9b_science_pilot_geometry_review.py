from __future__ import annotations

import ast
import importlib.util
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase9b_science_pilot_geometry_review.py"


def _load_review() -> Any:
    spec = importlib.util.spec_from_file_location("phase9b_science_pilot_geometry_review", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_angle_and_kabsch_preserve_frozen_order() -> None:
    review = _load_review()
    reference = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 2.0, 0.5]])
    theta = math.radians(37.0)
    rotation = np.asarray(
        [
            [math.cos(theta), -math.sin(theta), 0.0],
            [math.sin(theta), math.cos(theta), 0.0],
            [0, 0, 1],
        ]
    )
    mobile = reference @ rotation + np.asarray([4.0, -3.0, 2.0])

    aligned, _ = review.kabsch_align(reference, mobile)

    assert np.sqrt(np.mean(np.sum((aligned - reference) ** 2, axis=1))) < 1.0e-12
    permuted, _ = review.kabsch_align(reference, mobile[[1, 0, 2, 3]])
    assert np.sqrt(np.mean(np.sum((permuted - reference) ** 2, axis=1))) > 0.1
    assert review.angle_degrees(reference, 0, 1, 2) == pytest.approx(90.0)


def test_connectivity_and_mapped_five_membered_ring() -> None:
    review = _load_review()
    ring = frozenset({(8, 14), (14, 15), (2, 15), (2, 3), (3, 8)})

    assert review.find_five_membered_ring(ring) == (8, 14, 15, 2, 3)
    assert review.neighbors(ring, 14) == (8, 15)
    assert review.connected_components(16, ring)[0] == [0]
    with pytest.raises(review.InvalidGeometryError, match="ring"):
        review.find_five_membered_ring(ring - {(2, 3)})


def test_ring_plane_and_c2_local_geometry() -> None:
    review = _load_review()
    points = np.zeros((16, 3), dtype=float)
    ring = (8, 14, 15, 2, 3)
    polygon = np.asarray(
        [
            [math.cos(2 * math.pi * index / 5), math.sin(2 * math.pi * index / 5), 0.0]
            for index in range(5)
        ]
    )
    for atom, point in zip(ring, polygon, strict=True):
        points[atom] = point
    elements = tuple("N" if index in (8, 15) else "C" for index in range(16))

    payload = review.ring_payload(elements, points, ring)

    assert payload["plane"]["rms_out_of_plane_angstrom"] < 1.0e-12
    assert abs(payload["c2_height_above_other_ring_plane_angstrom"]) < 1.0e-12
    assert payload["angle_sum_degrees"] == pytest.approx(540.0)
    assert payload["c2_two_coordinate_pyramidalization_directly_defined"] is False


def test_common_atom_mapping_removes_only_frozen_h23() -> None:
    review = _load_review()
    cation = ["C"] * 26
    cation[8] = "N"
    cation[15] = "N"
    cation[23] = "H"
    neutral = tuple(cation[:23] + cation[24:])

    assert review.cation_minus_proton_elements(cation) == neutral
    cation[23] = "C"
    with pytest.raises(review.InvalidGeometryError, match="proton"):
        review.cation_minus_proton_elements(cation)


def test_sha_mismatch_is_rejected() -> None:
    review = _load_review()
    identity = review.FileIdentity(1, 2, 0o600, 1, 3, 4)
    evidence = review.FileEvidence(
        relative_path="input/neutral_initial.xyz",
        byte_count=3,
        sha256="a" * 64,
        regular_file=True,
        symlink=False,
        before=identity,
        after=identity,
    )

    review.verify_expected_file_identity(evidence, expected_bytes=3, expected_sha256="a" * 64)
    with pytest.raises(review.InvalidGeometryError, match="identity drifted"):
        review.verify_expected_file_identity(evidence, expected_bytes=3, expected_sha256="b" * 64)


def test_read_only_file_capture_does_not_modify_source(tmp_path: Path) -> None:
    review = _load_review()
    source = tmp_path / "geometry.xyz"
    raw = b"1\nfixture\nH 0.0 0.0 0.0\n"
    source.write_bytes(raw)
    before = source.stat()

    observed, evidence = review.read_regular_file(tmp_path, "geometry.xyz")
    after = source.stat()

    assert observed == raw
    assert evidence.before == evidence.after
    assert (before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )


def test_review_source_has_no_compute_or_geometry_optimizer_imports() -> None:
    tree = ast.parse(SCRIPT.read_text())
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert imported_roots.isdisjoint(
        {"aimnet", "ase", "torch", "pyscf", "geometric", "rdkit", "xtb"}
    )
    assert "subprocess" not in imported_roots
