# Evidence Routing

Load the smallest authoritative evidence set that can answer the selected mode
and stage. Do not bulk-read historical reports, `results/`, or every pipeline
configuration.

## Authority precedence

Resolve a claim in this order:

1. active safety and authorization instructions, including the user's explicit
   scope for the current request;
2. `AGENT.md` common constraints and its current-phase section, then the current
   boundary in `PHASE_STATUS.md`;
3. frozen scientific and data contracts such as `docs/SCIENCE_SCOPE.md`,
   `docs/DATA_CONTRACT.md`, and `docs/MODEL_CARD.md`;
4. the exact phase plan, protocol, configuration, split, or manifest named by
   that authority chain;
5. immutable primary receipts, results, hashes, and file contents bound by
   those artifacts;
6. implementation and tests for writer/reader behavior;
7. logs, process state, and live read-only observations as diagnostic evidence
   only.

A lower-ranked source cannot silently override a higher-ranked source. Record
the conflict and return the mode-appropriate blocked or inconclusive status.
An explicit new user decision may freeze an open choice, but it does not waive
a safety boundary or rewrite immutable historical evidence.

Bind each material source to its repository-relative or public path projection,
Git/worktree identity, byte count, and SHA256 when available. Never select an
artifact as authoritative merely because its filename looks newer, its mtime is
later, or it is the last match from a glob. Resolve the active identity from an
authority reference, manifest edge, configuration field, or explicit user
choice. If two plausible identities remain, ask one focused question and stop
that dependent branch.

## Common minimum

For every mode:

1. inspect the worktree and record HEAD, branch, dirty state, and relevant
   tracked/untracked changes;
2. read the common constraints and current-phase heading in `AGENT.md`;
3. read the current boundary and only the applicable phase section in
   `PHASE_STATUS.md`;
4. follow explicit references from those sections to the exact active
   artifacts;
5. expand the evidence set only when a gate or unresolved identity requires it.

Do not treat a report summary as primary evidence when its named receipt,
manifest, configuration, or source file is available.

## Mode and stage routes

| Mode or stage | Add to the common minimum |
| --- | --- |
| Complete plan | Read the frozen scientific, data, and model contracts; the active candidate/split authority; the active parent-level protocol; dataset/target contract; fine-tune configuration authority; validation/promotion authority; and exact current manifests/results needed to mark every stage gate. Do not load unrelated historical phases. |
| Candidate or split audit | Read the candidate-pool identity and SHA256, permanent split ledger/manifests, exclusion/production/active-campaign identities, and only the scientific fields needed for element, charge, multiplicity, electron, atom-map, and diversity gates. |
| Parent-level route audit | Read the exact protocol/configuration, endpoint inputs and hashes, writer/reader contract, endpoint and route manifests, terminal receipt, and process-cleanup evidence for the named candidate or cohort. |
| Frame or dataset audit | Read `docs/DATA_CONTRACT.md`, the admitted route manifests, exact frame set, D3 identity and subtraction configuration, dataset writer/reader implementation, split projection, and dataset manifest/result. |
| Training readiness or result audit | Read `docs/MODEL_CARD.md`, exact dataset/split/model-weight identities, fine-tune configuration, training writer/reader implementation, claim/terminal/checkpoint evidence, and validation result. Do not open final-test evidence unless the model-freeze authority proves it is permitted. |
| Validation or final-test audit | Read the frozen validation/promotion thresholds, selected model/checkpoint identity, sealed split identity, equal-input/equal-resource comparison contract, and exact validation or one-shot final-test result. |
| One-shot progress check | For QUICK_ACTIVE_STAGE, resolve the private connection/run root and only the active stage configuration, current claim/terminal identity, active logs/manifests, and bounded process/resource observations. Add the full queue, lane, split, model, and pipeline identities only for FULL_PROGRESS_AUDIT or an observed anomaly. Historical reports are context, not live status. |
| Performance plan or readiness audit | Read the frozen workload and scientific protocol, resource limits, exact historical timing receipts, concurrency/affinity configuration, storage/memory/GPU gates, and benchmark comparison contract. Preserve measured distributions and censored bounds; do not derive exact ETA or speedup from incomplete evidence. |

For a stage audit, retain the immediately upstream input identity and downstream
consumer identity without loading their full evidence trees.

## Stop and expansion rules

- If a progress check lacks an unambiguous private connection or remote-root
  identity, ask; do not guess or scan arbitrary servers.
- If an active artifact points to another manifest or receipt required to prove
  a gate, follow that edge. Do not recursively collect unrelated siblings.
- Source control flow, log text, mtime, and a live-process boolean do not prove
  scientific acceptance or manifest closure.
- Missing primary evidence is `unavailable`; an applicable check not performed
  is `not_run`; an irrelevant field is `not_applicable`.
- Keep all discovery and inspection read-only. Describe any required mutation
  as a separately authorized next action.
