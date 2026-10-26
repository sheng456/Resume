"""L3 JD 驱动的改写计划生成（确定性）。

输出一份 ``EditPlan``：每个可改写块一条 ``EditBrief``（术语对齐 + 职级上限 +
覆盖数），外加按 JD 覆盖度排出的 ``bullet_order`` 与 ``forbidden_terms``
（JD 有、简历没有的技术词黑名单）。

**整份计划不含任何目标文本。** 文本要么由确定性操作机械生成，要么由模型
生成后过 L5。计划本身是 Gate T 的审批对象，因此必须确定可复现。

若干公共辅助函数供 ``plan/plan.py``（指令驱动）复用。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from ..domain.contracts import (
    AlignmentPair,
    EditBrief,
    EditOperation,
    EditPlan,
    JdRequirement,
    ResumeBlock,
)
from ..diagnose.gap import analyze_gaps
from ..lexicon.synonyms import canonical_terms_in, find_alignments
from ..lexicon.tech import TechLexicon, get_lexicon
from ..verify.fact_units import extract_seniority
from .intent import is_rewritable

__all__ = [
    "alignments_for",
    "block_coverage",
    "build_jd_plan",
    "forbidden_terms_of",
    "jd_tech_terms",
    "plan_id_of",
    "resume_tech_terms",
    "seniority_ceiling",
]


def jd_tech_terms(requirements: Sequence[JdRequirement], lex: TechLexicon) -> frozenset[str]:
    """JD 全文涉及的技术词（canonical）。"""
    terms: set[str] = set()
    for req in requirements:
        terms |= lex.find(req.text)
    return frozenset(terms)


def resume_tech_terms(blocks: Sequence[ResumeBlock], lex: TechLexicon) -> frozenset[str]:
    """简历全文涉及的技术词（canonical）。"""
    terms: set[str] = set()
    for block in blocks:
        terms |= lex.find(block.text)
    return frozenset(terms)


def forbidden_terms_of(
    requirements: Sequence[JdRequirement],
    blocks: Sequence[ResumeBlock],
    lex: TechLexicon,
) -> tuple[str, ...]:
    """JD 有、简历没有的禁用词黑名单（技术词 + 同义短语 canonical 双通道）。

    与 L5 的注入检测保持一致：否则"微服务/高并发/性能优化"这类中文同义短语
    会成为模型可注入却不在黑名单里的漏网词。
    """
    jd_tech = jd_tech_terms(requirements, lex)
    resume_tech = resume_tech_terms(blocks, lex)
    jd_canon: set[str] = set()
    for req in requirements:
        jd_canon |= canonical_terms_in(req.text)
    resume_canon: set[str] = set()
    for block in blocks:
        resume_canon |= canonical_terms_in(block.text)
    return tuple(sorted((jd_tech - resume_tech) | (jd_canon - resume_canon)))


def block_coverage(block: ResumeBlock, jd_terms: frozenset[str], lex: TechLexicon) -> int:
    """块命中的 JD 技术词数量（用于重排排序）。"""
    return len(jd_terms & lex.find(block.text))


def seniority_ceiling(text: str) -> int:
    """源块观察到的最高职级档位；无职级词时为 -1。

    这是模型改写（未来 reword）的硬上限：改写不得把职级升到更高档。
    """
    role = extract_seniority(text).get("role", (-1, ""))
    return role[0]


def alignments_for(block: ResumeBlock, requirements: Sequence[JdRequirement], terms_by_req: dict[str, set[str]]) -> tuple[AlignmentPair, ...]:
    """按 JD 各要求项找术语对齐（确定性）。"""
    pairs: list[AlignmentPair] = []
    for req in requirements:
        terms = terms_by_req.get(req.requirement_id, set())
        for source, target, group_idx in find_alignments(block.text, sorted(terms)):
            pairs.append(AlignmentPair(source, target, req.requirement_id, group_idx))
    return tuple(pairs)


def plan_id_of(
    requirements: Sequence[JdRequirement],
    steps: Sequence[EditBrief],
    bullet_order: Sequence[str],
    forbidden: Sequence[str],
    extra: str = "",
    resume_content_hash: str = "",
    jd_content_hash: str = "",
    strategy_version: str = "",
) -> str:
    """生成确定性的 plan id（绑定简历/JD 内容哈希与策略版本，可附加指令哈希）。

    绑定内容哈希的意义：同一组 JD 要求 + 相同块结构，换一份简历内容就不能
    复用同一 planId——否则 Gate T 无法区分"这个计划批给哪份简历"。
    """
    parts: list[str] = []
    parts.append(f"resume:{resume_content_hash}")
    parts.append(f"jd:{jd_content_hash}")
    parts.append(f"strategy:{strategy_version}")
    for req in requirements:
        parts.append(f"req:{req.requirement_id}")
    for step in steps:
        align = ",".join(f"{a.source_phrase}>{a.target_phrase}" for a in step.alignments)
        parts.append(
            f"step:{step.block_id}:{step.operation.value}:{step.coverage}:"
            f"{step.seniority_ceiling}:{step.direction or ''}:{step.origin}:{align}"
        )
    parts.append("order:" + ",".join(bullet_order))
    parts.append("forbidden:" + ",".join(forbidden))
    if extra:
        parts.append("extra:" + extra)
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return "tailor-plan:" + digest


def build_jd_plan(
    *,
    requirements: Sequence[JdRequirement],
    blocks: Sequence[ResumeBlock],
    lexicon: TechLexicon | None = None,
    resume_content_hash: str = "",
    jd_content_hash: str = "",
    strategy_version: str = "",
) -> EditPlan:
    """根据 JD 要求生成改写计划（driver='jd_gap'）。

    Args:
        requirements: JD 要求项。
        blocks: 全部简历块。
        lexicon: 技术词词库；默认使用内置词库。
        resume_content_hash: 简历内容哈希（绑定 planId，防跨简历串用）。
        jd_content_hash: JD 内容哈希。
        strategy_version: 策略版本。

    Returns:
        EditPlan。所有 step 仅覆盖可改写块（``is_rewritable``）。
    """
    lex = lexicon or get_lexicon()
    jd_terms = jd_tech_terms(requirements, lex)
    forbidden = forbidden_terms_of(requirements, blocks, lex)

    gaps = analyze_gaps(requirements=requirements, blocks=blocks, lexicon=lex)
    terms_by_req = {gap.requirement_id: set(gap.requirement_terms) for gap in gaps}

    rewritable = [block for block in blocks if is_rewritable(block)]
    steps: list[EditBrief] = []
    for block in rewritable:
        alignments = alignments_for(block, requirements, terms_by_req)
        operation = (
            EditOperation.TERMINOLOGY_ALIGN if alignments else EditOperation.UNCHANGED
        )
        steps.append(
            EditBrief(
                block_id=block.block_id,
                operation=operation,
                alignments=alignments,
                coverage=block_coverage(block, jd_terms, lex),
                seniority_ceiling=seniority_ceiling(block.text),
            )
        )

    original_order = {block.block_id: index for index, block in enumerate(blocks)}
    bullet_order = tuple(
        block.block_id
        for block in sorted(
            rewritable,
            key=lambda b: (-block_coverage(b, jd_terms, lex), original_order[b.block_id]),
        )
    )

    rejected = tuple(
        (block.block_id, "not_rewritable")
        for block in blocks
        if not is_rewritable(block) and block_coverage(block, jd_terms, lex) > 0
    )

    return EditPlan(
        plan_id=plan_id_of(
            requirements,
            steps,
            bullet_order,
            forbidden,
            resume_content_hash=resume_content_hash,
            jd_content_hash=jd_content_hash,
            strategy_version=strategy_version,
        ),
        driver="jd_gap",
        steps=tuple(steps),
        bullet_order=bullet_order,
        forbidden_terms=forbidden,
        rejected=rejected,
    )
