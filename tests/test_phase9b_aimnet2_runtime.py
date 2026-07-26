"""Phase 9B AIMNet2 production runtime regressions.

No torch, no ASE, no aimnet, no CUDA, no weight file, no PySCF. The model loader
and the optimizer are injected, so nothing here loads a model or touches a GPU.
What is under test is the runtime's own logic: offline enforcement, cache
isolation, the single load, the endpoint state machine, the structural gates,
durable evidence, and the byte-closed handoff into PySCF.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from nhc_deprot_ranker.quantum import phase9b_aimnet2_runtime as rt
from nhc_deprot_ranker.quantum.phase9b_aimnet2_runtime import (
    TRAJECTORY_SCHEMA_VERSION,
    Aimnet2NotAuthorizedError,
    Aimnet2RuntimeError,
    OptimizerOutcome,
    TerminalState,
    TrajectoryFrame,
    build_isolated_environment,
    infer_connectivity,
    parse_xyz,
    render_xyz,
    run_assisted_stage,
    serialize_trajectory,
    validate_structure,
    verify_offline_environment,
    verify_weight,
    write_exclusively,
)
from nhc_deprot_ranker.quantum.phase9b_authority import PHASE9B_CANDIDATE
from nhc_deprot_ranker.quantum.phase9b_handoff import (
    AIMNET2_WEIGHT_BYTES,
    AIMNET2_WEIGHT_FILENAME,
    AIMNET2_WEIGHT_SHA256,
    pyscf_may_start,
)
from nhc_deprot_ranker.quantum.phase9b_permit import ROUTE_ASSISTED, ROUTE_ATTEMPT_IDS

_ATTEMPT = ROUTE_ATTEMPT_IDS[ROUTE_ASSISTED]

# C9 F9 H<n> N3 with N1 at 8, C2 at 14, N3 at 15 -- the candidate's real atom map,
# never Phase 8B's 3/4/5.
_ORDER_HEAD = ["C"] * 8 + ["N"] + ["F"] * 5 + ["C"] + ["N", "N"] + ["F"] * 4


def _elements(hydrogens: int) -> list[str]:
    return [*_ORDER_HEAD, *["H"] * hydrogens]


def _coordinates(elements: Sequence[str], *, acidic_proton: bool) -> list[list[float]]:
    """A layout that bonds N1-C2-N3, and puts the acidic proton on N1 only for
    the cation.

    Every other atom is spread far enough apart to have no bonds, so the gates
    under test see exactly the connectivity the fixture intends.
    """

    points: list[list[float]] = [[index * 6.0, 0.0, 0.0] for index in range(len(elements))]
    atom_map = PHASE9B_CANDIDATE.atom_map
    c2, n1, n3 = atom_map["C2_carbene"], atom_map["N1"], atom_map["N3"]
    points[c2] = [0.0, 0.0, 0.0]
    points[n1] = [1.35, 0.0, 0.0]
    points[n3] = [-1.35, 0.0, 0.0]
    if acidic_proton:
        # The cation's ring proton, on N1.  The neutral simply does not have it.
        points[len(_ORDER_HEAD)] = [2.35, 0.0, 0.0]
    return points


def _xyz(hydrogens: int, *, acidic_proton: bool) -> bytes:
    elements = _elements(hydrogens)
    return render_xyz(
        elements, _coordinates(elements, acidic_proton=acidic_proton), comment="endpoint"
    )


_CATION_XYZ = _xyz(5, acidic_proton=True)
_NEUTRAL_XYZ = _xyz(4, acidic_proton=False)


class _FakeCalculator:
    def __init__(self, charge: int, multiplicity: int) -> None:
        self.charge = charge
        self.multiplicity = multiplicity

    def energy_and_forces(
        self, coordinates: Sequence[Sequence[float]]
    ) -> tuple[float, Sequence[Sequence[float]]]:
        return -1.0, [[0.0, 0.0, 0.0] for _ in coordinates]


class _FakeModel:
    """One model.  Counts how often a calculator is made, and from how many loads."""

    def __init__(self) -> None:
        self.calculators: list[tuple[int, int]] = []

    def calculator_for(self, *, charge: int, multiplicity: int) -> _FakeCalculator:
        self.calculators.append((charge, multiplicity))
        return _FakeCalculator(charge, multiplicity)


class _CountingLoader:
    def __init__(self) -> None:
        self.loads = 0
        self.model = _FakeModel()

    def __call__(self, *, weight_path: Path, device: str) -> _FakeModel:
        del weight_path, device
        self.loads += 1
        return self.model


class _FakeOptimizer:
    """Nudges coordinates by a fixed amount; never calls a real model."""

    def __init__(self, **overrides: Any) -> None:
        self.overrides = overrides
        self.calls: list[tuple[int, int]] = []

    def optimize(
        self,
        *,
        calculator: Any,
        coordinates: Sequence[Sequence[float]],
        elements: Sequence[str],
        fmax: float,
        max_steps: int,
        deadline_monotonic: float,
    ) -> OptimizerOutcome:
        del fmax, max_steps, deadline_monotonic
        self.calls.append((calculator.charge, calculator.multiplicity))
        start = tuple(tuple(float(v) for v in point) for point in coordinates)
        moved = tuple((x + 0.01, y, z) for x, y, z in start)
        # A real trajectory, so every downstream evidence gate is exercised by
        # the mock exactly as it would be by the production optimizer.
        frames = tuple(
            _frame(
                calculator=calculator,
                elements=elements,
                index=index,
                coordinates=points,
                energy=-4321.0 - index * 0.25,
                max_force=1.7 if index == 0 else 0.02,
                is_initial=index == 0,
                is_terminal=index == 1,
            )
            for index, points in enumerate((start, moved))
        )
        base: dict[str, Any] = {
            "coordinates": moved,
            "converged": True,
            "steps": 37,
            "energy_evaluations": 40,
            "force_evaluations": 40,
            "calculator_invocations": 40,
            "initial_max_force": 1.7,
            "final_max_force": 0.02,
            "trajectory_frames": len(frames),
            "initial_energy_ev": frames[0].energy_ev,
            "final_energy_ev": frames[-1].energy_ev,
            "trajectory": frames,
            "elapsed_seconds": 12.5,
            "terminal_state": TerminalState.CONVERGED,
        }
        base.update(self.overrides)
        if "trajectory_sha256" not in self.overrides:
            base["trajectory_sha256"] = hashlib.sha256(
                serialize_trajectory(base["trajectory"])
            ).hexdigest()
        if "trajectory_frames" not in self.overrides:
            base["trajectory_frames"] = len(base["trajectory"])
        return OptimizerOutcome(**base)


def _frame(
    *,
    calculator: Any,
    elements: Sequence[str],
    index: int,
    coordinates: tuple[tuple[float, float, float], ...],
    energy: float,
    max_force: float,
    is_initial: bool,
    is_terminal: bool,
) -> TrajectoryFrame:
    return TrajectoryFrame(
        schema_version=TRAJECTORY_SCHEMA_VERSION,
        endpoint="cation" if calculator.charge == 1 else "neutral",
        frame_index=index,
        elapsed_seconds=float(index),
        charge=calculator.charge,
        multiplicity=calculator.multiplicity,
        atom_count=len(elements),
        element_order_sha256=hashlib.sha256(" ".join(elements).encode()).hexdigest(),
        coordinates=coordinates,
        energy_ev=energy,
        max_force_ev_per_angstrom=max_force,
        calculator_invocation_index=index + 1,
        optimizer_step=index,
        is_initial=is_initial,
        is_terminal=is_terminal,
    )


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
    request_sha256: str = "1" * 64
    runner_source_sha256: str = "2" * 64


def _weight(tmp_path: Path) -> Path:
    """A file with the real name, size, and digest, without the real model."""

    path = tmp_path / AIMNET2_WEIGHT_FILENAME
    path.write_bytes(b"")
    return path


def _request(tmp_path: Path) -> _Request:
    inputs = tmp_path / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    cation = inputs / "cation.xyz"
    neutral = inputs / "neutral.xyz"
    cation.write_bytes(_CATION_XYZ)
    neutral.write_bytes(_NEUTRAL_XYZ)
    return _Request(
        cation=_Endpoint(cation, hashlib.sha256(_CATION_XYZ).hexdigest(), 1, 1),
        neutral=_Endpoint(neutral, hashlib.sha256(_NEUTRAL_XYZ).hexdigest(), 0, 1),
    )


def _stage(
    tmp_path: Path,
    *,
    loader: _CountingLoader | None = None,
    optimizer: Any = None,
    request: _Request | None = None,
    weight_path: Path | None = None,
    absolute_deadline_monotonic: float = 1e18,
    **kw: Any,
) -> rt.AssistedStageResult:
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    cache_root = run_root / "runtime/cache"
    environment = build_isolated_environment(cache_root=cache_root, gpu_index=2)
    used_loader = loader or _CountingLoader()
    return run_assisted_stage(
        request=request or _request(tmp_path),  # type: ignore[arg-type]
        run_root=run_root,
        attempt_id=_ATTEMPT,
        gpu_index=2,
        absolute_deadline_monotonic=absolute_deadline_monotonic,
        model_loader=used_loader,
        optimizer=optimizer if optimizer is not None else _FakeOptimizer(),
        weight_path=weight_path if weight_path is not None else _patched_weight(tmp_path),
        environ=environment,
        **kw,
    )


def _patched_weight(tmp_path: Path) -> Path:
    path = tmp_path / AIMNET2_WEIGHT_FILENAME
    if not path.exists():
        path.write_bytes(b"\0" * AIMNET2_WEIGHT_BYTES)
    return path


@pytest.fixture(autouse=True)
def _accept_the_synthetic_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Accept a same-size synthetic file instead of shipping an 8.4 MB blob.

    The name, byte size, symlink, and regular-file checks all run for real; only
    the digest constant is pointed at the synthetic file's digest, so the weight
    verification path is exercised without committing a model to the repository.
    """

    synthetic = hashlib.sha256(b"\0" * AIMNET2_WEIGHT_BYTES).hexdigest()
    monkeypatch.setattr(rt, "AIMNET2_WEIGHT_SHA256", synthetic)


