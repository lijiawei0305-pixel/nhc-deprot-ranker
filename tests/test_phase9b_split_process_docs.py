from __future__ import annotations

import ast
import copy
import json
import re
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "docs" / "schemas"
V8_SHA256 = "5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2"
V9_SHA256 = "13ba49fe33f8a85cceae76b043619df832d15633aa08a91d0eadfab7c6f580f5"
SHA256_RE = re.compile(r"[0-9a-f]{64}")

DESIGN_DOCS = (
    "PHASE9B_SPLIT_PROCESS_RUNTIME_PLAN.md",
    "PHASE9B_SPLIT_PROCESS_AUTHORITY_CHAIN.md",
    "PHASE9B_INTERNAL_STAGE_CAPABILITY_CONTRACT.md",
    "PHASE9B_CROSS_PROCESS_HANDOFF_CONTRACT.md",
    "PHASE9B_ATTEMPT_AND_PROCESS_STATE_MACHINES.md",
    "PHASE9B_SPLIT_PROCESS_FAILURE_SEMANTICS.md",
    "PHASE9B_SPLIT_PROCESS_EVIDENCE_TREE.md",
    "PHASE9B_DIRECT_ASSISTED_PYSCF_PARITY.md",
    "PHASE9B_SPLIT_PROCESS_SOURCE_IDENTITY_PLAN.md",
    "PHASE9B_SPLIT_PROCESS_IMPLEMENTATION_PLAN.md",
    "PHASE9B_SPLIT_PROCESS_TEST_PLAN.md",
    "PHASE9B_SPLIT_PROCESS_REACHABILITY_AUDIT.md",
    "PHASE9B_UNIFIED_ENVIRONMENT_STRATEGY_CLOSEOUT.md",
)

SCHEMA_EXAMPLES = (
    "phase9b_assisted_campaign_permit_v3.example.json",
    "phase9b_internal_stage_capability_v1.example.json",
    "phase9b_cross_process_handoff_v1.example.json",
    "phase9b_campaign_terminal_v1.example.json",
)


def _read(name: str) -> str:
    return (ROOT / "docs" / name).read_text(encoding="utf-8")


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def _load_example(name: str) -> dict[str, object]:
    raw = (SCHEMA_ROOT / name).read_bytes()
    payload = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)
    return cast(dict[str, object], value)


def _sha(value: object) -> str:
    assert isinstance(value, str) and SHA256_RE.fullmatch(value)
    return value


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key) for key in value}
        for item in value.values():
            keys.update(_all_keys(item))
        return keys
    if isinstance(value, list):
        list_keys: set[str] = set()
        for item in value:
            list_keys.update(_all_keys(item))
        return list_keys
    return set()


def _is_non_authorizing_example(payload: dict[str, object]) -> bool:
    if payload.get("execution_authorized") is False:
        return True
    authorization = payload.get("authorization")
    return isinstance(authorization, dict) and authorization.get("execution_authorized") is False


def test_design_documents_exist_and_freeze_revised_contracts() -> None:
    combined = "\n".join(_read(name) for name in DESIGN_DOCS)
    for phrase in (
        "closed_after_u5",
        "AssistedCampaignPermitV3",
        "A1HandoffProposalReceiptV1",
        "SupervisorHandoffVerificationReceiptV1",
        "StageA2AdmissionReceiptV1",
        "AttemptLifecycleV1",
        "GuardianLaunchStateV1",
        "CampaignRuntimeStateV1",
        "InterpreterProfileStableIdentityV1",
        "InterpreterProfilePrivateBindingV1",
        "campaign_monotonic_start_ns",
        "clock-domain/boot digest",
        "one model load",
        "Disjoint",
        "acyclic",
    ):
        assert phrase in combined
    assert "no further unified-environment attempt" in combined
    assert "two ordinary assisted permits" in combined
    assert "CrossProcessPySCFHandoffReceiptV1" not in combined
    assert "initialized by A1" not in combined


