# 组合方案分析：resume content-plane × boss-watch-agent

> 日期 2026-10-25。抛弃"合成一个插件"的前置假设，独立评估两者组合的所有方案。

## 0. 本质：两个正交系统，不是"一个系统的两半"

| | boss-watch-agent | resume content-plane |
| --- | --- | --- |
| 职责 | 求职**事实 + 投递编排**（找 JD、管简历版本、匹配、审批、投递） | 简历**改写引擎**（抽取/缺口/计划/改写/校验/评审/落盘） |
| 运行时 | TypeScript，浏览器依赖，已在 DSH 内 | Python 3.12，纯本地计算，零第三方依赖，可完全独立 |
| 边界 | 观察为主，登录/验证码/投递永远人工 | 正文永不出本机，不臆造是硬门禁 |

"组合"的本质不是合体，而是**定义一条最小交接契约**，让两个系统各自独立、只通过契约交接。

## 1. 交接契约（唯一必须对齐的东西）

```
boss-watch: (JD 文本, 简历版本 V1)  ──交接──▶  content-plane: 改写
content-plane: (markdown, contentHash, lineage→V1)  ──回写──▶  boss-watch: 新版本 V2
```

身份规则已对齐并实测验证：`resume-version:sha256`、`local-resume://sha256:`、
`supersedesResumeVersionId` 校验、幂等 `reused`。交接面无障碍。

## 2. 方案谱系（松 → 紧）

### 方案 A：完全独立 + agent 手动桥接（现状）
content-plane 跑独立 `serve`/CLI，agent 用通用 HTTP/bash 工具把 boss-watch 的 JD+简历
喂进去、拿 markdown 写回 resumeRoot。**已验证跑通。**
- ✅ 零改动、零耦合、立即可用
- ❌ 手动、不能规模化

### 方案 B：共享数据层，异步解耦（队列/任务目录/SQLite）
定义"任务"：boss-watch 把 `(JD 引用, resumeVersionId)` 写进共享目录/表，content-plane
（独立服务或 cron）消费→改写→写回结果，boss-watch 读结果 import。
- ✅ 最强解耦、可批处理、可重试、两边独立重启、可脱离 DSH 跑
- ❌ 要设计任务状态机 + 锁/队列；非实时

### 方案 C：boss-watch 内加桥接工具（薄工具层）
直接在 boss-watch-agent 里加 2 个 Host 工具，内部复用它的 resume store：读 JD+简历 →
调 content-plane serve → 拿 markdown → import 成新版本。
- ✅ agent 一条龙、复用 boss-watch 的 store/gate、隐私边界清晰
- ❌ 改 boss-watch 仓库；serve 要常驻

### 方案 D：content-plane 作为标准协议服务（MCP）独立接入 ⭐ 推荐
content-plane 做成 MCP server（Python，独立），DSH 用标准 MCP 配置接入；agent 同时握有
boss-watch 工具 + content-plane 工具。
- ✅ content-plane 完全独立（boss-watch 零改动）、标准协议、可独立演进（模型级匹配、批量）
- ❌ 要写 MCP 适配壳；MCP 工具返回会进 transcript，隐私要专门锁死（只回 id/hash + 本地评审页）

### 方案 E：子进程内嵌（boss-watch spawn Python）
boss-watch 工具内 `spawn python -m resume_tailor`，传文件路径、拿结果路径。
- ✅ 无常驻服务、部署只要 Python 在 PATH
- ❌ 每次 spawn 开销、跨语言传数据、超时/错误要自己管、不适合高频

### 方案 F：单进程融合/重写一端 —— 不推荐
放弃 154 例已测的 Python 引擎或 boss-watch 的成熟 TS，工作量大收益低。

## 3. 权衡一览

| | 改动面 | 隐私控制 | 部署复杂度 | 实时性 | 可规模化 | 可脱离 DSH |
| --- | --- | --- | --- | --- | --- | --- |
| A 桥接 | 零 | 好 | 低 | 手动 | ❌ | ✅ |
| B 队列 | 中 | 好 | 中（状态机） | 异步 | ✅ | ✅ |
| C 桥接工具 | boss-watch | 好 | serve 常驻 | 实时 | ✅ | ❌ |
| D MCP | content-plane | 需专门锁 | serve 常驻 | 实时 | ✅ | ✅（服务端独立） |
| E 子进程 | boss-watch | 好 | 无服务 | 实时 | ⚠️ | ❌ |

## 4. 决策：首选 D，务实过渡用 A

1. **D 最符合"两个正交系统"的本质**——content-plane 保持纯 Python 独立服务、零依赖、
   可独立演进，boss-watch 一行不改，DSH 只是"把两个工具集并排给 agent 用"。
2. **隐私是唯一要专门做的点**，已在 serve 层设计好（正文不回传、评审走本地页、令牌鉴权），
   MCP 只是再套一层协议壳。
3. **A 已经能用**，所以"没 MCP 壳"时 agent 用通用工具桥接也能跑——风险低、随时可退。
4. C/E 都要动 boss-watch 仓库；E 的高频/跨语言成本不划算；B 适合"批量投递"这类有规模
   诉求的后续阶段，现在上太早。

**一句话**：把 content-plane 当成一个独立的、有严格隐私边界的"改写服务"（已有 serve），
boss-watch 继续当"求职事实层"，中间用标准协议（MCP）或 agent 桥接连起来——而不是焊死成一个插件。