# --- gate and closure --------------------------------------------------------


def test_the_source_gate_is_closed_and_a_real_load_refuses(tmp_path: Path) -> None:
    assert rt.EXECUTION_AUTHORIZED is False
    source = Path(rt.__file__).read_text(encoding="utf-8")
    assert "EXECUTION_AUTHORIZED: Final[bool] = False" in source
    with pytest.raises(Aimnet2NotAuthorizedError, match="source execution gate is closed"):
        rt._load_base_model(  # pyright: ignore[reportPrivateUsage]
            weight_path=_patched_weight(tmp_path), device="cuda:0"
        )


def test_no_chemistry_is_imported_at_module_scope() -> None:
    """The guardian and supervisor import this module's package; they need no ML."""

    tree = ast.parse(Path(rt.__file__).read_text(encoding="utf-8"))
    top: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top.add(node.module.split(".")[0])
    assert not (top & {"torch", "ase", "aimnet", "pyscf", "numpy"})


# --- offline and cache isolation ---------------------------------------------


def test_the_isolated_environment_redirects_every_cache_root(tmp_path: Path) -> None:
    cache_root = tmp_path / "runtime/cache"
    env = build_isolated_environment(cache_root=cache_root, gpu_index=3)
    for name, expected in rt.OFFLINE_ENVIRONMENT.items():
        assert env[name] == expected
    for name in rt.CACHE_ENVIRONMENT_VARIABLES:
        assert env[name].startswith(cache_root.as_posix())
    assert env["CUDA_VISIBLE_DEVICES"] == "3"
    verify_offline_environment(env, cache_root=cache_root)


