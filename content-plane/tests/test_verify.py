"""L5 事实锚点校验器的测试。

测试数据全部为虚构、脱敏内容（某某公司 / 某某大学 / 138-0000-0000），
与 `fixtures/` 的回归语料同源。

运行：
    PYTHONPATH=src python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

from resume_tailor.domain.contracts import (
    AnchorStatus,
    BlockKind,
    DeclaredFact,
    ResumeBlock,
    Section,
    VerdictDecision,
)
from resume_tailor.lexicon.tech import get_lexicon
from resume_tailor.verify.fact_units import canonical_metric, extract_fact_units
from resume_tailor.verify.verifier import verify_edit

# --------------------------------------------------------------------------- #
# Fixtures（虚构、脱敏）
# --------------------------------------------------------------------------- #

JD_TEXT = (
    "岗位要求：熟悉 Java、Spring Boot、MySQL、Redis、Kafka；"
    "有 Kubernetes 与 Docker 使用经验；具备高并发系统设计能力；本科及以上学历。"
)

WORK_1 = ResumeBlock(
    block_id="block:w1",
    section=Section.WORK,
    kind=BlockKind.BULLET,
    text="负责订单履约模块开发，将核心查询接口 P99 从 320ms 降至 90ms",
)
WORK_3 = ResumeBlock(
    block_id="block:w3",
    section=Section.WORK,
    kind=BlockKind.BULLET,
    text="参与 CI/CD 流程建设，发布耗时从 25 分钟缩短至 8 分钟",
)
WORK_2 = ResumeBlock(
    block_id="block:w2",
    section=Section.WORK,
    kind=BlockKind.BULLET,
    text="主导订单表分库分表改造，单表数据量从 8000 万降至 500 万",
)
PROJECT_1 = ResumeBlock(
    block_id="block:p1",
    section=Section.PROJECT,
    kind=BlockKind.BULLET,
    text="使用 Spring Boot + MySQL + Redis 重构订单核心链路",
)


class TestFactUnitExtraction(unittest.TestCase):
    """事实单元抽取。"""

    def test_metric_with_cjk_unit_is_canonicalised(self) -> None:
        self.assertEqual(canonical_metric("8000 万"), ("80000000", ""))
        self.assertEqual(canonical_metric("320ms"), ("320", "ms"))
        self.assertEqual(canonical_metric("25 分钟"), ("25", "min"))
        self.assertEqual(canonical_metric("1200"), ("1200", ""))

    def test_multiplier_units_are_numerically_equivalent(self) -> None:
        """乘数单位折叠进数值：8000 万 == 80000000 == 0.8 亿。"""
        self.assertEqual(canonical_metric("8000 万"), canonical_metric("80000000"))
        self.assertEqual(canonical_metric("8000 万"), canonical_metric("0.8 亿"))
        self.assertEqual(canonical_metric("500 万"), canonical_metric("0.05 亿"))

    def test_date_range_is_time_not_metric(self) -> None:
        units = extract_fact_units("2024.03 – 2024.09", get_lexicon())
        classes = {unit.unit_class.value for unit in units}
        self.assertIn("time", classes)
        self.assertNotIn("metric", classes)

    def test_phone_number_is_masked_and_not_a_unit(self) -> None:
        units = extract_fact_units("联系方式：138-0000-0000", get_lexicon())
        self.assertFalse(
            [u for u in units if "138" in u.text],
            "手机号不应被当成量化指标",
        )

    def test_bare_four_digit_year_is_time(self) -> None:
        units = extract_fact_units("2024 年加入", get_lexicon())
        self.assertTrue(any(u.unit_class.value == "time" for u in units))

    def test_bare_large_number_is_metric(self) -> None:
        units = extract_fact_units("峰值 QPS 从 1200 提升至 4500", get_lexicon())
        metrics = {u.text for u in units if u.unit_class.value == "metric"}
        self.assertEqual(metrics, {"1200", "4500"})


class TestAnchoring(unittest.TestCase):
    """四条锚定判定。"""

    def test_unchanged_text_is_accepted(self) -> None:
        verdict = verify_edit(source_blocks=[WORK_1], candidate_text=WORK_1.text, jd_text=JD_TEXT)
        self.assertIs(verdict.decision, VerdictDecision.ACCEPT)
        self.assertTrue(all(u.status is AnchorStatus.ANCHORED for u in verdict.units))

    def test_downgrade_is_abstracted_and_accepted(self) -> None:
        candidate = "参与订单履约模块开发，将核心查询接口 P99 从 320ms 降至 90ms"
        verdict = verify_edit(source_blocks=[WORK_1], candidate_text=candidate, jd_text=JD_TEXT)
        seniority = [u for u in verdict.units if u.unit_class.value == "seniority"]
        self.assertTrue(any(u.status is AnchorStatus.ABSTRACTED for u in seniority))
        self.assertIs(verdict.decision, VerdictDecision.ACCEPT, "降级表达不需要用户确认")

    def test_upgrade_requires_confirmation(self) -> None:
        candidate = "主导 CI/CD 流程建设，发布耗时从 25 分钟缩短至 8 分钟"
        verdict = verify_edit(source_blocks=[WORK_3], candidate_text=candidate, jd_text=JD_TEXT)
        seniority = [u for u in verdict.units if u.unit_class.value == "seniority"]
        self.assertTrue(any(u.status is AnchorStatus.UPGRADED for u in seniority))
        self.assertIs(verdict.decision, VerdictDecision.NEEDS_USER_CONFIRMATION)

    def test_invented_metric_is_unsupported(self) -> None:
        candidate = "负责订单履约模块开发，将核心查询接口 P99 从 320ms 降至 45ms"
        verdict = verify_edit(source_blocks=[WORK_1], candidate_text=candidate, jd_text=JD_TEXT)
        unsupported = [u for u in verdict.units if u.status is AnchorStatus.UNSUPPORTED]
        self.assertEqual([u.text for u in unsupported], ["45ms"])
        self.assertIs(verdict.decision, VerdictDecision.NEEDS_USER_CONFIRMATION)

    def test_declared_fact_makes_metric_anchored(self) -> None:
        candidate = "负责订单履约模块开发，将核心查询接口 P99 从 320ms 降至 45ms"
        verdict = verify_edit(
            source_blocks=[WORK_1],
            candidate_text=candidate,
            jd_text=JD_TEXT,
            declared_facts=[DeclaredFact("fact:1", "45ms", "2024 年压测报告")],
        )
        self.assertIs(verdict.decision, VerdictDecision.ACCEPT)
        self.assertTrue(any(u.anchor_ref == "fact:1" for u in verdict.units))

    def test_invented_organisation_is_unsupported(self) -> None:
        candidate = "在某某银行负责订单履约模块开发"
        verdict = verify_edit(source_blocks=[WORK_1], candidate_text=candidate, jd_text=JD_TEXT)
        self.assertTrue(
            any(
                u.unit_class.value == "proper_noun" and u.status is AnchorStatus.UNSUPPORTED
                for u in verdict.units
            )
        )

    def test_declared_fact_requires_evidence(self) -> None:
        with self.assertRaises(ValueError):
            DeclaredFact("fact:2", "45ms", "   ")

    def test_surviving_metrics_are_anchored_not_flagged(self) -> None:
        """改写保留了原量化结果时，不应产生任何 unsupported。"""
        candidate = "负责订单表分库分表改造，单表数据量从 8000 万降至 500 万"
        verdict = verify_edit(source_blocks=[WORK_2], candidate_text=candidate, jd_text=JD_TEXT)
        self.assertIs(verdict.decision, VerdictDecision.ACCEPT)


class TestJdInjection(unittest.TestCase):
    """JD 注入硬门禁。"""

    def test_tech_from_jd_not_in_resume_is_rejected(self) -> None:
        candidate = "使用 Spring Boot + MySQL + Redis + Kubernetes 重构订单核心链路"
        verdict = verify_edit(source_blocks=[PROJECT_1], candidate_text=candidate, jd_text=JD_TEXT)
        self.assertEqual(verdict.jd_injection, ("kubernetes",))
        self.assertIs(verdict.decision, VerdictDecision.REJECT, "JD 注入必须硬拒绝，用户无法确认绕过")

    def test_tech_absent_from_jd_is_unsupported_not_injection(self) -> None:
        """不在 JD 里的凭空技术词走 unsupported 分支，而不是注入分支。"""
        candidate = "使用 Spring Boot + MySQL + Redis + Spark 重构订单核心链路"
        verdict = verify_edit(source_blocks=[PROJECT_1], candidate_text=candidate, jd_text=JD_TEXT)
        self.assertEqual(verdict.jd_injection, ())
        self.assertIs(verdict.decision, VerdictDecision.NEEDS_USER_CONFIRMATION)

    def test_declared_fact_legitimises_jd_tech(self) -> None:
        candidate = "使用 Spring Boot + MySQL + Redis + Kubernetes 重构订单核心链路"
        verdict = verify_edit(
            source_blocks=[PROJECT_1],
            candidate_text=candidate,
            jd_text=JD_TEXT,
            declared_facts=[DeclaredFact("fact:k8s", "Kubernetes", "负责过 K8s 集群迁移")],
        )
        self.assertEqual(verdict.jd_injection, ())
        self.assertIs(verdict.decision, VerdictDecision.ACCEPT)

    def test_existing_tech_is_never_injection(self) -> None:
        candidate = "使用 MySQL + Redis 重构订单核心链路"
        verdict = verify_edit(source_blocks=[PROJECT_1], candidate_text=candidate, jd_text=JD_TEXT)
        self.assertEqual(verdict.jd_injection, ())

    def test_synonym_phrase_from_jd_is_injection(self) -> None:
        """同义短语（高并发）也属硬门禁：不在简历/声明里即 reject（修复 F4）。"""
        candidate = "使用 Spring Boot + MySQL + Redis 重构订单核心链路，支持高并发"
        verdict = verify_edit(source_blocks=[PROJECT_1], candidate_text=candidate, jd_text=JD_TEXT)
        self.assertEqual(verdict.jd_injection, ("高并发",))
        self.assertIs(verdict.decision, VerdictDecision.REJECT, "同义短语注入必须硬拒绝")


class TestAtsIssues(unittest.TestCase):
    """ATS 提示（不改变裁决）。"""

    def test_glued_tech_terms_are_detected(self) -> None:
        candidate = "JavaSpring BootMySQLRedisKafka"
        verdict = verify_edit(source_blocks=[WORK_1], candidate_text=candidate)
        self.assertTrue(
            any(issue.startswith("tech_glued:") for issue in verdict.ats_issues),
            f"应检出粘连，实际 ats_issues={verdict.ats_issues}",
        )

    def test_intact_tech_list_is_not_flagged_as_glued(self) -> None:
        candidate = "Java、Spring Boot、MySQL、Redis、Kafka、Docker、Kubernetes"
        verdict = verify_edit(source_blocks=[WORK_1], candidate_text=candidate)
        self.assertFalse(
            [i for i in verdict.ats_issues if i.startswith("tech_glued:")],
            "有顿号分隔的正常技能行不应被误判为粘连",
        )

    def test_javascript_is_not_mistaken_for_glued_java(self) -> None:
        """嵌套误判防线：JavaScript 含 java 子串，但最长匹配只算一个词。"""
        verdict = verify_edit(source_blocks=[WORK_1], candidate_text="使用 JavaScript 开发前端")
        self.assertFalse([i for i in verdict.ats_issues if i.startswith("tech_glued:")])

    def test_replacement_char_is_reported(self) -> None:
        verdict = verify_edit(source_blocks=[WORK_1], candidate_text="负责订单履约\ufffd模块开发")
        self.assertIn("replacement_char_present", verdict.ats_issues)


class TestDeterminism(unittest.TestCase):
    """同输入必须同输出——审批对象必须确定。"""

    def test_repeated_verification_is_identical(self) -> None:
        candidate = "主导订单履约模块开发，将核心查询接口 P99 从 320ms 降至 45ms"
        first = verify_edit(source_blocks=[WORK_1], candidate_text=candidate, jd_text=JD_TEXT)
        second = verify_edit(source_blocks=[WORK_1], candidate_text=candidate, jd_text=JD_TEXT)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
