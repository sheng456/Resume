# resume-tailor

> 一个**不臆造、不夸大**的简历改写引擎。配合 [boss-watch-agent](https://github.com/sheng456)，把 BOSS 岗位 JD 和你已有的简历，改写成「更匹配但不虚构」的版本。

## 为什么它不会编造

核心原则：**证据锚定是硬门禁，不是提示词约束**。

- JD 词进简历只有三条通道：① 简历本来就有、② `synonyms.json` 人工认定的同义短语、③ 用户显式声明的事实；
- 每条改写都要过 L5 校验：事实单元必须能追溯到源句或声明，否则回退原文；
- 事实保留检查：删掉量化指标 / 技术词 / 公司名 → 拦截；拔高职级（参与→主导）→ 需用户确认；
- 模型只在「表达层」有自由，主张层和事实层零自由。

## 架构

```
内容面（Python，本仓库）              控制面（DSH 插件 / MCP）
├─ L1 抽取 + 置信度门禁              ├─ boss-watch-agent：抓 JD、简历版本、匹配、投递
├─ L2 缺口诊断 + 模型级语义匹配       └─ resume-tailor MCP（本仓库 serve_mcp.py）
├─ L3 计划（指令优先 / JD 兜底）
├─ L4 改写（术语对齐 / reword / 重排）
├─ L5 校验（锚定 / JD 注入 / 事实保留）
├─ L6 评审（提案 → 接受/拒绝/声明事实）
└─ L7 落盘（内容寻址 + 血缘 + Gate W）
```

## 快速开始

### 跑测试

```bash
cd content-plane
PYTHONPATH=src python3 -m unittest discover -s tests -t .
# 169 例全过，零第三方依赖
```

### 起本地 HTTP 服务

```bash
cd content-plane
PYTHONPATH=src python3 -m resume_tailor serve --port 4319
```

### 作为 MCP server 接进 DSH

```bash
cd content-plane
PYTHONPATH=src python3 -m resume_tailor mcp
```

`dsh-mcp-bundle/` 是 DSH 配置型 bundle；装进 profile 后工具名为
`mcp__resume-tailor__{extract,gap,plan,run,review,commit,export}`。

### 演示

```bash
python3 demo_commit.py               # 完整闭环（抽取 → 计划 → 改写 → 落盘）
python3 demo_review.py               # L6 评审
python3 demo_pipeline.py --no-model  # 确定性改写（不接模型也能跑）
```

## 与 boss-watch 的两步闭环

```
boss-watch 抓 JD + 简历版本 V1
  → mcp__resume-tailor__extract / gap / plan / run / review / commit
  → mcp__resume-tailor__export        写 markdown 到 boss-watch resumeRoot
  → boss_watch_resume_import_apply    新版本登记进库（哈希逐字节对齐）
```

身份规则 `resume-version:sha256` + `local-resume://sha256:` 与 boss-watch 完全一致。
详见 [`docs/AGENT-ORCHESTRATION.md`](docs/AGENT-ORCHESTRATION.md)。

## 目录

```
content-plane/   Python 内容面（核心：L1–L7 + serve + MCP server）
control-plane/   TS 薄插件切片（已 author，未构建）
dsh-mcp-bundle/  MCP 配置 bundle（stdio）
docs/            架构 / 契约 / 集成方案 / 编排 / 根因
fixtures/        脱敏回归语料（虚构数据）
```

## 文档

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — 主架构
- [`docs/CONTRACTS.md`](docs/CONTRACTS.md) — loopback / MCP 契约
- [`docs/AGENT-ORCHESTRATION.md`](docs/AGENT-ORCHESTRATION.md) — agent 编排（两步闭环）
- [`docs/INTEGRATION-OPTIONS.md`](docs/INTEGRATION-OPTIONS.md) — 与 boss-watch 的组合方案分析
- [`docs/DSH-GITBASH-SHELL-ROOT-CAUSE.md`](docs/DSH-GITBASH-SHELL-ROOT-CAUSE.md) — 路径改写根因记录

## 隐私边界

- 简历正文永远只在本机内容面进程与内容寻址工件里；
- 跨边界只传 id / hash / 标签 / 计数；
- 评审 diff 只进本地 HTML 页面，不进 transcript；
- 登录 / 验证码 / 投递永远人工。

## 环境

Python 3.12（WSL Ubuntu-24.04 实测）。可选 `pypdf` 用于 PDF 提取——缺失时如实报
`pdf_extractor_unavailable`，绝不静默返回空串。
