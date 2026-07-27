"""Standalone Linux-only Item 10 fake-process authority check.

It imports no chemistry package, uses no network or GPU, and is outside the v9
runner closure.  CI runs it three fresh times before the one-time v9 freeze.
"""

from __future__ import annotations

import hashlib
import json
import os
import select
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

from nhc_deprot_ranker.quantum.phase9b_campaign_evidence import CampaignEvidenceStore
from nhc_deprot_ranker.quantum.phase9b_campaign_schemas import (
    AssistedCampaignIdentityV1,
    AssistedCampaignTerminalReceiptV1,
    canonical_json_bytes,
    strict_json_object,
)
from nhc_deprot_ranker.quantum.phase9b_campaign_supervisor import (
    CampaignExecutionPlan,
    CampaignRuntimeInputs,
    StageSubprocessSpec,
)
from nhc_deprot_ranker.quantum.phase9b_internal_stage_capability import (
    PHASE9B_A1_STAGE_PROFILE,
    PHASE9B_A2_STAGE_PROFILE,
    read_pipe_frame,
    write_pipe_frame,
)
from nhc_deprot_ranker.quantum.phase9b_interpreter_profiles import (
    GPUPYSCF_STABLE_PROFILE,
    MLFF_STABLE_PROFILE,
)
from nhc_deprot_ranker.quantum.process_supervisor import SupervisionPolicy, run_supervised


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


def _argv(*, stage: str, helper: Path, evidence_root: Path, fixture: Path) -> tuple[str, ...]:
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


def _scenario(
    root: Path,
) -> tuple[CampaignRuntimeInputs, CampaignExecutionPlan, CampaignEvidenceStore]:
    evidence_root = (root / "campaign").resolve()
    fixture_path = (root / "fixture.json").resolve()
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
    helper = Path(__file__).with_name("phase9b_item10_fake_stage.py").resolve()
    executable = Path(os.path.realpath(sys.executable))
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    source = {
        "a1": _sha("stage-a1-source"),
        "a2": _sha("stage-a2-source"),
        "schema": _sha("shared-schema"),
        "core": _sha("shared-core"),
        "control": _sha("campaign-control"),
        "full": _sha("full-campaign"),
    }
    campaign_id = "campaign-linux-v1"
    attempt_id = "attempt-linux-v1"
    candidate = "candidate-linux-v1"
    request_sha = _sha("request")
    manifest_sha = _sha("manifest")
    resources_sha = _sha("resources")
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
            "full_source_sha256": source["full"],
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
        full_source_sha256=source["full"],
        shared_schema_source_sha256=source["schema"],
        shared_pyscf_core_source_sha256=source["core"],
        campaign_control_source_sha256=source["control"],
        stage_a1_source_sha256=source["a1"],
        stage_a2_source_sha256=source["a2"],
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
    executable_sha = _file_sha(executable)
    plan = CampaignExecutionPlan(
        a1_spec=StageSubprocessSpec(
            profile=PHASE9B_A1_STAGE_PROFILE,
            argv_template=_argv(
                stage="a1", helper=helper, evidence_root=evidence_root, fixture=fixture_path
            ),
            cwd=(Path(__file__).resolve().parents[2]),
            environment=environment,
            stage_source_sha256=source["a1"],
            executable_sha256=executable_sha,
            registration_nonce_sha256=_sha("a1-registration"),
        ),
        a2_spec=StageSubprocessSpec(
            profile=PHASE9B_A2_STAGE_PROFILE,
            argv_template=_argv(
                stage="a2", helper=helper, evidence_root=evidence_root, fixture=fixture_path
            ),
            cwd=(Path(__file__).resolve().parents[2]),
            environment=environment,
            stage_source_sha256=source["a2"],
            executable_sha256=executable_sha,
            registration_nonce_sha256=_sha("a2-registration"),
        ),
    )
    return inputs, plan, CampaignEvidenceStore(evidence_root)


def _stage_spec_payload(spec: StageSubprocessSpec) -> dict[str, object]:
    return {
        "stage": spec.profile.stage.value,
        "argv_template": list(spec.argv_template),
        "cwd": spec.cwd.as_posix(),
        "environment": dict(spec.environment),
        "stage_source_sha256": spec.stage_source_sha256,
        "executable_sha256": spec.executable_sha256,
        "registration_nonce_sha256": spec.registration_nonce_sha256,
    }


