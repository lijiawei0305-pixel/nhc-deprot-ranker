"""Compute-capability identity parameterization regressions.

No chemistry, no server, no compute. These pin the last of the three Phase 8B
bindings the guarded worker depended on: the capability validator now compares
against a registry entry instead of module constants, so a second authority
chain needs a registered expectation rather than an edit to the validation logic.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, cast

import pytest

from nhc_deprot_ranker.quantum import two_endpoint as runner
from nhc_deprot_ranker.quantum.phase8b_permit import (
    FROZEN_ATTEMPT_ID,
    FROZEN_INCHIKEY,
    FROZEN_INPUT_SHA256,
    FROZEN_PROTOCOL_SHA256,
    FROZEN_REQUEST_ID,
)


def _expectation() -> runner.CapabilityIdentityExpectation:
    return runner._phase8b_capability_identity_expectation()  # pyright: ignore[reportPrivateUsage]


def test_phase8b_expectation_reproduces_the_historical_constants_verbatim() -> None:
    from nhc_deprot_ranker.quantum.phase8b_authority import (
        FROZEN_ELECTRON_COUNT,
        PHASE7_GEOMETRY_VALIDATION_SHA256,
    )

    expected = _expectation()
    assert expected.identity_key == runner.PHASE8B_CAPABILITY_IDENTITY_KEY
    assert expected.request_id == FROZEN_REQUEST_ID
    assert expected.inchikey == FROZEN_INCHIKEY
    assert expected.attempt_ids == (FROZEN_ATTEMPT_ID,)
    assert expected.protocol_sha256 == FROZEN_PROTOCOL_SHA256
    assert expected.electron_count == FROZEN_ELECTRON_COUNT == 120
    assert expected.endpoint_atom_map_sha256 == FROZEN_INPUT_SHA256["endpoint_atom_map"]
    assert expected.legacy_atom_map_sha256 == FROZEN_INPUT_SHA256["legacy_atom_map"]
    assert expected.geometry_validation_sha256 == PHASE7_GEOMETRY_VALIDATION_SHA256
    assert (
        expected.resources_sha256 == runner._frozen_resources_sha256()  # pyright: ignore[reportPrivateUsage]
    )


def test_expectation_is_deterministic() -> None:
    assert _expectation() == _expectation()


def test_registry_holds_only_fully_frozen_chains() -> None:
    """Both chains now have frozen resources; nothing else may be registered."""

    registry = runner._CAPABILITY_IDENTITY_EXPECTATIONS  # pyright: ignore[reportPrivateUsage]
    assert sorted(registry) == ["phase8b-qxh-smoke", "phase9b-lbnp-paired-smoke"]
    for build in registry.values():
        expectation = build()
        assert len(expectation.resources_sha256) == 64
        assert expectation.electron_count % 2 == 0


def test_identity_key_is_part_of_the_capability_binding() -> None:
    """A swapped key must invalidate the registered binding tuple."""

    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "capability._identity_key," in source


def test_validator_no_longer_compares_against_module_constants() -> None:
    """The candidate-specific comparison must go through the registry."""

    source = Path(runner.__file__).read_text(encoding="utf-8")
    start = source.index("def _validate_compute_capability_fields")
    end = source.index("class PySCFBackend")
    body = source[start:end]
    assert "_CAPABILITY_IDENTITY_EXPECTATIONS.get(capability._identity_key)" in body
    for forbidden in (
        "FROZEN_REQUEST_ID",
        "FROZEN_INCHIKEY",
        "FROZEN_ATTEMPT_ID",
        "FROZEN_ELECTRON_COUNT",
        "FROZEN_INPUT_SHA256",
        "PHASE7_GEOMETRY_VALIDATION_SHA256",
        "_frozen_resources_sha256()",
    ):
        assert forbidden not in body, forbidden


class _FakeCapability:
    """Mirrors only the attributes the validator reads."""

    def __init__(self, key: str) -> None:
        expected = _expectation()
        self._seal = runner._COMPUTE_CAPABILITY_SEAL  # pyright: ignore[reportPrivateUsage]
        self._identity_key = key
        self._compute_claim_sha256 = "a" * 64
        self._request_id = expected.request_id
        self._inchikey = expected.inchikey
        self._attempt_id = expected.attempt_ids[0]
        self._protocol_sha256 = expected.protocol_sha256
        self._electron_count = expected.electron_count
        self._endpoint_atom_map_sha256 = expected.endpoint_atom_map_sha256
        self._legacy_atom_map_sha256 = expected.legacy_atom_map_sha256
        self._geometry_validation_sha256 = expected.geometry_validation_sha256
        self._resources_sha256 = expected.resources_sha256
        import os
        import time

        self._pid = os.getpid()
        self._absolute_deadline_ns = time.monotonic_ns() + 60_000_000_000


def _validate(capability: object) -> None:
    runner._validate_compute_capability_fields(  # pyright: ignore[reportPrivateUsage]
        capability  # type: ignore[arg-type]
    )


def test_registered_key_validates() -> None:
    _validate(_FakeCapability(runner.PHASE8B_CAPABILITY_IDENTITY_KEY))


def test_unregistered_key_fails_closed() -> None:
    registry = runner._CAPABILITY_IDENTITY_EXPECTATIONS  # pyright: ignore[reportPrivateUsage]
    unregistered = "phase10-production-batch"
    assert unregistered not in registry
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="no frozen identity expectation"):
        _validate(_FakeCapability(unregistered))


def test_empty_key_fails_closed() -> None:
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="no frozen identity expectation"):
        _validate(_FakeCapability(""))


def test_field_drift_under_a_registered_key_still_fails_closed() -> None:
    capability = _FakeCapability(runner.PHASE8B_CAPABILITY_IDENTITY_KEY)
    capability._electron_count = 160
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="identity drifted"):
        _validate(capability)


def test_atom_map_drift_under_a_registered_key_fails_closed() -> None:
    capability = _FakeCapability(runner.PHASE8B_CAPABILITY_IDENTITY_KEY)
    capability._endpoint_atom_map_sha256 = "b" * 64
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="identity drifted"):
        _validate(capability)


def test_broken_seal_fails_before_the_registry_lookup() -> None:
    capability = _FakeCapability(runner.PHASE8B_CAPABILITY_IDENTITY_KEY)
    capability._seal = object()
    with pytest.raises(runner.ExecutionNotAuthorizedError, match="identity drifted"):
        _validate(capability)


def test_expectation_record_is_immutable() -> None:
    expected = _expectation()
    with pytest.raises(FrozenInstanceError):
        expected.electron_count = 160  # type: ignore[misc]
    assert replace(expected, electron_count=160).electron_count == 160
    assert _expectation().electron_count == 120


def test_capability_issue_rejects_an_unregistered_identity_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caught by mutation testing: the registry guard inside capability issue was
    unobservable because no test drove that function with a bad key.
    """

    from nhc_deprot_ranker.quantum.phase8b_execution import ComputeClaimEvidence

    monkeypatch.setattr(runner, "EXECUTION_AUTHORIZED", True)
    evidence = object.__new__(ComputeClaimEvidence)

    def _must_not_reload(**kwargs: object) -> tuple[object, object]:
        raise AssertionError("reload must not run for an unregistered identity key")

    with pytest.raises(runner.ExecutionNotAuthorizedError, match="no frozen identity expectation"):
        runner._issue_guarded_compute_capability(  # pyright: ignore[reportPrivateUsage]
            request=cast(Any, object()),
            consumed=object(),
            authority=cast(Any, object()),
            bootstrap_proof=object(),
            output_root=Path("/nonexistent"),
            attempt_id="attempt-anything",
            absolute_deadline_ns=1,
            compute_claim_evidence=evidence,
            consumed_permit_type=object,
            authority_type=object,
            identity_key="phase10-production-batch",
            allowed_cpus=frozenset({0}),
            reload_permit_and_authority=_must_not_reload,
            extra_authority_match=None,
        )


