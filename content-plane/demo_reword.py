"""M2 reword 演示：接真 Ollama 模型，展示门禁如何放行 / 拦截。

运行：
    PYTHONPATH=src python3 demo_reword.py            # 默认 qwen2.5-coder:7b
    OLLAMA_MODEL=qwen2.5:3b PYTHONPATH=src python3 demo_reword.py

Ollama 不可达时，reword_block 会 fail-closed（保留原文），脚本仍不崩。
"""

from __future__ import annotations

import os

from resume_tailor.domain.contracts import BlockKind, ResumeBlock, Section
from resume_tailor.rewrite.models import get_reword_model
from resume_tailor.rewrite.reword import reword_block

JD = "岗位要求：熟悉微服务、Java、Spring Boot；有 Kubernetes 经验。"

BULLETS = (
    ResumeBlock(
        "b1", Section.WORK, BlockKind.BULLET,
        "负责订单系统服务拆分，接口 P99 从 320ms 降至 90ms",
    ),
    ResumeBlock(
        "b2", Section.WORK, BlockKind.BULLET,
        "参与订单表分库分表改造，单表数据量从 8000 万降至 500 万",
    ),
    ResumeBlock(
        "b3", Section.PROJECT, BlockKind.BULLET,
        "使用 Java 与 Spring Boot 开发订单核心链路",
    ),
)


def main() -> None:
    """逐条改写并打印门禁结果。"""
    provider = os.environ.get("RESUME_REWORD_PROVIDER", "ollama")
    model = get_reword_model()
    print(f"provider：{provider}（RESUME_REWORD_PROVIDER 控制，默认 ollama）")
    print(f"JD（仅用于注入检测，不进入提示词）：{JD}\n")

    for block in BULLETS:
        result = reword_block(source_block=block, model=model, jd_text=JD)
        print(f"原：{block.text}")
        if result.changed:
            print(f"新：{result.rewritten_text}")
        else:
            print("   ↳ 未采纳（门禁拦截或模型不可达），保留原文")
        print()


if __name__ == "__main__":
    main()
