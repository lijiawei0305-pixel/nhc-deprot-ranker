"""Typed YAML configuration for legacy source discovery."""

from __future__ import annotations

import math
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


class SlopePenaltyConfig(StrictModel):
    """Optional original-scale slope prior interface."""

    free: Literal[True]
    prior_center: float
    penalty: float = Field(ge=0.0)


class HierarchicalRegularizationConfig(StrictModel):
    """Finite coarse and refinement grids for H1."""

    shared_family_coarse_grid: list[float]
    axis_specific_refinement: Literal[True]
    lambda_skeleton_grid: list[float]
    lambda_axis_a_grid: list[float]
    lambda_axis_b_grid: list[float]

    @model_validator(mode="after")
    def validate_grids(self) -> HierarchicalRegularizationConfig:
        """Require finite non-negative unique grids without silent sorting."""

        for name in (
            "shared_family_coarse_grid",
            "lambda_skeleton_grid",
            "lambda_axis_a_grid",
            "lambda_axis_b_grid",
        ):
            values = getattr(self, name)
            if not values or any(not math.isfinite(value) or value < 0.0 for value in values):
                raise ValueError(f"{name} must contain finite non-negative values")
            if len(values) != len(set(values)):
                raise ValueError(f"{name} values must be unique")
        return self


class HierarchicalBootstrapConfig(StrictModel):
    """H1 fixed-penalty bootstrap settings."""

    development_repeats: int = Field(ge=1)
    final_repeats: int = Field(ge=1)
    seed: int
    regularization_policy: Literal["fixed_from_nested_cv"]


class InnerCVConfig(StrictModel):
    """Deterministic inner-fold settings."""

    folds: int = Field(ge=2)
    seed: int


class NumericalSolverConfig(StrictModel):
    """Linear-system conditioning policy."""

    condition_number_threshold: float = Field(gt=1.0)


class HierarchicalModelConfig(StrictModel):
    """Typed Phase 3 H1 configuration."""

    model_name: Literal["hierarchical_linear"]
    model_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    dataset_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    baseline_result_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    expected_label_rows: int = Field(ge=3)
    target_column: Literal["dft_deprot_electronic_kcal"]
    baseline_column: Literal["xtb_deprot_kcal"]
    lower_is_better: Literal[True]
    family_terms: tuple[
        Literal["skeleton"],
        Literal["axis_a_family"],
        Literal["axis_b_family"],
    ]
    include_size: Literal[False]
    size_column: Literal["n_electrons", "n_heavy_atoms"]
    slope: SlopePenaltyConfig
    regularization: HierarchicalRegularizationConfig
    bootstrap: HierarchicalBootstrapConfig
    unknown_family_policy: Literal["zero_effect"]
    skeleton_policy: Literal["inactive_if_single_level"]
    inner_cv: InnerCVConfig
    numerical: NumericalSolverConfig


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
    seed: int


class StableImprovementConfig(StrictModel):
    """Point and paired-bootstrap stability rule for a claimed improvement."""

    min_delta: float = Field(ge=0.0)
    require_95_percent_lower_bound_nonnegative: Literal[True]


class FamilyCollapseConfig(StrictModel):
    """Operational definition of catastrophic held-out-family error."""

    max_heldout_mae_increase_kcal: float = Field(gt=0.0)
    max_heldout_mae_ratio: float = Field(gt=1.0)
    catastrophic_requires_both: Literal[True]


class FamilyOffsetStabilityConfig(StrictModel):
    """Bootstrap sign-stability rule for supported family offsets."""

    minimum_support: int = Field(ge=1)
    min_conditional_sign_stability: float = Field(ge=0.5, le=1.0)


class PromotionConfig(StrictModel):
    """Pre-registered Phase 4 promotion thresholds."""

    min_spearman_delta: float
    min_kendall_delta: float
    max_regret_increase_kcal: float = Field(ge=0.0)
    require_no_family_collapse: Literal[True]
    primary_rank: StableImprovementConfig
    family_collapse: FamilyCollapseConfig
    family_offset_stability: FamilyOffsetStabilityConfig
    head_recall: StableImprovementConfig


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


