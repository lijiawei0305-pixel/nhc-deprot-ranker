"""Single PySCF execution core shared by Phase 9B direct and assisted A2.

The route wrappers are authority/input-provenance adapters only.  Once a
validated :class:`~nhc_deprot_ranker.quantum.two_endpoint.TwoEndpointRequest`
reaches this module, both routes use this exact function for endpoint order,
standard-to-SOSCF behaviour, D3 evidence, failure classification, and the
label formula.  PySCF remains a lazy import behind an issued capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, Protocol

if TYPE_CHECKING:  # pragma: no cover
    from nhc_deprot_ranker.quantum.two_endpoint import TwoEndpointRequest

SHARED_PYSCF_CORE_SCHEMA_VERSION: Final = "nhc-phase9b-shared-pyscf-core-v1"


class SharedPySCFCoreError(RuntimeError):
    """The shared core was invoked with invalid route provenance."""


@dataclass(frozen=True, slots=True)
class FrozenDirectInputProvenance:
    """Direct route provenance for the frozen Phase 7 input bytes."""

    route: Literal["direct"]
    cation_xyz_sha256: str
    neutral_xyz_sha256: str


@dataclass(frozen=True, slots=True)
class AdmittedA1InputProvenance:
    """Assisted route provenance for supervisor-admitted A1 bytes."""

    route: Literal["assisted"]
    proposal_sha256: str
    verification_sha256: str
    admission_sha256: str
    cation_xyz_sha256: str
    neutral_xyz_sha256: str
    cation_parser_input_sha256: str
    neutral_parser_input_sha256: str


PySCFInputProvenance = FrozenDirectInputProvenance | AdmittedA1InputProvenance


class BackendFactory(Protocol):
    def __call__(self, capability: object) -> object: ...


def _require_sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise SharedPySCFCoreError(f"{label} must be a lowercase SHA256")


def validate_input_provenance(provenance: PySCFInputProvenance) -> None:
    """Reject route confusion and prove A2 hands the disk bytes to the parser."""

    _require_sha256(provenance.cation_xyz_sha256, "cation_xyz_sha256")
    _require_sha256(provenance.neutral_xyz_sha256, "neutral_xyz_sha256")
    if provenance.cation_xyz_sha256 == provenance.neutral_xyz_sha256:
        raise SharedPySCFCoreError("the two endpoint byte identities must differ")
    if isinstance(provenance, AdmittedA1InputProvenance):
        for label, value in (
            ("proposal_sha256", provenance.proposal_sha256),
            ("verification_sha256", provenance.verification_sha256),
            ("admission_sha256", provenance.admission_sha256),
        ):
            _require_sha256(value, label)
        if provenance.cation_parser_input_sha256 != provenance.cation_xyz_sha256:
            raise SharedPySCFCoreError("cation disk bytes differ from parser input bytes")
        if provenance.neutral_parser_input_sha256 != provenance.neutral_xyz_sha256:
            raise SharedPySCFCoreError("neutral disk bytes differ from parser input bytes")


def run_shared_two_endpoint_pyscf(
    request: TwoEndpointRequest,
    output_root: Path,
    *,
    capability: object,
    attempt_id: str,
    absolute_deadline_monotonic: float,
    input_provenance: PySCFInputProvenance,
    backend_factory: BackendFactory | None = None,
) -> int:
    """Run the one two-endpoint PySCF algorithm used by both routes."""

    validate_input_provenance(input_provenance)
    from nhc_deprot_ranker.quantum import two_endpoint as runner

    backend = (
        backend_factory(capability)
        if backend_factory is not None
        else runner.PySCFBackend(capability)
    )
    try:
        runner._execute_validated_request(  # pyright: ignore[reportPrivateUsage]
            request,
            output_root,
            backend=backend,  # type: ignore[arg-type]
            attempt_id=attempt_id,
            absolute_deadline_monotonic=absolute_deadline_monotonic,
        )
    except runner.TwoEndpointRunError as error:
        return int(error.exit_code)
    return 0


@dataclass(frozen=True, slots=True)
class SharedTwoEndpointPySCFCore:
    """Strongly typed callable identity for direct/A2 parity assertions."""

    schema_version: str = SHARED_PYSCF_CORE_SCHEMA_VERSION

    def execute(
        self,
        request: TwoEndpointRequest,
        output_root: Path,
        *,
        capability: object,
        attempt_id: str,
        absolute_deadline_monotonic: float,
        input_provenance: PySCFInputProvenance,
        backend_factory: BackendFactory | None = None,
    ) -> int:
        if self.schema_version != SHARED_PYSCF_CORE_SCHEMA_VERSION:
            raise SharedPySCFCoreError("shared PySCF core schema drifted")
        return run_shared_two_endpoint_pyscf(
            request,
            output_root,
            capability=capability,
            attempt_id=attempt_id,
            absolute_deadline_monotonic=absolute_deadline_monotonic,
            input_provenance=input_provenance,
            backend_factory=backend_factory,
        )


SHARED_TWO_ENDPOINT_PYSCF_CORE: Final = SharedTwoEndpointPySCFCore()


__all__ = [
    "SHARED_PYSCF_CORE_SCHEMA_VERSION",
    "SHARED_TWO_ENDPOINT_PYSCF_CORE",
    "AdmittedA1InputProvenance",
    "BackendFactory",
    "FrozenDirectInputProvenance",
    "PySCFInputProvenance",
    "SharedPySCFCoreError",
    "SharedTwoEndpointPySCFCore",
    "run_shared_two_endpoint_pyscf",
    "validate_input_provenance",
]
