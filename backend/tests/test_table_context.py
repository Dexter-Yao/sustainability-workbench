# ABOUTME: 表格 ModelContext 装配单测——受控 row_seed → row_context、by_table 路径口径、行 prompt 无泄漏。
from sustainability_desk.contract.models import (
    Block,
    GenerationSpec,
    GsColDef,
    GsTable,
    IntakeItem,
    Report,
    Section,
)
from sustainability_desk.llm.prompts import build_model_context
from sustainability_desk.llm.table_schema import RowSeed
from knowledge_package_fixtures import SSE_PACKAGE
from knowledge_package_fixtures import sse_model_context


def test_row_seed_whitelist_only():
    """build_model_context 接 row_seed → row_context 仅含白名单非空字段（category 为 None 被剔除）。"""
    tmpl = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[
        Block(id="t.x", type="table", blockType="generative", source="ai",
              generation={"task": {"focus": "by_table_missing"}},
              table=GsTable(colDefs=[GsColDef(key="name", header="名")])),
    ])])
    seed = RowSeed(theme="极端高温", driver_hint="气温上升")
    ctx = build_model_context(tmpl.find_block("t.x"), tmpl, tmpl, row_seed=seed)
    assert ctx.row_context == {"theme": "极端高温", "driver_hint": "气温上升"}


def test_row_seed_none_keeps_row_context_empty():
    """不传 row_seed 时 row_context 为空——段落生成路径不受影响。"""
    tmpl = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[
        Block(id="p", type="paragraph", blockType="generative", source="ai", content=[]),
    ])])
    ctx = build_model_context(tmpl.find_block("p"), tmpl, tmpl)
    assert ctx.row_context == {}


def test_row_seed_category_included():
    """category 非空时进入 row_context（白名单正向覆盖）。"""
    tmpl = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[
        Block(id="t.x", type="table", blockType="generative", source="ai",
              generation={"task": {"focus": "by_table_missing"}},
              table=GsTable(colDefs=[GsColDef(key="name", header="名")])),
    ])])
    seed = RowSeed(theme="极端高温", category="慢性物理风险")
    ctx = build_model_context(tmpl.find_block("t.x"), tmpl, tmpl, row_seed=seed)
    assert ctx.row_context == {"theme": "极端高温", "category": "慢性物理风险"}


def test_table_block_uses_explicit_task_no_fact_guidance():
    """表块无资料时使用显式 noFactGuidance，不从表题注推断任务。"""
    blk = Block(id="t.phys", type="table", blockType="generative", source="ai",
                generation=GenerationSpec(
                    task={"focus": "识别物理风险。", "noFactGuidance": "据行业与 TCFD 参考识别典型物理风险。"},
                ),
                table=GsTable(caption="物理风险识别", colDefs=[GsColDef(key="name", header="名")]))
    tmpl = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[blk])])

    ctx_none = build_model_context(blk, tmpl, tmpl)  # 无资料 → 行业路径
    assert "TCFD" in ctx_none.section_task
    assert not ctx_none.evidence.intake_facts


def test_table_block_with_intake_uses_focus_and_filled_content():
    """表块有填报内容时只使用 focus，并注入同源 Evidence。"""
    blk = Block(id="t.phys", type="table", blockType="generative", source="ai",
                generation=GenerationSpec(
                    task={"focus": "依据填报内容梳理本公司物理风险。", "noFactGuidance": "使用行业参考。"},
                    inputs={"evidence": {"kind": "explicit", "intakeItems": ["doc1"]}},
                ),
                table=GsTable(caption="物理风险识别", colDefs=[GsColDef(key="name", header="名")]))
    inst = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        intakeItems=[IntakeItem(key="doc1", contentScopeId="climate_change", prompt="物理风险资料", kind="text", answer="厂区高温影响生产")],
        sections=[Section(key="s", title="S", headingLevel=1, blocks=[blk])],
    )
    ctx = build_model_context(blk, inst, inst)
    assert ctx.evidence.intake_facts and "依据填报内容" in ctx.section_task


def test_render_propose_and_complete_prompt():
    """定行 prompt 含表主题/行数/报告主体行业；补全 prompt 含列 header+genHint+行 seed，且不泄漏列 key。"""
    from sustainability_desk.contract.models import GsColDef
    from sustainability_desk.llm.prompts import render_complete_prompt, render_propose_prompt

    cols = [
        GsColDef(key="name", header="风险名称", cellType="text"),
        GsColDef(key="response", header="应对措施", cellType="ai_text", genHint="覆盖缓解/转移/承受/控制"),
        GsColDef(key="value_chain", header="价值链", cellType="multi_select", options=["上游价值链", "公司运营"]),
    ]
    ctx = sse_model_context(section_task="物理风险识别", report_subject=("所属行业：电气制造",))

    sys_p, usr_p = render_propose_prompt(ctx, cols, count_min=3, count_max=6)
    assert "物理风险识别" in sys_p and ("3" in sys_p and "6" in sys_p)
    assert "电气制造" in sys_p  # 报告主体（行业）进系统提示

    ctx2 = ctx.model_copy(update={"row_context": {"theme": "极端高温", "driver_hint": "气温上升"}})
    sys_c, usr_c = render_complete_prompt(ctx2, cols)
    assert "应对措施" in sys_c and "覆盖缓解/转移/承受/控制" in sys_c  # 列 header + genHint 进指令
    assert "极端高温" in usr_c  # 行 seed 进用户提示
    assert "value_chain" not in sys_c and "value_chain" not in usr_c  # 列 key 不泄漏（只露 header）


