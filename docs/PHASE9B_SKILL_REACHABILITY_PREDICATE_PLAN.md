# Skill 可达性判据（REACHABILITY_PREDICATE）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `.codex/skills/plan-nhc-aimnet2-workflow/` 增加一个 `UNREACHABLE` 进度状态与其判定算法 `REACHABILITY_PREDICATE`，使 skill 能够区分「这条 route 在推进」与「这条 route 的产出还能被下游门消费」，并在 `QUICK_ACTIVE_STAGE` 快查模式下强制执行该判据。

**Architecture:** 判据是一个三值谓词，作用在「活跃 route → 最近的下游 consumer gate」这条边上。它把冻结门表达式拆成合取项（conjunct），逐项判断该合取项是 `PERMANENTLY_FALSE` 还是只是 `NOT_YET`；永久性必须由一条被引用的冻结禁令条款（no-retry / no-substitution / no-queue-extension / exactly-once writer / immutable split）承载，而不是由「等得久」推出。判据只读少量 durable 状态文件（门自己读的那些），因此可以无条件塞进快查模式。新增一个只读脚本把该谓词机械化，并扩展报告校验器让 `UNREACHABLE` 能出现在归档 JSON 中且不能与 `HEALTHY` 共存。

**Tech Stack:** Markdown contract 文本（英文）、Python 3.11+ 标准库（`argparse`/`json`/`pathlib`，与现有三个 helper 同构、无第三方依赖）、pytest。

## Global Constraints

- Skill 正文（`SKILL.md`、`references/*.md`、`scripts/*.py` 的 docstring 与输出）一律用英文；状态名、schema 名、命令、单位必须逐字保留（`SKILL.md:23`）。本计划文档本身用中文。
- Skill 文风：密集、祈使句、无废话的 contract 体。禁止出现解释性散文、举例段落、"you should" 之类的口语。所有拟议片段必须能直接粘进现有文件而不破坏语气。
- Skill 是 read-only / design-only。新状态、新脚本、新判据都不得授权停止、发信号、重试、替换、重排、回收任何进程或资源（`SKILL.md:57-67`）。
- 新脚本必须与现有三个 helper 同构：纯本地、纯 stdlib、输入是 JSON 文件、输出是 JSON 到 stdout、退出码 0/1/2、定义自己的 `InputError(ValueError)`。不得进行远端读取、不得 SSH、不得访问 `/proc`、不得调用 `nvidia-smi`。
- Ruff：`line-length = 100`，`select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]`，`target-version = "py311"`。
- 不得修改 `PHASE_STATUS.md`。不得修改 `scripts/phase9b_*.py` 生产/流水线源码（本计划只读它们作为门表达式的权威来源）。
- 判据必须**不对称地**失败：证明不了「永久」就绝不输出 `UNREACHABLE`。漏报（继续算）成本有界，误报（错误停工）成本无界。

---

## 背景与动机（实施者必读）

### 缺口

`references/progress-audit.md:83-89` 定义的 5 个状态全部描述**被观测的工作本身**：

```
HEALTHY / WARNING / CRITICAL / TERMINAL / INCONCLUSIVE
```

没有任何一个能表达：**这条 route 完全健康、正在推进，但它所喂的下游门的前置条件已被某个 terminal 事件永久破坏，因此它的产出永远不可能被消费。**

### 真实事故（CLX 案例）

冻结的流水线状态机（`docs/PHASE9B_CONTINUOUS_PIPELINE_AUTOMATION.md:27-37`）：

```text
BIND_CONFIG → RUN_LANES → AUDIT_RESULTS → WAIT_FOR_9_OF_9_PASS
→ BUILD_DATASET_ONCE → WAIT_FOR_RESOURCES → TRAIN_ONCE
→ VALIDATE_AND_FREEZE → COMPLETE
```

门的实现在 `scripts/phase9b_aimnet2_finetune_watch.py:212-214`：

```python
"collection_complete": not failed_queue_states
    and complete == len(candidates)      # 9
    and all(item["exhausted"] for item in queue_states),
```

`complete` 的计数来自 `collection_snapshot`（同文件 `125-215`）：只有当候选 run root 下存在 `controller_exit_code`、其值为 0、`result.json:final_outcome == "PASS"` 且 `result.json:candidate` 匹配时才 `complete += 1`。

候选 `CLXFIGGGSODORK-UHFFFAOYSA-N`（lane C 队列首位，`docs/PHASE9B_PIPELINE_CONFIG_V001.json:96-99`）已 terminal timeout。仓库权威已经durable地写下了这一事实：`docs/PHASE9B_RBK_THROUGHPUT_CONTINUATION_V001.md:8` 称其为 "the timed-out `CLXFIGGGSODORK-UHFFFAOYSA-N` route"，`:27` 称 "current cohort remains blocked by CLX timeout"。

禁令是冻结的且多处冗余：

| 禁令 ID | 权威来源 | 内容 |
| --- | --- | --- |
| `NO_RETRY` | `docs/PHASE9B_PIPELINE_CONFIG_V001.json:7` | `"retry": false` |
| `NO_SUBSTITUTION` | `docs/PHASE9B_PIPELINE_CONFIG_V001.json:8` | `"candidate_replacement": false` |
| `NO_SUBSTITUTION` | `references/workflow-contract.md:68` | "An attempted candidate or model generation is never silently replaced." |
| `NO_QUEUE_EXTENSION` | `docs/PHASE9B_CONTINUOUS_PIPELINE_AUTOMATION.md:94-97` | "No queue is extended after launch. A candidate failure blocks collection and training; it is not replaced." |
| `EXACTLY_ONCE_WRITER` | `docs/PHASE9B_CONTINUOUS_PIPELINE_AUTOMATION.md:78-80` | "An existing orchestrator state root is never overwritten or reused." |
| `IMMUTABLE_MEMBERSHIP` | `references/workflow-contract.md:43` | "never move an InChIKey between splits" |

于是 `complete` 的上限恒为 8，`required_candidate_count` 恒为 9，`collection_complete` 恒为 False，`WAIT_FOR_9_OF_9_PASS` 永久死锁。而远端仍有 3 条 PySCF route 在 `RUN_LANES` 阶段烧掉约 84 个逻辑 CPU，喂的正是这道已经打不开的门。

用现有 skill 去查每次都返回 `HEALTHY`：route 在推进、没有违反任何冻结门。

### 实施者必须处理的两个变体（本次调查的关键发现）

CLX 的 terminal 事件会落到**哪里**，决定了故障表现完全不同。判据必须同时覆盖两者：

**变体 A — 门可见的失败（fail-closed 生效，但仍需 UNREACHABLE）。**
`scripts/phase9b_parent_level_autofill.py:680-684` 用 `timeout --signal=TERM --kill-after=30s` 包裹 worker，`:749-751` 在 `subprocess.run` 返回后写 `controller_exit_code`。超时返回 124（`docs/PHASE9B_GTHO_NEUTRAL_CONTINUATION_V001.md:8-9` 明确记录过 "the original controller exits with timeout status 124"）。此时：

- lane C watcher 在 `phase9b_parent_level_autofill.py:590-610` 的下一轮 audit 失败，写 `lane_terminal.json`（outcome `PREDECESSOR_AUDIT_FAILED` 或 `FINAL_CANDIDATE_AUDIT_FAILED`）并退出；
- fine-tune watcher 的 `failed_candidates` / `failed_queue_states` 非空，`phase9b_aimnet2_finetune_watch.py:441-451` 写 `COLLECTION_FAILED` terminal 并 `return 2`。

此时 fine-tune watcher 自身**是** `TERMINAL`。但 lane A/B/D 上仍在跑的 3 条 route 既不是 `TERMINAL` 也不是 `CRITICAL`，它们是 `UNREACHABLE`——它们的唯一消费者已经关门了。现有状态集在这里给出 `HEALTHY`。

**变体 B — 门不可见的失败（真正的静默死锁）。**
如果 CLX 的 run root 里从未出现 `controller_exit_code`（launcher 本身被杀、进程组被整体 kill、OOM、或 route 被 orchestrator 之外的手段终止），则：

- lane C watcher 卡在 `phase9b_parent_level_autofill.py:590` 的 `while not (watched / "controller_exit_code").exists(): sleep`，永远不写 `lane_terminal.json`，也永远不写 `queue_exhausted.json`；
- fine-tune watcher 里该候选 `terminal=False`，既不进 `complete` 也不进 `failed`；三个合取项里两个恒 False，watcher 永远轮询，不产生任何 terminal 文件。

变体 B 才是完全静默的：整条流水线没有任何一个文件说"我失败了"，而仓库文档说 CLX 已 timeout。判据必须能从「唯一被许可的 writer 已消失且按 exactly-once 规则不可重建」推出 `ABANDONED`，否则变体 B 永远只会被判成「还没到」。

### 雪上加霜

`references/progress-audit.md:16-22` 规定省 token 的请求一律按 `QUICK_ACTIVE_STAGE`，只看**活跃 stage** 的进度标记。而死掉的门在下游、在别的 lane、在另一个 state root 里——快查模式按构造就看不见它。这不是「快查恰好漏了」，是「快查必然漏」。因此判据必须在快查模式里强制执行，不能被 token 预算省掉。

---

## 拟议状态名与语义决策

**采用 `UNREACHABLE`。** 备选与否决理由：

| 候选名 | 否决理由 |
| --- | --- |
| `BLOCKED` | 已被 `report-schema.md:82` 的 gate status 占用，且其现有语义恰恰是**可恢复**的「已知未满足前置条件」。复用会把「还没满足」和「永远不可能满足」合并，正是本计划要拆开的东西。保留 `BLOCKED` 与 `UNREACHABLE` 的对立本身就是文档价值。 |
| `DEAD_END` / `ORPHANED` | 非 contract 语域；`ORPHANED` 暗示「没有所有者」，但这里 writer 和 owner 都在，只是消费者关门了。 |
| `NON_CONSUMABLE` | 描述产物属性而非 route 状态，与其余 5 个状态（都描述 route）不同轴。 |
| `BLOCKED_DOWNSTREAM` | 与 gate `BLOCKED` 视觉混淆，且未表达永久性。 |
| `STARVED` | 调度语义，指资源饥饿，方向相反。 |

