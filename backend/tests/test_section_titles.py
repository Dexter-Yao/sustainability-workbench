# ABOUTME: 动态章节标题合同测试，覆盖统一解析、H4 正文指纹、H1 级联失效和五模块结构化输出。
# ABOUTME: 所有生成均使用假 Agent；测试不调用真实模型。
from __future__ import annotations

from types import SimpleNamespace

import pytest

from sustainability_desk.contract.models import (
    Block,
    Inline,
    Report,
    Section,
    SectionDisplayTitle,
    SectionTitleGeneration,
)
from sustainability_desk.contract.section_titles import (
    display_title_is_stale,
    module_fingerprint,
    paragraph_fingerprint,
    resolved_display_title,
    section_title_input_fingerprint,
)
from sustainability_desk.contract.topic_registry import all_report_modules
from sustainability_desk.llm.ai_observability import create_observation_run
from sustainability_desk.contract.visibility import visible
from sustainability_desk.llm.generate_module_titles import (
    GeneratedReportModuleTitles,
    build_report_module_titles_context,
    generate_report_module_titles,
    render_report_module_titles_prompt,
)
from stage_test_support import TEST_UNIT_STAGE, unit_span
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_templates_from

TOPIC_DIR = SSE_PACKAGE.topic_sections_dir


def _h4_report() -> tuple[Report, Section, Block]:
    block = Block(
        id="climate.gov.practice",
        type="paragraph",
        blockType="generative",
        source="ai",
        content=[Inline(kind="text", text="当前正文")],
    )
    h4 = Section(
        key="climate.gov.practice",
        title="治理实践",
        headingLevel=4,
        titleGeneration=SectionTitleGeneration(
            sourceBlockId=block.id,
            guidance="概括本段治理实践。",
        ),
        blocks=[block],
    )
    module = Section(
        key="environmental_sustainability",
        title="环境可持续",
        headingLevel=1,
        reportModuleId="environmental_sustainability",
        children=[
            Section(
                key="climate_change",
                title="应对气候变化",
                headingLevel=2,
                reportSectionId="climate_change",
                children=[
                    Section(
                        key="climate.gov",
                        title="治理",
                        headingLevel=3,
                        children=[h4],
                    )
                ],
            )
        ],
    )
    return Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[module]), h4, block


def test_h4_title_becomes_stale_when_source_body_changes() -> None:
    report, h4, block = _h4_report()
    h4.displayTitle = SectionDisplayTitle(
        text="治理协同与实践",
        origin="generated",
        inputFingerprint=paragraph_fingerprint(block.content),
    )
    assert resolved_display_title(h4, report) == "治理协同与实践"
    assert not display_title_is_stale(h4, report)

    block.content = [Inline(kind="text", text="正文已由用户修改")]
    assert display_title_is_stale(h4, report)


def test_omitted_title_source_block_carries_no_title_obligation() -> None:
    """证据门控源块受控省略：节不进正文与目录，无标题义务，不得判 stale 阻断导出。

    缺陷回归：举报机制块（组合门控）被省略后 displayTitle 恒为 None，
    若 display_title_is_stale 据此恒真，会以 block 级
    stale_display_title 阻断整份报告的全部交付物。
    """
    report, h4, block = _h4_report()
    block.state = "omitted"
    assert h4.displayTitle is None
    assert not display_title_is_stale(h4, report)

    # 源块恢复生成后标题义务照常回归。
    block.state = "ready"
    assert display_title_is_stale(h4, report)


def test_omitted_h4_stays_out_of_module_title_context_and_fingerprint() -> None:
    """已省略 H4 不进入模块标题上下文与模块指纹；恢复后自动回归（指纹随之变化）。"""
    from sustainability_desk.llm.generate_module_titles import _h4_sections

    report, h4, block = _h4_report()
    module = report.sections[0]

    block.state = "omitted"
    assert h4 not in _h4_sections(module, report)
    fingerprint_omitted = module_fingerprint(module, report)

    block.state = "ready"
    assert h4 in _h4_sections(module, report)
    assert module_fingerprint(module, report) != fingerprint_omitted


