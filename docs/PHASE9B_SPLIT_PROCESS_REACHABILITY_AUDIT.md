# Phase 9B Split-Process Reachability Audit

## Current single-process assumptions

The v8 assisted route assumes all of the following:

1. AIMNet2 and PySCF imports occur in one worker interpreter. The assisted
   adapter calls `run_assisted_stage` and then `_run_two_endpoint_pyscf` in the
   same `_execute_assisted` call
   (`quantum/phase9b_execution.py:255-301`).
2. One worker owns both stages. `Phase8BWorkerLaunch` represents one pre-import
   worker handshake (`quantum/two_endpoint.py:673-695`), and the Phase 9B
   supervisor returns one such launch record
   (`quantum/phase9b_supervisor.py:660-668`).
3. Handoff is in-process plus durable bytes. `AssistedStageResult` returns an
   in-memory `pyscf_request` and endpoint byte objects
   (`quantum/phase9b_aimnet2_runtime.py:379-405`), while the runtime also writes
   and re-reads output bytes (`:1618-1645`).
4. One worker process tree represents the route. The shared supervisor reports
   one child and one process group (`quantum/process_supervisor.py:300-580`).
5. One compute capability authorizes the complete route. `ComputeClaim` is a
   permanent process-bound authorization for one worker import
   (`quantum/phase8b_execution.py:237-282`), and worker adapter selection happens
   only after that claim (`quantum/worker.py:624-830`).
6. One terminal receipt represents all runtime stages. The shared two-endpoint
   executor creates one result/failure terminal around both endpoints
   (`quantum/two_endpoint.py:3373-4050`).

Those assumptions must be replaced explicitly; none can be left for runtime
inference.

## Reachability matrix

