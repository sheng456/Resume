"""指令意图接入计划/管线的演示。

对比三种情况：无指令（JD 兜底）、有指令（指令驱动）、歧义/冲突（不生成计划）。

运行：
    PYTHONPATH=src python3 demo_instruction.py
"""

from __future__ import annotations

from resume_tailor.domain.contracts import BlockKind, JdRequirement, ResumeBlock, Section
from resume_tailor.plan.plan import build_plan

BLOCKS = (
    ResumeBlock("block:w1", Section.WORK, BlockKind.BULLET, "负责订单系统服务拆分，接口 P99 从 320ms 降至 90ms"),
    ResumeBlock("block:w2", Section.WORK, BlockKind.BULLET, "主导订单表分库分表改造，单表数据量从 8000 万降至 500 万"),
    ResumeBlock("block:p1", Section.PROJECT, BlockKind.BULLET, "引入 Kafka 异步化，峰值 QPS 从 1200 提升至 4500"),
    ResumeBlock("block:s1", Section.SKILL, BlockKind.SKILL_LIST, "Java、Spring Boot、MySQL、Redis、Kafka"),
)

JD = (
    JdRequirement("req:1", "熟悉微服务架构"),
    JdRequirement("req:2", "熟悉 Java、Spring Boot"),
    JdRequirement("req:3", "有 Kubernetes 经验"),
)


def main() -> None:
    """打印三种情况。"""
    print("=" * 78)
    print("① 无指令：JD 兜底")
    print("=" * 78)
    r = build_plan(requirements=JD, blocks=BLOCKS, instruction=None)
    print(f"  driver={r.plan.driver}  intent_id={r.plan.intent_id}")
    for s in r.plan.steps:
        align = "；".join(f"{a.source_phrase}→{a.target_phrase}" for a in s.alignments)
        print(f"  {s.block_id}: op={s.operation.value} origin={s.origin} dir={s.direction} align=[{align or '无'}]")

    print("\n" + "=" * 78)
    print("② 有指令：把项目经历写得更专业一些")
    print("=" * 78)
    r = build_plan(requirements=JD, blocks=BLOCKS, instruction="把项目经历写得更专业一些")
    print(f"  driver={r.plan.driver}  intent_id={r.plan.intent_id}")
    print(f"  instruction_hash={r.plan.instruction_hash[:16]}…")
    print(f"  重排首位：{r.plan.bullet_order[0]}")
    for s in r.plan.steps:
        if s.origin == "instruction" or s.direction:
            print(f"  {s.block_id}: origin={s.origin} direction={s.direction}")

    print("\n" + "=" * 78)
    print("③ 歧义 / 冲突（不生成计划）")
    print("=" * 78)
    r = build_plan(requirements=JD, blocks=BLOCKS, instruction="写得好一点")
    print(f"  歧义：plan={r.plan}  澄清项={len(r.clarification_options)}")
    for o in r.clarification_options:
        print(f"    - {o}")

    r = build_plan(requirements=JD, blocks=BLOCKS, instruction="弱化 Kubernetes")
    print(f"  冲突：plan={r.plan}  冲突={len(r.conflicts)}")
    for c in r.conflicts:
        print(f"    - 缺口「{c.gap_direction}」vs 指令「{c.instruction_direction}」")


if __name__ == "__main__":
    main()
