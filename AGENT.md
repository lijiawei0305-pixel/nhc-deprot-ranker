# AGENT.md — nhc-deprot-ranker 工作约束

本文件适用于本仓库中的所有设计、审计、代码、测试、报告和服务器相关操作。任务真值首先来自 `prompt.md`；若本文与 `prompt.md` 冲突，以更严格且不扩大当前 Phase 范围的规则为准，并先向用户确认。

## 0. 交接入口

- 若你是接手本项目的新 agent（Codex 或其他），先读 `docs/HANDOFF_PHASE9B_FOR_NEXT_AGENT.md`。
  它是冷启动简报：冻结的科学身份、authority/permit 安全模型、Item 9 与 Item 10 的
  具体要求、真实执行为何被阻塞、以及本仓库已经踩过的坑。
- 本文件与 `PHASE_STATUS.md` 仍然是权威约束；交接文档只负责让你更快读懂它们。

## 1. 项目边界

- 本仓库是独立项目，只负责 NHC 前体脱质子电子能的 Part 1 排序与校准。
- 全量低保真指标是 `delta_e_deprot_xtb`/标准化后的 `xtb_deprot_kcal`；少量高保真标签是 B3LYP-D3(BJ)/def2-SVP 脱质子电子能。
- 旧项目仅作为只读数据、代码与报告来源。不得修改、回写、重构、提交或推送 `configs/legacy.local.yaml` 指定的本地旧仓库、服务器知识 worktree 或 GitHub 旧仓库。
- 不得把旧项目的大型 CSV、Parquet、XYZ、模型或计算产物复制进本仓库。
- 旧仓库真实绝对路径只能写入被 `.gitignore` 排除的 `configs/legacy.local.yaml`；示例与正式配置不得硬编码私人路径。

## 2. 当前阶段与阶段门禁

