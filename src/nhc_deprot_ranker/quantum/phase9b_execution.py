"""Route-aware execution adapters, selected by exact attempt identity.

Before this module the worker ended with one unconditional line::

    backend = PySCFBackend(compute_capability)

so ``attempt-phase9b-lbnp-direct-v001`` and ``attempt-phase9b-lbnp-assisted-v001``
executed *identically*.  The assisted route was a second copy of the direct route
wearing a different attempt id, and the paired comparison could not have measured
anything.

The chain is now::

    exact attempt -> source-frozen WorkerAuthorityProfile -> exact
    ExecutionAdapter -> backend / runtime

Adapter selection is by exact attempt only.  Nothing in the request, the CLI, the
payload, an environment variable, a file name, or a remote root name can choose
one.  Two adapters may never match one attempt, and an unregistered attempt has
no adapter at all.

**No chemistry is imported at module scope.**  Both adapters import their backend
lazily, inside ``execute``, which is reachable only after the permit is consumed,
the handshake is verified, the compute claim is validated, and the capability is
issued.  The direct adapter never imports the machine-learning stack at all.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from nhc_deprot_ranker.quantum.phase9b_permit import (
    ROUTE_ASSISTED,
    ROUTE_ATTEMPT_IDS,
    ROUTE_DIRECT,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nhc_deprot_ranker.quantum.two_endpoint import TwoEndpointRequest

EXECUTION_ADAPTER_SCHEMA_VERSION: Final = "nhc-phase9b-execution-adapter-v1"

# Relative layout of the assisted route's runtime tree, frozen so it enters the
# hash identity rather than being decided at run time.
AIMNET2_TREE_RELATIVE: Final = "runtime/aimnet2"
AIMNET2_CACHE_RELATIVE: Final = "runtime/cache"
EVIDENCE_TREE_RELATIVE: Final = "runtime/evidence"
LOG_TREE_RELATIVE: Final = "runtime/logs"

ENDPOINT_ORDER: Final[tuple[str, ...]] = ("cation", "neutral")


class ExecutionAdapterError(RuntimeError):
    """The route's execution could not prove its closed scope."""


class EndpointState(Enum):
    """One endpoint's fixed progression.  No stage may be skipped or reordered."""

    INITIAL = "initial"
    INPUT_VERIFIED = "input_verified"
    AIMNET2_RUNNING = "aimnet2_running"
    AIMNET2_CONVERGED = "aimnet2_converged"
    STRUCTURE_VALIDATED = "structure_validated"
    PREOPT_EVIDENCE_DURABLE = "preopt_evidence_durable"
    HANDOFF_CLOSED = "handoff_closed"
    PYSCF_ALLOWED = "pyscf_allowed"
    PYSCF_RUNNING = "pyscf_running"
    PYSCF_TERMINAL = "pyscf_terminal"
    FAILED = "failed"


_ASSISTED_SEQUENCE: Final[tuple[EndpointState, ...]] = (
    EndpointState.INITIAL,
    EndpointState.INPUT_VERIFIED,
    EndpointState.AIMNET2_RUNNING,
    EndpointState.AIMNET2_CONVERGED,
    EndpointState.STRUCTURE_VALIDATED,
    EndpointState.PREOPT_EVIDENCE_DURABLE,
    EndpointState.HANDOFF_CLOSED,
    EndpointState.PYSCF_ALLOWED,
    EndpointState.PYSCF_RUNNING,
    EndpointState.PYSCF_TERMINAL,
)


def assisted_state_sequence() -> tuple[EndpointState, ...]:
    """The one legal order.  Exposed so a test can assert it rather than infer it."""

    return _ASSISTED_SEQUENCE


class EndpointProgress:
    """Enforces the fixed order for one endpoint.  Terminal on first failure."""

    __slots__ = ("_endpoint", "_failed", "_index")

    def __init__(self, endpoint: str) -> None:
        if endpoint not in ENDPOINT_ORDER:
            raise ExecutionAdapterError(f"unknown endpoint: {endpoint!r}")
        self._endpoint = endpoint
        self._index = 0
        self._failed = False

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def state(self) -> EndpointState:
        return EndpointState.FAILED if self._failed else _ASSISTED_SEQUENCE[self._index]

    @property
    def failed(self) -> bool:
        return self._failed

    def advance(self, expected: EndpointState) -> None:
        """Move exactly one step, and only to the next state in the sequence."""

        if self._failed:
            raise ExecutionAdapterError(
                f"{self._endpoint} already failed; no stage may follow a failure"
            )
        nxt = self._index + 1
        if nxt >= len(_ASSISTED_SEQUENCE) or _ASSISTED_SEQUENCE[nxt] is not expected:
            raise ExecutionAdapterError(
                f"{self._endpoint} cannot move from {self.state.value} to {expected.value}"
            )
        self._index = nxt

    def fail(self) -> None:
        self._failed = True


