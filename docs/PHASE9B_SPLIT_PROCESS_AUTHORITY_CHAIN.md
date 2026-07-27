# Phase 9B Split-Process Authority Chain

## One user authority, two internal stages

`AssistedCampaignPermitV3` is the only user-level assisted authority and is
consumed once. It binds the candidate, route, overall attempt, remote root,
composite source closure and subclosures, supervisor and stage sources, evidence
schemas, duration limits (7200-second campaign, 900-second A1 and 10-second
termination grace), fixed route schedule, and no
retry/resume/fallback semantics.

It also binds the frozen initial cation and neutral XYZ bytes and hashes, atom
order, charges, multiplicities, electron count, atom map 14/8/15, structural
gates, PySCF protocol, and label formula. Its A1 profile binds the exact MLFF
interpreter and package/weight/optimizer/cache identities. Its A2 profile binds
the exact GPU-PySCF interpreter and the frozen PySCF/geomeTRIC/dispersion and
resource protocols.

The A1 profile freezes Python 3.11.15, torch 2.8.0+cu128, CUDA 12.8, AIMNet
0.2.0, ASE 3.29.0, the explicit 8,836,941-byte
`aimnet2_wb97m_d3_0.pt` with SHA256
`f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28`,
loader decision A, `compile_model=false`, `validate_species=true`, and a
900-second local ceiling. The A2 profile freezes Python 3.11.15, PySCF 2.13.1,
geomeTRIC 1.1.1, pyscf-dispersion 1.5.0, and B3LYP-D3(BJ)/def2-SVP with the
shared direct-route grid, SCF, geometry and resource protocol. Both profiles
bind stable interpreter-profile IDs and digests. Host-local absolute prefixes,
executables and inode identities live only in private bindings used by
preflight; the request and public permit cannot carry or override them.

The permit does not bind the not-yet-existing A1 output digest. It binds the
only authorized procedure that may produce those bytes, the validation contract
that must admit them, and the only stage source/interpreter that may consume
them. This is not self-reference: the permit hashes immutable inputs and
procedures; the runtime output digest is later linked by receipts whose schemas
and verifying sources were already permit-bound.

## Guardian boundary

`AssistedCampaignGuardian` verifies source, request, manifest, resources,
permit, route, attempt, candidate, root, schedule, and both interpreter
identities before any irreversible action. It then consumes the permit by
exclusive/no-follow one-shot transition, writes the consumption receipt, starts
the campaign supervisor as an independent session/process-group leader, passes
a campaign capability through the audited handshake, waits for a bounded
acknowledgement, writes its launch receipt, and returns.

Guardian-owned `GuardianLaunchStateV1` values are:

```text
not_started
permit_validated
permit_consumed
supervisor_spawned
supervisor_spawn_failed
acknowledged
ack_failed
indeterminate
```

Consumption is never restored. The guardian never imports compute packages,
interprets XYZ, starts A1/A2, validates scientific acceptance, or waits for the
campaign computation.

## Supervisor boundary

`AssistedCampaignSupervisor` is the only long-lived controller. Its state starts
at `campaign_capability_validated`; it never claims permit validation,
consumption, or its own spawn. It is
standard-library plus project control-plane source only. It validates the
campaign capability, fixes the absolute monotonic deadline, creates the evidence
root, issues and supervises A1, proves the A1 process tree is reaped, validates
all A1 and handoff bytes, issues A2 only after an admission receipt is durable,
supervises and reaps A2, then writes exactly one overall terminal receipt.

It can hash files, parse canonical JSON and XYZ, validate schemas, identities,
deadlines and exact path manifests without importing torch, aimnet, ASE, PySCF,
geomeTRIC, or dispersion.

## Authority flow

```text
user AssistedCampaignPermitV3
  --consume once--> campaign guardian
  --audited pipe/registration/ack--> campaign supervisor
  --issue once--> A1 InternalStageCapabilityV1
  --A1 terminal + independent handoff verification-->
  --issue at most once--> A2 InternalStageCapabilityV1
  --A2 terminal--> one campaign terminal
```

Request and CLI data cannot select adapters or interpreters. Exact interpreter
profiles come from the source-frozen attempt registry, and every later identity
must equal the permit-bound registry projection.

## Stable and private interpreter identity

`InterpreterProfileStableIdentityV1` is portable and may enter request,
manifest, resources and permit. It contains logical profile ID, Python version,
package-version projection, executable content identity, activation-script
digest, runtime capabilities, sanitized environment identity, and canonical
digest. Direct and A2 bind the same GPU-PySCF stable profile digest; A1 binds the
MLFF stable profile digest.

`InterpreterProfilePrivateBindingV1` is host-local and never enters public Git.
It contains absolute prefix and executable, device/inode, private paths and
host-local mappings. Future preflight proves that a private binding realizes the
permit-bound stable identity. Request, CLI and environment variables can never
supply an arbitrary interpreter path.
