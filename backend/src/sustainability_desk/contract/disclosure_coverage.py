# ABOUTME: 准则披露覆盖判定——按覆盖审定表与报告级义务注册表，对一份已装配报告做确定性合规判定。
# ABOUTME: 纯函数、无 LLM、无 IO 副作用；产出稳定 code 供审阅稿投影与 trace 留痕，判定本身不裁决法律合规。
# ABOUTME(en): Disclosure coverage verdicts: deterministic compliance judgement over an assembled report.
# ABOUTME(en): Pure, no LLM or IO; emits stable codes for review projection and trace, and adjudicates no legal claim.
from __future__ import annotations

from functools import lru_cache
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    knowledge_package_of,
    load_knowledge_package,
)
from sustainability_desk.contract.models import Report, Section
from sustainability_desk.contract.topic_registry import all_report_sections
from sustainability_desk.contract.visibility import visible

CoverageStatus = Literal[
    "bound_to_block",
    "metric_disclosure_catalog",
    "integrated_report_level",
    "excluded_for_simplified",
    "conditional_applicability",
]
ObligationKind = Literal["structural", "statement", "process", "fallback_statement"]

# 判定结论；轻量版全部作为审阅稿留意项处置，不阻断导出。
CoverageFindingCode = Literal[
    "requirement_covered",
    "requirement_conditional_not_triggered",
    "requirement_omitted_needs_statement",
    "requirement_excluded_by_design",
    "topic_requirements_pending",
]
ObligationVerdictCode = Literal["satisfied", "satisfied_via_fallback", "attention", "not_applicable"]


class RequirementCoverageEntry(BaseModel):
    """覆盖审定表的一条人工审定结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    coverageStatus: CoverageStatus
    exclusionRationaleCode: str | None = None
    userFacingNote: str | None = None


class TopicRequirementCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    topicStatus: Literal["reviewed", "requirements_pending"]
    requirements: dict[str, RequirementCoverageEntry] = {}


class ReportLevelDisclosureObligation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    obligationKey: str
    obligationTitle: str
    sourceLabel: str
    obligationText: str
    obligationKind: ObligationKind
    carrierSectionKeys: tuple[str, ...] = ()
    carrierBlockIds: tuple[str, ...] = ()
    userFacingNote: str


class CoverageFinding(BaseModel):
    """单条准则披露要求在本次报告中的承载结论。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: CoverageFindingCode
    reportSectionId: str
    requirementKey: str | None = None
    requirementTitle: str | None = None
    exclusionRationaleCode: str | None = None
    userFacingNote: str | None = None


class ObligationVerdict(BaseModel):
    """单条报告级义务在本次报告中的满足结论。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ObligationVerdictCode
    obligationKey: str
    obligationTitle: str
    userFacingNote: str | None = None


class DisclosureCoverageReport(BaseModel):
    """一次交付的完整合规判定结果，供审阅稿投影与 trace 留痕。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    findings: tuple[CoverageFinding, ...] = ()
    obligations: tuple[ObligationVerdict, ...] = ()

    @property
    def attention_findings(self) -> tuple[CoverageFinding, ...]:
        return tuple(f for f in self.findings if f.code == "requirement_omitted_needs_statement")

    @property
    def attention_obligations(self) -> tuple[ObligationVerdict, ...]:
        return tuple(o for o in self.obligations if o.code == "attention")

    @property
    def covered_requirement_count(self) -> int:
        return sum(1 for f in self.findings if f.code == "requirement_covered")

    def finding_codes(self) -> tuple[str, ...]:
        codes = {f.code for f in self.findings} | {
            f"obligation_{o.code}" for o in self.obligations if o.code == "attention"
        }
        return tuple(sorted(codes))


