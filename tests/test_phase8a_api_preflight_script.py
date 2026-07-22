"""Static no-compute contract for the streamed Phase 8A server inspector."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import cast

SCRIPT = Path("scripts/phase8a_api_preflight.py")


def test_registered_phase7_compact_tree_identity_is_reproducible() -> None:
    evidence = json.loads(
        Path("docs/GEOMETRY_SMOKE_V001_MANIFEST.json").read_text(encoding="utf-8")
    )
    output_sha256 = cast(dict[str, str], evidence["output_sha256"])
    canonical = json.dumps(
        output_sha256, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    assert len(output_sha256) == 27
    assert hashlib.sha256(canonical).hexdigest() == (
        "9b92a1f453274995661bd262e607239a86f4992bf4cc2809a311207dceadbecb"
    )


def test_script_has_no_forbidden_compute_or_write_calls() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    forbidden_attributes = {
        "M",
        "Mole",
        "RKS",
        "UKS",
        "build",
        "kernel",
        "optimize",
        "run",
        "scf",
        "newton",
        "get_dispersion",
        "do_disp",
        "Hessian",
        "write_text",
        "write_bytes",
    }
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    for call in calls:
        if isinstance(call.func, ast.Attribute):
            assert call.func.attr not in forbidden_attributes
        if isinstance(call.func, ast.Attribute) and call.func.attr == "open":
            assert call.args and isinstance(call.args[0], ast.Constant)
            assert call.args[0].value == "rb"


def test_script_records_all_no_compute_safety_flags() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for fragment in (
        '"molecule_constructed": False',
        '"mean_field_constructed": False',
        '"compute_kernel_called": False',
        '"optimizer_called": False',
        '"dispersion_evaluated": False',
        '"hessian_computed": False',
        '"server_file_written": False',
    ):
        assert fragment in source
