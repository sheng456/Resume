# resume-tailor MCP bundle（方案 D）

配置型 bundle：把本地 `resume-tailor` 内容面（Python）以 **MCP stdio** 接入 DSH。
安装后工具以 `mcp__resume-tailor__<tool>` 暴露（`extract / gap / plan / run / review / commit`）。

## 前置

- WSL 里有 Python 3.12 + 内容面源码在 `/mnt/e/python/代码/resume/content-plane`。
- 内容面零第三方依赖（可选 pypdf 用于 PDF 提取，缺失时如实报 `pdf_extractor_unavailable`）。

## 安装（有 profile 副作用，需确认）

用 `plugin_manager`，`action: install_bundle`，`target` 设为本目录绝对路径。

## 传输与命令

`cordis.patch.yml` 用 `transport: stdio`，`command: wsl` 在 WSL 里跑
`python -m resume_tailor mcp`（stdin/stdout 经 WSL 转发，无常驻 HTTP 服务）。

若想用 Windows 原生 Python（内容面是 stdlib 实现，PDF 之外无需依赖），把
`command/args` 换成：

```yaml
command: python
args: ['-m', 'resume_tailor', 'mcp']
env:
  PYTHONPATH: 'E:\\python\\代码\\resume\\content-plane\\src'
```

## 路径约定（重要）

`extract` 工具收 `file_path`，必须能被 WSL 里的 Python 读取。Windows 路径
`E:\...` / `C:\...` 要转成 `/mnt/e/...` / `/mnt/c/...` 再传。

## 持久化

`run_stdio` 默认把版本库/工件写到 WSL 的 `~/.resume-tailor`。若要落到 Windows
可见路径（评审 HTML、落盘版本），在 `args` 的命令里内联
`RESUME_TAILOR_HOME=/mnt/c/Users/<你>/AppData/Local/resume-tailor`：

```yaml
args:
  - '-e'
  - 'bash'
  - '-lc'
  - 'cd /mnt/e/python/代码/resume/content-plane && RESUME_TAILOR_HOME=/mnt/c/Users/<你>/AppData/Local/resume-tailor PYTHONPATH=src python3 -m resume_tailor mcp'
```

## 隐私边界（与 serve 一致，测试锁死）

- 任何工具结果只含 id/hash/标签/枚举/计数，不回简历/JD 正文；
- `review` 把 diff 写成本地 HTML 文件、只回文件路径，正文不进 transcript；
- 见 `../docs/CONTRACTS.md` 与 `content-plane/src/resume_tailor/serve_mcp.py`。
