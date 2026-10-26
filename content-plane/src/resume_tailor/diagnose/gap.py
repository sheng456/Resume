"""L2 缺口诊断：JD 要求 × 简历块 → 覆盖情况。

确定性、无模型。覆盖判定同时看两套词表：

- 技术词（``lexicon.tech``，含英文别名归一，``k8s`` -> ``kubernetes``）
- 同义短语（``lexicon.synonyms``，``服务拆分`` 与 ``微服务`` 视为同一事实）

后者是"术语对齐"能成立的前提：只有当 JD 的词被简历里某个**同义**短语覆盖时，
才谈得上"对齐而不是补写"。
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.contracts import Coverage, GapItem, JdRequirement, ResumeBlock
from ..lexicon.synonyms import canonical_terms_in
from ..lexicon.tech import TechLexicon, get_lexicon

__all__ = ["analyze_gaps", "requirement_terms", "block_terms"]


def requirement_terms(requirement: JdRequirement, lexicon: TechLexicon) -> frozenset[str]:
    """抽取一条 JD 要求涉及的全部术语（技术词 + 同义短语 canonical）。

    Args:
        requirement: JD 要求项。
        lexicon: 技术词词库。

    Returns:
        术语集合；提取不到时为空集合。
    """
    return lexicon.find(requirement.text) | canonical_terms_in(requirement.text)


def block_terms(block: ResumeBlock, lexicon: TechLexicon) -> frozenset[str]:
    """抽取一个简历块涉及的全部术语。

    Args:
        block: 简历块。
        lexicon: 技术词词库。

    Returns:
        术语集合。
    """
    return lexicon.find(block.text) | canonical_terms_in(block.text)


def analyze_gaps(
    *,
    requirements: Sequence[JdRequirement],
    blocks: Sequence[ResumeBlock],
    lexicon: TechLexicon | None = None,
) -> tuple[GapItem, ...]:
    """逐条 JD 要求计算其在简历中的覆盖情况。

    Args:
        requirements: JD 要求项。
        blocks: 全部简历块。
        lexicon: 技术词词库；默认使用内置词库。

    Returns:
        ``GapItem`` 元组，与 ``requirements`` 顺序一致。
    """
    lex = lexicon or get_lexicon()
    items: list[GapItem] = []

    for req in requirements:
        req_terms = requirement_terms(req, lex)
        label = "、".join(sorted(req_terms)) if req_terms else "无技术词"
        if not req_terms:
            items.append(
                GapItem(
                    requirement_id=req.requirement_id,
                    label=label,
                    coverage=Coverage.MISSING,
                    reason="no_extractable_terms",
                )
            )
            continue

        covered_terms: set[str] = set()
        scored: list[tuple[int, str]] = []
        for block in blocks:
            overlap = req_terms & block_terms(block, lex)
            if overlap:
                covered_terms |= overlap
                scored.append((len(overlap), block.block_id))

        if len(covered_terms) == len(req_terms):
            coverage = Coverage.COVERED
        elif covered_terms:
            coverage = Coverage.PARTIAL
        else:
            coverage = Coverage.MISSING

        best_block_ids = tuple(bid for _, bid in sorted(scored, key=lambda x: -x[0]))
        items.append(
            GapItem(
                requirement_id=req.requirement_id,
                label=label,
                coverage=coverage,
                best_block_ids=best_block_ids,
                requirement_terms=tuple(sorted(req_terms)),
            )
        )

    return tuple(items)
