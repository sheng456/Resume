"""L3 指令解析与缺口冲突的测试。

覆盖 `docs/ARCHITECTURE.md` §5.3 要求的三条边界与四条解析分支：

- 明确指令（目标 + 范围）——高置信度；
- 模糊指令——低置信度并要求澄清，**不得**生成计划；
- 指令方向与 JD 缺口相反——报冲突交用户裁决；
- 指令只产出范围与目标——**不产出任何文本**。

运行：
    PYTHONPATH=src python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import dataclasses
import unittest

from resume_tailor.domain.contracts import (
    BlockKind,
    Coverage,
    GapItem,
    IntentGoal,
    ParseConfidence,
    ResumeBlock,
    Section,
)
from resume_tailor.plan.intent import build_intent, parse_instruction

# --------------------------------------------------------------------------- #
# Fixtures（虚构、脱敏）
# --------------------------------------------------------------------------- #

BLOCKS: tuple[ResumeBlock, ...] = (
    ResumeBlock("block:w1", Section.WORK, BlockKind.BULLET, "负责订单履约模块开发，将接口 P99 从 320ms 降至 90ms"),
    ResumeBlock("block:w3", Section.WORK, BlockKind.BULLET, "参与 CI/CD 流程建设，发布耗时从 25 分钟缩短至 8 分钟"),
    ResumeBlock("block:p1", Section.PROJECT, BlockKind.BULLET, "使用 Java 与 Spring Boot 开发订单系统"),
    ResumeBlock("block:p2", Section.PROJECT, BlockKind.BULLET, "引入 Kafka 异步化，峰值 QPS 从 1200 提升至 4500"),
    ResumeBlock("block:s1", Section.SKILL, BlockKind.SKILL_LIST, "Java、Spring Boot、MySQL、Redis、Kafka"),
)

MISSING_JAVA_GAP = GapItem(
    requirement_id="req:java",
    label="Java 后端开发",
    coverage=Coverage.MISSING,
    requirement_terms=("java", "spring"),
)

COVERED_JAVA_GAP = GapItem(
    requirement_id="req:java",
    label="Java 后端开发",
    coverage=Coverage.COVERED,
    best_block_ids=("block:p1",),
    requirement_terms=("java", "spring"),
)


class TestIntentParsing(unittest.TestCase):
    """目标与范围的解析。"""

    def test_goal_and_scope_is_high_confidence(self) -> None:
        intent = parse_instruction("把项目经历写得更专业一些", blocks=BLOCKS)
        self.assertIs(intent.goal, IntentGoal.REWORD)
        self.assertIn(Section.PROJECT, intent.scope_sections)
        self.assertIs(intent.parse_confidence, ParseConfidence.HIGH)
        self.assertEqual(intent.clarification_options, ())

    def test_vague_instruction_is_low_confidence_and_offers_clarification(self) -> None:
        intent = parse_instruction("写得好一点", blocks=BLOCKS)
        self.assertIs(intent.goal, None)
        self.assertIs(intent.parse_confidence, ParseConfidence.LOW)
        self.assertTrue(intent.clarification_options, "低置信度必须给出澄清候选")

    def test_scope_can_come_from_a_mentioned_technology(self) -> None:
        intent = parse_instruction("突出 Kafka 那条", blocks=BLOCKS)
        self.assertIs(intent.goal, IntentGoal.EMPHASIZE)
        self.assertEqual(intent.scope_block_ids, ("block:p2",))
        self.assertIs(intent.parse_confidence, ParseConfidence.HIGH)

    def test_goal_uses_earliest_mention(self) -> None:
        intent = parse_instruction("先精简一下，再突出量化结果", blocks=BLOCKS)
        self.assertIs(intent.goal, IntentGoal.CONDENSE)

    def test_empty_instruction_is_low_confidence(self) -> None:
        intent = parse_instruction("   ", blocks=BLOCKS)
        self.assertIs(intent.goal, None)
        self.assertIs(intent.parse_confidence, ParseConfidence.LOW)

    def test_intent_id_is_deterministic(self) -> None:
        first = parse_instruction("把项目经历写得更专业一些", blocks=BLOCKS)
        second = parse_instruction("把项目经历写得更专业一些", blocks=BLOCKS)
        self.assertEqual(first.intent_id, second.intent_id)

    def test_different_instruction_yields_different_intent_id(self) -> None:
        first = parse_instruction("把项目经历写得更专业一些", blocks=BLOCKS)
        second = parse_instruction("把工作经历写得更专业一些", blocks=BLOCKS)
        self.assertNotEqual(first.intent_id, second.intent_id)


class TestIntentCarriesNoText(unittest.TestCase):
    """结构性不变量：意图只描述范围与目标，不携带任何正文。

    这是"指令不能成为绕过事实门禁的通道"的机械保证——如果
    ``TailorIntent`` 上出现一个装文本的字段，这条边界就被破坏了。
    """

    def test_tailor_intent_has_no_text_bearing_field(self) -> None:
        field_names = {field.name for field in dataclasses.fields(parse_instruction("突出 Kafka", blocks=BLOCKS))}
        self.assertEqual(
            field_names,
            {
                "intent_id",
                "instruction_id",
                "goal",
                "scope_block_ids",
                "scope_sections",
                "parse_confidence",
                "conflicts_with_gap",
                "clarification_options",
            },
        )

    def test_no_field_holds_the_raw_instruction_text(self) -> None:
        instruction = "把项目经历写得更专业一些"
        intent = parse_instruction(instruction, blocks=BLOCKS)
        for field in dataclasses.fields(intent):
            value = getattr(intent, field.name)
            if isinstance(value, str):
                self.assertNotEqual(value, instruction, f"字段 {field.name} 直接保存了指令原文")


class TestGapConflict(unittest.TestCase):
    """指令与 JD 缺口的冲突。"""

    def test_deemphasising_a_missing_requirement_is_a_conflict(self) -> None:
        intent = build_intent(
            "弱化 Java 相关的内容",
            blocks=BLOCKS,
            gap_items=(MISSING_JAVA_GAP,),
        )
        self.assertIs(intent.goal, IntentGoal.DEEMPHASIZE)
        self.assertEqual(len(intent.conflicts_with_gap), 1)
        conflict = intent.conflicts_with_gap[0]
        self.assertEqual(conflict.requirement_id, "req:java")
        self.assertIn("missing", conflict.gap_direction)
        self.assertIn("deemphasize", conflict.instruction_direction)

    def test_emphasising_a_missing_requirement_is_not_a_conflict(self) -> None:
        intent = build_intent("突出 Java 相关的内容", blocks=BLOCKS, gap_items=(MISSING_JAVA_GAP,))
        self.assertEqual(intent.conflicts_with_gap, ())

    def test_deemphasising_a_covered_requirement_is_not_a_conflict(self) -> None:
        intent = build_intent("弱化 Java 相关的内容", blocks=BLOCKS, gap_items=(COVERED_JAVA_GAP,))
        self.assertEqual(intent.conflicts_with_gap, ())

    def test_deemphasising_unrelated_tech_is_not_a_conflict(self) -> None:
        intent = build_intent("弱化 Redis 相关的内容", blocks=BLOCKS, gap_items=(MISSING_JAVA_GAP,))
        self.assertEqual(intent.conflicts_with_gap, ())

    def test_conflict_does_not_rewrite_the_instruction(self) -> None:
        """冲突必须如实记录，绝不能静默把指令改成 JD 的方向。"""
        intent = build_intent("弱化 Java 相关的内容", blocks=BLOCKS, gap_items=(MISSING_JAVA_GAP,))
        self.assertIs(intent.goal, IntentGoal.DEEMPHASIZE, "指令方向不得被 JD 覆盖")
        self.assertEqual(intent.scope_block_ids, ("block:p1",))


class TestRewriteBoundary(unittest.TestCase):
    """指令不能把可改写范围撑大（ARCHITECTURE §5.1）。"""

    def test_skill_list_is_excluded_from_scope(self) -> None:
        """技能行也含 Kafka，但它是 skill_list，不得被纳入改写范围。

        这条边界很重要：改写技能列表正是 JD 注入最容易得手的地方。
        """
        intent = parse_instruction("突出 Kafka 那条", blocks=BLOCKS)
        self.assertEqual(intent.scope_block_ids, ("block:p2",))
        self.assertNotIn("block:s1", intent.scope_block_ids)

    def test_immutable_block_is_excluded_from_scope(self) -> None:
        blocks = BLOCKS + (
            ResumeBlock(
                "block:e1",
                Section.EDUCATION,
                BlockKind.BULLET,
                "2019.09 – 2023.06 某某大学 Kafka 方向本科",
            ),
        )
        intent = parse_instruction("突出 Kafka 那条", blocks=blocks)
        self.assertNotIn("block:e1", intent.scope_block_ids)

    def test_is_rewritable_matches_documented_rule(self) -> None:
        from resume_tailor.plan.intent import is_rewritable

        self.assertTrue(is_rewritable(ResumeBlock("b", Section.WORK, BlockKind.BULLET, "x")))
        self.assertFalse(is_rewritable(ResumeBlock("b", Section.SKILL, BlockKind.SKILL_LIST, "x")))
        self.assertFalse(is_rewritable(ResumeBlock("b", Section.EDUCATION, BlockKind.BULLET, "x")))
        self.assertFalse(is_rewritable(ResumeBlock("b", Section.WORK, BlockKind.META, "x")))
        self.assertFalse(is_rewritable(ResumeBlock("b", Section.WORK, BlockKind.BULLET, "x", immutable=True)))

    def test_clarification_explains_why_named_tech_is_uneditable(self) -> None:
        """点名了技术词却落在不可改写块时，必须说清原因。

        否则用户只会看到"要改哪一部分？"——而他明明已经说了要改什么。
        这里 Kafka 只出现在技能行 block:s1，没有任何可改写的经历条目包含它
        （block:p2 已被排除）。
        """
        blocks = (BLOCKS[0], BLOCKS[1], BLOCKS[2], BLOCKS[4])
        intent = parse_instruction("突出 Kafka 那条", blocks=blocks)
        self.assertIs(intent.goal, IntentGoal.EMPHASIZE)
        self.assertIs(intent.parse_confidence, ParseConfidence.LOW)
        joined = " ".join(intent.clarification_options)
        self.assertIn("kafka", joined)
        self.assertIn("不可改写", joined)

    def test_ambiguity_and_conflict_report_both_but_ambiguity_wins(self) -> None:
        """两者同时出现时两个字段都填，但错误码优先级按文档以歧义为先。"""
        blocks = (BLOCKS[0], BLOCKS[1], BLOCKS[2], BLOCKS[4])
        intent = build_intent("弱化 Kafka", blocks=blocks, gap_items=(MISSING_JAVA_GAP,))
        self.assertIs(intent.parse_confidence, ParseConfidence.LOW)
        self.assertTrue(intent.clarification_options)
        self.assertEqual(intent.conflicts_with_gap, (), "Kafka 不在缺口词表内，不应报冲突")


if __name__ == "__main__":
    unittest.main()
