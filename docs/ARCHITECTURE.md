# 简历改写 Agent（Resume Tailor Agent）架构设计

状态：设计草案 v0.3，待评审
日期：2026-10-02
定位：独立设计。**本文档不动 `boss-watch-agent` 与 `job` 任何仓库**，只把它们当作上游能力与集成契约来引用。
配套实测：[`FEASIBILITY-READ-WRITE.md`](./FEASIBILITY-READ-WRITE.md) —— v0.2 的 L1 门禁与 L8 渲染改动均基于该实测。

**实现状态：M1（L0 契约 + L3 指令解析 + L5 事实锚点校验器）已落地**，44 例测试通过，见 [`../content-plane/README.md`](../content-plane/README.md)。M1 刻意不接模型——事实门禁不可靠时，无法区分"模型没编造"和"我们没检查"。

**已由用户拍板的决策（其余均为待评审的设计判断）：**

| 决策 | 用户选择 | 落点 |
| --- | --- | --- |
| 项目落点 | `E:\python\代码\resume`，独立设计，不改动上游仓库 | 全文 |
| 简历正文的模型可见性 | 双模式：默认本地模型；云端需逐次授权（Gate E） | §2 |
| 修改权归属 | 三源合流：用户指令 > JD 缺口 > 模型表达自由 | §1.5 |

---

## 0. 一句话结论

把"简历改写"做成一个**内容面与控制面分离**的本地 Agent：原始简历正文、改写候选、片段文本只存在于本机内容面进程内；DSH Transcript 与工具响应只看到 **ID、哈希、标签、计数和 diff 摘要**。默认走本地模型（正文永不出本机），云端模型需要**逐次出网授权**（Gate E），且只发送最小必要片段与脱敏后的文本。

改写的每一句都必须能追溯到简历原文或用户显式声明的事实——**证据锚定是硬门禁，不是提示词约束**。

**实测补注（v0.2）：** 真正会拖垮这个 Agent 的不是模型改写质量，而是**读取环节的静默失败**。实测中 `pdftotext` 把中文以 0.0% 的保留率静默丢弃，表格版 DOCX 的章节归属被静默打乱，两者都返回了成功状态。因此 L1 增加了**提取置信度硬门禁**（§5.1.1），产出模式默认改为**模板重生**而非原地改写（§5.1.2）。

---

## 1. 问题与动机

### 1.1 现状

| 仓库 | 已有的能力 | 缺的能力 |
| --- | --- | --- |
| `job`（Python，本地求职流水线） | 简历文本加载（`src/resume/loader.py`，支持 pdf/docx/md/txt）、检索分块（`src/resume/chunker.py`，`CHUNK_SIZE=500` / `CHUNK_OVERLAP=50`）、三路匹配（`0.35*kw + 0.35*vec + 0.30*rerank`）、本地 Ollama 调用 | 无块级结构、无简历文件哈希、无版本表（只有 `resume_version` 字符串列，默认 `"v1"`）、无改写 |
| `boss-watch-agent`（TS，DSH 插件） | `ResumeVersion` 本地版本目录（内容寻址、SHA-256、`supersedes` 父引用）、`resume_match` 脱敏匹配快照、Gate A/B 审批身份、严格隐私边界 | 明确不做简历内容生成（见 §1.3 原文引用） |

`job/docs/DESIGN.md` 把这件事列为远期：

> L75（§3.3 P2 远期）：`- 简历自动 tailoring（针对 JD 改写项目描述）`

### 1.2 为什么不能只是"加个 prompt"

1. **检索分块不能拿来编辑。** `chunker.py` 产出 500 字滑窗、50 字重叠，同一段文字出现在两个 `ResumeChunk` 里（`id = {resume_version}#{section}#{order}`，`order` 是跨 section 全局计数器）。对重叠块做改写会在合并时产生重复段落。**编辑需要语义块（一条 bullet = 一个可编辑单元，无重叠、可逆映射回原文），这是与检索分块完全不同的抽取器。**
2. **改写必须能证明没编造。** 简历注水是这类 Agent 的头号失败模式。用户真正要买的不是"更漂亮的措辞"，而是"改动可核对、不撒谎"。
3. **改写必须让模型读到正文，这与上游契约正面冲突。** 见 §2。

### 1.3 与上游契约的冲突（必须先显式承认）

`boss-watch-agent` 现行契约逐字：

- `AGENTS.md`：`The default product mode is observation-only. Do not add automatic external messaging, resume delivery, interview acceptance, or follow-up without an explicit approval contract and focused tests.`
- `docs/job-search-agent-spec.md:36`：`不在 MVP 1.0 自动生成或改写定制化简历；当前批次只引用用户明确选定的既有简历版本；`
- `docs/superpowers/plans/2026-08-18-resume-version-delivery.md:26`：`不生成定制简历；`（同段另有 `不解析或抽取简历正文；不把简历上传到模型、岗位来源或飞书；`）
- `README.md:45`：`原文不写入 DSH Transcript，不上传外部模型`
- 实现注释（`packages/dsh-plugin/src/resume-version.ts:353-357`）：`Callers must keep the returned text in-memory and must not put it in a transcript, log, SQLite row, or tool response.`

**结论：本文档与上述非目标直接冲突，落地前必须由仓库所有者修订契约（把"不生成定制简历"改为"允许在 Gate T/E/W 下生成定制简历"），并补聚焦测试。这是前置条件，不是并行项。**

`job` 侧的冲突较轻：只需把 §3.3 的 P2 提为 v2 主体，且 `DESIGN.md` 的 `不做在线学习 / 简历自动改写（可列为 v2）` 需要同步修订。

### 1.4 非目标（本设计明确不做）

- 不自动投递、不自动打招呼、不上传 ATS、不写招聘方/飞书（归 `boss-watch-agent` 的 Gate A/B 管）。
- 不修改或覆盖任何既有 `ResumeVersion` 文件；只追加新版本。
- 不生成"无源经历"；不接受把 JD 要求的技术词搬进简历。
- 不做多用户 / SaaS / 权限体系；单用户本机桌面事实账本。
- 不做在线学习、不做模型微调、不做面经生成。

### 1.5 修改权层级（三源合流）

"改什么"由谁决定，必须显式分级，不能由实现细节默认成"规则说了算"。

```text
0. 硬约束（任何来源都不能越过）
   - 事实单元只能来自简历原文，或用户显式声明的事实
   - 禁止 JD 注入：JD 要求但简历与用户事实都没有的技术词，不得进入正文

1. 用户的显式指令          最高业务优先级
2. 用户的持久化偏好        可选，跨任务复用
3. JD 缺口（GapReport）    默认驱动源，仅在无指令时生效
4. 模型自主                仅限表达层：措辞 / 语序 / 同类合并 / 强调谁
```

**两条冲突规则：**

- **指令优先于 JD，但冲突必须显式暴露。** 当指令方向与 JD 缺口相反（例如指令要求"弱化后端"，而目标岗位正是后端岗），系统**不得静默按 JD 改**，必须返回 `tailor_instruction_conflicts_with_gap` 并附两侧依据，由用户裁决。
- **指令不能越过事实门禁。** 指令要求写入简历没有的事实（"加上我会 Kubernetes"）时，系统不执行改写，而是要求用户把它**声明为事实**（附证据），声明后才成为合法锚点。这是"想怎么改就怎么改"唯一的后门。

**模型自主权的边界**（回答"是不是模型认为怎么改就怎么改"）：

| 层 | 模型可否自主 | 例子 |
| --- | --- | --- |
| 表达层 | ✅ 可以 | 把"负责了 X 的开发"改成"负责 X 开发" |
| 主张层 | ❌ 不可以 | 决定"这段应该突出架构能力"——须由指令或 JD 缺口驱动 |
| 事实层 | ❌ 不可以 | 任何数字、时间、公司名、技术词 |

