from __future__ import annotations

import importlib
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest

import nhc_deprot_ranker.quantum as quantum_package
from nhc_deprot_ranker.quantum import phase8b_authority as authority_module
from nhc_deprot_ranker.quantum import phase8b_execution as execution
from nhc_deprot_ranker.quantum import phase8b_permit as permit_module
from nhc_deprot_ranker.quantum import two_endpoint as runner
from nhc_deprot_ranker.quantum import worker, worker_bootstrap
from nhc_deprot_ranker.quantum.linux_guardian import ProcessIdentity, send_start_release
from nhc_deprot_ranker.quantum.phase8b_authority import (
    PHASE7_GEOMETRY_VALIDATION_SHA256,
    ExactPhase8BAuthority,
)
from nhc_deprot_ranker.quantum.phase8b_permit import (
    FROZEN_ATTEMPT_ID,
    FROZEN_INCHIKEY,
    FROZEN_INPUT_SHA256,
    FROZEN_PROTOCOL_SHA256,
    FROZEN_REQUEST_ID,
    FROZEN_RESOURCES,
    ConsumedPhase8BPermit,
    Phase8BPermit,
)

_REQUEST_SHA256 = "1" * 64
_SOURCE_SHA256 = "2" * 64
_PERMIT_SHA256 = "3" * 64
_PAYLOAD_SHA256 = "4" * 64
_RELEASE_TOKEN = "5" * 64
_TRANSPORT_SHA256 = "6" * 64
_CPUS = frozenset({0, 1, 2, 3})
_BOOT_ID = "11111111-2222-3333-4444-555555555555"


def _endpoint(name: runner.EndpointName, root: Path) -> runner.EndpointRequest:
    return runner.EndpointRequest(
        name=name,
        xyz_relative_path=f"{name}.xyz",
        xyz_path=root / f"{name}.xyz",
        xyz_sha256=FROZEN_INPUT_SHA256[f"{name}_xyz"],
        charge=1 if name == "cation" else 0,
        multiplicity=1,
        electron_count=runner.FROZEN_ELECTRON_COUNT,
        geometry=runner.XYZGeometry(()),
    )


def _authorized_objects(
    tmp_path: Path,
) -> tuple[
    runner.TwoEndpointRequest,
    ConsumedPhase8BPermit,
    ExactPhase8BAuthority,
    Path,
    Path,
]:
    project_root = tmp_path.resolve()
    run_root = project_root / "run"
    request_path = run_root / "input/request.json"
    output_root = run_root / "runtime/output"
    output_root.parent.mkdir(parents=True)
    private_root = run_root / "private"
    private_root.mkdir(mode=0o700)
    private_root.chmod(0o700)
    consumed_path = private_root / "permit.consumed.json"
    ready_path = private_root / "permit.ready.json"
    request = runner.TwoEndpointRequest(
        schema_version=runner.REQUEST_SCHEMA_VERSION,
        request_id=FROZEN_REQUEST_ID,
        inchikey=FROZEN_INCHIKEY,
        execution_authorized=True,
        timeout_seconds=cast(int, FROZEN_RESOURCES["hard_wall_timeout_seconds"]),
        runner_source_sha256=_SOURCE_SHA256,
        request_path=request_path,
        request_sha256=_REQUEST_SHA256,
        protocol_sha256=FROZEN_PROTOCOL_SHA256,
        cation=_endpoint("cation", run_root),
        neutral=_endpoint("neutral", run_root),
    )
    permit = Phase8BPermit(
        request_sha256=_REQUEST_SHA256,
        runner_source_sha256=_SOURCE_SHA256,
        payload_manifest_sha256=_PAYLOAD_SHA256,
        project_root=project_root,
        run_root=run_root,
        request_path=request_path,
        output_root=output_root,
        ready_path=ready_path,
        consumed_path=consumed_path,
        raw_bytes=b"synthetic consumed permit\n",
        permit_sha256=_PERMIT_SHA256,
    )
    consumed = ConsumedPhase8BPermit(
        permit=permit,
        consumed_path=consumed_path,
        consumed_sha256=_PERMIT_SHA256,
    )
    exact = ExactPhase8BAuthority(
        request_sha256=_REQUEST_SHA256,
        runner_source_sha256=_SOURCE_SHA256,
        permit_sha256=_PERMIT_SHA256,
        payload_manifest_sha256=_PAYLOAD_SHA256,
        endpoint_atom_map_sha256=FROZEN_INPUT_SHA256["endpoint_atom_map"],
        legacy_atom_map_sha256=FROZEN_INPUT_SHA256["legacy_atom_map"],
        geometry_validation_sha256=PHASE7_GEOMETRY_VALIDATION_SHA256,
        electron_count=runner.FROZEN_ELECTRON_COUNT,
        request_id=FROZEN_REQUEST_ID,
        inchikey=FROZEN_INCHIKEY,
        attempt_id=FROZEN_ATTEMPT_ID,
        project_root=project_root.as_posix(),
        run_root=run_root.as_posix(),
        request_path=request_path.as_posix(),
        output_root=output_root.as_posix(),
        resources_sha256=runner._frozen_resources_sha256(),  # pyright: ignore[reportPrivateUsage]
    )
    scratch = output_root.parent / f".worker-{FROZEN_ATTEMPT_ID}-fixture"
    scratch.mkdir(mode=0o700)
    return request, consumed, exact, output_root, scratch