class AcquisitionWeightsConfig(StrictModel):
    """Non-negative Phase 5 acquisition score weights."""

    top: float = Field(ge=0.0)
    uncertainty: float = Field(ge=0.0)
    rank_shift: float = Field(ge=0.0)
    family_novelty: float = Field(ge=0.0)
    cutoff: float = Field(ge=0.0)
    diversity: float = Field(ge=0.0)


class AcquisitionQuotasConfig(StrictModel):
    """Configured acquisition-bucket fractions."""

    predicted_top_region: float = Field(ge=0.0, le=1.0)
    cutoff_region: float = Field(ge=0.0, le=1.0)
    chemical_family_diversity: float = Field(ge=0.0, le=1.0)
    uncertain_ood_conflict: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def sum_to_one(self) -> AcquisitionQuotasConfig:
        """Require an exact complete allocation within float tolerance."""

        total = (
            self.predicted_top_region
            + self.cutoff_region
            + self.chemical_family_diversity
            + self.uncertain_ood_conflict
        )
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("acquisition quotas must sum to 1")
        return self


class AcquisitionConfig(StrictModel):
    """Typed Phase 5 full-score and acquisition policy."""

    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    dataset_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    top_k: int = Field(ge=1)
    score_top_n: int = Field(ge=1)
    acquisition_batch_size: int = Field(ge=1)
    probability_top_k: list[int]
    sparse_family_min_support: int = Field(ge=1)
    high_uncertainty_quantile: float = Field(gt=0.0, lt=1.0)
    bootstrap_chunk_rows: int = Field(ge=1)
    cutoff_rank: int = Field(ge=1)
    cutoff_window: int = Field(ge=1)
    top_region_max_rank: int = Field(ge=1)
    quota_rounding: Literal["largest_remainder_config_order"]
    diversity_fields: tuple[
        Literal["combined_family"],
        Literal["axis_a_family"],
        Literal["axis_b_family"],
        Literal["n1_frag"],
        Literal["n3_frag"],
        Literal["c4_frag"],
        Literal["c5_frag"],
    ]
    weights: AcquisitionWeightsConfig
    quotas: AcquisitionQuotasConfig
    exclude_already_labeled: Literal[True]
    submit_hpc: Literal[False]
    seed: int

    @model_validator(mode="after")
    def validate_phase5_policy(self) -> AcquisitionConfig:
        """Require unique cutoffs/fields and the approved B0/B1 Top-50 policy."""

        if not self.probability_top_k or any(value < 1 for value in self.probability_top_k):
            raise ValueError("probability_top_k must contain positive values")
        if len(self.probability_top_k) != len(set(self.probability_top_k)):
            raise ValueError("probability_top_k values must be unique")
        if self.top_k not in self.probability_top_k:
            raise ValueError("top_k must be included in probability_top_k")
        if len(self.diversity_fields) != len(set(self.diversity_fields)):
            raise ValueError("diversity_fields must be unique")
        if self.cutoff_rank != self.top_k:
            raise ValueError("approved Phase 5 cutoff_rank must equal top_k")
        if self.score_top_n < max(self.probability_top_k):
            raise ValueError("score_top_n must cover the largest Top-K probability")
        return self


class DFTPlanBucketCounts(StrictModel):
    """One deterministic Phase 6 batch allocation."""

    predicted_top_region: int = Field(ge=0)
    cutoff_region: int = Field(ge=0)
    chemical_family_diversity: int = Field(ge=0)
    uncertain_ood_conflict: int = Field(ge=0)

    def total(self) -> int:
        """Return the number of candidates assigned to this batch."""

        return sum(self.model_dump().values())


class DFTPlanBatchConfig(StrictModel):
    """Named batch and its exact acquisition-bucket counts."""

    batch_id: str = Field(pattern=r"^batch_[0-9]{2}$")
    counts: DFTPlanBucketCounts