- Phase 0 至 Phase 8A 已合入 `main`；Phase 8B 规划由 PR #9 合入 `main`，其 rejected 执行事故、未来代码修正与关闭门回归已由 merge commit `7d65f72` 合入 `main`。用户授权的唯一 QXH 双端点 DFT smoke attempt 已消耗并被终态证据链拒绝；该授权不得复用，也不扩展到第二 attempt、其他候选或后续阶段。发布 rejected incident 已完成，不再是待办下一步。
- Phase 4 裁定 `raw_xTB_wins`：B0 是生产排序默认，B1 只能作为绝对能量校准 companion，H1 不得用于正式全库排序。
- Phase 5 只读取不可变的 `data/processed/v001`、B0/B1/Phase 4 决策及其 manifest；不得改写 Phase 1/2/3/4 结果，不得重新拟合或调参。
- Phase 5 可生成本地评分表、适用域审计、候选建议与无 Hessian DFT 互操作 manifest；不得运行 PySCF、xTB、Hessian，不得连接或写入 HPC，不得提交作业。
- Phase 5 必须在 Phase 4 通过、产生明确生产默认模型并获得用户明确确认后才能开始。
- Phase 5 已按用户确认的 B0/B1 双轨语义、Top-100 和 50 条 `15/13/12/10` 配额完成；任何真实高保真计算、上传服务器或提交作业都属于新阶段，仍需重新文档先行和明确授权。
- Phase 6 只把冻结的 50 条建议转换为本地、不可变、可校验的 legacy-ready CSV、5×10 分批计划、四桶 smoke 清单和协议/预期产物 manifest；必须写明 `geometry_generated=false`、`execution_ready=false`、`quantum_chemistry_run=false`、`server_write_authorized=false`、`submit_hpc=false`。
- 当前只有 Phase 7 的 4 条 smoke 具有强验证的 cation/neutral 初始 XYZ；其余 46 条仍未生成。不得在本地运行 RDKit/力场、xTB、PySCF 或 Hessian 来补齐，不得把完整 50 条计划包称为可直接运行的 DFT 输入。
- 旧 `dft_batch --skip-hessian` 的额外 ωB97X-D/def2-TZVP cation/neutral/radical 单点仍被禁用。专用双端点 runner 的唯一获准 attempt 已在执行协议层失败，未产生完整端点工作流或最终能量；execution gate 必须保持关闭。
- Phase 7 几何范围严格等于 Phase 6 `smoke.csv` 的 4 个 InChIKey；不得扩展到 batch 01 的其余 6 条或完整 50 条，不得运行 xTB、PySCF、Hessian、旧 M4 或专用 runner。
- Phase 7 只允许在私有配置指定的全新版本化服务器运行目录中写入；必须先确认目标不存在并完成只读环境/资源/legacy 文件哈希预检。禁止修改 `$WJW` 既有代码、环境、候选库或生产结果。
- 禁止使用旧仓库全量 `deploy`、`rsync --delete`、远端删除/覆盖或模糊目标同步。只可定向上传已登记的小型 smoke 输入/脚本，传输后必须核对真实目标和 SHA256。
- 服务器 M2 必须显式进入 `$WJW`、设置 `PYTHONPATH=$WJW` 并只 `source $WJW/env/envs/molenv.sh`；不得 `source ~/.bashrc`、混用软件栈或安装/升级依赖。
- 专用 runner 只允许 cation(+1, singlet) 与 neutral(0, singlet) 的气相 B3LYP-D3(BJ)/def2-SVP geomeTRIC 优化和最终电子能；接口中不得出现 Hessian、ZPE、热化学、ωB97X-D/def2-TZVP 单点、radical、Molden 或作业提交逻辑。当前 execution authorization 必须保持 false；只有 Phase 8A 父进程 supervisor 的独立 session/process-group deadline 才可称为硬 wall-time，后端调用前后检查仍不能单独称为硬超时。
- Phase 8A 只可在本地开发 supervisor/worker/状态协议并用无化学的短命令、挂起命令和子孙进程夹具测试；所有测试必须证明 timeout 后 TERM→grace→KILL、进程组回收、非零退出、无孤儿进程和原子失败证据。
- Phase 8A 服务器动作严格只读：只允许显式进入项目根、只 source `molenv.sh`、设置 `PYTHONDONTWRITEBYTECODE=1`，然后导入模块并用 `inspect` 检查版本、可调用对象、签名与默认值。禁止创建 `Mole`、调用 `build()`、实例化真实 RKS/UKS、调用 `kernel()`/`optimize()`、计算积分/梯度/色散或写入服务器。
- Phase 8A 不上传代码、不创建远端目录、不改 Phase 7 运行目录、不安装/升级依赖、不提交后台或调度任务。API 预检结果只能下载/记录为无私人坐标的 checked-in evidence。
- `EXECUTION_AUTHORIZED` 与私有配置中的量化执行授权必须保持 false。请求 JSON、CLI 参数、环境变量、依赖注入或测试 monkeypatch 均不得成为真实执行的公开旁路。
- Phase 8B 当前只允许只读事故取证、终态身份比较缺陷修复、关闭门回归和 rejected portable evidence。不得重写不可变远端 receipt、恢复 permit、再次启动 worker、替换候选或产生补算结果。
- Phase 8B 计划必须预先冻结候选 InChIKey 及选择理由、两端点输入哈希、唯一协议、线程/内存/timeout 上限、新版本化远端根、同步前后哈希、动态 D3(BJ) 验收、失败保留/清理、证据下载和强制停止条件；不得保留“现场再决定”的科学或安全参数。
- Phase 8B 规划裁定冻结 `QXHIEGFUWOLQIJ-UHFFFAOYSA-N`，cation/neutral 输入 SHA256 分别为 `097f08ab7c3f265efa8ee36c3fd45d72776c9bdcbd3de503baf8fe91561c12aa` 与 `e41e87daca3c7a74383364a427d277df5cf8a0aa70bff015c4cf432455f26bd0`；资源固定为单 worker 串行、4 个计算线程、整棵进程树 CPU affinity `0-3`、PySCF `max_memory=12000 MB` 软上限和整请求 `7200 s` hard wall-time。任何更换或扩大均须新计划和新授权。
- Phase 8B 的本地源码门、通用请求门与私有执行位均须保持 false。任何未来计算都必须使用新版本根、新 attempt、新 permit、新的文档先行计划和用户明确授权；本次 bundle、路径和许可永久不可复用。
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

上述规划条件已通过 PR #9 合入 `main`，且用户已明确授权执行该冻结 smoke。

