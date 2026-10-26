"""L6 评审演示：把改写提案摊开，模拟人逐条决定接受 / 声明事实 / 拒绝。

用脚本化假模型产生一个"混合"提案集，完整走一遍评审逻辑（确定性、可复现）：

- 安全改写            -> 自动接受；
- 新增量化（仅"无源"） -> 声明事实后接受；
- 篡改数字 + 能力升级 -> 拒绝。

运行：
    PYTHONPATH=src python3 demo_review.py
"""

from __future__ import annotations

from resume_tailor.domain.contracts import BlockKind, DeclaredFact, ResumeBlock, Section
from resume_tailor.rewrite.reword import propose_blocks
from resume_tailor.review.review import (
    ReviewDecision,
    ReviewItem,
    apply_decisions,
    assemble_review,
    reverify,
)

BLOCKS = (
    ResumeBlock("block:a", Section.WORK, BlockKind.BULLET, "负责订单系统服务拆分，接口 P99 从 320ms 降至 90ms"),
    ResumeBlock("block:b", Section.WORK, BlockKind.BULLET, "主导订单表分库分表改造，单表数据量从 8000 万降至 500 万"),
    ResumeBlock("block:c", Section.WORK, BlockKind.BULLET, "参与 CI/CD 流程建设，发布耗时从 25 分钟缩短至 8 分钟"),
)

# 依次对应 block:a / block:b / block:c 的模型候选。
CANDIDATES = (
    "负责订单系统微服务，接口 P99 从 320ms 降至 90ms",                              # 安全
    "主导订单表分库分表改造，单表数据量从 8000 万降至 500 万，覆盖 100 万用户",       # 新增"100 万"（无源）
    "主导 CI/CD 流程建设，发布耗时从 25 分钟缩短至 3 分钟",                          # 升级"主导"+ 篡改"3 分钟"
)


class QueueModel:
    """按顺序返回候选的假模型。"""

    def __init__(self, candidates: tuple[str, ...]) -> None:
        self._it = iter(candidates)

    def reword(self, prompt: str) -> str:
        return next(self._it)


STATUS_CN = {
    "accept": "可接受",
    "needs_user_confirmation": "需确认",
    "reject": "硬拒绝",
}


def main() -> None:
    """打印提案 -> 评审 -> 最终简历。"""
    proposals = propose_blocks(blocks=BLOCKS, model=QueueModel(CANDIDATES))
    items = list(assemble_review(proposals))
    by_id = {b.block_id: b for b in BLOCKS}

    print("=" * 78)
    print("评审项（原文 vs 候选）")
    print("=" * 78)
    for item in items:
        print(f"\n[{item.block_id}]")
        if not item.changed:
            print("  未改动（无需评审）")
            continue
        print(f"  原文：{item.original_text}")
        print(f"  候选：{item.proposed_text}")
        print(f"  L5 裁决：{STATUS_CN[item.verdict.decision.value]}  事实保留：{item.facts_retained}")
        for unit in item.verdict.units:
            if unit.status.value != "anchored":
                print(f"    · {unit.text!r} -> {unit.status.value}")

    # 模拟人做决定
    print("\n" + "=" * 78)
    print("人的决定")
    print("=" * 78)

    # block:a 安全 -> 接受
    items[0] = ReviewItem(items[0].block_id, items[0].original_text, items[0].proposed_text,
                          items[0].verdict, items[0].facts_retained, ReviewDecision.ACCEPT)
    print(f"  block:a 接受（安全改写）")

    # block:b 仅无源 -> 声明事实后接受
    b_item = items[1]
    verdict = reverify(
        block=by_id["block:b"],
        proposed_text=b_item.proposed_text,
        declared_facts=[DeclaredFact("fact:1", "覆盖 100 万用户", "用户规模报表")],
    )
    print(f"  block:b 声明事实「覆盖 100 万用户」后重新校验：{STATUS_CN[verdict.decision.value]}")
    if verdict.decision.value == "accept":
        items[1] = ReviewItem(b_item.block_id, b_item.original_text, b_item.proposed_text,
                              verdict, b_item.facts_retained, ReviewDecision.ACCEPT)

    # block:c 升级+篡改 -> 拒绝
    items[2] = ReviewItem(items[2].block_id, items[2].original_text, items[2].proposed_text,
                          items[2].verdict, items[2].facts_retained, ReviewDecision.REJECT)
    print(f"  block:c 拒绝（能力升级 + 篡改数字）")

    # 应用决定 -> 最终简历
    final = apply_decisions(items)
    print("\n" + "=" * 78)
    print("最终简历")
    print("=" * 78)
    for item in final:
        mark = "·" if item.original_text == item.rewritten_text else "改"
        print(f"  {mark} {item.rewritten_text}")


if __name__ == "__main__":
    main()
