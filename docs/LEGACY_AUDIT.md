# Legacy Audit

Status: **legacy evidence collection complete; repository skeleton and Phase 0 packaging pending**
Primary source: `<LEGACY_LOCAL_ROOT>` current working tree
Server-knowledge source: `<SERVER_KNOWLEDGE_WORKTREE>` (connection knowledge only)
Audit date: 2026-07-22

This document is intentionally created before audit execution. Sections marked `PENDING EVIDENCE` must be filled from direct code, configuration, table, hash, and Git inspection. They are not assumptions.

## 1. Snapshot provenance

| Item | Evidence |
| --- | --- |
| Legacy root | `<LEGACY_LOCAL_ROOT>`; real value stored only in ignored local config |
| Branch | `Vasp_on_the_fly` |
| HEAD commit | `44a68bf70031bd75799f42c4a02adf71f1b99d31` |
| HEAD date | `2026-07-15T17:11:27+08:00` |
| Remote | `https://github.com/lijiawei0305-pixel/nhc-predictor.git` |
| Dirty working tree | Yes: four modified MLFF/RETRO files and one untracked MLFF report directory; none of the 21 prompt-required files is dirty |
| Python/dependency declarations | `env/molecular.yml`: Python 3.11; NumPy/SciPy/pandas/pyarrow/scikit-learn/PyYAML plus PySCF/geomeTRIC/xTB and other legacy dependencies. Root `requirements.txt` is less complete than this environment file. |
| Required-file existence | All 21 prompt-required files exist and are clean relative to HEAD; individual SHA256 values recorded below |

The selected source is a dirty working tree by user decision. All evidence must therefore identify whether it is clean at HEAD or a working-tree-only addition. Current uncommitted changes are unrelated to the 21 required audit files, but this does not turn the entire working tree into a reproducible Git commit.

The deployment at `<HPC_PROJECT_ROOT>` is not a Git working tree. Server-only data therefore cannot inherit a server commit SHA; it is pinned by project-relative path, byte size, schema, and SHA256. Source-code provenance remains the local legacy HEAD plus the separately recorded local working-tree state.

### 1.1 Required-file manifest

| Required path | SHA256 |
| --- | --- |
| `doc/claude/science-decisions.md` | `e23c2893da67e3c8827b85a09aba4fe4a8d32211715ef13d3ac6e0288e88f42f` |
| `config/surrogate/target_a.yaml` | `e26e242ed58ce1f5da8b3fc10a2a576d36b2ff47c85ac5bf09942de2e2528b96` |
| `scripts/surrogate/fragment_features.py` | `62fe1c85e1d18914fa290a8ec0ef6c3c3a7ab5e3aab8725a1a762f4b40cfdafb` |
| `scripts/surrogate/small_sample.py` | `1116fd0f45bd3732d797c2e23e5961b40656bad3e9ac9ef00adafe15d8884694` |
| `scripts/surrogate/improvements/step4_multifidelity/delta_learning.py` | `10e9b1ad4b043ce71233f13649375170fb56d6522dc4e2f4136671b30095261a` |
| `scripts/surrogate/improvements/step4_multifidelity/run_multifidelity.py` | `784807a6f1f6e6fe8e794ba726cd52288ca0979c4c0bb164d37685b3c0ab4489` |
| `scripts/surrogate/improvements/README.md` | `aff9dc541f99fbd7d4f237ae4d9e2020b9016f349ae14668af06465a4fb67fb3` |
| `scripts/post/apply_gas_proton_to_delta_e_deprot.py` | `9088a85745ac80fe355444646c44d925c8c52b9d0a54cfaa805ba4bf79b030cb` |
| `scripts/mol/dft_runner.py` | `45b3bbb8118a749b7e453b414d22edb42c5fe7d19861bcf184711ed3e12ce832` |
| `scripts/mol/dft_batch.py` | `9641125099c2f95f6566cb76bc2b24525d2b784dbde936403893433ae702a71b` |
| `reports/part1-blind-round2-2026-07-09/blind_round2_preregistration.md` | `d1828fc13d3151b2e53d50a04b19eb80a6f10db7dfe46cb6747e587517ebfa3a` |
| `reports/part1-blind-round2-2026-07-09/deltaE_final.csv` | `4c457f12363c44698279f0dc43e85a6933bc3bae0c4a9a807a35398cfe84eb5b` |
| `reports/part1-blind-round2-2026-07-09/analyze_round2_results.py` | `79d65a589f33f643bfc9c9681b23b2723495882224d8dceb71fedfbf763144f4` |
| `reports/part1-small-train-big-predict-2026-07-09/README.md` | `93f9d3abdd852691df7665403767a2981c6d1dc44fa427437e21d88318f0472a` |
| `reports/part1-small-train-big-predict-2026-07-09/stbp_learning_curve.py` | `0c7cee0703de1331e5d3cdbf52525feca085cbea2adb368ee2346b2926567933` |
| `reports/part1-masquerade-trap-breaking-2026-07-12/README.md` | `e09e646cc44f445b6cb6a3f4e3c864f10272fbc1799ea760ced27b39e19b25c3` |
| `reports/part1-masquerade-trap-breaking-2026-07-12/load_data.py` | `2829daf1221de450c9b6dce47f0a9ca1fb526655f2dec286691cb4c2a509f15f` |
| `reports/part1-masquerade-trap-breaking-2026-07-12/literature_support.md` | `c806fe737a497e7b6c750007e2542285bdcbf275b5ce50a9703d7d8e83963f8f` |
| `reports/part1-masquerade-trap-breaking-2026-07-12/C_clean_model.py` | `bf830db8623ade3f5f2aa6b26cf227f6c46c8b1512ee899d6a7075567c247c04` |
| `reports/part1-masquerade-trap-breaking-2026-07-12/skeptic_S1_check.py` | `b8d02cb774769f141b6ed5fb5b2d416d65b32825932188abe7fdee3e05442e63` |
| `reports/part1-masquerade-trap-breaking-2026-07-12/skeptic_S3_check.py` | `a2e1815808a5ca29eb0f8705cbb7679efb577ce15b5d463d36e18b01ee92a6e0` |

