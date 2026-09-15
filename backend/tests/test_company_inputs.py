# ABOUTME: CompanyInputs parse-first 契约的 fail-loud 单测——合法上游输入通过，捏造/派生/越界/非法即报错。
# ABOUTME: 守住"eval 输入只能是上游真实产出的形状"这条边界，防再次出现 fixture 捏造上游不产的数据。
import pytest
from pydantic import ValidationError

from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.contract.company_inputs import parse_company_inputs


def _base() -> dict:
    return {
        "fields": {"company_short_name": "示例", "reporting_year": 2025,
                   "industry_major_category": "制造业", "industry_division": "金属制品业"},
        "company_profile": "公司简介……",
        "business_summary": "约100字主营业务概述占位",
        "intake": {"climate.q_training_activities": {"answer": "是"}},
        "assessmentInput": {
            "reportingYear": 2025,
            "threshold": {"financial": 4.0, "impact": 4.0},
            "scores": [{
                "assessmentTopicId": "climate_change",
                "financialScore": 4.4,
                "impactScore": 4.3,
            }],
        },
        "disclosureProfile": {"mainlandStandard": "sse"},
    }


def test_valid_inputs_parse():
    inputs = parse_company_inputs(package=SSE_PACKAGE, raw=_base())
    assert inputs.assessmentInput.scores[0].assessmentTopicId == "climate_change"
    assert inputs.business_summary.startswith("约100字")


def test_reject_derived_field():
    bad = _base()
    bad["fields"]["industry"] = "制造业 / 金属制品业"
    with pytest.raises(ValidationError, match="派生字段"):
        parse_company_inputs(package=SSE_PACKAGE, raw=bad)
    bad2 = _base()
    bad2["fields"]["company_business_summary"] = "手设派生"
    with pytest.raises(ValidationError, match="派生字段"):
        parse_company_inputs(package=SSE_PACKAGE, raw=bad2)


def test_reject_unknown_field():
    bad = _base()
    bad["fields"]["made_up_field"] = "x"
    with pytest.raises(ValidationError, match="非 user_input 字段"):
        parse_company_inputs(package=SSE_PACKAGE, raw=bad)


def test_reject_materiality_or_iroitems_on_topic_score():
    bad = _base()
    bad["assessmentInput"]["scores"][0]["materiality"] = "dual"
    with pytest.raises(ValidationError):  # extra=forbid
        parse_company_inputs(package=SSE_PACKAGE, raw=bad)
    bad2 = _base()
    bad2["assessmentInput"]["scores"][0]["reportSectionId"] = "climate_change"
    with pytest.raises(ValidationError):
        parse_company_inputs(package=SSE_PACKAGE, raw=bad2)


def test_reject_unknown_topic_id():
    bad = _base()
    bad["assessmentInput"]["scores"][0]["assessmentTopicId"] = "not_a_real_topic"
    with pytest.raises(ValidationError, match="未知评分议题"):
        parse_company_inputs(package=SSE_PACKAGE, raw=bad)


@pytest.mark.parametrize("value", [0, -0.5, 5.1, 3.55])
def test_reject_topic_score_outside_template_scale(value: float):
    bad = _base()
    bad["assessmentInput"]["scores"][0]["financialScore"] = value
    with pytest.raises(ValidationError, match="评分"):
        parse_company_inputs(package=SSE_PACKAGE, raw=bad)


def test_reject_answer_shape_mismatch():
    bad = _base()
    bad["intake"]["climate.q_training_activities"] = {"answer": ["是"]}  # list into single_select
    with pytest.raises(ValidationError, match="single_select"):
        parse_company_inputs(package=SSE_PACKAGE, raw=bad)
    bad2 = _base()
    bad2["intake"]["climate.q_training_activities"] = {"answer": "也许"}  # 越界选项
    with pytest.raises(ValidationError, match="single_select"):
        parse_company_inputs(package=SSE_PACKAGE, raw=bad2)


def test_reject_company_profile_duplicate_in_generic_intake() -> None:
    bad = _base()
    bad["intake"]["company_profile"] = {"answer": "重复的公司简介"}

    with pytest.raises(ValidationError, match="CompanyInputs.company_profile"):
        parse_company_inputs(package=SSE_PACKAGE, raw=bad)


def test_reject_extra_toplevel_key():
    bad = _base()
    bad["assessment"] = {"topics": []}  # 已装配层字段不该出现在上游输入
    with pytest.raises(ValidationError):
        parse_company_inputs(package=SSE_PACKAGE, raw=bad)
