# 内容面 loopback 契约（P0）

内容面（Python 本机服务）与控制面（DSH 插件切片）之间的 HTTP 契约。
**正文永不跨边界**：简历/JD/改写候选只在本进程内存与内容寻址工件里，
跨边界只传 id / hash / 标签 / 枚举 / 计数。

## 传输

- `POST /`，请求体 JSON：`{"method": "<方法>", "params": {...}, "token": "<服务令牌>"}`
- 响应：`{"ok": true, "result": {...}}` 或 `{"ok": false, "error": "<稳定错误码>"}`
- 令牌：`RESUME_TAILOR_TOKEN` 环境变量；缺省启动时随机生成并打印前缀。
- 评审 diff：`GET /review/<plan_id>` 返回本地 HTML 页；文本只在这一页，不进工具响应。

## 方法

### extract — 上传字节、提取文本、只回元数据

- 入参：`filename`（后缀决定提取器）、`data_b64`（文件字节 base64）
- 出参：`doc_id`（内容寻址 `doc:sha256`）、`media_type`、`extractor`、`confidence`
  （high/low）、`signals[]`、`char_count`、`cjk_count`、`usable`
- **不回文本**。低置信度（表格布局/0% 中文/粘连/无 PDF 提取器）如实标注，由上层走重生模式。

### gap — JD 缺口诊断

- 入参：`jd_doc_id`、`resume_doc_id`
- 出参：`requirement_count`、`gaps[]`（`requirement_id`、`coverage`、
  `requirement_terms`（技术标签）、`best_block_ids`）
- **不回 JD 原文（`label`）**。

### plan — 计划（Gate T 审批对象）

- 入参：`jd_doc_id`、`resume_doc_id`、`instruction?`
- 出参（成功）：`plan_id`、`driver`（instruction/jd_gap）、`intent_id`、
  `instruction_hash`、`step_count`、`forbidden_terms`、`bullet_order`
- 出参（歧义/冲突）：`ok: false` + `clarification_options` / `conflicts[]`
- **不回任何目标文本**。

### run — 触发改写（确定性对齐 + 重排；模型按环境变量插入）

- 入参：`plan_id`
- 出参：`changed_count`、`changed_block_ids`、`total_blocks`
- **不回改写后的正文**。

### commit — 内容寻址落盘 + 血缘（Gate W 审批）

- 入参：`plan_id`、`base_resume_version_id?`
- 出参：`resume_version_id`、`content_hash`、`local_artifact_ref`、`lineage_id`、`reused`
- 幂等：同内容重复落盘 `reused=true`；supersedes 指向不存在版本时拒绝。

### export — 渲染 markdown 到导入目录（打通 boss-watch 闭环）

- 入参：`plan_id`、`resume_dir?`（缺省 `BOSS_WATCH_RESUME_DIR`，即 boss-watch 的 resumeRoot）、`display_name?`
- 出参：`file_name`、`file_path`、`content_hash`、`resume_version_id`、`media_type`、`byte_size`
- **身份对齐**：`content_hash = sha256(markdown 字节)`，与 boss-watch 的 `resume_import_preview`
  算出的哈希逐字节相同；随后调用 `boss_watch_resume_import_apply(fileName, supersedes?)`
  即可把新版本登记进 boss-watch 简历库（实测同哈希 `b4d8d3ef…`）。

### review — 打开本地评审页

- 入参：`plan_id`
- 出参：`review_url`（`/review/<plan_id>?token=<短命评审令牌>`）；diff 文本只在该本地页。
- **鉴权**：评审页是唯一返回正文的端点，`GET /review/<plan_id>` 必须带按 plan 绑定的
  短命 `token`（由 `review` 签发、进程内短命、重启失效），不带令牌返回 `401`。
  服务令牌绝不进 URL。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `RESUME_TAILOR_TOKEN` | 随机 | loopback 服务令牌 |
| `RESUME_TAILOR_HOME` | `~/.resume-tailor` | 落盘根目录 |
| `RESUME_TAILOR_DB_PATH` | `$HOME/versions.sqlite3` | 版本 SQLite |
| `RESUME_TAILOR_ARTIFACT_ROOT` | `$HOME/artifacts` | 内容寻址工件目录 |
| `RESUME_REWORD_PROVIDER` | `ollama` | 改写模型 provider（未来接 run） |

## 隐私不变量（测试锁死）

1. 任何 `result` 中不出现简历正文、JD 正文、改写候选正文；
2. 正文只存在于 `extract` 之后的服务端内存与内容寻址工件；
3. HTTP 层不打印请求体（`log_message` 置空）；
4. 置信度信号的 `detail` 只回固定文案与计数，**不拼原文片段**（粘连 run 尤其）；
5. 评审页（正文端点）必须带按 plan 绑定的短命评审令牌，其余元数据端点用服务令牌。
