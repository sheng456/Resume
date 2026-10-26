"""统一的计划生成入口：指令驱动优先，JD 规则兜底。

对应 `docs/ARCHITECTURE.md` §5.3：

- 无指令 -> JD 缺口规则（``driver='jd_gap'``）；
- 有指令且高置信度、无缺口冲突 -> 指令驱动（``driver='instruction'``）；
- 有指令但解析置信度低 -> 要求澄清，不生成计划；
- 有指令但与 JD 缺口方向冲突 -> 报冲突，不生成计划。

本模块绝不静默地把指令改写成 JD 的方向，也不在指令歧义时猜一个计划。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..diagnose.gap import analyze_gaps
from ..domain.contracts import (
    EditBrief,
    EditOperation,
    EditPlan,
    IntentConflict,
    JdRequirement,
    ResumeBlock,
)
from ..lexicon.tech import TechLexicon, get_lexicon
from ..store.identity import sha256_hex
from .intent import ParseConfidence, build_intent, is_rewritable
from .jd_plan import (
    alignments_for,
    block_coverage,
    build_jd_plan,
    forbidden_terms_of,
    jd_tech_terms,
    plan_id_of,
    seniority_ceiling,
)

__all__ = ["PlanResult", "build_plan"]


@dataclass(frozen=True)
class PlanResult:
    """计划生成结果：成功时含 plan，否则含澄清项或冲突。"""

    plan: EditPlan | None = None
    clarification_options: tuple[str, ...] = ()
    conflicts: tuple[IntentConflict, ...] = ()

    @property
    def ok(self) -> bool:
        """是否成功生成计划。"""
        return self.plan is not None

    @property
    def ambiguous(self) -> bool:
        """是否需要澄清（低置信度）。"""
        return self.plan is None and bool(self.clarification_options)

    @property
    def has_conflict(self) -> bool:
        """是否与 JD 缺口冲突。"""
        return bool(self.conflicts)


def build_plan(
    *,
    requirements: Sequence[JdRequirement],
    blocks: Sequence[ResumeBlock],
    instruction: str | None = None,
    lexicon: TechLexicon | None = None,
    resume_content_hash: str = "",
    jd_content_hash: str = "",
    strategy_version: str = "",
) -> PlanResult:
    """生成改写计划（指令驱动优先，JD 兜底）。

    Args:
        requirements: JD 要求项。
        blocks: 全部简历块。
        instruction: 用户指令原文；None/空白则走 JD 兜底。
        lexicon: 技术词词库。
        resume_content_hash: 简历内容哈希（绑定 planId）。
        jd_content_hash: JD 内容哈希。
        strategy_version: 策略版本。

    Returns:
        PlanResult；歧义/冲突时 ``plan`` 为 None。
    """
    lex = lexicon or get_lexicon()
    text = (instruction or "").strip()

    if not text:
        return PlanResult(
            plan=build_jd_plan(
                requirements=requirements,
                blocks=blocks,
                lexicon=lex,
                resume_content_hash=resume_content_hash,
                jd_content_hash=jd_content_hash,
                strategy_version=strategy_version,
            )
        )

    gaps = analyze_gaps(requirements=requirements, blocks=blocks, lexicon=lex)
    intent = build_intent(text, blocks=blocks, gap_items=gaps, lexicon=lex)

    if intent.parse_confidence is ParseConfidence.LOW:
        # 歧义优先于冲突（没有可执行范围时，报冲突为时尚早），
        # 但冲突信息仍一并保留，供上层一次性展示全部问题。
        return PlanResult(
            clarification_options=intent.clarification_options,
            conflicts=intent.conflicts_with_gap,
        )
    if intent.conflicts_with_gap:
        return PlanResult(conflicts=intent.conflicts_with_gap)

    return PlanResult(
        plan=_build_instruction_plan(
            intent=intent,
            instruction_text=text,
            requirements=requirements,
            blocks=blocks,
            lex=lex,
            resume_content_hash=resume_content_hash,
            jd_content_hash=jd_content_hash,
            strategy_version=strategy_version,
        )
    )


def _build_instruction_plan(
    *,
    intent,
    instruction_text: str,
    requirements: Sequence[JdRequirement],
    blocks: Sequence[ResumeBlock],
    lex: TechLexicon,
    resume_content_hash: str,
    jd_content_hash: str,
    strategy_version: str,
) -> EditPlan:
    """把已解析的指令意图落成计划。"""
    jd_terms = jd_tech_terms(requirements, lex)
    forbidden = forbidden_terms_of(requirements, blocks, lex)

    gaps = analyze_gaps(requirements=requirements, blocks=blocks, lexicon=lex)
    terms_by_req = {gap.requirement_id: set(gap.requirement_terms) for gap in gaps}

    # 范围：显式 block + 章节内所有可改写块
    scope_ids = set(intent.scope_block_ids)
    if intent.scope_sections:
        section_set = set(intent.scope_sections)
        scope_ids |= {block.block_id for block in blocks if block.section in section_set}

    rewritable = [block for block in blocks if is_rewritable(block)]
    steps: list[EditBrief] = []
    for block in rewritable:
        alignments = alignments_for(block, requirements, terms_by_req)
        in_scope = block.block_id in scope_ids
        direction = intent.goal.value if in_scope else None
        origin = "instruction" if in_scope else "jd_gap"

        if alignments:
            operation = EditOperation.TERMINOLOGY_ALIGN
        elif in_scope:
            operation = EditOperation.REWORD
        else:
            operation = EditOperation.UNCHANGED

        steps.append(
            EditBrief(
                block_id=block.block_id,
                operation=operation,
                alignments=alignments,
                coverage=block_coverage(block, jd_terms, lex),
                seniority_ceiling=seniority_ceiling(block.text),
                direction=direction,
                origin=origin,
            )
        )

    original_order = {block.block_id: index for index, block in enumerate(blocks)}
    # 指令命中的块优先，其次按 JD 覆盖度
    bullet_order = tuple(
        block.block_id
        for block in sorted(
            rewritable,
            key=lambda b: (
                b.block_id not in scope_ids,
                -block_coverage(b, jd_terms, lex),
                original_order[b.block_id],
            ),
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
            extra=intent.intent_id,
            resume_content_hash=resume_content_hash,
            jd_content_hash=jd_content_hash,
            strategy_version=strategy_version,
        ),
        driver="instruction",
        steps=tuple(steps),
        bullet_order=bullet_order,
        forbidden_terms=forbidden,
        rejected=rejected,
        intent_id=intent.intent_id,
        instruction_hash=sha256_hex(instruction_text),
    )