`UNREACHABLE` 是图/活性分析的标准术语，语义精确（目标状态在允许的转移关系下不可达），且不与任何既有取值冲突。

**精确语义（写进 skill）：** 被观测的工作本身可能正在正常推进且未违反任何冻结门，但 `REACHABILITY_PREDICATE` 证明其最近的下游 consumer gate 在冻结禁令下**不存在任何被许可的转移序列**能使其成立，因此该工作的产出永远不可能被消费。

**优先级（插进现有偏序）：**

```
CRITICAL > UNREACHABLE > TERMINAL > WARNING > HEALTHY
```

- `CRITICAL > UNREACHABLE`：`CRITICAL` 意味着 identity/hash/manifest/split/科学门被证实违反，即证据基底本身可能已损坏。在损坏的证据上做「永久性」断言是不允许的。既有的 `CRITICAL takes precedence over TERMINAL`（`progress-audit.md:91`）出于同样理由，本条与之同构。
- `UNREACHABLE > TERMINAL`：`TERMINAL` 的定义要求**全部**预期工作都有结构化 terminal。若范围内还有活着但不可达的 route，`TERMINAL` 就是事实错误（变体 A 正是此形）。
- `UNREACHABLE > WARNING > HEALTHY`：不可达是已证实的终局，严于任何风险提示。
- `INCONCLUSIVE` 与之正交：判据本身算不出来时输出 `REACHABILITY_UNKNOWN`，它**禁止** `HEALTHY` 并至少产生 `WARNING`，但不自动把整份报告降成 `INCONCLUSIVE`（`INCONCLUSIVE` 保留给「没有任何观测可分类」）。

---

## File Structure

| 文件 | 责任 | 动作 |
| --- | --- | --- |
| `.codex/skills/plan-nhc-aimnet2-workflow/references/progress-audit.md` | 判据算法正文、`UNREACHABLE` 状态定义、优先级、快查强制条款 | 修改 §1、新增 §6、原 §6 顺延为 §7 并扩写 |
| `.codex/skills/plan-nhc-aimnet2-workflow/references/report-schema.md` | progress 状态枚举、gate 状态枚举、强制 gate `downstream_reachability` | 修改 §Mode and status、§Typed gates |
| `.codex/skills/plan-nhc-aimnet2-workflow/references/evidence-routing.md` | 快查模式的证据集合必须包含下游门这条边 | 修改 One-shot progress check 行、新增一条 expansion rule |
| `.codex/skills/plan-nhc-aimnet2-workflow/SKILL.md` | 路由入口、helper 清单、边界声明 | 修改 §Select the contract、helper 列表、§Enforce the planning boundary |
| `.codex/skills/plan-nhc-aimnet2-workflow/scripts/audit_gate_reachability.py` | 三值谓词的机械化实现 | 新建 |
| `.codex/skills/plan-nhc-aimnet2-workflow/scripts/validate_workflow_report.py` | 归档 JSON 的状态枚举与结构一致性 | 修改 `STATUS_BY_MODE`、`GATE_STATUSES`、新增 progress 强制 gate 规则 |
| `tests/test_plan_skill_gate_reachability.py` | 谓词与守卫的单元/回归测试，含 CLX 金样本与变异矩阵 | 新建 |
| `tests/test_plan_skill_reachability_docs.py` | skill 文本条款存在性与一致性测试 | 新建 |

> 不涉及：`reference-data-contract.md`、`model-generation-contract.md`、`aimnet2-handoff-promotion.md`、`server-performance-contract.md`。可达性是进度/报告语义，不是科学接受语义；把它塞进科学契约会污染那些文件已经写扎实的边界。资源浪费的量化仍走 `server-performance-contract.md` 既有的 THROUGHPUT_COLLECTION 证据，不需要新条款。

---

### Task 1: 在 `progress-audit.md` 写入可达性判据正文

**Files:**
- Modify: `.codex/skills/plan-nhc-aimnet2-workflow/references/progress-audit.md`（在第 79 行 `Idle capacity is not permission...` 段之后、第 81 行 `## 6. Use one status` 之前插入新 §6；原 §6 改编号为 §7）
- Test: `tests/test_plan_skill_reachability_docs.py`

**Interfaces:**
- Produces: 术语 `REACHABILITY_PREDICATE`、三值判据取值 `REACHABLE` / `UNREACHABLE` / `REACHABILITY_UNKNOWN`、成员分类 `ACCEPTED` / `FAILED` / `ABANDONED` / `PENDING` / `UNKNOWN`、合取项状态 `PERMANENTLY_FALSE` / `NOT_YET` / `SATISFIED`、禁令 ID `NO_RETRY` / `NO_SUBSTITUTION` / `NO_QUEUE_EXTENSION` / `EXACTLY_ONCE_WRITER` / `IMMUTABLE_MEMBERSHIP`。Task 3、4、5、6、7 全部复用这些字面量。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_plan_skill_reachability_docs.py`：

```python
"""The plan skill must carry the downstream reachability predicate."""

from __future__ import annotations

from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / ".codex/skills/plan-nhc-aimnet2-workflow"
PROGRESS_AUDIT = SKILL / "references/progress-audit.md"


def test_progress_audit_defines_the_reachability_predicate() -> None:
    text = PROGRESS_AUDIT.read_text(encoding="utf-8")
    for token in (
        "## 6. Prove downstream reachability",
        "REACHABILITY_PREDICATE",
        "REACHABLE",
        "UNREACHABLE",
        "REACHABILITY_UNKNOWN",
        "ACCEPTED",
        "FAILED",
        "ABANDONED",
        "PENDING",
        "PERMANENTLY_FALSE",
        "NO_RETRY",
        "NO_SUBSTITUTION",
        "NO_QUEUE_EXTENSION",
        "EXACTLY_ONCE_WRITER",
        "IMMUTABLE_MEMBERSHIP",
    ):
        assert token in text, token


def test_progress_audit_separates_not_yet_from_never() -> None:
    text = PROGRESS_AUDIT.read_text(encoding="utf-8")
    assert "a permitted action can still satisfy the prerequisite" in text
    assert "no permitted action exists" in text
    assert "exceeded deadline alone proves nothing here" in text


def test_reachability_verdict_never_authorizes_mutation() -> None:
    text = PROGRESS_AUDIT.read_text(encoding="utf-8")
    assert "It never authorizes stopping, signalling, retrying, replacing," in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_plan_skill_reachability_docs.py -v`
Expected: FAIL，三个测试全部 `AssertionError`（`## 6. Prove downstream reachability` 等 token 不存在）。

- [ ] **Step 3: 插入新 §6**

在 `references/progress-audit.md` 第 79 行之后、`## 6. Use one status` 之前插入（英文、contract 体）：

````markdown
## 6. Prove downstream reachability

A route that advances is not a route whose product can be consumed. Before
assigning a status, evaluate `REACHABILITY_PREDICATE` for the nearest downstream
consumer gate of every in-scope active route.

Resolve four inputs, all from durable state:

1. the gate expression and its conjuncts, from the SHA256-bound deployed source
   or the frozen automation contract; never from memory, a log, or a summary;
2. the frozen member set and required count, from the split or configuration
   authority bound by its own SHA256;
3. one durable terminal fact per member and one durable writer fact per
   conjunct writer;
4. the prohibition clauses that would make a false conjunct permanent.

Classify every member:

```text
ACCEPTED  : a durable terminal equals the gate's accept value
FAILED    : a durable terminal exists and is not the accept value
ABANDONED : no durable terminal, its only permitted writer is gone, and the
            exactly-once rule forbids recreating that writer
PENDING   : no durable terminal and a permitted writer may still produce one
UNKNOWN   : the terminal fact is unresolved
```

The accepted ceiling is `ACCEPTED` plus `PENDING` plus `UNKNOWN` plus the
`FAILED` and `ABANDONED` members covered by an authorized continuation. Classify
every conjunct:

```text
SATISFIED         : the conjunct is currently true
NOT_YET           : the conjunct is false and a permitted transition can flip it
PERMANENTLY_FALSE : the conjunct is false and no permitted transition can flip it
```

A counting conjunct is `PERMANENTLY_FALSE` when the accepted ceiling is below the
required count. A writer-owned conjunct is `PERMANENTLY_FALSE` when its evidence
file is absent, its only permitted writer is gone, and that writer is
unrecreatable. An irreversible-negative conjunct is `PERMANENTLY_FALSE` once its
forbidden evidence exists and no authorization reopens the writer.

Return exactly one verdict:

```text
REACHABLE            : a permitted transition sequence can still satisfy the gate
UNREACHABLE          : no permitted transition sequence can satisfy the gate
REACHABILITY_UNKNOWN : a required input is unresolved or conflicting
```

Return `UNREACHABLE` only when every condition holds:

- the gate expression is bound to the digest of the deployed source, not of an
  adopt-compatible sibling that is not the running one;
- at least one conjunct is `PERMANENTLY_FALSE`;
- every fact supporting that conjunct is durable evidence;
- the permanence is carried by at least one quoted frozen prohibition clause
  with its path and line, drawn from `NO_RETRY`, `NO_SUBSTITUTION`,
  `NO_QUEUE_EXTENSION`, `EXACTLY_ONCE_WRITER`, or `IMMUTABLE_MEMBERSHIP`;
- no higher-precedence authority authorizes a continuation, exception, or
  re-scope for the failing member or writer.

Otherwise return `REACHABILITY_UNKNOWN`. `BLOCKED` means a permitted action can
still satisfy the prerequisite; `UNREACHABLE` means no permitted action exists.
Never convert a slow, waiting, resource-starved, or overdue observation into
`UNREACHABLE`. A log line, mtime, absent PID, elapsed time, or exceeded deadline
alone proves nothing here. A member past its wall limit whose writer has not yet
written its terminal is `PENDING`; report it under `not_yet`.

Prefer [scripts/audit_gate_reachability.py](../scripts/audit_gate_reachability.py)
over a hand-evaluated predicate whenever its input contract applies.

`UNREACHABLE` is a report status. It never authorizes stopping, signalling,
retrying, replacing, rescheduling, or reclaiming any route, watcher, queue, or
resource. Report the affected routes, their occupied resource envelope, the
proved conjunct, its prohibition clause, and exactly one next permitted action.
````

