"""Small key-integrity helpers shared by future importers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable


class DuplicatePrimaryKeyError(ValueError):
    """Input contains a repeated InChIKey."""


def assert_unique_primary_keys(keys: Iterable[str]) -> tuple[str, ...]:
    """Return materialized keys or reject blanks and duplicates."""

    values = tuple(keys)
    blank_count = sum(not value for value in values)
    if blank_count:
        raise ValueError(f"primary key contains {blank_count} blank value(s)")
    duplicates = sorted(key for key, count in Counter(values).items() if count > 1)
    if duplicates:
        preview = ", ".join(duplicates[:5])
        raise DuplicatePrimaryKeyError(
            f"duplicate InChIKey values: {len(duplicates)} unique duplicate(s); {preview}"
        )
    return values
