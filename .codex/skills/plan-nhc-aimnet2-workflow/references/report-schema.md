# Report Contract

## Mode and status

Return exactly one top-level status after enough evidence exists to classify the
request:

```text
complete_plan | performance_plan:
  PLAN_READY | PLAN_BLOCKED | INCONCLUSIVE
stage_audit | performance_audit:
  AUDIT_PASS | AUDIT_FAIL | INCONCLUSIVE
progress:
  HEALTHY | WARNING | CRITICAL | TERMINAL | INCONCLUSIVE
```

Apply status precedence as follows:

1. Use `INCONCLUSIVE` when a required identity, threshold, or primary evidence
   item is missing or conflicting and no failure can be proved.
2. For an audit, a proved mandatory-gate violation is `AUDIT_FAIL`; use
   `AUDIT_PASS` only when every applicable mandatory gate passes.
3. For a plan, a known prerequisite or unresolved user decision that prevents
   an actionable frozen plan is `PLAN_BLOCKED`; conflicting evidence remains
   `INCONCLUSIVE`. Use `PLAN_READY` only when the plan itself is complete. It
   never authorizes execution.
4. For progress, a proved identity, integrity, manifest, or scientific failure
   is `CRITICAL`. Use `TERMINAL` only when structured terminal closure is
   verified; a claimed terminal with invalid closure evidence is `CRITICAL`.
   Otherwise prefer `WARNING` over `HEALTHY` whenever a frozen resource,
   deadline, or evidence-closure risk exists.

Do not assign a report status during a clarification-only turn. Do not present
passing counts as overall success while a mandatory gate remains open.

## Common report fields

Formal Markdown and archived JSON reports carry these semantic fields. Keep
every field in archived JSON and use `not_applicable` when the mode does not use it:

```text
schema
mode
status
timestamp
git_identity
worktree_state
scope
assumptions
inputs_and_sha256
candidate_and_split_summary
protocol_identity
environment_model_config_result_identities
gates
findings
blockers
required_user_decisions
read_only_commands
privacy_redactions
next_permitted_action
```

Use these literal sentinels consistently:

- `not_applicable`: the field or measurement does not apply to this mode;
- `unavailable`: it applies, but authoritative evidence cannot supply it;
- `not_run`: it applies, but the inspection or measurement was not performed.

Never encode an unknown or unmeasured value as zero. Preserve units, sign,
ratio direction, inequality bounds, and observed-versus-inferred provenance.

## Typed gates

Represent every gate with the same shape in JSON and an equivalent Markdown
row or subsection:

```json
{
  "id": "stable_gate_id",
  "stage": "stage_name",
  "criterion": "frozen acceptance criterion",
  "status": "PASS | FAIL | BLOCKED | INCONCLUSIVE | NOT_APPLICABLE",
  "observations": ["measured or directly inspected fact"],
  "evidence": [
    {
      "kind": "file | manifest | receipt | command | observation",
      "path_projection": "public or repository-relative identity",
      "sha256": "digest | unavailable | not_applicable",
      "detail": "concise binding or observation"
    }
  ],
  "missing": ["required evidence not present"],
  "impact": "why this gate affects the top-level status",
  "next_permitted_action": "one read-only or separately authorized action | not_applicable"
}
```

The gate status is `BLOCKED` for a known unmet prerequisite, `INCONCLUSIVE` for
insufficient/conflicting evidence, and `NOT_APPLICABLE` only when the criterion
does not belong to the selected scope.

## Mode-specific content

- `complete_plan`: include every workflow stage, required inputs, exact
  writers/readers, immutable outputs, acceptance gates, failure states,
  assumptions, user decisions, and the next separately authorized action.
- `performance_plan`: additionally include workload cardinality, measured
  baselines, resource envelope, concurrency/affinity, memory/storage growth,
  overhead allocation, variability or censored bounds, bottlenecks, and frozen
  performance gates. Keep scientific quality metrics separate from runtime and
  utilization metrics.
- `stage_audit`: include the audited stage plus its upstream input and downstream
  consumer identities, with a finding and evidence for every applicable gate.
- `progress`: include compact lane/candidate and resource summaries, observed
  progress, ETA only when supported, anomalies, and exactly one next read-only
  check or separately authorized action.

## Conversation and archival artifacts

A conversational progress check does not require JSON. Lead with status and
reason, then report compact applicable sections; do not create an artifact
unless the user requests archival.

For archival, JSON is the canonical structured record and Markdown is its
human-readable projection. They must have identical mode, status, identities,
counts, gate statuses, blockers, decisions, and `next_permitted_action`.
Re-read and compare both before reporting completion.

Derive the filename phase prefix from the active authority; never hard-code
`PHASE9B` for a future phase. Propose collision-free names using:

```text
docs/<ACTIVE_PHASE>_<TOPIC>_V###_REPORT.md
docs/<ACTIVE_PHASE>_<TOPIC>_V###_RESULT.json
```

If no phase is frozen, use a repository-neutral topic prefix or ask the user.
Select versions from existing authoritative names, not mtime, and never
overwrite a version.

## Privacy

Public artifacts must omit or digest SSH alias, hostname, username, IP,
credentials, private absolute paths/environment prefixes, GPU UUID, private
process bindings, and sensitive command arguments or configuration values.
Record redaction categories in `privacy_redactions`. Conversation may expose
only the minimum temporary private detail required for the current diagnosis.

Run scripts/validate_workflow_report.py on canonical archived JSON before
delivery. A validator pass checks structure and status consistency; it does not
prove that the cited evidence is scientifically true.
