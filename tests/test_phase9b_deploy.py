"""Phase 9B deployment regressions.

No chemistry, no server, no compute. SSH, the filesystem, and remote hashing are
all driven through injected fakes and tmp_path, so nothing here reaches a network.
Every enumerated failure mode is exercised.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from nhc_deprot_ranker.preparation import phase9b_deploy as dp
from nhc_deprot_ranker.preparation.phase9b_deploy import (
    DeployState,
    Phase9BDeployError,
    Phase9BDeployNotAuthorizedError,
    RoutePlan,
    build_route_plan,
    deploy_both_routes,
    validate_absolute_root,
    validate_relative_member,
    verify_local_payload,
    verify_remote_evidence,
)
from nhc_deprot_ranker.quantum.phase9b_permit import ROUTE_ASSISTED, ROUTE_DIRECT

_PROJECT = "/srv/project"
_MEMBERS = ("input/request.json", "xyz/cation.xyz", "xyz/neutral.xyz")


def _write_bundle(root: Path, *, extra: str | None = None) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for index, member in enumerate(_MEMBERS):
        path = root / member
        path.parent.mkdir(parents=True, exist_ok=True)
        body = f"payload-{index}\n".encode()
        path.write_bytes(body)
        hashes[member] = hashlib.sha256(body).hexdigest()
    if extra is not None:
        stray = root / extra
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_bytes(b"stray\n")
    return hashes


def _plan(route: str, tmp_path: Path, *, attempt: str = "attempt-phase9b-lbnp") -> RoutePlan:
    bundle = tmp_path / route
    bundle.mkdir(parents=True, exist_ok=True)
    files = _write_bundle(bundle)
    return build_route_plan(
        route=route, project_root=_PROJECT, attempt_id=f"{attempt}-{route}", files=files
    )


def _plans(tmp_path: Path) -> tuple[RoutePlan, RoutePlan]:
    return _plan(ROUTE_DIRECT, tmp_path), _plan(ROUTE_ASSISTED, tmp_path)


def _bundles(tmp_path: Path) -> dict[str, Path]:
    return {ROUTE_DIRECT: tmp_path / ROUTE_DIRECT, ROUTE_ASSISTED: tmp_path / ROUTE_ASSISTED}


class _FakeRemote:
    """Simulates the receiver and promoter without a network or a shell."""

    def __init__(
        self,
        *,
        existing_final: set[str] | None = None,
        existing_staging: set[str] | None = None,
        corrupt_hash_for: str | None = None,
        extra_present: str | None = None,
        drop_member: str | None = None,
        upload_code: int = 0,
        upload_stderr: bytes = b"",
        promote_code: int = 0,
        promote_stderr: bytes = b"",
        raise_on_call: int | None = None,
        fail_route: str | None = None,
        truncate_after: int | None = None,
    ) -> None:
        self.existing_final = existing_final or set()
        self.existing_staging = existing_staging or set()
        self.corrupt_hash_for = corrupt_hash_for
        self.extra_present = extra_present
        self.drop_member = drop_member
        self.upload_code = upload_code
        self.upload_stderr = upload_stderr
        self.promote_code = promote_code
        self.promote_stderr = promote_stderr
        self.raise_on_call = raise_on_call
        self.fail_route = fail_route
        self.truncate_after = truncate_after
        self.calls: list[Sequence[str]] = []
        self.streams: list[bytes] = []
        self.promoted: list[str] = []

    def __call__(
        self, command: Sequence[str], *, stdin: bytes, timeout: float
    ) -> tuple[int, bytes, bytes]:
        del timeout
        self.calls.append(command)
        if self.raise_on_call is not None and len(self.calls) == self.raise_on_call:
            raise OSError("connection reset by peer")
        remote = command[-1]
        if dp.REMOTE_PROMOTER_SOURCE in remote:
            if self.promote_code != 0 or self.promote_stderr:
                return self.promote_code or 1, b"", self.promote_stderr or b"rename failed"
            pairs = json.loads(remote.rsplit(" ", 1)[-1].strip("'"))
            self.promoted = [final for _, final in pairs]
            return 0, json.dumps({"promoted": self.promoted}, sort_keys=True).encode(), b""

        self.streams.append(stdin)
        header_len = int.from_bytes(stdin[:8], "big")
        header = json.loads(stdin[8 : 8 + header_len].decode())
        route = header["route"]
        if self.fail_route == route:
            return 1, b"", b"synthetic route failure"
        if header["staging_root"] in self.existing_staging:
            return 1, b"", b"staging root already exists"
        if header["final_root"] in self.existing_final:
            return 1, b"", b"final root already exists"
        if self.upload_code != 0 or self.upload_stderr:
            return self.upload_code or 1, b"", self.upload_stderr or b"upload failed"

        written: dict[str, Any] = {}
        for member, entry in header["files"].items():
            digest = entry["sha256"]
            if self.corrupt_hash_for == member:
                digest = "0" * 64
            written[member] = {
                "sha256": digest,
                "bytes": entry["bytes"],
                "regular": True,
            }
        if self.drop_member and self.drop_member in written:
            del written[self.drop_member]
        present = sorted(written)
        if self.truncate_after is not None:
            present = present[: self.truncate_after]
        if self.extra_present:
            present = sorted([*present, self.extra_present])
        payload = {
            "schema_version": dp.DEPLOY_EVIDENCE_SCHEMA_VERSION,
            "route": route,
            "attempt_id": header["attempt_id"],
            "staging_root": header["staging_root"],
            "written": written,
            "present": present,
            "promoted": False,
        }
        return 0, json.dumps(payload, sort_keys=True).encode(), b""


def _deploy(tmp_path: Path, remote: _FakeRemote, **kw: Any) -> dp.DeploymentOutcome:
    direct, assisted = _plans(tmp_path)
    params: dict[str, Any] = {
        "ssh_alias": "host",
        "plans": (direct, assisted),
        "bundle_dirs": _bundles(tmp_path),
        "run_command": remote,
    }
    params.update(kw)
    return deploy_both_routes(**params)


# --- gate and closure -------------------------------------------------------


def test_source_gate_is_closed_and_a_real_deploy_refuses(tmp_path: Path) -> None:
    assert dp.EXECUTION_AUTHORIZED is False
    source = Path(dp.__file__).read_text(encoding="utf-8")
    assert "EXECUTION_AUTHORIZED: Final[bool] = False" in source
    direct, assisted = _plans(tmp_path)
    with pytest.raises(Phase9BDeployNotAuthorizedError, match="not authorized"):
        deploy_both_routes(
            ssh_alias="host", plans=(direct, assisted), bundle_dirs=_bundles(tmp_path)
        )


def test_module_is_control_plane_not_runner_source() -> None:
    """It must not be able to change runner_source_sha256."""

    from nhc_deprot_ranker.quantum import two_endpoint

    closure = two_endpoint._RUNNER_SOURCE_RELATIVE_PATHS  # pyright: ignore[reportPrivateUsage]
    assert not any("phase9b_deploy" in member for member in closure)
    assert not any("preparation" in member for member in closure)


def test_module_never_launches_or_touches_compute() -> None:
    import ast

    tree = ast.parse(Path(dp.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for forbidden in ("torch", "aimnet", "ase", "pyscf", "rdkit"):
        assert forbidden not in imported, forbidden

    source = Path(dp.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "run_phase9b_supervisor",
        "run_phase8b_supervisor",
        "_issue_guarded_compute_capability",
        "load_consumed_phase9b_permit",
        "build_production_optimizer",
        "phase9b_launch",
        "kcal",
        "627.509474",
    ):
        assert forbidden not in source, forbidden


def test_module_never_rebuilds_a_manifest() -> None:
    source = Path(dp.__file__).read_text(encoding="utf-8")
    for forbidden in ("build_route_payload", "build_route_request", "render_phase9b_permit"):
        assert forbidden not in source, forbidden


# --- path validation --------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "../escape",
        "/absolute",
        "a/../b",
        "a//b",
        "./a",
        "a\\b",
        "a b",
        "a$b",
        "a;rm -rf /",
        "a`id`",
        "a*b",
        "a\nb",
    ],
)
def test_relative_member_rejects_traversal_and_shell_surface(bad: str) -> None:
    with pytest.raises(Phase9BDeployError):
        validate_relative_member(bad, label="member")


@pytest.mark.parametrize(
    "bad",
    ["relative/path", "/a/../b", "/a b", "/a$b", "/a;id", "/a|b"],
)
def test_absolute_root_rejects_traversal_and_shell_surface(bad: str) -> None:
    with pytest.raises(Phase9BDeployError):
        validate_absolute_root(bad, label="root")


def test_retired_phase8b_artifacts_cannot_be_targeted() -> None:
    for retired in (
        "/srv/data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001",
        "/srv/QXHIEGFUWOLQIJ",
        "/srv/phase8b/root",
    ):
        with pytest.raises(Phase9BDeployError, match="retired Phase 8B artifact"):
            validate_absolute_root(retired, label="root")


def test_retired_attempt_id_is_refused(tmp_path: Path) -> None:
    bundle = tmp_path / "b"
    bundle.mkdir()
    files = _write_bundle(bundle)
    with pytest.raises(Phase9BDeployError, match="retired chain"):
        build_route_plan(
            route=ROUTE_DIRECT,
            project_root=_PROJECT,
            attempt_id="attempt-phase8b-qxh-v001",
            files=files,
        )


def test_plan_roots_are_attempt_unique_and_distinct(tmp_path: Path) -> None:
    direct, assisted = _plans(tmp_path)
    assert direct.staging_root != direct.final_root
    assert direct.staging_root != assisted.staging_root
    assert direct.final_root != assisted.final_root
    for plan in (direct, assisted):
        assert plan.attempt_id in plan.staging_root, "staging root is namespaced by attempt"


# --- local verification -----------------------------------------------------


def test_local_hash_drift_fails_closed(tmp_path: Path) -> None:
    plan = _plan(ROUTE_DIRECT, tmp_path)
    (tmp_path / ROUTE_DIRECT / _MEMBERS[0]).write_bytes(b"tampered\n")
    with pytest.raises(Phase9BDeployError, match="local file hash drifted"):
        verify_local_payload(plan, bundle_dir=tmp_path / ROUTE_DIRECT)


def test_missing_registered_file_fails_closed(tmp_path: Path) -> None:
    plan = _plan(ROUTE_DIRECT, tmp_path)
    (tmp_path / ROUTE_DIRECT / _MEMBERS[1]).unlink()
    with pytest.raises(Phase9BDeployError, match="registered file is missing"):
        verify_local_payload(plan, bundle_dir=tmp_path / ROUTE_DIRECT)


def test_unregistered_extra_file_fails_closed(tmp_path: Path) -> None:
    """No directory-level sync: an unregistered file is a hard stop."""

    plan = _plan(ROUTE_DIRECT, tmp_path)
    (tmp_path / ROUTE_DIRECT / "xyz" / "stray.xyz").write_bytes(b"stray\n")
    with pytest.raises(Phase9BDeployError, match="unregistered file"):
        verify_local_payload(plan, bundle_dir=tmp_path / ROUTE_DIRECT)


def test_symlinked_member_fails_closed(tmp_path: Path) -> None:
    plan = _plan(ROUTE_DIRECT, tmp_path)
    target = tmp_path / ROUTE_DIRECT / _MEMBERS[2]
    target.unlink()
    target.symlink_to(tmp_path / ROUTE_DIRECT / _MEMBERS[1])
    with pytest.raises(Phase9BDeployError, match=r"not a regular file|symlink"):
        verify_local_payload(plan, bundle_dir=tmp_path / ROUTE_DIRECT)


def test_symlinked_parent_directory_fails_closed(tmp_path: Path) -> None:
    bundle = tmp_path / "linked"
    bundle.mkdir()
    files = _write_bundle(bundle)
    plan = build_route_plan(
        route=ROUTE_DIRECT, project_root=_PROJECT, attempt_id="a-direct", files=files
    )
    real = bundle / "xyz"
    real.rename(bundle / "xyz_real")
    (bundle / "xyz").symlink_to(bundle / "xyz_real")
    with pytest.raises(Phase9BDeployError, match="symlink"):
        verify_local_payload(plan, bundle_dir=bundle)


# --- remote verification ----------------------------------------------------


def test_remote_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    outcome = _deploy(tmp_path, _FakeRemote(corrupt_hash_for=_MEMBERS[0]))
    assert outcome.state is DeployState.FAILED
    assert "remote hash differs" in (outcome.failure_reason or "")


def test_remote_extra_file_fails_closed(tmp_path: Path) -> None:
    outcome = _deploy(tmp_path, _FakeRemote(extra_present="xyz/unexpected.xyz"))
    assert outcome.state is DeployState.FAILED
    assert "extra or missing file" in (outcome.failure_reason or "")


def test_remote_missing_file_fails_closed(tmp_path: Path) -> None:
    outcome = _deploy(tmp_path, _FakeRemote(drop_member=_MEMBERS[1]))
    assert outcome.state is DeployState.FAILED
    assert "differs from the registered set" in (outcome.failure_reason or "")


def test_partial_upload_fails_closed(tmp_path: Path) -> None:
    outcome = _deploy(tmp_path, _FakeRemote(truncate_after=1))
    assert outcome.state is DeployState.FAILED
    assert "extra or missing file" in (outcome.failure_reason or "")


def test_existing_final_root_fails_closed(tmp_path: Path) -> None:
    direct, _ = _plans(tmp_path)
    outcome = _deploy(tmp_path, _FakeRemote(existing_final={direct.final_root}))
    assert outcome.state is DeployState.FAILED
    assert "final root already exists" in (outcome.failure_reason or "")


def test_existing_staging_root_fails_closed(tmp_path: Path) -> None:
    direct, _ = _plans(tmp_path)
    outcome = _deploy(tmp_path, _FakeRemote(existing_staging={direct.staging_root}))
    assert outcome.state is DeployState.FAILED
    assert "staging root already exists" in (outcome.failure_reason or "")


def test_evidence_claiming_promotion_at_upload_is_refused(tmp_path: Path) -> None:
    plan = _plan(ROUTE_DIRECT, tmp_path)
    sizes = verify_local_payload(plan, bundle_dir=tmp_path / ROUTE_DIRECT)
    payload = {
        "schema_version": dp.DEPLOY_EVIDENCE_SCHEMA_VERSION,
        "route": plan.route,
        "attempt_id": plan.attempt_id,
        "staging_root": plan.staging_root,
        "written": {
            m: {"sha256": h, "bytes": sizes[m], "regular": True} for m, h in plan.files.items()
        },
        "present": sorted(plan.files),
        "promoted": True,
    }
    with pytest.raises(Phase9BDeployError, match="must not promote"):
        verify_remote_evidence(json.dumps(payload, sort_keys=True).encode(), plan=plan, sizes=sizes)


def test_non_regular_remote_file_fails_closed(tmp_path: Path) -> None:
    plan = _plan(ROUTE_DIRECT, tmp_path)
    sizes = verify_local_payload(plan, bundle_dir=tmp_path / ROUTE_DIRECT)
    written = {m: {"sha256": h, "bytes": sizes[m], "regular": True} for m, h in plan.files.items()}
    written[_MEMBERS[0]]["regular"] = False
    payload = {
        "schema_version": dp.DEPLOY_EVIDENCE_SCHEMA_VERSION,
        "route": plan.route,
        "attempt_id": plan.attempt_id,
        "staging_root": plan.staging_root,
        "written": written,
        "present": sorted(plan.files),
        "promoted": False,
    }
    with pytest.raises(Phase9BDeployError, match="not a regular file"):
        verify_remote_evidence(json.dumps(payload, sort_keys=True).encode(), plan=plan, sizes=sizes)


def test_wrong_host_identity_in_evidence_fails_closed(tmp_path: Path) -> None:
    """Evidence bound to another attempt or staging root is refused."""

    plan = _plan(ROUTE_DIRECT, tmp_path)
    sizes = verify_local_payload(plan, bundle_dir=tmp_path / ROUTE_DIRECT)
    payload = {
        "schema_version": dp.DEPLOY_EVIDENCE_SCHEMA_VERSION,
        "route": plan.route,
        "attempt_id": "attempt-somewhere-else",
        "staging_root": plan.staging_root,
        "written": {
            m: {"sha256": h, "bytes": sizes[m], "regular": True} for m, h in plan.files.items()
        },
        "present": sorted(plan.files),
        "promoted": False,
    }
    with pytest.raises(Phase9BDeployError, match="identity drifted"):
        verify_remote_evidence(json.dumps(payload, sort_keys=True).encode(), plan=plan, sizes=sizes)


# --- transaction semantics --------------------------------------------------


def test_both_routes_deploy_as_one_transaction(tmp_path: Path) -> None:
    remote = _FakeRemote()
    outcome = _deploy(tmp_path, remote)
    assert outcome.state is DeployState.PROMOTED
    assert outcome.promoted_routes == (ROUTE_ASSISTED, ROUTE_DIRECT)
    assert outcome.ssh_invocations == 3, "two uploads plus one promotion"
    assert len(remote.promoted) == 2


def test_one_route_failing_blocks_the_whole_transaction(tmp_path: Path) -> None:
    """A single successful upload is never grounds for launchability."""

    remote = _FakeRemote(fail_route=ROUTE_ASSISTED)
    outcome = _deploy(tmp_path, remote)
    assert outcome.state is DeployState.FAILED
    assert outcome.promoted_routes == ()
    assert remote.promoted == [], "nothing may be promoted"
    assert outcome.failure_roots, "the failure must name the root it touched"


def test_nothing_is_promoted_before_both_routes_verify(tmp_path: Path) -> None:
    remote = _FakeRemote(corrupt_hash_for=_MEMBERS[0])
    outcome = _deploy(tmp_path, remote)
    assert outcome.state is DeployState.FAILED
    assert remote.promoted == []
    promote_calls = [c for c in remote.calls if dp.REMOTE_PROMOTER_SOURCE in c[-1]]
    assert promote_calls == [], "promotion must not be attempted"


def test_promotion_failure_names_every_root_it_may_have_touched(tmp_path: Path) -> None:
    """Two renames cannot be one atomic step, so a partial state is named."""

    outcome = _deploy(tmp_path, _FakeRemote(promote_code=1))
    assert outcome.state is DeployState.FAILED
    assert "may be partial" in (outcome.failure_reason or "")
    assert len(outcome.failure_roots) == 4, "both staging and both final roots"


def test_network_interruption_fails_closed_without_retry(tmp_path: Path) -> None:
    remote = _FakeRemote(raise_on_call=2)
    outcome = _deploy(tmp_path, remote)
    assert outcome.state is DeployState.FAILED
    assert "transport failed" in (outcome.failure_reason or "")
    assert len(remote.calls) == 2, "no automatic retry"


def test_transaction_requires_exactly_both_routes(tmp_path: Path) -> None:
    direct, _ = _plans(tmp_path)
    with pytest.raises(Phase9BDeployError, match="exactly both routes"):
        deploy_both_routes(
            ssh_alias="host",
            plans=(direct,),
            bundle_dirs=_bundles(tmp_path),
            run_command=_FakeRemote(),
        )
    with pytest.raises(Phase9BDeployError, match="exactly both routes"):
        deploy_both_routes(
            ssh_alias="host",
            plans=(direct, direct),
            bundle_dirs=_bundles(tmp_path),
            run_command=_FakeRemote(),
        )


def test_nonzero_exit_and_unexpected_stderr_fail_closed(tmp_path: Path) -> None:
    assert _deploy(tmp_path, _FakeRemote(upload_code=7)).state is DeployState.FAILED
    outcome = _deploy(tmp_path, _FakeRemote(upload_stderr=b"warn"))
    assert outcome.state is DeployState.FAILED


# --- command construction ---------------------------------------------------


def test_upload_and_promote_commands_carry_no_delete_or_overwrite(tmp_path: Path) -> None:
    direct, assisted = _plans(tmp_path)
    upload = dp.build_upload_command(ssh_alias="host", plan=direct)
    promote = dp.build_promote_command(ssh_alias="host", plans=(direct, assisted))
    for command in (upload, promote):
        joined = " ".join(command)
        for forbidden in ("rsync", "--delete", "scp", "sftp", " rm ", "rmtree", "unlink"):
            assert forbidden not in joined, forbidden
        assert command[0] == "ssh"
        assert "BatchMode=yes" in command


def test_receiver_uses_exclusive_create_and_never_follows_symlinks() -> None:
    source = dp.REMOTE_RECEIVER_SOURCE
    assert "O_EXCL" in source
    assert "O_NOFOLLOW" in source
    assert "exist_ok=False" in source
    for forbidden in ("shutil.rmtree", "os.remove", "os.unlink", "--delete", "shell=True"):
        assert forbidden not in source, forbidden


def test_receiver_refuses_preexisting_roots_and_trailing_bytes() -> None:
    source = dp.REMOTE_RECEIVER_SOURCE
    assert "staging root already exists" in source
    assert "final root already exists" in source
    assert "trailing bytes" in source


def test_promoter_refuses_an_existing_final_root() -> None:
    assert "final root already exists" in dp.REMOTE_PROMOTER_SOURCE
    for forbidden in ("os.remove", "shutil.rmtree", "os.unlink"):
        assert forbidden not in dp.REMOTE_PROMOTER_SOURCE, forbidden


def test_stream_is_deterministic_and_length_prefixed(tmp_path: Path) -> None:
    plan = _plan(ROUTE_DIRECT, tmp_path)
    sizes = verify_local_payload(plan, bundle_dir=tmp_path / ROUTE_DIRECT)
    first = dp.build_deploy_stream(plan, bundle_dir=tmp_path / ROUTE_DIRECT, sizes=sizes)
    second = dp.build_deploy_stream(plan, bundle_dir=tmp_path / ROUTE_DIRECT, sizes=sizes)
    assert first == second
    header_len = int.from_bytes(first[:8], "big")
    header = json.loads(first[8 : 8 + header_len].decode())
    assert set(header["files"]) == set(plan.files)
    assert "promoted" not in header, "the stream header never asserts promotion"
    assert header["staging_root"] != header["final_root"]


def test_out_of_range_timeout_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timeout must be in"):
        _deploy(tmp_path, _FakeRemote(), timeout_seconds=99_999.0)


def test_missing_bundle_directory_for_a_route_fails_closed(tmp_path: Path) -> None:
    direct, assisted = _plans(tmp_path)
    outcome = deploy_both_routes(
        ssh_alias="host",
        plans=(direct, assisted),
        bundle_dirs={ROUTE_DIRECT: tmp_path / ROUTE_DIRECT},
        run_command=_FakeRemote(),
    )
    assert outcome.state is DeployState.FAILED
    assert "no bundle directory" in (outcome.failure_reason or "")


def test_outcome_always_reports_both_root_sets(tmp_path: Path) -> None:
    for remote in (_FakeRemote(), _FakeRemote(fail_route=ROUTE_DIRECT)):
        outcome = _deploy(tmp_path, remote)
        assert set(outcome.staging_roots) == {ROUTE_DIRECT, ROUTE_ASSISTED}
        assert set(outcome.final_roots) == {ROUTE_DIRECT, ROUTE_ASSISTED}
