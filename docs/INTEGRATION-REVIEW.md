# 全流程插件化复审

> 范围：BOSS JD 抓取 → 简历分析 → JD 匹配度评判 → 简历修改，这四步能否形成插件；
> 不能则组合成 agent（可脱离 DSH、也可依赖 DSH）。
> 状态：架构复审，**不改代码**。日期 2026-10-24。

---

## 0. 一句话结论

**能形成插件，但不是"一个插件装下全部"——正确形态是「一个控制面插件（薄）+ 一个内容面服务（Python）+ 一个编排 agent（preset + Skill）」。**

BOSS JD 抓取**已经是**一个成熟插件的既有能力（`boss-watch-agent`），不该重做；
简历分析 / 匹配 / 修改已在 `resume/content-plane`（Python）实现并测试，但它是**内容面**，
按隐私契约不能塞进 DSH 插件进程。所以全流程 = 复用已有插件抓 JD + 用薄插件切片包
Python 内容面 + 用一个 agent 编排四步。

---

## 1. 现状盘点：四步各自在哪、成熟度

| 步骤 | 现状 | 位置 | 成熟度 |
| --- | --- | --- | --- |
| ① 抓 BOSS JD | 浏览器控制器（BossHunter/CDP/4318）+ 页面适配器 + 人工登录；`discover_jobs` / `capture_discovered_job` / `capture_current_job` / `boss_search_preview/run` | `boss-watch-agent`（TS 插件） | ✅ 已实现，观测模式 |
| ② 分析简历 | 语义块抽取 `extract/` + 提取置信度门禁 | `resume/content-plane`（Python） | ✅ 129 测试 |
| ③ 评判 JD 匹配 | **三处冗余**：`boss_watch_resume_match`（v3：能力标签/硬约束/打分）、`job` three-way（关键词/向量/重排）、`gap.py`（词表+同义覆盖） | 三处 | ⚠️ 需定一个规范 |
| ④ 修改简历 | 计划 `plan/` + 改写 `rewrite/`（对齐/reword/重排）+ 校验 `verify/` + 评审 `review/` + 落盘 `store/` + Gate W | `resume/content-plane` | ✅ 129 测试 |

**结论：②③④ 的核心逻辑已经做完，① 已经存在。缺的不是"能力"，是"把它们接起来的那层壳"。**

---

## 2. 关键边界：为什么"一个插件装不下"

### 2.1 内容面 / 控制面分离（隐私契约，不可破坏）

- `boss-watch-agent` 的产品边界写死：简历原文**不进 DSH Transcript、不上传外部模型**。
- 我建的 `resume/content-plane` 正是这个"内容面"：正文、改写候选、事实单元只在本机
  进程内；跨边界只传 id/hash/标签/计数/摘要。
- 若把内容面塞进 DSH 插件（TS）进程，等于把简历正文带进宿主，破坏契约。

### 2.2 浏览器边界（登录/验证码永远人工）

- 抓 BOSS JD 依赖浏览器 + 人工登录/扫码/验证。这是**控制面**的事，只能留在插件/运行时侧。

### 2.3 模型边界

- reword 默认本地 Ollama（正文不出本机）；云端（DeepSeek）需 Gate E（尚未实现，非当前 blocker）。

### 2.4 语言/运行时边界

- 内容面是 Python（复用 `job` 的解析/匹配思路 + 标准库零依赖 + 中文字体/文件处理更顺）。
- 控制面是 TS（DSH 插件形态 + boss-watch 已有 Gate/令牌/tool schema 约定）。
- 二者经 **loopback HTTP + 服务令牌** 对接（对齐 boss-watch 4318 控制器模式）。

---

## 3. 逐条评估：每步"能否进插件"

