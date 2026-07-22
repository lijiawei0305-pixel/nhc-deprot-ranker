# AGENT.md — nhc-deprot-ranker 工作约束

本文件适用于本仓库中的所有设计、审计、代码、测试、报告和服务器相关操作。任务真值首先来自 `prompt.md`；若本文与 `prompt.md` 冲突，以更严格且不扩大当前 Phase 范围的规则为准，并先向用户确认。

## 1. 项目边界

- 本仓库是独立项目，只负责 NHC 前体脱质子电子能的 Part 1 排序与校准。
- 全量低保真指标是 `delta_e_deprot_xtb`/标准化后的 `xtb_deprot_kcal`；少量高保真标签是 B3LYP-D3(BJ)/def2-SVP 脱质子电子能。
- 旧项目仅作为只读数据、代码与报告来源。不得修改、回写、重构、提交或推送 `configs/legacy.local.yaml` 指定的本地旧仓库、服务器知识 worktree 或 GitHub 旧仓库。
- 不得把旧项目的大型 CSV、Parquet、XYZ、模型或计算产物复制进本仓库。
- 旧仓库真实绝对路径只能写入被 `.gitignore` 排除的 `configs/legacy.local.yaml`；示例与正式配置不得硬编码私人路径。

## 2. 当前阶段与阶段门禁