## 2. Candidate sources

The local checkout does not contain the authoritative full xTB table named by `config/surrogate/target_a.yaml`, nor the correct v3 graph table. Legacy documentation correctly identifies them as HPC-only. They were verified by an approved read-only SSH audit; no legacy file was copied or modified.

Two independent local products establish the intended universe size without establishing the xTB table schema:

- `results/surrogate/target_a/D_deprot.csv`: 401,856 rows, 401,856 unique non-null InChIKeys, no null `D_deprot`, SHA256 `105ae5d394b20c8d06929804422d9432bcc2ac77069ba84ac2f59bfc1a63dfd1`.
- `results/calculations/20260628/imid_v4_crude/imid_v4_pubchem_merged.csv`: 401,856 rows, 401,856 unique non-null InChIKeys, SHA256 `e09e458a87ff8fa1e5863f78a932cdb52b0d658640be6f50218f5043d2d15c75`.

These key-only/derived tables cannot by themselves establish target missingness, endpoint energies, exact xTB schema, or fragment join coverage. Those facts now come from the authoritative server inputs below.

| Source role | Path | SHA256 | Rows | Unique InChIKeys | Notes |
| --- | --- | --- | ---: | ---: | --- |
| Full xTB candidates | `results/calculations/20260628/imid_v4_crude/imid_full_v4menu_crude_0618_method.csv` on HPC | `327c00871fde7149b79e527de537dd98ea26686af641b87882a112e15a01617f` | 401,856 | 401,856 | Authoritative config path; complete 28-column table |
| Reduced M3 projection | `results/calculations/20260628/imid_v4_crude/combined_m3.csv` on HPC | `202941803d9351ca4d9d5d3cfa232d9bf1476cd36a4a72fb98d29c49bda70a16` | 401,856 | 401,856 | Same key set/order and same target; not authoritative because other common fields diverge |
| v3 graph/family source | `data/candidates/imid_lib_v3menu_graph_full.csv` on HPC | `30ad7d4479a4902f22856ae5e5838e368eaf47eab1f576ee68b352a2a03316ae` | 36,585 | 36,585 | Correct graph/molzip enumeration; zero null fragment cells |
| v4 new-only source | `results/calculations/20260627/pubchem_v4_expansion/pubchem_imid/imidazolium_graph_v4_new_only_pubchem_annotated.csv` | `ff319a318ab3d954ea530e559ec90dca59e5f8c1d209b013e679a2a60f946747` | 365,271 | 365,271 | Zero null fragment cells |
| Obsolete local v3 (not admissible as source) | `data/candidates/imid_lib_v3_full.csv` | `36516cf93b86a5f5224da70ffe1d3775b3f4bb10246a2f65f620597e61c0c4c6` | 15,130 | 15,130 | Pre-fix string-builder enumeration; explicitly prohibited as replacement |
| Local 120 descriptor sample | `results/surrogate/part1/part1_descriptors.parquet` | `b43060e3b9481aee5e012c33cdd24656c4d69981af3936bdab0df0e3f4a783d7` | 120 | 120 | Supports the 71-label historical audit, not full-pool import |

