"""Leakage-checked deterministic Phase 2 split construction."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from nhc_deprot_ranker.models.base import ModelInputError, validated_keys


@dataclass(frozen=True)
class ValidationFold:
    """One explicit train/test key partition."""

    protocol: str
    fold_id: str
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    held_out_group: str | None = None

    def to_manifest(self, keys: Sequence[str]) -> dict[str, Any]:
        """Serialize explicit keys for independent leakage review."""

        return {
            "fold_id": self.fold_id,
            "held_out_group": self.held_out_group,
            "train_keys": [keys[index] for index in self.train_indices],
            "test_keys": [keys[index] for index in self.test_indices],
        }


def _validate_fold(fold: ValidationFold, keys: Sequence[str]) -> None:
    train_keys = {keys[index] for index in fold.train_indices}
    test_keys = {keys[index] for index in fold.test_indices}
    if not train_keys or not test_keys:
        raise ModelInputError(f"{fold.fold_id} has an empty train or test partition")
    if train_keys & test_keys:
        raise ModelInputError(f"{fold.fold_id} leaks InChIKeys")
    if train_keys | test_keys != set(keys):
        raise ModelInputError(f"{fold.fold_id} does not partition all keys")


def loocv_folds(keys: Sequence[str]) -> tuple[ValidationFold, ...]:
    """Return one deterministic held-out key per fold."""

    normalized_keys = validated_keys(keys, expected_size=len(keys))
    folds: list[ValidationFold] = []
    for test_index in sorted(range(len(keys)), key=lambda index: normalized_keys[index]):
        train_indices = tuple(index for index in range(len(keys)) if index != test_index)
        fold = ValidationFold(
            protocol="loocv",
            fold_id=f"loocv::{normalized_keys[test_index]}",
            train_indices=train_indices,
            test_indices=(test_index,),
        )
        _validate_fold(fold, normalized_keys)
        folds.append(fold)
    return tuple(folds)


def leave_one_group_out_folds(
    *,
    keys: Sequence[str],
    groups: Sequence[str],
    protocol: str,
) -> tuple[ValidationFold, ...]:
    """Hold out every family once and reject held-out-family leakage."""

    normalized_keys = validated_keys(keys, expected_size=len(keys))
    normalized_groups = tuple(str(group).strip() for group in groups)
    if len(normalized_groups) != len(normalized_keys):
        raise ModelInputError("group and key counts must match")
    if any(not group for group in normalized_groups):
        raise ModelInputError("group values must be nonblank")
    unique_groups = sorted(set(normalized_groups))
    if len(unique_groups) < 2:
        raise ModelInputError("group holdout requires at least two groups")
    folds: list[ValidationFold] = []
    for group in unique_groups:
        test_indices = tuple(
            index for index, value in enumerate(normalized_groups) if value == group
        )
        train_indices = tuple(
            index for index, value in enumerate(normalized_groups) if value != group
        )
        fold = ValidationFold(
            protocol=protocol,
            fold_id=f"{protocol}::{group}",
            train_indices=train_indices,
            test_indices=test_indices,
            held_out_group=group,
        )
        _validate_fold(fold, normalized_keys)
        if group in {normalized_groups[index] for index in train_indices}:
            raise ModelInputError(f"{fold.fold_id} leaks held-out family")
        folds.append(fold)
    return tuple(folds)
