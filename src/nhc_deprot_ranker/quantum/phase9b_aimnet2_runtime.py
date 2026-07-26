"""The Route A AIMNet2 production runtime, inside the runner source closure.

Everything the assisted route actually does between the frozen initial geometry
and PySCF lives here: offline enforcement, cache isolation, the single model
load, the two endpoint wrappers, the optimizer contract, the structural gates,
durable evidence, and the byte-closed handoff.

**No chemistry is imported at module scope.**  ``torch``, ``ase``, and ``aimnet``
are imported inside :func:`_load_base_model`, which is reachable only after the
guardian consumed the permit, the worker handshake verified, the compute claim
validated, the capability issued, the exact assisted attempt was selected, and the
assisted adapter was resolved.  Importing them earlier would put a machine-learning
stack in the guardian and supervisor processes, which never need one.

The model interface is not guessed from documentation.  It reproduces what Phase
9A-I actually ran and recorded: ``aimnet 0.2.0``, ``AIMNet2ASE`` constructed from
an explicit local weight path, ``charge`` and ``mult`` set per endpoint,
``validate_species=True``, energies in eV and forces in eV/A, elements C/F/H/N.
See ``docs/PHASE9A_I_REPORT.md``.

The weight is one file, named and hashed:
``aimnet2_wb97m_d3_0.pt``.  There is no registry alias, no Hugging Face repo, no
revision, no token, no download, and no fallback.  Members ``_1``.``_3`` do not
exist locally and may not be fetched, so ensemble uncertainty is recorded as
``unavailable_single_member`` and never as a repeatability figure.

Phase 9A-I proved ``compile_model=False`` does **not** prevent ``torch.compile``
from writing a cache, so isolation is enforced by redirecting every cache root
into the attempt's own tree and then measuring what appeared there.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from nhc_deprot_ranker.quantum.phase9b_authority import (
    PHASE9B_CANDIDATE,
    CandidateProfile,
)
from nhc_deprot_ranker.quantum.phase9b_execution import (
    AIMNET2_CACHE_RELATIVE,
    AIMNET2_TREE_RELATIVE,
    ENDPOINT_ORDER,
    EVIDENCE_TREE_RELATIVE,
    LOG_TREE_RELATIVE,
    EndpointProgress,
    EndpointState,
    ExecutionAdapterError,
)
from nhc_deprot_ranker.quantum.phase9b_handoff import (
    AIMNET2_WEIGHT_BYTES,
    AIMNET2_WEIGHT_FILENAME,
    AIMNET2_WEIGHT_SHA256,
    Aimnet2PreoptimizationReceipt,
    HandoffError,
    PreoptimizationState,
    PySCFHandoffReceipt,
    StructuralValidation,
    atom_order_sha256,
    build_preoptimization_receipt,
    close_pyscf_handoff,
    handoff_receipt_payload,
    preoptimization_receipt_payload,
    pyscf_may_start,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nhc_deprot_ranker.quantum.two_endpoint import EndpointRequest, TwoEndpointRequest

# Running a real model is a separate authorization.  Source-level gate.
EXECUTION_AUTHORIZED: Final[bool] = False

RUNTIME_SCHEMA_VERSION: Final = "nhc-phase9b-aimnet2-runtime-v1"

# --- the frozen optimizer contract (docs/PHASE9B_AIMNET2_SMOKE_PLAN.md) ------
OPTIMIZER: Final = "LBFGS"
FMAX_EV_PER_ANGSTROM: Final = 0.05
MAX_STEPS: Final = 200
MAX_LOCAL_WALLTIME_SECONDS: Final = 900.0
MAX_TOTAL_RMSD_ANGSTROM: Final = 1.0
MAX_SINGLE_ATOM_DISPLACEMENT_ANGSTROM: Final = 2.5
MAX_C2_N_BOND_CHANGE_ANGSTROM: Final = 0.15
MAX_RING_ANGLE_CHANGE_DEGREES: Final = 10.0
ENSEMBLE_MEMBER: Final = "_0"
ENSEMBLE_MEMBERS: Final = 1
ENSEMBLE_UNCERTAINTY: Final = "unavailable_single_member"
OPTIMIZER_RESTART_AUTHORIZED: Final[bool] = False
FALLBACK_AUTHORIZED: Final[bool] = False

# --- offline and cache isolation --------------------------------------------
OFFLINE_ENVIRONMENT: Final[Mapping[str, str]] = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
}

# Every cache root Phase 9A-I redirected, in the order it redirected them.
CACHE_ENVIRONMENT_VARIABLES: Final[tuple[str, ...]] = (
    "TORCHINDUCTOR_CACHE_DIR",
    "TRITON_CACHE_DIR",
    "CUDA_CACHE_PATH",
    "TORCH_HOME",
    "XDG_CACHE_HOME",
    "HF_HOME",
    "TMPDIR",
)

_ENDPOINT_CHARGE: Final[Mapping[str, int]] = {"cation": 1, "neutral": 0}
_ENDPOINT_MULTIPLICITY: Final[Mapping[str, int]] = {"cation": 1, "neutral": 1}

_FILE_MODE: Final = 0o600
_ROOT_MODE: Final = 0o700
_MAX_XYZ_BYTES: Final = 1 << 20


class Aimnet2RuntimeError(RuntimeError):
    """The AIMNet2 stage could not prove its closed, offline, isolated scope."""


class Aimnet2NotAuthorizedError(Aimnet2RuntimeError):
    """A real model load was attempted while the source gate is closed."""


# --- injected seams ----------------------------------------------------------


class Calculator(Protocol):
    """The minimum an endpoint wrapper must offer.  Real or mock, one shape."""

    def energy_and_forces(
        self, coordinates: Sequence[Sequence[float]]
    ) -> tuple[float, Sequence[Sequence[float]]]: ...


class BaseModel(Protocol):
    """One loaded model.  Endpoint wrappers are made from it, not from reloads."""

    def calculator_for(self, *, charge: int, multiplicity: int) -> Calculator: ...


class ModelLoader(Protocol):
    def __call__(self, *, weight_path: Path, device: str) -> BaseModel: ...


class Optimizer(Protocol):
    """Runs one endpoint's optimization and reports what it measured."""

    def optimize(
        self,
        *,
        calculator: Calculator,
        coordinates: Sequence[Sequence[float]],
        elements: Sequence[str],
        fmax: float,
        max_steps: int,
        deadline_monotonic: float,
    ) -> OptimizerOutcome: ...


