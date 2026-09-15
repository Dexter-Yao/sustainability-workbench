# ABOUTME: StoredReportStateV4 独立领域合同测试，锁定嵌套严格解析、废弃版本拒绝与数据库边界归一化。
# ABOUTME: 状态快照中的未知结构不得被 API 或持久化层静默丢弃。
from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from sustainability_desk.contract.stored_report_state import StoredReportStateV4
from sustainability_desk.persistence import reports


def _state() -> dict:
    return {
        "version": 4,
        "fields": {},
        "intakeItems": {},
        "generatedBlocks": {},
        "tableBlocks": {},
    }


def test_stored_report_state_rejects_unknown_nested_fields() -> None:
    with pytest.raises(ValidationError):
        StoredReportStateV4.model_validate(
            {
                **_state(),
                "generatedBlocks": {
                    "about.generated": {
                        "content": [
                            {"kind": "text", "text": "正文", "plate_internal": True}
                        ]
                    }
                },
            }
        )


def test_stored_report_state_rejects_retired_v3_with_rebuild_message() -> None:
    with pytest.raises(ValidationError, match="状态版本已废弃，请重建报告"):
        StoredReportStateV4.model_validate({**_state(), "version": 3})


def test_stored_report_state_validates_structured_input_freshness() -> None:
    state = StoredReportStateV4.model_validate(
        {
            **_state(),
            "structuredInputFreshness": {
                "assessmentContextFingerprint": "a" * 64,
                "quantitativeMetricsContextFingerprint": None,
            },
        }
    )

    assert state.structuredInputFreshness.assessmentContextFingerprint == "a" * 64
    with pytest.raises(ValidationError):
        StoredReportStateV4.model_validate(
            {
                **_state(),
                "structuredInputFreshness": {
                    "assessmentContextFingerprint": "not-sha256",
                },
            }
        )


class _StateReader:
    async def fetchrow(self, *_args):
        return {
            "report_id": uuid4(),
            "state": {**_state(), "unknown": "数据库脏字段"},
            "state_seq": 1,
            "contract_version": "contract-version",
        }


async def test_database_read_parses_stored_report_state() -> None:
    with pytest.raises(ValidationError):
        await reports.get_state(_StateReader(), uuid4(), uuid4())

