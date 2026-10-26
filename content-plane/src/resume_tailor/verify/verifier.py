"""事实锚点校验器（L5）。

这是整套设计的技术核心：改写的每一句都必须能追溯到简历原文，或追溯到
用户**显式声明**的事实。它不调用任何模型，是纯确定性代码，因此可被
穷举测试与复现。

四条判定：

- ``anchored``    事实单元能在被引用源块或用户声明中找到；
- ``abstracted``  等价或降级变换（负责 -> 参与、精通 -> 熟悉）通过；
- ``upgraded``    能力升级（参与 -> 主导、熟悉 -> 精通）必须用户逐条确认；
- ``unsupported`` 任何白名单都找不到，默认不落盘。

一条硬门禁：

- **JD 注入**：JD 要求、但简历原文与用户声明都没有的技术词，出现在改写
  文本里即 ``reject``，用户无法通过确认绕过。这条规则的意义是——
  不允许因为岗位要求 Kubernetes 就把 Kubernetes 写进简历。
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.contracts import (
    AnchorStatus,
    DeclaredFact,
    FactUnit,
    FactUnitClass,
    ResumeBlock,
    Verdict,
    VerdictDecision,
)
from ..lexicon.tech import TechLexicon, get_lexicon
from ..lexicon.synonyms import canonical_terms_in
from .fact_units import (
    canonical_metric,
    extract_fact_units,
    extract_seniority,
    normalize_text,
)

__all__ = ["verify_edit"]

_REPLACEMENT_CHAR = "\ufffd"

# 需要用户确认的状态：unsupported（无源）与 upgraded（能力升级）。
_NEEDS_CONFIRMATION = frozenset({AnchorStatus.UNSUPPORTED, AnchorStatus.UPGRADED})


def _metric_keys(text: str, lexicon: TechLexicon) -> set[tuple[str, str]]:
    """抽取文本中的 (数值, 单位) 集合。"""
    keys: set[tuple[str, str]] = set()
    for unit in extract_fact_units(text, lexicon):
        if unit.unit_class in (FactUnitClass.METRIC, FactUnitClass.TIME):
            key = canonical_metric(unit.text)
            if key is not None:
                keys.add(key)
    return keys


def _find_anchor_block(raw: str, blocks: Sequence[ResumeBlock]) -> str | None:
    """找出包含该原文片段的源块 id。"""
    needle = normalize_text(raw)
    for block in blocks:
        if needle and needle in normalize_text(block.text):
            return block.block_id
    return None


def _detect_tech_gluing(text: str, lexicon: TechLexicon) -> tuple[str, ...]:
    """检测技术词粘连（如 ``JavaSpring BootMySQL``）。

    这是实测中真实出现过的损坏形态：PDF 提取丢失中文顿号后，
    相邻技术词之间不再有任何分隔符，技能段的匹配会整体失效。
    """
    return lexicon.find_glued(text)


def verify_edit(
    *,
    source_blocks: Sequence[ResumeBlock],
    candidate_text: str,
    jd_text: str = "",
    declared_facts: Sequence[DeclaredFact] = (),
    lexicon: TechLexicon | None = None,
) -> Verdict:
    """校验一条改写文本是否可追溯到源简历。

    Args:
        source_blocks: 该改写被声明引用（``cites``）的源块。通常是一条
            bullet 的源块，或其所在段落。
        candidate_text: 改写后的文本。
        jd_text: 目标岗位 JD 全文，用于 JD 注入检测。
        declared_facts: 用户显式声明的事实，是唯一的"无源事实"入口。
        lexicon: 技术词词库；默认使用内置词库。

    Returns:
        Verdict，包含逐单元判定、JD 注入列表、ATS 提示与整条裁决。
    """
    lex = lexicon or get_lexicon()

    source_blob = normalize_text(" ".join(block.text for block in source_blocks))
    declared_blob = normalize_text(" ".join(fact.text for fact in declared_facts))

    source_metrics = _metric_keys(source_blob, lex)
    declared_metrics = _metric_keys(declared_blob, lex)
    source_tech = lex.find(source_blob)
    declared_tech = lex.find(declared_blob)

    source_seniority = extract_seniority(source_blob)
    declared_seniority = extract_seniority(declared_blob)

    results: list[FactUnit] = []

    # ---- 量化 / 时间 / 技术词 / 专有名词 ----
    for raw in extract_fact_units(candidate_text, lex):
        if raw.unit_class in (FactUnitClass.METRIC, FactUnitClass.TIME):
            key = canonical_metric(raw.text)
            if key is not None and key in source_metrics:
                results.append(
                    FactUnit(raw.text, raw.unit_class, AnchorStatus.ANCHORED, _find_anchor_block(raw.text, source_blocks))
                )
            elif key is not None and key in declared_metrics:
                results.append(FactUnit(raw.text, raw.unit_class, AnchorStatus.ANCHORED, _declared_ref(raw.text, declared_facts)))
            else:
                results.append(FactUnit(raw.text, raw.unit_class, AnchorStatus.UNSUPPORTED, None, "metric_not_in_source"))

        elif raw.unit_class is FactUnitClass.TECH:
            if raw.text in source_tech:
                results.append(
                    FactUnit(raw.text, raw.unit_class, AnchorStatus.ANCHORED, _find_anchor_block(raw.text, source_blocks))
                )
            elif raw.text in declared_tech:
                results.append(FactUnit(raw.text, raw.unit_class, AnchorStatus.ANCHORED, _declared_ref(raw.text, declared_facts)))
            else:
                results.append(FactUnit(raw.text, raw.unit_class, AnchorStatus.UNSUPPORTED, None, "tech_not_in_source"))

        elif raw.unit_class is FactUnitClass.PROPER_NOUN:
            needle = raw.text
            if needle in source_blob:
                results.append(
                    FactUnit(raw.text, raw.unit_class, AnchorStatus.ANCHORED, _find_anchor_block(needle, source_blocks))
                )
            elif needle in declared_blob:
                results.append(FactUnit(raw.text, raw.unit_class, AnchorStatus.ANCHORED, _declared_ref(needle, declared_facts), None))
            else:
                results.append(FactUnit(raw.text, raw.unit_class, AnchorStatus.UNSUPPORTED, None, "proper_noun_not_in_source"))

    # ---- 职级 / 程度词：方向性判定 ----
    for ladder_name, (cand_rank, cand_term) in extract_seniority(candidate_text).items():
        source_rank = source_seniority.get(ladder_name, (-1, ""))[0]
        declared_rank = declared_seniority.get(ladder_name, (-1, ""))[0]
        allowed_rank = max(source_rank, declared_rank)
        unit_text = f"{ladder_name}:{cand_term}"
        if cand_rank > allowed_rank:
            results.append(FactUnit(unit_text, FactUnitClass.SENIORITY, AnchorStatus.UPGRADED, None, f"rank {cand_rank} > {allowed_rank}"))
        elif cand_rank < allowed_rank:
            results.append(FactUnit(unit_text, FactUnitClass.SENIORITY, AnchorStatus.ABSTRACTED, None, f"rank {cand_rank} < {allowed_rank}"))
        else:
            results.append(FactUnit(unit_text, FactUnitClass.SENIORITY, AnchorStatus.ANCHORED, _find_anchor_block(cand_term, source_blocks)))

    # ---- JD 注入（硬门禁）----
    # 技术词 + 同义短语 canonical 两条通道都查：否则模型把 JD 里的"微服务/高并发/
    # 性能优化"这类中文短语写进没有该词的块，既不算 tech 注入也逃过锚点校验。
    candidate_tech = lex.find(candidate_text)
    jd_tech = lex.find(jd_text)
    source_canon = canonical_terms_in(source_blob)
    declared_canon = canonical_terms_in(declared_blob)
    candidate_canon = canonical_terms_in(candidate_text)
    jd_canon = canonical_terms_in(jd_text)
    tech_injection = (candidate_tech - source_tech - declared_tech) & jd_tech
    canon_injection = (candidate_canon - source_canon - declared_canon) & jd_canon
    jd_injection = tuple(sorted(tech_injection | canon_injection))

    # ---- ATS 提示（仅供参考，不改变裁决）----
    ats: list[str] = []
    if _REPLACEMENT_CHAR in candidate_text:
        ats.append("replacement_char_present")
    ats.extend(f"tech_glued:{pair}" for pair in _detect_tech_gluing(candidate_text, lex))

    if jd_injection:
        decision = VerdictDecision.REJECT
    elif any(unit.status in _NEEDS_CONFIRMATION for unit in results):
        decision = VerdictDecision.NEEDS_USER_CONFIRMATION
    else:
        decision = VerdictDecision.ACCEPT

    return Verdict(
        units=tuple(results),
        jd_injection=jd_injection,
        ats_issues=tuple(ats),
        decision=decision,
    )


def _declared_ref(raw: str, declared_facts: Sequence[DeclaredFact]) -> str | None:
    """找出包含该片段的用户声明 id。"""
    needle = normalize_text(raw)
    for fact in declared_facts:
        if needle and needle in normalize_text(fact.text):
            return fact.fact_id
    return None
