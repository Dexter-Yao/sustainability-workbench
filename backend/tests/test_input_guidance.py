# ABOUTME: 输入体验合同测试，确保用户可见说明与默认规则只绑定已声明字段且不进入模型上下文。
# ABOUTME: 模板保持无公司事实；路径错误或规则错配必须在加载期失败。

import pytest

from sustainability_desk.contract.loader import load_contract
from sustainability_desk.contract.models import Block, Field, Inline, Report, Section
from sustainability_desk.llm.prompts import build_model_context, render_prompt
from knowledge_package_fixtures import SSE_PACKAGE

CONTRACT = SSE_PACKAGE.report_contract_path


def test_template_declares_user_visible_report_period_guidance() -> None:
    """报告期三个字段使用受控默认规则，模板本身仍不带字段值。"""
    report = load_contract(CONTRACT)

    assert report.fields["reporting_year"].value is None
    assert report.inputGuidance is not None
    assert report.inputGuidance["fields.reporting_year.value"].defaultRule == "previous_calendar_year"
    assert report.inputGuidance["fields.report_period_start.value"].defaultRule == "reporting_year_start"
    assert report.inputGuidance["fields.report_period_end.value"].defaultRule == "reporting_year_end"
    assert "appendixPackage.readerFeedbackContactInformation.email" in report.inputGuidance
    # helpText 可省（标签自明时不复述），但写了就不得是空白；且每条至少承载一项内容。
    assert all(
        guidance.helpText is None or guidance.helpText.strip()
        for guidance in report.inputGuidance.values()
    )
    assert all(
        guidance.helpText or guidance.termExplanation or guidance.defaultRule
        for guidance in report.inputGuidance.values()
    )


def test_input_guidance_rejects_unknown_field_path() -> None:
    """说明只能挂在模板已声明的输入位置，避免 JSX 与配置漂移。"""
    with pytest.raises(ValueError, match="未声明字段"):
        Report.model_validate(
            {
                "title": "t",
                "fields": {
                    "reporting_year": {
                        "key": "reporting_year",
                        "label": "报告年份",
                        "type": "year",
                        "source": "user_input",
                    }
                },
                "inputGuidance": {
                    "fields.missing_field.value": {"helpText": "填写说明"},
                },
                "sections": [],
            }
        )


def test_input_guidance_rejects_default_rule_target_mismatch() -> None:
    """默认规则与字段目标必须一一对应，避免默认值含义漂移。"""
    with pytest.raises(ValueError, match="只能用于"):
        Report.model_validate(
            {
                "title": "t",
                "fields": {
                    "reporting_year": {
                        "key": "reporting_year",
                        "label": "报告年份",
                        "type": "year",
                        "source": "user_input",
                    }
                },
                "inputGuidance": {
                    "fields.reporting_year.value": {
                        "helpText": "填写报告覆盖的完整年度。",
                        "defaultRule": "reporting_year_start",
                    },
                },
                "sections": [],
            }
        )


def test_user_visible_input_guidance_never_enters_model_context() -> None:
    """填写释义仅服务用户界面，LLM 只读取声明为生成输入的字段事实。"""
    guidance = "填写本报告覆盖的完整年度。"
    block = Block(
        id="about.generated",
        type="paragraph",
        blockType="generative",
        source="ai",
        content=[Inline(kind="text", text="撰写报告概述")],
        generation={
            "task": {"focus": "about"},
            "inputs": {
                "evidence": {"kind": "explicit"},
                "fields": ["reporting_year"],
            },
        },
    )
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        fields={
            "reporting_year": Field(
                key="reporting_year",
                label="报告年份",
                type="year",
                source="user_input",
                value="2025",
            )
        },
        inputGuidance={"fields.reporting_year.value": {"helpText": guidance}},
        sections=[Section(key="about", title="关于本报告", headingLevel=1, blocks=[block])],
    )

    system, user = render_prompt(build_model_context(block, report, report))

    assert guidance not in system + user