- [ ] **Step 4: 把原 §6 重编号为 §7**

将 `## 6. Use one status` 改为 `## 7. Use one status`。本步骤不改该节内容（内容在 Task 2 改）。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_plan_skill_reachability_docs.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 6: Commit**

```bash
git add .codex/skills/plan-nhc-aimnet2-workflow/references/progress-audit.md \
        tests/test_plan_skill_reachability_docs.py
git commit -m "docs(skill): add downstream reachability predicate to progress audit"
```

---

### Task 2: 定义 `UNREACHABLE` 状态、优先级与快查强制条款

**Files:**
- Modify: `.codex/skills/plan-nhc-aimnet2-workflow/references/progress-audit.md:16-22`（快查条款）和 `§7. Use one status`
- Modify: `.codex/skills/plan-nhc-aimnet2-workflow/references/report-schema.md:8-15`（progress 枚举）、`:17-34`（precedence）、`:77-100`（gate 形状与枚举）
- Test: `tests/test_plan_skill_reachability_docs.py`

**Interfaces:**
- Consumes: Task 1 的 `REACHABILITY_PREDICATE`、三值判据取值。
- Produces: progress 顶层状态 `UNREACHABLE`；gate status 取值 `UNREACHABLE`；强制 gate id 字面量 `downstream_reachability`。Task 3 的校验器与 Task 7 的回归测试依赖这两个字面量。

- [ ] **Step 1: 追加失败测试**

在 `tests/test_plan_skill_reachability_docs.py` 末尾追加：

```python
REPORT_SCHEMA = SKILL / "references/report-schema.md"


def test_progress_status_set_contains_unreachable() -> None:
    text = PROGRESS_AUDIT.read_text(encoding="utf-8")
    assert "- UNREACHABLE: the observed work may itself be advancing" in text
    assert "CRITICAL takes precedence over UNREACHABLE" in text
    assert "UNREACHABLE takes precedence over TERMINAL" in text
    assert "REACHABILITY_UNKNOWN forbids HEALTHY" in text


def test_quick_mode_cannot_skip_the_predicate() -> None:
    text = PROGRESS_AUDIT.read_text(encoding="utf-8")
    assert "`QUICK_ACTIVE_STAGE` always executes `REACHABILITY_PREDICATE`" in text
    assert "may never mark the predicate `not_applicable` or `not_run`" in text


def test_report_schema_carries_the_new_status_and_gate() -> None:
    text = REPORT_SCHEMA.read_text(encoding="utf-8")
    assert "HEALTHY | WARNING | UNREACHABLE | CRITICAL | TERMINAL | INCONCLUSIVE" in text
    assert '"status": "PASS | FAIL | BLOCKED | UNREACHABLE | INCONCLUSIVE | NOT_APPLICABLE"' in text
    assert "downstream_reachability" in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_plan_skill_reachability_docs.py -v`
Expected: FAIL，新增的 3 个测试报 `AssertionError`。

- [ ] **Step 3: 改 `progress-audit.md` §1 的快查条款**

在第 22 行 `not_applicable` rather than expanding the audit.` 之后插入一段：

```markdown
`QUICK_ACTIVE_STAGE` always executes `REACHABILITY_PREDICATE` for the active
stage's nearest downstream consumer gate. A token budget may reduce sampling
breadth; it may never mark the predicate `not_applicable` or `not_run`. The
predicate reads only durable state the gate already reads: one configuration,
one member authority, one terminal fact per member, and one writer fact per
conjunct. It needs no second sampling window, no CPU-time delta, no process
walk, and no GPU probe, so its cost is bounded by cohort size and is below the
cost of the process sampling quick mode already performs. Quick mode inspects
only the active stage, which is exactly where an already-unsatisfiable
downstream gate is invisible.
```

- [ ] **Step 4: 改 `progress-audit.md` §7 的状态清单与优先级**

在 `- TERMINAL: ...` 与 `- INCONCLUSIVE: ...` 之间插入：

```markdown
- UNREACHABLE: the observed work may itself be advancing without violating a
  frozen gate, but `REACHABILITY_PREDICATE` proves that its nearest downstream
  consumer gate can never be satisfied, so this work can never be consumed.
```

将原第 91 行 `CRITICAL takes precedence over TERMINAL when a supposedly terminal route has invalid evidence. INCONCLUSIVE is for missing observation, not a known failure.` 整段替换为：

```markdown
`CRITICAL` takes precedence over `UNREACHABLE`, because a violated identity,
hash, manifest, or scientific gate can invalidate the evidence a permanence
claim rests on. `UNREACHABLE` takes precedence over `TERMINAL`, `WARNING`, and
`HEALTHY`. `CRITICAL` takes precedence over `TERMINAL` when a supposedly
terminal route has invalid evidence. Never report `HEALTHY` while any in-scope
verdict is `UNREACHABLE`. A verdict of `REACHABILITY_UNKNOWN` forbids `HEALTHY`
and yields at least `WARNING`; it is `INCONCLUSIVE` only when no other
observation in scope can be classified either. `INCONCLUSIVE` is for missing
observation, not a known failure and not a proved dead end.
```

- [ ] **Step 5: 改 `report-schema.md` 的枚举与 precedence**

第 13-14 行改为：

```text
progress:
  HEALTHY | WARNING | UNREACHABLE | CRITICAL | TERMINAL | INCONCLUSIVE
```

precedence 第 4 条（第 27-31 行）整体替换为：

```markdown
4. For progress, a proved identity, integrity, manifest, or scientific failure
   is `CRITICAL`. A proved `UNREACHABLE` reachability verdict outranks
   `TERMINAL`, `WARNING`, and `HEALTHY`. Use `TERMINAL` only when structured
   terminal closure is verified; a claimed terminal with invalid closure
   evidence is `CRITICAL`. Otherwise prefer `WARNING` over `HEALTHY` whenever a
   frozen resource, deadline, evidence-closure, or unresolved-reachability risk
   exists.
```

- [ ] **Step 6: 改 `report-schema.md` 的 typed gate**

第 82 行改为：

```json
  "status": "PASS | FAIL | BLOCKED | UNREACHABLE | INCONCLUSIVE | NOT_APPLICABLE",
```

第 98-100 行整段替换为：

```markdown
The gate status is `BLOCKED` for a known unmet prerequisite that a permitted
action can still satisfy, `UNREACHABLE` for a prerequisite that no permitted
action can satisfy under the frozen prohibitions, `INCONCLUSIVE` for
insufficient or conflicting evidence, and `NOT_APPLICABLE` only when the
criterion does not belong to the selected scope.

Every `progress` report carries exactly one gate whose `id` is
`downstream_reachability`. Its `criterion` names the evaluated downstream gate,
its `observations` carry one entry per conjunct with that conjunct's state, and
its `missing` carries the unresolved reachability inputs. When its status is
`UNREACHABLE`, its `evidence` binds the digest of the deployed gate expression
and at least one quoted prohibition clause. A top-level `UNREACHABLE` requires
this gate to be `UNREACHABLE`, and this gate being `UNREACHABLE` forbids a
top-level `HEALTHY`, `WARNING`, or `TERMINAL`.
```

- [ ] **Step 7: 运行测试确认通过**

Run: `python -m pytest tests/test_plan_skill_reachability_docs.py -v`
Expected: PASS（6 passed）。

- [ ] **Step 8: Commit**

```bash
git add .codex/skills/plan-nhc-aimnet2-workflow/references/progress-audit.md \
        .codex/skills/plan-nhc-aimnet2-workflow/references/report-schema.md \
        tests/test_plan_skill_reachability_docs.py
git commit -m "docs(skill): add UNREACHABLE status, precedence, and quick-mode mandate"
```

---

### Task 3: 让报告校验器接受并强制 `UNREACHABLE`

**Files:**
- Modify: `.codex/skills/plan-nhc-aimnet2-workflow/scripts/validate_workflow_report.py:12-25`、`:111-119`
- Test: `tests/test_plan_skill_gate_reachability.py`

**Interfaces:**
- Consumes: Task 2 的 `UNREACHABLE`、`downstream_reachability`。
- Produces: `validate_report(value: Any) -> list[str]`（签名不变）。新增校验错误串 `"progress report must contain a downstream_reachability gate"`、`"top-level UNREACHABLE requires the downstream_reachability gate to be UNREACHABLE"`、`"downstream_reachability gate is UNREACHABLE but status is {status!r}"`。Task 7 依赖这三个串。

注意：`REQUIRED_TOP_LEVEL` 保持不变。新状态通过 `gates` 数组承载，不新增顶层字段，因此不破坏任何既有归档报告的字段集。同时现有的 `positive_status` 检查（第 111-119 行）已经天然禁止「`HEALTHY` + 任何非 `PASS`/`NOT_APPLICABLE` 的 gate」，这条约束对新 gate 直接生效，无需另写。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_plan_skill_gate_reachability.py`：

```python
"""Unit tests for the plan skill's reachability helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

SKILL_SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / ".codex/skills/plan-nhc-aimnet2-workflow/scripts"
)


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SKILL_SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load("validate_workflow_report")


def _gate(status: str) -> dict[str, Any]:
    return {
        "id": "downstream_reachability",
        "stage": "RUN_LANES",
        "criterion": "collection_complete stays satisfiable",
        "status": status,
        "observations": [],
        "evidence": [],
        "missing": [],
        "impact": "decides whether active routes can be consumed",
        "next_permitted_action": "not_applicable",
    }


def _report(status: str, gates: list[dict[str, Any]]) -> dict[str, Any]:
    body: dict[str, Any] = dict.fromkeys(validator.REQUIRED_TOP_LEVEL, "not_applicable")
    body.update(
        {
            "mode": "progress",
            "status": status,
            "gates": gates,
            "assumptions": [],
            "findings": [],
            "blockers": [],
            "required_user_decisions": [],
            "privacy_redactions": [],
            "next_permitted_action": "take one bounded read-only snapshot",
        }
    )
    return body


def test_unreachable_is_a_valid_progress_status() -> None:
    errors = validator.validate_report(_report("UNREACHABLE", [_gate("UNREACHABLE")]))
    assert errors == []


def test_progress_report_requires_the_reachability_gate() -> None:
    errors = validator.validate_report(_report("HEALTHY", []))
    assert "progress report must contain a downstream_reachability gate" in errors


def test_top_level_unreachable_requires_the_gate_to_agree() -> None:
    errors = validator.validate_report(_report("UNREACHABLE", [_gate("PASS")]))
    assert (
        "top-level UNREACHABLE requires the downstream_reachability gate to be UNREACHABLE"
        in errors
    )


def test_unreachable_gate_forbids_a_softer_top_level_status() -> None:
    for status in ("HEALTHY", "WARNING", "TERMINAL"):
        errors = validator.validate_report(_report(status, [_gate("UNREACHABLE")]))
        assert (
            f"downstream_reachability gate is UNREACHABLE but status is {status!r}" in errors
        )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_plan_skill_gate_reachability.py -v`
