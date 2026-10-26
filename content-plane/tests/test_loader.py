"""P1 字节→文本提取的测试。

覆盖：DOCX 段落提取（中文保留）、DOCX 表格列结构保留（不交错）并被门禁判低、
Markdown/TXT 解码、GB18030 兜底、PDF 无提取器时的如实标记。

运行：
    PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

from resume_tailor.extract.loader import extract_text, extract_text_from_path


def _find_fixture(name: str) -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "fixtures" / name
        if candidate.is_file():
            return candidate
    return None


class TestDocxExtraction(unittest.TestCase):
    """DOCX 段落 + 表格。"""

    def test_plain_docx_keeps_cjk_and_high_confidence(self) -> None:
        path = _find_fixture("plain.docx")
        if path is None:
            self.skipTest("语料不可用")
        result = extract_text_from_path(path, expected_cjk=True)
        self.assertIn("工作经历", result.text)
        self.assertIn("张明", result.text)
        self.assertEqual(result.confidence.confidence, "high", result.confidence.signals)
        self.assertTrue(result.usable)

    def test_table_docx_preserves_columns_and_flagged(self) -> None:
        """两列表格：列结构用制表符保留，门禁判低（table_layout），不静默交错。"""
        path = _find_fixture("table-split.docx")
        if path is None:
            self.skipTest("语料不可用")
        result = extract_text_from_path(path, expected_cjk=True)
        self.assertIn("\t", result.text)
        # 联系方式这一行应同时含左栏「联系方式」与右栏「张明」，证明列配对未丢
        contact_line = next(line for line in result.text.splitlines() if "联系方式" in line)
        self.assertIn("张明", contact_line)
        names = {s.name for s in result.confidence.signals}
        self.assertIn("table_layout", names)
        self.assertEqual(result.confidence.confidence, "low")
        self.assertFalse(result.usable)


class TestTextDecoding(unittest.TestCase):
    """Markdown/TXT 解码。"""

    def test_markdown_roundtrip(self) -> None:
        raw = "# 个人总结\n- 负责订单系统服务拆分\n"
        result = extract_text(raw.encode("utf-8"), source_name="resume.md", expected_cjk=True)
        self.assertEqual(result.text, raw)
        self.assertEqual(result.confidence.confidence, "high")

    def test_gb18030_fallback(self) -> None:
        raw = "中文内容：负责订单系统"
        result = extract_text(raw.encode("gb18030"), source_name="resume.txt", expected_cjk=True)
        self.assertEqual(result.text, raw)


class TestPdfUnavailable(unittest.TestCase):
    """无 PDF 提取器时如实标记，不静默返回空串。"""

    def test_pdf_without_extractor_is_low(self) -> None:
        result = extract_text(b"%PDF-1.4 1 0 obj", source_name="resume.pdf", expected_cjk=True)
        self.assertEqual(result.confidence.confidence, "low")


if __name__ == "__main__":
    unittest.main()
