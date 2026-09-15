# ABOUTME: 披露准则名称派生测试——大陆三所准则名、港交所守则并入与附加参考文件进入编制依据。
# ABOUTME: 断言按无档位语义编写：准则名派生不依赖任何披露档位。
from sustainability_desk.contract.models import DisclosureProfile, Report
from sustainability_desk.contract.report_values import (
    disclosure_basis_statement,
    selected_standard_names_text,
)
from knowledge_package_fixtures import SSE_PACKAGE

MAINLAND_STANDARD_NAMES = SSE_PACKAGE.manifest.disclosure_basis.mainland_standard_names.by_code()


def _report(profile: DisclosureProfile | None) -> Report:
    return Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[], disclosureProfile=profile)


def test_mainland_standard_selects_exchange_specific_name() -> None:
    assert "深圳证券交易所" in selected_standard_names_text(
        _report(DisclosureProfile(mainlandStandard="szse"))
    )
    assert "北京证券交易所" in selected_standard_names_text(
        _report(DisclosureProfile(mainlandStandard="bse"))
    )
    # 未配置时按 sse 兜底。
    assert MAINLAND_STANDARD_NAMES["sse"] == selected_standard_names_text(_report(None))


def test_hong_kong_guide_and_additional_references_join_basis_statement() -> None:
    profile = DisclosureProfile(
        mainlandStandard="sse",
        includesHongKongExchangeGuide=True,
        additionalDisclosureReferences=["《GRI 可持续发展报告标准》", "  "],
    )
    statement = disclosure_basis_statement(_report(profile))
    assert MAINLAND_STANDARD_NAMES["sse"] in statement
    assert "香港联合交易所" in statement
    assert "《GRI 可持续发展报告标准》" in statement
    # 空白附加项不进入编制依据。
    assert "、、" not in statement and not statement.endswith("、")