def test_schema_examples_are_strict_json_and_structurally_complete() -> None:
    examples = {name: _load_example(name) for name in SCHEMA_EXAMPLES}
    for payload in examples.values():
        assert _is_non_authorizing_example(payload)
        assert isinstance(payload.get("schema_version"), str) or set(payload) == {
            "a1_handoff_proposal",
            "execution_authorized",
            "stage_a2_admission",
            "supervisor_handoff_verification",
        }
    permit = examples[SCHEMA_EXAMPLES[0]]
    assert set(permit) == {
        "authorization",
        "campaign",
        "evidence",
        "inputs",
        "interpreter_profiles",
        "manifest_sha256",
        "request_sha256",
        "resources",
        "schema_identities",
        "schema_version",
        "source",
    }
    for key in ("manifest_sha256", "request_sha256"):
        _sha(permit[key])
    assert set(_object(permit["inputs"])) == {
        "atom_map_sha256",
        "cation",
        "electron_count",
        "neutral",
    }
    assert set(_object(permit["interpreter_profiles"])) == {"a1", "direct_and_a2"}


def _permit_holds_contract(payload: dict[str, object]) -> bool:
    try:
        authorization = _object(payload["authorization"])
        campaign = _object(payload["campaign"])
        inputs = _object(payload["inputs"])
        profiles = _object(payload["interpreter_profiles"])
        source = _object(payload["source"])
        a1 = _object(profiles["a1"])
        direct_a2 = _object(profiles["direct_and_a2"])
    except (AssertionError, KeyError):
        return False
    forbidden = {
        "absolute_executable",
        "absolute_prefix",
        "campaign_absolute_deadline_ns",
        "device",
        "inode",
        "private_binding",
    }
    return (
        authorization.get("execution_authorized") is False
        and authorization.get("permit_consumption_authorized") is False
        and authorization.get("label_authorized") is False
        and authorization.get("one_shot") is True
        and authorization.get("retry_authorized") is False
        and authorization.get("resume_authorized") is False
        and authorization.get("fallback_authorized") is False
        and campaign.get("campaign_wall_limit_seconds") == 7200
        and campaign.get("a1_local_limit_seconds") == 900
        and campaign.get("termination_grace_seconds") == 10
        and campaign.get("topology") == "split_process_campaign"
        and campaign.get("schedule")
        == [
            "aimnet2_preoptimization",
            "handoff_verification",
            "pyscf_residual_optimization",
        ]
        and set(inputs) == {"atom_map_sha256", "cation", "electron_count", "neutral"}
        and a1.get("logical_profile_id") == "phase9b-mlff-stable-v1"
        and direct_a2.get("logical_profile_id") == "phase9b-gpupyscf-stable-v1"
        and all(
            key in profile
            for profile in (a1, direct_a2)
            for key in (
                "activation_script_sha256",
                "executable_content_sha256",
                "package_versions",
                "python_version",
                "runtime_capabilities",
                "sanitized_environment_identity_sha256",
                "stable_identity_sha256",
            )
        )
        and set(source)
        == {
            "campaign_control_source_sha256",
            "closure_dependency_edges_sha256",
            "deployment_inventory_sha256",
            "full_assisted_campaign_source_sha256",
            "shared_pyscf_core_source_sha256",
            "shared_schema_source_sha256",
            "stage_a1_source_sha256",
            "stage_a2_source_sha256",
        }
        and not (_all_keys(payload) & forbidden)
    )


def test_permit_duration_and_public_profile_mutations_fail_closed() -> None:
    original = _load_example(SCHEMA_EXAMPLES[0])
    assert _permit_holds_contract(original)
    mutations: list[dict[str, object]] = []
    for section, key, value in (
        ("authorization", "one_shot", False),
        ("authorization", "retry_authorized", True),
        ("campaign", "campaign_wall_limit_seconds", 8100),
        ("campaign", "campaign_absolute_deadline_ns", 12200000000000),
        ("interpreter_profiles", "direct_and_a2", {"logical_profile_id": "/private/python"}),
    ):
        mutated = copy.deepcopy(original)
        _object(mutated[section])[key] = value
        mutations.append(mutated)
    missing_source = copy.deepcopy(original)
    del _object(missing_source["source"])["stage_a2_source_sha256"]
    mutations.append(missing_source)
    assert all(not _permit_holds_contract(mutated) for mutated in mutations)


