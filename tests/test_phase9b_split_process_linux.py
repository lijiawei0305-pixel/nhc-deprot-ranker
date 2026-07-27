"""Authoritative Linux fake-process tests for the Item 10 campaign runtime."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from nhc_deprot_ranker.quantum.linux_guardian import (
    ProcessIdentityError,
    read_process_identity,
)
from nhc_deprot_ranker.quantum.phase9b_campaign_evidence import CampaignEvidenceStore
from nhc_deprot_ranker.quantum.phase9b_campaign_schemas import AssistedCampaignIdentityV1
from nhc_deprot_ranker.quantum.phase9b_campaign_supervisor import (
    CampaignExecutionPlan,
    CampaignRuntimeInputs,
    StageSubprocessSpec,
    run_assisted_campaign,
)
from nhc_deprot_ranker.quantum.phase9b_internal_stage_capability import (
    PHASE9B_A1_STAGE_PROFILE,
    PHASE9B_A2_STAGE_PROFILE,
)
from nhc_deprot_ranker.quantum.phase9b_interpreter_profiles import (
    GPUPYSCF_STABLE_PROFILE,
    MLFF_STABLE_PROFILE,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not hasattr(os, "waitid") or not hasattr(os, "WNOWAIT"),
    reason="authoritative process supervision requires Linux waitid(WNOWAIT)",
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _elements() -> tuple[tuple[str, ...], tuple[str, ...]]:
    heavy = tuple(["C"] * 8 + ["N"] + ["F"] * 5 + ["C", "N", "N"] + ["F"] * 4)
    return heavy + ("H",) * 5, heavy + ("H",) * 4


def _xyz(elements: tuple[str, ...], comment: str) -> str:
    lines = [str(len(elements)), comment]
    lines.extend(f"{element} {index}.0 0.0 0.0" for index, element in enumerate(elements))
    return "\n".join(lines) + "\n"


def _common_template(
    *, stage: str, helper: Path, evidence_root: Path, fixture: Path
) -> tuple[str, ...]:
    del helper
    return (
        os.path.realpath(sys.executable),
        "-m",
        "nhc_deprot_ranker.preparation.phase9b_item10_fake_stage",
        "--stage-kind",
        stage,
        "--registration-fd",
        "{registration_fd}",
        "--release-fd",
        "{release_fd}",
        "--campaign-id",
        "{campaign_id}",
        "--attempt-id",
        "{attempt_id}",
        "--candidate",
        "{candidate}",
        "--supervisor-pid",
        "{supervisor_pid}",
        "--supervisor-start-time",
        "{supervisor_start_time}",
        "--supervisor-session-id",
        "{supervisor_session_id}",
        "--supervisor-process-group-id",
        "{supervisor_process_group_id}",
        "--stage-source-sha256",
        "{stage_source_sha256}",
        "--registration-nonce-sha256",
        "{registration_nonce_sha256}",
        "--clock-domain-digest",
        "{clock_domain_digest}",
        "--linux-boot-id-sha256",
        "{linux_boot_id_sha256}",
        "--evidence-root",
        evidence_root.as_posix(),
        "--fixture-path",
        fixture.as_posix(),
    )


def _campaign(tmp_path: Path):
    evidence_root = (tmp_path / "campaign").resolve()
    fixture_path = (tmp_path / "fixture.json").resolve()
    cation, neutral = _elements()
    fixture_path.write_text(
        json.dumps(
            {
                "endpoints": {
                    "cation": {
                        "input_xyz": _xyz(cation, "cation initial"),
                        "output_xyz": _xyz(cation, "cation A1 output"),
                    },
                    "neutral": {
                        "input_xyz": _xyz(neutral, "neutral initial"),
                        "output_xyz": _xyz(neutral, "neutral A1 output"),
                    },
                },
                "weight_sha256": _sha("fake-weight"),
                "optimizer_protocol_sha256": _sha("fake-optimizer"),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    helper = (
        Path(__file__).resolve().parents[1]
        / "src/nhc_deprot_ranker/preparation/phase9b_item10_fake_stage.py"
    )
    executable = Path(os.path.realpath(sys.executable))
    executable_sha = _file_sha(executable)
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    a1_source = _sha("stage-a1-source")
    a2_source = _sha("stage-a2-source")
    shared_schema = _sha("shared-schema")
    shared_core = _sha("shared-core")
    control = _sha("campaign-control")
    full = _sha("full-campaign")
    request_sha = _sha("request")
    manifest_sha = _sha("manifest")
    resources_sha = _sha("resources")
    campaign_id = "campaign-linux-v1"
    attempt_id = "attempt-linux-v1"
    candidate = "candidate-linux-v1"
    identity = AssistedCampaignIdentityV1(
        {
            "schema_version": AssistedCampaignIdentityV1.SCHEMA_VERSION,
            "campaign_id": campaign_id,
            "attempt_id": attempt_id,
            "candidate": candidate,
            "route": "assisted",
            "request_sha256": request_sha,
            "manifest_sha256": manifest_sha,
            "resources_sha256": resources_sha,
            "full_source_sha256": full,
            "mlff_profile_sha256": MLFF_STABLE_PROFILE.sha256(),
            "gpupyscf_profile_sha256": GPUPYSCF_STABLE_PROFILE.sha256(),
        }
    )
    inputs = CampaignRuntimeInputs(
        campaign_identity=identity,
        campaign_capability_sha256=_sha("campaign-capability"),
        candidate=candidate,
        request_id="request-linux-v1",
        attempt_id=attempt_id,
        request_sha256=request_sha,
        manifest_sha256=manifest_sha,
        resources_sha256=resources_sha,
        full_source_sha256=full,
        shared_schema_source_sha256=shared_schema,
        shared_pyscf_core_source_sha256=shared_core,
        campaign_control_source_sha256=control,
        stage_a1_source_sha256=a1_source,
        stage_a2_source_sha256=a2_source,
        mlff_stable_profile_id=MLFF_STABLE_PROFILE.logical_profile_id,
        mlff_stable_profile_sha256=MLFF_STABLE_PROFILE.sha256(),
        mlff_private_binding_sha256=_sha("private-mlff"),
        gpupyscf_stable_profile_id=GPUPYSCF_STABLE_PROFILE.logical_profile_id,
        gpupyscf_stable_profile_sha256=GPUPYSCF_STABLE_PROFILE.sha256(),
        gpupyscf_private_binding_sha256=_sha("private-gpupyscf"),
        input_identity_sha256=_sha("inputs"),
        output_root_identity_sha256=_sha("output-root"),
        schema_identities_sha256=_sha("schemas"),
        weight_sha256=_sha("fake-weight"),
        optimizer_protocol_sha256=_sha("fake-optimizer"),
    )
    plan = CampaignExecutionPlan(
        a1_spec=StageSubprocessSpec(
            profile=PHASE9B_A1_STAGE_PROFILE,
            argv_template=_common_template(
                stage="a1", helper=helper, evidence_root=evidence_root, fixture=fixture_path
            ),
            cwd=(Path(__file__).resolve().parents[1] / "src"),
            environment=environment,
            stage_source_sha256=a1_source,
            executable_sha256=executable_sha,
            registration_nonce_sha256=_sha("a1-registration"),
        ),
        a2_spec=StageSubprocessSpec(
            profile=PHASE9B_A2_STAGE_PROFILE,
            argv_template=_common_template(
                stage="a2", helper=helper, evidence_root=evidence_root, fixture=fixture_path
            ),
            cwd=(Path(__file__).resolve().parents[1] / "src"),
            environment=environment,
            stage_source_sha256=a2_source,
            executable_sha256=executable_sha,
            registration_nonce_sha256=_sha("a2-registration"),
        ),
    )
    return inputs, plan, CampaignEvidenceStore(evidence_root)


def test_linux_real_subprocess_campaign_is_sequential_reaped_and_hash_closed(
    tmp_path: Path,
) -> None:
    inputs, plan, store = _campaign(tmp_path)
    terminal = run_assisted_campaign(inputs=inputs, plan=plan, store=store)
    payload = terminal.to_payload()
    assert payload["route_outcome"] == "accepted"
    assert payload["campaign_runtime_state"] == "route_accepted"
    assert payload["failure"] is None
    assert payload["label"]["synthetic_test_only"] is True
    assert payload["label"]["dft_deprot_electronic_kcal"] == 123.456
    store.assert_no_extra_files()


def test_linux_timeout_kills_exact_stage_group_and_never_reuses_capability(
    tmp_path: Path,
) -> None:
    from nhc_deprot_ranker.quantum.process_supervisor import SupervisionPolicy, run_supervised

    result = run_supervised(
        (
            sys.executable,
            "-c",
            "import os,time; os.fork() == 0 and time.sleep(60); time.sleep(60)",
        ),
        policy=SupervisionPolicy(
            timeout_seconds=0.2,
            terminate_grace_seconds=0.05,
            stream_capture_limit_bytes=1024,
            poll_interval_seconds=0.01,
        ),
        cwd=tmp_path,
    )
    assert result.outcome == "timeout"
    assert result.term_sent is True
    assert result.group_cleanup_confirmed is True
    assert result.direct_child_reaped is True
    assert result.safe_to_finalize is True
    if result.pid is not None:
        with pytest.raises(ProcessIdentityError):
            read_process_identity(result.pid)