### 2.1 Authoritative full-table checks

The full xTB table has:

- 401,856 parsed rows, 401,856 unique non-null InChIKeys, zero duplicate rows;
- zero missing cation SMILES, neutral SMILES, endpoint energies, or target values;
- finite `delta_e_deprot_kcal` range `44.002403` to `124.685725 kcal/mol`;
- formula maximum absolute error `1.42e-14 kcal/mol` over all 401,856 rows and zero failures over `0.02`;
- `hessian_computed=False` and `frequency_status=skipped_hessian` for all 401,856 rows.

The table also stores `n_imaginary=0` for every row despite the skipped Hessian. That value is not evidence of zero imaginary modes. Import logic must give `hessian_computed`/`frequency_status` precedence and normalize the unknown imaginary-mode count to null or an explicit not-computed state.

`combined_m3.csv` has the same key set, row order, and target values as the authoritative table. It differs in `delta_e_kcal` for 372,397 rows, `gap` for 10,980, and `gap_cation` for 9,667. It is therefore a later reduced/assembled projection, not an interchangeable source for all fields. The new project will use the explicit `target_a.yaml` full-table path.

## 3. Target definition trace

The xTB producer `scripts/m03_batch_runner.py` defines

```text
delta_e_deprot_kcal =
    (e_neutral - e_cation) * 627.509474 - 6.28
```

The migration script `scripts/post/apply_gas_proton_to_delta_e_deprot.py` applies the same `-6.28 kcal/mol` constant to older stored values that lacked it. `scripts/m03_prescreen_filter.py` accepts lower values as easier deprotonation, establishing `lower_is_better=true`.

For DFT, `scripts/mol/dft_runner.py` produces B3LYP-D3(BJ)/def2-SVP optimized endpoint electronic energies using PySCF, `pyscf-dispersion` through `mf.disp='d3bj'`, and geomeTRIC. Cation and neutral are closed-shell singlets with charges +1 and 0. The high-fidelity electronic target uses those optimized-state `E_cation` and `E_neutral` values and the same conversion/proton constant.

Legacy prose often calls the target `ΔG` or uses a `G_*` field even when `--skip-hessian` makes `G=E`. The new project must not preserve that naming error. It will store the endpoint electronic difference separately and call the target an electronic deprotonation energy.

## 4. Fragment and family provenance

The authoritative lookup is the disjoint union of the correct 36,585-row v3 graph table and the 365,271-row v4-new table. The read-only server audit found zero overlap, 401,856 unique union keys, zero union keys absent from the full xTB table, and zero full-table keys absent from the lookup. Fragment coverage is therefore 100%.

`fragment_features.py` checks for duplicate InChIKeys after concatenation and encodes each axis by unordered presence/count, specifically to respect N1/N3 and C4/C5 exchange symmetry.

The local v4-new table has 365,271 unique keys and zero missing fragment cells. It is **not** a strictly equal-substituent population:

- `N1_frag == N3_frag`: 10,832 / 365,271 (2.965%);
- `C4_frag == C5_frag`: 12,219 / 365,271 (3.345%);
- both equal: 626 / 365,271 (0.171%).

Across the complete 401,856 lookup, only 896 candidates (0.223%) have both `N1=N3` and `C4=C5`. The union contains 528 canonical axis-A families, 406 canonical axis-B families, and 214,368 exact combined families.

Therefore the applicable first-phase constraint is canonical exchange symmetry/deduplication, not the blanket assertion that both positions on each axis are identical.

All current candidate sources are imidazolium-only by explicit project scope. The Phase 0 skeleton can therefore be assigned from explicit source metadata as `imidazolium`; no filename substring classifier is needed for this snapshot.

## 5. High-fidelity label sources