def _capability_holds_contract(payload: dict[str, object]) -> bool:
    try:
        auth = _object(payload["authorization"])
        clock = _object(payload["clock"])
        process = _object(payload["process_identity"])
        interpreter = _object(payload["interpreter"])
    except (AssertionError, KeyError):
        return False
    start = clock.get("campaign_monotonic_start_ns")
    deadline = clock.get("campaign_absolute_deadline_ns")
    process_keys = {
        "expected_parent_pid",
        "stage_pid",
        "stage_process_group_id",
        "stage_session_id",
        "stage_start_time",
        "supervisor_pid",
        "supervisor_process_group_id",
        "supervisor_session_id",
        "supervisor_start_time",
    }
    return (
        auth == {"execution_authorized": False, "one_shot": True, "release_consumed": False}
        and type(start) is int
        and type(deadline) is int
        and deadline - start == 7200 * 1_000_000_000
        and clock.get("clock_type") == "CLOCK_MONOTONIC"
        and all(
            key in clock
            for key in (
                "clock_domain_digest",
                "host_execution_identity_sha256",
                "linux_boot_id_sha256",
                "monotonic_resolution_ns",
                "stage_deadline_ns",
            )
        )
        and set(process) == process_keys
        and process.get("expected_parent_pid") == process.get("supervisor_pid")
        and process.get("stage_pid") == process.get("stage_session_id")
        and process.get("stage_pid") == process.get("stage_process_group_id")
        and set(interpreter)
        == {"private_binding_sha256", "stable_profile_id", "stable_profile_sha256"}
        and "registration_receipt_sha256" in payload
        and "expected_process_group_id" not in process
    )


def test_deadline_boot_domain_and_registration_mutations_fail_closed() -> None:
    original = _load_example(SCHEMA_EXAMPLES[1])
    assert _capability_holds_contract(original)
    mutations: list[dict[str, object]] = []
    wrong_deadline = copy.deepcopy(original)
    _object(wrong_deadline["clock"])["campaign_absolute_deadline_ns"] = 7200000000000
    mutations.append(wrong_deadline)
    for missing in ("linux_boot_id_sha256", "clock_domain_digest"):
        mutated = copy.deepcopy(original)
        del _object(mutated["clock"])[missing]
        mutations.append(mutated)
    pre_registration = copy.deepcopy(original)
    del pre_registration["registration_receipt_sha256"]
    mutations.append(pre_registration)
    ambiguous_group = copy.deepcopy(original)
    _object(ambiguous_group["process_identity"])["expected_process_group_id"] = 4100
    mutations.append(ambiguous_group)
    assert all(not _capability_holds_contract(mutated) for mutated in mutations)


def test_registration_precedes_capability_construction_and_release() -> None:
    contract = _read("PHASE9B_INTERNAL_STAGE_CAPABILITY_CONTRACT.md")
    ordered = (
        "stage sends registration to supervisor",
        "supervisor verifies child PID and start time",
        "supervisor constructs InternalStageCapabilityV1 from that registration",
        "supervisor writes immutable acknowledgement",
        "supervisor sends capability + one-shot release token",
        "stage permanently consumes the release",
        "only then may the stage import compute packages",
    )
    positions = [contract.index(phrase) for phrase in ordered]
    assert positions == sorted(positions)


