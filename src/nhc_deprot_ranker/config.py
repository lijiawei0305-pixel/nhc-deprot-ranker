"""Typed YAML configuration for legacy source discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Forbid unreviewed configuration keys."""

    model_config = ConfigDict(extra="forbid")


class LegacyRepoConfig(StrictModel):
    """Local legacy source-code checkout metadata."""

    root: Path
    expected_remote: str
    expected_commit: str | None = None


class SourceAccessConfig(StrictModel):
    """Read-only source transport."""

    mode: Literal["local", "ssh"] = "local"
    ssh_alias: str | None = None
    remote_root: Path | None = None
    read_only: bool = True

    @model_validator(mode="after")
    def validate_access(self) -> SourceAccessConfig:
        """Require explicit SSH coordinates and prohibit writable legacy access."""

        if not self.read_only:
            raise ValueError("legacy source access must remain read_only")
        if self.mode == "ssh" and (not self.ssh_alias or self.remote_root is None):
            raise ValueError("ssh mode requires ssh_alias and remote_root")
        return self


class LocatedPath(StrictModel):
    """A source path anchored at the local legacy or remote root."""

    location: Literal["legacy_repo", "remote_root"]
    path: Path

    @field_validator("path")
    @classmethod
    def require_relative_path(cls, value: Path) -> Path:
        """Keep portable source paths relative to their declared root."""

        if value.is_absolute() or ".." in value.parts:
            raise ValueError("located source path must be a safe relative path")
        return value


class CandidateSources(StrictModel):
    """Legacy candidate inputs."""

    xtb_crude_csv: LocatedPath
    xtb_reduced_csv: LocatedPath
    v3_graph_csv: LocatedPath
    v4_new_only_csv: LocatedPath
    descriptors_parquet: LocatedPath


class LabelSource(LocatedPath):
    """One traceable high-fidelity source."""

    source_group: Literal["gold", "blind_round1", "blind_round2"]
    type: Literal["electronic_energy"]


class LabelSources(StrictModel):
    """Configured high-fidelity label inputs."""

    sources: list[LabelSource]

    @field_validator("sources")
    @classmethod
    def unique_source_groups(cls, value: list[LabelSource]) -> list[LabelSource]:
        """Reject ambiguous repeated group declarations."""

        groups = [source.source_group for source in value]
        if len(groups) != len(set(groups)):
            raise ValueError("label source_group values must be unique")
        return value


class LegacyConfig(StrictModel):
    """Top-level Phase 0 legacy configuration."""

    legacy_repo: LegacyRepoConfig
    source_access: SourceAccessConfig
    candidates: CandidateSources
    labels: LabelSources


class CandidateColumnMap(StrictModel):
    """Source columns required to normalize candidates."""

    inchikey: str
    smiles_cation: str
    smiles_neutral: str
    e_cation_hartree: str
    e_neutral_hartree: str
    xtb_deprot_kcal: str
    n1_frag: str
    n3_frag: str
    c4_frag: str
    c5_frag: str


class LabelColumnMap(StrictModel):
    """Source columns required to normalize one label group."""

    inchikey: str
    e_cation_hartree: str
    e_neutral_hartree: str
    stored_target: str


class LabelColumnMaps(StrictModel):
    """Per-group label mappings."""

    gold: LabelColumnMap
    blind_round1: LabelColumnMap
    blind_round2: LabelColumnMap

    def for_group(self, source_group: str) -> LabelColumnMap:
        """Return the mapping for one validated source group."""

        if source_group not in {"gold", "blind_round1", "blind_round2"}:
            raise ValueError(f"unknown label source group: {source_group}")
        value = getattr(self, source_group)
        if not isinstance(value, LabelColumnMap):  # pragma: no cover - Pydantic invariant
            raise TypeError(f"invalid label column mapping: {source_group}")
        return value


class DataValidationConfig(StrictModel):
    """Hard-reject thresholds and normalization rules."""

    formula_absolute_tolerance_kcal: float = Field(ge=0.0)
    duplicate_target_tolerance_kcal: float = Field(ge=0.0)
    reject_nonfinite: bool = True
    normalize_skipped_hessian_n_imaginary_to_null: bool = True


class ProtocolConfig(StrictModel):
    """Normalized high-fidelity electronic protocol."""

    method: str
    basis: str
    dispersion: str
    geometry_optimizer: str
    cation_charge: int
    cation_multiplicity: int = Field(ge=1)
    neutral_charge: int
    neutral_multiplicity: int = Field(ge=1)
    proton_constant_kcal: float
    target_definition: Literal["electronic_deprotonation_energy"]
    label_quality: Literal["electronic_energy_only"]


class LabelDefaults(StrictModel):
    """Audited convergence/Hessian state shared by current sources."""

    cation_converged: bool
    neutral_converged: bool
    hessian_computed: bool
    n_imaginary: int | None = None

    @model_validator(mode="after")
    def validate_hessian_state(self) -> LabelDefaults:
        """A skipped Hessian cannot carry an imaginary-frequency count."""

        if not self.hessian_computed and self.n_imaginary is not None:
            raise ValueError("n_imaginary must be null when hessian_computed=false")
        return self


class DataConfig(StrictModel):
    """Typed immutable processed-dataset configuration."""

    dataset_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    processed_root: Path
    primary_key: Literal["inchikey"]
    lower_is_better: Literal[True]
    candidate_columns: CandidateColumnMap
    label_columns: LabelColumnMaps
    validation: DataValidationConfig
    protocol: ProtocolConfig
    label_defaults: LabelDefaults


class SkeletonFamilyConfig(StrictModel):
    """Versioned skeleton metadata policy."""

    source: Literal["explicit_source_metadata"]
    current_value: str


