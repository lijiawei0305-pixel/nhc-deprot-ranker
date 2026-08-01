from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/phase9b_parent_level_p01_r1.py"
PAIRED = ROOT / "scripts/phase9b_parent_level_paired_benchmark.py"


def _load():
    spec = importlib.util.spec_from_file_location("p01_r1_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


r1 = _load()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0-3", (0, 1, 2, 3)),
        ("1-3,8,10-11", (1, 2, 3, 8, 10, 11)),
        ("7", (7,)),
    ],
)
def test_cpu_list_roundtrip(value: str, expected: tuple[int, ...]) -> None:
    assert r1.parse_cpu_list(value) == expected
    assert r1.parse_cpu_list(r1.format_cpu_list(expected)) == expected


def _topology() -> dict[int, tuple[int, int, int]]:
    return {
        0: (0, 0, 0),
        1: (0, 0, 1),
        2: (1, 1, 2),
        3: (1, 1, 3),
        4: (0, 0, 0),
        5: (0, 0, 1),
        6: (1, 1, 2),
        7: (1, 1, 3),
    }


def test_physical_and_logical_counts_are_distinct() -> None:
    topology = _topology()
    assert r1.physical_count(tuple(topology), topology) == 4
    assert r1.physical_count((0, 1, 4, 5), topology) == 2


def test_shared_node_selection_leaves_other_socket_and_active_core() -> None:
    result = r1.safe_shared_node_selection(
        allowed=tuple(range(8)), topology=_topology(), active_cpus=(0,), selected_socket=0
    )
    assert result["node_exclusive"] is False
    assert result["physical_cpu_list"] == "1"
    assert result["logical_cpu_list"] == "1,5"
    assert result["n_safe_physical"] == 1
    assert result["n_safe_logical"] == 2
    assert result["untouched_sockets"] == [1]


def test_affinity_restriction_precedes_system_count() -> None:
    result = r1.safe_shared_node_selection(
        allowed=(0, 4), topology=_topology(), active_cpus=(), selected_socket=0
    )
    assert result["n_safe_physical"] == 1
    assert result["n_safe_logical"] == 2


def test_memory_safe_uses_minimum_and_cap() -> None:
    assert r1.memory_safe_mb(available_bytes=100_000_000_000, cgroup_limit=20_000_000_000) == 16_000
    assert r1.memory_safe_mb(available_bytes=200_000_000_000, cgroup_limit=None) == 64_000


def test_thread_environment_is_unified() -> None:
    environment = r1.thread_environment(27)
    for name in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "BLIS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        assert environment[name] == "27"
    assert environment["OMP_DYNAMIC"] == "FALSE"
    assert environment["MKL_DYNAMIC"] == "FALSE"


def test_smt_threshold_is_five_percent() -> None:
    assert r1.SMT_IMPROVEMENT_FRACTION == 0.05


def test_grid_protocol_and_science_boundaries_are_frozen() -> None:
    source = SCRIPT.read_text()
    assert 'PARENT_XC: Final = "wb97m-d3bj"' in source
    assert 'PARENT_BASIS: Final = "def2-tzvpp"' in source
    assert "SCF_TOLERANCE: Final = 1.0e-9" in source
    assert "mean_field.grids.level = grid_level" in source
    assert '"grid": 4' in source
    assert '"retry": False' in source
    assert '"production_accepted": False' in source


def test_unconverged_grid_energy_cannot_reach_comparison() -> None:
    source = SCRIPT.read_text()
    convergence_guard = source.index("if not mean_field.converged")
    comparison = source.index('"energy_delta_hartree_grid4_minus_grid3"')
    assert convergence_guard < comparison


def test_no_rescue_batch_or_second_candidate() -> None:
    source = SCRIPT.read_text().lower()
    forbidden = ("x" + "tb", "g" + "fn", "dft" + "b")
    assert all(value not in source for value in forbidden)


def test_script_is_outside_production_source() -> None:
    assert SCRIPT.parent.name == "scripts"
    assert not list(ROOT.joinpath("src").glob("**/*p01_r1*"))


def test_paired_groups_bind_same_dynamic_resources() -> None:
    source = PAIRED.read_text()
    assert "GROUP_A_LIMIT_SECONDS: Final = 21600" in source
    assert "GROUP_B_LIMIT_SECONDS: Final = 86400" in source
    assert "cpu_list = _parse_cpu_list(args.cpu_list)" in source
    assert "threads=args.threads" in source
    assert "max_memory_mb=args.max_memory_mb" in source
    assert "args.cpu_list" in source


def test_paired_worker_rejects_thread_affinity_mismatch() -> None:
    spec = importlib.util.spec_from_file_location("p01_paired_r1_test", PAIRED)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    with pytest.raises(module.BenchmarkError, match="thread count exceeds CPU affinity"):
        module._configure_parent_resources(
            module=object(), root=ROOT, threads=3, cpu_list=(0, 1), memory_mb=64000
        )
