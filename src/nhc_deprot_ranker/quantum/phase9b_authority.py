"""Candidate-parameterized endpoint authority for Phase 9B.

The Phase 8B authority module cannot validate any candidate but the one it was
frozen for.  It hard-codes an element composition, an electron count of 120, and
a positional ring pin requiring ``N, C, N`` at indices 3, 4, 5.  The Phase 9B
candidate has 160 electrons and carries its ring atoms at indices 8, 14, and 15,
so that module would reject a correct structure.

This module supplies the same guarantees from a :class:`CandidateProfile`
instead of literals, and reads ring identity from the candidate's atom map
rather than from fixed positions.  Reordering atoms to satisfy a positional pin
is never an acceptable remedy: atom order is a load-bearing invariant across the
geometry validator, the runner, and the handoff hash closure.

The Phase 8B module is left untouched.  It is an immutable record of a rejected
attempt, not a component to be generalized in place.

This module is deliberately **not** yet listed in the runner source closure.
Adding it changes ``runner_source_sha256``, which must happen together with
generating the new request, payload manifest, and one-shot permit, not before.

No chemistry import, no compute, no label.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Protocol

# Covers every element the project's candidates actually contain.  The Phase 8B
# table omitted F, S, Cl, and Br, which is safe only for its single candidate.
ATOMIC_NUMBERS: Final[Mapping[str, int]] = MappingProxyType(
    {"H": 1, "C": 6, "N": 7, "O": 8, "F": 9, "S": 16, "Cl": 17, "Br": 35}
)

_MAP_KEYS: Final = ("C2_carbene", "N1", "N3")
_MAP_ELEMENTS: Final[Mapping[str, str]] = MappingProxyType(
    {"C2_carbene": "C", "N1": "N", "N3": "N"}
)


class Phase9BAuthorityError(RuntimeError):
    """A Phase 9B endpoint or candidate profile failed its closed-scope proof."""


class _AtomLike(Protocol):
    # Read-only members: this module only ever reads geometry, and read-only
    # properties keep frozen dataclasses structurally compatible.
    @property
    def element(self) -> str: ...


class _GeometryLike(Protocol):
    @property
    def atoms(self) -> Sequence[_AtomLike]: ...


class _EndpointLike(Protocol):
    @property
    def geometry(self) -> _GeometryLike: ...

    @property
    def charge(self) -> int: ...

    @property
    def multiplicity(self) -> int: ...


@dataclass(frozen=True, slots=True)
class CandidateProfile:
    """Everything candidate-specific, in one place, so no validator hard-codes it."""

    inchikey: str
    cation_composition: Mapping[str, int]
    neutral_composition: Mapping[str, int]
    electron_count: int
    atom_map: Mapping[str, int]
    cation_xyz_sha256: str
    neutral_xyz_sha256: str


PHASE9B_CANDIDATE: Final = CandidateProfile(
    inchikey="LBNPGYISTSLAHY-UHFFFAOYSA-N",
    cation_composition=MappingProxyType({"C": 9, "F": 9, "H": 5, "N": 3}),
    neutral_composition=MappingProxyType({"C": 9, "F": 9, "H": 4, "N": 3}),
    electron_count=160,
    atom_map=MappingProxyType({"C2_carbene": 14, "N1": 8, "N3": 15}),
    cation_xyz_sha256="543c6944233bb988483b309884c465150c9468798ff2eda0000a8e1273f3d286",
    neutral_xyz_sha256="af9c30640801eec3ab27538a33204186849303dd57592ca5c93320ec1390f4b8",
)


def computed_electron_count(elements: Sequence[str], *, charge: int) -> int:
    """Sum atomic numbers minus charge.  An unknown element is a hard failure."""

    total = 0
    for element in elements:
        number = ATOMIC_NUMBERS.get(element)
        if number is None:
            raise Phase9BAuthorityError(f"unknown element in geometry: {element}")
        total += number
    return total - charge


def _composition_electron_count(composition: Mapping[str, int], *, charge: int) -> int:
    total = 0
    for element, count in composition.items():
        number = ATOMIC_NUMBERS.get(element)
        if number is None:
            raise Phase9BAuthorityError(f"unknown element in composition: {element}")
        total += number * count
    return total - charge


def validate_profile_self_consistency(profile: CandidateProfile) -> None:
    """Catch a mis-specified profile at definition rather than mid-attempt."""

    cation_electrons = _composition_electron_count(profile.cation_composition, charge=1)
    neutral_electrons = _composition_electron_count(profile.neutral_composition, charge=0)
    if cation_electrons != profile.electron_count:
        raise Phase9BAuthorityError(
            f"profile cation electron count recomputes to {cation_electrons}, "
            f"not the declared {profile.electron_count}"
        )
    if neutral_electrons != profile.electron_count:
        raise Phase9BAuthorityError(
            f"profile neutral electron count recomputes to {neutral_electrons}, "
            f"not the declared {profile.electron_count}"
        )
    if profile.electron_count % 2 != 0:
        raise Phase9BAuthorityError("profile electron count is not closed-shell even")
    cation_h = profile.cation_composition.get("H", 0)
    neutral_h = profile.neutral_composition.get("H", 0)
    if cation_h != neutral_h + 1:
        raise Phase9BAuthorityError("profile endpoints do not differ by exactly one proton")
    heavy_cation = {k: v for k, v in profile.cation_composition.items() if k != "H"}
    heavy_neutral = {k: v for k, v in profile.neutral_composition.items() if k != "H"}
    if heavy_cation != heavy_neutral:
        raise Phase9BAuthorityError("profile heavy-atom compositions differ")
    if set(profile.atom_map) != set(_MAP_KEYS):
        raise Phase9BAuthorityError("profile atom map keys drifted")
    if len(set(profile.atom_map.values())) != len(_MAP_KEYS):
        raise Phase9BAuthorityError("profile atom map indices must be distinct")


def validate_atom_map_against_geometry(
    elements: Sequence[str], *, profile: CandidateProfile
) -> None:
    """Ring identity by mapped index, never by assumed position."""

    for key in _MAP_KEYS:
        index = profile.atom_map.get(key)
        if index is None:
            raise Phase9BAuthorityError(f"atom map is missing {key}")
        if not 0 <= index < len(elements):
            raise Phase9BAuthorityError(f"atom map index out of range for {key}")
        if elements[index] != _MAP_ELEMENTS[key]:
            raise Phase9BAuthorityError(
                f"atom map element mismatch at {key}: "
                f"expected {_MAP_ELEMENTS[key]}, found {elements[index]}"
            )


def validate_endpoint_pair(
    cation: _EndpointLike, neutral: _EndpointLike, *, profile: CandidateProfile
) -> None:
    """Recompute the candidate's composition and electron closure from geometry."""

    cation_elements = tuple(atom.element for atom in cation.geometry.atoms)
    neutral_elements = tuple(atom.element for atom in neutral.geometry.atoms)

    if Counter(cation_elements) != Counter(dict(profile.cation_composition)):
        raise Phase9BAuthorityError("cation element composition drifted")
    if Counter(neutral_elements) != Counter(dict(profile.neutral_composition)):
        raise Phase9BAuthorityError("neutral element composition drifted")

    cation_heavy = tuple(element for element in cation_elements if element != "H")
    neutral_heavy = tuple(element for element in neutral_elements if element != "H")
    if cation_heavy != neutral_heavy:
        raise Phase9BAuthorityError("endpoint heavy-element ordering drifted")

    cation_h = sum(1 for element in cation_elements if element == "H")
    neutral_h = sum(1 for element in neutral_elements if element == "H")
    if cation_h != neutral_h + 1:
        raise Phase9BAuthorityError("endpoints do not differ by exactly one proton")

    if cation.multiplicity != 1 or neutral.multiplicity != 1:
        raise Phase9BAuthorityError("both endpoints must declare multiplicity 1")

    cation_electrons = computed_electron_count(cation_elements, charge=cation.charge)
    neutral_electrons = computed_electron_count(neutral_elements, charge=neutral.charge)
    if (cation_electrons, neutral_electrons) != (profile.electron_count, profile.electron_count):
        raise Phase9BAuthorityError(
            f"endpoint electron count did not recompute to {profile.electron_count}"
        )

    validate_atom_map_against_geometry(cation_elements, profile=profile)
    validate_atom_map_against_geometry(neutral_elements, profile=profile)


__all__ = [
    "ATOMIC_NUMBERS",
    "PHASE9B_CANDIDATE",
    "CandidateProfile",
    "Phase9BAuthorityError",
    "computed_electron_count",
    "validate_atom_map_against_geometry",
    "validate_endpoint_pair",
    "validate_profile_self_consistency",
]
