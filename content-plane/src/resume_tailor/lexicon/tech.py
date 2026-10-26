"""技术词词库：把文本里出现的技术词归一到 canonical 名称。

词库来源与取舍
--------------

合并了两份上游词表：

1. ``job/src/match/skills_map.json``（21 条 alias -> canonical 映射）
2. ``boss-watch-agent`` 的 ``SKILL_ALIASES``（29 项技术词，含 RAG / LLM / Agent）

**刻意丢弃了若干两字母英文别名**（``fe`` / ``be`` / ``pm`` / ``cv`` / ``ml`` /
``dl`` / ``es``）。上游把它们当同义词用，但在事实校验场景下代价太高：

- ``be`` 会命中英文里的 "will be"，把普通句子判成"后端"；
- ``cv`` 在简历语境里既可能是"计算机视觉"也可能是 curriculum vitae；
- ``ml`` / ``dl`` / ``es`` 同理。

事实校验的假阳性会直接变成错误的"事实单元"，比漏检更糟。中文写法
（前端 / 后端 / 计算机视觉 / 机器学习 / 深度学习）仍全部保留，
``k8s`` / ``mq`` / ``py`` / ``pg`` 等低碰撞别名也保留。

两种匹配模式
------------

- **严格模式**（``find``）：ASCII 别名带词边界断言，避免 ``go`` 命中
  ``google``。正常文本的提取走这条。
- **宽松模式**（``scan_longest``）：无边界，贪心最长匹配切分一个连续
  alphanumeric 片段。只用于检测**技术词粘连**——粘连恰恰破坏了词边界
  （``JavaSpring`` 里的 ``java`` 在严格模式下匹配不到），所以必须换一套。

贪心最长匹配同时避免了嵌套误判：``JavaScript`` 在严格模式下含 ``java``
子串，但最长匹配会整段吃掉 ``javascript``，只算一个词。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

__all__ = ["TechLexicon", "get_lexicon"]

_DATA_PATH = Path(__file__).with_name("data") / "tech_terms.json"

# ASCII 别名用边界断言，避免 go 命中 google。
# 边界字符集排除 # 与 +，使 c++ / c# 能被当作整体。
_BOUNDARY = r"[A-Za-z0-9+#.]"

# 连续 alphanumeric 片段：粘连检测的输入单位。
RE_ALNUM_RUN = re.compile(r"[A-Za-z][A-Za-z0-9+#.]*")


def _is_ascii(value: str) -> bool:
    """判断别名是否全为 ASCII。

    Args:
        value: 待判断的别名。

    Returns:
        全为 ASCII 时返回 True。
    """
    return all(ord(ch) < 128 for ch in value)


class TechLexicon:
    """技术词匹配器。

    Attributes:
        canonical_names: 全部 canonical 名称。
    """

    def __init__(self, canonical_to_aliases: dict[str, list[str]]) -> None:
        self._canonical_names: frozenset[str] = frozenset(canonical_to_aliases)

        strict: list[tuple[re.Pattern[str], str]] = []
        loose: dict[str, str] = {}
        for canonical, aliases in canonical_to_aliases.items():
            for alias in aliases:
                if _is_ascii(alias):
                    strict.append(
                        (
                            re.compile(
                                rf"(?<!{_BOUNDARY}){re.escape(alias)}(?!{_BOUNDARY})",
                                re.IGNORECASE,
                            ),
                            canonical,
                        )
                    )
                else:
                    strict.append((re.compile(re.escape(alias)), canonical))
                loose[alias.lower()] = canonical

        self._strict: tuple[tuple[re.Pattern[str], str], ...] = tuple(strict)
        self._loose: dict[str, str] = loose
        self._max_alias_len: int = max((len(alias) for alias in loose), default=1)

    @property
    def canonical_names(self) -> frozenset[str]:
        """全部 canonical 名称。"""
        return self._canonical_names

    def find(self, text: str) -> frozenset[str]:
        """找出文本中出现的技术词（严格模式，canonical 形式）。

        Args:
            text: 任意文本。

        Returns:
            命中的 canonical 名称集合；无命中时为空集合。
        """
        found: set[str] = set()
        for pattern, canonical in self._strict:
            if canonical not in found and pattern.search(text):
                found.add(canonical)
        return frozenset(found)

    def scan_longest(self, segment: str) -> tuple[str, ...]:
        """在连续片段上做贪心最长匹配，返回命中的 canonical 序列。

        用于粘连检测：一个片段里出现 2 个以上词，说明它们之间缺少分隔符。

        Args:
            segment: 不含分隔符的连续片段，如 ``JavaSpring``。

        Returns:
            按出现顺序排列的 canonical 名称；未命中时为空元组。
        """
        return self._scan_covered(segment)[0]

    def _scan_covered(self, segment: str) -> tuple[tuple[str, ...], int]:
        """贪心最长匹配，同时返回被技术词覆盖的字符数（用于排除误报）。"""
        lowered = segment.lower()
        hits: list[str] = []
        covered = 0
        index = 0
        while index < len(lowered):
            matched = False
            upper = min(self._max_alias_len, len(lowered) - index)
            for length in range(upper, 0, -1):
                canonical = self._loose.get(lowered[index : index + length])
                if canonical is not None:
                    hits.append(canonical)
                    covered += length
                    index += length
                    matched = True
                    break
            if not matched:
                index += 1
        return tuple(hits), covered

    def find_glued(self, text: str) -> tuple[str, ...]:
        """检测技术词粘连。

        实测依据：PDF 提取丢失中文顿号后，``Java、Spring Boot、MySQL`` 会变成
        ``JavaSpring BootMySQL``，相邻技术词之间不再有任何分隔符，技能段的
        关键词匹配会整体失效。

        只有连续片段**基本被技术词铺满**（覆盖 ≥ 75%）才算真粘连：否则
        ``PyEcharts+Qt`` 这类产品名里恰含 ``py`` / ``ts`` 短别名会被误报。

        Args:
            text: 任意文本。

        Returns:
            粘连的片段描述，形如 ``"JavaSpring(java+spring)"``。
        """
        glued: list[str] = []
        for match in RE_ALNUM_RUN.finditer(text):
            run = match.group(0)
            hits, covered = self._scan_covered(run)
            if len(hits) >= 2 and covered >= 0.75 * len(run):
                glued.append(f"{run}({'+'.join(hits)})")
        return tuple(glued)


@lru_cache(maxsize=1)
def get_lexicon() -> TechLexicon:
    """加载内置技术词词库（进程内缓存）。

    Returns:
        共享的 TechLexicon 实例。
    """
    raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return TechLexicon({canonical: list(aliases) for canonical, aliases in raw.items()})
