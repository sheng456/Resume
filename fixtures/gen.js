// 生成简历保真度实验的 fixture。仅写入 scratch 目录，不触碰任何项目文件。
const fs = require('node:fs')
const path = require('node:path')
const zlib = require('node:zlib')

const OUT = process.argv[2]
fs.mkdirSync(OUT, { recursive: true })

// ---------- 1. 虚构、脱敏的简历内容（ground truth） ----------
const SIDEBAR_LEFT = [
  '联系方式',
  '电话：138-0000-0000',
  '邮箱：zhangming@example.com',
  '城市：上海',
  '专业技能',
  'Java、Spring Boot、MySQL、Redis、Kafka、Docker、Kubernetes',
  '教育背景',
  '2019.09 – 2023.06  某某大学  计算机科学与技术  本科',
]

const MAIN_RIGHT = [
  '张明',
  '求职意向：后端开发工程师',
  '工作经历',
  '某某科技有限公司 ｜ 后端开发工程师 ｜ 2023.07 – 至今',
  '· 负责订单履约模块开发，将核心查询接口 P99 从 320ms 降至 90ms',
  '· 主导订单表分库分表改造，单表数据量从 8000 万降至 500 万',
  '· 参与 CI/CD 流程建设，发布耗时从 25 分钟缩短至 8 分钟',
  '项目经历',
  '订单履约系统重构 ｜ 2024.03 – 2024.09',
  '· 使用 Spring Boot + MySQL + Redis 重构订单核心链路',
  '· 引入 Kafka 异步化，峰值 QPS 从 1200 提升至 4500',
]

const SECTIONS = {
  contact: SIDEBAR_LEFT.slice(1, 4),
  skills: [SIDEBAR_LEFT[5]],
  education: [SIDEBAR_LEFT[7]],
  work: MAIN_RIGHT.slice(4, 7),
  project: MAIN_RIGHT.slice(9, 11),
}

fs.writeFileSync(
  path.join(OUT, 'ground-truth.json'),
  JSON.stringify({ SIDEBAR_LEFT, MAIN_RIGHT, SECTIONS }, null, 2),
  'utf8',
)