## 19. Phase 8B 单次真实 smoke 执行停止条件

1. 本次授权只包含 `QXHIEGFUWOLQIJ-UHFFFAOYSA-N` 的 cation(+1, singlet) 后 neutral(0, singlet) 两端点；request ID 固定为 `phase8b-qxh-smoke-v001`，attempt ID 固定为 `attempt-phase8b-qxh-v001`；
2. 本文件必须是授权后的第一个文件改动；随后先实现通用安全能力并以关闭 gate 通过 fake backend/标准库进程测试、238+ 全套回归、Ruff、format、strict mypy、pre-commit、build、静态禁算扫描和独立审计；
3. 只有最终候选特异源码再次完成无化学测试与审计后，才可冻结 source hash，按无环顺序生成 true request、permit-excluding payload manifest、一次性私有 permit 与 outer transport inventory；
4. 一次性 permit 必须绑定解析后的固定远端根、request/output 路径、候选、attempt、输入、协议、资源和 payload hash，在任何 worker spawn 前原子且不可逆消费；成功、失败或 spawn error 均不得恢复；
5. 新鲜服务器只读 preflight 必须先通过计划中的版本/API/source hash、Phase 7 hash、`nproc/load/MemAvailable/disk/taskset/CPU 0-3`、进程 CWD/RSS 和目标不存在门禁；任一失败即停止且不得改名或放宽；
6. 远端写入只允许固定相对根 `data/runs/nhc_deprot_ranker_phase8b_dft_smoke_v001` 和 manifest 登记文件，使用定向传输并逐文件复核；禁止覆盖、`rsync --delete`、全库部署、环境修改或调度提交；
7. 真实运行严格为 one worker、cation→neutral、CPU affinity `0-3`、4 计算线程、PySCF `max_memory=12000 MB` 软上限、整请求 `7200 s` hard wall-time、10 s TERM grace 和 64 KiB/stream；不得现场增加资源；
8. 独立 chemistry-free watchdog、pre-import handshake、parent-death containment、PID/PGID/start-time 校验与 TERM/KILL/reap 必须生效；监督器死亡也不得让 worker 脱离 deadline；
9. 每端点必须动态证明 D3(BJ) energy/gradient hook、summary 算术与一次 zero-SCF D3 分量复核；必须显式收敛且有限；不得运行 Hessian、频率、ZPE、热化学、no-D3 对照、额外电子单点、radical、Molden 或第二 attempt；
10. 无论成功或失败，均先证明精确进程树消失、permit 已消费、远端/本地 hash 与 Phase 7 不变性，再下载 private result、关闭本地执行 gate、写 portable evidence 并停止；不得自动替换候选、重跑、摄取模型或进入下一阶段。

上述唯一 attempt 已消耗：远端 permit 为 consumed，compute claim 已线性化，但不可变 guardian receipt 因终态身份比较错误记录 `cleanup_failed` 且未绑定 claim hash。该 attempt 因此被拒绝。拒绝依据是不可变终态记录与冻结验收契约，不是冻结 postflight 的读取结论：冻结 postflight 在校验 receipt 之前，就已因 Phase 7 一个合法零字节 helper log 被通用 reader 拒绝而退出，从未产生 canonical postflight payload。没有完成任何端点级工作流，也没有产生或接受最终 SCF 能量、动态 D3 证据或脱质子标签。现存证据不足以证明 SCF/DFT kernel 从未被调用；只可将其状态记录为 `indeterminate`。本阶段只允许生成独立 rejected incident evidence、修复未来代码并保持 execution gate 关闭；再次执行必须重新计划和授权。

## 20. Phase 8B 之后的本地安全收尾边界

