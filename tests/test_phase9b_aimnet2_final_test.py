from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/phase9b_aimnet2_final_test.py"


def _load():
    spec = importlib.util.spec_from_file_location("phase9b_aimnet2_final_test_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


evaluator = _load()


def test_consumption_claim_precedes_every_payload_assembly_or_evaluation() -> None:
    source = SCRIPT.read_text()
    readiness_gate = source.index('readiness.get("state") != "REGISTERED"')
    claim = source.index('write_new(output_root / "consumption_claim.json"')
    dataset_process = source.index("completed = subprocess.run")
    frozen_evaluation = source.index("frozen_metrics = helper.evaluate_frozen_bundle")
    assert readiness_gate < claim < dataset_process < frozen_evaluation


def test_final_test_is_not_a_checkpoint_selection_authority() -> None:
    source = SCRIPT.read_text()
    assert '"checkpoint_selection_changed": False' in source
    assert '"thresholds_changed": False' in source
    assert '"final_test_decision": "UNADJUDICATED_THRESHOLDS_NOT_FROZEN"' in source
    assert '"production_accepted": False' in source
