"""L1 语义块抽取与提取置信度门禁的测试。

覆盖：干净文本正确切块、各置信度信号、以及**真实损坏产物**（fixtures/out 里的
pdftotext 0% 中文、表格错乱）能被门禁判为低置信度。

运行：
    PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

from resume_tailor.domain.contracts import BlockKind, Section
from resume_tailor.extract.blocks import extract_blocks
from resume_tailor.extract.confidence import assess_extraction

CLEAN_TEXT = """张明
求职意向：后端开发工程师
电话：138-0000-0000 ｜ 邮箱：zhangming@example.com ｜ 城市：上海
教育背景
2019.09 – 2023.06  某某大学  计算机科学与技术  本科
工作经历
某某科技有限公司 ｜ 后端开发工程师 ｜ 2023.07 – 至今
· 负责订单履约模块开发，将核心查询接口 P99 从 320ms 降至 90ms
· 主导订单表分库分表改造，单表数据量从 8000 万降至 500 万
项目经历
订单履约系统重构 ｜ 2024.03 – 2024.09
· 使用 Spring Boot + MySQL + Redis 重构订单核心链路
专业技能
Java、Spring Boot、MySQL、Redis、Kafka"""


class TestExtractBlocks(unittest.TestCase):
    """干净文本的语义切块。"""

    def test_headings_and_sections(self) -> None:
        blocks = extract_blocks(CLEAN_TEXT)
        headings = [b for b in blocks if b.kind is BlockKind.HEADING]
        self.assertEqual(
            [(b.section, b.text) for b in headings],
            [
                (Section.EDUCATION, "教育背景"),
                (Section.WORK, "工作经历"),
                (Section.PROJECT, "项目经历"),
                (Section.SKILL, "专业技能"),
            ],
        )

    def test_meta_is_immutable(self) -> None:
        blocks = extract_blocks(CLEAN_TEXT)
        meta = [b for b in blocks if b.kind is BlockKind.META]
        self.assertTrue(meta, "应有 meta 块（联系方式）")
        self.assertTrue(all(b.immutable for b in meta))

    def test_skill_list_is_immutable(self) -> None:
        blocks = extract_blocks(CLEAN_TEXT)
        skill = [b for b in blocks if b.kind is BlockKind.SKILL_LIST]
        self.assertEqual(len(skill), 1)
        self.assertTrue(skill[0].immutable)

    def test_work_bullets_assigned_work_section(self) -> None:
        blocks = extract_blocks(CLEAN_TEXT)
        work_bullets = [b for b in blocks if b.kind is BlockKind.BULLET and b.section is Section.WORK]
        self.assertEqual(len(work_bullets), 3)
        self.assertTrue(all(not b.immutable for b in work_bullets))
        # bullet 标记被剥掉
        self.assertTrue(all(not b.text.startswith("·") for b in work_bullets))

    def test_no_overlap_blocks(self) -> None:
        """块文本集合应覆盖所有非空行（无重复、无遗漏）。"""
        blocks = extract_blocks(CLEAN_TEXT)
        source_lines = [l for l in CLEAN_TEXT.splitlines() if l.strip()]
        self.assertEqual(len(blocks), len(source_lines))


class TestConfidenceSignals(unittest.TestCase):
    """置信度信号。"""

    def test_clean_text_is_high(self) -> None:
        blocks = extract_blocks(CLEAN_TEXT)
        result = assess_extraction(text=CLEAN_TEXT, blocks=blocks, expected_cjk=True)
        self.assertEqual(result.confidence, "high", result.signals)

    def test_empty_is_low(self) -> None:
        result = assess_extraction(text="   \n", expected_cjk=True)
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.signals[0].name, "empty_text")

    def test_glued_tech_is_low(self) -> None:
        result = assess_extraction(text="JavaSpring BootMySQLRedisKafka", expected_cjk=True)
        self.assertEqual(result.confidence, "low")
        self.assertTrue(any(s.name == "glued_tech" for s in result.signals))

    def test_cjk_loss_is_low_when_expected(self) -> None:
        result = assess_extraction(text="Java Spring Boot MySQL Redis", expected_cjk=True)
        self.assertEqual(result.confidence, "low")
        self.assertTrue(any(s.name == "cjk_loss" for s in result.signals))

    def test_no_cjk_not_low_when_not_expected(self) -> None:
        result = assess_extraction(text="Java Spring Boot MySQL Redis", expected_cjk=False)
        self.assertNotEqual(result.confidence, "low", result.signals)


# 语料路径解析（与 test_regression_fixtures.py 同款：向上找 fixtures/）。
def _find_corpus(name: str) -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "fixtures" / "out" / name
        if candidate.is_file():
            return candidate
    return None


def _read_corpus(name: str) -> str | None:
    path = _find_corpus(name)
    if path is None:
        return None
    return path.read_text(encoding="utf-8", errors="replace")


class TestAgainstMeasuredArtifacts(unittest.TestCase):
    """在真实损坏产物上的回归。"""

    def test_pdftotext_output_is_low(self) -> None:
        text = _read_corpus("single-col.layout.txt")
        if text is None:
            self.skipTest("语料不可用")
        result = assess_extraction(text=text, expected_cjk=True)
        self.assertEqual(result.confidence, "low", "pdftotext 的 0% 中文 + 粘连必须被判低置信度")
        names = {s.name for s in result.signals}
        self.assertIn("glued_tech", names)

    def test_table_split_extraction_is_low(self) -> None:
        text = _read_corpus("table-split.extracted.txt")
        if text is None:
            self.skipTest("语料不可用")
        blocks = extract_blocks(text)
        result = assess_extraction(text=text, blocks=blocks, expected_cjk=True)
        self.assertEqual(result.confidence, "low", "表格简历章节错乱必须被判低置信度")
        names = {s.name for s in result.signals}
        self.assertIn("layout_meta_after_content", names)

    def test_plain_docx_extraction_is_high(self) -> None:
        text = _read_corpus("plain.extracted.txt")
        if text is None:
            self.skipTest("语料不可用")
        blocks = extract_blocks(text)
        result = assess_extraction(text=text, blocks=blocks, expected_cjk=True)
        self.assertEqual(result.confidence, "high", result.signals)


if __name__ == "__main__":
    unittest.main()
