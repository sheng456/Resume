"""安全改写（无模型）的测试。

核心命题：确定性改写（术语对齐 + 重排）**不可能引入新事实**——

1. 对齐只替换有同义证据的短语，量化结果逐字保留；
2. 重排是纯置换，token 一个不多不少；
3. 改写结果过 L5 恒通过（这是"没有臆造"的机械保证）；
4. JD 有、简历没有的技术词绝不出现。

运行：
    PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import unittest

from resume_tailor.domain.contracts import VerdictDecision
from resume_tailor.plan.jd_plan import build_jd_plan
from resume_tailor.rewrite.safe import reorder_blocks, rewrite_blocks, verify_rewrite
from tests.resume_fixtures import (
    ALL_BLOCKS,
    REQ_JAVA,
    REQ_JAVA_KAFKA,
    REQ_K8S,
    REQ_MICRO,
    WORK_A,
    WORK_B,
    WORK_C,
)


class TestAlignmentRewrite(unittest.TestCase):
    """术语对齐替换。"""

    def test_synonym_is_replaced_and_metric_preserved(self) -> None:
        plan = build_jd_plan(requirements=[REQ_MICRO], blocks=[WORK_A])
        (result,) = rewrite_blocks(blocks=[WORK_A], plan=plan)
        self.assertIn("微服务", result.rewritten_text)
        self.assertNotIn("服务拆分", result.rewritten_text)
        # 量化结果逐字保留
        self.assertIn("320ms", result.rewritten_text)
        self.assertIn("90ms", result.rewritten_text)

    def test_unchanged_block_is_byte_exact(self) -> None:
        plan = build_jd_plan(requirements=[REQ_MICRO], blocks=[WORK_B])
        (result,) = rewrite_blocks(blocks=[WORK_B], plan=plan)
        self.assertEqual(result.rewritten_text, result.original_text)
        self.assertFalse(result.changed)


class TestReorder(unittest.TestCase):
    """section 内重排。"""

    def test_high_coverage_bullet_moves_first_within_section(self) -> None:
        plan = build_jd_plan(requirements=[REQ_JAVA], blocks=[WORK_A, WORK_B, WORK_C])
        results = rewrite_blocks(blocks=[WORK_A, WORK_B, WORK_C], plan=plan)
        self.assertEqual(results[0].block_id, "block:wc")

    def test_reorder_does_not_change_any_text(self) -> None:
        """重排是纯置换：改写后所有文本与原文本集合一致。"""
        plan = build_jd_plan(requirements=[REQ_JAVA], blocks=[WORK_A, WORK_B, WORK_C])
        results = rewrite_blocks(blocks=[WORK_A, WORK_B, WORK_C], plan=plan)
        originals = sorted(r.original_text for r in results)
        rewritten = sorted(r.rewritten_text for r in results)
        self.assertEqual(originals, rewritten)

    def test_bullet_order_overrides_coverage(self) -> None:
        """P2：给定 bullet_order 时按它重排（覆盖数不再是唯一依据）。"""
        blocks = [WORK_A, WORK_B, WORK_C]
        ordered = reorder_blocks(blocks, {}, ["block:wb", "block:wa", "block:wc"])
        self.assertEqual([b.block_id for b in ordered], ["block:wb", "block:wa", "block:wc"])


class TestFidelityInvariants(unittest.TestCase):
    """不臆造 / 不注水的不变量。"""

    def test_rewrite_always_passes_l5(self) -> None:
        plan = build_jd_plan(requirements=[REQ_MICRO], blocks=[WORK_A])
        results = rewrite_blocks(blocks=[WORK_A], plan=plan)
        verdicts = verify_rewrite(blocks=[WORK_A], rewritten=results, jd_text=REQ_MICRO.text)
        self.assertTrue(verdicts)
        self.assertTrue(all(v.decision is VerdictDecision.ACCEPT for v in verdicts))

    def test_forbidden_jd_tech_never_appears(self) -> None:
        """JD 要求 Kubernetes、简历没有：改写后绝不能冒出 kubernetes。"""
        plan = build_jd_plan(requirements=[REQ_JAVA, REQ_K8S], blocks=ALL_BLOCKS)
        self.assertIn("kubernetes", plan.forbidden_terms)
        results = rewrite_blocks(blocks=ALL_BLOCKS, plan=plan)
        joined = "\n".join(r.rewritten_text for r in results)
        self.assertNotIn("kubernetes", joined)
        self.assertNotIn("k8s", joined)

    def test_no_metric_is_fabricated(self) -> None:
        """改写不新增任何源块里没有的数字。"""
        plan = build_jd_plan(requirements=[REQ_MICRO], blocks=[WORK_A])
        results = rewrite_blocks(blocks=[WORK_A], plan=plan)
        self.assertNotIn("45ms", results[0].rewritten_text)
        self.assertNotIn("99.9%", results[0].rewritten_text)


class TestDeterminism(unittest.TestCase):
    """同输入同输出。"""

    def test_rewrite_is_deterministic(self) -> None:
        plan = build_jd_plan(requirements=[REQ_MICRO], blocks=[WORK_A])
        first = rewrite_blocks(blocks=[WORK_A], plan=plan)
        second = rewrite_blocks(blocks=[WORK_A], plan=plan)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
