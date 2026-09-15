# ABOUTME: 服务端统一诊断 diagnose(report)→Diagnostics 单测——可导出性规则（必填/表行 gate/【key】残留）。
# ABOUTME: 导出闸与前端预检同源消费此诊断；规则确定性、无 LLM；议题级诊断留杠杆4。
from sustainability_desk.contract.models import (
    Block,
    AppendixPackage,
    Condition,
    ConditionRule,
    DisclosureProfile,
    ExternalAssuranceReport,
    Field,
    GenerationSpec,
    GsColDef,
    GsTable,
    Inline,
    ReaderFeedbackContactInformation,
    Report,
    RowOrigin,
    Section,
)
from sustainability_desk.contract.table_ops import data_row
from sustainability_desk.diagnostics import diagnose
from knowledge_package_fixtures import SSE_PACKAGE


def _report(*blocks: Block, fields: dict | None = None) -> Report:
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        fields=fields or {},
        disclosureProfile=DisclosureProfile(),
        appendixPackage=AppendixPackage(
            readerFeedbackContactInformation=ReaderFeedbackContactInformation(
                address="addr", email="esg@example.com", phone="0577"
            )
        ),
        sections=[Section(key="s", title="S", headingLevel=1, blocks=list(blocks))],
    )


def test_diagnose_flags_missing_authored_required_field():
    """authoring contract 必填字段为空 → block 级 issue，整体 blocking。"""
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        fields={
            "company_registered_name": Field(
                key="company_registered_name",
                label="公司注册名",
                type="string",
                source="user_input",
                required=True,
                value="",
            )
        },
        disclosureProfile=DisclosureProfile(),
        appendixPackage=AppendixPackage(
            readerFeedbackContactInformation=ReaderFeedbackContactInformation(
                address="addr", email="esg@example.com", phone="0577"
            )
        ),
        sections=[],
    )
    diag = diagnose(report)
    assert diag.blocking
    assert any(
        i.level == "block" and i.fieldKey == "company_registered_name"
        for i in diag.issues
    )


def test_diagnose_includes_table_row_gate():
    """表行 gate 接入 diagnose（接上 table_export_issues，消解 H1）：必填列空 → block。"""
    cols = [
        GsColDef(key="name", header="名称", required=True),
        GsColDef(key="resp", header="应对", cellType="ai_text"),
    ]
    blk = Block(id="t.risk", type="table", blockType="generative", source="ai",
                table=GsTable(colDefs=cols, children=[
                    data_row(cols, {"name": "", "resp": ""}, state="ready"),
                ]))
    diag = diagnose(_report(blk))
    assert diag.blocking
    assert any(i.blockId == "t.risk" and i.rowId == "0" and i.code == "required_empty" for i in diag.issues)


def test_diagnose_risk_matrix_flags_fixed_row_and_ai_text_issues_with_readable_message():
    """风险矩阵表缺固定行、AI 文本空均阻断，并给出用户可读表名/行名/列名。"""
    cols = [
        GsColDef(key="risk_type", header="风险类型", required=True),
        GsColDef(key="response", header="应对措施", cellType="ai_text"),
    ]
    blk = Block(
        id="t.risk_matrix",
        type="table",
        blockType="generative",
        source="ai",
        generation=GenerationSpec(
            task={"focus": "x"},
            fixedRowSeeds=[
                {"theme": "合规与监管风险", "category": "风险"},
                {"theme": "人员廉洁意识风险", "category": "风险"},
            ],
        ),
        table=GsTable(
            caption="反商业贿赂与反贪污风险内容、影响及应对措施",
            layoutProfile="risk_response_matrix",
            colDefs=cols,
            children=[
                data_row(
                    cols,
                    {"risk_type": "合规与监管风险", "response": ""},
                    state="ready",
                    origin=RowOrigin(theme="合规与监管风险", category="风险"),
                )
            ],
        ),
    )

    diag = diagnose(_report(blk))

    messages = [issue.message for issue in diag.issues]
    assert diag.blocking
    assert any("缺少「人员廉洁意识风险」行" in message for message in messages)
    assert any("反商业贿赂与反贪污风险内容、影响及应对措施" in message and "应对措施为空" in message for message in messages)


