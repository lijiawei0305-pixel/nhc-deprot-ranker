from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/phase9b_aimnet2_finetune.py"
CONFIG = ROOT / "docs/PHASE9B_AIMNET2_FINETUNE_CONFIG_V001.json"
MODEL = ROOT / "docs/PHASE9B_AIMNET2_FINETUNE_MODEL_V001.yaml"
SPLIT = ROOT / "docs/PHASE9B_AIMNET2_FINETUNE_SPLIT_V002.json"


def _load():
    spec = importlib.util.spec_from_file_location("phase9b_aimnet2_finetune_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


finetune = _load()


def test_frozen_config_and_model_hashes_are_exact() -> None:
    config, _ = finetune.load_frozen_config(CONFIG, ROOT)
    assert config["base_bundle"]["sha256"] == finetune.BASE_SHA256
    assert finetune.sha256_bytes(SPLIT.read_bytes()) == finetune.SPLIT_SHA256
    assert config["training_model"]["sha256"] == finetune.sha256_bytes(MODEL.read_bytes())


def test_training_model_restores_lr_coulomb_but_excludes_external_d3() -> None:
    model = yaml.safe_load(MODEL.read_text())
    outputs = model["kwargs"]["outputs"]
    assert "lrcoulomb" in outputs
    assert "srcoulomb" not in outputs
    assert "dftd3" not in outputs
    assert outputs["lrcoulomb"]["kwargs"] == {
        "rc": 4.599999904632568,
        "key_in": "charges",
        "key_out": "energy",
        "method": "simple",
        "subtract_sr": True,
        "envelope": "exp",
    }


def test_config_is_one_shot_molecule_disjoint_and_final_test_locked() -> None:
    config = json.loads(CONFIG.read_text())
    assert config["single_training_attempt"] is True
    assert config["retry"] is False
    assert config["data"]["split_unit"] == "InChIKey"
    assert config["data"]["required_candidate_count"] == 9
    assert config["data"]["final_test_visible_before_model_freeze"] is False
    assert config["training"]["checkpoint_selection"]["final_test_involved"] is False
    assert config["post_freeze_evaluation"]["final_test_may_change_selected_model"] is False
    assert config["post_freeze_evaluation"]["speed_benchmark"] is False


def test_state_key_migration_is_exact_and_reversible() -> None:
    state = {finetune.SHORT_RANGE_KEY: "rc", "weight": "w"}
    training = finetune.migrate_base_state(state, to_training=True)
    assert training == {finetune.LONG_RANGE_KEY: "rc", "weight": "w"}
    assert finetune.migrate_base_state(training, to_training=False) == state
    with pytest.raises(finetune.FineTuneError, match="migration"):
        finetune.migrate_base_state({"weight": "w"}, to_training=True)


def test_export_metadata_rejects_external_physics_drift() -> None:
    base = {
        "format_version": 2,
        "model_yaml": "model",
        "cutoff": 5.0,
        "needs_coulomb": True,
        "needs_dispersion": True,
        "coulomb_mode": "sr_embedded",
        "coulomb_sr_rc": 4.6,
        "coulomb_sr_envelope": "exp",
        "d3_params": {"s6": 1.0, "s8": 0.3908, "a1": 0.566, "a2": 3.128},
        "has_embedded_lr": True,
        "implemented_species": [1, 6, 7],
    }
    finetune.validate_export_metadata(base, dict(base))
    drifted = dict(base)
    drifted["needs_dispersion"] = False
    with pytest.raises(finetune.FineTuneError, match="metadata"):
        finetune.validate_export_metadata(base, drifted)


def test_only_energy_head_is_trainable_and_atomic_charge_is_not_a_target() -> None:
    config = json.loads(CONFIG.read_text())
    assert config["training"]["trainable_parameter_regex"] == [r"^outputs\.energy_mlp\."]
    assert config["training"]["all_other_parameters_frozen"] is True
    assert config["data"]["x"] == ["coord", "numbers", "charge"]
    assert config["data"]["y"] == ["energy", "forces"]
    assert config["data"]["atomic_charge_target"] is False
