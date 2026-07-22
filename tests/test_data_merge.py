"""Primary-key integrity tests."""

import pytest

from nhc_deprot_ranker.data.merge import (
    DuplicatePrimaryKeyError,
    assert_unique_primary_keys,
)


def test_unique_keys_are_retained() -> None:
    assert assert_unique_primary_keys(["A", "B"]) == ("A", "B")


def test_duplicate_key_is_rejected() -> None:
    with pytest.raises(DuplicatePrimaryKeyError, match="duplicate"):
        assert_unique_primary_keys(["A", "B", "A"])


def test_blank_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="blank"):
        assert_unique_primary_keys(["A", ""])
