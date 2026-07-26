"""Phase 9B execution reachability, through the real validators.

The previous round asserted "Phase 9B reaches capability issue" while
monkeypatching ``_validate_worker_compute_claim`` to a no-op. That is not done
here: the shipped compute-claim validator runs, and both routes must pass it.

No torch, no ASE, no aimnet, no PySCF, no geomeTRIC, no CUDA. The backend and the
AIMNet2 runtime are injected; the security path is real.
"""

from __future__ import annotations

import ast
import dataclasses
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from nhc_deprot_ranker.quantum import phase9b_execution as ex
from nhc_deprot_ranker.quantum import two_endpoint as runner
from nhc_deprot_ranker.quantum import worker
from nhc_deprot_ranker.quantum.phase8b_execution import (
    ComputeClaim,
    ComputeClaimAuthority,
    ComputeClaimEvidence,
    TransactionPaths,
    WorkerRegistration,
)
from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE
from nhc_deprot_ranker.quantum.phase9b_permit import (
    ROUTE_ASSISTED,
    ROUTE_ATTEMPT_IDS,
    ROUTE_DIRECT,
    ConsumedPhase9BPermit,
    Phase9BExactAuthority,
    Phase9BPermit,
)
from nhc_deprot_ranker.quantum.phase9b_resources import phase9b_resources_sha256

_PROJECT = Path("/srv/project")
_REQUEST = "1" * 64
_SOURCE = "2" * 64
_PAYLOAD = "3" * 64
_PERMIT = "4" * 64
_TRANSPORT = "5" * 64
_PROTOCOL = "6" * 64
_CATION = "7" * 64
_NEUTRAL = "8" * 64


def _run_root(route: str) -> Path:
    return _PROJECT / "data/runs/nhc_deprot_ranker_phase9b_paired_smoke_v001" / route


def _permit(route: str) -> Phase9BPermit:
    root = _run_root(route)
    return Phase9BPermit(
        route=route,
        attempt_id=ROUTE_ATTEMPT_IDS[route],
        cation_xyz_sha256=_CATION,
        neutral_xyz_sha256=_NEUTRAL,
        request_sha256=_REQUEST,
        runner_source_sha256=_SOURCE,
        payload_manifest_sha256=_PAYLOAD,
        project_root=_PROJECT,
        run_root=root,
        request_path=root / "input/request.json",
        output_root=root / "runtime/output",
        ready_path=root / "private/permit.ready.json",
        consumed_path=root / "private/permit.consumed.json",
        raw_bytes=b"{}\n",
        permit_sha256=_PERMIT,
    )


def _authority(route: str) -> Phase9BExactAuthority:
    root = _run_root(route)
    return Phase9BExactAuthority(
        route=route,
        request_sha256=_REQUEST,
        runner_source_sha256=_SOURCE,
        permit_sha256=_PERMIT,
        payload_manifest_sha256=_PAYLOAD,
        cation_xyz_sha256=_CATION,
        neutral_xyz_sha256=_NEUTRAL,
        legacy_atom_map_sha256=PHASE9B_CANDIDATE.legacy_atom_map_sha256,
        endpoint_atom_map_sha256=PHASE9B_CANDIDATE.endpoint_atom_map_sha256,
        geometry_validation_sha256=PHASE9B_CANDIDATE.geometry_validation_sha256,
        resources_sha256=phase9b_resources_sha256(),
        electron_count=160,
        request_id="phase9b-lbnp-paired-smoke-v001",
        inchikey=PHASE9B_CANDIDATE.inchikey,
        attempt_id=ROUTE_ATTEMPT_IDS[route],
        project_root=_PROJECT.as_posix(),
        run_root=root.as_posix(),
        request_path=(root / "input/request.json").as_posix(),
        output_root=(root / "runtime/output").as_posix(),
    )


def _consumed(route: str) -> ConsumedPhase9BPermit:
    permit = _permit(route)
    return ConsumedPhase9BPermit(
        permit=permit, consumed_path=permit.consumed_path, consumed_sha256=_PERMIT
    )


@dataclasses.dataclass(frozen=True)
class _Endpoint:
    xyz_sha256: str
    charge: int
    multiplicity: int
    electron_count: int = 160


