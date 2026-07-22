"""Auditable diagonal-penalty linear solver for H1."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from nhc_deprot_ranker.models.base import FloatArray, ModelInputError, finite_vector


@dataclass(frozen=True)
class SolverDiagnostics:
    """Numerical state for one penalized solve."""

    design_rows: int
    design_columns: int
    design_rank: int
    penalized_rank: int
    condition_number: float
    used_pseudoinverse: bool
    solver: str


@dataclass(frozen=True)
class SolverResult:
    """Coefficients and numerical diagnostics."""

    coefficients: FloatArray
    diagnostics: SolverDiagnostics


def solve_penalized(
    *,
    design: NDArray[np.float64],
    target: FloatArray,
    penalties: FloatArray,
    prior: FloatArray,
    condition_number_threshold: float,
    weights: FloatArray | None = None,
) -> SolverResult:
    """Solve `(X'WX + P) theta = X'Wy + P*prior` without hidden jitter."""

    matrix = np.asarray(design, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
        raise ModelInputError("design must be a nonempty two-dimensional matrix")
    if not np.isfinite(matrix).all():
        raise ModelInputError("design contains non-finite values")
    y = finite_vector(target, name="target")
    penalty = finite_vector(penalties, name="penalties")
    prior_vector = finite_vector(prior, name="prior")
    rows, columns = matrix.shape
    if len(y) != rows:
        raise ModelInputError("target length does not match design rows")
    if len(penalty) != columns or len(prior_vector) != columns:
        raise ModelInputError("penalty/prior length does not match design columns")
    if np.any(penalty < 0.0):
        raise ModelInputError("penalties must be non-negative")
    if condition_number_threshold <= 1.0:
        raise ValueError("condition_number_threshold must exceed 1")
    if weights is None:
        weight = np.ones(rows, dtype=np.float64)
    else:
        weight = finite_vector(weights, name="weights")
        if len(weight) != rows or np.any(weight <= 0.0):
            raise ModelInputError("weights must be positive and match design rows")
    weighted_design = weight[:, None] * matrix
    system = matrix.T @ weighted_design + np.diag(penalty)
    right_hand_side = matrix.T @ (weight * y) + penalty * prior_vector
    design_rank = int(np.linalg.matrix_rank(matrix))
    penalized_rank = int(np.linalg.matrix_rank(system))
    condition_number = float(np.linalg.cond(system))
    direct = (
        penalized_rank == columns
        and np.isfinite(condition_number)
        and condition_number <= condition_number_threshold
    )
    if direct:
        raw_coefficients = np.linalg.solve(system, right_hand_side)
        solver = "symmetric_direct"
    else:
        raw_coefficients = np.linalg.pinv(system) @ right_hand_side
        solver = "moore_penrose_pseudoinverse"
    coefficients = np.asarray(raw_coefficients, dtype=np.float64)
    if not np.isfinite(coefficients).all():
        raise ModelInputError("penalized solver produced non-finite coefficients")
    return SolverResult(
        coefficients=coefficients,
        diagnostics=SolverDiagnostics(
            design_rows=rows,
            design_columns=columns,
            design_rank=design_rank,
            penalized_rank=penalized_rank,
            condition_number=condition_number,
            used_pseudoinverse=not direct,
            solver=solver,
        ),
    )
