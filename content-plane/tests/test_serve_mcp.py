"""MCP stdio server 的测试：协议分发 + 隐私不变量 + 子进程往返。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from resume_tailor.serve import TailorService
from resume_tailor.serve_mcp import McpServer, _normalize_path
from resume_tailor.store.version_store import ResumeVersionStore

RESUME_TEXT = "张明\n工作经历\n· 负责订单系统服务拆分，接口 P99 从 320ms 降至 90ms\n专业技能\nJava"
JD_TEXT = "熟悉微服务架构\n熟悉 Java"


def _server() -> tuple[McpServer, TailorService, str]:
    tmp = tempfile.mkdtemp()
    store = ResumeVersionStore(db_path=":memory:", artifact_root=str(Path(tmp) / "artifacts"))
    service = TailorService(token="t", store=store)
    return McpServer(service, review_dir=str(Path(tmp) / "reviews")), service, tmp


def _call(server: McpServer, name: str, args: dict) -> str:
    resp = server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": name, "arguments": args}})
    return resp["result"]["content"][0]["text"]


class TestPathNormalization(unittest.TestCase):
    """P0：路径归一（Windows 盘符 / git-bash 前缀）。"""

    def test_windows_drive(self) -> None:
        self.assertEqual(_normalize_path("E:\\python\\foo.pdf"), "/mnt/e/python/foo.pdf")
        self.assertEqual(_normalize_path("E:/python/foo.pdf"), "/mnt/e/python/foo.pdf")

    def test_git_prefix_strip(self) -> None:
        self.assertEqual(_normalize_path("c:/program files/git/mnt/e/python/foo.pdf"), "/mnt/e/python/foo.pdf")
        self.assertEqual(_normalize_path("c:/Program Files/Git/etc/hostname"), "/etc/hostname")

    def test_wsl_path_untouched(self) -> None:
        self.assertEqual(_normalize_path("/mnt/e/python/foo.pdf"), "/mnt/e/python/foo.pdf")

    def test_extract_accepts_legacy_file_path_alias(self) -> None:
        """旧字段名 file_path 仍可调用（破坏性兼容）。"""
        server, _, tmp = _server()
        p = Path(tmp) / "r.txt"
        p.write_text("张明\n工作经历\n· 负责订单系统服务拆分", encoding="utf-8")
        res = _call(server, "extract", {"file_path": str(p)})
        self.assertIn("doc_id", res)


class TestMcpProtocol(unittest.TestCase):
    """协议分发。"""

    def test_initialize(self) -> None:
        server, _, _ = _server()
        resp = server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})
        self.assertEqual(resp["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(resp["result"]["serverInfo"]["name"], "resume-tailor")

    def test_tools_list_has_seven(self) -> None:
        server, _, _ = _server()
        resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertEqual(
            names, {"extract", "gap", "plan", "run", "review", "commit", "export"}
        )

    def test_ping(self) -> None:
        server, _, _ = _server()
        resp = server.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        self.assertEqual(resp["result"], {})

    def test_notification_returns_none(self) -> None:
        server, _, _ = _server()
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))


class TestPrivacy(unittest.TestCase):
    """工具结果不回正文。"""

    def test_full_flow_leaks_no_body(self) -> None:
        server, _, tmp = _server()
        r_path = Path(tmp) / "resume.txt"
        j_path = Path(tmp) / "jd.txt"
        r_path.write_text(RESUME_TEXT, encoding="utf-8")
        j_path.write_text(JD_TEXT, encoding="utf-8")

        extract = _call(server, "extract", {"filePath": str(r_path)})
        self.assertNotIn("张明", extract)
        self.assertNotIn("服务拆分", extract)
        jd_extract = _call(server, "extract", {"filePath": str(j_path)})
        r_doc = json.loads(extract)["doc_id"]
        j_doc = json.loads(jd_extract)["doc_id"]

        for payload in (
            _call(server, "gap", {"jd_doc_id": j_doc, "resume_doc_id": r_doc}),
            _call(server, "plan", {"jd_doc_id": j_doc, "resume_doc_id": r_doc}),
        ):
            self.assertNotIn("熟悉微服务", payload)
            self.assertNotIn("张明", payload)

        plan = json.loads(_call(server, "plan", {"jd_doc_id": j_doc, "resume_doc_id": r_doc}))
        run = _call(server, "run", {"plan_id": plan["plan_id"]})
        self.assertNotIn("服务拆分", run)
        self.assertNotIn("90ms", run)

        review = _call(server, "review", {"plan_id": plan["plan_id"]})
        review_path = json.loads(review)["review_path"]
        # diff 正文只落在本地 HTML 文件里，工具结果只回路径
        self.assertTrue(Path(review_path).exists())
        self.assertIn("服务拆分", Path(review_path).read_text(encoding="utf-8"))

        commit = _call(server, "commit", {"plan_id": plan["plan_id"]})
        self.assertTrue(json.loads(commit)["resume_version_id"].startswith("resume-version:"))


class TestStdioRoundTrip(unittest.TestCase):
    """子进程 stdio 往返。"""

    def test_initialize_and_list_over_stdio(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = "src"
        env["RESUME_TAILOR_HOME"] = tempfile.mkdtemp()
        proc = subprocess.Popen(
            [sys.executable, "-m", "resume_tailor", "mcp"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=True,
        )
        try:
            assert proc.stdin and proc.stdout
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}) + "\n")
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n")
            proc.stdin.flush()
            first = json.loads(proc.stdout.readline())
            second = json.loads(proc.stdout.readline())
            self.assertEqual(first["id"], 0)
            self.assertEqual(first["result"]["serverInfo"]["name"], "resume-tailor")
            self.assertEqual(second["id"], 1)
            self.assertEqual(len(second["result"]["tools"]), 7)
        finally:
            proc.stdin.close()
            proc.stdout.close()
            proc.stderr.close()
            proc.terminate()
            proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