@lru_cache(maxsize=None)
def _load_requirement_coverage(package_id: str) -> dict[str, TopicRequirementCoverage]:
    package = load_knowledge_package(package_id)
    raw = yaml.safe_load(package.requirement_coverage_path.read_text(encoding="utf-8")) or {}
    return {
        topic: TopicRequirementCoverage.model_validate(entry)
        for topic, entry in (raw["topicRequirementCoverage"] or {}).items()
    }


def load_requirement_coverage(package: KnowledgePackage) -> dict[str, TopicRequirementCoverage]:
    return _load_requirement_coverage(package.id)


@lru_cache(maxsize=None)
def _load_report_level_obligations(
    package_id: str,
) -> tuple[ReportLevelDisclosureObligation, ...]:
    package = load_knowledge_package(package_id)
    raw = yaml.safe_load(package.report_level_obligations_path.read_text(encoding="utf-8")) or {}
    return tuple(
        ReportLevelDisclosureObligation.model_validate(item)
        for item in raw["reportLevelDisclosureObligations"] or []
    )


def load_report_level_obligations(
    package: KnowledgePackage,
) -> tuple[ReportLevelDisclosureObligation, ...]:
    return _load_report_level_obligations(package.id)


@lru_cache(maxsize=None)
def _requirement_titles(package_id: str) -> dict[str, str]:
    """requirementKey → 业务语言标题；审阅稿只展示标题，不展示 key。"""
    package = load_knowledge_package(package_id)
    titles: dict[str, str] = {}
    for path in sorted(package.standard_disclosure_requirements_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text()) or {}
        for group in raw.get("topicStandardDisclosureRequirementGroups") or []:
            for requirement in group["standardDisclosureRequirements"]:
                titles[requirement["standardDisclosureRequirementKey"]] = requirement[
                    "standardDisclosureRequirementTitle"
                ]
    return titles


def _iter_sections(sections: list[Section]):
    for section in sections:
        yield section
        yield from _iter_sections(section.children or [])


def _requirement_block_states(report: Report) -> dict[str, list[str]]:
    """requirementKey → 承载它的块在本次报告中的状态列表（同一要求可被多块承载）。"""
    states: dict[str, list[str]] = {}
    for block in report.iter_blocks():
        keys = (block.generation.standardDisclosureRequirementKeys if block.generation else None) or []
        for key in keys:
            states.setdefault(key, []).append(block.state)
    return states


def _visible_section_keys(report: Report) -> set[str]:
    return {
        section.key
        for section in _iter_sections(report.sections)
        if visible(section.appears_when, report)
    }


def _visible_block_ids(report: Report) -> set[str]:
    return {block.id for block in report.iter_blocks() if block.state != "omitted"}


def _included_topic_ids(report: Report) -> list[str]:
    """本次报告实际纳入的正式议题章节 id，按模板次序。"""
    present = {
        section.reportSectionId
        for section in _iter_sections(report.sections)
        if section.reportSectionId
    }
    return [
        section.id
        for section in all_report_sections(knowledge_package_of(report))
        if section.id in present
    ]


def evaluate_disclosure_coverage(report: Report) -> DisclosureCoverageReport:
    """对已装配（并已完成生成）的报告做披露覆盖与报告级义务判定。

    判定读取块的 `state`：`omitted` 是证据门控下的合法成功态，但对 required 要求而言，
    静默省略未附说明即构成需用户留意的事项——「省略并说明」合规，「静默省略」需留意。
    """
    package = knowledge_package_of(report)
    coverage_table = load_requirement_coverage(package)
    titles = _requirement_titles(package.id)
    block_states = _requirement_block_states(report)

    findings: list[CoverageFinding] = []
    for topic_id in _included_topic_ids(report):
        entry = coverage_table.get(topic_id)
        if entry is None or entry.topicStatus == "requirements_pending":
            findings.append(
                CoverageFinding(code="topic_requirements_pending", reportSectionId=topic_id)
            )
            continue
        for requirement_key, reviewed in entry.requirements.items():
            findings.append(
                _requirement_finding(
                    topic_id=topic_id,
                    requirement_key=requirement_key,
                    entry=reviewed,
                    states=block_states.get(requirement_key, []),
                    title=titles.get(requirement_key),
                )
            )

    return DisclosureCoverageReport(
        findings=tuple(findings),
        obligations=tuple(_obligation_verdicts(report)),
    )


