"""Phase 9B candidate-parameterized authority regressions.

No chemistry, no server, no compute.  These tests define the contract the
Phase 8B authority module could not satisfy: candidate identity supplied by a
profile rather than hard-coded, and ring identity read from the atom map rather
than from fixed positions 3/4/5.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from nhc_deprot_ranker.quantum import phase9b_authority as authority
from nhc_deprot_ranker.quantum.phase9b_authority import (
    PHASE9B_CANDIDATE,
    CandidateProfile,
    Phase9BAuthorityError,
    computed_electron_count,
    validate_atom_map_against_geometry,
    validate_endpoint_pair,
    validate_profile_self_consistency,
)


@dataclass(frozen=True)
class _Atom:
    element: str


@dataclass(frozen=True)
class _Geometry:
    atoms: tuple[_Atom, ...]


@dataclass(frozen=True)
class _Endpoint:
    geometry: _Geometry
    charge: int
    multiplicity: int = 1


def _elements(hydrogens: int) -> tuple[str, ...]:
    """C9 F9 N3 heavy skeleton with the real atom-map layout.

    Indices 8 / 14 / 15 carry N / C / N, matching the candidate's atom map, and
    deliberately not the Phase 8B positional pin at 3 / 4 / 5.
    """

    heavy = ["C"] * 8 + ["N"] + ["F"] * 5 + ["C"] + ["N"] + ["N"] + ["F"] * 4
    return tuple(heavy + ["H"] * hydrogens)


def _endpoint(hydrogens: int, charge: int) -> _Endpoint:
    return _Endpoint(
        geometry=_Geometry(atoms=tuple(_Atom(e) for e in _elements(hydrogens))),
        charge=charge,
    )


def _cation() -> _Endpoint:
    return _endpoint(5, 1)


def _neutral() -> _Endpoint:
    return _endpoint(4, 0)


def test_frozen_candidate_profile_is_self_consistent() -> None:
    validate_profile_self_consistency(PHASE9B_CANDIDATE)
    assert PHASE9B_CANDIDATE.inchikey == "LBNPGYISTSLAHY-UHFFFAOYSA-N"
    assert PHASE9B_CANDIDATE.electron_count == 160
    assert PHASE9B_CANDIDATE.atom_map == {"C2_carbene": 14, "N1": 8, "N3": 15}


def test_profile_declaring_a_wrong_electron_count_is_rejected() -> None:
    """A mis-specified profile must fail at definition, not silently at runtime."""

    bad = replace(PHASE9B_CANDIDATE, electron_count=120)
    with pytest.raises(Phase9BAuthorityError, match="electron count"):
        validate_profile_self_consistency(bad)


def test_valid_endpoint_pair_passes() -> None:
    validate_endpoint_pair(_cation(), _neutral(), profile=PHASE9B_CANDIDATE)
    validate_atom_map_against_geometry(_elements(5), profile=PHASE9B_CANDIDATE)
    validate_atom_map_against_geometry(_elements(4), profile=PHASE9B_CANDIDATE)


def test_electron_count_is_160_not_the_phase8b_120() -> None:
    assert computed_electron_count(_elements(5), charge=1) == 160
    assert computed_electron_count(_elements(4), charge=0) == 160


def test_ring_identity_uses_the_atom_map_not_positions_three_four_five() -> None:
    """The Phase 8B positional pin would reject this correct structure."""

    elements = _elements(5)
    assert (elements[3], elements[4], elements[5]) != ("N", "C", "N")
    validate_atom_map_against_geometry(elements, profile=PHASE9B_CANDIDATE)


def test_wrong_element_at_a_mapped_index_fails_closed() -> None:
    broken = list(_elements(5))
    broken[14] = "N"
    with pytest.raises(Phase9BAuthorityError, match="atom map element"):
        validate_atom_map_against_geometry(tuple(broken), profile=PHASE9B_CANDIDATE)


def test_atom_map_index_out_of_range_fails_closed() -> None:
    bad = replace(PHASE9B_CANDIDATE, atom_map={"C2_carbene": 999, "N1": 8, "N3": 15})
    with pytest.raises(Phase9BAuthorityError, match="out of range"):
        validate_atom_map_against_geometry(_elements(5), profile=bad)


def test_composition_drift_fails_closed() -> None:
    wrong = _endpoint(6, 1)
    with pytest.raises(Phase9BAuthorityError, match="cation element composition"):
        validate_endpoint_pair(wrong, _neutral(), profile=PHASE9B_CANDIDATE)


def test_heavy_element_ordering_drift_fails_closed() -> None:
    swapped = list(_elements(4))
    first_c, first_f = swapped.index("C"), swapped.index("F")
    swapped[first_c], swapped[first_f] = swapped[first_f], swapped[first_c]
    bad = _Endpoint(_Geometry(tuple(_Atom(e) for e in swapped)), charge=0)
    with pytest.raises(Phase9BAuthorityError, match="heavy-element ordering"):
        validate_endpoint_pair(_cation(), bad, profile=PHASE9B_CANDIDATE)


def test_neutral_with_wrong_hydrogen_count_fails_closed() -> None:
    """Composition is the stricter gate and fires before the proton-difference check."""

    with pytest.raises(Phase9BAuthorityError, match="neutral element composition"):
        validate_endpoint_pair(_cation(), _endpoint(3, 0), profile=PHASE9B_CANDIDATE)


def test_profile_whose_endpoints_differ_by_two_protons_fails_closed() -> None:
    bad = replace(PHASE9B_CANDIDATE, neutral_composition={"C": 9, "F": 9, "H": 3, "N": 3})
    with pytest.raises(Phase9BAuthorityError, match=r"one proton|electron count"):
        validate_profile_self_consistency(bad)


def test_wrong_charge_fails_closed() -> None:
    with pytest.raises(Phase9BAuthorityError, match="electron count"):
        validate_endpoint_pair(_endpoint(5, 0), _neutral(), profile=PHASE9B_CANDIDATE)


def test_nonsinglet_multiplicity_fails_closed() -> None:
    triplet = _Endpoint(_Geometry(tuple(_Atom(e) for e in _elements(5))), charge=1, multiplicity=3)
    with pytest.raises(Phase9BAuthorityError, match="multiplicity"):
        validate_endpoint_pair(triplet, _neutral(), profile=PHASE9B_CANDIDATE)


def test_unknown_element_fails_closed_rather_than_defaulting() -> None:
    """An element absent from the table must raise, never contribute zero."""

    with pytest.raises(Phase9BAuthorityError, match="unknown element"):
        computed_electron_count(("C", "Xx", "H"), charge=0)


def test_atomic_number_table_covers_every_element_the_project_needs() -> None:
    """The Phase 8B table omitted F, S, Cl, Br; this one must not."""

    for element in ("H", "C", "N", "O", "F", "S", "Cl", "Br"):
        assert element in authority.ATOMIC_NUMBERS, element


def test_profile_is_reusable_for_a_different_candidate() -> None:
    """Parameterization is the point: a second candidate needs no code change."""

    from nhc_deprot_ranker.quantum.phase8b_authority import PHASE7_GEOMETRY_VALIDATION_SHA256
    from nhc_deprot_ranker.quantum.phase8b_permit import FROZEN_INPUT_SHA256

    # Real Phase 8B values, so this proves the profile can genuinely represent
    # that chain rather than merely accepting placeholder strings.
    other = CandidateProfile(
        inchikey="QXHIEGFUWOLQIJ-UHFFFAOYSA-N",
        cation_composition={"C": 7, "N": 6, "O": 4, "H": 5},
        neutral_composition={"C": 7, "N": 6, "O": 4, "H": 4},
        electron_count=120,
        atom_map={"C2_carbene": 4, "N1": 3, "N3": 5},
        cation_xyz_sha256=FROZEN_INPUT_SHA256["cation_xyz"],
        neutral_xyz_sha256=FROZEN_INPUT_SHA256["neutral_xyz"],
        legacy_atom_map_sha256=FROZEN_INPUT_SHA256["legacy_atom_map"],
        endpoint_atom_map_sha256=FROZEN_INPUT_SHA256["endpoint_atom_map"],
        geometry_validation_sha256=PHASE7_GEOMETRY_VALIDATION_SHA256,
    )
    validate_profile_self_consistency(other)
    assert other.electron_count == 120
    assert other.atom_map["C2_carbene"] == 4


def test_module_is_hash_bound_inside_the_runner_source_closure() -> None:
    """Now wired: the capability expectation builder imports this at call time.

    It was deliberately outside the closure while unused. Once closure-internal
    code depended on its content, leaving it out would have meant this module
    could change without changing runner_source_sha256.
    """

    from nhc_deprot_ranker.quantum import two_endpoint

    closure = two_endpoint._RUNNER_SOURCE_RELATIVE_PATHS  # pyright: ignore[reportPrivateUsage]
    assert "nhc_deprot_ranker/quantum/phase9b_authority.py" in closure
    assert two_endpoint.RUNNER_SOURCE_SCHEMA_VERSION.endswith("-v6")


def test_module_imports_no_chemistry_and_declares_no_label() -> None:
    source = Path(authority.__file__).read_text(encoding="utf-8").lower()
    for forbidden in ("import pyscf", "import torch", "import aimnet", "import rdkit"):
        assert forbidden not in source, forbidden
    for forbidden in ("627.509474", "6.28", "dft_deprot", "kcal"):
        assert forbidden not in source, forbidden


def test_phase8b_authority_is_untouched() -> None:
    """Historical authority is an immutable record of a rejected attempt."""

    from nhc_deprot_ranker.quantum import phase8b_authority

    assert phase8b_authority.FROZEN_ELECTRON_COUNT == 120