def test_diagnose_does_not_require_separate_acceptance_for_ready_content():
    """生成内容进入 ready 后就是当前版本，不再产生独立采纳或待确认诊断。"""
    blk = Block(id="b.gen", type="paragraph", blockType="generative", source="ai", state="ready",
                content=[Inline(kind="text", text="草稿正文")],
                generation=GenerationSpec(task={"focus": "x"}))
    diag = diagnose(_report(blk))
    assert not any(i.code in {"unreviewed", "row_unreviewed"} for i in diag.issues)


def test_diagnose_flags_ref_residue():
    """正文 ref 指向空字段 → 导出该处缺失 → block；消息用字段标签，不泄漏内部引用键。"""
    blk = Block(id="b.ref", type="paragraph", blockType="fixed", source="template",
                content=[Inline(kind="text", text="报告期为"), Inline(kind="ref", ref="year")])
    report = _report(blk, fields={"year": Field(key="year", label="年度", type="year", source="user_input", value="")})
    diag = diagnose(report)
    residue = [i for i in diag.issues if i.code == "key_residue"]
    assert residue and residue[0].level == "block" and residue[0].blockId == "b.ref"
    assert "「年度」" in residue[0].message
    assert "year" not in residue[0].message


def test_diagnose_ref_with_fallback_is_not_residue():
    """带回退文案的引用由渲染器用 fallback 渲染，不是导出缺失，不得阻断。"""
    blk = Block(id="b.fallback", type="paragraph", blockType="fixed", source="template",
                content=[Inline(kind="ref", ref="company_short_name", fallback="本公司")])
    report = _report(blk, fields={
        "company_short_name": Field(key="company_short_name", label="公司简称", type="string", source="user_input", value="")
    })
    diag = diagnose(report)
    assert not any(i.code == "key_residue" for i in diag.issues)


def test_diagnose_messages_do_not_leak_internal_state_paths():
    """诊断消息面向用户；内部状态路径只允许出现在 path/fieldKey 定位字段。"""
    blk = Block(
        id="b.appendix_ref",
        type="paragraph",
        blockType="fixed",
        source="template",
        content=[Inline(kind="ref", ref="appendixPackage.externalAssuranceReport.fileLabel")],
    )
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        disclosureProfile=DisclosureProfile(),
        appendixPackage=AppendixPackage(
            externalAssuranceReport=ExternalAssuranceReport(isIncluded=True, fileLabel=None),
        ),
        sections=[Section(key="s", title="S", headingLevel=1, blocks=[blk])],
    )
    diag = diagnose(report)
    assert diag.blocking
    for issue in diag.issues:
        assert "appendixPackage." not in issue.message
        assert "disclosureProfile." not in issue.message


def test_diagnose_deduplicates_residue_against_existing_blockers():
    """同一缺失事实（外部鉴证附件说明）只报一条：required_assurance_report 存在时不再叠加 key_residue。"""
    blk = Block(
        id="b.assurance_ref",
        type="paragraph",
        blockType="fixed",
        source="template",
        appears_when=Condition(
            all=[
                ConditionRule(
                    path="appendixPackage.externalAssuranceReport.fileLabel",
                    op="exists",
                )
            ]
        ),
        content=[Inline(kind="ref", ref="appendixPackage.externalAssuranceReport.fileLabel")],
    )
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        disclosureProfile=DisclosureProfile(),
        appendixPackage=AppendixPackage(
            externalAssuranceReport=ExternalAssuranceReport(isIncluded=True, fileLabel=None),
            readerFeedbackContactInformation=ReaderFeedbackContactInformation(
                address="addr", email="esg@example.com", phone="0577"
            ),
        ),
        sections=[Section(key="s", title="S", headingLevel=1, blocks=[blk])],
    )
    diag = diagnose(report)
    fileLabel_issues = [
        i
        for i in diag.issues
        if i.path == "appendixPackage.externalAssuranceReport.fileLabel" or i.code == "key_residue"
    ]
    assert [i.code for i in fileLabel_issues] == ["required_assurance_report"]


