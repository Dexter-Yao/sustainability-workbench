# ABOUTME: 联系邮箱格式跨端 golden 一致性测试（后端侧）——读共享 fixture 跑 is_valid_contact_email。
# ABOUTME: 与前端 input-validation.test.ts 消费同一 fixture，两端各自对 golden 成立即防双写漂移。
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sustainability_desk.contract.report_values import is_valid_contact_email

FIXTURE = Path(__file__).parent / "fixtures" / "email_validation_golden.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[case["value"] for case in CASES])
def test_contact_email_golden(case: dict) -> None:
    assert is_valid_contact_email(case["value"]) is case["expected"]
