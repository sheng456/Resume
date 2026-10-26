"""L7 落盘编排：渲染 -> 哈希 -> 版本 -> 血缘。

把评审后的最终简历渲染成稳定文本、算内容哈希、幂等落盘为新 ``ResumeVersion``，
并写一条血缘，把新版本、基础版本、JD、计划、模型串起来。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from ..domain.contracts import ResumeBlock, ResumeVersion, RewrittenBlock, TailorLineage
from ..render.markdown import render_markdown
from .identity import (
    artifact_ref_of,
    lineage_id_of,
    resume_version_id_of,
    sha256_hex,
    tailor_id_of,
)
from .version_store import ResumeVersionStore

__all__ = ["CommitResult", "commit_resume"]


@dataclass(frozen=True)
class CommitResult:
    """落盘结果。"""

    resume_version: ResumeVersion
    lineage: TailorLineage
    reused: bool


def commit_resume(
    *,
    store: ResumeVersionStore,
    final: Sequence[RewrittenBlock],
    blocks: Sequence[ResumeBlock],
    base_resume_version_id: str | None,
    plan_id: str,
    jd_content_hash: str,
    strategy_version: str,
    mode: str,
    model_ref: str,
    display_name: str | None = None,
    now: Callable[[], datetime] | None = None,
) -> CommitResult:
    """渲染并落盘一份新简历版本，附血缘。

    Args:
        store: 版本存储。
        final: 评审后的最终块序列（最终顺序）。
        blocks: 原简历块（提供结构）。
        base_resume_version_id: 基础版本 id；None 表示无基础（首版）。
        plan_id: 驱动本次改写的计划 id。
        jd_content_hash: 目标 JD 的内容哈希。
        strategy_version: 策略版本。
        mode: 改写模式（local / cloud / rule）。
        model_ref: 模型标识（如 ``ollama:qwen2.5-coder:7b``）。
        display_name: 新版本显示名；缺省由哈希派生。
        now: 时钟注入（测试用）。

    Returns:
        CommitResult。

    Raises:
        ValueError: ``base_resume_version_id`` 指向不存在的版本。
    """
    clock = now or (lambda: datetime.now(timezone.utc))

    base_version = store.get(base_resume_version_id) if base_resume_version_id else None
    if base_resume_version_id is not None and base_version is None:
        raise ValueError("tailor_supersedes_not_found")

    content_bytes = render_markdown(final, blocks).encode("utf-8")
    content_hash = sha256_hex(content_bytes)
    resume_version_id = resume_version_id_of(content_hash)
    artifact_ref = artifact_ref_of(content_hash)
    created_at = clock().isoformat()

    version = ResumeVersion(
        resume_version_id=resume_version_id,
        display_name=display_name or f"tailored-{content_hash[:8]}",
        local_artifact_ref=artifact_ref,
        content_hash=content_hash,
        media_type="text/markdown",
        byte_size=len(content_bytes),
        created_at=created_at,
        supersedes_resume_version_id=base_resume_version_id,
    )
    saved = store.save_version(version, content_bytes)

    base_hash = base_version.content_hash if base_version else ""
    tailor_id = tailor_id_of(
        base_hash=base_hash,
        jd_hash=jd_content_hash,
        plan_id=plan_id,
        strategy_version=strategy_version,
    )
    lineage_id = lineage_id_of(tailor_id, saved.version.resume_version_id)
    lineage = TailorLineage(
        lineage_id=lineage_id,
        new_resume_version_id=saved.version.resume_version_id,
        base_resume_version_id=base_resume_version_id,
        tailor_id=tailor_id,
        plan_id=plan_id,
        jd_content_hash=jd_content_hash,
        mode=mode,
        model_ref=model_ref,
        strategy_version=strategy_version,
        created_at=created_at,
    )
    store.save_lineage(lineage)

    return CommitResult(saved.version, lineage, saved.reused)
