"""L6 评审：把改写提案变成"经人确认"的最终版本。

评审是"人在环"的闸门：改写管线产出草稿，评审把每条改动摊开，由用户逐条
决定**接受 / 拒绝 / 声明事实**。只有评审通过（无待确认的 blocked 项）的
版本才能进入 L7 落盘。

原则（对应 ``docs/ARCHITECTURE.md`` §5.6）：

- 逐块 diff：原文 vs 候选，并列展示；
- 每条改动带 verdict（哪些单元锚定 / 无源 / 升级）；
- 无源/升级的单元可由用户"声明为事实"（附证据）后重新锚定；
- 评审文本不进 Transcript——本模块只产出数据与决策逻辑，UI 属控制面。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from ..domain.contracts import (
    DeclaredFact,
    ResumeBlock,
    RewriteProposal,
    RewrittenBlock,
    Verdict,
    VerdictDecision,
)
from ..lexicon.tech import TechLexicon, get_lexicon
from ..verify.verifier import verify_edit

__all__ = [
    "ReviewDecision",
    "ReviewItem",
    "apply_decisions",
    "assemble_review",
    "pending_blocked",
    "reverify",
]


class ReviewDecision(StrEnum):
    """用户对一条评审项的决定。"""

    PENDING = "pending"   # 待用户处理（被门禁挡住）
    ACCEPT = "accept"     # 接受候选
    REJECT = "reject"     # 拒绝候选，回退原文


@dataclass(frozen=True)
class ReviewItem:
    """一条评审项：原文、候选、校验结论、用户决定。"""

    block_id: str
    original_text: str
    proposed_text: str
    verdict: Verdict
    facts_retained: bool = True
    decision: ReviewDecision = ReviewDecision.PENDING

    @property
    def changed(self) -> bool:
        """候选是否不同于原文。"""
        return self.original_text != self.proposed_text

    @property
    def acceptable(self) -> bool:
        """候选是否可直接接受（L5 通过且事实保留）。"""
        return self.verdict.decision is VerdictDecision.ACCEPT and self.facts_retained

    @property
    def blocked(self) -> bool:
        """是否被门禁挡住、需要用户处理（声明事实或拒绝）。"""
        return self.changed and not self.acceptable


def assemble_review(proposals: Sequence[RewriteProposal]) -> tuple[ReviewItem, ...]:
    """把提案组装成评审项。

    未改动的提案直接 ACCEPT（无需评审）；改动的提案，acceptable 则 ACCEPT，
    否则保持 PENDING 待用户处理。

    Args:
        proposals: ``propose_blocks`` 的产出。

    Returns:
        ReviewItem 元组，顺序与提案一致。
    """
    items: list[ReviewItem] = []
    for proposal in proposals:
        if not proposal.changed:
            items.append(
                ReviewItem(
                    proposal.block_id,
                    proposal.original_text,
                    proposal.proposed_text,
                    proposal.verdict,
                    proposal.facts_retained,
                    ReviewDecision.ACCEPT,
                )
            )
            continue
        decision = ReviewDecision.ACCEPT if proposal.acceptable else ReviewDecision.PENDING
        items.append(
            ReviewItem(
                proposal.block_id,
                proposal.original_text,
                proposal.proposed_text,
                proposal.verdict,
                proposal.facts_retained,
                decision,
            )
        )
    return tuple(items)


def reverify(
    *,
    block: ResumeBlock,
    proposed_text: str,
    declared_facts: Sequence[DeclaredFact],
    jd_text: str = "",
    lexicon: TechLexicon | None = None,
) -> Verdict:
    """用新增的用户声明重新校验一条被挡住的候选。

    典型场景：候选把 90ms 改成 45ms，被判"无源"；用户声明"45ms 来自 2024
    压测报告"后，本函数重新校验，若通过则该候选可被接受。

    Args:
        block: 源块。
        proposed_text: 被挡住的候选文本。
        declared_facts: 用户声明的事实（含证据）。
        jd_text: JD 全文。
        lexicon: 技术词词库。

    Returns:
        重新校验后的 Verdict。
    """
    return verify_edit(
        source_blocks=[block],
        candidate_text=proposed_text,
        declared_facts=declared_facts,
        jd_text=jd_text,
        lexicon=lexicon or get_lexicon(),
    )


def pending_blocked(items: Sequence[ReviewItem]) -> tuple[str, ...]:
    """返回仍处于"被挡住且未决定"状态的 block_id。

    这些项必须由用户处理（声明事实或拒绝）后才能进入落盘。
    """
    return tuple(item.block_id for item in items if item.blocked and item.decision is ReviewDecision.PENDING)


def apply_decisions(items: Sequence[ReviewItem]) -> tuple[RewrittenBlock, ...]:
    """把评审决定转成最终简历。

    接受 -> 候选；拒绝或仍 pending -> 原文（安全默认）。

    Args:
        items: 评审项（含用户决定）。

    Returns:
        RewrittenBlock 元组，最终版本。
    """
    out: list[RewrittenBlock] = []
    for item in items:
        final = item.proposed_text if item.decision is ReviewDecision.ACCEPT else item.original_text
        out.append(RewrittenBlock(item.block_id, item.original_text, final))
    return tuple(out)