def test_h4_body_change_cascades_to_module_title_fingerprint() -> None:
    report, h4, block = _h4_report()
    h4.displayTitle = SectionDisplayTitle(
        text="治理协同与实践",
        origin="generated",
        inputFingerprint=paragraph_fingerprint(block.content),
    )
    module = report.sections[0]
    before = module_fingerprint(module, report)

    block.content = [Inline(kind="text", text="正文已由用户修改")]
    assert module_fingerprint(module, report) != before


def _five_module_report() -> Report:
    modules = []
    for definition in all_report_modules(SSE_PACKAGE):
        modules.append(Section(
            key=definition.id,
            title=definition.navigationTitle,
            headingLevel=1,
            reportModuleId=definition.id,
            children=[Section(
                key=f"{definition.id}.section",
                title=f"{definition.navigationTitle}议题",
                headingLevel=2,
                reportSectionId="climate_change",
            )],
        ))
    return Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=modules)


def test_module_title_context_contains_only_title_tasks() -> None:
    context = build_report_module_titles_context(_five_module_report())
    system, user = render_report_module_titles_prompt(context)

    assert len(context.modules) == 5
    assert "严格按结构化输出返回" in system
    assert "financialScore" not in user
    assert "impactScore" not in user
    assert "provenance" not in user
    assert "当前正文" not in user


def test_module_title_context_ignores_stale_titles_on_hidden_h4() -> None:
    """appears_when 为假的 H4 不进正文与目录，其 stale 标题不得阻断模块标题生成。"""
    climate = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)["climate_change"]
    modules = []
    for definition in all_report_modules(SSE_PACKAGE):
        if definition.id == "environmental_sustainability":
            children = [climate]
        else:
            children = [Section(
                key=f"{definition.id}.section",
                title=f"{definition.navigationTitle}议题",
                headingLevel=2,
                reportSectionId="climate_change",
            )]
        modules.append(Section(
            key=definition.id,
            title=definition.navigationTitle,
            headingLevel=1,
            reportModuleId=definition.id,
            children=children,
        ))
    report = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=modules)

    # 无条件 H4（管理框架）先落新鲜标题——本测试只关注隐藏 H4 的 stale 忽略语义。
    management_framework = next(
        h4
        for h3 in climate.children or []
        for h4 in h3.children or []
        if h4.key == "climate.iro.management_framework"
    )
    management_framework.displayTitle = SectionDisplayTitle(
        text="气候变化管理机制",
        origin="generated",
        inputFingerprint=section_title_input_fingerprint(management_framework, report),
    )

    reduction_practice = next(
        h4
        for h3 in climate.children or []
        for h4 in h3.children or []
        if h4.key == "climate.iro.reduction_practice"
    )
    # intakeItems 未答 → contains_any 不满足 → 该 H4 不可见。
    assert visible(reduction_practice, report) is False
    # 人为构造过期实例标题：指纹与源块正文不一致。
    reduction_practice.displayTitle = SectionDisplayTitle(
        text="过期节能减排标题",
        origin="generated",
        inputFingerprint="f" * 64,
    )
    assert display_title_is_stale(reduction_practice, report)

    context = build_report_module_titles_context(report)

    environmental = next(
        task for task in context.modules
        if task.reportModuleId == "environmental_sustainability"
    )
    assert "过期节能减排标题" not in environmental.h4Titles
    assert "节能减排与资源效率" not in environmental.h4Titles


@pytest.mark.asyncio
async def test_module_title_generation_requires_all_five_in_registry_order(
    monkeypatch,
    tmp_path,
) -> None:
    report = _five_module_report()
    expected = [module.id for module in all_report_modules(SSE_PACKAGE)]

    class Agent:
        async def run(self, _user):
            return SimpleNamespace(output=GeneratedReportModuleTitles(modules=[
                {"reportModuleId": module_id, "displayTitle": f"标题{index}"}
                for index, module_id in enumerate(expected, start=1)
            ]))

    monkeypatch.setattr(
        "sustainability_desk.llm.generate_module_titles.build_agent",
        lambda *_args, **_kwargs: Agent(),
    )
    observation = create_observation_run(TEST_UNIT_STAGE, contract_version="cv-test",
        model_id="qwen3.7-plus",
        workload_kind="evaluation",
        block_id="report.module_titles",
        root=tmp_path,
    )

    with unit_span(observation):
        generated = await generate_report_module_titles(
            report,
            observation=observation,
            model_id="qwen3.7-plus",
        )
    assert [item.reportModuleId for item in generated.modules] == expected