| Source group | Path | SHA256 | Rows | Unique InChIKeys | Endpoint energies | Protocol | Hessian evidence |
| --- | --- | --- | ---: | ---: | --- | --- | --- |
| Gold | HPC `data/runs/mol_gold/gold_labels.csv` + `dft_gold.csv` + 24 `runs/<key>/freq.json`; local prediction export identifies the same 24 | labels `ba181ef3...6d9e`; summary `58c83f1e...5b659`; local export `561f362a...15066f` | 24 | 24 | Yes | B3LYP-D3(BJ)/def2-SVP electronic, geomeTRIC | Direct: all 24 successful, Hessian skipped, `G=E`, endpoint states (+1/1 and 0/1) correct |
| Blind round 1 | `reports/part1-dft-gold-validation-2026-07-06/blind_test_dft_energies.csv` + `blind_test_comparison.csv` | energies `03ad6bca...19367`; comparison `f353d3e9...04f62` | 12 | 12 | Yes | Same protocol | Direct: 12/12 `freq_computed=false`, `n_vfreq=-1` |
| Blind round 2 | `reports/part1-blind-round2-2026-07-09/deltaE_final.csv` | `4c457f12363c44698279f0dc43e85a6933bc3bae0c4a9a807a35398cfe84eb5b` | 35 successful of 36 locked | 35 | Yes | Same protocol; run script explicitly uses `--skip-hessian` | Batch-level evidence: skipped for all attempted labels; per-row Hessian column absent in harvested file |

The three sources contain 24 + 12 + 35 = **71 unique labeled InChIKeys**, with zero pairwise overlap and therefore zero cross-source conflicting duplicates.

- Blind round 1: all 12 endpoint pairs recomputed with `627.509474` and `-6.28`; maximum absolute stored-label difference `0.000214 kcal/mol`; zero failures over `0.02`.
- Blind round 2: all 35 endpoint pairs recomputed; maximum absolute difference `0.000248 kcal/mol`; zero failures over `0.02`. The stored file was harvested with the rounded factor `627.509` and four-decimal output, explaining the harmless sub-millikcal differences.
- Gold 24: all endpoint pairs were recovered from HPC `gold_labels.csv`, `dft_gold.csv`, and the 24 raw `freq.json` records. Formula error is exactly zero at stored precision; all 24 sources agree within `2.28e-13 Hartree`.

All three groups are the same B3LYP-D3(BJ)/def2-SVP/geomeTRIC electronic-energy protocol with skipped Hessian. Direct raw evidence confirms:

- gold: 24/24 successful, 24/24 skipped Hessian, 24/24 `G=E`;
- blind round 1: 12/12 successful, 12/12 `freq_computed=false`, 12/12 `n_vfreq=-1`;
- blind round 2: 35/35 successful final labels with matching raw `freq.json`, 35/35 skipped Hessian, 35/35 `G=E`.

All 71 endpoint state records use cation charge/multiplicity `(+1,1)` and neutral `(0,1)` where raw JSON was checked. Hessian status therefore does not reduce the usable electronic-label count.

### 5.1 Label family support

All 71 labels occur in both the full xTB table and the full fragment lookup. Their xTB range is `57.348205` to `116.171696 kcal/mol`.

- axis A: 38 observed families; 22 singletons; maximum support 10;
- axis B: 35 observed families; 16 singletons; maximum support 5;
- exact combined family: 71 observed families, all 71 singletons.

This directly supports the new specification's decision to use partially pooled additive axis effects and reject exact combined-family effects in the MVP. Exact combined effects are unidentifiable from the current labels.

## 6. Historical modeling evidence

The old Δ-learning implementation always returns

```text
y_hat_DFT = y_xTB + delta_model(X)
```

so the explicit coefficient of the low-fidelity baseline is fixed at 1. It cannot learn the empirically observed slope `rho != 1`; correlated residual features may indirectly mimic a slope correction, which is exactly the shortcut risk identified later.

Using the legacy single-writer 71-label merge, the historical global affine fit is:

```text
y_DFT = 196.178439 + 0.715701 * xTB
```

Evidence from the same dataset:

- raw xTB Spearman `0.958954`, Kendall `0.825352`;
- affine exact-LOO MAE `2.7214 kcal/mol`, RMSE `3.5098`, Q²/R²_LOO `0.90685`;
- affine OOF Spearman `0.957076`, Kendall `0.821328`.

A positive full-data affine slope preserves the raw full-data rank exactly; fold-varying OOF coefficients make the OOF rank metrics slightly different. The size-extrapolation report finds raw/offset xTB ranking near `rho ≈ 0.97` for 30 large molecules while the offset-only MAE remains `5.629 kcal/mol`: the historical gain is mainly absolute calibration, not ranking.

