# Server Read-Only Verification Plan

Status: completed with explicit user approval on 2026-07-22.

## Purpose

Phase 0 needed server access only because the legacy source code and local documentation state that the authoritative 401,856-row xTB table and correct 36,585-row v3 graph table exist only under `<HPC_PROJECT_ROOT>`. The raw 24-gold DFT endpoint records also existed only there.

No computation, environment activation, upload, download, file creation, timestamp modification, process control, or job submission is required.

## Connection policy

1. Use `<HPC_SSH_ALIAS>` from the ignored local configuration with its dedicated identity, `BatchMode=yes`, `IdentitiesOnly=yes`, and a short connection timeout.
2. Attempt the normal connection first.
3. If it fails or closes, verify the private SOCKS5 endpoint documented in the server-knowledge worktree, then retry through its documented ProxyCommand.
4. Do not interpret a local `198.18.x.x` result as public DNS; if DNS diagnosis becomes necessary, follow `AGENT.md` Section 8.
5. Stop after repeated connection failure; do not change the proxy, VPN, server, SSH config, or keys.

## Permitted remote actions

Only commands equivalent to the following are permitted:

- `pwd`, `test -r`, `find` for exact source discovery;
- `stat`, `wc -l`, `head -n 1`, `sha256sum` for metadata;
- a stdin-fed Python audit that opens CSV/JSON inputs read-only and prints aggregate counts, columns, missingness, duplicate counts, ranges, symmetry proportions, joins, and formula differences;
- `git rev-parse`, `git status --short`, and dependency/version reads if needed for provenance.

The audit will prefer these candidate paths, while accepting that discovery may reveal a renamed canonical file:

```text
<HPC_PROJECT_ROOT>/results/calculations/20260628/imid_v4_crude/combined_m3.csv
<HPC_PROJECT_ROOT>/results/calculations/20260628/imid_v4_crude/imid_full_v4menu_crude_0618_method.csv
<HPC_PROJECT_ROOT>/data/candidates/imid_lib_v3menu_graph_full.csv
<HPC_PROJECT_ROOT>/results/calculations/20260627/pubchem_v4_expansion/pubchem_imid/imidazolium_graph_v4_new_only_pubchem_annotated.csv
<HPC_PROJECT_ROOT>/data/runs/mol_gold/dft_mol.csv
<HPC_PROJECT_ROOT>/data/runs/mol_gold/runs/*/freq.json
```

## Explicitly prohibited actions

- No `source`/conda activation.
- No PySCF, xTB, Hessian, VASP, CP2K, tests, or model runs.
- No `mkdir`, redirection to remote files, `touch`, `tee`, editor, patch, `sed -i`, move, copy, sync, or deletion.
- No process/job inspection beyond what becomes necessary to diagnose the connection itself; no kill/restart/submit.
- No copying large legacy files into the new repository. Only aggregate evidence is printed back to the local audit.

## Expected outputs

- exact authoritative paths and SHA256;
- candidate row/key/target/endpoint statistics;
- v3/v4 lookup row/key/fragment/symmetry statistics and full join coverage;
- gold endpoint/convergence/Hessian statistics and formula revalidation, if raw records are found;
- a precise list of any evidence that remains unavailable after the read-only check.

## Completion record

- Direct SSH succeeded; SOCKS5 fallback was not needed.
- The authoritative full xTB table, reduced M3 projection, correct v3 graph table, v4-new table, gold label table, gold DFT summary, and 24 raw gold JSON records were inspected read-only.
- Aggregate checks covered row counts, keys, columns, missingness, formula reconstruction, family joins, symmetry, label overlaps, Hessian state, convergence, endpoint states, and SHA256.
- The remote deployment is not a Git checkout; server-only data is therefore pinned by path and SHA256, not a server commit.
- No remote file was created, modified, copied, downloaded, or deleted. No environment was activated and no calculation or job command was run.
