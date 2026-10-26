"""模型工厂与 DeepSeek 适配器的测试。

- 工厂按 provider 名选择适配器，未知 provider 报错；
- DeepSeek 适配器用本地 mock HTTP 服务器验证 OpenAI 兼容请求格式与响应解析
  （不依赖真实 API Key）。

运行：
    PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from resume_tailor.rewrite.deepseek import DeepseekRewordModel
from resume_tailor.rewrite.models import get_reword_model
from resume_tailor.rewrite.ollama import OllamaRewordModel


class _MockHandler(BaseHTTPRequestHandler):
    """本地 mock：回传一条固定 OpenAI 兼容响应，并记录收到的请求。"""

    captured: dict = {}

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        _MockHandler.captured.update(
            {
                "path": self.path,
                "auth": self.headers.get("Authorization"),
                "payload": body,
            }
        )
        resp = json.dumps(
            {"choices": [{"message": {"content": "改写后的句子"}}]}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *args: object) -> None:  # 静音访问日志
        pass


class TestFactory(unittest.TestCase):
    """按名选择适配器。"""

    def test_provider_selection(self) -> None:
        self.assertIsInstance(get_reword_model("ollama"), OllamaRewordModel)
        self.assertIsInstance(get_reword_model("deepseek"), DeepseekRewordModel)

    def test_unknown_provider_raises(self) -> None:
        with self.assertRaises(ValueError):
            get_reword_model("bogus")


class TestDeepseekAdapter(unittest.TestCase):
    """用本地 mock 验证请求格式与响应解析。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = HTTPServer(("127.0.0.1", 0), _MockHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def setUp(self) -> None:
        _MockHandler.captured = {}

    def test_posts_openai_format_and_parses_response(self) -> None:
        model = DeepseekRewordModel(
            base_url=f"http://127.0.0.1:{self.port}",
            model="deepseek-chat",
            api_key="test-key",
        )
        out = model.reword("请改写这句")
        self.assertEqual(out, "改写后的句子")
        self.assertEqual(_MockHandler.captured["path"], "/v1/chat/completions")
        self.assertEqual(_MockHandler.captured["auth"], "Bearer test-key")
        payload = _MockHandler.captured["payload"]
        self.assertEqual(payload["model"], "deepseek-chat")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "请改写这句"}])
        self.assertFalse(payload["stream"])

    def test_missing_key_raises_before_http(self) -> None:
        saved = os.environ.pop("DEEPSEEK_API_KEY", None)
        try:
            model = DeepseekRewordModel(base_url="http://127.0.0.1:1", model="deepseek-chat")
            with self.assertRaises(ValueError):
                model.reword("x")
        finally:
            if saved is not None:
                os.environ["DEEPSEEK_API_KEY"] = saved


if __name__ == "__main__":
    unittest.main()
