"""The production AIMNet2 adapter and ASE/LBFGS optimizer, actually executed.

These tests run the real constructor and the real optimizer against the strict
fake stack in ``tests/fake_ml_stack.py``.  ``_load_base_model`` is never replaced
by a lambda: the gate wrapper is tested for refusing before any import, and the
construction core is tested for building exactly what Phase 9A-S4 proved is safe.
"""

from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path
from typing import Any

import fake_ml_stack as fake
import pytest

from nhc_deprot_ranker.quantum import phase9b_aimnet2_runtime as rt

_ML_ROOTS = {"torch", "ase", "aimnet"}
_WEIGHT = Path("/isolated/cache/aimnet/aimnet2_wb97m_d3_0.pt")
_ELEMENTS = ("C", "N", "N", "H")
_COORDS = ((0.0, 0.0, 0.0), (1.35, 0.0, 0.0), (-1.35, 0.0, 0.0), (0.0, 1.08, 0.0))


def _core(*, device: str = "cuda:0", weight: Path = _WEIGHT) -> Any:
    return rt._construct_base_model_after_authorization(weight_path=weight, device=device)


def _deadline(*, seconds: float = 900.0) -> float:
    return 1_000.0 + seconds


class _Clock:
    """A monotonic clock the test drives, so no test sleeps or races a wall."""

    def __init__(self, *, start: float = 1_000.0, tick: float = 0.001) -> None:
        self.now = start
        self.tick = tick

    def __call__(self) -> float:
        value = self.now
        self.now += self.tick
        return value