@pytest.mark.parametrize("missing", sorted(rt.OFFLINE_ENVIRONMENT))
def test_a_missing_offline_variable_refuses(tmp_path: Path, missing: str) -> None:
    cache_root = tmp_path / "runtime/cache"
    env = dict(build_isolated_environment(cache_root=cache_root, gpu_index=0))
    del env[missing]
    with pytest.raises(Aimnet2RuntimeError, match="offline environment is not set"):
        verify_offline_environment(env, cache_root=cache_root)


@pytest.mark.parametrize("leaked", sorted(rt.CACHE_ENVIRONMENT_VARIABLES))
def test_a_cache_root_outside_the_attempt_refuses(tmp_path: Path, leaked: str) -> None:
    cache_root = tmp_path / "runtime/cache"
    env = dict(build_isolated_environment(cache_root=cache_root, gpu_index=0))
    env[leaked] = "/home/someone/.cache"
    with pytest.raises(Aimnet2RuntimeError, match="not redirected into the attempt"):
        verify_offline_environment(env, cache_root=cache_root)


@pytest.mark.parametrize("forbidden", ["HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "AIMNET2_MODEL"])
def test_a_token_or_registry_alias_refuses(tmp_path: Path, forbidden: str) -> None:
    cache_root = tmp_path / "runtime/cache"
    env = dict(build_isolated_environment(cache_root=cache_root, gpu_index=0))
    env[forbidden] = "value"
    with pytest.raises(Aimnet2RuntimeError, match="forbidden model variable"):
        verify_offline_environment(env, cache_root=cache_root)


# --- the weight --------------------------------------------------------------


def test_the_weight_is_verified_by_name_size_and_digest(tmp_path: Path) -> None:
    observation = verify_weight(_patched_weight(tmp_path))
    assert observation.bytes_before == AIMNET2_WEIGHT_BYTES
    assert observation.sha256_before == observation.sha256_after


def test_a_missing_weight_refuses(tmp_path: Path) -> None:
    with pytest.raises(Aimnet2RuntimeError, match="weight file is missing"):
        verify_weight(tmp_path / AIMNET2_WEIGHT_FILENAME)


def test_a_renamed_weight_refuses(tmp_path: Path) -> None:
    other = tmp_path / "aimnet2.pt"
    other.write_bytes(b"\0" * AIMNET2_WEIGHT_BYTES)
    with pytest.raises(Aimnet2RuntimeError, match="weight file name"):
        verify_weight(other)


def test_a_symlinked_weight_refuses(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    real = _patched_weight(tmp_path / "real")
    link = tmp_path / AIMNET2_WEIGHT_FILENAME
    link.symlink_to(real)
    with pytest.raises(Aimnet2RuntimeError, match="symlink"):
        verify_weight(link)


def test_a_wrong_sized_weight_refuses(tmp_path: Path) -> None:
    path = tmp_path / AIMNET2_WEIGHT_FILENAME
    path.write_bytes(b"\0" * (AIMNET2_WEIGHT_BYTES - 1))
    with pytest.raises(Aimnet2RuntimeError, match="byte size drifted"):
        verify_weight(path)


def test_a_wrong_digest_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rt, "AIMNET2_WEIGHT_SHA256", AIMNET2_WEIGHT_SHA256)
    with pytest.raises(Aimnet2RuntimeError, match="SHA256 drifted"):
        verify_weight(_patched_weight(tmp_path))


def test_a_relative_weight_path_refuses() -> None:
    with pytest.raises(Aimnet2RuntimeError, match="must be absolute"):
        verify_weight(Path(AIMNET2_WEIGHT_FILENAME))


# --- geometry ----------------------------------------------------------------


def test_xyz_round_trips_and_refuses_malformed_input() -> None:
    elements, points = parse_xyz(_CATION_XYZ)
    assert len(elements) == 26
    assert elements[8] == "N" and elements[14] == "C" and elements[15] == "N"
    assert render_xyz(elements, points, comment="endpoint") == _CATION_XYZ
    for bad in (b"", b"1\n", b"x\ncomment\nC 0 0 0\n", b"5\nc\nC 0 0 0\n", b"1\nc\nC a b c\n"):
        with pytest.raises(Aimnet2RuntimeError):
            parse_xyz(bad)


def test_connectivity_is_index_preserving_not_graph_isomorphic() -> None:
    """Swapping two same-element atoms must be visible."""

    elements, points = parse_xyz(_CATION_XYZ)
    swapped = list(points)
    swapped[8], swapped[15] = swapped[15], swapped[8]
    assert infer_connectivity(elements, points) != infer_connectivity(elements, swapped)


def test_an_unsupported_element_refuses() -> None:
    with pytest.raises(Aimnet2RuntimeError, match="unsupported element"):
        infer_connectivity(["C", "Pt"], [[0.0, 0.0, 0.0], [1.5, 0.0, 0.0]])


# --- structural gates --------------------------------------------------------


def _validate(after_shift: float = 0.01, **kw: Any) -> Any:
    elements, before = parse_xyz(_CATION_XYZ)
    after = [[x + after_shift, y, z] for x, y, z in before]
    params: dict[str, Any] = {
        "endpoint": "cation",
        "elements_before": elements,
        "before": before,
        "elements_after": elements,
        "after": after,
    }
    params.update(kw)
    return validate_structure(**params)


def test_a_small_relaxation_passes_every_gate() -> None:
    validation = _validate()
    assert validation.all_gates_passed
    assert validation.atom_order_preserved
    assert validation.connectivity_preserved
    assert validation.proton_host_index_preserved


def test_the_gates_use_the_candidates_own_atom_map() -> None:
    """14/8/15, never Phase 8B's 3/4/5."""

    assert PHASE9B_CANDIDATE.atom_map == {"C2_carbene": 14, "N1": 8, "N3": 15}
    elements, _ = parse_xyz(_CATION_XYZ)
    assert elements[14] == "C"
    assert elements[8] == "N"
    assert elements[15] == "N"


def test_a_changed_atom_count_refuses() -> None:
    elements, before = parse_xyz(_CATION_XYZ)
    with pytest.raises(Aimnet2RuntimeError, match="atom count changed"):
        _validate(elements_after=list(elements)[:-1], after=list(before)[:-1])


def test_a_changed_element_sequence_refuses() -> None:
    elements, _ = parse_xyz(_CATION_XYZ)
    swapped = list(elements)
    swapped[8], swapped[9] = swapped[9], swapped[8]
    with pytest.raises(Aimnet2RuntimeError, match="element sequence changed"):
        _validate(elements_after=swapped)


def test_a_large_displacement_fails_the_gate() -> None:
    assert not _validate(after_shift=3.0).all_gates_passed


def test_the_cation_must_keep_its_ring_proton() -> None:
    elements, before = parse_xyz(_CATION_XYZ)
    moved = [list(point) for point in before]
    moved[len(_ORDER_HEAD)] = [99.0, 99.0, 99.0]
    with pytest.raises(Aimnet2RuntimeError, match="lost its acidic proton"):
        validate_structure(
            endpoint="cation",
            elements_before=elements,
            before=before,
            elements_after=elements,
            after=moved,
        )


def test_the_neutral_may_not_gain_a_ring_proton() -> None:
    """A proton that migrates onto N1 turns the neutral back into the cation."""

    elements, before = parse_xyz(_NEUTRAL_XYZ)
    clean = validate_structure(
        endpoint="neutral",
        elements_before=elements,
        before=before,
        elements_after=elements,
        after=[list(point) for point in before],
    )
    assert clean.all_gates_passed

    migrated = [list(point) for point in before]
    migrated[len(_ORDER_HEAD)] = [2.35, 0.0, 0.0]
    with pytest.raises(Aimnet2RuntimeError, match="gained a ring proton"):
        validate_structure(
            endpoint="neutral",
            elements_before=elements,
            before=before,
            elements_after=elements,
            after=migrated,
        )


# --- durable evidence --------------------------------------------------------


def test_evidence_is_written_once_and_re_read(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    digest = write_exclusively(path, b"{}\n")
    assert digest == hashlib.sha256(b"{}\n").hexdigest()
    assert path.read_bytes() == b"{}\n"
    assert not list(tmp_path.glob(".*partial"))
    with pytest.raises(Aimnet2RuntimeError, match="already exists"):
        write_exclusively(path, b'{"other": 1}\n')
    assert path.read_bytes() == b"{}\n"


def test_evidence_refuses_a_symlinked_target(tmp_path: Path) -> None:
    target = tmp_path / "real.json"
    target.write_bytes(b"{}\n")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(Aimnet2RuntimeError, match="already exists"):
        write_exclusively(link, b"{}\n")


# --- the stage ---------------------------------------------------------------


def test_a_clean_stage_closes_both_handoffs_and_opens_pyscf(tmp_path: Path) -> None:
    loader = _CountingLoader()
    optimizer = _FakeOptimizer()
    result = _stage(tmp_path, loader=loader, optimizer=optimizer)

    assert result.may_start_pyscf
    assert result.reason is None
    assert [item.endpoint for item in result.endpoints] == ["cation", "neutral"]
    for item in result.endpoints:
        assert pyscf_may_start(item.handoff)
        assert item.preoptimization.state.value == "converged"

    # The model is loaded once for the whole route.
    assert loader.loads == result.model_load_count == 1
    # Each endpoint gets its own calculator with its own charge.
    assert optimizer.calls == [(1, 1), (0, 1)]

    run_root = tmp_path / "run"
    for endpoint in ("cation", "neutral"):
        assert (run_root / f"runtime/aimnet2/{endpoint}/input.xyz").is_file()
        assert (run_root / f"runtime/aimnet2/{endpoint}/output.xyz").is_file()
        assert (run_root / f"runtime/aimnet2/{endpoint}/trajectory.jsonl").is_file()
        assert (run_root / f"runtime/logs/{endpoint}.aimnet2.log").is_file()
        preopt = run_root / f"runtime/evidence/{endpoint}.aimnet2_preoptimization.json"
        handoff = run_root / f"runtime/evidence/{endpoint}.pyscf_handoff.json"
        assert json.loads(preopt.read_bytes())["state"] == "converged"
        assert json.loads(handoff.read_bytes())["state"] == "closed"
        assert preopt.stat().st_mode & 0o777 == 0o400


def test_pyscf_reads_exactly_the_bytes_the_handoff_closed_over(tmp_path: Path) -> None:
    """The strongest property in the route, checked end to end."""

    result = _stage(tmp_path)
    assert result.may_start_pyscf
    for endpoint in ("cation", "neutral"):
        item = next(one for one in result.endpoints if one.endpoint == endpoint)
        rebound = getattr(result.pyscf_request, endpoint)
        on_disk = Path(item.output_xyz_path).read_bytes()
        # The request PySCF will read points at the same file, and the digest the
        # handoff receipt closed over is that file's digest.
        assert rebound.xyz_path == Path(item.output_xyz_path)
        assert rebound.xyz_sha256 == hashlib.sha256(on_disk).hexdigest()
        assert rebound.xyz_sha256 == item.handoff.pyscf_input_xyz_sha256
        assert item.handoff.aimnet2_output_xyz_sha256 == rebound.xyz_sha256


def test_an_unconverged_endpoint_stops_the_route(tmp_path: Path) -> None:
    result = _stage(tmp_path, optimizer=_FakeOptimizer(converged=False))
    assert not result.may_start_pyscf
    assert "did not converge" in (result.reason or "")
    assert result.endpoints == ()


def test_a_force_above_the_frozen_threshold_stops_the_route(tmp_path: Path) -> None:
    result = _stage(tmp_path, optimizer=_FakeOptimizer(final_max_force=0.9))
    assert not result.may_start_pyscf
    assert "force threshold" in (result.reason or "")


def test_exceeding_the_step_limit_stops_the_route(tmp_path: Path) -> None:
    result = _stage(tmp_path, optimizer=_FakeOptimizer(steps=rt.MAX_STEPS + 1))
    assert not result.may_start_pyscf
    assert "step limit" in (result.reason or "")


def test_an_empty_trajectory_stops_the_route(tmp_path: Path) -> None:
    result = _stage(tmp_path, optimizer=_FakeOptimizer(trajectory_frames=0))
    assert not result.may_start_pyscf
    assert "empty trajectory" in (result.reason or "")


def test_a_non_finite_force_stops_the_route(tmp_path: Path) -> None:
    result = _stage(tmp_path, optimizer=_FakeOptimizer(final_max_force=float("nan")))
    assert not result.may_start_pyscf


def test_a_failed_structural_gate_stops_the_route(tmp_path: Path) -> None:
    class _Wrecker(_FakeOptimizer):
        def optimize(self, **kw: Any) -> OptimizerOutcome:
            outcome = super().optimize(**kw)
            wrecked = tuple((x + 5.0, y, z) for x, y, z in outcome.coordinates)
            return dataclasses.replace(outcome, coordinates=wrecked)

    result = _stage(tmp_path, optimizer=_Wrecker())
    assert not result.may_start_pyscf
    assert "structural gate" in (result.reason or "")


def test_the_cation_failing_means_the_neutral_never_starts(tmp_path: Path) -> None:
    optimizer = _FakeOptimizer(converged=False)
    result = _stage(tmp_path, optimizer=optimizer)
    assert not result.may_start_pyscf
    # Only the cation's calculator was ever made.
    assert optimizer.calls == [(1, 1)]
    assert not (tmp_path / "run/runtime/aimnet2/neutral/output.xyz").exists()


def test_a_drifted_input_digest_stops_the_route(tmp_path: Path) -> None:
    request = _request(tmp_path)
    broken = dataclasses.replace(
        request, cation=dataclasses.replace(request.cation, xyz_sha256="9" * 64)
    )
    result = _stage(tmp_path, request=broken)
    assert not result.may_start_pyscf
    assert "does not match the request digest" in (result.reason or "")


def test_a_drifted_endpoint_charge_stops_the_route(tmp_path: Path) -> None:
    request = _request(tmp_path)
    broken = dataclasses.replace(request, neutral=dataclasses.replace(request.neutral, charge=1))
    result = _stage(tmp_path, request=broken)
    assert not result.may_start_pyscf
    assert "charge or multiplicity drifted" in (result.reason or "")


def test_the_model_is_loaded_once_for_the_whole_route(tmp_path: Path) -> None:
    loader = _CountingLoader()
    result = _stage(tmp_path, loader=loader)
    assert loader.loads == 1
    assert result.model_load_count == 1
    # Two calculators from one model, with different charges and no shared state.
    assert loader.model.calculators == [(1, 1), (0, 1)]


def test_preoptimization_runs_exactly_once_per_endpoint(tmp_path: Path) -> None:
    optimizer = _FakeOptimizer()
    result = _stage(tmp_path, optimizer=optimizer)
    assert result.may_start_pyscf
    assert len(optimizer.calls) == 2
    # A second stage over the same root cannot re-run: the evidence is exclusive.
    again = _stage(tmp_path, optimizer=_FakeOptimizer())
    assert not again.may_start_pyscf
    assert "already exists" in (again.reason or "")


def test_the_local_deadline_never_extends_the_route_deadline(tmp_path: Path) -> None:
    seen: list[float] = []

    class _DeadlineSpy(_FakeOptimizer):
        def optimize(self, **kw: Any) -> OptimizerOutcome:
            seen.append(float(kw["deadline_monotonic"]))
            return super().optimize(**kw)

    _stage(tmp_path, optimizer=_DeadlineSpy(), absolute_deadline_monotonic=5.0)
    assert seen and all(value <= 5.0 for value in seen)


def test_the_stage_records_cache_and_weight_observations(tmp_path: Path) -> None:
    result = _stage(tmp_path)
    assert result.cache.cache_root.endswith("runtime/cache")
    assert result.cache.files_created >= 0
    assert result.weight.sha256_before == result.weight.sha256_after
    assert result.weight.bytes_before == AIMNET2_WEIGHT_BYTES


def test_the_stage_never_writes_outside_its_run_root(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    outside = tmp_path / "outside"
    outside.mkdir()
    _stage(tmp_path)
    assert not any(outside.iterdir())
    for entry in run_root.rglob("*"):
        assert run_root in entry.parents or entry == run_root


def test_a_broken_bond_alone_fails_the_connectivity_gate() -> None:
    """Isolated from RMSD and displacement, which would otherwise mask it.

    Mutation testing found that a large-displacement test cannot prove the
    connectivity comparison: RMSD fails first. This moves one atom just far
    enough to break its bond and no further.
    """

    elements, before = parse_xyz(_CATION_XYZ)
    after = [list(point) for point in before]
    atom_map = PHASE9B_CANDIDATE.atom_map
    # Stretch C2-N1 past the covalent cutoff while staying inside every distance
    # gate except the bond-change one.
    after[atom_map["N1"]] = [2.1, 0.0, 0.0]
    validation = validate_structure(
        endpoint="cation",
        elements_before=elements,
        before=before,
        elements_after=elements,
        after=after,
    )
    assert validation.total_rmsd_angstrom < rt.MAX_TOTAL_RMSD_ANGSTROM
    assert (
        validation.max_single_atom_displacement_angstrom < rt.MAX_SINGLE_ATOM_DISPLACEMENT_ANGSTROM
    )
    assert validation.connectivity_preserved is False
    assert validation.all_gates_passed is False


def test_one_endpoint_may_be_preoptimized_only_once() -> None:
    """The exactly-once record, driven directly.

    A second stage over the same root fails earlier on exclusive evidence, so
    that path cannot prove this guard; this drives the record itself.
    """

    once = rt._EndpointOnce()  # pyright: ignore[reportPrivateUsage]
    result = rt.EndpointResult(
        endpoint="cation",
        state=rt.EndpointState.PYSCF_ALLOWED,
        preoptimization=None,  # type: ignore[arg-type]
        handoff=None,  # type: ignore[arg-type]
        output_xyz_bytes=b"",
        output_xyz_path="/tmp/out.xyz",
        failure_reason=None,
    )
    once.record(result)
    assert once.has("cation")
    assert not once.has("neutral")
    with pytest.raises(Aimnet2RuntimeError, match="requested twice"):
        once.record(result)


def test_a_refused_cation_handoff_stops_before_the_neutral(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-endpoint gate stops the route; it does not merely flag it later.

    ``may_start_pyscf`` is also recomputed over every handoff at the end, so this
    isolates what the in-loop check uniquely contributes: the neutral never runs.
    """

    real_gate = rt.pyscf_may_start
    optimizer = _FakeOptimizer()

    def refuse_the_cation(handoff: Any) -> bool:
        return real_gate(handoff) and handoff.endpoint != "cation"

    monkeypatch.setattr(rt, "pyscf_may_start", refuse_the_cation)
    result = _stage(tmp_path, optimizer=optimizer)
    assert not result.may_start_pyscf
    assert "handoff did not close" in (result.reason or "")
    # Only the cation was ever optimized.
    assert optimizer.calls == [(1, 1)]
    assert not (tmp_path / "run/runtime/aimnet2/neutral/output.xyz").exists()


def test_the_final_gate_is_recomputed_over_every_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The backstop, isolated from the in-loop check."""

    real_gate = rt.pyscf_may_start
    seen: list[str] = []

    def watch(handoff: Any) -> bool:
        seen.append(handoff.endpoint)
        return real_gate(handoff)

    monkeypatch.setattr(rt, "pyscf_may_start", watch)
    result = _stage(tmp_path)
    assert result.may_start_pyscf
    # Each endpoint is checked in the loop and again in the final recomputation.
    assert seen.count("cation") >= 2
    assert seen.count("neutral") >= 2
