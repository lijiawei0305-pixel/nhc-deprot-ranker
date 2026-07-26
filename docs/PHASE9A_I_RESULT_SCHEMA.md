# Phase 9A-I Result Schema

## Per-call record

One record per evaluation, six in total:

```text
endpoint                    cation | neutral
repeat_index                1 | 2 | 3
process_index               which clean process produced it
input_xyz_sha256
atom_order_sha256
atom_count
charge
multiplicity
model_weight_sha256
model_identity
implemented_species
device_identity
gpu_index
dtype
energy_value
energy_unit
forces_shape
forces_dtype
forces_unit
forces_all_finite
max_abs_force_component
max_atomic_force_norm
coordinates_unchanged
walltime_seconds
cuda_memory_allocated
cuda_memory_reserved
warnings
exceptions
```

Every record carries its full identity — input hash, weight hash, charge,
device. A record that cannot state which weight and which input produced it is
not evidence, and later aggregation must never have to infer it.

## Per-call assertions

```text
energy is a finite scalar
forces shape == (N, 3)
all force components finite
atom count matches the input
atom order matches the input
input coordinates identical before and after the call
energy unit is eV
forces unit is eV/A
charge and multiplicity as constructed
```

`coordinates_unchanged` is checked by rehashing the coordinate array after the
call. This phase performs no optimization, so any coordinate change means the
calculator mutated its input — which would silently invalidate the repeat
comparison and every downstream assumption about frozen geometry.

## Aggregate record

```text
candidate_inchikey
request_id
attempt_id
isolated_root_file_inventory
global_cache_unchanged
model_weight_unchanged
environment_unchanged
download_detected
cation_energy_spread
cation_max_force_component_spread
neutral_energy_spread
neutral_max_force_component_spread
tolerances_preregistered
determinism_pass
element_coverage_pass
unsupported_elements_other_candidates
```

Spreads are reported per endpoint and never pooled.

## Interpretation constraints

**Do not compare cation and neutral energies to judge stability.** The two
endpoints have different atomic composition — the cation has one more proton —
so their absolute energies are not comparable on any common reference. A
difference between them is not a deprotonation energy and must not be presented,
plotted, or stored as one.

The only legitimate deprotonation energy in this project comes from PySCF
B3LYP-D3(BJ)/def2-SVP endpoint energies through the frozen formula. No AIMNet2
number may enter it.

**No label field exists in this schema.** There is no
`dft_deprot_electronic_kcal`, no `electronic_difference_kcal`, and no field that
could be mistaken for one. The omission is deliberate: a schema without a label
slot cannot accidentally acquire a label.

## Privacy

Tracked evidence carries versions, hashes, units, shapes, capability booleans,
spreads, and pass/fail. It does not carry absolute paths, hostnames, account
names, IP addresses, PIDs, raw logs, credentials, or **molecular coordinates**.

Energies and forces are aggregate scalars and summary extrema, not per-atom
coordinate data, so they may be recorded.

## Status vocabulary

```text
status            passed | failed | blocked
failure_class     from docs/AIMNET2_FAILURE_TAXONOMY.md
```

`blocked` covers a run that could not legitimately start — absent weight, failed
isolation, no free GPU. A blocked run is a valid outcome that has established a
fact, and is never reported as a failure of the design or converted into a
partial pass.