- 当前工作是纯本地安全收尾，计划见 `docs/PHASE8B_CLOSEOUT_PLAN.md`。它不连接服务器、不构造分子、不导入化学栈、不运行 worker、不打开任何执行门。
- 收尾只涵盖：当前状态入口文档修正、关闭陈旧私有 `server_write_authorized` 位、为 deploy 路径补齐与 bundle/launch 一致的 consumed latch、增加复活抵抗回归、按记录解释器跑质量门、隐私与边界检查。
- `phase8b_deploy.py` 此前既无源码执行门检查也无 consumed latch，是已退役授权链中最弱的一环。补齐后，deploy、bundle、launch 三条退役路径必须同时持有 latch，任何单模块 patch 都不得重开该链。
- consumed latch 必须是模块级 `Final` 常量，不得来自参数、环境变量、配置键或请求字段；必须在读取本地输入、构建部署计划、校验 permit 和调用注入式 command runner 之前无条件拒绝。
- 陈旧私有配置位一律不构成授权。即使 `configs/phase8b.local.yaml` 中 `server_write_authorized` 为 true，也不得据此复活 deploy/bundle/launch 或解释为用户许可；这一点必须由 checked-in 回归保证，而不是仅靠本地文件当前取值。
- 收尾不得重构 Phase 0–8A、不得刷新任何不可变 artifact 或证据哈希、不得为命名对称重写历史报告，也不处理 `pyproject.toml` 的 setuptools `project.license` 弃用警告。
- `docs/PHASE8B_DFT_SMOKE_V001.json` 必须保持逐字节不变，SHA256 仍为 `0767f20f5a5b9d0a6d87769b7de5e26010c5af9ecdd1a097fbfe4839319b6aa8`。
- 本机 `.venv` 是 macOS CPython 3.11.15，缺少 `os.waitid(..., WNOWAIT)`，supervisor 套件在该解释器上按设计失败关闭；这是平台能力限制，不得报告为代码回归。质量门须在提供该原语的本机 CPython 3.14.3 上运行并记录解释器。
- 软件门通过与科学结果不存在必须始终分开陈述。收尾中的任何测试结果都不改变 receipt 为 `cleanup_failed`、claim hash 为 null、无端点结果、无标签、kernel 状态为 `indeterminate` 的事实。
- 收尾完成后只有三个合法前进选项：归档在 rejected Phase 8B、规划全新只读服务器事故取证、规划全新计算阶段。三者都不由本收尾启动，均需用户单独决定。

## 21. Phase 9A — AIMNet2 预优化审计与设计边界

