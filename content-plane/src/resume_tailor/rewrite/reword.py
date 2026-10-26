"""模型改写（L4 的 reword）——模型的"笼子"。

这里的核心不是"让模型改得好"，而是**无论模型输出什么，都进不了臆造**：

1. 模型永远看不到 JD 全文，只看到单条源句 + 中性改写指令；
2. 模型输出先解析、再逐条过 L5 事实锚点校验（防**新增**臆造）；
3. 再做过**事实保留**检查（防**删减**源里已有的量化/技术事实）；
4. 任一不过 → 回退原文（fail-closed），绝不采用模型版本。

因此未来接入 Ollama / 云端模型时，它既无法把 JD 要求但简历没有的技术词塞进来、
无法凭空造数字、无法把"参与"写成"主导"（L5 拦截），也无法把"320ms 降至 90ms"
悄悄删成"优化了性能"（事实保留拦截）。

JD 匹配由确定性的缺口分析（L2）与计划（L3，术语对齐/黑名单/重排）完成；
reword 只负责"把一条既定事实表达得更好"，两者职责分离。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from ..domain.contracts import (
    FactUnitClass,
    ResumeBlock,
    RewriteProposal,
    RewrittenBlock,
    Verdict,
    VerdictDecision,
)
from ..lexicon.tech import TechLexicon, get_lexicon
from ..plan.intent import is_rewritable
from ..verify.fact_units import canonical_metric, extract_fact_units
from ..verify.verifier import verify_edit

__all__ = [
    "RewordModel",
    "build_reword_prompt",
    "extract_rewritten_text",
    "fact_retention_ok",
    "propose_block",
    "propose_blocks",
    "reword_block",
    "reword_blocks",
]


class RewordModel(Protocol):
    """可插拔的改写模型接口。

    实现只需一个方法：给定**提示词**返回改写文本。未来接 Ollama / 云端，
    写一个 ``reword`` 方法即可；提示词由 ``reword_block`` 统一构建（保证
    不含 JD），门禁（L5 + 事实保留）由 ``reword_block`` 统一兜底。
    """

    def reword(self, prompt: str) -> str:
        """给定提示词，返回改写后的文本。

        Args:
            prompt: 由 ``build_reword_prompt`` 构建的中性改写提示词。

        Returns:
            改写后的文本。
        """
        ...


_SYSTEM = (
    "你是简历改写助手。只改写下面这一条工作经历，使其表达更清晰、更精炼，"
    "但不得改变任何事实。\n"
    "严格约束，违反任何一条都算失败：\n"
    "- 职级动词（负责/参与/主导/协助/熟悉/掌握/精通等）必须与原文完全一致，一字不改；\n"
    "- 不得新增或删除任何数字、时间、公司名、技术名词；\n"
    "- 保持原语言；\n"
    "- 只输出改写后的这一句话，不要解释、不要加引号。"
)

_CODE_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)

# 指令目标 -> 中性改写方向。方向只指导"表达"，不提供 JD 技能、不暗示升职级，
# 因此仍安全；事实门禁（L5 + 保留）不变。
_DIRECTION_PROMPT: dict[str, str] = {
    "emphasize": "突出其中已有的量化结果与关键能力",
    "deemphasize": "弱化非核心、与目标岗位关联弱的表述",
    "condense": "精简冗余表述，保留全部事实",
    "expand": "在事实范围内把表达写得更完整",
    "reword": "润色措辞，使其更清晰、更精炼",
    "reorder": "调整语序，使关键信息前置",
}


def build_reword_prompt(source_text: str, direction: str | None = None) -> str:
    """构建改写提示词。

    **刻意不含 JD 全文、不含黑名单、不含职级上限的数值。** 模型只做局部
    表达润色；JD 匹配已由确定性流程完成。这样模型既没机会抄 JD 技能，
    也没机会知道"该往哪升"——它能做的边界由提示词划死，违反则由门禁拦截。

    ``direction`` 是指令解析出的目标（口径化），只加一句中性方向；不含任何
    JD 内容，也不放宽事实约束。

    Args:
        source_text: 单条 bullet 原文。
        direction: 可选改写方向（IntentGoal 值）。

    Returns:
        完整提示词。
    """
    if direction and direction in _DIRECTION_PROMPT:
        hint = f"\n\n改写方向：{_DIRECTION_PROMPT[direction]}。"
    else:
        hint = ""
    return f"{_SYSTEM}{hint}\n\n原文：\n{source_text}"


def extract_rewritten_text(raw: str) -> str:
    """从模型输出里取回改写文本，容错常见包裹（引号/代码块/空行）。

    只取第一行：模型若多输出解释，后续一律丢弃。

    Args:
        raw: 模型原始输出。

    Returns:
        清洗后的单句文本；为空时返回空字符串。
    """
    text = _CODE_FENCE.sub("", raw or "")
    text = text.strip().strip('"\'“”')
    if not text:
        return ""
    return text.splitlines()[0].strip()


def _metric_keys(text: str, lex: TechLexicon) -> set[tuple[str, str]]:
    """抽取文本中的 (数值, 量纲) 集合（含量化指标与时长时间）。

    注意与 ``verify.verifier._metric_keys`` 保持一致：量化指标（METRIC）与
    时长（TIME，如 8 分钟）都要纳入，否则"8 分钟改成 3 分钟"这类时长篡改
    会逃过事实保留检查。
    """
    keys: set[tuple[str, str]] = set()
    for unit in extract_fact_units(text, lex):
        if unit.unit_class in (FactUnitClass.METRIC, FactUnitClass.TIME):
            key = canonical_metric(unit.text)
            if key is not None:
                keys.add(key)
    return keys


def _proper_nouns(text: str, lex: TechLexicon) -> set[str]:
    """抽取机构类专有名词（公司/学校/实验室等），用于防删减。"""
    return {
        unit.text
        for unit in extract_fact_units(text, lex)
        if unit.unit_class is FactUnitClass.PROPER_NOUN
    }


def fact_retention_ok(source: ResumeBlock, candidate: str, lex: TechLexicon) -> bool:
    """检查候选是否**保留了源块的全部量化、技术、机构事实**（防删减）。

    量化指标 + 时长 + 技术词 + 机构专有名词（公司/学校）都要保留——它们是
    "不夸大/不缩水"最该守住的硬事实。日期通常在不可改写的 meta/教育块，职级
    由 L5 的升级检测负责（降级按 M1 语义视为可接受）。

    Args:
        source: 源块。
        candidate: 改写文本。
        lex: 技术词词库。

    Returns:
        源块的量化指标、技术词与机构专有名词全部保留时返回 True。
    """
    if not (_metric_keys(source.text, lex) <= _metric_keys(candidate, lex)):
        return False
    if not (lex.find(source.text) <= lex.find(candidate)):
        return False
    if not (_proper_nouns(source.text, lex) <= _proper_nouns(candidate, lex)):
        return False
    return True


def reword_block(
    *,
    source_block: ResumeBlock,
    model: RewordModel | None,
    jd_text: str = "",
    lexicon: TechLexicon | None = None,
    direction: str | None = None,
) -> RewrittenBlock:
    """改写一个块，并过双重门禁；任一不过则回退原文。

    门禁顺序：解析 -> L5 锚点校验（防臆造/注入/升级）-> 事实保留（防删减）。

    Args:
        source_block: 待改写的源块（用于锚定）。
        model: 改写模型；为 None 时直接返回原文（不 reword）。
        jd_text: JD 全文，仅用于 L5 的注入检测，**不进入提示词**。
        lexicon: 技术词词库。
        direction: 可选改写方向（IntentGoal 值），只影响提示词表达。

    Returns:
        RewrittenBlock；模型输出被采纳时 ``changed`` 为 True，否则原文不变。
    """
    if model is None:
        return RewrittenBlock(source_block.block_id, source_block.text, source_block.text)

    lex = lexicon or get_lexicon()
    try:
        raw = model.reword(build_reword_prompt(source_block.text, direction))
    except Exception:
        # 模型不可达/超时/崩溃：fail-closed，保留原文，绝不因模型故障丢简历内容。
        return RewrittenBlock(source_block.block_id, source_block.text, source_block.text)
    candidate = extract_rewritten_text(raw)
    if not candidate or candidate == source_block.text:
        return RewrittenBlock(source_block.block_id, source_block.text, source_block.text)

    verdict = verify_edit(
        source_blocks=[source_block],
        candidate_text=candidate,
        jd_text=jd_text,
        lexicon=lex,
    )
    if verdict.decision is not VerdictDecision.ACCEPT:
        return RewrittenBlock(source_block.block_id, source_block.text, source_block.text)

    if not fact_retention_ok(source_block, candidate, lex):
        return RewrittenBlock(source_block.block_id, source_block.text, source_block.text)

    return RewrittenBlock(source_block.block_id, source_block.text, candidate)


def reword_blocks(
    *,
    blocks: Sequence[ResumeBlock],
    model: RewordModel | None = None,
    jd_text: str = "",
    lexicon: TechLexicon | None = None,
    direction_by_id: dict[str, str] | None = None,
) -> tuple[RewrittenBlock, ...]:
    """对全部可改写块执行 reword（保持传入顺序），每条过双重门禁。

    不可改写块（技能行/教育背景等）原样保留，模型接触不到它们。
    ``model`` 为 None 时不做任何 reword（等价于只做确定性改写）。

    Args:
        blocks: 全部简历块。
        model: 改写模型；None 表示不 reword。
        jd_text: JD 全文，仅用于注入检测。
        lexicon: 技术词词库。
        direction_by_id: block_id -> 改写方向（IntentGoal 值），可选。

    Returns:
        RewrittenBlock 元组，顺序与 ``blocks`` 一致。
    """
    directions = direction_by_id or {}
    out: list[RewrittenBlock] = []
    for block in blocks:
        if not is_rewritable(block):
            out.append(RewrittenBlock(block.block_id, block.text, block.text))
            continue
        out.append(
            reword_block(
                source_block=block,
                model=model,
                jd_text=jd_text,
                lexicon=lexicon,
                direction=directions.get(block.block_id),
            )
        )
    return tuple(out)


def propose_block(
    *,
    source_block: ResumeBlock,
    model: RewordModel | None,
    jd_text: str = "",
    lexicon: TechLexicon | None = None,
    direction: str | None = None,
) -> RewriteProposal:
    """生成一条改写提案（**不 fail-closed**）。

    与 ``reword_block`` 的区别：模型输出无论是否通过校验都保留为候选，
    校验结论挂在 ``verdict`` 与 ``facts_retained`` 上，交由 L6 评审决定
    接受 / 拒绝 / 声明事实。模型不可达或无模型时，提案即原文（changed=False）。

    Args:
        source_block: 待改写的源块。
        model: 改写模型；None 时提案即原文。
        jd_text: JD 全文，仅用于注入检测。
        lexicon: 技术词词库。
        direction: 可选改写方向（IntentGoal 值）。

    Returns:
        RewriteProposal。
    """
    lex = lexicon or get_lexicon()
    if model is None:
        return RewriteProposal(source_block.block_id, source_block.text, source_block.text, Verdict(), True)

    try:
        raw = model.reword(build_reword_prompt(source_block.text, direction))
    except Exception:
        return RewriteProposal(source_block.block_id, source_block.text, source_block.text, Verdict(), True)

    candidate = extract_rewritten_text(raw)
    if not candidate or candidate == source_block.text:
        return RewriteProposal(source_block.block_id, source_block.text, source_block.text, Verdict(), True)

    verdict = verify_edit(
        source_blocks=[source_block],
        candidate_text=candidate,
        jd_text=jd_text,
        lexicon=lex,
    )
    retained = fact_retention_ok(source_block, candidate, lex)
    return RewriteProposal(source_block.block_id, source_block.text, candidate, verdict, retained)


def propose_blocks(
    *,
    blocks: Sequence[ResumeBlock],
    model: RewordModel | None = None,
    jd_text: str = "",
    lexicon: TechLexicon | None = None,
    direction_by_id: dict[str, str] | None = None,
) -> tuple[RewriteProposal, ...]:
    """对全部块生成提案（保持顺序，不 fail-closed）。

    不可改写块（技能行/教育背景等）提案即原文，模型接触不到它们。

    Args:
        blocks: 全部简历块。
        model: 改写模型；None 表示不产生任何改写提案。
        jd_text: JD 全文，仅用于注入检测。
        lexicon: 技术词词库。
        direction_by_id: block_id -> 改写方向（IntentGoal 值），可选。

    Returns:
        RewriteProposal 元组，顺序与 ``blocks`` 一致。
    """
    directions = direction_by_id or {}
    out: list[RewriteProposal] = []
    for block in blocks:
        if not is_rewritable(block):
            out.append(RewriteProposal(block.block_id, block.text, block.text, Verdict(), True))
            continue
        out.append(
            propose_block(
                source_block=block,
                model=model,
                jd_text=jd_text,
                lexicon=lexicon,
                direction=directions.get(block.block_id),
            )
        )
    return tuple(out)
