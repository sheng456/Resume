# 简历读取与改写可行性实测

状态：实测报告，结论已回写进 `ARCHITECTURE.md`
日期：2026-10-02
动因：质疑 `ARCHITECTURE.md` 的核心假设——"L1 语义块抽取"默认简历文本能被准确读出。

---

## 0. 结论（先看这三句）

1. **"能不能准确读简历"与模型无关，取决于源文件格式和提取器。** 当前两条上游路径（`job` 的 `python-docx`、`boss-watch-agent` 的 `pdftotext`/`unzip+xmlToText`）在**最常见的中文简历形态上都会失败**，而且**全部静默失败**——返回成功状态、合理的字符数，内容却是错的或空的。
2. **"能不能准确改简历"的瓶颈不是模型改写质量，而是提取阶段就已经丢掉的节点映射信息**（语义块 ↔ `<w:p>`/`<w:r>`）以及格式归属。模型写出一句更好的话是容易的；把这句话放回正确的位置、且不破坏其余部分，是真正的工程量。
3. 因此架构应从"**原地改写**"改为"**事实抽取 + 模板重生**为主、高置信度原地改写为辅"。

---

## 1. 实验设置

| 项 | 内容 |
| --- | --- |
| Ground truth | 一份虚构、脱敏的中文简历：160 个汉字、108 个不同汉字，含 联系方式 / 专业技能 / 教育背景 / 工作经历 / 项目经历 |
| 输入形态 | ① 单栏 PDF ② 双栏侧边栏 PDF ③ 单栏段落流 DOCX ④ 表格版 DOCX（N 行 × 2 列，逐行配对）⑤ 表格版 DOCX（1 行 × 2 列，左右各一个整列单元格） |
| 上游提取路径 | PDF → `pdftotext -layout` / `pdftotext`（**boss-watch-agent 实际实现**）；DOCX → `unzip -p <f> word/document.xml` + 逐字复刻 `resume-version.ts` 的 `xmlToText`（**boss-watch-agent 实际的 DOCX 回退路径**） |
| 另一个上游 | `job/src/resume/loader.py` 用 `python-docx` 的 `doc.paragraphs`（**不能执行，按源码静态判定**） |
| 生成器 | PDF 由 headless Edge 打印真实 HTML（真实中文字体嵌入、真实 ToUnicode）；DOCX 由手工 OOXML 包生成（表结构与 Word 输出同构） |

**实测命令（PDF）：**

```bash
pdftotext -layout single-col.pdf out/single-col.layout.txt
pdftotext          single-col.pdf out/single-col.raw.txt
```

---

## 2. 发现 A · PDF 路径：中文归零，且不报错

| 来源 | 提取路径 | 提取字符数 | 保留汉字 | 汉字保留率 | U+FFFD |
| --- | --- | --- | --- | --- | --- |
| 单栏 PDF | `pdftotext` | 250 | **0** | **0.0%** | 3 |
| 单栏 PDF | `pdftotext -layout` | 289 | **0** | **0.0%** | 3 |
| 双栏 PDF | `pdftotext` | 258 | **0** | **0.0%** | 3 |
| 双栏 PDF | `pdftotext -layout` | 440 | **0** | **0.0%** | 3 |

提取结果全文（单栏 PDF）：

```text
 138-0000-0000  zhangming@example.com
 2019.09 � 2023.06
     2023.07 �
 P99  320ms  90ms  8000  500   CI/CD  25  8
   2024.03 � 2024.09
 Spring Boot + MySQL + Redis   Kafka  QPS  1200  4500
 JavaSpring BootMySQLRedisKafkaDockerKubernetes
```

**108 个不同汉字，一个都没剩下。** 只有数字、英文技术词和邮箱活了下来。

### 2.1 为什么这不是"PDF 没有文本层"

PDF 内部检查结果：

- `single-col.pdf`：`ToUnicode` 出现 2 次，`Identity-H` 出现 2 次，`BaseFont=[AAAAAA+MicrosoftYaHei-Bold, BAAAAA+MicrosoftYaHei]`
- 提取时出现的 3 个 `U+FFFD` 是 `–`（en dash），不是中文

**文字层是完整的、ToUnicode 映射也在。** 失败发生在提取器：本机 `pdftotext` 是 **Xpdf 4.00（Glyph & Cog）**，Xpdf 的 CJK 支持需要单独安装语言包（`xpdf-chinese-simplified` 等）。装的语言包缺失 → 中文被直接丢弃，**不报错、不警告**。

**这是环境相关缺陷，不是 PDF 的固有属性**——poppler 版 `pdftotext` 能正常提取中文。但它对本设计是致命的，因为：