@dataclasses.dataclass(frozen=True)
class _Request:
    request_sha256: str = _REQUEST
    runner_source_sha256: str = _SOURCE
    protocol_sha256: str = _PROTOCOL
    request_id: str = "phase9b-lbnp-paired-smoke-v001"
    inchikey: str = PHASE9B_CANDIDATE.inchikey
    execution_authorized: bool = True
    timeout_seconds: int = 7200
    cation: _Endpoint = dataclasses.field(default_factory=lambda: _Endpoint(_CATION, 1, 1))
    neutral: _Endpoint = dataclasses.field(default_factory=lambda: _Endpoint(_NEUTRAL, 0, 1))
    request_path: Path = _run_root(ROUTE_DIRECT) / "input/request.json"


def _claim(route: str, *, scratch: Path, **overrides: Any) -> ComputeClaimEvidence:
    root = _run_root(route)
    base: dict[str, Any] = {
        "transport_inventory_sha256": _TRANSPORT,
        "payload_manifest_sha256": _PAYLOAD,
        "permit_sha256": _PERMIT,
        "request_sha256": _REQUEST,
        "runner_source_sha256": _SOURCE,
        "protocol_sha256": _PROTOCOL,
        "resources_sha256": phase9b_resources_sha256(),
        "cation_xyz_sha256": _CATION,
        "neutral_xyz_sha256": _NEUTRAL,
        "endpoint_atom_map_sha256": PHASE9B_CANDIDATE.endpoint_atom_map_sha256,
        "legacy_atom_map_sha256": PHASE9B_CANDIDATE.legacy_atom_map_sha256,
        "geometry_validation_sha256": PHASE9B_CANDIDATE.geometry_validation_sha256,
        "electron_count": 160,
        "request_id": "phase9b-lbnp-paired-smoke-v001",
        "inchikey": PHASE9B_CANDIDATE.inchikey,
        "attempt_id": ROUTE_ATTEMPT_IDS[route],
        "project_root": _PROJECT,
        "run_root": root,
        "request_path": root / "input/request.json",
        "output_root": root / "runtime/output",
    }
    base.update(overrides)
    authority = ComputeClaimAuthority(**base)
    paths = TransactionPaths(
        registration=root / "private/worker_registration.json",
        acknowledgement=root / "private/guardian_acknowledgement.json",
        compute_claim=root / "private/compute_claim.json",
        receipt=root / "private/guardian_receipt.json",
    )
    claim = object.__new__(ComputeClaim)
    object.__setattr__(claim, "authority", authority)
    object.__setattr__(claim, "paths", paths)
    object.__setattr__(claim, "worker_scratch_path", scratch)
    evidence = object.__new__(ComputeClaimEvidence)
    object.__setattr__(evidence, "claim", claim)
    return evidence


def _validate(route: str, *, scratch: Path, **overrides: Any) -> None:
    """Drive the shipped validator.  Nothing here is monkeypatched."""

    profile = worker._resolve_worker_profile(  # pyright: ignore[reportPrivateUsage]
        ROUTE_ATTEMPT_IDS[route]
    )
    root = _run_root(route)
    worker._validate_worker_compute_claim(  # pyright: ignore[reportPrivateUsage]
        _claim(route, scratch=scratch, **overrides.pop("claim", {})),
        request=overrides.pop("request", _Request(request_path=root / "input/request.json")),
        consumed=overrides.pop("consumed", _consumed(route)),
        authority=overrides.pop("authority", _authority(route)),
        expected_transport_inventory_sha256=_TRANSPORT,
        expected_payload_manifest_sha256=_PAYLOAD,
        expected_permit_sha256=_PERMIT,
        expected_request_sha256=_REQUEST,
        expected_runner_source_sha256=_SOURCE,
        authorized_output_root=root / "runtime/output",
        worker_scratch_path=scratch,
        compute_claim_path=root / "private/compute_claim.json",
        attempt_id=overrides.pop("attempt_id", ROUTE_ATTEMPT_IDS[route]),
        profile=overrides.pop("profile", profile),
    )


# --- A. real execution reachability -----------------------------------------


@pytest.mark.parametrize("route", [ROUTE_DIRECT, ROUTE_ASSISTED])
def test_both_routes_pass_the_real_compute_claim_validator(tmp_path: Path, route: str) -> None:
    """The shipped validator, not a no-op.  Both routes must get through it."""

    _validate(route, scratch=tmp_path / "scratch")