# --- the gate ----------------------------------------------------------------
def test_the_source_gate_is_closed_and_is_the_only_switch() -> None:
    assert rt.EXECUTION_AUTHORIZED is False
    source = Path(rt.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    gate = [
        node
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "EXECUTION_AUTHORIZED"
    ]
    assert len(gate) == 1
    assert isinstance(gate[0].value, ast.Constant) and gate[0].value.value is False


def test_a_closed_gate_refuses_before_any_machine_learning_import() -> None:
    for name in list(sys.modules):
        assert name.split(".")[0] not in _ML_ROOTS, f"{name} was already imported"
    with pytest.raises(rt.Aimnet2NotAuthorizedError, match="source execution gate is closed"):
        rt._load_base_model(weight_path=_WEIGHT, device="cuda:0")
    leaked = sorted(n for n in sys.modules if n.split(".")[0] in _ML_ROOTS)
    assert leaked == [], f"the closed gate let a machine-learning stack in: {leaked}"


def test_the_gate_cannot_be_opened_by_an_argument_or_the_environment() -> None:
    source = Path(rt.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            names = {a.arg for a in [*node.args.args, *node.args.kwonlyargs]}
            assert not names & {"authorized", "skip_gate", "force", "allow_execution"}
    gate_fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "enforce_source_execution_gate"
    )
    assert not gate_fn.args.args and not gate_fn.args.kwonlyargs, "the gate takes no argument"
    # Executable code only: the docstring explains why there is no switch, and
    # naively matching its text would make this assertion match itself.
    executable = [
        n
        for n in gate_fn.body
        if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
    ]
    rendered = "\n".join(ast.unparse(n) for n in executable)
    for banned in ("environ", "getenv", "argv", "open("):
        assert banned not in rendered, banned
    assert "EXECUTION_AUTHORIZED" in rendered


# --- the loader: scheme A, exactly ------------------------------------------
def test_the_construction_core_builds_scheme_a_exactly() -> None:
    with fake.installed() as ledger:
        model = _core()
        assert ledger.model_load_count == 1
        built = ledger.base_calculator_constructions[0]
        assert built == {
            "model": _WEIGHT.as_posix(),
            "device": "cuda:0",
            "compile_model": False,
        }
        assert ledger.load_model_calls == 0, "scheme B was used"
        assert ledger.eval_calls == 0, "the adapter added an .eval() call"
        assert ledger.compile_calls == 0, "torch.compile ran despite compile_model=False"
        assert model.load_count == 1
        assert model.device == "cuda:0"


@pytest.mark.parametrize(
    "weight",
    [
        Path("aimnet2_wb97m_d3_0.pt"),
        Path("cache/aimnet2_wb97m_d3_0.pt"),
    ],
)
def test_a_relative_weight_path_is_refused(weight: Path) -> None:
    with fake.installed(), pytest.raises(rt.Aimnet2RuntimeError, match="absolute"):
        _core(weight=weight)


def test_a_registry_alias_or_hugging_face_identifier_never_reaches_the_calculator() -> None:
    # The adapter has no code path that produces one, so the fake's refusal is
    # the backstop rather than the test: assert the source itself is clean.
    source = Path(rt.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "aimnet2" not in literals
    for banned in ("load_from_hf_repo", "get_registry_model_path", "huggingface_hub", "requests"):
        assert banned not in {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        }, banned


@pytest.mark.parametrize("device", ["cuda", "cpu", "cuda:x", "", "CUDA:0"])
def test_an_inexact_device_is_refused(device: str) -> None:
    with pytest.raises(rt.Aimnet2RuntimeError, match="device"):
        rt._verify_device(device)


def test_the_granted_gpu_index_is_the_one_used() -> None:
    rt._verify_device("cuda:2", gpu_index=2)
    with pytest.raises(rt.Aimnet2RuntimeError, match="not the one the route was granted"):
        rt._verify_device("cuda:3", gpu_index=2)


def test_the_production_source_carries_no_forbidden_call() -> None:
    tree = ast.parse(Path(rt.__file__).read_text(encoding="utf-8"))
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            calls.add(ast.unparse(node.func))
    for banned in ("torch.jit.load", "torch.load", "torch.compile", "load_model"):
        assert banned not in calls, f"the adapter calls {banned}"
    assert not any(name.endswith(".eval") for name in calls), "the adapter calls .eval()"


def test_the_adapter_does_not_import_the_scheme_b_loader() -> None:
    tree = ast.parse(Path(rt.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert "aimnet.models.base.load_model" not in imported
    assert not any(name.startswith("aimnet.models") for name in imported)
    assert "aimnet.calculators.AIMNet2ASE" in imported
    assert "aimnet.calculators.AIMNet2Calculator" in imported


# --- endpoint isolation ------------------------------------------------------
def test_one_base_model_yields_two_isolated_endpoint_wrappers() -> None:
    with fake.installed() as ledger:
        model = _core()
        cation = model.calculator_for(charge=1, multiplicity=1)
        neutral = model.calculator_for(charge=0, multiplicity=1)

        assert ledger.model_load_count == 1, "the weight was read more than once"
        assert len(ledger.endpoint_constructions) == 2
        assert {e["charge"] for e in ledger.endpoint_constructions} == {0, 1}
        assert all(e["mult"] == 1 for e in ledger.endpoint_constructions)
        assert all(e["validate_species"] is True for e in ledger.endpoint_constructions)
        # Both endpoints wrap the same base object; neither reloaded it.
        assert len({e["base_id"] for e in ledger.endpoint_constructions}) == 1

        assert cation is not neutral
        assert cation.endpoint == "cation" and cation.charge == 1
        assert neutral.endpoint == "neutral" and neutral.charge == 0
        assert cation._ase_calculator is not neutral._ase_calculator
        assert cation._ledger is not neutral._ledger


def test_a_second_wrapper_for_the_same_endpoint_is_refused() -> None:
    with fake.installed():
        model = _core()
        model.calculator_for(charge=1, multiplicity=1)
        with pytest.raises(rt.Aimnet2RuntimeError, match="second cation calculator"):
            model.calculator_for(charge=1, multiplicity=1)


@pytest.mark.parametrize(("charge", "multiplicity"), [(1, 2), (0, 3), (2, 1), (-1, 1)])
def test_an_off_contract_charge_or_multiplicity_is_refused(charge: int, multiplicity: int) -> None:
    with fake.installed():
        model = _core()
        with pytest.raises(rt.Aimnet2RuntimeError, match="not a Phase 9B endpoint"):
            model.calculator_for(charge=charge, multiplicity=multiplicity)


def test_each_call_builds_fresh_atoms_and_copies_the_coordinates() -> None:
    with fake.installed() as ledger:
        model = _core()
        cation = model.calculator_for(charge=1, multiplicity=1)
        mutable = [list(point) for point in _COORDS]
        first = cation.new_atoms(elements=_ELEMENTS, coordinates=mutable)
        second = cation.new_atoms(elements=_ELEMENTS, coordinates=mutable)

        assert first is not second
        assert len(ledger.atoms_constructions) == 2
        first.set_positions([[9.0, 9.0, 9.0]] * len(_ELEMENTS))
        assert mutable == [list(point) for point in _COORDS], "the input was mutated"
        assert second.get_positions() == [list(p) for p in _COORDS]


def test_the_element_order_may_not_change_for_an_endpoint() -> None:
    with fake.installed():
        cation = _core().calculator_for(charge=1, multiplicity=1)
        cation.new_atoms(elements=_ELEMENTS, coordinates=_COORDS)
        with pytest.raises(rt.Aimnet2RuntimeError, match="element order changed"):
            cation.new_atoms(elements=("N", "C", "N", "H"), coordinates=_COORDS)


def test_energy_and_forces_are_finite_and_correctly_shaped() -> None:
    with fake.installed():
        cation = _core().calculator_for(charge=1, multiplicity=1)
        cation.new_atoms(elements=_ELEMENTS, coordinates=_COORDS)
        energy, forces = cation.energy_and_forces(_COORDS)
        assert isinstance(energy, float) and energy == energy
        assert len(forces) == len(_ELEMENTS)
        assert all(len(row) == 3 for row in forces)
        assert all(value == value for row in forces for value in row)


# --- the production optimizer ------------------------------------------------
def _optimize(
    *,
    clock: _Clock | None = None,
    deadline: float | None = None,
    extra: bool = False,
) -> tuple[rt.OptimizerOutcome, Any, Any]:
    clock = clock or _Clock()
    with fake.installed(extra_convergence_evaluation=extra) as ledger:
        model = _core()
        cation = model.calculator_for(charge=1, multiplicity=1)
        optimizer = rt.AseLBFGSOptimizer(monotonic=clock)
        outcome = optimizer.optimize(
            calculator=cation,
            coordinates=_COORDS,
            elements=_ELEMENTS,
            fmax=rt.FMAX_EV_PER_ANGSTROM,
            max_steps=rt.MAX_STEPS,
            deadline_monotonic=deadline if deadline is not None else _deadline(),
        )
        return outcome, ledger, cation


def test_the_optimizer_uses_lbfgs_on_the_frozen_contract() -> None:
    outcome, ledger, _ = _optimize()
    assert len(ledger.lbfgs_constructions) == 1
    built = ledger.lbfgs_constructions[0]
    assert built["restart"] is None, "a restart file was allowed"
    assert built["trajectory"] is None, "ASE was allowed to write its own trajectory"
    # Everything else is left at ASE's own default, and pinned in the receipt.
    assert built["memory"] == 100
    assert built["damping"] == 1.0
    assert built["alpha"] == 70.0
    assert built["maxstep"] is None
    assert built["use_line_search"] is False
    assert outcome.converged is True
    assert outcome.terminal_state is rt.TerminalState.CONVERGED


def test_off_contract_fmax_or_steps_are_refused() -> None:
    clock = _Clock()
    with fake.installed():
        cation = _core().calculator_for(charge=1, multiplicity=1)
        optimizer = rt.AseLBFGSOptimizer(monotonic=clock)
        for kwargs in ({"fmax": 0.01}, {"max_steps": 500}):
            with pytest.raises(rt.Aimnet2RuntimeError, match="frozen optimizer contract"):
                optimizer.optimize(
                    calculator=cation,
                    coordinates=_COORDS,
                    elements=_ELEMENTS,
                    fmax=kwargs.get("fmax", rt.FMAX_EV_PER_ANGSTROM),
                    max_steps=kwargs.get("max_steps", rt.MAX_STEPS),
                    deadline_monotonic=_deadline(),
                )


def test_the_optimizer_refuses_an_undeclared_calculator() -> None:
    class _Bare:
        def energy_and_forces(self, coordinates: Any) -> Any:  # pragma: no cover
            raise AssertionError("must not be reached")

    optimizer = rt.AseLBFGSOptimizer(monotonic=_Clock())
    with pytest.raises(rt.Aimnet2RuntimeError, match="declared AseEndpointCalculator"):
        optimizer.optimize(
            calculator=_Bare(),  # type: ignore[arg-type]
            coordinates=_COORDS,
            elements=_ELEMENTS,
            fmax=rt.FMAX_EV_PER_ANGSTROM,
            max_steps=rt.MAX_STEPS,
            deadline_monotonic=_deadline(),
        )


def test_steps_come_from_ase_and_are_not_derived_from_the_frame_count() -> None:
    outcome, ledger, calculator = _optimize()
    assert outcome.steps >= 1
    # The initial frame is recorded at step zero, so frames == steps + 1 here --
    # but the runtime never computes it that way, and the counts prove it.
    assert outcome.trajectory_frames == outcome.steps + 1
    energy, force, invocations = calculator.evaluation_counts()
    assert invocations == len(ledger.calculate_calls)
    assert energy == force == invocations, (
        "ASE asked for energy and forces together, so one model execution "
        "increments both counters; the invocation count is the real cost"
    )
    assert invocations >= outcome.steps, "fewer model executions than steps is impossible"


def test_an_extra_convergence_evaluation_is_counted_not_assumed() -> None:
    plain, _, _ = _optimize()
    extra, _, calculator = _optimize(extra=True)
    _, _, invocations = calculator.evaluation_counts()
    assert invocations > extra.steps
    assert extra.calculator_invocations > plain.calculator_invocations, (
        "an ASE that re-reads the gradient must show up as more invocations"
    )


# --- the three deadline checkpoints -----------------------------------------
def test_an_expired_deadline_stops_before_anything_is_constructed() -> None:
    clock = _Clock(start=5_000.0)
    with fake.installed() as ledger:
        cation = _core().calculator_for(charge=1, multiplicity=1)
        optimizer = rt.AseLBFGSOptimizer(monotonic=clock)
        with pytest.raises(rt.Aimnet2TimeoutError, match="already passed"):
            optimizer.optimize(
                calculator=cation,
                coordinates=_COORDS,
                elements=_ELEMENTS,
                fmax=rt.FMAX_EV_PER_ANGSTROM,
                max_steps=rt.MAX_STEPS,
                deadline_monotonic=4_999.0,
            )
        assert ledger.lbfgs_constructions == [], "an optimizer was built past the deadline"
        assert ledger.calculate_calls == [], "a model ran past the deadline"


def test_a_deadline_crossed_mid_run_stops_the_route_with_evidence() -> None:
    # A coarse tick makes the clock cross the deadline part-way through the run.
    clock = _Clock(start=1_000.0, tick=3.0)
    outcome, ledger, _ = _optimize(clock=clock, deadline=1_020.0)
    assert outcome.terminal_state is rt.TerminalState.TIMEOUT
    assert outcome.converged is False
    assert outcome.failure_reason is not None
    assert outcome.trajectory_frames >= 1, "a timeout must still leave its last provable frame"
    assert outcome.trajectory[-1].is_terminal is True
    assert ledger.calculate_calls, "the run did start before it timed out"


def test_the_step_observer_records_a_frame_for_every_step() -> None:
    outcome, _, _ = _optimize()
    assert outcome.trajectory[0].is_initial is True
    assert outcome.trajectory[-1].is_terminal is True
    assert [f.frame_index for f in outcome.trajectory] == list(range(outcome.trajectory_frames))
    elapsed = [f.elapsed_seconds for f in outcome.trajectory]
    assert elapsed == sorted(elapsed), "elapsed time went backwards"


# --- trajectory as evidence --------------------------------------------------
def test_the_trajectory_carries_real_coordinates_and_diagnostics() -> None:
    outcome, _, _ = _optimize()
    first, last = outcome.trajectory[0], outcome.trajectory[-1]
    assert first.coordinates == tuple(tuple(p) for p in _COORDS)
    assert last.coordinates != first.coordinates, "the geometry never moved"
    assert last.coordinates == outcome.coordinates
    for frame in outcome.trajectory:
        assert frame.schema_version == rt.TRAJECTORY_SCHEMA_VERSION
        assert frame.charge == 1 and frame.multiplicity == 1
        assert frame.atom_count == len(_ELEMENTS)
        assert (
            frame.element_order_sha256 == hashlib.sha256(" ".join(_ELEMENTS).encode()).hexdigest()
        )
        assert len(frame.coordinates) == len(_ELEMENTS)
        assert frame.energy_ev == frame.energy_ev
        assert frame.max_force_ev_per_angstrom >= 0.0
    assert last.max_force_ev_per_angstrom < first.max_force_ev_per_angstrom


def test_the_trajectory_digest_is_over_the_bytes_that_are_written() -> None:
    outcome, _, _ = _optimize()
    raw = rt.serialize_trajectory(outcome.trajectory)
    assert hashlib.sha256(raw).hexdigest() == outcome.trajectory_sha256
    lines = raw.splitlines()
    assert len(lines) == outcome.trajectory_frames
    import json

    decoded = [json.loads(line) for line in lines]
    assert decoded[0]["is_initial"] is True
    assert decoded[-1]["is_terminal"] is True
    assert "coordinates" in decoded[0] and len(decoded[0]["coordinates"]) == len(_ELEMENTS)
    for field in ("energy_ev", "max_force_ev_per_angstrom", "optimizer_step"):
        assert field in decoded[0]


def test_the_trajectory_carries_no_scientific_result() -> None:
    outcome, _, _ = _optimize()
    raw = rt.serialize_trajectory(outcome.trajectory).decode()
    for banned in ("pyscf", "label", "kcal", "deprotonation", "promotion", "627.509474"):
        assert banned not in raw.lower()


def test_an_oversized_trajectory_is_refused() -> None:
    outcome, _, _ = _optimize()
    original = rt.MAX_TRAJECTORY_BYTES
    try:
        rt.MAX_TRAJECTORY_BYTES = 10  # type: ignore[misc]
        with pytest.raises(rt.Aimnet2RuntimeError, match="frozen size limit"):
            rt.serialize_trajectory(outcome.trajectory)
    finally:
        rt.MAX_TRAJECTORY_BYTES = original  # type: ignore[misc]


# --- the production factory --------------------------------------------------
def test_the_production_factory_returns_a_loader_and_an_optimizer() -> None:
    loader, optimizer = rt.build_production_assisted_runtime()
    assert loader is rt._load_base_model
    assert isinstance(optimizer, rt.AseLBFGSOptimizer)


def test_the_assisted_route_can_never_reach_an_endpoint_without_an_optimizer() -> None:
    source = Path(rt.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    stage = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_assisted_stage"
    )
    body = ast.get_source_segment(source, stage)
    assert body is not None
    assert "build_production_assisted_runtime" in body
    # The resolution must happen before the endpoint loop, so a missing optimizer
    # is found before the cation writes any durable evidence.
    assert body.index("build_production_assisted_runtime") < body.index("for endpoint in")
    endpoint = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_run_one_endpoint"
    )
    annotation = next(a.annotation for a in endpoint.args.kwonlyargs if a.arg == "optimizer")
    assert ast.unparse(annotation) == "Optimizer", "the endpoint still accepts a missing optimizer"


def test_no_request_field_can_select_the_production_optimizer() -> None:
    from nhc_deprot_ranker.quantum import phase9b_execution as ex

    source = Path(ex.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "run_assisted_stage"
    )
    passed = {kw.arg for kw in call.keywords}
    assert "optimizer" not in passed
    assert "model_loader" not in passed


# --- end to end: fake AIMNet2 -> real evidence -> handoff -> mock PySCF ------
def _weight_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A same-size synthetic weight, as the rest of the suite already uses.

    The name, symlink, regular-file and byte-size checks all run for real; only
    the digest constant is pointed at the synthetic file, so the state machine is
    reachable without committing an 8.4 MB model. The digest gate itself has its
    own tests against the registered value.
    """

    path = tmp_path / rt.AIMNET2_WEIGHT_FILENAME
    path.write_bytes(b"\0" * rt.AIMNET2_WEIGHT_BYTES)
    monkeypatch.setattr(rt, "AIMNET2_WEIGHT_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    return path


def _endpoint_geometry(*, acidic_proton: bool) -> tuple[tuple[str, ...], tuple]:
    """The candidate's own atom map, with N1-C2-N3 bonded and the rest apart.

    Only the cation carries the ring proton on N1, so the preregistered proton
    gates see exactly the connectivity the fixture intends.
    """

    from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE

    atom_map = PHASE9B_CANDIDATE.atom_map
    c2, n1, n3 = atom_map["C2_carbene"], atom_map["N1"], atom_map["N3"]
    head = max(c2, n1, n3) + 1
    elements = ["C"] * head
    elements[n1] = elements[n3] = "N"
    elements[c2] = "C"
    elements += ["H"] * (5 if acidic_proton else 4)
    points = [[index * 6.0, 0.0, 0.0] for index in range(len(elements))]
    points[c2] = [0.0, 0.0, 0.0]
    points[n1] = [1.35, 0.0, 0.0]
    points[n3] = [-1.35, 0.0, 0.0]
    if acidic_proton:
        points[head] = [2.35, 0.0, 0.0]
    return tuple(elements), tuple(tuple(row) for row in points)


def _write_xyz(path: Path, elements: tuple[str, ...], coords: tuple) -> bytes:
    raw = rt.render_xyz(elements, coords, comment="frozen initial geometry")
    path.write_bytes(raw)
    return raw


def test_the_whole_assisted_stage_runs_on_the_production_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real state machine, the real evidence writer, the real handoff gate."""

    import dataclasses

    from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE

    profile = PHASE9B_CANDIDATE
    geometry = {
        "cation": _endpoint_geometry(acidic_proton=True),
        "neutral": _endpoint_geometry(acidic_proton=False),
    }

    @dataclasses.dataclass(frozen=True)
    class _Endpoint:
        xyz_path: Path
        xyz_sha256: str
        charge: int
        multiplicity: int

    @dataclasses.dataclass(frozen=True)
    class _Request:
        cation: _Endpoint
        neutral: _Endpoint
        request_sha256: str
        runner_source_sha256: str

    def _endpoint(name: str, charge: int) -> _Endpoint:
        path = tmp_path / f"{name}.xyz"
        raw = _write_xyz(path, *geometry[name])
        return _Endpoint(path, hashlib.sha256(raw).hexdigest(), charge, 1)

    request = _Request(_endpoint("cation", 1), _endpoint("neutral", 0), "a" * 64, "b" * 64)
    run_root = tmp_path / "run"
    cache_root = run_root / rt.AIMNET2_CACHE_RELATIVE
    environment = rt.build_isolated_environment(cache_root=cache_root, gpu_index=0)
    weight = _weight_fixture(tmp_path, monkeypatch)

    clock = _Clock(tick=0.01)
    with fake.installed() as ledger:
        loader, optimizer = rt.build_production_assisted_runtime(monotonic=clock)

        def _loader(*, weight_path: Path, device: str) -> Any:
            # The gate is closed, so the production loader refuses; the
            # construction core is what this exercises, with the same arguments
            # the production loader would have passed it.
            rt._verify_device(device)
            return rt._construct_base_model_after_authorization(
                weight_path=weight_path, device=device
            )

        result = rt.run_assisted_stage(
            request=request,  # type: ignore[arg-type]
            run_root=run_root,
            attempt_id="attempt-phase9b-assisted-v001",
            gpu_index=0,
            absolute_deadline_monotonic=clock.now + 7200.0,
            model_loader=_loader,
            optimizer=optimizer,
            weight_path=weight,
            environ=environment,
            monotonic=clock,
            profile=profile,
        )
        del loader

    assert result.reason is None, result.reason
    assert result.may_start_pyscf is True
    assert result.model_load_count == 1
    assert ledger.model_load_count == 1, "the weight was read once for the whole route"
    assert len(ledger.endpoint_constructions) == 2
    assert len(ledger.lbfgs_constructions) == 2, "one optimizer per endpoint"
    assert all(b["restart"] is None for b in ledger.lbfgs_constructions)

    for endpoint in ("cation", "neutral"):
        trajectory = run_root / rt.AIMNET2_TREE_RELATIVE / endpoint / "trajectory.jsonl"
        raw = trajectory.read_bytes()
        assert raw.count(b"\n") >= 2, "the trajectory is not a placeholder"
        assert b"coordinates" in raw and b"energy_ev" in raw
        receipt = result.endpoints[0 if endpoint == "cation" else 1].preoptimization
        assert receipt.trajectory_sha256 == hashlib.sha256(raw).hexdigest()
        assert receipt.trajectory_frames == raw.count(b"\n")
        assert receipt.terminal_state == "converged"
        assert receipt.calculator_invocations >= receipt.optimizer_steps

    # The bytes PySCF is pointed at are the bytes the handoff receipt closed over.
    for endpoint, item in zip(("cation", "neutral"), result.endpoints, strict=True):
        rebound = getattr(result.pyscf_request, endpoint)
        assert rebound.xyz_path.read_bytes() == item.output_xyz_bytes
        assert rebound.xyz_sha256 == item.handoff.pyscf_input_xyz_sha256
        assert rt.pyscf_may_start(item.handoff)


def test_a_second_endpoint_never_starts_after_the_first_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE

    class _Refusing:
        def optimize(self, **kwargs: Any) -> Any:
            raise rt.Aimnet2RuntimeError("cation refused on purpose")

    import dataclasses

    profile = PHASE9B_CANDIDATE
    geometry = {
        "cation": _endpoint_geometry(acidic_proton=True),
        "neutral": _endpoint_geometry(acidic_proton=False),
    }

    @dataclasses.dataclass(frozen=True)
    class _E:
        xyz_path: Path
        xyz_sha256: str
        charge: int
        multiplicity: int

    @dataclasses.dataclass(frozen=True)
    class _R:
        cation: _E
        neutral: _E
        request_sha256: str
        runner_source_sha256: str

    def _mk(name: str, charge: int) -> _E:
        path = tmp_path / f"{name}.xyz"
        raw = _write_xyz(path, *geometry[name])
        return _E(path, hashlib.sha256(raw).hexdigest(), charge, 1)

    run_root = tmp_path / "run"
    cache_root = run_root / rt.AIMNET2_CACHE_RELATIVE
    clock = _Clock(tick=0.01)
    with fake.installed() as ledger:
        result = rt.run_assisted_stage(
            request=_R(_mk("cation", 1), _mk("neutral", 0), "a" * 64, "b" * 64),  # type: ignore[arg-type]
            run_root=run_root,
            attempt_id="attempt-phase9b-assisted-v001",
            gpu_index=0,
            absolute_deadline_monotonic=clock.now + 7200.0,
            weight_path=_weight_fixture(tmp_path, monkeypatch),
            model_loader=lambda *, weight_path, device: (
                rt._construct_base_model_after_authorization(weight_path=weight_path, device=device)
            ),
            optimizer=_Refusing(),  # type: ignore[arg-type]
            environ=rt.build_isolated_environment(cache_root=cache_root, gpu_index=0),
            monotonic=clock,
            profile=profile,
        )
    assert result.may_start_pyscf is False
    assert result.reason is not None and result.reason.startswith("cation:")
    assert result.endpoints == ()
    # The neutral endpoint never got a wrapper, so it never ran.
    assert [e["charge"] for e in ledger.endpoint_constructions] == [1]
    assert not (run_root / rt.AIMNET2_TREE_RELATIVE / "neutral").exists()


def test_the_direct_route_never_loads_the_fake_stack_either() -> None:
    """Even with a fake ML stack importable, the direct route must not touch it."""

    from nhc_deprot_ranker.quantum import phase9b_execution as ex

    assert ex.DIRECT_ADAPTER.imports_machine_learning_stack is False
    assert ex.DIRECT_ADAPTER.uses_preoptimization is False
    tree = ast.parse(Path(ex.__file__).read_text(encoding="utf-8"))
    direct = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_execute_direct"
    )
    # Executable code only.  The docstring says the words "torch", "ase" and
    # "aimnet" while promising not to use them, so a naive substring scan over
    # the whole function would match the promise instead of the code.
    body = [
        node
        for node in direct.body
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
    ]
    rendered = "\n".join(ast.unparse(node) for node in body)
    for banned in ("aimnet", "torch", "ase", "run_assisted_stage", "pyscf_may_start"):
        assert banned not in rendered, f"the direct route references {banned}"

    with fake.installed():
        before = {n for n in sys.modules if n.split(".")[0] in _ML_ROOTS}
        assert before, "the fake stack should be importable for this test to mean anything"
        ex.resolve_execution_adapter(ex.DIRECT_ADAPTER.attempt_id)
        after = {n for n in sys.modules if n.split(".")[0] in _ML_ROOTS}
        assert after == before, "resolving the direct adapter pulled in a machine-learning module"


# --- guards the first mutation round found nothing watching -----------------
def test_the_gate_wrapper_delegates_to_the_construction_core() -> None:
    """The wrapper must end in delegation, not in a refusal stub.

    Asserted structurally because the gate is closed: with it closed the
    delegation can never be reached at run time, so a stub left in its place
    would otherwise look exactly like correct fail-closed behaviour.
    """

    source = Path(rt.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    loader = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_load_base_model"
    )
    body = [
        n
        for n in loader.body
        if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
    ]
    assert isinstance(body[-1], ast.Return), "the loader does not end by returning"
    returned = body[-1].value
    assert isinstance(returned, ast.Call)
    assert ast.unparse(returned.func) == "_construct_base_model_after_authorization"
    # And the gate is read first, before any other statement.
    assert ast.unparse(body[0]) == "enforce_source_execution_gate()"
    assert not any(isinstance(n, ast.Raise) for n in body), "the loader still raises a stub"


@pytest.mark.parametrize("device", ["1", "0", "cuda", "cpu", "cuda:", "cuda:x", "CUDA:0", ""])
def test_every_inexact_device_string_is_refused(device: str) -> None:
    with pytest.raises(rt.Aimnet2RuntimeError):
        rt._verify_device(device)


def test_the_caller_coordinates_are_copied_not_aliased() -> None:
    with fake.installed():
        cation = _core().calculator_for(charge=1, multiplicity=1)
        mutable = [list(point) for point in _COORDS]
        atoms = cation.new_atoms(elements=_ELEMENTS, coordinates=mutable)
        before = atoms.get_positions()
        # Mutate the caller's list in place after handing it over.  An adapter
        # that aliased instead of copying would let this reach ASE.
        mutable[0][0] = 99.0
        mutable[1][2] = -99.0
        assert atoms.get_positions() == before, "the adapter aliased the caller's coordinates"


class _ScriptedClock:
    """Returns a fixed sequence, so a test can place the deadline exactly."""

    def __init__(self, values: list[float]) -> None:
        self.values = list(values)
        self.index = 0

    def __call__(self) -> float:
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return value


def test_only_the_step_observer_can_catch_a_deadline_crossed_after_an_evaluation() -> None:
    """Place the expiry between the after-probe and the observer.

    The evaluation-boundary probe reads the clock either side of the model call
    and sees a time still inside the budget; the deadline is crossed only by the
    time the step observer runs.  If the observer had no check of its own, this
    run would continue.
    """

    clock = _ScriptedClock([0.0, 1.0, 2.0, 500.0])
    with fake.installed() as ledger:
        cation = _core().calculator_for(charge=1, multiplicity=1)
        outcome = rt.AseLBFGSOptimizer(monotonic=clock).optimize(
            calculator=cation,
            coordinates=_COORDS,
            elements=_ELEMENTS,
            fmax=rt.FMAX_EV_PER_ANGSTROM,
            max_steps=rt.MAX_STEPS,
            deadline_monotonic=100.0,
        )
    assert outcome.terminal_state is rt.TerminalState.TIMEOUT
    assert outcome.trajectory_frames == 1
    assert outcome.trajectory[0].is_initial and outcome.trajectory[0].is_terminal
    assert len(ledger.calculate_calls) == 1, "a second evaluation ran after the deadline"
    # The discriminator: the observer fires at step zero, so a run it stops has
    # taken no step at all.  Without its own check the boundary probe would
    # still catch this -- but only on the *next* evaluation, one full LBFGS
    # step later, and that step would show up here.
    assert outcome.steps == 0, "an LBFGS step ran after the deadline had passed"


def test_a_timeout_is_reported_as_a_timeout_not_as_non_convergence(tmp_path: Path) -> None:
    """Operators must be able to tell a budget overrun from a bad optimization."""

    import dataclasses

    from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE

    class _TimedOut:
        def optimize(self, *, calculator: Any, coordinates: Any, elements: Any, **_: Any) -> Any:
            frame = rt.TrajectoryFrame(
                schema_version=rt.TRAJECTORY_SCHEMA_VERSION,
                endpoint=calculator.endpoint,
                frame_index=0,
                elapsed_seconds=0.0,
                charge=calculator.charge,
                multiplicity=calculator.multiplicity,
                atom_count=len(elements),
                element_order_sha256=hashlib.sha256(" ".join(elements).encode()).hexdigest(),
                coordinates=tuple(tuple(p) for p in coordinates),
                energy_ev=-1.0,
                max_force_ev_per_angstrom=9.0,
                calculator_invocation_index=1,
                optimizer_step=0,
                is_initial=True,
                is_terminal=True,
            )
            return rt.OptimizerOutcome(
                coordinates=frame.coordinates,
                converged=False,
                steps=3,
                energy_evaluations=4,
                force_evaluations=4,
                initial_max_force=9.0,
                final_max_force=9.0,
                trajectory_frames=1,
                trajectory=(frame,),
                terminal_state=rt.TerminalState.TIMEOUT,
                failure_reason="budget expired",
            )

    geometry = {
        "cation": _endpoint_geometry(acidic_proton=True),
        "neutral": _endpoint_geometry(acidic_proton=False),
    }

    @dataclasses.dataclass(frozen=True)
    class _E:
        xyz_path: Path
        xyz_sha256: str
        charge: int
        multiplicity: int

    @dataclasses.dataclass(frozen=True)
    class _R:
        cation: _E
        neutral: _E
        request_sha256: str
        runner_source_sha256: str

    def _mk(name: str, charge: int) -> _E:
        path = tmp_path / f"{name}.xyz"
        raw = _write_xyz(path, *geometry[name])
        return _E(path, hashlib.sha256(raw).hexdigest(), charge, 1)

    run_root = tmp_path / "run"
    clock = _Clock(tick=0.01)
    monkey = pytest.MonkeyPatch()
    try:
        with fake.installed():
            result = rt.run_assisted_stage(
                request=_R(_mk("cation", 1), _mk("neutral", 0), "a" * 64, "b" * 64),  # type: ignore[arg-type]
                run_root=run_root,
                attempt_id="attempt-phase9b-assisted-v001",
                gpu_index=0,
                absolute_deadline_monotonic=clock.now + 7200.0,
                weight_path=_weight_fixture(tmp_path, monkey),
                model_loader=lambda *, weight_path, device: (
                    rt._construct_base_model_after_authorization(
                        weight_path=weight_path, device=device
                    )
                ),
                optimizer=_TimedOut(),  # type: ignore[arg-type]
                environ=rt.build_isolated_environment(
                    cache_root=run_root / rt.AIMNET2_CACHE_RELATIVE, gpu_index=0
                ),
                monotonic=clock,
                profile=PHASE9B_CANDIDATE,
            )
    finally:
        monkey.undo()

    assert result.may_start_pyscf is False
    assert result.reason is not None
    assert "ran out of time" in result.reason, (
        "a budget overrun must be reported as a timeout, not merely as unconverged"
    )
    assert result.endpoints == ()


def test_pyscf_is_never_pointed_at_bytes_the_receipt_did_not_close_over() -> None:
    """The rebind step re-derives the digest instead of trusting the receipt.

    A genuinely closed handoff is built, then the result is given output bytes
    that do not hash to it -- exactly the shape of a post-receipt tamper.
    """

    import dataclasses

    from nhc_deprot_ranker.quantum import phase9b_handoff as hf

    elements, coords = _endpoint_geometry(acidic_proton=True)
    produced = rt.render_xyz(elements, coords, comment="produced")
    preopt = hf.build_preoptimization_receipt(
        route="assisted",
        attempt_id="attempt-phase9b-assisted-v001",
        endpoint="cation",
        charge=1,
        multiplicity=1,
        input_xyz=produced,
        output_xyz=produced,
        optimizer_steps=3,
        energy_evaluations=4,
        force_evaluations=4,
        calculator_invocations=4,
        initial_max_force_ev_per_angstrom=1.0,
        final_max_force_ev_per_angstrom=0.01,
        initial_energy_ev=-1.0,
        final_energy_ev=-2.0,
        wall_time_seconds=1.0,
        isolated_cache_bytes_written=0,
        trajectory_sha256="c" * 64,
        trajectory_frames=4,
        terminal_state="converged",
        validation=hf.StructuralValidation(
            total_rmsd_angstrom=0.0,
            max_single_atom_displacement_angstrom=0.0,
            c2_n1_bond_change_angstrom=0.0,
            c2_n3_bond_change_angstrom=0.0,
            ring_angle_change_degrees=0.0,
            atom_count_preserved=True,
            atom_order_preserved=True,
            connectivity_preserved=True,
            proton_host_index_preserved=True,
            all_gates_passed=True,
        ),
        state=hf.PreoptimizationState.CONVERGED,
    )
    handoff = hf.close_pyscf_handoff(
        preoptimization=preopt,
        aimnet2_output_xyz=produced,
        pyscf_input_xyz=produced,
        request_sha256="a" * 64,
        runner_source_sha256="b" * 64,
    )
    assert rt.pyscf_may_start(handoff), "the fixture handoff must itself be closed"

    @dataclasses.dataclass(frozen=True)
    class _E:
        xyz_path: Path
        xyz_sha256: str
        charge: int
        multiplicity: int

    @dataclasses.dataclass(frozen=True)
    class _R:
        cation: _E
        neutral: _E

    results = [
        rt.EndpointResult(
            endpoint=name,
            state=rt.EndpointState.PYSCF_ALLOWED,
            preoptimization=preopt,
            handoff=handoff,
            output_xyz_bytes=b"these bytes do not hash to the receipt digest",
            output_xyz_path=f"/tmp/{name}.xyz",
            failure_reason=None,
        )
        for name in ("cation", "neutral")
    ]
    request = _R(_E(Path("/tmp/c.xyz"), "a" * 64, 1, 1), _E(Path("/tmp/n.xyz"), "b" * 64, 0, 1))
    with pytest.raises(rt.Aimnet2RuntimeError, match="differ from the receipt"):
        rt._rebind_request_to_handoff(request, results)  # type: ignore[arg-type]
