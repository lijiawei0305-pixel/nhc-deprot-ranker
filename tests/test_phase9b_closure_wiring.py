"""Runner source closure wiring regressions.

No chemistry, no server, no compute.

The capability expectation builder inside two_endpoint.py already imports the
Phase 9B authority, permit, and resource modules at call time, so their content
already influences closure-internal behaviour. They therefore belong inside the
closure now, and the schema version must change with the file set.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from nhc_deprot_ranker.quantum import two_endpoint as runner

_PHASE9B_CLOSURE_MEMBERS = (
    "nhc_deprot_ranker/quantum/phase9b_authority.py",
    "nhc_deprot_ranker/quantum/phase9b_permit.py",
    "nhc_deprot_ranker/quantum/phase9b_resources.py",
    "nhc_deprot_ranker/quantum/phase9b_supervisor.py",
)


def _closure() -> tuple[str, ...]:
    return runner._RUNNER_SOURCE_RELATIVE_PATHS  # pyright: ignore[reportPrivateUsage]


def test_schema_version_reflects_the_changed_file_set() -> None:
    """A digest over a different file set must not share the old version."""

    assert runner.RUNNER_SOURCE_SCHEMA_VERSION == "nhc-two-endpoint-runner-source-v4"
    assert "v3" not in runner.RUNNER_SOURCE_SCHEMA_VERSION


def test_every_phase9b_module_is_now_in_the_closure() -> None:
    closure = _closure()
    for member in _PHASE9B_CLOSURE_MEMBERS:
        assert member in closure, member


def test_closure_holds_exactly_eighteen_files_with_no_duplicates() -> None:
    closure = _closure()
    assert len(closure) == 18
    assert len(set(closure)) == len(closure)


def test_the_historical_fourteen_are_all_retained() -> None:
    """Wiring must add, never drop: a removed file would stop being hash-bound."""

    historical = (
        "nhc_deprot_ranker/__init__.py",
        "nhc_deprot_ranker/constants.py",
        "nhc_deprot_ranker/data/__init__.py",
        "nhc_deprot_ranker/data/provenance.py",
        "nhc_deprot_ranker/quantum/__init__.py",
        "nhc_deprot_ranker/quantum/linux_guardian.py",
        "nhc_deprot_ranker/quantum/phase8b_authority.py",
        "nhc_deprot_ranker/quantum/phase8b_execution.py",
        "nhc_deprot_ranker/quantum/phase8b_permit.py",
        "nhc_deprot_ranker/quantum/phase8b_runtime.py",
        "nhc_deprot_ranker/quantum/two_endpoint.py",
        "nhc_deprot_ranker/quantum/worker.py",
        "nhc_deprot_ranker/quantum/worker_bootstrap.py",
        "nhc_deprot_ranker/quantum/process_supervisor.py",
    )
    closure = _closure()
    for member in historical:
        assert member in closure, member
    assert len(historical) == 14


def test_every_closure_member_exists_on_disk() -> None:
    root = Path(runner.__file__).resolve().parents[2]
    for member in _closure():
        path = root / member
        assert path.is_file(), member
        assert not path.is_symlink(), member


def test_current_source_hash_is_computable_and_stable() -> None:
    first = runner.current_runner_source_sha256()
    assert len(first) == 64
    assert first == runner.current_runner_source_sha256()


def test_source_hash_covers_the_phase9b_content() -> None:
    """Changing a Phase 9B module must change the digest, or it is not bound."""

    root = Path(runner.__file__).resolve().parents[2]
    sources = {name: (root / name).read_bytes() for name in _closure()}
    baseline = runner._canonical_runner_source_sha256(  # pyright: ignore[reportPrivateUsage]
        sources
    )
    assert baseline == runner.current_runner_source_sha256()

    for member in _PHASE9B_CLOSURE_MEMBERS:
        tampered = dict(sources)
        tampered[member] = sources[member] + b"# tamper\n"
        mutated = runner._canonical_runner_source_sha256(  # pyright: ignore[reportPrivateUsage]
            tampered
        )
        assert mutated != baseline, member


def test_hash_requires_the_exact_file_set() -> None:
    root = Path(runner.__file__).resolve().parents[2]
    sources = {name: (root / name).read_bytes() for name in _closure()}

    short = dict(sources)
    short.pop("nhc_deprot_ranker/quantum/phase9b_permit.py")
    with pytest.raises(ValueError, match="exact canonical file set"):
        runner._canonical_runner_source_sha256(short)  # pyright: ignore[reportPrivateUsage]

    extra = dict(sources)
    extra["nhc_deprot_ranker/quantum/nonexistent.py"] = b""
    with pytest.raises(ValueError, match="exact canonical file set"):
        runner._canonical_runner_source_sha256(extra)  # pyright: ignore[reportPrivateUsage]


def test_schema_version_participates_in_the_digest() -> None:
    """The version must be mixed in, or a file-set change could collide."""

    root = Path(runner.__file__).resolve().parents[2]
    sources = {name: (root / name).read_bytes() for name in _closure()}
    real = runner._canonical_runner_source_sha256(sources)  # pyright: ignore[reportPrivateUsage]

    digest = hashlib.sha256()
    digest.update(b"nhc-two-endpoint-runner-source-v3")
    digest.update(b"\x00")
    for name in _closure():
        encoded_name = name.encode("utf-8")
        content = sources[name]
        digest.update(len(encoded_name).to_bytes(2, "big"))
        digest.update(encoded_name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    assert digest.hexdigest() != real


def test_phase9b_authority_now_carries_the_resource_hash() -> None:
    """The worker claim validator reads authority.resources_sha256."""

    from nhc_deprot_ranker.quantum.phase9b_permit import Phase9BExactAuthority

    assert "resources_sha256" in Phase9BExactAuthority.__dataclass_fields__


def test_phase9b_authority_field_set_covers_every_field_the_worker_reads() -> None:
    from nhc_deprot_ranker.quantum.phase9b_permit import Phase9BExactAuthority

    worker_source = Path(Path(runner.__file__).resolve().parent / "worker.py").read_text(
        encoding="utf-8"
    )
    read_fields = {
        line.split("authority.")[1].split()[0].rstrip(",)")
        for line in worker_source.splitlines()
        if "authority." in line and "authority_" not in line
    }
    available = set(Phase9BExactAuthority.__dataclass_fields__)
    missing = {f for f in read_fields if f and f.isidentifier()} - available
    assert not missing, f"Phase 9B authority is missing fields the worker reads: {missing}"
