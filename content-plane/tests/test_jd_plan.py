"""L3 JD 驱动计划生成的测试。

核心命题：

1. ``forbidden_terms`` 锁死"JD 有、简历没有"的技术词，任何路径不得引入；
2. 术语对齐必须带同义词组证据，且只作用于可改写块；
3. ``seniority_ceiling`` 记录源块职级上限，供模型改写做硬上限；
4. 计划确定可复现（它是 Gate T 的审批对象）。

运行：
    PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import unittest

from resume_tailor.domain.contracts import EditOperation, JdRequirement
from resume_tailor.plan.jd_plan import build_jd_plan
from tests.resume_fixtures import (
    ALL_BLOCKS,
    REQ_JAVA,
    REQ_K8S,
    REQ_MICRO,
    WORK_A,
    WORK_B,
    WORK_C,
)


class TestForbiddenTerms(unittest.TestCase):
    """JD 注入黑名单。"""

    def test_jd_tech_absent_from_resume_is_forbidden(self) -> None:
        plan = build_jd_plan(requirements=[REQ_JAVA, REQ_K8S], blocks=ALL_BLOCKS)
        self.assertIn("kubernetes", plan.forbidden_terms)

    def test_tech_already_in_resume_is_not_forbidden(self) -> None:
        plan = build_jd_plan(requirements=[REQ_JAVA], blocks=ALL_BLOCKS)
        self.assertNotIn("java", plan.forbidden_terms)
        self.assertNotIn("spring", plan.forbidden_terms)

    def test_synonym_phrase_absent_from_resume_is_forbidden(self) -> None:
        """同义短语（高并发）也进黑名单（修复 F4）。"""
        plan = build_jd_plan(requirements=[JdRequirement("req:hc", "熟悉高并发系统设计")], blocks=ALL_BLOCKS)
        self.assertIn("高并发", plan.forbidden_terms)


class TestPlanIdBinding(unittest.TestCase):
    """planId 绑定简历/JD 内容哈希（修复 F2）。"""

    def test_plan_id_binds_resume_content(self) -> None:
        a = build_jd_plan(
            requirements=[REQ_JAVA], blocks=ALL_BLOCKS,
            resume_content_hash="r1", jd_content_hash="j1", strategy_version="v1",
        )
        b = build_jd_plan(
            requirements=[REQ_JAVA], blocks=ALL_BLOCKS,
            resume_content_hash="r2", jd_content_hash="j1", strategy_version="v1",
        )
        self.assertNotEqual(a.plan_id, b.plan_id)


class TestAlignment(unittest.TestCase):
    """术语对齐证据。"""

    def test_synonym_alignment_is_emitted(self) -> None:
        plan = build_jd_plan(requirements=[REQ_MICRO], blocks=[WORK_A])
        (step,) = [s for s in plan.steps if s.block_id == "block:wa"]
        self.assertIs(step.operation, EditOperation.TERMINOLOGY_ALIGN)
        self.assertTrue(step.alignments)
        pair = step.alignments[0]
        self.assertEqual((pair.source_phrase, pair.target_phrase), ("服务拆分", "微服务"))
        self.assertIsInstance(pair.synonym_group, int)

    def test_block_without_synonym_is_unchanged(self) -> None:
        plan = build_jd_plan(requirements=[REQ_MICRO], blocks=[WORK_B])
        (step,) = [s for s in plan.steps if s.block_id == "block:wb"]
        self.assertIs(step.operation, EditOperation.UNCHANGED)
        self.assertEqual(step.alignments, ())


class TestSeniorityCeiling(unittest.TestCase):
    """职级硬上限。"""

    def test_ceiling_records_observed_role_rank(self) -> None:
        plan = build_jd_plan(requirements=[REQ_MICRO], blocks=[WORK_B, WORK_A])
        by_id = {s.block_id: s for s in plan.steps}
        self.assertEqual(by_id["block:wb"].seniority_ceiling, 2)  # 主导
        self.assertEqual(by_id["block:wa"].seniority_ceiling, 1)  # 负责


class TestRewriteBoundary(unittest.TestCase):
    """技能行不入计划；重排只排可改写块。"""

    def test_skill_list_is_not_in_steps(self) -> None:
        plan = build_jd_plan(requirements=[REQ_JAVA], blocks=ALL_BLOCKS)
        step_ids = [s.block_id for s in plan.steps]
        self.assertNotIn("block:skill", step_ids)

    def test_skill_list_is_reported_as_rejected(self) -> None:
        plan = build_jd_plan(requirements=[REQ_JAVA], blocks=ALL_BLOCKS)
        self.assertIn(("block:skill", "not_rewritable"), plan.rejected)

    def test_bullet_order_by_coverage(self) -> None:
        plan = build_jd_plan(requirements=[REQ_JAVA], blocks=[WORK_A, WORK_B, WORK_C])
        self.assertEqual(plan.bullet_order[0], "block:wc")  # Java+Spring Boot 覆盖最高


class TestDeterminism(unittest.TestCase):
    """计划是审批对象，必须确定。"""

    def test_plan_id_is_stable(self) -> None:
        first = build_jd_plan(requirements=[REQ_MICRO, REQ_JAVA], blocks=ALL_BLOCKS)
        second = build_jd_plan(requirements=[REQ_MICRO, REQ_JAVA], blocks=ALL_BLOCKS)
        self.assertEqual(first.plan_id, second.plan_id)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