// ---------- 2. 单栏 HTML（对照组） ----------
const singleHtml = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
@page { size: A4; margin: 15mm; }
body { font-family: "Microsoft YaHei", SimSun, sans-serif; font-size: 10.5pt; line-height: 1.5; }
h1 { font-size: 16pt; margin: 0 0 2mm 0; }
h2 { font-size: 11pt; margin: 4mm 0 1mm 0; border-bottom: 1px solid #999; }
p  { margin: 0 0 1mm 0; }
ul { margin: 0; padding-left: 5mm; }
</style></head><body>
<h1>${MAIN_RIGHT[0]}</h1>
<p>${MAIN_RIGHT[1]}</p>
<p>${SIDEBAR_LEFT[1]} ｜ ${SIDEBAR_LEFT[2]} ｜ ${SIDEBAR_LEFT[3]}</p>
<h2>教育背景</h2>
<p>${SIDEBAR_LEFT[7]}</p>
<h2>工作经历</h2>
<p>${MAIN_RIGHT[3]}</p>
<ul>${SECTIONS.work.map((x) => `<li>${x.replace(/^·\s*/, '')}</li>`).join('')}</ul>
<h2>项目经历</h2>
<p>${MAIN_RIGHT[8]}</p>
<ul>${SECTIONS.project.map((x) => `<li>${x.replace(/^·\s*/, '')}</li>`).join('')}</ul>
<h2>专业技能</h2>
<p>${SIDEBAR_LEFT[5]}</p>
</body></html>`
fs.writeFileSync(path.join(OUT, 'single-col.html'), singleHtml, 'utf8')

// ---------- 3. 双栏侧边栏 HTML（真实高频版式） ----------
const sidebarHtml = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
@page { size: A4; margin: 0; }
body { font-family: "Microsoft YaHei", SimSun, sans-serif; font-size: 10.5pt; margin: 0; }
.wrap { display: flex; }
.left { width: 33%; background: #f2f2f2; padding: 12mm 6mm; box-sizing: border-box; }
.right { width: 67%; padding: 12mm 8mm; box-sizing: border-box; }
h1 { font-size: 16pt; margin: 0 0 2mm 0; }
h2 { font-size: 11pt; margin: 4mm 0 1mm 0; border-bottom: 1px solid #999; }
.left h2 { border-bottom: 1px solid #bbb; }
p { margin: 0 0 1mm 0; }
ul { margin: 0; padding-left: 5mm; }
</style></head><body>
<div class="wrap">
  <div class="left">
    <h2>联系方式</h2>
    ${SIDEBAR_LEFT.slice(1, 4).map((x) => `<p>${x}</p>`).join('')}
    <h2>专业技能</h2>
    <p>${SIDEBAR_LEFT[5]}</p>
    <h2>教育背景</h2>
    <p>${SIDEBAR_LEFT[7]}</p>
  </div>
  <div class="right">
    <h1>${MAIN_RIGHT[0]}</h1>
    <p>${MAIN_RIGHT[1]}</p>
    <h2>工作经历</h2>
    <p>${MAIN_RIGHT[3]}</p>
    <ul>${SECTIONS.work.map((x) => `<li>${x.replace(/^·\s*/, '')}</li>`).join('')}</ul>
    <h2>项目经历</h2>
    <p>${MAIN_RIGHT[8]}</p>
    <ul>${SECTIONS.project.map((x) => `<li>${x.replace(/^·\s*/, '')}</li>`).join('')}</ul>
  </div>
</div>
</body></html>`
fs.writeFileSync(path.join(OUT, 'sidebar.html'), sidebarHtml, 'utf8')

// ---------- 4. ZIP 写入器（无 zip 命令，手工构造 DOCX 容器） ----------
const CRC_TABLE = (() => {
  const t = new Int32Array(256)
  for (let n = 0; n < 256; n++) {
    let c = n
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    t[n] = c
  }
  return t
})()
function crc32(buf) {
  let c = -1
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8)
  return (c ^ -1) >>> 0
}
function zip(entries) {
  const locals = []
  const centrals = []
  let offset = 0
  for (const [name, content] of entries) {
    const nameBuf = Buffer.from(name, 'utf8')
    const data = Buffer.from(content, 'utf8')
    const comp = zlib.deflateRawSync(data)
    const crc = crc32(data)
    const lh = Buffer.alloc(30)
    lh.writeUInt32LE(0x04034b50, 0)
    lh.writeUInt16LE(20, 4)
    lh.writeUInt16LE(0, 6)
    lh.writeUInt16LE(8, 8)
    lh.writeUInt16LE(0, 10)
    lh.writeUInt16LE(0, 12)
    lh.writeUInt32LE(crc, 14)
    lh.writeUInt32LE(comp.length, 18)
    lh.writeUInt32LE(data.length, 22)
    lh.writeUInt16LE(nameBuf.length, 26)
    lh.writeUInt16LE(0, 28)
    locals.push(lh, nameBuf, comp)

    const ch = Buffer.alloc(46)
    ch.writeUInt32LE(0x02014b50, 0)
    ch.writeUInt16LE(20, 4)
    ch.writeUInt16LE(20, 6)
    ch.writeUInt16LE(0, 8)
    ch.writeUInt16LE(8, 10)
    ch.writeUInt16LE(0, 12)
    ch.writeUInt16LE(0, 14)
    ch.writeUInt32LE(crc, 16)
    ch.writeUInt32LE(comp.length, 20)
    ch.writeUInt32LE(data.length, 24)
    ch.writeUInt16LE(nameBuf.length, 28)
    ch.writeUInt16LE(0, 30)
    ch.writeUInt16LE(0, 32)
    ch.writeUInt16LE(0, 34)
    ch.writeUInt16LE(0, 36)
    ch.writeUInt32LE(0, 38)
    ch.writeUInt32LE(offset, 42)
    centrals.push(ch, nameBuf)
    offset += 30 + nameBuf.length + comp.length
  }
  const localBuf = Buffer.concat(locals)
  const centralBuf = Buffer.concat(centrals)
  const eocd = Buffer.alloc(22)
  eocd.writeUInt32LE(0x06054b50, 0)
  eocd.writeUInt16LE(0, 4)
  eocd.writeUInt16LE(0, 6)
  eocd.writeUInt16LE(entries.length, 8)
  eocd.writeUInt16LE(entries.length, 10)
  eocd.writeUInt32LE(centralBuf.length, 12)
  eocd.writeUInt32LE(localBuf.length, 16)
  eocd.writeUInt16LE(0, 20)
  return Buffer.concat([localBuf, centralBuf, eocd])
}

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

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const P = (t) => `<w:p><w:r><w:t xml:space="preserve">${esc(t)}</w:t></w:r></w:p>`

