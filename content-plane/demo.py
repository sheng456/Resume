"""M1 人工演示：把事实锚点校验器与指令解析器的判定结果打出来。

用途是让评审者**肉眼核对判定是否符合直觉**——测试保证行为不回归，
demo 保证设计意图可被读懂。两者都需要。

运行：
    PYTHONPATH=src python3 demo.py
"""

from __future__ import annotations

from resume_tailor.domain.contracts import (
    BlockKind,
    Coverage,
    DeclaredFact,
    GapItem,
    ResumeBlock,
    Section,
)
from resume_tailor.plan.intent import build_intent
from resume_tailor.verify.verifier import verify_edit

JD = (
    "岗位要求：熟悉 Java、Spring Boot、MySQL、Redis、Kafka；"
    "有 Kubernetes 与 Docker 使用经验；具备高并发系统设计能力。"
)

SOURCE = ResumeBlock(
    block_id="block:w1",
    section=Section.WORK,
    kind=BlockKind.BULLET,
    text="负责订单履约模块开发，将核心查询接口 P99 从 320ms 降至 90ms",
)

PROJECT = ResumeBlock(
    block_id="block:p1",
    section=Section.PROJECT,
    kind=BlockKind.BULLET,
    text="使用 Spring Boot + MySQL + Redis 重构订单核心链路",
)

DECLARED = [DeclaredFact("fact:1", "45ms", "2024 年压测报告")]

SCENARIOS: tuple[tuple[str, ResumeBlock, str, list[DeclaredFact]], ...] = (
    ("原文照抄（应通过）", SOURCE, SOURCE.text, []),
    ("降级表达：负责 -> 参与（应通过）", SOURCE, "参与订单履约模块开发，将核心查询接口 P99 从 320ms 降至 90ms", []),
    ("能力升级：负责 -> 主导（需确认）", SOURCE, "主导订单履约模块开发，将核心查询接口 P99 从 320ms 降至 90ms", []),
    ("篡改数字：90ms -> 45ms（需确认）", SOURCE, "负责订单履约模块开发，将核心查询接口 P99 从 320ms 降至 45ms", []),
    ("同上，但用户声明了 45ms（应通过）", SOURCE, "负责订单履约模块开发，将核心查询接口 P99 从 320ms 降至 45ms", DECLARED),
    ("JD 注入：凭空加 Kubernetes（硬拒绝）", PROJECT, "使用 Spring Boot + MySQL + Redis + Kubernetes 重构订单核心链路", []),
    ("凭空加 Spark（不在 JD，需确认）", PROJECT, "使用 Spring Boot + MySQL + Redis + Spark 重构订单核心链路", []),
)

TITLE = {
    "accept": "通过",
    "needs_user_confirmation": "需确认",
    "reject": "拒绝",
}

STATUS_MARK = {
    "anchored": "锚定",
    "abstracted": "降级",
    "upgraded": "升级",
    "unsupported": "无源",
}


def main() -> None:
    """打印全部演示场景的判定结果。"""
    print("=" * 78)
    print("L5 事实锚点校验器")
    print("=" * 78)

    for label, source, candidate, declared in SCENARIOS:
        verdict = verify_edit(
            source_blocks=[source],
            candidate_text=candidate,
            jd_text=JD,
            declared_facts=declared,
        )
        print(f"\n【{label}】")
        print(f"  改写：{candidate}")
        print(f"  裁决：{TITLE[verdict.decision.value]}")
        if verdict.jd_injection:
            print(f"  JD 注入（硬门禁）：{', '.join(verdict.jd_injection)}")
        flagged = [u for u in verdict.units if u.status.value != "anchored"]
        if flagged:
            for unit in flagged:
                print(f"    - {unit.text}  [{STATUS_MARK[unit.status.value]}]  {unit.detail or ''}")
        if verdict.ats_issues:
            print(f"  ATS 提示：{', '.join(verdict.ats_issues)}")

    print("\n" + "=" * 78)
    print("L3 指令解析")
    print("=" * 78)

    blocks = (
        SOURCE,
        PROJECT,
        ResumeBlock("block:s1", Section.SKILL, BlockKind.SKILL_LIST, "Java、Spring Boot、MySQL、Redis、Kafka"),
    )
    gap = GapItem(
        requirement_id="req:java",
        label="Java 后端开发",
        coverage=Coverage.MISSING,
        requirement_terms=("java", "spring"),
    )

    for label, instruction, gaps in (
        ("明确指令", "把项目经历写得更专业一些", ()),
        ("模糊指令", "写得好一点", ()),
        ("靠技术词定位", "突出 Kafka 那条", ()),
        ("与 JD 缺口冲突", "弱化 Java 相关的内容", (gap,)),
    ):
        intent = build_intent(instruction, blocks=blocks, gap_items=gaps)
        print(f"\n【{label}】{instruction}")
        print(f"  目 标：{intent.goal.value if intent.goal else '未识别'}")
        print(f"  范 围：{list(intent.scope_sections) or '未识别'} / {list(intent.scope_block_ids) or '未识别'}")
        print(f"  置信度：{intent.parse_confidence.value}")
        if intent.conflicts_with_gap:
            for conflict in intent.conflicts_with_gap:
                print(f"  冲 突：JD 缺口「{conflict.gap_direction}」 vs 指令方向「{conflict.instruction_direction}」")
        if intent.clarification_options:
            print("  需澄清：")
            for option in intent.clarification_options:
                print(f"    - {option}")


if __name__ == "__main__":
    main()
