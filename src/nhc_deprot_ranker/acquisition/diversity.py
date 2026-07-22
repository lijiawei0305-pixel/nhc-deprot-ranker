"""Deterministic categorical diversity scores and greedy selection."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


def static_diversity_score(frame: pd.DataFrame, fields: Sequence[str]) -> np.ndarray:
    """Average inverse-frequency novelty across registered categorical fields."""

    if not fields:
        raise ValueError("diversity fields must not be empty")
    scores = np.zeros(len(frame), dtype=np.float64)
    for field in fields:
        if field not in frame.columns:
            raise ValueError(f"diversity field is missing: {field}")
        counts = frame[field].astype(str).map(frame[field].astype(str).value_counts())
        scores += 1.0 / np.sqrt(counts.to_numpy(dtype=np.float64))
    scores /= len(fields)
    maximum = float(scores.max()) if len(scores) else 0.0
    minimum = float(scores.min()) if len(scores) else 0.0
    if maximum > minimum:
        scores = (scores - minimum) / (maximum - minimum)
    else:
        scores.fill(0.0)
    return scores


def greedy_diverse_indices(
    frame: pd.DataFrame,
    *,
    count: int,
    fields: Sequence[str],
    base_score_column: str,
    diversity_weight: float,
) -> list[int]:
    """Select rows by score plus new categorical coverage with stable ties."""

    if count < 0 or count > len(frame):
        raise ValueError("diversity selection count is outside the candidate pool")
    if count == 0:
        return []
    remaining = frame.copy()
    selected: list[int] = []
    seen: dict[str, set[str]] = {field: set() for field in fields}
    for _ in range(count):
        novelty = np.zeros(len(remaining), dtype=np.float64)
        for field in fields:
            values = remaining[field].astype(str)
            novelty += (~values.isin(seen[field])).to_numpy(dtype=np.float64)
        novelty /= len(fields)
        dynamic = (
            remaining[base_score_column].to_numpy(dtype=np.float64) + diversity_weight * novelty
        )
        ranked = remaining.assign(_dynamic_diversity_score=dynamic).sort_values(
            ["_dynamic_diversity_score", "production_rank", "inchikey"],
            ascending=[False, True, True],
            kind="mergesort",
        )
        index = int(ranked.index[0])
        selected.append(index)
        row = remaining.loc[index]
        for field in fields:
            seen[field].add(str(row[field]))
        remaining = remaining.drop(index=index)
    return selected