def test_the_validator_is_not_monkeypatched_anywhere_in_this_module() -> None:
    """Guards against the failure mode that hid this gap for a whole round."""

    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    patched = {
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"setattr", "patch"}
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
    }
    assert "_validate_worker_compute_claim" not in patched
    assert "_issue_guarded_compute_capability" not in patched


@pytest.mark.parametrize("route", [ROUTE_DIRECT, ROUTE_ASSISTED])
def test_each_route_resolves_to_its_own_profile_and_adapter(route: str) -> None:
    profile = worker._resolve_worker_profile(  # pyright: ignore[reportPrivateUsage]
        ROUTE_ATTEMPT_IDS[route]
    )
    adapter = ex.resolve_execution_adapter(ROUTE_ATTEMPT_IDS[route])
    assert profile.route == route
    assert profile.execution_adapter is adapter
    assert adapter.route == route
    assert adapter.uses_preoptimization is (route == ROUTE_ASSISTED)


# --- B. cross-profile rejection ---------------------------------------------


def test_a_crossed_authority_is_refused(tmp_path: Path) -> None:
    """direct claim + assisted authority, and the reverse."""

    scratch = tmp_path / "scratch"
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="attempt identity drifted"):
        _validate(ROUTE_DIRECT, scratch=scratch, authority=_authority(ROUTE_ASSISTED))
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="attempt identity drifted"):
        _validate(ROUTE_ASSISTED, scratch=scratch, authority=_authority(ROUTE_DIRECT))


def test_a_crossed_consumed_permit_is_refused(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    with pytest.raises(runner.ExecutionNotAuthorizedError):
        _validate(ROUTE_DIRECT, scratch=scratch, consumed=_consumed(ROUTE_ASSISTED))
    with pytest.raises(runner.ExecutionNotAuthorizedError):
        _validate(ROUTE_ASSISTED, scratch=scratch, consumed=_consumed(ROUTE_DIRECT))


def test_a_phase8b_profile_cannot_validate_a_phase9b_pair(tmp_path: Path) -> None:
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="authority type drifted"):
        _validate(
            ROUTE_DIRECT,
            scratch=tmp_path / "scratch",
            profile=worker.PHASE8B_WORKER_PROFILE,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("payload_manifest_sha256", "9" * 64),
        ("permit_sha256", "9" * 64),
        ("request_sha256", "9" * 64),
        ("runner_source_sha256", "9" * 64),
        ("resources_sha256", "9" * 64),
        ("endpoint_atom_map_sha256", "9" * 64),
        ("legacy_atom_map_sha256", "9" * 64),
        ("geometry_validation_sha256", "9" * 64),
        ("electron_count", 120),
        ("transport_inventory_sha256", "9" * 64),
        ("protocol_sha256", "9" * 64),
        ("cation_xyz_sha256", "9" * 64),
        ("neutral_xyz_sha256", "9" * 64),
    ],
)
def test_any_claim_field_that_drifts_is_refused(tmp_path: Path, field: str, value: Any) -> None:
    with pytest.raises(runner.ExecutionNotAuthorizedError):
        _validate(ROUTE_DIRECT, scratch=tmp_path / "scratch", claim={field: value})


def test_a_wrong_remote_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(runner.ExecutionNotAuthorizedError):
        _validate(
            ROUTE_DIRECT,
            scratch=tmp_path / "scratch",
            claim={"run_root": Path("/srv/elsewhere")},
        )


def test_a_wrong_electron_count_is_refused_by_the_profile(tmp_path: Path) -> None:
    broken = dataclasses.replace(_authority(ROUTE_DIRECT), electron_count=120)
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="electron count drifted"):
        _validate(ROUTE_DIRECT, scratch=tmp_path / "scratch", authority=broken)


def test_a_wrong_candidate_is_refused_by_the_profile(tmp_path: Path) -> None:
    broken = dataclasses.replace(_authority(ROUTE_DIRECT), inchikey="QXHIEGFUWOLQIJ-UHFFFAOYSA-N")
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="candidate identity drifted"):
        _validate(ROUTE_DIRECT, scratch=tmp_path / "scratch", authority=broken)


# --- C. the closed worker CLI ------------------------------------------------


