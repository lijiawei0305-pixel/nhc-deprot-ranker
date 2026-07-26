"""A strict fake torch/ase/aimnet tree, so the production path really runs.

The point of this module is that ``_construct_base_model_after_authorization``
and ``AseLBFGSOptimizer.optimize`` execute their *real* code against it.  Nothing
here is monkeypatched over the runtime; the runtime's own lazy imports resolve to
these modules, and every constructor argument the production adapter passes is
checked for exactly.

The fakes are deliberately unforgiving.  An unknown keyword, a relative path, a
registry alias, or a Hugging Face-looking identifier is an error rather than a
shrug, because the whole value of running the real constructor is that a wrong
argument shows up here instead of on a GPU.

``LBFGS`` reproduces the control flow Phase 9A-S4 read out of ASE 3.29.0: the
observer fires once at step zero when ``trajectory is None``, then after every
completed step, and the gradient is read again for the convergence test.  The
calculator caches by geometry the way ASE does, so reading energy and forces for
one geometry is one model execution, not two.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Callable, Sequence
from typing import Any

WEIGHT_FILENAME = "aimnet2_wb97m_d3_0.pt"
_HF_LIKE = "/"


class FakeError(RuntimeError):
    """The fake stack was used in a way the production adapter must never use."""


# --- ledger shared with the tests -------------------------------------------
class StackLedger:
    """What the fake stack observed, so tests assert on facts not on mocks."""

    def __init__(self) -> None:
        self.base_calculator_constructions: list[dict[str, Any]] = []
        self.endpoint_constructions: list[dict[str, Any]] = []
        self.atoms_constructions: list[dict[str, Any]] = []
        self.lbfgs_constructions: list[dict[str, Any]] = []
        self.calculate_calls: list[tuple[str, tuple[str, ...]]] = []
        self.eval_calls = 0
        self.load_model_calls = 0
        self.compile_calls = 0

    @property
    def model_load_count(self) -> int:
        return len(self.base_calculator_constructions)


LEDGER = StackLedger()


# --- torch -------------------------------------------------------------------
def _build_torch() -> types.ModuleType:
    torch = types.ModuleType("torch")

    class _Module:
        def __init__(self) -> None:
            self.training = True
            self._grad = True

        def train(self, mode: bool = True) -> _Module:
            self.training = bool(mode)
            return self

        def eval(self) -> _Module:
            LEDGER.eval_calls += 1
            return self.train(False)

        def parameters(self) -> list[Any]:
            return []

        def to(self, device: str) -> _Module:
            self.device = device
            return self

    nn = types.ModuleType("torch.nn")
    nn.Module = _Module  # type: ignore[attr-defined]
    torch.nn = nn  # type: ignore[attr-defined]

    def _compile(model: Any, **kwargs: Any) -> Any:
        LEDGER.compile_calls += 1
        return model

    torch.compile = _compile  # type: ignore[attr-defined]

    def _load(*args: Any, **kwargs: Any) -> Any:
        raise FakeError("torch.load must not be called by the Phase 9B adapter")

    torch.load = _load  # type: ignore[attr-defined]
    jit = types.ModuleType("torch.jit")
    jit.load = _load  # type: ignore[attr-defined]
    torch.jit = jit  # type: ignore[attr-defined]
    return torch


# --- ase ---------------------------------------------------------------------
all_changes = ("positions", "numbers", "cell", "pbc", "initial_charges", "initial_magmoms")


class FakeAseCalculator:
    """The parts of ``ase.calculators.calculator.Calculator`` that are used.

    ``get_property`` caches on geometry exactly as ASE does, so one geometry
    costs one ``calculate`` call however many properties are read from it.
    """

    implemented_properties: tuple[str, ...] = ("energy", "forces")

    def __init__(self) -> None:
        self.results: dict[str, Any] = {}
        self._cached_key: tuple[tuple[float, ...], ...] | None = None

    def calculate(
        self,
        atoms: Any = None,
        properties: Sequence[str] | None = None,
        system_changes: Sequence[str] = all_changes,
    ) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def reset(self) -> None:
        self.results = {}
        self._cached_key = None

    always_recalculate = False

    def get_property(self, name: str, atoms: Any, properties: Sequence[str]) -> Any:
        key = tuple(tuple(row) for row in atoms.get_positions())
        if self.always_recalculate or key != self._cached_key or name not in self.results:
            self.calculate(atoms, list(properties), all_changes)
            self._cached_key = key
        return self.results[name]


class PropertyNotImplementedError(RuntimeError):
    pass


class FakeAtoms:
    """Minimal ``ase.Atoms``: symbols, positions, and a bound calculator."""

    def __init__(self, symbols: Sequence[str] | None = None, positions: Any = None) -> None:
        if symbols is None or positions is None:
            raise FakeError("the adapter must build Atoms with explicit symbols and positions")
        self._symbols = list(symbols)
        self._positions = [[float(v) for v in row] for row in positions]
        if len(self._symbols) != len(self._positions):
            raise FakeError("symbols and positions disagree")
        self.calc: Any = None
        LEDGER.atoms_constructions.append(
            {"symbols": tuple(self._symbols), "positions": tuple(map(tuple, self._positions))}
        )

    def __len__(self) -> int:
        return len(self._symbols)

    def get_chemical_symbols(self) -> list[str]:
        return list(self._symbols)

    def get_positions(self) -> list[list[float]]:
        return [list(row) for row in self._positions]

    def set_positions(self, positions: Any) -> None:
        rows = [[float(v) for v in row] for row in positions]
        if len(rows) != len(self._symbols):
            raise FakeError("a position update changed the atom count")
        self._positions = rows

    def get_potential_energy(self) -> float:
        if self.calc is None:
            raise FakeError("Atoms has no calculator bound")
        return float(self.calc.get_property("energy", self, ("energy", "forces")))

    def get_forces(self) -> list[list[float]]:
        if self.calc is None:
            raise FakeError("Atoms has no calculator bound")
        return [list(row) for row in self.calc.get_property("forces", self, ("energy", "forces"))]


class FakeLBFGS:
    """ASE 3.29.0's observed control flow, reproduced for the production path."""

    def __init__(
        self,
        atoms: Any,
        restart: Any = None,
        logfile: Any = "-",
        trajectory: Any = None,
        maxstep: float | None = None,
        memory: int = 100,
        damping: float = 1.0,
        alpha: float = 70.0,
        use_line_search: bool = False,
        **kwargs: Any,
    ) -> None:
        if kwargs:
            raise FakeError(f"unexpected LBFGS arguments: {sorted(kwargs)}")
        LEDGER.lbfgs_constructions.append(
            {
                "restart": restart,
                "logfile": logfile,
                "trajectory": trajectory,
                "maxstep": maxstep,
                "memory": memory,
                "damping": damping,
                "alpha": alpha,
                "use_line_search": use_line_search,
            }
        )
        self.atoms = atoms
        self.restart = restart
        self.trajectory = trajectory
        self.nsteps = 0
        self.observers: list[tuple[Callable[..., Any], int, tuple[Any, ...], dict[str, Any]]] = []
        self.fmax = 0.05

    def attach(self, function: Any, interval: int = 1, *args: Any, **kwargs: Any) -> None:
        if not callable(function):
            function = function.write
        self.observers.append((function, interval, args, kwargs))

    def call_observers(self) -> None:
        for function, interval, args, kwargs in self.observers:
            call = False
            if interval > 0:
                call = (self.nsteps % interval) == 0
            elif self.nsteps == abs(interval):
                call = True
            if call:
                function(*args, **kwargs)

    def get_number_of_steps(self) -> int:
        return self.nsteps

    def _max_force(self) -> float:
        return max(
            (sum(c * c for c in row) ** 0.5 for row in self.atoms.get_forces()),
            default=0.0,
        )

    def step(self) -> None:
        # Steepest descent is enough: the production code under test is the
        # adapter, the deadline and the evidence, not the minimizer's algebra.
        forces = self.atoms.get_forces()
        positions = self.atoms.get_positions()
        moved = [
            [p + 0.5 * f for p, f in zip(row, force, strict=True)]
            for row, force in zip(positions, forces, strict=True)
        ]
        self.atoms.set_positions(moved)

    def run(self, fmax: float = 0.05, steps: int = 100_000_000) -> bool:
        self.fmax = fmax
        max_steps = self.nsteps + steps
        self.atoms.get_forces()
        if self.nsteps == 0 and self.trajectory is None:
            self.call_observers()
        converged = self._max_force() < fmax
        while not converged and self.nsteps < max_steps:
            self.step()
            self.nsteps += 1
            self.atoms.get_forces()
            self.call_observers()
            converged = self._max_force() < fmax
        return converged


