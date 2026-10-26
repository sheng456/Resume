"""L7 渲染：把最终简历块渲染成稳定的 markdown 文本（哈希输入）。

docx / pdf 渲染属 L8；这里只做 md，作为内容寻址落盘的规范文本形态。
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.contracts import BlockKind, ResumeBlock, RewrittenBlock, Section

__all__ = ["render_markdown"]

_SECTION_TITLES: dict[Section, str] = {
    Section.SUMMARY: "个人总结",
    Section.EDUCATION: "教育背景",
    Section.WORK: "工作经历",
    Section.PROJECT: "项目经历",
    Section.SKILL: "专业技能",
    Section.AWARD: "奖项",
    Section.OTHER: "其他",
}


def render_markdown(
    final: Sequence[RewrittenBlock],
    blocks: Sequence[ResumeBlock],
) -> str:
    """把最终简历渲染成确定性的 markdown 文本。

    结构（section/kind）取自原块，文本取最终改写结果；标题块用 ``##``、
    bullet/skill 用 ``-``、meta 原样。逐块一行，顺序即最终顺序。

    Args:
        final: ``rewrite_resume`` / 评审后的最终块序列（最终顺序）。
        blocks: 原简历块（提供 section/kind 结构）。

    Returns:
        稳定的 markdown 字符串（以单个换行结尾）。
    """
    meta = {block.block_id: block for block in blocks}
    lines: list[str] = []

    for item in final:
        original = meta.get(item.block_id)
        kind = original.kind if original else BlockKind.BULLET
        text = item.rewritten_text

        if kind is BlockKind.HEADING:
            lines.append(f"## {text}")
        elif kind is BlockKind.SKILL_LIST or kind is BlockKind.BULLET:
            lines.append(f"- {text}")
        else:  # META
            lines.append(text)

    return "\n".join(lines).rstrip() + "\n"
