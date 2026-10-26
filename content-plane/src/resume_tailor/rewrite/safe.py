"""安全改写（无模型）：术语对齐 + 重排。

这两个操作都是机械变换，**不可能引入新事实**：

- 术语对齐 = 用证据（同义词表）把一个短语换成等价短语；
- 重排 = 把 JD 覆盖度高的 bullet 提到前面，是纯置换（token 一个不多不少）。

改写结果仍会逐条过一遍 L5 校验作为兜底——L5 不通过即说明本层出了 bug，
调用方应回退原文（fail-closed）。确定性操作唯一能改变文本的地方就是
对齐替换，因此 L5 应当恒通过；这条不变量由测试锁住。
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.contracts import EditPlan, ResumeBlock, RewrittenBlock, Verdict
from ..plan.intent import is_rewritable
from ..verify.verifier import verify_edit

__all__ = ["apply_alignments", "reorder_blocks", "rewrite_blocks", "verify_rewrite"]

# 私有使用区占位符，避免多条替换互相级联（A->B 后 B 又被当 A）。
_MARK = "\ue000"


def apply_alignments(text: str, alignments: Sequence) -> str:
    """把术语对齐逐条套到文本上。

    两段式替换：先把源短语换成占位符，再统一换成目标短语，避免
    "先替换产生的结果又被下一条当源" 的级联污染。

    Args:
        text: 原文。
        alignments: ``AlignmentPair`` 序列。

    Returns:
        替换后的文本；无对齐时原样返回。
    """
    if not alignments:
        return text
    # 按源短语长度降序；同一源短语只取第一条，避免"一个源词对应多个目标词"
    # 时两段式替换把第二个目标词静默丢掉（先替换成占位符后，源词已不在文本中）。
    pairs: list = []
    seen: set[str] = set()
    for pair in sorted(alignments, key=lambda a: len(a.source_phrase), reverse=True):
        if pair.source_phrase in seen:
            continue
        seen.add(pair.source_phrase)
        pairs.append(pair)
    result = text
    for index, pair in enumerate(pairs):
        result = result.replace(pair.source_phrase, f"{_MARK}{index}{_MARK}")
    for index, pair in enumerate(pairs):
        result = result.replace(f"{_MARK}{index}{_MARK}", pair.target_phrase)
    return result


def reorder_blocks(
    blocks: Sequence[ResumeBlock],
    coverage_by_id: dict[str, int],
    bullet_order: Sequence[str] | None = None,
) -> list[ResumeBlock]:
    """section 内重排可改写 bullet，其余块原位不动。

    纯置换，不改变任何文本内容。

    Args:
        blocks: 原简历块。
        coverage_by_id: block_id -> JD 技术词覆盖数（``bullet_order`` 缺省时用）。
        bullet_order: 计划的全局 bullet 顺序（``EditPlan.bullet_order``）；给定则
            按它排序（指令驱动的顺序由此生效），否则回退按覆盖数。

    Returns:
        重排后的 ResumeBlock 列表。
    """
    rank = {bid: index for index, bid in enumerate(bullet_order)} if bullet_order is not None else {}

    sections: list[list[ResumeBlock]] = []
    for block in blocks:
        if sections and sections[-1][0].section == block.section:
            sections[-1].append(block)
        else:
            sections.append([block])

    ordered: list[ResumeBlock] = []
    for run in sections:
        index_by_id = {block.block_id: index for index, block in enumerate(run)}
        if rank:
            key = lambda b: (rank.get(b.block_id, len(rank)), index_by_id[b.block_id])  # noqa: E731
        else:
            key = lambda b: (-coverage_by_id.get(b.block_id, 0), index_by_id[b.block_id])  # noqa: E731
        sorted_bullets = sorted(
            (block for block in run if is_rewritable(block)),
            key=key,
        )
        iterator = iter(sorted_bullets)
        rebuilt: list[ResumeBlock] = []
        for block in run:
            rebuilt.append(next(iterator) if is_rewritable(block) else block)
        ordered.extend(rebuilt)
    return ordered


def rewrite_blocks(
    *,
    blocks: Sequence[ResumeBlock],
    plan: EditPlan,
) -> tuple[RewrittenBlock, ...]:
    """按计划执行安全改写，返回新顺序下的块。

    Args:
        blocks: 原简历块。
        plan: ``build_jd_plan`` 产出的计划。

    Returns:
        ``RewrittenBlock`` 元组，顺序为改写+重排后的顺序。
    """
    align_by_id = {step.block_id: step.alignments for step in plan.steps if step.alignments}
    coverage_by_id = {step.block_id: step.coverage for step in plan.steps}

    aligned = {
        block.block_id: apply_alignments(block.text, align_by_id.get(block.block_id, ()))
        for block in blocks
    }

    return tuple(
        RewrittenBlock(
            block_id=block.block_id,
            original_text=block.text,
            rewritten_text=aligned[block.block_id],
        )
        for block in reorder_blocks(blocks, coverage_by_id, plan.bullet_order)
    )


def verify_rewrite(
    *,
    blocks: Sequence[ResumeBlock],
    rewritten: Sequence[RewrittenBlock],
    jd_text: str = "",
) -> tuple[Verdict, ...]:
    """对每条发生变化的块跑 L5，作为兜底。

    确定性改写应当恒通过；任何非 ``ACCEPT`` 都意味着本层引入了不该引入的
    内容，调用方应回退原文。

    Args:
        blocks: 原简历块（用于锚定）。
        rewritten: ``rewrite_blocks`` 的产出。
        jd_text: JD 全文，用于注入检测。

    Returns:
        Verdict 元组，每条对应一个发生变化的块。
    """
    by_id = {block.block_id: block for block in blocks}
    verdicts: list[Verdict] = []
    for item in rewritten:
        if item.original_text == item.rewritten_text:
            continue
        verdicts.append(
            verify_edit(
                source_blocks=[by_id[item.block_id]],
                candidate_text=item.rewritten_text,
                jd_text=jd_text,
            )
        )
    return tuple(verdicts)