- Phase 0 至 Phase 8A 已合入 `main`；当前只进入用户确认的 Phase 8B 单候选 DFT smoke 文档规划阶段。规划不等于执行授权，真实 DFT 仍未授权。
- Phase 4 裁定 `raw_xTB_wins`：B0 是生产排序默认，B1 只能作为绝对能量校准 companion，H1 不得用于正式全库排序。
- Phase 5 只读取不可变的 `data/processed/v001`、B0/B1/Phase 4 决策及其 manifest；不得改写 Phase 1/2/3/4 结果，不得重新拟合或调参。
- Phase 5 可生成本地评分表、适用域审计、候选建议与无 Hessian DFT 互操作 manifest；不得运行 PySCF、xTB、Hessian，不得连接或写入 HPC，不得提交作业。
- Phase 5 必须在 Phase 4 通过、产生明确生产默认模型并获得用户明确确认后才能开始。
- Phase 5 已按用户确认的 B0/B1 双轨语义、Top-100 和 50 条 `15/13/12/10` 配额完成；任何真实高保真计算、上传服务器或提交作业都属于新阶段，仍需重新文档先行和明确授权。
- Phase 6 只把冻结的 50 条建议转换为本地、不可变、可校验的 legacy-ready CSV、5×10 分批计划、四桶 smoke 清单和协议/预期产物 manifest；必须写明 `geometry_generated=false`、`execution_ready=false`、`quantum_chemistry_run=false`、`server_write_authorized=false`、`submit_hpc=false`。
- 当前只有 Phase 7 的 4 条 smoke 具有强验证的 cation/neutral 初始 XYZ；其余 46 条仍未生成。不得在本地运行 RDKit/力场、xTB、PySCF 或 Hessian 来补齐，不得把完整 50 条计划包称为可直接运行的 DFT 输入。
- 旧 `dft_batch --skip-hessian` 的额外 ωB97X-D/def2-TZVP cation/neutral/radical 单点仍被禁用；专用双端点 runner 与同组进程树硬 wall-time 已实现但未执行，在新的 Phase 8B 明确授权前必须保持 execution blocked。
- Phase 7 几何范围严格等于 Phase 6 `smoke.csv` 的 4 个 InChIKey；不得扩展到 batch 01 的其余 6 条或完整 50 条，不得运行 xTB、PySCF、Hessian、旧 M4 或专用 runner。
- Phase 7 只允许在私有配置指定的全新版本化服务器运行目录中写入；必须先确认目标不存在并完成只读环境/资源/legacy 文件哈希预检。禁止修改 `$WJW` 既有代码、环境、候选库或生产结果。
- 禁止使用旧仓库全量 `deploy`、`rsync --delete`、远端删除/覆盖或模糊目标同步。只可定向上传已登记的小型 smoke 输入/脚本，传输后必须核对真实目标和 SHA256。
- 服务器 M2 必须显式进入 `$WJW`、设置 `PYTHONPATH=$WJW` 并只 `source $WJW/env/envs/molenv.sh`；不得 `source ~/.bashrc`、混用软件栈或安装/升级依赖。
- 专用 runner 只允许 cation(+1, singlet) 与 neutral(0, singlet) 的气相 B3LYP-D3(BJ)/def2-SVP geomeTRIC 优化和最终电子能；接口中不得出现 Hessian、ZPE、热化学、ωB97X-D/def2-TZVP 单点、radical、Molden 或作业提交逻辑。当前 execution authorization 必须保持 false；只有 Phase 8A 父进程 supervisor 的独立 session/process-group deadline 才可称为硬 wall-time，后端调用前后检查仍不能单独称为硬超时。
- Phase 8A 只可在本地开发 supervisor/worker/状态协议并用无化学的短命令、挂起命令和子孙进程夹具测试；所有测试必须证明 timeout 后 TERM→grace→KILL、进程组回收、非零退出、无孤儿进程和原子失败证据。
- Phase 8A 服务器动作严格只读：只允许显式进入项目根、只 source `molenv.sh`、设置 `PYTHONDONTWRITEBYTECODE=1`，然后导入模块并用 `inspect` 检查版本、可调用对象、签名与默认值。禁止创建 `Mole`、调用 `build()`、实例化真实 RKS/UKS、调用 `kernel()`/`optimize()`、计算积分/梯度/色散或写入服务器。
- Phase 8A 不上传代码、不创建远端目录、不改 Phase 7 运行目录、不安装/升级依赖、不提交后台或调度任务。API 预检结果只能下载/记录为无私人坐标的 checked-in evidence。
- `EXECUTION_AUTHORIZED` 与私有配置中的量化执行授权必须保持 false。请求 JSON、CLI 参数、环境变量、依赖注入或测试 monkeypatch 均不得成为真实执行的公开旁路。
- Phase 8B 当前只可读取 Phase 6–8A 已登记的计划、四条 Phase 7 几何证据、runner/supervisor 契约和本地服务器知识，形成恰好一个候选、cation/neutral 两端点的最小 smoke 计划。不得连接服务器、上传、创建远端目录、运行 worker 或改动执行代码。
- Phase 8B 计划必须预先冻结候选 InChIKey 及选择理由、两端点输入哈希、唯一协议、线程/内存/timeout 上限、新版本化远端根、同步前后哈希、动态 D3(BJ) 验收、失败保留/清理、证据下载和强制停止条件；不得保留“现场再决定”的科学或安全参数。
- Phase 8B 规划裁定冻结 `QXHIEGFUWOLQIJ-UHFFFAOYSA-N`，cation/neutral 输入 SHA256 分别为 `097f08ab7c3f265efa8ee36c3fd45d72776c9bdcbd3de503baf8fe91561c12aa` 与 `e41e87daca3c7a74383364a427d277df5cf8a0aa70bff015c4cf432455f26bd0`；资源固定为单 worker 串行、4 个计算线程、整棵进程树 CPU affinity `0-3`、PySCF `max_memory=12000 MB` 软上限和整请求 `7200 s` hard wall-time。任何更换或扩大均须新计划和新授权。
- Phase 8B 规划阶段中 `EXECUTION_AUTHORIZED` 与所有私有量化执行位继续为 false。只有计划经用户再次明确确认后，才可另行更新 `AGENT.md` 与私有授权并执行已冻结的一个 smoke；“进入 Phase 8B”本身不得解释为该第二次授权。
- 每个 Phase 必须先写清范围、输入、输出、假设、风险、命令和验收门禁，再执行代码或数据操作。
- 每个 Phase 完成后，按 `prompt.md` 第 23 节报告完成项、读取文件、改动文件、科学假设、数据质量、命令、测试、未执行事项、门禁结论和下一步。

## 3. 互动式工作方式

- 采用逐步确认：一次只提出一个会实质改变科学口径、数据源、执行范围、服务器状态或交付结构的问题。
- 可通过只读检查自行获得的事实先检查，不把可发现信息反问用户。
- 做出不可逆选择、扩大 Phase、运行真实量化计算、连接服务器执行写操作、覆盖已有结果或提交 HPC 作业前，必须得到用户明确批准。
- 用户未回复时，只继续不依赖该答案的只读审计或文档整理，不越过门禁。

## 4. 文档先行

- 根级入口文档至少说明科学边界、数据契约、Phase 状态和复现方式。
- 开始实现某个模块前，先创建或更新对应规范文档；实现必须与文档一致。
- Phase 0 优先交付 `docs/SCIENCE_SCOPE.md`、`docs/LEGACY_AUDIT.md`、路径/数据源说明和 `PHASE_STATUS.md`，其中未知事实明确标记为待审计，不以猜测填充。
- 审计结论必须来自代码、配置、CSV/Parquet 表头、行数、主键、缺失率、重复/冲突和 SHA256 的实际检查，不能只转述旧报告。
- 任何暂未验证的数量、标签协议或历史性能必须写成“未验证”，不得写成事实。

