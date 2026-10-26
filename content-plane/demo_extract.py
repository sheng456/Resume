"""L1 语义块抽取与置信度门禁的演示。

对比：干净简历 -> 正确切块 + 高置信度；真实损坏产物 -> 低置信度 + 具体信号。

运行：
    PYTHONPATH=src python3 demo_extract.py
"""

from __future__ import annotations

from pathlib import Path

from resume_tailor.domain.contracts import BlockKind
from resume_tailor.extract.blocks import extract_blocks
from resume_tailor.extract.confidence import assess_extraction

CLEAN = """张明
求职意向：后端开发工程师
电话：138-0000-0000 ｜ 邮箱：zhangming@example.com ｜ 城市：上海
教育背景
2019.09 – 2023.06  某某大学  计算机科学与技术  本科
工作经历
· 负责订单履约模块开发，将核心查询接口 P99 从 320ms 降至 90ms
· 主导订单表分库分表改造，单表数据量从 8000 万降至 500 万
专业技能
Java、Spring Boot、MySQL、Redis、Kafka"""

KIND_CN = {"heading": "标题", "meta": "联系方式", "bullet": "条目", "skill_list": "技能"}


def _corpus(name: str) -> str | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "fixtures" / "out" / name
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")
    return None


def main() -> None:
    """打印干净 vs 损坏的对比。"""
    print("=" * 78)
    print("① 干净简历：切块 + 置信度")
    print("=" * 78)
    blocks = extract_blocks(CLEAN)
    for b in blocks:
        print(f"  [{KIND_CN[b.kind.value]:>4}] ({b.section.value}) {b.text}")
    conf = assess_extraction(text=CLEAN, blocks=blocks, expected_cjk=True)
    print(f"\n  置信度：{conf.confidence}")

    for name, label in (
        ("single-col.layout.txt", "pdftotext 提取（0% 中文 + 技术词粘连）"),
        ("table-split.extracted.txt", "表格简历逐行交错（章节错乱）"),
        ("plain.extracted.txt", "单栏 docx（正常）"),
    ):
        text = _corpus(name)
        if text is None:
            print(f"\n  （语料不可用：{name}）")
            continue
        blocks = extract_blocks(text)
        conf = assess_extraction(text=text, blocks=blocks, expected_cjk=True)
        print(f"\n{'=' * 78}\n② {label}\n{'=' * 78}")
        print(f"  置信度：{conf.confidence}")
        for signal in conf.signals:
            print(f"    · {signal.name}: {signal.detail}")


if __name__ == "__main__":
    main()
