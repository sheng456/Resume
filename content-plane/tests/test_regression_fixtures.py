"""把 M1 与实测回归语料接起来。

`fixtures/` 里保存的是真实工具链的产出：headless Edge 打印的中文 PDF，
经本机 Xpdf 的 ``pdftotext -layout`` 提取。那份提取结果**汉字归零、
技术词粘连**——这是 `docs/FEASIBILITY-READ-WRITE.md` §2 的原始证据。

本测试确认：L5 的粘连检测器能在那份**真实损坏产物**上触发，
而不是只在我构造的字符串上触发。

语料缺失时跳过（语料是可选依赖，不应让单测失败）。

运行：
    PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

from resume_tailor.domain.contracts import BlockKind, ResumeBlock, Section
from resume_tailor.lexicon.tech import get_lexicon
from resume_tailor.verify.verifier import verify_edit

_RELATIVE_CORPUS = Path("fixtures") / "out" / "single-col.layout.txt"
_REAL_PDF_BROKEN_SKILL_LINE = "JavaSpring BootMySQLRedisKafkaDockerKubernetes"


def _find_corpus() -> Path | None:
    """向上搜索回归语料。

    暂存区布局与最终布局的层级深度不同（暂存区多两层），因此不能写死
    ``parents[N]``——改为从测试文件所在目录逐级向上找。
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _RELATIVE_CORPUS
        if candidate.is_file():
            return candidate
    return None


_REAL_PDF_EXTRACTION = _find_corpus()


def _read(path: Path | None) -> str | None:
    """读取语料文件，缺失或不可读时返回 None。"""
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


class TestAgainstMeasuredArtifacts(unittest.TestCase):
    """在真实损坏产物上的回归。"""

    def test_measured_glued_line_is_detected(self) -> None:
        """实测中那条粘连技能行必须被检出。"""
        glued = get_lexicon().find_glued(_REAL_PDF_BROKEN_SKILL_LINE)
        self.assertTrue(glued, "实测粘连行 JavaSpring BootMySQL… 未被检出")
        flattened = "+".join(glued)
        self.assertIn("java", flattened)
        self.assertIn("mysql", flattened)
        self.assertIn("kubernetes", flattened)

    def test_real_pdftotext_output_contains_glued_tech(self) -> None:
        """在真实 pdftotext 产物上触发，而不是只在构造字符串上触发。"""
        text = _read(_REAL_PDF_EXTRACTION)
        if text is None:
            self.skipTest(f"语料不可用：{_REAL_PDF_EXTRACTION}")

        verdict = verify_edit(
            source_blocks=[ResumeBlock("block:s1", Section.SKILL, BlockKind.SKILL_LIST, "技能")],
            candidate_text=text,
        )
        glued_issues = [issue for issue in verdict.ats_issues if issue.startswith("tech_glued:")]
        self.assertTrue(
            glued_issues,
            "真实提取产物中的技术词粘连未被检出——L1 置信度门禁的 tokenIntegrity 会失效",
        )

    def test_real_pdf_output_loses_all_chinese(self) -> None:
        """锁住实测结论：该提取路径汉字归零。

        这条断言若失败，说明提取器换了——`ARCHITECTURE.md` §5.1.1 的阈值
        需要重新标定，这本身就是需要被通知的变化。
        """
        text = _read(_REAL_PDF_EXTRACTION)
        if text is None:
            self.skipTest(f"语料不可用：{_REAL_PDF_EXTRACTION}")

        han = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
        self.assertEqual(han, [], "本机 pdftotext 路径的汉字保留率不再为 0，阈值需重新标定")


if __name__ == "__main__":
    unittest.main()