- 用户已冻结采用 **AIMNet2** 作为 cation/neutral 结构预优化模型。本阶段不重新选型，不比较 MACE、ANI、NequIP 或其他机器学习势。
- 目标流水线：`SMILES → RDKit ETKDGv3 → MMFF94(异常退 UFF) → cation/neutral 两端点 → AIMNet2 几何预优化 → PySCF B3LYP-D3(BJ)/def2-SVP 残余最终优化 → 最终电子能 → 脱质子电子能标签`。
- Phase 9A 只做只读审计、文档先行设计、接口设计、门禁设计、测试设计和后续阶段规划；不运行 AIMNet2、PySCF、xTB、MMFF/UFF，不连接服务器，不安装或下载，不创建几何，不创建 permit，不开启任何执行门。本阶段不写实现代码。
- AIMNet2 只负责预优化。它不得替代最终 PySCF 优化、不得替代最终电子能、不得直接产生标签、其能量不得进入标签公式、不得声称 AIMNet2 极小点即 B3LYP 极小点、不得声称未做频率分析的结构为频率确认极小点。
- PySCF 必须从 AIMNet2 结构重建 Mole 并继续优化至冻结收敛标准；"最后一步"不等于只跑一个 optimizer step。不得因 AIMNet2 已收敛而跳过梯度验收、放宽收敛、增加 maxsteps、改 SCF 算法或静默重启。
- **预优化器必须位于 runner source closure 之外**。two-endpoint runner 把精确 14 个文件哈希进 `runner_source_sha256` 并绑定 permit；把预优化器放进闭包会在每次修改时作废授权链，并把 ML 栈变成受保护 worker 的身份组成部分。预优化器作为 `preparation/` 下的上游生产者，产出 XYZ 与新 request，`two_endpoint.py` 不改动。
- cation 与 neutral 由**两个独立 SMILES 列**分别构建，代码中不存在程序化脱质子，**两端点索引无对应保证**（历史 8 例中 3 例出现 cation-map/neutral-index 失配）。必须逐端点验证，必须保持原子顺序，且必须采用 DFT 门的**有序**重原子序列比较，而非 Phase 7 的多重集比较。
- AIMNet2 与 PySCF 不得共用同一进程或同一环境。旧记录中 AIMNet2 位于独立 conda prefix（含 torch/ase），本项目当前只被允许使用 `molenv.sh` 的 `molecular` 环境（有 ase，无 torch、无 aimnet），且禁止混用软件栈与安装依赖。是否允许调用第二环境属于用户决策，不得由代理推定。
- 元素审计结论：Phase 7 smoke 为 `H C N O F`；71 标签与 50 acquisition 为 `H C N O F Cl Br`；401,856 全量为 `H C N O F S Cl Br`。任何层级均无超出该集合的元素。是否被安装权重支持须由 Phase 9A-R 实测确认，不得据发表文档断言。
- 元素受支持不等于化学域受支持。中性端点是单重态卡宾，通用有机训练集对其覆盖不足；C2 中心是最可能失真处，验证必须专门检查 C2 与 C2–N 键，并在可得时记录 C2 的逐原子 ensemble 分歧。
- 预优化后 `geometry_quality=initial_force_field_geometry` 不再成立。必须使用新的显式标签值与版本化的 endpoint-atom-map schema，且新值不得声称已验证局部极小点或频率验证。
- **必须记录的既往负面结果**：旧工程已在同一硬件与化学体系上测过 AIMNet2 预优化，n=12 公平对照中位加速仅 **1.10×**（最好 3.28×，最差 0.78×），并因"起始几何从来不是瓶颈"判为死路（DFT 从任何起点均需约 20 步）。该量与本项目晋级门 E1/E2 是同一个量。允许继续 Phase 9B（本项目基线自 MMFF94 起步，差距更大），但必须在测量前承认"不晋级"是可能且合法的结果，不得事后放宽门禁。
- 已记录证据只支持单一权重 `aimnet2_wb97m_d3_0.pt`；`_1`/`_2`/`_3` 无任何证据，且禁止下载。四成员 ensemble 不得假定存在。
- 单位必须显式转换并核验：ASE 接口返回 eV 与 eV/Å，XYZ 与 runner 使用 Å，PySCF 能量为 Hartree。Bohr/Å 或 eV/Hartree 混淆会产生看似收敛的错误结果。
- 每个端点必须显式传入总电荷（cation `+1`、neutral `0`），不得由文件名、目录名或原子数推断。任一端点失败即不得产生标签。
- Phase 8B 边界不变：失败关闭、零完整端点、零 DFT 标签、高保真标签仍为 71、旧 QXH 授权链永久不可复用。大量 Phase 8B 基础设施代码不代表已获得 DFT 结果。
- 前进路线与授权阶梯：`Phase 9A（本阶段）→ Phase 9A-R 只读服务器预检 → Phase 9B 双路线 smoke → Phase 9C 小型 pilot → Phase 10 分批生产`。每一步都是独立授权；文档规划不等于实现授权，实现不等于服务器写入授权，服务器写入不等于计算授权。

## 22. Phase 9B-U1 — 专用统一环境构建与审计边界

- 用户已冻结采用“离线 clone 项目 `mlff` prefix，再在全新
  `phase9b_unified_v001` prefix 中加入精确 PySCF 栈”的架构；不得修改
  `mlff`、`aimnet2`、`gpupyscf`、共享 `molecular` 或任何其他既有环境，
  不得拼接 `PYTHONPATH`，不得自动切换成双进程架构。
- 本轮允许的服务器写入严格限于此前不存在的
  `<PHASE9B_UNIFIED_ENV_ROOT>`、`<PRIVATE_WHEELHOUSE>` 及其中登记的构建、
  cache 与证据文件。任一目标已存在、是 symlink、有同名 registry entry
  或 staging 残留即 fail closed；不得覆盖、删除、复用或自行换成 v002。
- 下载只允许官方 PyPI / `files.pythonhosted.org` 上提示词登记的精确
  PySCF 2.13.1 wheel、geometric 1.1.1 sdist、pyscf-dispersion 1.5.0
  wheel，以及确有缺失时从 gpupyscf 冻结版本派生的 `networkx`/`six`
  精确 artifact。必须先落 wheelhouse、完整 SHA256 复核，再离线
  `--no-index --no-deps` 安装；禁止 model/Hugging Face/registry 下载。
