# ABOUTME(en): Prompt Profile contract tests: one profile per knowledge package, identified by the package id,
# ABOUTME(en): with a strict configuration shape; new report audiences add packages, never nested conditionals.
import pytest
from pydantic import ValidationError

from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.llm.prompt_profiles import (
    ReportGenerationPromptProfile,
    load_prompt_profile,
)


def test_sse_profile_is_typed_and_named_for_its_package() -> None:
    profile = load_prompt_profile(SSE_PACKAGE)

    assert profile.schema_version == "sustainability_desk.prompt_profile.v1"
    assert profile.profile_id == SSE_PACKAGE.id
    assert "中国中小企业" in profile.shared_system_segments.role
    expression_guidance = profile.shared_system_segments.expression_guidance.strip()
    assert len(expression_guidance) > 100
    assert "最有信息量" not in expression_guidance
    assert "段落先明确中心" in expression_guidance
    assert "直接进入当前模块的实质内容" in expression_guidance
    report_body_contract = profile.shared_system_segments.report_body_contract
    assert "正式正文" in report_body_contract
    assert "咨询建议" in report_body_contract
    # 格式红线逐条列全而非引用外部文档：唯一注入点承载 Markdown 禁令、数值范围百分号、
    # 概数顿号、日期标全与标题/题注标点红线（模型输出规范 v1）。
    content_format = profile.shared_system_segments.content_format
    assert "GB/T 1.1-2020" in content_format
    assert "不使用 Markdown" in content_format
    assert "百分号不得省略" in content_format
    assert "概数连用不加顿号" in content_format
    assert "不编虚位" in content_format
    assert "标题末尾不用标点" in content_format
    assert "项目符号" in content_format
    assert set(type(profile.shared_system_segments).model_fields) == {
        "context_fields",
        "role",
        "report_body_contract",
        "expression_guidance",
        "content_format",
    }


def test_prompt_profile_rejects_unknown_configuration_fields() -> None:
    profile = load_prompt_profile(SSE_PACKAGE)
    payload = profile.model_dump(by_alias=True)
    payload["unowned_future_scope"] = "上市公司"

    with pytest.raises(ValidationError):
        ReportGenerationPromptProfile.model_validate(payload)


def test_profile_owns_every_model_visible_text_section() -> None:
    """The package profile, not code, words what the model reads: labels, postures, agent instructions."""

    profile = load_prompt_profile(SSE_PACKAGE)
    assert profile.labels.key_value_separator == "："
    assert profile.labels.table.none == "（无）"
    assert profile.evidence_postures.context_only.source_use
    assert profile.context_only_calibration.governance
    assert profile.public_risk_disclosure_guidance
    assert profile.metric_narrative.process_labels.statistics == "统计"
    assert "FileDossierProposal" in profile.agent_instructions.file_agent.instructions
    assert profile.company_business_summary.target_length == 100
    assert profile.module_title_generation is not None
    assert "{module_count}" in profile.module_title_generation.system_instruction


def test_profile_rejects_a_missing_label() -> None:
    profile = load_prompt_profile(SSE_PACKAGE)
    payload = profile.model_dump(by_alias=True)
    del payload["labels"]["table"]["none"]

    with pytest.raises(ValidationError):
        ReportGenerationPromptProfile.model_validate(payload)
