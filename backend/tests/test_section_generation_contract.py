# ABOUTME: 整节生成公共响应合同测试。
# ABOUTME: 锁定段落/表格互斥结果与未知字段 fail-loud，不允许下游消费松散字典。
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sustainability_desk.contract.section_generation import SectionGenerationResponse


def _response() -> dict:
    return {
        "batch_id": str(uuid4()),
        "mode": "initial",
        "replayed": False,
        "state_seq": 2,
        "results": [{"block_id": "profile", "text": "企业简介"}],
        "section_titles": {},
        "input_fingerprint": "a" * 64,
        "freshness": "fresh",
        "company_business_summary": None,
        "allowance": {
            "quota": 3,
            "used": 0,
            "reserved": 0,
            "remaining": 3,
        },
    }


def test_section_generation_response_parses_public_projection() -> None:
    parsed = SectionGenerationResponse.model_validate(_response())

    assert parsed.results[0].block_id == "profile"


def test_section_generation_response_rejects_unknown_nested_fields() -> None:
    payload = _response()
    payload["allowance"]["debug"] = True

    with pytest.raises(ValidationError):
        SectionGenerationResponse.model_validate(payload)
