"""Protocol-locked cation/neutral electronic-energy runner.

The public execution gate remains deliberately closed in Phase 8A.  Request
validation, the parent/worker publication protocol, and the process supervisor
can be tested without importing PySCF or geomeTRIC.  A later authorized phase
must make a reviewed source change before :func:`run_two_endpoint` can execute.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Final, Literal, Protocol, cast

from nhc_deprot_ranker.constants import (
    GAS_PROTON_KCAL_MOL,
    HARTREE_TO_KCAL_MOL,
    LOWER_IS_BETTER,
)
from nhc_deprot_ranker.data.provenance import sha256_file
from nhc_deprot_ranker.quantum.phase8b_authority import (
    PHASE7_GEOMETRY_VALIDATION_SHA256,
    ExactPhase8BAuthority,
)
from nhc_deprot_ranker.quantum.phase8b_execution import ComputeClaimEvidence
from nhc_deprot_ranker.quantum.phase8b_permit import (
    FROZEN_ATTEMPT_ID,
    FROZEN_INCHIKEY,
    FROZEN_INPUT_SHA256,
    FROZEN_PROTOCOL_SHA256,
    FROZEN_REQUEST_ID,
    FROZEN_RESOURCES,
    ConsumedPhase8BPermit,
)

EndpointName = Literal["cation", "neutral"]
SCFStrategy = Literal["standard", "soscf"]

REQUEST_SCHEMA_VERSION: Final = "nhc-two-endpoint-request-v1"
RESULT_SCHEMA_VERSION: Final = "nhc-two-endpoint-result-v2"
ATTEMPT_SCHEMA_VERSION: Final = "nhc-two-endpoint-attempt-v2"
SUCCESS_SCHEMA_VERSION: Final = "nhc-two-endpoint-success-v2"
SUPERVISOR_SUCCESS_SCHEMA_VERSION: Final = "nhc-two-endpoint-supervisor-success-v1"
FAILURE_SCHEMA_VERSION: Final = "nhc-two-endpoint-failure-v1"
RUNNER_SOURCE_SCHEMA_VERSION: Final = "nhc-two-endpoint-runner-source-v3"

# This is a source-level gate, not a caller-provided option.  A later phase must
# review and deliberately change it before any backend can load PySCF.
EXECUTION_AUTHORIZED: Final[bool] = False

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
_REQUEST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_ATTEMPT_ID_RE = re.compile(r"^attempt-[a-z0-9][a-z0-9-]{0,63}$")
_ELEMENT_RE = re.compile(r"^[A-Z][a-z]?$|^D$|^T$")
_MAX_REQUEST_BYTES = 64 * 1024
_MAX_XYZ_BYTES = 2 * 1024 * 1024
_MAX_ATOMS = 1000
_MAX_ABS_COORDINATE_ANGSTROM = 10_000.0
_SUPERVISION_OUTCOMES: Final[frozenset[str]] = frozenset(
    {"clean", "nonzero", "timeout", "spawn_error", "supervision_error", "orphan_descendants"}
)
COMPUTE_THREADS: Final = 4
PYSCF_MAX_MEMORY_MB: Final = 12_000
FROZEN_ELECTRON_COUNT: Final = 120
PYSCF_DISPERSION_VERSION: Final = "1.5.0"
THREAD_ENVIRONMENT: Final[dict[str, str]] = {
    "BLIS_NUM_THREADS": "4",
    "GOTO_NUM_THREADS": "4",
    "MKL_DYNAMIC": "FALSE",
    "MKL_NUM_THREADS": "4",
    "NUMEXPR_NUM_THREADS": "4",
    "OMP_DYNAMIC": "FALSE",
    "OMP_MAX_ACTIVE_LEVELS": "1",
    "OMP_NESTED": "FALSE",
    "OMP_NUM_THREADS": "4",
    "OMP_THREAD_LIMIT": "4",
    "OMP_WAIT_POLICY": "PASSIVE",
    "OPENBLAS_NUM_THREADS": "4",
    "VECLIB_MAXIMUM_THREADS": "4",
}
_CANONICAL_THREAD_ENVIRONMENT: Final[tuple[tuple[str, str], ...]] = tuple(
    sorted(THREAD_ENVIRONMENT.items())
)
_SUPERVISOR_TERMINATE_GRACE_SECONDS: Final = 10.0
_SUPERVISOR_STREAM_CAPTURE_LIMIT_BYTES: Final = 64 * 1024
_SUPERVISOR_HARD_WALL_SECONDS: Final = 7200.0
_PRIVATE_FILE_MODE: Final = 0o600
_RUNNER_SOURCE_RELATIVE_PATHS: Final[tuple[str, ...]] = (
    "nhc_deprot_ranker/__init__.py",
    "nhc_deprot_ranker/constants.py",
    "nhc_deprot_ranker/data/__init__.py",
    "nhc_deprot_ranker/data/provenance.py",
    "nhc_deprot_ranker/quantum/__init__.py",
    "nhc_deprot_ranker/quantum/linux_guardian.py",
    "nhc_deprot_ranker/quantum/phase8b_authority.py",
    "nhc_deprot_ranker/quantum/phase8b_execution.py",
    "nhc_deprot_ranker/quantum/phase8b_permit.py",
    "nhc_deprot_ranker/quantum/phase8b_runtime.py",
    "nhc_deprot_ranker/quantum/two_endpoint.py",
    "nhc_deprot_ranker/quantum/worker.py",
    "nhc_deprot_ranker/quantum/worker_bootstrap.py",
    "nhc_deprot_ranker/quantum/process_supervisor.py",
)
_WORKER_BOOTSTRAP: Final = (
    "import runpy,sys;"
    "sys.path.insert(0,sys.argv.pop(1));"
    "runpy.run_module('nhc_deprot_ranker.quantum.worker',run_name='__main__',alter_sys=True)"
)
_HANDSHAKE_WORKER_BOOTSTRAP: Final = (
    "import runpy,sys;"
    "sys.path.insert(0,sys.argv.pop(1));"
    "runpy.run_module('nhc_deprot_ranker.quantum.worker_bootstrap',"
    "run_name='__main__',alter_sys=True)"
)
_SUCCESS_ATTEMPT_FILENAMES: Final[frozenset[str]] = frozenset(
    {
        "_ATTEMPT_SUCCESS",
        "cation.json",
        "cation.optimized.xyz",
        "neutral.json",
        "neutral.optimized.xyz",
        "result.json",
    }
)
_WORKER_FAILURE_ATTEMPT_FILENAMES: Final[frozenset[str]] = frozenset(
    {
        "failure.json",
        "cation.json",
        "cation.optimized.xyz",
        "neutral.json",
        "neutral.optimized.xyz",
    }
)
_WORKER_FAILURE_STAGES: Final[frozenset[str]] = frozenset(
    {"initialization", "cation", "neutral", "label", "publish_attempt"}
)
_WORKER_ERROR_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

_ELEMENTS: Final[frozenset[str]] = frozenset(
    {
        "H",
        "He",
        "Li",
        "Be",
        "B",
        "C",
        "N",
        "O",
        "F",
        "Ne",
        "Na",
        "Mg",
        "Al",
        "Si",
        "P",
        "S",
        "Cl",
        "Ar",
        "K",
        "Ca",
        "Sc",
        "Ti",
        "V",
        "Cr",
        "Mn",
        "Fe",
        "Co",
        "Ni",
        "Cu",
        "Zn",
        "Ga",
        "Ge",
        "As",
        "Se",
        "Br",
        "Kr",
        "Rb",
        "Sr",
        "Y",
        "Zr",
        "Nb",
        "Mo",
        "Tc",
        "Ru",
        "Rh",
        "Pd",
        "Ag",
        "Cd",
        "In",
        "Sn",
        "Sb",
        "Te",
        "I",
        "Xe",
        "Cs",
        "Ba",
        "La",
        "Ce",
        "Pr",
        "Nd",
        "Pm",
        "Sm",
        "Eu",
        "Gd",
        "Tb",
        "Dy",
        "Ho",
        "Er",
        "Tm",
        "Yb",
        "Lu",
        "Hf",
        "Ta",
        "W",
        "Re",
        "Os",
        "Ir",
        "Pt",
        "Au",
        "Hg",
        "Tl",
        "Pb",
        "Bi",
        "Po",
        "At",
        "Rn",
        "Fr",
        "Ra",
        "Ac",
        "Th",
        "Pa",
        "U",
        "Np",
        "Pu",
        "Am",
        "Cm",
        "Bk",
        "Cf",
        "Es",
        "Fm",
        "Md",
        "No",
        "Lr",
        "Rf",
        "Db",
        "Sg",
        "Bh",
        "Hs",
        "Mt",
        "Ds",
        "Rg",
        "Cn",
        "Nh",
        "Fl",
        "Mc",
        "Lv",
        "Ts",
        "Og",
        "D",
        "T",
    }
)

_PERIODIC_SYMBOLS: Final[tuple[str, ...]] = tuple(
    """H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn
    Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr
    Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra
    Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts
    Og""".split()  # noqa: SIM905 - compact immutable periodic-table declaration
)
_ATOMIC_NUMBERS: Final[dict[str, int]] = {
    symbol: atomic_number for atomic_number, symbol in enumerate(_PERIODIC_SYMBOLS, start=1)
}
_ATOMIC_NUMBERS.update({"D": 1, "T": 1})


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, allow_nan=False, ensure_ascii=True) + "\n"
    ).encode("utf-8")


LOCKED_PROTOCOL: Final[dict[str, object]] = {
    "label_protocol_id": "2d03e2dc62c94cbf2bb6aaa1a40b842bb1369427c9df10b742441ef7227850fd",
    "reaction": "NHC-H+ -> NHC + H+",
    "phase": "gas",
    "method": "B3LYP",
    "dispersion": "D3(BJ)",
    "basis": "def2-SVP",
    "grid_level": 3,
    "geometry_optimizer": "geomeTRIC",
    "geometry_maxsteps": 100,
    "scf_conv_tol": 1.0e-9,
    "cation_charge": 1,
    "cation_multiplicity": 1,
    "neutral_charge": 0,
    "neutral_multiplicity": 1,
    "target_definition": "electronic_deprotonation_energy",
    "label_quality": "electronic_energy_only",
    "hartree_to_kcal_mol": HARTREE_TO_KCAL_MOL,
    "proton_constant_kcal": GAS_PROTON_KCAL_MOL,
    "lower_is_better": LOWER_IS_BETTER,
    "hessian_computed": False,
}
LOCKED_PROTOCOL_SHA256: Final[str] = hashlib.sha256(
    _canonical_json_bytes(LOCKED_PROTOCOL)
).hexdigest()


class TwoEndpointError(RuntimeError):
    """Base class for fail-closed runner errors."""


class RequestValidationError(TwoEndpointError):
    """The frozen request, path, hash, or XYZ contract is invalid."""


class ExecutionNotAuthorizedError(TwoEndpointError):
    """Public quantum execution is disabled by the Phase 7 source gate."""

    exit_code = 2


class ResumeValidationError(TwoEndpointError):
    """An existing success state is corrupt or differs from the request."""


class BackendError(TwoEndpointError):
    """A backend failed without permission to change scientific protocol."""


class DispersionUnavailableError(BackendError):
    """The backend cannot prove that D3(BJ) is active."""


class DispersionEvaluationError(BackendError):
    """An enabled D3(BJ) energy, gradient, or audit evaluation failed."""


class SCFConvergenceError(BackendError):
    """Base class for typed SCF convergence failures."""


class SCFNotConvergedError(SCFConvergenceError):
    """An SCF returned normally but explicitly reported non-convergence.

    This is the only backend failure type that may consume the endpoint's one
    same-protocol SOSCF retry.  Exceptions raised by an SCF implementation are
    deliberately classified elsewhere and never become retryable by message
    inspection.
    """


class GeometryConvergenceError(BackendError):
    """The geomeTRIC optimization did not explicitly converge."""


class BackendTimeoutError(BackendError):
    """The backend exceeded the frozen request deadline."""


class ResourceConfigurationError(BackendError):
    """The frozen thread or PySCF memory controls were not retained."""


class ResourceLimitError(BackendError):
    """The backend exhausted a resource inside the frozen envelope."""


class BackendUnknownError(BackendError):
    """An unclassified backend exception failed closed without a retry."""


class TwoEndpointRunError(TwoEndpointError):
    """A guarded attempt failed and emitted a failure envelope."""

    def __init__(self, message: str, *, exit_code: int, attempt_dir: Path | None) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.attempt_dir = attempt_dir


@dataclass(frozen=True)
class XYZAtom:
    """One validated XYZ atom in Angstrom."""

    element: str
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class XYZGeometry:
    """A finite, ordered XYZ geometry."""

    atoms: tuple[XYZAtom, ...]

    def to_xyz_bytes(self, *, comment: str) -> bytes:
        """Serialize deterministically without changing atom order."""

        lines = [str(len(self.atoms)), comment]
        lines.extend(
            f"{atom.element:<2} {atom.x: .12f} {atom.y: .12f} {atom.z: .12f}" for atom in self.atoms
        )
        return ("\n".join(lines) + "\n").encode("utf-8")


@dataclass(frozen=True)
class EndpointRequest:
    """Validated endpoint identity and geometry."""

    name: EndpointName
    xyz_relative_path: str
    xyz_path: Path
    xyz_sha256: str
    charge: int
    multiplicity: int
    electron_count: int
    geometry: XYZGeometry


@dataclass(frozen=True)
class TwoEndpointRequest:
    """Strict, hash-bound future execution request."""

    schema_version: str
    request_id: str
    inchikey: str
    execution_authorized: bool
    timeout_seconds: int
    runner_source_sha256: str
    request_path: Path
    request_sha256: str
    protocol_sha256: str
    cation: EndpointRequest
    neutral: EndpointRequest


@dataclass(frozen=True)
class RuntimeEvidence:
    """Resource and electronic-state evidence retained after an operation."""

    compute_threads: int
    thread_environment: tuple[tuple[str, str], ...]
    pyscf_threads: int
    molecule_max_memory_mb: int
    mean_field_max_memory_mb: int
    electron_count: int


@dataclass(frozen=True)
class OptimizationD3Evidence:
    """Proof that optimization energies and gradients used active D3(BJ)."""

    tag: str
    energy_hook_calls: int
    gradient_hook_calls: int
    gradient_shape: tuple[int, int]
    energy_values_finite: bool
    gradient_values_finite: bool


@dataclass(frozen=True)
class FinalEnergyBreakdown:
    """Non-overlapping PySCF RKS summary components for the final total."""

    nuclear_hartree: float
    one_electron_hartree: float
    coulomb_hartree: float
    exchange_correlation_hartree: float
    dispersion_hartree: float
    reconstructed_hartree: float
    total_hartree: float
    absolute_error_hartree: float


@dataclass(frozen=True)
class FinalD3Evidence:
    """Final-SCF D3(BJ) hook, arithmetic, and one zero-SCF adapter audit."""

    tag: str
    energy_hook_calls: int
    breakdown: FinalEnergyBreakdown
    audit_calls: int
    audit_energy_hartree: float
    audit_gradient_shape: tuple[int, int]
    audit_gradient_finite: bool
    audit_absolute_error_hartree: float
    adapter_version: str


@dataclass(frozen=True)
class BackendOptimizationResult:
    """Backend response for one geomeTRIC optimization."""

    geometry: XYZGeometry
    geometry_converged: bool
    scf_converged: bool
    last_energy_hartree: float
    runtime: RuntimeEvidence
    dispersion: OptimizationD3Evidence


@dataclass(frozen=True)
class BackendSCFResult:
    """Backend response for the final same-method electronic energy."""

    converged: bool
    energy_hartree: float
    runtime: RuntimeEvidence
    dispersion: FinalD3Evidence


@dataclass(frozen=True)
class _PySCFModules:
    """Lazily loaded compute modules and their verified runtime state."""

    gto: Any
    dft: Any
    geometric_solver: Any
    lib: Any
    dftd3: Any
    thread_environment: tuple[tuple[str, str], ...]
    pyscf_threads: int
    adapter_version: str


class TwoEndpointBackend(Protocol):
    """Dependency-injected backend seam used by mock tests."""

    def optimize(
        self,
        *,
        endpoint: EndpointName,
        geometry: XYZGeometry,
        charge: int,
        multiplicity: int,
        strategy: SCFStrategy,
        deadline_monotonic: float,
    ) -> BackendOptimizationResult:
        """Run the one allowed geometry optimization."""

    def final_scf(
        self,
        *,
        endpoint: EndpointName,
        geometry: XYZGeometry,
        charge: int,
        multiplicity: int,
        strategy: SCFStrategy,
        deadline_monotonic: float,
    ) -> BackendSCFResult:
        """Run the final same-method energy evaluation."""


class _SupervisionResultLike(Protocol):
    """Narrow result surface consumed from the process-tree supervisor."""

    outcome: str
    returncode: int | None
    child_returncode: int | None
    stdout: bytes
    stderr: bytes
    stdout_total_bytes: int
    stderr_total_bytes: int
    timed_out: bool
    term_sent: bool
    kill_sent: bool
    orphan_descendants_detected: bool
    process_started: bool
    group_cleanup_confirmed: bool
    direct_child_reaped: bool
    stdout_truncated: bool
    stderr_truncated: bool
    duration_seconds: float
    pid: int | None
    pgid: int | None
    error_message: str | None


class _RunSupervised(Protocol):
    """Dependency-injection seam for harmless Phase 8A protocol tests."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        policy: object,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        pass_fds: Sequence[int] = (),
        on_process_started: Callable[[int, int], None] | None = None,
    ) -> _SupervisionResultLike:
        """Run one isolated worker process tree."""


class _SupervisionPolicyFactory(Protocol):
    """Lazy constructor surface supplied by ``process_supervisor``."""

    def __call__(
        self,
        *,
        timeout_seconds: float,
        terminate_grace_seconds: float,
        stream_capture_limit_bytes: int,
        absolute_deadline_monotonic: float | None = None,
    ) -> object:
        """Build the concrete supervisor policy."""


@dataclass(frozen=True)
class TwoEndpointRunResult:
    """Successful two-endpoint label and immutable output identity."""

    attempt_id: str
    request_id: str
    inchikey: str
    cation_energy_hartree: float
    neutral_energy_hartree: float
    electronic_difference_kcal: float
    dft_deprot_electronic_kcal: float
    result_relative_path: str
    result_sha256: str
    resumed: bool
    exit_code: int = 0


