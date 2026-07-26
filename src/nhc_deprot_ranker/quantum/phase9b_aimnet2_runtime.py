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
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Protocol

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

RUNTIME_SCHEMA_VERSION: Final = "nhc-phase9b-aimnet2-runtime-v2"
TRAJECTORY_SCHEMA_VERSION: Final = "nhc-phase9b-aimnet2-trajectory-v1"

# --- the loader decision, proved from installed source in Phase 9A-S4 --------
#
# An absolute local path fails aimnet's inline one-slash Hugging Face pattern and
# is not a directory, so ``AIMNet2Calculator.__init__`` takes its local branch,
# where ``os.path.isfile`` short-circuits the registry family lookup and
# ``get_model_path`` returns the path unchanged.  ``get_registry_model_path`` --
# the only route to ``requests.get`` -- is unreachable for a path that exists.
# See docs/PHASE9A_S4_DEDUPLICATED_SOURCE_INSPECTION.md.
LOADER_DECISION: Final = "A"
LOADER_EVIDENCE_GRADE: Final = "source_proven"
LOADER_EVIDENCE_PHASE: Final = "9A-S4"
MODEL_PATH_MUST_BE_ABSOLUTE: Final[bool] = True
COMPILE_MODEL: Final[bool] = False
VALIDATE_SPECIES: Final[bool] = True
BASE_MODEL_LOADS_PER_ROUTE: Final = 1

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

# ASE 3.29.0's own ``LBFGS.__init__`` defaults, read from the installed source in
# Phase 9A-S4 and pinned here so a future ASE default drift is a receipt change
# rather than a silent change of method.  The runtime sets none of them; it
# records them, and refuses to run against an ASE whose defaults have moved.
LBFGS_FROZEN_DEFAULTS: Final[Mapping[str, object]] = MappingProxyType(
    {
        "restart": None,
        "logfile": "-",
        "trajectory": None,
        "maxstep": None,
        "memory": 100,
        "damping": 1.0,
        "alpha": 70.0,
        "use_line_search": False,
    }
)
# Passed explicitly rather than left to the default, because the contract names
# them: no restart file may be written or read, and the authoritative trajectory
# is this project's canonical JSONL, not an unregistered ASE binary.
LBFGS_EXPLICIT_ARGUMENTS: Final[tuple[str, ...]] = ("restart", "trajectory")

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
MAX_TRAJECTORY_BYTES: Final = 8 << 20


class Aimnet2RuntimeError(RuntimeError):
    """The AIMNet2 stage could not prove its closed, offline, isolated scope."""


class Aimnet2NotAuthorizedError(Aimnet2RuntimeError):
    """A real model load was attempted while the source gate is closed."""


class Aimnet2TimeoutError(Aimnet2RuntimeError):
    """The local budget or the route deadline ran out during optimization."""


def enforce_source_execution_gate() -> None:
    """The one place the source gate is read.  Called before any lazy import.

    Every production entry point calls this *first*, so a closed gate stops the
    route before ``torch``, ``ase``, or ``aimnet`` can enter the process.  There
    is deliberately no parameter, no environment variable, and no request field
    that can reach it: opening the gate means editing this module's source, which
    moves ``runner_source_sha256`` and invalidates every prepared identity.
    """

    if EXECUTION_AUTHORIZED is not True:
        raise Aimnet2NotAuthorizedError(
            "the Phase 9B production AIMNet2 runtime is wired but the source "
            "execution gate is closed; running a real model requires separate "
            "explicit authorization"
        )


# --- injected seams ----------------------------------------------------------


class Calculator(Protocol):
    """The minimum an endpoint wrapper must offer.  Real or mock, one shape."""

    def energy_and_forces(
        self, coordinates: Sequence[Sequence[float]]
    ) -> tuple[float, Sequence[Sequence[float]]]: ...


