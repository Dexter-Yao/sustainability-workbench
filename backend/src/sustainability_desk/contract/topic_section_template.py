# ABOUTME: 严格解析议题章节来源模板，并把唯一指标披露声明编译为运行态 Report 结构。
# ABOUTME: metricDisclosure 只属于 authoring contract；运行态 Section 不保存或反向推断该字段。
# ABOUTME(en): Strictly parses topic section source templates and compiles metric disclosure into runtime structure.
# ABOUTME(en): metricDisclosure belongs to the authoring contract; runtime Sections neither store nor back-infer it.
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationInfo, model_validator

from sustainability_desk.contract.models import (
    Block,
    Condition,
    ConditionRule,
    DerivedVisualizationSpec,
    ExplicitGenerationEvidenceSelector,
    GenerationInputs,
    GenerationSpec,
    GenerationTask,
    ImageModel,
    SOURCE_PILLARS,
    Section,
)
from sustainability_desk.contract.knowledge_packages import KnowledgePackage
from sustainability_desk.contract.loader import (
    validate_ai_source_paragraphs,
)
from sustainability_desk.quantitative_metrics import quantitative_metrics_by_key



class MetricDisclosureSpec(BaseModel):
    """一个报告 H2 的指标目录映射；空列表明确表示由模型提出通用指标名称。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    catalogMetricKeys: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_catalog_keys(self, info: ValidationInfo) -> MetricDisclosureSpec:
        if len(self.catalogMetricKeys) != len(set(self.catalogMetricKeys)):
            raise ValueError("metricDisclosure.catalogMetricKeys 不得重复")
        package = (info.context or {}).get("package")
        if package is None:
            raise ValueError("topic section templates must be validated with a knowledge package context")
        catalog = quantitative_metrics_by_key(package)
        for key in self.catalogMetricKeys:
            metric = catalog.get(key)
            if metric is None:
                raise ValueError(f"metricDisclosure 引用未知指标：{key}")
        return self


class TopicSectionTemplate(BaseModel):
    """议题章节 YAML 的 source-only 合同；解析后必须编译为普通 Section。"""

    model_config = ConfigDict(extra="forbid")

    section: Section
    metricDisclosure: MetricDisclosureSpec

    @model_validator(mode="after")
    def validate_source_pillars(self, info: ValidationInfo) -> TopicSectionTemplate:
        package = (info.context or {}).get("package")
        if package is None:
            raise ValueError("topic section templates must be validated with a knowledge package context")
        pillar_titles = package.manifest.pillar_titles
        children = tuple(self.section.children or ())
        source_pillars = tuple(child for child in children if child.title)
        if tuple(child.pillar for child in source_pillars) != SOURCE_PILLARS:
            raise ValueError(
                "议题模板的具名来源支柱必须按 governance → strategy → iro_management 声明三个 H3 并标注 pillar"
            )
        for child in source_pillars:
            expected_title = pillar_titles.title(child.pillar)
            if child.title != expected_title:
                raise ValueError(
                    f"支柱 {child.pillar} 的 H3 标题必须是知识包声明的「{expected_title}」，实际为「{child.title}」"
                )
        if any(child.headingLevel != 3 for child in source_pillars):
            raise ValueError("议题模板的三个来源支柱必须是 H3")
        for child in children:
            if child.headingLevel == 3 and (
                child.pillar == "metrics_targets" or child.key.endswith(".metrics")
            ):
                raise ValueError("指标与目标 H3 必须由 metricDisclosure 编译，不得在 section 中手写")
        for descendant in _iter_descendants(self.section):
            if descendant.pillar is not None and descendant.headingLevel != 3:
                raise ValueError(f"章节 {descendant.key} 不是 H3，不得声明 pillar")
        if self.section.conciseDisclosure is None:
            raise ValueError("议题模板必须声明 conciseDisclosure，由 Planner 与四支柱分支互斥装配")
        validate_ai_source_paragraphs([self.section], where=f"议题模板 {self.section.key}")
        return self


def _iter_descendants(section: Section):
    for child in section.children or ():
        yield child
        yield from _iter_descendants(child)


def _metric_narrative_condition(metric_keys: tuple[str, ...]) -> Condition | None:
    if not metric_keys:
        return None
    return Condition(
        all=[
            ConditionRule(path=f"quantitativeMetrics.{key}", op="not_exists")
            for key in metric_keys
        ]
    )


def compile_topic_section_template(
    template: TopicSectionTemplate, *, package: KnowledgePackage
) -> Section:
    """把一个严格来源模板编译成 Planner 消费的普通 H2 Section。"""

    section = template.section
    report_section_id = section.reportSectionId
    if report_section_id is None:
        raise ValueError("议题模板 section 缺少 reportSectionId")
    metric_keys = template.metricDisclosure.catalogMetricKeys
    metrics_key = f"{report_section_id}.metrics"
    narrative_block_id = f"{report_section_id}.metrics_narrative_body"

    narrative_block = Block(
        id=narrative_block_id,
        type="paragraph",
        blockType="constrained",
        source="ai",
        styleRole="body",
        generation=GenerationSpec(
            task=GenerationTask(
                mode="metric_narrative",
                focus=f"围绕“{section.title}”议题的指标体系建设与后续披露形成简短正文。",
            ),
            inputs=GenerationInputs(
                evidence=ExplicitGenerationEvidenceSelector(
                    kind="explicit",
                    quantitativeMetrics=list(metric_keys),
                )
            ),
            targetChars=(60, 160),
        ),
    )
    image_blocks: list[Block] = []
    if metric_keys:
        image_blocks.append(
            Block(
                id=f"{report_section_id}.metrics_summary",
                type="image",
                blockType="fixed",
                source="derived",
                styleRole="figure_inline",
                image=ImageModel(
                    # 不设题注：图是「指标与目标」小节下的唯一一幅，所属议题与小节标题已给全，
                    # 题注只会把上两级标题再念一遍。也不参与「图N」编号。
                    derivedVisualization=DerivedVisualizationSpec(
                        kind="quantitative_metric_summary",
                        metricKeys=list(metric_keys),
                        displayMode="auto",
                        emptyBehavior="hide",
                    )
                ),
            )
        )

    metrics = Section(
        key=metrics_key,
        title=package.manifest.pillar_titles.metrics_targets,
        pillar="metrics_targets",
        headingLevel=3,
        blocks=[
            *image_blocks,
            narrative_block.model_copy(
                update={"appears_when": _metric_narrative_condition(metric_keys)}
            ),
            # 素材图片承载位：该议题的排版素材在生成期确定性放置于章节末尾。
            Block(
                id=f"{report_section_id}.layout_assets",
                type="image",
                blockType="slot",
                source="user_input",
                styleRole="figure_inline",
                image=ImageModel(layoutAssetSlot=True),
            ),
        ],
    )
    return section.model_copy(update={"children": [*(section.children or []), metrics]})


def compiled_metric_disclosure_keys(section: Section) -> tuple[str, ...]:
    """从已编译 H2 的 typed 指标正文块读取唯一目录映射。

    来源模板仍只在 ``metricDisclosure`` 声明一次；编译后的指标正文选择器是运行态
    Evidence resolver 可消费的确定性投影，不通过 block id、标题或路径猜测语义。
    """

    candidates: list[Block] = []

    def walk(current: Section) -> None:
        for block in current.blocks:
            generation = block.generation
            if generation is not None and generation.task.mode == "metric_narrative":
                candidates.append(block)
        for child in current.children or []:
            walk(child)

    walk(section)
    if len(candidates) != 1:
        raise ValueError(
            f"报告章节 {section.reportSectionId or section.key} 必须有且仅有一个已编译指标正文块"
        )
    selector = candidates[0].generation.inputs.evidence
    if not isinstance(selector, ExplicitGenerationEvidenceSelector):
        raise ValueError("已编译指标正文块必须使用 explicit 证据选择器")
    return tuple(selector.quantitativeMetrics)
