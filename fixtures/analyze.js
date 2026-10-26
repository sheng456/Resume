// 保真度分析：PDF/DOCX 提取结果 vs ground truth
const fs = require('node:fs')
const path = require('node:path')
const OUT = process.argv[2]
const R = (f) => {
  try { return fs.readFileSync(path.join(OUT, f), 'utf8') } catch { return null }
}

const gt = JSON.parse(R('ground-truth.json'))
const cjk = (s) => (s.match(/[\u4e00-\u9fff]/g) || []).length
const cjkSet = (s) => new Set(s.match(/[\u4e00-\u9fff]/g) || [])

// ground truth 的全部中文
const allTruth = [...gt.SIDEBAR_LEFT, ...gt.MAIN_RIGHT].join('\n')
const truthCJK = cjkSet(allTruth)
const truthCJKCount = cjk(allTruth)

// 复刻 boss-watch-agent resume-version.ts 的 xmlToText
function xmlToText(xml) {
  return xml
    .replace(/<w:tab\s*\/?>/gu, '\t')
    .replace(/<w:br\s*\/?>/gu, '\n')
    .replace(/<\/w:p>/gu, '\n')
    .replace(/<[^>]+>/gu, '')
    .replace(/&amp;/gu, '&')
    .replace(/&lt;/gu, '<')
    .replace(/&gt;/gu, '>')
    .replace(/&quot;/gu, '"')
    .replace(/&apos;/gu, "'")
}
// 复刻上游 normalizeExtractedText
function normalizeExtractedText(v) {
  return v
    .replace(/\u0000/gu, '')
    .replace(/\r\n?/gu, '\n')
    .replace(/[ \t]+\n/gu, '\n')
    .replace(/\n{3,}/gu, '\n\n')
    .trim()
}

const report = []
const line = (s) => report.push(s)

line('# 简历读取保真度实测\n')
line(`ground truth：中文 ${truthCJKCount} 字（去重 ${truthCJK.size} 个不同汉字）\n`)

// ---------- A. PDF 提取器内部结构 ----------
line('## A. 生成的 PDF 内部是否有中文文本层\n')
for (const name of ['single-col', 'sidebar']) {
  const raw = fs.readFileSync(path.join(OUT, `${name}.pdf`))
  const latin = raw.toString('latin1')
  const hasToUnicode = (latin.match(/\/ToUnicode/g) || []).length
  const hasIdentityH = (latin.match(/Identity-H/g) || []).length
  const fontMatches = [...latin.matchAll(/\/BaseFont\s*\/([A-Za-z0-9+\-_,]+)/g)].map((m) => m[1])
  line(`- \`${name}.pdf\`：ToUnicode 出现 ${hasToUnicode} 次，Identity-H 出现 ${hasIdentityH} 次，BaseFont=[${[...new Set(fontMatches)].join(', ')}]`)
}
line('')

// ---------- B. 提取保真度对比 ----------
line('## B. 提取结果 vs ground truth\n')
line('| 来源 | 提取路径 | 提取字符数 | 保留汉字数 | 汉字保留率 | 是否出现替换符 U+FFFD |')
line('| --- | --- | --- | --- | --- | --- |')

const rows = [
  ['single-col.pdf', 'pdftotext', R('out/single-col.raw.txt')],
  ['single-col.pdf', 'pdftotext -layout', R('out/single-col.layout.txt')],
  ['sidebar.pdf', 'pdftotext', R('out/sidebar.raw.txt')],
  ['sidebar.pdf', 'pdftotext -layout', R('out/sidebar.layout.txt')],
]
for (const [src, how, text] of rows) {
  const n = text ? cjk(text) : 0
  const pct = ((n / truthCJKCount) * 100).toFixed(1) + '%'
  const fffd = text ? (text.match(/\uFFFD/g) || []).length : 0
  line(`| ${src} | ${how} | ${text ? text.trim().length : 0} | ${n} | ${pct} | ${fffd} |`)
}