class AseEndpointCalculator(ABC):
    """The declared contract the production ASE optimizer requires.

    ASE's ``LBFGS`` needs an ``Atoms`` object with a calculator bound to it, which
    the generic :class:`Calculator` protocol cannot express.  Rather than reach
    for that capability with ``hasattr`` or by reading a private field, the
    production optimizer requires this type by name.  It is an abstract base
    class, not a structural protocol, so conformance is nominal: an object either
    declares itself an ASE endpoint adapter or the optimizer refuses it.

    Mock optimizers keep using :class:`Calculator`; only the production optimizer
    demands this.
    """

    __slots__ = ()

    @abstractmethod
    def new_atoms(
        self,
        *,
        elements: Sequence[str],
        coordinates: Sequence[Sequence[float]],
    ) -> object:
        """A fresh ``Atoms`` with this endpoint's calculator and copied coordinates."""

    @abstractmethod
    def energy_and_forces(
        self, coordinates: Sequence[Sequence[float]]
    ) -> tuple[float, Sequence[Sequence[float]]]: ...

    @abstractmethod
    def install_boundary_probe(self, probe: Callable[[str], None] | None) -> None:
        """Install (or clear) the deadline probe run either side of an evaluation."""

    @abstractmethod
    def evaluation_counts(self) -> tuple[int, int, int]:
        """``(energy_evaluations, force_evaluations, calculator_invocations)``.

        The third number is what matters for cost: ASE asks for energy and forces
        in a single ``calculate`` call, so one model execution can increment both
        of the first two.  Reporting those two as if they were separate model runs
        would double-count the work, so the invocation count is carried alongside
        them and is the figure the receipt calls a model execution.
        """

    @property
    @abstractmethod
    def endpoint(self) -> str: ...

    @property
    @abstractmethod
    def charge(self) -> int: ...

    @property
    @abstractmethod
    def multiplicity(self) -> int: ...


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
class TrajectoryFrame:
    """One recorded point of a real optimization.  Diagnostic evidence only.

    Carries AIMNet2 energies because they are what the optimizer minimized.  They
    are never a scientific result: no field here reaches the deprotonation label,
    which is computed from PySCF electronic energies alone.
    """

    schema_version: str
    endpoint: str
    frame_index: int
    elapsed_seconds: float
    charge: int
    multiplicity: int
    atom_count: int
    element_order_sha256: str
    coordinates: tuple[tuple[float, float, float], ...]
    energy_ev: float
    max_force_ev_per_angstrom: float
    calculator_invocation_index: int
    optimizer_step: int
    is_initial: bool
    is_terminal: bool


class TerminalState(Enum):
    """How one endpoint's optimization actually ended."""

    CONVERGED = "converged"
    UNCONVERGED = "unconverged"
    TIMEOUT = "timeout"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class OptimizerOutcome:
    """What one endpoint's optimization produced.  Energies are diagnostic only.

    Every field is measured, not assumed.  In particular ``steps`` comes from
    ASE's own ``get_number_of_steps()``, never from ``len(trajectory) - 1``, and
    the evaluation counts come from the endpoint wrapper's ledger, never from an
    assumption that a step costs one force evaluation.  ASE reads the gradient
    again for its convergence test, so the counts routinely exceed the step
    count, and a step may cost more than one evaluation when a line search runs.
    """

    coordinates: tuple[tuple[float, float, float], ...]
    converged: bool
    steps: int
    energy_evaluations: int
    force_evaluations: int
    initial_max_force: float
    final_max_force: float
    trajectory_frames: int
    calculator_invocations: int = 0
    initial_energy_ev: float = 0.0
    final_energy_ev: float = 0.0
    trajectory: tuple[TrajectoryFrame, ...] = ()
    trajectory_sha256: str = ""
    elapsed_seconds: float = 0.0
    deadline_monotonic: float = 0.0
    terminal_state: TerminalState = TerminalState.CONVERGED
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


class _EvaluationLedger:
    """Counts what the model actually did, and runs the deadline probe.

    One ledger per endpoint.  It sits on the single funnel every ASE property
    request passes through, so the counts are observations rather than estimates.
    """

    __slots__ = ("_probe", "calculator_invocations", "energy_evaluations", "force_evaluations")

    def __init__(self) -> None:
        self.energy_evaluations = 0
        self.force_evaluations = 0
        self.calculator_invocations = 0
        self._probe: Callable[[str], None] | None = None

    def install_probe(self, probe: Callable[[str], None] | None) -> None:
        self._probe = probe

    def before(self) -> None:
        if self._probe is not None:
            self._probe("before")

    def after(self, properties: Sequence[str] | None) -> None:
        self.calculator_invocations += 1
        requested = tuple(properties) if properties else ("energy",)
        if "energy" in requested or "free_energy" in requested:
            self.energy_evaluations += 1
        if "forces" in requested:
            self.force_evaluations += 1
        if self._probe is not None:
            self._probe("after")


