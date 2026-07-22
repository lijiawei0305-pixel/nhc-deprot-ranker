"""Fixed-penalty H1 bootstrap tests."""

import numpy as np
import pandas as pd

from nhc_deprot_ranker.models.bootstrap import bootstrap_hierarchical
from nhc_deprot_ranker.validation.nested_cv import PenaltySet


def _fixture() -> tuple[pd.DataFrame, np.ndarray]:
    frame = pd.DataFrame(
        {
            "inchikey": [f"K-{index}" for index in range(12)],
            "xtb_deprot_kcal": np.linspace(50.0, 100.0, 12),
            "skeleton": ["imidazolium"] * 12,
            "axis_a_family": ["A", "A", "A", "A", "B", "B", "B", "B", "C", "C", "D", "D"],
            "axis_b_family": ["X", "Y"] * 6,
        }
    )
    target = (
        15.0
        + 0.7 * frame["xtb_deprot_kcal"].to_numpy()
        + frame["axis_a_family"].map({"A": -2.0, "B": 2.0, "C": 1.0, "D": -1.0}).to_numpy()
    )
    return frame, target


def test_hierarchical_bootstrap_is_deterministic_and_complete() -> None:
    frame, target = _fixture()
    kwargs = {
        "training_frame": frame,
        "y": target,
        "query_frame": frame,
        "penalties": PenaltySet(0.0, 10.0, 10.0),
        "lambda_slope": 0.0,
        "rho_prior": 1.0,
        "condition_number_threshold": 1e12,
        "skeleton_policy": "inactive_if_single_level",
        "repeats": 30,
        "seed": 42,
        "confidence": 0.95,
        "top_k": [3, 5],
    }
    first = bootstrap_hierarchical(**kwargs)
    second = bootstrap_hierarchical(**kwargs)
    assert first.metadata == second.metadata
    assert first.predictions.equals(second.predictions)
    assert first.family_effects.equals(second.family_effects)
    assert first.metadata["successful_repeats"] == 30
    assert first.metadata["failed_repeats"] == 0
    assert first.predictions["probability_top_3"].between(0.0, 1.0).all()
    skeleton = first.family_effects.query("term == 'skeleton'").iloc[0]
    assert skeleton["effect_mean"] == 0.0
