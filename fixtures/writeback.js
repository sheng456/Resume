// 改写写回实验：把语义块映射回 OOXML 节点并重新打包，检验可行性与代价
const fs = require('node:fs')
const path = require('node:path')
const zlib = require('node:zlib')

const OUT = process.argv[2]

/* ---------- 复刻：ZIP 写入 ---------- */
const CRC_TABLE = (() => {
  const t = new Int32Array(256)
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c }
  return t
})()
const crc32 = (b) => { let c = -1; for (let i = 0; i < b.length; i++) c = CRC_TABLE[(c ^ b[i]) & 0xff] ^ (c >>> 8); return (c ^ -1) >>> 0 }
function zip(entries) {
  const locals = [], centrals = []; let offset = 0
  for (const [name, content] of entries) {
    const nameBuf = Buffer.from(name, 'utf8'), data = Buffer.from(content, 'utf8')
    const comp = zlib.deflateRawSync(data), crc = crc32(data)
    const lh = Buffer.alloc(30)
    lh.writeUInt32LE(0x04034b50, 0); lh.writeUInt16LE(20, 4); lh.writeUInt16LE(0, 6); lh.writeUInt16LE(8, 8)
    lh.writeUInt16LE(0, 10); lh.writeUInt16LE(0, 12); lh.writeUInt32LE(crc, 14)
    lh.writeUInt32LE(comp.length, 18); lh.writeUInt32LE(data.length, 22)
    lh.writeUInt16LE(nameBuf.length, 26); lh.writeUInt16LE(0, 28)
    locals.push(lh, nameBuf, comp)
    const ch = Buffer.alloc(46)
    ch.writeUInt32LE(0x02014b50, 0); ch.writeUInt16LE(20, 4); ch.writeUInt16LE(20, 6)
    ch.writeUInt16LE(0, 8); ch.writeUInt16LE(8, 10); ch.writeUInt16LE(0, 12); ch.writeUInt16LE(0, 14)
    ch.writeUInt32LE(crc, 16); ch.writeUInt32LE(comp.length, 20); ch.writeUInt32LE(data.length, 24)
    ch.writeUInt16LE(nameBuf.length, 28); ch.writeUInt16LE(0, 30); ch.writeUInt16LE(0, 32)
    ch.writeUInt16LE(0, 34); ch.writeUInt16LE(0, 36); ch.writeUInt32LE(0, 38); ch.writeUInt32LE(offset, 42)
    centrals.push(ch, nameBuf); offset += 30 + nameBuf.length + comp.length
  }
  const lb = Buffer.concat(locals), cb = Buffer.concat(centrals), eocd = Buffer.alloc(22)
  eocd.writeUInt32LE(0x06054b50, 0); eocd.writeUInt16LE(entries.length, 8); eocd.writeUInt16LE(entries.length, 10)
  eocd.writeUInt32LE(cb.length, 12); eocd.writeUInt32LE(lb.length, 16)
  return Buffer.concat([lb, cb, eocd])
}
// 从 docx 读回 entries（支持 deflate/stored）
function unzip(buf) {
  const entries = []
  let i = 0
  while (i < buf.length - 4) {
    if (buf.readUInt32LE(i) !== 0x04034b50) break
    const method = buf.readUInt16LE(i + 8)
    const csize = buf.readUInt32LE(i + 18), usize = buf.readUInt32LE(i + 22)
    const fnlen = buf.readUInt16LE(i + 26), extlen = buf.readUInt16LE(i + 28)
    const name = buf.slice(i + 30, i + 30 + fnlen).toString('utf8')
    const start = i + 30 + fnlen + extlen
    const comp = buf.slice(start, start + csize)
    const data = method === 8 ? zlib.inflateRawSync(comp) : comp
    entries.push([name, data.toString('utf8')])
    i = start + csize
  }
  return entries
}

/* ---------- 造一个"像 Word 输出"的 DOCX：段落文本跨多个 run ---------- */
const CONTENT_TYPES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>`
const RELS = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>`
const R_ = (t, bold = false) =>
  `<w:r>${bold ? '<w:rPr><w:b/></w:rPr>' : ''}<w:t xml:space="preserve">${t.replace(/&/g, '&amp;').replace(/</g, '&lt;')}</w:t></w:r>`

