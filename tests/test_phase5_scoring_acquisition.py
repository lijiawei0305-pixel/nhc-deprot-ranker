"""Phase 5 B0/B1 scoring, applicability, quota, and diversity tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nhc_deprot_ranker.acquisition.quotas import largest_remainder_quotas
from nhc_deprot_ranker.acquisition.scoring import (
    affine_bootstrap_uncertainty,
    score_candidate_frame,
)
from nhc_deprot_ranker.acquisition.selection import select_acquisition_batch
from nhc_deprot_ranker.config import load_acquisition_config
from nhc_deprot_ranker.models.base import ModelInputError


def _candidates(n: int = 120) -> pd.DataFrame:
    rank = np.arange(1, n + 1)
    x = np.linspace(50.0, 120.0, n)
    return pd.DataFrame(
        {
            "inchikey": [f"KEY-{index:04d}" for index in range(n)],
            "smiles_cation": [f"C[N+]({index % 5})(C)C" for index in range(n)],
            "smiles_neutral": [f"CN({index % 5})C" for index in range(n)],
            "xtb_deprot_kcal": x,
            "xtb_rank": rank,
            "xtb_percentile": (rank - 1) / (n - 1),
            "n1_frag": [f"N{index % 7}" for index in range(n)],
            "n3_frag": [f"N{(index + 1) % 7}" for index in range(n)],
            "c4_frag": [f"C{index % 6}" for index in range(n)],
            "c5_frag": [f"C{(index + 2) % 6}" for index in range(n)],
            "skeleton": ["imidazolium"] * n,
            "axis_a_family": [f"A{index % 20}" for index in range(n)],
            "axis_b_family": [f"B{index % 18}" for index in range(n)],
            "combined_family": [f"F{index % 60}" for index in range(n)],
            "n_heavy_atoms": pd.Series([pd.NA] * n, dtype="Int64"),
            "n_electrons": pd.Series([pd.NA] * n, dtype="Int64"),
        }
    )


def _bootstrap() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "repeat": np.arange(20),
            "beta_0": np.linspace(190.0, 200.0, 20),
            "rho": np.linspace(0.65, 0.78, 20),
            "used_pseudoinverse": [False] * 20,
        }
    )


def _coefficients() -> dict[str, object]:
    return {
        "B0": {"x_min": 55.0, "x_max": 115.0},
        "B1": {"beta_0": 196.0, "rho": 0.72, "x_min": 55.0, "x_max": 115.0},
    }


def test_chunked_affine_uncertainty_matches_unbounded_reference() -> None:
    x = np.linspace(40.0, 125.0, 17)
    bootstrap = _bootstrap()
    actual = affine_bootstrap_uncertainty(x, bootstrap, chunk_rows=3)
    reference = (
        bootstrap["beta_0"].to_numpy()[:, None] + bootstrap["rho"].to_numpy()[:, None] * x[None, :]
    )
    assert actual.mean == pytest.approx(np.mean(reference, axis=0))
    assert actual.standard_deviation == pytest.approx(np.std(reference, axis=0, ddof=1))
    assert actual.p05 == pytest.approx(np.quantile(reference, 0.05, axis=0))
    assert actual.p50 == pytest.approx(np.quantile(reference, 0.50, axis=0))
    assert actual.p95 == pytest.approx(np.quantile(reference, 0.95, axis=0))


def test_affine_uncertainty_rejects_nonpositive_slope() -> None:
    bootstrap = _bootstrap()
    bootstrap.loc[0, "rho"] = 0.0
    with pytest.raises(ModelInputError, match="positive"):
        affine_bootstrap_uncertainty(np.asarray([1.0, 2.0]), bootstrap, chunk_rows=2)


def test_b0_scoring_preserves_rank_and_reports_applicability() -> None:
    candidates = _candidates()
    labels = pd.DataFrame({"inchikey": candidates["inchikey"].iloc[10:16].tolist()})
    config = load_acquisition_config(Path("configs/acquisition.yaml"))
    scored, summary = score_candidate_frame(
        candidates=candidates,
        labels=labels,
        coefficients=_coefficients(),
        bootstrap_coefficients=_bootstrap(),
        config=config,
        production_model_sha256="a" * 64,
        decision_manifest_sha256="b" * 64,
    )
    assert np.array_equal(scored["production_rank"], scored["xtb_rank"])
    assert np.array_equal(scored["calibrated_rank"], scored["xtb_rank"])
    assert scored["rank_shift"].eq(0).all()
    assert scored.loc[0, "probability_top_10"] == 1.0
    assert scored.loc[10, "probability_top_10"] == 0.0
    assert (~scored["size_available"]).all()
    assert scored["applicability_status"].str.contains("size_unavailable").all()
    assert not scored["applicability_status"].eq("in_domain").any()
    assert summary["size_unavailable"] == len(candidates)
    assert summary["rank_shift_nonzero"] == 0


def test_quota_rounding_and_selection_are_exact_and_deterministic() -> None:
    candidates = _candidates()
    labels = pd.DataFrame({"inchikey": candidates["inchikey"].iloc[10:16].tolist()})
    config = load_acquisition_config(Path("configs/acquisition.yaml"))
    scored, _ = score_candidate_frame(
        candidates=candidates,
        labels=labels,
        coefficients=_coefficients(),
        bootstrap_coefficients=_bootstrap(),
        config=config,
        production_model_sha256="a" * 64,
        decision_manifest_sha256="b" * 64,
    )
    assert largest_remainder_quotas(config) == {
        "predicted_top_region": 15,
        "cutoff_region": 13,
        "chemical_family_diversity": 12,
        "uncertain_ood_conflict": 10,
    }
    first, first_summary = select_acquisition_batch(
        scored=scored, labeled_keys=set(labels["inchikey"]), config=config
    )
    second, second_summary = select_acquisition_batch(
        scored=scored, labeled_keys=set(labels["inchikey"]), config=config
    )
    assert first["inchikey"].tolist() == second["inchikey"].tolist()
    assert first_summary == second_summary
    assert len(first) == 50
    assert first["inchikey"].nunique() == 50
    assert not set(first["inchikey"]) & set(labels["inchikey"])
    assert first_summary["realized_quotas"] == largest_remainder_quotas(config)
    assert first["rank_shift_component"].eq(0.0).all()
    assert first["reason_codes"].str.contains("rank_shift_zero_by_positive_affine").all()
