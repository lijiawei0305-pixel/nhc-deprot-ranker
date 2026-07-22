"""Auditable Phase 2 baseline figures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
import pandas as pd

matplotlib.use("Agg")
from matplotlib import pyplot as plt


def _finish(
    *,
    figure: Any,
    path: Path,
    n: int,
    protocol: str,
    model_version: str,
    dataset_version: str,
    oof: bool,
    ci: str,
) -> None:
    figure.text(
        0.5,
        0.01,
        f"n={n} | split={protocol} | model={model_version} | dataset={dataset_version} "
        f"| OOF={str(oof).lower()} | CI={ci}",
        ha="center",
        fontsize=7,
    )
    figure.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    figure.savefig(path, dpi=160)
    plt.close(figure)


def generate_baseline_figures(
    *,
    labeled: pd.DataFrame,
    loocv: pd.DataFrame,
    metrics: dict[str, Any],
    coefficients: dict[str, Any],
    output_dir: Path,
    dataset_version: str,
    model_version: str,
) -> tuple[Path, ...]:
    """Generate the baseline-applicable subset of pre-specified figures."""

    output_dir.mkdir(parents=True, exist_ok=False)
    paths: list[Path] = []
    n = len(labeled)
    x = labeled["xtb_deprot_kcal"]
    y = labeled["dft_deprot_electronic_kcal"]

    figure, axis = plt.subplots(figsize=(6.2, 5.0))
    axis.scatter(x, y, s=24, alpha=0.8)
    axis.set(
        title="xTB vs DFT electronic deprotonation energy",
        xlabel="xTB (kcal/mol)",
        ylabel="DFT (kcal/mol)",
    )
    path = output_dir / "01_xtb_vs_dft.png"
    _finish(
        figure=figure,
        path=path,
        n=n,
        protocol="full_labels",
        model_version=model_version,
        dataset_version=dataset_version,
        oof=False,
        ci="none",
    )
    paths.append(path)

    figure, axis = plt.subplots(figsize=(6.2, 5.0))
    axis.scatter(x, y, s=24, alpha=0.75, label="labels")
    ordered = labeled.sort_values("xtb_deprot_kcal")
    line = coefficients["B1"]["beta_0"] + coefficients["B1"]["rho"] * ordered["xtb_deprot_kcal"]
    axis.plot(ordered["xtb_deprot_kcal"], line, color="tab:red", label="full-fit B1")
    axis.legend()
    axis.set(title="Global affine calibration", xlabel="xTB (kcal/mol)", ylabel="DFT (kcal/mol)")
    path = output_dir / "02_affine_calibration.png"
    _finish(
        figure=figure,
        path=path,
        n=n,
        protocol="full_fit",
        model_version=model_version,
        dataset_version=dataset_version,
        oof=False,
        ci="coefficient bootstrap in JSON/Parquet",
    )
    paths.append(path)

    residual = loocv["b1_prediction_kcal"] - loocv["true_dft_kcal"]
    figure, axis = plt.subplots(figsize=(6.2, 4.6))
    axis.axhline(0.0, color="black", linewidth=1)
    axis.scatter(loocv["xtb_deprot_kcal"], residual, s=24, alpha=0.8)
    axis.set(
        title="Affine LOOCV residual vs xTB",
        xlabel="xTB (kcal/mol)",
        ylabel="OOF prediction - DFT (kcal/mol)",
    )
    path = output_dir / "03_affine_oof_residual.png"
    _finish(
        figure=figure,
        path=path,
        n=n,
        protocol="loocv",
        model_version=model_version,
        dataset_version=dataset_version,
        oof=True,
        ci="none",
    )
    paths.append(path)

    for number, prediction_column, title, filename, model in (
        (4, "b0_rank", "True DFT rank vs raw xTB rank", "04_true_rank_vs_xtb_rank.png", "B0"),
        (5, "b1_rank", "True DFT rank vs affine OOF rank", "05_true_rank_vs_affine_rank.png", "B1"),
    ):
        del number
        figure, axis = plt.subplots(figsize=(5.5, 5.2))
        axis.plot([1, n], [1, n], color="black", linewidth=1, linestyle="--")
        axis.scatter(loocv["true_rank"], loocv[prediction_column], s=24, alpha=0.8)
        axis.set(title=title, xlabel="True DFT rank", ylabel=f"{model} predicted rank")
        path = output_dir / filename
        _finish(
            figure=figure,
            path=path,
            n=n,
            protocol="loocv",
            model_version=model_version,
            dataset_version=dataset_version,
            oof=True,
            ci="none",
        )
        paths.append(path)

    loo_metrics = metrics["protocols"]["loocv"]["models"]
    selection_rows: list[dict[str, Any]] = []
    for model in ("B0", "B1"):
        for name, value in loo_metrics[model].items():
            if name.startswith("recall_true_top_"):
                parts = name.removeprefix("recall_true_top_").split("_in_predicted_top_")
                m, k = (int(part) for part in parts)
                selection_rows.append(
                    {
                        "model": model,
                        "m": m,
                        "k": k,
                        "metric": f"M={m}, K={k}",
                        "value": value,
                    }
                )
    selection = pd.DataFrame.from_records(selection_rows).sort_values(["m", "k", "model"])
    metric_order = selection.drop_duplicates(["m", "k"])["metric"].tolist()
    figure, axis = plt.subplots(figsize=(10.0, 4.8))
    selection.pivot(index="metric", columns="model", values="value").loc[metric_order].plot.bar(
        ax=axis
    )
    axis.set(
        title="LOOCV Top-M recall by predicted budget",
        xlabel="selection target",
        ylabel="recall",
        ylim=(0.0, 1.05),
    )
    axis.tick_params(axis="x", labelrotation=45)
    path = output_dir / "06_top_m_recall.png"
    _finish(
        figure=figure,
        path=path,
        n=n,
        protocol="loocv",
        model_version=model_version,
        dataset_version=dataset_version,
        oof=True,
        ci="none",
    )
    paths.append(path)

    for filename, prefix, title, ylabel in (
        ("07_ndcg.png", "ndcg_at_", "LOOCV NDCG@K", "NDCG"),
        ("08_top_k_regret.png", "regret_at_", "LOOCV Top-K regret", "regret (kcal/mol)"),
    ):
        figure, axis = plt.subplots(figsize=(6.5, 4.5))
        for model in ("B0", "B1"):
            points = sorted(
                (int(name.removeprefix(prefix)), float(value))
                for name, value in loo_metrics[model].items()
                if name.startswith(prefix)
            )
            axis.plot(
                [point[0] for point in points],
                [point[1] for point in points],
                marker="o",
                label=model,
            )
        axis.legend()
        axis.set(title=title, xlabel="K", ylabel=ylabel)
        path = output_dir / filename
        _finish(
            figure=figure,
            path=path,
            n=n,
            protocol="loocv",
            model_version=model_version,
            dataset_version=dataset_version,
            oof=True,
            ci="none",
        )
        paths.append(path)

    grouped = pd.DataFrame.from_records(
        [
            {
                "protocol": protocol,
                "B0": metrics["protocols"][protocol]["models"]["B0"]["mae_kcal"],
                "B1": metrics["protocols"][protocol]["models"]["B1"]["mae_kcal"],
            }
            for protocol in ("leave_axis_a_out", "leave_axis_b_out")
        ]
    ).set_index("protocol")
    figure, axis = plt.subplots(figsize=(6.8, 4.5))
    grouped.plot.bar(ax=axis)
    axis.set_yscale("log")
    axis.set(
        title="Grouped OOF absolute error",
        xlabel="held-out family protocol",
        ylabel="MAE (kcal/mol, log scale)",
    )
    axis.tick_params(axis="x", labelrotation=0)
    path = output_dir / "09_grouped_cv_mae.png"
    _finish(
        figure=figure,
        path=path,
        n=n,
        protocol="axis_group_holdout",
        model_version=model_version,
        dataset_version=dataset_version,
        oof=True,
        ci="none",
    )
    paths.append(path)
    return tuple(paths)