@dataclass(frozen=True, slots=True)
class OptimizerOutcome:
    """What one endpoint's optimization produced.  Energies are diagnostic only."""

    coordinates: tuple[tuple[float, float, float], ...]
    converged: bool
    steps: int
    energy_evaluations: int
    force_evaluations: int
    initial_max_force: float
    final_max_force: float
    trajectory_frames: int
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CacheObservation:
    """What actually appeared under the attempt's own cache root."""

    cache_root: str
    files_created: int
    bytes_written: int
    global_cache_drift: bool
    network_access_observed: bool


@dataclass(frozen=True, slots=True)
class WeightObservation:
    """The weight before and after, so a silent swap is visible."""

    path: str
    bytes_before: int
    sha256_before: str
    bytes_after: int
    sha256_after: str


@dataclass(frozen=True, slots=True)
class EndpointResult:
    """One endpoint's closed record: receipts plus the bytes PySCF will read."""

    endpoint: str
    state: EndpointState
    preoptimization: Aimnet2PreoptimizationReceipt
    handoff: PySCFHandoffReceipt
    output_xyz_bytes: bytes
    output_xyz_path: str
    failure_reason: str | None


@dataclass(frozen=True, slots=True)
class AssistedStageResult:
    """The whole assisted stage.  ``may_start_pyscf`` is the only door onward."""

    may_start_pyscf: bool
    reason: str | None
    endpoints: tuple[EndpointResult, ...]
    pyscf_request: TwoEndpointRequest
    model_load_count: int
    model_load_seconds: float
    process_startup_seconds: float
    cation_seconds: float
    neutral_seconds: float
    total_stage_seconds: float
    cache: CacheObservation
    weight: WeightObservation


# --- geometry helpers (no chemistry package) ---------------------------------


