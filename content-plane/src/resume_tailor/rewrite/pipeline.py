"""完整改写管线：把确定性改写与模型 reword 串成最终简历版本。

顺序固定，职责分离：

1. 术语对齐（确定性，``safe.apply_alignments``）——只换有同义证据的词；
2. 模型 reword（可选，``reword.reword_block`` 双重门禁）——只润色单句表达；
3. 重排（确定性，``safe.reorder_blocks``）——按 JD 覆盖度排序，纯置换。

对齐先于 reword：模型看到的是已 JD 对齐过的文本，不会再去"改术语"；
reword 先于重排：重排是纯置换，与文本内容无关。

上层（评审 UI / 版本落盘）只消费 ``rewrite_resume`` 的产出，不直接调下层。
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.contracts import EditPlan, ResumeBlock, RewrittenBlock
from ..lexicon.tech import TechLexicon
from ..plan.intent import is_rewritable
from .reword import RewordModel, reword_block
from .safe import apply_alignments, reorder_blocks

__all__ = ["rewrite_resume"]


def rewrite_resume(
    *,
    blocks: Sequence[ResumeBlock],
    plan: EditPlan,
    model: RewordModel | None = None,
    jd_text: str = "",
    lexicon: TechLexicon | None = None,
) -> tuple[RewrittenBlock, ...]:
    """按计划执行完整改写，产出最终简历块序列。

    Args:
        blocks: 原简历块。
        plan: ``build_jd_plan`` 产出的计划。
        model: 改写模型；None 时跳过 reword（只对齐 + 重排）。
        jd_text: JD 全文，仅用于 reword 门禁的注入检测。
        lexicon: 技术词词库。

    Returns:
        ``RewrittenBlock`` 元组，最终顺序；每个含 original/rewritten 文本。
    """
    by_id = {block.block_id: block for block in blocks}
    align_by_id = {step.block_id: step.alignments for step in plan.steps if step.alignments}
    coverage_by_id = {step.block_id: step.coverage for step in plan.steps}
    direction_by_id = {step.block_id: step.direction for step in plan.steps if step.direction}

    # 1) 术语对齐（确定性）
    aligned = {
        block.block_id: apply_alignments(block.text, align_by_id.get(block.block_id, ()))
        for block in blocks
    }

    # 2) 模型 reword（对齐后的文本；锚定与事实保留都以对齐后的文本为基准）
    final_text = dict(aligned)
    for block in blocks:
        if model is None or not is_rewritable(block):
            continue
        aligned_block = ResumeBlock(
            block.block_id,
            block.section,
            block.kind,
            aligned[block.block_id],
            block.immutable,
        )
        result = reword_block(
            source_block=aligned_block,
            model=model,
            jd_text=jd_text,
            lexicon=lexicon,
            direction=direction_by_id.get(block.block_id),
        )
        final_text[block.block_id] = result.rewritten_text

    # 3) 重排（确定性，纯置换；按计划 bullet_order，指令驱动的顺序由此生效）
    ordered = reorder_blocks(blocks, coverage_by_id, plan.bullet_order)
    return tuple(
        RewrittenBlock(
            block_id=block.block_id,
            original_text=by_id[block.block_id].text,
            rewritten_text=final_text[block.block_id],
        )
        for block in ordered
    )
