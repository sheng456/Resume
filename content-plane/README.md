# content-plane（内容面）

本地 Python 服务。持有简历正文、执行改写与校验。**当前实现 M1 + M2 的确定性部分。**

对应设计：[`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)

---

## 交付范围

| 层 | 内容 | 状态 |
| --- | --- | --- |
| L0 | 数据契约（`domain/contracts.py`） | ✅ |
| L2 | 缺口诊断（`diagnose/gap.py`，JD 要求 × 简历块，含同义短语覆盖） | ✅ M2 |
| L3 | 指令解析 + 缺口冲突检测（`plan/intent.py`、`plan/conflict.py`） | ✅ M1 |
| L3 | 统一计划生成（`plan/plan.py`：指令驱动优先，JD 兜底） | ✅ |
| L3 | JD 驱动计划生成（`plan/jd_plan.py`：对齐 + 黑名单 + 重排 + 职级上限） | ✅ M2 |
| L4 | 安全改写·确定性部分（`rewrite/safe.py`：术语对齐 + 重排） | ✅ M2 |
| L4 | 改写·模型 reword（`rewrite/reword.py` 门禁 + ollama/deepseek 适配器 + `models.py` 工厂） | ✅ M2 |
| L4 | 完整管线（`rewrite/pipeline.py`：对齐 → reword → 重排） | ✅ M2 |
| L5 | 事实锚点校验器（`verify/`） | ✅ M1 |
| L6 | 评审（`review/review.py`：提案 → 逐条接受/拒绝/声明事实） | ✅ M2 |
| L7 | 版本落盘（`store/` + `render/markdown.py` + `policy/gate_w.py`：内容寻址 + 血缘 + Gate W） | ✅ |
| L1 | 语义块抽取（`extract/blocks.py`）+ 提取置信度门禁（`extract/confidence.py`） | ✅ |
| L8-L9 | docx/pdf 渲染 / Gate T/E / 评审 UI（控制面） | ❌ M3+ |

**确定性部分与门禁先于模型。** 理由：如果事实门禁本身不可靠，就没法区分
"模型没编造"和"我们没检查"。先把能证伪的部分做扎实，再让模型进来——模型
（reword）现在已接入，但它的输出先过 L5 锚点校验、再过事实保留检查，任一
不过就回退原文。

---

## 运行

依赖：Python 3.11+（本机经 WSL 使用 3.12.3）。**无第三方依赖**，不需要
`pip install` 任何东西。

```bash
cd content-plane

# 全部测试
PYTHONPATH=src python3 -m unittest discover -s tests -t . -v

# 单个模块
PYTHONPATH=src python3 -m unittest tests.test_verify -v

# 人工演示（打印每个场景的判定）
PYTHONPATH=src python3 demo.py

# M2 演示：JD -> 缺口 -> 计划 -> 安全改写 端到端
PYTHONPATH=src python3 demo_jd.py

# M2 演示：真 Ollama reword（门禁放行/拦截）
PYTHONPATH=src python3 demo_reword.py

# 语法检查
python3 -m compileall -q src tests
```

测试用标准库 `unittest` 编写，因此**没有 pytest 也能跑**；装了 pytest 时
`pytest` 同样能直接发现并运行这些 `TestCase`（上游 `job` / `chogu-nlp`
用的是 pytest，两边兼容）。

**当前状态：169 例测试全部通过**（M1 44 + M2 125），经 WSL 的 Python 3.12.3 实际执行；模型 reword 已用真 Ollama 实测，完整管线、评审、L1 置信度门禁与字节→文本提取（loader）、L7 落盘、指令意图接入、P0 loopback 服务（serve）端到端跑通。

---

## 结构

```
content-plane/
├─ src/resume_tailor/
│  ├─ domain/contracts.py     L0 契约（枚举 + frozen dataclass）
│  ├─ extract/blocks.py       L1 语义块抽取（文本 -> 块）
│  ├─ extract/confidence.py   L1 提取置信度门禁（检测静默损坏）
│  ├─ extract/loader.py       P1 字节→文本（docx/zip + 表格按行，pdf 如实标 unavailable）
│  ├─ lexicon/tech.py         技术词词库：严格匹配 + 粘连检测
│  ├─ lexicon/synonyms.py     同义短语映射（术语对齐的证据来源，M2）
│  ├─ diagnose/gap.py         L2 缺口诊断（JD × 简历，含同义覆盖，M2）
│  ├─ verify/fact_units.py    事实单元抽取（指标/时间/技术词/专有名词/职级）
│  ├─ verify/verifier.py      L5 校验器：锚定判定 + JD 注入 + ATS 提示
│  ├─ plan/intent.py          L3 指令解析
│  ├─ plan/conflict.py        指令与 JD 缺口的冲突检测
│  ├─ plan/jd_plan.py         L3 JD 驱动计划生成（M2）
│  ├─ plan/plan.py            L3 统一计划：指令驱动优先，JD 兜底
│  ├─ rewrite/safe.py         L4 安全改写：术语对齐 + 重排（M2）
│  ├─ rewrite/reword.py       L4 模型 reword 门禁：提示词 + L5 + 事实保留（M2）
│  ├─ rewrite/ollama.py       Ollama 适配器（RewordModel，标准库 urllib）
│  ├─ rewrite/deepseek.py     DeepSeek 适配器（OpenAI 兼容，占位待真测）
│  ├─ rewrite/models.py       按 provider 名选择适配器（插件式接缝）
│  └─ rewrite/pipeline.py     L4 完整管线：对齐 → reword → 重排（M2）
│  ├─ review/review.py        L6 评审：提案 → 逐条接受/拒绝/声明事实（M2）
│  ├─ render/markdown.py      L7 渲染：最终简历 -> 稳定 markdown
│  ├─ store/identity.py       L7 身份：哈希 / 版本 id / 血缘 id
│  ├─ store/version_store.py  L7 存储：内容寻址工件 + SQLite 元数据 + 血缘
│  ├─ store/version.py        L7 编排：渲染 -> 哈希 -> 版本 -> 血缘
│  └─ policy/gate_w.py        Gate W：版本落盘审批闸门（两段式令牌）
│  ├─ serve.py                P0 本地服务：loopback HTTP + 服务/评审令牌，正文不出进程
│  └─ __main__.py             `python -m resume_tailor serve` 入口
├─ tests/
│  ├─ test_verify.py                 校验器
│  ├─ test_intent.py                 解析器
│  ├─ test_extract.py                 L1 抽取 + 置信度（含真实损坏产物）
│  ├─ test_loader.py                  P1 字节→文本提取
│  ├─ test_serve.py                   P0 服务 + 隐私不变量
│  ├─ test_gap.py                    缺口诊断（M2）
│  ├─ test_jd_plan.py                JD 计划（M2）
│  ├─ test_safe_rewrite.py           安全改写（M2）
│  ├─ test_reword.py                 reword 门禁（M2）
│  ├─ test_models.py                 模型工厂 + DeepSeek 适配器（M2）
│  ├─ test_pipeline.py               完整管线（M2）
│  ├─ test_review.py                 评审（M2）
│  ├─ test_version.py                L7 落盘 / 血缘 / Gate W
│  ├─ test_instruction_plan.py       指令意图接入
│  └─ test_regression_fixtures.py    与实测损坏产物对接
├─ demo.py
├─ demo_extract.py                      L1 抽取 + 置信度演示
├─ demo_jd.py                          JD -> 改写 端到端演示（M2）
├─ demo_reword.py                      真模型 reword 演示（M2）
├─ demo_pipeline.py                    完整管线演示（M2）
├─ demo_review.py                      评审演示（M2）
├─ demo_commit.py                      L7 完整闭环演示（抽取→落盘→Gate W）
└─ demo_instruction.py                 指令意图演示（指令驱动/JD 兜底/歧义/冲突）
```

---

## 关键设计决策（值得评审）

### 1. 判定四条 + 一条硬门禁

| 状态 | 含义 | 处理 |
| --- | --- | --- |
| `anchored` | 能在源块或用户声明中找到 | 通过 |
| `abstracted` | 降级/等价变换（负责 → 参与） | 通过 |
| `upgraded` | 能力升级（参与 → 主导） | 需用户逐条确认 |
| `unsupported` | 任何白名单都找不到 | 需用户声明或改写 |

**JD 注入是独立硬门禁**：JD 要求、但简历原文与用户声明都没有的技术词
出现在改写里即 `reject`，用户**无法通过确认绕过**。意义是——不允许因为
岗位要求 Kubernetes 就把 Kubernetes 写进简历。

### 2. 方向性判定用"阶梯取最高档"

`负责` 是 `负责人` 的子串，`参与` 与 `负责` 又在同一条阶梯上。
实现取"该阶梯上出现过的最高档"，因此 `负责人` 得 2 分而不是被误判成 1 分。

**保守取向**：源文本没有职级词（档位 -1）而改写加了 `负责`，会被判为
`upgraded`。这在实践中偏严——但简历场景下"宁可要求确认，不可静默升级"。
这是一个可调阈值，不是定论。

### 3. 指令不能扩大可改写范围

`plan.intent.is_rewritable` 是独立于事实门禁的第三条边界：只有
`summary` / `work` / `project` 的 `bullet` 可改。

这条边界是**被测试逼出来的**：用户说"突出 Kafka 那条"（单数），最初的
作用域解析同时抓了项目 bullet 和技能行——而改写技能列表正是 JD 注入最
容易得手的地方。

### 4. 意图不携带任何文本

`TailorIntent` 上没有任何装正文的字段，且有测试机械地锁住这一点。
这是"指令不能成为绕过事实门禁的通道"的结构性保证：
指令只产出范围与目标，文本一律由 L4 生成并受 L5 校验。

### 5. 错误码优先级：歧义先于冲突

低置信度与缺口冲突可能同时出现。调用方应**先报** `tailor_instruction_ambiguous`
——指令没解析清楚、没有可执行范围时，报冲突为时尚早。但冲突信息仍保留在
返回值里一并展示，避免来回试探。

### 6. 词库刻意丢弃若干两字母别名

上游 `job/skills_map.json` 有 `fe`/`be`/`pm`/`cv`/`ml`/`dl`/`es` 等两字母英文
别名。本实现**全部丢弃**：`be` 会命中英文 "will be"，`cv` 在简历语境里
既可能是"计算机视觉"也可能是 curriculum vitae。事实校验的假阳性会直接
变成错误的"事实单元"，比漏检更糟。中文写法全部保留。

---

## JD 驱动安全改写（M2 核心机制）

回答"如何根据 JD 更新简历，又不臆造、不夸大"——一句话：**JD 不能直接碰
改写，它必须先被中介成"带证据的编辑指令"。**

```
捕获的 JD
  -> L2 缺口诊断       确定性：哪些要求已被覆盖/部分覆盖/缺失，证据块是谁
  -> L3 计划生成       确定性：术语对齐 + 黑名单 + 重排 + 职级上限
  -> L4 安全改写       确定性：只做「同义替换」与「重排」，无模型
  -> L5 兜底校验       改写结果逐条过事实锚点校验，不过即回退
```

**JD 只能通过三条通道进入简历，其余全封死：**

| 通道 | 依据 | 举例 |
| --- | --- | --- |
| 它本来就在简历里 | 原文事实 | 简历已有 "Java"，JD 也要 Java |
| 它被人工认定为等价 | `synonyms.json` 的证据 | 简历 "服务拆分" == JD "微服务" |
| 用户显式声明为事实 | `DeclaredFact` + 证据 | "我确实用过 Kubernetes" |

**M2 落地的是前两条的确定性部分**：`synonyms.json` 里的同义短语做术语对齐，
按 JD 技术词覆盖度做 bullet 重排。这两个操作是机械变换，**数学上不可能
引入新事实**——对齐只替换有证据的词，重排是纯置换（token 一个不多不少）。

第三条（用户声明）由 M1 的 L5 事实门禁兜住；模型 reword 也已落地，但它
同样只能复用这三条通道——reword 的输出先过 L5 锚点校验、再过事实保留检查，
任一不过就回退原文。

**`forbidden_terms` 黑名单**：JD 有、简历没有的技术词（如 JD 要 Kubernetes、
简历没有）会被显式列入计划，任何路径（含模型）都不得引入。测试
`test_forbidden_jd_tech_never_appears` 锁住这条不变量。

---

## 模型 reword 的门禁（M2 后半）

`rewrite/reword.py` 不是"让模型改得好"，而是**让模型改不坏**。三道防线：

1. **提示词不含 JD**：模型只看到单条源句 + 中性改写指令，看不到 JD 全文、
   黑名单、职级上限的数值——它既没机会抄 JD 技能，也没机会知道"该往哪升"。
2. **L5 锚点校验**（防新增臆造）：凭空造数字、能力升级（参与→主导）、JD 注入
   一律拒绝。
3. **事实保留检查**（防删减）：源句里的量化指标与技术词必须原样保留，
   杜绝"把 320ms 降至 90ms 删成'优化了性能'"。

**真模型实测发现（重要）**：qwen2.5-coder:7b 对简历 bullet 有**系统性拔高
倾向**——即使提示词写明了"不得把能力往上调"，它仍把"负责"改成"主导"、
"参与"改成"主导"。门禁每次都精准拦截（`upgraded (rank 2 > 1)`）并回退原文。
这证明了那条设计原则：**证据锚定是硬门禁，不是提示词约束**——提示词只是
减震带，门禁才是安全网。

据此把提示词从"更有冲击力"（会引诱拔高）改为"更清晰、更精炼"并显式锁死
职级动词，实测后模型不再拔高、改写全部安全放行。

**局限（有意为之）**：术语对齐只覆盖 `synonyms.json` 里人工认定的等价短语；
模型 reword 只做单句局部润色，不做"根据 JD 跨块补写"。泛化改写（embedding
或更强的模型）仍需受 L5 约束。

---

## 与实测的对接

`tests/test_regression_fixtures.py` 直接读取 [`../fixtures/`](../fixtures/) 里
**真实工具链的产出**（headless Edge 打印的中文 PDF → 本机 Xpdf
`pdftotext -layout`），断言三件事：

1. 实测那条粘连技能行 `JavaSpring BootMySQLRedisKafkaDockerKubernetes` 能被检出；
2. 在真实提取产物全文上，粘连检测器也会触发（不是只在构造字符串上触发）；
3. 该路径的汉字保留率仍为 0（若失败，说明提取器换了，§5.1.1 的阈值需重标定）。

语料缺失时这 3 例自动跳过，不会让单测失败。

---

## 已知局限（M1 不做，不是遗漏）

| 局限 | 影响 | 计划 |
| --- | --- | --- |
| `8000 万` 与 `80000000` 不视为等价 | 换算式改写会被判无源 | 需要数值归一化，M2 之前补 |
| 裸数字的"年份 vs 指标"用 1900–2100 启发式 | 4 位指标可能被误判为年份 | 引入上下文判定 |
| 无 NER，专有名词只认机构后缀模式 | 产品名/项目名不参与校验 | 可接受；技术词词库覆盖了主要风险面 |
| 指令解析是纯规则，无同义扩展 | "项目那块儿" 之类说法识别不到 | M2 引入 LLM 辅助解析，但低置信度仍须澄清 |
| 不做语义等价（"重构" vs "改造"） | 换词改写可能触发 upgraded | 属 L4 提示词约束范围 |
| ATS 检查只有粘连与替换符两条 | 版式类问题不覆盖 | L8 渲染阶段补齐 |

---

## 下一步（M3 起）

1. 数值归一化 ✅（`8000 万` == `80000000` == `0.8 亿`）；
2. 完整管线 ✅（`rewrite/pipeline.py`：对齐 → reword → 重排）；
3. L6 评审 ✅（`review/review.py`：提案 → 逐条接受/拒绝/声明事实）；
4. L1 语义块抽取 + 提取置信度门禁 ✅（`extract/`）；
5. L7 版本落盘 + 血缘 + Gate W ✅（`store/` + `render/` + `policy/gate_w.py`）；
6. 指令意图接入 ✅（`plan/plan.py`：指令驱动优先，JD 兜底；方向串进提示词）；
7. L8 docx/pdf 渲染；Gate T/E；评审 UI（本地页）与控制面（DSH 插件）。

**L4 的模型 reword 必须建立在 L5 之上**——顺序不能反（已完成，见上）。

---

## L6 评审（人在环闸门）

改写管线产出的是**草稿**；评审把每条改动摊开，由人决定。数据流：

```
propose_blocks（模型输出不 fail-closed，被门禁挡住的候选也保留）
  -> assemble_review（每条提案带 verdict + 事实保留，标 accept / pending）
  -> 人逐条决定：接受 / 拒绝 / 声明事实（reverify 重新锚定）
  -> apply_decisions（accept -> 候选，reject/pending -> 原文）
```

关键语义：

- 被门禁挡住的候选（`unsupported`/`upgraded`/JD 注入/事实丢失）**不会静默丢弃**，
  而是摊给用户：无源/升级的单元可"声明为事实"（附证据）后重新锚定；
- 事实丢失（如"8 分钟"被改成"3 分钟"）与 JD 注入无法用声明修复，只能拒绝；
- 只有无待处理项的版本才能进入 L7 落盘（`pending_blocked` 提供闸门）。

本模块只产出数据与决策逻辑；浏览器 UI（本地页、文本不进 Transcript）属控制面。

---

## 插件化方向（预留，不写死）

最终目标是**把整个项目做成 DSH 插件**。为此已预留的接缝：

- 模型层：上层只依赖 `RewordModel` 协议 + `get_reword_model(provider)`，
  不依赖具体 provider；新增模型（其他云端/本地推理）只需写一个适配器并在
  `models.py` 登记一行。配置（地址/模型名/密钥）全部走环境变量，不在代码写死。
- 内容面 / 控制面分离：Python 内容面（纯逻辑，本目录）与未来的 TS 控制面
  （DSH 插件）经 loopback 契约对接，见 `docs/ARCHITECTURE.md` §3.3。

DeepSeek 适配器当前为**占位**：已用本地 mock 验证请求格式与解析，真实 API
待提供 `DEEPSEEK_API_KEY` 后接入测试。

---

## 验证记录

- 全量测试：**169 例通过**（M1 44 + M2 125），`python3 -m unittest discover -s tests -t .`
- 语法检查：`python3 -m compileall -q src tests` 通过
- 端到端演示：`demo_extract.py`（L1）、`demo_jd.py`（确定性）、`demo_reword.py`
  （真模型 reword）、`demo_pipeline.py`（完整管线）、`demo_review.py`（评审）、
  `demo_commit.py`（L7 落盘闭环）、`demo_instruction.py`（指令意图）输出符合预期
- 真模型实测：qwen2.5-coder:7b 有"拔高职级"倾向，门禁逐条拦截并回退原文（见上"模型 reword 的门禁"）
- 独立静态审查：子代理对未执行代码做了精读审查，结论"无致命缺陷"，3 条可选改进已全部落地

无第三方依赖（适配器只用标准库 `urllib`）；本机经 WSL Ubuntu-24.04 的
Python 3.12.3 运行，Ollama 经宿主机 `172.27.176.1:11434`。
