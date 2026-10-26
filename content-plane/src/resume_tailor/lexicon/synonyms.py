"""同义表达映射——术语对齐的证据来源。

这是"让一个 JD 词进入简历"的**唯一确定性通道**：只有当简历里的某个短语
被人工认定为与 JD 里的某个短语**事实等价**时，才允许替换。没有这条证据，
任何 JD 词都不能凭空进入简历。

关键区分：

- ``lexicon/tech.py`` 管**英文技术词别名归一**（``k8s`` -> ``kubernetes``），
  用于注入检测与覆盖打分；
- 本模块管**中文事实等价短语**（``服务拆分`` == ``微服务``），用于术语对齐。

证据是人工维护、可审计的 ``data/synonyms.json``，**不是模型推断**。未来的
模型改写（reword）也不能绕过它——模型只能复用这里已经认定的等价关系，
否则 L5 事实校验会把它判为无源。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

__all__ = [
    "canonical",
    "canonical_terms_in",
    "equivalent",
    "find_alignments",
    "group_index",
    "groups",
]

_DATA_PATH = Path(__file__).with_name("data") / "synonyms.json"


@lru_cache(maxsize=1)
def _groups() -> tuple[tuple[str, ...], ...]:
    """加载同义短语组（进程内缓存）。"""
    raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return tuple(tuple(group) for group in raw["groups"])


def groups() -> tuple[tuple[str, ...], ...]:
    """全部同义短语组。"""
    return _groups()


def group_index(phrase: str) -> int | None:
    """返回短语所属的同义组下标；不属于任何组时返回 None。

    Args:
        phrase: 待查短语。

    Returns:
        组下标或 None。
    """
    target = phrase.strip().lower()
    for index, group in enumerate(_groups()):
        if any(member.lower() == target for member in group):
            return index
    return None


def canonical(phrase: str) -> str:
    """把短语归一为该同义组的 canonical 形式（组内第一个）。

    Args:
        phrase: 任意短语。

    Returns:
        canonical 形式；不在任何组内时原样返回。
    """
    index = group_index(phrase)
    return _groups()[index][0] if index is not None else phrase


def equivalent(left: str, right: str) -> bool:
    """判断两个短语是否属于同一同义组（事实等价）。

    Args:
        left: 短语 A。
        right: 短语 B。

    Returns:
        同组时返回 True。
    """
    li, ri = group_index(left), group_index(right)
    return li is not None and li == ri


def canonical_terms_in(text: str) -> frozenset[str]:
    """返回文本中命中的所有同义组的 canonical 短语。

    Args:
        text: 任意文本。

    Returns:
        canonical 短语集合；无命中时为空集合。
    """
    found: set[str] = set()
    for group in _groups():
        for member in group:
            if member in text:
                found.add(group[0])
                break
    return frozenset(found)


def find_alignments(
    source_text: str,
    target_terms: Iterable[str],
) -> tuple[tuple[str, str, int], ...]:
    """找出 source 中可与 target 术语对齐的短语。

    仅当 target 术语本身不在 source、但其同义词在 source 中时产生一条对齐。
    对齐方向固定：简历里的短语 -> JD 的 canonical 词，保证简历向 JD 口径靠拢。

    Args:
        source_text: 简历块原文。
        target_terms: JD 要求项的术语集合。

    Returns:
        ``(source_phrase, target_phrase, group_index)`` 元组。
    """
    pairs: list[tuple[str, str, int]] = []
    for term in target_terms:
        index = group_index(term)
        if index is None:
            continue
        if term in source_text:
            continue  # 已经直接命中，无需对齐
        group = _groups()[index]
        for alternative in group:
            if alternative != term and alternative in source_text:
                pairs.append((alternative, term, index))
                break
    return tuple(pairs)