class AxisFamilyConfig(StrictModel):
    """One exchange-invariant family axis."""

    columns: tuple[str, str]
    canonicalization: Literal["sorted_pair"]


class CombinedFamilyConfig(StrictModel):
    """Exact family formatting."""

    format: str


class ExactCombinedFamilyConfig(StrictModel):
    """Disabled sparse exact-family effect policy."""

    enabled: bool
    min_labels_per_family: int = Field(ge=1)


class FamiliesConfig(StrictModel):
    """Typed family canonicalization configuration."""

    version: str
    unknown_token: str
    skeleton: SkeletonFamilyConfig
    axis_a: AxisFamilyConfig
    axis_b: AxisFamilyConfig
    combined_family: CombinedFamilyConfig
    model_terms: list[str]
    exact_combined_family: ExactCombinedFamilyConfig
    unknown_family_policy: Literal["zero_effect"]


class AffineConfig(StrictModel):
    """Numerical safeguards for the Phase 2 affine baseline."""

    min_samples: int = Field(ge=3)
    condition_number_threshold: float = Field(gt=1.0)


class BaselineBootstrapConfig(StrictModel):
    """Deterministic coefficient-bootstrap settings."""

    development_repeats: int = Field(ge=1)
    final_repeats: int = Field(ge=1)
    confidence: float = Field(gt=0.0, lt=1.0)
    seed: int


class HistoricalReferenceConfig(StrictModel):
    """Audited legacy results used only as a reproduction gate."""

    enforce: bool = True
    intercept: float
    slope: float
    loocv_mae: float = Field(ge=0.0)
    loocv_rmse: float = Field(ge=0.0)
    loocv_spearman: float = Field(ge=-1.0, le=1.0)
    loocv_kendall: float = Field(ge=-1.0, le=1.0)
    raw_spearman: float = Field(ge=-1.0, le=1.0)
    raw_kendall: float = Field(ge=-1.0, le=1.0)
    intercept_absolute_tolerance: float = Field(ge=0.0)
    slope_absolute_tolerance: float = Field(ge=0.0)
    metric_absolute_tolerance: float = Field(ge=0.0)


class BaselineModelConfig(StrictModel):
    """Typed Phase 2 B0/B1 configuration."""

    model_name: Literal["baseline_suite"]
    model_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    dataset_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    target_column: Literal["dft_deprot_electronic_kcal"]
    baseline_column: Literal["xtb_deprot_kcal"]
    lower_is_better: Literal[True]
    affine: AffineConfig
    bootstrap: BaselineBootstrapConfig
    historical_reference: HistoricalReferenceConfig


class RankingEvaluationConfig(StrictModel):
    """Lower-is-better ranking metric grids."""

    lower_is_better: Literal[True]
    true_top_m: list[int]
    predicted_budget_k: list[int]
    ndcg_k: list[int]
    pairwise_tie_threshold_kcal: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_positive_cutoffs(self) -> RankingEvaluationConfig:
        """Require nonempty, unique, positive rank cutoffs."""

        for name in ("true_top_m", "predicted_budget_k", "ndcg_k"):
            values = getattr(self, name)
            if not values or any(value < 1 for value in values):
                raise ValueError(f"{name} must contain positive integers")
            if len(values) != len(set(values)):
                raise ValueError(f"{name} values must be unique")
        return self


class BootstrapCIConfig(StrictModel):
    """Report-level bootstrap interval declaration."""

    repeats: int = Field(ge=1)
    confidence: float = Field(gt=0.0, lt=1.0)


class PromotionConfig(StrictModel):
    """Pre-registered Phase 4 promotion thresholds."""

    min_spearman_delta: float
    min_kendall_delta: float
    max_regret_increase_kcal: float = Field(ge=0.0)
    require_no_family_collapse: bool


class BlindHoldoutConfig(StrictModel):
    """Availability of a genuine unseen holdout."""

    status: Literal["missing"]
    reason: str


class EvaluationConfig(StrictModel):
    """Typed validation and ranking configuration."""

    protocols: list[
        Literal[
            "loocv",
            "leave_axis_a_out",
            "leave_axis_b_out",
            "combined_family_holdout_if_supported",
            "size_extrapolation",
        ]
    ]
    ranking: RankingEvaluationConfig
    bootstrap_ci: BootstrapCIConfig
    promotion: PromotionConfig
    blind_holdout: BlindHoldoutConfig

    @field_validator("protocols")
    @classmethod
    def unique_protocols(cls, value: list[str]) -> list[str]:
        """Reject repeated validation protocol declarations."""

        if len(value) != len(set(value)):
            raise ValueError("evaluation protocols must be unique")
        return value


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    """Load a YAML mapping without accepting implicit scalar roots."""

    if not path.is_file():
        raise FileNotFoundError(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"configuration must contain a YAML mapping: {path}")
    return raw


def load_legacy_config(path: Path) -> LegacyConfig:
    """Load and validate a legacy YAML configuration."""

    return LegacyConfig.model_validate(_load_yaml_mapping(path))


def load_data_config(path: Path) -> DataConfig:
    """Load and validate the processed-dataset configuration."""

    return DataConfig.model_validate(_load_yaml_mapping(path))


def load_families_config(path: Path) -> FamiliesConfig:
    """Load and validate family canonicalization configuration."""

    return FamiliesConfig.model_validate(_load_yaml_mapping(path))


def load_baseline_model_config(path: Path) -> BaselineModelConfig:
    """Load and validate the Phase 2 baseline configuration."""

    return BaselineModelConfig.model_validate(_load_yaml_mapping(path))


def load_evaluation_config(path: Path) -> EvaluationConfig:
    """Load and validate the evaluation configuration."""

    return EvaluationConfig.model_validate(_load_yaml_mapping(path))
