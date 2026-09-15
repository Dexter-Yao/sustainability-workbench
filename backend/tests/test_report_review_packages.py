# ABOUTME: 验证客户审阅版只说明资料文件与使用范围，内部包保留 FileMaterial 选择与 trace。
# ABOUTME: 两种投影都从同一冻结资料和 BlockMaterialDecision 构造，不暴露内部 trace 给客户。
from __future__ import annotations

from datetime import UTC, datetime
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sustainability_desk.contract.models import Block, Inline, Report, Section
from sustainability_desk.export.docx_renderer import build_document_render_plan
from sustainability_desk.material.intake.file_agent_contract import (
    AttentionItem,
    FileAgentRunReceipt,
    FileDossier,
    FileMaterial,
    FileSourceRevision,
    file_dossier_fingerprint,
)
from sustainability_desk.material.intake.models import UserFileDeclarationRevision
from sustainability_desk.material.mapping.decisions import BlockMaterialDecision
from sustainability_desk.material.mapping.snapshot import FrozenMappingPlan, MappingPlanScope
from sustainability_desk.report_review_packages import (
    BlockReviewLabel,
    InternalExportReceipt,
    InternalTraceReference,
    ReportArtifactReference,
    ReportMaterialReviewInput,
    ReportReviewSource,
    ReportRevisionReference,
    build_customer_commentary_package,
    build_internal_audit_package,
    build_material_processing_notice,
    render_customer_cover_comment,
    render_customer_comment_texts,
    render_internal_audit_markdown,
)
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.export.format_profile import load_format_profile

DELIVERY_TEXTS = load_format_profile(SSE_PACKAGE).delivery_texts


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
SHA = "a" * 64
OUTSIDE_SCOPE_NOTICE = "资料超出试用版议题范畴，正式版可覆盖此类议题。"


def _source() -> ReportReviewSource:
    report_revision_id = uuid4()
    source_revision = FileSourceRevision(source_id=uuid4(), source_sha256=SHA, declaration_revision=1)
    material = FileMaterial(
        material_id=uuid4(),
        applicable_scope_ids=("report-section:climate",),
        content_markdown="董事会每年审议气候相关风险。",
    )
    dossier = FileDossier(
        source_revision=source_revision,
        relevance="relevant",
        relevance_reason="文件包含气候治理资料。",
        materials=(material,),
        dossier_fingerprint=file_dossier_fingerprint(
            source_revision=source_revision,
            relevance="relevant",
            relevance_reason="文件包含气候治理资料。",
            materials=(material,),
            attention_items=(),
        ),
    )
    declaration = UserFileDeclarationRevision(
        revision_id=uuid4(), binding_id=uuid4(), revision=1, declared_at=NOW,
        description="公司提交的气候治理制度资料。", role="semantic_material", topic_tags=["气候变化"],
    )
    return ReportReviewSource(
        report_revision=ReportRevisionReference(
            report_id=uuid4(), revision_id=report_revision_id, revision=1,
            content_fingerprint=SHA, created_at=NOW,
        ),
        report_title="示例企业 ESG 报告",
        materials=(ReportMaterialReviewInput(source_revision=source_revision, filename="气候治理制度.docx", declaration=declaration),),
        dossiers=(dossier,),
        block_decisions=(
            BlockMaterialDecision(
                scope_id="report-section:climate", block_id="block-climate",
                disposition="supported", material_ids=(material.material_id,), reason="资料直接支持。",
            ),
        ),
        mapping_plan=FrozenMappingPlan(
            candidate_dossier_ids=(dossier.dossier_id,),
            scopes=(MappingPlanScope(scope_id="report-section:climate", dossier_ids=(dossier.dossier_id,), block_ids=("block-climate",)),),
        ),
        block_labels=(BlockReviewLabel(block_id="block-climate", label="气候风险管理"),),
        artifacts=(ReportArtifactReference(artifact_id=uuid4(), report_revision_id=report_revision_id, kind="word", filename="报告.docx", content_fingerprint=SHA, storage_ref="private/report.docx"),),
        file_agent_receipts=(FileAgentRunReceipt(
            run_id=uuid4(), observation_run_id="trace-file-agent", attempt=1, status="completed",
            source_revision=source_revision, started_at=NOW, finished_at=NOW, tool_receipts=(), trace_events=(), dossier_fingerprint=dossier.dossier_fingerprint,
        ),),
        trace_references=(InternalTraceReference(
            stage="mapping", trace_id="trace-mapping", contract="sustainability_desk.ai_observability.v2",
            input_fingerprint=SHA, output_fingerprint=SHA, storage_ref="private/mapping.jsonl",
        ),),
        outside_scope_material_notice=OUTSIDE_SCOPE_NOTICE,
    )