## 5. 科学硬约束

- 反应口径：`NHC-H+ -> NHC + H+`。
- 兼容旧项目的标签：`(E_neutral - E_cation) * 627.509474 - 6.28 kcal/mol`。
- 同时保存不含质子常数的 `electronic_difference_kcal = (E_neutral - E_cation) * 627.509474`。
- 目标只能命名为 `dft_deprot_electronic_kcal` 或 `delta_e_deprot_dft_kcal`，不得称为 Gibbs 自由能。
- `lower_is_better: true` 必须在配置、代码、指标和测试中保持一致。
- 未算 Hessian 不拒绝电子能标签；不得伪造 ZPE、熵、热校正或局部极小点结论。
- InChIKey 是唯一主键；同一 InChIKey 不得跨训练/验证/测试；重复、标签冲突、协议混合必须显式审计并按契约拒绝。
- 若存在两端电子能，标签重算绝对误差超过 `0.02 kcal/mol` 时硬拒绝。
- family 必须保持 N1/N3、C4/C5 镜面对称 canonicalization；未知 family 效应为 0，退回全局校准。
- 原始 xTB（B0）始终是基线；B1/H1 只有通过诚实排名门禁才可晋级。允许最终结论为 xTB 已足够或证据不足。

## 6. 旧项目与来源优先级

- 旧项目主要本地来源由 `legacy_repo.root` 指定。实际使用前记录分支、commit SHA、remote、工作树状态和所有输入 SHA256。
- 用户指定的服务器知识 worktree 仅用于读取连接与 VASP/HPC 相关知识；除非用户另行指定，不把该 worktree 的业务数据默认混入 legacy 数据快照。
- `prompt.md` 列出的旧文件必须逐一核实存在性并实际读取；本地版本比 GitHub 更完整的内容可纳入审计，但来源、commit 和工作树状态必须清晰记录。
- 若本地文件含未提交改动，不能把它们冒充某个 Git commit 的内容；报告中分别记录 HEAD 与工作树差异。
- 需要比较 GitHub 时仅做只读 fetch/query；不得 fork 回写或修改旧仓库。

## 7. 本地与服务器操作

- 本地 macOS 只做编辑、只读审计、数据质量检查、轻量测试和报告；不得在本地运行量子化学计算。
- HPC 基本约束与连接方式应从用户指定的服务器知识 worktree 实际文档读取，不凭记忆编造。
- 未经用户明确批准，不执行服务器写操作、不启动/终止作业、不改环境、不上传或删除文件。
- 若获准连接 HPC，先做只读健康检查，并遵守本地私有配置中的 SSH alias、项目根、显式环境脚本、资源检查和代理回退规则。
- SSH 失败时先区分校园网直连与本地私有配置/服务器知识文档指定的 SOCKS5 代理，不能直接判定服务器故障。

## 8. DNS / HTTPS 调试

本机可能使用 Clash / sing-box / TUN fake-ip DNS。本地解析若返回 `198.18.x.x`，视为 fake-ip，不是公网真实记录。判断 Cloudflare、Nginx、HTTPS 或证书配置前至少比较：

```bash
dig domain +short
dig domain @1.1.1.1 +short
ssh server "dig domain +short"
dig +trace domain
```

## 9. 工程与数据安全

- 输出默认不可覆盖；`--overwrite` 必须显式指定，正式数据集与模型版本保持不可变。
- 所有输入记录路径、SHA256、来源、理论级别、标签定义和 protocol ID。
- 固定随机种子；预处理只在训练折拟合；未知类别 `handle_unknown=ignore`；不得泄漏测试折。
- CI 与单元测试使用小型合成 fixture，不依赖 HPC、PySCF、xTB 或大型生产数据。
- 不提交密钥、私人路径、服务器凭据、环境私密信息或生产大文件。
- 修改前检查工作树，保留用户已有改动；不使用破坏性 Git 或文件命令。

## 10. 历史 Phase 0 停止条件

只有以下事实均有证据且被记录后，才可建议 Phase 0 通过：