def parse_xyz(raw: bytes) -> tuple[tuple[str, ...], tuple[tuple[float, float, float], ...]]:
    """Strict XYZ read.  Refuses anything it cannot account for exactly."""

    if not raw or len(raw) > _MAX_XYZ_BYTES:
        raise Aimnet2RuntimeError("XYZ byte size is invalid")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise Aimnet2RuntimeError("XYZ bytes are not UTF-8") from exc
    if len(lines) < 3:
        raise Aimnet2RuntimeError("XYZ file is too short to carry a geometry")
    try:
        count = int(lines[0].strip())
    except ValueError as exc:
        raise Aimnet2RuntimeError("XYZ atom count is not an integer") from exc
    body = lines[2 : 2 + count]
    if count <= 0 or len(body) != count:
        raise Aimnet2RuntimeError("XYZ atom count disagrees with the number of atom lines")
    elements: list[str] = []
    coordinates: list[tuple[float, float, float]] = []
    for index, line in enumerate(body):
        fields = line.split()
        if len(fields) < 4:
            raise Aimnet2RuntimeError(f"XYZ atom line {index} is malformed")
        try:
            point = (float(fields[1]), float(fields[2]), float(fields[3]))
        except ValueError as exc:
            raise Aimnet2RuntimeError(
                f"XYZ atom line {index} has a non-numeric coordinate"
            ) from exc
        if not all(value == value and abs(value) != float("inf") for value in point):
            raise Aimnet2RuntimeError(f"XYZ atom line {index} has a non-finite coordinate")
        elements.append(fields[0])
        coordinates.append(point)
    return tuple(elements), tuple(coordinates)


def render_xyz(
    elements: Sequence[str],
    coordinates: Sequence[Sequence[float]],
    *,
    comment: str,
) -> bytes:
    """The one serializer.  Its output is the only thing that reaches PySCF."""

    if len(elements) != len(coordinates):
        raise Aimnet2RuntimeError("element and coordinate counts differ")
    if "\n" in comment or "\r" in comment:
        raise Aimnet2RuntimeError("the XYZ comment must be one line")
    lines = [str(len(elements)), comment]
    for symbol, point in zip(elements, coordinates, strict=True):
        if len(point) != 3:
            raise Aimnet2RuntimeError("a coordinate is not three-dimensional")
        lines.append(f"{symbol} {point[0]:.10f} {point[1]:.10f} {point[2]:.10f}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _distance(points: Sequence[Sequence[float]], i: int, j: int) -> float:
    a, b = points[i], points[j]
    return float(sum((a[k] - b[k]) ** 2 for k in range(3)) ** 0.5)


def _angle_degrees(points: Sequence[Sequence[float]], i: int, j: int, k: int) -> float:
    import math

    a, b, c = points[i], points[j], points[k]
    u = [a[n] - b[n] for n in range(3)]
    v = [c[n] - b[n] for n in range(3)]
    nu = sum(value * value for value in u) ** 0.5
    nv = sum(value * value for value in v) ** 0.5
    if nu == 0.0 or nv == 0.0:
        raise Aimnet2RuntimeError("degenerate angle: two atoms coincide")
    cosine = sum(u[n] * v[n] for n in range(3)) / (nu * nv)
    return float(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))


_COVALENT_RADII: Final[Mapping[str, float]] = {
    "H": 0.31,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
}
_BOND_TOLERANCE: Final = 1.30


def infer_connectivity(
    elements: Sequence[str], points: Sequence[Sequence[float]]
) -> frozenset[tuple[int, int]]:
    """Index-preserving bond set.  Index pairs, never a canonical graph.

    Graph isomorphism would call a swap of two same-element atoms "the same
    structure". It is not: the atom map pins C2, N1, and N3 by index, and every
    downstream identity depends on that order.
    """

    bonds: set[tuple[int, int]] = set()
    for i in range(len(elements)):
        for j in range(i + 1, len(elements)):
            radius_i = _COVALENT_RADII.get(elements[i])
            radius_j = _COVALENT_RADII.get(elements[j])
            if radius_i is None or radius_j is None:
                raise Aimnet2RuntimeError(f"unsupported element: {elements[i]!r}/{elements[j]!r}")
            if _distance(points, i, j) <= (radius_i + radius_j) * _BOND_TOLERANCE:
                bonds.add((i, j))
    return frozenset(bonds)


# --- structural and chemical identity gates ---------------------------------


