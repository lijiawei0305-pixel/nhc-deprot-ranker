#!/usr/bin/env python3
"""Remote, read-only static API inspection for Phase 8A.

This file is streamed to ``python -B -`` after the established molecular
environment is sourced.  It deliberately constructs no molecule or mean-field
object and calls no chemistry, optimization, dispersion, SCF or Hessian kernel.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.metadata
import inspect
import json
import platform
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, Final

SCHEMA_VERSION: Final = "phase8a.api_preflight.v1"
EXPECTED_PHASE7_FILE_COUNT: Final = 27
# Canonical compact-JSON SHA256 of the exact 27 path->content-SHA256 entries
# registered in docs/GEOMETRY_SMOKE_V001_MANIFEST.json.
EXPECTED_PHASE7_CANONICAL_TREE_SHA256: Final = (
    "9b92a1f453274995661bd262e607239a86f4992bf4cc2809a311207dceadbecb"
)
EXPECTED_PHASE7_REPORTED_TREE_SHA256: Final = (
    "644f027e276902dc1ab105f02f08864967f69ae87dc8883f608f5e4d17a372ad"
)
EXPECTED_SOURCE_SHA256: Final[dict[str, str]] = {
    "molenv": "e9b3e124f53a10e84c43cfc71a56af3ddd56a86f082610593d2b23ed9692ea6f",
    "legacy_gen_3d": "d23c7ad9a6e35948949f6485b53caafb0f3f5705148f642e3a4a30fb589a946a",
    "legacy_structure_gen": "a50b50b9967ac9e8203b398fe69f3daebf40a144f37dae8e0aa086e613ad1365",
}
SOURCE_PATHS: Final[dict[str, str]] = {
    "molenv": "env/envs/molenv.sh",
    "legacy_gen_3d": "scripts/mol/gen_3d.py",
    "legacy_structure_gen": "scripts/mol/structure_gen.py",
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_sha256(obj: Any) -> str:
    return _sha256_bytes(inspect.getsource(obj).encode("utf-8"))


def _safe_phase7_relative(raw: str) -> PurePosixPath:
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or ".." in path.parts
        or len(path.parts) != 3
        or path.parts[:2] != ("data", "runs")
        or not path.parts[-1].startswith("nhc_deprot_ranker_phase7_smoke_")
        or path.as_posix() != raw
    ):
        raise ValueError("unsafe Phase 7 run identity")
    return path


def _tree_snapshot(root: Path) -> tuple[int, str]:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("Phase 7 root is missing or unsafe")
    mapping: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("Phase 7 tree contains a symlink")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            mapping[relative] = _sha256_file(path)
    canonical = json.dumps(
        mapping, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return len(mapping), _sha256_bytes(canonical)


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _import(name: str) -> ModuleType:
    module = importlib.import_module(name)
    if not isinstance(module, ModuleType):
        raise TypeError(f"{name} did not resolve to a module")
    return module


def _kernel_returns_convergence_pair(function: Any) -> bool:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Tuple):
            continue
        if len(node.value.elts) != 2:
            continue
        first, second = node.value.elts
        if (
            isinstance(first, ast.Name)
            and first.id == "conv"
            and isinstance(second, ast.Attribute)
            and second.attr == "mol"
        ):
            return True
    return False


def _optimize_discards_convergence_flag(function: Any) -> bool:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Subscript):
            continue
        call = node.value.value
        index = node.value.slice
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "kernel"
            and isinstance(index, ast.Constant)
            and index.value == 1
        ):
            return True
    return False


def _static_callable(owner: object, name: str) -> tuple[Any, bool]:
    attribute = inspect.getattr_static(owner, name)
    return attribute, callable(attribute)


def inspect_api(phase7_relative: str) -> dict[str, object]:
    """Inspect installed symbols without constructing or executing chemistry objects."""

    if Path.cwd().is_symlink():
        raise RuntimeError("project root must not be a symlink")
    phase7_root = Path(*_safe_phase7_relative(phase7_relative).parts)
    before_count, before_tree = _tree_snapshot(phase7_root)
    source_before = {
        logical_name: _sha256_file(Path(relative_path))
        for logical_name, relative_path in SOURCE_PATHS.items()
    }

    pyscf = _import("pyscf")
    geometric = _import("geometric")
    geometric_solver = _import("pyscf.geomopt.geometric_solver")
    hf = _import("pyscf.scf.hf")
    scf_dispersion = _import("pyscf.scf.dispersion")
    dft = _import("pyscf.dft")
    dft_rks = _import("pyscf.dft.rks")
    dftd3 = _import("pyscf.dispersion.dftd3")
    newton_ah = _import("pyscf.soscf.newton_ah")

    kernel = vars(geometric_solver)["kernel"]
    optimize = vars(geometric_solver)["optimize"]
    scf_class = vars(hf)["SCF"]
    public_rks = vars(dft)["RKS"]
    rks_implementation_class = vars(dft_rks)["RKS"]
    adapter_class = vars(dftd3)["DFTD3Dispersion"]
    damping_map = vars(dftd3)["_load_damping_param"]
    dispersion_versions = vars(scf_dispersion)["DISP_VERSIONS"]
    dispersion_check = vars(scf_dispersion)["check_disp"]
    dispersion_get = vars(scf_dispersion)["get_dispersion"]
    newton_function = vars(newton_ah)["newton"]
    do_disp, do_disp_callable = _static_callable(scf_class, "do_disp")
    newton, newton_callable = _static_callable(scf_class, "newton")
    get_dispersion, get_dispersion_callable = _static_callable(scf_class, "get_dispersion")

    source_after = {
        logical_name: _sha256_file(Path(relative_path))
        for logical_name, relative_path in SOURCE_PATHS.items()
    }
    after_count, after_tree = _tree_snapshot(phase7_root)

    checks = {
        "phase7_exact_file_count": before_count == EXPECTED_PHASE7_FILE_COUNT,
        "phase7_registered_tree_matches": (before_tree == EXPECTED_PHASE7_CANONICAL_TREE_SHA256),
        "phase7_tree_unchanged": (before_count, before_tree) == (after_count, after_tree),
        "registered_sources_match": source_before == EXPECTED_SOURCE_SHA256,
        "registered_sources_unchanged": source_before == source_after,
        "geometric_kernel_has_required_parameters": {
            "assert_convergence",
            "maxsteps",
            "method",
        }.issubset(inspect.signature(kernel).parameters),
        "geometric_kernel_returns_pair": _kernel_returns_convergence_pair(kernel),
        "geometric_optimize_discards_flag": _optimize_discards_convergence_flag(optimize),
        "public_rks_is_callable": callable(public_rks),
        "public_rks_signature_has_mol": "mol" in inspect.signature(public_rks).parameters,
        "rks_implementation_is_scf_subclass": (
            inspect.isclass(rks_implementation_class)
            and inspect.isclass(scf_class)
            and issubclass(rks_implementation_class, scf_class)
        ),
        "scf_static_hooks_callable": all(
            (do_disp_callable, newton_callable, get_dispersion_callable)
        ),
        "scf_dispersion_aliases_match": (
            do_disp is dispersion_check and get_dispersion is dispersion_get
        ),
        "d3bj_in_scf_supported_versions": "d3bj" in dispersion_versions,
        "d3bj_in_adapter_damping_map": isinstance(damping_map, dict) and "d3bj" in damping_map,
        "d3_adapter_is_class": inspect.isclass(adapter_class),
        "d3_adapter_signature_has_required_parameters": {
            "mol",
            "xc",
            "version",
        }.issubset(inspect.signature(adapter_class.__init__).parameters),
        "newton_function_is_static_only": callable(newton_function),
    }
    passed = all(checks.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "8A",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "status": "passed" if passed else "failed",
        "safety": {
            "read_only": True,
            "module_imports_only": True,
            "molecule_constructed": False,
            "mean_field_constructed": False,
            "compute_kernel_called": False,
            "optimizer_called": False,
            "dispersion_evaluated": False,
            "hessian_computed": False,
            "server_file_written": False,
        },
        "versions": {
            "python": platform.python_version(),
            "pyscf": _distribution_version("pyscf") or vars(pyscf).get("__version__"),
            "geometric": _distribution_version("geometric") or vars(geometric).get("__version__"),
            "pyscf_dispersion": _distribution_version("pyscf-dispersion"),
        },
        "imports": {
            "pyscf": True,
            "geometric": True,
            "geometric_solver": True,
            "scf_hf": True,
            "scf_dispersion": True,
            "dft": True,
            "dft_rks_implementation": True,
            "dftd3_adapter": True,
            "newton_ah": True,
        },
        "phase7_integrity": {
            "registered_file_count": before_count,
            "canonical_tree_sha256": before_tree,
            "reported_phase7_tree_sha256": EXPECTED_PHASE7_REPORTED_TREE_SHA256,
            "before_after_match": (before_count, before_tree) == (after_count, after_tree),
            "registered_sources_match": source_before == EXPECTED_SOURCE_SHA256,
            "registered_sources_before_after_match": source_before == source_after,
        },
        "geometric": {
            "kernel_signature": str(inspect.signature(kernel)),
            "optimize_signature": str(inspect.signature(optimize)),
            "kernel_source_sha256": _source_sha256(kernel),
            "optimize_source_sha256": _source_sha256(optimize),
            "kernel_returns_convergence_pair": _kernel_returns_convergence_pair(kernel),
            "optimize_discards_convergence_flag": _optimize_discards_convergence_flag(optimize),
        },
        "scf": {
            "public_rks_signature": str(inspect.signature(public_rks)),
            "public_rks_is_callable": checks["public_rks_is_callable"],
            "rks_implementation_is_scf_subclass": checks["rks_implementation_is_scf_subclass"],
            "do_disp_signature": str(inspect.signature(do_disp)),
            "newton_signature": str(inspect.signature(newton)),
            "get_dispersion_signature": str(inspect.signature(get_dispersion)),
            "newton_function_signature": str(inspect.signature(newton_function)),
            "do_disp_alias_matches": do_disp is dispersion_check,
            "get_dispersion_alias_matches": get_dispersion is dispersion_get,
        },
        "dispersion": {
            "supported_versions": sorted(str(item) for item in dispersion_versions),
            "d3bj_supported": "d3bj" in dispersion_versions,
            "adapter_class": "pyscf.dispersion.dftd3.DFTD3Dispersion",
            "adapter_init_signature": str(inspect.signature(adapter_class.__init__)),
            "adapter_damping_keys": sorted(str(item) for item in damping_map),
            "adapter_source_sha256": _source_sha256(adapter_class),
        },
        "acceptance": {"checks": checks, "passed": passed},
    }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: phase8a_api_preflight.py PHASE7_RUN_RELATIVE")
    payload = inspect_api(sys.argv[1])
    print(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
