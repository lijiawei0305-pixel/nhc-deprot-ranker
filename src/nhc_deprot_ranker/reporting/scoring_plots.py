"""Phase 5 full-scoring and acquisition figures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
import pandas as pd

matplotlib.use("Agg")
from matplotlib import pyplot as plt


def _finish(
    figure: Any,
    path: Path,
    *,
    n: int,
    protocol: str,
    version: str,
    dataset_version: str,
    note: str,
) -> None:
    provenance = (
        f"n={n} | split={protocol} | version={version} | dataset={dataset_version} | OOF=false"
    )
    figure.text(
        0.5,
        0.01,
        f"{provenance}\nCI={note}",
        ha="center",
        va="bottom",
        fontsize=7,
    )
    figure.tight_layout(rect=(0.0, 0.09, 1.0, 1.0))
    figure.savefig(path, dpi=160)
    plt.close(figure)


def generate_scoring_figures(
    *,
    scored: pd.DataFrame,
    summary: dict[str, Any],
    output_dir: Path,
    dataset_version: str,
    score_version: str,
) -> tuple[Path, ...]:
    """Generate four audit plots for the complete candidate score table."""

    output_dir.mkdir(parents=True, exist_ok=False)
    paths: list[Path] = []
    n = len(scored)

    figure, axis = plt.subplots(figsize=(7.0, 4.8))
    axis.hist(scored["xtb_deprot_kcal"], bins=80, alpha=0.8)
    x_min, x_max = summary["baseline_training_range"]
    axis.axvline(x_min, color="tab:red", linestyle="--", label="labeled xTB range")
    axis.axvline(x_max, color="tab:red", linestyle="--")
    axis.legend()
    axis.set(
        title="Full-pool B0 score distribution",
        xlabel="xTB deprotonation electronic energy (kcal/mol)",
        ylabel="candidate count",
    )
    path = output_dir / "01_xtb_rank_distribution.png"
    _finish(
        figure,
        path,
        n=n,
        protocol="full_pool_B0_order",
        version=score_version,
        dataset_version=dataset_version,
        note="none; red=labeled_range",
    )
    paths.append(path)

    sample_step = max(1, len(scored) // 20000)
    sample = scored.iloc[::sample_step]
    figure, axis = plt.subplots(figsize=(7.0, 5.0))
    axis.scatter(
        sample["xtb_deprot_kcal"],
        sample["prediction_interval_width_kcal"],
        s=5,
        alpha=0.25,
    )
    axis.axhline(
        summary["high_uncertainty_interval_width_threshold_kcal"],
        color="tab:red",
        linestyle="--",
        label="labeled-query p95 threshold",
    )
    axis.legend()
    axis.set(
        title="B1 companion interval width vs xTB",
        xlabel="xTB (kcal/mol)",
        ylabel="p95-p05 width (kcal/mol)",
    )
    path = output_dir / "02_b1_interval_width_vs_xtb.png"
    _finish(
        figure,
        path,
        n=n,
        protocol="full_pool_B1_companion",
        version=score_version,
        dataset_version=dataset_version,
        note="90% coefficient-bootstrap interval; sampled display",
    )
    paths.append(path)

    counts = pd.Series(
        {
            "baseline extrapolation": summary["baseline_extrapolation"],
            "size unavailable": summary["size_unavailable"],
            "unseen axis A": summary["unseen_axis_a"],
            "unseen axis B": summary["unseen_axis_b"],
            "sparse family": summary["sparse_family"],
            "high uncertainty": summary["high_uncertainty"],
            "core in-domain": summary["core_model_in_domain"],
        }
    )
    figure, axis = plt.subplots(figsize=(8.5, 4.8))
    counts.plot.bar(ax=axis)
    axis.set(title="Applicability audit counts", xlabel="status", ylabel="candidate count")
    axis.tick_params(axis="x", labelrotation=35)
    path = output_dir / "03_applicability_counts.png"
    _finish(
        figure,
        path,
        n=n,
        protocol="full_pool_applicability",
        version=score_version,
        dataset_version=dataset_version,
        note="B1 parameter uncertainty only",
    )
    paths.append(path)

    coverage = pd.Series(
        {
            "both axes seen": summary["both_axes_seen"],
            "axis A unseen": summary["unseen_axis_a"],
            "axis B unseen": summary["unseen_axis_b"],
            "sparse seen axis": summary["sparse_family"],
        }
    )
    figure, axis = plt.subplots(figsize=(7.2, 4.7))
    coverage.plot.bar(ax=axis)
    axis.set(title="High-fidelity family-support coverage", xlabel="coverage", ylabel="rows")
    axis.tick_params(axis="x", labelrotation=25)
    path = output_dir / "04_family_support_coverage.png"
    _finish(
        figure,
        path,
        n=n,
        protocol="71_label_family_lookup",
        version=score_version,
        dataset_version=dataset_version,
        note="none",
    )
    paths.append(path)
    return tuple(paths)


def generate_acquisition_figures(
    *,
    selected: pd.DataFrame,
    output_dir: Path,
    dataset_version: str,
    acquisition_version: str,
) -> tuple[Path, ...]:
    """Generate four audit plots for the proposed local high-fidelity batch."""

    output_dir.mkdir(parents=True, exist_ok=False)
    paths: list[Path] = []
    n = len(selected)

    figure, axis = plt.subplots(figsize=(7.2, 4.7))
    selected["acquisition_bucket"].value_counts().sort_index().plot.bar(ax=axis)
    axis.set(title="Acquisition quota realization", xlabel="bucket", ylabel="selected count")
    axis.tick_params(axis="x", labelrotation=25)
    path = output_dir / "01_acquisition_buckets.png"
    _finish(
        figure,
        path,
        n=n,
        protocol="deterministic_quota_selection",
        version=acquisition_version,
        dataset_version=dataset_version,
        note="none",
    )
    paths.append(path)

    figure, axis = plt.subplots(figsize=(7.0, 5.0))
    for bucket, subset in selected.groupby("acquisition_bucket", sort=True):
        axis.scatter(
            subset["production_rank"],
            subset["prediction_interval_width_kcal"],
            label=bucket,
            s=30,
            alpha=0.8,
        )
    axis.set_xscale("log")
    axis.legend(fontsize=7)
    axis.set(
        title="Selected rank vs B1 companion uncertainty",
        xlabel="B0 production rank (log scale)",
        ylabel="p95-p05 width (kcal/mol)",
    )
    path = output_dir / "02_selected_rank_vs_uncertainty.png"
    _finish(
        figure,
        path,
        n=n,
        protocol="selected_unlabeled_batch",
        version=acquisition_version,
        dataset_version=dataset_version,
        note="90% B1 coefficient-bootstrap interval",
    )
    paths.append(path)

    family_counts = pd.Series(
        {
            "unique combined": selected["combined_family"].nunique(),
            "unique axis A": selected["axis_a_family"].nunique(),
            "unique axis B": selected["axis_b_family"].nunique(),
            "unseen axis A": (~selected["axis_a_seen_in_training"]).sum(),
            "unseen axis B": (~selected["axis_b_seen_in_training"]).sum(),
        }
    )
    figure, axis = plt.subplots(figsize=(7.5, 4.7))
    family_counts.plot.bar(ax=axis)
    axis.set(title="Selected family coverage", xlabel="coverage", ylabel="count")
    axis.tick_params(axis="x", labelrotation=25)
    path = output_dir / "03_selected_family_coverage.png"
    _finish(
        figure,
        path,
        n=n,
        protocol="selected_unlabeled_batch",
        version=acquisition_version,
        dataset_version=dataset_version,
        note="none",
    )
    paths.append(path)

    status_counts = pd.Series(
        {
            "baseline extrapolation": (~selected["baseline_in_training_range"]).sum(),
            "size unavailable": (~selected["size_available"]).sum(),
            "sparse family": selected["sparse_family"].sum(),
            "high uncertainty": selected["high_uncertainty"].sum(),
            "core in-domain": selected["core_model_in_domain"].sum(),
        }
    )
    figure, axis = plt.subplots(figsize=(7.5, 4.7))
    status_counts.plot.bar(ax=axis)
    axis.set(title="Selected applicability warnings", xlabel="status", ylabel="selected count")
    axis.tick_params(axis="x", labelrotation=25)
    path = output_dir / "04_selected_applicability.png"
    _finish(
        figure,
        path,
        n=n,
        protocol="selected_unlabeled_batch",
        version=acquisition_version,
        dataset_version=dataset_version,
        note="B1 parameter uncertainty only",
    )
    paths.append(path)
    return tuple(paths)
