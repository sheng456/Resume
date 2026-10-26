"""L1 提取置信度门禁：检测"提取器返回成功、但内容已损坏"的静默失败。

对应 `docs/ARCHITECTURE.md` §5.1.1 与 `FEASIBILITY-READ-WRITE.md` 的实测结论：
本机 Xpdf 的 `pdftotext` 会把中文以 0% 保留率静默丢弃、并把技术词粘连；
`job` 的 `python-docx` 会把表格简历解析成空串。这些失败都不报错，只能靠自检。

低置信度**不意味着"不能用"**，而是强制走重生模式（§5.1.2），宁保守勿错位。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ..domain.contracts import BlockKind, ResumeBlock, Section
from ..lexicon.tech import TechLexicon, get_lexicon

__all__ = ["ConfidenceSignal", "ExtractionConfidence", "assess_extraction"]

_CJK = re.compile(r"[\u4e00-\u9fff]")


@dataclass(frozen=True)
class ConfidenceSignal:
    """一条置信度信号。"""

    name: str
    detail: str


@dataclass(frozen=True)
class ExtractionConfidence:
    """提取置信度结论。"""

    confidence: Literal["high", "low"]
    signals: tuple[ConfidenceSignal, ...] = ()

    @property
    def is_low(self) -> bool:
        """是否低置信度（强制重生模式）。"""
        return self.confidence == "low"


def _cjk_count(text: str) -> int:
    return len(_CJK.findall(text))


def _meta_after_content(blocks: tuple[ResumeBlock, ...]) -> bool:
    """meta（联系方式等）出现在内容章节之后，疑似侧栏表格错乱。

    正常简历的联系方式在内容之前；侧栏两列表格被逐行交错后，左栏的城市/邮箱
    会落到工作经历之后。
    """
    seen_content = False
    for block in blocks:
        if block.kind is BlockKind.HEADING and block.section is not Section.OTHER:
            seen_content = True
        if block.kind is BlockKind.META and seen_content:
            return True
    return False


def _section_revisited(blocks: tuple[ResumeBlock, ...]) -> bool:
    """同一章节的 bullet 被其他章节打断（非连续），疑似多栏交错。"""
    seen: set[Section] = set()
    prev: Section | None = None
    for block in blocks:
        if block.kind is not BlockKind.BULLET:
            continue
        if block.section != prev:
            if block.section in seen:
                return True
            seen.add(block.section)
        prev = block.section
    return False


def assess_extraction(
    *,
    text: str,
    blocks: tuple[ResumeBlock, ...] | None = None,
    expected_cjk: bool = False,
    lexicon: TechLexicon | None = None,
) -> ExtractionConfidence:
    """评估提取结果的置信度。

    Args:
        text: 提取出的纯文本。
        blocks: 已切分的语义块（可选；缺省时跳过布局检测）。
        expected_cjk: 源简历是否预期含中文（中文简历应传 True）。
        lexicon: 技术词词库。

    Returns:
        ExtractionConfidence；任一硬信号触发即 low。
    """
    lex = lexicon or get_lexicon()
    signals: list[ConfidenceSignal] = []
    low = False

    stripped = (text or "").strip()
    if not stripped:
        return ExtractionConfidence(
            "low", (ConfidenceSignal("empty_text", "提取结果为空"),)
        )

    if "\ufffd" in stripped:
        signals.append(
            ConfidenceSignal("replacement_char", "存在替换符 U+FFFD，编码/提取损坏")
        )

    glued = lex.find_glued(stripped)
    if glued:
        low = True
        # 只回数量，不回粘连 run 原文——否则损坏简历的原文片段会漏进工具响应。
        signals.append(ConfidenceSignal("glued_tech", f"检测到 {len(glued)} 处技术词粘连"))

    if expected_cjk and _cjk_count(stripped) == 0:
        low = True
        signals.append(ConfidenceSignal("cjk_loss", "预期中文但提取结果无任何汉字"))

    if "\t" in stripped:
        low = True
        signals.append(
            ConfidenceSignal("table_layout", "文本含制表符，疑似表格/多栏布局，需表格感知解析而非块级编辑")
        )

    if blocks is not None:
        if _meta_after_content(blocks):
            low = True
            signals.append(
                ConfidenceSignal(
                    "layout_meta_after_content", "联系方式等 meta 出现在内容章节之后，疑似多栏错乱"
                )
            )
        if _section_revisited(blocks):
            low = True
            signals.append(
                ConfidenceSignal("layout_section_revisited", "同一章节条目被其他章节打断")
            )

    return ExtractionConfidence("low" if low else "high", tuple(signals))
