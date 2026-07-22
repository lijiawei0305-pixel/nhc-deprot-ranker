"""Leakage checks for LOOCV and family holdouts."""

import pytest

from nhc_deprot_ranker.models.base import ModelInputError
from nhc_deprot_ranker.validation.splits import leave_one_group_out_folds, loocv_folds


def test_loocv_holds_each_key_once() -> None:
    keys = ["C", "A", "B", "D"]
    folds = loocv_folds(keys)
    held_out = [keys[fold.test_indices[0]] for fold in folds]
    assert held_out == ["A", "B", "C", "D"]
    assert all(set(fold.train_indices).isdisjoint(fold.test_indices) for fold in folds)


def test_grouped_split_holds_family_out_completely() -> None:
    keys = ["A", "B", "C", "D", "E"]
    groups = ["g1", "g1", "g2", "g3", "g3"]
    folds = leave_one_group_out_folds(keys=keys, groups=groups, protocol="axis")
    assert [fold.held_out_group for fold in folds] == ["g1", "g2", "g3"]
    for fold in folds:
        assert fold.held_out_group not in {groups[index] for index in fold.train_indices}
        assert {groups[index] for index in fold.test_indices} == {fold.held_out_group}


def test_grouped_split_requires_multiple_groups() -> None:
    with pytest.raises(ModelInputError, match="at least two"):
        leave_one_group_out_folds(
            keys=["A", "B", "C"],
            groups=["same", "same", "same"],
            protocol="axis",
        )
