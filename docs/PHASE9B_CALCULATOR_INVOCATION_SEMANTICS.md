# Phase 9B Calculator Invocation Semantics

## Registered gap

```text
PHASE9B_CALCULATOR_INVOCATION_SEMANTICS_GAP
```

Phase 9B-U1 established that the current production property-access sequence
does not match the prose which describes energy and forces as one calculator
invocation. The production sequence is, for each endpoint:

```text
fresh ASE Atoms
bind one endpoint-specific AIMNet2ASE wrapper
atoms.get_potential_energy()
atoms.get_forces()
```

U1 observed one entry to `AIMNet2ASE.calculate()` for each property read: two
per endpoint and four across cation then neutral. U1 had preregistered two total
calculator invocations and therefore remained `failed_incomplete_environment`;
this later clarification does not validate or reinterpret U1.

## Three non-interchangeable counters

An `ase_property_read` is one call to either
`atoms.get_potential_energy()` or `atoms.get_forces()`.

An `aimnet2ase_calculate_call` is one observed entry to
`AIMNet2ASE.calculate(...)`. A counting subclass records this at the real
calculator boundary. The public field `calculator_invocations` means only this
counter.

A `base_model_forward_call` is an invocation of the lower-level AIMNet2 model.
U2 has no instrumentation at that boundary, so its only honest value is:

```text
base_model_forward_calls = unmeasured
```

Property reads, calculator calls, base-model loads, endpoint-wrapper
constructions, and base-model forwards are separate ledgers. None may be
renamed or substituted for another.

## U2 frozen metrology contract

Endpoint order is `cation`, then `neutral`. For each endpoint U2 creates fresh
Atoms, binds a distinct wrapper, reads energy first and forces second, then
checks finite energy, finite `(N, 3)` forces, and unchanged coordinates.

```text
per endpoint
  energy_property_reads       1
  force_property_reads        1
  total_property_reads        2
  energy_calculate_calls      1
  force_calculate_calls       1
  total_calculate_calls       2

both endpoints
  energy_property_reads       2
  force_property_reads        2
  total_property_reads        4
  energy_calculate_calls      2
  force_calculate_calls       2
  total_calculate_calls       4

base_model_load_count         1
endpoint_wrapper_count        2
base_model_forward_calls      unmeasured
geometry_optimization_steps   0
pyscf_kernel_calls            0
pyscf_gradient_calls          0
labels                        0
```

Counts 2, 3, and 5 are specifically rejected as total calculate-call results;
the accepted value is exactly 4, not an open interval. U2 does not combine the
two properties into an explicit `calculate(properties=[...])` call, read only
forces and obtain energy from `results`, change the property order, modify the
production runtime, modify `AIMNet2ASE`, or alter calculator caching.

## Deferred integration work

U2 is environment validation only. It does not edit the runner source. The
subsequent Unified Environment Identity Integration must align the runner
source comments, receipt-field description, and relevant tests with these
terms while binding the validated interpreter into resources, requests, and
permits. That edit necessarily moves `runner_source_sha256`; it must be a
visible source-v9 rebaseline, never a silent v8 correction.