1. 它**静默**。调用方拿到 `extractionStatus = "text_extracted"`、`characterCount = 289`，完全看不出内容已经残缺。
2. 它对**关键词匹配**的破坏是连锁的。看这一行：

   ```text
   JavaSpring BootMySQLRedisKafkaDockerKubernetes
   ```

   原文 `Java、Spring Boot、MySQL、...` 里的顿号是中文，被丢掉后技术词**全部粘连成一个 token**。技能段的匹配会整体失效。
3. `boss-watch-agent` 的主要部署目标是 macOS（数据目录是 `~/Library/Application Support/BossWatchAgent`），而 macOS 默认**根本没有 `pdftotext`**。那里的结果是 `resume_text_extraction_unavailable` —— 不是错，是完全没有。

---

## 3. 发现 B · `job` 的 DOCX 路径：整张表格直接消失

`job/src/resume/loader.py:23`：

```python
doc = Document(str(p))
return "\n".join(par.text for par in doc.paragraphs)
```

`python-docx` 的 `Document.paragraphs` **只返回 body 级段落，不返回任何表格单元格内的段落**。对表格版简历，上式返回**空字符串**。

后果链条（全静默）：

```text
load_resume_text(table_resume.docx) -> ""            # 不抛异常
  -> chunk_resume("") -> 0 个 chunk                  # 空块被过滤
  -> score_keyword(jd, []) -> (0.0, [], [], [])      # 无 requirements 或无 chunks 直接返回 0
  -> final_score = 0.0
```

而 `src/main.py:cmd_match` 取简历用的是 `sorted(texts)[0]`（**字典序第一个文件**）。只要目录里字典序最靠前的是表格版简历，整轮匹配就恒为 0 分，且没有任何错误信息。

`load_resume_dir` 的 `except Exception: continue` 也帮不上忙——这里根本没抛异常。

---

## 4. 发现 C · `boss-watch-agent` 的 DOCX 路径：文字保住了，归属打乱了

对比表（同一份 ground truth）：

| 来源 | 提取路径 | 提取字符数 | 保留汉字 | 汉字保留率 |
| --- | --- | --- | --- | --- |
| `plain.docx`（单栏段落流） | `unzip` + `xmlToText` | 434 | 156 | 100%（写入的内容全部保留） |
| `table-split.docx`（N 行 × 2 列） | `unzip` + `xmlToText` | 438 | **160** | **100%** |
| `table-onecol-pair.docx`（1 行 × 2 列） | `unzip` + `xmlToText` | 435 | **160** | **100%** |

**`table-split.docx` 汉字保留率 100%，但内容完全错乱：**

```text
 1  联系方式
 2  张明                        ← 侧栏标题和姓名拼在了一起
 3  电话：138-0000-0000
 4  求职意向：后端开发工程师
 5  邮箱：zhangming@example.com
 6  工作经历                    ← 「工作经历」变成了联系方式的一条
 7  城市：上海
 8  某某科技有限公司 ｜ 后端开发工程师 ｜ 2023.07 – 至今
 9  专业技能                    ← 「专业技能」插进了工作经历
10  · 负责订单履约模块开发，将核心查询接口 P99 从 320ms 降至 90ms
11  Java、Spring Boot、MySQL、Redis、Kafka、Docker、Kubernetes
12  · 主导订单表分库分表改造，单表数据量从 8000 万降至 500 万
13  教育背景                    ← 「教育背景」插进了工作经历
14  · 参与 CI/CD 流程建设，发布耗时从 25 分钟缩短至 8 分钟
15  2019.09 – 2023.06  某某大学  计算机科学与技术  本科
16  项目经历
```

**这条链对简历编辑器是致命的：**

| 行 | 问题 | 对改写的影响 |
| --- | --- | --- |
| 14 | 一条**工作经历 bullet** 落在「教育背景」标题之下 | 改写"教育背景段"时会把这条工作成果当成教育内容处理 |
| 11 | **技能行**夹在两条工作 bullet 中间 | 改写"工作经历块"时会把技能列表当成一句工作成果来重写 |
| 6 / 9 / 13 | 章节标题变成了前一段的普通条目 | 章节边界识别失效，块归属全部错位 |

原因不是 bug，是**规范决定的**：OOXML 表格按**行主序**存储。`xmlToText` 只把 `</w:p>` 转成换行、对 `<w:tr>`/`<w:tc>` 不做任何处理，于是"逐行配对"的表格必然产出交错文本。

---

## 5. 发现 D · 决定可读性的是 XML 结构，不是视觉版式

这是本次实验最有价值的一条。`table-split.docx` 与 `table-onecol-pair.docx` **渲染出来是完全一样的双栏侧边栏简历**，提取质量却天差地别：

