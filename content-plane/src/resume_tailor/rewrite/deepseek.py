"""DeepSeek（OpenAI 兼容）改写模型适配器。

把 DeepSeek 的 OpenAI 兼容接口（``/v1/chat/completions``）包装成
``RewordModel``，与 ``ollama.py`` 对称，二者可互换。

API Key 从 ``DEEPSEEK_API_KEY``（或构造参数）读取；缺失时抛 ``ValueError``，
由 ``reword_block`` 捕获并 fail-closed。只用标准库 ``urllib``。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

__all__ = ["DeepseekRewordModel"]

# 默认值，可经环境变量覆盖（DEEPSEEK_BASE_URL / DEEPSEEK_MODEL / DEEPSEEK_API_KEY）。
_DEFAULT_BASE_URL = "https://api.deepseek.com"
_DEFAULT_MODEL = "deepseek-chat"


class DeepseekRewordModel:
    """经 DeepSeek OpenAI 兼容接口做单句改写。

    Attributes:
        base_url: 服务地址。
        model: 模型名。
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout_s: int = 180,
    ) -> None:
        self._base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL", _DEFAULT_BASE_URL)).rstrip("/")
        self._model = model or os.environ.get("DEEPSEEK_MODEL", _DEFAULT_MODEL)
        self._api_key = (api_key or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
        self._timeout_s = timeout_s

    def reword(self, prompt: str) -> str:
        """调用 DeepSeek，返回改写文本。

        Args:
            prompt: 由 ``build_reword_prompt`` 构建的提示词。

        Returns:
            模型返回的文本。

        Raises:
            ValueError: API Key 缺失。
            urllib.error.URLError: 网络/服务不可达（由上层 fail-closed）。
        """
        if not self._api_key:
            raise ValueError("deepseek_api_key_missing")

        payload = json.dumps(
            {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "stream": False,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            f"{self._base_url}/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))

        choices = data.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "")