def test_handoff_receipts_are_three_distinct_immutable_objects() -> None:
    payload = _load_example(SCHEMA_EXAMPLES[2])
    assert set(payload) == {
        "a1_handoff_proposal",
        "execution_authorized",
        "stage_a2_admission",
        "supervisor_handoff_verification",
    }
    assert payload["execution_authorized"] is False
    proposal = _object(payload["a1_handoff_proposal"])
    verification = _object(payload["supervisor_handoff_verification"])
    admission = _object(payload["stage_a2_admission"])
    assert proposal["schema_version"] == "nhc-phase9b-a1-handoff-proposal-v1"
    assert verification["schema_version"] == "nhc-phase9b-supervisor-handoff-verification-v1"
    assert admission["schema_version"] == "nhc-phase9b-stage-a2-admission-v1"
    digests = {_sha(item["receipt_sha256"]) for item in (proposal, verification, admission)}
    assert len(digests) == 3
    assert all(item["immutable"] is True for item in (proposal, verification, admission))
    assert verification["proposal_receipt_sha256"] == proposal["receipt_sha256"]
    assert admission["proposal_receipt_sha256"] == proposal["receipt_sha256"]
    assert admission["verification_receipt_sha256"] == verification["receipt_sha256"]
    endpoints = _object(proposal["endpoints"])
    admitted = _object(admission["admitted_endpoints"])
    for name in ("cation", "neutral"):
        endpoint = _object(endpoints[name])
        admitted_endpoint = _object(admitted[name])
        assert admitted_endpoint["xyz_sha256"] == endpoint["a1_output_xyz_sha256"]
        assert admitted_endpoint["xyz_byte_count"] == endpoint["a1_output_xyz_byte_count"]


def test_attempt_and_process_state_ownership_is_disjoint() -> None:
    states = _read("PHASE9B_ATTEMPT_AND_PROCESS_STATE_MACHINES.md")
    assert "not a state file owned by one process" in states
    assert "The supervisor never claims permit validation, permit consumption, or its own" in states
    guardian_section = states.split("## `GuardianLaunchStateV1`")[1].split(
        "## `CampaignRuntimeStateV1`"
    )[0]
    supervisor_section = states.split("## `CampaignRuntimeStateV1`")[1].split("## Stage terminals")[
        0
    ]
    assert "permit_consumed" in guardian_section and "supervisor_spawned" in guardian_section
    assert "a1_running" not in guardian_section
    assert "a1_running" in supervisor_section and "handoff_verifying" in supervisor_section
    assert "PERMIT_CONSUMED" not in supervisor_section


def _closure_fixture() -> tuple[dict[str, dict[str, object]], str]:
    leaves: dict[str, dict[str, object]] = {
        "shared_schema_source": {"files": ("schemas.py",), "depends": (), "digest": "a", "gen": 9},
        "shared_pyscf_core_source": {
            "files": ("core.py",),
            "depends": ("shared_schema_source",),
            "digest": "b",
            "gen": 9,
        },
        "campaign_control_source": {
            "files": ("guardian.py", "supervisor.py"),
            "depends": ("shared_schema_source",),
            "digest": "c",
            "gen": 9,
        },
        "stage_a1_source": {
            "files": ("a1.py",),
            "depends": ("shared_schema_source",),
            "digest": "d",
            "gen": 9,
        },
        "stage_a2_source": {
            "files": ("a2.py",),
            "depends": ("shared_schema_source", "shared_pyscf_core_source"),
            "digest": "e",
            "gen": 9,
        },
    }
    return leaves, "b"


def _closure_dag_valid(leaves: dict[str, dict[str, object]], direct_core_digest: str) -> bool:
    expected = {
        "campaign_control_source",
        "shared_pyscf_core_source",
        "shared_schema_source",
        "stage_a1_source",
        "stage_a2_source",
    }
    if set(leaves) != expected:
        return False
    owners: dict[str, str] = {}
    generations: set[object] = set()
    for leaf, record in leaves.items():
        generations.add(record.get("gen"))
        for file_name in cast(tuple[str, ...], record.get("files", ())):
            if file_name in owners:
                return False
            owners[file_name] = leaf
        if any(dep not in leaves for dep in cast(tuple[str, ...], record.get("depends", ()))):
            return False
    if len(generations) != 1:
        return False
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> bool:
        if name in visiting:
            return False
        if name in visited:
            return True
        visiting.add(name)
        for dependency in cast(tuple[str, ...], leaves[name]["depends"]):
            if not visit(dependency):
                return False
        visiting.remove(name)
        visited.add(name)
        return True

    return all(visit(name) for name in leaves) and (
        direct_core_digest == leaves["shared_pyscf_core_source"]["digest"]
    )


