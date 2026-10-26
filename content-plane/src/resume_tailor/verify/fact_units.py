"""事实单元抽取：把一段候选文本拆成可独立验证的最小断言。

设计要点
--------

抽取顺序是**先长后短、先具体后笼统**，每抽一类就用哨兵字符屏蔽掉，
避免同一段文字被重复归类（例如 ``2023.07 – 2024.09`` 不应再被
"4 位裸数字"规则抓成两个 metric）：

1. 手机号（屏蔽且**不产出单元**——它属于 meta，不该出现在工作 bullet 里）
2. 日期区间 / 时长 / 年月
3. 带单位的量化指标
4. 4 位裸数字（1900–2100 视为年份，否则视为指标）
5. 3 位以上裸数字（指标）
6. 技术词（走词库）
7. 机构类专有名词
8. 职级/程度词（单独参与方向性判定，见 ``extract_seniority``）

已知局限（M1 不处理，已在 README 记录）：
- ``8000 万`` 与 ``80000000`` 不被视为等价；
- 无 NER，专有名词只认机构后缀模式；
- 裸数字的"年份 vs 指标"用 1900–2100 启发式判定，可能误判。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ..domain.contracts import FactUnitClass
from ..lexicon.tech import TechLexicon

__all__ = [
    "RawUnit",
    "canonical_metric",
    "extract_fact_units",
    "extract_seniority",
    "normalize_text",
]

_MASK = "\x00"

# --------------------------------------------------------------------------- #
# 正则
# --------------------------------------------------------------------------- #

_RE_PHONE = re.compile(r"(?<!\d)(?:\d{3}[-\s]?\d{4}[-\s]?\d{4}|\d{11})(?!\d)")
_RE_DATE_RANGE = re.compile(
    r"\d{4}\s*[./\-年]\s*\d{1,2}\s*[-–—~～至到]\s*"
    r"(?:\d{4}\s*[./\-年]\s*\d{1,2}|至今|现在|present)",
    re.IGNORECASE,
)
_RE_YEAR_MONTH = re.compile(r"\d{4}\s*[./\-年]\s*\d{1,2}")
_RE_DURATION = re.compile(r"\d+(?:\.\d+)?\s*(?:个月|小时|分钟|秒钟|天|周)")
_RE_METRIC_UNIT = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|‰|倍|万人次|人次|万|亿|千|人|次|条|个|台|"
    r"qps|tps|rps|ms|毫秒|秒|min|kb|mb|gb|tb|kw)",
    re.IGNORECASE,
)
_RE_BARE_YEAR = re.compile(r"(?<![\d.])\d{4}(?![\d.])")
_RE_BARE_NUMBER = re.compile(r"(?<![\d.])\d{3,}(?![\d.])")
_RE_ORG = re.compile(r"[\u4e00-\u9fff]{2,12}(?:公司|集团|科技|大学|学院|实验室|研究院|银行|事业部|中心)")
_RE_NUM_UNIT = re.compile(r"^(\d+(?:\.\d+)?)\s*(.*)$", re.DOTALL)

# 乘数单位：会放大数值（8000 万 == 80000000 == 0.8 亿），折叠进数值参与等价判定。
_MULTIPLIER: dict[str, float] = {
    "千": 1e3,
    "万": 1e4,
    "亿": 1e8,
}

# 量纲单位：只表示物理量，不放大数值。键按最长前缀匹配。
_DIMENSION_CANON: dict[str, str] = {
    "人次": "person-time",
    "%": "percent",
    "‰": "permille",
    "倍": "times",
    "人": "person",
    "次": "count",
    "条": "count",
    "个": "count",
    "台": "count",
    "qps": "qps",
    "tps": "tps",
    "rps": "rps",
    "ms": "ms",
    "毫秒": "ms",
    "秒": "s",
    "min": "min",
    "分钟": "min",
    "小时": "h",
    "kb": "kb",
    "mb": "mb",
    "gb": "gb",
    "tb": "tb",
    "kw": "kw",
}

# --------------------------------------------------------------------------- #
# 职级 / 程度词阶梯（低 -> 高）
# --------------------------------------------------------------------------- #

ROLE_LADDER: tuple[tuple[str, ...], ...] = (
    ("参与", "协助", "配合", "支持", "协同"),
    ("负责", "承担", "独立完成", "独立负责"),
    ("主导", "牵头", "负责人", "owner", "主导设计", "主导开发"),
)

KNOWLEDGE_LADDER: tuple[tuple[str, ...], ...] = (
    ("了解", "接触过", "初步"),
    ("熟悉", "掌握", "使用", "运用"),
    ("精通", "深入理解", "熟练", "深刻理解"),
)

_LADDERS: dict[str, tuple[tuple[str, ...], ...]] = {
    "role": ROLE_LADDER,
    "knowledge": KNOWLEDGE_LADDER,
}

_ABSENT_RANK = -1


@dataclass(frozen=True)
class RawUnit:
    """尚未溯源的原始事实单元。"""

    text: str
    unit_class: FactUnitClass


def normalize_text(value: str) -> str:
    """NFKC 归一 + 小写 + 压缩空白。

    全角数字、全角百分号等会被折叠为半角，使 ``８０％`` 与 ``80%`` 可比。

    Args:
        value: 原始文本。

    Returns:
        归一化后的文本。
    """
    folded = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"\s+", " ", folded).strip()


def canonical_metric(raw: str) -> tuple[str, str] | None:
    """把带单位的量化文本归一成 ``(数值, 量纲)``。

    乘数单位（千/万/亿）折叠进数值，使 ``8000 万``、``80000000``、``0.8 亿``
    三者等价；量纲单位（ms/分钟/%/人次…）不放大数值，只作物理量标记。

    Args:
        raw: 形如 ``320ms`` / ``8000 万`` / ``1200`` 的片段。

    Returns:
        ``(归一数值字符串, 归一量纲)``；无法解析时返回 None。无单位时量纲为空。
    """
    match = _RE_NUM_UNIT.match(raw.strip())
    if match is None:
        return None
    number_str, unit_raw = match.group(1), match.group(2).strip().lower()
    if not unit_raw:
        return (number_str, "")

    multiplier = 1.0
    rest = unit_raw
    for length in range(len(unit_raw), 0, -1):
        key = unit_raw[:length]
        if key in _MULTIPLIER:
            multiplier = _MULTIPLIER[key]
            rest = unit_raw[length:]
            break

    dimension = ""
    if rest:
        for length in range(len(rest), 0, -1):
            key = rest[:length]
            if key in _DIMENSION_CANON:
                dimension = _DIMENSION_CANON[key]
                break
        if not dimension:
            dimension = rest

    if multiplier != 1.0:
        number_str = format(float(number_str) * multiplier, ".10g")

    return (number_str, dimension)


def extract_seniority(text: str) -> dict[str, tuple[int, str]]:
    """抽取职级/程度词的阶梯档位。

    取每条阶梯上**出现过的最高档**。因为高档词包含低档词
    （``负责人`` 含 ``负责``），取 max 正好得到正确的意图档位。

    Args:
        text: 任意文本。

    Returns:
        ``{阶梯名: (档位, 命中的词)}``；某条阶梯无命中则不出现该键。
    """
    result: dict[str, tuple[int, str]] = {}
    for ladder_name, ladder in _LADDERS.items():
        best_rank = _ABSENT_RANK
        best_term = ""
        for rank, terms in enumerate(ladder):
            for term in terms:
                if term in text and rank > best_rank:
                    best_rank, best_term = rank, term
        if best_rank > _ABSENT_RANK:
            result[ladder_name] = (best_rank, best_term)
    return result


def _masked(text: str, pattern: re.Pattern[str], sink: list[RawUnit], unit_class: FactUnitClass) -> str:
    """用哨兵屏蔽 pattern 的命中，并把命中记为原始单元。"""
    for match in pattern.finditer(text):
        sink.append(RawUnit(match.group(0).strip(), unit_class))
    return pattern.sub(lambda m: _MASK * len(m.group(0)), text)


def extract_fact_units(text: str, lexicon: TechLexicon) -> tuple[RawUnit, ...]:
    """抽取一段文本中全部可验证事实单元。

    Args:
        text: 候选（或源）文本。
        lexicon: 技术词词库。

    Returns:
        原始事实单元元组，顺序为抽取顺序。职级词不在此列，
        它们由 ``extract_seniority`` 单独处理（需要两侧对比才有意义）。
    """
    units: list[RawUnit] = []
    working = normalize_text(text)

    # 1) 手机号：屏蔽但不产出单元。
    working = _RE_PHONE.sub(lambda m: _MASK * len(m.group(0)), working)

    # 2) 时间类。顺序：区间 -> 时长 -> 年月。
    working = _masked(working, _RE_DATE_RANGE, units, FactUnitClass.TIME)
    working = _masked(working, _RE_DURATION, units, FactUnitClass.TIME)
    working = _masked(working, _RE_YEAR_MONTH, units, FactUnitClass.TIME)

    # 3) 带单位的量化指标。
    working = _masked(working, _RE_METRIC_UNIT, units, FactUnitClass.METRIC)

    # 4) 4 位裸数字：1900-2100 视为年份，否则视为指标。
    for match in list(_RE_BARE_YEAR.finditer(working)):
        value = int(match.group(0))
        unit_class = FactUnitClass.TIME if 1900 <= value <= 2100 else FactUnitClass.METRIC
        units.append(RawUnit(match.group(0), unit_class))
    working = _RE_BARE_YEAR.sub(lambda m: _MASK * len(m.group(0)), working)

    # 5) 3 位以上裸数字 -> 指标。
    working = _masked(working, _RE_BARE_NUMBER, units, FactUnitClass.METRIC)

    # 6) 技术词（在原文上匹配，不受屏蔽影响）。
    for canonical in sorted(lexicon.find(text)):
        units.append(RawUnit(canonical, FactUnitClass.TECH))

    # 7) 机构类专有名词。
    for match in _RE_ORG.finditer(normalize_text(text)):
        units.append(RawUnit(match.group(0), FactUnitClass.PROPER_NOUN))

    return tuple(units)


def seniority_terms(text: str) -> frozenset[str]:
    """返回文本中出现的全部职级/程度词。

    Args:
        text: 任意文本。

    Returns:
        命中的词集合。
    """
    found: set[str] = set()
    for ladder in _LADDERS.values():
        for terms in ladder:
            for term in terms:
                if term in text:
                    found.add(term)
    return frozenset(found)
