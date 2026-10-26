"""指令意图接入计划与管线的测试。

覆盖：无指令走 JD 兜底、有指令走 driver='instruction'、歧义要求澄清、
与 JD 缺口冲突报冲突、instruction_hash 绑定原句、方向串进提示词。

运行：
    PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import unittest

from resume_tailor.plan.plan import build_plan
from resume_tailor.rewrite.reword import build_reword_prompt, reword_block
from tests.resume_fixtures import (
    ALL_BLOCKS,
    REQ_JAVA,
    WORK_A,
    WORK_B,
)


class TestDriverSelection(unittest.TestCase):
    """指令驱动 vs JD 兜底。"""

    def test_no_instruction_is_jd_gap(self) -> None:
        result = build_plan(requirements=[REQ_JAVA], blocks=ALL_BLOCKS, instruction=None)
        self.assertTrue(result.ok)
        self.assertEqual(result.plan.driver, "jd_gap")
        self.assertIsNone(result.plan.intent_id)
        self.assertIsNone(result.plan.instruction_hash)

    def test_instruction_is_instruction_driver(self) -> None:
        result = build_plan(
            requirements=[REQ_JAVA], blocks=ALL_BLOCKS,
            instruction="把项目经历写得更专业一些",
        )
        self.assertTrue(result.ok)
        plan = result.plan
        self.assertEqual(plan.driver, "instruction")
        self.assertIsNotNone(plan.intent_id)
        self.assertIsNotNone(plan.instruction_hash)

        by_id = {step.block_id: step for step in plan.steps}
        self.assertEqual(by_id["block:pk"].origin, "instruction")
        self.assertEqual(by_id["block:pk"].direction, "reword")
        # 非指令命中的块仍走 JD 兜底（origin 标 jd_gap，无方向）
        self.assertEqual(by_id["block:wa"].origin, "jd_gap")
        self.assertIsNone(by_id["block:wa"].direction)

    def test_instruction_scoped_blocks_surface_first(self) -> None:
        result = build_plan(
            requirements=[REQ_JAVA], blocks=ALL_BLOCKS,
            instruction="把项目经历写得更专业一些",
        )
        self.assertEqual(result.plan.bullet_order[0], "block:pk")


class TestBlockers(unittest.TestCase):
    """歧义与冲突不生成计划。"""

    def test_vague_instruction_requires_clarification(self) -> None:
        result = build_plan(requirements=[REQ_JAVA], blocks=ALL_BLOCKS, instruction="写得好一点")
        self.assertTrue(result.ambiguous)
        self.assertIsNone(result.plan)
        self.assertTrue(result.clarification_options)
        self.assertFalse(result.has_conflict)

    def test_gap_conflict_is_reported(self) -> None:
        """弱化 JD 缺口项 -> 报冲突（且因无范围同时歧义，冲突信息仍保留）。"""
        result = build_plan(
            requirements=[REQ_JAVA], blocks=[WORK_A, WORK_B],
            instruction="弱化 Java 相关的内容",
        )
        self.assertTrue(result.has_conflict)
        self.assertIsNone(result.plan)
        self.assertEqual(result.conflicts[0].requirement_id, "req:java")


class TestInstructionBinding(unittest.TestCase):
    """指令哈希绑定原句。"""

    def test_instruction_hash_binds_exact_sentence(self) -> None:
        first = build_plan(requirements=[REQ_JAVA], blocks=ALL_BLOCKS, instruction="把项目经历写得更专业一些")
        second = build_plan(requirements=[REQ_JAVA], blocks=ALL_BLOCKS, instruction="把工作经历写得更专业一些")
        self.assertNotEqual(first.plan.instruction_hash, second.plan.instruction_hash)


class TestDirectionInPrompt(unittest.TestCase):
    """方向串进提示词，但不泄漏 JD。"""

    def test_prompt_contains_direction_but_not_jd(self) -> None:
        prompt = build_reword_prompt("负责订单系统服务拆分", direction="emphasize")
        self.assertIn("突出", prompt)
        self.assertNotIn("kubernetes", prompt)

    def test_reword_block_passes_direction_to_model(self) -> None:
        captured: dict = {}

        class CapturingModel:
            def reword(self, prompt: str) -> str:
                captured["prompt"] = prompt
                return "负责订单系统微服务"

        reword_block(source_block=WORK_A, model=CapturingModel(), direction="emphasize")
        self.assertIn("突出", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