1. xTB target 的精确定义已核实；
2. DFT target、质子常数和 Hessian 边界已核实；
3. 实际可用高保真标签数、来源、重叠、冲突和协议一致性已核实；
4. 全量候选表行数、InChIKey 唯一性、family 来源和覆盖率已核实；
5. 指定旧代码与报告均已读取并形成非转述式审计；
6. 新仓库骨架、配置样例、科学范围、legacy 审计与 Phase 状态文档齐全；
7. 未执行任何被 Phase 0 禁止的计算或建模操作。

## 11. Phase 2 停止条件

只有以下事实均有证据且被记录后，才可建议 Phase 2 通过：

1. B0 与自由斜率 B1 均有测试覆盖且只使用已标注行拟合；
2. 完整 71 标签的仿射系数复现或明确解释旧结果差异；
3. LOOCV 为每个 InChIKey 生成且仅生成一条 OOF 预测；
4. axis-A/axis-B 分组验证无 InChIKey 或 held-out family 泄漏；
5. 排名方向、tie threshold、Top-M/K、NDCG、富集和 regret 定义有配置与测试；
6. 真实结果目录不可覆盖，输入/输出 SHA256、数据集版本、模型版本和 split manifest 完整；
7. size extrapolation 若缺少已验证尺寸字段，明确记为 unavailable，不得伪造；
8. 未执行 H1、正式全库评分、量化计算或服务器写操作。

## 12. Phase 3 停止条件

只有以下事实均有证据且被记录后，才可建议 Phase 3 通过：

1. H1 求解器在合成数据上恢复已知 family offset，且稀有 family 收缩强于高支持 family；
2. lambda 增大时 family effect 接近 0，lambda=0 的可识别情形接近 one-hot OLS；
3. 连续量中心化、family vocabulary 和超参数选择只来自各训练折；
4. LOOCV、axis-A、axis-B outer OOF 均覆盖 71/71 InChIKey，inner 选择不接触 outer test；
5. 未见 family effect 明确为 0、预测有限，并有单元测试；
6. 2,000 次最终 bootstrap 使用固定且已记录的 nested-CV penalty，失败数和 family 稳定性完整报告；
7. 模型保存/读取后预测逐位一致，秩亏/条件数/pseudoinverse 状态可审计；
8. 未执行 H2、Phase 4 晋级、正式全库评分、量化计算或服务器写操作。

## 13. Phase 4 停止条件

只有以下事实均有证据且被记录后，才可建议 Phase 4 通过：

1. Phase 1/2/3 evidence manifest、运行结果哈希、模型版本与共同 71-key 身份全部复核；
2. B0/B1/H1 只在完全对齐的冻结 OOF 行上比较，未重新拟合、重新调参或读取全库候选排名；
3. Spearman、Kendall、头部召回和 regret 的差值及置信区间按预注册 bootstrap 单元、种子和重复数生成；
4. B1 对 B0 与 H1 对 B1 的每一条门禁均独立记录 pass/fail/not-applicable 和实际阈值；
5. family collapse、held-out family 灾难性误差和 bootstrap offset 翻转使用写入 YAML 的明确规则，不按结果临时修改；
6. 最终结果严格为 `raw_xTB_wins`、`global_affine_wins`、`hierarchical_wins` 或 `insufficient_evidence` 之一；
7. `MODEL_CARD.md` 记录适用范围、失败模式、缺失 blind/size 验证、训练范围、哈希、裁决和禁止外推声明；
8. Phase 4 结果目录不可覆盖，输入/输出/源码 SHA256 与独立读回完整；
9. 未执行 H2、Phase 5 全库评分、量化计算、HPC 连接或服务器写操作。

## 14. Phase 5 停止条件

只有以下事实均有证据且被记录后，才可建议 Phase 5 通过：

1. 只用 Phase 4 晋级的 B0 生成正式排序；B1 校准字段与参数 bootstrap 不得被包装成新的排名模型；
2. 全量评分恰好覆盖 401,856 个唯一 InChIKey，排序方向为 lower-is-better，B0 排名与 v001 `xtb_rank` 逐行一致；
3. B1 校准、区间和 Top-K 概率明确标记为 companion/参数不确定度，并验证所有 bootstrap 斜率为正时排名不变；
4. baseline range、family seen/support、稀疏 family、bootstrap uncertainty、size 缺失和外推状态均逐行可审计；不得因预测有限而自动标记 `in_domain`；
5. `n_heavy_atoms`/`n_electrons` 全缺失时输出 `size_unavailable`，不得伪造尺寸或 size extrapolation 结论；
6. acquisition 排除全部 71 个已标注 key，无重复，批量大小、权重、配额、舍入、候选池和 tie-break 均来自 YAML 或明确规范；
7. 选点兼顾头部、截止线、family 多样性和 uncertain/OOD，记录 reason codes；rank shift 恒为零时不得虚构冲突收益；
8. `high_fidelity_batch_manifest.json` 只描述建议与电子能协议，明确 `submit_hpc=false`，不得触发外部动作；
9. 评分与选点结果不可覆盖，输入/输出/源码 SHA256、行数、排序、配额和独立读回完整；
10. 未运行量化计算、Hessian、HPC 连接、服务器写操作或作业提交。