def _process_identity(pid: int, *, ppid: int) -> ProcessIdentity:
    return ProcessIdentity(
        pid=pid,
        ppid=ppid,
        pgid=pid,
        sid=pid,
        starttime_ticks=pid * 100,
        state="S",
        boot_id=_BOOT_ID,
        cpus_allowed=_CPUS,
    )


def _publish_compute_claim(
    *,
    request: runner.TwoEndpointRequest,
    consumed: ConsumedPhase8BPermit,
    exact: ExactPhase8BAuthority,
    scratch: Path,
    deadline_ns: int,
) -> tuple[
    Path,
    dict[int, ProcessIdentity],
]:
    run_root = consumed.permit.run_root
    paths = execution.TransactionPaths(
        registration=run_root / "private/worker_registration.json",
        acknowledgement=run_root / "private/guardian_acknowledgement.json",
        compute_claim=run_root / "private/compute_claim.json",
        receipt=run_root / "private/guardian_receipt.json",
    )
    guardian = _process_identity(91_001, ppid=2)
    supervisor = _process_identity(os.getppid(), ppid=guardian.pid)
    worker_identity = _process_identity(os.getpid(), ppid=supervisor.pid)
    identities = {
        guardian.pid: guardian,
        supervisor.pid: supervisor,
        worker_identity.pid: worker_identity,
    }
    created_ns = time.monotonic_ns()
    registration = execution.make_registration(
        transaction_id=FROZEN_ATTEMPT_ID,
        absolute_deadline_ns=deadline_ns,
        allowed_cpus=_CPUS,
        release_token=_RELEASE_TOKEN,
        guardian=guardian,
        supervisor=supervisor,
        worker=worker_identity,
        clock_ns=lambda: created_ns,
    )
    execution.write_registration(paths.registration, registration)
    acknowledgement = execution.make_acknowledgement(
        registration,
        clock_ns=lambda: created_ns + 1,
    )
    execution.write_acknowledgement(paths.acknowledgement, acknowledgement)
    claim_authority = execution.ComputeClaimAuthority(
        transport_inventory_sha256=_TRANSPORT_SHA256,
        payload_manifest_sha256=exact.payload_manifest_sha256,
        permit_sha256=exact.permit_sha256,
        request_sha256=exact.request_sha256,
        runner_source_sha256=exact.runner_source_sha256,
        protocol_sha256=request.protocol_sha256,
        resources_sha256=exact.resources_sha256,
        cation_xyz_sha256=request.cation.xyz_sha256,
        neutral_xyz_sha256=request.neutral.xyz_sha256,
        endpoint_atom_map_sha256=exact.endpoint_atom_map_sha256,
        legacy_atom_map_sha256=exact.legacy_atom_map_sha256,
        geometry_validation_sha256=exact.geometry_validation_sha256,
        electron_count=exact.electron_count,
        request_id=exact.request_id,
        inchikey=exact.inchikey,
        attempt_id=exact.attempt_id,
        project_root=consumed.permit.project_root,
        run_root=run_root,
        request_path=consumed.permit.request_path,
        output_root=consumed.permit.output_root,
    )
    claim = execution.make_compute_claim(
        authority=claim_authority,
        paths=paths,
        worker_scratch_path=scratch,
        registration=registration,
        acknowledgement=acknowledgement,
        clock_ns=lambda: created_ns + 2,
    )
    execution.write_compute_claim(paths.compute_claim, claim)
    return paths.compute_claim, identities


def test_fabricated_exact_authority_cannot_reach_compute_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _request, _consumed, fabricated, _output, _scratch = _authorized_objects(tmp_path)
    imported: list[str] = []

    def forbidden_import(name: str, package: str | None = None) -> object:
        del package
        imported.append(name)
        raise AssertionError("fabricated authority reached importlib")

    monkeypatch.setattr(runner, "EXECUTION_AUTHORIZED", True)
    monkeypatch.setattr(importlib, "import_module", forbidden_import)
    backend = runner.PySCFBackend(fabricated)
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="bootstrap-issued"):
        backend._load_modules()  # pyright: ignore[reportPrivateUsage]
    assert imported == []


def test_backend_is_not_exported_by_quantum_package() -> None:
    assert "PySCFBackend" not in quantum_package.__all__
    assert not hasattr(quantum_package, "PySCFBackend")


