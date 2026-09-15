# ABOUTME: 简易报告资料输入适配器合同测试，锁定字段、内容清单、指标与附录的统一写入边界。
# ABOUTME: 资料解析只能经 adapter 写入 StoredReportStateV4，派生字段与正文不在其所有权范围内。
from __future__ import annotations

import pytest

from sustainability_desk.material.input_adapter import (
    InputWrite,
    LightweightReportInputAdapter,
    TargetValueConflictError,
    UnknownMaterialTargetError,
)
from knowledge_package_fixtures import SSE_PACKAGE


def test_adapter_exposes_all_user_owned_lightweight_input_targets() -> None:
    adapter = LightweightReportInputAdapter(SSE_PACKAGE)
    profile = adapter.target("company_profile")
    topic = adapter.target("climate.q_training_activities")

    assert profile.scope_id == "profile"
    assert profile.kind == "text"
    assert topic.scope_id == "climate_change"
    assert topic.options == ("是", "否", "不确定")
    field = adapter.target("field.company_short_name")
    metric = adapter.target("metric.economic_environment_r04")
    appendix = adapter.target("appendix.reader_feedback.email")

    assert field.target_type == "field"
    assert field.kind == "text"
    assert metric.target_type == "quantitative_metric"
    assert metric.kind == "number"
    assert appendix.target_type == "appendix"
    with pytest.raises(UnknownMaterialTargetError):
        adapter.target("field.industry")


def test_adapter_rejects_unknown_option_group_and_length_violations() -> None:
    adapter = LightweightReportInputAdapter(SSE_PACKAGE)
    with pytest.raises(ValueError, match="选项"):
        adapter.validate_write(
            InputWrite(
                target_key="climate.q_training_activities",
                answer="没有证据",
                expected_definition_fingerprint=adapter.target_fingerprint("climate.q_training_activities"),
                expected_target_fingerprint=adapter.fingerprint(None, None),
            )
        )
    with pytest.raises(ValueError, match="至少选择"):
        adapter.validate_write(
            InputWrite(
                target_key="climate.q_climate_risk_choices",
                answer=["台风"],
                expected_definition_fingerprint=adapter.target_fingerprint("climate.q_climate_risk_choices"),
                expected_target_fingerprint=adapter.fingerprint(None, None),
            )
        )
    with pytest.raises(ValueError, match="至少 100"):
        adapter.validate_write(
            InputWrite(
                target_key="company_profile",
                answer="太短",
                expected_definition_fingerprint=adapter.target_fingerprint("company_profile"),
                expected_target_fingerprint=adapter.fingerprint(None, None),
            )
        )


def test_adapter_accepts_climate_opportunity_selection_without_option_groups() -> None:
    """无分组选项不应因风险题的分组校验而触发未初始化变量错误。"""
    adapter = LightweightReportInputAdapter(SSE_PACKAGE)

    validated = adapter.validate_write(
        InputWrite(
            target_key="climate.q_climate_opportunity_choices",
            answer=["能源绿色转型"],
            expected_definition_fingerprint=adapter.target_fingerprint(
                "climate.q_climate_opportunity_choices"
            ),
            expected_target_fingerprint=adapter.fingerprint(None, None),
        )
    )

    assert validated.answer == ["能源绿色转型"]


def test_adapter_applies_only_validated_targets_and_checks_target_fingerprint() -> None:
    adapter = LightweightReportInputAdapter(SSE_PACKAGE)
    state = {
        "version": 4,
        "fields": {"company_name": "示例公司"},
        "intakeItems": {
            "climate.q_training_activities": {"answer": None, "supplement": None},
        },
        "generatedBlocks": {"existing": {"content": [{"kind": "text", "text": "保留"}]}},
    }
    write = InputWrite(
        target_key="climate.q_training_activities",
        answer="是",
        supplement="开展了节能培训。",
        expected_definition_fingerprint=adapter.target_fingerprint("climate.q_training_activities"),
        expected_target_fingerprint=adapter.fingerprint(None, None),
    )

    updated = adapter.apply(state, [write])

    assert updated["intakeItems"][write.target_key] == {
        "answer": "是",
        "supplement": "开展了节能培训。",
    }
    assert updated["fields"] == state["fields"]
    assert updated["generatedBlocks"] == state["generatedBlocks"]
    assert state["intakeItems"][write.target_key]["answer"] is None

    stale = write.model_copy(update={"expected_target_fingerprint": "0" * 64})
    with pytest.raises(TargetValueConflictError):
        adapter.apply(state, [stale])


def test_adapter_applies_field_metric_and_appendix_to_their_single_state_owners() -> None:
    adapter = LightweightReportInputAdapter(SSE_PACKAGE)
    state = {
        "version": 4,
        "fields": {},
        "meta": None,
        "appendixPackage": None,
    }
    writes = [
        InputWrite(
            target_key="field.company_short_name",
            answer="示例公司",
            expected_definition_fingerprint=adapter.target_fingerprint("field.company_short_name"),
            expected_target_fingerprint=adapter.fingerprint(None, None),
        ),
        InputWrite(
            target_key="metric.economic_environment_r04",
            answer="120.5",
            supplement="按年度盘查口径统计",
            expected_definition_fingerprint=adapter.target_fingerprint("metric.economic_environment_r04"),
            expected_target_fingerprint=adapter.fingerprint(None, None),
        ),
        InputWrite(
            target_key="appendix.reader_feedback.email",
            answer="esg@example.com",
            expected_definition_fingerprint=adapter.target_fingerprint("appendix.reader_feedback.email"),
            expected_target_fingerprint=adapter.fingerprint(None, None),
        ),
    ]

    updated = adapter.apply_automatic(state, writes)

    assert updated["fields"]["company_short_name"] == "示例公司"
    assert updated["meta"]["quantitativeMetrics"]["metrics"]["economic_environment_r04"] == {
        "value": "120.5", "note": "按年度盘查口径统计",
    }
    assert updated["appendixPackage"]["readerFeedbackContactInformation"]["email"] == "esg@example.com"