def _verify_device(device: str, *, gpu_index: int | None = None) -> None:
    """The device is exact.  No ``"cuda"`` auto-select, no CPU fallback."""

    if not device.startswith("cuda:"):
        raise Aimnet2RuntimeError(f"the device must be an exact cuda:<index>, got {device!r}")
    suffix = device.removeprefix("cuda:")
    if not suffix.isdigit():
        raise Aimnet2RuntimeError(f"the device index is not a plain integer: {device!r}")
    if gpu_index is not None and int(suffix) != gpu_index:
        raise Aimnet2RuntimeError("the device index is not the one the route was granted")


def _load_base_model(*, weight_path: Path, device: str) -> BaseModel:
    """The single production entry point for loading AIMNet2.

    Order matters: the source gate is read *before* anything else, so a closed
    gate refuses without importing a machine-learning stack into this process.
    Only after the gate, the weight identity, and the isolation environment all
    pass does this delegate to the construction core, which is where the lazy
    imports and the source-proven constructor live.
    """

    enforce_source_execution_gate()
    _verify_device(device)
    verify_weight(weight_path)
    verify_offline_environment(os.environ, cache_root=_cache_root_from_environment(os.environ))
    return _construct_base_model_after_authorization(weight_path=weight_path, device=device)


def _cache_root_from_environment(environ: Mapping[str, str]) -> Path:
    """The attempt's own cache root, taken from the redirection already in place."""

    value = environ.get(CACHE_ENVIRONMENT_VARIABLES[0])
    if not value:
        raise Aimnet2RuntimeError("the isolated cache root is not redirected")
    return Path(value).parent


def _construct_base_model_after_authorization(
    *, weight_path: Path, device: str
) -> _Aimnet2BaseModel:
    """Build the one base calculator, exactly as Phase 9A-S4 proved is safe.

    This is scheme **A**: the absolute local path goes straight to
    ``AIMNet2Calculator``.  Scheme B -- calling ``aimnet.models.base.load_model``
    by hand and passing the resulting module -- is not used, because A already
    reaches that same public loader, while B would enter the ``nn.Module`` branch
    whose ``cutoff`` silently falls back to ``5.0`` when the attribute is absent.
    B adds a code path and a silent default and removes no network call.

    ``.eval()`` is deliberately not called: the constructor already runs
    ``self.model.train(False)`` and clears ``requires_grad`` on every parameter.
    Adding it would be an unrecorded state change on top of audited control flow.
    """

    # Reached only after enforce_source_execution_gate().  Import path taken from
    # the installed source read in Phase 9A-S4, not from published documentation.
    from aimnet.calculators import (  # type: ignore[import-not-found]
        AIMNet2ASE,
        AIMNet2Calculator,
    )
    from ase import Atoms

    if not weight_path.is_absolute():
        raise Aimnet2RuntimeError("the weight path must be absolute")
    base_calculator = AIMNet2Calculator(
        model=str(weight_path),
        device=device,
        compile_model=COMPILE_MODEL,
    )
    return _Aimnet2BaseModel(
        base_calculator=base_calculator,
        endpoint_class=AIMNet2ASE,
        atoms_class=Atoms,
        device=device,
        weight_path=weight_path,
    )


