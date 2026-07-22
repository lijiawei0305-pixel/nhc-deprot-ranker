"""B0/B1 estimator and coefficient-bootstrap tests."""

from pathlib import Path

import joblib
import numpy as np
import pytest

from nhc_deprot_ranker.models.affine import AffineCalibrator
from nhc_deprot_ranker.models.base import ModelInputError
from nhc_deprot_ranker.models.bootstrap import bootstrap_affine
from nhc_deprot_ranker.models.registry import BaselineModelBundle
from nhc_deprot_ranker.models.xtb_baseline import XtbBaseline


def _fixture() -> tuple[np.ndarray, np.ndarray, list[str]]:
    x = np.asarray([40.0, 50.0, 63.0, 79.0, 95.0, 120.0])
    y = 12.5 + 0.72 * x
    keys = [f"KEY-{index}" for index in range(len(x))]
    return x, y, keys


def test_b0_is_identity_and_records_range() -> None:
    x, _, keys = _fixture()
    model = XtbBaseline().fit(x, keys)
    assert model.predict(x).tolist() == x.tolist()
    assert model.metadata()["x_min"] == 40.0
    assert model.metadata()["lower_is_better"] is True


def test_affine_recovers_free_intercept_and_slope() -> None:
    x, y, keys = _fixture()
    model = AffineCalibrator().fit(x, y, keys)
    assert model.intercept_ == pytest.approx(12.5, abs=1e-10)
    assert model.slope_ == pytest.approx(0.72, abs=1e-12)
    assert model.slope_ != 1.0
    assert model.predict([55.0]).item() == pytest.approx(52.1)
    assert model.rank_ == 2
    assert model.used_pseudoinverse_ is False


def test_affine_rejects_degenerate_and_nonfinite_inputs() -> None:
    keys = ["A", "B", "C"]
    with pytest.raises(ModelInputError, match="nonzero x variance"):
        AffineCalibrator().fit([1.0, 1.0, 1.0], [2.0, 3.0, 4.0], keys)
    with pytest.raises(ModelInputError, match="non-finite"):
        AffineCalibrator().fit([1.0, 2.0, np.nan], [2.0, 3.0, 4.0], keys)


def test_affine_records_pseudoinverse_fallback_when_threshold_requires_it() -> None:
    x, y, keys = _fixture()
    model = AffineCalibrator(condition_number_threshold=2.0).fit(x, y, keys)
    assert model.used_pseudoinverse_ is True
    assert model.intercept_ == pytest.approx(12.5, abs=1e-10)
    assert model.slope_ == pytest.approx(0.72, abs=1e-12)


def test_bootstrap_is_seed_deterministic() -> None:
    x, y, keys = _fixture()
    first = bootstrap_affine(
        x=x,
        y=y,
        keys=keys,
        repeats=30,
        seed=7,
        confidence=0.95,
        min_samples=3,
        condition_number_threshold=1e12,
    )
    second = bootstrap_affine(
        x=x,
        y=y,
        keys=keys,
        repeats=30,
        seed=7,
        confidence=0.95,
        min_samples=3,
        condition_number_threshold=1e12,
    )
    assert first.summary == second.summary
    assert first.replicates.equals(second.replicates)
    assert first.summary["successful_repeats"] == 30


def test_model_bundle_roundtrip_predictions_are_identical(tmp_path: Path) -> None:
    x, y, keys = _fixture()
    bundle = BaselineModelBundle(
        dataset_version="vtest",
        model_version="vtest",
        b0=XtbBaseline().fit(x, keys),
        b1=AffineCalibrator().fit(x, y, keys),
    )
    path = tmp_path / "model.pkl"
    joblib.dump(bundle, path)
    loaded = joblib.load(path)
    assert isinstance(loaded, BaselineModelBundle)
    assert np.array_equal(loaded.b0.predict(x), bundle.b0.predict(x))
    assert np.array_equal(loaded.b1.predict(x), bundle.b1.predict(x))