def test_diagnose_blocks_internal_report_text():
    """正式正文不得包含内部说明、代理提示或实现进度文案。"""
    blk = Block(
        id="about.basis_note",
        type="paragraph",
        blockType="slot",
        source="template",
        styleRole="source_note",
        content=[Inline(kind="text", text="编制依据按所选准则合成；监管强制表述，AI 不得改写。")],
    )
    diag = diagnose(_report(blk))
    assert diag.blocking
    assert any(i.code == "internal_report_text" and i.blockId == "about.basis_note" for i in diag.issues)



def test_diagnose_clean_report_still_blocked_by_upstream_readiness():
    """正文自身无问题，但轻量版上游准备未完成时仍由 readiness 阻断。

    此处的阻断来自评分与准则（正文对二者有无条件引用），不再来自基本配置字段。
    """
    blk = Block(id="b.ok", type="paragraph", blockType="generative", source="ai", state="ready",
                content=[Inline(kind="text", text="完整正文")], generation=GenerationSpec(task={"focus": "x"}))
    diag = diagnose(_report(blk))
    assert diag.blocking
    assert diag.readiness is not None
    # 基本配置字段缺失只作提示，不再阻断交付。
    assert all(
        issue.level == "warn"
        for issue in diag.issues
        if issue.code == "required_report_configuration"
        and issue.fieldKey not in _EXPORT_GATED_FIELDS
    )


_EXPORT_GATED_FIELDS = {
    "company_registered_name",
    "reporting_year",
    "report_period_start",
    "report_period_end",
}


def _basic_info_fields() -> dict[str, Field]:
    def field(key: str, label: str, field_type: str, value) -> Field:
        return Field(
            key=key, label=label, type=field_type,
            source="user_input", required=True, value=value,
        )

    return {
        "company_registered_name": field(
            "company_registered_name", "公司注册名", "string", "汉美科技股份有限公司"
        ),
        "reporting_year": field("reporting_year", "报告年份", "year", 2025),
        "report_period_start": field(
            "report_period_start", "报告期起始", "date", "2025-01-01"
        ),
        "report_period_end": field(
            "report_period_end", "报告期截止", "date", "2025-12-31"
        ),
    }


def test_lightweight_report_with_basic_info_only_can_export():
    """轻量版定位：能生成就必须能导出。

    只填四项基本信息、不填重要性评分、不填定量信息、不传资料，正文本身无问题时
    导出闸不得阻断——否则用户跑完一次昂贵生成却拿不到 Word。
    """
    blk = Block(id="b.ok", type="paragraph", blockType="generative", source="ai", state="ready",
                content=[Inline(kind="text", text="完整正文")], generation=GenerationSpec(task={"focus": "x"}))
    diag = diagnose(
        _report(blk, fields=_basic_info_fields()),
        include_assessment=False,
    )
    assert not diag.blocking
    assert [issue for issue in diag.issues if issue.level == "warn"]


def test_unfilled_configuration_fields_stay_visible_as_warnings():
    """放行不等于沉默：未填字段仍以 warn 呈现，前端引导照常提示。"""
    blk = Block(id="b.ok", type="paragraph", blockType="generative", source="ai", state="ready",
                content=[Inline(kind="text", text="完整正文")], generation=GenerationSpec(task={"focus": "x"}))
    diag = diagnose(
        _report(blk, fields=_basic_info_fields()),
        include_assessment=False,
    )
    warned = {
        issue.fieldKey
        for issue in diag.issues
        if issue.code == "required_report_configuration" and issue.level == "warn"
    }
    # 发布与审批类字段已改为纯可选，不再进引导清单；仍须填的配置字段以 warn 呈现。
    assert "company_short_name" in warned
    assert "has_technology_ethics_sensitive_activity" in warned