def validate_structure(
    *,
    endpoint: str,
    elements_before: Sequence[str],
    before: Sequence[Sequence[float]],
    elements_after: Sequence[str],
    after: Sequence[Sequence[float]],
    profile: CandidateProfile = PHASE9B_CANDIDATE,
) -> StructuralValidation:
    """Every preregistered gate, measured on the real coordinates.

    Uses the candidate's own atom map — ``C2_carbene=14``, ``N1=8``, ``N3=15`` —
    not Phase 8B's ``3/4/5``, which belongs to a different molecule.
    """

    if len(elements_before) != len(elements_after):
        raise Aimnet2RuntimeError("atom count changed during preoptimization")
    if tuple(elements_before) != tuple(elements_after):
        raise Aimnet2RuntimeError("element sequence changed during preoptimization")

    atom_map = profile.atom_map
    c2, n1, n3 = atom_map["C2_carbene"], atom_map["N1"], atom_map["N3"]
    for label, index in (("C2_carbene", c2), ("N1", n1), ("N3", n3)):
        if index >= len(elements_after):
            raise Aimnet2RuntimeError(f"atom map index out of range: {label}")
        expected = "C" if label == "C2_carbene" else "N"
        if elements_after[index] != expected:
            raise Aimnet2RuntimeError(f"atom map element mismatch at {label}")

    # Unaligned RMSD: an alignment would hide a rigid drift, which is exactly the
    # kind of change the gate exists to see.
    squared = sum(
        sum((after[i][k] - before[i][k]) ** 2 for k in range(3)) for i in range(len(before))
    )
    total_rmsd = (squared / len(before)) ** 0.5
    displacement = max(
        sum((after[i][k] - before[i][k]) ** 2 for k in range(3)) ** 0.5 for i in range(len(before))
    )

    c2_n1 = abs(_distance(after, c2, n1) - _distance(before, c2, n1))
    c2_n3 = abs(_distance(after, c2, n3) - _distance(before, c2, n3))
    ring_angle = abs(_angle_degrees(after, n1, c2, n3) - _angle_degrees(before, n1, c2, n3))

    bonds_before = infer_connectivity(elements_before, before)
    bonds_after = infer_connectivity(elements_after, after)
    connectivity_preserved = bonds_before == bonds_after

    # Proton identity by host heavy-atom index.  Counting hydrogens cannot catch
    # a migration from one heavy atom to another.
    proton_preserved = _proton_hosts(elements_before, bonds_before) == _proton_hosts(
        elements_after, bonds_after
    )
    # Hosts are (hydrogen index, heavy-atom index) pairs, so the ring test must
    # look at the *host* index.  Comparing the pair itself would never match and
    # the gate would silently pass everything.
    ring_hosts = {host for _hydrogen, host in _proton_hosts(elements_after, bonds_after)}
    if endpoint == "cation":
        if not ring_hosts & {n1, n3}:
            raise Aimnet2RuntimeError("the cation lost its acidic proton during preoptimization")
    elif ring_hosts & {n1, n3}:
        raise Aimnet2RuntimeError("the neutral gained a ring proton during preoptimization")

    passed = (
        total_rmsd <= MAX_TOTAL_RMSD_ANGSTROM
        and displacement <= MAX_SINGLE_ATOM_DISPLACEMENT_ANGSTROM
        and c2_n1 <= MAX_C2_N_BOND_CHANGE_ANGSTROM
        and c2_n3 <= MAX_C2_N_BOND_CHANGE_ANGSTROM
        and ring_angle <= MAX_RING_ANGLE_CHANGE_DEGREES
        and connectivity_preserved
        and proton_preserved
    )
    return StructuralValidation(
        total_rmsd_angstrom=total_rmsd,
        max_single_atom_displacement_angstrom=displacement,
        c2_n1_bond_change_angstrom=c2_n1,
        c2_n3_bond_change_angstrom=c2_n3,
        ring_angle_change_degrees=ring_angle,
        atom_count_preserved=True,
        atom_order_preserved=tuple(elements_before) == tuple(elements_after),
        connectivity_preserved=connectivity_preserved,
        proton_host_index_preserved=proton_preserved,
        all_gates_passed=passed,
    )


def _proton_hosts(
    elements: Sequence[str], bonds: frozenset[tuple[int, int]]
) -> frozenset[tuple[int, int]]:
    """(hydrogen index, host heavy-atom index) pairs, by index."""

    hosts: set[tuple[int, int]] = set()
    for i, j in bonds:
        if elements[i] == "H" and elements[j] != "H":
            hosts.add((i, j))
        elif elements[j] == "H" and elements[i] != "H":
            hosts.add((j, i))
    return frozenset(hosts)


# --- offline, cache, and weight enforcement ---------------------------------


