"""完整改写管线的测试。

验证三件事：对齐与 reword 的顺序正确、事实在整条管线后仍被保留、重排不丢失。

运行：
    PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import unittest

from resume_tailor.domain.contracts import VerdictDecision
from resume_tailor.plan.jd_plan import build_jd_plan
from resume_tailor.rewrite.pipeline import rewrite_resume
from resume_tailor.rewrite.safe import rewrite_blocks, verify_rewrite
from tests.resume_fixtures import (
    ALL_BLOCKS,
    REQ_JAVA,
    REQ_MICRO,
    WORK_A,
    WORK_C,
)


class _FixedModel:
    """返回固定有效改写，用于验证 reword 被采纳。"""

    def reword(self, prompt: str) -> str:
        return "负责订单系统微服务，将接口 P99 从 320ms 降至 90ms"


class TestPipelineWithoutModel(unittest.TestCase):
    """无模型时管线 == 对齐 + 重排。"""

    def test_equals_safe_rewrite(self) -> None:
        plan = build_jd_plan(requirements=[REQ_MICRO, REQ_JAVA], blocks=[WORK_A, WORK_C])
        piped = rewrite_resume(blocks=[WORK_A, WORK_C], plan=plan, model=None)
        safe = rewrite_blocks(blocks=[WORK_A, WORK_C], plan=plan)
        self.assertEqual(piped, safe)

    def test_reorder_still_applies(self) -> None:
        plan = build_jd_plan(requirements=[REQ_JAVA], blocks=[WORK_A, WORK_C])
        result = rewrite_resume(blocks=[WORK_A, WORK_C], plan=plan, model=None)
        self.assertEqual(result[0].block_id, "block:wc")  # Java+Spring 覆盖高，前移


class TestPipelineWithModel(unittest.TestCase):
    """有模型时对齐与 reword 都生效。"""

    def test_alignment_and_reword_both_apply(self) -> None:
        plan = build_jd_plan(requirements=[REQ_MICRO], blocks=[WORK_A])
        (result,) = rewrite_resume(blocks=[WORK_A], plan=plan, model=_FixedModel())
        self.assertTrue(result.changed)
        # 对齐：服务拆分 -> 微服务
        self.assertIn("微服务", result.rewritten_text)
        self.assertNotIn("服务拆分", result.rewritten_text)
        # reword：加上了"将接口"
        self.assertIn("将接口", result.rewritten_text)

    def test_facts_preserved_through_pipeline(self) -> None:
        plan = build_jd_plan(requirements=[REQ_MICRO, REQ_JAVA], blocks=ALL_BLOCKS)
        result = rewrite_resume(blocks=ALL_BLOCKS, plan=plan, model=_FixedModel())
        verdicts = verify_rewrite(
            blocks=ALL_BLOCKS,
            rewritten=result,
            jd_text=" ".join(r.text for r in [REQ_MICRO, REQ_JAVA]),
        )
        self.assertTrue(all(v.decision is VerdictDecision.ACCEPT for v in verdicts))

    def test_skill_list_untouched(self) -> None:
        plan = build_jd_plan(requirements=[REQ_MICRO, REQ_JAVA], blocks=ALL_BLOCKS)
        result = rewrite_resume(blocks=ALL_BLOCKS, plan=plan, model=_FixedModel())
        skill = next(r for r in result if r.block_id == "block:skill")
        self.assertFalse(skill.changed)


class TestPipelineDeterminism(unittest.TestCase):
    """同输入同输出。"""

    def test_deterministic(self) -> None:
        plan = build_jd_plan(requirements=[REQ_MICRO, REQ_JAVA], blocks=ALL_BLOCKS)
        first = rewrite_resume(blocks=ALL_BLOCKS, plan=plan, model=None)
        second = rewrite_resume(blocks=ALL_BLOCKS, plan=plan, model=None)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
