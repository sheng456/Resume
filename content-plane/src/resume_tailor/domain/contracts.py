"""数据契约。

对应 `docs/ARCHITECTURE.md` §4 的数据契约。字段名刻意与文档保持一致，避免
文档与实现分叉；个别地方做了 Python 化的扁平处理，已在字段注释中标明。

M1 覆盖指令解析（L3）与事实锚点校验（L5）；M2 追加 JD 驱动计划（L3）与
安全改写（L4 的确定性部分）。简历读取/落盘（L1/L7）仍不在本模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# --------------------------------------------------------------------------- #
# 枚举
# --------------------------------------------------------------------------- #


class Section(StrEnum):
    """简历章节。统一词表，废弃上游 ``job`` 中未定义的 ``general``。"""

    SUMMARY = "summary"
    EDUCATION = "education"
    WORK = "work"
    PROJECT = "project"
    SKILL = "skill"
    AWARD = "award"
    OTHER = "other"


class BlockKind(StrEnum):
    """语义块类型。"""

    BULLET = "bullet"
    HEADING = "heading"
    META = "meta"
    SKILL_LIST = "skill_list"


class FactUnitClass(StrEnum):
    """可验证事实单元的类别。"""

    METRIC = "metric"
    TIME = "time"
    PROPER_NOUN = "proper_noun"
    TECH = "tech"
    SENIORITY = "seniority"


class AnchorStatus(StrEnum):
    """单一事实单元的溯源判定结果。

    ``ABSTRACTED`` 与 ``UPGRADED`` 是能力表达的方向性判定：
    降级/等价变换（负责 -> 参与）通过；升级（参与 -> 主导）必须用户确认。
    """

    ANCHORED = "anchored"
    ABSTRACTED = "abstracted"
    UPGRADED = "upgraded"
    UNSUPPORTED = "unsupported"


class VerdictDecision(StrEnum):
    """整条改写的裁决。"""

    ACCEPT = "accept"
    NEEDS_USER_CONFIRMATION = "needs_user_confirmation"
    REJECT = "reject"


class IntentGoal(StrEnum):
    """用户指令的结构化目标。"""

    EMPHASIZE = "emphasize"
    DEEMPHASIZE = "deemphasize"
    CONDENSE = "condense"
    EXPAND = "expand"
    REWORD = "reword"
    REORDER = "reorder"


class Coverage(StrEnum):
    """JD 要求项在简历中的覆盖情况。"""

    COVERED = "covered"
    PARTIAL = "partial"
    MISSING = "missing"


class ParseConfidence(StrEnum):
    """指令解析置信度。``LOW`` 时必须澄清，不得直接生成计划。"""

    HIGH = "high"
    LOW = "low"


# --------------------------------------------------------------------------- #
# 输入契约
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ResumeBlock:
    """语义块：编辑的最小单位，无重叠。

    M1 只用 ``text`` 与 ``immutable``；其余字段为与文档契约对齐而保留。
    """

    block_id: str
    section: Section
    kind: BlockKind
    text: str
    immutable: bool = False


@dataclass(frozen=True)
class DeclaredFact:
    """用户显式声明的事实。

    这是唯一允许"无源事实"进入简历的入口，因此 ``evidence_note`` 必填。
    """

    fact_id: str
    text: str
    evidence_note: str

    def __post_init__(self) -> None:
        if not self.evidence_note.strip():
            raise ValueError("declared_fact_requires_evidence_note")


@dataclass(frozen=True)
class GapItem:
    """JD 要求项的缺口。

    ``requirement_terms`` 是该要求涉及的技术词（口径化），用于指令冲突检测。
    文档 §4 的原始契约只有 ``label``；这里补一个词表字段，否则无法判断
    "用户要弱化的东西是否正好是 JD 缺口"。
    """

    requirement_id: str
    label: str
    coverage: Coverage
    best_block_ids: tuple[str, ...] = ()
    requirement_terms: tuple[str, ...] = ()
    reason: str | None = None


# --------------------------------------------------------------------------- #
# 输出契约
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FactUnit:
    """一个可独立验证的最小断言。"""

    text: str
    unit_class: FactUnitClass
    status: AnchorStatus
    anchor_ref: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class Verdict:
    """改写文本的校验结论。

    ``jd_injection`` 非空即硬拒绝，用户无法通过确认绕过。
    """

    units: tuple[FactUnit, ...] = ()
    jd_injection: tuple[str, ...] = ()
    ats_issues: tuple[str, ...] = ()
    decision: VerdictDecision = VerdictDecision.ACCEPT


@dataclass(frozen=True)
class IntentConflict:
    """指令方向与 JD 缺口方向相反。"""

    requirement_id: str
    gap_direction: str
    instruction_direction: str


@dataclass(frozen=True)
class TailorIntent:
    """指令的结构化形态。

    只描述范围与目标，**不产出任何文本**——文本一律由 L4 生成并受 L5 校验。

    文档 §4 的契约写作 ``scope: {blockIds} | {sections}``；这里扁平为两个
    元组，便于 Python 侧消费，语义等价。
    """

    intent_id: str
    instruction_id: str | None = None
    goal: IntentGoal | None = None
    scope_block_ids: tuple[str, ...] = ()
    scope_sections: tuple[Section, ...] = ()
    parse_confidence: ParseConfidence = ParseConfidence.LOW
    conflicts_with_gap: tuple[IntentConflict, ...] = ()
    clarification_options: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_scope(self) -> bool:
        """指令是否指明了作用范围。"""
        return bool(self.scope_block_ids or self.scope_sections)


# --------------------------------------------------------------------------- #
# 改写层（M2 起）：JD 驱动计划与安全改写
# --------------------------------------------------------------------------- #


class EditOperation(StrEnum):
    """对单个语义块的操作类型。

    ``TERMINOLOGY_ALIGN`` 与 ``REORDER`` 是**确定性操作**，由代码机械执行、
    不经过模型，因此不可能臆造。``REWORD`` 是未来的模型层，仍须过 L5。
    """

    TERMINOLOGY_ALIGN = "terminology_align"
    REORDER = "reorder"
    REWORD = "reword"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class JdRequirement:
    """JD 里的一条要求（口径化后）。"""

    requirement_id: str
    text: str


@dataclass(frozen=True)
class AlignmentPair:
    """一条术语对齐：把简历里的原词换成 JD 的等价词。

    这是唯一能"凭空"让一个 JD 词进入简历的确定性途径，且必须带
    ``synonym_group`` 这条人工认定的事实等价证据。没有证据 = 不许改。
    """

    source_phrase: str
    target_phrase: str
    requirement_id: str
    synonym_group: int


@dataclass(frozen=True)
class EditBrief:
    """对一个语义块的编辑指令。**不携带任何目标文本。**

    文本要么由确定性操作（对齐/重排）机械生成，要么由模型生成后过 L5。
    ``seniority_ceiling`` 是模型改写时的硬上限：不得把它升到更高档位。
    ``direction`` 是指令的目标（口径化，如 ``emphasize``）；``origin`` 是该
    step 的驱动来源（``instruction`` / ``jd_gap``）。
    """

    block_id: str
    operation: EditOperation
    alignments: tuple[AlignmentPair, ...] = ()
    coverage: int = 0
    seniority_ceiling: int = -1
    direction: str | None = None
    origin: str = "jd_gap"


@dataclass(frozen=True)
class EditPlan:
    """一份精确的改写计划（Gate T 的审批对象）。

    ``forbidden_terms`` 是 JD 有、简历没有的技术词黑名单：任何改写路径
    （含模型）都不得引入它们。``bullet_order`` 是重排的全局排名。
    ``intent_id`` / ``instruction_hash`` 在指令驱动时非空，使"你的哪句话"
    也成为 Gate T 的审批对象。
    """

    plan_id: str
    driver: str = "jd_gap"
    steps: tuple[EditBrief, ...] = ()
    bullet_order: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    rejected: tuple[tuple[str, str], ...] = ()
    intent_id: str | None = None
    instruction_hash: str | None = None


@dataclass(frozen=True)
class RewrittenBlock:
    """安全改写后的块：原句与改写句并列，供 diff 评审。"""

    block_id: str
    original_text: str
    rewritten_text: str

    @property
    def changed(self) -> bool:
        """该块是否发生了变化。"""
        return self.original_text != self.rewritten_text


@dataclass(frozen=True)
class RewriteProposal:
    """一条改写提案：原句、候选句、以及候选句的校验结论。

    与 ``RewrittenBlock`` 的区别：提案**不做 fail-closed**——即使校验不通过，
    也保留候选句，交由 L6 评审让用户决定接受 / 拒绝 / 声明事实。
    ``facts_retained`` 表示候选是否保留了源块的量化与技术事实（防删减）。
    """

    block_id: str
    original_text: str
    proposed_text: str
    verdict: Verdict
    facts_retained: bool = True

    @property
    def changed(self) -> bool:
        """候选是否不同于原句。"""
        return self.original_text != self.proposed_text

    @property
    def acceptable(self) -> bool:
        """候选是否可直接接受（L5 通过且事实保留）。"""
        return self.verdict.decision is VerdictDecision.ACCEPT and self.facts_retained


# --------------------------------------------------------------------------- #
# L7 版本与血缘
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ResumeVersion:
    """一份已落盘的简历版本元数据。

    身份规则与 boss-watch-agent 对齐：``content_hash = sha256(渲染字节)``，
    ``resume_version_id = "resume-version:" + content_hash``。正文不进元数据，
    只存哈希与内容寻址引用。
    """

    resume_version_id: str
    display_name: str
    local_artifact_ref: str
    content_hash: str
    media_type: str
    byte_size: int
    created_at: str
    supersedes_resume_version_id: str | None = None


@dataclass(frozen=True)
class TailorLineage:
    """一次改写落盘的血缘：把新版本、基础版本、JD、计划、模型串起来。"""

    lineage_id: str
    new_resume_version_id: str
    base_resume_version_id: str | None
    tailor_id: str
    plan_id: str
    jd_content_hash: str
    mode: str
    model_ref: str
    strategy_version: str
    created_at: str