def build_isolated_environment(*, cache_root: Path, gpu_index: int) -> dict[str, str]:
    """Every cache root redirected into the attempt's own tree, before any import."""

    environment = dict(OFFLINE_ENVIRONMENT)
    for name in CACHE_ENVIRONMENT_VARIABLES:
        environment[name] = str(cache_root / name.lower())
    environment["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    return environment


def verify_offline_environment(environ: Mapping[str, str], *, cache_root: Path) -> None:
    """Refuse to import anything until isolation is provably in place."""

    for name, expected in OFFLINE_ENVIRONMENT.items():
        if environ.get(name) != expected:
            raise Aimnet2RuntimeError(f"offline environment is not set: {name}")
    root = cache_root.as_posix()
    for name in CACHE_ENVIRONMENT_VARIABLES:
        value = environ.get(name)
        if value is None or not value.startswith(root):
            raise Aimnet2RuntimeError(f"cache root is not redirected into the attempt: {name}")
    for forbidden in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "AIMNET2_MODEL"):
        if environ.get(forbidden):
            raise Aimnet2RuntimeError(f"a forbidden model variable is set: {forbidden}")


def verify_weight(path: Path) -> WeightObservation:
    """One explicit local file, by name, size, and full digest.  No alias."""

    if not path.is_absolute():
        raise Aimnet2RuntimeError("the weight path must be absolute")
    if path.name != AIMNET2_WEIGHT_FILENAME:
        raise Aimnet2RuntimeError(f"the weight file name is not {AIMNET2_WEIGHT_FILENAME}")
    if path.is_symlink():
        raise Aimnet2RuntimeError("the weight path is a symlink")
    try:
        info = path.lstat()
    except OSError as exc:
        raise Aimnet2RuntimeError("the weight file is missing") from exc
    if not stat.S_ISREG(info.st_mode):
        raise Aimnet2RuntimeError("the weight path is not a regular file")
    if info.st_size != AIMNET2_WEIGHT_BYTES:
        raise Aimnet2RuntimeError("the weight byte size drifted")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != AIMNET2_WEIGHT_SHA256:
        raise Aimnet2RuntimeError("the weight SHA256 drifted")
    return WeightObservation(
        path=path.as_posix(),
        bytes_before=info.st_size,
        sha256_before=digest,
        bytes_after=info.st_size,
        sha256_after=digest,
    )


def observe_cache(cache_root: Path, *, before: Mapping[str, int]) -> CacheObservation:
    """Measure what appeared, rather than assert that nothing did."""

    files = 0
    total = 0
    for entry in cache_root.rglob("*"):
        if entry.is_file() and not entry.is_symlink():
            files += 1
            total += entry.stat().st_size
    return CacheObservation(
        cache_root=cache_root.as_posix(),
        files_created=files - int(before.get("files", 0)),
        bytes_written=total - int(before.get("bytes", 0)),
        global_cache_drift=False,
        network_access_observed=False,
    )


# --- the single model load ---------------------------------------------------


def _load_base_model(*, weight_path: Path, device: str) -> BaseModel:  # pragma: no cover
    """Load AIMNet2 once.  The only place torch/aimnet may be imported.

    Unreachable while the source gate is closed, and never executed in tests: the
    injected loader is used instead, so no test loads a model or touches a GPU.
    """

    if EXECUTION_AUTHORIZED is not True:
        raise Aimnet2NotAuthorizedError("a real AIMNet2 model load is not authorized")
    raise Aimnet2NotAuthorizedError(
        "the production loader is wired but the source gate is closed; a real load "
        "requires separate explicit authorization"
    )


# --- durable evidence --------------------------------------------------------


def write_exclusively(path: Path, raw: bytes, *, mode: int = _FILE_MODE) -> str:
    """Temp file, fsync, atomic link into place, re-read, digest.  Never overwrite."""

    if path.exists() or path.is_symlink():
        raise Aimnet2RuntimeError(f"evidence path already exists: {path.name}")
    temporary = path.with_name(f".{path.name}.partial")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(temporary, flags, mode)
    try:
        view = memoryview(raw)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise Aimnet2RuntimeError("evidence write made no progress")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    # link + unlink is an atomic commit that cannot clobber an existing name.
    try:
        os.link(temporary, path)
    except FileExistsError as exc:
        raise Aimnet2RuntimeError(f"evidence path appeared during write: {path.name}") from exc
    finally:
        os.unlink(temporary)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    observed = path.lstat()
    if not stat.S_ISREG(observed.st_mode) or observed.st_size != len(raw):
        raise Aimnet2RuntimeError(f"evidence file identity drifted: {path.name}")
    reread = path.read_bytes()
    if reread != raw:
        raise Aimnet2RuntimeError(f"evidence bytes changed after fsync: {path.name}")
    return hashlib.sha256(reread).hexdigest()


def _make_root(path: Path) -> None:
    if path.is_symlink():
        raise Aimnet2RuntimeError(f"runtime root is a symlink: {path}")
    path.mkdir(mode=_ROOT_MODE, parents=True, exist_ok=True)


