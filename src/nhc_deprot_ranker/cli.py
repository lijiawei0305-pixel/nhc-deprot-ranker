"""Unified command-line interface with Phase 0-safe behavior."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from nhc_deprot_ranker.config import load_legacy_config
from nhc_deprot_ranker.constants import LABEL_FORMULA_ATOL_KCAL_MOL
from nhc_deprot_ranker.data.build import build_dataset
from nhc_deprot_ranker.legacy.audit import build_source_plan, validate_label_csv
from nhc_deprot_ranker.models.train import train_baselines

LOGGER = logging.getLogger(__name__)
LATER_PHASE_COMMANDS = ("evaluate", "score", "acquire", "report")


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="validate and plan without outputs")
    parser.add_argument(
        "--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR")
    )
    parser.add_argument("--seed", type=int, default=20260722)
    parser.add_argument(
        "--overwrite", action="store_true", help="allow replacing an explicit output"
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""

    parser = argparse.ArgumentParser(prog="nhc-deprot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser(
        "audit-legacy", help="validate config and emit a read-only source plan"
    )
    audit.add_argument("--config", type=Path, required=True)
    audit.add_argument("--out", type=Path)
    _add_common_options(audit)

    labels = subparsers.add_parser("validate-labels", help="recompute a local electronic label CSV")
    labels.add_argument("--input", type=Path, required=True)
    labels.add_argument("--key-column", default="InChIKey")
    labels.add_argument("--cation-column", default="E_cation")
    labels.add_argument("--neutral-column", default="E_neutral")
    labels.add_argument("--target-column", required=True)
    labels.add_argument("--tolerance-kcal", type=float, default=LABEL_FORMULA_ATOL_KCAL_MOL)
    labels.add_argument("--out", type=Path)
    _add_common_options(labels)

    build = subparsers.add_parser(
        "build-dataset", help="build one immutable Phase 1 processed dataset"
    )
    build.add_argument("--legacy-config", type=Path, required=True)
    build.add_argument("--data-config", type=Path, required=True)
    build.add_argument("--families-config", type=Path, default=Path("configs/families.yaml"))
    build.add_argument("--out", type=Path, required=True)
    _add_common_options(build)

    train = subparsers.add_parser("train", help="fit and evaluate immutable Phase 2 baselines")
    train.add_argument("--dataset", type=Path, required=True)
    train.add_argument("--model-config", type=Path, default=Path("configs/baselines.yaml"))
    train.add_argument("--evaluation-config", type=Path, default=Path("configs/evaluation.yaml"))
    train.add_argument("--evidence", type=Path, default=Path("docs/PROCESSED_V001_MANIFEST.json"))
    train.add_argument("--out", type=Path, required=True)
    _add_common_options(train)

    for command in LATER_PHASE_COMMANDS:
        later = subparsers.add_parser(command, help=f"reserved for a later phase: {command}")
        _add_common_options(later)
    return parser


def _emit(payload: dict[str, Any], out: Path | None, *, overwrite: bool, dry_run: bool) -> None:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if out is None or dry_run:
        sys.stdout.write(rendered)
        return
    if out.exists() and not overwrite:
        raise FileExistsError(f"output already exists (use --overwrite): {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")


def run(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process status."""

    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        if args.command == "audit-legacy":
            config = load_legacy_config(args.config)
            payload = build_source_plan(config)
            payload.update(
                {
                    "command": args.command,
                    "dry_run": bool(args.dry_run),
                    "seed": args.seed,
                    "note": (
                        "Phase 0 source planning never connects to SSH automatically; "
                        "approved remote evidence is recorded in docs/LEGACY_AUDIT.md."
                    ),
                }
            )
            _emit(payload, args.out, overwrite=args.overwrite, dry_run=args.dry_run)
            return 0
        if args.command == "validate-labels":
            payload = validate_label_csv(
                args.input,
                key_column=args.key_column,
                cation_column=args.cation_column,
                neutral_column=args.neutral_column,
                target_column=args.target_column,
                tolerance_kcal=args.tolerance_kcal,
            )
            payload.update(
                {"command": args.command, "dry_run": bool(args.dry_run), "seed": args.seed}
            )
            _emit(payload, args.out, overwrite=args.overwrite, dry_run=args.dry_run)
            return 1 if payload["formula_failures"] else 0
        if args.command == "build-dataset":
            build_result = build_dataset(
                legacy_config_path=args.legacy_config,
                data_config_path=args.data_config,
                families_config_path=args.families_config,
                output_dir=args.out,
                dry_run=args.dry_run,
                overwrite=args.overwrite,
            )
            _emit(build_result.payload, None, overwrite=False, dry_run=True)
            return 0
        if args.command == "train":
            train_result = train_baselines(
                dataset_dir=args.dataset,
                model_config_path=args.model_config,
                evaluation_config_path=args.evaluation_config,
                evidence_path=args.evidence,
                output_dir=args.out,
                seed=args.seed,
                dry_run=args.dry_run,
                overwrite=args.overwrite,
            )
            _emit(train_result.payload, None, overwrite=False, dry_run=True)
            return 0
        LOGGER.error("%s is outside active Phase 1 and is not implemented", args.command)
        return 2
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        LOGGER.error("%s", exc)
        return 2


def main() -> None:
    """Console-script entry point."""

    raise SystemExit(run())


if __name__ == "__main__":
    main()
