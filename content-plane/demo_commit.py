"""L7 完整闭环演示：抽取 → 计划 → 改写 → 落盘 → Gate W。

确定性（不接模型），完整走一遍从"简历文本"到"落盘新版本 + 血缘"的闭环，
并演示内容哈希幂等与 Gate W 审批。

运行：
    PYTHONPATH=src python3 demo_commit.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from resume_tailor.domain.contracts import JdRequirement
from resume_tailor.extract.blocks import extract_blocks
from resume_tailor.extract.confidence import assess_extraction
from resume_tailor.plan.jd_plan import build_jd_plan
from resume_tailor.policy.gate_w import GateWService
from resume_tailor.rewrite.pipeline import rewrite_resume
from resume_tailor.store.identity import sha256_hex
from resume_tailor.store.version import commit_resume
from resume_tailor.store.version_store import ResumeVersionStore

RESUME = """张明
求职意向：后端开发工程师
工作经历
· 负责订单系统服务拆分，接口 P99 从 320ms 降至 90ms
· 主导订单表分库分表改造，单表数据量从 8000 万降至 500 万
项目经历
· 引入 Kafka 异步化，峰值 QPS 从 1200 提升至 4500
专业技能
Java、Spring Boot、MySQL、Redis、Kafka"""

JD = (JdRequirement("req:1", "熟悉微服务架构"), JdRequirement("req:2", "熟悉 Java、Spring Boot"))


def main() -> None:
    """走一遍闭环。"""
    blocks = extract_blocks(RESUME)
    conf = assess_extraction(text=RESUME, blocks=blocks, expected_cjk=True)
    print(f"L1 置信度：{conf.confidence}")

    plan = build_jd_plan(requirements=JD, blocks=blocks)
    print(f"L3 计划：禁止引入 {', '.join(plan.forbidden_terms) or '无'}")

    final = rewrite_resume(blocks=blocks, plan=plan, model=None)
    print("\nL4 改写后：")
    for item in final:
        if item.changed:
            print(f"  改 {item.original_text}  ->  {item.rewritten_text}")

    tmp = tempfile.mkdtemp()
    store = ResumeVersionStore(db_path=str(Path(tmp) / "store.db"), artifact_root=str(Path(tmp) / "artifacts"))
    jd_hash = sha256_hex(" ".join(r.text for r in JD))

    commit_kwargs = dict(
        store=store,
        final=final,
        blocks=blocks,
        base_resume_version_id=None,
        plan_id=plan.plan_id,
        jd_content_hash=jd_hash,
        strategy_version="resume-tailor-plan-v1",
        mode="local",
        model_ref="none",
    )

    first = commit_resume(**commit_kwargs)
    print("\nL7 落盘：")
    print(f"  版本 id：{first.resume_version.resume_version_id}")
    print(f"  内容哈希：{first.resume_version.content_hash}")
    print(f"  血缘 id：{first.lineage.lineage_id}")

    second = commit_resume(**commit_kwargs)
    print(f"\n重复落盘：reused={second.reused}（同内容幂等）")

    # Gate W
    gate = GateWService()
    preview = gate.preview(tailor_id=first.lineage.tailor_id, result_hash=first.resume_version.content_hash, base_resume_version_id=None)
    fields = gate.apply(
        preview_token=preview.preview_token,
        confirmed=True,
        tailor_id=first.lineage.tailor_id,
        result_hash=first.resume_version.content_hash,
    )
    print(f"\nGate W：确认后放行，目标格式={fields['target_format']}")


if __name__ == "__main__":
    main()