@dataclass(frozen=True)
class Phase8BWorkerLaunch:
    """Pre-import worker handshake and exact authorization argv."""

    start_read_fd: int
    release_write_fd: int
    release_token: str
    absolute_deadline_ns: int
    compute_claim_path: Path
    on_process_started: Callable[[int, int, Path], None]
    authorization_argv: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.start_read_fd, bool)
            or isinstance(self.release_write_fd, bool)
            or self.start_read_fd < 0
            or self.release_write_fd < 0
            or self.start_read_fd == self.release_write_fd
        ):
            raise ValueError("worker handshake file descriptors are invalid")
        if _SHA256_RE.fullmatch(self.release_token) is None:
            raise ValueError("worker release token must be one lowercase SHA256 token")
        if isinstance(self.absolute_deadline_ns, bool) or self.absolute_deadline_ns <= 0:
            raise ValueError("worker absolute deadline must be positive integer nanoseconds")
        if (
            not self.compute_claim_path.is_absolute()
            or self.compute_claim_path.name != "compute_claim.json"
            or Path(os.path.abspath(self.compute_claim_path)) != self.compute_claim_path
        ):
            raise ValueError("worker compute claim path is invalid")
        if not callable(self.on_process_started):
            raise TypeError("worker start callback must be callable")
        if any(not isinstance(value, str) or not value for value in self.authorization_argv):
            raise ValueError("worker authorization argv must contain non-empty strings")


def _canonical_runner_source_sha256(sources: Mapping[str, bytes]) -> str:
    """Hash the complete exact pre-gate executable source closure."""

    if set(sources) != set(_RUNNER_SOURCE_RELATIVE_PATHS):
        raise ValueError("runner source bundle must contain the exact canonical file set")
    digest = hashlib.sha256()
    digest.update(RUNNER_SOURCE_SCHEMA_VERSION.encode("ascii"))
    digest.update(b"\x00")
    for name in _RUNNER_SOURCE_RELATIVE_PATHS:
        content = sources[name]
        if not isinstance(content, bytes) or not content:
            raise ValueError(f"runner source is empty or not bytes: {name}")
        encoded_name = name.encode("ascii")
        digest.update(len(encoded_name).to_bytes(2, "big"))
        digest.update(encoded_name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def current_runner_source_sha256() -> str:
    """Return the canonical hash of the parent, worker and supervisor sources."""

    source_root = Path(__file__).resolve().parents[2]
    sources: dict[str, bytes] = {}
    for name in _RUNNER_SOURCE_RELATIVE_PATHS:
        path = source_root / name
        try:
            if path.is_symlink() or not path.is_file():
                raise OSError("not a regular source file")
            sources[name] = path.read_bytes()
        except OSError as exc:
            raise TwoEndpointError(f"runner source identity is unavailable: {name}") from exc
    return _canonical_runner_source_sha256(sources)


def _require_exact_keys(payload: dict[str, object], expected: set[str], label: str) -> None:
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise RequestValidationError(f"{label} fields mismatch; missing={missing}, extra={extra}")


def _strict_json_object(
    raw: bytes, *, label: str, error_cls: type[TwoEndpointError]
) -> dict[str, object]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise error_cls(f"{label} must be UTF-8") from exc

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise error_cls(f"{label} contains duplicate key: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        raise error_cls(f"{label} contains non-finite JSON number: {value}")

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except error_cls:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise error_cls(f"{label} is not strict JSON") from exc
    if not isinstance(parsed, dict):
        raise error_cls(f"{label} must be a JSON object")
    return cast(dict[str, object], parsed)


def _json_without_duplicates(raw: bytes, *, label: str) -> dict[str, object]:
    return _strict_json_object(raw, label=label, error_cls=RequestValidationError)


def _require_regular_file(path: Path, *, label: str, max_bytes: int) -> bytes:
    if path.is_symlink():
        raise RequestValidationError(f"{label} must not be a symlink")
    if not path.is_file():
        raise RequestValidationError(f"{label} must be a regular file")
    size = path.stat().st_size
    if size <= 0 or size > max_bytes:
        raise RequestValidationError(f"{label} size is outside the allowed range")
    return path.read_bytes()


def _safe_relative_file(base: Path, name: object, *, label: str) -> tuple[str, Path]:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise RequestValidationError(f"{label} must be a non-empty POSIX relative path")
    relative = PurePosixPath(name)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise RequestValidationError(f"{label} contains an unsafe path")
    if relative.as_posix() != name:
        raise RequestValidationError(f"{label} must be canonical POSIX form")
    if base.is_symlink() or not base.is_dir():
        raise RequestValidationError("request directory must be a real directory")
    candidate = base.joinpath(*relative.parts)
    current = base
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise RequestValidationError(f"{label} traverses a symlink")
        if not current.is_dir():
            raise RequestValidationError(f"{label} parent does not exist")
    if candidate.is_symlink():
        raise RequestValidationError(f"{label} must not be a symlink")
    base_resolved = base.resolve(strict=True)
    candidate_resolved = candidate.resolve(strict=True)
    try:
        candidate_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise RequestValidationError(f"{label} escapes the request directory") from exc
    return name, candidate


def _require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise RequestValidationError(f"{label} must be a lowercase SHA256")
    return value


def _parse_xyz(raw: bytes, *, label: str) -> XYZGeometry:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RequestValidationError(f"{label} must be UTF-8") from exc
    if "\x00" in text:
        raise RequestValidationError(f"{label} contains NUL")
    lines = text.splitlines()
    if len(lines) < 3:
        raise RequestValidationError(f"{label} is too short")
    try:
        count = int(lines[0].strip())
    except ValueError as exc:
        raise RequestValidationError(f"{label} has an invalid atom count") from exc
    if count <= 0 or count > _MAX_ATOMS:
        raise RequestValidationError(f"{label} atom count is outside the allowed range")
    if len(lines) != count + 2:
        raise RequestValidationError(f"{label} line count does not match its atom count")
    atoms: list[XYZAtom] = []
    for index, line in enumerate(lines[2:], start=1):
        fields = line.split()
        if len(fields) != 4:
            raise RequestValidationError(f"{label} atom {index} must have four fields")
        element = fields[0]
        if _ELEMENT_RE.fullmatch(element) is None or element not in _ELEMENTS:
            raise RequestValidationError(f"{label} atom {index} has an unknown element")
        try:
            coordinates = tuple(float(value) for value in fields[1:])
        except ValueError as exc:
            raise RequestValidationError(f"{label} atom {index} has invalid coordinates") from exc
        if len(coordinates) != 3 or not all(math.isfinite(value) for value in coordinates):
            raise RequestValidationError(f"{label} atom {index} has non-finite coordinates")
        if any(abs(value) > _MAX_ABS_COORDINATE_ANGSTROM for value in coordinates):
            raise RequestValidationError(f"{label} atom {index} has unbounded coordinates")
        atoms.append(XYZAtom(element, *coordinates))
    return XYZGeometry(tuple(atoms))


def _electron_count_for_geometry(geometry: XYZGeometry, *, charge: int) -> int:
    """Compute the all-electron count without importing a chemistry package."""

    if type(charge) is not int:
        raise RequestValidationError("endpoint charge must be an integer")
    try:
        nuclear_charge = sum(_ATOMIC_NUMBERS[atom.element] for atom in geometry.atoms)
    except KeyError as exc:
        raise RequestValidationError(
            "endpoint contains an element without an atomic number"
        ) from exc
    electron_count = nuclear_charge - charge
    if electron_count <= 0:
        raise RequestValidationError("endpoint electron count must be positive")
    return electron_count


def _validate_endpoint_pair_electrons(
    cation: EndpointRequest,
    neutral: EndpointRequest,
    *,
    expected_electron_count: int | None = None,
) -> int:
    """Fail closed on pair/state drift before any PySCF import.

    The exact C2 attachment remains bound by the Phase 7 map closure.  This
    chemistry-free check independently proves the ordered heavy-element
    sequence, one-proton difference, equal/even electrons, and singlet parity.
    """

    cation_elements = tuple(atom.element for atom in cation.geometry.atoms)
    neutral_elements = tuple(atom.element for atom in neutral.geometry.atoms)
    cation_heavy = tuple(element for element in cation_elements if element not in {"H", "D", "T"})
    neutral_heavy = tuple(element for element in neutral_elements if element not in {"H", "D", "T"})
    if cation_heavy != neutral_heavy:
        raise RequestValidationError("endpoint ordered heavy-element sequences differ")
    if len(cation_elements) != len(neutral_elements) + 1:
        raise RequestValidationError("endpoints must differ by exactly one atom")
    cation_counts = {element: cation_elements.count(element) for element in set(cation_elements)}
    neutral_counts = {element: neutral_elements.count(element) for element in set(neutral_elements)}
    symbols = set(cation_counts) | set(neutral_counts)
    differences = {
        symbol: cation_counts.get(symbol, 0) - neutral_counts.get(symbol, 0)
        for symbol in symbols
        if cation_counts.get(symbol, 0) != neutral_counts.get(symbol, 0)
    }
    if differences != {"H": 1}:
        raise RequestValidationError("endpoints must differ by exactly one protium")
    cation_electrons = _electron_count_for_geometry(cation.geometry, charge=cation.charge)
    neutral_electrons = _electron_count_for_geometry(neutral.geometry, charge=neutral.charge)
    if cation_electrons != cation.electron_count or neutral_electrons != neutral.electron_count:
        raise RequestValidationError("stored endpoint electron count drifted")
    if cation_electrons != neutral_electrons:
        raise RequestValidationError("endpoint electron counts differ")
    if cation_electrons % 2 != 0:
        raise RequestValidationError("locked singlet endpoints require an even electron count")
    if cation.multiplicity != 1 or neutral.multiplicity != 1:
        raise RequestValidationError("locked endpoint multiplicities must be singlets")
    if expected_electron_count is not None and cation_electrons != expected_electron_count:
        raise RequestValidationError(
            f"frozen endpoint pair must contain exactly {expected_electron_count} electrons"
        )
    return cation_electrons


def _validate_frozen_120_electron_pair(cation: EndpointRequest, neutral: EndpointRequest) -> int:
    """Exact Phase 8B pre-gate helper for the frozen QXH endpoint pair."""

    return _validate_endpoint_pair_electrons(
        cation,
        neutral,
        expected_electron_count=FROZEN_ELECTRON_COUNT,
    )


def _parse_endpoint(*, name: EndpointName, payload: object, request_dir: Path) -> EndpointRequest:
    if not isinstance(payload, dict):
        raise RequestValidationError(f"endpoints.{name} must be an object")
    endpoint_payload = cast(dict[str, object], payload)
    _require_exact_keys(
        endpoint_payload,
        {"xyz_path", "xyz_sha256", "charge", "multiplicity"},
        f"endpoints.{name}",
    )
    relative, path = _safe_relative_file(
        request_dir, endpoint_payload["xyz_path"], label=f"endpoints.{name}.xyz_path"
    )
    expected_hash = _require_sha256(
        endpoint_payload["xyz_sha256"], label=f"endpoints.{name}.xyz_sha256"
    )
    raw = _require_regular_file(path, label=f"{name} XYZ", max_bytes=_MAX_XYZ_BYTES)
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != expected_hash:
        raise RequestValidationError(f"{name} XYZ SHA256 mismatch")
    expected_charge = 1 if name == "cation" else 0
    charge = endpoint_payload["charge"]
    multiplicity = endpoint_payload["multiplicity"]
    if type(charge) is not int or charge != expected_charge:
        raise RequestValidationError(f"{name} charge must be {expected_charge}")
    if type(multiplicity) is not int or multiplicity != 1:
        raise RequestValidationError(f"{name} multiplicity must be 1")
    geometry = _parse_xyz(raw, label=f"{name} XYZ")
    return EndpointRequest(
        name=name,
        xyz_relative_path=relative,
        xyz_path=path,
        xyz_sha256=expected_hash,
        charge=charge,
        multiplicity=multiplicity,
        electron_count=_electron_count_for_geometry(geometry, charge=charge),
        geometry=geometry,
    )


def load_two_endpoint_request(request_path: Path) -> TwoEndpointRequest:
    """Validate a frozen request, source identity, paths, hashes, and both XYZ files."""

    raw = _require_regular_file(
        request_path, label="two-endpoint request", max_bytes=_MAX_REQUEST_BYTES
    )
    payload = _json_without_duplicates(raw, label="two-endpoint request")
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "request_id",
            "inchikey",
            "execution_authorized",
            "timeout_seconds",
            "runner_source_sha256",
            "protocol",
            "endpoints",
        },
        "two-endpoint request",
    )
    if payload["schema_version"] != REQUEST_SCHEMA_VERSION:
        raise RequestValidationError("unsupported request schema_version")
    request_id = payload["request_id"]
    if not isinstance(request_id, str) or _REQUEST_ID_RE.fullmatch(request_id) is None:
        raise RequestValidationError("request_id must be a safe lowercase identifier")
    inchikey = payload["inchikey"]
    if not isinstance(inchikey, str) or _INCHIKEY_RE.fullmatch(inchikey) is None:
        raise RequestValidationError("inchikey is not canonical")
    execution_authorized = payload["execution_authorized"]
    if type(execution_authorized) is not bool:
        raise RequestValidationError("execution_authorized must be boolean")
    timeout_seconds = payload["timeout_seconds"]
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 7 * 24 * 3600:
        raise RequestValidationError("timeout_seconds must be an integer in [1, 604800]")
    runner_hash = _require_sha256(payload["runner_source_sha256"], label="runner_source_sha256")
    if runner_hash != current_runner_source_sha256():
        raise RequestValidationError("runner source SHA256 mismatch")
    if not isinstance(payload["protocol"], dict) or payload["protocol"] != LOCKED_PROTOCOL:
        raise RequestValidationError("request protocol is not the unique locked protocol")
    endpoints = payload["endpoints"]
    if not isinstance(endpoints, dict):
        raise RequestValidationError("endpoints must be an object")
    endpoint_payload = cast(dict[str, object], endpoints)
    _require_exact_keys(endpoint_payload, {"cation", "neutral"}, "endpoints")
    cation = _parse_endpoint(
        name="cation", payload=endpoint_payload["cation"], request_dir=request_path.parent
    )
    neutral = _parse_endpoint(
        name="neutral", payload=endpoint_payload["neutral"], request_dir=request_path.parent
    )
    if cation.xyz_path.resolve() == neutral.xyz_path.resolve():
        raise RequestValidationError("cation and neutral XYZ paths must differ")
    _validate_endpoint_pair_electrons(cation, neutral)
    return TwoEndpointRequest(
        schema_version=REQUEST_SCHEMA_VERSION,
        request_id=request_id,
        inchikey=inchikey,
        execution_authorized=execution_authorized,
        timeout_seconds=timeout_seconds,
        runner_source_sha256=runner_hash,
        request_path=request_path,
        request_sha256=hashlib.sha256(raw).hexdigest(),
        protocol_sha256=LOCKED_PROTOCOL_SHA256,
        cation=cation,
        neutral=neutral,
    )


def _ensure_execution_authorized() -> None:
    if EXECUTION_AUTHORIZED is not True:
        raise ExecutionNotAuthorizedError("two-endpoint quantum execution is disabled in Phase 8A")


