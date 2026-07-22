"""Exchange-invariant family tests."""

from nhc_deprot_ranker.chemistry.families import (
    canonical_sorted_pair,
    combined_family,
)


def test_axis_a_exchange_is_invariant() -> None:
    assert canonical_sorted_pair("Me", "Et") == canonical_sorted_pair("Et", "Me")


def test_axis_b_exchange_is_invariant() -> None:
    assert canonical_sorted_pair("Cl", "H") == canonical_sorted_pair("H", "Cl")


def test_unknown_fragment_is_explicit() -> None:
    assert canonical_sorted_pair(None, "") == "unknown|unknown"


def test_combined_family_is_deterministic() -> None:
    axis_a = canonical_sorted_pair("Me", "Et")
    axis_b = canonical_sorted_pair("H", "Cl")
    assert (
        combined_family(skeleton="imidazolium", axis_a_family=axis_a, axis_b_family=axis_b)
        == "imidazolium::A=Et|Me::B=Cl|H"
    )