def _render_plan():
    return build_document_render_plan(Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="示例企业 ESG 报告",
        sections=[Section(key="climate", title="气候风险管理", headingLevel=1, blocks=[
            Block(id="block-climate", type="paragraph", blockType="generative", source="ai", content=[Inline(kind="text", text="气候风险管理安排。")])
        ])],
    ))


def test_customer_commentary_shows_file_name_without_internal_trace() -> None:
    package = build_customer_commentary_package(_source(), _render_plan())
    rendered = next(iter(render_customer_comment_texts(package, DELIVERY_TEXTS).values()))
    payload = json.dumps(package.model_dump(mode="json"), ensure_ascii=False)

    assert "气候治理制度.docx" in rendered
    assert "trace-mapping" not in rendered
    assert "private/mapping.jsonl" not in payload
    assert render_customer_cover_comment(package, DELIVERY_TEXTS).startswith("本次报告说明：")


def _source_with_uncovered_scope_material() -> ReportReviewSource:
    """在 _source 基础上追加一份只适用于本次报告未覆盖议题的相关资料：候选但未路由。"""
    source = _source()
    source_revision = FileSourceRevision(source_id=uuid4(), source_sha256="b" * 64, declaration_revision=1)
    material = FileMaterial(
        material_id=uuid4(),
        applicable_scope_ids=("report-section:water_resource_management",),
        content_markdown="公司建立了水资源管理制度。",
    )
    dossier = FileDossier(
        source_revision=source_revision,
        relevance="relevant",
        relevance_reason="文件只涉及水资源管理。",
        materials=(material,),
        dossier_fingerprint=file_dossier_fingerprint(
            source_revision=source_revision,
            relevance="relevant",
            relevance_reason="文件只涉及水资源管理。",
            materials=(material,),
            attention_items=(),
        ),
    )
    declaration = UserFileDeclarationRevision(
        revision_id=uuid4(), binding_id=uuid4(), revision=1, declared_at=NOW,
        description="公司提交的水资源管理制度资料。", role="semantic_material", topic_tags=["uncertain"],
    )
    return source.model_copy(update={
        "materials": (*source.materials, ReportMaterialReviewInput(
            source_revision=source_revision, filename="水资源管理制度.docx", declaration=declaration,
        )),
        "dossiers": (*source.dossiers, dossier),
        "mapping_plan": source.mapping_plan.model_copy(update={
            "candidate_dossier_ids": (*source.mapping_plan.candidate_dossier_ids, dossier.dossier_id),
        }),
    })


def test_customer_overview_explains_material_outside_report_scope() -> None:
    """适用范围全在本次报告之外的资料按范围说明，不再笼统说成「未采用」。"""
    source = _source_with_uncovered_scope_material()
    uncovered = source.dossiers[1].dossier_id

    assert source.outside_scope_dossier_ids() == frozenset({uncovered})
    overview = build_customer_commentary_package(source, _render_plan()).overview
    assert "已采用资料：气候治理制度.docx。" in overview
    assert f"《水资源管理制度.docx》：{OUTSIDE_SCOPE_NOTICE}" in overview
    assert "未作为企业事实采用" not in overview


def test_internal_package_preserves_material_selection_and_trace() -> None:
    source = _source()
    package = build_internal_audit_package(
        source,
        customer_commentary=build_customer_commentary_package(source, _render_plan()),
        export_receipt=InternalExportReceipt(
            render_plan_fingerprint=SHA, normal_word_fingerprint=SHA, customer_word_fingerprint=SHA,
            customer_commentary_fingerprint=SHA, comment_entry_count=1,
        ),
    )
    payload = package.model_dump(mode="json")

    assert payload["dossiers"][0]["materials"][0]["content_markdown"] == "董事会每年审议气候相关风险。"
    assert payload["block_decisions"][0]["material_ids"]
    assert "trace-mapping" in render_internal_audit_markdown(package)