用户在 Gate T 之外还拥有：逐块接受/拒绝权（§5.6）、事实声明权。

---

## 2. 核心矛盾与解法：双模式

改写要求"模型看到正文"，上游要求"正文不外流"。二者不可同时满足，只能**把'外流'定义清楚并按次授权**。

```
                        ┌─────────────── 控制面 (Control Plane) ───────────────┐
                        │  DSH Transcript / 工具响应 / SQLite 元数据            │
                        │  只出现：id · hash · section 标签 · 计数 · diff 摘要   │
                        │  永不出现：简历原文 · 改写文本 · 片段文本              │
                        └───────────────────────┬──────────────────────────────┘
                                                │ loopback + 服务令牌
                                    只允许 id/hash/结构化标签跨越
                                                │
                        ┌───────────────────────┴──────────────────────────────┐
                        │ 内容面 (Content Plane)  本机进程，0700/0600 权限       │
                        │  简历原文 · ResumeDoc/Blocks · 改写候选 · 事实校验     │
                        └──────┬───────────────────────────────┬───────────────┘
                               │                               │
                    模式 L（默认）                    模式 C（需 Gate E 逐次授权）
                               │                               │
                    ┌──────────┴──────────┐        ┌───────────┴────────────┐
                    │ 本地 Ollama          │        │ 云端 provider/model    │
                    │ 正文永不出进程        │        │ 只发最小片段 + 脱敏文本 │
                    └─────────────────────┘        └────────────────────────┘
```

### 2.1 模式 L：本地（默认）

- 模型：复用 `job` 的 Ollama 约定（`ollama_host`，默认 Windows 宿主机 `11434`；`ollama_chat_model`）。
- 出网：无。
- 仍需审计（记录模型标识、处理的 block、耗时、verdict 统计），但不需要 Gate E。
- 建议模型档位：`qwen2.5:7b-instruct` 起步；`3b` 档只用于"规范化措辞"，不用于"重构表达"。

### 2.2 模式 C：云端（逐次授权）

触发条件：用户显式选择模式 C **且** 持有未过期、未消费、范围匹配的 `EgressApproval`（Gate E，见 §7）。

发送前固定流水线：

```text
选中 block 集合
  -> 计算 spanScopeHash = sha256(sorted(blockId:spanHash) 列表)
  -> 脱敏（姓名/电话/邮箱/身份证/住址 → 《NAME》/《PHONE》/…）
  -> 组装最小 payload = [脱敏 block 文本] + [block.section] + [口径化 JD 要求标签]
  -> 字符数校验：Σ chars <= approval.maxChars，否则 tailor_egress_scope_exceeded
  -> 记录 egress ledger（发送内容哈希 + 字符数 + provider/model + 授权 id + 时间）
  -> 单次调用 -> 消费授权（consumed_at 落库）
  -> 响应回到内容面 -> 回填占位符 -> 进入事实校验
```

**绝不发送**：整份简历、照片、未选中的 block、BOSS 页面内容、招聘方消息、任何 cookie/令牌。

---

## 3. 总体架构

### 3.1 分层

```text
L0  Domain        纯数据契约：ResumeDoc / Block / GapReport / EditPlan / Edit / Verdict / TailorLineage
L1  Extract       简历字节 → ResumeDoc（语义块，无重叠，span 可逆映射回原文）+ 提取置信度门禁
L2  Diagnose      ResumeDoc × JD → GapReport（要求级覆盖 + 缺失 + 约束）
L3  Plan          GapReport → EditPlan（确定性规则优先，LLM 可选增强）
L4  Rewrite       内容面：模式 L / 模式 C，schema 校验 + 重试
L5  Verify        事实锚点校验器 + 能力升级检测 + JD 注入检测 + ATS 检查   ← 核心
L6  Review        块级 diff 渲染到本地 UI（不进 Transcript）
L7  Version       新 ResumeVersion + TailorLineage（交给上游版本目录）
L8  Render        输出 md / docx / pdf（docx 优先）
L9  Policy         Gate T / E / W、审批令牌、出网账本、审计
```

依赖方向严格单向 `L0 ← L1 ← … ← L9`；`L2` 复用 `job` 的匹配算法，`L7` 对齐 `boss-watch-agent` 的 `ResumeVersion` 身份规则。

### 3.2 端到端闭环

```text
已捕获完整 JD (applicationId)
      │
      ├─ resume_tailor_gap_preview      → GapReport（只有标签/计数/哈希）
      │
      ├─ resume_tailor_plan_preview     → EditPlan 摘要（哪些 block、什么动作、多少条）
      ├─ resume_tailor_plan_confirm     → ★ Gate T
      │
      ├─ [模式 C] resume_tailor_egress_preview / _apply → ★ Gate E
      │
      ├─ resume_tailor_run_apply        → 内容面执行改写，返回 verdict 统计，无文本
      │
      ├─ resume_tailor_review_open      → 本地 UI 逐块评审（接受/拒绝/声明新事实）
      │
      ├─ resume_tailor_commit_preview   → 预览将生成的新版本（哈希/字数变化）
      ├─ resume_tailor_commit_apply     → ★ Gate W → 新 ResumeVersion + Lineage
      │
      └─ resume_tailor_audit_list       → 审计账本
                    │
                    └─> 交给 boss-watch-agent 重新 resume_match 做 A/B 度量（§12）
```

### 3.3 部署形态

| 组件 | 语言 | 职责 | 权限 |
| --- | --- | --- | --- |
| `content-plane` 本地服务 | Python 3.12 | 抽取、改写、校验、渲染、内容寻址工件 | 0700 目录 / 0600 文件，loopback only |
| `control-plane` DSH 插件 | TypeScript | 工具 schema、Gate 令牌、状态派生、UI | 只经 loopback 调内容面 |
| 本地评审 UI | TS（DSH client plugin） | 块级 diff 展示与逐条决策 | 经 loopback，不经 Transcript |

内容面 = Python 的理由：`job` 已有 loader/chunker/匹配/Ollama 客户端；中文字体与 docx 渲染在 Python 侧更成熟。
控制面 = TS 的理由：Gate/令牌/工具 schema/隐私边界在 `boss-watch-agent` 已经成型，直接沿用其约定。

**边界契约（硬规则）：跨 loopback 的 payload 只允许出现 `id / hash / section 标签 / 枚举 / 计数 / 时间`。任何携带正文的响应都是设计缺陷。** 唯一例外是本地评审 UI 的渲染通道——它由用户在浏览器直连内容面读取渲染结果，不经过模型。

---

## 4. 数据契约（L0）

