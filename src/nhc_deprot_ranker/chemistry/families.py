"""Exchange-invariant family construction."""

from __future__ import annotations

UNKNOWN_FAMILY_TOKEN = "unknown"


def normalize_fragment(value: str | None, *, unknown_token: str = UNKNOWN_FAMILY_TOKEN) -> str:
    """Normalize blank/missing fragment codes to an explicit token."""

    normalized = "" if value is None else value.strip()
    return normalized or unknown_token


def canonical_sorted_pair(
    left: str | None,
    right: str | None,
    *,
    unknown_token: str = UNKNOWN_FAMILY_TOKEN,
) -> str:
    """Return a deterministic unordered pair for one substitution axis."""

    values = sorted(
        (
            normalize_fragment(left, unknown_token=unknown_token),
            normalize_fragment(right, unknown_token=unknown_token),
        )
    )
    return "|".join(values)


def combined_family(
    *,
    skeleton: str | None,
    axis_a_family: str,
    axis_b_family: str,
    unknown_token: str = UNKNOWN_FAMILY_TOKEN,
) -> str:
    """Return the exact, exchange-invariant combined family identifier."""

    skel = normalize_fragment(skeleton, unknown_token=unknown_token)
    return f"{skel}::A={axis_a_family}::B={axis_b_family}"