// 段落1：整句在一个 run 里（理想情况）
const para1 = `<w:p>${R_('· 负责订单履约模块开发，将核心查询接口 P99 从 320ms 降至 90ms')}</w:p>`
// 段落2：像 Word 一样被切成多个 run（数字/技术词被自动拆分并加粗）
const para2 = `<w:p>${R_('· 主导订单表分库分表改造，单表数据量从 ')}${R_('8000', true)}${R_(' 万降至 ')}${R_('500', true)}${R_(' 万')}</w:p>`
// 段落3：数字与中文粘在同一个 run 里 —— 改数字必须切分 run
const para3 = `<w:p>${R_('· 参与 CI/CD 流程建设，发布耗时从25分钟缩短至8分钟')}</w:p>`

const doc = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
${para1}${para2}${para3}
</w:body></w:document>`
const runsPath = path.join(OUT, 'runs.docx')
fs.writeFileSync(runsPath, zip([['[Content_Types].xml', CONTENT_TYPES], ['_rels/.rels', RELS], ['word/document.xml', doc]]))

/* ---------- 复刻上游 xmlToText ---------- */
const xmlToText = (x) => x.replace(/<w:tab\s*\/?>/gu, '\t').replace(/<w:br\s*\/?>/gu, '\n')
  .replace(/<\/w:p>/gu, '\n').replace(/<[^>]+>/gu, '')
  .replace(/&amp;/gu, '&').replace(/&lt;/gu, '<').replace(/&gt;/gu, '>').replace(/&quot;/gu, '"').replace(/&apos;/gu, "'")

const report = []
const L = (s) => report.push(s)

/* ---------- 分析：block ↔ XML 节点的对应关系 ---------- */
const entriesIn = unzip(fs.readFileSync(runsPath))
const docXml = entriesIn.find(([n]) => n === 'word/document.xml')[1]
const paras = [...docXml.matchAll(/<w:p>.*?<\/w:p>/gs)].map((m) => m[0])

L('# 简历「修改」环节实测：把改写文本写回 OOXML\n')
L('## A. 提取文本 vs XML 节点：一个"语义块"到底对应几个节点\n')
L('| 段落 | 提取出的文本（上游 xmlToText） | run 数 | `<w:t>` 数 | 文本是否跨 run |')
L('| --- | --- | --- | --- | --- |')
paras.forEach((p, i) => {
  const runs = (p.match(/<w:r>/g) || []).length
  const ts = (p.match(/<w:t[^>]*>/g) || []).length
  const text = xmlToText(p).trim()
  L(`| ${i + 1} | ${text} | ${runs} | ${ts} | ${runs > 1 ? '**是**' : '否'} |`)
})
L('')
L('上游 `readText → xmlToText → chunk_resume` 得到的是**字符串**；字符串里没有任何 run 边界信息。')
L('要把改写结果写回去，必须重新定位到 `<w:p>`/`<w:r>`，这一步在提取阶段就把信息丢掉了。\n')

/* ---------- B. 策略1：整段替换（合并 run） ---------- */
L('## B. 策略 1 · 整段替换（把段落所有 run 换成单 run）\n')
function rewriteParagraphWhole(docXml, index, newText) {
  const list = [...docXml.matchAll(/<w:p>.*?<\/w:p>/gs)]
  const target = list[index][0]
  const replacement = `<w:p>${R_(newText)}</w:p>`
  return docXml.replace(target, replacement)
}
const b1 = rewriteParagraphWhole(docXml, 1, '· 主导订单表分库分表改造，单表数据量从 8000 万降至 300 万')
const b1RunsBold = ((b1.match(/<w:b\/>/g) || []).length)
L('对第 2 段（原本 3 个加粗 run）执行整段替换：')
L('```text')
L(`改写前加粗标记数量: ${(docXml.match(/<w:b\/>/g) || []).length}`)
L(`改写后加粗标记数量: ${b1RunsBold}`)
L('```')
L('**结果：文本可正确写入，但 run 级格式（加粗的量化数字）全部丢失。**')
L('这是"整段替换"的必然代价——格式化信息只存在于 run 上，合并 run 就等于放弃格式。\n')