Expected: FAIL，`test_unreachable_is_a_valid_progress_status` 报 `status 'UNREACHABLE' is invalid for mode 'progress'`，其余三个报缺少期望错误串。

- [ ] **Step 3: 改枚举**

`validate_workflow_report.py` 第 15-21 行改为：

```python
    "progress": {
        "HEALTHY",
        "WARNING",
        "UNREACHABLE",
        "CRITICAL",
        "TERMINAL",
        "INCONCLUSIVE",
    },
```

第 25 行改为：

```python
GATE_STATUSES = {"PASS", "FAIL", "BLOCKED", "UNREACHABLE", "INCONCLUSIVE", "NOT_APPLICABLE"}
```

在第 25 行之后新增：

```python
REACHABILITY_GATE_ID = "downstream_reachability"
SOFTER_THAN_UNREACHABLE = {"HEALTHY", "WARNING", "TERMINAL"}
```

- [ ] **Step 4: 加结构规则**

在 `validate_workflow_report` 中，紧接现有 `positive_status` 块（第 111-119 行）之后、`next_action` 块之前插入：

```python
    if mode == "progress" and isinstance(gates, list):
        reachability = [
            gate
            for gate in gates
            if isinstance(gate, dict) and gate.get("id") == REACHABILITY_GATE_ID
        ]
        if not reachability:
            errors.append(
                f"progress report must contain a {REACHABILITY_GATE_ID} gate"
            )
        else:
            gate_status = reachability[0].get("status")
            if status == "UNREACHABLE" and gate_status != "UNREACHABLE":
                errors.append(
                    f"top-level UNREACHABLE requires the {REACHABILITY_GATE_ID} "
                    "gate to be UNREACHABLE"
                )
            if gate_status == "UNREACHABLE" and status in SOFTER_THAN_UNREACHABLE:
                errors.append(
                    f"{REACHABILITY_GATE_ID} gate is UNREACHABLE but status is {status!r}"
                )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_plan_skill_gate_reachability.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 6: 静态检查**

Run: `python -m ruff check .codex/skills/plan-nhc-aimnet2-workflow/scripts/validate_workflow_report.py`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add .codex/skills/plan-nhc-aimnet2-workflow/scripts/validate_workflow_report.py \
        tests/test_plan_skill_gate_reachability.py
git commit -m "feat(skill): validate UNREACHABLE status and the reachability gate"
```

---

### Task 4: 新建 `audit_gate_reachability.py` 的谓词核心

**Files:**
- Create: `.codex/skills/plan-nhc-aimnet2-workflow/scripts/audit_gate_reachability.py`
- Test: `tests/test_plan_skill_gate_reachability.py`（追加）

**Interfaces:**
- Consumes: Task 1 的字面量。
- Produces:
  - `class InputError(ValueError)`
  - `classify_member(member: dict[str, Any]) -> str`，返回 `ACCEPTED` / `FAILED` / `ABANDONED` / `PENDING` / `UNKNOWN`
  - `evaluate_conjunct(conjunct: dict[str, Any], members: list[dict[str, Any]], required: int) -> dict[str, Any]`，返回 `{"id", "kind", "state", "reason", "supporting_member_ids", "supporting_writer_ids"}`
  - `decide(payload: dict[str, Any]) -> dict[str, Any]`，返回 `{"schema", "gate_id", "verdict", "conjuncts", "not_yet", "missing", "permanence_clauses"}`
  - 常量 `OUTPUT_SCHEMA = "nhc_gate_reachability_v1"`、`INPUT_SCHEMA = "nhc_gate_reachability_input_v1"`
  Task 5 在 `decide` 上加守卫，Task 7 用这些名字构造金样本。成员字段 `writer_evidence` 只在成员被判为 `ABANDONED` 时才被 Task 5 的守卫读取；`terminal` 为 `FAILED` 时读 `terminal_evidence`。两者都可以为 `null`，代价是判据降级为 `REACHABILITY_UNKNOWN`。

输入契约（写进脚本 docstring 与 `--help`）：

```json
{
  "schema": "nhc_gate_reachability_input_v1",
  "gate": {
    "id": "collection_complete",
    "expression_source": {
      "path_projection": "<runner>:212-214",
      "sha256": "<64 hex digest of the deployed source>"
    },
    "conjuncts": [
      {"id": "no_failed_queue_states", "kind": "irreversible_negative",
       "satisfied": true, "reopened_by_authorization": false,
       "evidence": {"kind": "file", "path_projection": "..."}},
      {"id": "complete_equals_required", "kind": "member_count"},
      {"id": "all_queues_exhausted", "kind": "writer_evidence", "satisfied": false,
       "writers": [{"id": "lane_c", "state": "GONE", "recreatable": false,
                    "evidence": {"kind": "observation", "path_projection": "..."}}]}
    ]
  },
  "required_member_count": 9,
  "members": [
    {"id": "CLXFIGGGSODORK-UHFFFAOYSA-N", "terminal": "FAILED",
     "terminal_evidence": {"kind": "file", "path_projection": "...",
                           "detail": "controller_exit_code=124"},
     "writer_state": "GONE", "writer_recreatable": false,
     "writer_evidence": null,
     "authorized_continuation": null}
  ],
  "prohibitions": [
    {"id": "NO_RETRY", "path_projection": "docs/PHASE9B_PIPELINE_CONFIG_V001.json",
     "field": "retry", "value": false}
  ]
}
```

- [ ] **Step 1: 写失败测试**

在 `tests/test_plan_skill_gate_reachability.py` 顶部 `validator = _load(...)` 之后加载模块，并在文件末尾追加：

```python
reachability = _load("audit_gate_reachability")


def _member(
    member_id: str,
    terminal: str,
    *,
    writer_state: str = "ALIVE",
    writer_recreatable: bool = True,
    continuation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": member_id,
        "terminal": terminal,
        "terminal_evidence": (
            None
            if terminal == "NONE"
            else {"kind": "file", "path_projection": f"runs/{member_id}/controller_exit_code"}
        ),
        "writer_state": writer_state,
        "writer_recreatable": writer_recreatable,
        "authorized_continuation": continuation,
    }


def test_classify_member_covers_every_state() -> None:
    assert reachability.classify_member(_member("a", "ACCEPTED")) == "ACCEPTED"
    assert reachability.classify_member(_member("b", "FAILED")) == "FAILED"
    assert reachability.classify_member(_member("c", "NONE")) == "PENDING"
    assert (
        reachability.classify_member(
            _member("d", "NONE", writer_state="GONE", writer_recreatable=False)
        )
        == "ABANDONED"
    )
    assert (
        reachability.classify_member(_member("e", "NONE", writer_state="UNKNOWN")) == "UNKNOWN"
    )


def test_member_count_conjunct_is_permanently_false_below_the_ceiling() -> None:
    members = [_member("dead", "FAILED")] + [_member(f"live{i}", "NONE") for i in range(8)]
    result = reachability.evaluate_conjunct(
        {"id": "complete_equals_required", "kind": "member_count"}, members, 9
    )
    assert result["state"] == "PERMANENTLY_FALSE"
    assert result["supporting_member_ids"] == ["dead"]


def test_member_count_conjunct_is_not_yet_while_all_members_can_still_pass() -> None:
    members = [_member(f"live{i}", "NONE") for i in range(9)]
    result = reachability.evaluate_conjunct(
        {"id": "complete_equals_required", "kind": "member_count"}, members, 9
    )
    assert result["state"] == "NOT_YET"


def test_authorized_continuation_restores_the_ceiling() -> None:
    members = [
        _member("dead", "FAILED", continuation={"state": "AUTHORIZED", "path_projection": "docs/x.md"})
    ] + [_member(f"live{i}", "NONE") for i in range(8)]
    result = reachability.evaluate_conjunct(
        {"id": "complete_equals_required", "kind": "member_count"}, members, 9
    )
    assert result["state"] == "NOT_YET"


def test_writer_evidence_conjunct_needs_a_gone_unrecreatable_writer() -> None:
    conjunct = {
        "id": "all_queues_exhausted",
        "kind": "writer_evidence",
        "satisfied": False,
        "writers": [
            {
                "id": "lane_c",
                "state": "GONE",
                "recreatable": False,
                "evidence": {"kind": "observation", "path_projection": "lane_c_state"},
            }
        ],
    }
    assert reachability.evaluate_conjunct(conjunct, [], 0)["state"] == "PERMANENTLY_FALSE"
    conjunct["writers"][0]["state"] = "ALIVE"
    assert reachability.evaluate_conjunct(conjunct, [], 0)["state"] == "NOT_YET"


def test_decide_returns_reachable_when_nothing_is_permanently_false() -> None:
    payload = {
        "schema": reachability.INPUT_SCHEMA,
        "gate": {
            "id": "collection_complete",
            "expression_source": {"path_projection": "watch.py:212-214", "sha256": "0" * 64},
            "conjuncts": [{"id": "complete_equals_required", "kind": "member_count"}],
        },
        "required_member_count": 9,
        "members": [_member(f"live{i}", "NONE") for i in range(9)],
        "prohibitions": [
            {"id": "NO_RETRY", "path_projection": "docs/cfg.json", "field": "retry", "value": False}
        ],
    }
    result = reachability.decide(payload)
    assert result["verdict"] == "REACHABLE"
    assert result["schema"] == reachability.OUTPUT_SCHEMA
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_plan_skill_gate_reachability.py -v`
Expected: FAIL，`FileNotFoundError` 或 `AssertionError`，因为 `audit_gate_reachability.py` 尚不存在。