class _ComputeCapabilityLike(Protocol):
    """Only the fact that a capability was issued matters at this layer."""


class BackendFactory(Protocol):
    """Constructs the PySCF backend from an issued capability."""

    def __call__(self, capability: object) -> object: ...


class Aimnet2RuntimeFactory(Protocol):
    """Constructs the AIMNet2 stage runtime.  Injected so tests never load a model."""

    def __call__(
        self,
        *,
        run_root: Path,
        request: TwoEndpointRequest,
        gpu_index: int,
        absolute_deadline_monotonic: float,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ExecutionAdapter:
    """One route's exact execution identity.  Frozen, and inside the closure."""

    schema_version: str
    adapter_id: str
    route: str
    attempt_id: str
    uses_preoptimization: bool
    imports_machine_learning_stack: bool
    _execute: Callable[..., int]

    def execute(self, *args: object, **kwargs: object) -> int:
        """Refuse any attempt but this adapter's own, then run it."""

        if kwargs.get("attempt_id") != self.attempt_id:
            raise ExecutionAdapterError(
                f"the {self.adapter_id} adapter refuses another attempt identity"
            )
        return int(self._execute(*args, **kwargs))

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_ADAPTER_SCHEMA_VERSION:
            raise ExecutionAdapterError("execution adapter schema version drifted")
        if self.uses_preoptimization != self.imports_machine_learning_stack:
            raise ExecutionAdapterError(
                "an adapter that preoptimizes must declare the ML stack, and one that "
                "does not must not"
            )


def _run_two_endpoint_pyscf(
    request: TwoEndpointRequest,
    output_root: Path,
    *,
    capability: object,
    attempt_id: str,
    absolute_deadline_monotonic: float,
    backend_factory: BackendFactory | None = None,
) -> int:
    """Direct provenance adapter into the shared direct/A2 PySCF core."""

    from nhc_deprot_ranker.quantum.phase9b_shared_pyscf_core import (
        SHARED_TWO_ENDPOINT_PYSCF_CORE,
        FrozenDirectInputProvenance,
    )

    return SHARED_TWO_ENDPOINT_PYSCF_CORE.execute(
        request,
        output_root,
        capability=capability,
        attempt_id=attempt_id,
        absolute_deadline_monotonic=absolute_deadline_monotonic,
        input_provenance=FrozenDirectInputProvenance(
            route="direct",
            cation_xyz_sha256=request.cation.xyz_sha256,
            neutral_xyz_sha256=request.neutral.xyz_sha256,
        ),
        backend_factory=backend_factory,
    )


def _execute_direct(
    request: TwoEndpointRequest,
    output_root: Path,
    *,
    capability: object,
    attempt_id: str,
    absolute_deadline_monotonic: float,
    backend_factory: BackendFactory | None = None,
    **_unused: object,
) -> int:
    """Route D.  The frozen scientific baseline, unchanged.

    It never imports torch, ASE, or aimnet, never reads the AIMNet2 weight, never
    creates a model cache, never preoptimizes, never produces a preoptimization or
    handoff receipt, never consults ``pyscf_may_start``, and never touches a GPU.
    That is asserted by a test that scans this module's executable code and by one
    that watches ``sys.modules`` across a direct execution.
    """

    return _run_two_endpoint_pyscf(
        request,
        output_root,
        capability=capability,
        attempt_id=attempt_id,
        absolute_deadline_monotonic=absolute_deadline_monotonic,
        backend_factory=backend_factory,
    )


def _execute_assisted(
    request: TwoEndpointRequest,
    output_root: Path,
    *,
    capability: object,
    attempt_id: str,
    absolute_deadline_monotonic: float,
    run_root: Path | None = None,
    gpu_index: int = 0,
    backend_factory: BackendFactory | None = None,
    aimnet2_runtime_factory: Aimnet2RuntimeFactory | None = None,
    **_unused: object,
) -> int:
    """Route A.  Preoptimization inside the route, then the same PySCF baseline.

    ``pyscf_may_start`` is the only door into PySCF, and it is reached only after
    a durable preoptimization receipt and a byte-closed handoff receipt exist for
    that endpoint.  Cation runs first; if any of its stages fails, neutral never
    starts and no label is produced.
    """

    from nhc_deprot_ranker.quantum.phase9b_aimnet2_runtime import run_assisted_stage

    if run_root is None:
        raise ExecutionAdapterError("the assisted adapter requires its frozen run root")

    # The AIMNet2 stage runs for both endpoints, in order, and closes a handoff
    # for each.  It refuses to hand off anything that did not pass every gate.
    stage = run_assisted_stage(
        request=request,
        run_root=run_root,
        attempt_id=attempt_id,
        gpu_index=gpu_index,
        absolute_deadline_monotonic=absolute_deadline_monotonic,
        runtime_factory=aimnet2_runtime_factory,
    )
    if not stage.may_start_pyscf:
        raise ExecutionAdapterError(f"the assisted route stopped before PySCF: {stage.reason}")

    return _run_two_endpoint_pyscf(
        stage.pyscf_request,
        output_root,
        capability=capability,
        attempt_id=attempt_id,
        absolute_deadline_monotonic=absolute_deadline_monotonic,
        backend_factory=backend_factory,
    )


PHASE8B_ADAPTER: Final = ExecutionAdapter(
    schema_version=EXECUTION_ADAPTER_SCHEMA_VERSION,
    adapter_id="phase8b-direct-pyscf",
    route="phase8b",
    attempt_id="attempt-phase8b-qxh-v001",
    uses_preoptimization=False,
    imports_machine_learning_stack=False,
    _execute=_execute_direct,
)

DIRECT_ADAPTER: Final = ExecutionAdapter(
    schema_version=EXECUTION_ADAPTER_SCHEMA_VERSION,
    adapter_id="phase9b-direct-pyscf",
    route=ROUTE_DIRECT,
    attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
    uses_preoptimization=False,
    imports_machine_learning_stack=False,
    _execute=_execute_direct,
)

# Item 10's paired generation has a fresh exact attempt.  It uses the same
# shared PySCF core as the retained v8 direct adapter; the distinct registry
# entry prevents a v8 attempt or request from being silently reinterpreted.
DIRECT_V3_ADAPTER: Final = ExecutionAdapter(
    schema_version=EXECUTION_ADAPTER_SCHEMA_VERSION,
    adapter_id="phase9b-direct-pyscf-v3",
    route=ROUTE_DIRECT,
    attempt_id="attempt-phase9b-lbnp-direct-v003",
    uses_preoptimization=False,
    imports_machine_learning_stack=False,
    _execute=_execute_direct,
)

ASSISTED_ADAPTER: Final = ExecutionAdapter(
    schema_version=EXECUTION_ADAPTER_SCHEMA_VERSION,
    adapter_id="phase9b-assisted-aimnet2-pyscf",
    route=ROUTE_ASSISTED,
    attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED],
    uses_preoptimization=True,
    imports_machine_learning_stack=True,
    _execute=_execute_assisted,
)