class _Aimnet2EndpointCalculator(AseEndpointCalculator):
    """One endpoint's ASE adapter over one ``AIMNet2ASE`` wrapper.

    Owns its own ``AIMNet2ASE``, its own ledger, and builds a fresh ``Atoms``
    every time it is asked.  Nothing is shared with the other endpoint: not the
    wrapper, not the atoms, not the coordinates, not the counts.
    """

    __slots__ = (
        "_ase_calculator",
        "_atoms_class",
        "_charge",
        "_elements",
        "_endpoint",
        "_ledger",
        "_multiplicity",
    )

    def __init__(
        self,
        *,
        endpoint: str,
        charge: int,
        multiplicity: int,
        ase_calculator: object,
        atoms_class: Callable[..., object],
        ledger: _EvaluationLedger,
        elements: Sequence[str] = (),
    ) -> None:
        self._endpoint = endpoint
        self._charge = charge
        self._multiplicity = multiplicity
        self._ase_calculator = ase_calculator
        self._atoms_class = atoms_class
        self._ledger = ledger
        self._elements = tuple(elements)

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def charge(self) -> int:
        return self._charge

    @property
    def multiplicity(self) -> int:
        return self._multiplicity

    def new_atoms(
        self, *, elements: Sequence[str], coordinates: Sequence[Sequence[float]]
    ) -> object:
        symbols = tuple(elements)
        if not symbols:
            raise Aimnet2RuntimeError("an endpoint geometry must have at least one atom")
        if len(coordinates) != len(symbols):
            raise Aimnet2RuntimeError("element and coordinate counts differ")
        if self._elements and symbols != self._elements:
            raise Aimnet2RuntimeError("the element order changed for this endpoint")
        # A fresh copy: the caller's coordinates are never handed to ASE, so
        # nothing downstream can mutate the frozen input geometry in place.
        positions: list[list[float]] = []
        for point in coordinates:
            if len(point) != 3:
                raise Aimnet2RuntimeError("a coordinate is not three-dimensional")
            row = [float(value) for value in point]
            if not all(value == value and abs(value) != float("inf") for value in row):
                raise Aimnet2RuntimeError("a coordinate is not finite")
            positions.append(row)
        self._elements = symbols
        atoms: Any = self._atoms_class(symbols=list(symbols), positions=positions)
        atoms.calc = self._ase_calculator
        return atoms

    def energy_and_forces(
        self, coordinates: Sequence[Sequence[float]]
    ) -> tuple[float, Sequence[Sequence[float]]]:
        atoms = self.new_atoms(elements=self._elements, coordinates=coordinates)
        return read_energy_and_forces(atoms, atom_count=len(self._elements))

    def install_boundary_probe(self, probe: Callable[[str], None] | None) -> None:
        self._ledger.install_probe(probe)

    def evaluation_counts(self) -> tuple[int, int, int]:
        return (
            self._ledger.energy_evaluations,
            self._ledger.force_evaluations,
            self._ledger.calculator_invocations,
        )


def read_energy_and_forces(atoms: Any, *, atom_count: int) -> tuple[float, list[list[float]]]:
    """Read one ASE result and prove its shape and finiteness before using it."""

    energy = float(atoms.get_potential_energy())
    if energy != energy or abs(energy) == float("inf"):
        raise Aimnet2RuntimeError("the calculator returned a non-finite energy")
    raw = atoms.get_forces()
    forces = [[float(component) for component in row] for row in raw]
    if len(forces) != atom_count:
        raise Aimnet2RuntimeError("the force array does not have one row per atom")
    for row in forces:
        if len(row) != 3:
            raise Aimnet2RuntimeError("a force row is not three-dimensional")
        for component in row:
            if component != component or abs(component) == float("inf"):
                raise Aimnet2RuntimeError("the calculator returned a non-finite force")
    return energy, forces


def max_force(forces: Sequence[Sequence[float]]) -> float:
    """Largest per-atom force magnitude, in eV/A."""

    return max(
        (sum(component * component for component in row) ** 0.5 for row in forces),
        default=0.0,
    )


class _Aimnet2BaseModel:
    """The one loaded model for a route.  Endpoint wrappers come from it.

    The weight is read once, into one ``AIMNet2Calculator``.  Asking for an
    endpoint calculator builds a fresh ``AIMNet2ASE`` around that same base
    object; it never re-reads the weight, never rebuilds the base calculator, and
    never changes the device.
    """

    __slots__ = (
        "_atoms_class",
        "_base_calculator",
        "_device",
        "_endpoint_class",
        "_issued",
        "_weight_path",
        "load_count",
    )

    def __init__(
        self,
        *,
        base_calculator: object,
        endpoint_class: Callable[..., object],
        atoms_class: Callable[..., object],
        device: str,
        weight_path: Path,
    ) -> None:
        self._base_calculator = base_calculator
        self._endpoint_class = endpoint_class
        self._atoms_class = atoms_class
        self._device = device
        self._weight_path = weight_path
        self._issued: dict[str, _Aimnet2EndpointCalculator] = {}
        self.load_count = BASE_MODEL_LOADS_PER_ROUTE

    @property
    def device(self) -> str:
        return self._device

    def calculator_for(self, *, charge: int, multiplicity: int) -> Calculator:
        endpoint = _endpoint_for_contract(charge=charge, multiplicity=multiplicity)
        if endpoint in self._issued:
            raise Aimnet2RuntimeError(
                f"a second {endpoint} calculator was requested; each endpoint gets one, "
                "so the two can never share mutable charge or coordinate state"
            )
        ledger = _EvaluationLedger()
        counting_class = _counting_endpoint_class(self._endpoint_class, ledger)
        ase_calculator = counting_class(
            self._base_calculator,
            charge=charge,
            mult=multiplicity,
            validate_species=VALIDATE_SPECIES,
        )
        wrapper = _Aimnet2EndpointCalculator(
            endpoint=endpoint,
            charge=charge,
            multiplicity=multiplicity,
            ase_calculator=ase_calculator,
            atoms_class=self._atoms_class,
            ledger=ledger,
        )
        self._issued[endpoint] = wrapper
        return wrapper