```ts
// 语义块：编辑的最小单位。无重叠、span 可逆映射回原文。
interface ResumeBlock {
  blockId: string            // "block:" + sha256(resumeContentHash + section + ordinal + textHash)
  resumeContentHash: string  // 来源简历版本的内容哈希（= boss-watch 的 contentHash）
  section: 'summary' | 'education' | 'work' | 'project' | 'skill' | 'award' | 'other'
  kind: 'bullet' | 'heading' | 'meta' | 'skill-list'
  ordinal: number            // section 内序号
  textHash: string           // sha256(原文文本)
  charCount: number
  immutable: boolean         // education/meta/日期 默认不可改写
  sourceSpan: { start: number; end: number } | null   // 内容面内部使用，不外传
}

interface GapItem {
  requirementId: string      // "req:" + sha256(要求文本)
  label: string              // 口径化标签，不外传原文
  coverage: 'covered' | 'partial' | 'missing'
  bestBlockIds: string[]     // 命中的块
  requirementTerms: string[] // 该要求涉及的技术词（口径化）；指令冲突检测依赖它，M1 实现新增
  reason?: string            // 枚举：missing_skill / evidence_missing / hard_constraint / preference_mismatch
}

interface GapReport {
  gapReportId: string
  applicationId: string
  resumeContentHash: string
  jdContentHash: string
  items: GapItem[]
  matchScore: number         // 复用 job 的三路融合结果
  risks: string[]
}

interface TailorInstruction {
  instructionId: string
  text: string               // 用户原话，原文保留
  source: 'user_message' | 'user_profile'
  receivedAt: string
}

// 指令的结构化形态。它是 Gate T 的实际审批对象之一，且只描述范围与目标，不产出文本。
interface TailorIntent {
  intentId: string
  instructionId?: string     // 无指令时为 undefined（纯 JD 驱动）
  scopeBlockIds: string[]    // 与 scopeSections 二选一或同时出现；
  scopeSections: string[]    // 原写法是 scope: {blockIds} | {sections}，M1 实现扁平为两个字段，语义等价
  goal?: 'emphasize' | 'deemphasize' | 'condense' | 'expand' | 'reword' | 'reorder'
  constraints: { maxChars?: number; keepNumbers: true; language: 'zh' | 'en' }
  conflictsWithGap: { requirementId: string; gapDirection: string; instructionDirection: string }[]
  parseConfidence: 'high' | 'low'   // low 时，产出需澄清而不能直接生成计划
  clarificationOptions: string[]    // low 时给出的澄清候选，供用户直接选
}

interface EditPlan {
  planId: string             // "tailor-plan:" + sha256(resumeHash \n jdHash \n planJson \n instructionHash \n strategyVersion)
  strategyVersion: 'resume-tailor-plan-v1'
  driver: 'instruction' | 'jd_gap'
  intentId?: string          // driver == 'instruction' 时必填
  instructionHash?: string   // 纳入 planId，使"你的哪句话"也成为被审批的内容
  steps: {
    blockId: string
    action: 'rewrite' | 'reorder' | 'condense' | 'expand' | 'drop' | 'keyword_align'
    direction: string        // 口径化指令，如 "突出量化结果" / "弱化与被投岗位无关的技术栈"
    origin: 'instruction' | 'jd_gap'   // 每个步骤的驱动来源，可追溯到指令或缺口
    constraints: { maxChars?: number; keepNumbers: true; keepTechTerms: true }
  }[]
  rejected: { blockId: string; reason: string }[]   // 不可改写块（immutable / 证据不足）
  requiresGateT: true
}

interface Edit {
  editId: string
  blockId: string
  changeType: 'rewritten' | 'reordered' | 'unchanged' | 'dropped'
  sourceTextHash: string
  resultTextHash: string     // 正文存内容寻址工件，SQLite 只存哈希
  cites: string[]            // 引用的源 blockId
  declarations: string[]     // 引用的 user_declared_fact_id
  verdict: Verdict
}

interface Verdict {
  units: {
    text: string             // 事实单元（数字/时间/专有名词/技术词/职级词）
    class: 'metric' | 'time' | 'proper_noun' | 'tech' | 'seniority'
    status: 'anchored' | 'abstracted' | 'upgraded' | 'unsupported'
    anchorRef?: string       // 命中的 blockId 或 declaration id
  }[]
  jdInjection: string[]      // JD 有、简历与用户事实都没有的技术词（必须为空才能提交）
  atsIssues: string[]
  decision: 'accept' | 'needs_user_confirmation' | 'reject'
}

interface TailorLineage {
  lineageId: string
  newResumeVersionId: string
  baseResumeVersionId: string
  tailorId: string
  planId: string
  jdContentHash: string
  mode: 'local' | 'cloud' | 'rule'
  modelRef: string           // 如 "ollama:qwen2.5:7b-instruct"
  strategyVersion: string
  createdAt: string
}
```

---

## 5. 流水线详述

### 5.1 L1 抽取：语义块（新增，不复用检索分块）

输入：`ResumeVersion` 的正文（经上游 `readText` 的等价实现，正文留在内容面）。

```text
简历文本
  -> 段落切分（空行 / 项目符号 ▸ - • * · / 编号 1. 2））
  -> 标题识别（沿用 job 的 SECTION_PATTERNS，注意迁移到完整词表）
  -> 块类型判定：heading / bullet / meta / skill-list
  -> 去重叠、去重、合并续行
  -> 输出 ResumeBlock[]
```

**必须修的坑（来自 `job` 现状）：**

| 现状 | 问题 | 本设计 |
| --- | --- | --- |
| section 词表只有 `education/work/project/skill`，未命中落到 `general`；DESIGN 写的 `other` 永不产生 | 词表与文档不一致，`general` 未定义 | 统一为 `summary/education/work/project/skill/award/other`，`general` 废弃 |
| `chunk_text(size=500, overlap=50)` 滑窗 | 重叠块合并会产生重复段落 | 编辑路径**不使用滑窗**；检索路径可继续用 |
| `order` 是跨 section 全局计数器 | 块定位不稳定 | 改为 section 内 `ordinal` |
| 无简历文件哈希 | 无法把块绑定到精确版本 | `resumeContentHash = sha256(bytes)`，与上游 `ResumeVersion.contentHash` 同源 |
| 无 token 上限校验 | 长块可能超模型上下文 | 按 `charCount` 上限切分长 bullet，并标记 `truncated` |

不可改写块（`immutable`）：`education`（学校/专业/时间/绩点）、`meta`（姓名联系方式）、所有日期区间。**改写只允许作用在 `work` / `project` / `summary` 的 `bullet` 上。**

#### 5.1.1 提取置信度门禁（硬门禁，实测后新增）

**不能假设"提取器返回成功"就是"提取正确"。** 见 `FEASIBILITY-READ-WRITE.md`：实测中 `pdftotext` 把中文以 **0.0%** 的保留率静默丢弃，表格版 DOCX 的章节归属被静默打乱，两者都返回了正常的成功状态与合理的字符数。

L1 必须在产出 `ResumeDoc` 前做自检，并据此决定后续可走哪条路径：

```text
cjkRetentionRatio   源文件语言含中文时，提取结果的中文占比是否合理
layoutIntegrity     每个章节标题后是否紧跟本章节条目（无外栏内容插入）
tokenIntegrity      是否存在技术词粘连（如 JavaSpring BootMySQLRedis）
runBoundaryMap      是否保留了 block <-> <w:p>/<w:r> 的映射
silentLossProbe     提取字符数 / 源文件文本层预估字符数
```

任一项低于阈值 → `extractionConfidence = low`，**禁止进入原地改写路径**，错误码 `tailor_extraction_low_confidence`。

**自检必须在提取后立刻执行**，不能等到改写完成才发现——实测中的两类静默失败在提取阶段就完全可检测。

#### 5.1.2 两种产出模式：默认不是"原地改写"

| 模式 | 前提 | 保留什么 | 代价 |
| --- | --- | --- | --- |
| **重生模式（Rebuild，默认）** | 任意可提取的源 | 事实（经锚点校验）+ 章节结构；由受控模板渲染 | 用户原版的个性化版式丢失 |
| **原地模式（Patch）** | `extractionConfidence = high` **且** `runBoundaryMap` 完整 | 原版式、原 run 级格式、未被改写的段落逐字不变 | 只能改措辞；跨 run 的目标子串必须切分/合并 run 并克隆 `rPr` |

**重生模式作为默认**，因为它把"格式正确性"从无界问题变成有界问题：模板由我们控制，ATS 安全性可验证，版式不会漂移。原地模式是高置信度下的可选增强。

这同时消解了表格版简历的章节归属问题——低置信度文件直接进重生模式，不再需要"猜"章节归属（猜错会静默写坏）。

### 5.2 L2 诊断：复用而非重写

直接复用 `job` 的匹配栈，但输出从"分数"升级为"要求级 + 块级"证据：

- `match/keyword.py`：`cover(r) = max_c hit(r, c)`，`matched = cover >= 0.5`，`missing = cover < 0.3`
- `match/vector.py`：`0.7*max + 0.3*top3`，section boost `{skill/work/project: 1.1, education/general: 0.7}`
- `match/fusion.py`：`(0.35k + 0.35v + 0.30r) * 100`，缺失路按剩余权重归一

