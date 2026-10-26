"""L7 版本身份与哈希工具。

身份规则与 boss-watch-agent 严格对齐：

- ``content_hash = sha256(渲染字节)``
- ``resume_version_id = "resume-version:" + content_hash``
- ``local_artifact_ref = "local-resume://sha256:" + content_hash``
- ``tailor_id = "tailor:" + sha256(baseHash \\n jdHash \\n planId \\n strategy)``
- ``lineage_id = "tailor-lineage:" + sha256(tailorId \\n newVersionId)``
"""

from __future__ import annotations

import hashlib

__all__ = [
    "artifact_ref_of",
    "lineage_id_of",
    "resume_version_id_of",
    "sha256_hex",
    "tailor_id_of",
]


def sha256_hex(data: str | bytes) -> str:
    """UTF-8 字符串或字节的 SHA-256 十六进制摘要。

    Args:
        data: 待哈希的字符串或字节。

    Returns:
        64 位小写十六进制摘要。
    """
    payload = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(payload).hexdigest()


def resume_version_id_of(content_hash: str) -> str:
    """由内容哈希构造版本 id。"""
    return f"resume-version:{content_hash}"


def artifact_ref_of(content_hash: str) -> str:
    """由内容哈希构造内容寻址工件引用。"""
    return f"local-resume://sha256:{content_hash}"


def tailor_id_of(
    *,
    base_hash: str,
    jd_hash: str,
    plan_id: str,
    strategy_version: str,
) -> str:
    """由一次改写的关键输入构造 tailor id（确定、可复现）。"""
    payload = "\n".join([base_hash, jd_hash, plan_id, strategy_version])
    return "tailor:" + sha256_hex(payload)


def lineage_id_of(tailor_id: str, new_version_id: str) -> str:
    """由 tailor id 与新版本 id 构造血缘 id。"""
    return "tailor-lineage:" + sha256_hex(f"{tailor_id}\n{new_version_id}")