def _build_ase() -> dict[str, types.ModuleType]:
    ase = types.ModuleType("ase")
    ase.Atoms = FakeAtoms  # type: ignore[attr-defined]
    ase.__path__ = []  # type: ignore[attr-defined]

    calculators = types.ModuleType("ase.calculators")
    calculators.__path__ = []  # type: ignore[attr-defined]
    calculator = types.ModuleType("ase.calculators.calculator")
    calculator.Calculator = FakeAseCalculator  # type: ignore[attr-defined]
    calculator.PropertyNotImplementedError = PropertyNotImplementedError  # type: ignore[attr-defined]
    calculator.all_changes = all_changes  # type: ignore[attr-defined]

    optimize = types.ModuleType("ase.optimize")
    optimize.LBFGS = FakeLBFGS  # type: ignore[attr-defined]
    optimize.__path__ = []  # type: ignore[attr-defined]
    lbfgs_module = types.ModuleType("ase.optimize.lbfgs")
    lbfgs_module.LBFGS = FakeLBFGS  # type: ignore[attr-defined]

    return {
        "ase": ase,
        "ase.calculators": calculators,
        "ase.calculators.calculator": calculator,
        "ase.optimize": optimize,
        "ase.optimize.lbfgs": lbfgs_module,
    }


# --- aimnet ------------------------------------------------------------------
class FakeAimnet2Calculator:
    """Strict stand-in for ``aimnet.calculators.AIMNet2Calculator``.

    Accepts only the three arguments the production adapter is allowed to pass,
    and refuses every input the loader contract forbids.
    """

    def __init__(
        self,
        model: Any = "aimnet2",
        device: str | None = None,
        compile_model: bool = False,
        **kwargs: Any,
    ) -> None:
        if kwargs:
            raise FakeError(f"the adapter passed unexpected arguments: {sorted(kwargs)}")
        if not isinstance(model, str):
            raise FakeError("scheme B detected: a pre-loaded module was passed instead of a path")
        if model == "aimnet2" or not model.endswith(".pt"):
            raise FakeError(f"a registry alias or non-weight identifier was used: {model!r}")
        if not model.startswith("/"):
            raise FakeError(f"a relative path was used: {model!r}")
        if model.count(_HF_LIKE) == 1:
            raise FakeError(f"a Hugging Face-shaped identifier was used: {model!r}")
        if not model.rsplit("/", 1)[-1] == WEIGHT_FILENAME:
            raise FakeError(f"an unexpected weight file was used: {model!r}")
        if device is None or not device.startswith("cuda:"):
            raise FakeError(f"the device was not an exact cuda index: {device!r}")
        if compile_model is not False:
            raise FakeError("compile_model must be False")
        self.model_path = model
        self.device = device
        self.compile_model = compile_model
        self.cutoff = 5.5
        LEDGER.base_calculator_constructions.append(
            {"model": model, "device": device, "compile_model": compile_model}
        )


