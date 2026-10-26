"""L7 版本落盘、血缘与 Gate W 的测试。

覆盖：渲染确定性、内容哈希身份、幂等复用、supersedes 校验、血缘、Gate W
的确认/过期/身份绑定/一次性。

运行：
    PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from resume_tailor.domain.contracts import BlockKind, ResumeBlock, RewrittenBlock, Section
from resume_tailor.policy.gate_w import GateWService
from resume_tailor.render.markdown import render_markdown
from resume_tailor.store.identity import resume_version_id_of, sha256_hex
from resume_tailor.store.version import commit_resume
from resume_tailor.store.version_store import ResumeVersionStore

BLOCKS = (
    ResumeBlock("block:h", Section.WORK, BlockKind.HEADING, "工作经历", True),
    ResumeBlock("block:1", Section.WORK, BlockKind.BULLET, "负责订单系统服务拆分", False),
    ResumeBlock("block:2", Section.WORK, BlockKind.BULLET, "主导订单表分库分表改造", False),
)

FINAL = (
    RewrittenBlock("block:h", "工作经历", "工作经历"),
    RewrittenBlock("block:1", "负责订单系统服务拆分", "负责订单系统微服务"),
    RewrittenBlock("block:2", "主导订单表分库分表改造", "主导订单表分库分表改造"),
)


def _store() -> tuple[ResumeVersionStore, str]:
    tmp = tempfile.mkdtemp()
    store = ResumeVersionStore(db_path=str(Path(tmp) / "store.db"), artifact_root=str(Path(tmp) / "artifacts"))
    return store, tmp


class TestRender(unittest.TestCase):
    """渲染确定性。"""

    def test_render_markdown_is_deterministic_and_structured(self) -> None:
        md = render_markdown(FINAL, BLOCKS)
        self.assertIn("## 工作经历", md)
        self.assertIn("- 负责订单系统微服务", md)
        self.assertEqual(md, render_markdown(FINAL, BLOCKS))


class TestIdentity(unittest.TestCase):
    """身份规则。"""

    def test_resume_version_id_format(self) -> None:
        h = sha256_hex(b"x")
        self.assertEqual(resume_version_id_of(h), f"resume-version:{h}")
        self.assertEqual(len(h), 64)


class TestCommit(unittest.TestCase):
    """落盘 + 幂等 + supersedes + 血缘。"""

    def test_commit_creates_version_and_lineage(self) -> None:
        store, _ = _store()
        try:
            result = commit_resume(
                store=store,
                final=FINAL,
                blocks=BLOCKS,
                base_resume_version_id=None,
                plan_id="tailor-plan:abc",
                jd_content_hash="j" * 64,
                strategy_version="resume-tailor-plan-v1",
                mode="local",
                model_ref="ollama:qwen2.5-coder:7b",
            )
            self.assertFalse(result.reused)
            self.assertTrue(result.resume_version.resume_version_id.startswith("resume-version:"))
            self.assertEqual(store.count(), 1)
            # 血缘
            lineage = store.get_lineage(result.lineage.lineage_id)
            self.assertIsNotNone(lineage)
            self.assertEqual(lineage.new_resume_version_id, result.resume_version.resume_version_id)
            # 工件文件已写
            artifact = Path(_artifact_root(store)) / f"{result.resume_version.content_hash}.md"
            self.assertTrue(artifact.exists())
        finally:
            store.close()

    def test_commit_is_idempotent_on_same_content(self) -> None:
        store, _ = _store()
        try:
            kwargs = dict(
                store=store, final=FINAL, blocks=BLOCKS, base_resume_version_id=None,
                plan_id="tailor-plan:abc", jd_content_hash="j" * 64,
                strategy_version="v1", mode="local", model_ref="ollama:qwen",
            )
            first = commit_resume(**kwargs)
            second = commit_resume(**kwargs)
            self.assertTrue(second.reused)
            self.assertEqual(first.resume_version.resume_version_id, second.resume_version.resume_version_id)
            self.assertEqual(store.count(), 1)
        finally:
            store.close()

    def test_commit_rejects_missing_supersedes(self) -> None:
        store, _ = _store()
        try:
            with self.assertRaises(ValueError):
                commit_resume(
                    store=store, final=FINAL, blocks=BLOCKS,
                    base_resume_version_id="resume-version:does-not-exist",
                    plan_id="p", jd_content_hash="j" * 64, strategy_version="v",
                    mode="local", model_ref="m",
                )
        finally:
            store.close()

    def test_supersedes_points_to_base(self) -> None:
        store, _ = _store()
        try:
            first = commit_resume(
                store=store, final=FINAL, blocks=BLOCKS, base_resume_version_id=None,
                plan_id="p1", jd_content_hash="j" * 64, strategy_version="v",
                mode="local", model_ref="m",
            )
            second = commit_resume(
                store=store,
                final=(FINAL[0], RewrittenBlock("block:1", "负责订单系统服务拆分", "负责订单系统微服务，性能翻倍"), FINAL[2]),
                blocks=BLOCKS,
                base_resume_version_id=first.resume_version.resume_version_id,
                plan_id="p2", jd_content_hash="j" * 64, strategy_version="v",
                mode="local", model_ref="m",
            )
            self.assertEqual(second.resume_version.supersedes_resume_version_id, first.resume_version.resume_version_id)
        finally:
            store.close()

    def test_multiple_lineages_for_same_version(self) -> None:
        """同一内容经不同计划 commit → 保留多条血缘（不再被 UNIQUE 静默丢弃）。"""
        store, _ = _store()
        try:
            a = commit_resume(
                store=store, final=FINAL, blocks=BLOCKS, base_resume_version_id=None,
                plan_id="p1", jd_content_hash="j" * 64, strategy_version="v",
                mode="local", model_ref="m",
            )
            b = commit_resume(
                store=store, final=FINAL, blocks=BLOCKS, base_resume_version_id=None,
                plan_id="p2", jd_content_hash="j" * 64, strategy_version="v",
                mode="local", model_ref="m",
            )
            self.assertEqual(a.resume_version.resume_version_id, b.resume_version.resume_version_id)
            self.assertNotEqual(a.lineage.lineage_id, b.lineage.lineage_id)
            self.assertIsNotNone(store.get_lineage(a.lineage.lineage_id))
            self.assertIsNotNone(store.get_lineage(b.lineage.lineage_id))
        finally:
            store.close()


class TestGateW(unittest.TestCase):
    """Gate W 审批闸门。"""

    def _svc(self, base: datetime) -> tuple[GateWService, datetime]:
        state = {"now": base}

        def clock() -> datetime:
            return state["now"]

        return GateWService(ttl_seconds=900, now=clock), state  # type: ignore[arg-type]

    def test_apply_requires_confirmation(self) -> None:
        svc, _ = self._svc(datetime(2026, 1, 1, tzinfo=timezone.utc))
        preview = svc.preview(tailor_id="t", result_hash="h" * 64, base_resume_version_id=None)
        with self.assertRaises(PermissionError):
            svc.apply(preview_token=preview.preview_token, confirmed=False, tailor_id="t", result_hash="h" * 64)

    def test_apply_requires_matching_binding(self) -> None:
        svc, _ = self._svc(datetime(2026, 1, 1, tzinfo=timezone.utc))
        preview = svc.preview(tailor_id="t", result_hash="h" * 64, base_resume_version_id=None)
        with self.assertRaises(ValueError):
            svc.apply(preview_token=preview.preview_token, confirmed=True, tailor_id="t", result_hash="o" * 64)

    def test_apply_is_one_shot(self) -> None:
        svc, _ = self._svc(datetime(2026, 1, 1, tzinfo=timezone.utc))
        preview = svc.preview(tailor_id="t", result_hash="h" * 64, base_resume_version_id=None)
        svc.apply(preview_token=preview.preview_token, confirmed=True, tailor_id="t", result_hash="h" * 64)
        with self.assertRaises(ValueError):
            svc.apply(preview_token=preview.preview_token, confirmed=True, tailor_id="t", result_hash="h" * 64)

    def test_apply_rejects_expired(self) -> None:
        svc, state = self._svc(datetime(2026, 1, 1, tzinfo=timezone.utc))
        preview = svc.preview(tailor_id="t", result_hash="h" * 64, base_resume_version_id=None)
        state["now"] = state["now"] + timedelta(seconds=901)
        with self.assertRaises(ValueError):
            svc.apply(preview_token=preview.preview_token, confirmed=True, tailor_id="t", result_hash="h" * 64)


def _artifact_root(store: ResumeVersionStore) -> str:
    return str(store._artifact_root)


if __name__ == "__main__":
    unittest.main()
