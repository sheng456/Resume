"""L4 模型 reword 门禁的测试。

用**确定性假模型**（ScriptedModel）注入各种输出，验证双重门禁：

- 合法改写 -> 采纳；
- 凭空造数字 / 能力升级 / JD 注入 -> L5 拦截 -> 回退原文；
- 删减量化结果 / 技术词 -> 事实保留拦截 -> 回退原文；
- 空输出 / 代码块包裹 -> 解析回退；
- 提示词永不泄漏 JD 内容。

运行：
    PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import unittest

from resume_tailor.domain.contracts import BlockKind, ResumeBlock, Section
from resume_tailor.rewrite.reword import (
    build_reword_prompt,
    reword_block,
    reword_blocks,
)
from tests.resume_fixtures import SKILL, WORK_A


class ScriptedModel:
    """返回固定文本的假模型，用于把任意输出注入门禁。"""

    def __init__(self, text: str) -> None:
        self._text = text

    def reword(self, prompt: str) -> str:
        return self._text


JD_K8S = "岗位要求：有 Kubernetes 经验。"


class TestPromptDoesNotLeakJd(unittest.TestCase):
    """提示词的结构性保证：模型看不到 JD。"""

    def test_prompt_contains_source_but_not_jd_terms(self) -> None:
        prompt = build_reword_prompt(WORK_A.text)
        self.assertIn(WORK_A.text, prompt)
        self.assertNotIn("kubernetes", prompt)
        self.assertNotIn("岗位要求", prompt)

    def test_prompt_is_deterministic(self) -> None:
        self.assertEqual(build_reword_prompt(WORK_A.text), build_reword_prompt(WORK_A.text))


class TestValidRewriteAccepted(unittest.TestCase):
    """合法改写被采纳。"""

    def test_synonym_rewrite_with_metrics_preserved_is_accepted(self) -> None:
        model = ScriptedModel("负责订单系统微服务，接口 P99 从 320ms 降至 90ms")
        result = reword_block(source_block=WORK_A, model=model, jd_text=JD_K8S)
        self.assertTrue(result.changed)
        self.assertEqual(result.rewritten_text, "负责订单系统微服务，接口 P99 从 320ms 降至 90ms")


class TestFabricationRejected(unittest.TestCase):
    """任何臆造都被拦截并回退原文。"""

    def test_invented_metric_is_rejected(self) -> None:
        model = ScriptedModel("负责订单系统服务拆分，接口 P99 从 320ms 降至 45ms")
        result = reword_block(source_block=WORK_A, model=model, jd_text=JD_K8S)
        self.assertFalse(result.changed, "凭空把 90ms 改成 45ms 必须被拦截")
        self.assertEqual(result.rewritten_text, WORK_A.text)

    def test_upgraded_seniority_is_rejected(self) -> None:
        model = ScriptedModel("主导订单系统服务拆分，接口 P99 从 320ms 降至 90ms")
        result = reword_block(source_block=WORK_A, model=model, jd_text=JD_K8S)
        self.assertFalse(result.changed, "负责 -> 主导 必须被拦截")
        self.assertEqual(result.rewritten_text, WORK_A.text)

    def test_jd_injection_is_rejected(self) -> None:
        source = ResumeBlock(
            "block:p1", Section.PROJECT, BlockKind.BULLET,
            "使用 Spring Boot 与 MySQL 重构订单核心链路",
        )
        model = ScriptedModel("使用 Spring Boot 与 MySQL 与 Kubernetes 重构订单核心链路")
        result = reword_block(source_block=source, model=model, jd_text=JD_K8S)
        self.assertFalse(result.changed, "凭空加 Kubernetes 必须被拦截")
        self.assertEqual(result.rewritten_text, source.text)


class TestFactLossRejected(unittest.TestCase):
    """删减源事实必须被拦截。"""

    def test_dropped_metric_is_rejected(self) -> None:
        model = ScriptedModel("负责订单系统服务拆分，优化了接口性能")
        result = reword_block(source_block=WORK_A, model=model, jd_text=JD_K8S)
        self.assertFalse(result.changed, "删掉 320ms/90ms 必须被拦截")
        self.assertEqual(result.rewritten_text, WORK_A.text)

    def test_dropped_tech_is_rejected(self) -> None:
        source = ResumeBlock(
            "block:p1", Section.PROJECT, BlockKind.BULLET,
            "使用 Spring Boot 与 MySQL 重构订单核心链路",
        )
        model = ScriptedModel("使用 Spring Boot 重构订单核心链路")
        result = reword_block(source_block=source, model=model, jd_text=JD_K8S)
        self.assertFalse(result.changed, "删掉 MySQL 必须被拦截")
        self.assertEqual(result.rewritten_text, source.text)

    def test_changed_duration_is_rejected(self) -> None:
        """时长（分钟）也属硬事实：8 分钟 -> 3 分钟必须被拦截。"""
        source = ResumeBlock(
            "block:w4", Section.WORK, BlockKind.BULLET,
            "参与 CI/CD 流程建设，发布耗时从 25 分钟缩短至 8 分钟",
        )
        model = ScriptedModel("主导 CI/CD 流程建设，发布耗时从 25 分钟缩短至 3 分钟")
        result = reword_block(source_block=source, model=model, jd_text=JD_K8S)
        self.assertFalse(result.changed, "把 8 分钟改成 3 分钟必须被拦截")
        self.assertEqual(result.rewritten_text, source.text)

    def test_dropped_company_name_is_rejected(self) -> None:
        """机构专有名词（公司名）也属硬事实：删掉必须被拦截（修复 F5）。"""
        source = ResumeBlock(
            "block:w5", Section.WORK, BlockKind.BULLET,
            "在某某科技有限公司负责订单系统服务拆分",
        )
        model = ScriptedModel("负责订单系统服务拆分")
        result = reword_block(source_block=source, model=model, jd_text=JD_K8S)
        self.assertFalse(result.changed, "删掉公司名必须被拦截")
        self.assertEqual(result.rewritten_text, source.text)


class TestParsingFallbacks(unittest.TestCase):
    """解析与空输出的回退。"""

    def test_empty_output_keeps_original(self) -> None:
        result = reword_block(source_block=WORK_A, model=ScriptedModel(""), jd_text=JD_K8S)
        self.assertFalse(result.changed)

    def test_code_fence_is_stripped(self) -> None:
        model = ScriptedModel("```\n负责订单系统微服务，接口 P99 从 320ms 降至 90ms\n```")
        result = reword_block(source_block=WORK_A, model=model, jd_text=JD_K8S)
        self.assertTrue(result.changed)
        self.assertEqual(result.rewritten_text, "负责订单系统微服务，接口 P99 从 320ms 降至 90ms")

    def test_no_model_makes_no_change(self) -> None:
        result = reword_block(source_block=WORK_A, model=None, jd_text=JD_K8S)
        self.assertFalse(result.changed)
        self.assertEqual(result.rewritten_text, WORK_A.text)


class TestRewordBlocksBoundary(unittest.TestCase):
    """技能行不可改写。"""

    def test_skill_list_is_untouched(self) -> None:
        model = ScriptedModel("这条会被改写")  # 但技能行不经过模型
        results = reword_blocks(blocks=[SKILL, WORK_A], model=model, jd_text=JD_K8S)
        by_id = {r.block_id: r for r in results}
        self.assertEqual(by_id["block:skill"].rewritten_text, SKILL.text)
        self.assertFalse(by_id["block:skill"].changed)
        # WORK_A 被改写成了"这条会被改写"，但丢了事实 -> 回退原文
        self.assertEqual(by_id["block:wa"].rewritten_text, WORK_A.text)


if __name__ == "__main__":
    unittest.main()
