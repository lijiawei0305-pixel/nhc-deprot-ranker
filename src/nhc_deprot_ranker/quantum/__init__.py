"""Guarded, protocol-locked quantum-chemistry interfaces.

Phase 7 exposes request validation and mockable data contracts, but the public
execution entry point remains disabled until a later phase explicitly changes
the source-level authorization gate.
"""

from nhc_deprot_ranker.quantum.two_endpoint import (
    EXECUTION_AUTHORIZED,
    LOCKED_PROTOCOL,
    LOCKED_PROTOCOL_SHA256,
    BackendOptimizationResult,
    BackendSCFResult,
    BackendTimeoutError,
    DispersionUnavailableError,
    ExecutionNotAuthorizedError,
    PySCFBackend,
    RequestValidationError,
    ResumeValidationError,
    TwoEndpointBackend,
    TwoEndpointRequest,
    TwoEndpointRunError,
    TwoEndpointRunResult,
    XYZAtom,
    XYZGeometry,
    current_runner_source_sha256,
    load_two_endpoint_request,
    run_two_endpoint,
)

__all__ = [
    "EXECUTION_AUTHORIZED",
    "LOCKED_PROTOCOL",
    "LOCKED_PROTOCOL_SHA256",
    "BackendOptimizationResult",
    "BackendSCFResult",
    "BackendTimeoutError",
    "DispersionUnavailableError",
    "ExecutionNotAuthorizedError",
    "PySCFBackend",
    "RequestValidationError",
    "ResumeValidationError",
    "TwoEndpointBackend",
    "TwoEndpointRequest",
    "TwoEndpointRunError",
    "TwoEndpointRunResult",
    "XYZAtom",
    "XYZGeometry",
    "current_runner_source_sha256",
    "load_two_endpoint_request",
    "run_two_endpoint",
]