def _requirement_finding(
    *,
    topic_id: str,
    requirement_key: str,
    entry: RequirementCoverageEntry,
    states: list[str],
    title: str | None,
) -> CoverageFinding:
    if entry.coverageStatus in ("excluded_for_simplified", "integrated_report_level"):
        return CoverageFinding(
            code="requirement_excluded_by_design",
            reportSectionId=topic_id,
            requirementKey=requirement_key,
            requirementTitle=title,
            exclusionRationaleCode=entry.exclusionRationaleCode,
            userFacingNote=entry.userFacingNote,
        )
    if entry.coverageStatus == "conditional_applicability":
        code: CoverageFindingCode = (
            "requirement_covered"
            if any(state != "omitted" for state in states)
            else "requirement_conditional_not_triggered"
        )
        return CoverageFinding(
            code=code,
            reportSectionId=topic_id,
            requirementKey=requirement_key,
            requirementTitle=title,
            exclusionRationaleCode=entry.exclusionRationaleCode,
            userFacingNote=entry.userFacingNote if code == "requirement_conditional_not_triggered" else None,
        )
    if entry.coverageStatus == "metric_disclosure_catalog":
        # 由定量指标目录与附录关键绩效表承载，指标缺值已由 readiness/指标链路各自判定。
        return CoverageFinding(
            code="requirement_covered",
            reportSectionId=topic_id,
            requirementKey=requirement_key,
            requirementTitle=title,
        )
    # bound_to_block：全部承载块被证据门控省略即为静默省略，需在定稿前补资料或补说明。
    if states and all(state == "omitted" for state in states):
        return CoverageFinding(
            code="requirement_omitted_needs_statement",
            reportSectionId=topic_id,
            requirementKey=requirement_key,
            requirementTitle=title,
            userFacingNote=entry.userFacingNote,
        )
    return CoverageFinding(
        code="requirement_covered",
        reportSectionId=topic_id,
        requirementKey=requirement_key,
        requirementTitle=title,
    )


def _obligation_verdicts(report: Report):
    section_keys = _visible_section_keys(report)
    block_ids = _visible_block_ids(report)
    for obligation in load_report_level_obligations(knowledge_package_of(report)):
        yield ObligationVerdict(
            code=_obligation_code(obligation, section_keys=section_keys, block_ids=block_ids),
            obligationKey=obligation.obligationKey,
            obligationTitle=obligation.obligationTitle,
            userFacingNote=obligation.userFacingNote,
        )


def _obligation_code(
    obligation: ReportLevelDisclosureObligation,
    *,
    section_keys: set[str],
    block_ids: set[str],
) -> ObligationVerdictCode:
    if obligation.obligationKind == "fallback_statement":
        # 出口类义务由具体缺口触发（见 findings），本身不独立判定。
        return "not_applicable"
    if obligation.obligationKind == "structural":
        missing = [key for key in obligation.carrierSectionKeys if key not in section_keys]
        missing += [bid for bid in obligation.carrierBlockIds if bid not in block_ids]
        return "attention" if missing else "satisfied"
    if not obligation.carrierSectionKeys and not obligation.carrierBlockIds:
        # 无承载位声明的声明义务（如报告名称）由交付环节决定，判定不臆断。
        return "not_applicable"
    if obligation.carrierBlockIds:
        # 声明义务的多个承载块是互斥变体，命中任一即满足。
        return "satisfied" if any(bid in block_ids for bid in obligation.carrierBlockIds) else "attention"
    return (
        "satisfied"
        if any(key in section_keys for key in obligation.carrierSectionKeys)
        else "attention"
    )
