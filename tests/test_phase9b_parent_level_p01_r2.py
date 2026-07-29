from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/phase9b_parent_level_nvrtc_short_path.py"
PAIRED = ROOT / "scripts/phase9b_parent_level_paired_benchmark.py"
PILOT = ROOT / "scripts/phase9b_science_pilot.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


r2 = _load(HELPER, "p01_r2_test")
paired = _load(PAIRED, "p01_r2_paired_test")


def _private_root(tmp_path: Path) -> Path:
    root = tmp_path / "p01r2.x"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


def test_short_root_length_owner_and_mode(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    if len(root.as_posix()) > 40:
        with pytest.raises(r2.RecoveryError, match="40 characters"):
            r2.validate_short_root(root, minimum_available=0)
    else:
        assert r2.validate_short_root(root, minimum_available=0)["mode"] == "0700"
    root.chmod(0o755)
    original_limit = r2.MAXIMUM_ROOT_LENGTH
    r2.MAXIMUM_ROOT_LENGTH = 4096
    try:
        with pytest.raises(r2.RecoveryError, match="owner or mode"):
            r2.validate_short_root(root, minimum_available=0)
    finally:
        r2.MAXIMUM_ROOT_LENGTH = original_limit


def test_symlink_short_root_is_rejected(tmp_path: Path) -> None:
    target = _private_root(tmp_path)
    link = tmp_path / "p01r2.link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(r2.RecoveryError):
        r2.validate_short_root(link, minimum_available=0)


@pytest.mark.parametrize("unsafe", [Path("/"), Path("/tmp"), Path("/dev/shm"), Path("relative")])
def test_unsafe_cleanup_path_is_rejected(unsafe: Path) -> None:
    assert r2.safe_cleanup_root(unsafe) is False


def test_environment_starts_from_copy_and_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _private_root(tmp_path)
    monkeypatch.setattr(r2, "MAXIMUM_ROOT_LENGTH", 4096)
    environment = r2.build_short_environment(root, {"PRESERVED": "yes"})
    monkeypatch.setenv("TMPDIR", environment["TMPDIR"])
    monkeypatch.setattr(r2.tempfile, "tempdir", None)
    assert environment["PRESERVED"] == "yes"
    for name in r2.REQUIRED_TEMP_VARIABLES:
        assert Path(environment[name]).is_relative_to(root)
    child = r2.child_environment_probe(environment, Path(sys.executable))
    assert child["environment"] == {name: environment[name] for name in r2.REQUIRED_TEMP_VARIABLES}


def test_paired_environment_is_os_copy_and_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _private_root(tmp_path)
    monkeypatch.setattr(r2, "MAXIMUM_ROOT_LENGTH", 4096)
    environment = r2.build_short_environment(root, dict(os.environ))
    paired._validate_short_temp_environment(environment)
    escaped = dict(environment)
    escaped["TMPDIR"] = tmp_path.as_posix()
    with pytest.raises(paired.BenchmarkError, match="escaped root"):
        paired._validate_short_temp_environment(escaped)


def test_smoke_contract_has_no_optimizer_or_label() -> None:
    source = HELPER.read_text()
    smoke = source[source.index("def smoke(") : source.index("def parser(")]
    assert "evaluate_bound_smoke(" in smoke
    assert 'optimizer_started": False' in smoke
    assert 'production_label_created": False' in smoke
    assert ".optimize(" not in smoke


def test_corrected_smoke_binds_26_frozen_elements_before_runtime() -> None:
    class FakeCalculator:
        def __init__(self) -> None:
            self.bound: tuple[tuple[str, ...], tuple[tuple[float, ...], ...]] | None = None

        def new_atoms(self, *, elements, coordinates):
            self.bound = (tuple(elements), tuple(tuple(row) for row in coordinates))
            return self.bound

    class FakeBase:
        def __init__(self) -> None:
            self.calculator = FakeCalculator()

        def calculator_for(self, *, charge: int, multiplicity: int):
            assert (charge, multiplicity) == (1, 1)
            return self.calculator

    class FakeRuntime:
        @staticmethod
        def read_energy_and_forces(atoms, *, atom_count: int):
            assert atom_count == 26
            assert atoms[0]
            return -1.0, [[0.0, 0.0, 0.0] for _ in range(26)]

        @staticmethod
        def max_force(forces) -> float:
            assert len(forces) == 26
            return 0.0

    pilot = _load(PILOT, "p01_r3_pilot_parser_test")
    frozen_order = [
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
    ]
    raw = (
        "26\nfrozen-order parser test\n"
        + "".join(f"{element} {index}.0 0.0 0.0\n" for index, element in enumerate(frozen_order))
    ).encode()
    elements, coordinates = pilot._parse_xyz_minimal(raw)
    base = FakeBase()
    result = r2.evaluate_bound_smoke(
        runtime=FakeRuntime(), base=base, elements=elements, coordinates=coordinates
    )
    assert len(elements) == len(coordinates) == 26
    assert all(len(row) == 3 for row in coordinates)
    assert base.calculator.bound == (elements, coordinates)
    assert result["element_order_sha256"] == r2.ELEMENT_ORDER_SHA256


def test_empty_element_binding_is_rejected_before_runtime() -> None:
    class NeverRuntime:
        def __getattr__(self, name):
            raise AssertionError(name)

    with pytest.raises(r2.RecoveryError, match="exactly 26 atoms"):
        r2.evaluate_bound_smoke(runtime=NeverRuntime(), base=object(), elements=(), coordinates=())


def test_p01r3_cleanup_prefix_is_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert '"/dev/shm/p01r3."' in HELPER.read_text()
    root = tmp_path / "p01r3.x"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    monkeypatch.setattr(r2, "MAXIMUM_ROOT_LENGTH", 4096)
    monkeypatch.setattr(r2, "safe_cleanup_root", lambda path: path == root)
    result = r2.cleanup_short_root(root)
    assert result["temporary_directory_cleaned"] is True


def test_formal_timing_does_not_include_smoke() -> None:
    source = PAIRED.read_text()
    assert "parent-worker" in source
    assert "smoke" not in source


def test_group_b_remains_conditional_and_resources_match() -> None:
    source = PAIRED.read_text()
    assert "GROUP_A_LIMIT_SECONDS: Final = 21600" in source
    assert "GROUP_B_LIMIT_SECONDS: Final = 86400" in source
    assert 'choices=("assisted", "pure_pyscf")' in source
    assert "threads=args.threads" in source
    assert "max_memory_mb=args.max_memory_mb" in source


def test_opt_in_short_path_does_not_change_default_pilot() -> None:
    source = PILOT.read_text()
    assert 'os.environ.get("NHC_P01R2_SHORT_TMP_ROOT")' in source
    assert "else:" in source[source.index("short_root_text") : source.index("gpu =")]


def test_no_rescue_grid_rerun_extension_or_production_authority() -> None:
    source = (HELPER.read_text() + PAIRED.read_text()).lower()
    for forbidden in ("x" + "tb", "g" + "fn", "extension_assisted", "production_permit"):
        assert forbidden not in source
    assert "grid-audit" not in HELPER.read_text()
    assert 'second_pure_pyscf_candidate": False' in PAIRED.read_text()


def test_historical_r1_result_is_not_modified() -> None:
    result = ROOT / "docs/PHASE9B_PARENT_LEVEL_P01_R1_RESULT.json"
    assert result.exists()
    assert "NVRTC_TEMP_DIRECTORY_PATH_TOO_LONG" in result.read_text()
