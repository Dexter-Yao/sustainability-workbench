# ABOUTME: 用一次报告级结构化调用生成五个 ESG 报告模块实例标题。
# ABOUTME: 模型只看到模块 guidance、适用 H2 固定名和已解析 H4 标题，不接收正文、评分或内部元数据。
# ABOUTME(en): Generates the five ESG report module instance titles in one report-level structured call.
# ABOUTME(en): The model sees only module guidance, applicable fixed H2 names and resolved H4 titles; no prose or data.
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from sustainability_desk.contract.models import Report, Section
from sustainability_desk.contract.section_titles import (
    display_title_is_stale,
    resolved_display_title,
    title_source_block_is_omitted,
)
from sustainability_desk.contract.visibility import visible
from sustainability_desk.contract.knowledge_packages import knowledge_package_of, load_knowledge_package
from sustainability_desk.contract.topic_registry import all_report_modules
from sustainability_desk.llm.ai_observability import ObservationRun
from sustainability_desk.llm.client import build_agent
from sustainability_desk.llm.prompt_profiles import ModuleTitleGenerationTexts, load_prompt_profile
from sustainability_desk.llm.concurrency import run_agent
from sustainability_desk.llm.model_registry import DEFAULT_MODEL_ID


class ReportModuleTitleTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reportModuleId: str
    guidance: str
    reportSectionTitles: tuple[str, ...]
    h4Titles: tuple[str, ...]


class ReportModuleTitlesContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    knowledge_package_id: str
    modules: tuple[ReportModuleTitleTask, ...]
    tone: str


class GeneratedReportModuleTitle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reportModuleId: str
    displayTitle: str

    @field_validator("displayTitle")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("模块标题不得为空")
        return value


class GeneratedReportModuleTitles(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: list[GeneratedReportModuleTitle]


def _h4_sections(
    section: Section,
    report: Report,
    *,
    generation_scope_section_ids: frozenset[str] | None = None,
) -> list[Section]:
    # appears_when 为假的 H4 不进入正文与目录,其标题既不需生成也不得阻断模块标题;
    # 只对可见 H4 判定标题过期并向模型提供已解析标题。
    # generation_scope_section_ids 声明本次真实生成的议题范围：范围外议题的 H4
    # 不参与生成，其标题既不作为新鲜度前置条件，也不进入模块标题上下文
    # （完整轻量版传入全部议题，与既有行为等价）。
    return [
        h4
        for h2 in section.children or []
        if visible(h2, report)
        and (
            generation_scope_section_ids is None
            or h2.reportSectionId in generation_scope_section_ids
        )
        for h3 in h2.children or []
        if visible(h3, report)
        for h4 in h3.children or []
        if h4.headingLevel == 4
        and visible(h4, report)
        and not title_source_block_is_omitted(h4)
    ]


def build_report_module_titles_context(
    report: Report,
    *,
    generation_scope_section_ids: frozenset[str] | None = None,
) -> ReportModuleTitlesContext:
    package = knowledge_package_of(report)
    texts = _module_title_texts(package)
    report_modules = all_report_modules(package)
    definitions = {module.id: module for module in report_modules}
    modules = [section for section in report.sections if section.reportModuleId is not None]
    expected = tuple(module.id for module in report_modules)
    if tuple(section.reportModuleId for section in modules) != expected:
        raise ValueError(f"报告必须先完成 {len(expected)} 个 ESG 模块装配")
    tasks: list[ReportModuleTitleTask] = []
    for section in modules:
        if definitions[section.reportModuleId].titleGenerationGuidance is None:
            # Fixed module title: the navigation title is the display title, no model call.
            continue
        h4_sections = _h4_sections(
            section,
            report,
            generation_scope_section_ids=generation_scope_section_ids,
        )
        stale = [
            h4.title or h4.key
            for h4 in h4_sections
            if h4.titleGeneration is not None and display_title_is_stale(h4, report)
        ]
        if stale:
            raise ValueError(f"模块标题生成前须先处理过期 H4 标题：{'、'.join(stale)}")
        module_id = section.reportModuleId
        definition = definitions[module_id]
        tasks.append(
            ReportModuleTitleTask(
                reportModuleId=module_id,
                guidance=definition.titleGenerationGuidance,
                reportSectionTitles=tuple(child.title for child in section.children or []),
                h4Titles=tuple(resolved_display_title(h4, report) for h4 in h4_sections),
            )
        )
    return ReportModuleTitlesContext(
        knowledge_package_id=package.id, modules=tuple(tasks), tone=texts.tone
    )


def _module_title_texts(package) -> ModuleTitleGenerationTexts:
    """A package whose modules generate titles must word the task in its prompt profile."""

    texts = load_prompt_profile(package).module_title_generation
    if texts is None:
        raise ValueError(
            f"knowledge package {package.id} generates module titles but its prompt profile "
            "declares no module_title_generation texts"
        )
    return texts


def render_report_module_titles_prompt(context: ReportModuleTitlesContext) -> tuple[str, str]:
    package = load_knowledge_package(context.knowledge_package_id)
    texts = _module_title_texts(package)
    labels = load_prompt_profile(package).labels
    sep = labels.key_value_separator
    join = labels.list_separator.join
    system = texts.system_instruction.format(module_count=len(context.modules))
    lines = [f"{texts.tone_label}{sep}{context.tone}"]
    for module in context.modules:
        lines.extend(
            [
                f"{texts.module_id_label}{sep}{module.reportModuleId}",
                f"{texts.requirement_label}{sep}{module.guidance}",
                f"{texts.sections_label}{sep}" + join(module.reportSectionTitles),
                f"{texts.h4_titles_label}{sep}" + (join(module.h4Titles) or texts.none),
            ]
        )
    return system, "\n".join(lines)


async def generate_report_module_titles(
    report: Report,
    *,
    observation: ObservationRun,
    model_id: str = DEFAULT_MODEL_ID,
    generation_scope_section_ids: frozenset[str] | None = None,
) -> GeneratedReportModuleTitles:
    context = build_report_module_titles_context(
        report, generation_scope_section_ids=generation_scope_section_ids
    )
    system, user = render_report_module_titles_prompt(context)
    agent = build_agent(model_id, output_type=GeneratedReportModuleTitles, instructions=system)
    result = (
        await run_agent(
            agent,
            user,
            observation.invocation(
                block_id="report.module_titles",
                model_id=model_id,
                task_context=context.model_dump(mode="json"),
            ),
        )
    ).output
    expected = [module.reportModuleId for module in context.modules]
    actual = [module.reportModuleId for module in result.modules]
    if actual != expected:
        raise ValueError(f"模块标题输出必须按权威顺序完整返回 {len(expected)} 个模块")
    return result
