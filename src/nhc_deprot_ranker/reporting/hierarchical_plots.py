"""Auditable Phase 3 H1 figures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
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
    interval: str,
) -> None:
    figure.text(
        0.5,
        0.01,
        f"n={n} | split={protocol} | model={model_version} | dataset={dataset_version} "
        f"| OOF={str(oof).lower()} | CI={interval}",
        ha="center",
        fontsize=7,
    )
    figure.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _forest(
    *,
    effects: pd.DataFrame,
    bootstrap: pd.DataFrame,
    term: str,
    title: str,
    path: Path,
    n: int,
    model_version: str,
    dataset_version: str,
) -> None:
    merged = effects.query("term == @term").merge(
        bootstrap.query("term == @term"), on=["term", "level", "support"], validate="one_to_one"
    )
    merged = merged.sort_values("effect_kcal").reset_index(drop=True)
    positions = np.arange(len(merged))
    figure, axis = plt.subplots(figsize=(8.0, max(6.0, len(merged) * 0.23)))
    lower = merged["effect_kcal"] - merged["effect_p025"]
    upper = merged["effect_p975"] - merged["effect_kcal"]
    axis.errorbar(
        merged["effect_kcal"],
        positions,
        xerr=np.vstack((lower.clip(lower=0.0), upper.clip(lower=0.0))),
        fmt="o",
        markersize=3,
        capsize=2,
    )
    axis.axvline(0.0, color="black", linewidth=1)
    axis.set_yticks(positions, merged["level"], fontsize=7)
    axis.set(title=title, xlabel="family effect (kcal/mol)", ylabel="family level")
    _finish(
        figure=figure,
        path=path,
        n=n,
        protocol="full_fit_fixed_nested_penalty",
        model_version=model_version,
        dataset_version=dataset_version,
        oof=False,
        interval="95% paired-key bootstrap",
    )


def generate_hierarchical_figures(
    *,
    loocv: pd.DataFrame,
    metrics: dict[str, Any],
    family_effects: pd.DataFrame,
    bootstrap_predictions: pd.DataFrame,
    bootstrap_family_effects: pd.DataFrame,
    output_dir: Path,
    dataset_version: str,
    model_version: str,
) -> tuple[Path, ...]:
    """Generate H1-vs-B1 validation and uncertainty figures."""

    output_dir.mkdir(parents=True, exist_ok=False)
    n = len(loocv)
    paths: list[Path] = []

    figure, axis = plt.subplots(figsize=(6.0, 5.3))
    axis.plot([1, n], [1, n], color="black", linestyle="--", linewidth=1)
    axis.scatter(loocv["true_rank"], loocv["b1_rank"], s=22, alpha=0.7, label="B1")
    axis.scatter(loocv["true_rank"], loocv["h1_rank"], s=22, alpha=0.7, label="H1")
    axis.legend()
    axis.set(
        title="LOOCV true rank vs B1/H1 rank", xlabel="true DFT rank", ylabel="OOF predicted rank"
    )
    path = output_dir / "01_true_rank_vs_b1_h1.png"
    _finish(
        figure=figure,
        path=path,
        n=n,
        protocol="loocv",
        model_version=model_version,
        dataset_version=dataset_version,
        oof=True,
        interval="none",
    )
    paths.append(path)

    figure, axis = plt.subplots(figsize=(6.3, 4.7))
    residual = loocv["h1_prediction_kcal"] - loocv["true_dft_kcal"]
    axis.axhline(0.0, color="black", linewidth=1)
    axis.scatter(loocv["xtb_deprot_kcal"], residual, s=24, alpha=0.8)
    axis.set(
        title="H1 LOOCV residual vs xTB",
        xlabel="xTB (kcal/mol)",
        ylabel="H1 OOF residual (kcal/mol)",
    )
    path = output_dir / "02_h1_oof_residual.png"
    _finish(
        figure=figure,
        path=path,
        n=n,
        protocol="loocv",
        model_version=model_version,
        dataset_version=dataset_version,
        oof=True,
        interval="none",
    )
    paths.append(path)

    loo_models = metrics["protocols"]["loocv"]["models"]
    rows: list[dict[str, Any]] = []
    for model in ("B1", "H1"):
        for name, value in loo_models[model].items():
            if name.startswith("recall_true_top_"):
                parts = name.removeprefix("recall_true_top_").split("_in_predicted_top_")
                m, k = (int(part) for part in parts)
                rows.append(
                    {"model": model, "m": m, "k": k, "label": f"M={m}, K={k}", "value": value}
                )
    selection = pd.DataFrame.from_records(rows).sort_values(["m", "k", "model"])
    order = selection.drop_duplicates(["m", "k"])["label"].tolist()
    figure, axis = plt.subplots(figsize=(10.0, 4.8))
    selection.pivot(index="label", columns="model", values="value").loc[order].plot.bar(ax=axis)
    axis.set(
        title="LOOCV Top-M recall: B1 vs H1",
        xlabel="selection target",
        ylabel="recall",
        ylim=(0.0, 1.05),
    )
    axis.tick_params(axis="x", labelrotation=45)
    path = output_dir / "03_top_m_recall_b1_h1.png"
    _finish(
        figure=figure,
        path=path,
        n=n,
        protocol="loocv",
        model_version=model_version,
        dataset_version=dataset_version,
        oof=True,
        interval="none",
    )
    paths.append(path)

    grouped = pd.DataFrame.from_records(
        [
            {
                "protocol": protocol,
                "B1": metrics["protocols"][protocol]["models"]["B1"]["mae_kcal"],
                "H1": metrics["protocols"][protocol]["models"]["H1"]["mae_kcal"],
            }
            for protocol in ("loocv", "leave_axis_a_out", "leave_axis_b_out")
        ]
    ).set_index("protocol")
    figure, axis = plt.subplots(figsize=(7.5, 4.8))
    grouped.plot.bar(ax=axis)
    axis.set(title="OOF absolute error: B1 vs H1", xlabel="outer protocol", ylabel="MAE (kcal/mol)")
    axis.tick_params(axis="x", labelrotation=15)
    path = output_dir / "04_grouped_mae_b1_h1.png"
    _finish(
        figure=figure,
        path=path,
        n=n,
        protocol="outer_oof",
        model_version=model_version,
        dataset_version=dataset_version,
        oof=True,
        interval="none",
    )
    paths.append(path)

    for number, term, label in (
        (5, "axis_a_family", "Axis-A family effects"),
        (6, "axis_b_family", "Axis-B family effects"),
    ):
        path = output_dir / f"{number:02d}_{term}_forest.png"
        _forest(
            effects=family_effects,
            bootstrap=bootstrap_family_effects,
            term=term,
            title=label,
            path=path,
            n=n,
            model_version=model_version,
            dataset_version=dataset_version,
        )
        paths.append(path)

    active = family_effects.query("active").copy()
    figure, axis = plt.subplots(figsize=(6.5, 4.8))
    for group_name, subset in active.groupby("term", sort=True):
        axis.scatter(
            subset["support"],
            np.abs(subset["effect_kcal"]),
            label=str(group_name),
            alpha=0.75,
        )
    axis.legend()
    axis.set(
        title="Family support vs fitted shrinkage",
        xlabel="label support",
        ylabel="|family effect| (kcal/mol)",
    )
    path = output_dir / "07_support_vs_effect.png"
    _finish(
        figure=figure,
        path=path,
        n=n,
        protocol="full_fit_fixed_nested_penalty",
        model_version=model_version,
        dataset_version=dataset_version,
        oof=False,
        interval="none",
    )
    paths.append(path)

    interval_frame = (
        loocv[["inchikey", "true_dft_kcal"]]
        .merge(bootstrap_predictions, on="inchikey", validate="one_to_one")
        .sort_values("true_dft_kcal")
    )
    positions = np.arange(len(interval_frame))
    figure, axis = plt.subplots(figsize=(12.0, 5.0))
    axis.fill_between(
        positions,
        interval_frame["prediction_p025"],
        interval_frame["prediction_p975"],
        alpha=0.25,
        label="95% bootstrap interval",
    )
    axis.plot(positions, interval_frame["prediction_mean"], label="bootstrap mean")
    axis.scatter(positions, interval_frame["true_dft_kcal"], s=12, label="DFT label")
    axis.legend()
    axis.set(
        title="H1 full-fit bootstrap prediction intervals",
        xlabel="labels sorted by true energy",
        ylabel="electronic energy (kcal/mol)",
    )
    path = output_dir / "08_bootstrap_prediction_intervals.png"
    _finish(
        figure=figure,
        path=path,
        n=n,
        protocol="full_fit_bootstrap_queries",
        model_version=model_version,
        dataset_version=dataset_version,
        oof=False,
        interval="95% paired-key bootstrap; not OOF",
    )
    paths.append(path)

    stability = bootstrap_family_effects.query("term != 'skeleton'")
    figure, axis = plt.subplots(figsize=(6.5, 4.8))
    for group_name, subset in stability.groupby("term", sort=True):
        axis.scatter(
            subset["support"],
            subset["sign_stability"],
            label=str(group_name),
            alpha=0.75,
        )
    axis.legend()
    axis.set(
        title="Family-effect sign stability",
        xlabel="label support",
        ylabel="max(P(effect>0), P(effect<0))",
        ylim=(0.0, 1.05),
    )
    path = output_dir / "09_family_sign_stability.png"
    _finish(
        figure=figure,
        path=path,
        n=n,
        protocol="full_fit_bootstrap",
        model_version=model_version,
        dataset_version=dataset_version,
        oof=False,
        interval="2,000 paired-key bootstrap",
    )
    paths.append(path)
    return tuple(paths)