| fixture | XML 结构 | 提取结果 |
| --- | --- | --- |
| `table-split.docx` | N 行 × 2 列（逐行配对） | **章节归属全毁**（见 §4） |
| `table-onecol-pair.docx` | 1 行 × 2 列（左右各一整列） | **章节内聚完好**，只是顺序变成"先左栏后右栏" |
| `plain.docx` | 无表格，段落流 | **完全正确** |

`table-onecol-pair.docx` 的提取结果：

```text
 1  联系方式
 2  电话：138-0000-0000
 3  邮箱：zhangming@example.com
 4  城市：上海
 5  专业技能
 6  Java、Spring Boot、MySQL、Redis、Kafka、Docker、Kubernetes
 7  教育背景
 8  2019.09 – 2023.06  某某大学  计算机科学与技术  本科
 9  张明                       ← 名字排到了第 9 行
10  求职意向：后端开发工程师
11  工作经历
12  某某科技有限公司 ｜ 后端开发工程师 ｜ 2023.07 – 至今
13  · 负责订单履约模块开发，...
```

**每一个章节内部都是内聚的**——这意味着**块级改写是安全的**。唯一失效的是"姓名/求职意向应该在最前"这个启发式。

**结论：无法从视觉版式推断可读性。必须看 XML 结构，或者干脆实测提取结果的置信度。**

---

## 6. 发现 E · 写回：难点不在模型，在节点映射与格式归属

写回实验（对 DOCX 的 `word/document.xml` 定位段落 → 替换 → 重新打包 → 再提取）：

### 6.1 语义块与 XML 节点是一对多

| 段落 | 提取文本 | run 数 | 文本是否跨 run |
| --- | --- | --- | --- |
| 1 | `· 负责订单履约模块开发，将核心查询接口 P99 从 320ms 降至 90ms` | 1 | 否 |
| 2 | `· 主导订单表分库分表改造，单表数据量从 8000 万降至 500 万` | 5 | **是** |
| 3 | `· 参与 CI/CD 流程建设，发布耗时从25分钟缩短至8分钟` | 1 | 否 |

上游 `readText → xmlToText` 产出的是**纯字符串**，字符串里**不含任何 run 边界信息**。要写回就必须重新定位 `<w:p>`/`<w:r>`——而这一步所需的信息在提取阶段就被丢掉了。

### 6.2 两种写回策略，各有硬代价

**策略 1 · 整段替换**（把段落所有 run 换成单 run）：

```text
改写前加粗标记数量: 2
改写后加粗标记数量: 0
```

文本正确写入，但 **run 级格式（加粗的量化数字）全部丢失**。格式化信息只存在于 run 上，合并 run 等于放弃格式。

**策略 2 · run 内原地替换**：只在目标子串落在单个 run 内时可行。

### 6.3 关键反例：目标子串跨越 run 边界

Word 在拼写/语言检查切换时会切分 run。构造如下段落：

```text
提取文本（正确）: · 引入 Kafka 异步化，峰值 QPS 从 1200 提升至 4500
XML 里的 run  : ["· 引入 Kafka 异步化，峰值 QPS 从 1", "200", " 提升至 4500"]
```

用整串 `1200` 做 run 内替换 → **命中：否**。

`1` 和 `200` 被切成两个 run，**XML 层根本不存在 `1200` 这个字符串**。任何"按提取文本做子串替换"的实现都会**静默失配**——不报错，只是改不动或改错位置。

正确实现必须：定位跨 run 字符区间 → 拆分/合并 run → 克隆 `rPr` → 处理 `xml:space`。

### 6.4 回环本身是通的

| 段 | 改写前 | 改写后 |
| --- | --- | --- |
| 1 | `· 负责订单履约模块开发，...P99 从 320ms 降至 90ms` | （逐字不变） |
| 2 | `· 主导订单表分库分表改造，...8000 万降至 500 万` | （逐字不变） |
| 3 | `· 参与 CI/CD 流程建设，发布耗时从25分钟缩短至8分钟` | `· 参与 CI/CD 流程建设，发布耗时从 15 分钟缩短至 8 分钟` |

文件大小 1193 → 1193 字节；内容哈希 `143ffd9b…` → `0caa1eaa…`；未改动的段落逐字不变。

**写回在机械层面跑通了。难点是"改哪一段/哪个字符区间"以及"格式归谁"，不是模型。**

---

## 7. 对架构的修正

基于以上实测，`ARCHITECTURE.md` 的三处必须改：

### 7.1 L1 增加"提取置信度门禁"（新增，硬门禁）

不能假设提取成功就是成功。L1 必须在产出 `ResumeDoc` 前算出自检分，并据此决定后续可用路径：

