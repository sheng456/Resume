"""L2 缺口诊断的测试。

核心命题：JD 的词被简历里的**同义短语**覆盖时，应判为覆盖而非缺失——
这是"术语对齐"（改词而不是补写）能成立的前提。

运行：
    PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import unittest

from resume_tailor.domain.contracts import Coverage
from resume_tailor.diagnose.gap import analyze_gaps
from tests.resume_fixtures import (
    REQ_EMPTY,
    REQ_JAVA,
    REQ_JAVA_KAFKA,
    REQ_K8S,
    REQ_MICRO,
    WORK_A,
    WORK_B,
    WORK_C,
)


class TestGapCoverage(unittest.TestCase):
    """覆盖三态。"""

    def test_synonym_counts_as_covered(self) -> None:
        """简历说"服务拆分"、JD 说"微服务架构"，应判覆盖而非缺失。"""
        (gap,) = analyze_gaps(requirements=[REQ_MICRO], blocks=[WORK_A])
        self.assertIs(gap.coverage, Coverage.COVERED)
        self.assertEqual(gap.best_block_ids, ("block:wa",))

    def test_partial_coverage(self) -> None:
        """命中一部分术语 -> PARTIAL。"""
        (gap,) = analyze_gaps(requirements=[REQ_JAVA_KAFKA], blocks=[WORK_C])
        self.assertIs(gap.coverage, Coverage.PARTIAL)
        self.assertIn("block:wc", gap.best_block_ids)

    def test_missing(self) -> None:
        (gap,) = analyze_gaps(requirements=[REQ_K8S], blocks=[WORK_B])
        self.assertIs(gap.coverage, Coverage.MISSING)
        self.assertEqual(gap.best_block_ids, ())

    def test_empty_requirement_is_missing_with_reason(self) -> None:
        (gap,) = analyze_gaps(requirements=[REQ_EMPTY], blocks=[WORK_C])
        self.assertIs(gap.coverage, Coverage.MISSING)
        self.assertEqual(gap.reason, "no_extractable_terms")


class TestBestBlockOrdering(unittest.TestCase):
    """最佳证据块按覆盖度排序。"""

    def test_most_relevant_block_first(self) -> None:
        (gap,) = analyze_gaps(requirements=[REQ_JAVA], blocks=[WORK_B, WORK_C])
        self.assertEqual(gap.best_block_ids, ("block:wc",))


class TestDeterminism(unittest.TestCase):
    """同输入同输出。"""

    def test_repeated_analysis_is_identical(self) -> None:
        first = analyze_gaps(requirements=[REQ_MICRO, REQ_JAVA], blocks=[WORK_A, WORK_C])
        second = analyze_gaps(requirements=[REQ_MICRO, REQ_JAVA], blocks=[WORK_A, WORK_C])
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