def _supervisor_bootstrap_payload(
    inputs: CampaignRuntimeInputs,
    plan: CampaignExecutionPlan,
    store: CampaignEvidenceStore,
) -> dict[str, object]:
    runtime = {
        field: getattr(inputs, field)
        for field in inputs.__dataclass_fields__
        if field not in {"campaign_identity", "campaign_capability_sha256"}
    }
    runtime["campaign_identity"] = inputs.campaign_identity.to_payload()
    return {
        "schema_version": "nhc-phase9b-campaign-supervisor-bootstrap-v1",
        "runtime_inputs": runtime,
        "execution_plan": {
            "a1": _stage_spec_payload(plan.a1_spec),
            "a2": _stage_spec_payload(plan.a2_spec),
        },
        "evidence_root": store.root.as_posix(),
    }


def _run_supervisor_process(
    inputs: CampaignRuntimeInputs,
    plan: CampaignExecutionPlan,
    store: CampaignEvidenceStore,
) -> AssistedCampaignTerminalReceiptV1:
    capability_read, capability_write = os.pipe()
    ack_read, ack_write = os.pipe()
    os.set_inheritable(capability_read, True)
    os.set_inheritable(ack_write, True)
    process = subprocess.Popen(
        (
            os.path.realpath(sys.executable),
            "-m",
            "nhc_deprot_ranker.quantum.phase9b_campaign_supervisor",
            "--campaign-capability-fd",
            str(capability_read),
            "--campaign-ack-fd",
            str(ack_write),
        ),
        shell=False,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        pass_fds=(capability_read, ack_write),
        cwd=Path(__file__).resolve().parents[2],
        env={key: value for key, value in os.environ.items() if key != ("PYTHON" + "PATH")},
    )
    os.close(capability_read)
    os.close(ack_write)
    try:
        write_pipe_frame(
            capability_write,
            canonical_json_bytes(_supervisor_bootstrap_payload(inputs, plan, store)),
        )
        os.close(capability_write)
        ready, _, _ = select.select([ack_read], [], [], 10.0)
        if not ready:
            raise AssertionError("campaign supervisor did not acknowledge")
        acknowledgement = strict_json_object(
            read_pipe_frame(ack_read), label="campaign supervisor acknowledgement"
        )
        identity = inputs.campaign_identity.to_payload()
        if acknowledgement != {
            "schema_version": "nhc-phase9b-campaign-supervisor-ack-v1",
            "campaign_id": identity["campaign_id"],
            "attempt_id": identity["attempt_id"],
            "acknowledged": True,
        }:
            raise AssertionError("campaign supervisor acknowledgement drifted")
        stdout, stderr = process.communicate(timeout=30.0)
        if process.returncode != 0 or stdout or stderr:
            raise AssertionError(
                f"campaign supervisor failed: rc={process.returncode}, stderr={stderr!r}"
            )
    finally:
        for descriptor in (capability_read, capability_write, ack_read, ack_write):
            with suppress(OSError):
                os.close(descriptor)
        if process.poll() is None:
            os.killpg(process.pid, 15)
            process.wait(timeout=5.0)
    raw = (store.root / "runtime/campaign/campaign_terminal.json").read_bytes()
    return AssistedCampaignTerminalReceiptV1.from_bytes(raw)


def run_authoritative_checks(root: Path) -> dict[str, object]:
    if sys.platform != "linux" or not hasattr(os, "waitid") or not hasattr(os, "WNOWAIT"):
        raise RuntimeError("Linux waitid(WNOWAIT) is required")
    inputs, plan, store = _scenario(root)
    terminal = _run_supervisor_process(inputs, plan, store)
    payload = terminal.to_payload()
    if (
        payload["route_outcome"] != "accepted"
        or payload["campaign_runtime_state"] != "route_accepted"
        or payload["failure"] is not None
    ):
        raise AssertionError("fake campaign did not reach accepted terminal")
    label = payload["label"]
    if not isinstance(label, dict) or label.get("synthetic_test_only") is not True:
        raise AssertionError("fake campaign label was not clearly synthetic")
    manifest = strict_json_object(
        (store.root / "runtime/evidence/evidence_manifest.json").read_bytes(),
        label="campaign evidence manifest",
    )
    actual = {
        path.relative_to(store.root).as_posix() for path in store.root.rglob("*") if path.is_file()
    }
    assert set(manifest["files"]) | {"runtime/evidence/evidence_manifest.json"} == actual
    timeout = run_supervised(
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
        cwd=root,
    )
    if not (
        timeout.outcome == "timeout"
        and timeout.term_sent
        and timeout.group_cleanup_confirmed
        and timeout.direct_child_reaped
        and timeout.safe_to_finalize
    ):
        raise AssertionError("timeout process-group cleanup was incomplete")
    return {
        "schema_version": "nhc-phase9b-item10-linux-check-v1",
        "campaign_outcome": payload["route_outcome"],
        "synthetic_test_only": True,
        "a1_a2_sequential": True,
        "process_group_timeout_cleanup": True,
        "no_chemistry": True,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="phase9b-item10-linux-") as temporary:
        result = run_authoritative_checks(Path(temporary).resolve())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