- [ ] **Step 3: 创建脚本**

创建 `.codex/skills/plan-nhc-aimnet2-workflow/scripts/audit_gate_reachability.py`：

```python
#!/usr/bin/env python3
"""Decide whether a frozen downstream gate can still be satisfied.

The input is a declaration of one gate, its conjuncts, its frozen member set,
the durable terminal and writer facts observed for them, and the prohibition
clauses that would make a false conjunct permanent. The audit is offline and
read-only: it opens no remote path, samples no process, and never infers a
terminal from a log, an mtime, an absent PID, or an exceeded deadline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

INPUT_SCHEMA = "nhc_gate_reachability_input_v1"
OUTPUT_SCHEMA = "nhc_gate_reachability_v1"

MEMBER_TERMINALS = {"ACCEPTED", "FAILED", "NONE"}
WRITER_STATES = {"ALIVE", "GONE", "UNKNOWN"}
CONJUNCT_KINDS = {"member_count", "writer_evidence", "irreversible_negative"}
PROHIBITION_IDS = {
    "NO_RETRY",
    "NO_SUBSTITUTION",
    "NO_QUEUE_EXTENSION",
    "EXACTLY_ONCE_WRITER",
    "IMMUTABLE_MEMBERSHIP",
}
CEILING_MEMBER_STATES = {"ACCEPTED", "PENDING", "UNKNOWN"}


class InputError(ValueError):
    """Raised when a reachability declaration is malformed."""


def _load_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise InputError(f"{path}: root must be a JSON object")
    return value


def _authorized(member: dict[str, Any]) -> bool:
    continuation = member.get("authorized_continuation")
    return isinstance(continuation, dict) and continuation.get("state") == "AUTHORIZED"


def classify_member(member: dict[str, Any]) -> str:
    terminal = member.get("terminal")
    if terminal not in MEMBER_TERMINALS:
        raise InputError(f"member terminal must be one of {sorted(MEMBER_TERMINALS)}")
    if terminal == "ACCEPTED":
        return "ACCEPTED"
    if terminal == "FAILED":
        return "FAILED"
    writer_state = member.get("writer_state")
    if writer_state not in WRITER_STATES:
        raise InputError(f"member writer_state must be one of {sorted(WRITER_STATES)}")
    if writer_state == "GONE" and member.get("writer_recreatable") is False:
        return "ABANDONED"
    if writer_state == "UNKNOWN":
        return "UNKNOWN"
    return "PENDING"


def _member_count_conjunct(
    conjunct: dict[str, Any], members: list[dict[str, Any]], required: int
) -> dict[str, Any]:
    ceiling = 0
    accepted = 0
    supporting: list[str] = []
    for member in members:
        member_state = classify_member(member)
        if member_state == "ACCEPTED":
            accepted += 1
        if member_state in CEILING_MEMBER_STATES or _authorized(member):
            ceiling += 1
        else:
            supporting.append(str(member.get("id")))
    if ceiling < required:
        state = "PERMANENTLY_FALSE"
        reason = f"accepted ceiling {ceiling} is below required {required}"
    elif accepted >= required:
        state = "SATISFIED"
        reason = f"accepted {accepted} meets required {required}"
        supporting = []
    else:
        state = "NOT_YET"
        reason = f"accepted {accepted} of {required}, ceiling {ceiling} still allows it"
        supporting = []
    return {
        "id": str(conjunct.get("id")),
        "kind": "member_count",
        "state": state,
        "reason": reason,
        "supporting_member_ids": supporting,
        "supporting_writer_ids": [],
    }


def _writer_evidence_conjunct(conjunct: dict[str, Any]) -> dict[str, Any]:
    writers = conjunct.get("writers")
    if not isinstance(writers, list) or not writers:
        raise InputError("writer_evidence conjunct requires a non-empty writers list")
    dead: list[str] = []
    for writer in writers:
        if not isinstance(writer, dict) or writer.get("state") not in WRITER_STATES:
            raise InputError("writer state is invalid")
        if writer.get("state") == "GONE" and writer.get("recreatable") is False:
            dead.append(str(writer.get("id")))
    if conjunct.get("satisfied") is True:
        state, reason = "SATISFIED", "conjunct evidence is present"
        dead = []
    elif dead:
        state = "PERMANENTLY_FALSE"
        reason = f"the only permitted writers are gone and unrecreatable: {dead}"
    else:
        state, reason = "NOT_YET", "a permitted writer may still produce the evidence"
    return {
        "id": str(conjunct.get("id")),
        "kind": "writer_evidence",
        "state": state,
        "reason": reason,
        "supporting_member_ids": [],
        "supporting_writer_ids": dead,
    }


def _irreversible_negative_conjunct(conjunct: dict[str, Any]) -> dict[str, Any]:
    if conjunct.get("satisfied") is True:
        state, reason = "SATISFIED", "no forbidden evidence exists"
    elif conjunct.get("reopened_by_authorization") is True:
        state, reason = "NOT_YET", "an authorization reopens the writer"
    else:
        state = "PERMANENTLY_FALSE"
        reason = "forbidden evidence exists and no authorization reopens it"
    return {
        "id": str(conjunct.get("id")),
        "kind": "irreversible_negative",
        "state": state,
        "reason": reason,
        "supporting_member_ids": [],
        "supporting_writer_ids": [],
    }


def evaluate_conjunct(
    conjunct: dict[str, Any], members: list[dict[str, Any]], required: int
) -> dict[str, Any]:
    kind = conjunct.get("kind")
    if kind not in CONJUNCT_KINDS:
        raise InputError(f"conjunct kind must be one of {sorted(CONJUNCT_KINDS)}")
    if kind == "member_count":
        return _member_count_conjunct(conjunct, members, required)
    if kind == "writer_evidence":
        return _writer_evidence_conjunct(conjunct)
    return _irreversible_negative_conjunct(conjunct)


def decide(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != INPUT_SCHEMA:
        raise InputError(f"input schema must be {INPUT_SCHEMA}")
    gate = payload.get("gate")
    if not isinstance(gate, dict):
        raise InputError("gate must be an object")
    conjuncts = gate.get("conjuncts")
    if not isinstance(conjuncts, list) or not conjuncts:
        raise InputError("gate requires a non-empty conjuncts list")
    members = payload.get("members")
    if not isinstance(members, list):
        raise InputError("members must be a list")
    required = payload.get("required_member_count")
    if isinstance(required, bool) or not isinstance(required, int) or required < 0:
        raise InputError("required_member_count must be a non-negative integer")
    if members and len(members) != required:
        raise InputError("members do not match required_member_count")

    evaluated = [evaluate_conjunct(item, members, required) for item in conjuncts]
    permanent = [item for item in evaluated if item["state"] == "PERMANENTLY_FALSE"]
    verdict = "UNREACHABLE" if permanent else "REACHABLE"
    prohibitions = payload.get("prohibitions")
    clauses = (
        [str(item.get("id")) for item in prohibitions if isinstance(item, dict)]
        if isinstance(prohibitions, list)
        else []
    )
    return {
        "schema": OUTPUT_SCHEMA,
        "gate_id": str(gate.get("id")),
        "verdict": verdict,
        "conjuncts": evaluated,
        "not_yet": [item["id"] for item in evaluated if item["state"] == "NOT_YET"],
        "missing": [],
        "permanence_clauses": clauses if permanent else [],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("declaration", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = decide(_load_object(args.declaration))
    except (OSError, json.JSONDecodeError, InputError) as exc:
        print(json.dumps({"schema": OUTPUT_SCHEMA, "verdict": "INVALID", "errors": [str(exc)]}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "REACHABLE" else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_plan_skill_gate_reachability.py -v`
Expected: PASS（10 passed）。

- [ ] **Step 5: 静态检查**

Run: `python -m ruff check .codex/skills/plan-nhc-aimnet2-workflow/scripts/audit_gate_reachability.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add .codex/skills/plan-nhc-aimnet2-workflow/scripts/audit_gate_reachability.py \
        tests/test_plan_skill_gate_reachability.py
git commit -m "feat(skill): add offline downstream gate reachability audit"
```

---

### Task 5: 给谓词加 fail-closed 守卫（防误报）

**Files:**
- Modify: `.codex/skills/plan-nhc-aimnet2-workflow/scripts/audit_gate_reachability.py`（在 `decide` 中新增守卫、新增 `_permanence_guard_failures`）
- Test: `tests/test_plan_skill_gate_reachability.py`（追加）

**Interfaces:**
- Consumes: Task 4 的 `decide`、`evaluate_conjunct`、`PROHIBITION_IDS`。
- Produces: `_permanence_guard_failures(payload, permanent) -> list[str]`；新增常量 `NON_DURABLE_EVIDENCE_KINDS`；`decide` 的 `verdict` 新增取值 `REACHABILITY_UNKNOWN`，`missing` 字段承载守卫失败原因。

守卫对应 Task 1 中 `UNREACHABLE` 的五个条件。只要任一不成立，`verdict` 从 `UNREACHABLE` 降级为 `REACHABILITY_UNKNOWN`，永不降级为 `REACHABLE`（漏报可接受，误报不可接受）。守卫只检查**承载永久性断言的那些事实**；与该断言无关的 `UNKNOWN` 成员只记入 `missing`，不阻断判定。

- [ ] **Step 1: 写失败测试**

在 `tests/test_plan_skill_gate_reachability.py` 末尾追加：

