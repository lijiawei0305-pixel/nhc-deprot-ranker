"""Phase 4 frozen-evidence promotion-decision figures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
from matplotlib import pyplot as plt


def _finish(
    figure: Any,
    path: Path,
    *,
    n: int,
    protocol: str,
    dataset_version: str,
    decision_version: str,
    note: str,
) -> None:
    figure.text(
        0.5,
        0.01,
        f"n={n} labels | split={protocol} | decision={decision_version} "
        f"| dataset={dataset_version} "
        f"| OOF=true | CI=95% paired-key bootstrap | {note}",
        ha="center",
        fontsize=7,
    )
    figure.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    figure.savefig(path, dpi=160)
    plt.close(figure)


def generate_decision_figures(
    *,
    uncertainty: pd.DataFrame,
    family_collapse: pd.DataFrame,
    family_stability: pd.DataFrame,
    output_dir: Path,
    min_sign_stability: float,
    n: int,
    dataset_version: str,
    decision_version: str,
) -> tuple[Path, ...]:
    """Generate the four Phase 4 comparison and failure-audit plots."""

    output_dir.mkdir(parents=True, exist_ok=False)
    paths: list[Path] = []

    primary = uncertainty.loc[
        uncertainty["comparison"].isin(("B1_minus_B0", "H1_minus_B1"))
        & uncertainty["metric"].isin(("spearman_rho", "kendall_tau"))
    ].copy()
    primary["label"] = (
        primary["comparison"] + " | " + primary["protocol"] + " | " + primary["metric"]
    )
    primary = primary.sort_values(["comparison", "protocol", "metric"]).reset_index(drop=True)
    positions = np.arange(len(primary))
    figure, axis = plt.subplots(figsize=(9.0, 6.2))
    axis.axvline(0.0, color="black", linewidth=1)
    axis.errorbar(
        primary["point_delta"],
        positions,
        xerr=np.vstack(
            (
                primary["point_delta"] - primary["ci_low"],
                primary["ci_high"] - primary["point_delta"],
            )
        ),
        fmt="o",
        capsize=3,
    )
    axis.set_yticks(positions, primary["label"], fontsize=8)
    axis.set(
        title="Primary ranking deltas (candidate minus baseline)",
        xlabel="metric delta; positive favors the candidate",
        ylabel="comparison",
    )
    path = output_dir / "01_primary_metric_deltas.png"
    _finish(
        figure,
        path,
        n=n,
        protocol="three_frozen_outer_protocols",
        dataset_version=dataset_version,
        decision_version=decision_version,
        note="models not refit",
    )
    paths.append(path)

    recall = uncertainty.loc[
        uncertainty["comparison"].eq("H1_minus_B1")
        & uncertainty["metric"].str.startswith("recall_true_top_")
    ].copy()
    recall["label"] = (
        recall["protocol"]
        + " | "
        + recall["metric"].str.replace("recall_true_top_", "T", regex=False)
    )
    recall = recall.sort_values(["protocol", "metric"]).reset_index(drop=True)
    positions = np.arange(len(recall))
    figure, axis = plt.subplots(figsize=(10.0, max(6.0, len(recall) * 0.28)))
    axis.axvline(0.0, color="black", linewidth=1)
    axis.errorbar(
        recall["point_delta"],
        positions,
        xerr=np.vstack(
            (
                recall["point_delta"] - recall["ci_low"],
                recall["ci_high"] - recall["point_delta"],
            )
        ),
        fmt="o",
        capsize=2,
    )
    axis.set_yticks(positions, recall["label"], fontsize=7)
    axis.set(
        title="H1 minus B1 head-recall deltas",
        xlabel="recall delta; positive favors H1",
        ylabel="protocol and Top-M/Top-K metric",
    )
    path = output_dir / "02_head_recall_deltas.png"
    _finish(
        figure,
        path,
        n=n,
        protocol="three_frozen_outer_protocols",
        dataset_version=dataset_version,
        decision_version=decision_version,
        note="models not refit",
    )
    paths.append(path)

    figure, axis = plt.subplots(figsize=(6.8, 5.8))
    normal = family_collapse.loc[~family_collapse["catastrophic"]]
    catastrophic = family_collapse.loc[family_collapse["catastrophic"]]
    axis.scatter(normal["B1_mae_kcal"], normal["H1_mae_kcal"], alpha=0.7, label="pass")
    if not catastrophic.empty:
        axis.scatter(
            catastrophic["B1_mae_kcal"],
            catastrophic["H1_mae_kcal"],
            color="tab:red",
            marker="x",
            s=70,
            label="catastrophic",
        )
        for row in catastrophic.to_dict("records"):
            axis.annotate(
                str(row["held_out_group"]),
                (float(row["B1_mae_kcal"]), float(row["H1_mae_kcal"])),
                fontsize=7,
            )
    upper = float(max(family_collapse["B1_mae_kcal"].max(), family_collapse["H1_mae_kcal"].max()))
    axis.plot([0.0, upper], [0.0, upper], color="black", linestyle="--", linewidth=1)
    axis.legend()
    axis.set(
        title="Held-out family error audit",
        xlabel="B1 family MAE (kcal/mol)",
        ylabel="H1 family MAE (kcal/mol)",
    )
    path = output_dir / "03_family_collapse_audit.png"
    _finish(
        figure,
        path,
        n=n,
        protocol="axis_family_holdout",
        dataset_version=dataset_version,
        decision_version=decision_version,
        note="red requires absolute AND ratio failure",
    )
    paths.append(path)

    figure, axis = plt.subplots(figsize=(7.2, 5.3))
    eligible = family_stability.loc[family_stability["eligible"]]
    ineligible = family_stability.loc[~family_stability["eligible"]]
    axis.axhline(min_sign_stability, color="tab:red", linestyle="--", label="registered threshold")
    axis.scatter(
        ineligible["support"],
        ineligible["conditional_sign_stability"],
        alpha=0.45,
        label="support below gate",
    )
    axis.scatter(
        eligible["support"],
        eligible["conditional_sign_stability"],
        alpha=0.8,
        label="gate-eligible",
    )
    unstable = eligible.loc[~eligible["stable"]]
    for row in unstable.to_dict("records"):
        axis.annotate(
            f"{row['term']}:{row['level']}",
            (float(row["support"]), float(row["conditional_sign_stability"])),
            fontsize=7,
        )
    axis.legend()
    axis.set(
        title="Bootstrap family-offset stability",
        xlabel="original label support",
        ylabel="conditional sign stability",
        ylim=(0.45, 1.02),
    )
    path = output_dir / "04_family_stability_audit.png"
    _finish(
        figure,
        path,
        n=n,
        protocol="full_fit_fixed_penalty_bootstrap",
        dataset_version=dataset_version,
        decision_version=decision_version,
        note="absence is not a sign flip",
    )
    paths.append(path)
    return tuple(paths)
