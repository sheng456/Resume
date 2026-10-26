"""改写模型的插件式选择。

按 provider 名返回对应的 ``RewordModel``；具体配置（地址/模型名/密钥）由各
适配器从环境变量读取，不在本层写死。后续接新模型（其他云端 / 其他本地推理
服务）只需：写一个实现 ``RewordModel`` 协议的适配器，再在此登记一行。

这也是"整个项目做成插件"在模型层的预留接缝——上层只依赖 ``RewordModel``
协议与 ``get_reword_model``，不依赖任何具体 provider。
"""

from __future__ import annotations

import os

from .deepseek import DeepseekRewordModel
from .ollama import OllamaRewordModel
from .reword import RewordModel

__all__ = ["get_reword_model"]

#: provider 名 -> 适配器构造。新增 provider 在此登记即可。
_REGISTRY: dict[str, type[RewordModel]] = {
    "ollama": OllamaRewordModel,
    "deepseek": DeepseekRewordModel,
}


def get_reword_model(provider: str | None = None) -> RewordModel:
    """按 provider 名返回改写模型。

    provider 缺省时读环境变量 ``RESUME_REWORD_PROVIDER``，仍缺省则用 ``ollama``。

    Args:
        provider: provider 名（``ollama`` / ``deepseek``）。

    Returns:
        对应适配器实例。

    Raises:
        ValueError: 未知 provider。
    """
    name = (provider or os.environ.get("RESUME_REWORD_PROVIDER", "ollama")).strip().lower()
    if name not in _REGISTRY:
        raise ValueError(f"unknown_reword_provider:{name}")
    return _REGISTRY[name]()
