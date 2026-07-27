"""No-chemistry contract tests for the Phase 9B-U2 remote harness."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from nhc_deprot_ranker.preparation import phase9b_u2_environment as u2


class _Calculator:
    def __init__(self, events: list[dict[str, object]], *, calls_per_read: int = 1) -> None:
        self.events = events
        self.calls_per_read = calls_per_read

    def read(self, property_name: str, atom_count: int) -> object:
        for _ in range(self.calls_per_read):
            self.events.append({"properties": [property_name], "entry": "AIMNet2ASE.calculate"})
        if property_name == "energy":
            return -12.5
        return [[0.01, -0.02, 0.03] for _ in range(atom_count)]


class _Atoms:
    def __init__(self, spec: u2.EndpointSpec, *, fail_forces: bool = False) -> None:
        self.spec = spec
        self.calc: object = object()
        self.fail_forces = fail_forces
        self.read_sequence: list[str] = []

    def get_potential_energy(self) -> float:
        self.read_sequence.append("energy")
        calculator = self.calc
        assert isinstance(calculator, _Calculator)
        return float(calculator.read("energy", len(self.spec.elements)))

    def get_forces(self) -> Sequence[Sequence[float]]:
        self.read_sequence.append("forces")
        if self.fail_forces:
            raise RuntimeError("synthetic neutral force failure")
        calculator = self.calc
        assert isinstance(calculator, _Calculator)
        value = calculator.read("forces", len(self.spec.elements))
        assert isinstance(value, list)
        return value

    def get_positions(self) -> Sequence[Sequence[float]]:
        return self.spec.coordinates


class _Model:
    def __init__(self, *, calls_per_read: int = 1, model_load_count: int = 1) -> None:
        self.calls_per_read = calls_per_read
        self._model_load_count = model_load_count
        self.bind_count = 0

    @property
    def model_load_count(self) -> int:
        return self._model_load_count

    def bind(self, spec: u2.EndpointSpec) -> u2.CalculatorBinding:
        self.bind_count += 1
        events: list[dict[str, object]] = []
        return u2.CalculatorBinding(
            calculator=_Calculator(events, calls_per_read=self.calls_per_read),
            wrapper_identity=f"wrapper-{spec.endpoint}-{self.bind_count}",
            calculate_events=events,
        )


class _SameWrapperModel(_Model):
    def bind(self, spec: u2.EndpointSpec) -> u2.CalculatorBinding:
        binding = super().bind(spec)
        return u2.CalculatorBinding(
            calculator=binding.calculator,
            wrapper_identity="same-wrapper",
            calculate_events=binding.calculate_events,
        )


def _specs() -> tuple[u2.EndpointSpec, u2.EndpointSpec]:
    coordinates = ((0.0, 0.0, 0.0), (1.2, 0.0, 0.0))
    return (
        u2.EndpointSpec("cation", 1, 1, ("C", "H"), coordinates),
        u2.EndpointSpec("neutral", 0, 1, ("C", "H"), coordinates),
    )


def _store(tmp_path: Path) -> u2.DurableReceiptStore:
    root = tmp_path / "evidence"
    root.mkdir()
    return u2.DurableReceiptStore(root.resolve())


def _seed_prerequisites(store: u2.DurableReceiptStore) -> None:
    store.write("attempt_header.json", {"schema": u2.HARNESS_SCHEMA, "stage": 0})
    store.write("build_receipt.json", {"schema": u2.HARNESS_SCHEMA, "stage": 1})
    for order in ("ml_first", "pyscf_first"):
        summary_sha256 = u2.sha256_bytes(order.encode())
        store.write(
            f"import_{order}.json",
            {
                "schema": u2.HARNESS_SCHEMA,
                "stage": 2,
                "order": order,
                "return_code": 0,
                "summary_sha256": summary_sha256,
                "native_maps_durable": True,
                "native_gate_classification": "compatible",
            },
        )
        u2.acknowledge_child_receipt(
            store,
            child_name=f"import_{order}.json",
            acknowledgement_name=f"import_{order}_parent_ack.json",
            child_summary_sha256=summary_sha256,
        )


def _finally_payloads(_error: BaseException | None) -> Mapping[str, Mapping[str, object]]:
    return {
        "global_cache_after.json": {
            "schema": u2.HARNESS_SCHEMA,
            "global_cache_drift": False,
        },
        "weight_after.json": {"schema": u2.HARNESS_SCHEMA, "weight_unchanged": True},
        "target_environment_after.json": {
            "schema": u2.HARNESS_SCHEMA,
            "target_digest_complete": True,
        },
    }


def test_frozen_sequence_is_two_reads_and_two_calculate_calls_per_endpoint(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _seed_prerequisites(store)
    atoms: list[_Atoms] = []

    def factory(spec: u2.EndpointSpec) -> _Atoms:
        value = _Atoms(spec)
        atoms.append(value)
        return value

    terminal = u2.run_capability_smoke(
        store=store,
        specs=_specs(),
        model=_Model(),
        atoms_factory=factory,
        finally_payloads=_finally_payloads,
    )

    assert terminal["status"] == "validated"
    assert terminal["ledger"] == u2.EXPECTED_TOTALS
    assert [value.read_sequence for value in atoms] == [["energy", "forces"]] * 2
    for endpoint in u2.ENDPOINT_ORDER:
        receipt = store.read(f"capability_{endpoint}.json")
        assert receipt["property_read_count"] == 2
        assert receipt["calculate_call_count"] == 2
        assert [row["property"] for row in receipt["property_read_sequence"]] == [
            "energy",
            "forces",
        ]
    assert terminal["base_model_forward_calls"] == "unmeasured"


@pytest.mark.parametrize("observed", [2, 3, 5])
def test_total_calculate_counts_other_than_four_are_rejected(observed: int) -> None:
    totals = dict(u2.EXPECTED_TOTALS)
    totals["total_calculate_calls"] = observed
    with pytest.raises(u2.U2ContractRejected, match="metrology mismatch"):
        u2.validate_frozen_totals(totals)


def test_property_reads_and_calculator_calls_are_separate_ledgers() -> None:
    ledger = u2.MetrologyLedger()
    ledger.record_property("cation", "energy")
    totals = ledger.totals(model_load_count=1)
    assert totals["total_property_reads"] == 1
    assert totals["total_calculate_calls"] == 0
    assert ledger.property_reads[0]["counter_type"] == "ase_property_read"


def test_model_load_count_is_not_the_calculate_count() -> None:
    ledger = u2.MetrologyLedger()
    for name in ("energy", "forces"):
        ledger.record_property("cation", name)
        ledger.record_calculations("cation", name, [{"event": name}])
    totals = ledger.totals(model_load_count=1)
    assert totals["base_model_load_count"] == 1
    assert totals["total_calculate_calls"] == 2


def test_cation_and_neutral_must_have_distinct_wrappers(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_prerequisites(store)
    terminal = u2.run_capability_smoke(
        store=store,
        specs=_specs(),
        model=_SameWrapperModel(),
        atoms_factory=_Atoms,
        finally_payloads=_finally_payloads,
    )
    assert terminal["status"] == "rejected_environment"
    assert store.exists("capability_cation.json")
    assert not store.exists("capability_neutral.json")


def test_endpoint_evidence_is_durable_before_terminal_count_assertion(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_prerequisites(store)
    terminal = u2.run_capability_smoke(
        store=store,
        specs=_specs(),
        model=_Model(calls_per_read=0),
        atoms_factory=_Atoms,
        finally_payloads=_finally_payloads,
    )
    assert terminal["status"] == "rejected_environment"
    assert store.exists("capability_cation.json")
    assert store.read("capability_cation.json")["calculate_call_count"] == 0
    assert store.exists("global_cache_after.json")
    assert store.exists("terminal_receipt.json")


def test_endpoint_one_payload_survives_endpoint_two_failure(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_prerequisites(store)

    def factory(spec: u2.EndpointSpec) -> _Atoms:
        return _Atoms(spec, fail_forces=spec.endpoint == "neutral")

    terminal = u2.run_capability_smoke(
        store=store,
        specs=_specs(),
        model=_Model(),
        atoms_factory=factory,
        finally_payloads=_finally_payloads,
    )
    assert terminal["status"] == "failed_incomplete_environment"
    assert store.exists("capability_cation.json")
    assert not store.exists("capability_neutral.json")
    assert store.exists("global_cache_after.json")
    assert store.exists("target_environment_after.json")


def test_native_maps_are_required_before_capability(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write("attempt_header.json", {"schema": u2.HARNESS_SCHEMA})
    store.write("build_receipt.json", {"schema": u2.HARNESS_SCHEMA})
    terminal = u2.run_capability_smoke(
        store=store,
        specs=_specs(),
        model=_Model(),
        atoms_factory=_Atoms,
        finally_payloads=_finally_payloads,
    )
    assert terminal["status"] == "failed_incomplete_environment"
    assert not store.exists("capability_cation.json")
    assert store.write_order.index("global_cache_after.json") < store.write_order.index(
        "terminal_receipt.json"
    )


def test_child_payload_is_acknowledged_durably_before_parent_continues(tmp_path: Path) -> None:
    store = _store(tmp_path)
    summary = u2.sha256_bytes(b"child")
    child = store.write(
        "import_ml_first.json",
        {
            "summary_sha256": summary,
            "native_gate_classification": "compatible",
        },
    )
    acknowledgement = u2.acknowledge_child_receipt(
        store,
        child_name="import_ml_first.json",
        acknowledgement_name="import_ml_first_parent_ack.json",
        child_summary_sha256=summary,
    )
    with pytest.raises(RuntimeError, match="parent crash"):
        raise RuntimeError("parent crash after acknowledgement")
    assert store.read("import_ml_first.json") == child
    assert acknowledgement["child_receipt_sha256"] == child["receipt_sha256"]
    assert store.exists("import_ml_first_parent_ack.json")


class _FailingFinallyStore(u2.DurableReceiptStore):
    def write(self, name: str, payload: Mapping[str, object]) -> dict[str, object]:
        if name == "global_cache_after.json":
            raise OSError("synthetic cache receipt failure")
        return super().write(name, payload)


def test_finally_receipt_failure_becomes_indeterminate_but_other_evidence_is_attempted(
    tmp_path: Path,
) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    store = _FailingFinallyStore(root.resolve())
    _seed_prerequisites(store)
    terminal = u2.run_capability_smoke(
        store=store,
        specs=_specs(),
        model=_Model(),
        atoms_factory=_Atoms,
        finally_payloads=_finally_payloads,
    )
    assert terminal["status"] == "indeterminate_evidence_failure"
    assert not store.exists("global_cache_after.json")
    assert store.exists("weight_after.json")
    assert store.exists("target_environment_after.json")
    assert store.exists("terminal_receipt.json")


def test_append_only_receipts_refuse_overwrite(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write("attempt_header.json", {"attempt": "v002"})
    with pytest.raises(FileExistsError):
        store.write("attempt_header.json", {"attempt": "changed"})


def test_snapshot_key_sets_cannot_differ() -> None:
    with pytest.raises(u2.U2HarnessError, match="key sets differ"):
        u2.compare_registered_snapshots({"a": 1}, {"a": 1, "b": 2})
    assert u2.compare_registered_snapshots({"a": 1}, {"a": 1}) is True


def test_v002_resource_validation_has_no_v001_fallback_or_reuse(tmp_path: Path) -> None:
    parent = (tmp_path / "env" / "conda").resolve()
    parent.mkdir(parents=True)
    v001 = parent / "phase9b_unified_v001"
    v001.mkdir()
    v002 = parent / "phase9b_unified_v002"
    u2.validate_fresh_resource_paths(
        v002_paths=[v002], registered_parents=[parent], v001_paths=[v001]
    )
    with pytest.raises(u2.U2ContractRejected, match="v001"):
        u2.validate_fresh_resource_paths(
            v002_paths=[parent / "phase9b_unified_v001_fallback"],
            registered_parents=[parent],
            v001_paths=[v001],
        )
    v002.mkdir()
    with pytest.raises(u2.U2ContractRejected, match="already exists"):
        u2.validate_fresh_resource_paths(
            v002_paths=[v002], registered_parents=[parent], v001_paths=[v001]
        )


def test_hardlink_sharing_with_v001_is_rejected(tmp_path: Path) -> None:
    v001 = tmp_path / "v001"
    v002 = tmp_path / "v002"
    v001.mkdir()
    v002.mkdir()
    protected = v001 / "protected.whl"
    protected.write_bytes(b"artifact")
    os.link(protected, v002 / "copied.whl")
    with pytest.raises(u2.U2ContractRejected, match="shares a regular-file inode"):
        u2.assert_no_shared_regular_file_inodes(v002, [v001])


def test_harness_lives_outside_runner_source_closure() -> None:
    from nhc_deprot_ranker.quantum import two_endpoint

    assert (
        "nhc_deprot_ranker/preparation/phase9b_u2_environment.py"
        not in two_endpoint._RUNNER_SOURCE_RELATIVE_PATHS  # pyright: ignore[reportPrivateUsage]
    )


def test_harness_has_no_scientific_execution_or_transport_entry_points() -> None:
    source = Path(u2.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "geometric_solver.kernel",
        ".optimize(",
        "subprocess.run",
        "paramiko",
        "requests.get",
        "label =",
    ):
        assert forbidden not in source


def test_public_u2_evidence_is_consistent_with_rejected_terminal_state() -> None:
    repository = Path(__file__).resolve().parents[1]

    def load(name: str) -> dict[str, object]:
        value = json.loads((repository / "docs" / name).read_bytes())
        assert isinstance(value, dict)
        return value

    manifest = load("PHASE9B_UNIFIED_ENVIRONMENT_V002_MANIFEST.json")
    capability = load("PHASE9B_UNIFIED_ENVIRONMENT_V002_CAPABILITY.json")
    native = load("PHASE9B_UNIFIED_ENVIRONMENT_V002_NATIVE_MAPS.json")
    cache = load("PHASE9B_UNIFIED_ENVIRONMENT_V002_CACHE_RECEIPT.json")

    assert manifest["status"] == "rejected_environment"
    target = manifest["target_environment"]
    assert isinstance(target, dict)
    assert target["unified_execution_environment_identity_v2_issued"] is False
    assert target["environment_canonical_sha256"] is None
    formal = manifest["formal_protected_snapshot_gate"]
    assert isinstance(formal, dict)
    assert formal["accepted"] is False
    assert formal["all_six_tree_digests_counts_bytes_and_critical_metadata_equal"] is True

    totals = capability["totals"]
    assert isinstance(totals, dict)
    assert totals["total_property_reads"] == 4
    assert totals["total_calculate_calls"] == 4
    assert capability["base_model_forward_calls"] == "unmeasured"
    assert capability["environment_terminal_status"] == "rejected_environment"

    import_orders = native["import_orders"]
    assert isinstance(import_orders, dict)
    assert all(row["classification"] == "compatible" for row in import_orders.values())
    assert cache["global_cache_drift"] is False
    assert cache["external_internet_connect_send_calls"] == 0

    execution = manifest["execution"]
    assert isinstance(execution, dict)
    assert execution["all_public_execution_gates_false"] is True
    assert execution["production_high_fidelity_labels"] == 71
