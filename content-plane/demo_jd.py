"""M2 人工演示：JD -> 缺口 -> 计划 -> 安全改写，端到端打出来。

目的是让评审者肉眼核对"根据 JD 更新"的每一步：改了什么、依据是什么、
为什么没有臆造。

运行：
    PYTHONPATH=src python3 demo_jd.py
"""

from __future__ import annotations

from resume_tailor.domain.contracts import (
    BlockKind,
    JdRequirement,
    ResumeBlock,
    Section,
)
from resume_tailor.diagnose.gap import analyze_gaps
from resume_tailor.plan.jd_plan import build_jd_plan
from resume_tailor.rewrite.safe import rewrite_blocks, verify_rewrite

# 虚构、脱敏的简历与 JD。
BLOCKS = (
    ResumeBlock("block:w1", Section.WORK, BlockKind.BULLET, "负责订单系统服务拆分，接口 P99 从 320ms 降至 90ms"),
    ResumeBlock("block:w2", Section.WORK, BlockKind.BULLET, "主导订单表分库分表改造，单表数据量从 8000 万降至 500 万"),
    ResumeBlock("block:w3", Section.WORK, BlockKind.BULLET, "使用 Java 与 Spring Boot 开发订单核心链路"),
    ResumeBlock("block:p1", Section.PROJECT, BlockKind.BULLET, "引入 Kafka 异步化，峰值 QPS 从 1200 提升至 4500"),
    ResumeBlock("block:s1", Section.SKILL, BlockKind.SKILL_LIST, "Java、Spring Boot、MySQL、Redis、Kafka"),
)

REQUIREMENTS = (
    JdRequirement("req:1", "熟悉微服务架构与高并发设计"),
    JdRequirement("req:2", "熟悉 Java、Spring Boot、消息队列"),
    JdRequirement("req:3", "有 Kubernetes 经验"),
)

COVERAGE_CN = {"covered": "已覆盖", "partial": "部分覆盖", "missing": "缺失"}


def main() -> None:
    """打印完整链路。"""
    print("=" * 80)
    print("捕获的 JD 要求")
    print("=" * 80)
    for req in REQUIREMENTS:
        print(f"  [{req.requirement_id}] {req.text}")

    gaps = analyze_gaps(requirements=REQUIREMENTS, blocks=BLOCKS)
    print("\n" + "=" * 80)
    print("L2 缺口诊断")
    print("=" * 80)
    for gap in gaps:
        best = ",".join(gap.best_block_ids) or "无"
        print(f"  {gap.label}")
        print(f"    覆盖：{COVERAGE_CN[gap.coverage.value]}  证据块：{best}")

    plan = build_jd_plan(requirements=REQUIREMENTS, blocks=BLOCKS)
    print("\n" + "=" * 80)
    print("L3 改写计划")
    print("=" * 80)
    print(f"  plan_id: {plan.plan_id}")
    print(f"  禁止引入的 JD 技术词（黑名单）：{', '.join(plan.forbidden_terms) or '无'}")
    for step in plan.steps:
        align = "；".join(f"{a.source_phrase}→{a.target_phrase}(组{a.synonym_group})" for a in step.alignments)
        print(
            f"  {step.block_id}: 操作={step.operation.value} 覆盖={step.coverage} "
            f"职级上限={step.seniority_ceiling} 对齐=[{align or '无'}]"
        )
    for block_id, reason in plan.rejected:
        print(f"  {block_id}: 拒绝原因={reason}")

    print("\n" + "=" * 80)
    print("L4 安全改写（确定性：术语对齐 + 重排）")
    print("=" * 80)
    rewritten = rewrite_blocks(blocks=BLOCKS, plan=plan)
    for item in rewritten:
        mark = "改" if item.changed else "·"
        print(f"  {mark} {item.block_id}")
        if item.changed:
            print(f"      原：{item.original_text}")
            print(f"      新：{item.rewritten_text}")
        else:
            print(f"      {item.rewritten_text}")

    print("\n" + "=" * 80)
    print("L5 兜底校验（每条改动过事实锚点校验）")
    print("=" * 80)
    verdicts = verify_rewrite(blocks=BLOCKS, rewritten=rewritten, jd_text=" ".join(r.text for r in REQUIREMENTS))
    print(f"  改动条数：{len(verdicts)}，全部通过：{all(v.decision.value == 'accept' for v in verdicts)}")
    for verdict in verdicts:
        print(f"    裁决={verdict.decision.value} 注入={verdict.jd_injection or '无'}")


if __name__ == "__main__":
    main()
