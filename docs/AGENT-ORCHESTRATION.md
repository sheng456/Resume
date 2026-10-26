# Agent 编排：抓 JD → 改写 → 回写 boss-watch（两步闭环）

> 目标：让 DSH agent 用现成工具，把「BOSS JD → 简历改写 → 新版本回写 boss-watch」
> 串成一条可执行的闭环。所有工具都已挂载并实测通过（169 例测试 + 真实数据验证）。

## 工具全景

| 阶段 | 工具 | 归属 |
| --- | --- | --- |
| 抓 JD / 简历版本 | `boss_watch_discover_jobs` / `capture_current_job` / `resume_list` | boss-watch 插件 |
| 分析 + 改写 | `mcp__resume-tailor__{extract,gap,plan,run,review,commit,export}` | resume-tailor MCP |
| 回写注册 | `boss_watch_resume_import_{preview,apply}` | boss-watch 插件 |

## 标准流程

### ① 取输入（boss-watch）

1. JD：`boss_watch_capture_current_job`（用户已打开 BOSS 详情页）或 `boss_watch_discover_jobs`
   → 拿到 JD 文本（抓到的 JD 常是**单行**，resume-tailor 已做句级切分，无需预处理）。
2. 基础简历：`boss_watch_resume_list` → 选一个版本 V1（`resume-version:…`）。

### ② 分析 + 改写（resume-tailor MCP）

先把 JD / 简历落成文件交给 `extract`（`filePath` 传 WSL `/mnt/...` 或 Windows `X:/...` 均可，
服务端自动归一）：

```
mcp__resume-tailor__extract(filePath=<JD 文件>)      → jd_doc_id
mcp__resume-tailor__extract(filePath=<简历文件>)     → resume_doc_id
mcp__resume-tailor__gap(jd_doc_id, resume_doc_id)     → 缺口报告（只回标签/覆盖，不回正文）
mcp__resume-tailor__plan(jd_doc_id, resume_doc_id[, instruction]) → plan_id
mcp__resume-tailor__run(plan_id)                       → changed/reordered 摘要
mcp__resume-tailor__review(plan_id)                    → 本地评审页路径（diff 只在该页）
mcp__resume-tailor__commit(plan_id)                    → resume_version_id + contentHash + lineage
```

### ③ 回写 boss-watch（**两步闭环**）

```
mcp__resume-tailor__export(plan_id, display_name)      → 写 markdown 到 boss-watch resumeRoot
                                                         返回 file_name + contentHash
boss_watch_resume_import_preview(fileName=<file_name>,
                                 supersedesResumeVersionId=<V1>)
boss_watch_resume_import_apply(previewToken, confirmed=true)
```

**身份对齐是自动的**：`export` 的 `content_hash = sha256(markdown 字节)`，与
`resume_import_preview` 算出的哈希**逐字节相同**（实测 `b4d8d3ef…`），所以新版本
干净落在 V1 的血缘链下。

## 硬边界（agent 必须遵守）

- **正文不进 Transcript**：所有 `mcp__resume-tailor__*` 只回 id/hash/标签/计数；
  评审 diff 只进本地 HTML 文件；`export` 只回文件名+哈希，不回 markdown 正文。
- **不臆造**：JD 词进简历只有三条通道（本来就有 / synonyms 等价 / 用户声明）；
  `forbidden_terms` 硬禁注入；`run` 的确定性改写 + reword 门禁兜底。
- **登录/验证码/投递永远人工**：本流程只做「改写 + 本地登记新版本」，不投递、不发送。
- **每一步只读/需确认分离**：`extract/gap/plan/run/review` 只读；`commit/export` 落盘；
  `resume_import_apply` 前先 `preview` 并等用户确认。

## 失败语义（结构化错误码）

- `file_not_found` / `not_a_file` / `unknown_reference` / `supersedes_not_found` /
  `store_unavailable` / `invalid_request` —— agent 据此报告，不自动重试、不绕过。
