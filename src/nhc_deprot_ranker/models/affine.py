"""B1 free-intercept, free-slope global affine calibrator."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from nhc_deprot_ranker.models.base import (
    FloatArray,
    ModelInputError,
    finite_vector,
    key_set_sha256,
)


class AffineCalibrator:
    """Ordinary least-squares calibration `beta_0 + rho*x`."""

    def __init__(self, *, min_samples: int = 3, condition_number_threshold: float = 1e12) -> None:
        if min_samples < 3:
            raise ValueError("min_samples must be at least 3")
        if condition_number_threshold <= 1.0:
            raise ValueError("condition_number_threshold must exceed 1")
        self.min_samples = min_samples
        self.condition_number_threshold = condition_number_threshold
        self.intercept_: float | None = None
        self.slope_: float | None = None
        self.intercept_standard_error_: float | None = None
        self.slope_standard_error_: float | None = None
        self.residual_variance_: float | None = None
        self.rank_: int | None = None
        self.condition_number_: float | None = None
        self.used_pseudoinverse_: bool | None = None
        self.n_samples_: int | None = None
        self.x_min_: float | None = None
        self.x_max_: float | None = None
        self.training_key_sha256_: str | None = None

    def fit(
        self,
        x: Sequence[float] | FloatArray,
        y: Sequence[float] | FloatArray,
        keys: Sequence[str],
    ) -> AffineCalibrator:
        """Fit finite OLS and record numerical diagnostics."""

        x_array = finite_vector(x, name="x")
        y_array = finite_vector(y, name="y")
        if len(x_array) != len(y_array) or len(x_array) != len(keys):
            raise ModelInputError("x, y, and keys must have equal length")
        if len(x_array) < self.min_samples:
            raise ModelInputError(f"affine fit requires at least {self.min_samples} samples")
        if float(np.ptp(x_array)) == 0.0:
            raise ModelInputError("affine fit requires nonzero x variance")
        training_hash = key_set_sha256(keys)
        design = np.column_stack((np.ones(len(x_array), dtype=np.float64), x_array))
        rank = int(np.linalg.matrix_rank(design))
        if rank < 2:
            raise ModelInputError("affine design matrix is rank deficient")
        condition_number = float(np.linalg.cond(design))
        if not np.isfinite(condition_number):
            raise ModelInputError("affine design condition number is non-finite")
        use_pseudoinverse = condition_number > self.condition_number_threshold
        solution: Any
        if use_pseudoinverse:
            solution = np.linalg.pinv(design) @ y_array
        else:
            solution, _, _, _ = np.linalg.lstsq(design, y_array, rcond=None)
        coefficients = np.asarray(solution, dtype=np.float64)
        predictions = design @ coefficients
        residuals = y_array - predictions
        degrees_of_freedom = len(y_array) - 2
        residual_variance = float(np.dot(residuals, residuals) / degrees_of_freedom)
        covariance = residual_variance * np.linalg.pinv(design.T @ design)
        standard_errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))
        if not np.isfinite(coefficients).all() or not np.isfinite(standard_errors).all():
            raise ModelInputError("affine fit produced non-finite coefficients")
        self.intercept_ = float(coefficients[0])
        self.slope_ = float(coefficients[1])
        self.intercept_standard_error_ = float(standard_errors[0])
        self.slope_standard_error_ = float(standard_errors[1])
        self.residual_variance_ = residual_variance
        self.rank_ = rank
        self.condition_number_ = condition_number
        self.used_pseudoinverse_ = use_pseudoinverse
        self.n_samples_ = len(x_array)
        self.x_min_ = float(x_array.min())
        self.x_max_ = float(x_array.max())
        self.training_key_sha256_ = training_hash
        return self

    def predict(self, x: Sequence[float] | FloatArray) -> FloatArray:
        """Predict calibrated electronic energies."""

        if self.intercept_ is None or self.slope_ is None:
            raise RuntimeError("AffineCalibrator is not fitted")
        vector = finite_vector(x, name="x")
        predictions = self.intercept_ + self.slope_ * vector
        if not np.isfinite(predictions).all():
            raise ModelInputError("affine prediction produced non-finite values")
        return predictions.astype(np.float64, copy=False)

    def coefficients(self) -> dict[str, Any]:
        """Return fitted coefficients and numerical diagnostics."""

        if self.intercept_ is None:
            raise RuntimeError("AffineCalibrator is not fitted")
        return {
            "model": "B1_global_affine",
            "beta_0": self.intercept_,
            "rho": self.slope_,
            "beta_0_standard_error": self.intercept_standard_error_,
            "rho_standard_error": self.slope_standard_error_,
            "residual_variance": self.residual_variance_,
            "rank": self.rank_,
            "condition_number": self.condition_number_,
            "used_pseudoinverse": self.used_pseudoinverse_,
            "n_samples": self.n_samples_,
            "x_min": self.x_min_,
            "x_max": self.x_max_,
            "training_key_sha256": self.training_key_sha256_,
            "lower_is_better": True,
        }