```text
extractionConfidence 自检项：
  - cjkRetentionRatio  : 源文件声明的语言含中文时，提取结果的中文占比是否合理
  - layoutIntegrity    : 章节标题后是否紧跟该章节条目（无外栏内容插入）
  - tokenIntegrity     : 是否存在技术词粘连（如 JavaSpring BootMySQL）
  - runBoundaryMap     : 是否保留了 block ↔ <w:p>/<w:r> 的映射
  - silentLossProbe    : 提取字符数 / 源文件文本层预估字符数
```

**任一项低于阈值 → 判定为低置信度，禁止走"原地改写"路径。** 错误码 `tailor_extraction_low_confidence`。

关键点：**这些自检必须在提取后立刻做，不能等到改写完才发现。**（本次实验里，`pdftotext` 路径的 0% 中文与 `table-split` 的章节错乱，在提取阶段就是完全可检测的。）

### 7.2 明确两种产出模式，默认不是"原地改写"

| 模式 | 前提 | 保留什么 | 代价 |
| --- | --- | --- | --- |
| **重生模式（Rebuild，默认）** | 任意可提取的源 | 事实（经锚点校验）、章节结构；输出由受控模板渲染 | 用户原版的个性化版式丢失 |
| **原地模式（Patch）** | 提取置信度高 **且** 有完整 `runBoundaryMap` | 原版式、原格式、原有非改写段落 | 只能改 `anchored` 的措辞；run 边界处必须切分/克隆 `rPr` |

**重生模式作为默认，是因为它把"格式正确性"从无界问题变成有界问题**：模板是我们控制的，ATS 安全性可验证，版式不会漂移。原地模式作为高置信度下的可选增强。

这同时消解了 §5 的发现 D——**低置信度的 `table-split` 类文件直接进重生模式，不再需要"猜"章节归属**（猜错会静默写坏）。

### 7.3 L8 渲染：从"继承样式"改为"模板 + 事实注入"

原设计写"从基础版本复制样式、只替换段落文本、不重建文档骨架"——写回实验证明这对 run 碎片化的真实文件不成立。改为：

```text
受控模板（单栏、纯文本、无文本框、无表格）
  + 事实账本（anchored facts）
  + 改写后的措辞
  -> 渲染新 DOCX
```

并提供 **ATS 文本还原检查**：把渲染产物重新抽文本，与预期逐字比对，不一致则拒绝输出。

### 7.4 风险表增补

| 风险 | 依据 |
| --- | --- |
| PDF 提取器缺 CJK 语言包 → 中文静默归零 | §2 实测 0.0% |
| 表格版 DOCX → 章节归属错乱 | §4 实测 |
| `python-docx` 的 `doc.paragraphs` 丢表格 → 空文本 | §3 静态判定 |
| 目标子串跨 run → 子串替换静默失配 | §6.3 实测 |

---

## 8. 实验局限（必须说明）

1. **PDF 的 0% 中文是本机 Xpdf 构建的缺陷，不是 PDF 的固有属性。** poppler 版 `pdftotext` 能正常提取。但"静默"这一点与构建无关，仍然成立。
2. **表格 DOCX 是合成 fixture，不是真实 Word 输出。** 但行主序是 OOXML 规范定义的，机制可靠；真实 Word 文件只会更碎片化（run 更多）。
3. **`job` 的 DOCX 路径无法实际执行**（本机无 Python），结论来自 `python-docx` 的公开语义静态判定。建议在真实环境补一次执行验证。
4. **样本量为 1 份简历、108 个不同汉字**，只用于证明"存在静默失败"，不构成统计结论。
5. 未验证：真实多栏 Word 模板、扫描件/图片型 PDF、`msyh` 以外的字体、多页简历。

---

## 9. 复现

全部实验产物在临时 scratch 目录（未写入任何项目）：

```text
$TEMP/dsh-scratch-resume-fidelity/
├─ gen.js            # 生成 5 个 fixture + ground-truth.json
├─ analyze.js        # 提取保真度分析 -> out/REPORT.md
├─ writeback.js      # 写回实验 -> out/WRITE-REPORT.md
├─ ground-truth.json
├─ single-col.html / sidebar.html / *.pdf / *.docx
└─ out/              # 提取结果与两份报告
```

复现步骤：

```bash
cd "$TEMP/dsh-scratch-resume-fidelity"
node gen.js .
# PDF 由 headless Edge 渲染：
#   msedge --headless=new --no-pdf-header-footer --print-to-pdf=<out>.pdf file://<in>.html
pdftotext -layout single-col.pdf out/single-col.layout.txt
unzip -p table-split.docx word/document.xml > out/table-split.doc.xml
node analyze.js .
node writeback.js .
```
