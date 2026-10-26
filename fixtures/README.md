# 简历读取/改写保真度回归语料

用途：为 `docs/FEASIBILITY-READ-WRITE.md` 的实测结论提供**可重复执行的断言基线**，并作为 M0/M1 的回归测试输入。

这套语料保护的是一条设计红线：**提取失败必须是可见的，不能静默。**

---

## 语料清单

| 文件 | 形态 | 它锁住的回归 |
| --- | --- | --- |
| `single-col.html` / `single-col.pdf` | 单栏 PDF，真实中文字体嵌入 | PDF 路径的 `cjkRetentionRatio`：**必须能被检出为 0%** |
| `sidebar.html` / `sidebar.pdf` | 双栏侧边栏 PDF | 同上；且锁住 `layoutIntegrity` |
| `plain.docx` | 单栏段落流 DOCX | **正向基线**：汉字保留率必须 = 100% |
| `table-split.docx` | 表格版 DOCX，N 行 × 2 列（逐行配对） | `layoutIntegrity`：章节归属**必须被判为错乱** |
| `table-onecol-pair.docx` | 表格版 DOCX，1 行 × 2 列（左右各一整列） | 视觉版式相同但结构不同 → **章节内聚必须判为通过**（仅顺序偏移） |
| `runs.docx` / `runs-rewritten.docx` | 段落文本跨多个 run 的 DOCX | `runBoundaryMap`：**跨 run 子串替换必须失配** |
| `ground-truth.json` | 上述内容的 ground truth | 全部比对的基准 |

**关键对照**：`table-split.docx` 与 `table-onecol-pair.docx` 渲染结果视觉上完全一致，提取质量却一个是"章节全毁"、一个是"章节内聚"。**因此可读性不能从版式推断，只能靠自检。**

---

## 三个必须保持为真的断言

1. `pdftotext`（本机 Xpdf 构建）对 `single-col.pdf` 的汉字保留率 = **0.0%**
2. `table-split.docx` 经 `unzip + xmlToText` 后，汉字保留率 = **100%**，但**至少有一条工作经历 bullet 落在「教育背景」标题之后**
3. `runs.docx` 中目标子串（XML 里被切成 `"…从 1"` + `"200"`）用整串 `1200` 做 run 内替换 → **命中 0 次**

第 1 条是环境相关的（换 poppler 会变）。若某天它不再成立，说明**提取器换了**，`ARCHITECTURE.md` §5.1.1 的阈值需要重新标定——这本身就是需要被通知的变化。

---

## 复现

```bash
cd fixtures

# 1) 重新生成 fixture（会覆盖 corpus 文件；PDF 由 headless Edge 单独渲染）
node gen.js .

# PDF 渲染（需 Edge）：
#   msedge --headless=new --no-pdf-header-footer --user-data-dir=./edge-profile \
#          --print-to-pdf="$PWD/single-col.pdf" "file:///$PWD/single-col.html"

# 2) 用上游提取路径抽取
for f in single-col sidebar; do
  pdftotext -layout "$f.pdf" "out/$f.layout.txt"
  pdftotext          "$f.pdf" "out/$f.raw.txt"
done
for d in plain table-split table-onecol-pair; do
  unzip -p "$d.docx" word/document.xml > "out/$d.doc.xml"
done
pdftotext --help >/dev/null   # 需要 Xpdf 4.x 或 poppler

# 3) 分析 -> out/REPORT.md
node analyze.js .

# 4) 写回实验 -> out/WRITE-REPORT.md
node writeback.js .
```

`out/REPORT.md` 与 `out/WRITE-REPORT.md` 是**当前基线**，重新运行后应与它们一致（PDF 的时间戳与字体子集编号可能使字节不同，比对时看结论表而非字节）。

---

## 环境依赖

| 依赖 | 本机状态 | 缺失时的影响 |
| --- | --- | --- |
| Node.js | ✅ v24.19.0 | 无法运行 `gen.js` / `analyze.js` / `writeback.js` |
| `pdftotext` | ✅ Xpdf 4.00（mingw64） | PDF 断言跳过 |
| `unzip` | ✅ | DOCX 断言跳过 |
| Microsoft Edge | ✅（`Program Files (x86)`） | 无法重新生成 PDF fixture（但已有的 `.pdf` 可直接用） |
| Python | ❌ 本机无有效解释器 | 无法执行 `job` 侧的 `python-docx` 对照验证（见下） |

---

## 已知缺口

- **`job/src/resume/loader.py` 的表格丢失问题未做执行验证。** 本机无 Python，结论来自 `python-docx` 的公开语义（`Document.paragraphs` 不返回表格内段落）的静态判定。环境具备后应补一条：对 `table-split.docx` 调 `load_resume_text`，断言返回空字符串。
- 语料为**合成 fixture**，非真实 Word 输出。行主序是 OOXML 规范定义的，机制可靠；但真实文件会更碎片化（run 更多），建议补一份真实脱敏样本。
- 未覆盖：扫描件/图片型 PDF、多页简历、`msyh` 以外字体、真实多栏 Word 模板。