| 步骤 | 能否进插件进程 | 理由 |
| --- | --- | --- |
| ① 抓 JD | ✅ 只能进（控制面） | 浏览器 + 人工登录；boss-watch 已做 |
| ② 分析简历 | ❌ 进内容面 | 正文/块/置信度，隐私敏感；Python |
| ③ JD 匹配 | ⚠️ 一半一半 | 脱敏的"匹配快照"进控制面；正文级匹配在内容面 |
| ④ 修改简历 | ❌ 进内容面 | 改写候选/事实校验/正文落盘，Python + 模型 + 文件 |

**结论：① 在插件、②③④ 在内容服务，中间加一个薄插件切片做"翻译 + 审批"。**

---

## 4. 推荐架构（三层）

```text
┌─ 控制面（DSH 插件，TS）───────────────────────────────────┐
│  boss-watch-agent（既有）        resume-tailor 切片（新增·薄） │
│  · 抓 JD / 简历版本 / Gate A/B   · 触发匹配/改写/评审/落盘      │
│  · 候选面板 / 投递预览            · Gate W 审批                │
│  · 只处理 id/hash/标签/摘要      · 只经 loopback 调内容面       │
└───────────────┬──────────────────────────────┬───────────────┘
                │ 复用（同进程，Host tools）      │ loopback + 服务令牌
                │                               ▼
┌───────────────┴───────────────┐  ┌──────────────────────────┐
│  浏览器运行时（BossHunter/CDP） │  │ 内容面（Python，本机服务）  │
│  · 真实页面 + 人工登录          │  │  resume/content-plane     │
└───────────────────────────────┘  │  · extract/gap/plan        │
                                   │  · rewrite/verify/review   │
                                   │  · store/lineage/Gate W    │
                                   │  · 正文不出进程；本地 Ollama │
                                   └──────────────────────────┘

┌─ 编排（agent preset + Skill）────────────────────────────┐
│  Skill 告诉模型何时调哪个只读/需确认工具，何时停在人工确认；   │
│  工具负责 schema/数据/副作用边界；preset 组合模型+工具+skill。 │
└───────────────────────────────────────────────────────────┘
```

### 4.1 复用 boss-watch 已有能力（不重做）

- 抓 JD：`discover_jobs` / `capture_discovered_job` / `capture_current_job` / `boss_search_preview/run`
- 简历版本目录：`resume_import_preview/apply/list/get`（内容寻址，正文不落 Transcript）
- 匹配快照：`resume_match`（v3）
- 审批：`gate_a_confirm`（Gate A）、投递 `apply_preview`/表单

### 4.2 新增「resume-tailor」薄切片（≈ 10 个 Host tool）

只做"翻译 + 审批"，不碰正文：

| 工具 | 作用 | 边界 |
| --- | --- | --- |
| `resume_tailor_gap_preview` | 触发内容面缺口诊断 | 只回标签/计数/哈希 |
| `resume_tailor_plan_preview/confirm` | 计划 + Gate T | 计划含 instruction_hash |
| `resume_tailor_run` | 触发改写 | 只回 diff 摘要 + verdict 计数 |
| `resume_tailor_review_open` | 打开本地评审页 | 文本只在该页，不进 Transcript |
| `resume_tailor_commit_preview/apply` | 落盘 + Gate W | 回新版本哈希 + lineage |
| `resume_tailor_audit_list` | 审计账本 | 哈希与动作 |

### 4.3 编排：agent preset + Skill（组合，不是新写引擎）

DSH 已有 `agent-preset-registry`（组合模型+工具+skill）与 `agent-default-model`。
"组合成一个 agent" = 注册一个 preset，把 boss-watch 工具 + resume-tailor 工具 +
一个 `resume-tailor-job-search` Skill 绑到一起；Skill 只描述**输入契约/证据规则/安全边界**，
不执行副作用（与 boss-watch 的 `skill.ts`/`SKILL.md` 同款）。

---

## 5. 如果"暂时做不到插件" → 组合成 agent 的最小做法

即使不写新插件，也能立刻组合出一个能跑的 agent：

1. **内容面先独立成 CLI / 本地服务**：`python -m resume_tailor serve`（FastAPI 或 stdlib http），
   暴露 gap/plan/run/review/commit 五个只读/需确认端点，服务令牌鉴权。
