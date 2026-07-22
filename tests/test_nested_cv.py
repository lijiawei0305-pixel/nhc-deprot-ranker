"""Finite H1 penalty search tests."""

from pathlib import Path

import numpy as np
import pandas as pd

from nhc_deprot_ranker.config import load_hierarchical_model_config
from nhc_deprot_ranker.validation.nested_cv import select_hierarchical_penalties
from nhc_deprot_ranker.validation.splits import hashed_kfolds


def _factorial_fixture(repeats: int) -> tuple[pd.DataFrame, np.ndarray]:
    rows: list[dict[str, object]] = []
    target: list[float] = []
    index = 0
    for _ in range(repeats):
        for axis_a, effect_a in (("A-", -2.0), ("A+", 2.0)):
            for axis_b, effect_b in (("B-", -1.0), ("B+", 1.0)):
                x = 50.0 + index * 2.5
                rows.append(
                    {
                        "inchikey": f"KEY-{index:03d}",
                        "xtb_deprot_kcal": x,
                        "skeleton": "imidazolium",
                        "axis_a_family": axis_a,
                        "axis_b_family": axis_b,
                    }
                )
                target.append(10.0 + 0.6 * x + effect_a + effect_b)
                index += 1
    return pd.DataFrame.from_records(rows), np.asarray(target)


def test_nested_search_is_finite_and_deterministic() -> None:
    frame, target = _factorial_fixture(repeats=3)
    config = load_hierarchical_model_config(Path("configs/model.yaml"))
    folds = hashed_kfolds(keys=frame["inchikey"].tolist(), n_splits=3, seed=7, protocol="inner")
    first = select_hierarchical_penalties(frame=frame, y=target, inner_folds=folds, config=config)
    second = select_hierarchical_penalties(frame=frame, y=target, inner_folds=folds, config=config)
    assert first.selected == second.selected
    assert first.selected_rmse == second.selected_rmse
    assert len(first.candidates) <= 14
    assert all(record["status"] == "complete" for record in first.candidates)


def test_nested_scaling_uses_each_inner_training_fold_only() -> None:
    frame, target = _factorial_fixture(repeats=3)
    config = load_hierarchical_model_config(Path("configs/model.yaml"))
    folds = hashed_kfolds(keys=frame["inchikey"].tolist(), n_splits=3, seed=9, protocol="inner")
    result = select_hierarchical_penalties(frame=frame, y=target, inner_folds=folds, config=config)
    first_candidate = result.candidates[0]
    for fold_record, fold in zip(first_candidate["folds"], folds, strict=True):
        expected = float(
            np.mean(frame.iloc[list(fold.train_indices)]["xtb_deprot_kcal"].to_numpy())
        )
        assert fold_record["train_x_mean"] == expected