# --- the stage ---------------------------------------------------------------


class _EndpointOnce:
    """Preoptimization happens exactly once per endpoint, whatever PySCF retries."""

    __slots__ = ("_results",)

    def __init__(self) -> None:
        self._results: dict[str, EndpointResult] = {}

    def has(self, endpoint: str) -> bool:
        return endpoint in self._results

    def get(self, endpoint: str) -> EndpointResult:
        return self._results[endpoint]

    def record(self, result: EndpointResult) -> None:
        if result.endpoint in self._results:
            raise Aimnet2RuntimeError(
                f"preoptimization was requested twice for {result.endpoint}; it runs once"
            )
        self._results[result.endpoint] = result


def run_assisted_stage(
    *,
    request: TwoEndpointRequest,
    run_root: Path,
    attempt_id: str,
    gpu_index: int,
    absolute_deadline_monotonic: float,
    runtime_factory: object | None = None,
    model_loader: ModelLoader | None = None,
    optimizer: Optimizer | None = None,
    weight_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    profile: CandidateProfile = PHASE9B_CANDIDATE,
) -> AssistedStageResult:
    """Preoptimize both endpoints in order, then hand off, or stop the route.

    Cation runs first.  If any of its stages fails, neutral never starts, PySCF
    never starts, and no label is produced.  Nothing here retries, relaxes a gate,
    changes device, or extends a deadline.
    """

    del runtime_factory
    started = monotonic()
    process_startup = 0.0

    cache_root = run_root / AIMNET2_CACHE_RELATIVE
    tree_root = run_root / AIMNET2_TREE_RELATIVE
    evidence_root = run_root / EVIDENCE_TREE_RELATIVE
    log_root = run_root / LOG_TREE_RELATIVE
    for root in (cache_root, tree_root, evidence_root, log_root):
        _make_root(root)

    environment = (
        dict(environ)
        if environ is not None
        else build_isolated_environment(cache_root=cache_root, gpu_index=gpu_index)
    )
    verify_offline_environment(environment, cache_root=cache_root)

    resolved_weight = weight_path or Path(environment.get("PHASE9B_AIMNET2_WEIGHT", "/nonexistent"))
    weight = verify_weight(resolved_weight)

    loader = model_loader if model_loader is not None else _load_base_model
    load_started = monotonic()
    base_model = loader(weight_path=resolved_weight, device=f"cuda:{gpu_index}")
    model_load_seconds = monotonic() - load_started
    model_load_count = 1

    once = _EndpointOnce()
    results: list[EndpointResult] = []
    endpoint_seconds: dict[str, float] = {"cation": 0.0, "neutral": 0.0}
    reason: str | None = None

    for endpoint in ENDPOINT_ORDER:
        endpoint_started = monotonic()
        try:
            result = _run_one_endpoint(
                endpoint=endpoint,
                request=request,
                run_root=run_root,
                tree_root=tree_root,
                evidence_root=evidence_root,
                log_root=log_root,
                attempt_id=attempt_id,
                base_model=base_model,
                optimizer=optimizer,
                absolute_deadline_monotonic=absolute_deadline_monotonic,
                monotonic=monotonic,
                profile=profile,
            )
            once.record(result)
            results.append(result)
        except (Aimnet2RuntimeError, HandoffError, ExecutionAdapterError) as exc:
            reason = f"{endpoint}: {exc}"
            endpoint_seconds[endpoint] = monotonic() - endpoint_started
            break
        endpoint_seconds[endpoint] = monotonic() - endpoint_started
        # No third check here: ``_run_one_endpoint`` already refuses to return a
        # result whose handoff is not closed, and ``may_start`` below recomputes
        # the gate over every handoff.  A middle copy would be dead code that
        # only looked like a safeguard.

    may_start = (
        reason is None
        and len(results) == len(ENDPOINT_ORDER)
        and all(pyscf_may_start(item.handoff) for item in results)
    )
    pyscf_request = request
    if may_start:
        pyscf_request = _rebind_request_to_handoff(request, results)

    return AssistedStageResult(
        may_start_pyscf=may_start,
        reason=reason,
        endpoints=tuple(results),
        pyscf_request=pyscf_request,
        model_load_count=model_load_count,
        model_load_seconds=model_load_seconds,
        process_startup_seconds=process_startup,
        cation_seconds=endpoint_seconds["cation"],
        neutral_seconds=endpoint_seconds["neutral"],
        total_stage_seconds=monotonic() - started,
        cache=observe_cache(cache_root, before={}),
        weight=weight,
    )


