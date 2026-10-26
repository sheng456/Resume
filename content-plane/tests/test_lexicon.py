"""技术词词库回归：数字后缀（Python3）与 Python/数据方向词。"""

from __future__ import annotations

import unittest

from resume_tailor.lexicon.tech import get_lexicon


class TestTechLexicon(unittest.TestCase):
    """词库匹配。"""

    def test_python_version_suffix(self) -> None:
        lex = get_lexicon()
        self.assertIn("python", lex.find("1年以上Python3经验"))
        self.assertIn("python", lex.find("熟悉 Python 开发"))

    def test_python_data_terms(self) -> None:
        lex = get_lexicon()
        self.assertIn("正则表达式", lex.find("熟悉正则表达式"))
        self.assertIn("pycharm", lex.find("熟练使用 PyCharm"))
        self.assertIn("调试", lex.find("熟练使用 debugger"))
        self.assertIn("pandas", lex.find("使用 pandas 处理数据"))
        self.assertIn("flask", lex.find("用过 Flask 和 Tornado"))
        self.assertIn("数据分析", lex.find("具备数据分析能力"))

    def test_strict_boundary_still_protects(self) -> None:
        lex = get_lexicon()
        # go 不应命中 google（严格边界仍生效）
        self.assertNotIn("go", lex.find("google 搜索"))


if __name__ == "__main__":
    unittest.main()