def _source_with_attention() -> ReportReviewSource:
    """把冻结夹具换成带须留意事项的 dossier（指纹必须同步用相同 attention_items 重算）。"""
    source = _source()
    dossier = source.dossiers[0]
    items = (
        AttentionItem(
            code="metric_conflict",
            message="研发人员占比数据存在显著差异：表格显示 10%，正文多处描述超 18%。",
            next_action="需与企业确认 2025 年度研发人员数量及占比的准确数据口径。",
        ),
        AttentionItem(
            code="external_reference",
            message="文件引用了未随附的碳核算证书，其中的排放量数据无法从本资料获取。",
            next_action="如需在报告中引用碳核查具体数据，需另行获取上述外部文件。",
        ),
    )
    updated = dossier.model_copy(
        update={
            "attention_items": items,
            "dossier_fingerprint": file_dossier_fingerprint(
                source_revision=dossier.source_revision,
                relevance=dossier.relevance,
                relevance_reason=dossier.relevance_reason,
                materials=dossier.materials,
                attention_items=items,
            ),
        }
    )
    return source.model_copy(update={"dossiers": (updated,)})


def test_material_processing_notice_projects_attention_items_with_file_name() -> None:
    notice = build_material_processing_notice(_source_with_attention(), texts=DELIVERY_TEXTS)

    assert notice is not None
    assert notice.contract == "sustainability_desk.material_processing_notice.v3"
    assert notice.heading == "资料处理说明"
    assert notice.files_heading == "资料核对事项"
    assert len(notice.files) == 1
    file = notice.files[0]
    # 只出现客户可读的文件名，条目文本原样取自 AttentionItem。
    assert file.material_name == "气候治理制度.docx"
    assert len(file.items) == 2
    assert file.items[0].message.startswith("研发人员占比数据存在显著差异")
    assert file.items[0].next_action.startswith("需与企业确认")


def test_material_processing_notice_excludes_internal_fields() -> None:
    payload = json.dumps(
        build_material_processing_notice(_source_with_attention(), texts=DELIVERY_TEXTS).model_dump(mode="json"),
        ensure_ascii=False,
    )

    # 内部判断代码、来源 id、指纹一律不得进入客户可见说明页。
    assert "metric_conflict" not in payload
    assert "external_reference" not in payload
    assert "dossier_fingerprint" not in payload
    assert "source_id" not in payload
    assert SHA not in payload


def test_material_processing_notice_absent_without_attention_items() -> None:
    # 无须留意事项时不出页，而非渲染一张空白说明页。
    assert build_material_processing_notice(_source(), texts=DELIVERY_TEXTS) is None


def test_review_source_rejects_decision_outside_frozen_material_set() -> None:
    source = _source()
    with pytest.raises(ValidationError, match="未知 FileMaterial"):
        ReportReviewSource.model_validate({
            **source.model_dump(mode="json"),
            "block_decisions": [{
                **source.block_decisions[0].model_dump(mode="json"),
                "material_ids": [str(uuid4())],
            }],
        })


def _metric_render_plan(*, filled: bool):
    """用真实合同块 human_capital_development.metrics_narrative_body 构造渲染计划。

    该块经编译定义声明消费 social_r02（员工总数）等指标；filled 控制用户是否真的填了值。
    必须用真实 block id：批注经与生成侧同一个编译定义解析 selector，虚构块无法解析。
    """
    from sustainability_desk.contract.models import (
        ExplicitGenerationEvidenceSelector,
        GenerationInputs,
        GenerationSpec,
        GenerationTask,
        QuantitativeMetricDraft,
        QuantitativeMetricsMeta,
        ReportMeta,
    )

    block_id = "human_capital_development.metrics_narrative_body"
    metrics = (
        {"social_r02": QuantitativeMetricDraft(value="1500")}
        if filled
        else {"social_r02": QuantitativeMetricDraft()}
    )
    return block_id, build_document_render_plan(
        Report(knowledgePackageId=SSE_PACKAGE.id, 
            title="示例企业 ESG 报告",
            meta=ReportMeta(quantitativeMetrics=QuantitativeMetricsMeta(metrics=metrics)),
            sections=[
                Section(
                    key="human_capital",
                    title="人力资本发展",
                    headingLevel=1,
                    blocks=[
                        Block(
                            id=block_id,
                            type="paragraph",
                            blockType="constrained",
                            source="ai",
                            content=[Inline(kind="text", text="报告期内员工总数 1500 人。")],
                            generation=GenerationSpec(
                                task=GenerationTask(mode="metric_narrative", focus="人力资本"),
                                inputs=GenerationInputs(
                                    evidence=ExplicitGenerationEvidenceSelector(
                                        kind="explicit", quantitativeMetrics=["social_r02"]
                                    )
                                ),
                            ),
                        )
                    ],
                )
            ],
        )
    )