def test_capability_issue_registry_guard_precedes_any_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A registered key must reach the reload; an unregistered one must not."""

    from nhc_deprot_ranker.quantum.phase8b_execution import ComputeClaimEvidence

    monkeypatch.setattr(runner, "EXECUTION_AUTHORIZED", True)
    evidence = object.__new__(ComputeClaimEvidence)
    reached: list[str] = []

    def _reload(**kwargs: object) -> tuple[object, object]:
        reached.append("reload")
        raise runner.ExecutionNotAuthorizedError("synthetic reload stop")

    with pytest.raises(runner.ExecutionNotAuthorizedError, match="synthetic reload stop"):
        runner._issue_guarded_compute_capability(  # pyright: ignore[reportPrivateUsage]
            request=cast(Any, object()),
            consumed=object(),
            authority=cast(Any, object()),
            bootstrap_proof=object(),
            output_root=Path("/nonexistent"),
            attempt_id="attempt-anything",
            absolute_deadline_ns=1,
            compute_claim_evidence=evidence,
            consumed_permit_type=object,
            authority_type=object,
            identity_key=runner.PHASE8B_CAPABILITY_IDENTITY_KEY,
            allowed_cpus=frozenset({0}),
            reload_permit_and_authority=_reload,
            extra_authority_match=None,
        )
    assert reached == ["reload"]
