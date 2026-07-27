# Phase 9B Split-Process Failure Semantics

> Item 11 audit qualification: the classifications below remain the frozen
> design taxonomy, but not every class has a durable production terminal writer
> in v9. Several guardian/supervisor exceptions exit before campaign terminal
> publication, and A2 maps every shared-core nonzero exit to
> `rejected_cation`. A read-only reader must classify such trees as incomplete
> or indeterminate; it must not infer the intended class. See
> `PHASE9B_ITEM11_EVIDENCE_GAP_REPORT.md`.

Every classification below is terminal for the assisted attempt. Retry,
authority restoration, resume, fallback, output repair, and label are forbidden.

| Classification | Irreversible action | Permit | A1 | A2 allowed | Required evidence | Label |
| --- | --- | --- | --- | --- | --- | --- |
| `failed_before_irreversible_action` | no | ready or absent | no | no | validation failure | no |
| `permit_consumed_supervisor_spawn_failed` | permit consumed | spent | no | no | consumption + spawn failure | no |
| `permit_consumed_ack_failed` | permit consumed, process may exist | spent | unknown | no | consumption + spawn identity + ack failure | no |
| `indeterminate` | possibly | never restored | possible | no new stage | all durable partial evidence | no |
| `a1_spawn_failed` | permit consumed | spent | not started | no | capability + spawn failure | no |
| `a1_timeout` | permit consumed, A1 started | spent | terminated/reaped | no | stage registration, timeout, cleanup | no |
| `a1_process_failed` | A1 started | spent | failed/reaped | no | process terminal + cleanup | no |
| `a1_cation_rejected` | A1 cation ran | spent | rejected | no | cation evidence + A1 terminal | no |
| `a1_neutral_rejected` | both A1 endpoints attempted | spent | rejected | no | both available endpoint records + terminal | no |
| `a1_evidence_failed` | A1 may have computed | spent | not accepted | no | durable partial tree + failure | no |
| `a1_indeterminate` | A1 state unknown | spent | unknown/reaped if provable | no | all obtainable evidence | no |
| `handoff_missing` | A1 accepted claim | spent | accepted/reaped | no | A1 terminal + missing-set receipt | no |
| `handoff_hash_mismatch` | A1 accepted claim | spent | accepted/reaped | no | conflicting hashes and bytes digests | no |
| `handoff_identity_mismatch` | A1 accepted claim | spent | accepted/reaped | no | field comparison receipt | no |
| `handoff_structure_rejected` | A1 completed | spent | not admitted | no | structure comparison | no |
| `handoff_extra_files` | A1 completed | spent | not admitted | no | exact file-set difference | no |
| `handoff_indeterminate` | A1 completed | spent | not admitted | no | partial verification | no |
| `a2_admission_failed` | handoff checked | spent | accepted/reaped | no | admission failure | no |
| `a2_spawn_failed` | admission durable | spent | accepted/reaped | spawn failed | capability + spawn failure | no |
| `a2_timeout` | A2 started | spent | accepted/reaped | already ran | timeout + cleanup | no |
| `a2_cation_rejected` | cation PySCF ran | spent | accepted/reaped | neutral no | cation endpoint + A2 terminal | no |
| `a2_neutral_rejected` | both PySCF endpoints attempted | spent | accepted/reaped | already ran | both available endpoint records | no |
| `a2_d3_failed` | PySCF work ran | spent | accepted/reaped | no further work | D3 failure evidence | no |
| `a2_evidence_failed` | PySCF may have completed | spent | accepted/reaped | no | partial A2 evidence | no |
| `a2_indeterminate` | A2 state unknown | spent | accepted/reaped | no | all obtainable evidence | no |
| `accepted` | all planned actions | spent | accepted/reaped | accepted/reaped | complete evidence manifest | at most one |
| `rejected` | one or more stage actions | spent | terminal | terminal or not run | classified terminal tree | no |
| `no_label` | any incomplete scientific route | spent as applicable | terminal | terminal or not run | route terminal | no |

`ROUTE_ACCEPTED` requires A1 accepted, handoff accepted, A2 accepted, no process
overlap or residual process, complete evidence, both endpoint PySCF results, and
one valid label formula. All scientific rejection classes map to route
`rejected` plus `no_label`; unprovable authority, process, or evidence state maps
to route `indeterminate` plus `no_label`.

A1 accepted / A2 not started, A1 accepted / handoff rejected, A1 accepted / A2
spawn failed, A1 accepted / A2 indeterminate, and A2 cation accepted / neutral
rejected are first-class, Postflight-readable terminal shapes. None is collapsed
into a generic worker failure.
