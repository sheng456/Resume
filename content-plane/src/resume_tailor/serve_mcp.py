"""MCP（Model Context Protocol）stdio server：把内容面暴露成 MCP 工具。

传输：stdio（每行一个 JSON-RPC 消息，无内嵌换行）。DSH 经 ``@deepseek-ai/dsh-mcp-client``
以 ``transport: stdio`` 接入，工具名变为 ``mcp__resume-tailor__<tool>``。

隐私边界与 ``serve.py`` 完全一致，**必须守住**：

- 任何工具结果只含 id / hash / 标签 / 枚举 / 计数，**绝不回正文**；
- 评审 diff 不写进工具结果，而是落成本地 HTML 文件、只回文件路径；
- 正文只存在于本进程内存与内容寻址工件。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .serve import TailorService
from .store.version_store import ResumeVersionStore

__all__ = ["McpServer", "PROTOCOL_VERSION", "SERVER_NAME", "run_stdio"]

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "resume-tailor"
SERVER_VERSION = "0.1.0"


def _normalize_path(p: str) -> str:
    """把模型传入的路径归一为 WSL 可读路径。

    两种常见畸形（都来自"工具跑在 Windows、字段名被改写"的假设）：

    - dsh-gitbash-shell 按字段名把 ``/mnt/...`` 改写成 ``c:/program files/git/mnt/...``
      → 先剥前缀（MCP 服务端活在 WSL，看不到 Git 安装根）；
    - Windows 盘符 ``E:\\...`` / ``E:/...`` → ``/mnt/e/...``。
    """
    p = (p or "").replace("\\", "/")
    lower = p.lower()
    if lower.startswith("c:/program files/git/"):
        rest = p[len("c:/program files/git/"):]
        p = rest if rest.startswith("/") else "/" + rest
    m = re.match(r"^([A-Za-z]):/(.*)$", p)
    if m:
        return f"/mnt/{m.group(1).lower()}/{m.group(2)}"
    return p


def _windows_path(p: str) -> str:
    """把 ``/mnt/x/...`` 转成 ``X:\\...``，方便 Windows 用户打开。"""
    m = re.match(r"^/mnt/([a-z])/(.*)$", p)
    if m:
        return f"{m.group(1).upper()}:\\{m.group(2).replace('/', chr(92))}"
    return p


def _error_code(exc: Exception) -> str:
    """把异常映射为稳定错误码（不回正文/堆栈/裸异常名）。"""
    msg = str(exc)
    if isinstance(exc, FileNotFoundError):
        return "file_not_found"
    if isinstance(exc, IsADirectoryError):
        return "not_a_file"
    if isinstance(exc, KeyError):
        return "unknown_reference"
    if msg == "tailor_supersedes_not_found":
        return "supersedes_not_found"
    if msg == "docx_invalid":
        return "invalid_docx"
    if isinstance(exc, RuntimeError):
        return "store_unavailable"
    if isinstance(exc, ValueError):
        return "invalid_request"
    return type(exc).__name__


def _tools() -> list[dict]:
    """MCP 工具清单（name / description / inputSchema）。"""
    return [
        {
            "name": "extract",
            "description": "Read a resume or JD file (PDF/DOCX/MD/TXT); returns a content-addressed doc id, extractor, confidence and counts — never the text.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "filePath": {"type": "string", "description": "Path to the file (WSL /mnt/x/... or Windows X:/...)."},
                    "file_path": {"type": "string", "description": "Deprecated alias of filePath."},
                },
                "required": ["filePath"],
            },
        },
        {
            "name": "gap",
            "description": "Diagnose which JD requirements are covered/partial/missing in a resume; returns labels and coverage only, never JD text.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "jd_doc_id": {"type": "string"},
                    "resume_doc_id": {"type": "string"},
                },
                "required": ["jd_doc_id", "resume_doc_id"],
            },
        },
        {
            "name": "plan",
            "description": "Build a rewrite plan (instruction-driven if instruction given, else JD-gap). Returns plan id, driver, intent/hash, step counts; never target text.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "jd_doc_id": {"type": "string"},
                    "resume_doc_id": {"type": "string"},
                    "instruction": {"type": "string"},
                },
                "required": ["jd_doc_id", "resume_doc_id"],
            },
        },
        {
            "name": "run",
            "description": "Run the deterministic rewrite (align + reorder). Returns changed block ids and counts; never rewritten text.",
            "inputSchema": {
                "type": "object",
                "properties": {"plan_id": {"type": "string"}},
                "required": ["plan_id"],
            },
        },
        {
            "name": "review",
            "description": "Render the rewrite diff into a LOCAL HTML file and return its path; the diff text never enters this tool result.",
            "inputSchema": {
                "type": "object",
                "properties": {"plan_id": {"type": "string"}},
                "required": ["plan_id"],
            },
        },
        {
            "name": "commit",
            "description": "Content-addressed commit of a rewritten resume (Gate W). Returns new resume version id/hash and lineage id; idempotent on same content.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                    "base_resume_version_id": {"type": "string"},
                },
                "required": ["plan_id"],
            },
        },
        {
            "name": "export",
            "description": "Render the rewritten resume as markdown into a target directory (default BOSS_WATCH_RESUME_DIR, boss-watch's resumeRoot). Returns the file name and resume-version id so boss_watch_resume_import_apply can register it; never returns text.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                    "resume_dir": {"type": "string"},
                    "display_name": {"type": "string"},
                },
                "required": ["plan_id"],
            },
        },
    ]


class McpServer:
    """MCP JSON-RPC 分发器（无 IO，可单测）。"""

    def __init__(self, service: TailorService, review_dir: str | Path | None = None) -> None:
        self._service = service
        self._review_dir = Path(review_dir) if review_dir else Path.home() / ".resume-tailor" / "reviews"

    def handle(self, message: dict) -> dict | None:
        """处理一条 JSON-RPC 消息，返回响应；通知类返回 None。"""
        method = message.get("method")
        msg_id = message.get("id")

        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return self._result(msg_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            })
        if method == "tools/list":
            return self._result(msg_id, {"tools": _tools()})
        if method == "tools/call":
            return self._call(msg_id, message.get("params") or {})
        if method == "ping":
            return self._result(msg_id, {})
        return self._error(msg_id, -32601, f"method_not_found: {method}")

    def _call(self, msg_id: int, params: dict) -> dict:
        name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            text = self._execute(name, args)
            return self._result(msg_id, {"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as exc:  # 结构化错误码，不回正文/堆栈/裸异常名
            return self._result(
                msg_id,
                {"content": [{"type": "text", "text": json.dumps({"error": _error_code(exc)}, ensure_ascii=False)}], "isError": True},
            )

    def _execute(self, name: str, args: dict) -> str:
        if name == "extract":
            path_str = args.get("filePath") or args.get("file_path") or ""
            path = Path(_normalize_path(path_str))
            data = path.read_bytes()
            return json.dumps(self._service.extract(path.name, data), ensure_ascii=False)
        if name == "gap":
            return json.dumps(self._service.gap(args["jd_doc_id"], args["resume_doc_id"]), ensure_ascii=False)
        if name == "plan":
            return json.dumps(
                self._service.plan(args["jd_doc_id"], args["resume_doc_id"], args.get("instruction")),
                ensure_ascii=False,
            )
        if name == "run":
            return json.dumps(self._service.run(args["plan_id"]), ensure_ascii=False)
        if name == "commit":
            return json.dumps(
                self._service.commit(args["plan_id"], args.get("base_resume_version_id")),
                ensure_ascii=False,
            )
        if name == "export":
            return json.dumps(
                self._service.export(
                    args["plan_id"],
                    args.get("resume_dir"),
                    args.get("display_name"),
                ),
                ensure_ascii=False,
            )
        if name == "review":
            return self._review(args["plan_id"])
        raise KeyError(name)

    def _review(self, plan_id: str) -> str:
        html = self._service.review_html(plan_id)
        self._review_dir.mkdir(parents=True, exist_ok=True)
        safe_name = plan_id.replace(":", "_") + ".html"
        path = self._review_dir / safe_name
        path.write_text(html, encoding="utf-8")
        return json.dumps(
            {"review_path": _windows_path(str(path))}, ensure_ascii=False
        )

    @staticmethod
    def _result(msg_id: int, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id: int, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def run_stdio() -> None:
    """从 stdin 读行分隔 JSON-RPC，向 stdout 写响应（MCP stdio 传输）。"""
    home = Path(os.environ.get("RESUME_TAILOR_HOME", Path.home() / ".resume-tailor"))
    store = ResumeVersionStore(
        db_path=str(home / "versions.sqlite3"),
        artifact_root=str(home / "artifacts"),
    )
    service = TailorService(token=os.environ.get("RESUME_TAILOR_TOKEN", ""), store=store)
    server = McpServer(service, review_dir=home / "reviews")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = server.handle(message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    run_stdio()
