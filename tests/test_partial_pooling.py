"""H1 recovery, shrinkage, fallback, and serialization tests."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nhc_deprot_ranker.models.base import ModelInputError
from nhc_deprot_ranker.models.hierarchical import HierarchicalLinearCalibrator


def _factorial_fixture(repeats: int = 4) -> tuple[pd.DataFrame, np.ndarray]:
    rows: list[dict[str, object]] = []
    target: list[float] = []
    axis_a_effect = {"A-": -2.0, "A+": 2.0}
    axis_b_effect = {"B-": -1.0, "B+": 1.0}
    index = 0
    for _ in range(repeats):
        for axis_a in axis_a_effect:
            for axis_b in axis_b_effect:
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
                target.append(10.0 + 0.6 * x + axis_a_effect[axis_a] + axis_b_effect[axis_b])
                index += 1
    return pd.DataFrame.from_records(rows), np.asarray(target)


def _fit(
    frame: pd.DataFrame,
    target: np.ndarray,
    *,
    lambda_axis_a: float,
    lambda_axis_b: float,
) -> HierarchicalLinearCalibrator:
    return HierarchicalLinearCalibrator(
        lambda_skeleton=0.0,
        lambda_axis_a=lambda_axis_a,
        lambda_axis_b=lambda_axis_b,
    ).fit(frame, target)


def test_h1_recovers_known_additive_effects_and_inactive_skeleton() -> None:
    frame, target = _factorial_fixture()
    model = _fit(frame, target, lambda_axis_a=1e-8, lambda_axis_b=1e-8)
    coefficients = model.get_coefficients()
    assert coefficients["beta_0"] == pytest.approx(10.0, abs=1e-5)
    assert coefficients["rho"] == pytest.approx(0.6, abs=1e-7)
    effects = model.family_effects().set_index(["term", "level"])
    assert effects.loc[("axis_a_family", "A+"), "effect_kcal"] == pytest.approx(2.0, abs=1e-5)
    assert effects.loc[("axis_a_family", "A-"), "effect_kcal"] == pytest.approx(-2.0, abs=1e-5)
    assert effects.loc[("skeleton", "imidazolium"), "effect_kcal"] == 0.0
    assert effects.loc[("skeleton", "imidazolium"), "status"] == "inactive_single_level"


def test_rare_family_shrinks_more_than_supported_family() -> None:
    rows: list[dict[str, object]] = []
    target: list[float] = []
    index = 0
    for family, support, effect in (("common+", 20, 3.0), ("common-", 20, -3.0), ("rare+", 1, 3.0)):
        for _ in range(support):
            x = 60.0 + index
            rows.append(
                {
                    "inchikey": f"R-{index:03d}",
                    "xtb_deprot_kcal": x,
                    "skeleton": "imidazolium",
                    "axis_a_family": family,
                    "axis_b_family": "B",
                }
            )
            target.append(20.0 + 0.5 * x + effect)
            index += 1
    frame = pd.DataFrame.from_records(rows)
    model = _fit(frame, np.asarray(target), lambda_axis_a=10.0, lambda_axis_b=10.0)
    effects = model.family_effects().query("term == 'axis_a_family'").set_index("level")
    assert abs(effects.loc["rare+", "effect_kcal"]) < abs(effects.loc["common+", "effect_kcal"])


def test_larger_lambda_drives_family_effects_toward_zero() -> None:
    frame, target = _factorial_fixture()
    weak = _fit(frame, target, lambda_axis_a=0.1, lambda_axis_b=0.1)
    strong = _fit(frame, target, lambda_axis_a=1000.0, lambda_axis_b=1000.0)
    weak_norm = float(np.linalg.norm(weak.family_effects()["effect_kcal"]))
    strong_norm = float(np.linalg.norm(strong.family_effects()["effect_kcal"]))
    assert strong_norm < weak_norm * 0.1


def test_lambda_zero_matches_unpenalized_training_predictions() -> None:
    frame, target = _factorial_fixture()
    model = _fit(frame, target, lambda_axis_a=0.0, lambda_axis_b=0.0)
    assert model.predict(frame) == pytest.approx(target, abs=1e-9)
    assert model.get_coefficients()["solver"]["used_pseudoinverse"] is True


def test_unseen_families_have_zero_effect_and_finite_prediction() -> None:
    frame, target = _factorial_fixture()
    model = _fit(frame, target, lambda_axis_a=10.0, lambda_axis_b=10.0)
    query = pd.DataFrame.from_records(
        [
            {
                "inchikey": "UNSEEN",
                "xtb_deprot_kcal": 80.0,
                "skeleton": "other_skeleton",
                "axis_a_family": "unseen_a",
                "axis_b_family": "unseen_b",
            }
        ]
    )
    components = model.predict_components(query).iloc[0]
    assert components["skeleton_effect"] == 0.0
    assert components["axis_a_effect"] == 0.0
    assert components["axis_b_effect"] == 0.0
    assert components["skeleton_known"] is False or not components["skeleton_known"]
    assert np.isfinite(components["final_prediction"])


def test_h1_roundtrip_predictions_are_identical(tmp_path: Path) -> None:
    frame, target = _factorial_fixture()
    model = _fit(frame, target, lambda_axis_a=10.0, lambda_axis_b=10.0)
    path = tmp_path / "h1.pkl"
    model.save(path)
    loaded = HierarchicalLinearCalibrator.load(path)
    assert np.array_equal(model.predict(frame), loaded.predict(frame))


def test_h1_rejects_bad_inputs() -> None:
    frame, target = _factorial_fixture()
    duplicated = frame.copy()
    duplicated.loc[1, "inchikey"] = duplicated.loc[0, "inchikey"]
    with pytest.raises(ModelInputError, match="unique"):
        _fit(duplicated, target, lambda_axis_a=1.0, lambda_axis_b=1.0)
    nonfinite = frame.copy()
    nonfinite.loc[0, "xtb_deprot_kcal"] = np.nan
    with pytest.raises(ModelInputError, match="non-finite"):
        _fit(nonfinite, target, lambda_axis_a=1.0, lambda_axis_b=1.0)
    constant = frame.copy()
    constant["xtb_deprot_kcal"] = 1.0
    with pytest.raises(ModelInputError, match="nonzero finite xTB scale"):
        _fit(constant, target, lambda_axis_a=1.0, lambda_axis_b=1.0)