_EXECUTION_ADAPTERS: Final[Mapping[str, ExecutionAdapter]] = {
    PHASE8B_ADAPTER.attempt_id: PHASE8B_ADAPTER,
    DIRECT_ADAPTER.attempt_id: DIRECT_ADAPTER,
    DIRECT_V3_ADAPTER.attempt_id: DIRECT_V3_ADAPTER,
    ASSISTED_ADAPTER.attempt_id: ASSISTED_ADAPTER,
}


def resolve_execution_adapter(attempt_id: str) -> ExecutionAdapter:
    """Exact, unique attempt match.  There is no other way to obtain an adapter."""

    matches = [
        adapter for adapter in _EXECUTION_ADAPTERS.values() if adapter.attempt_id == attempt_id
    ]
    if len(matches) != 1:
        raise ExecutionAdapterError(
            f"no execution adapter matches the requested attempt: {attempt_id!r}"
        )
    return matches[0]


def registered_execution_adapters() -> tuple[ExecutionAdapter, ...]:
    return tuple(_EXECUTION_ADAPTERS.values())


__all__ = [
    "AIMNET2_CACHE_RELATIVE",
    "AIMNET2_TREE_RELATIVE",
    "ASSISTED_ADAPTER",
    "DIRECT_ADAPTER",
    "DIRECT_V3_ADAPTER",
    "ENDPOINT_ORDER",
    "EVIDENCE_TREE_RELATIVE",
    "EXECUTION_ADAPTER_SCHEMA_VERSION",
    "LOG_TREE_RELATIVE",
    "PHASE8B_ADAPTER",
    "Aimnet2RuntimeFactory",
    "BackendFactory",
    "EndpointProgress",
    "EndpointState",
    "ExecutionAdapter",
    "ExecutionAdapterError",
    "assisted_state_sequence",
    "registered_execution_adapters",
    "resolve_execution_adapter",
]
