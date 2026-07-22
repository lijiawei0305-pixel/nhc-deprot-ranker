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
import sys
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Final, Literal, Protocol, cast

from nhc_deprot_ranker.constants import (
    GAS_PROTON_KCAL_MOL,
    HARTREE_TO_KCAL_MOL,
    LOWER_IS_BETTER,
)
from nhc_deprot_ranker.data.provenance import sha256_file

EndpointName = Literal["cation", "neutral"]
SCFStrategy = Literal["standard", "soscf"]

REQUEST_SCHEMA_VERSION: Final = "nhc-two-endpoint-request-v1"
RESULT_SCHEMA_VERSION: Final = "nhc-two-endpoint-result-v1"
ATTEMPT_SCHEMA_VERSION: Final = "nhc-two-endpoint-attempt-v1"
SUCCESS_SCHEMA_VERSION: Final = "nhc-two-endpoint-success-v1"
FAILURE_SCHEMA_VERSION: Final = "nhc-two-endpoint-failure-v1"
RUNNER_SOURCE_SCHEMA_VERSION: Final = "nhc-two-endpoint-runner-source-v2"

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
_SUPERVISOR_TERMINATE_GRACE_SECONDS: Final = 10.0
_SUPERVISOR_STREAM_CAPTURE_LIMIT_BYTES: Final = 64 * 1024
_RUNNER_SOURCE_RELATIVE_PATHS: Final[tuple[str, ...]] = (
    "nhc_deprot_ranker/__init__.py",
    "nhc_deprot_ranker/constants.py",
    "nhc_deprot_ranker/data/__init__.py",
    "nhc_deprot_ranker/data/provenance.py",
    "nhc_deprot_ranker/quantum/__init__.py",
    "nhc_deprot_ranker/quantum/two_endpoint.py",
    "nhc_deprot_ranker/quantum/worker.py",
    "nhc_deprot_ranker/quantum/process_supervisor.py",
)
_WORKER_BOOTSTRAP: Final = (
    "import runpy,sys;"
    "sys.path.insert(0,sys.argv.pop(1));"
    "runpy.run_module('nhc_deprot_ranker.quantum.worker',run_name='__main__',alter_sys=True)"
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


class SCFConvergenceError(BackendError):
    """A same-protocol SCF did not converge."""


class GeometryConvergenceError(BackendError):
    """The geomeTRIC optimization did not explicitly converge."""


class BackendTimeoutError(BackendError):
    """The backend exceeded the frozen request deadline."""


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
class BackendOptimizationResult:
    """Backend response for one geomeTRIC optimization."""

    geometry: XYZGeometry
    geometry_converged: bool
    scf_converged: bool
    last_energy_hartree: float


@dataclass(frozen=True)
class BackendSCFResult:
    """Backend response for the final same-method electronic energy."""

    converged: bool
    energy_hartree: float


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
    timed_out: bool
    term_sent: bool
    kill_sent: bool
    orphan_descendants_detected: bool
    process_started: bool
    group_cleanup_confirmed: bool
    direct_child_reaped: bool
    stdout_truncated: bool
    stderr_truncated: bool


class _RunSupervised(Protocol):
    """Dependency-injection seam for harmless Phase 8A protocol tests."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        policy: object,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
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


def _canonical_runner_source_sha256(sources: Mapping[str, bytes]) -> str:
    """Hash the exact eight-file pre-gate bundle without importing its modules."""

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
    return EndpointRequest(
        name=name,
        xyz_relative_path=relative,
        xyz_path=path,
        xyz_sha256=expected_hash,
        charge=charge,
        multiplicity=multiplicity,
        geometry=_parse_xyz(raw, label=f"{name} XYZ"),
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


class PySCFBackend:
    """Lazy PySCF/geomeTRIC adapter for the unique locked protocol.

    Every method repeats the source-level authorization check.  Merely importing
    this module or constructing this adapter imports no compute dependency.
    """

    def _load_modules(self) -> tuple[Any, Any, Any]:
        _ensure_execution_authorized()
        try:
            gto = importlib.import_module("pyscf.gto")
            dft = importlib.import_module("pyscf.dft")
            geometric_solver = importlib.import_module("pyscf.geomopt.geometric_solver")
            # Prove the optional engine that actually supplies D3(BJ) is present.
            importlib.import_module("pyscf.dispersion.dftd3")
        except ImportError as exc:
            raise BackendError("locked PySCF/geomeTRIC/D3(BJ) backend is unavailable") from exc
        return gto, dft, geometric_solver

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
    ) -> Any:
        gto, dft, _ = self._load_modules()
        if multiplicity != 1 or charge not in {0, 1}:
            raise BackendError("backend received a forbidden charge or multiplicity")
        atom_spec = [(atom.element, (atom.x, atom.y, atom.z)) for atom in geometry.atoms]
        try:
            molecule = gto.M(
                atom=atom_spec,
                unit="Angstrom",
                basis="def2-svp",
                charge=charge,
                spin=0,
                verbose=0,
            )
            mean_field = dft.RKS(molecule)
            mean_field.xc = "B3LYP"
            mean_field.grids.level = 3
            mean_field.conv_tol = 1.0e-9
            mean_field.max_cycle = 100 if strategy == "standard" else 200
            mean_field.disp = "d3bj"
            if str(getattr(mean_field, "disp", "")).lower() != "d3bj":
                raise DispersionUnavailableError("mf.disp did not retain d3bj")
            if not self._d3bj_is_active(mean_field):
                raise DispersionUnavailableError("mf.disp=d3bj is not active")
            if strategy == "soscf":
                mean_field = mean_field.newton()
                if str(getattr(mean_field, "disp", "")).lower() != "d3bj":
                    raise DispersionUnavailableError("SOSCF dropped mf.disp=d3bj")
                if not self._d3bj_is_active(mean_field):
                    raise DispersionUnavailableError("SOSCF did not retain active D3(BJ)")
        except DispersionUnavailableError:
            raise
        except Exception as exc:  # pragma: no cover - requires compute environment
            raise BackendError("failed to construct the locked mean field") from exc
        return mean_field

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
        mean_field = self._mean_field(
            geometry=geometry,
            charge=charge,
            multiplicity=multiplicity,
            strategy=strategy,
        )
        _, _, geometric_solver = self._load_modules()
        try:
            geometry_converged, optimized_molecule = geometric_solver.kernel(
                mean_field,
                assert_convergence=True,
                maxsteps=100,
            )
        except Exception as exc:  # pragma: no cover - requires compute environment
            message = str(exc).lower()
            if "scf" in message or "nuclear gradients not converged" in message:
                raise SCFConvergenceError("SCF failed during geomeTRIC optimization") from exc
            raise GeometryConvergenceError("geomeTRIC optimization failed") from exc
        self._check_deadline(deadline_monotonic)
        if geometry_converged is not True:
            raise GeometryConvergenceError("geomeTRIC did not explicitly converge")
        if not bool(getattr(mean_field, "converged", False)):
            raise SCFConvergenceError("last optimization SCF was not converged")
        last_energy = float(getattr(mean_field, "e_tot", math.nan))
        if not math.isfinite(last_energy):
            raise BackendError("optimization returned a non-finite energy")
        return BackendOptimizationResult(
            geometry=self._geometry_from_molecule(optimized_molecule),
            geometry_converged=True,
            scf_converged=True,
            last_energy_hartree=last_energy,
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
        mean_field = self._mean_field(
            geometry=geometry,
            charge=charge,
            multiplicity=multiplicity,
            strategy=strategy,
        )
        try:
            energy = float(mean_field.kernel())
        except Exception as exc:  # pragma: no cover - requires compute environment
            raise SCFConvergenceError("final same-method SCF raised an error") from exc
        self._check_deadline(deadline_monotonic)
        return BackendSCFResult(
            converged=bool(getattr(mean_field, "converged", False)),
            energy_hartree=energy,
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


def _validate_optimization(result: BackendOptimizationResult, *, original: XYZGeometry) -> None:
    if not isinstance(result, BackendOptimizationResult):
        raise BackendError("backend returned the wrong optimization result type")
    if not result.geometry_converged:
        raise GeometryConvergenceError("geomeTRIC did not explicitly converge")
    if not result.scf_converged:
        raise SCFConvergenceError("optimization SCF did not explicitly converge")
    if not math.isfinite(result.last_energy_hartree):
        raise BackendError("optimization energy is non-finite")
    _validate_backend_geometry(result.geometry)
    if tuple(atom.element for atom in result.geometry.atoms) != tuple(
        atom.element for atom in original.atoms
    ):
        raise BackendError("optimization changed atom count or ordering")


def _validate_scf(result: BackendSCFResult) -> None:
    if not isinstance(result, BackendSCFResult):
        raise BackendError("backend returned the wrong SCF result type")
    if not result.converged:
        raise SCFConvergenceError("final same-method SCF did not converge")
    if not math.isfinite(result.energy_hartree):
        raise BackendError("final electronic energy is non-finite")


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
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
    _validate_optimization(result, original=endpoint.geometry)
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
    _validate_scf(result)
    return result


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
    except SCFConvergenceError:
        optimization_attempts.append(
            {"strategy": "standard", "converged": False, "failure_kind": "scf"}
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
    except SCFConvergenceError:
        if final_scf_strategy == "soscf":
            raise
        scf_attempts.append({"strategy": "standard", "converged": False, "failure_kind": "scf"})
        final_scf_strategy = "soscf"
        final_scf = _call_scf(
            backend=backend,
            endpoint=endpoint,
            geometry=optimization.geometry,
            strategy="soscf",
            deadline=deadline,
        )
        scf_attempts.append({"strategy": "soscf", "converged": True})

    record: dict[str, object] = {
        "charge": endpoint.charge,
        "multiplicity": endpoint.multiplicity,
        "input_xyz_path": endpoint.xyz_relative_path,
        "input_xyz_sha256": endpoint.xyz_sha256,
        "optimization": {
            "optimizer": "geomeTRIC",
            "geometry_converged": True,
            "scf_converged": True,
            "selected_strategy": optimization_strategy,
            "last_energy_hartree": optimization.last_energy_hartree,
            "attempts": optimization_attempts,
        },
        "final_scf": {
            "converged": True,
            "selected_strategy": final_scf_strategy,
            "energy_hartree": final_scf.energy_hartree,
            "attempts": scf_attempts,
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
        if converged is False and failure_kind != "scf":
            raise ResumeValidationError(f"{label} failure kind drifted")
        normalized.append((strategy, converged, failure_kind))
    if len(normalized) == 1:
        if normalized[0][1] is not True:
            raise ResumeValidationError(f"{label} single attempt was not converged")
    elif normalized != [("standard", False, "scf"), ("soscf", True, None)]:
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
        "input_xyz_path",
        "input_xyz_sha256",
        "optimization",
        "final_scf",
        "optimized_xyz_sha256",
    }:
        raise ResumeValidationError(f"{endpoint.name} result fields drifted")
    if (
        typed["charge"] != endpoint.charge
        or typed["multiplicity"] != endpoint.multiplicity
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
    if not isinstance(optimization, dict) or set(optimization) != {
        "optimizer",
        "geometry_converged",
        "scf_converged",
        "selected_strategy",
        "last_energy_hartree",
        "attempts",
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
    if not isinstance(final_scf, dict) or set(final_scf) != {
        "converged",
        "selected_strategy",
        "energy_hartree",
        "attempts",
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
    if not math.isclose(result.electronic_difference_kcal, expected_difference, abs_tol=1e-12):
        raise ResumeValidationError("stored electronic difference fails the locked formula")
    if not math.isclose(result.dft_deprot_electronic_kcal, expected_label, abs_tol=1e-12):
        raise ResumeValidationError("stored deprotonation label fails the locked formula")
    for key, expected in _success_flags().items():
        if payload.get(key) != expected:
            raise ResumeValidationError(f"stored safety flag drifted: {key}")
    return result


def _resume_if_valid(
    *, request: TwoEndpointRequest, output_root: Path
) -> TwoEndpointRunResult | None:
    marker_path = output_root / "_SUCCESS"
    success_path = output_root / "success.json"
    if not marker_path.exists() and not success_path.exists():
        if output_root.exists():
            unknown = {path.name for path in output_root.iterdir()} - {"attempts"}
            if unknown:
                raise ResumeValidationError("incomplete output root contains unknown state")
        return None
    if not marker_path.exists() or not success_path.exists():
        raise ResumeValidationError("success state is incomplete")
    top_level_names = {path.name for path in output_root.iterdir()}
    if top_level_names != {"_SUCCESS", "success.json", "attempts"}:
        raise ResumeValidationError("completed output root contains unexpected state")
    attempts_root = output_root / "attempts"
    if attempts_root.is_symlink() or not attempts_root.is_dir():
        raise ResumeValidationError("attempts root is unsafe")
    marker = _read_json_object(marker_path, error_cls=ResumeValidationError)
    _require_resume_keys(marker, {"schema_version", "success_sha256"}, "_SUCCESS")
    if marker["schema_version"] != SUCCESS_SCHEMA_VERSION:
        raise ResumeValidationError("success marker schema drifted")
    expected_success_hash = marker["success_sha256"]
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
        },
        "success.json",
    )
    if success["schema_version"] != SUCCESS_SCHEMA_VERSION or success["status"] != "success":
        raise ResumeValidationError("success.json status or schema drifted")
    expected_identity = _identity(request)
    for key, expected in expected_identity.items():
        if success.get(key) != expected:
            raise ResumeValidationError(f"resume identity mismatch: {key}")
    if success["request_id"] != request.request_id or success["inchikey"] != request.inchikey:
        raise ResumeValidationError("resume candidate identity mismatch")
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
) -> TwoEndpointRunResult:
    """Execute through an injected backend; private so Phase 7 has no public bypass."""

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
    deadline = time.monotonic() + request.timeout_seconds
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
        os.replace(temporary_attempt, final_attempt_dir)
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
                os.replace(temporary_attempt, final_attempt_dir)
            except Exception:
                shutil.rmtree(temporary_attempt, ignore_errors=True)
        raise TwoEndpointRunError(
            f"two-endpoint attempt failed at {stage}: {_safe_failure_message(error)}",
            exit_code=_failure_exit_code(error),
            attempt_dir=final_attempt_dir if final_attempt_dir.exists() else None,
        ) from error


def _supervision_failure_kind(result: _SupervisionResultLike) -> tuple[str, str, int] | None:
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


def _publish_supervisor_failure(
    *,
    request: TwoEndpointRequest,
    output_root: Path,
    attempt_id: str,
    error_type: str,
    error_message: str,
    exit_code: int,
    supervision: _SupervisionResultLike,
) -> Path:
    """Atomically publish one failure envelope after supervision has returned."""

    attempts_root = output_root / "attempts"
    final_attempt_dir = attempts_root / attempt_id
    if final_attempt_dir.exists() or final_attempt_dir.is_symlink():
        raise ResumeValidationError("attempt_id already exists before failure publication")
    temporary_attempt = Path(
        tempfile.mkdtemp(prefix=f".tmp-{attempt_id}-supervisor-failure-", dir=attempts_root)
    )
    failure_payload = {
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
        "supervision": {
            "outcome": supervision.outcome,
            "returncode": supervision.returncode,
            "timed_out": supervision.timed_out,
            "term_sent": supervision.term_sent,
            "kill_sent": supervision.kill_sent,
            "orphan_descendants_detected": supervision.orphan_descendants_detected,
            "process_started": supervision.process_started,
            "group_cleanup_confirmed": supervision.group_cleanup_confirmed,
            "direct_child_reaped": supervision.direct_child_reaped,
            "stdout_truncated": supervision.stdout_truncated,
            "stderr_truncated": supervision.stderr_truncated,
        },
    }
    try:
        _atomic_write_json(temporary_attempt / "failure.json", failure_payload)
        if {path.name for path in temporary_attempt.iterdir()} != {"failure.json"}:
            raise ResumeValidationError("supervisor failure envelope file set drifted")
        os.replace(temporary_attempt, final_attempt_dir)
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
) -> TwoEndpointRunResult:
    """Validate the isolated worker state before publishing its exact attempt."""

    if worker_output_root.is_symlink() or not worker_output_root.is_dir():
        raise ResumeValidationError("worker output root is unsafe")
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
    success_bytes = (worker_output_root / "success.json").read_bytes()
    marker_bytes = (worker_output_root / "_SUCCESS").read_bytes()
    os.replace(worker_attempt_dir, final_attempt_dir)
    try:
        _atomic_write_bytes(output_root / "success.json", success_bytes)
        _atomic_write_bytes(output_root / "_SUCCESS", marker_bytes)
    except Exception:
        (output_root / "_SUCCESS").unlink(missing_ok=True)
        (output_root / "success.json").unlink(missing_ok=True)
        raise
    return replace(worker_result, resumed=False)


def _execute_supervised_request(
    request: TwoEndpointRequest,
    output_root: Path,
    *,
    run_supervised: _RunSupervised,
    supervision_policy: object,
    attempt_id: str | None = None,
    python_executable: str | None = None,
) -> TwoEndpointRunResult:
    """Run a fixed-attempt worker and publish only parent-validated state."""

    if request.execution_authorized is not True:
        raise ExecutionNotAuthorizedError("frozen request does not authorize execution")
    _validate_output_root(output_root)
    resumed = _resume_if_valid(request=request, output_root=output_root)
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
    argv = [
        python_executable or sys.executable,
        "-I",
        "-B",
        "-c",
        _WORKER_BOOTSTRAP,
        str(source_root),
        "--request-path",
        str(request.request_path.resolve(strict=True)),
        "--output-root",
        str(worker_output_root.resolve(strict=True)),
        "--attempt-id",
        safe_attempt_id,
    ]
    try:
        supervision = run_supervised(
            argv,
            policy=supervision_policy,
            cwd=source_root,
            env=environment,
        )
    except Exception:
        # An unexpected supervisor exception cannot prove that a spawned group is
        # dead, so it must not be converted into a published attempt or cleaned.
        raise

    failure = _supervision_failure_kind(supervision)
    if not _supervision_safe_to_finalize(supervision):
        raise TwoEndpointRunError(
            "worker supervision could not prove process-group cleanup and child reap",
            exit_code=1,
            attempt_dir=None,
        )
    if failure is not None:
        error_type, error_message, exit_code = failure
        attempt_dir = _publish_supervisor_failure(
            request=request,
            output_root=output_root,
            attempt_id=safe_attempt_id,
            error_type=error_type,
            error_message=error_message,
            exit_code=exit_code,
            supervision=supervision,
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
        )
    except Exception as error:
        if final_attempt_dir.exists() or final_attempt_dir.is_symlink():
            # Publication had already moved the validated six-file attempt.  It
            # remains uncommitted (no _SUCCESS) and must not be overwritten with
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
            supervision=supervision,
        )
        shutil.rmtree(worker_output_root, ignore_errors=True)
        raise TwoEndpointRunError(
            "two-endpoint worker returned invalid success state",
            exit_code=1,
            attempt_dir=attempt_dir,
        ) from error
    shutil.rmtree(worker_output_root, ignore_errors=True)
    return result


def run_two_endpoint(request_path: Path, output_root: Path) -> TwoEndpointRunResult:
    """Public parent-supervised entry point, disabled before any side effect.

    No parameter can override the source gate.  A future reviewed source change
    must still satisfy the frozen request gate before importing the supervisor,
    spawning the worker, importing compute dependencies or creating output.
    """

    _ensure_execution_authorized()
    request = load_two_endpoint_request(request_path)
    if request.execution_authorized is not True:
        raise ExecutionNotAuthorizedError("frozen request does not authorize execution")
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
    )
    return _execute_supervised_request(
        request,
        output_root,
        run_supervised=supervised_runner,
        supervision_policy=policy,
    )
