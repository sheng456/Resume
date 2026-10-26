"""Ollama 本地改写模型适配器。

把 Ollama 的 HTTP 接口包装成 ``RewordModel``，使 reword 门禁能接上真模型。
默认指向 WSL 视角下的宿主机（``http://172.27.176.1:11434``，与 `job` 仓库的
``.env.example`` 一致）。

只用标准库 ``urllib``，不引入第三方依赖。模型不可达时**抛出异常**——由
``reword_block`` 捕获并 fail-closed（回退原文），符合本项目"优雅降级"约定。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

__all__ = ["OllamaRewordModel"]

# 默认值，可经环境变量覆盖（OLLAMA_HOST / OLLAMA_CHAT_MODEL），不在代码里写死。
_DEFAULT_BASE_URL = "http://172.27.176.1:11434"
_DEFAULT_MODEL = "qwen2.5-coder:7b"


class OllamaRewordModel:
    """经 Ollama `/api/generate` 做单句改写。

    Attributes:
        base_url: Ollama 服务地址。
        model: 模型名。
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: int = 180,
    ) -> None:
        self._base_url = (base_url or os.environ.get("OLLAMA_HOST", _DEFAULT_BASE_URL)).rstrip("/")
        self._model = model or os.environ.get("OLLAMA_CHAT_MODEL", _DEFAULT_MODEL)
        self._timeout_s = timeout_s

    def reword(self, prompt: str) -> str:
        """调用 Ollama，返回改写文本。

        Args:
            prompt: 由 ``build_reword_prompt`` 构建的提示词。

        Returns:
            Ollama 返回的响应文本。

        Raises:
            urllib.error.URLError: 模型不可达时抛出（由上层 fail-closed）。
        """
        payload = json.dumps(
            {
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 512},
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            f"{self._base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("response", "")