def test_export_gated_field_still_blocks_when_missing():
    """正文无条件引用的字段缺失仍必须阻断，否则渲染层会 fail-loud 且拿不到任何交付物。"""
    blk = Block(id="b.ok", type="paragraph", blockType="generative", source="ai", state="ready",
                content=[Inline(kind="text", text="完整正文")], generation=GenerationSpec(task={"focus": "x"}))
    fields = _basic_info_fields()
    del fields["reporting_year"]
    diag = diagnose(
        _report(blk, fields=fields),
        include_assessment=False,
    )
    assert diag.blocking
    assert any(
        issue.level == "block" and issue.fieldKey == "reporting_year"
        for issue in diag.issues
    )


def test_diagnose_flags_unresolved_standard_disclosure_requirement():
    """准则披露要求引用无法解析 → 阻断，避免准则映射静默漂移。"""
    blk = Block(
        id="climate.bad_requirement",
        type="paragraph",
        blockType="generative",
        source="ai",
        state="ready",
        content=[Inline(kind="text", text="完整正文")],
        generation=GenerationSpec(
            task={"focus": "x"},
            standardDisclosureRequirementKeys=["climate.gov.does_not_exist"],
        ),
    )
    report = _report(blk)
    report.sections = [
        Section(
            key="climate_change",
            title="应对气候变化",
            headingLevel=2,
            reportSectionId="climate_change",
            blocks=[blk],
        )
    ]
    diag = diagnose(report)
    assert diag.blocking
    assert any(
        i.code == "unresolved_standard_disclosure_requirement"
        and i.blockId == "climate.bad_requirement"
        for i in diag.issues
    )


def test_diagnose_warns_when_visible_clause_annotation_source_missing(monkeypatch):
    """用户可见准则批注事实源缺失 → warning；不与准则披露要求映射资产混用。"""
    monkeypatch.setattr(
        "sustainability_desk.diagnostics.find_user_visible_disclosure_clause_annotation_entry",
        lambda *_, **__: None,
    )
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        disclosureProfile=DisclosureProfile(),
        appendixPackage=AppendixPackage(
            readerFeedbackContactInformation=ReaderFeedbackContactInformation(
                address="addr", email="esg@example.com", phone="0577"
            )
        ),
        sections=[
            Section(
                key="climate_change",
                title="应对气候变化",
                headingLevel=2,
                reportSectionId="climate_change",
            )
        ],
    )
    diag = diagnose(report)
    assert any(i.code == "missing_user_visible_clause_annotation_source" and i.level == "warn" for i in diag.issues)


def test_reader_feedback_missing_never_blocks_export():
    """读者反馈联系为纯选填：无论附录块是否在场，缺失都不得阻断导出。"""
    for block in (
        Block(id="p.x", type="paragraph", blockType="fixed", source="template", content=[]),
        Block(
            id="appendix.reader_feedback.email",
            type="paragraph",
            blockType="slot",
            source="user_input",
            content=[],
        ),
    ):
        report = Report(knowledgePackageId=SSE_PACKAGE.id, 
            title="t",
            disclosureProfile=DisclosureProfile(),
            appendixPackage=AppendixPackage(),
            sections=[Section(key="s", title="S", headingLevel=1, blocks=[block])],
        )
        blocking = [i for i in diagnose(report).issues if i.level == "block"]
        assert not any("读者反馈" in i.message for i in blocking), blocking


def test_diagnose_warns_assurance_without_material():
    """外部鉴证为纯选填：开关开启但未补齐降为 warn 引导，不阻断导出。"""
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        disclosureProfile=DisclosureProfile(),
        appendixPackage=AppendixPackage(
            externalAssuranceReport=ExternalAssuranceReport(isIncluded=True, fileLabel=None),
            readerFeedbackContactInformation=ReaderFeedbackContactInformation(
                address="addr", email="esg@example.com", phone="0577"
            ),
        ),
        sections=[],
    )
    diag = diagnose(report)
    issues = [i for i in diag.issues if i.code == "required_assurance_report"]
    assert len(issues) == 1
    assert issues[0].level == "warn"
    assert issues[0].path == "appendixPackage.externalAssuranceReport.fileLabel"
    assert "鉴证机构" in issues[0].message and "附件说明" in issues[0].message