class DFTPlanProtocolConfig(StrictModel):
    """Frozen electronic-label protocol for the non-executable handoff."""

    label_protocol_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    reaction: Literal["NHC-H+ -> NHC + H+"]
    phase: Literal["gas"]
    method: Literal["B3LYP"]
    dispersion: Literal["D3(BJ)"]
    basis: Literal["def2-SVP"]
    geometry_optimizer: Literal["geomeTRIC"]
    cation_charge: Literal[1]
    cation_multiplicity: Literal[1]
    neutral_charge: Literal[0]
    neutral_multiplicity: Literal[1]
    target_definition: Literal["electronic_deprotonation_energy"]
    label_quality: Literal["electronic_energy_only"]
    hartree_to_kcal_mol: float = Field(gt=0.0)
    proton_constant_kcal: float
    lower_is_better: Literal[True]
    hessian_computed: Literal[False]

    @model_validator(mode="after")
    def validate_electronic_label_constants(self) -> DFTPlanProtocolConfig:
        """Lock the finite legacy-compatible electronic-label constants."""

        if not math.isfinite(self.hartree_to_kcal_mol) or not math.isclose(
            self.hartree_to_kcal_mol, 627.509474, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError("Phase 6 Hartree conversion must equal 627.509474")
        if not math.isfinite(self.proton_constant_kcal) or not math.isclose(
            self.proton_constant_kcal, -6.28, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError("Phase 6 proton constant must equal -6.28 kcal/mol")
        return self


class LegacyInterfaceFileConfig(StrictModel):
    """Portable identity for one audited legacy interface file."""

    path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def require_relative_legacy_path(cls, value: Path) -> Path:
        """Forbid personal absolute paths and traversal in tracked configuration."""

        if value.is_absolute() or ".." in value.parts:
            raise ValueError("legacy interface path must be safe and relative")
        return value


class LegacyDFTInterfaceConfig(StrictModel):
    """Audited legacy commit and file identities used only as an interface contract."""

    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    files: list[LegacyInterfaceFileConfig]
    relevant_files_match_commit: Literal[True]
    legacy_m2_handoff_ready: Literal[True]
    legacy_m4_execution_ready: Literal[False]
    compatibility_blockers: tuple[Literal["blocked_no_xyz"], Literal["blocked_runner_extra_steps"]]

    @field_validator("files")
    @classmethod
    def unique_interface_paths(
        cls, value: list[LegacyInterfaceFileConfig]
    ) -> list[LegacyInterfaceFileConfig]:
        """Reject repeated or empty audited interface lists."""

        paths = [item.path.as_posix() for item in value]
        if not paths or len(paths) != len(set(paths)):
            raise ValueError("legacy interface files must be nonempty and unique")
        return value


class DFTPlanConfig(StrictModel):
    """Typed Phase 6 local-only DFT execution-plan policy."""

    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    dataset_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    acquisition_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    expected_candidates: int = Field(ge=1)
    expected_labels: int = Field(ge=1)
    batch_size: int = Field(ge=1)
    bucket_order: tuple[
        Literal["predicted_top_region"],
        Literal["cutoff_region"],
        Literal["chemical_family_diversity"],
        Literal["uncertain_ood_conflict"],
    ]
    batches: list[DFTPlanBatchConfig]
    smoke_per_bucket: Literal[1]
    protocol: DFTPlanProtocolConfig
    legacy_interface: LegacyDFTInterfaceConfig
    geometry_generated: Literal[False]
    geometry_status: Literal["not_generated"]
    quantum_chemistry_run: Literal[False]
    execution_ready: Literal[False]
    server_write_authorized: Literal[False]
    submit_hpc: Literal[False]
    seed: int

    @model_validator(mode="after")
    def validate_plan_allocation(self) -> DFTPlanConfig:
        """Require the approved five-batch allocation and exact Phase 5 totals."""

        expected_order = (
            "predicted_top_region",
            "cutoff_region",
            "chemical_family_diversity",
            "uncertain_ood_conflict",
        )
        if self.bucket_order != expected_order:
            raise ValueError("Phase 6 bucket order must match the frozen Phase 5 order")
        batch_ids = [batch.batch_id for batch in self.batches]
        if not batch_ids or len(batch_ids) != len(set(batch_ids)):
            raise ValueError("Phase 6 batch ids must be nonempty and unique")
        if batch_ids != sorted(batch_ids):
            raise ValueError("Phase 6 batches must be ordered by batch_id")
        if self.expected_candidates != 50 or self.batch_size != 10:
            raise ValueError("Phase 6 must contain exactly five batches of ten candidates")
        if batch_ids != [f"batch_{index:02d}" for index in range(1, 6)]:
            raise ValueError("Phase 6 batch ids must be exactly batch_01 through batch_05")
        expected_matrix = (
            (3, 3, 2, 2),
            (3, 3, 2, 2),
            (3, 3, 2, 2),
            (3, 2, 3, 2),
            (3, 2, 3, 2),
        )
        realized_matrix = tuple(
            tuple(int(getattr(batch.counts, bucket)) for bucket in expected_order)
            for batch in self.batches
        )
        if realized_matrix != expected_matrix:
            raise ValueError("Phase 6 batch allocation matrix changed")
        if any(batch.counts.total() != self.batch_size for batch in self.batches):
            raise ValueError("every Phase 6 batch must contain exactly batch_size rows")
        if len(self.batches) * self.batch_size != self.expected_candidates:
            raise ValueError("Phase 6 batches do not cover expected_candidates")
        totals = {
            bucket: sum(int(getattr(batch.counts, bucket)) for batch in self.batches)
            for bucket in expected_order
        }
        if totals != {
            "predicted_top_region": 15,
            "cutoff_region": 13,
            "chemical_family_diversity": 12,
            "uncertain_ood_conflict": 10,
        }:
            raise ValueError("Phase 6 allocation must preserve the approved 15/13/12/10 quotas")
        return self


class GeometrySmokeCanonicalInputConfig(StrictModel):
    """Byte identity of the four-row legacy M2 request CSV."""

    name: Literal["smoke_candidates.csv"]
    bytes: Literal[542]
    sha256: Literal["f486f93a2d58fb144c05a7340fd432334eeec46385c9319aca34d2e1b5c4cc87"]
    columns: tuple[Literal["InChIKey"], Literal["SMILES_cation"], Literal["SMILES_neutral"]]


class GeometrySmokePhase6InputsConfig(StrictModel):
    """Frozen checked-in and ignored Phase 6 artifact identities."""

    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    smoke_csv_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidates_csv_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class GeometrySmokeLegacyFileConfig(StrictModel):
    """One portable, hash-locked legacy M2 source identity."""

    path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def require_safe_relative_path(cls, value: Path) -> Path:
        """Reject host-specific, traversing, or non-canonical source paths."""

        if value.is_absolute() or ".." in value.parts or value.as_posix().startswith("./"):
            raise ValueError("geometry-smoke legacy path must be safe and relative")
        return value


class GeometrySmokeLegacyConfig(StrictModel):
    """Audited legacy M2 source commit and exact files."""

    commit: Literal["44a68bf70031bd75799f42c4a02adf71f1b99d31"]
    gen_3d: GeometrySmokeLegacyFileConfig
    structure_gen: GeometrySmokeLegacyFileConfig

    @model_validator(mode="after")
    def validate_m2_files(self) -> GeometrySmokeLegacyConfig:
        """Lock the only two legacy source paths that the smoke may use."""

        expected = {
            "gen_3d": (
                "scripts/mol/gen_3d.py",
                "d23c7ad9a6e35948949f6485b53caafb0f3f5705148f642e3a4a30fb589a946a",
            ),
            "structure_gen": (
                "scripts/mol/structure_gen.py",
                "a50b50b9967ac9e8203b398fe69f3daebf40a144f37dae8e0aa086e613ad1365",
            ),
        }
        for field, (path, digest) in expected.items():
            item = getattr(self, field)
            if item.path.as_posix() != path or item.sha256 != digest:
                raise ValueError(f"Phase 7 legacy {field} identity changed")
        return self


class GeometrySmokeM2Config(StrictModel):
    """The only molecular geometry operation authorized in Phase 7."""

    environment_script: Path
    embedding_method: Literal["ETKDGv3"]
    seed: Literal[42]
    num_conformers: Literal[10]
    use_random_coords: Literal[False]
    force_field_primary: Literal["MMFF94"]
    force_field_fallback: Literal["UFF"]
    parallel: Literal[1]
    geometry_quality: Literal["initial_force_field_geometry"]
    force_field_convergence: Literal["unavailable_legacy_m2"]

    @field_validator("environment_script")
    @classmethod
    def require_molecular_environment(cls, value: Path) -> Path:
        """Permit only the audited project-relative molecular environment."""

        if value.as_posix() != "env/envs/molenv.sh":
            raise ValueError("Phase 7 must source only env/envs/molenv.sh")
        return value


class GeometrySmokeConfig(StrictModel):
    """Strict Phase 7 four-candidate geometry bundle policy."""

    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    phase6_plan_version: Literal["v001"]
    expected_smoke_count: Literal[4]
    ordered_keys: tuple[str, ...]
    canonical_input: GeometrySmokeCanonicalInputConfig
    phase6_inputs: GeometrySmokePhase6InputsConfig
    legacy: GeometrySmokeLegacyConfig
    m2: GeometrySmokeM2Config
    geometry_scope: Literal["smoke_only"]
    geometry_generated: Literal[False]
    quantum_chemistry_run: Literal[False]
    hessian_computed: Literal[False]
    old_m4_run: Literal[False]
    dedicated_runner_run: Literal[False]
    submit_hpc: Literal[False]

    @model_validator(mode="after")
    def validate_frozen_smoke(self) -> GeometrySmokeConfig:
        """Lock the exact preregistered Phase 6 smoke identity and order."""

        expected = (
            "IJWCXRPLHNQISE-UHFFFAOYSA-N",
            "LBNPGYISTSLAHY-UHFFFAOYSA-N",
            "QXHIEGFUWOLQIJ-UHFFFAOYSA-N",
            "HQKHXILTVGYEGE-UHFFFAOYSA-N",
        )
        if self.ordered_keys != expected or len(set(self.ordered_keys)) != 4:
            raise ValueError("Phase 7 smoke keys or order changed")
        return self


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


def load_acquisition_config(path: Path) -> AcquisitionConfig:
    """Load and validate the Phase 5 scoring/acquisition configuration."""

    return AcquisitionConfig.model_validate(_load_yaml_mapping(path))


def load_dft_plan_config(path: Path) -> DFTPlanConfig:
    """Load and validate the Phase 6 local execution-plan configuration."""

    return DFTPlanConfig.model_validate(_load_yaml_mapping(path))


def load_geometry_smoke_config(path: Path) -> GeometrySmokeConfig:
    """Load and validate the Phase 7 geometry-smoke bundle policy."""

    return GeometrySmokeConfig.model_validate(_load_yaml_mapping(path))


def load_hierarchical_model_config(path: Path) -> HierarchicalModelConfig:
    """Load and validate the Phase 3 H1 configuration."""

    return HierarchicalModelConfig.model_validate(_load_yaml_mapping(path))


def load_model_name(path: Path) -> str:
    """Read only the declared model name for CLI dispatch."""

    value = _load_yaml_mapping(path).get("model_name")
    if not isinstance(value, str) or value not in {"baseline_suite", "hierarchical_linear"}:
        raise ValueError(f"unsupported or missing model_name in {path}")
    return value