- clone 后安装前必须证明 Python 3.11.15、torch 2.8.0+cu128、CUDA 12.8、
  `sm_70`、aimnet 0.2.0、ASE 3.29.0 与 source MLFF 保护包一致；resolver
  若想改变 Python、Torch、AIMNet、ASE、NumPy、SciPy、h5py、CUDA、Warp
  或 nvalchemi toolkit，立即停止。
- U1 能力 smoke 只允许在一张当前空闲 V100 上用现有 `_0` 权重，对冻结
  LBNP cation/neutral 各做一次 AIMNet2 energy+force 请求。不得优化坐标，
  不得构造或运行 PySCF kernel/gradient、geomeTRIC、D3，不得生成标签；
  无空闲 GPU 时不等待、不换卡、不重试。
- 四个既有环境必须在安装前后用相同 key set 做完整快照并逐项相等；
  任一漂移为终态失败，且不得尝试“修回去”。失败的新环境保留并标记
  `failed_incomplete_environment` 或 `rejected`，不得删除或复用。
- U1 结束时所有 public execution gates 仍为 false；不得做 Item 9
  Postflight、Item 10 rehearsal、permit 生成/placement、deploy、launch 或
  paired science。成功也只得到 `environment_validated`，当前 v8 身份仍是
  `execution_identity_not_yet_rebased` / `phase9b_not_authorized`。
- 当前 v8 request/resources/permit 不绑定统一解释器，preflight 仍调用未
  绑定 prefix 的 `python3`；后续须另开 gate-closed identity integration，
  诚实重基线 preflight/resources/request/permit，并将旧受阻身份记为
  `superseded_before_execution`。仅环境变化不构成 runner source v9。
- Phase 9B-U1 已执行并 fail closed：新 v001 prefix 成功 clone 且精确
  PySCF 栈安装、`pip check` 与 metadata 依赖验证通过，但 capability
  harness 预期 2 次 calculator invocation，真实 ASE energy/force 访问记录
  4 次，故状态为 `failed_incomplete_environment`。不得事后重解释为通过。
- 失败的 `<PHASE9B_UNIFIED_ENV_ROOT>` 与 `<PRIVATE_WHEELHOUSE>` 已保留；
  不得删除、修补、重跑或复用。四个既有环境 before/after 完全一致，
  所有 execution gate 仍 false，生产标签仍 71。唯一安全后续动作是停止；
  若用户另行授权，必须使用全新 v002 prefix/wheelhouse，并先冻结
  calculator invocation 与 energy/force property read 的精确定义。

## 23. Phase 9B-U2 — Unified Environment v002 终态边界

- U2 的 document-first 合同已由 PR #50 在任何服务器写入前合入 `main`。
  `ase_property_read`、`aimnet2ase_calculate_call` 与未测量的
  `base_model_forward_call` 是三个不可混用的计数；实际 capability 精确得到
  4 次 property read、4 次 `AIMNet2ASE.calculate()`、1 次 model load 和 2 个
  endpoint wrapper。
- v002 使用新的 prefix、wheelhouse、attempt cache、request/attempt identity，
  以 `--copy` offline clone 项目 MLFF，并重新下载和验证三份官方 artifact；
  未复制或 hardlink v001，未复用 v001 wheelhouse/cache/log/receipt。
- 精确 PySCF 栈、`pip check`、独立 metadata validation、保护包零漂移、两种
  import order、native map、端点有限性、坐标不变、cache/network/weight/target
  after evidence均完成。没有 optimizer、PySCF kernel/gradient、D3 或 label。
- U2 终态是 `rejected_environment`，不是 `validated`。Stage 0 protected
  snapshot 没有顶层 `state` 字段，Stage 4 snapshot 增加 `state=present`；虽然
  六项真实 tree digest/count/bytes/mtime、Python/conda/pip/METADATA/RECORD 均
  相同，canonical snapshot SHA 仍按冻结合同不相等。不得在 U2 中修补或改判。
