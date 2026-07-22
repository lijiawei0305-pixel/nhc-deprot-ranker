"""Normalized schema behavior tests."""

import math

import pytest
from pydantic import ValidationError

from nhc_deprot_ranker.data.schemas import CandidateRecord


def _candidate(**updates: object) -> CandidateRecord:
    values: dict[str, object] = {
        "inchikey": "TEST-KEY",
        "xtb_deprot_kcal": 100.0,
        "xtb_rank": 1,
        "xtb_percentile": 0.0,
        "skeleton": "imidazolium",
        "axis_a_family": "Me|Me",
        "axis_b_family": "H|H",
        "combined_family": "imidazolium::A=Me|Me::B=H|H",
        "source_file": "fixture.csv",
        "source_sha256": "0" * 64,
    }
    values.update(updates)
    return CandidateRecord.model_validate(values)


def test_candidate_accepts_finite_value() -> None:
    assert _candidate().xtb_rank == 1


def test_candidate_rejects_nonfinite_target() -> None:
    with pytest.raises(ValidationError):
        _candidate(xtb_deprot_kcal=math.nan)


def test_candidate_rejects_bad_hash() -> None:
    with pytest.raises(ValidationError):
        _candidate(source_sha256="not-a-hash")
