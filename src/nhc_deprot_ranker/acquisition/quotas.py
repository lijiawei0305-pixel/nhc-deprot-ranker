"""Deterministic Phase 5 acquisition quota allocation."""

from __future__ import annotations

import math

from nhc_deprot_ranker.config import AcquisitionConfig

BUCKET_ORDER = (
    "predicted_top_region",
    "cutoff_region",
    "chemical_family_diversity",
    "uncertain_ood_conflict",
)


def largest_remainder_quotas(config: AcquisitionConfig) -> dict[str, int]:
    """Convert configured fractions to exact batch counts in YAML order."""

    batch_size = config.acquisition_batch_size
    fractions = config.quotas.model_dump()
    raw = {bucket: float(fractions[bucket]) * batch_size for bucket in BUCKET_ORDER}
    counts = {bucket: math.floor(raw[bucket]) for bucket in BUCKET_ORDER}
    remaining = batch_size - sum(counts.values())
    order = sorted(
        BUCKET_ORDER,
        key=lambda bucket: (-(raw[bucket] - counts[bucket]), BUCKET_ORDER.index(bucket)),
    )
    for bucket in order[:remaining]:
        counts[bucket] += 1
    if sum(counts.values()) != batch_size:
        raise RuntimeError("largest-remainder quotas do not sum to batch size")
    return counts
