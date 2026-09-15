# ABOUTME: 地基对齐 schema 扩展测试——IntakeItem 与附录 fileLabel。
from sustainability_desk.contract.models import ExternalAssuranceReport, Field, IntakeItem, QuantitativeMetricDraft, Report
from knowledge_package_fixtures import SSE_PACKAGE


def test_intake_item_has_supplement():
    item = IntakeItem(key="k", contentScopeId="t", prompt="组织架构说明", kind="text", supplement="由办公室负责")
    assert item.supplement == "由办公室负责"


def test_external_assurance_uses_file_label():
    report = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[])
    report.appendixPackage.externalAssuranceReport = ExternalAssuranceReport(isIncluded=True, fileLabel="assurance.pdf")
    assert report.appendixPackage.externalAssuranceReport.fileLabel == "assurance.pdf"


def test_table_cell_value_accepts_str_and_list():
    """GsTableCell.value 以 str 或 list[str] 为合法值（SSOT §3.C 与实现一致）。"""
    from sustainability_desk.contract.models import GsTableCell

    assert GsTableCell(colKey="name", value="市场风险").value == "市场风险"
    cell = GsTableCell(colKey="value_chain", value=["上游价值链", "公司运营"])
    assert cell.value == ["上游价值链", "公司运营"]


def test_table_cell_value_rejects_non_str():
    """GsTableCell.value 仅接受 str 或 list[str]（或 None），其他类型（如 int）应被拒绝。"""
    import pytest
    from pydantic import ValidationError
    from sustainability_desk.contract.models import GsTableCell

    with pytest.raises(ValidationError):
        GsTableCell(colKey="x", value=123)


def test_typed_field_values_reject_free_text_for_number_and_dates():
    import pytest
    from pydantic import ValidationError

    assert Field(key="year", label="年份", type="year", source="user_input", value="2026").value == "2026"
    assert Field(key="date", label="日期", type="date", source="user_input", value="2024-02-29").value == "2024-02-29"
    assert Field(key="year", label="年份", type="year", source="user_input", value="").value == ""
    with pytest.raises(ValidationError):
        Field(key="number", label="数值", type="number", source="user_input", value="12吨")
    with pytest.raises(ValidationError):
        Field(key="date", label="日期", type="date", source="user_input", value="2026-02-29")
    with pytest.raises(ValidationError):
        Field(key="date", label="日期", type="date", source="user_input", value="20260203")


def test_quantitative_metric_values_reject_units_and_free_text():
    import pytest
    from pydantic import ValidationError

    assert QuantitativeMetricDraft(value="-12.5").value == "-12.5"
    with pytest.raises(ValidationError):
        QuantitativeMetricDraft(value="12.5 吨")