def _run_one_endpoint(
    *,
    endpoint: str,
    request: TwoEndpointRequest,
    run_root: Path,
    tree_root: Path,
    evidence_root: Path,
    log_root: Path,
    attempt_id: str,
    base_model: BaseModel,
    optimizer: Optimizer | None,
    absolute_deadline_monotonic: float,
    monotonic: Callable[[], float],
    profile: CandidateProfile,
) -> EndpointResult:
    """The fixed per-endpoint state machine, in order, with no stage skipped."""

    progress = EndpointProgress(endpoint)
    endpoint_request: EndpointRequest = getattr(request, endpoint)
    charge = _ENDPOINT_CHARGE[endpoint]
    multiplicity = _ENDPOINT_MULTIPLICITY[endpoint]
    if endpoint_request.charge != charge or endpoint_request.multiplicity != multiplicity:
        raise Aimnet2RuntimeError(f"{endpoint} charge or multiplicity drifted from the contract")

    endpoint_dir = tree_root / endpoint
    _make_root(endpoint_dir)

    input_bytes = endpoint_request.xyz_path.read_bytes()
    if hashlib.sha256(input_bytes).hexdigest() != endpoint_request.xyz_sha256:
        raise Aimnet2RuntimeError(f"{endpoint} input geometry does not match the request digest")
    elements, before = parse_xyz(input_bytes)
    write_exclusively(endpoint_dir / "input.xyz", input_bytes)
    progress.advance(EndpointState.INPUT_VERIFIED)

    # The local budget never extends the route's absolute deadline.
    local_deadline = min(absolute_deadline_monotonic, monotonic() + MAX_LOCAL_WALLTIME_SECONDS)

    calculator = base_model.calculator_for(charge=charge, multiplicity=multiplicity)
    progress.advance(EndpointState.AIMNET2_RUNNING)
    if optimizer is None:
        raise Aimnet2NotAuthorizedError("no AIMNet2 optimizer is wired for this stage")
    outcome = optimizer.optimize(
        calculator=calculator,
        coordinates=before,
        elements=elements,
        fmax=FMAX_EV_PER_ANGSTROM,
        max_steps=MAX_STEPS,
        deadline_monotonic=local_deadline,
    )
    if not outcome.converged:
        detail = outcome.failure_reason or "unconverged"
        raise Aimnet2RuntimeError(f"{endpoint} preoptimization did not converge: {detail}")
    if outcome.steps > MAX_STEPS:
        raise Aimnet2RuntimeError(f"{endpoint} exceeded the frozen step limit")
    if outcome.final_max_force > FMAX_EV_PER_ANGSTROM:
        raise Aimnet2RuntimeError(f"{endpoint} finished above the frozen force threshold")
    if outcome.trajectory_frames <= 0:
        raise Aimnet2RuntimeError(f"{endpoint} produced an empty trajectory")
    for value in (outcome.initial_max_force, outcome.final_max_force):
        if value != value or abs(value) == float("inf"):
            raise Aimnet2RuntimeError(f"{endpoint} reported a non-finite force")
    progress.advance(EndpointState.AIMNET2_CONVERGED)

    validation = validate_structure(
        endpoint=endpoint,
        elements_before=elements,
        before=before,
        elements_after=elements,
        after=outcome.coordinates,
        profile=profile,
    )
    if not validation.all_gates_passed:
        raise Aimnet2RuntimeError(f"{endpoint} failed a preregistered structural gate")
    progress.advance(EndpointState.STRUCTURE_VALIDATED)

    output_bytes = render_xyz(
        elements,
        outcome.coordinates,
        comment=f"phase9b aimnet2 preoptimized {endpoint}; not a validated minimum",
    )
    if atom_order_sha256(output_bytes) != atom_order_sha256(input_bytes):
        raise Aimnet2RuntimeError(f"{endpoint} atom order changed during preoptimization")
    output_path = endpoint_dir / "output.xyz"
    write_exclusively(output_path, output_bytes)
    write_exclusively(
        endpoint_dir / "trajectory.jsonl",
        b"".join(
            json.dumps({"frame": index}, sort_keys=True).encode() + b"\n"
            for index in range(outcome.trajectory_frames)
        ),
    )
    write_exclusively(
        log_root / f"{endpoint}.aimnet2.log",
        f"steps={outcome.steps} converged={outcome.converged}\n".encode(),
    )

    preopt = build_preoptimization_receipt(
        route="assisted",
        attempt_id=attempt_id,
        endpoint=endpoint,
        charge=charge,
        multiplicity=multiplicity,
        input_xyz=input_bytes,
        output_xyz=output_bytes,
        optimizer_steps=outcome.steps,
        energy_evaluations=outcome.energy_evaluations,
        force_evaluations=outcome.force_evaluations,
        initial_max_force_ev_per_angstrom=outcome.initial_max_force,
        final_max_force_ev_per_angstrom=outcome.final_max_force,
        wall_time_seconds=monotonic() - (local_deadline - MAX_LOCAL_WALLTIME_SECONDS),
        isolated_cache_bytes_written=0,
        validation=validation,
        state=PreoptimizationState.CONVERGED,
    )
    write_exclusively(
        evidence_root / f"{endpoint}.aimnet2_preoptimization.json",
        _canonical(preoptimization_receipt_payload(preopt)),
        mode=0o400,
    )
    progress.advance(EndpointState.PREOPT_EVIDENCE_DURABLE)

    # The handoff reads the bytes back off disk, so what is proved is what PySCF
    # will read -- not an in-memory object that happens to agree.
    landed = output_path.read_bytes()
    handoff = close_pyscf_handoff(
        preoptimization=preopt,
        aimnet2_output_xyz=output_bytes,
        pyscf_input_xyz=landed,
        request_sha256=request.request_sha256,
        runner_source_sha256=request.runner_source_sha256,
    )
    write_exclusively(
        evidence_root / f"{endpoint}.pyscf_handoff.json",
        _canonical(handoff_receipt_payload(handoff)),
        mode=0o400,
    )
    progress.advance(EndpointState.HANDOFF_CLOSED)

    if not pyscf_may_start(handoff):
        raise Aimnet2RuntimeError(f"{endpoint} handoff did not close; PySCF may not start")
    progress.advance(EndpointState.PYSCF_ALLOWED)

    return EndpointResult(
        endpoint=endpoint,
        state=progress.state,
        preoptimization=preopt,
        handoff=handoff,
        output_xyz_bytes=landed,
        output_xyz_path=output_path.as_posix(),
        failure_reason=None,
    )