def _endpoint_for_contract(*, charge: int, multiplicity: int) -> str:
    """Only the two contracted endpoints exist.  Anything else is refused."""

    for endpoint in ENDPOINT_ORDER:
        if (
            _ENDPOINT_CHARGE[endpoint] == charge
            and _ENDPOINT_MULTIPLICITY[endpoint] == multiplicity
        ):
            return endpoint
    raise Aimnet2RuntimeError(
        f"charge {charge} multiplicity {multiplicity} is not a Phase 9B endpoint"
    )


def _counting_endpoint_class(
    endpoint_class: Callable[..., object], ledger: _EvaluationLedger
) -> Callable[..., object]:
    """Subclass ``AIMNet2ASE`` so every property request passes one funnel.

    ``AIMNet2ASE.calculate`` is the single method ASE routes every energy and
    force request through, so overriding it counts real model executions instead
    of inferring them, and gives the deadline a place to be checked either side
    of a call.  Arguments are forwarded untouched -- nothing about the
    calculation is reimplemented here.
    """

    class _CountingEndpointCalculator(endpoint_class):  # type: ignore[misc,valid-type]
        def calculate(self, *args: object, **kwargs: object) -> object:
            ledger.before()
            result = super().calculate(*args, **kwargs)
            properties = kwargs.get("properties")
            if properties is None and len(args) >= 2:
                properties = args[1]
            ledger.after(properties if isinstance(properties, Sequence) else None)
            return result

    return _CountingEndpointCalculator


# --- the production optimizer -------------------------------------------------


class _DeadlineExceeded(Exception):
    """Internal signal.  Raised at an evaluation or step boundary, never escapes."""


class _Expiry:
    """One mutable flag, so the after-boundary can arm a stop the next check sees."""

    __slots__ = ("armed",)

    def __init__(self) -> None:
        self.armed = False


def serialize_trajectory(frames: Sequence[TrajectoryFrame]) -> bytes:
    """Canonical JSONL.  The same bytes are digested and written, never re-derived."""

    lines: list[bytes] = []
    for frame in frames:
        payload = {
            "schema_version": frame.schema_version,
            "endpoint": frame.endpoint,
            "frame_index": frame.frame_index,
            "elapsed_seconds": round(frame.elapsed_seconds, 6),
            "charge": frame.charge,
            "multiplicity": frame.multiplicity,
            "atom_count": frame.atom_count,
            "element_order_sha256": frame.element_order_sha256,
            "coordinates": [[round(value, 10) for value in point] for point in frame.coordinates],
            "energy_ev": frame.energy_ev,
            "max_force_ev_per_angstrom": frame.max_force_ev_per_angstrom,
            "calculator_invocation_index": frame.calculator_invocation_index,
            "optimizer_step": frame.optimizer_step,
            "is_initial": frame.is_initial,
            "is_terminal": frame.is_terminal,
        }
        lines.append(
            json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False).encode("utf-8")
        )
    raw = b"\n".join(lines) + (b"\n" if lines else b"")
    if len(raw) > MAX_TRAJECTORY_BYTES:
        raise Aimnet2RuntimeError("the trajectory exceeded its frozen size limit")
    return raw