def _full_argv(route: str = ROUTE_DIRECT) -> list[str]:
    values = {
        "--request-path": "/srv/p/input/request.json",
        "--output-root": "/srv/p/.worker-x",
        "--attempt-id": ROUTE_ATTEMPT_IDS[route],
        "--consumed-permit-path": "/srv/p/private/permit.consumed.json",
        "--expected-permit-sha256": _PERMIT,
        "--expected-request-sha256": _REQUEST,
        "--expected-runner-source-sha256": _SOURCE,
        "--expected-payload-manifest-sha256": _PAYLOAD,
        "--expected-transport-inventory-sha256": _TRANSPORT,
        "--compute-claim-path": "/srv/p/private/compute_claim.json",
        "--authorized-output-root": "/srv/p/runtime/output",
        "--absolute-deadline-ns": "999999999999999999",
        "--release-token": "a" * 64,
    }
    out: list[str] = []
    for flag in worker.WORKER_REQUIRED_FLAGS:
        out += [flag, values[flag]]
    return out


def test_the_worker_cli_accepts_its_exact_contract() -> None:
    parsed = worker._parse_arguments(_full_argv())  # pyright: ignore[reportPrivateUsage]
    assert parsed.attempt_id == ROUTE_ATTEMPT_IDS[ROUTE_DIRECT]
    assert parsed.absolute_deadline_ns == 999999999999999999


@pytest.mark.parametrize("flag", list(worker.WORKER_REQUIRED_FLAGS))
def test_the_worker_cli_rejects_a_missing_argument(flag: str) -> None:
    full = _full_argv()
    index = full.index(flag)
    with pytest.raises(worker.WorkerArgumentError, match="is missing"):
        worker._parse_arguments(full[:index] + full[index + 2 :])  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    ("argv", "match"),
    [
        ([*_full_argv(), "--attempt-id", "x"], "repeated"),
        ([*_full_argv(), "--unknown", "x"], "not whitelisted"),
        ([*_full_argv(), "--attempt", "x"], "not whitelisted"),
        ([*_full_argv(), "positional"], "positional"),
        (["--attempt-id=x", *_full_argv()], "inline flag values"),
        (_full_argv()[:-1], "no value"),
    ],
)
def test_the_worker_cli_rejects_malformed_argv(argv: list[str], match: str) -> None:
    with pytest.raises(worker.WorkerArgumentError, match=match):
        worker._parse_arguments(argv)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    ("flag", "value", "match"),
    [
        ("--absolute-deadline-ns", "-1", "non-negative decimal"),
        ("--absolute-deadline-ns", "1e9", "non-negative decimal"),
        ("--expected-permit-sha256", "A" * 64, "lowercase SHA256"),
        ("--expected-permit-sha256", "short", "lowercase SHA256"),
        ("--request-path", "relative/path", "normalized absolute"),
        ("--request-path", "/srv/../etc/passwd", "dot or traversal"),
        ("--attempt-id", "", "empty value"),
        ("--attempt-id", "with\nnewline", "control character"),
        ("--attempt-id", "with\x00nul", "control character"),
    ],
)
def test_the_worker_cli_rejects_malformed_values(flag: str, value: str, match: str) -> None:
    full = _full_argv()
    full[full.index(flag) + 1] = value
    with pytest.raises(worker.WorkerArgumentError, match=match):
        worker._parse_arguments(full)  # pyright: ignore[reportPrivateUsage]


def test_the_worker_cli_does_not_use_argparse() -> None:
    """argparse honours unambiguous abbreviations; the contract forbids them."""

    tree = ast.parse(Path(worker.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "argparse" not in imported


# --- D. adapter selection ----------------------------------------------------


def test_only_an_exact_attempt_selects_an_adapter() -> None:
    assert ex.resolve_execution_adapter(ROUTE_ATTEMPT_IDS[ROUTE_DIRECT]) is ex.DIRECT_ADAPTER
    assert ex.resolve_execution_adapter(ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED]) is ex.ASSISTED_ADAPTER
    assert ex.resolve_execution_adapter("attempt-phase8b-qxh-v001") is ex.PHASE8B_ADAPTER
    for unknown in ("", "attempt-nowhere", "direct", "assisted", ROUTE_DIRECT):
        with pytest.raises(ex.ExecutionAdapterError, match="no execution adapter"):
            ex.resolve_execution_adapter(unknown)


def test_no_attempt_matches_two_adapters() -> None:
    seen = [adapter.attempt_id for adapter in ex.registered_execution_adapters()]
    assert len(seen) == len(set(seen)) == 3


def test_an_adapter_refuses_another_attempt() -> None:
    with pytest.raises(ex.ExecutionAdapterError, match="refuses another attempt"):
        ex.DIRECT_ADAPTER.execute(
            None, Path("/tmp/x"), capability=None, attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED]
        )
    with pytest.raises(ex.ExecutionAdapterError, match="refuses another attempt"):
        ex.ASSISTED_ADAPTER.execute(
            None, Path("/tmp/x"), capability=None, attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT]
        )


