"""Disjoint, acyclic v9 source-closure DAG and composite identity."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from nhc_deprot_ranker.quantum.phase9b_campaign_schemas import canonical_json_bytes, require_sha256

RUNNER_SOURCE_SCHEMA_VERSION_V9: Final = "nhc-two-endpoint-runner-source-v9"
LEAF_ORDER: Final = (
    "shared_schema_source",
    "shared_pyscf_core_source",
    "campaign_control_source",
    "stage_a1_source",
    "stage_a2_source",
)


class SourceClosureError(RuntimeError):
    """A v9 source leaf, dependency edge, or deployment inventory is invalid."""


@dataclass(frozen=True, slots=True)
class SourceLeafDefinition:
    name: str
    files: tuple[str, ...]
    dependencies: tuple[str, ...]
    interpreter_profile_role: str

    def __post_init__(self) -> None:
        if self.name not in LEAF_ORDER:
            raise SourceClosureError("unknown source leaf")
        if (
            not self.files
            or tuple(sorted(self.files)) != self.files
            or len(set(self.files)) != len(self.files)
        ):
            raise SourceClosureError(f"{self.name} files must be non-empty, unique, and sorted")
        if tuple(sorted(self.dependencies)) != self.dependencies or len(
            set(self.dependencies)
        ) != len(self.dependencies):
            raise SourceClosureError(f"{self.name} dependencies must be unique and sorted")


SOURCE_LEAVES: Final = (
    SourceLeafDefinition(
        name="shared_schema_source",
        files=tuple(
            sorted(
                {
                    "nhc_deprot_ranker/quantum/phase9b_campaign_evidence.py",
                    "nhc_deprot_ranker/quantum/phase9b_campaign_schemas.py",
                    "nhc_deprot_ranker/quantum/phase9b_cross_process_handoff.py",
                    "nhc_deprot_ranker/quantum/phase9b_internal_stage_capability.py",
                    "nhc_deprot_ranker/quantum/phase9b_interpreter_profiles.py",
                    "nhc_deprot_ranker/quantum/phase9b_source_identity.py",
                }
            )
        ),
        dependencies=(),
        interpreter_profile_role="control_plane_standard_library",
    ),
    SourceLeafDefinition(
        name="shared_pyscf_core_source",
        files=tuple(
            sorted(
                {
                    "nhc_deprot_ranker/__init__.py",
                    "nhc_deprot_ranker/constants.py",
                    "nhc_deprot_ranker/data/__init__.py",
                    "nhc_deprot_ranker/data/provenance.py",
                    "nhc_deprot_ranker/quantum/__init__.py",
                    "nhc_deprot_ranker/quantum/phase9b_execution.py",
                    "nhc_deprot_ranker/quantum/phase9b_shared_pyscf_core.py",
                    "nhc_deprot_ranker/quantum/two_endpoint.py",
                    "nhc_deprot_ranker/quantum/worker.py",
                }
            )
        ),
        dependencies=("shared_schema_source",),
        interpreter_profile_role="direct_and_a2_gpupyscf",
    ),
    SourceLeafDefinition(
        name="campaign_control_source",
        files=tuple(
            sorted(
                {
                    "nhc_deprot_ranker/quantum/linux_guardian.py",
                    "nhc_deprot_ranker/quantum/one_shot_permit.py",
                    "nhc_deprot_ranker/quantum/phase8b_authority.py",
                    "nhc_deprot_ranker/quantum/phase8b_execution.py",
                    "nhc_deprot_ranker/quantum/phase8b_permit.py",
                    "nhc_deprot_ranker/quantum/phase8b_runtime.py",
                    "nhc_deprot_ranker/quantum/phase9b_authority.py",
                    "nhc_deprot_ranker/quantum/phase9b_campaign_guardian.py",
                    "nhc_deprot_ranker/quantum/phase9b_campaign_supervisor.py",
                    "nhc_deprot_ranker/quantum/phase9b_guardian.py",
                    "nhc_deprot_ranker/quantum/phase9b_permit.py",
                    "nhc_deprot_ranker/quantum/phase9b_resources.py",
                    "nhc_deprot_ranker/quantum/phase9b_supervisor.py",
                    "nhc_deprot_ranker/quantum/process_supervisor.py",
                    "nhc_deprot_ranker/quantum/worker_bootstrap.py",
                }
            )
        ),
        dependencies=("shared_schema_source",),
        interpreter_profile_role="control_plane_standard_library",
    ),
    SourceLeafDefinition(
        name="stage_a1_source",
        files=tuple(
            sorted(
                {
                    "nhc_deprot_ranker/quantum/phase9b_aimnet2_runtime.py",
                    "nhc_deprot_ranker/quantum/phase9b_handoff.py",
                    "nhc_deprot_ranker/quantum/phase9b_stage_a1.py",
                }
            )
        ),
        dependencies=("shared_schema_source",),
        interpreter_profile_role="a1_mlff",
    ),
    SourceLeafDefinition(
        name="stage_a2_source",
        files=("nhc_deprot_ranker/quantum/phase9b_stage_a2.py",),
        dependencies=("shared_pyscf_core_source", "shared_schema_source"),
        interpreter_profile_role="direct_and_a2_gpupyscf",
    ),
)


@dataclass(frozen=True, slots=True)
class SourceLeafIdentity:
    name: str
    files: tuple[tuple[str, str], ...]
    file_list_sha256: str
    source_sha256: str
    dependencies: tuple[tuple[str, str], ...]
    interpreter_profile_role: str
    interpreter_profile_sha256: str

    def payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "files": [{"path": name, "sha256": digest} for name, digest in self.files],
            "file_list_sha256": self.file_list_sha256,
            "source_sha256": self.source_sha256,
            "dependencies": [
                {"leaf": name, "source_sha256": digest} for name, digest in self.dependencies
            ],
            "interpreter_profile_role": self.interpreter_profile_role,
            "interpreter_profile_sha256": self.interpreter_profile_sha256,
        }


@dataclass(frozen=True, slots=True)
class CompositeSourceIdentityV9:
    leaves: tuple[SourceLeafIdentity, ...]
    dependency_edges_sha256: str
    deployment_inventory_sha256: str
    full_assisted_campaign_source_sha256: str

    def payload_without_composite(self) -> dict[str, object]:
        return {
            "schema_version": RUNNER_SOURCE_SCHEMA_VERSION_V9,
            "leaves": [leaf.payload() for leaf in self.leaves],
            "dependency_edges_sha256": self.dependency_edges_sha256,
            "deployment_inventory_sha256": self.deployment_inventory_sha256,
        }

    def payload(self) -> dict[str, object]:
        return {
            **self.payload_without_composite(),
            "full_assisted_campaign_source_sha256": self.full_assisted_campaign_source_sha256,
        }


def validate_source_closure_definitions(
    leaves: tuple[SourceLeafDefinition, ...] = SOURCE_LEAVES,
) -> None:
    if tuple(leaf.name for leaf in leaves) != LEAF_ORDER:
        raise SourceClosureError("source leaf order drifted")
    names = {leaf.name for leaf in leaves}
    owners: dict[str, str] = {}
    for leaf in leaves:
        for file_name in leaf.files:
            previous = owners.setdefault(file_name, leaf.name)
            if previous != leaf.name:
                raise SourceClosureError(
                    f"source file has duplicate leaf ownership: {file_name}: {previous}/{leaf.name}"
                )
        unknown = set(leaf.dependencies) - names
        if unknown:
            raise SourceClosureError(f"{leaf.name} has unknown dependencies: {sorted(unknown)}")
        if leaf.name in leaf.dependencies:
            raise SourceClosureError(f"{leaf.name} depends on itself")

    visiting: set[str] = set()
    visited: set[str] = set()
    by_name = {leaf.name: leaf for leaf in leaves}

    def visit(name: str) -> None:
        if name in visiting:
            raise SourceClosureError("source closure dependency cycle detected")
        if name in visited:
            return
        visiting.add(name)
        for dependency in by_name[name].dependencies:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for name in LEAF_ORDER:
        visit(name)


def _leaf_source_digest(name: str, files: tuple[tuple[str, str], ...]) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "schema_version": RUNNER_SOURCE_SCHEMA_VERSION_V9,
                "leaf": name,
                "files": [{"path": path, "sha256": digest} for path, digest in files],
            }
        )
    ).hexdigest()


def compute_composite_source_identity(
    source_root: Path,
    *,
    interpreter_profile_assignments: Mapping[str, str],
    leaves: tuple[SourceLeafDefinition, ...] = SOURCE_LEAVES,
) -> CompositeSourceIdentityV9:
    """Hash every owned source file, dependency edge, profile, and deployment item."""

    validate_source_closure_definitions(leaves)
    if set(interpreter_profile_assignments) != {
        "control_plane_standard_library",
        "a1_mlff",
        "direct_and_a2_gpupyscf",
    }:
        raise SourceClosureError("interpreter profile assignment set drifted")
    for role, digest in interpreter_profile_assignments.items():
        require_sha256(digest, f"{role} interpreter profile")

    identities: list[SourceLeafIdentity] = []
    digests: dict[str, str] = {}
    deployment: list[dict[str, str]] = []
    for definition in leaves:
        files: list[tuple[str, str]] = []
        for relative in definition.files:
            path = source_root / relative
            if path.is_symlink() or not path.is_file():
                raise SourceClosureError(f"source closure file is absent/non-regular: {relative}")
            content = path.read_bytes()
            if not content:
                raise SourceClosureError(f"source closure file is empty: {relative}")
            digest = hashlib.sha256(content).hexdigest()
            files.append((relative, digest))
            deployment.append({"path": relative, "sha256": digest, "leaf": definition.name})
        file_tuple = tuple(files)
        file_list_digest = hashlib.sha256(
            canonical_json_bytes([{"path": path, "sha256": digest} for path, digest in file_tuple])
        ).hexdigest()
        source_digest = _leaf_source_digest(definition.name, file_tuple)
        dependencies = tuple((name, digests[name]) for name in definition.dependencies)
        profile_digest = interpreter_profile_assignments[definition.interpreter_profile_role]
        identity = SourceLeafIdentity(
            name=definition.name,
            files=file_tuple,
            file_list_sha256=file_list_digest,
            source_sha256=source_digest,
            dependencies=dependencies,
            interpreter_profile_role=definition.interpreter_profile_role,
            interpreter_profile_sha256=profile_digest,
        )
        identities.append(identity)
        digests[definition.name] = source_digest

    edges = [
        {"from": leaf.name, "to": dependency, "to_source_sha256": digests[dependency]}
        for leaf in leaves
        for dependency in leaf.dependencies
    ]
    edges_digest = hashlib.sha256(canonical_json_bytes(edges)).hexdigest()
    deployment_digest = hashlib.sha256(
        canonical_json_bytes(sorted(deployment, key=lambda item: item["path"]))
    ).hexdigest()
    provisional = {
        "schema_version": RUNNER_SOURCE_SCHEMA_VERSION_V9,
        "leaves": [identity.payload() for identity in identities],
        "dependency_edges_sha256": edges_digest,
        "deployment_inventory_sha256": deployment_digest,
    }
    composite = hashlib.sha256(canonical_json_bytes(provisional)).hexdigest()
    return CompositeSourceIdentityV9(
        leaves=tuple(identities),
        dependency_edges_sha256=edges_digest,
        deployment_inventory_sha256=deployment_digest,
        full_assisted_campaign_source_sha256=composite,
    )


def assert_direct_a2_core_parity(identity: CompositeSourceIdentityV9) -> None:
    by_name = {leaf.name: leaf for leaf in identity.leaves}
    shared = by_name["shared_pyscf_core_source"]
    a2 = by_name["stage_a2_source"]
    dependencies = dict(a2.dependencies)
    if dependencies.get("shared_pyscf_core_source") != shared.source_sha256:
        raise SourceClosureError("A2 does not bind the direct shared PySCF core")
    if shared.interpreter_profile_sha256 != a2.interpreter_profile_sha256:
        raise SourceClosureError("direct/shared-core and A2 interpreter profiles differ")


__all__ = [
    "LEAF_ORDER",
    "RUNNER_SOURCE_SCHEMA_VERSION_V9",
    "SOURCE_LEAVES",
    "CompositeSourceIdentityV9",
    "SourceClosureError",
    "SourceLeafDefinition",
    "SourceLeafIdentity",
    "assert_direct_a2_core_parity",
    "compute_composite_source_identity",
    "validate_source_closure_definitions",
]
