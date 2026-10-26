# resume-tailor 控制面切片（P3 + P4）

薄 DSH 插件：把 Python 内容面（`../content-plane`）的 loopback 契约暴露成
`resume_tailor_*` Host 工具，并注册 `resume-tailor` Skill 与 `resume-tailor` agent preset。

**隐私边界**：所有工具只回 id / hash / 标签 / 枚举 / 计数；简历/JD/改写候选正文
只存在于内容面进程，diff 只走 `resume_tailor_review` 返回的本地页。

## 结构

```
control-plane/
├─ src/index.ts         插件入口：注册工具 + skill
├─ src/http-client.ts    loopback HTTP 客户端
├─ src/tools.ts         6 个 Host 工具（extract/gap/plan/run/review/commit）
├─ src/skill.ts         resume-tailor Skill
├─ package.json         bundle manifest
├─ cordis.patch.yml     插入插件行 + agent preset 声明
└─ tsconfig.json
```

## 前置：内容面服务

先启动 Python 内容面：

```bash
cd ../content-plane
PYTHONPATH=src python3 -m resume_tailor serve --host 127.0.0.1 --port 4319
```

记下启动时打印的 token，或自行设置 `RESUME_TAILOR_TOKEN`。

## 构建（未在此仓库执行）

> ⚠️ `package.json` 里的 `devDependencies` 用 `link:` 指向 deepseek-harness 源树，
> 路径是占位（`../../../deepseek-harness`）。构建前必须把它改成你机器上实际
> `deepseek-harness` checkout 的绝对/相对路径，与 `boss-watch-agent/packages/dsh-plugin`
> 的写法一致。

```bash
pnpm install
pnpm run build          # tsdown + tsc -> lib/
pnpm run typecheck
```

## 安装到 DSH profile（有 profile 副作用，需用户确认）

用 `plugin_manager` `action: install_bundle`，`target` 设为本目录绝对路径。
它自己执行 pnpm 安装与 bundle 选择；安装后 `list_plugins` 应出现
`resume-tailor-dsh` 与 `preset-resume-tailor` 两行。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `RESUME_TAILOR_URL` | `http://127.0.0.1:4319` | 内容面 loopback 地址 |
| `RESUME_TAILOR_TOKEN` | 空 | 内容面服务令牌（需与 serve 端一致） |

## 与内容面契约

见 `../docs/CONTRACTS.md`。工具名与 HTTP method 一一对应：
`resume_tailor_extract` -> `extract`，`gap` -> `gap`，`plan` -> `plan`，
`run` -> `run`，`review` -> `review`，`commit` -> `commit`。