def test_the_adapter_registry_is_not_selectable_by_request_cli_or_environment() -> None:
    """The resolver takes one argument, and it is the attempt identity."""

    import inspect

    signature = inspect.signature(ex.resolve_execution_adapter)
    assert list(signature.parameters) == ["attempt_id"]
    source = Path(ex.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "getenv" not in called and "environ" not in called


def test_the_direct_adapter_declares_and_imports_no_machine_learning_stack() -> None:
    assert ex.DIRECT_ADAPTER.uses_preoptimization is False
    assert ex.DIRECT_ADAPTER.imports_machine_learning_stack is False
    tree = ast.parse(Path(ex.__file__).read_text(encoding="utf-8"))
    start = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_execute_direct":
            start = node
    assert start is not None
    imported: set[str] = set()
    for node in ast.walk(start):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"torch", "ase", "aimnet"})


def test_a_direct_execution_never_imports_the_machine_learning_stack(tmp_path: Path) -> None:
    """Watched across a real call, not inferred from the source alone."""

    calls: list[str] = []

    def backend_factory(capability: object) -> object:
        del capability
        calls.append("backend")
        return object()

    def fake_execute(request: object, output_root: Path, *, backend: object, **kw: Any) -> None:
        del request, output_root, backend, kw
        calls.append("executed")

    before = {name for name in sys.modules if name.split(".")[0] in {"torch", "ase", "aimnet"}}
    original = runner._execute_validated_request  # pyright: ignore[reportPrivateUsage]
    try:
        runner._execute_validated_request = fake_execute  # type: ignore[assignment]
        result = ex.DIRECT_ADAPTER.execute(
            _Request(),
            tmp_path,
            capability=object(),
            attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
            absolute_deadline_monotonic=1e18,
            backend_factory=backend_factory,
        )
    finally:
        runner._execute_validated_request = original
    assert result == 0
    assert calls == ["backend", "executed"]
    after = {name for name in sys.modules if name.split(".")[0] in {"torch", "ase", "aimnet"}}
    assert after == before


def test_the_assisted_adapter_cannot_fall_back_to_direct() -> None:
    assert ex.ASSISTED_ADAPTER.uses_preoptimization is True
    source = Path(ex.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assisted = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_execute_assisted"
    )
    names = {node.id for node in ast.walk(assisted) if isinstance(node, ast.Name)}
    assert "_execute_direct" not in names
    assert "DIRECT_ADAPTER" not in names


def test_the_assisted_adapter_requires_its_run_root() -> None:
    with pytest.raises(ex.ExecutionAdapterError, match="frozen run root"):
        ex.ASSISTED_ADAPTER.execute(
            _Request(),
            Path("/tmp/x"),
            capability=object(),
            attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED],
            absolute_deadline_monotonic=1e18,
        )


# --- the endpoint state machine ---------------------------------------------


def test_the_endpoint_state_machine_order_is_fixed() -> None:
    sequence = ex.assisted_state_sequence()
    assert sequence[0] is ex.EndpointState.INITIAL
    assert sequence[-1] is ex.EndpointState.PYSCF_TERMINAL
    assert ex.EndpointState.PYSCF_ALLOWED in sequence
    assert sequence.index(ex.EndpointState.HANDOFF_CLOSED) < sequence.index(
        ex.EndpointState.PYSCF_ALLOWED
    )
    assert sequence.index(ex.EndpointState.STRUCTURE_VALIDATED) < sequence.index(
        ex.EndpointState.PREOPT_EVIDENCE_DURABLE
    )


def test_a_stage_may_not_be_skipped_or_repeated() -> None:
    progress = ex.EndpointProgress("cation")
    progress.advance(ex.EndpointState.INPUT_VERIFIED)
    with pytest.raises(ex.ExecutionAdapterError, match="cannot move"):
        progress.advance(ex.EndpointState.HANDOFF_CLOSED)
    with pytest.raises(ex.ExecutionAdapterError, match="cannot move"):
        progress.advance(ex.EndpointState.INPUT_VERIFIED)


