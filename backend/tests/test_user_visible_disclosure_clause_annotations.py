# ABOUTME: 用户可见准则批注条款原文测试，保障批注读取独立于准则披露要求库。
# ABOUTME: 本测试不触碰 Prompt 装配，避免两条准则链路混用。

from sustainability_desk.contract.disclosure_standards_index import (
    apply_disclosure_standards_index_projection,
)
from sustainability_desk.contract.loader import load_contract
from sustainability_desk.contract.user_visible_disclosure_clause_annotations import (
    find_user_visible_disclosure_clause_annotation_entry,
    load_user_visible_disclosure_clause_annotations,
)
from knowledge_package_fixtures import SSE_PACKAGE


def test_loads_climate_clause_text_for_each_mainland_standard():
    entries = load_user_visible_disclosure_clause_annotations(SSE_PACKAGE)
    standards = {entry.mainlandStandard for entry in entries if entry.reportSectionKey == "climate_change"}
    assert standards == {"sse", "szse", "bse"}


def test_finds_climate_clause_text_by_standard_and_section():
    entry = find_user_visible_disclosure_clause_annotation_entry(SSE_PACKAGE, 
        mainland_standard="sse",
        report_section_key="climate_change",
    )
    assert entry is not None
    assert entry.reportContentTopicName == "应对气候变化"
    assert "第二十四条" in entry.appendixIndexClauseReferences
    assert any("温室气体范围1排放量" in item.clauseOriginalText for item in entry.clauseOriginalTexts)


def test_appendix_index_topics_are_available_for_all_mainland_standards():
    entries = load_user_visible_disclosure_clause_annotations(SSE_PACKAGE)
    by_standard = {}
    for entry in entries:
        by_standard.setdefault(entry.mainlandStandard, set()).add(entry.reportContentTopicName)

    expected_topics = {
        "应对气候变化",
        "环境合规管理",
        "污染物排放管理",
        "废弃物管理",
        "生态系统与生物多样性保护",
        "能源管理",
        "水资源管理",
        "促进循环经济",
        "乡村振兴与社会贡献",
        "创新驱动",
        "科技伦理",
        "可持续供应链管理",
        "平等对待中小企业",
        "产品质量与安全",
        "客户服务质量管理",
        "数据安全与客户隐私保护",
        "人力资本发展",
        "职业健康与安全",
        "可持续发展管理",
        "尽职调查",
        "利益相关方沟通",
        "反商业贿赂与反贪污",
        "反不正当竞争",
    }
    assert by_standard == {
        "sse": expected_topics,
        "szse": expected_topics,
        "bse": expected_topics,
    }


def test_special_topic_boundaries_follow_appendix_index():
    entries = load_user_visible_disclosure_clause_annotations(SSE_PACKAGE)
    sse_entries = {entry.reportContentTopicName: entry for entry in entries if entry.mainlandStandard == "sse"}

    assert sse_entries["科技伦理"].reportSectionKey == "technology_ethics"
    assert "第四十三条" in sse_entries["科技伦理"].appendixIndexClauseReferences

    assert sse_entries["可持续发展管理"].reportSectionKey == "sustainability_mgmt"
    assert "第五十一条" in sse_entries["可持续发展管理"].appendixIndexClauseReferences

    assert sse_entries["利益相关方沟通"].reportSectionKey == "sm.stakeholder"
    assert "第五十三条" in sse_entries["利益相关方沟通"].appendixIndexClauseReferences


def test_index_table_replicates_template_verbatim():
    """索引表逐字复刻模板：章分组行 + 每条款一行 + 节跨行合并；科技伦理不适用显示“不涉及”。"""
    report = load_contract(
        SSE_PACKAGE.report_contract_path
    )
    projected = apply_disclosure_standards_index_projection(report)
    table = projected.find_block("appendix.standards_index.table").table
    assert table is not None
    rows = [row for row in table.children if not row.headerRow]

    chapter_rows = [row for row in rows if len(row.children) == 1]
    assert [row.children[0].value for row in chapter_rows] == [
        "第三章 环境信息披露",
        "第四章 社会信息披露",
        "第五章 可持续发展相关治理信息披露",
    ]
    assert all(row.children[0].colSpan == 3 for row in chapter_rows)

    clause_rows = [row for row in rows if len(row.children) > 1]
    assert len(clause_rows) == 37  # 第二十条—第五十六条逐条一行
    clauses = []
    for row in clause_rows:
        cells = {cell.colKey: cell for cell in row.children}
        clauses.append((cells["clause_reference"].value, cells["report_section"].value))
    by_clause = dict(clauses)
    assert by_clause["第二十条"] == "应对气候变化"
    assert by_clause["第二十九条"] == "环境合规管理\n污染物排放管理\n废弃物管理\n生态系统与生物多样性保护"
    assert by_clause["第五十一条"] == "可持续发展管理"
    assert by_clause["第五十三条"] == "利益相关方沟通"
    # 固定大纲(未装配科技伦理章节)下,第四十三条按模板显示"不涉及"。
    assert by_clause["第四十三条"] == "不涉及"

    # 披露要求列按节合并:首条款行携带节名与 rowSpan,续行省略该单元格。
    first_climate = next(
        row for row in clause_rows
        if any(c.colKey == "clause_reference" and c.value == "第二十条" for c in row.children)
    )
    requirement = next(c for c in first_climate.children if c.colKey == "disclosure_requirement")
    assert requirement.value == "第一节 应对气候变化"
    assert requirement.rowSpan == 9
    second_climate = next(
        row for row in clause_rows
        if any(c.colKey == "clause_reference" and c.value == "第二十一条" for c in row.children)
    )
    assert all(c.colKey != "disclosure_requirement" for c in second_climate.children)
