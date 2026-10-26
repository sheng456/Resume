"""模型级语义匹配（L2 增强）。

纯词级 ``analyze_gaps`` 有天花板：JD 写「Information Extraction」，简历写
「文本检索链路（关键词召回+BGE精排）」，词对不上但语义相关。本模块用本地
模型做**相关性判断**，把这种语义相关性补出来。

关键边界（不可破坏）：

- 模型只输出「哪些简历条目与这条要求语义相关」——是一个**信号**，用于
  覆盖展示与重排排序，**不是事实证据**；
- JD 词进简历仍只有三条通道（本来就有 / synonyms 人工等价 / 用户声明事实），
  本模块**不新增任何注入通道**，不改写、不补事实；
- 模型不可达 / 输出无法解析时，**回退到词级覆盖**（deterministic），不报错。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..domain.contracts import JdRequirement, ResumeBlock

__all__ = [
    "SemanticGapReport",
    "SemanticMatch",
    "analyze_semantic_gaps",
    "judge_requirement_relevance",
]

# ``prompt -> str`` 的模型调用函数（如 ``model.reword``）。
Generate = Callable[[str], str]


@dataclass(frozen=True)
class SemanticMatch:
    """一条要求的相关块判定。"""

    requirement_id: str
    relevant_block_ids: tuple[str, ...]


@dataclass(frozen=True)
class SemanticGapReport:
    """一批要求的语义匹配结果。"""

    matches: tuple[SemanticMatch, ...]

    def blocks_for(self, requirement_id: str) -> tuple[str, ...]:
        for match in self.matches:
            if match.requirement_id == requirement_id:
                return match.relevant_block_ids
        return ()


def _build_prompt(requirement_text: str, blocks: Sequence[ResumeBlock]) -> str:
    numbered = "\n".join(f"{index}: {block.text}" for index, block in enumerate(blocks))
    return (
        "你是简历匹配助手。判断下面每条简历条目是否体现了这条招聘要求（语义相关即可，"
        "不要求逐字相同；只判断相关性，不要改写、不要补充任何事实）。\n"
        "宁可漏报，不可多报：只有明确体现、支撑了这条要求的条目才标记，泛泛相关不要标。\n\n"
        f"招聘要求：{requirement_text}\n\n"
        f"简历条目：\n{numbered}\n\n"
        "只输出相关条目的编号，用逗号分隔（例如：0,2,5）；都不相关只输出 none。"
    )


def _parse_ids(raw: str, max_id: int) -> tuple[int, ...]:
    """从模型输出里稳健地取回编号（容忍夹带的解释文字）。"""
    text = (raw or "").strip().lower()
    if not text or "none" in text:
        return ()
    ids: list[int] = []
    for part in re.split(r"[^0-9]+", text):
        if part.isdigit():
            value = int(part)
            if 0 <= value < max_id and value not in ids:
                ids.append(value)
    return tuple(ids)


def judge_requirement_relevance(
    *,
    requirement_text: str,
    blocks: Sequence[ResumeBlock],
    generate: Generate,
) -> tuple[str, ...]:
    """判断哪些简历条目与一条要求语义相关。

    Args:
        requirement_text: 单条招聘要求。
        blocks: 参与匹配的简历块（按顺序编号）。
        generate: ``prompt -> str`` 的模型调用函数。

    Returns:
        相关块的 ``block_id`` 元组；模型失败 / 无相关时为空。
    """
    indexed = list(blocks)
    if not indexed:
        return ()
    try:
        raw = generate(_build_prompt(requirement_text, indexed))
    except Exception:
        return ()
    return tuple(indexed[i].block_id for i in _parse_ids(raw, len(indexed)))


def analyze_semantic_gaps(
    *,
    requirements: Sequence[JdRequirement],
    blocks: Sequence[ResumeBlock],
    generate: Generate,
) -> SemanticGapReport:
    """对给定要求做模型级相关性匹配。

    Args:
        requirements: 需要做语义匹配的 JD 要求项（通常传词级覆盖下的
            MISSING/PARTIAL 项，避免对已 covered 项浪费模型调用）。
        blocks: 参与匹配的简历块。
        generate: 模型调用函数。

    Returns:
        SemanticGapReport。
    """
    matches = tuple(
        SemanticMatch(
            requirement_id=req.requirement_id,
            relevant_block_ids=judge_requirement_relevance(
                requirement_text=req.text, blocks=blocks, generate=generate,
            ),
        )
        for req in requirements
    )
    return SemanticGapReport(matches)
