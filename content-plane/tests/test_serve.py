"""P0 内容面服务（serve）与隐私不变量的测试。

覆盖：extract/gap/plan/run/commit 全链路、评审本地页、HTTP 层、以及**正文不泄漏**
这一硬约束（任何工具结果里都不出现简历/JD 正文）。

运行：
    PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from resume_tailor.serve import TailorService, _jd_requirements, make_server
from resume_tailor.store.version_store import ResumeVersionStore

RESUME_TEXT = """张明
求职意向：后端开发工程师
工作经历
· 负责订单系统服务拆分，接口 P99 从 320ms 降至 90ms
· 主导订单表分库分表改造，单表数据量从 8000 万降至 500 万
专业技能
Java、Spring Boot、MySQL、Redis、Kafka"""

JD_TEXT = """熟悉微服务架构
熟悉 Java、Spring Boot"""

# 不得出现在任何工具结果里的正文片段
RESUME_LEAKS = ("张明", "负责订单系统服务拆分", "8000 万")
JD_LEAKS = ("熟悉微服务", "熟悉 Java")


def _service() -> TailorService:
    tmp = tempfile.mkdtemp()
    store = ResumeVersionStore(db_path=":memory:", artifact_root=str(Path(tmp) / "artifacts"))
    return TailorService(token="test-token", store=store)


def _assert_no_leak(testcase: unittest.TestCase, payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    for leak in RESUME_LEAKS + JD_LEAKS:
        testcase.assertNotIn(leak, text)


class TestJdRequirements(unittest.TestCase):
    """P1：JD 切分（BOSS 抓的 JD 常是单行）。"""

    def test_single_line_jd_splits_by_sentence(self) -> None:
        jd = ("熟悉 Python 工具包设计与实现，并能与现有产品代码结合。"
              "熟悉信息抽取、实体匹配、模型集成。熟悉正则表达式。"
              "熟悉 Django、Flask、Tornado 等 Web 框架。")
        reqs = _jd_requirements(jd)
        self.assertGreater(len(reqs), 1)
        self.assertTrue(any("信息抽取" in r.text for r in reqs))

    def test_short_line_is_single_requirement(self) -> None:
        reqs = _jd_requirements("熟悉 Java")
        self.assertEqual(len(reqs), 1)


class TestServiceFlow(unittest.TestCase):
    """extract → gap → plan → run → commit 全链路。"""

    def test_full_flow_and_no_leak(self) -> None:
        svc = _service()
        jd = svc.extract("jd.txt", JD_TEXT.encode("utf-8"))
        resume = svc.extract("resume.txt", RESUME_TEXT.encode("utf-8"))
        self.assertEqual(jd["confidence"], "high")
        self.assertEqual(resume["confidence"], "high")
        _assert_no_leak(self, jd)
        _assert_no_leak(self, resume)

        gap = svc.gap(jd["doc_id"], resume["doc_id"])
        _assert_no_leak(self, gap)
        self.assertEqual(gap["requirement_count"], 2)

        plan = svc.plan(jd["doc_id"], resume["doc_id"])
        _assert_no_leak(self, plan)
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["driver"], "jd_gap")

        run = svc.run(plan["plan_id"])
        _assert_no_leak(self, run)
        self.assertGreater(run["changed_count"], 0)  # 服务拆分→微服务 对齐

        commit = svc.commit(plan["plan_id"])
        _assert_no_leak(self, commit)
        self.assertTrue(commit["resume_version_id"].startswith("resume-version:"))
        self.assertTrue(commit["lineage_id"].startswith("tailor-lineage:"))

    def test_instruction_plan_driver(self) -> None:
        svc = _service()
        jd = svc.extract("jd.txt", JD_TEXT.encode())
        resume = svc.extract("resume.txt", RESUME_TEXT.encode())
        plan = svc.plan(jd["doc_id"], resume["doc_id"], instruction="把工作经历写得更专业一些")
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["driver"], "instruction")
        self.assertIsNotNone(plan["instruction_hash"])

    def test_gap_excludes_jd_label(self) -> None:
        svc = _service()
        jd = svc.extract("jd.txt", JD_TEXT.encode())
        resume = svc.extract("resume.txt", RESUME_TEXT.encode())
        gap = svc.gap(jd["doc_id"], resume["doc_id"])
        self.assertNotIn("label", json.dumps(gap, ensure_ascii=False))

    def test_glued_signal_does_not_leak_run_text(self) -> None:
        """H1 回归：粘连信号的 detail 只回数量，不回粘连 run 原文。"""
        svc = _service()
        result = svc.extract("resume.txt", "负责订单系统 JavaSpring BootMySQLRedisKafka 改造".encode())
        payload = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("JavaSpring", payload)
        self.assertNotIn("BootMySQLRedisKafka", payload)
        self.assertEqual(result["confidence"], "low")


class TestReviewPage(unittest.TestCase):
    """评审 diff 只在本地页，不进工具结果。"""

    def test_review_html_local_only(self) -> None:
        svc = _service()
        jd = svc.extract("jd.txt", JD_TEXT.encode())
        resume = svc.extract("resume.txt", RESUME_TEXT.encode())
        plan = svc.plan(jd["doc_id"], resume["doc_id"])
        svc.run(plan["plan_id"])
        html = svc.review_html(plan["plan_id"])
        self.assertIn("服务拆分", html)  # diff 文本在本地页
        # 但 run/commit 结果里没有正文
        self.assertNotIn("服务拆分", json.dumps(svc.run(plan["plan_id"]), ensure_ascii=False))


class TestHttpLayer(unittest.TestCase):
    """HTTP 层 + 令牌鉴权。"""

    def test_http_roundtrip_and_unauthorized(self) -> None:
        svc = _service()
        server = make_server(svc, "127.0.0.1", 0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # 未授权
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                _post(port, {"method": "extract", "params": {"filename": "r.txt", "data_b64": ""}, "token": "wrong"})
            self.assertEqual(ctx.exception.code, 401)

            # 授权 + 提取
            b64 = base64.b64encode(RESUME_TEXT.encode("utf-8")).decode()
            resp = _post(port, {"method": "extract", "params": {"filename": "r.txt", "data_b64": b64}, "token": "test-token"})
            self.assertTrue(resp["ok"])
            _assert_no_leak(self, resp)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_review_get_requires_token(self) -> None:
        """H2 回归：评审页（最敏感正文端点）必须校验一次性令牌。"""
        svc = _service()
        jd = svc.extract("jd.txt", JD_TEXT.encode())
        resume = svc.extract("resume.txt", RESUME_TEXT.encode())
        plan = svc.plan(jd["doc_id"], resume["doc_id"])
        svc.run(plan["plan_id"])
        review = svc.review(plan["plan_id"])

        server = make_server(svc, "127.0.0.1", 0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            path_no_token = review["review_url"].split("?")[0]
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{port}{path_no_token}")
            self.assertEqual(ctx.exception.code, 401)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{review['review_url']}") as resp:
                html = resp.read().decode("utf-8")
            self.assertIn("服务拆分", html)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_commit_through_threaded_server(self) -> None:
        """线程安全回归：commit 经 ThreadingHTTPServer（请求线程）用文件库必须成功。

        复现过 sqlite3.ProgrammingError——连接在主线程创建、请求在新线程使用，
        未加 check_same_thread=False 时直接 500。
        """
        tmp = tempfile.mkdtemp()
        store = ResumeVersionStore(
            db_path=str(Path(tmp) / "v.sqlite3"), artifact_root=str(Path(tmp) / "artifacts")
        )
        svc = TailorService(token="test-token", store=store)
        jd = svc.extract("jd.txt", JD_TEXT.encode())
        resume = svc.extract("resume.txt", RESUME_TEXT.encode())
        plan = svc.plan(jd["doc_id"], resume["doc_id"])
        svc.run(plan["plan_id"])

        server = make_server(svc, "127.0.0.1", 0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            resp = _post(port, {"method": "commit", "params": {"plan_id": plan["plan_id"]}, "token": "test-token"})
            self.assertTrue(resp["ok"], resp)
            self.assertTrue(resp["result"]["resume_version_id"].startswith("resume-version:"))
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            store.close()

    def test_export_writes_markdown_for_boss_watch(self) -> None:
        """#6：export 渲染 markdown 到目标目录，身份与 boss-watch 对齐。"""
        svc = _service()
        jd = svc.extract("jd.txt", JD_TEXT.encode())
        resume = svc.extract("resume.txt", RESUME_TEXT.encode())
        plan = svc.plan(jd["doc_id"], resume["doc_id"])
        svc.run(plan["plan_id"])
        out_dir = tempfile.mkdtemp()
        result = svc.export(plan["plan_id"], resume_dir=out_dir, display_name="tailored-test")
        path = Path(out_dir) / "tailored-test.md"
        self.assertTrue(path.exists())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), result["content_hash"])
        self.assertEqual(result["resume_version_id"], "resume-version:" + result["content_hash"])


def _post(port: int, payload: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