/* ---------- C. 策略2：run 内原地替换 ---------- */
L('## C. 策略 2 · 在 run 内原地替换目标子串\n')
function replaceInRuns(docXml, index, from, to) {
  const list = [...docXml.matchAll(/<w:p>.*?<\/w:p>/gs)]
  const target = list[index][0]
  let hit = false
  const patched = target.replace(/(<w:t[^>]*>)([\s\S]*?)(<\/w:t>)/g, (m, o, body, c) => {
    if (!hit && body.includes(from)) { hit = true; return o + body.replace(from, to) + c }
    return m
  })
  return { xml: docXml.replace(target, patched), hit }
}
const cases = [
  ['第 1 段：目标数字与整句在同一个 run', 0, '320ms', '280ms'],
  ['第 2 段：目标数字独占一个 run', 1, '8000', '6000'],
  ['第 3 段：目标数字与中文同在一个 run（"从25分钟"）', 2, '25分钟', '15分钟'],
]
L('| 场景 | 目标子串 | 是否命中单个 run | 结果 |')
L('| --- | --- | --- | --- |')
for (const [label, idx, from, to] of cases) {
  const { hit } = replaceInRuns(docXml, idx, from, to)
  L(`| ${label} | \`${from}\` | ${hit ? '是' : '否'} | ${hit ? '可原地替换，保留格式 ✅' : '**跨 run / 未命中，需切分或合并 run** ❌'} |`)
}
L('')
L('说明：全部三种情况在这里都"命中"了，是因为我构造的 fixture 够简单。真正的问题在下面。\n')

/* ---------- D. 关键反例：目标子串跨越 run 边界 ---------- */
L('## D. 关键反例 · 目标子串跨越 run 边界\n')
const splitDoc = `<w:p>${R_('· 引入 Kafka 异步化，峰值 QPS 从 1')}${R_('200', true)}${R_(' 提升至 4500')}</w:p>`
const sdRuns = (splitDoc.match(/<w:t[^>]*>([\s\S]*?)<\/w:t>/g) || []).map((t) => t.replace(/<[^>]+>/g, ''))
L('构造一个"数字被 Word 拆开"的段落（这在真实 Word 文件里很常见，例如拼写/语言检查切换时会切 run）：')
L('```text')
L(`提取文本（正确）: ${xmlToText(splitDoc).trim()}`)
L(`XML 里的 run  : ${JSON.stringify(sdRuns)}`)
L('```')
const attempt = replaceInRuns(`<w:body>${splitDoc}</w:body>`, 0, '1200', '2600')
L(`- 用整串 \`1200\` 做 run 内替换 → 命中：**${attempt.hit ? '是' : '否'}**`)
L('- 因为 `1` 和 `200` 被切在两个 run 里，任何"按提取文本做子串替换"的实现都会**静默失配**：')
L('  提取层看到的是 `1200`，XML 层根本不存在 `1200` 这个字符串。')
L('- 正确做法必须：定位跨 run 的字符区间 → 拆分/合并 run → 克隆 `rPr` → 处理 `xml:space`。')
L('  **这是"准确修改"真正的工程量所在，而不是调用一次模型。**\n')

/* ---------- E. 端到端回环验证 ---------- */
L('## E. 端到端回环：改写 → 重新打包 → 再提取\n')
const rewritten = rewriteParagraphWhole(docXml, 2, '· 参与 CI/CD 流程建设，发布耗时从 15 分钟缩短至 8 分钟')
fs.writeFileSync(path.join(OUT, 'runs-rewritten.docx'),
  zip([['[Content_Types].xml', CONTENT_TYPES], ['_rels/.rels', RELS], ['word/document.xml', rewritten]]))
const rt = unzip(fs.readFileSync(path.join(OUT, 'runs-rewritten.docx'))).find(([n]) => n === 'word/document.xml')[1]
const before = xmlToText(docXml).trim().split('\n')
const after = xmlToText(rt).trim().split('\n')
L('| 段 | 改写前 | 改写后 |')
L('| --- | --- | --- |')
before.forEach((b, i) => L(`| ${i + 1} | ${b} | ${after[i] || '(缺失)'} |`))
const sizeBefore = fs.statSync(runsPath).size, sizeAfter = fs.statSync(path.join(OUT, 'runs-rewritten.docx')).size
L('')
L(`- 文件大小：${sizeBefore} → ${sizeAfter} 字节`)
L(`- 内容哈希：${require('node:crypto').createHash('sha256').update(fs.readFileSync(runsPath)).digest('hex').slice(0, 16)} → ${require('node:crypto').createHash('sha256').update(fs.readFileSync(path.join(OUT, 'runs-rewritten.docx'))).digest('hex').slice(0, 16)}`)
L('- **回环在机械层面跑通了**：改一个 `\\`<w:p>\\``、重新打包、再次提取，其余段落逐字不变。')
L('- 结论：**写回本身不是难点；难点是"哪一段/哪个字符区间"以及"格式归谁"。**\n')

fs.writeFileSync(path.join(OUT, 'out/WRITE-REPORT.md'), report.join('\n'), 'utf8')
console.log(report.join('\n'))
