"""模型级语义匹配的测试（用假模型，确定性）。"""

from __future__ import annotations

import unittest

from resume_tailor.diagnose.semantic_match import (
    SemanticGapReport,
    analyze_semantic_gaps,
    judge_requirement_relevance,
)
from resume_tailor.domain.contracts import BlockKind, JdRequirement, ResumeBlock, Section

BLOCKS = (
    ResumeBlock("b0", Section.WORK, BlockKind.BULLET, "负责订单系统服务拆分"),
    ResumeBlock("b1", Section.WORK, BlockKind.BULLET, "参与文本检索链路工程"),
    ResumeBlock("b2", Section.WORK, BlockKind.BULLET, "引入 Kafka 异步化"),
)


class TestJudge(unittest.TestCase):
    """相关性判定。"""

    def test_returns_relevant_ids(self) -> None:
        ids = judge_requirement_relevance(
            requirement_text="信息抽取", blocks=BLOCKS, generate=lambda _p: "0,2"
        )
        self.assertEqual(ids, ("b0", "b2"))

    def test_none_is_empty(self) -> None:
        ids = judge_requirement_relevance(
            requirement_text="信息抽取", blocks=BLOCKS, generate=lambda _p: "none"
        )
        self.assertEqual(ids, ())

    def test_tolerates_surrounding_text(self) -> None:
        ids = judge_requirement_relevance(
            requirement_text="信息抽取", blocks=BLOCKS, generate=lambda _p: "相关的是 1 和 2"
        )
        self.assertEqual(ids, ("b1", "b2"))

    def test_model_failure_falls_back_empty(self) -> None:
        def boom(_p: str) -> str:
            raise RuntimeError("down")

        self.assertEqual(
            judge_requirement_relevance(requirement_text="x", blocks=BLOCKS, generate=boom), ()
        )


class TestReport(unittest.TestCase):
    """批量报告。"""

    def test_blocks_for_lookup(self) -> None:
        report = analyze_semantic_gaps(
            requirements=(JdRequirement("r0", "信息抽取"), JdRequirement("r1", "高并发")),
            blocks=BLOCKS,
            generate=lambda _p: "1",
        )
        self.assertIsInstance(report, SemanticGapReport)
        self.assertEqual(report.blocks_for("r0"), ("b1",))
        self.assertEqual(report.blocks_for("r1"), ("b1",))
        self.assertEqual(report.blocks_for("nope"), ())


if __name__ == "__main__":
    unittest.main()