```python
def _clx_payload() -> dict[str, Any]:
    members = [
        _member("CLXFIGGGSODORK-UHFFFAOYSA-N", "FAILED", writer_state="GONE",
                writer_recreatable=False)
    ]
    members += [_member(f"LIVE{i}-UHFFFAOYSA-N", "NONE") for i in range(8)]
    return {
        "schema": reachability.INPUT_SCHEMA,
        "gate": {
            "id": "collection_complete",
            "expression_source": {
                "path_projection": "phase9b_aimnet2_finetune_watch.py:212-214",
                "sha256": "c" * 64,
            },
            "conjuncts": [{"id": "complete_equals_required", "kind": "member_count"}],
        },
        "required_member_count": 9,
        "members": members,
        "prohibitions": [
            {
                "id": "NO_SUBSTITUTION",
                "path_projection": "references/workflow-contract.md:68",
                "quote": "An attempted candidate or model generation is never silently replaced.",
            }
        ],
    }


def test_clx_case_is_unreachable() -> None:
    result = reachability.decide(_clx_payload())
    assert result["verdict"] == "UNREACHABLE"
    assert result["permanence_clauses"] == ["NO_SUBSTITUTION"]
    assert result["missing"] == []


def test_missing_prohibition_downgrades_to_unknown() -> None:
    payload = _clx_payload()
    payload["prohibitions"] = []
    result = reachability.decide(payload)
    assert result["verdict"] == "REACHABILITY_UNKNOWN"
    assert "no frozen prohibition clause carries the permanence claim" in result["missing"]


def test_unbound_gate_expression_downgrades_to_unknown() -> None:
    payload = _clx_payload()
    payload["gate"]["expression_source"]["sha256"] = "unavailable"
    result = reachability.decide(payload)
    assert result["verdict"] == "REACHABILITY_UNKNOWN"
    assert "gate expression source is not bound to a digest" in result["missing"]


def test_non_durable_terminal_evidence_downgrades_to_unknown() -> None:
    for kind in ("log", "mtime", "pid", "process_boolean", "elapsed_time"):
        payload = _clx_payload()
        payload["members"][0]["terminal_evidence"] = {"kind": kind, "path_projection": "x"}
        result = reachability.decide(payload)
        assert result["verdict"] == "REACHABILITY_UNKNOWN", kind


def test_unrelated_unknown_member_does_not_block_the_verdict() -> None:
    payload = _clx_payload()
    payload["members"][1]["writer_state"] = "UNKNOWN"
    result = reachability.decide(payload)
    assert result["verdict"] == "UNREACHABLE"
    assert "LIVE0-UHFFFAOYSA-N" in result["unresolved_member_ids"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_plan_skill_gate_reachability.py -v`
Expected: FAIL，5 个新测试失败（`verdict` 仍是 `UNREACHABLE`、`missing` 为空、无 `unresolved_member_ids` 键）。

- [ ] **Step 3: 加常量与守卫函数**

在 `audit_gate_reachability.py` 的 `CEILING_MEMBER_STATES` 之后新增：

```python
NON_DURABLE_EVIDENCE_KINDS = {"log", "mtime", "pid", "process_boolean", "elapsed_time"}
```

在 `decide` 之前新增：

```python
def _durable(evidence: Any) -> bool:
    return (
        isinstance(evidence, dict)
        and evidence.get("kind") not in NON_DURABLE_EVIDENCE_KINDS
        and isinstance(evidence.get("path_projection"), str)
        and bool(evidence["path_projection"].strip())
    )


def _valid_prohibition(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and item.get("id") in PROHIBITION_IDS
        and isinstance(item.get("path_projection"), str)
        and bool(item["path_projection"].strip())
        and (bool(str(item.get("quote", "")).strip()) or "field" in item)
    )


def _permanence_guard_failures(
    payload: dict[str, Any],
    permanent: list[dict[str, Any]],
    members_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    source = payload["gate"].get("expression_source")
    digest = source.get("sha256") if isinstance(source, dict) else None
    if not (
        isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest.lower())
    ):
        failures.append("gate expression source is not bound to a digest")
    prohibitions = payload.get("prohibitions")
    if not (
        isinstance(prohibitions, list) and any(_valid_prohibition(item) for item in prohibitions)
    ):
        failures.append("no frozen prohibition clause carries the permanence claim")
    for conjunct in permanent:
        for member_id in conjunct["supporting_member_ids"]:
            member = members_by_id.get(member_id, {})
            if member.get("terminal") == "FAILED" and not _durable(
                member.get("terminal_evidence")
            ):
                failures.append(f"terminal evidence for {member_id} is not durable")
            if classify_member(member) == "ABANDONED" and not _durable(
                member.get("writer_evidence")
            ):
                failures.append(f"writer-gone evidence for {member_id} is not durable")
        for writer_id in conjunct["supporting_writer_ids"]:
            writers = [
                writer
                for item in payload["gate"]["conjuncts"]
                for writer in (item.get("writers") or [])
                if isinstance(writer, dict) and writer.get("id") == writer_id
            ]
            if not writers or not _durable(writers[0].get("evidence")):
                failures.append(f"writer-gone evidence for {writer_id} is not durable")
    return sorted(set(failures))
```

- [ ] **Step 4: 在 `decide` 里接上守卫**

把 `decide` 中从 `permanent = ...` 到 `return {...}` 的部分替换为：

```python
    permanent = [item for item in evaluated if item["state"] == "PERMANENTLY_FALSE"]
    members_by_id = {str(member.get("id")): member for member in members}
    unresolved = [
        str(member.get("id")) for member in members if classify_member(member) == "UNKNOWN"
    ]
    prohibitions = payload.get("prohibitions")
    clauses = (
        [str(item.get("id")) for item in prohibitions if _valid_prohibition(item)]
        if isinstance(prohibitions, list)
        else []
    )
    missing: list[str] = []
    if permanent:
        missing = _permanence_guard_failures(payload, permanent, members_by_id)
        verdict = "REACHABILITY_UNKNOWN" if missing else "UNREACHABLE"
    else:
        verdict = "REACHABLE"
    return {
        "schema": OUTPUT_SCHEMA,
        "gate_id": str(gate.get("id")),
        "verdict": verdict,
        "conjuncts": evaluated,
        "not_yet": [item["id"] for item in evaluated if item["state"] == "NOT_YET"],
        "missing": missing,
        "unresolved_member_ids": unresolved,
        "permanence_clauses": clauses if verdict == "UNREACHABLE" else [],
    }
```

同时把 `main` 的返回码规则改为：

```python
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "REACHABLE" else 1
```

（保持不变；`UNREACHABLE` 与 `REACHABILITY_UNKNOWN` 同为 1，`INVALID` 为 2。）

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_plan_skill_gate_reachability.py -v`
Expected: PASS（15 passed）。

- [ ] **Step 6: 静态检查**

Run: `python -m ruff check .codex/skills/plan-nhc-aimnet2-workflow/scripts/`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add .codex/skills/plan-nhc-aimnet2-workflow/scripts/audit_gate_reachability.py \
        tests/test_plan_skill_gate_reachability.py
git commit -m "feat(skill): fail closed on unproved reachability permanence"
```

---

### Task 6: 把判据接进 `evidence-routing.md` 与 `SKILL.md`

**Files:**
- Modify: `.codex/skills/plan-nhc-aimnet2-workflow/references/evidence-routing.md:64`（One-shot progress check 行）、`:70-81`（Stop and expansion rules）
- Modify: `.codex/skills/plan-nhc-aimnet2-workflow/SKILL.md:28`（Select the contract）、`:32-36`（helper 清单）、`:57-67`（planning boundary）
- Test: `tests/test_plan_skill_reachability_docs.py`（追加）

**Interfaces:**
- Consumes: Task 1、2 的 `REACHABILITY_PREDICATE` / `UNREACHABLE`；Task 4 的脚本路径。
- Produces: 无新符号，只做路由绑定。

- [ ] **Step 1: 追加失败测试**

在 `tests/test_plan_skill_reachability_docs.py` 末尾追加：

```python
EVIDENCE_ROUTING = SKILL / "references/evidence-routing.md"
SKILL_MD = SKILL / "SKILL.md"


def test_quick_route_loads_the_downstream_consumer_gate() -> None:
    text = EVIDENCE_ROUTING.read_text(encoding="utf-8")
    assert "Always add the nearest downstream consumer gate" in text
    assert "Follow the downstream consumer edge of the active stage in every mode." in text


def test_skill_routes_and_bounds_the_predicate() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "always evaluate `REACHABILITY_PREDICATE`" in text
    assert "scripts/audit_gate_reachability.py" in text
    assert "An `UNREACHABLE` verdict is a report status." in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_plan_skill_reachability_docs.py -v`
Expected: FAIL，2 个新测试报 `AssertionError`。

- [ ] **Step 3: 改 `evidence-routing.md` 的路由表行**

第 64 行整行替换为：

```markdown
| One-shot progress check | For QUICK_ACTIVE_STAGE, resolve the private connection/run root and only the active stage configuration, current claim/terminal identity, active logs/manifests, and bounded process/resource observations. Always add the nearest downstream consumer gate: its digest-bound expression source, its frozen member set and required count, one durable terminal fact per member, one durable writer fact per conjunct, and the prohibition clauses that would make a false conjunct permanent. Add the full queue, lane, split, model, and pipeline identities only for FULL_PROGRESS_AUDIT or an observed anomaly. Historical reports are context, not live status. |
```

- [ ] **Step 4: 增补 expansion rule**

在 `## Stop and expansion rules` 列表中，`- Source control flow, log text, mtime, ...` 之前插入：

```markdown
- Follow the downstream consumer edge of the active stage in every mode. An
  upstream-only evidence set cannot distinguish an advancing route from an
  advancing route whose consumer gate is already unsatisfiable.
```

- [ ] **Step 5: 改 `SKILL.md`**

第 28 行整行替换为：

```markdown
- For a live status request, read [references/progress-audit.md](references/progress-audit.md). Keep it lightweight unless an observed anomaly requires a deeper contract, but always evaluate `REACHABILITY_PREDICATE` for the nearest downstream consumer gate, including under QUICK_ACTIVE_STAGE.
```

在 helper 清单（第 36 行之后）追加：

```markdown
- [scripts/audit_gate_reachability.py](scripts/audit_gate_reachability.py) decides offline whether a frozen downstream gate remains satisfiable under the no-retry, no-substitution, no-queue-extension, and exactly-once-writer prohibitions.
```

在 planning boundary 的禁止列表（第 65 行 `- establish recurring monitoring under a one-shot request.`）之后、第 67 行段落之前插入：

