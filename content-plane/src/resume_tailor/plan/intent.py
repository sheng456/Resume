"""指令解析（L3 的入口）。

把用户的一句自然语言指令解析成结构化的 ``TailorIntent``：**只描述范围与
目标，绝不产出文本**。文本一律由 L4 生成并受 L5 校验——这样"指令"就不可能
成为绕过事实门禁的通道。

三条边界（对应 ``docs/ARCHITECTURE.md`` §5.3）：

1. 只产出 ``scope`` 与 ``goal``；
2. 解析置信度低时必须澄清，不得猜测后直接生成计划；
3. 指令要求写入简历没有的事实时，本层**不拦也不照做**，交给 L5 统一拦截，
   避免两处规则分叉。

M1 是规则解析（无模型），因此对模糊指令天然保守：识别不到明确目标就判低置信度。

错误码优先级
------------

低置信度与缺口冲突可能同时出现——"弱化 Java"在 Java 只出现于技能行时就是这样。
此时调用方应**先报** ``tailor_instruction_ambiguous``：指令还没解析清楚、没有
可执行的范围，此时报冲突为时尚早。但冲突信息仍保留在返回值里一并展示，
让用户一次看到全部问题，避免来回试探。

改写范围不受指令扩张
--------------------

``is_rewritable`` 是一条独立于事实门禁的边界：指令不能把可改写范围撑大。
没有它，"突出 Kafka 那条"会因为技能行也含 Kafka 而把技能列表一起纳入，
而改写技能列表正是 JD 注入最容易得手的地方。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from ..domain.contracts import (
    BlockKind,
    GapItem,
    IntentGoal,
    ParseConfidence,
    ResumeBlock,
    Section,
    TailorIntent,
)
from ..lexicon.tech import TechLexicon, get_lexicon
from .conflict import detect_gap_conflicts

__all__ = ["GOAL_PATTERNS", "SECTION_KEYWORDS", "build_intent", "parse_instruction"]

#: 目标词表。**顺序即优先级**，用于同一位置命中多个目标时打破平局。
GOAL_PATTERNS: tuple[tuple[IntentGoal, tuple[str, ...]], ...] = (
    (IntentGoal.EMPHASIZE, ("突出", "强调", "着重", "重点", "放大", "凸显", "加强")),
    (IntentGoal.DEEMPHASIZE, ("弱化", "淡化", "少提", "别提", "省略", "去掉", "删掉", "不重要")),
    (IntentGoal.CONDENSE, ("精简", "压缩", "缩短", "简洁", "简短", "短一点", "减少字数")),
    (IntentGoal.EXPAND, ("展开", "补充", "详细", "丰富", "多写", "加长")),
    (IntentGoal.REWORD, ("润色", "改写", "措辞", "表达", "专业", "流畅", "通顺")),
    (IntentGoal.REORDER, ("排序", "前移", "挪到", "调到前面", "调整顺序", "放在最前")),
)

#: 章节词表。会话里说"项目经历"和说"项目"都指向 PROJECT。
SECTION_KEYWORDS: dict[Section, tuple[str, ...]] = {
    Section.SUMMARY: ("个人总结", "个人简介", "自我介绍", "总结", "概述"),
    Section.EDUCATION: ("教育背景", "教育经历", "教育", "学历"),
    Section.WORK: ("工作经历", "工作经验", "任职"),
    Section.PROJECT: ("项目经历", "项目经验", "项目"),
    Section.SKILL: ("专业技能", "技能", "技术栈"),
    Section.AWARD: ("奖项", "荣誉", "获奖"),
}

#: 低置信度时给出的澄清候选（最多展示这么多个）。
_MAX_CLARIFICATION_OPTIONS = 4

#: 允许被改写的章节。``docs/ARCHITECTURE.md`` §5.1：改写只允许作用在
#: summary / work / project 的 bullet 上；教育背景、联系方式、日期一律不可改。
REWRITABLE_SECTIONS: frozenset[Section] = frozenset({Section.SUMMARY, Section.WORK, Section.PROJECT})


def is_rewritable(block: ResumeBlock) -> bool:
    """判断一个块是否允许被改写。

    这是一条**独立于事实门禁**的边界：指令不能把可改写范围撑大。
    没有它，"突出 Kafka 那条"会因为技能行也含 Kafka 而把技能列表一起纳入
    改写范围——而改写技能列表正是 JD 注入最容易得手的地方。

    Args:
        block: 待判断的块。

    Returns:
        允许改写时返回 True。
    """
    return (
        not block.immutable
        and block.kind is BlockKind.BULLET
        and block.section in REWRITABLE_SECTIONS
    )


def _detect_goal(instruction: str) -> IntentGoal | None:
    """按"最早出现优先、同级按词表顺序"选出目标。

    Args:
        instruction: 用户指令原文。

    Returns:
        命中的目标；无命中时返回 None。
    """
    best: tuple[int, int, IntentGoal] | None = None
    for priority, (goal, keywords) in enumerate(GOAL_PATTERNS):
        for keyword in keywords:
            index = instruction.find(keyword)
            if index < 0:
                continue
            candidate = (index, priority, goal)
            if best is None or candidate[:2] < best[:2]:
                best = candidate
    return None if best is None else best[2]


def _detect_scope(
    instruction: str,
    blocks: Sequence[ResumeBlock],
    lexicon: TechLexicon,
) -> tuple[tuple[Section, ...], tuple[str, ...], tuple[str, ...]]:
    """解析指令的作用范围：章节 + 具体块。

    Args:
        instruction: 用户指令原文。
        blocks: 全部候选块。
        lexicon: 技术词词库。

    Returns:
        ``(命中的章节, 命中的块 id, 只出现在不可改写块里的技术词)``。
        第三项用于把"你说的东西不可改写"这件事讲清楚，而不是笼统地
        回一句"要改哪一部分"。
    """
    sections: list[Section] = []
    for section, keywords in SECTION_KEYWORDS.items():
        if any(keyword in instruction for keyword in keywords):
            sections.append(section)

    mentioned_tech = lexicon.find(instruction)
    block_ids: list[str] = []
    blocked_tech: list[str] = []
    if mentioned_tech:
        for block in blocks:
            if is_rewritable(block) and lexicon.find(block.text) & mentioned_tech:
                block_ids.append(block.block_id)
        for tech in sorted(mentioned_tech):
            in_rewritable = any(
                is_rewritable(block) and tech in lexicon.find(block.text) for block in blocks
            )
            in_non_rewritable = any(
                not is_rewritable(block) and tech in lexicon.find(block.text) for block in blocks
            )
            if in_non_rewritable and not in_rewritable:
                blocked_tech.append(tech)

    return tuple(sections), tuple(block_ids), tuple(blocked_tech)


def _clarification_options(
    goal: IntentGoal | None,
    sections: Sequence[Section],
    tech_without_rewritable_block: Sequence[str],
) -> tuple[str, ...]:
    """在低置信度时给出可选的澄清方向。

    Args:
        goal: 已识别的目标，可能为 None。
        sections: 已识别的章节。
        tech_without_rewritable_block: 被点名、但只出现在不可改写块
            （技能行、教育背景等）里的技术词。这种情况必须**说清原因**——
            否则用户只会看到"要改哪一部分？"，而他明明已经说了要改什么。

    Returns:
        澄清候选项。
    """
    options: list[str] = []

    if tech_without_rewritable_block:
        names = "、".join(tech_without_rewritable_block)
        options.append(
            f"你点名的 {names} 只出现在技能行等不可改写的位置。要改的是哪一条经历？"
        )

    if goal is None:
        options.extend(
            [
                "你想改的方向是什么？（突出某段 / 精简字数 / 润色措辞 / 调整顺序）",
                "或者直接说明要改哪一条经历",
            ]
        )
    if not sections and not tech_without_rewritable_block:
        options.append("要改哪一部分？（工作经历 / 项目经历 / 专业技能 / 个人总结）")

    return tuple(options[:_MAX_CLARIFICATION_OPTIONS])


def _intent_id(instruction: str, goal: IntentGoal | None, sections: Sequence[Section], block_ids: Sequence[str]) -> str:
    """生成确定性的意图 id。

    同样的指令 + 同样的范围必须得到同样的 id，否则 Gate T 的审批对象不确定。
    """
    payload = "\n".join(
        [
            instruction.strip(),
            goal.value if goal else "",
            ",".join(section.value for section in sections),
            ",".join(block_ids),
        ]
    )
    return "intent:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_instruction(
    instruction: str,
    *,
    blocks: Sequence[ResumeBlock],
    instruction_id: str | None = None,
    lexicon: TechLexicon | None = None,
) -> TailorIntent:
    """把一句指令解析成结构化意图（不含缺口冲突）。

    Args:
        instruction: 用户指令原文。
        blocks: 全部候选块。
        instruction_id: 指令的稳定 id；缺省时由内容哈希派生。
        lexicon: 技术词词库；默认使用内置词库。

    Returns:
        TailorIntent。``goal`` 与范围同时命中时为 HIGH，否则为 LOW 并附带
        澄清候选——调用方在 LOW 时**不得**继续生成计划。
    """
    lex = lexicon or get_lexicon()
    text = (instruction or "").strip()

    goal = _detect_goal(text)
    sections, block_ids, blocked_tech = _detect_scope(text, blocks, lex)

    has_scope = bool(sections or block_ids)
    confidence = ParseConfidence.HIGH if (goal is not None and has_scope) else ParseConfidence.LOW
    options = () if confidence is ParseConfidence.HIGH else _clarification_options(goal, sections, blocked_tech)

    return TailorIntent(
        intent_id=_intent_id(text, goal, sections, block_ids),
        instruction_id=instruction_id or ("instruction:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]),
        goal=goal,
        scope_block_ids=block_ids,
        scope_sections=sections,
        parse_confidence=confidence,
        conflicts_with_gap=(),
        clarification_options=options,
    )


def build_intent(
    instruction: str,
    *,
    blocks: Sequence[ResumeBlock],
    gap_items: Sequence[GapItem] = (),
    instruction_id: str | None = None,
    lexicon: TechLexicon | None = None,
) -> TailorIntent:
    """解析指令并检测它与 JD 缺口的冲突。

    冲突**不改变**意图本身，只是如实记录，由调用方返回
    ``tailor_instruction_conflicts_with_gap`` 交用户裁决——本函数绝不
    静默地把指令改写成 JD 的方向。

    Args:
        instruction: 用户指令原文。
        blocks: 全部候选块。
        gap_items: JD 缺口项。
        instruction_id: 指令的稳定 id。
        lexicon: 技术词词库。

    Returns:
        填好 ``conflicts_with_gap`` 的 TailorIntent。
    """
    lex = lexicon or get_lexicon()
    intent = parse_instruction(instruction, blocks=blocks, instruction_id=instruction_id, lexicon=lex)
    conflicts = detect_gap_conflicts(
        intent=intent,
        instruction_text=instruction,
        gap_items=gap_items,
        lexicon=lex,
    )
    if not conflicts:
        return intent
    return TailorIntent(
        intent_id=intent.intent_id,
        instruction_id=intent.instruction_id,
        goal=intent.goal,
        scope_block_ids=intent.scope_block_ids,
        scope_sections=intent.scope_sections,
        parse_confidence=intent.parse_confidence,
        conflicts_with_gap=conflicts,
        clarification_options=intent.clarification_options,
    )
