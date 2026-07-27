"""Phase 9B-U2 metrology and append-only remote evidence harness.

This module is outside ``two_endpoint._RUNNER_SOURCE_RELATIVE_PATHS``. It does
not open a production execution gate and contains no optimizer, PySCF kernel,
gradient, D3, label, network client, package installer, or SSH implementation.
The server driver supplies already-authorized environment operations and the
real AIMNet2 objects through narrow protocols; this controller freezes the
property sequence, counts the actual calculator boundary, and makes evidence
durable before terminal assertions.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol, cast

HARNESS_SCHEMA: Final = "nhc-phase9b-unified-v002-harness-v1"
LOGICAL_NAME: Final = "nhc-phase9b-unified-v002"
BASE_MODEL_FORWARD_CALLS: Final = "unmeasured"
ENDPOINT_ORDER: Final = ("cation", "neutral")

EXPECTED_TOTALS: Final[dict[str, int]] = {
    "energy_property_reads": 2,
    "force_property_reads": 2,
    "total_property_reads": 4,
    "energy_calculate_calls": 2,
    "force_calculate_calls": 2,
    "total_calculate_calls": 4,
    "base_model_load_count": 1,
    "endpoint_wrapper_count": 2,
    "geometry_optimization_steps": 0,
    "pyscf_kernel_calls": 0,
    "pyscf_gradient_calls": 0,
    "labels": 0,
}

EXPECTED_RECEIPTS: Final = (
    "attempt_header.json",
    "build_receipt.json",
    "import_ml_first.json",
    "import_ml_first_parent_ack.json",
    "import_pyscf_first.json",
    "import_pyscf_first_parent_ack.json",
    "capability_cation.json",
    "capability_neutral.json",
    "global_cache_after.json",
    "weight_after.json",
    "target_environment_after.json",
    "terminal_receipt.json",
)


class U2HarnessError(RuntimeError):
    """The U2 contract could not be proved exactly."""


class U2ContractRejected(U2HarnessError):
    """Complete observations disagree with the frozen contract."""


class U2EvidenceFailure(U2HarnessError):
    """Critical finally evidence could not be made durable."""


def canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    """Return the one canonical JSON encoding used by every U2 receipt."""

    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _with_receipt_digest(payload: Mapping[str, object]) -> dict[str, object]:
    if "receipt_sha256" in payload:
        raise U2HarnessError("caller may not supply receipt_sha256")
    result = dict(payload)
    result["receipt_sha256"] = sha256_bytes(canonical_json_bytes(result))
    return result


def _verify_receipt_digest(payload: Mapping[str, object]) -> None:
    claimed = payload.get("receipt_sha256")
    unsigned = {key: value for key, value in payload.items() if key != "receipt_sha256"}
    if not isinstance(claimed, str) or claimed != sha256_bytes(canonical_json_bytes(unsigned)):
        raise U2EvidenceFailure("receipt digest is absent or invalid")


@dataclass(slots=True)
class DurableReceiptStore:
    """Exclusive, fsynced, re-read JSON receipts; never overwrite or unlink."""

    root: Path
    write_order: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.root.is_absolute():
            raise U2HarnessError("receipt root must be absolute")
        if self.root.is_symlink() or not self.root.is_dir():
            raise U2HarnessError("receipt root must be an existing non-symlink directory")

    def path_for(self, name: str) -> Path:
        if name not in EXPECTED_RECEIPTS:
            raise U2HarnessError(f"unregistered U2 receipt name: {name}")
        return self.root / name

    def write(self, name: str, payload: Mapping[str, object]) -> dict[str, object]:
        destination = self.path_for(name)
        durable = _with_receipt_digest(payload)
        raw = canonical_json_bytes(durable)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(destination, flags, 0o400)
        try:
            written = 0
            while written < len(raw):
                written += os.write(descriptor, raw[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory_fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        observed = destination.read_bytes()
        if observed != raw:
            raise U2EvidenceFailure(f"receipt bytes changed after fsync: {name}")
        decoded = self.read(name)
        if decoded != durable:
            raise U2EvidenceFailure(f"receipt payload changed after fsync: {name}")
        self.write_order.append(name)
        return decoded

    def read(self, name: str) -> dict[str, object]:
        path = self.path_for(name)
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode):
            raise U2EvidenceFailure(f"receipt is not a regular non-symlink file: {name}")
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict):
            raise U2EvidenceFailure(f"receipt is not a JSON object: {name}")
        payload = cast(dict[str, object], value)
        _verify_receipt_digest(payload)
        return payload

    def exists(self, name: str) -> bool:
        return self.path_for(name).exists()


@dataclass(frozen=True, slots=True)
class EndpointSpec:
    endpoint: str
    charge: int
    multiplicity: int
    elements: tuple[str, ...]
    coordinates: tuple[tuple[float, float, float], ...]

    def __post_init__(self) -> None:
        expected = {"cation": 1, "neutral": 0}
        if self.endpoint not in expected or self.charge != expected[self.endpoint]:
            raise U2HarnessError("endpoint charge is outside the frozen U2 contract")
        if self.multiplicity != 1:
            raise U2HarnessError("endpoint multiplicity must be one")
        if not self.elements or len(self.elements) != len(self.coordinates):
            raise U2HarnessError("endpoint atom and coordinate counts disagree")
        if any(
            len(row) != 3 or not all(math.isfinite(value) for value in row)
            for row in self.coordinates
        ):
            raise U2HarnessError("endpoint coordinates must be finite triples")


class AtomsLike(Protocol):
    calc: object

    def get_potential_energy(self) -> float: ...

    def get_forces(self) -> Sequence[Sequence[float]]: ...

    def get_positions(self) -> Sequence[Sequence[float]]: ...


@dataclass(frozen=True, slots=True)
class CalculatorBinding:
    calculator: object
    wrapper_identity: str
    calculate_events: list[dict[str, object]]


class ModelLike(Protocol):
    @property
    def model_load_count(self) -> int: ...

    def bind(self, spec: EndpointSpec) -> CalculatorBinding: ...


@dataclass(slots=True)
class MetrologyLedger:
    property_reads: list[dict[str, object]] = field(default_factory=list)
    calculate_calls: list[dict[str, object]] = field(default_factory=list)
    wrapper_identities: list[str] = field(default_factory=list)

    def record_property(self, endpoint: str, property_name: str) -> None:
        self.property_reads.append(
            {
                "endpoint": endpoint,
                "property": property_name,
                "ordinal": len(self.property_reads) + 1,
                "counter_type": "ase_property_read",
            }
        )

    def record_calculations(
        self, endpoint: str, property_name: str, events: Sequence[Mapping[str, object]]
    ) -> None:
        for event in events:
            self.calculate_calls.append(
                {
                    "endpoint": endpoint,
                    "triggering_property_read": property_name,
                    "ordinal": len(self.calculate_calls) + 1,
                    "counter_type": "aimnet2ase_calculate_call",
                    "observed_event": dict(event),
                }
            )

    def totals(self, *, model_load_count: int) -> dict[str, int]:
        energy_reads = sum(row["property"] == "energy" for row in self.property_reads)
        force_reads = sum(row["property"] == "forces" for row in self.property_reads)
        energy_calls = sum(
            row["triggering_property_read"] == "energy" for row in self.calculate_calls
        )
        force_calls = sum(
            row["triggering_property_read"] == "forces" for row in self.calculate_calls
        )
        return {
            "energy_property_reads": energy_reads,
            "force_property_reads": force_reads,
            "total_property_reads": len(self.property_reads),
            "energy_calculate_calls": energy_calls,
            "force_calculate_calls": force_calls,
            "total_calculate_calls": len(self.calculate_calls),
            "base_model_load_count": model_load_count,
            "endpoint_wrapper_count": len(self.wrapper_identities),
            "geometry_optimization_steps": 0,
            "pyscf_kernel_calls": 0,
            "pyscf_gradient_calls": 0,
            "labels": 0,
        }


def validate_frozen_totals(totals: Mapping[str, int]) -> None:
    """Reject any deviation, including historically tempting 2, 3, or 5."""

    if dict(totals) != EXPECTED_TOTALS:
        raise U2ContractRejected(
            f"frozen U2 metrology mismatch: expected={EXPECTED_TOTALS}, observed={dict(totals)}"
        )


def _coordinate_digest(rows: Sequence[Sequence[float]]) -> str:
    normalized = [[float(value) for value in row] for row in rows]
    return sha256_bytes(canonical_json_bytes({"coordinates_angstrom": normalized}))


def _atom_order_digest(elements: Sequence[str]) -> str:
    return sha256_bytes(canonical_json_bytes({"elements": list(elements)}))


def _finite_force_shape(
    forces: Sequence[Sequence[float]], atom_count: int
) -> tuple[bool, list[int]]:
    rows = [list(row) for row in forces]
    shape = [len(rows), 3]
    valid = len(rows) == atom_count and all(
        len(row) == 3 and all(math.isfinite(float(value)) for value in row) for row in rows
    )
    return valid, shape


def require_native_receipts(store: DurableReceiptStore) -> None:
    """Prove both child receipts and immediate parent acknowledgements exist."""

    store.read("attempt_header.json")
    store.read("build_receipt.json")
    for order in ("ml_first", "pyscf_first"):
        child = store.read(f"import_{order}.json")
        acknowledgement = store.read(f"import_{order}_parent_ack.json")
        if child.get("native_gate_classification") != "compatible":
            raise U2ContractRejected(f"{order} native-library gate is not compatible")
        if acknowledgement.get("child_receipt_sha256") != child.get("receipt_sha256"):
            raise U2EvidenceFailure(f"{order} parent acknowledgement does not bind child")


def acknowledge_child_receipt(
    store: DurableReceiptStore,
    *,
    child_name: str,
    acknowledgement_name: str,
    child_summary_sha256: str,
) -> dict[str, object]:
    """Persist the parent acknowledgement immediately after child delivery."""

    child = store.read(child_name)
    if child.get("summary_sha256") != child_summary_sha256:
        raise U2EvidenceFailure("child summary differs from its durable receipt")
    return store.write(
        acknowledgement_name,
        {
            "schema": HARNESS_SCHEMA,
            "child_receipt": child_name,
            "child_receipt_sha256": child["receipt_sha256"],
            "child_summary_sha256": child_summary_sha256,
            "acknowledged_immediately": True,
        },
    )


def _validate_endpoint_receipt(payload: Mapping[str, object]) -> None:
    if payload.get("energy_finite") is not True:
        raise U2ContractRejected("endpoint energy is not finite")
    if payload.get("forces_finite_and_shape_n3") is not True:
        raise U2ContractRejected("endpoint forces are not finite (N,3)")
    if payload.get("coordinates_unchanged") is not True:
        raise U2ContractRejected("capability smoke changed coordinates")
    if payload.get("property_read_count") != 2:
        raise U2ContractRejected("endpoint property-read count is not two")
    if payload.get("calculate_call_count") != 2:
        raise U2ContractRejected("endpoint calculate-call count is not two")


FinallyPayloadFactory = Callable[[BaseException | None], Mapping[str, Mapping[str, object]]]
AtomsFactory = Callable[[EndpointSpec], AtomsLike]


def run_capability_smoke(
    *,
    store: DurableReceiptStore,
    specs: Sequence[EndpointSpec],
    model: ModelLike,
    atoms_factory: AtomsFactory,
    finally_payloads: FinallyPayloadFactory,
) -> dict[str, object]:
    """Run the frozen property sequence and always attempt terminal evidence."""

    error: BaseException | None = None
    ledger = MetrologyLedger()
    completed: list[str] = []
    terminal_status = "validated"
    finally_errors: list[str] = []
    try:
        require_native_receipts(store)
        completed.append("native_gate")
        if tuple(spec.endpoint for spec in specs) != ENDPOINT_ORDER:
            raise U2ContractRejected("endpoint order is not cation then neutral")
        for spec in specs:
            atoms = atoms_factory(spec)
            before = tuple(tuple(float(value) for value in row) for row in atoms.get_positions())
            binding = model.bind(spec)
            if binding.wrapper_identity in ledger.wrapper_identities:
                raise U2ContractRejected("cation and neutral wrappers are not distinct")
            ledger.wrapper_identities.append(binding.wrapper_identity)
            atoms.calc = binding.calculator

            start = len(binding.calculate_events)
            energy = float(atoms.get_potential_energy())
            ledger.record_property(spec.endpoint, "energy")
            middle = len(binding.calculate_events)
            ledger.record_calculations(
                spec.endpoint, "energy", binding.calculate_events[start:middle]
            )

            forces = atoms.get_forces()
            ledger.record_property(spec.endpoint, "forces")
            end = len(binding.calculate_events)
            ledger.record_calculations(
                spec.endpoint, "forces", binding.calculate_events[middle:end]
            )
            after = tuple(tuple(float(value) for value in row) for row in atoms.get_positions())
            forces_valid, force_shape = _finite_force_shape(forces, len(spec.elements))
            totals = ledger.totals(model_load_count=model.model_load_count)
            endpoint_reads = [
                row for row in ledger.property_reads if row["endpoint"] == spec.endpoint
            ]
            endpoint_calls = [
                row for row in ledger.calculate_calls if row["endpoint"] == spec.endpoint
            ]
            receipt = store.write(
                f"capability_{spec.endpoint}.json",
                {
                    "schema": HARNESS_SCHEMA,
                    "endpoint": spec.endpoint,
                    "charge": spec.charge,
                    "multiplicity": spec.multiplicity,
                    "atom_order_sha256": _atom_order_digest(spec.elements),
                    "coordinate_input_sha256": _coordinate_digest(before),
                    "coordinate_output_sha256": _coordinate_digest(after),
                    "coordinates_unchanged": before == after,
                    "energy_ev": energy,
                    "energy_finite": math.isfinite(energy),
                    "force_shape": force_shape,
                    "forces_finite_and_shape_n3": forces_valid,
                    "property_read_sequence": endpoint_reads,
                    "calculate_call_sequence": endpoint_calls,
                    "property_read_count": len(endpoint_reads),
                    "calculate_call_count": len(endpoint_calls),
                    "cumulative_ledger": totals,
                    "model_load_count": model.model_load_count,
                    "wrapper_identity": binding.wrapper_identity,
                    "base_model_forward_calls": BASE_MODEL_FORWARD_CALLS,
                },
            )
            completed.append(f"capability_{spec.endpoint}")
            _validate_endpoint_receipt(receipt)
        totals = ledger.totals(model_load_count=model.model_load_count)
        validate_frozen_totals(totals)
    except BaseException as exc:
        error = exc
        terminal_status = (
            "rejected_environment"
            if isinstance(exc, U2ContractRejected)
            else "failed_incomplete_environment"
        )
    finally:
        try:
            snapshots = finally_payloads(error)
        except BaseException as exc:
            snapshots = {}
            finally_errors.append(f"finally_payloads:{type(exc).__name__}:{exc}")
        for name in (
            "global_cache_after.json",
            "weight_after.json",
            "target_environment_after.json",
        ):
            try:
                payload = snapshots[name]
                store.write(name, payload)
                completed.append(name.removesuffix(".json"))
            except BaseException as exc:
                finally_errors.append(f"{name}:{type(exc).__name__}:{exc}")
        if finally_errors:
            terminal_status = "indeterminate_evidence_failure"
        terminal_payload = {
            "schema": HARNESS_SCHEMA,
            "status": terminal_status,
            "completed_stages": completed,
            "missing_receipts": [
                name
                for name in EXPECTED_RECEIPTS
                if name != "terminal_receipt.json" and not store.exists(name)
            ],
            "failure_type": None if error is None else type(error).__name__,
            "failure_assertion": None if error is None else str(error),
            "finally_errors": finally_errors,
            "base_model_forward_calls": BASE_MODEL_FORWARD_CALLS,
            "ledger": ledger.totals(model_load_count=model.model_load_count),
        }
        try:
            terminal = store.write("terminal_receipt.json", terminal_payload)
        except BaseException as exc:
            raise U2EvidenceFailure("terminal receipt could not be made durable") from exc
    if finally_errors:
        return terminal
    if error is not None:
        return terminal
    return terminal


def compare_registered_snapshots(before: Mapping[str, object], after: Mapping[str, object]) -> bool:
    """Refuse the vacuous different-key-set comparison that affected U1 design."""

    if set(before) != set(after):
        raise U2HarnessError("before/after snapshot key sets differ")
    return dict(before) == dict(after)


def validate_fresh_resource_paths(
    *,
    v002_paths: Sequence[Path],
    registered_parents: Sequence[Path],
    v001_paths: Sequence[Path],
) -> None:
    """Read-only pre-write validation; no fallback and no directory creation."""

    if len(v002_paths) != len(registered_parents):
        raise U2HarnessError("each v002 root must have one registered parent")
    old = {path.resolve() for path in v001_paths}
    for path, parent in zip(v002_paths, registered_parents, strict=True):
        if not path.is_absolute() or not parent.is_absolute():
            raise U2HarnessError("resource identities must be absolute")
        if path.exists() or path.is_symlink():
            raise U2ContractRejected(f"v002 resource already exists: {path.name}")
        if parent.is_symlink() or not parent.is_dir():
            raise U2ContractRejected("registered resource parent is invalid")
        if path.parent.resolve() != parent.resolve():
            raise U2ContractRejected("v002 resource is outside its registered parent")
        if path.resolve() in old or "phase9b_unified_v001" in path.as_posix():
            raise U2ContractRejected("v002 resource falls back to v001")


def assert_no_shared_regular_file_inodes(v002_root: Path, protected_roots: Sequence[Path]) -> None:
    """Prove a built v002 tree has no hardlinked regular file from protected roots."""

    protected: set[tuple[int, int]] = set()
    for root in protected_roots:
        for path in root.rglob("*"):
            info = path.lstat()
            if stat.S_ISREG(info.st_mode):
                protected.add((info.st_dev, info.st_ino))
    for path in v002_root.rglob("*"):
        info = path.lstat()
        if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) in protected:
            raise U2ContractRejected("v002 shares a regular-file inode with protected state")