| Current component and source evidence | Current assumption | Reuse unchanged | Required Item 10 change | Identity/schema/test impact |
| --- | --- | --- | --- | --- |
| `phase9b_guardian.py` transaction order and irreversible consumption (`:8-37`, `:671-817`) | one route permit starts one route supervisor | exclusive/no-follow receipt writer (`:303-349`) and consume-before-spawn order | add campaign-specific verification, two interpreter profiles, campaign schedule, ack-failure state; guardian still launches only supervisor | campaign guardian closure; permit v3; guardian state tests |
| guardian CLI (`phase9b_guardian.py:930-987`) | one fixed supervisor entry and one worker binding | strict closed argv and prompt return | bind only campaign supervisor for assisted; never expose stage argv | launch v3 and bypass mutations |
| supervisor CLI (`phase9b_supervisor.py:278-409`) | thirteen flags identify one route worker | hand-written exact parsing, hash/path validation | new campaign flag schema and composite hashes; no free text | campaign launch schema and parser tests |
| `WorkerHandshakeBinding` (`phase9b_guardian.py:355-420`) | one worker consumes the entire route authority | field-by-field identity binding pattern | split into campaign binding plus internal stage bindings | shared schema closure, replay tests |
| `WorkerRegistration`, acknowledgement, release and compute claim (`phase8b_execution.py:209-282`, `:1694-1885`) | one registration/release/claim per route | reuse protocol and filesystem/process primitives | generalize role and parent/stage identity without weakening checks; two one-shot internal uses | internal capability schema; role/cross-attempt mutations |
| `Phase8BWorkerLaunch` (`two_endpoint.py:673-695`) | one pipe/token/deadline launches one worker | shape and release transport concepts | create typed campaign/A1/A2 launches; do not pass a Phase8B launch through campaign | composite closure and type-refusal tests |
| one-shot permit (`phase9b_permit.py:446-495`) | one route permit is consumed before one worker chain | shared `consume_one_shot_permit` linearization and no restoration | new assisted campaign v3 payload; no A1/A2 permits | permit v3 and exactly-once mutations |
| execution adapter registry (`phase9b_execution.py:163-191`, `:304-351`) | exact attempt selects one function in one worker | exact-attempt registry and no request-selected adapter | direct remains; assisted resolves campaign topology, never a stage entrypoint | source v9; adapter reachability tests |
| direct adapter (`phase9b_execution.py:226-253`) | directly invokes shared two-endpoint PySCF path | direct orchestration and input provenance | call extracted shared typed PySCF core | parity contract and shared-core identity |
| assisted adapter (`phase9b_execution.py:255-301`) | invokes ML then PySCF in one process | endpoint semantics only | replace with campaign guardian/supervisor orchestration; no compute imports | major campaign closure; import-isolation tests |
| `run_assisted_stage` (`phase9b_aimnet2_runtime.py:1356-1472`) | returns in-memory rebound request for immediate PySCF | one model load, endpoint order, gates and metrics | refactor behind A1-only entrypoint; durable terminal and no PySCF request object crosses process | A1 closure and terminal schema |
| `_load_base_model` (`phase9b_aimnet2_runtime.py:747-811`) | imported by the route worker | exact weight/offline/device checks and lazy import | reachable only after A1 capability; assert one call | A1 closure and load-count tests |
| `AseLBFGSOptimizer` (`phase9b_aimnet2_runtime.py:1087-1230`) | same process continues to PySCF | frozen optimizer, deadline probes, trajectory measurements | retain algorithm; use A1 derived deadline and stage receipts | A1 tests; invocation semantics remain registered |
| `pyscf_may_start` / `PySCFHandoffReceipt` (`phase9b_handoff.py:269-289`, handoff validators later in file) | an in-process result opens PySCF | structural/byte identity primitives | replace admission authority with immutable A1 proposal, separate supervisor verification, separate A2 admission, and A2 disk read | three receipt schemas and tamper matrix |
| PySCF backend (`two_endpoint.py:1814-2647`) | constructed inside the same authorized worker | exact package protocol, lazy import, backend evidence | extract one shared core callable by direct and A2 wrappers | shared core closure and parity tests |
| endpoint runner (`two_endpoint.py:2648-3372`) | one process executes both endpoints in order | cation-before-neutral, standard/SOSCF behavior, endpoint failure stop | preserve inside shared core; accept typed byte provenance | endpoint schemas and no-retry tests |
| process supervisor (`process_supervisor.py:300-580`) | one child process group per route | exact group TERM/KILL, bounded reap, orphan detection (`:416-555`) | campaign supervisor invokes a stage-scoped instance sequentially and stays alive | process-tree receipt and overlap/orphan tests |
| launch (`preparation/phase9b_launch.py:339-528`, `:833-862`) | external control launches one guardian per route | strict argv construction, short acknowledgement, guardian-only rule | assisted argv names campaign guardian/profile; forbid public stage functions | launch v3 and bypass tests |
| deploy (`preparation/phase9b_deploy.py:245-650`) | route inventory contains one runner closure | local/remote hash verification and all-route transaction pattern | inventory all subclosures and promote all A1/A2/shared sources before run | manifest v3 and partial-source replacement tests |
| resources (`phase9b_resources.py:45-87`) | one interpreter process owns AIMNet2 and PySCF; preopt budget is nested | frozen PySCF envelope and 900/7200 values | bind distinct stage interpreters/resources and one campaign deadline; precise GPU/CPU accounting | resources v2 and timing tests |
| preflight (`preparation/phase9b_preflight.py:247-340`) | one host result is enough for one runtime interpreter | fail-closed evaluator and injected read-only runner | validate exact MLFF and GPU-PySCF interpreters, selected V100, source profiles and no shared process requirement | preflight v2 fixtures; no server in Item 10 |
| request/bundle (`preparation/phase9b_bundle.py:153-318`) | both routes bind one runner hash and assisted in-process stage | canonical bytes, shared initial geometry, parity validator | request/manifest v3 bind topology, composite/subclosure and fixed profiles | paired-generation and arbitrary-interpreter rejection tests |
| permit placement | one per-route v2 permit | exclusive placement/no replacement policy | render one assisted campaign permit, never internal capabilities | permit-placement v3 tests |
| future Postflight | one worker receipt and process tree suffice | strict canonical parsing, process absence and label formula ideas from Phase 8B (`phase8b_postflight.py:287-842`) | inspect campaign guardian/supervisor, A1, handoff, A2, both interpreter/source identities, no overlap, residuals and partial terminals | Item 11 only; campaign-aware schema |

## Classified outcome

No execution-reachable component is unclassified. Existing scientific kernels
and safety primitives have named reuse paths; orchestration, authority, schema,
identity, deploy/launch, and Postflight have named refactors or new components.
“Reuse” above means reuse of the cited behavior, not byte-for-byte reuse unless
the Item 10 implementation proves the signature and closure remain unchanged.

The present source is intentionally untouched. Its v8 single-process path is
complete but cannot be hosted by a validated interpreter and stays unreachable
behind false gates.
