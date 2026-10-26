"""L6 评审与提案的测试。

验证：提案不做 fail-closed（被挡候选仍被保留）、评审项三态、声明事实能
解除"无源"、决策落到最终简历时接受/拒绝/待定的正确语义。

运行：
    PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import unittest

from resume_tailor.domain.contracts import DeclaredFact, VerdictDecision
from resume_tailor.rewrite.reword import propose_block
from resume_tailor.review.review import (
    ReviewDecision,
    ReviewItem,
    apply_decisions,
    assemble_review,
    pending_blocked,
    reverify,
)
from tests.resume_fixtures import WORK_A


class ScriptedModel:
    """返回固定文本的假模型。"""

    def __init__(self, text: str) -> None:
        self._text = text

    def reword(self, prompt: str) -> str:
        return self._text


class TestPropose(unittest.TestCase):
    """提案不做 fail-closed。"""

    def test_blocked_candidate_is_kept(self) -> None:
        model = ScriptedModel("负责订单系统服务拆分，接口 P99 从 320ms 降至 45ms")
        proposal = propose_block(source_block=WORK_A, model=model)
        self.assertTrue(proposal.changed)
        self.assertEqual(proposal.proposed_text, "负责订单系统服务拆分，接口 P99 从 320ms 降至 45ms")
        self.assertIs(proposal.verdict.decision, VerdictDecision.NEEDS_USER_CONFIRMATION)
        self.assertFalse(proposal.facts_retained, "90ms 被换成 45ms，事实丢失")

    def test_valid_candidate_is_acceptable(self) -> None:
        model = ScriptedModel("负责订单系统微服务，接口 P99 从 320ms 降至 90ms")
        proposal = propose_block(source_block=WORK_A, model=model)
        self.assertTrue(proposal.acceptable)


class TestAssembleReview(unittest.TestCase):
    """评审项三态。"""

    def test_unchanged_is_auto_accepted(self) -> None:
        model = ScriptedModel(WORK_A.text)
        proposal = propose_block(source_block=WORK_A, model=model)
        (item,) = assemble_review([proposal])
        self.assertFalse(item.changed)
        self.assertIs(item.decision, ReviewDecision.ACCEPT)

    def test_blocked_is_pending(self) -> None:
        model = ScriptedModel("负责订单系统服务拆分，接口 P99 从 320ms 降至 45ms")
        proposal = propose_block(source_block=WORK_A, model=model)
        (item,) = assemble_review([proposal])
        self.assertTrue(item.blocked)
        self.assertIs(item.decision, ReviewDecision.PENDING)
        self.assertEqual(pending_blocked([item]), ("block:wa",))


class TestDeclareFact(unittest.TestCase):
    """声明事实解除"无源"。"""

    def test_declared_fact_unblocks_added_metric(self) -> None:
        # 新增 QPS 2000、保留 320ms/90ms：只触发 unsupported，不触发事实丢失
        candidate = "负责订单系统服务拆分，接口 P99 从 320ms 降至 90ms，QPS 提升到 2000"
        proposal = propose_block(source_block=WORK_A, model=ScriptedModel(candidate))
        self.assertIs(proposal.verdict.decision, VerdictDecision.NEEDS_USER_CONFIRMATION)
        self.assertTrue(proposal.facts_retained)

        verdict = reverify(
            block=WORK_A,
            proposed_text=proposal.proposed_text,
            declared_facts=[DeclaredFact("fact:1", "QPS 2000", "2024 压测报告")],
        )
        self.assertIs(verdict.decision, VerdictDecision.ACCEPT)


class TestApplyDecisions(unittest.TestCase):
    """决策落到最终简历。"""

    def test_accept_uses_proposed_reject_uses_original(self) -> None:
        model = ScriptedModel("负责订单系统微服务，接口 P99 从 320ms 降至 90ms")
        proposal = propose_block(source_block=WORK_A, model=model)
        item = assemble_review([proposal])[0]

        accept = ReviewItem(item.block_id, item.original_text, item.proposed_text, item.verdict, item.facts_retained, ReviewDecision.ACCEPT)
        reject = ReviewItem(item.block_id, item.original_text, item.proposed_text, item.verdict, item.facts_retained, ReviewDecision.REJECT)

        (accepted,) = apply_decisions([accept])
        (rejected,) = apply_decisions([reject])
        self.assertEqual(accepted.rewritten_text, "负责订单系统微服务，接口 P99 从 320ms 降至 90ms")
        self.assertEqual(rejected.rewritten_text, WORK_A.text)

    def test_pending_falls_back_to_original(self) -> None:
        model = ScriptedModel("负责订单系统服务拆分，接口 P99 从 320ms 降至 45ms")
        proposal = propose_block(source_block=WORK_A, model=model)
        (item,) = assemble_review([proposal])
        self.assertIs(item.decision, ReviewDecision.PENDING)
        (final,) = apply_decisions([item])
        self.assertEqual(final.rewritten_text, WORK_A.text)


if __name__ == "__main__":
    unittest.main()