2. **agent 里用通用 Bash/HTTP 工具调它**（临时），或用脚本化方式把四步串成一个 CLI：
   `capture(JD 文本) → analyze(简历文本) → match → rewrite → review → commit`。
3. **复用 boss-watch 的 JD 抓取与简历版本**，agent 只负责把"抓到的 JD 文本 + 简历版本 id"
   喂给内容面。

这样**不依赖 DSH 插件机制**也能闭环；依赖 DSH 时再把 Bash 调用换成正式 Host tools。

### 5.1 脱离 DSH 的边界（诚实）

| 部分 | 能否脱离 DSH | 说明 |
| --- | --- | --- |
| 内容面（②③④） | ✅ 完全可 | 纯 Python，零依赖，CLI/service 即可 |
| 抓 JD（①） | ⚠️ 部分 | 依赖浏览器运行时；可走 boss-watch 独立运行时，或 `job` 的 scraper（真实实现尚未落地） |
| 评审 UI（本地页） | ✅ 可 | 内容面直接起本地 HTTP 评审页 |
| 云端模型 | ⚠️ | 需 API key + Gate E（未实现） |

---

## 6. 已知缺口（如实清单，非装饰）

1. **简历文件 → 文本 的可靠实现缺失**：内容面 `extract_blocks` 吃的是**文本**，不是 PDF/DOCX
   字节；字节→文本在 boss-watch（pdftotext/textutil/unzip）与 job（pypdf/python-docx），
   而实测证明这些路径会**静默损坏**（0% 中文、表格错乱）。内容面的置信度门禁能**检出**损坏，
   但还没有一个"经门禁保护、可靠地字节→文本"的实现接上。
2. **匹配三分冗余**：boss-watch v3、job three-way、内容面 gap.py 三个匹配器并存，
   分数口径不一致。全流程必须定**一个**规范匹配器。
3. **docx/pdf 渲染（L8）未做**：落盘是 markdown，真实投递需 docx。
4. **Gate E（云端出网授权）未做**：当前 reword 默认本地 Ollama，尚不阻塞；接 DeepSeek 需补。
5. **Gate T（计划审批）未做**：只有 Gate W（落盘）。计划/改写这两步的"人审批"目前靠评审层兜。
6. **指令意图已接入，但评审 UI 与控制面工具还没接**：内容是库，还没有对外服务壳。

---

## 7. 落地路径（建议顺序）

| 阶段 | 内容 | 产出 |
| --- | --- | --- |
| P0 | 内容面包成本地服务（loopback + 服务令牌 + 五个端点） | `resume_tailor serve` |
| P1 | 补「字节→文本」可靠提取 + 接上置信度门禁 | 补上缺口 1 |
| P2 | 收敛匹配器（定规范，复用内容面 gap 或 boss-watch v3） | 补上缺口 2 |
| P3 | 写薄插件切片（Host tools → loopback）+ Skill | 补上插件壳 |
| P4 | 注册 agent preset，组合 boss-watch + resume-tailor + Skill | 组合成 agent |
| P5 | docx 渲染 + Gate T/E | 补上缺口 3/4/5 |

**判断：P0+P3+P4 即可让"四步闭环"作为插件+agent 跑通；P1/P2/P5 是把质量补到可投递。**

---

## 8. 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 隐私契约被"薄切片"破坏 | 正文漏进 Transcript | 切片工具只回 id/hash/摘要；测试锁死边界 |
| 内容服务与插件版本漂移 | 工具调用失败 | loopback 契约文件化 + 版本握手 |
| 匹配器不一致 | 打分打架、用户困惑 | P2 先收敛 |
| BOSS 页面结构变化 | 抓取失败 | 复用 boss-watch 的 `page_adapter_mismatch` 交还人工 |
| 云端模型出网未授权 | 正文泄露 | 默认本地 Ollama；云端必须 Gate E |