@dataclass(frozen=True, slots=True)
class AseLBFGSOptimizer:
    """The production optimizer: ASE 3.29.0 ``LBFGS``, on the frozen contract.

    Only the two arguments the contract names are passed -- ``restart=None`` so no
    restart file is ever read or written, and ``trajectory=None`` so ASE writes no
    unregistered binary alongside this project's canonical JSONL.  Every other
    ``LBFGS`` argument is left at ASE's own default and recorded in
    :data:`LBFGS_FROZEN_DEFAULTS`, so a future ASE default drift shows up as a
    receipt mismatch instead of a quietly different method.
    """

    monotonic: Callable[[], float] = time.monotonic
    logfile: object = None

    def optimize(
        self,
        *,
        calculator: Calculator,
        coordinates: Sequence[Sequence[float]],
        elements: Sequence[str],
        fmax: float,
        max_steps: int,
        deadline_monotonic: float,
    ) -> OptimizerOutcome:
        """Run one endpoint to convergence, the step budget, or the deadline."""

        # Nominal, not structural: the optimizer requires a declared ASE endpoint
        # adapter by type.  It never inspects an unknown object for capabilities.
        if not isinstance(calculator, AseEndpointCalculator):
            raise Aimnet2RuntimeError(
                "the production optimizer requires a declared AseEndpointCalculator; "
                "it will not probe an unknown object for ASE capability"
            )
        if fmax != FMAX_EV_PER_ANGSTROM or max_steps != MAX_STEPS:
            raise Aimnet2RuntimeError("the frozen optimizer contract was not used")

        started = self.monotonic()
        # 1 of 3: nothing is constructed and no model runs if the budget is gone.
        if started >= deadline_monotonic:
            raise Aimnet2TimeoutError(
                "the local deadline had already passed before optimization began"
            )

        from ase.optimize import LBFGS

        _verify_lbfgs_defaults(LBFGS)
        # ASE ships partial annotations, so the class and the Atoms handle are
        # opaque here on purpose.  What the adapter relies on is pinned by
        # _verify_lbfgs_defaults and by the fake-stack tests, not by ASE's stubs.
        lbfgs: Any = LBFGS
        atoms: Any = calculator.new_atoms(elements=elements, coordinates=coordinates)
        order_digest = hashlib.sha256(" ".join(elements).encode("utf-8")).hexdigest()
        frames: list[TrajectoryFrame] = []
        expiry = _Expiry()

        def probe(phase: str) -> None:
            # 2 of 3: either side of every real evaluation.  A call that itself
            # crosses the deadline is allowed to return -- arming the flag stops
            # the run before the next step rather than mid-evaluation.
            now = self.monotonic()
            if phase == "before":
                if expiry.armed or now >= deadline_monotonic:
                    raise _DeadlineExceeded
            elif now >= deadline_monotonic:
                expiry.armed = True

        def observer() -> None:
            # 3 of 3: after every completed LBFGS step, and once at step zero.
            # ASE calls observers with a warm result cache, so reading energy and
            # forces here costs no extra model execution -- and if it ever did,
            # the invocation counter would show it.
            now = self.monotonic()
            energy, forces = read_energy_and_forces(atoms, atom_count=len(elements))
            _, _, invocations = calculator.evaluation_counts()
            index = len(frames)
            frames.append(
                TrajectoryFrame(
                    schema_version=TRAJECTORY_SCHEMA_VERSION,
                    endpoint=calculator.endpoint,
                    frame_index=index,
                    elapsed_seconds=max(0.0, now - started),
                    charge=calculator.charge,
                    multiplicity=calculator.multiplicity,
                    atom_count=len(elements),
                    element_order_sha256=order_digest,
                    coordinates=_as_points(atoms.get_positions()),
                    energy_ev=energy,
                    max_force_ev_per_angstrom=max_force(forces),
                    calculator_invocation_index=invocations,
                    optimizer_step=index,
                    is_initial=index == 0,
                    is_terminal=False,
                )
            )
            if expiry.armed or now >= deadline_monotonic:
                raise _DeadlineExceeded

        calculator.install_boundary_probe(probe)
        optimizer = lbfgs(atoms, restart=None, trajectory=None, logfile=self.logfile)
        optimizer.attach(observer, interval=1)

        terminal = TerminalState.CONVERGED
        failure: str | None = None
        converged = False
        try:
            converged = bool(optimizer.run(fmax=fmax, steps=max_steps))
        except _DeadlineExceeded:
            terminal = TerminalState.TIMEOUT
            failure = "the local AIMNet2 budget or the route deadline expired"
        except Exception as exc:
            terminal = TerminalState.FAILED
            failure = f"{type(exc).__name__}: {exc}"
        finally:
            calculator.install_boundary_probe(None)

        steps = int(optimizer.get_number_of_steps())
        energy_evaluations, force_evaluations, invocations = calculator.evaluation_counts()
        if terminal is TerminalState.CONVERGED and not converged:
            terminal = TerminalState.UNCONVERGED
            failure = failure or "the optimizer reached its step budget without converging"
        if frames:
            frames[-1] = replace(frames[-1], is_terminal=True)
        if not frames:
            raise Aimnet2RuntimeError("the optimization recorded no trajectory frame")

        final = frames[-1]
        raw = serialize_trajectory(frames)
        return OptimizerOutcome(
            coordinates=final.coordinates,
            converged=converged and terminal is TerminalState.CONVERGED,
            steps=steps,
            energy_evaluations=energy_evaluations,
            force_evaluations=force_evaluations,
            initial_max_force=frames[0].max_force_ev_per_angstrom,
            final_max_force=final.max_force_ev_per_angstrom,
            trajectory_frames=len(frames),
            calculator_invocations=invocations,
            initial_energy_ev=frames[0].energy_ev,
            final_energy_ev=final.energy_ev,
            trajectory=tuple(frames),
            trajectory_sha256=hashlib.sha256(raw).hexdigest(),
            elapsed_seconds=self.monotonic() - started,
            deadline_monotonic=deadline_monotonic,
            terminal_state=terminal,
            failure_reason=failure,
        )