def test_catalog_table_fill_prompt_uses_reference_materials_without_row_repetition():
    """目录表整表填充 prompt 接收参考资料，但要求全表距离感和行间去重。"""
    from sustainability_desk.contract.models import GsColDef
    from sustainability_desk.llm.prompts import (
        GenerationEvidence,
        Material,
        render_catalog_table_fill_prompt,
    )

    cols = [
        GsColDef(key="risk_type", header="风险类型", cellType="text"),
        GsColDef(key="risk_name", header="风险名称", cellType="text"),
        GsColDef(
            key="impact",
            header="潜在影响",
            cellType="ai_text",
            genHint="统一使用“公司”作为主体，体现行业和业务类型相关性",
        ),
        GsColDef(
            key="response",
            header="应对及管理措施",
            cellType="ai_text",
            genHint="用中文分号分隔，不写项目符号",
        ),
    ]
    ctx = sse_model_context(
        section_task="气候相关物理风险识别",
        report_subject=("所属行业：电气制造", "主营业务概述：精密连接器，客户为车企一级供应商"),
        evidence=GenerationEvidence(
          intake_facts=(
            Material(
                label="战略方向",
                text="公司围绕清洁能源替代、能效提升与低碳产品三条路径推进低碳转型，已在主厂区部署屋顶分布式光伏。",
            ),
            Material(
                label="气候相关机遇",
                text="已选择：开发低碳产品、服务或解决方案；补充说明：低碳连接器契合新能源汽车客户的绿色采购需求。",
            ),
          ),
        ),
    )

    system, user = render_catalog_table_fill_prompt(
        ctx,
        catalog_rows=[
            {"risk_type": "慢性物理风险", "risk_name": "平均气温上升", "referenceImpact": "高温增加生产与用能管理压力"},
            {"risk_type": "慢性物理风险", "risk_name": "水短缺", "referenceImpact": "水资源约束影响生产运营"},
        ],
        columns=cols,
        kind_label="风险",
    )

    assert "行业和业务类型相关性" in system
    assert "用户填写内容只作为全表参考资料" in system
    assert "不得把同一段用户资料机械分摊到每一行" in system
    assert "低承诺动词不能豁免具体工具或成熟机制" in system
    assert "绿色信贷" in system
    assert "能源管理系统" in system
    assert "产品碳足迹" in system
    assert "同一表内各行应各司其职" in system
    assert "平均气温上升" in system and "水短缺" in system
    assert "risk_name" not in system
    assert "贴合本公司真实经营场景" not in system
    assert "主营业务" in system
    assert "车企一级供应商" in system
    assert "开发低碳产品、服务或解决方案" in user
    assert "战略方向" in user
    assert "主厂区部署屋顶分布式光伏" in user
    assert "新能源汽车客户" in user


def test_catalog_table_fill_prompt_renders_row_support_context_as_xml():
    """目录表 prompt 用 XML 解释行级支持状态含义，避免孤立状态词。"""
    from sustainability_desk.contract.models import GsColDef
    from sustainability_desk.llm.prompts import (
        CATALOG_ROW_SUPPORT_EVIDENCE_KEY,
        CATALOG_ROW_SUPPORT_STATUS_KEY,
        CATALOG_ROW_WRITING_RULE_KEY,
        render_catalog_table_fill_prompt,
    )

    cols = [
        GsColDef(key="risk_type", header="风险类型", cellType="text"),
        GsColDef(key="risk_name", header="风险名称", cellType="text"),
        GsColDef(key="impact", header="潜在影响", cellType="ai_text"),
    ]
    ctx = sse_model_context(section_task="气候相关物理风险识别", report_subject=("所属行业：电气制造",))

    system, user = render_catalog_table_fill_prompt(
        ctx,
        catalog_rows=[
            {
                "risk_type": "急性风险",
                "risk_name": "台风",
                "referenceImpact": "大风天气可能影响运营连续性",
                CATALOG_ROW_SUPPORT_STATUS_KEY: "user_supported_anchor",
                CATALOG_ROW_SUPPORT_EVIDENCE_KEY: "用户在本表绑定的问题中选择或补充了「台风」。",
                CATALOG_ROW_WRITING_RULE_KEY: "围绕该锚点概括用户已提供信息。",
            },
            {"risk_type": "慢性风险", "risk_name": "水短缺", "referenceImpact": "水资源约束影响生产运营"},
        ],
        columns=cols,
        kind_label="风险",
    )

    assert "<catalog_row_input_context>" in system
    assert "<support_status_guide>" in system
    assert '<support_status code="user_supported_anchor">' in system
    assert '<support_status code="framework_anchor">' in system
    assert '<row_input_support status="user_supported_anchor">' in system
    assert '<row_input_support status="framework_anchor">' in system
    assert "<business_meaning>用户在本表绑定的问题中选择或补充了「台风」。</business_meaning>" in system
    assert "不代表用户已经识别该风险/机遇" in system
    assert "不得把其他行或全表用户资料迁移为本行的公司事实" in system
    assert "风险类型" in system and "risk_type" not in system
    assert "referenceImpact" not in system
    assert CATALOG_ROW_SUPPORT_STATUS_KEY not in system
    assert "台风" not in user and user.startswith("<filled_content")