## 15. Phase 6 停止条件

只有以下事实均有证据且被记录后，才可建议 Phase 6 本地计划门禁通过：

1. 只读取冻结的 v001 dataset/acquisition 及其证据，50 个 InChIKey 唯一且与 71 个已标注 key 零重叠；
2. `candidates.csv` 使用旧接口精确列名 `InChIKey`、`SMILES_cation`、`SMILES_neutral`，两端 SMILES 非空且逐行与 Phase 5 manifest 一致；
3. 50 条按确认矩阵分为 5×10，无重复、无遗漏，并保持总桶配额 `15/13/12/10`；
4. smoke 恰好 4 条、四个 acquisition bucket 各 1 条、全部属于 batch 01，并使用冻结 tie-break；
5. 协议锁定为气相 B3LYP-D3(BJ)/def2-SVP、geomeTRIC、阳离子 +1/单重态、中性 0/单重态、电子能-only、无 Hessian；
6. 输出明确 `geometry_status=not_generated`，目录中没有 XYZ、Molden、`freq.json`、电子能或其他伪计算产物；
7. legacy compatibility 同时记录 `blocked_no_xyz` 和 `blocked_runner_extra_steps`，不得宣称 execution-ready；
8. 计划包不可覆盖，输入/输出/源码 SHA256、key 集合/顺序、批次并集和独立读回完整；
9. 输出不含私人绝对路径、SSH 信息、凭据或可执行提交脚本；
10. 未运行 RDKit 几何、xTB、PySCF、Hessian，未连接/写入服务器，未传输文件或提交作业。

## 16. Phase 7 停止条件

只有以下事实均有证据且被记录后，才可建议 Phase 7 几何 smoke 与 runner 开发门禁通过：

1. Phase 6 PR 已合入 `main`，Phase 7 只读取不可变 `dft_input_plan_v001`、其 checked-in evidence 与恰好 4 条 smoke；
2. 服务器连接、项目根、环境脚本和运行目录来自被忽略的私有配置及已读取的服务器知识文档，tracked 文件中无私人路径、IP、alias 或凭据；
3. 远端只读预检验证 molecular 环境可导入 RDKit、legacy M2 两个脚本哈希匹配、目标版本目录不存在，并记录资源/并发状态；
4. 定向传输不含 `--delete`，只传 geometry bundle 的输入 CSV、manifest、M2 wrapper 与 validator；这些文件均在本地与远端逐文件 SHA256 一致，未执行的 runner 源码不上传服务器；
5. legacy M2 只处理 4 条 smoke，固定 ETKDGv3 seed 42、10 conformers、MMFF94（legacy UFF fallback）、`parallel=1`，退出码与失败清单均为通过状态；
6. 4 个 key 各有且仅有有效的 cation XYZ、neutral XYZ 和 `C2_carbene/N1/N3` atom-map JSON；原子数、元素、有限坐标、形式电荷、C2/N 索引、集合完整性和文件哈希全部独立验证；
7. legacy M2 未记录力场收敛码时必须明确标为 `force_field_convergence=unavailable_legacy_m2`，不得把可解析初始几何称为已验证局部极小点；
8. 几何产物下载到忽略的本地版本目录，远端与本地 12 个核心产物及审计文件哈希一致，既有 Phase 1–6 结果未改变；
9. 专用双端点 runner 对协议、状态、原子读入、色散硬失败、SCF/优化收敛、原子写入、resume、失败/退出码和标签公式有 mock 单测，但没有被本地或服务器执行；
10. 全程未运行 xTB、PySCF、Hessian、旧 M4、专用 DFT runner，未提交后台/调度作业，未扩展到 smoke 之外；Phase 8 DFT smoke 仍需新的明确授权。

## 17. Phase 8A 停止条件

只有以下事实均有证据且被记录后，才可建议 Phase 8A 硬超时与 API 兼容性门禁通过：

