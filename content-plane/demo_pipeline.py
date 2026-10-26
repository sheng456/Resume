"""完整管线演示：JD -> 计划 -> 对齐 + reword + 重排 -> 最终简历（真模型）。

运行：
    PYTHONPATH=src python3 demo_pipeline.py
    PYTHONPATH=src python3 demo_pipeline.py --no-model        # 跳过模型，只做确定性对齐+重排（Ollama 不可达时用这个）
    RESUME_REWORD_PROVIDER=deepseek PYTHONPATH=src python3 demo_pipeline.py
"""

from __future__ import annotations

import argparse

from resume_tailor.domain.contracts import BlockKind, JdRequirement, ResumeBlock, Section
from resume_tailor.plan.jd_plan import build_jd_plan
from resume_tailor.rewrite.models import get_reword_model
from resume_tailor.rewrite.pipeline import rewrite_resume

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

SECTION_CN = {
    "work": "工作经历",
    "project": "项目经历",
    "skill": "专业技能",
}


def main() -> None:
    """打印计划摘要与最终简历 diff。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-model", action="store_true", help="跳过模型 reword，只做确定性对齐+重排")
    args = parser.parse_args()

    jd_text = " ".join(r.text for r in REQUIREMENTS)
    plan = build_jd_plan(requirements=REQUIREMENTS, blocks=BLOCKS)

    print("=" * 78)
    print("改写计划")
    print("=" * 78)
    print(f"  禁止引入（JD 有、简历没有）：{', '.join(plan.forbidden_terms) or '无'}")
    for step in plan.steps:
        align = "；".join(f"{a.source_phrase}→{a.target_phrase}" for a in step.alignments)
        if align:
            print(f"  {step.block_id}: 对齐 {align}")

    model = None if args.no_model else get_reword_model()
    final = rewrite_resume(blocks=BLOCKS, plan=plan, model=model, jd_text=jd_text)

    print("\n" + "=" * 78)
    print("最终简历（重排后顺序；改动处并列展示）")
    print("=" * 78)
    current_section = None
    for item in final:
        original = next(b for b in BLOCKS if b.block_id == item.block_id)
        if original.section.value != current_section:
            current_section = original.section.value
            print(f"\n[{SECTION_CN.get(current_section, current_section)}]")
        if item.changed:
            print(f"  - 原：{item.original_text}")
            print(f"    ↳ 新：{item.rewritten_text}")
        else:
            print(f"  - {item.rewritten_text}")


if __name__ == "__main__":
    main()
