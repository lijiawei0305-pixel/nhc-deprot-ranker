"""Serializable Phase 2 model bundle."""

from __future__ import annotations

from dataclasses import dataclass

from nhc_deprot_ranker.models.affine import AffineCalibrator
from nhc_deprot_ranker.models.xtb_baseline import XtbBaseline


@dataclass(frozen=True)
class BaselineModelBundle:
    """Frozen B0/B1 models with version identity."""

    dataset_version: str
    model_version: str
    b0: XtbBaseline
    b1: AffineCalibrator