The masquerade audit classifies the following as directly source-related or highly redundant with xTB-HOMO/baseline: `local_softness_C2`, `vertical_ip`, `esp_min`, `esp_max`, ESP means, `mpi_ev`, `balance_of_charges_nu`, `internal_charge_separation`, `polar_surface_area`, plus algebraic frontier-orbital repackagings `gap`, `chi`, `eta`, `softness`, `omega`, and `nucleophilicity`. Endpoint total energies and many surface/volume measures also act mainly as size proxies. `homo` and `lumo` are not automatically scientifically meaningless, but xTB-HOMO is strongly baseline-collinear (`r≈0.975`) and is prohibited from the default production model by the new task.

## 7. Required audit questions

1. Full xTB candidate row count — 401,856.
2. InChIKey uniqueness in the full table — 401,856/401,856 unique, zero null/duplicate keys.
3. Exact definition of `delta_e_deprot_kcal` — `(E_neutral-E_cation)*627.509474-6.28 kcal/mol`.
4. Fragment-code coverage of xTB candidates — 401,856/401,856 (100%).
5. Fragment lookup source files — correct v3 graph table plus v4-new delta; obsolete local v3 is prohibited.
6. N1/N3 and C4/C5 first-phase symmetry — exchange/canonical-pair symmetry, not strict equality; strict both-axis equality occurs in only 896/401,856.
7. Existing usable high-fidelity label count — 71.
8. High-fidelity label source files — identified above.
9. Three-source overlaps or conflicts — zero overlap, zero conflicts.
10. DFT protocol consistency — all 71 use the same documented and raw-confirmed electronic protocol.
11. Hessian-computed versus skipped labels — 0 computed, 71 skipped.
12. Hessian status effect — skipped Hessian makes `G=E`, `n_imaginary=-1`; it does not invalidate the electronic-energy target and must not be described as a Gibbs target.
13. Old Δ-learning fixed slope — explicit `y_hat=y_xTB+delta_model(X)` fixes the baseline coefficient at 1.
14. Global affine history — slope `0.715701`, intercept `196.178439`, exact-LOO MAE `2.7214`, R²_LOO `0.90685` on n=71.
15. Raw xTB ranking history — Spearman `0.958954`, Kendall `0.825352` on n=71; size-OOD report also gives approximately `rho=0.97`.
16. Source-related/highly collinear features — identified in Section 6; broad same-run xTB electronics/ESP are excluded from the default production model.
17. Migration boundary — preliminary decision below; final paths/hashes await HPC input verification.

## 8. Data-quality summary

| Metric | Result |
| --- | ---: |
| Candidate rows | 401,856 |
| Candidate key nulls | 0 |
| Candidate duplicate keys | 0 |
| xTB target null/non-finite | 0 |
| Labels before deduplication | 71 |
| Unique labeled InChIKeys | 71 |
| Cross-source overlaps | 0 |
| Conflicting labels | 0 |
| Formula failures over 0.02 kcal/mol | 0/71 |
| Family coverage | 401,856/401,856 (100%) |

## 9. Migration decision

Migrate as definitions or reimplementations with new tests:

- the electronic target formula, exact constants, charges/multiplicities, and skipped-Hessian semantics;
- InChIKey joins, SHA256 provenance, convergence fields, and duplicate/conflict checks;
- unordered/canonical axis family construction and unknown-family fallback;
- raw xTB and free-slope affine baselines;
- honest grouped/size validation ideas and the warning that preprocessing/selection belongs inside folds;
- the evidence that broad same-run xTB electronics/ESP are shortcut-prone and unsuitable for the default model.

Do not migrate:

- large legacy CSV/Parquet/XYZ/model artifacts;
- fitted estimators, SHAP-selected feature sets, locked blind predictions, or the old 120-row descriptor sample as production data;
- the fixed-slope-1 Δ-learning assumption;
- absolute-path scripts or legacy target names implying Gibbs free energy;
- claims that hierarchy, HOMO, structural descriptors, or any historical model already wins under the new ranking gates;
- a previously revealed blind set as a new blind test.

## 10. Phase 0 gate

Current decision: **Phase 0 passed**. Scientific/data evidence, independent repository skeleton, portable/ignored configuration split, audit utilities, source manifest, reports, tests, lint, typing, configuration parsing, privacy scan, and package build all pass. No Phase 1 importer/model work is authorized until the user explicitly approves entry into Phase 1.