// 4a. 朴素 DOCX（单栏，段落流）—— 对照组
const plainBody = [
  P(MAIN_RIGHT[0]), P(MAIN_RIGHT[1]),
  P(`${SIDEBAR_LEFT[1]} ｜ ${SIDEBAR_LEFT[2]} ｜ ${SIDEBAR_LEFT[3]}`),
  P('教育背景'), P(SIDEBAR_LEFT[7]),
  P('工作经历'), P(MAIN_RIGHT[3]), ...SECTIONS.work.map(P),
  P('项目经历'), P(MAIN_RIGHT[8]), ...SECTIONS.project.map(P),
  P('专业技能'), P(SIDEBAR_LEFT[5]),
].join('')
const plainDoc = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${plainBody}</w:body></w:document>`
fs.writeFileSync(
  path.join(OUT, 'plain.docx'),
  zip([['[Content_Types].xml', CONTENT_TYPES], ['_rels/.rels', RELS], ['word/document.xml', plainDoc]]),
)

// 4b. 表格版 DOCX（左侧栏 + 右主栏，逐行配对）—— 真实高频「表格简历」
const rows = []
const maxRows = Math.max(SIDEBAR_LEFT.length, MAIN_RIGHT.length)
for (let i = 0; i < maxRows; i++) {
  const l = SIDEBAR_LEFT[i] ? P(SIDEBAR_LEFT[i]) : P('')
  const r = MAIN_RIGHT[i] ? P(MAIN_RIGHT[i]) : P('')
  rows.push(`<w:tr><w:tc>${l}</w:tc><w:tc>${r}</w:tc></w:tr>`)
}
const tableDoc = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:tbl>${rows.join('')}</w:tbl>
</w:body></w:document>`
fs.writeFileSync(
  path.join(OUT, 'table-split.docx'),
  zip([['[Content_Types].xml', CONTENT_TYPES], ['_rels/.rels', RELS], ['word/document.xml', tableDoc]]),
)

// 4c. 表格版 DOCX 变体：左栏整块一个单元格，右栏整块一个单元格（单行两列）
const oneRowDoc = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:tbl><w:tr><w:tc>${SIDEBAR_LEFT.map(P).join('')}</w:tc><w:tc>${MAIN_RIGHT.map(P).join('')}</w:tc></w:tr></w:tbl>
</w:body></w:document>`
fs.writeFileSync(
  path.join(OUT, 'table-onecol-pair.docx'),
  zip([['[Content_Types].xml', CONTENT_TYPES], ['_rels/.rels', RELS], ['word/document.xml', oneRowDoc]]),
)

console.log('fixtures written to', OUT)
for (const f of fs.readdirSync(OUT)) console.log(' -', f)