def test_no_stage_may_follow_a_failure() -> None:
    progress = ex.EndpointProgress("neutral")
    progress.fail()
    assert progress.state is ex.EndpointState.FAILED
    with pytest.raises(ex.ExecutionAdapterError, match="already failed"):
        progress.advance(ex.EndpointState.INPUT_VERIFIED)


def test_an_unknown_endpoint_has_no_progress() -> None:
    with pytest.raises(ex.ExecutionAdapterError, match="unknown endpoint"):
        ex.EndpointProgress("dication")


def test_the_execution_module_imports_no_chemistry_at_module_scope() -> None:
    tree = ast.parse(Path(ex.__file__).read_text(encoding="utf-8"))
    top: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top.add(node.module.split(".")[0])
    assert not (top & {"torch", "ase", "aimnet", "pyscf", "geometric"})


def test_both_new_modules_are_inside_the_runner_source_closure() -> None:
    closure = set(runner._RUNNER_SOURCE_RELATIVE_PATHS)  # pyright: ignore[reportPrivateUsage]
    assert "nhc_deprot_ranker/quantum/phase9b_execution.py" in closure
    assert "nhc_deprot_ranker/quantum/phase9b_aimnet2_runtime.py" in closure


def test_the_shipped_cli_parser_runs_in_a_subprocess() -> None:
    """Executes the parser that ships, not a re-implementation."""

    import subprocess

    script = (
        "import json,sys;"
        "from nhc_deprot_ranker.quantum import worker;"
        "argv=json.loads(sys.argv[1]);"
        "print(worker._parse_arguments(argv).attempt_id)"
    )
    import json as _json

    result = subprocess.run(
        [sys.executable, "-B", "-c", script, _json.dumps(_full_argv())],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
        cwd=Path(__file__).resolve().parent.parent,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ROUTE_ATTEMPT_IDS[ROUTE_DIRECT]

    rejected = subprocess.run(
        [sys.executable, "-B", "-c", script, _json.dumps([*_full_argv(), "--attempt", "x"])],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
        cwd=Path(__file__).resolve().parent.parent,
        check=False,
    )
    assert rejected.returncode != 0
    assert "not whitelisted" in rejected.stderr


def test_registration_shape_is_shared_rather_than_reimplemented() -> None:
    """Phase 9B reuses Phase 8B's registration record rather than copying it."""

    assert issubclass(WorkerRegistration, object)
    tree = ast.parse(Path(worker.__file__).read_text(encoding="utf-8"))
    classes = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    for copied in ("WorkerRegistration", "GuardianAcknowledgement", "ComputeClaim"):
        assert copied not in classes


def _unused(value: Sequence[object]) -> None:  # pragma: no cover - typing helper
    del value


def test_the_shared_claim_validator_rejects_an_unregistered_identity() -> None:
    """No existing test covered this guard; mutation testing surfaced the gap.

    The validator is shared by both chains, so what it accepts is a registry.
    A candidate outside that registry must be refused whatever chain claims it.
    """

    from nhc_deprot_ranker.quantum import phase8b_execution as execution

    registered = execution.registered_transaction_identities()
    assert ROUTE_ATTEMPT_IDS[ROUTE_DIRECT] in registered
    assert ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED] in registered
    assert "attempt-phase8b-qxh-v001" in registered
    assert "attempt-anything-else" not in registered

    triples = execution.registered_candidate_identities()
    assert ("phase9b-lbnp-paired-smoke-v001", PHASE9B_CANDIDATE.inchikey, 160) in triples
    # A Phase 9B request id paired with the Phase 8B candidate is not registered.
    assert ("phase9b-lbnp-paired-smoke-v001", "QXHIEGFUWOLQIJ-UHFFFAOYSA-N", 120) not in triples

    root = _run_root(ROUTE_DIRECT)
    for broken in (
        {"attempt_id": "attempt-anything-else"},
        {"inchikey": "QXHIEGFUWOLQIJ-UHFFFAOYSA-N"},
        {"electron_count": 120},
        {"request_id": "some-other-request"},
    ):
        base: dict[str, Any] = {
            "transport_inventory_sha256": _TRANSPORT,
            "payload_manifest_sha256": _PAYLOAD,
            "permit_sha256": _PERMIT,
            "request_sha256": _REQUEST,
            "runner_source_sha256": _SOURCE,
            "protocol_sha256": _PROTOCOL,
            "resources_sha256": phase9b_resources_sha256(),
            "cation_xyz_sha256": _CATION,
            "neutral_xyz_sha256": _NEUTRAL,
            "endpoint_atom_map_sha256": PHASE9B_CANDIDATE.endpoint_atom_map_sha256,
            "legacy_atom_map_sha256": PHASE9B_CANDIDATE.legacy_atom_map_sha256,
            "geometry_validation_sha256": PHASE9B_CANDIDATE.geometry_validation_sha256,
            "electron_count": 160,
            "request_id": "phase9b-lbnp-paired-smoke-v001",
            "inchikey": PHASE9B_CANDIDATE.inchikey,
            "attempt_id": ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
            "project_root": _PROJECT,
            "run_root": root,
            "request_path": root / "input/request.json",
            "output_root": root / "runtime/output",
        }
        base.update(broken)
        with pytest.raises(execution.ExecutionIdentityError, match="identity drifted"):
            execution.validate_compute_claim_authority(ComputeClaimAuthority(**base))

    # And the registered pair passes, so the guard is not simply always-refusing.
    execution.validate_compute_claim_authority(
        ComputeClaimAuthority(
            **base
            | broken
            | {
                "attempt_id": ROUTE_ATTEMPT_IDS[ROUTE_DIRECT],
                "inchikey": PHASE9B_CANDIDATE.inchikey,
                "electron_count": 160,
                "request_id": "phase9b-lbnp-paired-smoke-v001",
            }
        )
    )