```markdown
An `UNREACHABLE` verdict is a report status. It does not authorize stopping,
signalling, retrying, replacing, rescheduling, or reclaiming any running route,
watcher, queue, or resource, and it does not reopen a frozen cohort. Report the
proved conjunct, its prohibition clause, the occupied resource envelope, and the
one next permitted action.
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/test_plan_skill_reachability_docs.py -v`
Expected: PASS（8 passed）。

- [ ] **Step 7: Commit**

```bash
git add .codex/skills/plan-nhc-aimnet2-workflow/references/evidence-routing.md \
        .codex/skills/plan-nhc-aimnet2-workflow/SKILL.md \
        tests/test_plan_skill_reachability_docs.py
git commit -m "docs(skill): route the reachability predicate into quick progress checks"
```

---

### Task 7: CLX 金样本回归与误报变异矩阵

**Files:**
- Create: `tests/fixtures/reachability/clx_variant_a.json`
- Create: `tests/fixtures/reachability/clx_variant_b.json`
- Create: `tests/fixtures/reachability/healthy_cohort.json`
- Create: `tests/fixtures/reachability/gtho_continuation.json`
- Modify: `tests/test_plan_skill_gate_reachability.py`（追加金样本与变异矩阵测试）

**Interfaces:**
- Consumes: Task 4、5 的 `decide` 与 `INPUT_SCHEMA`；Task 3 的 `validate_report`。
- Produces: 四个可复用的声明 fixture，供后续任何门的可达性回归复用。

这一步是本计划的验证方案本体：证明判据在 CLX 真实案例上报 `UNREACHABLE`，且在正常情况下不误报。

- [ ] **Step 1: 写变体 A fixture（门可见的失败）**

创建 `tests/fixtures/reachability/clx_variant_a.json`（`<digest>` 换成实际部署 watcher 源码的 64 位摘要；本地测试可用 `docs/PHASE9B_PIPELINE_CONFIG_V001.json:26` 的 `c1b9e4082c871f674796b9f20f8a152ecaf5afd1c6108465b49636f0a2cf86f0`）：

```json
{
  "schema": "nhc_gate_reachability_input_v1",
  "gate": {
    "id": "collection_complete",
    "expression_source": {
      "path_projection": "scripts/phase9b_aimnet2_finetune_watch.py:212-214",
      "sha256": "c1b9e4082c871f674796b9f20f8a152ecaf5afd1c6108465b49636f0a2cf86f0"
    },
    "conjuncts": [
      {
        "id": "no_failed_queue_states",
        "kind": "irreversible_negative",
        "satisfied": false,
        "reopened_by_authorization": false,
        "evidence": {
          "kind": "file",
          "path_projection": "<lane_c_state_root>/lane_terminal.json",
          "detail": "outcome=PREDECESSOR_AUDIT_FAILED"
        }
      },
      {"id": "complete_equals_required", "kind": "member_count"},
      {
        "id": "all_queues_exhausted",
        "kind": "writer_evidence",
        "satisfied": false,
        "writers": [
          {
            "id": "lane_c",
            "state": "GONE",
            "recreatable": false,
            "evidence": {
              "kind": "observation",
              "path_projection": "<lane_c_state_root>",
              "detail": "watcher exited after lane_terminal.json; state root is exclusive-create"
            }
          }
        ]
      }
    ]
  },
  "required_member_count": 9,
  "members": [
    {
      "id": "CLXFIGGGSODORK-UHFFFAOYSA-N",
      "terminal": "FAILED",
      "terminal_evidence": {
        "kind": "file",
        "path_projection": "<runs_root>/<clx_run>/controller_exit_code",
        "detail": "controller_exit_code=124"
      },
      "writer_state": "GONE",
      "writer_recreatable": false,
      "authorized_continuation": null
    },
    {"id": "ACGCNTKELWXJPN-UHFFFAOYSA-N", "terminal": "ACCEPTED",
     "terminal_evidence": {"kind": "file", "path_projection": "<runs_root>/<acg_run>/result.json",
                           "detail": "final_outcome=PASS"},
     "writer_state": "GONE", "writer_recreatable": false, "authorized_continuation": null},
    {"id": "KZYKDQNIIMATMJ-UHFFFAOYSA-N", "terminal": "NONE", "terminal_evidence": null,
     "writer_state": "ALIVE", "writer_recreatable": true, "authorized_continuation": null},
    {"id": "PDIYCCLDBKWBTK-UHFFFAOYSA-N", "terminal": "NONE", "terminal_evidence": null,
     "writer_state": "ALIVE", "writer_recreatable": true, "authorized_continuation": null},
    {"id": "RATKDJDMBGPDPZ-UHFFFAOYSA-N", "terminal": "NONE", "terminal_evidence": null,
     "writer_state": "ALIVE", "writer_recreatable": true, "authorized_continuation": null},
    {"id": "RBKFFSUUCLDQER-UHFFFAOYSA-N", "terminal": "NONE", "terminal_evidence": null,
     "writer_state": "ALIVE", "writer_recreatable": true, "authorized_continuation": null},
    {"id": "RMEQTBVGGNKAEQ-UHFFFAOYSA-N", "terminal": "NONE", "terminal_evidence": null,
     "writer_state": "ALIVE", "writer_recreatable": true, "authorized_continuation": null},
    {"id": "VNYHGZAUUQMMDL-UHFFFAOYSA-N", "terminal": "NONE", "terminal_evidence": null,
     "writer_state": "ALIVE", "writer_recreatable": true, "authorized_continuation": null},
    {"id": "VPAFDQIFHJWCBK-UHFFFAOYSA-N", "terminal": "NONE", "terminal_evidence": null,
     "writer_state": "ALIVE", "writer_recreatable": true, "authorized_continuation": null}
  ],
  "prohibitions": [
    {"id": "NO_RETRY", "path_projection": "docs/PHASE9B_PIPELINE_CONFIG_V001.json:7",
     "field": "retry", "value": false},
    {"id": "NO_QUEUE_EXTENSION",
     "path_projection": "docs/PHASE9B_CONTINUOUS_PIPELINE_AUTOMATION.md:94-96",
     "quote": "No queue is extended after launch. A candidate failure blocks collection and training; it is not replaced."},
    {"id": "NO_SUBSTITUTION",
     "path_projection": ".codex/skills/plan-nhc-aimnet2-workflow/references/workflow-contract.md:68",
     "quote": "An attempted candidate or model generation is never silently replaced."},
    {"id": "EXACTLY_ONCE_WRITER",
     "path_projection": "docs/PHASE9B_CONTINUOUS_PIPELINE_AUTOMATION.md:78-80",
     "quote": "An existing orchestrator state root is never overwritten or reused."}
  ]
}
```

- [ ] **Step 2: 写变体 B fixture（静默死锁）**

`cp tests/fixtures/reachability/clx_variant_a.json tests/fixtures/reachability/clx_variant_b.json`，然后只改两处。

`no_failed_queue_states` 合取项（lane C watcher 卡死，从未写 `lane_terminal.json`）：

```json
      {
        "id": "no_failed_queue_states",
        "kind": "irreversible_negative",
        "satisfied": true,
        "reopened_by_authorization": false,
        "evidence": {
          "kind": "observation",
          "path_projection": "<lane_c_state_root>",
          "detail": "no lane_terminal.json exists"
        }
      },
```

CLX 成员（run root 里从未出现 `controller_exit_code`，唯一被许可的 writer 已消失且按 exactly-once 不可重建）：

```json
    {
      "id": "CLXFIGGGSODORK-UHFFFAOYSA-N",
      "terminal": "NONE",
      "terminal_evidence": null,
      "writer_state": "GONE",
      "writer_recreatable": false,
      "writer_evidence": {
        "kind": "observation",
        "path_projection": "<lane_c_state_root>",
        "detail": "no lane_terminal.json and no queue_exhausted.json; state root is exclusive-create so the writer cannot be recreated"
      },
      "authorized_continuation": null
    },
```

此变体只能靠 `ABANDONED` 通道判出 `PERMANENTLY_FALSE`。

- [ ] **Step 3: 写正常与授权续跑 fixture**

`cp tests/fixtures/reachability/clx_variant_a.json tests/fixtures/reachability/healthy_cohort.json`，改三处：`no_failed_queue_states` 的 `satisfied` 改为 `true`；`all_queues_exhausted` 的 lane_c writer 改为 `"state": "ALIVE", "recreatable": true`；CLX 成员改为

```json
    {
      "id": "CLXFIGGGSODORK-UHFFFAOYSA-N",
      "terminal": "NONE",
      "terminal_evidence": null,
      "writer_state": "ALIVE",
      "writer_recreatable": true,
      "authorized_continuation": null
    },
```

`cp tests/fixtures/reachability/clx_variant_a.json tests/fixtures/reachability/gtho_continuation.json`，改三处：`no_failed_queue_states` 的 `reopened_by_authorization` 改为 `true`；`all_queues_exhausted` 的 lane_c writer 改为 `"state": "ALIVE", "recreatable": true`；CLX 成员的 `authorized_continuation` 改为

```json
      "authorized_continuation": {
        "state": "AUTHORIZED",
        "path_projection": "docs/PHASE9B_GTHO_NEUTRAL_CONTINUATION_V001.md",
        "detail": "one-shot non-production continuation precedent for a timed-out route"
      }
```

- [ ] **Step 4: 写金样本与变异矩阵测试**

先把 `import copy` 和 `import json` 加进 `tests/test_plan_skill_gate_reachability.py` 顶部的 import 块（放在 `import importlib.util` 之前，保持 `I` 规则的字母序），然后在文件末尾追加：

