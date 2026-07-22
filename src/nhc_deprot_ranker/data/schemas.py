"""Pydantic records for normalized candidate and label rows."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DataRecord(BaseModel):
    """Strict finite-value data model base."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CandidateRecord(DataRecord):
    """Normalized low-fidelity candidate record."""

    inchikey: str = Field(min_length=1)
    smiles_cation: str | None = None
    smiles_neutral: str | None = None
    xtb_deprot_kcal: float
    xtb_rank: int = Field(ge=1)
    xtb_percentile: float = Field(ge=0.0, le=1.0)
    n1_frag: str | None = None
    n3_frag: str | None = None
    c4_frag: str | None = None
    c5_frag: str | None = None
    skeleton: str
    axis_a_family: str
    axis_b_family: str
    combined_family: str
    n_heavy_atoms: int | None = Field(default=None, ge=0)
    n_electrons: int | None = Field(default=None, ge=0)
    source_file: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HighFidelityLabel(DataRecord):
    """Normalized electronic-energy-only high-fidelity label."""

    inchikey: str = Field(min_length=1)
    e_cation_hartree: float | None = None
    e_neutral_hartree: float | None = None
    electronic_difference_kcal: float | None = None
    dft_deprot_electronic_kcal: float
    formula_revalidated: bool
    method: str
    basis: str
    dispersion: str
    geometry_optimizer: str | None = None
    cation_converged: bool
    neutral_converged: bool
    hessian_computed: bool
    n_imaginary: int | None = None
    label_quality: str
    label_protocol_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_group: str
    source_file: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