1. Phase 7 PR 已合入 `main`，Phase 8A 位于独立分支，先更新本文与实现计划再改代码或连接服务器；
2. 硬 wall-time 在父进程中使用独立会话/进程组，超时后先 TERM、有限 grace 后 KILL，并无条件 wait/reap；不得只依赖 Python signal、调用前后 monotonic 检查或后端合作；
3. 正常退出、非零退出、父进程挂起、忽略 TERM、产生子孙进程、输出过量、启动失败和 timeout 竞态均有无化学测试；测试结束后相关 PID/PGID 全部不存在；
4. supervisor 的请求、source、协议、输入、attempt 和输出身份继续 hash-closed；timeout 失败证据原子落盘，不跨 attempt 拼接端点，不把 partial 输出标记成功；
5. 公开 runner 与 worker 在任何 PySCF lazy import 前同时检查不可由用户输入覆盖的源码门禁；Phase 8A 中该门禁保持 false；
6. 服务器只读 API 预检记录 Python、PySCF、geomeTRIC、pyscf-dispersion 版本，确认 `geometric_solver.kernel` 的收敛返回/参数、D3(BJ) API 和 RKS/newton 接口存在；不创建分子或 mean-field 对象，不调用任何计算 kernel；
7. 私有服务器坐标继续只存在 ignored 配置；tracked evidence 无路径、alias、IP 或凭据；服务器与 Phase 7 结果零写入；
8. 全套 pytest、Ruff、format、mypy、pre-commit、构建、静态禁算扫描和独立审计通过；
9. 全程未运行 RDKit 几何、xTB、PySCF SCF/DFT、geomeTRIC 优化、Hessian、旧 M4 或专用 runner，未提交后台/调度作业；
10. Phase 8B 真实 DFT smoke 仍保持 blocked，必须由用户在审阅 Phase 8A 证据后另行明确授权。

## 18. Phase 8B 文档规划停止条件

只有以下事实均在计划中冻结后，才可向用户请求单候选真实 DFT smoke 的第二次明确授权：

1. Phase 8A PR #8 已合入 `main`，Phase 8B 位于独立分支，并在任何 Phase 8B 其他改动前先更新本文；
2. 当前阶段只写计划与决策证据，不连接服务器、不创建分子、不执行 runner、不改源码 gate、不产生量化结果；
3. 范围严格等于 Phase 7 四条强验证几何中的一个预注册 InChIKey，不允许运行时替换、回填第二候选或扩展到其余 46 条；
4. 计算严格等于 cation(+1, singlet) 和 neutral(0, singlet) 的 B3LYP-D3(BJ)/def2-SVP geomeTRIC 优化及各自最终同方法电子能；每端点只允许一次不运行 SCF、不改变总能量的 D3 分量动态复核，用于证明能量/梯度 hook 实际生效，不得再次加到标签；不含 Hessian、频率、ZPE、热化学、no-D3 对照、额外电子单点、radical 或 Molden；
5. 计划给出可核验的输入/源码/协议 hash 闭包、固定 attempt、独立 worker scratch、父进程 hard wall-time、独立 deadline watchdog、TERM/KILL/reap 证明和只接受同 attempt 精确成功文件集的规则；监督器异常死亡也不得让 worker 脱离期限；
6. CPU 线程与整树 affinity、内存、wall-time、SOSCF 唯一重试、输出上限和进程组合同均有固定数值或从只读证据推导的单一规则，不允许由请求临时扩大；
7. 远端只能使用全新固定相对根 `data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001`，执行前必须确认目标不存在；一次性私有 permit 必须绑定解析后的根、请求/输出路径和全部身份，并在 spawn 前原子消费，成功或失败均不可复用；禁止覆盖 Phase 7、全量部署、`rsync --delete`、调度提交或修改服务器环境。小时级真实 smoke 获得第二次授权后，只允许按服务器知识库规则启动一次自包含、记录 PID/SID 的 `setsid` 监督器与独立 watchdog；禁止其他后台任务或第二 attempt；
8. 动态验收明确区分 API 可用、D3(BJ) 实际启用、优化/SCF 显式收敛、有限能量、原子顺序与标签公式；任何一项不明即失败，不得把静态 Phase 8A 证据替代动态结果；
9. 计划规定执行前/后资源与文件哈希、无 Hessian/无额外计算证明、失败 envelope、远端/本地只读回读和 checked-in portable evidence；私人坐标不得进入 tracked 文件；
10. 计划写完后立即停止，向用户展示候选与全部资源/安全边界，并等待明确的“授权执行该冻结 smoke”；未收到该表述前所有执行位保持 false。