def _source_without_materials(block_id: str) -> ReportReviewSource:
    """去掉文件资料采用决定并对齐目标 block：正文只由指标与结构化填写支撑。"""
    source = _source()
    return source.model_copy(
        update={
            "block_decisions": tuple(
                item.model_copy(update={"material_ids": (), "block_id": block_id})
                for item in source.block_decisions
            ),
            "block_labels": tuple(
                item.model_copy(update={"block_id": block_id})
                for item in source.block_labels
            ),
            "mapping_plan": source.mapping_plan.model_copy(
                update={
                    "scopes": tuple(
                        scope.model_copy(update={"block_ids": (block_id,)})
                        for scope in source.mapping_plan.scopes
                    )
                }
            ),
        }
    )


def test_commentary_declares_quantitative_metrics_actually_used() -> None:
    """正文含用户填写的指标值时，批注必须如实说明依据，不得说「未使用企业具体资料」。"""
    block_id, plan = _metric_render_plan(filled=True)
    package = build_customer_commentary_package(_source_without_materials(block_id), plan)
    entry = package.entries[0]

    assert "未使用企业具体资料" not in entry.explanation
    assert "定量指标" in entry.explanation
    assert "quantitative_metric" in entry.basis
    # 指标以带值的结构化条目完整列出，供客户逐条校对正文数值。
    assert [(m.metric_name, m.value) for m in entry.metrics] == [("员工总数", "1500")]
    rendered = render_customer_comment_texts(package, DELIVERY_TEXTS)[entry.anchor_id]
    assert "本段引用的定量指标（用户填写值）：" in rendered
    assert "- 员工总数：1500人" in rendered


def test_commentary_ignores_metrics_without_user_value() -> None:
    """块声明消费但用户一个都没填时，不得把空指标说成依据。"""
    block_id, plan = _metric_render_plan(filled=False)
    package = build_customer_commentary_package(_source_without_materials(block_id), plan)
    entry = package.entries[0]

    assert "定量指标" not in entry.explanation
    assert "quantitative_metric" not in entry.basis
    # 未填写的指标不得出现在批注里。
    assert entry.metrics == ()


def _layout_asset_render_plan(*, layout_asset_id=None):
    """含一道已作答问题、一段正文与一个素材承载位的渲染计划。

    正文段落让所在节可渲染：整节无任何可见输出时 Word 里没有对应位置，素材批注也无处可指。
    """
    from sustainability_desk.contract.models import ImageModel, IntakeItem

    blocks = [
        Block(
            id="sm.gov_body",
            type="paragraph",
            blockType="generative",
            source="ai",
            content=[Inline(kind="text", text="公司由总经理统筹可持续发展事项。")],
        )
    ]
    if layout_asset_id is not None:
        blocks.append(
            Block(
                id="sm.layout_assets",
                type="image",
                blockType="slot",
                source="user_input",
                image=ImageModel(layoutAssetSlot=True, layoutAssetIds=[layout_asset_id]),
            )
        )
    return build_document_render_plan(
        Report(knowledgePackageId=SSE_PACKAGE.id, 
            title="示例企业 ESG 报告",
            intakeItems=[
                IntakeItem(
                    key="sustainability_governance_structure",
                    contentScopeId="sustainability_management",
                    prompt="参与管理可持续发展相关事项的机构、部门或岗位有哪些？",
                    kind="text",
                    answer="总经理统筹，下设 ESG 工作小组。",
                )
            ],
            sections=[
                Section(
                    key="sm",
                    title="可持续发展管理",
                    headingLevel=1,
                    children=[
                        Section(key="sm.gov", title="可持续发展治理", headingLevel=2, blocks=blocks)
                    ],
                )
            ],
        )
    )