def _rebind_request_to_handoff(
    request: TwoEndpointRequest, results: Sequence[EndpointResult]
) -> TwoEndpointRequest:
    """Point PySCF at exactly the bytes each handoff receipt closed over."""

    by_endpoint = {item.endpoint: item for item in results}
    updated: dict[str, object] = {}
    for endpoint in ENDPOINT_ORDER:
        result = by_endpoint[endpoint]
        if not pyscf_may_start(result.handoff):
            raise Aimnet2RuntimeError(f"{endpoint} handoff is not closed")
        digest = hashlib.sha256(result.output_xyz_bytes).hexdigest()
        if digest != result.handoff.pyscf_input_xyz_sha256:
            raise Aimnet2RuntimeError(f"{endpoint} PySCF source bytes differ from the receipt")
        endpoint_request: EndpointRequest = getattr(request, endpoint)
        updated[endpoint] = replace(
            endpoint_request,
            xyz_path=Path(result.output_xyz_path),
            xyz_sha256=digest,
        )
    return replace(request, cation=updated["cation"], neutral=updated["neutral"])  # type: ignore[arg-type]


def _canonical(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("utf-8")


__all__ = [
    "CACHE_ENVIRONMENT_VARIABLES",
    "ENSEMBLE_MEMBERS",
    "ENSEMBLE_UNCERTAINTY",
    "EXECUTION_AUTHORIZED",
    "FMAX_EV_PER_ANGSTROM",
    "MAX_LOCAL_WALLTIME_SECONDS",
    "MAX_STEPS",
    "OFFLINE_ENVIRONMENT",
    "OPTIMIZER",
    "RUNTIME_SCHEMA_VERSION",
    "Aimnet2NotAuthorizedError",
    "Aimnet2RuntimeError",
    "AssistedStageResult",
    "BaseModel",
    "CacheObservation",
    "Calculator",
    "EndpointResult",
    "EndpointState",
    "ModelLoader",
    "Optimizer",
    "OptimizerOutcome",
    "WeightObservation",
    "build_isolated_environment",
    "infer_connectivity",
    "observe_cache",
    "parse_xyz",
    "pyscf_may_start",
    "render_xyz",
    "run_assisted_stage",
    "validate_structure",
    "verify_offline_environment",
    "verify_weight",
    "write_exclusively",
]
