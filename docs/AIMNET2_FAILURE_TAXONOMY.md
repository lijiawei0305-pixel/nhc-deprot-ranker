# AIMNet2 Failure Taxonomy

## Purpose

Enumerate every way the AIMNet2-assisted pipeline can fail, and fix in advance
what each failure means, what it produces, and what it forbids.

Every class below is **fail-closed**. No class permits a silent fallback, a
retry with different settings, a substituted model, a substituted candidate, or
a downgraded claim that still yields a label.

## Global rules

1. A failed endpoint never produces an endpoint result.
2. A failed endpoint on either side means **no deprotonation label** for that
   candidate. One good endpoint is not half a label.
3. A failure is recorded with its class, its evidence, and its inputs; it is
   never deleted to keep a batch clean.
4. Failed candidates are excluded from success-rate statistics for the stage
   they never legitimately entered, and this exclusion is reported explicitly
   rather than applied silently.
5. No failure class may be resolved by editing the frozen protocol, thresholds,
   resources, or acceptance rules after the fact.

## Class A — asset and identity failures

Detected before any computation.

| Code | Condition |
| --- | --- |
| `A1_package_absent` | `aimnet`, `torch`, or `ase` not importable |
| `A2_weights_absent` | no registered weight file present |
| `A3_weight_hash_unknown` | weight SHA256 cannot be computed |
| `A4_weight_hash_drift` | weight SHA256 differs from the registered value |
| `A5_model_id_drift` | model registry name or version differs from the frozen record |
| `A6_ensemble_incomplete` | the frozen ensemble member list is not fully present |
| `A7_license_unclear` | model license cannot be established |

Forbidden responses: downloading a weight, installing a package, upgrading a
package, substituting another weight, or proceeding with a subset of the frozen
ensemble.

## Class B — chemical domain failures

| Code | Condition |
| --- | --- |
| `B1_unsupported_element` | any element of either endpoint outside declared model coverage |
| `B2_element_set_unknown` | model element coverage cannot be established |
| `B3_endpoint_charge_mismatch` | electron count inconsistent with the declared endpoint charge |
| `B4_endpoint_identity_mismatch` | the endpoint is not the project's closed-shell singlet definition |
| `B5_proton_count_mismatch` | neutral is not exactly one proton fewer than cation |

`B1` is decided per candidate and covers **both** endpoints. A candidate whose
cation is supported and whose neutral is not is a `B1` failure for the whole
candidate.

Forbidden responses: ignoring the element, mapping it to a different element,
silently falling back to MMFF, UFF, or xTB, silently skipping AIMNet2 while
still describing the run as AIMNet2-assisted, or counting the candidate in
AIMNet2 success statistics.

## Class C — numerical failures

| Code | Condition |
| --- | --- |
| `C1_nan_coordinate` | any non-finite coordinate |
| `C2_nan_energy` | non-finite energy |
| `C3_nan_force` | non-finite force component |
| `C4_optimizer_error` | optimizer raised or aborted |
| `C5_not_converged` | `fmax` not reached within the frozen step limit |
| `C6_walltime_exceeded` | frozen AIMNet2 wall-time limit hit |

`C5` deserves emphasis: an unconverged AIMNet2 preoptimization must **not** be
marked successful and must not be handed to PySCF. The preoptimizer exists to
supply a better starting structure; an unconverged one has not demonstrated
that it did.

## Class D — structural integrity failures

| Code | Condition |
| --- | --- |
| `D1_atom_count_changed` | atom count differs before and after |
| `D2_element_order_changed` | element sequence differs |
| `D3_atom_mapping_broken` | C2/N1/N3 mapping no longer valid |
| `D4_atom_overlap` | non-physical interatomic distance |
| `D5_dissociation` | fragment separated beyond the frozen threshold |
| `D6_bond_broken` | a bond present in the initial graph is absent |
| `D7_bond_formed` | a bond absent in the initial graph is present |
| `D8_proton_migration` | the target proton moved to a different heavy atom |
| `D9_ring_skeleton_changed` | NHC five-membered ring connectivity altered |

Class D distinguishes **allowed geometric relaxation** from **changed reaction
identity**. That distinction cannot rest on a single distance cutoff. It is
decided by comparing the initial molecular graph, covalent-radius-based
candidate connectivity, the atom mapping, the key-bond list, and proton
identity together, as specified in `docs/AIMNET2_STRUCTURE_VALIDATION.md`.

`D8` is the failure this pipeline most needs to catch. A preoptimizer that
relocates the acidic proton silently converts the cation endpoint into a
different molecule, and the resulting label would be a well-formed number for
the wrong reaction.

## Class E — handoff failures

| Code | Condition |
| --- | --- |
| `E1_hash_mismatch` | PySCF input hash does not close against AIMNet2 output hash |
| `E2_unregistered_intervention` | any unlogged geometry edit between the stages |
| `E3_charge_not_propagated` | endpoint charge not carried into the PySCF stage |
| `E4_atom_order_not_propagated` | atom order not preserved across the boundary |
| `E5_missing_parent_link` | result lacks its `parent_aimnet2_task_id` |

`E2` explicitly covers re-running MMFF, UFF, or xTB, or hand-editing
coordinates, between the two stages. Any such step must be a registered,
hashed pipeline stage or it is a failure.

## Class F — PySCF stage failures

| Code | Condition |
| --- | --- |
| `F1_scf_not_converged` | final SCF did not explicitly converge |
| `F2_geometry_not_converged` | geomeTRIC did not explicitly converge |
| `F3_d3_not_verified` | D3(BJ) activity not dynamically demonstrated |
| `F4_walltime_exceeded` | frozen request deadline hit |
| `F5_backend_error` | unclassified backend exception |
| `F6_energy_not_finite` | final electronic energy not finite |

Forbidden responses: registering an unconverged structure as an endpoint,
silently relaxing convergence criteria, silently raising `maxsteps`, silently
changing the SCF algorithm, silently restarting, or skipping gradient
acceptance because AIMNet2 already converged.

## Class G — provenance and authority failures

| Code | Condition |
| --- | --- |
| `G1_protocol_identity_drift` | any frozen protocol field differs from its record |
| `G2_optimizer_settings_absent` | optimizer settings not part of protocol identity |
| `G3_retired_authority_reuse` | any attempt to reuse the Phase 8B QXH chain |
| `G4_permit_absent` | no valid one-shot permit for the attempt |
| `G5_execution_gate_closed` | source execution gate not open for an authorized run |
| `G6_route_config_mismatch` | Route D and Route A PySCF configurations differ |

`G3` is absolute. The Phase 8B candidate, request, attempt, permit, bundle, and
remote root are permanently unusable, and no Phase 9 artifact may reference
them as authority.

`G6` protects the entire comparison: if the two routes do not share identical
PySCF settings and resources, any measured speedup is uninterpretable.

## Reporting requirement

Every failure is reported with its class code, the stage at which it was
detected, and whether it occurred before or after any irreversible action.
Aggregate reporting must never present a failed candidate as absent from the
run. A batch report that shows only successes is incomplete by definition.