def test_closure_dag_mutations_are_rejected() -> None:
    leaves, direct_core = _closure_fixture()
    assert _closure_dag_valid(leaves, direct_core)
    duplicate = copy.deepcopy(leaves)
    duplicate["stage_a2_source"]["files"] = ("a2.py", "core.py")
    cycle = copy.deepcopy(leaves)
    cycle["shared_schema_source"]["depends"] = ("stage_a1_source",)
    missing = copy.deepcopy(leaves)
    missing["stage_a1_source"]["depends"] = ("missing_source",)
    mixed = copy.deepcopy(leaves)
    mixed["stage_a2_source"]["gen"] = 10
    assert not _closure_dag_valid(duplicate, direct_core)
    assert not _closure_dag_valid(cycle, direct_core)
    assert not _closure_dag_valid(missing, direct_core)
    assert not _closure_dag_valid(mixed, direct_core)
    assert not _closure_dag_valid(leaves, "different-core")


def test_interpreter_public_private_layers_do_not_leak_paths() -> None:
    authority = _read("PHASE9B_SPLIT_PROCESS_AUTHORITY_CHAIN.md")
    permit = _load_example(SCHEMA_EXAMPLES[0])
    capability = _load_example(SCHEMA_EXAMPLES[1])
    assert "InterpreterProfileStableIdentityV1" in authority
    assert "InterpreterProfilePrivateBindingV1" in authority
    assert not _all_keys(permit) & {"absolute_executable", "absolute_prefix", "device", "inode"}
    interpreter = _object(capability["interpreter"])
    assert set(interpreter) == {
        "private_binding_sha256",
        "stable_profile_id",
        "stable_profile_sha256",
    }


def test_campaign_terminal_uses_derived_lifecycle_and_clock_domain() -> None:
    terminal = _load_example(SCHEMA_EXAMPLES[3])
    lifecycle = _object(terminal["attempt_lifecycle"])
    deadline = _object(terminal["deadline"])
    authorization = _object(terminal["authorization"])
    assert lifecycle["derived_from_immutable_receipts"] is True
    assert terminal["guardian_launch_state"] == "acknowledged"
    assert terminal["campaign_runtime_state"] == "route_rejected"
    start = deadline["campaign_monotonic_start_ns"]
    absolute = deadline["campaign_absolute_deadline_ns"]
    assert type(start) is int and type(absolute) is int
    assert absolute - start == 7200 * 1_000_000_000
    assert deadline["clock_type"] == "CLOCK_MONOTONIC"
    assert "linux_boot_id_sha256" in deadline and "clock_domain_digest" in deadline
    assert authorization["execution_authorized"] is False
    assert authorization["label_authorized"] is False
    assert terminal["label"] is None


def test_item_numbering_v9_gates_and_label_boundary_are_consistent() -> None:
    status = (ROOT / "PHASE_STATUS.md").read_text(encoding="utf-8")
    identity = _read("PHASE9B_SPLIT_PROCESS_SOURCE_IDENTITY_PLAN.md")
    for marker in ("9/12", "10/12", "11/12", "12/12"):
        assert marker in status
    assert V8_SHA256 in status and V8_SHA256 in identity
    assert V9_SHA256 in status and V9_SHA256 in identity
    assert "full composite v9" in identity
    assert "10/12 split-process runtime implementation + v9 freeze complete" in status
    assert "high-fidelity label count remains 71" in status
    assert "生产标签持续 71" in (ROOT / "AGENT.md").read_text(encoding="utf-8")

    assignments: list[tuple[Path, bool]] = []
    for path in sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AnnAssign | ast.Assign):
                continue
            names: list[str] = []
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.append(node.target.id)
            elif isinstance(node, ast.Assign):
                names.extend(target.id for target in node.targets if isinstance(target, ast.Name))
            if "EXECUTION_AUTHORIZED" in names:
                assignments.append(
                    (path, isinstance(node.value, ast.Constant) and node.value.value is False)
                )
    assert len(assignments) == 11
    assert all(is_false for _path, is_false in assignments)
