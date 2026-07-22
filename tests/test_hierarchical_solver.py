"""Penalized H1 solver numerical tests."""

import numpy as np
import pytest

from nhc_deprot_ranker.models.base import ModelInputError
from nhc_deprot_ranker.models.solver import solve_penalized


def test_penalized_solver_matches_closed_form_ridge() -> None:
    design = np.asarray([[1.0, -1.0], [1.0, 0.0], [1.0, 1.0]])
    target = np.asarray([1.0, 2.0, 4.0])
    penalties = np.asarray([0.0, 2.0])
    prior = np.zeros(2)
    result = solve_penalized(
        design=design,
        target=target,
        penalties=penalties,
        prior=prior,
        condition_number_threshold=1e12,
    )
    expected = np.linalg.solve(design.T @ design + np.diag(penalties), design.T @ target)
    assert result.coefficients == pytest.approx(expected)
    assert result.diagnostics.used_pseudoinverse is False


def test_rank_deficient_solver_records_pseudoinverse() -> None:
    design = np.asarray([[1.0, 1.0], [1.0, 1.0], [1.0, 1.0]])
    result = solve_penalized(
        design=design,
        target=np.asarray([2.0, 2.0, 2.0]),
        penalties=np.zeros(2),
        prior=np.zeros(2),
        condition_number_threshold=1e12,
    )
    assert result.diagnostics.design_rank == 1
    assert result.diagnostics.used_pseudoinverse is True
    assert design @ result.coefficients == pytest.approx([2.0, 2.0, 2.0])


def test_solver_rejects_negative_penalty_and_nonfinite_design() -> None:
    with pytest.raises(ModelInputError, match="non-negative"):
        solve_penalized(
            design=np.eye(2),
            target=np.ones(2),
            penalties=np.asarray([0.0, -1.0]),
            prior=np.zeros(2),
            condition_number_threshold=1e12,
        )
    with pytest.raises(ModelInputError, match="non-finite"):
        solve_penalized(
            design=np.asarray([[1.0, np.nan], [1.0, 2.0]]),
            target=np.ones(2),
            penalties=np.ones(2),
            prior=np.zeros(2),
            condition_number_threshold=1e12,
        )
