"""指令与 JD 缺口的冲突检测。

对应 ``docs/ARCHITECTURE.md`` §1.5 的第一条冲突规则：

> 指令优先于 JD，但冲突必须显式暴露。……**不得静默按 JD 改**。

典型场景：用户说"弱化后端相关的技术栈"，而目标岗位恰恰是后端岗，且简历在
后端能力上存在缺口。系统不能替用户决定听谁的——只能把两侧依据摆出来。

判定条件（三条同时成立才算冲突）：

1. 指令目标是"弱化/精简"这类**做减法**的方向（做加法不会与缺口冲突）；
2. 指令里点名了某个技术词；
3. 存在一个**未覆盖**的 JD 要求项，其 ``requirement_terms`` 与点名的词相交。
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.contracts import (
    Coverage,
    GapItem,
    IntentConflict,
    IntentGoal,
    TailorIntent,
)
from ..lexicon.tech import TechLexicon, get_lexicon

__all__ = ["detect_gap_conflicts"]

#: 只有做减法的方向才可能与 JD 缺口冲突。
_CONFLICTING_GOALS = frozenset({IntentGoal.DEEMPHASIZE, IntentGoal.CONDENSE})


def detect_gap_conflicts(
    *,
    intent: TailorIntent,
    instruction_text: str,
    gap_items: Sequence[GapItem],
    lexicon: TechLexicon | None = None,
) -> tuple[IntentConflict, ...]:
    """找出指令方向与 JD 缺口方向相反的要求项。

    Args:
        intent: 已解析的意图（用其 ``goal``）。
        instruction_text: 用户指令原文（用于取点名技术词）。
        gap_items: JD 缺口项。
        lexicon: 技术词词库；默认使用内置词库。

    Returns:
        冲突元组；无冲突时为空元组。
    """
    if intent.goal is None or intent.goal not in _CONFLICTING_GOALS:
        return ()

    lex = lexicon or get_lexicon()
    mentioned = lex.find(instruction_text)
    if not mentioned:
        return ()

    conflicts: list[IntentConflict] = []
    for gap in gap_items:
        if gap.coverage is not Coverage.MISSING:
            continue
        overlap = mentioned & set(gap.requirement_terms)
        if not overlap:
            continue
        conflicts.append(
            IntentConflict(
                requirement_id=gap.requirement_id,
                gap_direction=f"missing:{gap.label}",
                instruction_direction=f"{intent.goal.value}:{','.join(sorted(overlap))}",
            )
        )
    return tuple(conflicts)