**已知上游缺陷，本设计不继承：**

1. `match/rerank.py` 的 `coarse * 100 >= settings.rerank_gate` 与 `fusion.fuse` 已返回 0~100 冲突，等价于闸门恒开。本设计在调用侧修正为 `coarse >= settings.rerank_gate`。
2. `fusion.build_reasons` 接收 `evidence` 却未使用。诊断必须使用 `evidence`（每条 requirement → 最佳块），这是块级定位的唯一来源。
3. `tfidf_cosine` 名为 TF-IDF 实为词频余弦。对缺口诊断影响可接受，但需在 `risks` 中标注 `lexical_only`。

### 5.3 L3 计划：指令优先，规则兜底

计划的驱动源由 §1.5 的层级决定：

```text
若存在用户指令:
    intent = parseInstruction(instruction)        # 只产出范围与目标枚举，不产出文本
    若 intent.parseConfidence == 'low'
        -> 要求澄清，不生成计划（tailor_instruction_ambiguous）
    若 intent.conflictsWithGap 非空
        -> 返回 tailor_instruction_conflicts_with_gap，附两侧依据，交用户裁决
    steps = planFromIntent(intent, gapReport)     # 指令定范围与目标（driver='instruction'）
否则:
    steps = planFromRules(gapReport)              # 兜底：规则从 JD 缺口推（driver='jd_gap'）
```

**规则兜底（无指令时）**：

```text
for each block where block.immutable == false:
    if block 命中某个 missing requirement 的最佳块候选 and 该块无量化结果:
        action = expand,  direction = "补充可核对的量化结果（需用户确认）"
    elif block 含与目标岗位无关的技术栈 and 该块另有强相关技术:
        action = condense, direction = "弱化无关技术栈，保留强相关部分"
    elif block 长度 > p90 and 无可核对量化:
        action = condense, direction = "压缩至 ≤ N 字，保持事实单元不变"
    else:
        action = keyword_align, direction = "在不改变事实的前提下对齐术语口径"
```

排序规则：`summary` 块优先（HR 先读），其次命中 JD 要求的 `project`/`work` 块。指令显式指定的 `scope` 覆盖排序规则。

**意图解析的三条边界**：

1. `parseInstruction` **只产出范围与目标枚举，绝不产出文本**——文本一律由 L4 生成并受 L5 校验。指令无法直接把内容塞进简历。
2. 解析置信度低（如"写得好一点"）**必须澄清**，不得猜测后直接生成计划。
3. 指令要求写入简历没有的事实时，解析层**不拦、也不照做**——它正常生成计划，由 L5 事实门禁拦下并转为"声明为事实"流程。**拦截点统一在 L5，避免两处规则分叉。**

**LLM 在规划阶段是可选的**：`plan.strategy = rule | llm_assisted`。默认 `rule`，因为规则计划的**可解释性与可复现性远高于 LLM 计划**，且 `planId` 是 Gate T 的审批对象——审批对象必须确定。指令解析同理：低置信度时宁可澄清，不可让审批对象变得不确定。

每个 `step.origin` 标明驱动来源，使用户在 Gate T 能看清"这条改动是你要的，还是 JD 推出来的"。

### 5.4 L4 改写：内容面执行

约束（写入 system prompt 并且**在 L5 用代码强制**，不只靠提示）：

```text
- 只输出 JSON：{"blockId": "...", "text": "..."}
- 不得新增任何数字、公司名、时间、技术词、职级词
- 不得把"参与"升级为"主导"/"负责"，不得把"了解"升级为"熟悉"/"精通"
- 允许的变换方向：措辞规范化、要点前置、同类合并、降级表达
- 保持原语言（中文简历不改写成英文）
- 保留全部原有事实单元
```

失败处理：JSON 解析失败 → `temperature=0` 重试 1 次 → 仍失败则**该块保持原文**并记录 `tailor_output_schema_invalid`。绝不接受无法解析的文本。

### 5.5 L5 事实锚点校验器（本设计的技术核心）

对每条 `Edit` 的产出文本，抽取**可验证事实单元**并逐个溯源：

| 类别 | 抽取方式 | 溯源白名单 |
| --- | --- | --- |
| `metric` | 正则 `\d+(\.\d+)?\s*(%|万|亿|ms|s|qps|tps|人|次|倍)` | 被引用源块原文 / `user_declared_facts` |
| `time` | 年份、区间、时长 | 同上；跨块引用需全部命中 |
| `proper_noun` | 机构/产品/学校（用源块实体集合 + 用户事实集合做白名单） | 同上 |
| `tech` | 命中 `job/src/match/skills_map.json`（21 条同义词映射）∪ `boss-watch-agent` 的 `SKILL_ALIASES`（29 项技术词，含 `RAG`/`LLM`/`Agent`） | 同上 |
| `seniority` | 动词/程度词表：主导·负责·参与·协助·熟悉·掌握·精通·了解 | 见下方向性规则 |

**判定与方向性规则**（这是"防止简历注水"的关键）：

```text
anchored    事实单元能在被引用源块或用户声明中找到            -> 通过
abstracted  等价或降级变换（负责 -> 参与；精通 -> 熟悉）      -> 通过，记录
upgraded    能力升级（参与 -> 主导；熟悉 -> 精通；了解 -> 掌握）-> 必须用户逐条确认，否则 reject
unsupported 在任何白名单都找不到                              -> 默认 reject
```

**JD 注入检测（独立硬门禁）：**

```text
injected = (JD 中出现的技术词) ∩ (改写文本中出现的技术词) - (源块已有词 ∪ 用户声明词)
若 injected 非空 -> 该 Edit 直接 reject，错误码 tailor_jd_skill_injection
```

这条规则的意义：**不允许因为岗位要求 Kubernetes 就把 Kubernetes 写进简历。** JD 有、简历没有的技术词只能出现在 `GapReport` 里，永远不能出现在改写后的正文里。

**ATS 检查：** 保留原有关键词密度、单栏、无文本框、无图片化文字、section 标题使用标准词、日期格式统一。

### 5.6 L6 评审：块级 diff 不走 Transcript

`resume_tailor_review_open(tailorId)` 让本地浏览器直连内容面渲染评审页：

```text
[project] 订单履约系统重构                        verdict: anchored ✅
  - 原文：负责订单模块开发，优化了接口性能
  + 改写：负责订单履约模块开发，将核心查询接口 P99 从 320ms 降到 90ms
  └ 事实单元：320ms ✅anchored(源块)   90ms ⚠️unsupported  →  需声明
     [声明为事实并附证据]  [删除该数字]  [接受整个改写]  [拒绝]
```

- 未确认 `unsupported` / `upgraded` 的 Edit **不能进入 commit**。
- 用户声明新事实时写入 `user_declared_facts`（含证据说明），此后该事实成为合法锚点。
- **整个页面的文本不经过模型，因此不进 Transcript。** 这是"用户要看改写结果"与"正文不外流"能同时成立的唯一办法。

### 5.7 L7 版本与血缘

产出新的 `ResumeVersion`，与 `boss-watch-agent` 的身份规则完全对齐：

```text
contentHash     = sha256(渲染后的字节或规范化 md 字节)
resumeVersionId = "resume-version:" + contentHash
localArtifactRef= "local-resume://sha256:" + contentHash
supersedesResumeVersionId = 基础版本 resumeVersionId

tailorId  = "tailor:" + sha256(baseResumeHash \n jdContentHash \n planId \n strategyVersion)
lineageId = "tailor-lineage:" + sha256(tailorId \n newResumeVersionId)
```

- 原始版本文件**永不修改**，新版本只追加。
- 同 `contentHash` 重复提交 → 幂等复用已有版本（对齐上游 `save()` 的 `reused: true`）。
- `supersedesResumeVersionId` 必须指向已存在版本，否则 `tailor_supersedes_not_found`。