def _validate_thread_environment(environ: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """Verify every frozen native-library thread variable before PySCF import."""

    for name, expected in _CANONICAL_THREAD_ENVIRONMENT:
        if environ.get(name) != expected:
            raise ResourceConfigurationError(
                f"frozen thread environment mismatch: {name} must equal {expected}"
            )
    return _CANONICAL_THREAD_ENVIRONMENT


def _configure_pyscf_threads(lib: Any) -> int:
    """Set and then independently query the PySCF/OpenMP thread count."""

    num_threads = getattr(lib, "num_threads", None)
    if not callable(num_threads):
        raise ResourceConfigurationError("pyscf.lib.num_threads is unavailable")
    try:
        set_result = int(num_threads(COMPUTE_THREADS))
        observed = int(num_threads())
    except Exception as exc:
        raise ResourceConfigurationError("failed to set the frozen PySCF thread count") from exc
    if set_result != COMPUTE_THREADS or observed != COMPUTE_THREADS:
        raise ResourceConfigurationError("PySCF did not retain exactly four OpenMP threads")
    return observed


def _require_explicit_scf_convergence(value: object, *, label: str) -> None:
    """Accept only a literal boolean and retry only a literal ``False``."""

    if type(value) is not bool:
        raise SCFConvergenceError(f"{label} convergence state is not a literal boolean")
    if value is False:
        raise SCFNotConvergedError(f"{label} did not explicitly converge")


def _require_explicit_geometry_convergence(value: object, *, label: str) -> None:
    """Reject ambiguous optimizer status without converting it into an SCF retry."""

    if type(value) is not bool:
        raise GeometryConvergenceError(f"{label} convergence state is not a literal boolean")
    if value is False:
        raise GeometryConvergenceError(f"{label} did not explicitly converge")


def _finite_nonzero_float(value: object, *, label: str) -> float:
    try:
        numeric = float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise DispersionEvaluationError(f"{label} is not numeric") from exc
    if not math.isfinite(numeric) or numeric == 0.0:
        raise DispersionEvaluationError(f"{label} must be finite and nonzero")
    return numeric


def _validate_finite_gradient(value: object, *, natm: int, label: str) -> tuple[int, int]:
    expected = (natm, 3)
    shape = getattr(value, "shape", None)
    if shape is not None:
        try:
            normalized_shape = tuple(int(part) for part in shape)
        except (TypeError, ValueError) as exc:
            raise DispersionEvaluationError(f"{label} shape is unreadable") from exc
        if normalized_shape != expected:
            raise DispersionEvaluationError(f"{label} shape must be {expected}")
    try:
        rows = tuple(cast(Any, value))
        if len(rows) != natm:
            raise DispersionEvaluationError(f"{label} shape must be {expected}")
        for row in rows:
            entries = tuple(row)
            if len(entries) != 3 or not all(math.isfinite(float(entry)) for entry in entries):
                raise DispersionEvaluationError(f"{label} contains invalid values")
    except DispersionEvaluationError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise DispersionEvaluationError(f"{label} is not a finite {natm}x3 array") from exc
    return expected


class _D3HookRecorder:
    """Mutable call recorder scoped to one disposable mean-field object."""

    def __init__(self, *, natm: int) -> None:
        self.natm = natm
        self.energy_hook_calls = 0
        self.gradient_hook_calls = 0

    def observe_energy(self, value: object) -> None:
        _finite_nonzero_float(value, label="D3(BJ) hook energy")
        self.energy_hook_calls += 1

    def observe_gradient(self, value: object) -> None:
        _validate_finite_gradient(value, natm=self.natm, label="D3(BJ) hook gradient")
        self.gradient_hook_calls += 1


def _install_dispersion_observer(
    owner: Any,
    *,
    kind: Literal["energy", "gradient"],
    recorder: _D3HookRecorder,
) -> None:
    original = getattr(owner, "get_dispersion", None)
    if not callable(original):
        raise DispersionUnavailableError(f"D3(BJ) {kind} hook is unavailable")

    def observed(*args: object, **kwargs: object) -> object:
        try:
            value = original(*args, **kwargs)
        except MemoryError as exc:
            raise ResourceLimitError(f"D3(BJ) {kind} hook exhausted memory") from exc
        except (BackendError, TwoEndpointError):
            raise
        except Exception as exc:
            raise DispersionEvaluationError(f"D3(BJ) {kind} hook raised an error") from exc
        if kind == "energy":
            recorder.observe_energy(value)
        else:
            recorder.observe_gradient(value)
        return value

    try:
        owner.get_dispersion = observed
    except Exception as exc:
        raise DispersionUnavailableError(f"D3(BJ) {kind} hook cannot be observed") from exc


def _unique_objects(values: Sequence[Any]) -> tuple[Any, ...]:
    unique: list[Any] = []
    identities: set[int] = set()
    for value in values:
        identity = id(value)
        if identity not in identities:
            identities.add(identity)
            unique.append(value)
    return tuple(unique)


def _require_frozen_memory(value: object, *, label: str) -> int:
    if type(value) not in {int, float}:
        raise ResourceConfigurationError(f"{label} max_memory is unreadable")
    numeric = float(cast(int | float, value))
    if not math.isfinite(numeric) or numeric != PYSCF_MAX_MEMORY_MB:
        raise ResourceConfigurationError(f"{label} did not retain max_memory=12000 MB")
    return int(numeric)


def _require_frozen_molecule_state(
    molecule: Any,
    *,
    label: str,
    expected_electron_count: int,
    expected_charge: int,
) -> int:
    try:
        memory = _require_frozen_memory(molecule.max_memory, label=label)
        electron_count = molecule.nelectron
        charge = molecule.charge
        spin = molecule.spin
    except AttributeError as exc:
        raise ResourceConfigurationError(f"{label} retained state is unavailable") from exc
    for value, state_label, expected in (
        (electron_count, "electron count", expected_electron_count),
        (charge, "charge", expected_charge),
        (spin, "spin", 0),
    ):
        if type(value) is not int or value != expected:
            raise ResourceConfigurationError(f"{label} did not retain the exact {state_label}")
    return memory


def _require_frozen_mean_field_state(
    mean_field: Any,
    *,
    label: str,
    expected_electron_count: int,
    expected_charge: int,
) -> tuple[int, Any]:
    try:
        memory = _require_frozen_memory(mean_field.max_memory, label=label)
        molecule = mean_field.mol
    except AttributeError as exc:
        raise ResourceConfigurationError(f"{label} retained state is unavailable") from exc
    _require_frozen_molecule_state(
        molecule,
        label=f"{label} molecule",
        expected_electron_count=expected_electron_count,
        expected_charge=expected_charge,
    )
    return memory, molecule


def _runtime_evidence(
    *,
    modules: _PySCFModules,
    molecule: Any,
    mean_field: Any,
    electron_count: int,
    charge: int,
) -> RuntimeEvidence:
    molecule_memory = _require_frozen_molecule_state(
        molecule,
        label="configured PySCF molecule",
        expected_electron_count=electron_count,
        expected_charge=charge,
    )
    mean_field_memory, _ = _require_frozen_mean_field_state(
        mean_field,
        label="configured PySCF mean field",
        expected_electron_count=electron_count,
        expected_charge=charge,
    )
    return RuntimeEvidence(
        compute_threads=COMPUTE_THREADS,
        thread_environment=modules.thread_environment,
        pyscf_threads=modules.pyscf_threads,
        molecule_max_memory_mb=molecule_memory,
        mean_field_max_memory_mb=mean_field_memory,
        electron_count=electron_count,
    )


def _retained_runtime_evidence(
    *,
    modules: _PySCFModules,
    molecules: Sequence[Any],
    mean_fields: Sequence[Any],
    expected_electron_count: int,
    expected_charge: int,
) -> RuntimeEvidence:
    """Read back every actual operation owner without resetting any control."""

    if not molecules or not mean_fields:
        raise ResourceConfigurationError("retained PySCF operation owners are unavailable")
    thread_environment = _validate_thread_environment(os.environ)
    num_threads = getattr(modules.lib, "num_threads", None)
    if not callable(num_threads):
        raise ResourceConfigurationError("retained pyscf.lib.num_threads is unavailable")
    try:
        observed_threads = num_threads()
    except Exception as exc:
        raise ResourceConfigurationError("retained PySCF thread count is unreadable") from exc
    if type(observed_threads) is not int or observed_threads != COMPUTE_THREADS:
        raise ResourceConfigurationError("PySCF did not retain exactly four OpenMP threads")

    owner_molecules: list[Any] = []
    mean_field_memories: list[int] = []
    for index, mean_field in enumerate(_unique_objects(mean_fields), start=1):
        memory, owner_molecule = _require_frozen_mean_field_state(
            mean_field,
            label=f"retained PySCF mean field owner {index}",
            expected_electron_count=expected_electron_count,
            expected_charge=expected_charge,
        )
        mean_field_memories.append(memory)
        owner_molecules.append(owner_molecule)

    molecule_memories = [
        _require_frozen_molecule_state(
            molecule,
            label=f"retained PySCF molecule owner {index}",
            expected_electron_count=expected_electron_count,
            expected_charge=expected_charge,
        )
        for index, molecule in enumerate(_unique_objects((*molecules, *owner_molecules)), start=1)
    ]
    return RuntimeEvidence(
        compute_threads=COMPUTE_THREADS,
        thread_environment=thread_environment,
        pyscf_threads=observed_threads,
        molecule_max_memory_mb=molecule_memories[0],
        mean_field_max_memory_mb=mean_field_memories[0],
        electron_count=expected_electron_count,
    )


_COMPUTE_CAPABILITY_SEAL: Final = object()


class _Phase8BComputeCapability:
    """One-use, process-bound authority for the first compute import."""

    __slots__ = (
        "_absolute_deadline_ns",
        "_attempt_id",
        "_backend_owner",
        "_claimed",
        "_compute_claim_sha256",
        "_electron_count",
        "_endpoint_atom_map_sha256",
        "_geometry_validation_sha256",
        "_inchikey",
        "_legacy_atom_map_sha256",
        "_output_root",
        "_payload_manifest_sha256",
        "_permit_sha256",
        "_pid",
        "_project_root",
        "_protocol_sha256",
        "_request_id",
        "_request_path",
        "_request_sha256",
        "_resources_sha256",
        "_run_root",
        "_runner_source_sha256",
        "_seal",
    )

    def __init__(
        self,
        *,
        seal: object,
        pid: int,
        absolute_deadline_ns: int,
        authority: ExactPhase8BAuthority,
        protocol_sha256: str,
        compute_claim_sha256: str,
    ) -> None:
        if seal is not _COMPUTE_CAPABILITY_SEAL:
            raise TypeError("Phase 8B compute capabilities cannot be caller-constructed")
        self._seal = seal
        self._pid = pid
        self._absolute_deadline_ns = absolute_deadline_ns
        self._request_sha256 = authority.request_sha256
        self._runner_source_sha256 = authority.runner_source_sha256
        self._permit_sha256 = authority.permit_sha256
        self._payload_manifest_sha256 = authority.payload_manifest_sha256
        self._endpoint_atom_map_sha256 = authority.endpoint_atom_map_sha256
        self._legacy_atom_map_sha256 = authority.legacy_atom_map_sha256
        self._geometry_validation_sha256 = authority.geometry_validation_sha256
        self._electron_count = authority.electron_count
        self._request_id = authority.request_id
        self._inchikey = authority.inchikey
        self._attempt_id = authority.attempt_id
        self._project_root = authority.project_root
        self._run_root = authority.run_root
        self._request_path = authority.request_path
        self._output_root = authority.output_root
        self._resources_sha256 = authority.resources_sha256
        self._protocol_sha256 = protocol_sha256
        self._compute_claim_sha256 = compute_claim_sha256
        self._claimed = False
        self._backend_owner: object | None = None


_ComputeCapabilityBinding = tuple[object, ...]
_LIVE_COMPUTE_CAPABILITIES: dict[
    int,
    tuple[_Phase8BComputeCapability, _ComputeCapabilityBinding],
] = {}


def _compute_capability_binding(
    capability: _Phase8BComputeCapability,
) -> _ComputeCapabilityBinding:
    return (
        capability._pid,
        capability._absolute_deadline_ns,
        capability._compute_claim_sha256,
        capability._request_sha256,
        capability._runner_source_sha256,
        capability._permit_sha256,
        capability._payload_manifest_sha256,
        capability._endpoint_atom_map_sha256,
        capability._legacy_atom_map_sha256,
        capability._geometry_validation_sha256,
        capability._electron_count,
        capability._request_id,
        capability._inchikey,
        capability._attempt_id,
        capability._project_root,
        capability._run_root,
        capability._request_path,
        capability._output_root,
        capability._resources_sha256,
        capability._protocol_sha256,
    )


def _frozen_resources_sha256() -> str:
    return hashlib.sha256(_canonical_json_bytes(FROZEN_RESOURCES)).hexdigest()


def _authority_matches_frozen_worker(
    *,
    request: TwoEndpointRequest,
    consumed: ConsumedPhase8BPermit,
    authority: ExactPhase8BAuthority,
    output_root: Path,
    attempt_id: str,
) -> bool:
    permit = consumed.permit
    return (
        consumed.consumed_path == permit.consumed_path
        and consumed.consumed_sha256 == permit.permit_sha256
        and request.schema_version == REQUEST_SCHEMA_VERSION
        and request.execution_authorized is True
        and request.request_id == authority.request_id == FROZEN_REQUEST_ID
        and request.inchikey == authority.inchikey == FROZEN_INCHIKEY
        and request.protocol_sha256 == FROZEN_PROTOCOL_SHA256 == LOCKED_PROTOCOL_SHA256
        and request.timeout_seconds == FROZEN_RESOURCES["hard_wall_timeout_seconds"]
        and request.request_sha256 == authority.request_sha256 == permit.request_sha256
        and request.runner_source_sha256
        == authority.runner_source_sha256
        == permit.runner_source_sha256
        and authority.permit_sha256 == permit.permit_sha256
        and authority.payload_manifest_sha256 == permit.payload_manifest_sha256
        and authority.endpoint_atom_map_sha256 == FROZEN_INPUT_SHA256["endpoint_atom_map"]
        and authority.legacy_atom_map_sha256 == FROZEN_INPUT_SHA256["legacy_atom_map"]
        and authority.geometry_validation_sha256 == PHASE7_GEOMETRY_VALIDATION_SHA256
        and authority.electron_count
        == request.cation.electron_count
        == request.neutral.electron_count
        == FROZEN_ELECTRON_COUNT
        and authority.attempt_id == attempt_id == FROZEN_ATTEMPT_ID
        and authority.project_root == permit.project_root.as_posix()
        and authority.run_root == permit.run_root.as_posix()
        and authority.request_path == permit.request_path.as_posix()
        and authority.output_root == permit.output_root.as_posix() == output_root.as_posix()
        and request.request_path == permit.request_path
        and authority.resources_sha256 == _frozen_resources_sha256()
    )


def _issue_phase8b_compute_capability(
    *,
    request: TwoEndpointRequest,
    consumed: ConsumedPhase8BPermit,
    authority: ExactPhase8BAuthority,
    bootstrap_proof: object,
    output_root: Path,
    attempt_id: str,
    absolute_deadline_ns: int,
    compute_claim_evidence: ComputeClaimEvidence,
) -> _Phase8BComputeCapability:
    """Revalidate exact consumed authority, then claim the bootstrap release."""

    _ensure_execution_authorized()
    if (
        not isinstance(consumed, ConsumedPhase8BPermit)
        or not isinstance(authority, ExactPhase8BAuthority)
        or not isinstance(compute_claim_evidence, ComputeClaimEvidence)
        or type(absolute_deadline_ns) is not int
    ):
        raise ExecutionNotAuthorizedError("worker compute authority has an invalid type")
    permit = consumed.permit
    from nhc_deprot_ranker.quantum.phase8b_authority import (
        Phase8BRequestLike,
        validate_exact_phase8b_authority,
    )
    from nhc_deprot_ranker.quantum.phase8b_permit import load_consumed_phase8b_permit

    reloaded = load_consumed_phase8b_permit(
        consumed.consumed_path,
        expected_permit_sha256=permit.permit_sha256,
        expected_request_sha256=permit.request_sha256,
        expected_runner_source_sha256=permit.runner_source_sha256,
        expected_payload_manifest_sha256=permit.payload_manifest_sha256,
    )
    revalidated = validate_exact_phase8b_authority(
        cast(Phase8BRequestLike, request),
        reloaded,
        output_root=output_root,
        attempt_id=attempt_id,
        expected_source_relative_paths=_RUNNER_SOURCE_RELATIVE_PATHS,
        require_output_absent=False,
    )
    if (
        reloaded != consumed
        or revalidated != authority
        or not _authority_matches_frozen_worker(
            request=request,
            consumed=reloaded,
            authority=revalidated,
            output_root=output_root,
            attempt_id=attempt_id,
        )
    ):
        raise ExecutionNotAuthorizedError(
            "worker compute authority differs from the revalidated consumed permit"
        )
    now_ns = time.monotonic_ns()
    maximum_deadline_ns = now_ns + int(request.timeout_seconds * 1_000_000_000)
    if absolute_deadline_ns <= now_ns or absolute_deadline_ns > maximum_deadline_ns:
        raise ExecutionNotAuthorizedError("worker compute deadline is expired or widened")
    if current_runner_source_sha256() != request.runner_source_sha256:
        raise ExecutionNotAuthorizedError("worker source identity drifted before capability issue")
    durable_claim = compute_claim_evidence.claim
    claim_authority = durable_claim.authority
    if (
        durable_claim.absolute_deadline_ns != absolute_deadline_ns
        or durable_claim.worker.pid != os.getpid()
        or claim_authority.permit_sha256 != revalidated.permit_sha256
        or claim_authority.request_sha256 != revalidated.request_sha256
        or claim_authority.runner_source_sha256 != revalidated.runner_source_sha256
        or claim_authority.payload_manifest_sha256 != revalidated.payload_manifest_sha256
        or claim_authority.protocol_sha256 != request.protocol_sha256
        or claim_authority.resources_sha256 != revalidated.resources_sha256
        or claim_authority.request_id != request.request_id
        or claim_authority.inchikey != request.inchikey
        or claim_authority.attempt_id != attempt_id
        or claim_authority.output_root != output_root
    ):
        raise ExecutionNotAuthorizedError("durable compute claim authority drifted")

    from nhc_deprot_ranker.quantum.worker_bootstrap import _claim_preimport_handshake_proof

    try:
        pid, _parent_pid, allowed_cpus, claim_hash = _claim_preimport_handshake_proof(
            bootstrap_proof,
            expected_absolute_deadline_ns=absolute_deadline_ns,
            expected_compute_claim_path=durable_claim.paths.compute_claim,
            expected_compute_claim_sha256=compute_claim_evidence.compute_claim_sha256,
        )
    except RuntimeError as exc:
        raise ExecutionNotAuthorizedError("worker pre-import handshake is not claimable") from exc
    if (
        pid != os.getpid()
        or allowed_cpus != frozenset({0, 1, 2, 3})
        or claim_hash != compute_claim_evidence.compute_claim_sha256
    ):
        raise ExecutionNotAuthorizedError("worker handshake binding drifted")
    capability = _Phase8BComputeCapability(
        seal=_COMPUTE_CAPABILITY_SEAL,
        pid=pid,
        absolute_deadline_ns=absolute_deadline_ns,
        authority=revalidated,
        protocol_sha256=request.protocol_sha256,
        compute_claim_sha256=claim_hash,
    )
    _LIVE_COMPUTE_CAPABILITIES[id(capability)] = (
        capability,
        _compute_capability_binding(capability),
    )
    return capability


def _validate_compute_capability_fields(capability: _Phase8BComputeCapability) -> None:
    if (
        capability._seal is not _COMPUTE_CAPABILITY_SEAL
        or capability._pid != os.getpid()
        or capability._absolute_deadline_ns <= time.monotonic_ns()
        or _SHA256_RE.fullmatch(capability._compute_claim_sha256) is None
        or capability._request_id != FROZEN_REQUEST_ID
        or capability._inchikey != FROZEN_INCHIKEY
        or capability._attempt_id != FROZEN_ATTEMPT_ID
        or capability._protocol_sha256 != FROZEN_PROTOCOL_SHA256
        or capability._electron_count != FROZEN_ELECTRON_COUNT
        or capability._endpoint_atom_map_sha256 != FROZEN_INPUT_SHA256["endpoint_atom_map"]
        or capability._legacy_atom_map_sha256 != FROZEN_INPUT_SHA256["legacy_atom_map"]
        or capability._geometry_validation_sha256 != PHASE7_GEOMETRY_VALIDATION_SHA256
        or capability._resources_sha256 != _frozen_resources_sha256()
    ):
        raise ExecutionNotAuthorizedError("worker compute capability identity drifted")


class PySCFBackend:
    """Lazy PySCF/geomeTRIC adapter for the unique locked protocol.

    Every method repeats the source-level authorization check.  Merely importing
    this module or constructing this adapter imports no compute dependency.
    """

    def __init__(self, capability: object) -> None:
        self._capability = capability
        self._modules: _PySCFModules | None = None

    def _claim_compute_capability(self) -> None:
        capability = self._capability
        if not isinstance(capability, _Phase8BComputeCapability):
            raise ExecutionNotAuthorizedError(
                "PySCF backend requires a bootstrap-issued Phase 8B compute capability"
            )
        _validate_compute_capability_fields(capability)
        registered = _LIVE_COMPUTE_CAPABILITIES.pop(id(capability), None)
        if (
            registered is None
            or registered[0] is not capability
            or registered[1] != _compute_capability_binding(capability)
            or capability._claimed
        ):
            raise ExecutionNotAuthorizedError("worker compute capability is forged or already used")
        capability._claimed = True
        capability._backend_owner = self

    def _validate_claimed_compute_capability(self) -> None:
        capability = self._capability
        if (
            not isinstance(capability, _Phase8BComputeCapability)
            or not capability._claimed
            or capability._backend_owner is not self
        ):
            raise ExecutionNotAuthorizedError("backend does not own a claimed compute capability")
        _validate_compute_capability_fields(capability)

    def _load_modules(self) -> _PySCFModules:
        _ensure_execution_authorized()
        if self._modules is not None:
            self._validate_claimed_compute_capability()
            if _configure_pyscf_threads(self._modules.lib) != self._modules.pyscf_threads:
                raise ResourceConfigurationError("cached PySCF thread state drifted")
            return self._modules
        self._claim_compute_capability()
        thread_environment = _validate_thread_environment(os.environ)
        capability = cast(_Phase8BComputeCapability, self._capability)
        if capability._runner_source_sha256 != current_runner_source_sha256():
            raise ExecutionNotAuthorizedError(
                "worker source identity drifted before compute import"
            )
        try:
            gto = importlib.import_module("pyscf.gto")
            dft = importlib.import_module("pyscf.dft")
            geometric_solver = importlib.import_module("pyscf.geomopt.geometric_solver")
            lib = importlib.import_module("pyscf.lib")
            dftd3 = importlib.import_module("pyscf.dispersion.dftd3")
            metadata = importlib.import_module("importlib.metadata")
        except ImportError as exc:
            raise BackendError("locked PySCF/geomeTRIC/D3(BJ) backend is unavailable") from exc
        except MemoryError as exc:
            raise ResourceLimitError("loading the compute backend exhausted memory") from exc
        try:
            adapter_version = str(metadata.version("pyscf-dispersion"))
        except Exception as exc:
            raise DispersionUnavailableError("pyscf-dispersion version is unavailable") from exc
        if adapter_version != PYSCF_DISPERSION_VERSION:
            raise DispersionUnavailableError(
                f"pyscf-dispersion must equal {PYSCF_DISPERSION_VERSION}"
            )
        modules = _PySCFModules(
            gto=gto,
            dft=dft,
            geometric_solver=geometric_solver,
            lib=lib,
            dftd3=dftd3,
            thread_environment=thread_environment,
            pyscf_threads=_configure_pyscf_threads(lib),
            adapter_version=adapter_version,
        )
        self._modules = modules
        return modules

    @staticmethod
    def _check_deadline(deadline_monotonic: float) -> None:
        if time.monotonic() >= deadline_monotonic:
            raise BackendTimeoutError("locked request deadline exceeded")

    @staticmethod
    def _d3bj_is_active(mean_field: Any) -> bool:
        """Accept PySCF versions whose ``do_disp`` returns bool or the D3 tag."""

        do_disp = getattr(mean_field, "do_disp", None)
        if not callable(do_disp):
            return False
        state = do_disp()
        if state is False or state is None:
            return False
        if isinstance(state, str):
            return state.lower() == "d3bj"
        return bool(state)

    @classmethod
    def _require_d3bj_active(cls, mean_field: Any, *, label: str) -> None:
        try:
            active = cls._d3bj_is_active(mean_field)
        except Exception as exc:
            raise DispersionUnavailableError(f"{label} D3(BJ) activation check failed") from exc
        if not active:
            raise DispersionUnavailableError(f"{label} did not retain active D3(BJ)")

    @classmethod
    def _require_exact_d3bj_owner(cls, owner: Any, *, label: str) -> None:
        if str(getattr(owner, "disp", "")).lower() != "d3bj":
            raise DispersionUnavailableError(f"{label} dropped mf.disp=d3bj")
        cls._require_d3bj_active(owner, label=label)

    @classmethod
    def _energy_owner(cls, owner: Any, *, strategy: SCFStrategy, label: str) -> Any:
        """Return the object whose energy_tot actually applies D3(BJ).

        PySCF Newton/SOSCF delegates energy evaluation to its inner ``_scf``
        object.  Observing the outer wrapper would miss the real hook and read
        the wrong ``scf_summary``.
        """

        cls._require_exact_d3bj_owner(owner, label=label)
        if strategy == "standard":
            return owner
        inner = getattr(owner, "_scf", None)
        if inner is None or inner is owner:
            raise DispersionUnavailableError(f"{label} SOSCF energy owner is unavailable")
        cls._require_exact_d3bj_owner(inner, label=f"{label} inner SCF")
        return inner

    @staticmethod
    def _geometry_from_molecule(molecule: Any) -> XYZGeometry:
        try:
            coordinates = molecule.atom_coords(unit="Angstrom")
            atoms = tuple(
                XYZAtom(
                    str(molecule.atom_symbol(index)),
                    float(coordinates[index][0]),
                    float(coordinates[index][1]),
                    float(coordinates[index][2]),
                )
                for index in range(int(molecule.natm))
            )
        except Exception as exc:  # pragma: no cover - requires compute environment
            raise BackendError("PySCF returned an unreadable optimized geometry") from exc
        geometry = XYZGeometry(atoms)
        _validate_backend_geometry(geometry)
        return geometry

    def _mean_field(
        self,
        *,
        geometry: XYZGeometry,
        charge: int,
        multiplicity: int,
        strategy: SCFStrategy,
    ) -> tuple[Any, RuntimeEvidence, _PySCFModules]:
        modules = self._load_modules()
        if multiplicity != 1 or charge not in {0, 1}:
            raise BackendError("backend received a forbidden charge or multiplicity")
        electron_count = _electron_count_for_geometry(geometry, charge=charge)
        if electron_count % 2 != 0:
            raise BackendError("backend received an odd-electron locked singlet")
        atom_spec = [(atom.element, (atom.x, atom.y, atom.z)) for atom in geometry.atoms]
        try:
            molecule = modules.gto.M(
                atom=atom_spec,
                unit="Angstrom",
                basis="def2-svp",
                charge=charge,
                spin=0,
                max_memory=PYSCF_MAX_MEMORY_MB,
                verbose=0,
            )
            molecule_symbols = tuple(
                str(molecule.atom_symbol(index)) for index in range(int(molecule.natm))
            )
            if molecule_symbols != tuple(atom.element for atom in geometry.atoms):
                raise BackendError("PySCF molecule changed atom count or ordering")
            if int(getattr(molecule, "nelectron", -1)) != electron_count:
                raise BackendError("PySCF molecule electron count drifted")
            if type(getattr(molecule, "charge", None)) is not int or molecule.charge != charge:
                raise BackendError("PySCF molecule did not retain the exact charge")
            if int(getattr(molecule, "spin", -1)) != 0:
                raise BackendError("PySCF molecule did not retain spin=0")
            mean_field = modules.dft.RKS(molecule)
            mean_field.xc = "B3LYP"
            mean_field.grids.level = 3
            mean_field.conv_tol = 1.0e-9
            mean_field.max_cycle = 100 if strategy == "standard" else 200
            mean_field.disp = "d3bj"
            self._require_exact_d3bj_owner(mean_field, label="standard mean field")
            if strategy == "soscf":
                mean_field = mean_field.newton()
                mean_field.max_cycle = 200
                self._energy_owner(mean_field, strategy=strategy, label="SOSCF mean field")
            runtime = _runtime_evidence(
                modules=modules,
                molecule=molecule,
                mean_field=mean_field,
                electron_count=electron_count,
                charge=charge,
            )
        except (BackendError, TwoEndpointError):
            raise
        except MemoryError as exc:
            raise ResourceLimitError("failed to construct mean field within memory limit") from exc
        except Exception as exc:  # pragma: no cover - requires compute environment
            raise BackendUnknownError("failed to construct the locked mean field") from exc
        return mean_field, runtime, modules

    def optimize(
        self,
        *,
        endpoint: EndpointName,
        geometry: XYZGeometry,
        charge: int,
        multiplicity: int,
        strategy: SCFStrategy,
        deadline_monotonic: float,
    ) -> BackendOptimizationResult:
        del endpoint
        self._check_deadline(deadline_monotonic)
        mean_field, configured_runtime, modules = self._mean_field(
            geometry=geometry,
            charge=charge,
            multiplicity=multiplicity,
            strategy=strategy,
        )
        recorder = _D3HookRecorder(natm=len(geometry.atoms))
        try:
            gradient_scanner = mean_field.nuc_grad_method().as_scanner()
            scanner_energy_owner = self._energy_owner(
                gradient_scanner.base,
                strategy=strategy,
                label="optimization scanner",
            )
            _install_dispersion_observer(
                scanner_energy_owner,
                kind="energy",
                recorder=recorder,
            )
            _install_dispersion_observer(
                gradient_scanner,
                kind="gradient",
                recorder=recorder,
            )

            def convergence_callback(environment: Mapping[str, object]) -> None:
                scanner = environment.get("g_scanner")
                if scanner is not gradient_scanner:
                    raise BackendUnknownError("geomeTRIC callback scanner identity drifted")
                _require_explicit_scf_convergence(
                    getattr(scanner, "converged", None),
                    label=f"{strategy} SCF during geomeTRIC optimization",
                )

            geometry_converged, optimized_molecule = modules.geometric_solver.kernel(
                gradient_scanner,
                assert_convergence=True,
                maxsteps=100,
                callback=convergence_callback,
            )
        except BackendError:
            raise
        except MemoryError as exc:
            raise ResourceLimitError("geomeTRIC optimization exhausted memory") from exc
        except Exception as exc:  # pragma: no cover - requires compute environment
            raise BackendUnknownError(
                "geomeTRIC optimization raised an unclassified error"
            ) from exc
        self._check_deadline(deadline_monotonic)
        _require_explicit_geometry_convergence(
            geometry_converged,
            label="geomeTRIC optimization",
        )
        _require_explicit_scf_convergence(
            getattr(gradient_scanner, "converged", None),
            label=f"last {strategy} optimization SCF",
        )
        last_energy = float(getattr(gradient_scanner, "e_tot", math.nan))
        if not math.isfinite(last_energy):
            raise BackendError("optimization returned a non-finite energy")
        if recorder.energy_hook_calls <= 0 or recorder.gradient_hook_calls <= 0:
            raise DispersionEvaluationError("optimization did not exercise both D3(BJ) hooks")
        retained_scanner_energy_owner = self._energy_owner(
            gradient_scanner.base,
            strategy=strategy,
            label="retained optimization scanner",
        )
        if retained_scanner_energy_owner is not scanner_energy_owner:
            raise DispersionUnavailableError("optimization scanner energy owner identity drifted")
        optimized_geometry = self._geometry_from_molecule(optimized_molecule)
        retained_runtime = _retained_runtime_evidence(
            modules=modules,
            molecules=(optimized_molecule,),
            mean_fields=(mean_field, gradient_scanner.base, scanner_energy_owner),
            expected_electron_count=configured_runtime.electron_count,
            expected_charge=charge,
        )
        self._check_deadline(deadline_monotonic)
        return BackendOptimizationResult(
            geometry=optimized_geometry,
            geometry_converged=True,
            scf_converged=True,
            last_energy_hartree=last_energy,
            runtime=retained_runtime,
            dispersion=OptimizationD3Evidence(
                tag="d3bj",
                energy_hook_calls=recorder.energy_hook_calls,
                gradient_hook_calls=recorder.gradient_hook_calls,
                gradient_shape=(len(geometry.atoms), 3),
                energy_values_finite=True,
                gradient_values_finite=True,
            ),
        )

    def final_scf(
        self,
        *,
        endpoint: EndpointName,
        geometry: XYZGeometry,
        charge: int,
        multiplicity: int,
        strategy: SCFStrategy,
        deadline_monotonic: float,
    ) -> BackendSCFResult:
        del endpoint
        self._check_deadline(deadline_monotonic)
        mean_field, configured_runtime, modules = self._mean_field(
            geometry=geometry,
            charge=charge,
            multiplicity=multiplicity,
            strategy=strategy,
        )
        recorder = _D3HookRecorder(natm=len(geometry.atoms))
        energy_owner = self._energy_owner(
            mean_field,
            strategy=strategy,
            label="final SCF",
        )
        _install_dispersion_observer(energy_owner, kind="energy", recorder=recorder)
        if "dispersion" in getattr(energy_owner, "scf_summary", {}):
            raise DispersionEvaluationError("fresh final SCF already cached a dispersion energy")
        try:
            energy = float(mean_field.kernel())
        except BackendError:
            raise
        except MemoryError as exc:
            raise ResourceLimitError("final same-method SCF exhausted memory") from exc
        except Exception as exc:  # pragma: no cover - requires compute environment
            raise BackendUnknownError("final same-method SCF raised an unclassified error") from exc
        self._check_deadline(deadline_monotonic)
        _require_explicit_scf_convergence(
            getattr(mean_field, "converged", None),
            label="final same-method SCF",
        )
        if not math.isfinite(energy):
            raise BackendError("final electronic energy is non-finite")
        if recorder.energy_hook_calls <= 0:
            raise DispersionEvaluationError("final SCF did not exercise the D3(BJ) energy hook")
        retained_energy_owner = self._energy_owner(
            mean_field,
            strategy=strategy,
            label="retained final SCF",
        )
        if retained_energy_owner is not energy_owner:
            raise DispersionUnavailableError("final SCF energy owner identity drifted")
        summary = getattr(energy_owner, "scf_summary", None)
        if not isinstance(summary, Mapping):
            raise DispersionEvaluationError("final SCF summary is unavailable")
        components: dict[str, float] = {}
        for key in ("nuc", "e1", "coul", "exc", "dispersion"):
            try:
                value = float(summary[key])
            except (KeyError, TypeError, ValueError) as exc:
                raise DispersionEvaluationError(
                    f"final SCF summary component is invalid: {key}"
                ) from exc
            if not math.isfinite(value):
                raise DispersionEvaluationError(f"final SCF summary component is non-finite: {key}")
            components[key] = value
        if components["dispersion"] == 0.0:
            raise DispersionEvaluationError("final D3(BJ) summary energy is zero")
        reconstructed = sum(components.values())
        arithmetic_error = abs(reconstructed - energy)
        if arithmetic_error > 1.0e-12:
            raise DispersionEvaluationError("final SCF summary does not reconstruct the total")
        _retained_runtime_evidence(
            modules=modules,
            molecules=(energy_owner.mol,),
            mean_fields=(mean_field, energy_owner),
            expected_electron_count=configured_runtime.electron_count,
            expected_charge=charge,
        )
        try:
            adapter = modules.dftd3.DFTD3Dispersion(
                energy_owner.mol,
                xc="B3LYP",
                version="d3bj",
                atm=False,
            )
            audit = adapter.get_dispersion(grad=True)
        except MemoryError as exc:
            raise ResourceLimitError("zero-SCF D3(BJ) audit exhausted memory") from exc
        except Exception as exc:
            raise DispersionEvaluationError("zero-SCF D3(BJ) audit raised an error") from exc
        self._check_deadline(deadline_monotonic)
        if not isinstance(audit, Mapping):
            raise DispersionEvaluationError("zero-SCF D3(BJ) audit returned no mapping")
        audit_energy = _finite_nonzero_float(
            audit.get("energy"), label="zero-SCF D3(BJ) audit energy"
        )
        audit_shape = _validate_finite_gradient(
            audit.get("gradient"),
            natm=len(geometry.atoms),
            label="zero-SCF D3(BJ) audit gradient",
        )
        audit_error = abs(audit_energy - components["dispersion"])
        if audit_error > 1.0e-12:
            raise DispersionEvaluationError("zero-SCF D3(BJ) audit disagrees with SCF summary")
        retained_energy_owner = self._energy_owner(
            mean_field,
            strategy=strategy,
            label="post-audit final SCF",
        )
        if retained_energy_owner is not energy_owner:
            raise DispersionUnavailableError("final SCF energy owner identity drifted after audit")
        retained_runtime = _retained_runtime_evidence(
            modules=modules,
            molecules=(energy_owner.mol,),
            mean_fields=(mean_field, energy_owner),
            expected_electron_count=configured_runtime.electron_count,
            expected_charge=charge,
        )
        self._check_deadline(deadline_monotonic)
        breakdown = FinalEnergyBreakdown(
            nuclear_hartree=components["nuc"],
            one_electron_hartree=components["e1"],
            coulomb_hartree=components["coul"],
            exchange_correlation_hartree=components["exc"],
            dispersion_hartree=components["dispersion"],
            reconstructed_hartree=reconstructed,
            total_hartree=energy,
            absolute_error_hartree=arithmetic_error,
        )
        return BackendSCFResult(
            converged=True,
            energy_hartree=energy,
            runtime=retained_runtime,
            dispersion=FinalD3Evidence(
                tag="d3bj",
                energy_hook_calls=recorder.energy_hook_calls,
                breakdown=breakdown,
                audit_calls=1,
                audit_energy_hartree=audit_energy,
                audit_gradient_shape=audit_shape,
                audit_gradient_finite=True,
                audit_absolute_error_hartree=audit_error,
                adapter_version=modules.adapter_version,
            ),
        )


def _validate_backend_geometry(geometry: XYZGeometry) -> None:
    if not isinstance(geometry, XYZGeometry) or not geometry.atoms:
        raise BackendError("backend returned an invalid geometry object")
    for atom in geometry.atoms:
        if atom.element not in _ELEMENTS:
            raise BackendError("backend changed an atom into an unknown element")
        if not all(math.isfinite(value) for value in (atom.x, atom.y, atom.z)):
            raise BackendError("backend returned non-finite coordinates")
        if any(abs(value) > _MAX_ABS_COORDINATE_ANGSTROM for value in (atom.x, atom.y, atom.z)):
            raise BackendError("backend returned unbounded coordinates")


def _validate_runtime_evidence(evidence: object, *, expected_electron_count: int) -> None:
    if not isinstance(evidence, RuntimeEvidence):
        raise ResourceConfigurationError("backend omitted typed runtime evidence")
    if (
        evidence.compute_threads != COMPUTE_THREADS
        or evidence.thread_environment != _CANONICAL_THREAD_ENVIRONMENT
        or evidence.pyscf_threads != COMPUTE_THREADS
        or evidence.molecule_max_memory_mb != PYSCF_MAX_MEMORY_MB
        or evidence.mean_field_max_memory_mb != PYSCF_MAX_MEMORY_MB
        or evidence.electron_count != expected_electron_count
    ):
        raise ResourceConfigurationError("backend runtime evidence drifted")


def _validate_optimization_dispersion(evidence: object, *, expected_atoms: int) -> None:
    if not isinstance(evidence, OptimizationD3Evidence):
        raise DispersionEvaluationError("backend omitted optimization D3(BJ) evidence")
    if (
        evidence.tag != "d3bj"
        or type(evidence.energy_hook_calls) is not int
        or evidence.energy_hook_calls <= 0
        or type(evidence.gradient_hook_calls) is not int
        or evidence.gradient_hook_calls <= 0
        or evidence.gradient_shape != (expected_atoms, 3)
        or evidence.energy_values_finite is not True
        or evidence.gradient_values_finite is not True
    ):
        raise DispersionEvaluationError("optimization D3(BJ) evidence drifted")


def _validate_final_dispersion(
    evidence: object, *, expected_atoms: int, total_energy: float
) -> None:
    if not isinstance(evidence, FinalD3Evidence):
        raise DispersionEvaluationError("backend omitted final D3(BJ) evidence")
    if (
        evidence.tag != "d3bj"
        or type(evidence.energy_hook_calls) is not int
        or evidence.energy_hook_calls <= 0
        or type(evidence.audit_calls) is not int
        or evidence.audit_calls != 1
        or evidence.audit_gradient_shape != (expected_atoms, 3)
        or evidence.audit_gradient_finite is not True
        or evidence.adapter_version != PYSCF_DISPERSION_VERSION
    ):
        raise DispersionEvaluationError("final D3(BJ) evidence drifted")
    breakdown = evidence.breakdown
    if not isinstance(breakdown, FinalEnergyBreakdown):
        raise DispersionEvaluationError("final D3(BJ) breakdown is untyped")
    components = (
        breakdown.nuclear_hartree,
        breakdown.one_electron_hartree,
        breakdown.coulomb_hartree,
        breakdown.exchange_correlation_hartree,
        breakdown.dispersion_hartree,
    )
    numeric = (
        *components,
        breakdown.reconstructed_hartree,
        breakdown.total_hartree,
        breakdown.absolute_error_hartree,
        evidence.audit_energy_hartree,
        evidence.audit_absolute_error_hartree,
    )
    if not all(type(value) in {int, float} and math.isfinite(value) for value in numeric):
        raise DispersionEvaluationError("final D3(BJ) evidence contains non-finite values")
    reconstructed = sum(components)
    arithmetic_error = abs(reconstructed - total_energy)
    audit_error = abs(evidence.audit_energy_hartree - breakdown.dispersion_hartree)
    if breakdown.dispersion_hartree == 0.0 or evidence.audit_energy_hartree == 0.0:
        raise DispersionEvaluationError("final D3(BJ) energy evidence is zero")
    if (
        not math.isclose(
            breakdown.reconstructed_hartree, reconstructed, rel_tol=0.0, abs_tol=1.0e-15
        )
        or not math.isclose(breakdown.total_hartree, total_energy, rel_tol=0.0, abs_tol=1.0e-15)
        or not math.isclose(
            breakdown.absolute_error_hartree,
            arithmetic_error,
            rel_tol=0.0,
            abs_tol=1.0e-15,
        )
        or not math.isclose(
            evidence.audit_absolute_error_hartree,
            audit_error,
            rel_tol=0.0,
            abs_tol=1.0e-15,
        )
        or arithmetic_error > 1.0e-12
        or audit_error > 1.0e-12
    ):
        raise DispersionEvaluationError("final D3(BJ) arithmetic evidence drifted")


def _validate_optimization(
    result: BackendOptimizationResult,
    *,
    original: XYZGeometry,
    expected_electron_count: int,
) -> None:
    if not isinstance(result, BackendOptimizationResult):
        raise BackendError("backend returned the wrong optimization result type")
    _require_explicit_geometry_convergence(
        result.geometry_converged,
        label="backend geomeTRIC optimization",
    )
    _require_explicit_scf_convergence(
        result.scf_converged,
        label="backend optimization SCF",
    )
    if not math.isfinite(result.last_energy_hartree):
        raise BackendError("optimization energy is non-finite")
    _validate_backend_geometry(result.geometry)
    if tuple(atom.element for atom in result.geometry.atoms) != tuple(
        atom.element for atom in original.atoms
    ):
        raise BackendError("optimization changed atom count or ordering")
    _validate_runtime_evidence(result.runtime, expected_electron_count=expected_electron_count)
    _validate_optimization_dispersion(result.dispersion, expected_atoms=len(original.atoms))


def _validate_scf(
    result: BackendSCFResult,
    *,
    expected_atoms: int,
    expected_electron_count: int,
) -> None:
    if not isinstance(result, BackendSCFResult):
        raise BackendError("backend returned the wrong SCF result type")
    _require_explicit_scf_convergence(
        result.converged,
        label="backend final same-method SCF",
    )
    if not math.isfinite(result.energy_hartree):
        raise BackendError("final electronic energy is non-finite")
    _validate_runtime_evidence(result.runtime, expected_electron_count=expected_electron_count)
    _validate_final_dispersion(
        result.dispersion,
        expected_atoms=expected_atoms,
        total_energy=result.energy_hartree,
    )


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISDIR(observed.st_mode):
            raise OSError(f"directory fsync target is not a directory: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _durably_move_attempt(source: Path, destination: Path, *, attempts_root: Path) -> None:
    if destination.parent != attempts_root:
        raise ResumeValidationError("attempt publication escaped the attempts root")
    os.replace(source, destination)
    _fsync_directory(destination)
    _fsync_directory(attempts_root)


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, _PRIVATE_FILE_MODE)
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != _PRIVATE_FILE_MODE
            or observed.st_uid != os.geteuid()
            or observed.st_nlink != 1
        ):
            raise OSError("atomic temporary file identity or mode drifted")
        stream = os.fdopen(descriptor, "wb")
        descriptor = -1
        with stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        if descriptor >= 0:
            with suppress(OSError):
                os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