def test_layout_image_comment_traces_to_uploaded_file_and_placement() -> None:
    """素材图批注列出上传文件名、用户说明与放置依据；识别 Agent 的模型文本不进入。"""
    from sustainability_desk.report_review_packages import LayoutImageReviewInput

    asset_id = uuid4()
    source = _source().model_copy(
        update={
            "layout_images": (
                LayoutImageReviewInput(
                    asset_id=asset_id,
                    block_id="sm.layout_assets",
                    material_name="ISO9001认证证书.png",
                    user_description="2025 年获颁的质量管理体系认证证书。",
                    category="certificate_or_award",
                    placement_scope_title="可持续发展管理",
                ),
            )
        }
    )
    plan = _layout_asset_render_plan(layout_asset_id=asset_id)
    package = build_customer_commentary_package(source, plan)
    entry = next(item for item in package.entries if item.anchor_id == "block:sm.layout_assets:image:0")

    assert entry.basis == ("uploaded_layout_image",)
    rendered = render_customer_comment_texts(package, DELIVERY_TEXTS)[entry.anchor_id]
    assert rendered.splitlines() == [
        "本图为用户上传的素材图片，系统按识别结果放置于本节，图片内容未作改动。",
        "- 上传文件《ISO9001认证证书.png》（用户说明：2025 年获颁的质量管理体系认证证书。）",
        "  系统识别为证书或奖项，放置于「可持续发展管理」。",
    ]
    assert "certificate_or_award" not in rendered
    assert str(asset_id) not in rendered


def _policy_render_plan():
    """覆盖批注政策各分支：前置豁免章节、模板固定段、填写表、模型正文、指标摘要图与评估矩阵图。"""
    from sustainability_desk.contract.models import (
        AssessmentResult,
        DerivedVisualizationSpec,
        GsColDef,
        GsTable,
        GsTableCell,
        GsTableRow,
        ImageModel,
        QuantitativeMetricDraft,
        QuantitativeMetricsMeta,
        ReportMeta,
        ScoredAssessmentResult,
    )

    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="示例企业 ESG 报告",
        assessment=AssessmentResult(
            reportingYear=2025,
            topics=[
                ScoredAssessmentResult(
                    determination="scored", assessmentTopicId="climate_change",
                    materiality="dual", financialScore=4.8, impactScore=4.6,
                )
            ],
        ),
        meta=ReportMeta(
            quantitativeMetrics=QuantitativeMetricsMeta(
                metrics={"social_r02": QuantitativeMetricDraft(value="1500")}
            )
        ),
        sections=[
            Section(key="about_report", title="关于本报告", headingLevel=1, blocks=[
                Block(id="about.opening", type="paragraph", blockType="fixed", source="template",
                      content=[Inline(kind="text", text="本报告为年度报告。")]),
            ]),
            Section(key="company_intro", title="关于公司", headingLevel=1, blocks=[
                Block(id="company_intro.body", type="paragraph", blockType="constrained", source="ai",
                      content=[Inline(kind="text", text="公司成立于 1997 年。")]),
            ]),
            Section(key="sm", title="可持续发展管理", headingLevel=1, blocks=[
                Block(id="sm.stakeholder_intro", type="paragraph", blockType="fixed", source="template",
                      content=[Inline(kind="text", text="利益相关方沟通有助于识别关注重点。")]),
                Block(id="sm.stakeholder_table", type="table", blockType="slot", source="user_input",
                      table=GsTable(caption="利益相关方沟通情况",
                                    colDefs=[GsColDef(key="party", header="利益相关方", cellType="text")],
                                    children=[GsTableRow(children=[GsTableCell(colKey="party", value="员工")])])),
                Block(id="sm.matrix_image", type="image", blockType="slot", source="assessment",
                      image=ImageModel(caption="双重重要性议题矩阵", placeholder="矩阵图")),
                Block(id="sm.body", type="paragraph", blockType="generative", source="ai",
                      content=[Inline(kind="text", text="公司建立可持续发展治理架构。")]),
                Block(id="hc.metrics_summary", type="image", blockType="fixed", source="derived",
                      image=ImageModel(derivedVisualization=DerivedVisualizationSpec(
                          kind="quantitative_metric_summary", metricKeys=["social_r02"]))),
            ]),
        ],
    )
    return build_document_render_plan(report)


def test_commentary_skips_deterministic_units_and_front_matter_sections() -> None:
    """批注只出现在系统做过判断的单元：模板固定文本、填写表不批注；「关于本报告」「关于公司」正文整体不批注。"""
    from sustainability_desk.report_review_packages import COMMENTARY_EXEMPT_SECTION_KEYS

    assert COMMENTARY_EXEMPT_SECTION_KEYS == frozenset({"about_report", "company_intro"})
    plan = _policy_render_plan()
    package = build_customer_commentary_package(_source_without_materials("sm.body"), plan)
    anchors = {entry.anchor_id for entry in package.entries}

    assert "block:about.opening:paragraph:0" in plan.unit_anchor_ids
    assert "block:company_intro.body:paragraph:0" in plan.unit_anchor_ids
    assert "block:sm.stakeholder_intro:paragraph:0" in plan.unit_anchor_ids
    assert "block:sm.stakeholder_table:table:0" in plan.unit_anchor_ids
    assert anchors == {
        "block:sm.body:paragraph:0",
        "block:sm.matrix_image:image:0",
        "block:hc.metrics_summary:image:0",
    }
    rendered = render_customer_comment_texts(package, DELIVERY_TEXTS)
    assert rendered["block:sm.body:paragraph:0"].startswith("本段未引用用户上传的资料")
    assert "确定性投影" not in json.dumps(package.model_dump(mode="json"), ensure_ascii=False)