### 5.8 L8 渲染

优先级：`docx` > `md` > `pdf`。

**重生模式（默认）：受控模板 + 事实注入**

```text
受控模板（单栏、纯文本、无文本框、无表格）
  + 事实账本（anchored facts）
  + 改写后的措辞
  -> 渲染新 DOCX
```

模板由本项目控制，因此版式、字体、章节标题、日期格式全部可验证，不受源文件结构影响。

**原地模式（高置信度才允许）**：在 `word/document.xml` 上就位替换目标段落/字符区间，重新打包。

- 目标子串落在单个 run 内 → 原地替换，保留 `rPr`。
- 目标子串跨 run → 定位跨 run 字符区间，拆分/合并 run，克隆 `rPr`，处理 `xml:space`。
- 抽象语义（"把这一段写得更强调量化结果"）**不适用原地模式**——它必然要重排 run，等于放弃格式，应直接走重生模式。

**实测依据**（`FEASIBILITY-READ-WRITE.md` §6）：`readText → xmlToText` 只产出纯字符串，不含 run 边界信息；整段替换会丢掉全部 run 级格式（实测加粗标记 2 → 0）；跨 run 的目标子串（XML 里是 `"…从 1"` + `"200"`）用整串 `1200` 替换会**静默失配**。

**ATS 文本还原检查（强制）**：把渲染产物重新抽取文本，与预期文本逐字比对；不一致则拒绝输出，错误码 `tailor_render_fidelity_check_failed`。

`pdf` 用 LibreOffice headless 从 docx 转换，避免两套排版。**注意：本机实测 `libreoffice`/`soffice` 不存在**，该路径需要显式依赖声明与可用性探测，缺失时降级为"只输出 docx + md"。

文本工件内容寻址存放：`<contentRoot>/.content/<sha256>`，`0700/0600`，**SQLite 只存哈希**。

---

## 6. 存储设计

复用上游约定：SQLite + WAL + `busy_timeout=5000` + `synchronous=NORMAL`，写路径 `BEGIN IMMEDIATE` 串行化；**正文不进 SQLite 行**。

```sql
-- 语义块目录：只存哈希与结构，不存文本
CREATE TABLE IF NOT EXISTS resume_blocks (
  block_id            TEXT PRIMARY KEY,
  resume_content_hash TEXT NOT NULL CHECK (length(resume_content_hash) = 64),
  section             TEXT NOT NULL,
  kind                TEXT NOT NULL,
  ordinal             INTEGER NOT NULL,
  text_hash           TEXT NOT NULL CHECK (length(text_hash) = 64),
  char_count          INTEGER NOT NULL CHECK (char_count >= 0),
  immutable           INTEGER NOT NULL DEFAULT 0,
  UNIQUE (resume_content_hash, section, ordinal)
);

CREATE TABLE IF NOT EXISTS resume_tailor_plans (
  plan_id             TEXT PRIMARY KEY,
  application_id      TEXT NOT NULL,
  resume_version_id   TEXT NOT NULL,
  resume_content_hash TEXT NOT NULL CHECK (length(resume_content_hash) = 64),
  jd_content_hash     TEXT NOT NULL CHECK (length(jd_content_hash) = 64),
  strategy_version    TEXT NOT NULL,
  plan_json           TEXT NOT NULL,
  created_at          TEXT NOT NULL,
  confirmed_at        TEXT,
  gate_t_id           TEXT
);

CREATE TABLE IF NOT EXISTS resume_tailor_runs (
  tailor_id            TEXT PRIMARY KEY,
  plan_id              TEXT NOT NULL,
  mode                 TEXT NOT NULL CHECK (mode IN ('local','cloud','rule')),
  model_ref            TEXT NOT NULL,
  span_scope_hash      TEXT,
  egress_approval_id   TEXT,
  status               TEXT NOT NULL CHECK (status IN ('started','completed','partial','failed')),
  started_at           TEXT NOT NULL,
  finished_at          TEXT,
  error_code           TEXT
);

CREATE TABLE IF NOT EXISTS resume_tailor_edits (
  edit_id           TEXT PRIMARY KEY,
  tailor_id         TEXT NOT NULL,
  block_id          TEXT NOT NULL,
  change_type       TEXT NOT NULL,
  source_text_hash  TEXT NOT NULL CHECK (length(source_text_hash) = 64),
  result_text_hash  TEXT          CHECK (result_text_hash IS NULL OR length(result_text_hash) = 64),
  cites_json        TEXT NOT NULL DEFAULT '[]',
  declarations_json TEXT NOT NULL DEFAULT '[]',
  verdict_json      TEXT NOT NULL,
  decision          TEXT NOT NULL CHECK (decision IN ('accept','needs_user_confirmation','reject','pending')),
  created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resume_tailor_lineage (
  lineage_id            TEXT PRIMARY KEY,
  new_resume_version_id TEXT NOT NULL UNIQUE,
  base_resume_version_id TEXT NOT NULL,
  tailor_id             TEXT NOT NULL,
  plan_id               TEXT NOT NULL,
  jd_content_hash       TEXT NOT NULL CHECK (length(jd_content_hash) = 64),
  mode                  TEXT NOT NULL,
  model_ref             TEXT NOT NULL,
  strategy_version      TEXT NOT NULL,
  created_at            TEXT NOT NULL
);

-- Gate E 出网授权
CREATE TABLE IF NOT EXISTS resume_egress_approvals (
  approval_id         TEXT PRIMARY KEY,
  session_id          TEXT NOT NULL,
  resume_content_hash TEXT NOT NULL CHECK (length(resume_content_hash) = 64),
  span_scope_hash     TEXT NOT NULL CHECK (length(span_scope_hash) = 64),
  provider            TEXT NOT NULL,
  model               TEXT NOT NULL,
  max_chars           INTEGER NOT NULL CHECK (max_chars > 0),
  sent_content_hash   TEXT          CHECK (sent_content_hash IS NULL OR length(sent_content_hash) = 64),
  issued_at           TEXT NOT NULL,
  expires_at          TEXT NOT NULL,
  consumed_at         TEXT
);

-- 用户声明的事实（唯一允许无源事实的入口）
CREATE TABLE IF NOT EXISTS user_declared_facts (
  fact_id             TEXT PRIMARY KEY,
  resume_content_hash TEXT NOT NULL CHECK (length(resume_content_hash) = 64),
  text                TEXT NOT NULL,
  evidence_note       TEXT NOT NULL,
  declared_at         TEXT NOT NULL
);

-- 审计账本（追加写）
CREATE TABLE IF NOT EXISTS resume_tailor_audit (
  audit_id     TEXT PRIMARY KEY,
  at           TEXT NOT NULL,
  actor        TEXT NOT NULL,
  action       TEXT NOT NULL,
  subject_ref  TEXT NOT NULL,
  hashes_json  TEXT NOT NULL,
  outcome      TEXT NOT NULL
);
```

**内容寻址工件目录（唯一存正文的地方）：**

```text
<contentRoot>/                      0700
  ├─ .content/<sha256>              0600   派生文本工件（改写结果、渲染中间产物）
  ├─ .render/<tailorId>/resume.docx 0600   渲染产物
  └─ .reviews/<tailorId>.html       0600   本地评审页（可选落盘）
```

原始简历字节**不复制**到这里——它仍由上游 `ResumeVersion` 的内容寻址工件持有，本设计只读。

---

## 7. 审批与令牌

### 7.1 三道闸门

| Gate | 批准对象 | 令牌绑定 | 授权了什么 | 明确不授权 |
| --- | --- | --- | --- | --- |
| **T** | 一份精确改写计划（含驱动它的用户指令） | `planId + applicationId + resumeContentHash + jdContentHash + planHash + instructionHash + strategyVersion` | 允许对该计划的块执行改写 | 不改文件、不出网、不投递 |
| **E** | 一次云端出网 | `sessionId + resumeContentHash + spanScopeHash + provider + model + maxChars + expiresAt` | 允许把**该范围**片段发给**该**模型一次 | 不发其他块、不复用、不延长 |
| **W** | 一次版本落盘 | `tailorId + resultHash + baseResumeVersionId + targetFormat` | 创建新 `ResumeVersion` / 导出文件 | 不上传 ATS、不写飞书、不投递 |

