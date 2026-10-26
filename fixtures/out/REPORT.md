# 简历读取保真度实测

ground truth：中文 160 字（去重 108 个不同汉字）

## A. 生成的 PDF 内部是否有中文文本层

- `single-col.pdf`：ToUnicode 出现 2 次，Identity-H 出现 2 次，BaseFont=[AAAAAA+MicrosoftYaHei-Bold, BAAAAA+MicrosoftYaHei]
- `sidebar.pdf`：ToUnicode 出现 2 次，Identity-H 出现 2 次，BaseFont=[AAAAAA+MicrosoftYaHei-Bold, BAAAAA+MicrosoftYaHei]

## B. 提取结果 vs ground truth

| 来源 | 提取路径 | 提取字符数 | 保留汉字数 | 汉字保留率 | 是否出现替换符 U+FFFD |
| --- | --- | --- | --- | --- | --- |
| single-col.pdf | pdftotext | 250 | 0 | 0.0% | 3 |
| single-col.pdf | pdftotext -layout | 289 | 0 | 0.0% | 3 |
| sidebar.pdf | pdftotext | 258 | 0 | 0.0% | 3 |
| sidebar.pdf | pdftotext -layout | 440 | 0 | 0.0% | 3 |
| plain.docx | unzip + xmlToText | 434 | 156 | 97.5% | 0 |
| table-split.docx | unzip + xmlToText | 438 | 160 | 100.0% | 0 |
| table-onecol-pair.docx | unzip + xmlToText | 435 | 160 | 100.0% | 0 |

## C. PDF 路径到底丢了什么

- **pdftotext -layout**：保留汉字 0/108，丢失 108 个
- **pdftotext**：保留汉字 0/108，丢失 108 个

## D. 结构性检验（这才是能否"准确修改"的关键）

检查每个 section 的标题与其条目在提取文本中是否**连续成组**（中间无其他栏目内容插入）。

### single-col.pdf / pdftotext -layout
  ❌ 中文全部丢失，结构性检验无意义

### sidebar.pdf / pdftotext -layout
  ❌ 中文全部丢失，结构性检验无意义

### plain.docx / xmlToText
  - 工作经历: 标题在前，中间夹着 24 个非空白字符（被插入 ❗）
  - 项目经历: 标题在前，中间夹着 22 个非空白字符（被插入 ❗）
  - 专业技能: 标题在前，中间夹着 0 个非空白字符（连续 ✅）

## E. 技能行是否被粘连（直接影响关键词匹配）

- **single-col.pdf / pdftotext -layout**：`JavaSpring BootMySQLRedisKafkaDockerKubernetes`
- **plain.docx / xmlToText**：`Java、Spring Boot、MySQL、Redis、Kafka、Docker、Kubernetes`

## F. 汇总

- 单栏 PDF 经 `pdftotext -layout`：汉字保留 **0.0%**
- 双栏 PDF 经 `pdftotext -layout`：汉字保留 **0.0%**