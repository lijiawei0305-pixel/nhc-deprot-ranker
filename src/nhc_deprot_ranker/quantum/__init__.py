"""Guarded, protocol-locked quantum-chemistry interfaces.

Phase 8A adds a parent-supervised worker protocol and hard-timeout seam while
the public execution entry point remains source-disabled.
"""

from nhc_deprot_ranker.quantum.two_endpoint import (
    EXECUTION_AUTHORIZED,
    LOCKED_PROTOCOL,
    LOCKED_PROTOCOL_SHA256,
    RUNNER_SOURCE_SCHEMA_VERSION,
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
    "RUNNER_SOURCE_SCHEMA_VERSION",
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