def test_figure_comments_state_concrete_drawing_basis() -> None:
    """每幅实际渲染的图都交代出处：指标摘要图列出所用指标与填写值，评估矩阵图说明依据评估结果绘制。"""
    plan = _policy_render_plan()
    package = build_customer_commentary_package(_source_without_materials("sm.body"), plan)
    rendered = render_customer_comment_texts(package, DELIVERY_TEXTS)

    assert rendered["block:hc.metrics_summary:image:0"].splitlines() == [
        "本图由系统根据用户填写的以下定量指标绘制，数值与填写值一致：",
        "- 员工总数：1500人",
    ]
    assert rendered["block:sm.matrix_image:image:0"] == (
        "本图由系统根据用户完成的议题重要性评估结果绘制，各议题的位置对应其财务重要性与影响重要性评估得分。"
    )


def test_customer_overview_explains_why_materials_were_not_adopted() -> None:
    """未采用的资料按稳定处置 code 分组给出客户可读原因；模型文本不进入封面说明。"""
    MATERIAL_NOT_ADOPTED_EXPLANATIONS = DELIVERY_TEXTS.overview.not_adopted

    source = _source_with_attention()
    # 去掉采用决定：唯一一份资料有须留意事项且未被任何块采用。
    unused = source.model_copy(update={
        "block_decisions": tuple(
            item.model_copy(update={"disposition": "needs_attention", "material_ids": ()})
            for item in source.block_decisions
        ),
    })
    overview = build_customer_commentary_package(unused, _render_plan()).overview
    assert overview.startswith("本版本已读取用户提供的资料，但未作为企业事实采用")
    assert f"《气候治理制度.docx》：{MATERIAL_NOT_ADOPTED_EXPLANATIONS['attention_items']}。" in overview
    assert "relevance_reason" not in overview and "资料直接支持" not in overview

    plain = _source().model_copy(update={
        "block_decisions": tuple(
            item.model_copy(update={"disposition": "context_only", "material_ids": ()})
            for item in _source().block_decisions
        ),
    })
    overview = build_customer_commentary_package(plain, _render_plan()).overview
    assert f"《气候治理制度.docx》：{MATERIAL_NOT_ADOPTED_EXPLANATIONS['no_supporting_content']}。" in overview


def test_trace_reference_expresses_unavailability_without_faking_a_path() -> None:
    """轨迹不可用是显式领域事实，不能用空串或假路径冒充可用。

    轨迹是审计旁路证据：正文已生成、交付物已产出时，一条引用取不到不应让用户拿不到
    报告（否则全部块生成成功、Word 已落盘，整次生成仍会被判 failed）。
    但缺失必须可见——因此 storage_ref 与 unavailable_reason 恰好二选一。
    """

    available = InternalTraceReference(
        stage="mapping",
        trace_id="run-1",
        contract="sustainability_desk.ai_observability.v3",
        input_fingerprint="a" * 64,
        output_fingerprint="b" * 64,
        storage_ref="/traces/run-1.jsonl",
    )
    assert available.unavailable_reason is None

    degraded = InternalTraceReference(
        stage="mapping",
        trace_id="run-2",
        contract="sustainability_desk.ai_observability.v3",
        input_fingerprint="a" * 64,
        output_fingerprint="b" * 64,
        unavailable_reason="轨迹在打包时不可读取",
    )
    assert degraded.storage_ref is None

    # 两者都给或都不给都是自相矛盾的引用，必须拒绝。
    for kwargs in (
        {},
        {"storage_ref": "/traces/x.jsonl", "unavailable_reason": "也不可用"},
    ):
        with pytest.raises(ValidationError):
            InternalTraceReference(
                stage="mapping",
                trace_id="run-3",
                contract="sustainability_desk.ai_observability.v3",
                input_fingerprint="a" * 64,
                output_fingerprint="b" * 64,
                **kwargs,
            )