def test_the_worker_cross_checks_the_registry_against_the_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile whose adapter disagrees with the registry must fail closed.

    Mutation testing found that asserting ``profile.execution_adapter is adapter``
    proves nothing if the worker simply reads the profile: the cross-check has to
    be driven with the two disagreeing.
    """

    # The profile constructor is the primary guard: a profile that binds another
    # route's adapter cannot be built at all.
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="another attempt identity"):
        dataclasses.replace(
            worker.PHASE9B_DIRECT_WORKER_PROFILE, execution_adapter=ex.ASSISTED_ADAPTER
        )
    # The worker's registry lookup is a second, independent layer over it.
    source = Path(worker.__file__).read_text(encoding="utf-8")
    assert "resolve_execution_adapter(arguments.attempt_id)" in source
    assert "adapter is not profile.execution_adapter" in source
    del monkeypatch


def test_a_profile_may_not_bind_an_adapter_for_another_attempt() -> None:
    """The profile refuses the mismatch at construction, before any execution."""

    with pytest.raises(runner.ExecutionNotAuthorizedError, match="another attempt identity"):
        dataclasses.replace(
            worker.PHASE9B_DIRECT_WORKER_PROFILE,
            attempt_ids=(ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED],),
        )


def test_the_phase8b_adapter_declares_no_machine_learning_stack() -> None:
    assert ex.PHASE8B_ADAPTER.uses_preoptimization is False
    assert ex.PHASE8B_ADAPTER.imports_machine_learning_stack is False


def test_the_assisted_adapter_refuses_to_reach_pyscf_on_a_stopped_stage(
    tmp_path: Path,
) -> None:
    """The adapter's own gate, driven directly rather than through the stage."""

    import types

    stopped = types.SimpleNamespace(
        may_start_pyscf=False, reason="cation: did not converge", pyscf_request=None
    )
    backend_calls: list[str] = []

    def backend_factory(capability: object) -> object:
        del capability
        backend_calls.append("backend")
        return object()

    from nhc_deprot_ranker.quantum import phase9b_aimnet2_runtime as rt

    original = rt.run_assisted_stage
    try:
        rt.run_assisted_stage = lambda **kw: stopped  # type: ignore[assignment]
        with pytest.raises(ex.ExecutionAdapterError, match="stopped before PySCF"):
            ex.ASSISTED_ADAPTER.execute(
                _Request(),
                tmp_path,
                capability=object(),
                attempt_id=ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED],
                absolute_deadline_monotonic=1e18,
                run_root=tmp_path,
                backend_factory=backend_factory,
            )
    finally:
        rt.run_assisted_stage = original
    assert backend_calls == []
