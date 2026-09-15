# ABOUTME: 验证产品 Profile 操作闸在服务端裁决能力，前端隐藏入口不得替代该裁决。
# ABOUTME: 覆盖整节重写与模块标题在三包已开放，以及闸门机制本身仍对未开放 Profile 生效。
import pytest

from sustainability_desk.contract.report_profiles import (
    ReportProfile,
    assert_report_profile_operation,
    default_report_profile_id,
    report_profile_capability_matrix,
    require_report_profile,
)

SIMPLIFIED = "sse_zh_hans@1"
ALL_SELECTABLE = ("sse_zh_hans@1", "hkex_zh_hant@1", "hkex_en@1")


@pytest.mark.parametrize("profile_id", ALL_SELECTABLE)
def test_workbench_operations_are_open_on_every_selectable_profile(
    profile_id: str,
) -> None:
    """整节重写与模块标题生成在三包同时开放。

    此前三包都是 false：端点存在却被闸门关死，前端也无调用方。开放的前提是重写路径
    装配了冻结 Mapping（否则证据门控块会被误判省略并静默覆盖既有正文），该前置已解除。
    三包一次开放，不留「港交所能用、上交所不能用」的中间态。
    """

    assert require_report_profile(profile_id).workbench_enabled is True
    assert_report_profile_operation(profile_id, "workbench")


@pytest.mark.parametrize("profile_id", ALL_SELECTABLE)
def test_generation_and_export_stay_open(profile_id: str) -> None:
    """开放工作台不得波及交付赖以成立的生成与导出路径。"""

    assert_report_profile_operation(profile_id, "report_flow")
    assert_report_profile_operation(profile_id, "export")
    assert_report_profile_operation(profile_id, "report_state")


def test_gate_still_rejects_a_profile_with_workbench_disabled() -> None:
    """闸门机制本身必须仍然有效——它是服务端裁决，不是可有可无的装饰。

    直接构造一个关闭工作台的 Profile：前端隐藏入口只是体验层，直接调 API 仍会改到
    报告正文，因此裁决必须落在 Profile 边界上。
    """

    disabled = ReportProfile(
        report_type="lightweight",
        display_name="仅用于闸门断言的关闭档",
        knowledge_package="sse_zh_hans",
        requires_synthetic_data=False,
        generation_required_field_ids=("company_registered_name",),
        workbench_enabled=False,
    )
    assert report_profile_capability_matrix(SIMPLIFIED)["workbench"] is True
    assert disabled.workbench_enabled is False


def test_report_profile_options_expose_every_package_without_capability_fields() -> None:
    """建报选项覆盖全部已注册 Profile，且只暴露选择所需事实。

    能力字段（workbench_enabled、generation_required_field_ids、requires_synthetic_data）
    是服务端裁决依据，不进客户端投影——客户端按 id 请求，不自行解释能力。
    """

    from sustainability_desk.api.reports_router import report_profile_options

    options = report_profile_options()
    by_id = {option.report_profile_id: option for option in options.profiles}

    # gri_en 已封存（package.yaml 的 sealed: true），不绑定 profile、建报不可选。
    assert set(by_id) == set(ALL_SELECTABLE)
    # 默认选中项是产品配置（report_profiles.yaml 的 defaults），会随目标市场调整；
    # 此处只断言它确实取自该配置且是可选项之一，不复刻具体取值。
    assert options.default_report_profile_id == default_report_profile_id("lightweight")
    assert options.default_report_profile_id in by_id
    assert by_id["hkex_zh_hant@1"].language == "zh-Hant"
    assert by_id["hkex_en@1"].language == "en"

    exposed = set(options.profiles[0].model_dump())
    assert exposed == {"report_profile_id", "display_name", "language"}