- v002 prefix、wheelhouse、cache、logs、traces、receipts 必须永久保留；不得
  删除、修复、重试或复用，不得自动创建 v003。因为没有签发
  `UnifiedExecutionEnvironmentIdentity v2`，不得进入 identity integration、
  Postflight、closed-gate rehearsal 或 Phase 9B 科学执行。
- runner source 仍为 v8，SHA256 仍为
  `5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2`；
  十一个 public execution gates 全为 false，生产高保真标签仍为 71。

## 24. Phase 9B-U3 — Qualified snapshot metrology 与 v003 边界

- U3 是全新的 environment attempt 加全新的 qualified metrology schema，
  不是 U2 重试。U1 保持 `failed_incomplete_environment`，U2 保持
  `rejected_environment`；两者的 prefix、wheelhouse、cache、logs、receipts
  与结论均不可删除、修复、补写、复用或重解释。
- U1 失败于 calculator-call metrology contract；U2 的 exact build、native、
  calculator、endpoint、cache 与 network 均通过，但失败于 protected-snapshot
  metrology contract，且其 terminal `failure_assertion=null` 是第二个保留缺陷。
  两次均不是 dependency、native library 或 AIMNet2 incompatibility。
- U3 必须先把 `ProtectedObjectSnapshotV2`、stable identity projection、
  observation receipt、结构化 terminal failure 与真实 U2 regression 合入
  `main`。在 document-first PR 合入前不得对服务器进行任何 U3 写入。
- 合入后，六个 protected environment 必须在一个只读进程中由同一 helper
  连续捕获 A/B；全部 `state=present`、schema keyset、projection bytes 与 SHA
  精确相等，才允许创建 v003 prefix、wheelhouse 或 cache。失败状态为
  `failed_before_environment_creation`，且不得创建任何 v003 资源。
- target environment 不进入 protected unchanged gate。它使用独立
  `TargetEnvironmentLifecycleReceiptV1`，只比较 post-build baseline 与
  post-capability final；不得比较 pre-build absent 与 post-build present。
- v003 成功仍只签发 `UnifiedExecutionEnvironmentIdentity v3`。本轮禁止修改
  runner、request/resources/permit、deploy、placement、launch、optimizer、
  PySCF kernel/gradient、D3、Postflight、rehearsal 与 label。
- runner source 保持 v8 / SHA256
  `5f9f710a68904a76022afb99bcf46e2b3a5aa019ba0b40a19a227d9e08772fc2`；
  十一个 public execution gates 必须持续为 false，生产标签持续为 71。
- U3 document-first 合同已由 PR #52 合入。其后唯一一次只读 measurement
  qualification 在创建环境前 fail closed：六个对象的 A/B schema keyset、
  projection bytes 与 SHA 均精确相等，但 capture state 全部为 `invalid` 而非
  `present`。状态为 `failed_before_environment_creation`；v003 prefix、
  wheelhouse 与 cache 前后均不存在，未下载 artifact、未 build、未 import、
  未运行 capability。不得修 helper 后重跑、不得补写、不得自动创建 v004。
- 因 U3 未签发 identity，目前仍不存在 validated unified environment；不得进入
  Identity Integration、Postflight、rehearsal 或科学执行。唯一允许动作是发布
  已脱敏的 qualification failure evidence 后停止。

## 25. Phase 9B-U4 — Symlink-aware protected metrology 边界

- U1/U2/U3 状态分别固定为 `failed_incomplete_environment`、
  `rejected_environment`、`failed_before_environment_creation`。U4 使用全新的
  helper/request/attempt/v004 resources/receipts/identity；不得修改或重跑 v003。
- U3 根因已在代码中确认：`bin/python` 为 symlink 时在 Python probe、conda、
  pip、tree 前直接返回 invalid；命令失败和宽泛异常也被压成相同 sentinel，且
  public receipt 未保存分支原因。U3 结论有效但其 sentinel 不能单独证明分支。
- U4 只接受普通可执行 launcher，或最终解析到同一环境根内普通可执行文件的
  稳定有界 symlink chain。必须拒绝 dangling、loop、root escape、其他环境、
  系统 Python、非普通/不可执行 target，以及 probe 前后任何 inode/identity 漂移。
- V3 snapshot / V2 projection 不静默改变 U3 V2/V1 语义；diagnostic 位于 stable
  projection 外。present 必须 `failure=null`，所有其他状态必须有具体注册 code、
  stage、assertion 和 digest；未知异常必须显式升级。