def _atomic_write_json(path: Path, payload: object) -> None:
    _atomic_write_bytes(path, _canonical_json_bytes(payload))


def _validate_output_root(output_root: Path) -> None:
    if output_root.is_symlink():
        raise ResumeValidationError("output root must not be a symlink")
    parent = output_root.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ResumeValidationError("output parent must be an existing real directory")
    if output_root.exists() and not output_root.is_dir():
        raise ResumeValidationError("output root exists but is not a directory")


def _identity(request: TwoEndpointRequest) -> dict[str, object]:
    return {
        "request_sha256": request.request_sha256,
        "protocol_sha256": request.protocol_sha256,
        "runner_source_sha256": request.runner_source_sha256,
        "input_sha256": {
            "cation": request.cation.xyz_sha256,
            "neutral": request.neutral.xyz_sha256,
        },
    }


def _relative_attempt_path(attempt_id: str, name: str) -> str:
    return f"attempts/{attempt_id}/{name}"


def _safe_attempt_id(attempt_id: str | None) -> str:
    value = attempt_id or f"attempt-{uuid.uuid4().hex}"
    if _ATTEMPT_ID_RE.fullmatch(value) is None:
        raise RequestValidationError("attempt_id is not a safe identifier")
    return value


def _deadline_check(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise BackendTimeoutError("locked request deadline exceeded")


def _resolve_request_deadline(
    request: TwoEndpointRequest, absolute_deadline_monotonic: float | None
) -> float:
    """Choose one deadline without allowing a caller to extend the request."""

    started_monotonic = time.monotonic()
    if absolute_deadline_monotonic is None:
        return started_monotonic + request.timeout_seconds
    if (
        type(absolute_deadline_monotonic) not in {int, float}
        or not math.isfinite(absolute_deadline_monotonic)
        or absolute_deadline_monotonic <= started_monotonic
    ):
        raise BackendTimeoutError("absolute request deadline is invalid or expired")
    if absolute_deadline_monotonic > started_monotonic + request.timeout_seconds:
        raise ResourceConfigurationError("absolute request deadline would extend wall-time")
    return float(absolute_deadline_monotonic)


def _call_optimize(
    *,
    backend: TwoEndpointBackend,
    endpoint: EndpointRequest,
    strategy: SCFStrategy,
    deadline: float,
) -> BackendOptimizationResult:
    _deadline_check(deadline)
    result = backend.optimize(
        endpoint=endpoint.name,
        geometry=endpoint.geometry,
        charge=endpoint.charge,
        multiplicity=endpoint.multiplicity,
        strategy=strategy,
        deadline_monotonic=deadline,
    )
    _deadline_check(deadline)
    _validate_optimization(
        result,
        original=endpoint.geometry,
        expected_electron_count=endpoint.electron_count,
    )
    return result


def _call_scf(
    *,
    backend: TwoEndpointBackend,
    endpoint: EndpointRequest,
    geometry: XYZGeometry,
    strategy: SCFStrategy,
    deadline: float,
) -> BackendSCFResult:
    _deadline_check(deadline)
    result = backend.final_scf(
        endpoint=endpoint.name,
        geometry=geometry,
        charge=endpoint.charge,
        multiplicity=endpoint.multiplicity,
        strategy=strategy,
        deadline_monotonic=deadline,
    )
    _deadline_check(deadline)
    _validate_scf(
        result,
        expected_atoms=len(geometry.atoms),
        expected_electron_count=endpoint.electron_count,
    )
    return result


def _runtime_evidence_payload(evidence: RuntimeEvidence) -> dict[str, object]:
    return {
        "compute_threads": evidence.compute_threads,
        "thread_environment": dict(evidence.thread_environment),
        "pyscf_threads": evidence.pyscf_threads,
        "molecule_max_memory_mb": evidence.molecule_max_memory_mb,
        "mean_field_max_memory_mb": evidence.mean_field_max_memory_mb,
        "electron_count": evidence.electron_count,
    }


def _optimization_dispersion_payload(evidence: OptimizationD3Evidence) -> dict[str, object]:
    return {
        "tag": evidence.tag,
        "energy_hook_calls": evidence.energy_hook_calls,
        "gradient_hook_calls": evidence.gradient_hook_calls,
        "gradient_shape": list(evidence.gradient_shape),
        "energy_values_finite": evidence.energy_values_finite,
        "gradient_values_finite": evidence.gradient_values_finite,
    }


def _final_dispersion_payload(evidence: FinalD3Evidence) -> dict[str, object]:
    breakdown = evidence.breakdown
    return {
        "tag": evidence.tag,
        "energy_hook_calls": evidence.energy_hook_calls,
        "breakdown": {
            "nuclear_hartree": breakdown.nuclear_hartree,
            "one_electron_hartree": breakdown.one_electron_hartree,
            "coulomb_hartree": breakdown.coulomb_hartree,
            "exchange_correlation_hartree": breakdown.exchange_correlation_hartree,
            "dispersion_hartree": breakdown.dispersion_hartree,
            "reconstructed_hartree": breakdown.reconstructed_hartree,
            "total_hartree": breakdown.total_hartree,
            "absolute_error_hartree": breakdown.absolute_error_hartree,
        },
        "audit_calls": evidence.audit_calls,
        "audit_energy_hartree": evidence.audit_energy_hartree,
        "audit_gradient_shape": list(evidence.audit_gradient_shape),
        "audit_gradient_finite": evidence.audit_gradient_finite,
        "audit_absolute_error_hartree": evidence.audit_absolute_error_hartree,
        "adapter_version": evidence.adapter_version,
    }


def _run_endpoint(
    *, backend: TwoEndpointBackend, endpoint: EndpointRequest, deadline: float
) -> tuple[BackendOptimizationResult, BackendSCFResult, dict[str, object]]:
    optimization_attempts: list[dict[str, object]] = []
    optimization_strategy: SCFStrategy = "standard"
    try:
        optimization = _call_optimize(
            backend=backend, endpoint=endpoint, strategy="standard", deadline=deadline
        )
        optimization_attempts.append({"strategy": "standard", "converged": True})
    except SCFNotConvergedError:
        optimization_attempts.append(
            {
                "strategy": "standard",
                "converged": False,
                "failure_kind": "scf_not_converged",
            }
        )
        optimization_strategy = "soscf"
        optimization = _call_optimize(
            backend=backend, endpoint=endpoint, strategy="soscf", deadline=deadline
        )
        optimization_attempts.append({"strategy": "soscf", "converged": True})

    scf_attempts: list[dict[str, object]] = []
    final_scf_strategy = optimization_strategy
    try:
        final_scf = _call_scf(
            backend=backend,
            endpoint=endpoint,
            geometry=optimization.geometry,
            strategy=final_scf_strategy,
            deadline=deadline,
        )
        scf_attempts.append({"strategy": final_scf_strategy, "converged": True})
    except SCFNotConvergedError:
        if final_scf_strategy == "soscf":
            raise
        scf_attempts.append(
            {
                "strategy": "standard",
                "converged": False,
                "failure_kind": "scf_not_converged",
            }
        )
        final_scf_strategy = "soscf"
        final_scf = _call_scf(
            backend=backend,
            endpoint=endpoint,
            geometry=optimization.geometry,
            strategy="soscf",
            deadline=deadline,
        )
        scf_attempts.append({"strategy": "soscf", "converged": True})

    if optimization_strategy == "soscf":
        soscf_stage: str | None = "optimization"
    elif final_scf_strategy == "soscf":
        soscf_stage = "final_scf"
    else:
        soscf_stage = None
    record: dict[str, object] = {
        "charge": endpoint.charge,
        "multiplicity": endpoint.multiplicity,
        "electron_count": endpoint.electron_count,
        "input_xyz_path": endpoint.xyz_relative_path,
        "input_xyz_sha256": endpoint.xyz_sha256,
        "retry": {
            "soscf_budget": 1,
            "soscf_consumed": soscf_stage is not None,
            "soscf_stage": soscf_stage,
        },
        "optimization": {
            "optimizer": "geomeTRIC",
            "geometry_converged": True,
            "scf_converged": True,
            "selected_strategy": optimization_strategy,
            "last_energy_hartree": optimization.last_energy_hartree,
            "attempts": optimization_attempts,
            "runtime": _runtime_evidence_payload(optimization.runtime),
            "dispersion": _optimization_dispersion_payload(optimization.dispersion),
        },
        "final_scf": {
            "converged": True,
            "selected_strategy": final_scf_strategy,
            "energy_hartree": final_scf.energy_hartree,
            "attempts": scf_attempts,
            "runtime": _runtime_evidence_payload(final_scf.runtime),
            "dispersion": _final_dispersion_payload(final_scf.dispersion),
        },
    }
    return optimization, final_scf, record


def _success_flags() -> dict[str, object]:
    return {
        "hessian_computed": False,
        "frequency_status": "not_computed",
        "n_imaginary": None,
        "extra_single_points_computed": False,
        "radical_computed": False,
        "molden_written": False,
        "label_quality": "electronic_energy_only",
    }


def _read_json_object(path: Path, *, error_cls: type[TwoEndpointError]) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise error_cls(f"required state file is missing or unsafe: {path.name}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise error_cls(f"state file is unreadable: {path.name}") from exc
    return _strict_json_object(raw, label=path.name, error_cls=error_cls)


def _resume_finite_number(value: object, *, label: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(cast(float, value)):
        raise ResumeValidationError(f"{label} must be finite")
    return float(cast(float, value))


def _resume_shape(value: object, *, label: str) -> tuple[int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(part) is not int for part in value)
    ):
        raise ResumeValidationError(f"{label} shape drifted")
    return int(value[0]), int(value[1])


def _parse_runtime_evidence(payload: object, *, label: str) -> RuntimeEvidence:
    if not isinstance(payload, dict):
        raise ResumeValidationError(f"{label} runtime evidence is not an object")
    typed = cast(dict[str, object], payload)
    _require_resume_keys(
        typed,
        {
            "compute_threads",
            "thread_environment",
            "pyscf_threads",
            "molecule_max_memory_mb",
            "mean_field_max_memory_mb",
            "electron_count",
        },
        f"{label} runtime evidence",
    )
    thread_environment = typed["thread_environment"]
    if not isinstance(thread_environment, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in thread_environment.items()
    ):
        raise ResumeValidationError(f"{label} thread environment drifted")
    integer_fields = (
        "compute_threads",
        "pyscf_threads",
        "molecule_max_memory_mb",
        "mean_field_max_memory_mb",
        "electron_count",
    )
    if any(type(typed[field]) is not int for field in integer_fields):
        raise ResumeValidationError(f"{label} runtime integer fields drifted")
    return RuntimeEvidence(
        compute_threads=cast(int, typed["compute_threads"]),
        thread_environment=tuple(sorted(cast(dict[str, str], thread_environment).items())),
        pyscf_threads=cast(int, typed["pyscf_threads"]),
        molecule_max_memory_mb=cast(int, typed["molecule_max_memory_mb"]),
        mean_field_max_memory_mb=cast(int, typed["mean_field_max_memory_mb"]),
        electron_count=cast(int, typed["electron_count"]),
    )


def _parse_optimization_dispersion(payload: object, *, label: str) -> OptimizationD3Evidence:
    if not isinstance(payload, dict):
        raise ResumeValidationError(f"{label} optimization dispersion is not an object")
    typed = cast(dict[str, object], payload)
    _require_resume_keys(
        typed,
        {
            "tag",
            "energy_hook_calls",
            "gradient_hook_calls",
            "gradient_shape",
            "energy_values_finite",
            "gradient_values_finite",
        },
        f"{label} optimization dispersion",
    )
    if type(typed["energy_hook_calls"]) is not int or type(typed["gradient_hook_calls"]) is not int:
        raise ResumeValidationError(f"{label} optimization hook counts drifted")
    return OptimizationD3Evidence(
        tag=str(typed["tag"]),
        energy_hook_calls=typed["energy_hook_calls"],
        gradient_hook_calls=typed["gradient_hook_calls"],
        gradient_shape=_resume_shape(
            typed["gradient_shape"], label=f"{label} optimization gradient"
        ),
        energy_values_finite=typed["energy_values_finite"] is True,
        gradient_values_finite=typed["gradient_values_finite"] is True,
    )


def _parse_final_dispersion(payload: object, *, label: str) -> FinalD3Evidence:
    if not isinstance(payload, dict):
        raise ResumeValidationError(f"{label} final dispersion is not an object")
    typed = cast(dict[str, object], payload)
    _require_resume_keys(
        typed,
        {
            "tag",
            "energy_hook_calls",
            "breakdown",
            "audit_calls",
            "audit_energy_hartree",
            "audit_gradient_shape",
            "audit_gradient_finite",
            "audit_absolute_error_hartree",
            "adapter_version",
        },
        f"{label} final dispersion",
    )
    breakdown_raw = typed["breakdown"]
    if not isinstance(breakdown_raw, dict):
        raise ResumeValidationError(f"{label} final breakdown is not an object")
    breakdown_payload = cast(dict[str, object], breakdown_raw)
    breakdown_fields = {
        "nuclear_hartree",
        "one_electron_hartree",
        "coulomb_hartree",
        "exchange_correlation_hartree",
        "dispersion_hartree",
        "reconstructed_hartree",
        "total_hartree",
        "absolute_error_hartree",
    }
    _require_resume_keys(breakdown_payload, breakdown_fields, f"{label} final breakdown")
    breakdown_values = {
        field: _resume_finite_number(
            breakdown_payload[field], label=f"{label} final breakdown {field}"
        )
        for field in breakdown_fields
    }
    if type(typed["energy_hook_calls"]) is not int or type(typed["audit_calls"]) is not int:
        raise ResumeValidationError(f"{label} final D3(BJ) call counts drifted")
    return FinalD3Evidence(
        tag=str(typed["tag"]),
        energy_hook_calls=typed["energy_hook_calls"],
        breakdown=FinalEnergyBreakdown(
            nuclear_hartree=breakdown_values["nuclear_hartree"],
            one_electron_hartree=breakdown_values["one_electron_hartree"],
            coulomb_hartree=breakdown_values["coulomb_hartree"],
            exchange_correlation_hartree=breakdown_values["exchange_correlation_hartree"],
            dispersion_hartree=breakdown_values["dispersion_hartree"],
            reconstructed_hartree=breakdown_values["reconstructed_hartree"],
            total_hartree=breakdown_values["total_hartree"],
            absolute_error_hartree=breakdown_values["absolute_error_hartree"],
        ),
        audit_calls=typed["audit_calls"],
        audit_energy_hartree=_resume_finite_number(
            typed["audit_energy_hartree"], label=f"{label} audit energy"
        ),
        audit_gradient_shape=_resume_shape(
            typed["audit_gradient_shape"], label=f"{label} audit gradient"
        ),
        audit_gradient_finite=typed["audit_gradient_finite"] is True,
        audit_absolute_error_hartree=_resume_finite_number(
            typed["audit_absolute_error_hartree"], label=f"{label} audit error"
        ),
        adapter_version=str(typed["adapter_version"]),
    )


def _validate_recorded_attempts(attempts: object, *, selected_strategy: object, label: str) -> None:
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= 2:
        raise ResumeValidationError(f"{label} attempt list drifted")
    normalized: list[tuple[object, object, object]] = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise ResumeValidationError(f"{label} attempt is not an object")
        expected = {"strategy", "converged"}
        if attempt.get("converged") is False:
            expected.add("failure_kind")
        if set(attempt) != expected:
            raise ResumeValidationError(f"{label} attempt fields drifted")
        strategy = attempt.get("strategy")
        converged = attempt.get("converged")
        failure_kind = attempt.get("failure_kind")
        if strategy not in {"standard", "soscf"} or type(converged) is not bool:
            raise ResumeValidationError(f"{label} attempt values drifted")
        if converged is False and failure_kind != "scf_not_converged":
            raise ResumeValidationError(f"{label} failure kind drifted")
        normalized.append((strategy, converged, failure_kind))
    if len(normalized) == 1:
        if normalized[0][1] is not True:
            raise ResumeValidationError(f"{label} single attempt was not converged")
    elif normalized != [("standard", False, "scf_not_converged"), ("soscf", True, None)]:
        raise ResumeValidationError(f"{label} retry sequence drifted")
    if normalized[-1][0] != selected_strategy:
        raise ResumeValidationError(f"{label} selected strategy drifted")


def _validate_endpoint_record(
    record: object, *, endpoint: EndpointRequest
) -> tuple[dict[str, object], float]:
    if not isinstance(record, dict):
        raise ResumeValidationError(f"{endpoint.name} result record is not an object")
    typed = cast(dict[str, object], record)
    if set(typed) != {
        "charge",
        "multiplicity",
        "electron_count",
        "input_xyz_path",
        "input_xyz_sha256",
        "retry",
        "optimization",
        "final_scf",
        "optimized_xyz_sha256",
    }:
        raise ResumeValidationError(f"{endpoint.name} result fields drifted")
    if (
        typed["charge"] != endpoint.charge
        or typed["multiplicity"] != endpoint.multiplicity
        or typed["electron_count"] != endpoint.electron_count
        or typed["input_xyz_path"] != endpoint.xyz_relative_path
        or typed["input_xyz_sha256"] != endpoint.xyz_sha256
    ):
        raise ResumeValidationError(f"{endpoint.name} input identity drifted")
    if (
        not isinstance(typed["optimized_xyz_sha256"], str)
        or _SHA256_RE.fullmatch(typed["optimized_xyz_sha256"]) is None
    ):
        raise ResumeValidationError(f"{endpoint.name} optimized XYZ hash is invalid")
    optimization = typed["optimization"]
    final_scf = typed["final_scf"]
    retry = typed["retry"]
    if not isinstance(retry, dict) or set(retry) != {
        "soscf_budget",
        "soscf_consumed",
        "soscf_stage",
    }:
        raise ResumeValidationError(f"{endpoint.name} retry schema drifted")
    if (
        retry["soscf_budget"] != 1
        or type(retry["soscf_consumed"]) is not bool
        or retry["soscf_stage"] not in {None, "optimization", "final_scf"}
        or (retry["soscf_consumed"] is True) != (retry["soscf_stage"] is not None)
    ):
        raise ResumeValidationError(f"{endpoint.name} retry values drifted")
    if not isinstance(optimization, dict) or set(optimization) != {
        "optimizer",
        "geometry_converged",
        "scf_converged",
        "selected_strategy",
        "last_energy_hartree",
        "attempts",
        "runtime",
        "dispersion",
    }:
        raise ResumeValidationError(f"{endpoint.name} optimization schema drifted")
    if (
        optimization["optimizer"] != "geomeTRIC"
        or optimization["geometry_converged"] is not True
        or optimization["scf_converged"] is not True
        or optimization["selected_strategy"] not in {"standard", "soscf"}
        or type(optimization["last_energy_hartree"]) not in {int, float}
        or not math.isfinite(cast(float, optimization["last_energy_hartree"]))
    ):
        raise ResumeValidationError(f"{endpoint.name} optimization values drifted")
    _validate_recorded_attempts(
        optimization["attempts"],
        selected_strategy=optimization["selected_strategy"],
        label=f"{endpoint.name} optimization",
    )
    optimization_runtime = _parse_runtime_evidence(
        optimization["runtime"], label=f"{endpoint.name} optimization"
    )
    optimization_dispersion = _parse_optimization_dispersion(
        optimization["dispersion"], label=endpoint.name
    )
    try:
        _validate_runtime_evidence(
            optimization_runtime,
            expected_electron_count=endpoint.electron_count,
        )
        _validate_optimization_dispersion(
            optimization_dispersion,
            expected_atoms=len(endpoint.geometry.atoms),
        )
    except BackendError as exc:
        raise ResumeValidationError(f"{endpoint.name} optimization evidence drifted") from exc
    if not isinstance(final_scf, dict) or set(final_scf) != {
        "converged",
        "selected_strategy",
        "energy_hartree",
        "attempts",
        "runtime",
        "dispersion",
    }:
        raise ResumeValidationError(f"{endpoint.name} final SCF schema drifted")
    if (
        final_scf["converged"] is not True
        or final_scf["selected_strategy"] not in {"standard", "soscf"}
        or type(final_scf["energy_hartree"]) not in {int, float}
        or not math.isfinite(cast(float, final_scf["energy_hartree"]))
    ):
        raise ResumeValidationError(f"{endpoint.name} final SCF values drifted")
    if optimization["selected_strategy"] == "soscf" and final_scf["selected_strategy"] != "soscf":
        raise ResumeValidationError(f"{endpoint.name} final SCF strategy regressed")
    _validate_recorded_attempts(
        final_scf["attempts"],
        selected_strategy=final_scf["selected_strategy"],
        label=f"{endpoint.name} final SCF",
    )
    expected_retry_stage: str | None
    if optimization["selected_strategy"] == "soscf":
        expected_retry_stage = "optimization"
    elif final_scf["selected_strategy"] == "soscf":
        expected_retry_stage = "final_scf"
    else:
        expected_retry_stage = None
    if retry["soscf_stage"] != expected_retry_stage:
        raise ResumeValidationError(f"{endpoint.name} retry stage disagrees with attempts")
    final_runtime = _parse_runtime_evidence(
        final_scf["runtime"], label=f"{endpoint.name} final SCF"
    )
    final_dispersion = _parse_final_dispersion(final_scf["dispersion"], label=endpoint.name)
    try:
        _validate_runtime_evidence(
            final_runtime,
            expected_electron_count=endpoint.electron_count,
        )
        _validate_final_dispersion(
            final_dispersion,
            expected_atoms=len(endpoint.geometry.atoms),
            total_energy=float(cast(float, final_scf["energy_hartree"])),
        )
    except BackendError as exc:
        raise ResumeValidationError(f"{endpoint.name} final evidence drifted") from exc
    return typed, float(cast(float, final_scf["energy_hartree"]))


def _parse_completed_result(
    payload: dict[str, object],
    *,
    request: TwoEndpointRequest,
    attempt_id: str,
    result_relative_path: str,
    result_sha256: str,
    resumed: bool,
) -> TwoEndpointRunResult:
    expected_fields = {
        "schema_version",
        "status",
        "attempt_id",
        "request_id",
        "inchikey",
        "protocol_sha256",
        "protocol",
        "endpoints",
        "electronic_difference_kcal",
        "dft_deprot_electronic_kcal",
        "lower_is_better",
        *_success_flags(),
    }
    if set(payload) != expected_fields:
        raise ResumeValidationError("result.json fields drifted")
    if payload["schema_version"] != RESULT_SCHEMA_VERSION or payload["status"] != "success":
        raise ResumeValidationError("result.json status or schema drifted")
    if payload["attempt_id"] != attempt_id:
        raise ResumeValidationError("result and success marker refer to different attempts")
    if payload["request_id"] != request.request_id or payload["inchikey"] != request.inchikey:
        raise ResumeValidationError("result candidate identity drifted")
    if (
        payload["protocol_sha256"] != request.protocol_sha256
        or payload["protocol"] != LOCKED_PROTOCOL
    ):
        raise ResumeValidationError("result protocol identity drifted")
    if payload["lower_is_better"] is not True:
        raise ResumeValidationError("result lower_is_better drifted")
    endpoints_raw = payload["endpoints"]
    if not isinstance(endpoints_raw, dict) or set(endpoints_raw) != {"cation", "neutral"}:
        raise ResumeValidationError("result endpoint set drifted")
    endpoints = cast(dict[str, object], endpoints_raw)
    _, cation_energy = _validate_endpoint_record(endpoints["cation"], endpoint=request.cation)
    _, neutral_energy = _validate_endpoint_record(endpoints["neutral"], endpoint=request.neutral)
    try:
        result = TwoEndpointRunResult(
            attempt_id=str(payload["attempt_id"]),
            request_id=str(payload["request_id"]),
            inchikey=str(payload["inchikey"]),
            cation_energy_hartree=cation_energy,
            neutral_energy_hartree=neutral_energy,
            electronic_difference_kcal=float(cast(float, payload["electronic_difference_kcal"])),
            dft_deprot_electronic_kcal=float(cast(float, payload["dft_deprot_electronic_kcal"])),
            result_relative_path=result_relative_path,
            result_sha256=result_sha256,
            resumed=resumed,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ResumeValidationError("result.json has an invalid schema") from exc
    values = (
        result.cation_energy_hartree,
        result.neutral_energy_hartree,
        result.electronic_difference_kcal,
        result.dft_deprot_electronic_kcal,
    )
    if not all(math.isfinite(value) for value in values):
        raise ResumeValidationError("result.json contains non-finite values")
    expected_difference = (
        result.neutral_energy_hartree - result.cation_energy_hartree
    ) * HARTREE_TO_KCAL_MOL
    expected_label = expected_difference + GAS_PROTON_KCAL_MOL
    if not math.isclose(
        result.electronic_difference_kcal,
        expected_difference,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ResumeValidationError("stored electronic difference fails the locked formula")
    if not math.isclose(
        result.dft_deprot_electronic_kcal,
        expected_label,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ResumeValidationError("stored deprotonation label fails the locked formula")
    for key, expected in _success_flags().items():
        if payload.get(key) != expected:
            raise ResumeValidationError(f"stored safety flag drifted: {key}")
    return result


def _resume_if_valid(
    *,
    request: TwoEndpointRequest,
    output_root: Path,
    require_supervision: bool = False,
    marker_name: str = "_SUCCESS",
    success_name: str = "success.json",
    success_schema_version: str = SUCCESS_SCHEMA_VERSION,
    marker_hash_key: str = "success_sha256",
) -> TwoEndpointRunResult | None:
    marker_path = output_root / marker_name
    success_path = output_root / success_name
    if not marker_path.exists() and not success_path.exists():
        if output_root.exists():
            unknown = {path.name for path in output_root.iterdir()} - {"attempts"}
            if unknown:
                raise ResumeValidationError("incomplete output root contains unknown state")
        return None
    if not marker_path.exists() or not success_path.exists():
        raise ResumeValidationError("success state is incomplete")
    top_level_names = {path.name for path in output_root.iterdir()}
    if top_level_names != {marker_name, success_name, "attempts"}:
        raise ResumeValidationError("completed output root contains unexpected state")
    attempts_root = output_root / "attempts"
    if attempts_root.is_symlink() or not attempts_root.is_dir():
        raise ResumeValidationError("attempts root is unsafe")
    marker = _read_json_object(marker_path, error_cls=ResumeValidationError)
    _require_resume_keys(marker, {"schema_version", marker_hash_key}, marker_name)
    if marker["schema_version"] != success_schema_version:
        raise ResumeValidationError("success marker schema drifted")
    expected_success_hash = marker[marker_hash_key]
    if not isinstance(expected_success_hash, str) or not _SHA256_RE.fullmatch(
        expected_success_hash
    ):
        raise ResumeValidationError("success marker hash is invalid")
    if sha256_file(success_path) != expected_success_hash:
        raise ResumeValidationError("success.json hash mismatch")
    success = _read_json_object(success_path, error_cls=ResumeValidationError)
    _require_resume_keys(
        success,
        {
            "schema_version",
            "status",
            "attempt_id",
            "request_id",
            "inchikey",
            "request_sha256",
            "protocol_sha256",
            "runner_source_sha256",
            "input_sha256",
            "output_sha256",
            "result_relative_path",
            "supervision",
        },
        success_name,
    )
    if success["schema_version"] != success_schema_version or success["status"] != "success":
        raise ResumeValidationError(f"{success_name} status or schema drifted")
    expected_identity = _identity(request)
    for key, expected in expected_identity.items():
        if success.get(key) != expected:
            raise ResumeValidationError(f"resume identity mismatch: {key}")
    if success["request_id"] != request.request_id or success["inchikey"] != request.inchikey:
        raise ResumeValidationError("resume candidate identity mismatch")
    recorded_supervision = success["supervision"]
    if recorded_supervision is None:
        if require_supervision:
            raise ResumeValidationError("parent-supervised success omitted supervision evidence")
    else:
        _validate_recorded_supervision(recorded_supervision, require_success=True)
    attempt_id = success["attempt_id"]
    if not isinstance(attempt_id, str) or _ATTEMPT_ID_RE.fullmatch(attempt_id) is None:
        raise ResumeValidationError("resume attempt_id is invalid")
    output_hashes = success["output_sha256"]
    if not isinstance(output_hashes, dict) or not output_hashes:
        raise ResumeValidationError("resume output hash map is invalid")
    expected_attempt_names = _SUCCESS_ATTEMPT_FILENAMES
    expected_output_names = {
        _relative_attempt_path(attempt_id, name) for name in expected_attempt_names
    }
    if set(output_hashes) != expected_output_names:
        raise ResumeValidationError("resume output file set drifted")
    attempt_dir = attempts_root / attempt_id
    if attempt_dir.is_symlink() or not attempt_dir.is_dir():
        raise ResumeValidationError("resume attempt directory is unsafe")
    if {path.name for path in attempt_dir.iterdir()} != expected_attempt_names:
        raise ResumeValidationError("resume attempt directory file set drifted")
    for name, expected_hash in cast(dict[str, object], output_hashes).items():
        if (
            not isinstance(name, str)
            or not isinstance(expected_hash, str)
            or _SHA256_RE.fullmatch(expected_hash) is None
        ):
            raise ResumeValidationError("resume output hash entry is invalid")
        relative = PurePosixPath(name)
        if (
            relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.as_posix() != name
            or relative.parts[:2] != ("attempts", attempt_id)
        ):
            raise ResumeValidationError("resume output path is unsafe or crosses attempts")
        path = output_root.joinpath(*relative.parts)
        if path.is_symlink() or not path.is_file() or sha256_file(path) != expected_hash:
            raise ResumeValidationError(f"resume output hash mismatch: {name}")
    result_relative_path = success["result_relative_path"]
    expected_result_path = _relative_attempt_path(attempt_id, "result.json")
    if result_relative_path != expected_result_path or result_relative_path not in output_hashes:
        raise ResumeValidationError("resume result path is not registered")
    result_path = output_root.joinpath(*PurePosixPath(expected_result_path).parts)
    result_payload = _read_json_object(result_path, error_cls=ResumeValidationError)
    result_endpoints = result_payload.get("endpoints")
    if not isinstance(result_endpoints, dict):
        raise ResumeValidationError("result endpoints are not an object")
    for endpoint in (request.cation, request.neutral):
        endpoint_record_path = attempt_dir / f"{endpoint.name}.json"
        endpoint_record = _read_json_object(endpoint_record_path, error_cls=ResumeValidationError)
        if endpoint_record != result_endpoints.get(endpoint.name):
            raise ResumeValidationError(f"{endpoint.name} record disagrees with result.json")
        optimized_path = attempt_dir / f"{endpoint.name}.optimized.xyz"
        try:
            optimized_geometry = _parse_xyz(
                optimized_path.read_bytes(), label=f"resumed {endpoint.name} XYZ"
            )
        except (OSError, RequestValidationError) as exc:
            raise ResumeValidationError(f"resumed {endpoint.name} XYZ is invalid") from exc
        if tuple(atom.element for atom in optimized_geometry.atoms) != tuple(
            atom.element for atom in endpoint.geometry.atoms
        ):
            raise ResumeValidationError(f"resumed {endpoint.name} XYZ atom order drifted")
        if endpoint_record.get("optimized_xyz_sha256") != sha256_file(optimized_path):
            raise ResumeValidationError(f"resumed {endpoint.name} XYZ identity drifted")
    attempt_marker_path = attempt_dir / "_ATTEMPT_SUCCESS"
    attempt_marker = _read_json_object(attempt_marker_path, error_cls=ResumeValidationError)
    _require_resume_keys(
        attempt_marker,
        {
            "schema_version",
            "status",
            "attempt_id",
            "request_id",
            "inchikey",
            "request_sha256",
            "protocol_sha256",
            "runner_source_sha256",
            "input_sha256",
            "result_sha256",
        },
        "_ATTEMPT_SUCCESS",
    )
    if (
        attempt_marker["schema_version"] != ATTEMPT_SCHEMA_VERSION
        or attempt_marker["status"] != "success"
        or attempt_marker["attempt_id"] != attempt_id
        or attempt_marker["request_id"] != request.request_id
        or attempt_marker["inchikey"] != request.inchikey
    ):
        raise ResumeValidationError("attempt marker identity drifted")
    for key, expected in _identity(request).items():
        if attempt_marker.get(key) != expected:
            raise ResumeValidationError(f"attempt marker identity mismatch: {key}")
    result_hash = cast(str, output_hashes[expected_result_path])
    if attempt_marker["result_sha256"] != result_hash:
        raise ResumeValidationError("attempt marker result hash drifted")
    return _parse_completed_result(
        result_payload,
        request=request,
        attempt_id=attempt_id,
        result_relative_path=expected_result_path,
        result_sha256=result_hash,
        resumed=True,
    )


def _require_resume_keys(payload: dict[str, object], expected: set[str], label: str) -> None:
    if set(payload) != expected:
        raise ResumeValidationError(f"{label} fields drifted")


def _safe_failure_message(error: Exception) -> str:
    if isinstance(error, TwoEndpointError):
        message = str(error)
    else:
        message = f"backend raised {type(error).__name__}"
    message = message.replace("\n", " ").replace("\r", " ")
    return message[:500]


def _failure_exit_code(error: Exception) -> int:
    return 124 if isinstance(error, BackendTimeoutError) else 1


def _execute_validated_request(
    request: TwoEndpointRequest,
    output_root: Path,
    *,
    backend: TwoEndpointBackend,
    attempt_id: str | None = None,
    absolute_deadline_monotonic: float | None = None,
) -> TwoEndpointRunResult:
    """Execute through an injected backend; private so Phase 7 has no public bypass."""

    deadline = _resolve_request_deadline(request, absolute_deadline_monotonic)
    _validate_output_root(output_root)
    resumed = _resume_if_valid(request=request, output_root=output_root)
    if resumed is not None:
        return resumed
    output_root.mkdir(parents=False, exist_ok=True)
    attempts_root = output_root / "attempts"
    attempts_root.mkdir(exist_ok=True)
    if attempts_root.is_symlink():
        raise ResumeValidationError("attempts root must not be a symlink")
    safe_attempt_id = _safe_attempt_id(attempt_id)
    final_attempt_dir = attempts_root / safe_attempt_id
    if final_attempt_dir.exists() or final_attempt_dir.is_symlink():
        raise ResumeValidationError("attempt_id already exists")
    temporary_attempt = Path(tempfile.mkdtemp(prefix=f".tmp-{safe_attempt_id}-", dir=attempts_root))
    stage = "initialization"
    try:
        stage = "cation"
        cation_opt, cation_scf, cation_record = _run_endpoint(
            backend=backend, endpoint=request.cation, deadline=deadline
        )
        cation_xyz_name = "cation.optimized.xyz"
        _atomic_write_bytes(
            temporary_attempt / cation_xyz_name,
            cation_opt.geometry.to_xyz_bytes(
                comment=f"{request.inchikey} cation B3LYP-D3BJ/def2-SVP"
            ),
        )
        cation_record["optimized_xyz_sha256"] = sha256_file(temporary_attempt / cation_xyz_name)
        _atomic_write_json(temporary_attempt / "cation.json", cation_record)

        stage = "neutral"
        neutral_opt, neutral_scf, neutral_record = _run_endpoint(
            backend=backend, endpoint=request.neutral, deadline=deadline
        )
        neutral_xyz_name = "neutral.optimized.xyz"
        _atomic_write_bytes(
            temporary_attempt / neutral_xyz_name,
            neutral_opt.geometry.to_xyz_bytes(
                comment=f"{request.inchikey} neutral B3LYP-D3BJ/def2-SVP"
            ),
        )
        neutral_record["optimized_xyz_sha256"] = sha256_file(temporary_attempt / neutral_xyz_name)
        _atomic_write_json(temporary_attempt / "neutral.json", neutral_record)

        stage = "label"
        electronic_difference = (
            neutral_scf.energy_hartree - cation_scf.energy_hartree
        ) * HARTREE_TO_KCAL_MOL
        label = electronic_difference + GAS_PROTON_KCAL_MOL
        if not math.isfinite(electronic_difference) or not math.isfinite(label):
            raise BackendError("locked label formula produced a non-finite value")
        result_payload: dict[str, object] = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "status": "success",
            "attempt_id": safe_attempt_id,
            "request_id": request.request_id,
            "inchikey": request.inchikey,
            "protocol_sha256": request.protocol_sha256,
            "protocol": LOCKED_PROTOCOL,
            "endpoints": {"cation": cation_record, "neutral": neutral_record},
            "electronic_difference_kcal": electronic_difference,
            "dft_deprot_electronic_kcal": label,
            "lower_is_better": True,
            **_success_flags(),
        }
        _atomic_write_json(temporary_attempt / "result.json", result_payload)
        attempt_payload = {
            "schema_version": ATTEMPT_SCHEMA_VERSION,
            "status": "success",
            "attempt_id": safe_attempt_id,
            "request_id": request.request_id,
            "inchikey": request.inchikey,
            **_identity(request),
            "result_sha256": sha256_file(temporary_attempt / "result.json"),
        }
        _atomic_write_json(temporary_attempt / "_ATTEMPT_SUCCESS", attempt_payload)
        stage = "publish_attempt"
        _durably_move_attempt(
            temporary_attempt,
            final_attempt_dir,
            attempts_root=attempts_root,
        )
        output_hashes = {
            _relative_attempt_path(safe_attempt_id, path.name): sha256_file(path)
            for path in sorted(final_attempt_dir.iterdir())
            if path.is_file() and not path.is_symlink()
        }
        result_relative_path = _relative_attempt_path(safe_attempt_id, "result.json")
        success_payload = {
            "schema_version": SUCCESS_SCHEMA_VERSION,
            "status": "success",
            "attempt_id": safe_attempt_id,
            "request_id": request.request_id,
            "inchikey": request.inchikey,
            **_identity(request),
            "output_sha256": output_hashes,
            "result_relative_path": result_relative_path,
            "supervision": None,
        }
        _atomic_write_json(output_root / "success.json", success_payload)
        _atomic_write_json(
            output_root / "_SUCCESS",
            {
                "schema_version": SUCCESS_SCHEMA_VERSION,
                "success_sha256": sha256_file(output_root / "success.json"),
            },
        )
        return TwoEndpointRunResult(
            attempt_id=safe_attempt_id,
            request_id=request.request_id,
            inchikey=request.inchikey,
            cation_energy_hartree=cation_scf.energy_hartree,
            neutral_energy_hartree=neutral_scf.energy_hartree,
            electronic_difference_kcal=electronic_difference,
            dft_deprot_electronic_kcal=label,
            result_relative_path=result_relative_path,
            result_sha256=output_hashes[result_relative_path],
            resumed=False,
        )
    except Exception as error:
        if temporary_attempt.exists():
            failure_payload = {
                "schema_version": FAILURE_SCHEMA_VERSION,
                "status": "failed",
                "attempt_id": safe_attempt_id,
                "request_id": request.request_id,
                "inchikey": request.inchikey,
                "stage": stage,
                "error_type": type(error).__name__,
                "error_message": _safe_failure_message(error),
                "exit_code": _failure_exit_code(error),
                **_identity(request),
            }
            try:
                _atomic_write_json(temporary_attempt / "failure.json", failure_payload)
                _durably_move_attempt(
                    temporary_attempt,
                    final_attempt_dir,
                    attempts_root=attempts_root,
                )
            except Exception:
                shutil.rmtree(temporary_attempt, ignore_errors=True)
        raise TwoEndpointRunError(
            f"two-endpoint attempt failed at {stage}: {_safe_failure_message(error)}",
            exit_code=_failure_exit_code(error),
            attempt_dir=final_attempt_dir if final_attempt_dir.exists() else None,
        ) from error


def _supervision_evidence_payload(result: _SupervisionResultLike) -> dict[str, object]:
    """Validate and serialize the complete bounded supervisor observation."""

    if result.outcome not in _SUPERVISION_OUTCOMES:
        raise ResumeValidationError("supervisor outcome is invalid")
    for label, value in (
        ("public returncode", result.returncode),
        ("child returncode", result.child_returncode),
    ):
        if value is not None and type(value) is not int:
            raise ResumeValidationError(f"supervisor {label} is invalid")
    if not isinstance(result.stdout, bytes) or not isinstance(result.stderr, bytes):
        raise ResumeValidationError("supervisor streams must be bounded bytes")
    for label, total, captured in (
        ("stdout", result.stdout_total_bytes, result.stdout),
        ("stderr", result.stderr_total_bytes, result.stderr),
    ):
        if (
            type(total) is not int
            or total < 0
            or total < len(captured)
            or len(captured) > _SUPERVISOR_STREAM_CAPTURE_LIMIT_BYTES
        ):
            raise ResumeValidationError(f"supervisor {label} byte counts are invalid")
    boolean_fields = {
        "stdout_truncated": result.stdout_truncated,
        "stderr_truncated": result.stderr_truncated,
        "timed_out": result.timed_out,
        "term_sent": result.term_sent,
        "kill_sent": result.kill_sent,
        "orphan_descendants_detected": result.orphan_descendants_detected,
        "process_started": result.process_started,
        "group_cleanup_confirmed": result.group_cleanup_confirmed,
        "direct_child_reaped": result.direct_child_reaped,
    }
    if any(type(value) is not bool for value in boolean_fields.values()):
        raise ResumeValidationError("supervisor boolean evidence is invalid")
    if result.stdout_truncated is not (result.stdout_total_bytes > len(result.stdout)):
        raise ResumeValidationError("supervisor stdout truncation evidence disagrees")
    if result.stderr_truncated is not (result.stderr_total_bytes > len(result.stderr)):
        raise ResumeValidationError("supervisor stderr truncation evidence disagrees")
    if (
        type(result.duration_seconds) not in {int, float}
        or not math.isfinite(result.duration_seconds)
        or result.duration_seconds < 0.0
    ):
        raise ResumeValidationError("supervisor duration is invalid")
    if (
        result.outcome == "clean"
        and result.returncode == 0
        and result.duration_seconds > _SUPERVISOR_HARD_WALL_SECONDS
    ):
        raise ResumeValidationError("successful supervision exceeded the frozen hard wall-time")
    for label, value in (("pid", result.pid), ("pgid", result.pgid)):
        if value is not None and (type(value) is not int or value <= 1):
            raise ResumeValidationError(f"supervisor {label} is invalid")
    if result.process_started:
        if result.pid is None:
            raise ResumeValidationError("started supervisor result omitted pid")
    elif result.pid is not None or result.pgid is not None:
        raise ResumeValidationError("unstarted supervisor result recorded process identity")
    if result.error_message is not None and (
        not isinstance(result.error_message, str) or len(result.error_message) > 4096
    ):
        raise ResumeValidationError("supervisor error message is invalid")
    return {
        "outcome": result.outcome,
        "public_returncode": result.returncode,
        "child_returncode": result.child_returncode,
        "duration_seconds": float(result.duration_seconds),
        "pid": result.pid,
        "pgid": result.pgid,
        "stdout_total_bytes": result.stdout_total_bytes,
        "stdout_captured_bytes": len(result.stdout),
        "stdout_captured_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "stdout_truncated": result.stdout_truncated,
        "stderr_total_bytes": result.stderr_total_bytes,
        "stderr_captured_bytes": len(result.stderr),
        "stderr_captured_sha256": hashlib.sha256(result.stderr).hexdigest(),
        "stderr_truncated": result.stderr_truncated,
        "timed_out": result.timed_out,
        "term_sent": result.term_sent,
        "kill_sent": result.kill_sent,
        "orphan_descendants_detected": result.orphan_descendants_detected,
        "process_started": result.process_started,
        "group_cleanup_confirmed": result.group_cleanup_confirmed,
        "direct_child_reaped": result.direct_child_reaped,
        "error_message": result.error_message,
    }


def _validate_recorded_supervision(payload: object, *, require_success: bool) -> None:
    if not isinstance(payload, dict):
        raise ResumeValidationError("recorded supervision evidence is not an object")
    typed = cast(dict[str, object], payload)
    expected_fields = {
        "outcome",
        "public_returncode",
        "child_returncode",
        "duration_seconds",
        "pid",
        "pgid",
        "stdout_total_bytes",
        "stdout_captured_bytes",
        "stdout_captured_sha256",
        "stdout_truncated",
        "stderr_total_bytes",
        "stderr_captured_bytes",
        "stderr_captured_sha256",
        "stderr_truncated",
        "timed_out",
        "term_sent",
        "kill_sent",
        "orphan_descendants_detected",
        "process_started",
        "group_cleanup_confirmed",
        "direct_child_reaped",
        "error_message",
    }
    _require_resume_keys(typed, expected_fields, "supervision evidence")
    if typed["outcome"] not in _SUPERVISION_OUTCOMES:
        raise ResumeValidationError("recorded supervision outcome drifted")
    for name in ("public_returncode", "child_returncode", "pid", "pgid"):
        value = typed[name]
        if value is not None and type(value) is not int:
            raise ResumeValidationError(f"recorded supervision {name} drifted")
    duration = typed["duration_seconds"]
    if type(duration) not in {int, float} or not math.isfinite(cast(float, duration)):
        raise ResumeValidationError("recorded supervision duration drifted")
    if cast(float, duration) < 0.0:
        raise ResumeValidationError("recorded supervision duration is negative")
    if require_success and cast(float, duration) > _SUPERVISOR_HARD_WALL_SECONDS:
        raise ResumeValidationError(
            "recorded successful supervision exceeded the frozen hard wall-time"
        )
    for stream in ("stdout", "stderr"):
        total = typed[f"{stream}_total_bytes"]
        captured = typed[f"{stream}_captured_bytes"]
        digest = typed[f"{stream}_captured_sha256"]
        truncated = typed[f"{stream}_truncated"]
        if (
            type(total) is not int
            or type(captured) is not int
            or total < 0
            or captured < 0
            or captured > total
            or captured > _SUPERVISOR_STREAM_CAPTURE_LIMIT_BYTES
            or not isinstance(digest, str)
            or _SHA256_RE.fullmatch(digest) is None
            or type(truncated) is not bool
            or truncated is not (total > captured)
        ):
            raise ResumeValidationError(f"recorded supervision {stream} evidence drifted")
    for name in (
        "timed_out",
        "term_sent",
        "kill_sent",
        "orphan_descendants_detected",
        "process_started",
        "group_cleanup_confirmed",
        "direct_child_reaped",
    ):
        if type(typed[name]) is not bool:
            raise ResumeValidationError(f"recorded supervision {name} drifted")
    message = typed["error_message"]
    if message is not None and (not isinstance(message, str) or len(message) > 4096):
        raise ResumeValidationError("recorded supervision error message drifted")
    if require_success and (
        typed["outcome"] != "clean"
        or typed["public_returncode"] != 0
        or typed["child_returncode"] != 0
        or typed["timed_out"] is not False
        or typed["term_sent"] is not False
        or typed["kill_sent"] is not False
        or typed["orphan_descendants_detected"] is not False
        or typed["process_started"] is not True
        or typed["group_cleanup_confirmed"] is not True
        or typed["direct_child_reaped"] is not True
        or typed["stdout_truncated"] is not False
        or typed["stderr_truncated"] is not False
        or type(typed["pid"]) is not int
        or typed["pid"] <= 1
        or typed["pgid"] != typed["pid"]
        or typed["error_message"] is not None
    ):
        raise ResumeValidationError("recorded supervision is not a clean bounded success")


def _supervision_failure_kind(result: _SupervisionResultLike) -> tuple[str, str, int] | None:
    if result.stdout_truncated or result.stderr_truncated:
        return (
            "WorkerOutputTruncatedError",
            "worker output exceeded the frozen capture limit",
            1,
        )
    if result.outcome == "supervision_error":
        return (
            "WorkerSupervisionError",
            "worker process-tree supervision failed",
            1,
        )
    if result.timed_out:
        return (
            "HardWallTimeoutError",
            "worker process tree exceeded the hard wall-time",
            124,
        )
    if result.orphan_descendants_detected:
        return (
            "WorkerOrphanDescendantsError",
            "worker left process-group descendants after direct-child exit",
            1,
        )
    if result.outcome == "clean" and result.returncode == 0:
        return None
    if result.outcome == "spawn_error":
        return ("WorkerSpawnError", "worker process could not be started", 1)
    if result.outcome == "nonzero":
        return ("WorkerExitError", "worker process exited nonzero", 1)
    return (
        "WorkerSupervisionError",
        f"worker supervision ended with outcome {result.outcome!r}",
        1,
    )


def _supervision_safe_to_finalize(result: _SupervisionResultLike) -> bool:
    """Require proof that no spawned process can still mutate scratch state."""

    return not result.process_started or (
        result.group_cleanup_confirmed and result.direct_child_reaped
    )


def _validate_worker_failure_file(path: Path, *, max_bytes: int) -> bytes:
    """Read one worker-owned evidence file only after strict inode checks."""

    if path.is_symlink():
        raise ResumeValidationError(f"worker failure artifact is a symlink: {path.name}")
    try:
        observed = path.stat()
    except OSError as exc:
        raise ResumeValidationError(f"worker failure artifact is unavailable: {path.name}") from exc
    if (
        not stat.S_ISREG(observed.st_mode)
        or observed.st_uid != os.geteuid()
        or observed.st_nlink != 1
        or observed.st_size <= 0
        or observed.st_size > max_bytes
    ):
        raise ResumeValidationError(f"worker failure artifact is unsafe: {path.name}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ResumeValidationError(f"worker failure artifact is unreadable: {path.name}") from exc
    if len(raw) != observed.st_size:
        raise ResumeValidationError(f"worker failure artifact changed while read: {path.name}")
    return raw


def _sanitized_worker_failure_message(value: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", value)[:500]


def _worker_failure_directory_names(path: Path, *, label: str) -> set[str]:
    if path.is_symlink():
        raise ResumeValidationError(f"{label} is a symlink")
    try:
        observed = path.stat()
        names = {entry.name for entry in path.iterdir()}
    except OSError as exc:
        raise ResumeValidationError(f"{label} is unavailable") from exc
    if not stat.S_ISDIR(observed.st_mode) or observed.st_uid != os.geteuid():
        raise ResumeValidationError(f"{label} is unsafe")
    return names


def _validated_worker_failure(
    *,
    request: TwoEndpointRequest,
    worker_output_root: Path,
    attempt_id: str,
    child_returncode: int | None,
) -> tuple[dict[str, object], str]:
    """Validate the exact nonzero-worker scratch and return bounded evidence."""

    if _worker_failure_directory_names(worker_output_root, label="worker failure output root") != {
        "attempts"
    }:
        raise ResumeValidationError("worker failure output root file set drifted")
    attempts_root = worker_output_root / "attempts"
    if _worker_failure_directory_names(attempts_root, label="worker failure attempts root") != {
        attempt_id
    }:
        raise ResumeValidationError("worker failure scratch contains cross-attempt state")
    attempt_dir = attempts_root / attempt_id
    names = _worker_failure_directory_names(attempt_dir, label="worker failure attempt directory")
    if "result.json" in names or "_ATTEMPT_SUCCESS" in names:
        raise ResumeValidationError("worker failure scratch contains success state")
    if "failure.json" not in names or not names <= _WORKER_FAILURE_ATTEMPT_FILENAMES:
        raise ResumeValidationError("worker failure attempt file set drifted")
    if "cation.json" in names and "cation.optimized.xyz" not in names:
        raise ResumeValidationError("worker cation partial state is out of order")
    if "neutral.json" in names and "neutral.optimized.xyz" not in names:
        raise ResumeValidationError("worker neutral partial state is out of order")
    if (
        names & {"neutral.json", "neutral.optimized.xyz"}
        and not {
            "cation.json",
            "cation.optimized.xyz",
        }
        <= names
    ):
        raise ResumeValidationError("worker neutral partial state precedes cation completion")
    for name in names - {"failure.json"}:
        limit = _MAX_XYZ_BYTES if name.endswith(".xyz") else _MAX_REQUEST_BYTES
        _validate_worker_failure_file(attempt_dir / name, max_bytes=limit)

    failure_raw = _validate_worker_failure_file(
        attempt_dir / "failure.json", max_bytes=_MAX_REQUEST_BYTES
    )
    failure = _strict_json_object(
        failure_raw,
        label="worker failure.json",
        error_cls=ResumeValidationError,
    )
    _require_resume_keys(
        failure,
        {
            "schema_version",
            "status",
            "attempt_id",
            "request_id",
            "inchikey",
            "stage",
            "error_type",
            "error_message",
            "exit_code",
            "request_sha256",
            "protocol_sha256",
            "runner_source_sha256",
            "input_sha256",
        },
        "worker failure.json",
    )
    if _canonical_json_bytes(failure) != failure_raw:
        raise ResumeValidationError("worker failure.json is not canonical")
    if (
        failure["schema_version"] != FAILURE_SCHEMA_VERSION
        or failure["status"] != "failed"
        or failure["attempt_id"] != attempt_id
        or failure["request_id"] != request.request_id
        or failure["inchikey"] != request.inchikey
    ):
        raise ResumeValidationError("worker failure identity drifted")
    for key, expected in _identity(request).items():
        if failure.get(key) != expected:
            raise ResumeValidationError(f"worker failure identity mismatch: {key}")
    stage = failure["stage"]
    error_type = failure["error_type"]
    error_message = failure["error_message"]
    exit_code = failure["exit_code"]
    if not isinstance(stage, str) or stage not in _WORKER_FAILURE_STAGES:
        raise ResumeValidationError("worker failure stage drifted")
    if not isinstance(error_type, str) or _WORKER_ERROR_TYPE_RE.fullmatch(error_type) is None:
        raise ResumeValidationError("worker failure error type is invalid")
    if not isinstance(error_message, str) or len(error_message) > 500:
        raise ResumeValidationError("worker failure error message is invalid")
    if type(exit_code) is not int or exit_code not in {1, 124} or child_returncode != exit_code:
        raise ResumeValidationError("worker failure exit code disagrees with supervision")

    sanitized = {
        "schema_version": FAILURE_SCHEMA_VERSION,
        "status": "failed",
        "attempt_id": attempt_id,
        "request_id": request.request_id,
        "inchikey": request.inchikey,
        "stage": stage,
        "error_type": error_type,
        "error_message": _sanitized_worker_failure_message(error_message),
        "exit_code": exit_code,
        **_identity(request),
    }
    return sanitized, hashlib.sha256(failure_raw).hexdigest()


def _publish_supervisor_failure(
    *,
    request: TwoEndpointRequest,
    output_root: Path,
    attempt_id: str,
    error_type: str,
    error_message: str,
    exit_code: int,
    supervision_evidence: Mapping[str, object],
    worker_failure: Mapping[str, object] | None = None,
    worker_failure_sha256: str | None = None,
) -> Path:
    """Atomically publish one failure envelope after supervision has returned."""

    attempts_root = output_root / "attempts"
    final_attempt_dir = attempts_root / attempt_id
    if final_attempt_dir.exists() or final_attempt_dir.is_symlink():
        raise ResumeValidationError("attempt_id already exists before failure publication")
    if (worker_failure is None) is not (worker_failure_sha256 is None):
        raise ResumeValidationError("worker failure evidence is incomplete")
    if worker_failure_sha256 is not None and _SHA256_RE.fullmatch(worker_failure_sha256) is None:
        raise ResumeValidationError("worker failure evidence hash is invalid")
    temporary_attempt = Path(
        tempfile.mkdtemp(prefix=f".tmp-{attempt_id}-supervisor-failure-", dir=attempts_root)
    )
    failure_payload: dict[str, object] = {
        "schema_version": FAILURE_SCHEMA_VERSION,
        "status": "failed",
        "attempt_id": attempt_id,
        "request_id": request.request_id,
        "inchikey": request.inchikey,
        "stage": "supervisor",
        "error_type": error_type,
        "error_message": error_message,
        "exit_code": exit_code,
        **_identity(request),
        "supervision": dict(supervision_evidence),
    }
    if worker_failure is not None:
        failure_payload["worker_failure"] = dict(worker_failure)
        failure_payload["worker_failure_sha256"] = worker_failure_sha256
    try:
        _atomic_write_json(temporary_attempt / "failure.json", failure_payload)
        if {path.name for path in temporary_attempt.iterdir()} != {"failure.json"}:
            raise ResumeValidationError("supervisor failure envelope file set drifted")
        _durably_move_attempt(
            temporary_attempt,
            final_attempt_dir,
            attempts_root=attempts_root,
        )
    except Exception:
        shutil.rmtree(temporary_attempt, ignore_errors=True)
        raise
    return final_attempt_dir


def _publish_worker_success(
    *,
    request: TwoEndpointRequest,
    worker_output_root: Path,
    output_root: Path,
    attempt_id: str,
    supervision_evidence: Mapping[str, object],
    defer_final_acceptance: bool = False,
) -> TwoEndpointRunResult:
    """Validate the isolated worker state before publishing its exact attempt."""

    if worker_output_root.is_symlink() or not worker_output_root.is_dir():
        raise ResumeValidationError("worker output root is unsafe")
    _validate_recorded_supervision(supervision_evidence, require_success=True)
    worker_result = _resume_if_valid(request=request, output_root=worker_output_root)
    if worker_result is None or worker_result.attempt_id != attempt_id:
        raise ResumeValidationError("worker did not produce the fixed attempt identity")
    worker_attempts_root = worker_output_root / "attempts"
    if {path.name for path in worker_attempts_root.iterdir()} != {attempt_id}:
        raise ResumeValidationError("worker scratch contains cross-attempt state")
    worker_attempt_dir = worker_attempts_root / attempt_id
    if {path.name for path in worker_attempt_dir.iterdir()} != _SUCCESS_ATTEMPT_FILENAMES:
        raise ResumeValidationError("worker success attempt file set drifted")

    final_attempt_dir = output_root / "attempts" / attempt_id
    if final_attempt_dir.exists() or final_attempt_dir.is_symlink():
        raise ResumeValidationError("attempt_id already exists before success publication")
    worker_success = _read_json_object(
        worker_output_root / "success.json", error_cls=ResumeValidationError
    )
    if worker_success.get("supervision") is not None:
        raise ResumeValidationError("worker scratch unexpectedly contains parent supervision")
    if defer_final_acceptance:
        success_schema = SUPERVISOR_SUCCESS_SCHEMA_VERSION
        success_name = "supervisor_success.json"
        marker_name = "_SUPERVISOR_SUCCESS"
        marker_hash_key = "supervisor_success_sha256"
    else:
        success_schema = SUCCESS_SCHEMA_VERSION
        success_name = "success.json"
        marker_name = "_SUCCESS"
        marker_hash_key = "success_sha256"
    parent_success = {
        **worker_success,
        "schema_version": success_schema,
        "supervision": dict(supervision_evidence),
    }
    success_bytes = _canonical_json_bytes(parent_success)
    marker_bytes = _canonical_json_bytes(
        {
            "schema_version": success_schema,
            marker_hash_key: hashlib.sha256(success_bytes).hexdigest(),
        }
    )
    _durably_move_attempt(
        worker_attempt_dir,
        final_attempt_dir,
        attempts_root=output_root / "attempts",
    )
    try:
        _atomic_write_bytes(output_root / success_name, success_bytes)
        _atomic_write_bytes(output_root / marker_name, marker_bytes)
        published = _resume_if_valid(
            request=request,
            output_root=output_root,
            require_supervision=True,
            marker_name=marker_name,
            success_name=success_name,
            success_schema_version=success_schema,
            marker_hash_key=marker_hash_key,
        )
        if published is None or published.attempt_id != attempt_id:
            raise ResumeValidationError("parent-published success could not be revalidated")
    except Exception:
        (output_root / marker_name).unlink(missing_ok=True)
        (output_root / success_name).unlink(missing_ok=True)
        raise
    return replace(published, resumed=False)


def _execute_supervised_request(
    request: TwoEndpointRequest,
    output_root: Path,
    *,
    run_supervised: _RunSupervised,
    supervision_policy: object,
    attempt_id: str | None = None,
    python_executable: str | None = None,
    defer_final_acceptance: bool = False,
    worker_launch: Phase8BWorkerLaunch | None = None,
) -> TwoEndpointRunResult:
    """Run a fixed-attempt worker and publish only parent-validated state."""

    if request.execution_authorized is not True:
        raise ExecutionNotAuthorizedError("frozen request does not authorize execution")
    if worker_launch is not None and (
        attempt_id != FROZEN_ATTEMPT_ID or defer_final_acceptance is not True
    ):
        raise ExecutionNotAuthorizedError(
            "Phase 8B handshake requires the fixed attempt and deferred final acceptance"
        )
    _validate_output_root(output_root)
    if defer_final_acceptance:
        resume_options = {
            "marker_name": "_SUPERVISOR_SUCCESS",
            "success_name": "supervisor_success.json",
            "success_schema_version": SUPERVISOR_SUCCESS_SCHEMA_VERSION,
            "marker_hash_key": "supervisor_success_sha256",
        }
    else:
        resume_options = {}
    resumed = _resume_if_valid(
        request=request,
        output_root=output_root,
        require_supervision=True,
        **resume_options,
    )
    if resumed is not None:
        return resumed

    safe_attempt_id = _safe_attempt_id(attempt_id)
    output_root.mkdir(parents=False, exist_ok=True)
    attempts_root = output_root / "attempts"
    attempts_root.mkdir(exist_ok=True)
    if attempts_root.is_symlink():
        raise ResumeValidationError("attempts root must not be a symlink")
    final_attempt_dir = attempts_root / safe_attempt_id
    if final_attempt_dir.exists() or final_attempt_dir.is_symlink():
        raise ResumeValidationError("attempt_id already exists")

    worker_output_root = Path(
        tempfile.mkdtemp(
            prefix=f".worker-{safe_attempt_id}-",
            dir=output_root.parent,
        )
    )
    source_root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    for inherited_python_setting in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        environment.pop(inherited_python_setting, None)
    environment.update(THREAD_ENVIRONMENT)
    worker_argv = [
        "--request-path",
        str(request.request_path.resolve(strict=True)),
        "--output-root",
        str(worker_output_root.resolve(strict=True)),
        "--attempt-id",
        safe_attempt_id,
    ]
    if worker_launch is None:
        argv = [
            python_executable or sys.executable,
            "-I",
            "-B",
            "-c",
            _WORKER_BOOTSTRAP,
            str(source_root),
            *worker_argv,
        ]
    else:
        argv = [
            python_executable or sys.executable,
            "-I",
            "-B",
            "-c",
            _HANDSHAKE_WORKER_BOOTSTRAP,
            str(source_root),
            "--start-fd",
            str(worker_launch.start_read_fd),
            "--release-token",
            worker_launch.release_token,
            "--expected-parent-pid",
            str(os.getpid()),
            "--absolute-deadline-ns",
            str(worker_launch.absolute_deadline_ns),
            "--allowed-cpus",
            "0-3",
            "--compute-claim-path",
            str(worker_launch.compute_claim_path),
            "--",
            *worker_argv,
            *worker_launch.authorization_argv,
        ]
    try:
        if worker_launch is None:
            supervision = run_supervised(
                argv,
                policy=supervision_policy,
                cwd=source_root,
                env=environment,
            )
        else:

            def register_started_worker(worker_pid: int, worker_pgid: int) -> None:
                worker_launch.on_process_started(
                    worker_pid,
                    worker_pgid,
                    worker_output_root,
                )

            supervision = run_supervised(
                argv,
                policy=supervision_policy,
                cwd=source_root,
                env=environment,
                pass_fds=(worker_launch.start_read_fd,),
                on_process_started=register_started_worker,
            )
    except Exception:
        # An unexpected supervisor exception cannot prove that a spawned group is
        # dead, so it must not be converted into a published attempt or cleaned.
        raise
    finally:
        if worker_launch is not None:
            for descriptor in (
                worker_launch.start_read_fd,
                worker_launch.release_write_fd,
            ):
                with suppress(OSError):
                    os.close(descriptor)

    try:
        supervision_evidence = _supervision_evidence_payload(supervision)
    except ResumeValidationError as error:
        raise TwoEndpointRunError(
            "worker supervisor returned structurally invalid evidence",
            exit_code=1,
            attempt_dir=None,
        ) from error
    failure = _supervision_failure_kind(supervision)
    if not _supervision_safe_to_finalize(supervision):
        raise TwoEndpointRunError(
            "worker supervision could not prove process-group cleanup and child reap",
            exit_code=1,
            attempt_dir=None,
        )
    if failure is not None:
        error_type, error_message, exit_code = failure
        worker_failure: dict[str, object] | None = None
        worker_failure_sha256: str | None = None
        if supervision.outcome == "nonzero":
            try:
                worker_failure, worker_failure_sha256 = _validated_worker_failure(
                    request=request,
                    worker_output_root=worker_output_root,
                    attempt_id=safe_attempt_id,
                    child_returncode=supervision.child_returncode,
                )
            except ResumeValidationError as error:
                protocol_message = _safe_failure_message(error)
                attempt_dir = _publish_supervisor_failure(
                    request=request,
                    output_root=output_root,
                    attempt_id=safe_attempt_id,
                    error_type="WorkerProtocolError",
                    error_message=protocol_message,
                    exit_code=1,
                    supervision_evidence=supervision_evidence,
                )
                raise TwoEndpointRunError(
                    "two-endpoint worker returned invalid failure state",
                    exit_code=1,
                    attempt_dir=attempt_dir,
                ) from error
        attempt_dir = _publish_supervisor_failure(
            request=request,
            output_root=output_root,
            attempt_id=safe_attempt_id,
            error_type=error_type,
            error_message=error_message,
            exit_code=exit_code,
            supervision_evidence=supervision_evidence,
            worker_failure=worker_failure,
            worker_failure_sha256=worker_failure_sha256,
        )
        shutil.rmtree(worker_output_root, ignore_errors=True)
        raise TwoEndpointRunError(
            f"two-endpoint worker failed: {error_message}",
            exit_code=exit_code,
            attempt_dir=attempt_dir,
        )

    try:
        result = _publish_worker_success(
            request=request,
            worker_output_root=worker_output_root,
            output_root=output_root,
            attempt_id=safe_attempt_id,
            supervision_evidence=supervision_evidence,
            defer_final_acceptance=defer_final_acceptance,
        )
    except Exception as error:
        if final_attempt_dir.exists() or final_attempt_dir.is_symlink():
            # Publication had already moved the validated six-file attempt.  It
            # remains uncommitted (no acceptance marker) and must not be overwritten with
            # a contradictory failure envelope under the same identity.
            shutil.rmtree(worker_output_root, ignore_errors=True)
            raise TwoEndpointRunError(
                "two-endpoint parent could not publish validated success state",
                exit_code=1,
                attempt_dir=None,
            ) from error
        attempt_dir = _publish_supervisor_failure(
            request=request,
            output_root=output_root,
            attempt_id=safe_attempt_id,
            error_type="WorkerProtocolError",
            error_message=_safe_failure_message(error),
            exit_code=1,
            supervision_evidence=supervision_evidence,
        )
        shutil.rmtree(worker_output_root, ignore_errors=True)
        raise TwoEndpointRunError(
            "two-endpoint worker returned invalid success state",
            exit_code=1,
            attempt_dir=attempt_dir,
        ) from error
    shutil.rmtree(worker_output_root, ignore_errors=True)
    return result


def run_phase8b_supervisor(
    request: TwoEndpointRequest,
    output_root: Path,
    *,
    authority: ExactPhase8BAuthority,
    worker_launch: Phase8BWorkerLaunch,
) -> TwoEndpointRunResult:
    """Run the one exact supervisor transaction and leave provisional success."""

    _ensure_execution_authorized()
    if not isinstance(authority, ExactPhase8BAuthority):
        raise ExecutionNotAuthorizedError("exact Phase 8B authority is required")
    if (
        authority.request_sha256 != request.request_sha256
        or authority.runner_source_sha256 != request.runner_source_sha256
        or authority.electron_count != FROZEN_ELECTRON_COUNT
    ):
        raise ExecutionNotAuthorizedError("exact Phase 8B authority disagrees with request")
    _validate_frozen_120_electron_pair(request.cation, request.neutral)
    if os.path.lexists(output_root):
        raise ExecutionNotAuthorizedError("Phase 8B output already exists; resume is prohibited")
    deadline_monotonic = worker_launch.absolute_deadline_ns / 1_000_000_000
    now = time.monotonic()
    if deadline_monotonic <= now or deadline_monotonic > now + request.timeout_seconds:
        raise ExecutionNotAuthorizedError("shared Phase 8B deadline is invalid or widened")
    supervisor_module = importlib.import_module("nhc_deprot_ranker.quantum.process_supervisor")
    policy_factory = cast(
        _SupervisionPolicyFactory,
        supervisor_module.SupervisionPolicy,
    )
    supervised_runner = cast(
        _RunSupervised,
        supervisor_module.run_supervised,
    )
    policy = policy_factory(
        timeout_seconds=float(request.timeout_seconds),
        terminate_grace_seconds=_SUPERVISOR_TERMINATE_GRACE_SECONDS,
        stream_capture_limit_bytes=_SUPERVISOR_STREAM_CAPTURE_LIMIT_BYTES,
        absolute_deadline_monotonic=deadline_monotonic,
    )
    return _execute_supervised_request(
        request,
        output_root,
        run_supervised=supervised_runner,
        supervision_policy=policy,
        attempt_id=FROZEN_ATTEMPT_ID,
        defer_final_acceptance=True,
        worker_launch=worker_launch,
    )


def run_two_endpoint(request_path: Path, output_root: Path) -> TwoEndpointRunResult:
    """Reject the obsolete generic entry even after the source gate opens.

    The only real execution path is :func:`run_phase8b_supervisor`, which
    requires an irreversibly consumed exact authority and guardian handshake.
    """

    del request_path, output_root
    _ensure_execution_authorized()
    raise ExecutionNotAuthorizedError(
        "generic two-endpoint execution is disabled; use the guarded Phase 8B transaction"
    )