对齐上游令牌纪律：`Bind every approval to the session, conversation, recipient, exact content hash, and expiration time.`

### 7.2 令牌结构

```ts
interface GateToken {
  gateId: string            // "gate-t:" | "gate-e:" | "gate-w:" + sha256(绑定字段 \n gateVersion)
  strategyVersion: 'gate-t-v1' | 'gate-e-v1' | 'gate-w-v1'
  sessionId: string
  binding: Record<string, string>   // 各 Gate 的字段集合
  issuedAt: string
  expiresAt: string         // T/E/W 均 15 分钟
  consumedAt?: string       // E 必须一次性
  decision: 'proceed'
  externalAction: 'not_authorized'  // 与上游 Gate A 同语义
}
```

### 7.3 失败关闭

| 条件 | 结果 |
| --- | --- |
| 令牌不存在 / 跨 session | `tailor_plan_not_found` / `tailor_session_mismatch` |
| 令牌过期 | `tailor_approval_expired` |
| 令牌已消费（Gate E） | `tailor_egress_approval_consumed` |
| 预览后简历或 JD 变化 | `tailor_plan_stale` / `tailor_commit_stale` |
| 出网范围超出授权 | `tailor_egress_scope_exceeded` |
| 缺出网授权但选了模式 C | `tailor_egress_approval_required` |
| 事实校验有注入或未确认升级 | `tailor_jd_skill_injection` / `tailor_capability_upgrade_unconfirmed` |
| 内容面不可用 | `tailor_content_plane_unavailable` |
| 指令解析置信度低 | `tailor_instruction_ambiguous` —— 要求澄清，不生成计划 |
| 指令方向与 JD 缺口相反 | `tailor_instruction_conflicts_with_gap` —— 附两侧依据，交用户裁决，**不得静默按 JD 改** |
| 指令要求写入简历没有的事实 | `tailor_fact_unsupported` —— 转为"声明为事实"流程，不执行改写 |

**页面内容、模型输出、Skill 文档都不能创建、延长或复用任何 Gate。**

---

## 8. 工具面（控制面）

命名空间 `resume_tailor_*`（独立于 `boss_watch_*`）。若日后挂载进 `boss-watch-agent` 插件，需改名为 `boss_watch_resume_tailor_*` 并同步其 Skill；**本设计不预设挂载方式**。

| 工具 | 副作用 | 返回内容 | 说明 |
| --- | --- | --- | --- |
| `resume_tailor_board` | 只读 | 候选 + 阶段 + `nextAction`/`nextTool` | 派生视图，复用上游 candidate-board 的形状 |
| `resume_tailor_gap_preview(applicationId, resumeVersionId)` | 只读 | GapReport（标签/计数/哈希） | 不返回简历或 JD 原文 |
| `resume_tailor_intent_preview(applicationId, resumeVersionId, instruction)` | 只读 | 结构化的 `scope`/`goal`/`parseConfidence`/`conflictsWithGap` | **指令入口**；只解析目标与范围，不生成文本；低置信度时要求澄清 |
| `resume_tailor_plan_preview(applicationId, resumeVersionId, instruction?, strategy?)` | 只读 | EditPlan 摘要（含每个 step 的 `origin`） | 无 `instruction` 时走 JD 缺口兜底；返回块 id、动作、条数；不返回文本 |
| `resume_tailor_plan_confirm(planId)` | 写本地 | Gate T | 幂等；同 planId 复用；`planId` 已包含 `instructionHash`，故"你的哪句话"也是被审批的内容 |
| `resume_tailor_egress_preview(spanScope)` | 只读 | 将发送的块数、字符数、脱敏替换计数、provider/model | 模式 C 必需 |
| `resume_tailor_egress_apply(previewToken, confirmed)` | 写本地 | Gate E | 一次性 |
| `resume_tailor_run_apply(planId, confirmed)` | 执行改写 | verdict 统计、失败块数、耗时 | **不返回任何正文** |
| `resume_tailor_review_open(tailorId)` | 打开本地页 | 本地 URL 句柄 | 文本只在该页出现 |
| `resume_tailor_commit_preview(tailorId, format?)` | 只读 | 新版本哈希预览、字数变化、计划处理的 Edit 数 | Gate W 前置 |
| `resume_tailor_commit_apply(previewToken, confirmed)` | 写本地 | 新 `ResumeVersion` + `lineageId` | 追加，不覆盖 |
| `resume_tailor_audit_list(limit?)` | 只读 | 审计条目 | 哈希与动作，无正文 |

**工具面禁止出现的能力**：不经 Gate W 写文件、不经 Gate E 出网、返回正文字符串、把 `review_open` 之外的正文渲染进 Transcript。

---

## 9. 降级与失败矩阵

| 失败 | 行为 | 是否产生事实 |
| --- | --- | --- |
| 本地模型不可用 | 降级规则改写（动词规范化 / 要点前置 / 长度裁剪 / 术语对齐），`mode='rule'` | 否 |
| 本地模型质量不达标（反复校验失败） | 该块保持原文，标记 `needs_review` | 否 |
| 模型输出 JSON 不合法 | `temperature=0` 重试 1 次；再失败则该块保持原文 | 否 |
| 模式 C 缺 Gate E | 拒绝执行，提示切模式 L 或先申请出网 | 否 |
| 事实校验命中 `unsupported` / `upgraded` | 转 `needs_user_confirmation`，commit 前必须处理 | 否（需声明） |
| 事实校验命中 JD 注入 | 直接 reject 该 Edit | 否 |
| 渲染失败 | 保留文本工件，不写 `ResumeVersion` | 否 |
| 内容面服务不可用 | 控制面返回稳定错误，不生成虚构结果 | 否 |
| 简历超长（> 200k 字符，对齐上游 `MAX_EXTRACTED_RESUME_CHARS`） | 返回 `tailor_resume_too_large`，提示分版本处理 | 否 |
| **指令解析置信度低** | 返回 `tailor_instruction_ambiguous` + 候选澄清项，**不生成计划** | 否 |
| **指令与 JD 缺口方向冲突** | 返回 `tailor_instruction_conflicts_with_gap`，展示两侧依据，等你裁决；默认不改 | 否 |
| **指令要求简历里没有的事实** | 不执行改写，转为"声明为事实"（附证据）；未声明则该 step 保持原文 | 否（需声明） |
| 指令与提取置信度门禁冲突（低置信度源） | 指令照常接受，但强制走重生模式，不做原地改写 | 否 |
| 提取置信度低 | `tailor_extraction_low_confidence`，禁入原地改写路径 | 否 |

---

## 10. 目录结构

