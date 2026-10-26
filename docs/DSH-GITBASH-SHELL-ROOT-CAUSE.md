# dsh-gitbash-shell 根因记录（暂不修改该插件）

> 这是 MCP 接入时发现的一个**跨插件**缺陷，记录在案供后续排期。当前已用项目侧
> 兼容绕过，`dsh-gitbash-shell` 插件本身**未改动**。

## 现象

MCP 工具 `mcp__resume-tailor__extract` 收不到任何**绝对路径**：

| 模型传入 | 服务端实际收到 |
| --- | --- |
| `/etc/hostname` | `c:/program files/git/etc/hostname` |
| `/mnt/e/python/…` | `c:/program files/git/mnt/e/python/…` |
| `/home/sheng/.bashrc` | `c:/program files/git/home/sheng/.bashrc` |
| `E:\python\…` | 原样通过（但 WSL 里的 Python 打不开 Windows 路径） |

相对路径（如 `../fixtures/single-col.pdf`）不受影响。

## 根因

`dsh-gitbash-shell`（profile 插件 `0.43.2`）有一个**全局 `tools/execute` 包装器**，
它按**字段名**（`file_path` / `path` / `workdir` / `root`，见插件 `src/index.js` 约 966 行的
`TRANSLATABLE_PATH_FIELDS`）对**所有工具**的参数做 MSYS→盘符改写，并把 `/etc`、`/usr`、
`/home`、`/mnt` 按 **Git 安装根**解析（`c:/program files/git/...`）。

这个假设只在「工具进程跑在 Windows 主机上」时成立；**MCP 服务端进程活在 WSL 里**，
于是它只能看见 `c:/program files/git/...` 这种不存在的路径 → 静默 `FileNotFoundError`，
用户/模型都看不出原因。

**影响面**：所有"服务端不在 Windows 文件系统里"的 MCP 服务（本 bundle 用
`wsl -e bash -lc … python3 -m resume_tailor mcp` 起的）都会中招。

## 当前绕过（项目侧，已生效）

1. **参数改名** `file_path` → `filePath`（避开字段名改写；`file_path` 仍作为 deprecated
   别名兼容旧客户端）。
2. **服务端归一**（`serve_mcp.py::_normalize_path`）：
   - 剥掉 `c:/program files/git/` 前缀；
   - Windows 盘符 `X:\…` / `X:/…` → `/mnt/x/…`。

实测四种路径写法（`/mnt/e/…`、`E:\…`、相对路径、被改写后的 `c:/program files/git/mnt/e/…`）
全部打通。

## 待排期的根因修法（需你确认，影响所有会话）

在 `dsh-gitbash-shell` 侧给 **`mcp__*` 工具**（或按 `serverName`）豁免字段名改写，这样
其它跑在 WSL 里的 MCP 服务也一并受益。改动点是第三方 profile 插件，风险面是"所有会话
的路径改写行为"，所以**暂时不动**，等确认后再动。