```python
FIXTURES = Path(__file__).resolve().parent / "fixtures/reachability"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_clx_variant_a_reports_unreachable() -> None:
    result = reachability.decide(_fixture("clx_variant_a"))
    assert result["verdict"] == "UNREACHABLE"
    permanent = {item["id"] for item in result["conjuncts"] if item["state"] == "PERMANENTLY_FALSE"}
    assert "complete_equals_required" in permanent
    assert set(result["permanence_clauses"]) >= {"NO_RETRY", "NO_SUBSTITUTION"}


def test_clx_variant_b_reports_unreachable_through_abandonment() -> None:
    payload = _fixture("clx_variant_b")
    result = reachability.decide(payload)
    assert result["verdict"] == "UNREACHABLE"
    clx = payload["members"][0]
    assert reachability.classify_member(clx) == "ABANDONED"


def test_healthy_cohort_is_reachable() -> None:
    result = reachability.decide(_fixture("healthy_cohort"))
    assert result["verdict"] == "REACHABLE"
    assert result["permanence_clauses"] == []


def test_authorized_continuation_is_not_unreachable() -> None:
    result = reachability.decide(_fixture("gtho_continuation"))
    assert result["verdict"] == "REACHABLE"


def test_mutation_matrix_never_keeps_unreachable_by_accident() -> None:
    base = _fixture("clx_variant_a")
    mutations = [
        ("clear prohibitions", lambda p: p.update({"prohibitions": []})),
        ("unbind digest", lambda p: p["gate"]["expression_source"].update({"sha256": "x"})),
        ("log-only terminal", lambda p: p["members"][0].update(
            {"terminal_evidence": {"kind": "log", "path_projection": "controller_stderr"}})),
        ("revive clx", lambda p: p["members"][0].update(
            {"terminal": "NONE", "writer_state": "ALIVE", "writer_recreatable": True,
             "terminal_evidence": None})),
        ("authorize continuation", lambda p: p["members"][0].update(
            {"authorized_continuation": {"state": "AUTHORIZED", "path_projection": "docs/x.md"}})),
    ]
    for label, mutate in mutations:
        payload = copy.deepcopy(base)
        payload["gate"]["conjuncts"] = [
            item for item in payload["gate"]["conjuncts"] if item["kind"] == "member_count"
        ]
        mutate(payload)
        verdict = reachability.decide(payload)["verdict"]
        assert verdict in {"REACHABLE", "REACHABILITY_UNKNOWN"}, (label, verdict)


def test_unreachable_verdict_survives_report_validation() -> None:
    report = _report("UNREACHABLE", [_gate("UNREACHABLE")])
    assert validator.validate_report(report) == []
```

- [ ] **Step 5: 运行全部测试**

Run: `python -m pytest tests/test_plan_skill_gate_reachability.py tests/test_plan_skill_reachability_docs.py -v`
Expected: PASS（全部通过；共 21 项）。

- [ ] **Step 6: 端到端 CLI 冒烟**

Run:

```bash
python .codex/skills/plan-nhc-aimnet2-workflow/scripts/audit_gate_reachability.py \
  tests/fixtures/reachability/clx_variant_a.json
```

Expected: 打印 `"verdict": "UNREACHABLE"`，退出码 1。

Run:

```bash
python .codex/skills/plan-nhc-aimnet2-workflow/scripts/audit_gate_reachability.py \
  tests/fixtures/reachability/healthy_cohort.json
```

Expected: 打印 `"verdict": "REACHABLE"`，退出码 0。

- [ ] **Step 7: 全仓回归**

Run: `python -m pytest -q`
Expected: 无新增失败（与实施前的基线一致）。

- [ ] **Step 8: Commit**

```bash
git add tests/fixtures/reachability tests/test_plan_skill_gate_reachability.py
git commit -m "test(skill): pin the CLX reachability case and the false-positive matrix"
```

---

## 验证方案（汇总）

| 验证目标 | 方式 | 位置 |
| --- | --- | --- |
| CLX 真实案例被正确报出 `UNREACHABLE` | 变体 A 金样本（`controller_exit_code=124` 可见） | Task 7 Step 1、4 |
| 静默死锁变体也被报出 | 变体 B 金样本（无 exit code、writer `GONE` 且不可重建 → `ABANDONED`） | Task 7 Step 2、4 |
| 正常运行不误报 | `healthy_cohort` fixture → `REACHABLE` | Task 7 Step 3、4 |
| 已授权续跑不误报（GTHO 先例） | `gtho_continuation` fixture → `REACHABLE` | Task 7 Step 3、4 |
| 「还没满足」不被当成「永远不可能」 | `test_member_count_conjunct_is_not_yet_...`、`test_writer_evidence_conjunct_needs_a_gone_unrecreatable_writer` | Task 4 Step 1 |
| 证据不够时降级而非误报 | 5 项守卫测试 + 5 条变异矩阵，断言变异后**绝不**残留 `UNREACHABLE` | Task 5 Step 1、Task 7 Step 4 |
| 新状态能进归档 JSON 且不与 `HEALTHY` 共存 | 校验器 4 项测试 + `test_unreachable_verdict_survives_report_validation` | Task 3 Step 1、Task 7 Step 4 |
| 快查模式不能省掉判据 | 文本条款测试 `test_quick_mode_cannot_skip_the_predicate` | Task 2 Step 1 |
| skill 文风与英文约束 | 所有拟议片段为英文 contract 体；`ruff check` 覆盖脚本 | Task 3/4/5 的静态检查步 |

**建议的额外人工验证（不进 CI）：** 实施完成后，用一次真实的 `QUICK_ACTIVE_STAGE` 请求跑该 skill，断言其返回的顶层状态不是 `HEALTHY`，且报告中含 `downstream_reachability` gate 与被引用的禁令条款路径。这是唯一能证明「路由真的把判据接上了」的检查，脚本测试无法替代。

---

## 最容易误报的边界情况（实施时必须逐条防守）

按风险从高到低：

1. **已授权的续跑/例外会重新打开一条 failed 成员** —— 本仓库**已经发生过**：`docs/PHASE9B_GTHO_NEUTRAL_CONTINUATION_V001.md` 就是对一条 timeout route 的一次性授权续跑，`docs/PHASE9B_RBK_THROUGHPUT_CONTINUATION_V001.md` 是对一个 never-claimed 候选的授权继续。如果判据只看「terminal 非 PASS + retry=false」，会把这类可恢复情形误判成永久不可达。防守：`authorized_continuation` 必须计回 ceiling；且 `UNREACHABLE` 的第 5 个条件明确要求「没有更高优先级权威授权 continuation/exception/re-scope」，按 `evidence-routing.md` 的 authority precedence 检索。

2. **terminal 写入滞后** —— `phase9b_parent_level_autofill.py:749-751` 在 `subprocess.run` 返回**之后**才写 `controller_exit_code`；`timeout --kill-after=30s` 还有 30 秒宽限。在这个窗口里快照会看到「超过 wall limit、无 terminal」。这**不是** `ABANDONED`。防守：`ABANDONED` 必须额外要求 writer `GONE` 且 `recreatable: false` 的 durable 证据；判据正文明确写「exceeded deadline alone proves nothing here」，超期未写 terminal 归入 `not_yet`。

3. **门表达式取错版本** —— `docs/PHASE9B_PIPELINE_CONFIG_V001.json:24-30` 同时给出 `finetune_watch.sha256`（`c1b9e40…`）与 `adopt_compatible_sha256`（`74e17b1…`）。当前部署跑的很可能是 adopt-compatible 那份，其失败语义与新版不同。读错源码就会算出错误的合取项集合。防守：`expression_source.sha256` 必须是**实际部署**那份的摘要；判据正文写明 "not of an adopt-compatible sibling that is not the running one"。

4. **run root 名字解析失败被当成成员死亡** —— `collection_snapshot` 用 `run_name_template.format(candidate_lower=...)` 定位候选目录。模板绑错、runs_root 绑错、大小写不符都会让一个健康候选看起来「目录不存在」。防守：`terminal: "NONE"` + `writer_state: "UNKNOWN"` → `UNKNOWN`（记入 `unresolved_member_ids`），绝不映射成 `FAILED` 或 `ABANDONED`；输入契约里「目录缺失」不是一个 terminal 取值。

5. **成员集合/required count 取自错误版本** —— split 有 V001（已 rejected，见 `PHASE9B_AIMNET2_FINETUNE_SPLIT_V002.json:3` 的 `supersedes_rejected_split`）与 V002；`required_candidate_count` 也在 fine-tune orchestration config 里另有一份。取错就直接算错 ceiling。防守：`decide` 强制 `len(members) == required_member_count`，且成员权威必须自带 SHA256 绑定（`load_contract` 在 `phase9b_aimnet2_finetune_watch.py:100-103` 已校验 `split_sha256`，判据必须引用同一份）。

6. **一条 route 有多个下游消费者** —— 若某条 route 同时喂两个门，其中一个死了不等于该 route 不可达。防守：判据的作用对象是 (route, consumer gate) 二元组；只有当**全部**已声明消费者都判出 `UNREACHABLE` 才把该 route 报成 `UNREACHABLE`，否则只在报告里列出死掉的那条边。当前 9B 流水线是单消费者，但不要把这个假设写死进脚本。

7. **把 `WAIT_FOR_RESOURCES` 误当永久** —— 状态机里 GPU/磁盘/内存等待（`phase9b_aimnet2_finetune_watch.py:516-532`）可以无限久，但资源是可恢复的，不受任何冻结禁令封锁。防守：资源等待没有对应的 `prohibitions` 条款，因此第 3 个 `UNREACHABLE` 条件（必须有被引用的冻结禁令承载永久性）会自动挡住；不要为资源等待新增禁令 ID。

8. **`UNKNOWN` 成员被当成 ceiling 的减项** —— 若把无法解析的成员算作「不可能通过」，任何一次证据缺失都会制造假不可达。防守：`CEILING_MEMBER_STATES` 显式包含 `UNKNOWN`，即 `UNKNOWN` 乐观计入 ceiling，只记录不扣分。

---

## 与既有边界的一致性声明

- 本计划不改动任何生产/流水线源码，不改 `PHASE_STATUS.md`，不引入远端读取。新脚本是纯本地、纯 stdlib、只读 JSON 声明的离线审计器，与 `audit_resource_plan.py` 同构。
- 判据不新增顶层报告字段，`validate_workflow_report.py:26-46` 的 `REQUIRED_TOP_LEVEL` 不变，既有归档报告仍然合法（除了 `progress` 模式新增的强制 gate —— 这是有意的破坏性收紧，因为一份没有可达性判定的 progress 报告正是本计划要消灭的东西）。
- `UNREACHABLE` 不授权任何 mutation。它的唯一产出是：受影响 route 清单、被占资源包络、被证明恒假的合取项、承载永久性的禁令条款引用，以及一个 next permitted action。
