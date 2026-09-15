# ABOUTME: 层级树地基测试——递归渲染各级标题、祖先 reportSectionId 注入 ModelContext、headingLevel 校验。
# ABOUTME: 议题章节产生与否由规划层 planner 构建期决定（见 test_planner）；此处测渲染与注入正确性。
import pytest
from docx import Document

from sustainability_desk.contract.loader import load_contract
from sustainability_desk.contract.models import (
    AssessmentResult,
    Block,
    ExplicitGenerationEvidenceSelector,
    GenerationInputs,
    GenerationSpec,
    GenerationTask,
    Inline,
    IROItem,
    Report,
    Section,
    ScoredAssessmentResult,
)
from sustainability_desk.export.docx_renderer import render_docx
from sustainability_desk.llm.prompts import (
    SectionPlacement,
    build_model_context,
    render_prompt,
    resolve_section_placement,
)
from knowledge_package_fixtures import SSE_PACKAGE


def _para(bid: str, text: str) -> Block:
    return Block(
        id=bid, type="paragraph", blockType="generative", source="ai",
        content=[Inline(kind="text", text=text)],
    )


def _generated_para(bid: str) -> Block:
    return Block(
        id=bid,
        type="paragraph",
        blockType="generative",
        source="ai",
        generation=GenerationSpec(
            task=GenerationTask(focus="说明当前内容单元的管理实践。"),
            inputs=GenerationInputs(
                evidence=ExplicitGenerationEvidenceSelector(kind="explicit")
            ),
        ),
    )


def _tree_report() -> Report:
    """环境模块(H1) → 应对气候变化(H2, reportSectionId) → 治理(H3) 的最小树。"""
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[
            Section(key="env", title="环境章", headingLevel=1, children=[
                Section(
                    key="climate", title="应对气候变化", headingLevel=2,
                    reportSectionId="climate_change",
                    children=[
                        Section(key="gov", title="治理", headingLevel=3,
                                blocks=[_para("climate.gov.body", "治理正文")]),
                    ],
                ),
            ]),
        ],
    )


def _assessment(materiality: str) -> AssessmentResult:
    return AssessmentResult(
        reportingYear=2025,
        topics=[ScoredAssessmentResult(determination="scored",
            assessmentTopicId="climate_change",
materiality=materiality,
            financialScore=4.0, impactScore=4.5,
            iroItems=[IROItem(kind="risk", description="台风导致停产")],
        )],
    )


def test_ancestor_topic_injected_for_grandchild_block():
    """reportSectionId 在 H2、生成块在 H3：ModelContext 须注入成员议题结论。"""
    template = _tree_report()
    instance = _tree_report()
    instance.assessment = _assessment("dual")
    block = template.find_block("climate.gov.body")
    ctx = build_model_context(block, template, instance)
    assert ctx.assessment, "祖先 reportSectionId 未解析 → 成员议题结论未注入 H3 生成块"
    assert ctx.assessment[0].name == "应对气候变化"
    assert any("台风" in i.description for i in ctx.assessment[0].iro)
    system, _user = render_prompt(ctx, n=1)
    assert "<iro_context>" in system
    assert "台风导致停产" in system
    assert "财务重要性（Financial Materiality）" not in system


def test_section_placement_projects_h2_h3_and_h4_stable_titles() -> None:
    """章节定位只读取稳定 Section 树，不读取动态 H1 或实例 displayTitle。"""

    block = _generated_para("climate.iro.actions")
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[
            Section(
                key="module",
                title="环境可持续",
                headingLevel=1,
                children=[
                    Section(
                        key="climate",
                        title="应对气候变化",
                        headingLevel=2,
                        reportSectionId="climate_change",
                        children=[
                            Section(
                                key="iro",
                                title="影响、风险与机遇管理",
                                headingLevel=3,
                                children=[
                                    Section(
                                        key="actions",
                                        title="气候行动",
                                        headingLevel=4,
                                        blocks=[block],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )

    assert resolve_section_placement(report, block.id) == SectionPlacement(
        reportSectionTitle="应对气候变化",
        pillarTitle="影响、风险与机遇管理",
        contentUnitTitle="气候行动",
    )


def test_section_placement_supports_h2_direct_and_h3_paragraphs() -> None:
    h2_block = _generated_para("topic.summary")
    h3_block = _generated_para("topic.governance")
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[
            Section(
                key="module",
                title="环境可持续",
                headingLevel=1,
                children=[
                    Section(
                        key="topic",
                        title="议题名称",
                        headingLevel=2,
                        reportSectionId="topic",
                        blocks=[h2_block],
                        children=[
                            Section(
                                key="governance",
                                title="治理",
                                headingLevel=3,
                                blocks=[h3_block],
                            )
                        ],
                    )
                ],
            )
        ],
    )

    assert resolve_section_placement(report, h2_block.id) == SectionPlacement(
        reportSectionTitle="议题名称"
    )
    assert resolve_section_placement(report, h3_block.id) == SectionPlacement(
        reportSectionTitle="议题名称",
        pillarTitle="治理",
    )


def test_section_placement_omits_h1_only_blocks_and_rejects_unknown_blocks() -> None:
    h1_block = _generated_para("company.body")
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[
            Section(
                key="company",
                title="关于公司",
                headingLevel=1,
                blocks=[h1_block],
            )
        ],
    )

    assert resolve_section_placement(report, h1_block.id) is None
    with pytest.raises(ValueError, match="无法定位生成块"):
        resolve_section_placement(report, "missing.block")


def test_subtree_renders_all_levels(base_template, out_dir):
    """递归树 H1/H2/H3 标题与 H3 正文全部渲染，且各按对应 Heading 样式。"""
    report = _tree_report()
    out = render_docx(report, base_template, out_dir / "tree_visible.docx")
    paras = Document(str(out)).paragraphs
    styles = {p.text: p.style.name for p in paras if p.text}
    assert styles.get("第一章 环境章") == "Heading 1"
    assert styles.get("一、应对气候变化") == "Heading 2"
    assert styles.get("（一）治理") == "Heading 3"
    assert "治理正文" in [p.text for p in paras]


def test_loader_rejects_skipped_heading_level(tmp_path):
    """子节 headingLevel 跳级（H1→H3）应在加载时报错。"""
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "title: t\nfields: {}\nsections:\n"
        "  - key: a\n    title: A\n    headingLevel: 1\n    children:\n"
        "      - key: b\n        title: B\n        headingLevel: 3\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="headingLevel"):
        load_contract(bad)


def test_loader_rejects_top_level_non_h1(tmp_path):
    """顶层 section 必须 headingLevel=1。"""
    bad = tmp_path / "bad2.yaml"
    bad.write_text(
        "title: t\nfields: {}\nsections:\n  - key: a\n    title: A\n    headingLevel: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="headingLevel"):
        load_contract(bad)
