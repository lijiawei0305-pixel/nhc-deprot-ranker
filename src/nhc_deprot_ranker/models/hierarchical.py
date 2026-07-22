"""H1 additive partially pooled hierarchical linear calibrator."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import joblib  # type: ignore[import-untyped]
import numpy as np
import pandas as pd

from nhc_deprot_ranker.models.base import FloatArray, ModelInputError, finite_vector, key_set_sha256
from nhc_deprot_ranker.models.solver import SolverDiagnostics, solve_penalized

FAMILY_COLUMNS = ("skeleton", "axis_a_family", "axis_b_family")


class HierarchicalLinearCalibrator:
    """Penalized additive family calibration with zero-effect unknown fallback."""

    def __init__(
        self,
        *,
        lambda_skeleton: float,
        lambda_axis_a: float,
        lambda_axis_b: float,
        lambda_slope: float = 0.0,
        rho_prior: float = 1.0,
        condition_number_threshold: float = 1e12,
        skeleton_policy: str = "inactive_if_single_level",
    ) -> None:
        penalties = (lambda_skeleton, lambda_axis_a, lambda_axis_b, lambda_slope)
        if any(not math.isfinite(value) or value < 0.0 for value in penalties):
            raise ValueError("all H1 penalties must be finite and non-negative")
        if not math.isfinite(rho_prior):
            raise ValueError("rho_prior must be finite")
        if condition_number_threshold <= 1.0:
            raise ValueError("condition_number_threshold must exceed 1")
        if skeleton_policy != "inactive_if_single_level":
            raise ValueError("unsupported skeleton policy")
        self.lambda_skeleton = float(lambda_skeleton)
        self.lambda_axis_a = float(lambda_axis_a)
        self.lambda_axis_b = float(lambda_axis_b)
        self.lambda_slope = float(lambda_slope)
        self.rho_prior = float(rho_prior)
        self.condition_number_threshold = float(condition_number_threshold)
        self.skeleton_policy = skeleton_policy
        self.coefficients_: FloatArray | None = None
        self.feature_names_: tuple[str, ...] = ()
        self.vocabularies_: dict[str, tuple[str, ...]] = {}
        self.active_terms_: dict[str, bool] = {}
        self.support_: dict[str, dict[str, int]] = {}
        self.effect_indices_: dict[str, dict[str, int]] = {}
        self.x_mean_: float | None = None
        self.x_scale_: float | None = None
        self.x_min_: float | None = None
        self.x_max_: float | None = None
        self.n_samples_: int | None = None
        self.training_key_sha256_: str | None = None
        self.solver_diagnostics_: SolverDiagnostics | None = None

    @staticmethod
    def _validated_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, tuple[str, ...]]:
        required = {"inchikey", "xtb_deprot_kcal", *FAMILY_COLUMNS}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ModelInputError(f"H1 input is missing columns: {missing}")
        normalized = frame.loc[:, ["inchikey", "xtb_deprot_kcal", *FAMILY_COLUMNS]].copy()
        keys = tuple(normalized["inchikey"].astype(str).str.strip())
        key_set_sha256(keys)
        x = normalized["xtb_deprot_kcal"].to_numpy(dtype=np.float64)
        finite_vector(x, name="xtb_deprot_kcal")
        for column in FAMILY_COLUMNS:
            values = normalized[column].astype(str).str.strip()
            if values.eq("").any() or normalized[column].isna().any():
                raise ModelInputError(f"{column} contains blank or missing values")
            normalized[column] = values
        normalized["inchikey"] = keys
        return normalized, keys

    def _make_design(self, frame: pd.DataFrame, *, fit: bool) -> FloatArray:
        x = frame["xtb_deprot_kcal"].to_numpy(dtype=np.float64)
        if fit:
            self.x_mean_ = float(np.mean(x))
            self.x_scale_ = float(np.std(x, ddof=0))
            if not math.isfinite(self.x_scale_) or self.x_scale_ <= 0.0:
                raise ModelInputError("H1 requires nonzero finite xTB scale")
            self.x_min_ = float(np.min(x))
            self.x_max_ = float(np.max(x))
            self.vocabularies_ = {
                column: tuple(sorted(frame[column].unique().tolist())) for column in FAMILY_COLUMNS
            }
            self.active_terms_ = {
                "skeleton": len(self.vocabularies_["skeleton"]) > 1,
                "axis_a_family": True,
                "axis_b_family": True,
            }
            self.support_ = {
                column: {
                    str(level): int(count) for level, count in frame[column].value_counts().items()
                }
                for column in FAMILY_COLUMNS
            }
        if self.x_mean_ is None or self.x_scale_ is None:
            raise RuntimeError("H1 scaling is not fitted")
        columns: list[FloatArray] = [
            np.ones(len(frame), dtype=np.float64),
            (x - self.x_mean_) / self.x_scale_,
        ]
        names = ["intercept", "xtb_standardized"]
        effect_indices: dict[str, dict[str, int]] = {column: {} for column in FAMILY_COLUMNS}
        for family_column in FAMILY_COLUMNS:
            if not self.active_terms_.get(family_column, False):
                continue
            values = frame[family_column].astype(str).to_numpy()
            for level in self.vocabularies_[family_column]:
                effect_indices[family_column][level] = len(columns)
                columns.append((values == level).astype(np.float64))
                names.append(f"{family_column}::{level}")
        if fit:
            self.feature_names_ = tuple(names)
            self.effect_indices_ = effect_indices
        elif tuple(names) != self.feature_names_:
            raise RuntimeError("H1 prediction design does not match fitted features")
        return np.column_stack(columns).astype(np.float64, copy=False)

    def fit(
        self,
        frame: pd.DataFrame,
        y: Sequence[float] | FloatArray,
    ) -> HierarchicalLinearCalibrator:
        """Fit H1 with training-only scaling and vocabularies."""

        normalized, keys = self._validated_frame(frame)
        target = finite_vector(y, name="target")
        if len(target) != len(normalized):
            raise ModelInputError("H1 target length does not match input rows")
        if len(target) < 3:
            raise ModelInputError("H1 requires at least three training rows")
        design = self._make_design(normalized, fit=True)
        penalties = np.zeros(design.shape[1], dtype=np.float64)
        prior = np.zeros(design.shape[1], dtype=np.float64)
        if self.x_scale_ is None:  # pragma: no cover - established in _make_design
            raise RuntimeError("H1 xTB scale missing")
        penalties[1] = self.lambda_slope / (self.x_scale_**2)
        prior[1] = self.rho_prior * self.x_scale_
        term_penalties = {
            "skeleton": self.lambda_skeleton,
            "axis_a_family": self.lambda_axis_a,
            "axis_b_family": self.lambda_axis_b,
        }
        for family_column, indices in self.effect_indices_.items():
            for index in indices.values():
                penalties[index] = term_penalties[family_column]
        result = solve_penalized(
            design=design,
            target=target,
            penalties=penalties,
            prior=prior,
            condition_number_threshold=self.condition_number_threshold,
        )
        self.coefficients_ = result.coefficients
        self.solver_diagnostics_ = result.diagnostics
        self.n_samples_ = len(normalized)
        self.training_key_sha256_ = key_set_sha256(keys)
        return self

    def _require_fitted(self) -> FloatArray:
        if self.coefficients_ is None:
            raise RuntimeError("HierarchicalLinearCalibrator is not fitted")
        return self.coefficients_

    def predict_components(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return global/family contributions and zero-effect unknown flags."""

        coefficients = self._require_fitted()
        normalized, _ = self._validated_frame(frame)
        design = self._make_design(normalized, fit=False)
        if self.x_mean_ is None or self.x_scale_ is None:
            raise RuntimeError("H1 scaling is not fitted")
        rho = float(coefficients[1] / self.x_scale_)
        beta_0 = float(coefficients[0] - coefficients[1] * self.x_mean_ / self.x_scale_)
        result = pd.DataFrame(
            {
                "inchikey": normalized["inchikey"],
                "global_intercept": beta_0,
                "global_slope_contribution": rho
                * normalized["xtb_deprot_kcal"].to_numpy(dtype=np.float64),
            }
        )
        for family_column, output_name in (
            ("skeleton", "skeleton_effect"),
            ("axis_a_family", "axis_a_effect"),
            ("axis_b_family", "axis_b_effect"),
        ):
            mapping = self.effect_indices_.get(family_column, {})
            values = normalized[family_column].astype(str).tolist()
            effects = np.asarray(
                [
                    float(coefficients[mapping[value]]) if value in mapping else 0.0
                    for value in values
                ],
                dtype=np.float64,
            )
            result[output_name] = effects
            result[f"{family_column}_known"] = [
                value in self.vocabularies_.get(family_column, ()) for value in values
            ]
        result["final_prediction"] = design @ coefficients
        if not np.isfinite(
            result[
                [
                    "global_intercept",
                    "global_slope_contribution",
                    "skeleton_effect",
                    "axis_a_effect",
                    "axis_b_effect",
                    "final_prediction",
                ]
            ].to_numpy(dtype=np.float64)
        ).all():
            raise ModelInputError("H1 prediction components contain non-finite values")
        return result

    def predict(self, frame: pd.DataFrame) -> FloatArray:
        """Return finite H1 predictions."""

        return self.predict_components(frame)["final_prediction"].to_numpy(dtype=np.float64)

    def family_effects(self) -> pd.DataFrame:
        """Return all trained levels, including inactive skeleton metadata."""

        coefficients = self._require_fitted()
        rows: list[dict[str, Any]] = []
        term_penalties = {
            "skeleton": self.lambda_skeleton,
            "axis_a_family": self.lambda_axis_a,
            "axis_b_family": self.lambda_axis_b,
        }
        for family_column in FAMILY_COLUMNS:
            active = self.active_terms_.get(family_column, False)
            mapping = self.effect_indices_.get(family_column, {})
            for level in self.vocabularies_.get(family_column, ()):
                rows.append(
                    {
                        "term": family_column,
                        "level": level,
                        "effect_kcal": float(coefficients[mapping[level]])
                        if level in mapping
                        else 0.0,
                        "support": self.support_[family_column][level],
                        "lambda": term_penalties[family_column],
                        "active": active,
                        "status": "estimated" if active else "inactive_single_level",
                    }
                )
        return pd.DataFrame.from_records(rows).sort_values(["term", "level"]).reset_index(drop=True)

    def get_coefficients(self) -> dict[str, Any]:
        """Return original-scale global terms and solver metadata."""

        coefficients = self._require_fitted()
        if self.x_mean_ is None or self.x_scale_ is None or self.solver_diagnostics_ is None:
            raise RuntimeError("H1 fitted metadata is incomplete")
        rho = float(coefficients[1] / self.x_scale_)
        beta_0 = float(coefficients[0] - coefficients[1] * self.x_mean_ / self.x_scale_)
        return {
            "model": "H1_hierarchical_linear",
            "beta_0": beta_0,
            "rho": rho,
            "standardized_slope": float(coefficients[1]),
            "x_mean": self.x_mean_,
            "x_scale": self.x_scale_,
            "x_min": self.x_min_,
            "x_max": self.x_max_,
            "n_samples": self.n_samples_,
            "training_key_sha256": self.training_key_sha256_,
            "penalties": {
                "skeleton": self.lambda_skeleton,
                "axis_a": self.lambda_axis_a,
                "axis_b": self.lambda_axis_b,
                "slope": self.lambda_slope,
            },
            "rho_prior": self.rho_prior,
            "skeleton_status": (
                "estimated"
                if self.active_terms_.get("skeleton", False)
                else "inactive_single_level"
            ),
            "vocabulary_sizes": {
                column: len(vocabulary) for column, vocabulary in self.vocabularies_.items()
            },
            "solver": {
                "design_rows": self.solver_diagnostics_.design_rows,
                "design_columns": self.solver_diagnostics_.design_columns,
                "design_rank": self.solver_diagnostics_.design_rank,
                "penalized_rank": self.solver_diagnostics_.penalized_rank,
                "condition_number": self.solver_diagnostics_.condition_number,
                "used_pseudoinverse": self.solver_diagnostics_.used_pseudoinverse,
                "solver": self.solver_diagnostics_.solver,
            },
            "unknown_family_policy": "zero_effect",
            "lower_is_better": True,
        }

    def save(self, path: Path) -> None:
        """Serialize a fitted estimator."""

        self._require_fitted()
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path, compress=3)

    @classmethod
    def load(cls, path: Path) -> HierarchicalLinearCalibrator:
        """Load and type-check a serialized estimator."""

        model = joblib.load(path)
        if not isinstance(model, cls):
            raise TypeError(f"serialized object is not {cls.__name__}")
        model._require_fitted()
        return model