for (const d of ['plain', 'table-split', 'table-onecol-pair']) {
  const xml = R(`out/${d}.doc.xml`)
  const text = xml ? normalizeExtractedText(xmlToText(xml)) : null
  const n = text ? cjk(text) : 0
  const pct = ((n / truthCJKCount) * 100).toFixed(1) + '%'
  const fffd = text ? (text.match(/\uFFFD/g) || []).length : 0
  line(`| ${d}.docx | unzip + xmlToText | ${text ? text.length : 0} | ${n} | ${pct} | ${fffd} |`)
  if (text) fs.writeFileSync(path.join(OUT, `out/${d}.extracted.txt`), text, 'utf8')
}
line('')

// ---------- C. 丢失了哪些汉字 ----------
line('## C. PDF 路径到底丢了什么\n')
for (const [label, f] of [['pdftotext -layout', 'out/single-col.layout.txt'], ['pdftotext', 'out/single-col.raw.txt']]) {
  const text = R(f)
  if (!text) continue
  const kept = cjkSet(text)
  const lost = [...truthCJK].filter((c) => !kept.has(c))
  line(`- **${label}**：保留汉字 ${kept.size}/${truthCJK.size}，丢失 ${lost.length} 个`)
}
line('')

// ---------- D. 结构性检验：section 标题 + bullet 是否成组 ----------
line('## D. 结构性检验（这才是能否"准确修改"的关键）\n')
line('检查每个 section 的标题与其条目在提取文本中是否**连续成组**（中间无其他栏目内容插入）。\n')

function contiguity(text) {
  const res = []
  const probes = [
    ['工作经历', gt.SECTIONS.work[0]],
    ['项目经历', gt.SECTIONS.project[0]],
    ['专业技能', gt.SECTIONS.skills[0]],
  ]
  for (const [heading, firstItem] of probes) {
    const hi = text.indexOf(heading)
    const ii = text.indexOf(firstItem)
    if (hi === -1 || ii === -1) {
      res.push(`  - ${heading}: ${hi === -1 ? '标题丢失' : ''}${ii === -1 ? ' 条目丢失' : ''}`)
      continue
    }
    const between = text.slice(Math.min(hi, ii) + (hi < ii ? heading.length : firstItem.length), Math.max(hi, ii))
    const foreign = between.replace(/[\s|｜·•\-–—]/gu, '').length
    res.push(`  - ${heading}: ${hi < ii ? '标题在前' : '❗条目在标题前'}，中间夹着 ${foreign} 个非空白字符${foreign === 0 ? '（连续 ✅）' : '（被插入 ❗）'}`)
  }
  return res
}
for (const [label, f] of [
  ['single-col.pdf / pdftotext -layout', 'out/single-col.layout.txt'],
  ['sidebar.pdf / pdftotext -layout', 'out/sidebar.layout.txt'],
  ['plain.docx / xmlToText', 'out/plain.extracted.txt'],
]) {
  const text = R(f) || R(f.replace('out/', 'out/'))
  line(`### ${label}`)
  if (!text) { line('  (缺失)\n'); continue }
  if (cjk(text) === 0) { line('  ❌ 中文全部丢失，结构性检验无意义\n'); continue }
  line(contiguity(text).join('\n'))
  line('')
}

// ---------- E. 技能词是否被粘连 ----------
line('## E. 技能行是否被粘连（直接影响关键词匹配）\n')
const skillProbe = 'Java'
for (const [label, f] of [
  ['single-col.pdf / pdftotext -layout', 'out/single-col.layout.txt'],
  ['plain.docx / xmlToText', 'out/plain.extracted.txt'],
]) {
  const text = R(f)
  if (!text) continue
  const m = text.split('\n').find((l) => l.includes(skillProbe)) || '(未找到该行)'
  line(`- **${label}**：\`${m.trim()}\``)
}
line('')

// ---------- F. 结论数字 ----------
line('## F. 汇总\n')
const singleLayout = R('out/single-col.layout.txt') || ''
const sidebarLayout = R('out/sidebar.layout.txt') || ''
line(`- 单栏 PDF 经 \`pdftotext -layout\`：汉字保留 **${((cjk(singleLayout) / truthCJKCount) * 100).toFixed(1)}%**`)
line(`- 双栏 PDF 经 \`pdftotext -layout\`：汉字保留 **${((cjk(sidebarLayout) / truthCJKCount) * 100).toFixed(1)}%**`)

fs.writeFileSync(path.join(OUT, 'out/REPORT.md'), report.join('\n'), 'utf8')
console.log(report.join('\n'))