```text
E:\python\代码\resume\
├─ docs\
│   ├─ ARCHITECTURE.md              ← 本文
│   ├─ FEASIBILITY-READ-WRITE.md    ← 读取/写回实测报告
│   ├─ CONTRACTS.md                 ← loopback 契约与工具 schema（待写）
│   └─ THREAT-MODEL.md              ← 出网与脱敏威胁模型（待写）
├─ fixtures\                        脱敏简历与 JD（禁止真实数据）
│   ├─ README.md                    回归语料说明与断言基线
│   ├─ gen.js / analyze.js / writeback.js
│   ├─ *.pdf / *.docx / *.html      5 个形态 fixture
│   └─ out\                         实测提取结果与两份报告
├─ content-plane\                    Python 3.12，本地服务
│   ├─ README.md                    M1+M2 范围、决策与已知局限
│   ├─ demo.py                      人工演示（L5 判定 / L3 解析）
│   ├─ demo_jd.py                   JD -> 缺口 -> 计划 -> 改写 端到端（M2）
│   ├─ src\resume_tailor\
│   │   ├─ domain\        契约（L0）                            ✅ M1+M2
│   │   ├─ lexicon\       技术词词库 + 粘连检测 + 同义短语       ✅ M1+M2
│   │   ├─ verify\        事实锚点 / 注入 / ATS（L5）★           ✅ M1
│   │   ├─ diagnose\      缺口诊断（L2，含同义覆盖）             ✅ M2
│   │   ├─ plan\          指令解析 + 冲突检测 + JD 计划           ✅ M1+M2
│   │   ├─ rewrite\       对齐/重排 + reword 门禁 + 模型工厂 + 完整管线 ✅ M2
│   │   ├─ review\        L6 评审：提案 → 接受/拒绝/声明事实             ✅ M2
│   │   ├─ extract\       语义块抽取 + 提取置信度门禁（L1）              ✅
│   │   ├─ render\        markdown 渲染（L7）                          ✅
│   │   ├─ store\         SQLite + 内容寻址工件 + 血缘（L7）            ✅
│   │   ├─ policy\        Gate W（L7）；Gate T/E 待做                    ⚠️
│   │   └─ api\           loopback HTTP + 服务令牌               ✅ P0（serve.py）
│   └─ tests\             167 例（M1 44 + M2 125，全过）
└─ control-plane\                   DSH 插件（TS）           ✅ P3/P4 已author（未构建/挂载）
    ├─ src\  tools · http-client · skill · index
    └─ test\
```

**运行与验证：**

```bash
cd content-plane
PYTHONPATH=src python3 -m unittest discover -s tests -t . -v   # 全量测试
PYTHONPATH=src python3 demo.py                                  # M1 人工演示
PYTHONPATH=src python3 demo_jd.py                               # M2 端到端演示
python3 -m compileall -q src tests                              # 语法检查
```

无第三方依赖；本机经 WSL Ubuntu-24.04 的 Python 3.12.3 运行。

**验证状态：169 例测试全部通过**（含 M2 的 125 例），`demo_extract.py` /
`demo_jd.py` / `demo_reword.py` / `demo_pipeline.py` / `demo_review.py` /
`demo_commit.py` / `demo_instruction.py` 端到端输出符合预期；模型 reword 已用
真 Ollama（qwen2.5-coder:7b）实测，门禁精准拦截模型的"拔高职级"倾向（见
`content-plane/README.md`）。数值归一化、模型工厂、完整管线、L6 评审、
L1 提取置信度门禁与字节→文本提取、L7 版本落盘、指令意图接入、P0 loopback
服务（serve + 服务/评审双令牌）均已落地；P3/P4（TS 薄插件切片 + Skill + preset）
已 author，待构建/挂载。

---

## 11. 安全与隐私检查清单

- [ ] 简历正文不进入 SQLite 任何列、不进入 DSH Transcript、不进入工具响应。
- [ ] 跨 loopback 边界的 payload 只含 id/hash/标签/枚举/计数/时间。
- [ ] 内容面目录 `0700`，工件 `0600`，创建用 `wx` 排他标志。
- [ ] 模式 C 必须持有未过期、未消费、范围匹配的 Gate E；`maxChars` 硬校验。
- [ ] 发送前脱敏（姓名/电话/邮箱/身份证/住址），返回后回填。
- [ ] 出网账本记录**实际发送内容**的哈希、字符数、provider/model、授权 id、时间。
- [ ] 云端 API Key 只从环境或系统密钥库读取，不落库、不进日志、不进 Transcript。
- [ ] 所有 Gate 绑定 `sessionId` 与精确内容哈希，15 分钟过期，Gate E 一次性。
- [ ] 测试与文档只用虚构/脱敏 fixture。
- [ ] `user_declared_facts.evidence_note` 必填，空则拒绝声明。

---

## 12. A/B 度量（改写到底有没有用）

提交后对同一 JD 分别匹配新旧版本（复用上游 `resume_match` / `job` 的三路融合）：

```text
matchDelta = {
  oldScore, newScore, delta,
  addedMatchedSkills, removedMatchedSkills,
  gapClosed: number, gapOpened: number,
  risksBefore, risksAfter
}
```

**防刷分守则（重要）：**

1. 只统计 `verdict.decision == 'accept'` 且事实单元全部 `anchored`/`abstracted` 的 Edit 带来的增量，记为 `effectiveDelta`。
2. 若 `delta > 0` 但存在任何 `unsupported` / `upgraded` 未确认 Edit → 标记 `score_gain_unverified`，**不计入有效提升**。
3. 若新增的 matched skill 全部来自 JD 注入 → `score_gain_injected`，且该状态不可能出现（L5 已 reject），出现即为 bug。
4. 若 `delta < 0` 且降幅 > 阈值 → 建议保留旧版本投递，把新版本作为备选。
5. 同一份简历对多个 JD 反复定向改写会产生"版本发散"：`lineage` 深度 > N（建议 5）时提示回到基础版本重做。

---

## 13. 交付切片

| 切片 | 内容 | 验收 |
| --- | --- | --- |
| **M0** | L0 契约 + L1 语义块抽取 + L2 缺口诊断（全只读、无模型） | **✅ L0/L1/L2 已实现** 语义块抽取正确切块、块数与原文 bullet 数一致、无重叠；提取置信度门禁在真实损坏产物（pdftotext 0% 中文、表格错乱）上判 low |
| **M1** | L5 事实锚点校验器 + L3 指令解析（纯本地、无模型） | **✅ 已实现（44 例测试通过）** 覆盖 `anchored/abstracted/upgraded/unsupported` 四类；JD 注入必被 reject；能力升级必转待确认；**指令解析覆盖：明确指令 / 低置信度要求澄清 / 与 JD 缺口冲突 / 要求无源事实转声明 四条分支**；给定改写文本与源块可确定性复现判定 |
| **M2** | L3 计划（指令优先 + 规则兜底）+ L4 改写 + L6 评审 | **✅ 已实现（129 例测试全过）** L1 语义块抽取 + 置信度门禁 + L2 缺口诊断 + L3 统一计划（指令驱动优先/JD 兜底，方向串进提示词）+ L4 安全改写（术语对齐 + 重排）+ L4 模型 reword（提示词不含 JD + L5 锚点 + 事实保留三道门禁，ollama/deepseek 适配器 + 模型工厂）+ L4 完整管线（对齐→reword→重排）+ L6 评审（提案→接受/拒绝/声明事实）+ 数值归一化 全部落地；每个 step 的 `origin` 可追溯到指令或 JD 缺口；**评审 UI（控制面）与 L7 之后的 docx/pdf 渲染、Gate T/E 待做** |
| **M3** | L7 版本与血缘 + Gate T/W | **✅ L7 已实现（Gate W 就绪）** 内容寻址落盘、同内容幂等 `reused`、`supersedes` 校验、血缘（tailorId/lineageId）、Gate W 两段式令牌（确认/过期/身份绑定/一次性）均落地；Gate T/E 与 docx/pdf 渲染待做 |
| **M4** | 模式 C 出网 + Gate E + 脱敏 + 出网账本 | 无授权必拒绝；范围超限必拒绝；授权一次性；账本记录实际发送哈希；payload 只含选中块 |
| **M5** | L8 渲染（docx 优先）+ A/B 度量（§12）+ 审计 | docx 版式与基础版本一致；`effectiveDelta` 与 `delta` 的差异可解释；审计可完整回放一次改写的全部哈希链 |

**每个切片必须带独立测试**，且 M1（校验器）必须先于任何模型调用落地——否则无法区分"模型没编造"和"我们没检查"。

---

## 14. 技术选型决策记录