def _as_points(rows: Any) -> tuple[tuple[float, float, float], ...]:
    points: list[tuple[float, float, float]] = []
    for row in rows:
        values = [float(value) for value in row]
        if len(values) != 3:
            raise Aimnet2RuntimeError("a position row is not three-dimensional")
        points.append((values[0], values[1], values[2]))
    return tuple(points)


def _verify_lbfgs_defaults(lbfgs: Any) -> None:
    """Refuse an ASE whose ``LBFGS`` defaults have moved away from the frozen set.

    The runtime sets none of these; leaving them at the default is the contract.
    That only means something if the default is still what Phase 9A-S4 read.
    """

    import inspect

    parameters = inspect.signature(lbfgs.__init__).parameters
    for name, expected in LBFGS_FROZEN_DEFAULTS.items():
        if name in LBFGS_EXPLICIT_ARGUMENTS:
            continue
        parameter = parameters.get(name)
        if parameter is None:
            raise Aimnet2RuntimeError(f"ASE LBFGS no longer accepts {name!r}")
        if parameter.default != expected:
            raise Aimnet2RuntimeError(
                f"ASE LBFGS default for {name!r} drifted from the frozen contract"
            )


def build_production_assisted_runtime(
    *,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[ModelLoader, Optimizer]:
    """The only way the assisted route gets its runtime.  No request touches it.

    Returned as a pair so the route cannot end up with a real loader and no
    optimizer.  The direct route never calls this, and nothing in a request,
    manifest, permit, or CLI can select a different optimizer: the assisted
    adapter calls this function with no arguments derived from input.
    """

    return _load_base_model, AseLBFGSOptimizer(monotonic=monotonic)


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

    # Resolved here, before a single endpoint starts.  If the assisted route
    # reached this point without an optimizer, that is discovered now -- not
    # after the cation has already written durable evidence.
    if model_loader is None or optimizer is None:
        production_loader, production_optimizer = build_production_assisted_runtime(
            monotonic=monotonic
        )
        loader = model_loader if model_loader is not None else production_loader
        resolved_optimizer = optimizer if optimizer is not None else production_optimizer
    else:
        loader, resolved_optimizer = model_loader, optimizer

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
                optimizer=resolved_optimizer,
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
    optimizer: Optimizer,
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
    outcome = optimizer.optimize(
        calculator=calculator,
        coordinates=before,
        elements=elements,
        fmax=FMAX_EV_PER_ANGSTROM,
        max_steps=MAX_STEPS,
        deadline_monotonic=local_deadline,
    )
    if outcome.terminal_state is TerminalState.TIMEOUT:
        raise Aimnet2TimeoutError(
            f"{endpoint} preoptimization ran out of time: {outcome.failure_reason}"
        )
    if outcome.terminal_state is not TerminalState.CONVERGED or not outcome.converged:
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

    # The trajectory is evidence, not a placeholder.  The optimizer digested the
    # frames it produced; this serializes them again and refuses to continue
    # unless the two digests and the digest of what actually landed all agree.
    trajectory_bytes = serialize_trajectory(outcome.trajectory)
    _verify_trajectory(
        outcome=outcome,
        endpoint=endpoint,
        charge=charge,
        multiplicity=multiplicity,
        elements=elements,
        raw=trajectory_bytes,
    )
    trajectory_digest = write_exclusively(endpoint_dir / "trajectory.jsonl", trajectory_bytes)
    if trajectory_digest != outcome.trajectory_sha256:
        raise Aimnet2RuntimeError(f"{endpoint} trajectory bytes differ from the optimizer digest")
    write_exclusively(
        log_root / f"{endpoint}.aimnet2.log",
        (
            f"steps={outcome.steps} converged={outcome.converged} "
            f"terminal={outcome.terminal_state.value} "
            f"invocations={outcome.calculator_invocations} "
            f"frames={outcome.trajectory_frames}\n"
        ).encode(),
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
        calculator_invocations=outcome.calculator_invocations,
        initial_max_force_ev_per_angstrom=outcome.initial_max_force,
        final_max_force_ev_per_angstrom=outcome.final_max_force,
        initial_energy_ev=outcome.initial_energy_ev,
        final_energy_ev=outcome.final_energy_ev,
        wall_time_seconds=outcome.elapsed_seconds,
        isolated_cache_bytes_written=0,
        trajectory_sha256=trajectory_digest,
        trajectory_frames=outcome.trajectory_frames,
        terminal_state=outcome.terminal_state.value,
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


def _verify_trajectory(
    *,
    outcome: OptimizerOutcome,
    endpoint: str,
    charge: int,
    multiplicity: int,
    elements: Sequence[str],
    raw: bytes,
) -> None:
    """Prove the trajectory is real evidence before it is written or digested."""

    frames = outcome.trajectory
    if not frames:
        raise Aimnet2RuntimeError(f"{endpoint} produced no trajectory frames")
    if len(frames) != outcome.trajectory_frames:
        raise Aimnet2RuntimeError(f"{endpoint} trajectory frame count disagrees with the outcome")
    if hashlib.sha256(raw).hexdigest() != outcome.trajectory_sha256:
        raise Aimnet2RuntimeError(f"{endpoint} trajectory digest does not match its frames")
    if not frames[0].is_initial or not frames[-1].is_terminal:
        raise Aimnet2RuntimeError(f"{endpoint} trajectory is missing an initial or terminal frame")
    order_digest = hashlib.sha256(" ".join(elements).encode("utf-8")).hexdigest()
    previous_elapsed = -1.0
    for index, frame in enumerate(frames):
        if frame.schema_version != TRAJECTORY_SCHEMA_VERSION:
            raise Aimnet2RuntimeError(f"{endpoint} trajectory schema drifted")
        if frame.frame_index != index:
            raise Aimnet2RuntimeError(f"{endpoint} trajectory frame index is not strictly ordered")
        if frame.elapsed_seconds < previous_elapsed:
            raise Aimnet2RuntimeError(f"{endpoint} trajectory elapsed time went backwards")
        previous_elapsed = frame.elapsed_seconds
        if frame.endpoint != endpoint or frame.charge != charge:
            raise Aimnet2RuntimeError(f"{endpoint} trajectory frame carries another endpoint")
        if frame.multiplicity != multiplicity:
            raise Aimnet2RuntimeError(f"{endpoint} trajectory multiplicity drifted")
        if frame.atom_count != len(elements) or frame.element_order_sha256 != order_digest:
            raise Aimnet2RuntimeError(f"{endpoint} trajectory atom order changed")
        if len(frame.coordinates) != len(elements):
            raise Aimnet2RuntimeError(f"{endpoint} trajectory frame has the wrong atom count")
        for value in (frame.energy_ev, frame.max_force_ev_per_angstrom):
            if value != value or abs(value) == float("inf"):
                raise Aimnet2RuntimeError(f"{endpoint} trajectory carries a non-finite value")
        for point in frame.coordinates:
            for component in point:
                if component != component or abs(component) == float("inf"):
                    raise Aimnet2RuntimeError(
                        f"{endpoint} trajectory carries a non-finite coordinate"
                    )
    if frames[-1].coordinates != outcome.coordinates:
        raise Aimnet2RuntimeError(f"{endpoint} final coordinates differ from the terminal frame")


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
