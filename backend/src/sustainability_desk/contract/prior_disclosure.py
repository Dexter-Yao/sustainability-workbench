# ABOUTME: 议题内已披露正文的领域对象与解析边界——把先落定的块正文解析为按支柱标注的 typed 事实。
# ABOUTME: 下游生成只消费「报告里已经写了什么」，不回头遍历 Section 树，也不感知 blockId 与生成状态。
# ABOUTME(en): Domain objects and parse boundary for prose already disclosed in a topic, typed and tagged by pillar.
# ABOUTME(en): Downstream generation consumes only what the report already says; it sees no blockId or generation state.
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from sustainability_desk.contract.compiled_definition import CompiledReportDefinition
from sustainability_desk.contract.models import PILLARS, Block, Report

# 报告支柱的固定先后：同一议题内先落定的支柱，其正文对后续支柱构成已披露事实。
# Pillar ids and their order are owned by contract.models.PILLARS; this module does not copy them.
PILLAR_ORDER = PILLARS


class PriorDisclosure(BaseModel):
    """同一议题中先于当前块落定、其事实已进入报告的正文。

    只承载下游改写所需的两件事：这段话属于哪个支柱、这段话写了什么。
    不含 blockId、生成状态、证据来源与节点结构——下游据此判断「哪些已经说过」，
    不据此反推实现细节。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pillar_title: str
    text: str


def _paragraph_text(block: Block) -> str:
    """段落块的已写入正文；未解析的字段引用视为尚未成文，不计入已披露事实。

    与审阅投影不同：审阅需要显示「[未解析字段引用]」提示人工，而生成侧一旦
    把该占位符当成已披露内容，模型会据此推断报告里存在一段并不存在的表述。
    """

    values: list[str] = []
    for item in block.content or []:
        if item.kind == "text" and item.text:
            values.append(item.text)
        elif item.fallback:
            values.append(item.fallback)
    return "".join(values).strip()


def _is_disclosed(block: Block) -> bool:
    """块正文是否已进入报告：仅 ready 段落块。

    生成中、失败与受控省略的块都没有正文可供参照；表格由各自的结论合同承载
    （见 iro_conclusions），不在本对象范围内。
    """

    return block.type == "paragraph" and block.state == "ready"


def prior_disclosures_for_block(
    report: Report,
    definition: CompiledReportDefinition,
    block_id: str,
) -> tuple[PriorDisclosure, ...]:
    """当前块生成时，同一议题内已经写入报告的正文（parse-first 边界）。

    「已经写入」按支柱先后判定：只取排在当前块所属支柱之前的支柱。同支柱内的块
    彼此并发、无先后可言，故不互相参照——宁可少给一层参照，也不把尚未落定的
    内容当成既成事实喂给模型。

    当前块无支柱归属（如议题摘要块是 planner 的互斥分支）时返回空。
    """

    try:
        current = definition.placement_for_block(block_id)
    except KeyError:
        return ()
    if current.pillar is None or current.report_section_id is None:
        return ()
    current_rank = PILLAR_ORDER.index(current.pillar)

    disclosures: list[PriorDisclosure] = []
    for block in report.iter_blocks():
        if block.id == block_id or not _is_disclosed(block):
            continue
        try:
            placement = definition.placement_for_block(block.id)
        except KeyError:
            continue
        if placement.report_section_id != current.report_section_id:
            continue
        if placement.pillar is None or placement.pillar_title is None:
            continue
        if PILLAR_ORDER.index(placement.pillar) >= current_rank:
            continue
        text = _paragraph_text(block)
        if text:
            disclosures.append(
                PriorDisclosure(pillar_title=placement.pillar_title, text=text)
            )
    return tuple(disclosures)


def pillar_rank_in_report(report: Report, block_id: str) -> int:
    """块所属支柱在披露顺序中的位次；无支柱归属时返回 -1（排在最前，不依赖在先正文）。

    从 Section 树的 H3 ``pillar`` 标识解析，与 ModelContext 的 section_placement 同源；
    生成编排据此分阶段，不新增契约声明。
    """

    trail: list[str] = []

    def walk(sections, ancestors: tuple[str, ...]) -> bool:
        for section in sections:
            here = ancestors + (
                (section.pillar,) if section.headingLevel == 3 and section.pillar else ()
            )
            if any(block.id == block_id for block in section.blocks):
                trail.extend(here)
                return True
            if section.children and walk(section.children, here):
                return True
        return False

    walk(report.sections, ())
    for pillar in trail:
        return PILLAR_ORDER.index(pillar)
    return -1