def test_valid_fake_authorized_worker_claims_capability_before_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, consumed, exact, output_root, scratch = _authorized_objects(tmp_path)
    deadline_ns = time.monotonic_ns() + 5_000_000_000
    compute_claim_path, identities = _publish_compute_claim(
        request=request,
        consumed=consumed,
        exact=exact,
        scratch=scratch,
        deadline_ns=deadline_ns,
    )
    imports: list[str] = []

    class FakeLib:
        threads = 1

        def num_threads(self, value: int | None = None) -> int:
            if value is not None:
                self.threads = value
            return self.threads

    fake_lib = FakeLib()

    class FakeMetadata:
        @staticmethod
        def version(distribution: str) -> str:
            assert distribution == "pyscf-dispersion"
            return runner.PYSCF_DISPERSION_VERSION

    fake_modules: dict[str, object] = {
        "pyscf.gto": object(),
        "pyscf.dft": object(),
        "pyscf.geomopt.geometric_solver": object(),
        "pyscf.lib": fake_lib,
        "pyscf.dispersion.dftd3": object(),
        "importlib.metadata": FakeMetadata(),
    }

    def fake_import(name: str, package: str | None = None) -> object:
        del package
        imports.append(name)
        return fake_modules[name]

    def fake_execute(
        worker_request: runner.TwoEndpointRequest,
        worker_output: Path,
        *,
        backend: runner.TwoEndpointBackend,
        attempt_id: str,
        absolute_deadline_monotonic: float,
    ) -> object:
        assert worker_request is request
        assert worker_output == scratch
        assert attempt_id == FROZEN_ATTEMPT_ID
        assert absolute_deadline_monotonic == deadline_ns / 1_000_000_000
        modules = backend._load_modules()  # type: ignore[attr-defined]
        assert modules.lib is fake_lib
        return object()

    monkeypatch.setattr(runner, "EXECUTION_AUTHORIZED", True)
    monkeypatch.setattr(runner, "load_two_endpoint_request", lambda path: request)
    monkeypatch.setattr(runner, "_validate_frozen_120_electron_pair", lambda *args: 120)
    monkeypatch.setattr(runner, "current_runner_source_sha256", lambda: _SOURCE_SHA256)
    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr(runner, "_execute_validated_request", fake_execute)
    monkeypatch.setattr(
        permit_module,
        "load_consumed_phase8b_permit",
        lambda *args, **kwargs: consumed,
    )
    monkeypatch.setattr(
        authority_module,
        "validate_exact_phase8b_authority",
        lambda *args, **kwargs: exact,
    )
    for name, value in runner.THREAD_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)

    argv = [
        "--request-path",
        str(request.request_path),
        "--output-root",
        str(scratch),
        "--attempt-id",
        FROZEN_ATTEMPT_ID,
        "--consumed-permit-path",
        str(consumed.consumed_path),
        "--expected-permit-sha256",
        _PERMIT_SHA256,
        "--expected-request-sha256",
        _REQUEST_SHA256,
        "--expected-runner-source-sha256",
        _SOURCE_SHA256,
        "--expected-payload-manifest-sha256",
        _PAYLOAD_SHA256,
        "--expected-transport-inventory-sha256",
        _TRANSPORT_SHA256,
        "--authorized-output-root",
        str(output_root),
        "--absolute-deadline-ns",
        str(deadline_ns),
        "--compute-claim-path",
        str(compute_claim_path),
        "--release-token",
        _RELEASE_TOKEN,
    ]
    read_fd, write_fd = os.pipe()
    send_start_release(write_fd, token=_RELEASE_TOKEN)

    def run_worker(arguments: Sequence[str], *, bootstrap_proof: object) -> int:
        assert tuple(arguments) == tuple(argv)
        return worker.main(
            arguments,
            bootstrap_proof=bootstrap_proof,
            identity_reader=lambda pid: identities[pid],
            task_affinity_reader=lambda pid: {pid: _CPUS},
        )

    result = worker_bootstrap.bootstrap_worker(
        start_fd=read_fd,
        release_token=_RELEASE_TOKEN,
        expected_parent_pid=os.getppid(),
        absolute_deadline_ns=deadline_ns,
        allowed_cpus=_CPUS,
        compute_claim_path=compute_claim_path,
        worker_args=argv,
        target=run_worker,
        install_pdeath=lambda parent_pid: None,
        affinity_reader=lambda pid: _CPUS,
        identity_reader=lambda pid: identities[pid],
        task_affinity_reader=lambda pid: {pid: _CPUS},
    )

    assert result == 0
    assert imports == list(fake_modules)


def test_compute_capability_constructor_rejects_normal_construction() -> None:
    with pytest.raises(TypeError, match="cannot be caller-constructed"):
        runner._Phase8BComputeCapability(  # pyright: ignore[reportPrivateUsage]
            seal=object(),
            pid=os.getpid(),
            absolute_deadline_ns=time.monotonic_ns() + 1_000_000_000,
            authority=object(),  # type: ignore[arg-type]
            protocol_sha256=FROZEN_PROTOCOL_SHA256,
            compute_claim_sha256="f" * 64,
        )
