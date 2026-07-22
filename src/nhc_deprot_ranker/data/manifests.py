"""Immutable source manifest records."""

from pydantic import BaseModel, ConfigDict, Field


class SourceManifest(BaseModel):
    """Minimal provenance for one audited input."""

    model_config = ConfigDict(extra="forbid")

    role: str
    source_file: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    row_count: int | None = Field(default=None, ge=0)
    unique_inchikeys: int | None = Field(default=None, ge=0)
