"""M2 共享测试夹具（虚构、脱敏内容）。

与 `fixtures/` 的回归语料同风格：某某公司 / 虚拟数字。JD 要求是虚构的
口径化要求项，用于驱动缺口分析与计划生成。
"""

from __future__ import annotations

from resume_tailor.domain.contracts import (
    BlockKind,
    JdRequirement,
    ResumeBlock,
    Section,
)

# ---- 简历块（虚构） ----
WORK_A = ResumeBlock(
    "block:wa",
    Section.WORK,
    BlockKind.BULLET,
    "负责订单系统服务拆分，接口 P99 从 320ms 降至 90ms",
)
WORK_B = ResumeBlock(
    "block:wb",
    Section.WORK,
    BlockKind.BULLET,
    "主导订单表分库分表改造，单表数据量从 8000 万降至 500 万",
)
WORK_C = ResumeBlock(
    "block:wc",
    Section.WORK,
    BlockKind.BULLET,
    "使用 Java 与 Spring Boot 开发订单核心链路",
)
PROJECT_KAFKA = ResumeBlock(
    "block:pk",
    Section.PROJECT,
    BlockKind.BULLET,
    "引入 Kafka 异步化，峰值 QPS 从 1200 提升至 4500",
)
SKILL = ResumeBlock(
    "block:skill",
    Section.SKILL,
    BlockKind.SKILL_LIST,
    "Java、Spring Boot、MySQL、Redis、Kafka",
)

ALL_BLOCKS = (WORK_A, WORK_B, WORK_C, PROJECT_KAFKA, SKILL)

# ---- JD 要求（虚构、口径化） ----
REQ_MICRO = JdRequirement("req:micro", "熟悉微服务架构")
REQ_MQ = JdRequirement("req:mq", "熟悉消息队列")
REQ_JAVA = JdRequirement("req:java", "熟悉 Java、Spring Boot")
REQ_JAVA_KAFKA = JdRequirement("req:jk", "熟悉 Java、Kafka")
REQ_K8S = JdRequirement("req:k8s", "有 Kubernetes 经验")
REQ_EMPTY = JdRequirement("req:empty", "要求详见附件说明")
