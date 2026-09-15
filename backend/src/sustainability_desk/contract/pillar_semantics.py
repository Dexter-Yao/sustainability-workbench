# ABOUTME: 四支柱的统一语义合同，由报告正式支柱名称解析，供生成、评估与人类审阅同源投影。
# ABOUTME: 本模块只表达跨议题稳定职责；议题专属 guidance 仍归各 topic section block 所有。
# ABOUTME(en): Unified semantic contract for the four pillars, resolved from the report's official pillar names.
# ABOUTME(en): Expresses cross-topic stable responsibilities only; topic guidance stays in each topic section block.
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from sustainability_desk.contract.models import Pillar, Report, Section

if TYPE_CHECKING:
    from sustainability_desk.llm.prompt_profiles import ReportGenerationPromptProfile


class PillarPurpose(BaseModel):
    """一个报告支柱的业务职责，不含生成实现细节。

    ``pillar`` is the stable identity code branches on; ``name`` is the package's display title
    of that pillar (the H3 as printed in the report), used only for human-facing projections.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pillar: Pillar
    name: str
    writingFocus: str
    trainingFocus: str = ""


PILLAR_PURPOSES: dict[Pillar, PillarPurpose] = {
    "governance": PillarPurpose(
        pillar="governance",
        name="治理",
        writingFocus="聚焦监督职责、组织架构、制度框架、决策机制与议题管理能力，不展开一线操作措施。",
        trainingFocus="如涉及培训，重点是议题管理职责人员对该议题的理解和管理能力建设。",
    ),
    "strategy": PillarPurpose(
        pillar="strategy",
        name="战略",
        writingFocus="聚焦高层目标、风险与机遇判断、总体方向和主要路径，不下沉到具体产品、工序或操作动作。",
    ),
    "iro_management": PillarPurpose(
        pillar="iro_management",
        name="影响、风险与机遇管理",
        writingFocus="聚焦影响、风险与机遇的识别评估流程、管理实践、行动及实施措施。",
        trainingFocus="如涉及培训，可面向与议题相关的内外部人员；内容可覆盖宏观认知或有事实支撑的实操能力。",
    ),
    "metrics_targets": PillarPurpose(
        pillar="metrics_targets",
        name="指标与目标",
        writingFocus=(
            "聚焦指标、目标与进展；有报告年度定量数值时由确定性可视化合同展示，"
            "无定量指标事实但支柱适用时，只说明适合关注的指标、目标或披露维度。"
        ),
    ),
}

def _find_pillar(sections: list[Section], block_id: str, current_pillar: Section | None = None) -> Section | None:
    for section in sections:
        pillar = section if section.headingLevel == 3 else current_pillar
        if any(block.id == block_id for block in section.blocks):
            return pillar
        found = _find_pillar(section.children or [], block_id, pillar)
        if found is not None:
            return found
    return None


def pillar_purpose_for(pillar: Pillar, title: str) -> PillarPurpose:
    """The cross-topic purpose of a pillar, named with the package's display title of that H3."""

    return PILLAR_PURPOSES[pillar].model_copy(update={"name": title})


def resolve_pillar_purpose(report: Report, block_id: str) -> PillarPurpose | None:
    """从 Report 的 H3 支柱标识解析职责；未标注 pillar 的 H3 不猜测。"""
    pillar = _find_pillar(report.sections, block_id)
    if pillar is None or pillar.pillar is None:
        return None
    return pillar_purpose_for(pillar.pillar, pillar.title)


def resolve_public_disclosure_guidance(
    disclosure_stance: str, profile: ReportGenerationPromptProfile
) -> str:
    """只有风险披露块需要额外的公开披露距离；措辞由包 profile 拥有。"""
    return (
        profile.public_risk_disclosure_guidance
        if disclosure_stance == "risk_disclosure"
        else ""
    )


def context_only_calibration_lines(
    purpose: PillarPurpose | None, profile: ReportGenerationPromptProfile
) -> tuple[str, ...]:
    """投影生成与 Judge 共用的支柱条件式示例；无配置的支柱不产生提示片段。"""

    if purpose is None:
        return ()
    examples = getattr(profile.context_only_calibration, purpose.pillar, None)
    if not examples:
        return ()
    return (
        profile.labels.structure.context_only_calibration_lead,
        *(f"- {example}" for example in examples),
    )
