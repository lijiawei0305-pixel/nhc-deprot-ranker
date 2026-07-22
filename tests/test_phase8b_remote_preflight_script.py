from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/phase8b_remote_preflight.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("phase8b_remote_preflight", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase8b_preflight_source_is_static_read_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_names = {
        "Mole",
        "RKS",
        "UKS",
        "kernel",
        "optimize",
        "get_dispersion",
        "Hessian",
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert forbidden_names.isdisjoint(called_names)
    assert "subprocess" not in source
    assert "mkdir(" not in source
    assert "write_text(" not in source
    assert "write_bytes(" not in source
    for fragment in (
        '"molecule_constructed": False',
        '"kernel_called": False',
        '"gradient_called": False',
        '"dispersion_evaluated": False',
        '"hessian_called": False',
        '"target_created": False',
    ):
        assert fragment in source


def test_phase8b_preflight_has_pinned_versions_sources_and_resources() -> None:
    module = _load_script()
    assert module.EXPECTED_VERSIONS == {
        "python": "3.11.15",
        "pyscf": "2.13.1",
        "geometric": "1.1.1",
        "pyscf_dispersion": "1.5.0",
    }
    assert set(module.EXPECTED_INSTALLED_SOURCE_SHA256) == {
        "pyscf.scf.hf",
        "pyscf.scf.dispersion",
        "pyscf.grad.rhf",
        "pyscf.grad.dispersion",
        "pyscf.dispersion.dftd3",
    }
    assert frozenset({0, 1, 2, 3}) == module.FIXED_CPUS
    assert module.MIN_MEMORY_AVAILABLE_KIB == 32 * 1024 * 1024
    assert module.MIN_DISK_AVAILABLE_BYTES == 20 * 1024 * 1024 * 1024


@pytest.mark.parametrize(
    "raw",
    [
        "/data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001",
        "data/runs/../escape",
        "data/runs/wrong",
        "data//runs/nhc_deprot_ranker_phase8b_x",
    ],
)
def test_phase8b_preflight_rejects_unsafe_run_identity(raw: str) -> None:
    module = _load_script()
    with pytest.raises(ValueError, match="unsafe"):
        module._safe_run_relative(raw, phase="phase8b")


def test_phase8b_preflight_parses_online_cpu_ranges() -> None:
    module = _load_script()
    assert module._parse_cpu_list("0-3,8,10-11\n") == frozenset({0, 1, 2, 3, 8, 10, 11})
    with pytest.raises(ValueError):
        module._parse_cpu_list("3-1")
