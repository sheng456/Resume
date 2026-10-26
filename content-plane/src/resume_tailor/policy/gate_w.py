"""Gate W：版本落盘的审批闸门。

对齐 boss-watch-agent 的 preview/apply 两段式：预览生成短期令牌并绑定精确
内容哈希，apply 只接受未过期、未消费、哈希一致的令牌。Gate W 只授权"创建
新 ResumeVersion / 导出文件"，**不授权**投递、上传 ATS、写飞书。
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

__all__ = ["GateWPreview", "GateWService"]

_DEFAULT_TTL_SECONDS = 15 * 60


@dataclass(frozen=True)
class GateWPreview:
    """Gate W 预览令牌。"""

    preview_token: str
    expires_at: str
    tailor_id: str
    result_hash: str
    base_resume_version_id: str | None
    target_format: str
    requires_confirmation: bool = True


class GateWService:
    """内存态 Gate W 令牌服务（短生命周期）。"""

    def __init__(
        self,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._previews: dict[str, tuple[datetime, dict[str, str | None]]] = {}

    def preview(
        self,
        *,
        tailor_id: str,
        result_hash: str,
        base_resume_version_id: str | None,
        target_format: str = "markdown",
    ) -> GateWPreview:
        """签发一个预览令牌，绑定精确身份。

        Args:
            tailor_id: 本次改写的 tailor id。
            result_hash: 落盘内容哈希。
            base_resume_version_id: 基础版本 id。
            target_format: 目标格式。

        Returns:
            GateWPreview。
        """
        token = "gate-w:" + secrets.token_urlsafe(24)
        expires = self._now() + self._ttl
        self._previews[token] = (
            expires,
            {
                "tailor_id": tailor_id,
                "result_hash": result_hash,
                "base_resume_version_id": base_resume_version_id,
                "target_format": target_format,
            },
        )
        return GateWPreview(
            preview_token=token,
            expires_at=expires.isoformat(),
            tailor_id=tailor_id,
            result_hash=result_hash,
            base_resume_version_id=base_resume_version_id,
            target_format=target_format,
            requires_confirmation=True,
        )

    def apply(
        self,
        *,
        preview_token: str,
        confirmed: bool,
        tailor_id: str,
        result_hash: str,
        now: datetime | None = None,
    ) -> dict[str, str | None]:
        """消费一个预览令牌（需确认 + 未过期 + 身份一致）。

        Args:
            preview_token: 预览令牌。
            confirmed: 用户是否显式确认。
            tailor_id: 实际执行的 tailor id。
            result_hash: 实际执行的内容哈希。

        Returns:
            令牌绑定的字段（target_format 等），供调用方落盘。

        Raises:
            PermissionError: 未确认。
            ValueError: 令牌不存在 / 已过期 / 身份不一致。
        """
        if not confirmed:
            raise PermissionError("gate_w_confirmation_required")

        binding = self._previews.get(preview_token)
        if binding is None:
            raise ValueError("gate_w_preview_not_found")

        expires, fields = binding
        if (now or self._now()) >= expires:
            self._previews.pop(preview_token, None)
            raise ValueError("gate_w_approval_expired")

        if fields["tailor_id"] != tailor_id or fields["result_hash"] != result_hash:
            raise ValueError("gate_w_binding_mismatch")

        self._previews.pop(preview_token, None)  # 一次性
        return fields
