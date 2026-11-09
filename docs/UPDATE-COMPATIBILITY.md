# 更新兼容性 & 冒烟清单

> 本文件记录 resume-tailor MCP 集成与 DSH / 插件的耦合点，以及**每次 DSH 更新后必须跑的冒烟清单**。
> 目的是：更新不背锅——坏没坏，用清单说话。

## 一、耦合点（更新可能打断的地方）

| 耦合点 | 依赖内容 | 风险 | 归属 |
| --- | --- | --- | --- |
| `@deepseek-ai/dsh-mcp-client` 配置 schema | `transport: stdio` / `command` / `args` / `serverName` / `failOnStartupError` | 中：字段改名则 bundle 失效 | DSH 内置 |
| `dsh.bundle.patch` 机制 | `package.json` 的 `dsh.bundle.patch` → `cordis.patch.yml` | 中：机制变更需改 bundle 格式 | DSH Loader |
| 工具命名 `mcp__<serverName>__<rawName>` | 工具名形如 `mcp__resume-tailor__extract` | 低：名字变了，调用方式不变 | DSH mcp-client |
| `dsh-gitbash-shell` 路径改写 | `TRANSLATABLE_PATH_FIELDS = {file_path, path, workdir, root}` | 低：**本项目用 `filePath` 绕过**，已在 `0.43.2` 与 `0.52.0` 验证不变 | 第三方插件 |
| `BOSS_WATCH_DATA_DIR` | boss-watch 存储根（`resolveDataDirectory()`） | **高：不持久则会回落 AppData**，已改为持久化用户环境变量 | boss-watch 插件 |

**不受影响的部分（关键）**：
- `content-plane/` 是**独立 Python 引擎**，`python3 -m resume_tailor mcp` / `serve` 不依赖 DSH；
- 数据是普通文件 + SQLite，与 DSH 无关。

## 二、每次 DSH 更新后的冒烟清单

按顺序跑，任一步失败即定位到对应耦合点：

1. **DSH 启动**：`dsh web` 能正常起来（确认 bundle 未因 schema 变更崩溃）。
2. **MCP 工具往返**：`mcp__resume-tailor__extract(filePath=...)` 返回 `doc_id`（确认 mcp-client 配置仍被接受）。
3. **旧字段兼容**：`extract(file_path=...)` 也返回 `doc_id`（确认 gitbash-shell 仍只改写 `file_path`、且 `_normalize_path` 兜底有效）。
4. **boss-watch 读新位置**：`boss_watch_resume_list` 返回的版本数应包含 `f2e05288…`（5 个）——若只有 4 个，说明 `BOSS_WATCH_DATA_DIR` 未生效、又回落 AppData 了。
5. **闭环对齐**：export 一份 → `resume_import_preview` 能读到且 `contentHash` 一致（确认导出目录 == boss-watch resumeRoot）。

## 三、更新记录

### 2026-11-09 核查（DSH 0.2.2-alpha.2 → 0.2.2-rc.1）

| 组件 | 旧 | 新 | 与本项目相关？ |
| --- | --- | --- | --- |
| DSH 本体 | 0.2.2-alpha.2 | **0.2.2-rc.1** | 是（mcp-client / bundle 机制） |
| `@deepseek-ai/dsh-mcp-client` | 0.2.2-alpha.2 | 0.2.2-rc.1 | 是（配置 schema） |
| `dsh-gitbash-shell` | 0.43.2 | **0.52.0** | 是（路径改写） |
| `@linxin666/dsh-pet` / `@linxin666/dsh-web-all` | 0.4.11 | 0.4.16 | 否 |
| `dsh-pet` | 0.3.8 | 0.4.7 | 否 |
| `dsh-wsl-workspace` | 0.7.11 | 0.7.13 | 否 |
| `dsh-plugin-wallpaper-engine` | ^1.4.0 | 1.4.2 | 否 |
| `@liustack/modsearch` / `dshmarket` | — | 新增 | 否 |

**核查结论：未出现破坏。** 依据：
- `extract(filePath)` 与 `extract(file_path)` 均返回同一 `doc_id`（`doc:d5092804…`）；
- `boss_watch_resume_list` 返回 5 个版本（含 `f2e05288…`），证明 boss-watch 读的是 `boss-watch-agent/data` 新位置；
- `dsh-gitbash-shell 0.52.0` 的 `TRANSLATABLE_PATH_FIELDS` 仍为 `{file_path, path, workdir, root}`，未包含 `filePath`，绕过继续有效。

## 四、已知风险与缓解

| 风险 | 缓解 |
| --- | --- |
| DSH alpha/rc 版本频繁变更 | 更新后立刻跑上面 5 步；出问题优先检查 `cordis.patch.yml` 的 schema 字段 |
| `dsh-gitbash-shell` 未来把 `filePath` 也纳入改写 | `_normalize_path` 已能剥 `c:/program files/git/` 前缀，即使被改写也能恢复；届时可再评估 |
| `BOSS_WATCH_DATA_DIR` 回落 AppData | 已设为**持久化用户环境变量**（`HKCU\Environment`），DSH 从新进程启动即可继承 |
| 引擎依赖 Python 3.12 | `content-plane` 零第三方依赖（可选 pypdf）；缺 pypdf 时如实报 `pdf_extractor_unavailable` |