| 决策 | 选择 | 备选 | 理由 |
| --- | --- | --- | --- |
| 内容面语言 | Python | 全 TS | 复用 `job` 的 loader/匹配/Ollama 客户端；docx/pdf 渲染与中文字体更成熟 |
| 控制面语言 | TypeScript | 全 Python | 复用 `boss-watch-agent` 的 Gate/令牌/工具 schema 约定与 DSH 插件形态 |
| 边界协议 | loopback HTTP + 服务令牌 | 进程内嵌 | 保持两面独立可测；对齐上游 4318 本机 Controller 的服务令牌模式 |
| 编辑单元 | 语义块（新增抽取器） | 复用 500 字滑窗 | 滑窗重叠会导致改写合并时重复段落 |
| 改写模型默认 | 本地 Ollama | 云端默认 | 用户决策：默认本地，云端逐次授权 |
| 计划生成 | 规则优先，LLM 可选 | LLM 优先 | `planId` 是 Gate T 审批对象，必须确定可复现 |
| 渲染首选格式 | docx | pdf | ATS 解析可靠、可继承样式、避免重排版 |
| 正文存放 | 内容寻址工件文件 | SQLite blob | 对齐上游 `resume_versions` 只存哈希的纪律 |
| **修改权归属** | **三源合流：用户指令 > JD 缺口 > 模型表达自由** | JD 优先 / 完全指令驱动 | 用户是简历所有者，必须先有话语权；同时保留"针对性"这一产品价值 |
| **指令与 JD 冲突时的行为** | **显式报冲突，交用户裁决** | 静默按 JD 改 / 静默按指令改 | 静默改任何一边都会让用户失去对简历的控制感与信任 |
| **意图解析产出** | 只产出范围与目标枚举 | 直接用指令文本驱动改写 | 保持"文本一律经 L5 校验"的单点；避免指令成为绕过事实门禁的通道 |

---

## 15. 风险与未决问题

| # | 风险 / 未决 | 影响 | 建议 |
| --- | --- | --- | --- |
| 1 | **与上游非目标正面冲突**（§1.3 逐字引用） | 无法在不改契约的情况下落地 | 落地前置：修订 `AGENTS.md` 与 spec 非目标，补聚焦测试 |
| 2 | 默认本地模型改写质量 | 用户感知价值 | 先用 `qwen2.5:7b-instruct` 做质量基线；`3b` 仅做措辞规范化 |
| 3 | 语义块抽取对多栏/表格简历的鲁棒性 | 块切错 → 改写错位 | 已实测证实（见 `FEASIBILITY-READ-WRITE.md` §4-5）：表格版 DOCX 章节归属被打乱。处理方式改为 §5.1.1 置信度门禁 + §5.1.2 重生模式，不再"降级 + 人工核对" |
| 4 | 15 分钟 TTL 与长改写任务冲突 | 大简历 + 本地模型可能跑超 15 分钟 | **TTL 只约束 Gate，不约束 run 执行**；run 用 `started_at` 记时，不用令牌计时 |
| 5 | PDF 中文字体/版式漂移 | ATS 解析失败 | docx 为唯一真源，pdf 只从 docx 转换；**实测本机 `soffice` 缺失，pdf 路径需显式可用性探测** |
| 6 | ATS 真实解析兼容性无法离线验证 | 改完仍被 ATS 读错 | 提供"ATS 文本还原检查"：把渲染产物重新抽文本与预期逐字比对 |
| 7 | 定向改写导致版本发散 | 版本目录膨胀、投递混淆 | lineage 深度上限（建议 5）；超出提示回基础版本 |
| 8 | 上游 `local-evidence-match-v3` 与 DSH 注入的工具描述 `v4` 不一致 | 策略版本口径混乱 | 需上游澄清；本设计在 `lineage.strategyVersion` 中显式记录实际使用的版本 |
| 9 | 用户可能把 `needs_user_confirmation` 一律点"接受" | 事实门禁被绕过 | 该操作记入审计；A/B 度量把这类 Edit 排除在 `effectiveDelta` 之外 |
| 10 | 内容面服务与 DSH 插件版本漂移 | 工具调用失败 | 契约文件化（`docs/CONTRACTS.md`），插件启动时校验内容面契约版本 |
| 11 | **PDF 提取器缺 CJK 语言包 → 中文静默归零** | 实测：108 个不同汉字保留 **0 个**，且返回成功状态 | 不作为可用输入路径，除非运行时自检 `cjkRetentionRatio`；见 `FEASIBILITY-READ-WRITE.md` §2 |
| 12 | **表格版 DOCX → 章节归属静默错乱** | 实测：工作 bullet 落到「教育背景」下，技能行夹在工作 bullet 之间 | §5.1.1 置信度门禁 → 强制重生模式 |
| 13 | **`python-docx` 的 `doc.paragraphs` 丢表格 → 空文本** | 表格版简历在 `job` 侧解析为空字符串，匹配恒 0 分且无报错 | 本设计不复用该读取路径，自带表格感知抽取 |
| 14 | **跨 run 的目标子串 → 子串替换静默失配** | 实测：XML 里是 `"…从 1"`+`"200"`，整串 `1200` 匹配不到 | 原地模式必须实现跨 run 区间定位与 `rPr` 克隆；否则强制重生模式 |
| 15 | **意图解析质量决定整套设计的可用性** | 解析错了 → 计划做对了但方向不对，且已在 Gate T 被批准 | 低置信度必须澄清而非猜测；`parseConfidence` 与 `conflictsWithGap` 对用户可见；M1 切片须先用虚构指令集覆盖解析分支 |
| 16 | 指令优先级可能被滥用为"注水通道" | 用户要求把没有的经历写进去 | 已封：拦截点统一在 L5 事实门禁，指令层不设例外（§5.3 边界 3） |

---

## 16. 与上游的集成点（不改上游）

| 集成点 | 上游 | 本设计如何用 | 需要上游做什么 |
| --- | --- | --- | --- |
| 简历版本目录 | `boss-watch-agent` `resume_versions` | 完全对齐 `contentHash / resumeVersionId / localArtifactRef / supersedes` 规则；新版本可被上游 `boss_watch_resume_list` 识别 | 放宽"不生成定制简历"契约 |
| 简历正文读取 | `LocalResumeImportService.readText()` | 内容面复用同一提取逻辑（pdf→`pdftotext -layout`，docx→`textutil` 回退 `unzip`，上限 200k 字符） | 无（本设计自行实现等价读取） |
| JD 来源 | `boss-watch-agent` `application_artifacts(kind='job_description')` | 只读已捕获的完整 JD 与其 `contentHash`；**拒绝用列表摘要做诊断** | 无 |
| 匹配算法 | `job` `src/match/*` | 复用三路融合做缺口诊断与 A/B 度量 | 修 `rerank` 量纲 bug（本设计在调用侧修正） |
| 投递 | `boss-watch-agent` Gate A/B | 本设计的产出是一个新的 `ResumeVersion`，供上游既有的 Gate A → 表单填充链路使用 | 无 |

---

## 附录 A：术语表

| 术语 | 含义 |
| --- | --- |
| 内容面（Content Plane） | 本机进程，持有简历正文与改写文本，占 `0700/0600` 权限 |
| 控制面（Control Plane） | DSH Transcript、工具响应、SQLite 元数据；只出现 id/hash/标签/计数 |
| 语义块（Block） | 编辑的最小单位，无重叠，一条 bullet = 一个块，可逆映射回原文 |
| 事实单元（Fact Unit） | 改写文本中可被独立验证的最小断言：数字/时间/专有名词/技术词/职级词 |
| 锚定（Anchored） | 事实单元能在被引用源块或用户声明中找到 |
| JD 注入 | 把 JD 要求但简历没有的技术词写进简历，属硬拒绝 |
| Gate T / E / W | 改写计划 / 云端出网 / 版本落盘 三道审批闸门 |
| 有效增量（effectiveDelta） | 仅由全部锚定的 Edit 带来的匹配分提升 |
