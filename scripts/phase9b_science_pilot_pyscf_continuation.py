#!/usr/bin/env python3
"""One-shot, non-production PySCF single-point continuation for pilot v004."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import stat
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Final, cast

CANDIDATE: Final = "LBNPGYISTSLAHY-UHFFFAOYSA-N"
CONTINUATION_ROOT_NAME: Final = "science_pilot_lbn_pyscf_v004"
SCHEMA_VERSION: Final = "nhc-phase9b-science-pilot-pyscf-continuation-v1"
ENDPOINTS: Final = ("cation", "neutral")
CHARGES: Final = {"cation": 1, "neutral": 0}
MULTIPLICITIES: Final = {"cation": 1, "neutral": 1}
SPINS: Final = {"cation": 0, "neutral": 0}
ATOM_COUNTS: Final = {"cation": 26, "neutral": 25}
ELECTRON_COUNT: Final = 160
SOURCE_BYTES: Final = {"cation": 1181, "neutral": 1133}
SOURCE_SHA256: Final = {
    "cation": "ea796a5c81504184382b965d57c588c74968a09de8942148d3d9cbadf70a7774",
    "neutral": "c40ca77bce9d8c8deefc2357bf2633fb4c0981ce9d4bd23aceb342d40646bc93",
}
V002_RESULT_SHA256: Final = "b1362a3b1df7ef7ba276bac0c91fd8002fd27123eca37d84a82b937edacd7071"
REVIEW_RESULT_SHA256: Final = "f8f5cd80f117edc8ce061f901f797bce23b6934dc6ded6d1c8a52871b533f86e"
REVIEW_SOURCE_SHA256: Final = "659021fbd5981906ca563810f62cb096347bd94c9facb5f7f55c129868c4d97f"
HELPER_SOURCE_SHA256: Final = "b38aa93008f744551c2dec352214c1bcc53f71e3ceddfcfe0e5e73ce15a04a55"
TWO_ENDPOINT_SOURCE_SHA256: Final = (
    "44e16576ae37e52ff7b0d399a1b11d3932a9baa19b6a4aae8c603c8e29f9d977"
)
HARTREE_TO_KCAL_MOL: Final = 627.509474
PROTON_CORRECTION_KCAL_MOL: Final = 6.28
WALL_LIMIT_SECONDS: Final = 7200.0
FILE_MODE: Final = 0o600
DIRECTORY_MODE: Final = 0o700
MAX_FILE_BYTES: Final = 64 << 20


class ContinuationError(RuntimeError):
    """The isolated continuation failed its evidence contract."""


class HandoffError(ContinuationError):
    """The exact v002 geometry bytes or endpoint identity were not preserved."""


@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int
    mode: int
    link_count: int
    size: int
    mtime_ns: int


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _identity(observed: os.stat_result) -> FileIdentity:
    return FileIdentity(
        device=observed.st_dev,
        inode=observed.st_ino,
        mode=stat.S_IMODE(observed.st_mode),
        link_count=observed.st_nlink,
        size=observed.st_size,
        mtime_ns=observed.st_mtime_ns,
    )


def read_regular_file(path: Path) -> tuple[bytes, FileIdentity]:
    if path.is_symlink():
        raise HandoffError(f"symlink is forbidden: {path.name}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before_stat = os.fstat(descriptor)
        if not stat.S_ISREG(before_stat.st_mode) or before_stat.st_nlink != 1:
            raise HandoffError(f"unsafe source file: {path.name}")
        if before_stat.st_size < 0 or before_stat.st_size > MAX_FILE_BYTES:
            raise HandoffError(f"source file size is invalid: {path.name}")
        chunks: list[bytes] = []
        remaining = before_stat.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1 << 20))
            if not chunk:
                raise HandoffError(f"short source read: {path.name}")
            chunks.append(chunk)
            remaining -= len(chunk)
        after_stat = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    before = _identity(before_stat)
    after = _identity(after_stat)
    if before != after:
        raise HandoffError(f"source identity drifted while reading: {path.name}")
    return b"".join(chunks), before


def capture_interpreter(
    logical_launcher: Path, *, expected_executable_sha256: str
) -> dict[str, object]:
    try:
        launcher_stat = logical_launcher.lstat()
        environment_root = logical_launcher.parent.parent.resolve(strict=True)
        resolved = logical_launcher.resolve(strict=True)
        resolved.relative_to(environment_root)
    except (OSError, ValueError) as exc:
        raise ContinuationError("interpreter launcher is not environment-local") from exc
    if not (stat.S_ISREG(launcher_stat.st_mode) or stat.S_ISLNK(launcher_stat.st_mode)):
        raise ContinuationError("interpreter launcher is neither a regular file nor a symlink")
    descriptor = os.open(resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before_stat = os.fstat(descriptor)
        if not stat.S_ISREG(before_stat.st_mode) or not os.access(resolved, os.X_OK):
            raise ContinuationError("resolved interpreter is not a regular executable")
        if before_stat.st_size < 0 or before_stat.st_size > MAX_FILE_BYTES:
            raise ContinuationError("resolved interpreter size is invalid")
        chunks: list[bytes] = []
        remaining = before_stat.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1 << 20))
            if not chunk:
                raise ContinuationError("short interpreter read")
            chunks.append(chunk)
            remaining -= len(chunk)
        after_stat = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    before = _identity(before_stat)
    after = _identity(after_stat)
    raw = b"".join(chunks)
    digest = _sha256(raw)
    if before != after:
        raise ContinuationError("interpreter identity drifted while reading")
    if digest != expected_executable_sha256:
        raise ContinuationError("interpreter executable content identity drifted")
    return {
        "logical_launcher": str(logical_launcher),
        "launcher_kind": "symlink" if stat.S_ISLNK(launcher_stat.st_mode) else "regular",
        "launcher_lstat_identity": asdict(_identity(launcher_stat)),
        "environment_root": str(environment_root),
        "resolved_executable": str(resolved),
        "resolved_inside_environment_root": True,
        "resolved_identity": asdict(before),
        "resolved_executable_bytes": len(raw),
        "resolved_executable_sha256": digest,
    }


def make_directory(path: Path) -> None:
    path.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=False)
    observed = path.lstat()
    if not stat.S_ISDIR(observed.st_mode) or path.is_symlink():
        raise ContinuationError(f"unsafe evidence directory: {path.name}")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_new(path: Path, raw: bytes) -> dict[str, object]:
    if len(raw) > MAX_FILE_BYTES:
        raise ContinuationError(f"evidence is too large: {path.name}")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        FILE_MODE,
    )
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            raise ContinuationError(f"unsafe new evidence file: {path.name}")
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    fsync_directory(path.parent)
    reread, _ = read_regular_file(path)
    if reread != raw:
        raise ContinuationError(f"evidence reread mismatch: {path.name}")
    return {"bytes": len(raw), "sha256": _sha256(raw)}


def write_json_new(path: Path, payload: object) -> dict[str, object]:
    return write_new(path, _canonical_json(payload))


def optional_file_receipt(path: Path) -> dict[str, object] | None:
    try:
        raw, identity = read_regular_file(path)
    except (OSError, ContinuationError):
        return None
    return {"bytes": len(raw), "sha256": _sha256(raw), "identity": asdict(identity)}


def load_pilot_helpers(path: Path) -> Any:
    raw, identity = read_regular_file(path)
    spec = importlib.util.spec_from_file_location("phase9b_science_pilot_v004_helpers", path)
    if spec is None or spec.loader is None:
        raise ContinuationError("science-pilot helper source cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    reread, reread_identity = read_regular_file(path)
    if raw != reread or identity != reread_identity:
        raise ContinuationError("science-pilot helper source drifted during import")
    return module


def resolve_safe_directory(path: Path, *, label: str) -> Path:
    try:
        observed = path.lstat()
    except OSError as exc:
        raise ContinuationError(f"{label} is unavailable") from exc
    if path.is_symlink() or not stat.S_ISDIR(observed.st_mode):
        raise ContinuationError(f"{label} is not a non-symlink directory")
    return path.resolve(strict=True)


def validate_source_and_copy(
    *,
    endpoint: str,
    source_path: Path,
    evidence_input_path: Path,
    parser_input_path: Path,
) -> tuple[bytes, dict[str, object]]:
    source_raw, source_identity = read_regular_file(source_path)
    if len(source_raw) != SOURCE_BYTES[endpoint] or _sha256(source_raw) != SOURCE_SHA256[endpoint]:
        raise HandoffError(f"{endpoint} retained AIMNet2 final identity drifted")
    evidence_copy = write_new(evidence_input_path, source_raw)
    parser_copy = write_new(parser_input_path, source_raw)
    copied_raw, copied_identity = read_regular_file(evidence_input_path)
    parser_raw, parser_identity = read_regular_file(parser_input_path)
    if not (source_raw == copied_raw == parser_raw):
        raise HandoffError(f"{endpoint} exact-byte handoff failed")
    return parser_raw, {
        "schema_version": "nhc-phase9b-science-pilot-handoff-v004",
        "science_pilot_only": True,
        "candidate": CANDIDATE,
        "endpoint": endpoint,
        "source_path_scope": "retained_v002_private_root",
        "source_identity": asdict(source_identity),
        "source_byte_count": len(source_raw),
        "source_sha256": _sha256(source_raw),
        "copied_input_relative_path": evidence_input_path.relative_to(
            evidence_input_path.parents[1]
        ).as_posix(),
        "copied_input_identity": asdict(copied_identity),
        "copied_input_byte_count": evidence_copy["bytes"],
        "copied_input_sha256": evidence_copy["sha256"],
        "parser_input_relative_path": parser_input_path.relative_to(
            parser_input_path.parents[2]
        ).as_posix(),
        "parser_input_identity": asdict(parser_identity),
        "parser_input_byte_count": parser_copy["bytes"],
        "parser_input_sha256": parser_copy["sha256"],
        "source_equals_copy": True,
        "copy_equals_parser": True,
        "charge": CHARGES[endpoint],
        "multiplicity": MULTIPLICITIES[endpoint],
        "spin": SPINS[endpoint],
        "atom_count": ATOM_COUNTS[endpoint],
    }


def _strategy_failure_is_retryable(module: Any, exc: BaseException) -> bool:
    return isinstance(exc, module.SCFNotConvergedError)


def build_observed_backend(*, pilot: Any, module: Any) -> Any:
    """Instrument the untouched PySCF initial-guess path before each kernel.

    The frozen backend deliberately does not set ``init_guess`` or pass ``dm0``.
    The observer proves what the runtime actually calls without selecting a guess.
    """

    base_backend = pilot._SciencePilotPySCFBackend.build(module)
    base_type = type(base_backend)

    class ObservedSciencePilotPySCFBackend(base_type):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__()
            self.initial_guess_evidence: dict[str, dict[str, object]] = {}

        def _mean_field(self, **kwargs: object) -> tuple[object, object, object]:
            result = super()._mean_field(**kwargs)
            mean_field = cast(Any, result[0])
            context = self._pilot_context
            if context is None:
                raise ContinuationError("PySCF observation context is unavailable")
            endpoint, operation, strategy = context
            if operation != "final_scf":
                raise ContinuationError("science-pilot observer reached a non-SCF operation")
            key = f"{endpoint}:{strategy}"
            if key in self.initial_guess_evidence:
                raise ContinuationError("PySCF observation key was reused")
            evidence: dict[str, object] = {
                "endpoint": endpoint,
                "strategy": strategy,
                "project_init_guess_override": False,
                "project_dm0_argument": False,
                "kernel_call_count": 0,
                "get_init_guess_calls": [],
                "owners": [],
            }
            owners: list[Any] = [mean_field]
            inner = getattr(mean_field, "_scf", None)
            if inner is not None and inner is not mean_field:
                owners.append(inner)
            seen: set[int] = set()
            for owner_index, owner in enumerate(owners):
                if id(owner) in seen:
                    continue
                seen.add(id(owner))
                original_guess = getattr(owner, "get_init_guess", None)
                if not callable(original_guess):
                    raise ContinuationError("PySCF get_init_guess is unavailable")
                owner_record = {
                    "owner_index": owner_index,
                    "owner_class": f"{type(owner).__module__}.{type(owner).__qualname__}",
                    "configured_init_guess_before": getattr(owner, "init_guess", None),
                    "chkfile_before": bool(getattr(owner, "chkfile", None)),
                }
                cast(list[object], evidence["owners"]).append(owner_record)

                def observed_guess(
                    *guess_args: object,
                    _owner_index: int = owner_index,
                    _original_guess: Any = original_guess,
                    **guess_kwargs: object,
                ) -> object:
                    key_value = guess_kwargs.get("key")
                    if key_value is None and len(guess_args) >= 2:
                        key_value = guess_args[1]
                    cast(list[object], evidence["get_init_guess_calls"]).append(
                        {
                            "owner_index": _owner_index,
                            "argument_count": len(guess_args),
                            "keyword_names": sorted(guess_kwargs),
                            "key": key_value,
                        }
                    )
                    return _original_guess(*guess_args, **guess_kwargs)

                owner.get_init_guess = observed_guess

            original_kernel = mean_field.kernel

            def observed_kernel(*kernel_args: object, **kernel_kwargs: object) -> object:
                evidence["kernel_call_count"] = cast(int, evidence["kernel_call_count"]) + 1
                if kernel_args or kernel_kwargs:
                    evidence["project_dm0_argument"] = True
                    raise ContinuationError("science-pilot must not pass dm0 or kernel arguments")
                return original_kernel()

            mean_field.kernel = observed_kernel
            self.initial_guess_evidence[key] = evidence
            return cast(tuple[object, object, object], result)

        def final_scf(self, **kwargs: object) -> object:
            endpoint = str(kwargs["endpoint"])
            strategy = str(kwargs["strategy"])
            key = f"{endpoint}:{strategy}"
            try:
                return super().final_scf(**kwargs)
            finally:
                evidence = self.initial_guess_evidence.get(key)
                if evidence is not None:
                    for owner in cast(list[dict[str, object]], evidence["owners"]):
                        owner_index = cast(int, owner["owner_index"])
                        observed_owner = cast(Any, self._pilot_last_mean_field)
                        if owner_index == 1:
                            observed_owner = getattr(observed_owner, "_scf", None)
                        owner["configured_init_guess_after"] = getattr(
                            observed_owner, "init_guess", None
                        )
                        owner["chkfile_after"] = bool(getattr(observed_owner, "chkfile", None))

    return ObservedSciencePilotPySCFBackend()


def run_single_point(
    *, module: Any, backend: Any, endpoint: Any, deadline: float
) -> tuple[Any, str, list[dict[str, object]]]:
    attempts: list[dict[str, object]] = []
    try:
        result = module._call_scf(
            backend=backend,
            endpoint=endpoint,
            geometry=endpoint.geometry,
            strategy="standard",
            deadline=deadline,
        )
    except BaseException as exc:
        attempts.append(
            {
                "strategy": "standard",
                "converged": False,
                "exception_class": type(exc).__name__,
            }
        )
        if not _strategy_failure_is_retryable(module, exc):
            raise
        result = module._call_scf(
            backend=backend,
            endpoint=endpoint,
            geometry=endpoint.geometry,
            strategy="soscf",
            deadline=deadline,
        )
        attempts.append({"strategy": "soscf", "converged": True})
        return result, "soscf", attempts
    attempts.append({"strategy": "standard", "converged": True})
    return result, "standard", attempts


def compute_deprotonation(cation_hartree: float, neutral_hartree: float) -> dict[str, object]:
    values = (cation_hartree, neutral_hartree)
    if not all(math.isfinite(value) for value in values):
        raise ContinuationError("endpoint energy is non-finite")
    difference_hartree = neutral_hartree - cation_hartree
    electronic_difference = difference_hartree * HARTREE_TO_KCAL_MOL
    label = electronic_difference - PROTON_CORRECTION_KCAL_MOL
    if not all(
        math.isfinite(value) for value in (difference_hartree, electronic_difference, label)
    ):
        raise ContinuationError("deprotonation arithmetic is non-finite")
    return {
        "cation_energy_hartree": cation_hartree,
        "neutral_energy_hartree": neutral_hartree,
        "hartree_difference": difference_hartree,
        "conversion_factor_kcal_per_hartree": HARTREE_TO_KCAL_MOL,
        "electronic_difference_kcal_per_mol": electronic_difference,
        "proton_correction_kcal_per_mol": PROTON_CORRECTION_KCAL_MOL,
        "formula": "((E_neutral_PySCF - E_cation_PySCF) * 627.509474) - 6.28",
        "value_kcal_per_mol": label,
        "lower_is_better": True,
        "definition": "gas_phase_electronic_energy_only",
        "aimnet2_energy_used": False,
    }


def validate_initial_guess_evidence(
    *, endpoint: str, selected_strategy: str, evidence: dict[str, dict[str, object]]
) -> None:
    selected_key = f"{endpoint}:{selected_strategy}"
    if selected_key not in evidence:
        raise ContinuationError(f"{endpoint} selected initial-guess evidence is unavailable")
    for attempt_key, attempt in evidence.items():
        if attempt.get("kernel_call_count") != 1:
            raise ContinuationError(f"{attempt_key} kernel execution count drifted")
        if (
            attempt.get("project_dm0_argument") is not False
            or attempt.get("project_init_guess_override") is not False
        ):
            raise ContinuationError(f"{attempt_key} initial guess was overridden")
        owners = cast(list[dict[str, object]], attempt.get("owners", []))
        calls = cast(list[dict[str, object]], attempt.get("get_init_guess_calls", []))
        if not owners or not calls:
            raise ContinuationError(f"{attempt_key} initial-guess execution was not observed")
        owner_by_index = {cast(int, owner["owner_index"]): owner for owner in owners}
        for owner in owners:
            if owner.get("configured_init_guess_before") != owner.get(
                "configured_init_guess_after"
            ):
                raise ContinuationError(f"{attempt_key} init_guess configuration drifted")
        for call in calls:
            current_owner = owner_by_index.get(cast(int, call["owner_index"]))
            if current_owner is None:
                raise ContinuationError(f"{attempt_key} initial-guess owner is unknown")
            expected_key = current_owner.get("configured_init_guess_before")
            observed_key = call.get("key") if call.get("key") is not None else expected_key
            if observed_key != expected_key:
                raise ContinuationError(f"{attempt_key} initial-guess key drifted")


def _failure_outcome(module: Any, exc: BaseException) -> str:
    environmental = (
        module.BackendTimeoutError,
        module.ResourceConfigurationError,
        module.ResourceLimitError,
        ImportError,
        OSError,
        TimeoutError,
    )
    if isinstance(exc, environmental):
        return "INCONCLUSIVE"
    scientific_or_protocol = (
        HandoffError,
        module.SCFNotConvergedError,
        module.SCFConvergenceError,
        module.DispersionUnavailableError,
        module.DispersionEvaluationError,
    )
    if isinstance(exc, scientific_or_protocol):
        return "FAIL"
    return "INCONCLUSIVE"


def _file_manifest(root: Path) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        observed = path.lstat()
        if stat.S_ISLNK(observed.st_mode):
            raise ContinuationError(f"evidence tree contains a symlink: {path.name}")
        if stat.S_ISDIR(observed.st_mode):
            continue
        if not stat.S_ISREG(observed.st_mode):
            raise ContinuationError(f"evidence tree contains a special file: {path.name}")
        relative = path.relative_to(root).as_posix()
        if relative.startswith("driver/") or relative == "file_manifest.json":
            continue
        raw, identity = read_regular_file(path)
        files.append(
            {
                "relative_path": relative,
                "bytes": len(raw),
                "sha256": _sha256(raw),
                "mode": identity.mode,
                "link_count": identity.link_count,
            }
        )
    return {
        "schema_version": "nhc-phase9b-science-pilot-file-manifest-v004",
        "science_pilot_only": True,
        "candidate": CANDIDATE,
        "files": files,
    }


def execute(args: argparse.Namespace) -> int:
    started = time.monotonic()
    deadline = started + WALL_LIMIT_SECONDS
    root = resolve_safe_directory(Path(args.root), label="continuation root")
    v002_root = resolve_safe_directory(Path(args.v002_root), label="retained v002 root")
    source_root = resolve_safe_directory(Path(args.source_root), label="deployed source root")
    if root.name != CONTINUATION_ROOT_NAME:
        raise ContinuationError("continuation root logical identity drifted")
    if v002_root.name != "science_pilot_lbn_v002":
        raise ContinuationError("retained v002 root logical identity drifted")
    if root.parent != v002_root.parent:
        raise ContinuationError("continuation and retained v002 roots do not share the runs root")
    if source_root != root / "driver" / "src":
        raise ContinuationError("deployed source root is not the fixed driver/src directory")
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        raise ContinuationError("source commit is not a full lowercase Git identity")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_executable_sha256):
        raise ContinuationError("expected interpreter content identity is invalid")
    if os.path.lexists(root / "result.json"):
        raise ContinuationError("continuation already has a terminal result")

    continuation_raw, _ = read_regular_file(Path(__file__).resolve(strict=True))
    if _sha256(continuation_raw) != args.continuation_source_sha256:
        raise ContinuationError("continuation source identity drifted")
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        os.environ.pop(name, None)
    if sys.version_info[:3] != (3, 11, 15):
        raise ContinuationError("science-pilot requires exact Python 3.11.15")
    interpreter_evidence_before = capture_interpreter(
        Path(sys.executable), expected_executable_sha256=args.expected_executable_sha256
    )
    helper_path = root / "driver" / "scripts" / "phase9b_science_pilot.py"
    expected_two_endpoint_path = source_root / "nhc_deprot_ranker" / "quantum" / "two_endpoint.py"
    helper_raw, helper_identity = read_regular_file(helper_path)
    two_endpoint_raw, two_endpoint_identity = read_regular_file(expected_two_endpoint_path)
    if _sha256(helper_raw) != HELPER_SOURCE_SHA256:
        raise ContinuationError("science-pilot helper source identity drifted before import")
    if _sha256(two_endpoint_raw) != TWO_ENDPOINT_SOURCE_SHA256:
        raise ContinuationError("frozen two-endpoint source identity drifted before import")
    pilot = load_pilot_helpers(helper_path)
    pilot._add_source_root(source_root)
    from nhc_deprot_ranker.quantum import two_endpoint

    two_endpoint_path = Path(two_endpoint.__file__).resolve(strict=True)
    if two_endpoint_path != expected_two_endpoint_path:
        raise ContinuationError("imported two-endpoint module came from another source root")
    helper_reread, helper_reread_identity = read_regular_file(helper_path)
    two_endpoint_reread, two_endpoint_reread_identity = read_regular_file(two_endpoint_path)
    if helper_raw != helper_reread or helper_identity != helper_reread_identity:
        raise ContinuationError("science-pilot helper source drifted across import")
    if (
        two_endpoint_raw != two_endpoint_reread
        or two_endpoint_identity != two_endpoint_reread_identity
    ):
        raise ContinuationError("two-endpoint source drifted across import")
    source_identities = {
        "continuation_source_sha256": _sha256(continuation_raw),
        "science_pilot_helper_sha256": _sha256(helper_raw),
        "two_endpoint_source_sha256": _sha256(two_endpoint_raw),
    }

    v002_result_raw, _ = read_regular_file(v002_root / "result.json")
    if _sha256(v002_result_raw) != V002_RESULT_SHA256:
        raise HandoffError("v002 terminal identity drifted")
    review_source_path = root / "driver" / "review_result.json"
    review_raw, _ = read_regular_file(review_source_path)
    if _sha256(review_raw) != REVIEW_RESULT_SHA256:
        raise HandoffError("corrected geometry review identity drifted")
    review = json.loads(review_raw)
    if (
        review.get("classification") != "SAME_BASIN_LIKELY"
        or review.get("stage_b_authorized_by_classification") is not True
        or review.get("production_10_degree_gate_unchanged") is not True
        or review.get("v002_terminal_unchanged") is not True
    ):
        raise HandoffError("corrected geometry review does not authorize Stage B")

    for name in ("input", "review", "handoff", "pyscf"):
        make_directory(root / name)
    for endpoint in ENDPOINTS:
        make_directory(root / "pyscf" / endpoint)

    corrected_review_receipt = write_new(
        root / "review" / "corrected_geometry_review.json", review_raw
    )
    binding = {
        "schema_version": "nhc-phase9b-science-pilot-geometry-review-binding-v004",
        "science_pilot_only": True,
        "candidate": CANDIDATE,
        "v002_result_sha256": V002_RESULT_SHA256,
        "cation_final_xyz_sha256": SOURCE_SHA256["cation"],
        "neutral_final_xyz_sha256": SOURCE_SHA256["neutral"],
        "corrected_review_source_sha256": REVIEW_SOURCE_SHA256,
        "corrected_review_result_sha256": REVIEW_RESULT_SHA256,
        "corrected_review_copy_sha256": corrected_review_receipt["sha256"],
        "classification": "SAME_BASIN_LIKELY",
        "production_10_degree_gate_unchanged": True,
        "v002_terminal_unchanged": True,
    }
    binding_receipt = write_json_new(root / "review" / "geometry_review_binding.json", binding)

    handoffs: dict[str, dict[str, object]] = {}
    endpoint_requests: dict[str, object] = {}
    input_manifest: dict[str, object] = {
        "schema_version": "nhc-phase9b-science-pilot-input-manifest-v004",
        "science_pilot_only": True,
        "candidate": CANDIDATE,
        "endpoints": {},
    }
    for endpoint in ENDPOINTS:
        source_path = v002_root / "aimnet2" / endpoint / "final.xyz"
        evidence_input = root / "input" / f"{endpoint}_aimnet2_final.xyz"
        parser_input = root / "pyscf" / endpoint / "input.xyz"
        raw, handoff = validate_source_and_copy(
            endpoint=endpoint,
            source_path=source_path,
            evidence_input_path=evidence_input,
            parser_input_path=parser_input,
        )
        geometry = two_endpoint._parse_xyz(raw, label=f"science pilot v004 {endpoint}")
        elements = tuple(atom.element for atom in geometry.atoms)
        if len(elements) != ATOM_COUNTS[endpoint]:
            raise HandoffError(f"{endpoint} parser atom count drifted")
        if two_endpoint._electron_count_for_geometry(geometry, charge=CHARGES[endpoint]) != 160:
            raise HandoffError(f"{endpoint} parser electron count drifted")
        if MULTIPLICITIES[endpoint] - 1 != SPINS[endpoint]:
            raise HandoffError(f"{endpoint} multiplicity-to-spin binding drifted")
        handoff.update(
            {
                "parser_element_order_sha256": _sha256(" ".join(elements).encode("utf-8")),
                "atom_order_preserved": True,
                "electron_count": ELECTRON_COUNT,
            }
        )
        write_json_new(root / "handoff" / f"{endpoint}_handoff.json", handoff)
        handoffs[endpoint] = handoff
        endpoint_requests[endpoint] = two_endpoint.EndpointRequest(
            name=cast(Any, endpoint),
            xyz_relative_path=f"pyscf/{endpoint}/input.xyz",
            xyz_path=parser_input,
            xyz_sha256=_sha256(raw),
            charge=CHARGES[endpoint],
            multiplicity=MULTIPLICITIES[endpoint],
            electron_count=ELECTRON_COUNT,
            geometry=geometry,
        )
        cast(dict[str, object], input_manifest["endpoints"])[endpoint] = {
            "source_sha256": SOURCE_SHA256[endpoint],
            "source_bytes": SOURCE_BYTES[endpoint],
            "copied_sha256": _sha256(raw),
            "copied_bytes": len(raw),
            "charge": CHARGES[endpoint],
            "multiplicity": MULTIPLICITIES[endpoint],
            "spin": SPINS[endpoint],
            "atom_count": len(elements),
            "atom_order_sha256": handoff["parser_element_order_sha256"],
        }
    write_json_new(root / "input" / "input_manifest.json", input_manifest)

    for name, value in two_endpoint.THREAD_ENVIRONMENT.items():
        os.environ[name] = value
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["TMPDIR"] = str(root / "pyscf")
    set_affinity = getattr(os, "sched_setaffinity", None)
    get_affinity = getattr(os, "sched_getaffinity", None)
    if not callable(set_affinity) or not callable(get_affinity):
        raise ContinuationError("exact Linux affinity API is unavailable")
    set_affinity(0, {0, 1, 2, 3})
    if set(get_affinity(0)) != {0, 1, 2, 3}:
        raise ContinuationError("CPU affinity did not retain cores 0-3")

    backend = build_observed_backend(pilot=pilot, module=two_endpoint)
    endpoint_results: dict[str, object] = {}
    energies: dict[str, float] = {}
    active_endpoint = "cation"
    try:
        for endpoint in ENDPOINTS:
            active_endpoint = endpoint
            endpoint_root = root / "pyscf" / endpoint
            run_config = {
                "schema_version": "nhc-phase9b-science-pilot-run-config-v004",
                "science_pilot_only": True,
                "candidate": CANDIDATE,
                "endpoint": endpoint,
                "protocol_kind": "frozen_final_scf_slice_single_point",
                "parent_protocol_reference_only": "production final_scf slice",
                "method": "B3LYP",
                "basis": "def2-SVP",
                "dispersion": "D3(BJ)",
                "d3_owner_setting": "mf.disp=d3bj",
                "grid_level": 3,
                "scf_conv_tol": 1.0e-9,
                "standard_max_cycles": 100,
                "soscf_max_cycles": 200,
                "soscf_policy": "once_only_after_typed_scf_nonconvergence",
                "initial_guess_policy": "project_does_not_override_or_pass_dm0",
                "geometry_optimization": False,
                "geometry_optimizer_invoked": False,
                "charge": CHARGES[endpoint],
                "multiplicity": MULTIPLICITIES[endpoint],
                "spin": SPINS[endpoint],
                "electron_count": ELECTRON_COUNT,
                "threads": 4,
                "max_memory_mb": 12000,
                "cpu_affinity": [0, 1, 2, 3],
                "deadline_monotonic": deadline,
                "handoff_sha256": _sha256(_canonical_json(handoffs[endpoint])),
            }
            write_json_new(endpoint_root / "run_config.json", run_config)
            endpoint_started = time.monotonic()
            with (
                pilot._capture_fds(endpoint_root / "stdout", endpoint_root / "stderr"),
                pilot._working_directory(endpoint_root),
            ):
                result, strategy, attempts = run_single_point(
                    module=two_endpoint,
                    backend=backend,
                    endpoint=endpoint_requests[endpoint],
                    deadline=deadline,
                )
            wall_seconds = time.monotonic() - endpoint_started
            stdout_raw, _ = read_regular_file(endpoint_root / "stdout")
            stderr_raw, _ = read_regular_file(endpoint_root / "stderr")
            metrics = cast(dict[str, object], backend.pilot_metrics.get(endpoint, {}))
            guess_evidence = {
                key: value
                for key, value in backend.initial_guess_evidence.items()
                if key.startswith(f"{endpoint}:")
            }
            validate_initial_guess_evidence(
                endpoint=endpoint, selected_strategy=strategy, evidence=guess_evidence
            )
            interpreter_evidence_after = capture_interpreter(
                Path(sys.executable),
                expected_executable_sha256=args.expected_executable_sha256,
            )
            if interpreter_evidence_after != interpreter_evidence_before:
                raise ContinuationError(f"{endpoint} interpreter identity drifted")
            endpoint_payload = {
                "schema_version": "nhc-phase9b-science-pilot-endpoint-result-v004",
                "science_pilot_only": True,
                "candidate": CANDIDATE,
                "endpoint": endpoint,
                "status": "success",
                "interpreter": {
                    "before": interpreter_evidence_before,
                    "after": interpreter_evidence_after,
                    "python_version": sys.version.split()[0],
                },
                "versions": {
                    "pyscf": metadata.version("pyscf"),
                    "geometric": metadata.version("geometric"),
                    "pyscf_dispersion": metadata.version("pyscf-dispersion"),
                },
                "method": "B3LYP",
                "basis": "def2-SVP",
                "grid_level": 3,
                "charge": CHARGES[endpoint],
                "multiplicity": MULTIPLICITIES[endpoint],
                "spin": SPINS[endpoint],
                "electron_count": ELECTRON_COUNT,
                "threads": 4,
                "max_memory_mb": 12000,
                "scf_tolerance": 1.0e-9,
                "standard_max_cycles": 100,
                "soscf_max_cycles": 200,
                "initial_guess_evidence": guess_evidence,
                "selected_strategy": strategy,
                "attempts": attempts,
                "scf_converged": result.converged,
                "scf_cycles": metrics.get("final_scf_cycles", "unavailable"),
                "energy_hartree": result.energy_hartree,
                "d3": two_endpoint._final_dispersion_payload(result.dispersion),
                "d3_audit_protocol": {
                    "xc": "B3LYP",
                    "version": "d3bj",
                    "atm": False,
                    "grad": True,
                },
                "runtime": two_endpoint._runtime_evidence_payload(result.runtime),
                "wall_seconds": wall_seconds,
                "handoff": handoffs[endpoint],
                "stdout": {"bytes": len(stdout_raw), "sha256": _sha256(stdout_raw)},
                "stderr": {"bytes": len(stderr_raw), "sha256": _sha256(stderr_raw)},
                "warnings": "captured_in_raw_stderr",
                "source_identities": source_identities,
            }
            write_json_new(endpoint_root / "endpoint_result.json", endpoint_payload)
            endpoint_results[endpoint] = endpoint_payload
            energies[endpoint] = result.energy_hartree
    except BaseException as exc:
        traceback.print_exc()
        outcome = _failure_outcome(two_endpoint, exc)
        endpoint_root = root / "pyscf" / active_endpoint
        failure_path = endpoint_root / "endpoint_result.json"
        failure_payload = {
            "schema_version": "nhc-phase9b-science-pilot-endpoint-result-v004",
            "science_pilot_only": True,
            "candidate": CANDIDATE,
            "endpoint": active_endpoint,
            "status": "failed",
            "failure": {
                "exception_class": type(exc).__name__,
                "message": str(exc)[:1000],
            },
            "handoff": handoffs.get(active_endpoint),
            "partial_evidence": {
                "initial_guess_evidence": {
                    key: value
                    for key, value in backend.initial_guess_evidence.items()
                    if key.startswith(f"{active_endpoint}:")
                },
                "metrics": backend.pilot_metrics.get(active_endpoint, {}),
                "stdout": optional_file_receipt(endpoint_root / "stdout"),
                "stderr": optional_file_receipt(endpoint_root / "stderr"),
            },
        }
        if not os.path.lexists(failure_path):
            write_json_new(failure_path, failure_payload)
        endpoint_results[active_endpoint] = failure_payload
        terminal = {
            "schema_version": SCHEMA_VERSION,
            "science_pilot_only": True,
            "production_accepted": False,
            "production_label_inserted": False,
            "v001_unchanged": True,
            "v002_unchanged": True,
            "production_10_degree_gate_unchanged": True,
            "aimnet2_rerun": False,
            "candidate": CANDIDATE,
            "geometry_review_binding_sha256": binding_receipt["sha256"],
            "handoff_status": "PASS",
            "endpoint_results": endpoint_results,
            "deprotonation": None,
            "final_outcome": outcome,
            "failure": {
                "stage": f"pyscf_{active_endpoint}",
                "exception_class": type(exc).__name__,
                "message": str(exc)[:1000],
            },
        }
        write_json_new(root / "result.json", terminal)
        write_json_new(root / "file_manifest.json", _file_manifest(root))
        raise

    deprotonation = compute_deprotonation(energies["cation"], energies["neutral"])
    terminal = {
        "schema_version": SCHEMA_VERSION,
        "science_pilot_only": True,
        "production_accepted": False,
        "production_label_inserted": False,
        "v001_unchanged": True,
        "v002_unchanged": True,
        "production_10_degree_gate_unchanged": True,
        "aimnet2_rerun": False,
        "candidate": CANDIDATE,
        "source_commit": args.source_commit,
        "continuation_source_sha256": args.continuation_source_sha256,
        "source_identities": source_identities,
        "geometry_review_binding_sha256": binding_receipt["sha256"],
        "handoff_status": "PASS",
        "endpoint_results": {
            endpoint: {
                "status": "success",
                "charge": CHARGES[endpoint],
                "multiplicity": MULTIPLICITIES[endpoint],
                "spin": SPINS[endpoint],
                "energy_hartree": energies[endpoint],
            }
            for endpoint in ENDPOINTS
        },
        "deprotonation": deprotonation,
        "total_wall_seconds": time.monotonic() - started,
        "final_outcome": "PASS",
        "failure": None,
    }
    write_json_new(root / "result.json", terminal)
    write_json_new(root / "file_manifest.json", _file_manifest(root))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--v002-root", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--continuation-source-sha256", required=True)
    parser.add_argument("--expected-executable-sha256", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        return execute(args)
    except BaseException as exc:
        traceback.print_exc()
        root = Path(args.root)
        try:
            observed = root.lstat()
            result_path = root / "result.json"
            safe_root = stat.S_ISDIR(observed.st_mode) and not root.is_symlink()
            if safe_root and not os.path.lexists(result_path):
                write_json_new(
                    result_path,
                    {
                        "schema_version": SCHEMA_VERSION,
                        "science_pilot_only": True,
                        "production_accepted": False,
                        "production_label_inserted": False,
                        "v001_unchanged": True,
                        "v002_unchanged": True,
                        "production_10_degree_gate_unchanged": True,
                        "aimnet2_rerun": False,
                        "candidate": CANDIDATE,
                        "handoff_status": "FAIL" if isinstance(exc, HandoffError) else "not_run",
                        "endpoint_results": {},
                        "deprotonation": None,
                        "final_outcome": "FAIL"
                        if isinstance(exc, HandoffError)
                        else "INCONCLUSIVE",
                        "failure": {
                            "stage": "setup_or_handoff",
                            "exception_class": type(exc).__name__,
                            "message": str(exc)[:1000],
                        },
                    },
                )
            manifest_path = root / "file_manifest.json"
            if (
                safe_root
                and result_path.is_file()
                and not result_path.is_symlink()
                and not os.path.lexists(manifest_path)
            ):
                write_json_new(root / "file_manifest.json", _file_manifest(root))
        except BaseException:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