def _build_aimnet(*, extra_convergence_evaluation: bool = False) -> dict[str, types.ModuleType]:
    class FakeAimnet2ASE(FakeAseCalculator):
        implemented_properties = ("energy", "forces")
        # Models an ASE that re-reads the gradient for its convergence test
        # instead of serving it from cache, so the counters -- not an assumption
        # about one evaluation per step -- are what the receipt reports.
        always_recalculate = extra_convergence_evaluation

        def __init__(
            self,
            base_calc: Any = "aimnet2",
            charge: int = 0,
            mult: int = 1,
            validate_species: bool = True,
            **kwargs: Any,
        ) -> None:
            if kwargs:
                raise FakeError(f"the adapter passed unexpected arguments: {sorted(kwargs)}")
            if isinstance(base_calc, str):
                raise FakeError("the adapter must pass a constructed calculator, not a string")
            if not isinstance(base_calc, FakeAimnet2Calculator):
                raise FakeError("the adapter must pass an AIMNet2Calculator")
            if validate_species is not True:
                raise FakeError("validate_species must be True")
            super().__init__()
            self.base_calc = base_calc
            self.charge = charge
            self.mult = mult
            self.validate_species = validate_species
            self._target: list[list[float]] | None = None
            LEDGER.endpoint_constructions.append(
                {
                    "charge": charge,
                    "mult": mult,
                    "validate_species": validate_species,
                    "base_id": id(base_calc),
                }
            )

        def calculate(
            self,
            atoms: Any = None,
            properties: Sequence[str] | None = None,
            system_changes: Sequence[str] = all_changes,
        ) -> None:
            LEDGER.calculate_calls.append(
                ("cation" if self.charge == 1 else "neutral", tuple(properties or ("energy",)))
            )
            positions = atoms.get_positions()
            # A harmonic well whose centre is pinned on the first evaluation.  A
            # centre defined relative to the *current* geometry would never be
            # reached, and the optimizer would march away forever.
            if self._target is None:
                self._target = [[row[0] - 0.4, row[1], row[2]] for row in positions]
            energy = 0.0
            forces: list[list[float]] = []
            for row, target in zip(positions, self._target, strict=True):
                delta = [row[k] - target[k] for k in range(3)]
                energy += 0.5 * sum(d * d for d in delta)
                forces.append([-d for d in delta])
            self.results = {"energy": -4321.0 + energy, "forces": forces}

    aimnet = types.ModuleType("aimnet")
    aimnet.__path__ = []  # type: ignore[attr-defined]
    calculators = types.ModuleType("aimnet.calculators")
    calculators.AIMNet2Calculator = FakeAimnet2Calculator  # type: ignore[attr-defined]
    calculators.AIMNet2ASE = FakeAimnet2ASE  # type: ignore[attr-defined]
    calculators.__path__ = []  # type: ignore[attr-defined]

    models = types.ModuleType("aimnet.models")
    models.__path__ = []  # type: ignore[attr-defined]
    base = types.ModuleType("aimnet.models.base")

    def _load_model(*args: Any, **kwargs: Any) -> Any:
        LEDGER.load_model_calls += 1
        raise FakeError("scheme B: the adapter must not call load_model itself")

    base.load_model = _load_model  # type: ignore[attr-defined]

    return {
        "aimnet": aimnet,
        "aimnet.calculators": calculators,
        "aimnet.models": models,
        "aimnet.models.base": base,
    }


# --- installation ------------------------------------------------------------
class installed:
    """Install the fake stack for the duration of a block, then remove it fully."""

    def __init__(self, *, extra_convergence_evaluation: bool = False) -> None:
        self._extra = extra_convergence_evaluation
        self._saved: dict[str, types.ModuleType | None] = {}

    def __enter__(self) -> StackLedger:
        global LEDGER
        LEDGER = StackLedger()
        modules: dict[str, types.ModuleType] = {"torch": _build_torch()}
        modules.update(_build_ase())
        modules.update(_build_aimnet(extra_convergence_evaluation=self._extra))
        for name, module in modules.items():
            self._saved[name] = sys.modules.get(name)
            sys.modules[name] = module
        return LEDGER

    def __exit__(self, *exc: object) -> None:
        for name, previous in self._saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        self._saved.clear()
