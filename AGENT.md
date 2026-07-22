# AGENT.md — nhc-deprot-ranker 工作约束

本文件适用于本仓库中的所有设计、审计、代码、测试、报告和服务器相关操作。任务真值首先来自 `prompt.md`；若本文与 `prompt.md` 冲突，以更严格且不扩大当前 Phase 范围的规则为准，并先向用户确认。

## 1. 项目边界

- 本仓库是独立项目，只负责 NHC 前体脱质子电子能的 Part 1 排序与校准。
- 全量低保真指标是 `delta_e_deprot_xtb`/标准化后的 `xtb_deprot_kcal`；少量高保真标签是 B3LYP-D3(BJ)/def2-SVP 脱质子电子能。
- 旧项目仅作为只读数据、代码与报告来源。不得修改、回写、重构、提交或推送 `configs/legacy.local.yaml` 指定的本地旧仓库、服务器知识 worktree 或 GitHub 旧仓库。
- 不得把旧项目的大型 CSV、Parquet、XYZ、模型或计算产物复制进本仓库。
- 旧仓库真实绝对路径只能写入被 `.gitignore` 排除的 `configs/legacy.local.yaml`；示例与正式配置不得硬编码私人路径。

## 2. 当前阶段与阶段门禁

- Phase 0、Phase 1、Phase 2 与 Phase 3 已完成并合并到 `main`；Phase 4 已在隔离分支完成并等待审查。
- Phase 4 只读取冻结证据并裁定 `raw_xTB_wins`：B0 是生产排序默认，B1 是绝对能量校准 companion，H1 未晋级。
- 当前不得改写 Phase 2/3/4 结果，不得重新拟合或调参，不得执行 H2/尺寸消融、Phase 5 全库评分或选点，不运行 PySCF、xTB、Hessian，不提交 HPC 作业，也不生成虚构性能。
- Phase 5 必须在 Phase 4 通过、产生明确生产默认模型并获得用户明确确认后才能开始。
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
