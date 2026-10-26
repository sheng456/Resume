"""L1 语义块抽取：把简历纯文本切成语义块（无重叠、可逆）。

对应 `docs/ARCHITECTURE.md` §5.1。与检索分块（500 字滑窗、50 字重叠）不同，
这里产出的是**编辑单位**：一条 bullet = 一个块，无重叠，section 归属正确。

局限（已知）：按行切分，不处理多行折行 bullet——简历 bullet 通常是单行，
这是可接受的折衷；多栏/表格简历的错乱由 `extract/confidence.py` 的置信度
门禁兜住（低置信度强制走重生模式，见 §5.1.2）。
"""

from __future__ import annotations

import re

from ..domain.contracts import BlockKind, ResumeBlock, Section

__all__ = ["detect_section", "extract_blocks"]

# 章节标题关键词。联系方式/个人信息归入 OTHER（meta 类，不可改写）。
_SECTION_KEYWORDS: dict[Section, tuple[str, ...]] = {
    Section.SUMMARY: ("个人总结", "个人简介", "自我介绍", "自我评价"),
    Section.EDUCATION: ("教育背景", "教育经历", "学历"),
    Section.WORK: ("工作经历", "工作经验", "任职经历"),
    Section.PROJECT: ("项目经历", "项目经验"),
    Section.SKILL: ("专业技能", "技术栈", "技能"),
    Section.AWARD: ("奖项", "荣誉", "获奖"),
    Section.OTHER: ("联系方式", "个人信息", "基本信息"),
}

# 联系方式等 meta 信息，独立成 META 块（不可改写）。
_META_HINT = re.compile(
    r"(电话|手机|邮箱|邮件|地址|城市|所在地|微信|QQ|@|出生|籍贯|求职意向|期望|政治面貌)"
)

# bullet 标记：· • - * ▸ 或 数字序号。
_BULLET_MARK = re.compile(r"^\s*(?:[·•●▪▸\-*]|\d{1,2}[.)、])\s*")


def detect_section(line: str) -> Section | None:
    """判断一行是否为章节标题。

    Args:
        line: 单行文本。

    Returns:
        命中的章节；非标题时返回 None。
    """
    stripped = line.strip().rstrip("：:")
    if not stripped or len(stripped) > 12:
        return None
    for section, keywords in _SECTION_KEYWORDS.items():
        for keyword in keywords:
            if stripped == keyword or stripped.startswith(keyword):
                return section
    return None


def _block_id(index: int) -> str:
    """按序生成确定性的 block id。"""
    return f"block:{index}"


def extract_blocks(text: str) -> tuple[ResumeBlock, ...]:
    """把纯文本简历切成语义块。

    规则：

    - 命中章节关键词的行 -> HEADING 块（不可改写），并切换当前 section；
    - 命中 meta 关键词（电话/邮箱/城市…）的行 -> META 块（不可改写）；
    - 当前 section 为 SKILL 的行 -> SKILL_LIST 块（不可改写）；
    - 其余行 -> BULLET 块，归属当前 section，剥掉 bullet 标记。

    Args:
        text: 简历纯文本。

    Returns:
        ResumeBlock 元组，顺序与原文一致。
    """
    blocks: list[ResumeBlock] = []
    current_section = Section.OTHER

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        section = detect_section(line)
        if section is not None:
            current_section = section
            blocks.append(
                ResumeBlock(_block_id(len(blocks)), section, BlockKind.HEADING, line, True)
            )
            continue

        if _META_HINT.search(line):
            blocks.append(
                ResumeBlock(_block_id(len(blocks)), Section.OTHER, BlockKind.META, line, True)
            )
            continue

        if current_section is Section.SKILL:
            blocks.append(
                ResumeBlock(
                    _block_id(len(blocks)), Section.SKILL, BlockKind.SKILL_LIST, line, True
                )
            )
            continue

        clean = _BULLET_MARK.sub("", line).strip()
        blocks.append(
            ResumeBlock(_block_id(len(blocks)), current_section, BlockKind.BULLET, clean, False)
        )

    return tuple(blocks)