- document-first PR 合入前禁止任何 SSH。合入后仅允许一次只读 Q4，对六对象
  各捕获 A/B；只有全部 present、diagnostic-free、projection/launcher/target
  identity 相等才可创建 v004。Q4 失败不得修 helper 或重跑，也不得创建 U5。
- 即使 v004 validated，本轮仍禁止 runner/request/resources/permit、deploy、
  launch、optimizer、PySCF、D3、Postflight、rehearsal 和 label。v8 SHA256、
  11 个 false gates 和 71 labels 必须保持不变。
- U4 document-first 合同已由 PR #54 合入。唯一一次只读 Q4 随后对六对象
  A/B 均返回 `CONDA_EXPLICIT_FAILED`；root containment 与 failed-projection
  equality为 true，但 state 均为 invalid。v004 三个资源路径前后均不存在。
- Q4 summary 未把 observation-level launcher chain、command return code 与精确
  failure stage 晋升为 portable evidence，而是输出失败 snapshot sentinel；此
  observability 限制必须公开保留，不得通过第二次 SSH、推断补写或 helper 修复。
  U4 终态为 `failed_before_environment_creation`，不得 build、重跑或创建 U5。

## 26. Phase 9B-U5 — Conda-metadata-native metrology 边界

- U1/U2/U3/U4 终态原样冻结。U5 是全新 helper/schema/Q5/request/attempt/v005
  identity；不修复、重跑或复用任何旧 attempt。
- U4 六对象均越过 launcher 与 Python probe 后报告 `CONDA_EXPLICIT_FAILED`，但
  portable receipt 未保存真实 command stage、return code 或 stderr。具体 CLI
  原因仍 unresolved，不得猜测；U4 仅证明 CLI-dependent capture 未通过，未证明
  protected environment 内容损坏。
- U5 protected identity 不得调用或 import conda/pip/mamba/micromamba，不得读取
  用户配置、registry、channel 或 cache。唯一子进程是已认证的环境内绝对 Python，
  以 `-I -B -c` 执行 stdlib-only probe。权威事实来自 `conda-meta/history`、全部
  package record、全部 `dist-info`、launcher/executable 与冻结 tree identity。
- capture 必须保存分阶段真实 evidence。Python probe 失败仍继续保存磁盘 metadata；
  后续失败不得用 sentinel 覆盖 launcher、probe、Conda 或 distribution evidence。
  每个非 present 结果必须有 code/stage/assertion/object/digests；不可表达的 evidence
  必须升级为 `PROTECTED_SNAPSHOT_EVIDENCE_INCOMPLETE`。
- document-first PR 合入前禁止 SSH。合入后仅一次 no-write/no-CLI Q5，对六对象
  各 A/B；全部 present、failure null、raw/normalized Conda inventory、dist-info、
  tree、projection 完全相等才可创建 v005。失败不得改 helper、重跑、放宽或建 U6。
- 若 Q5 因 helper 设计缺陷失败，不再创建统一环境 attempt；后续唯一设计方向是
  另行授权的 dual-environment / split-process assisted route。
- 即使 v005 validated，本轮仍禁止 runner/resources/request/permit、deploy、
  launch、optimizer、PySCF、D3、Postflight、rehearsal 和 label。runner v8 SHA、
  十一个 false gates 与 71 个生产标签保持不变。
- PR #56 已合入 document-first 合同。唯一一次 Q5 SSH 在任何 object capture 前的
  remote helper module initialization 失败：动态 module 未注册到 `sys.modules`，
  dataclass decoration 抛出 `AttributeError`。没有 launcher/probe/conda-meta/
  dist-info/tree evidence 可被诚实声称，因此终态是
  `failed_before_environment_creation` 加
  `PROTECTED_SNAPSHOT_EVIDENCE_INCOMPLETE`。
- 不得修复 loader、重跑 Q5、补用旧 receipt、创建 v005/U6 或继续 Integration。
  根据 U5 冻结决策，新的统一环境 attempt 到此终止；唯一允许的下一设计方向是
  另行授权的 dual-environment / split-process assisted route。
