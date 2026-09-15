# ABOUTME: 产品观测写入边界测试——未知枚举静默丢弃、写入失败不冒泡、payload 不含用户数据。
# ABOUTME: 观测不得改变产品行为，这三条是本模块的全部契约。
from __future__ import annotations

from uuid import uuid4

import pytest

from sustainability_desk.persistence.product_telemetry import (
    is_known_error_kind,
    is_known_screen,
    record_export_blocked,
    record_page_error,
    record_page_reached,
)


class _RecordingPool:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, object, object]] = []
        self._fail = fail

    async def execute(self, sql: str, *args: object) -> None:
        if self._fail:
            raise RuntimeError("数据库不可用")
        self.calls.append((sql, args[0], args[1] if len(args) > 1 else None))


@pytest.mark.asyncio
async def test_page_reached_writes_only_screen_id():
    pool = _RecordingPool()
    report_id = uuid4()
    await record_page_reached(pool, report_id, "topic-questions")
    assert len(pool.calls) == 1
    sql, rid, payload = pool.calls[0]
    assert "page_reached" in sql and rid == report_id
    assert payload == {"screenId": "topic-questions"}


@pytest.mark.asyncio
async def test_unknown_screen_is_dropped_not_raised():
    """浏览器不能自定义事件语义；未知值静默丢弃，不写库也不报错。"""
    pool = _RecordingPool()
    await record_page_reached(pool, uuid4(), "attacker-supplied")
    await record_page_error(pool, uuid4(), "report-document", "made-up-kind")
    assert pool.calls == []


@pytest.mark.asyncio
async def test_page_error_payload_excludes_message_and_stack():
    pool = _RecordingPool()
    await record_page_error(pool, uuid4(), "report-document", "chunk_load_error")
    _sql, _rid, payload = pool.calls[0]
    assert payload == {"screenId": "report-document", "kind": "chunk_load_error"}
    assert "message" not in payload and "stack" not in payload


@pytest.mark.asyncio
async def test_export_blocked_records_codes_only():
    """issue message 含报告正文片段，只有稳定 code 可以落库。"""
    pool = _RecordingPool()
    await record_export_blocked(pool, uuid4(), ("missing_metric", "empty_block"))
    _sql, _rid, payload = pool.calls[0]
    assert payload == {
        "issueCodes": ["missing_metric", "empty_block"],
        "issueCount": 2,
    }


@pytest.mark.asyncio
async def test_write_failure_never_propagates():
    """观测失败不得让用户的导出或页面加载失败。"""
    pool = _RecordingPool(fail=True)
    await record_page_reached(pool, uuid4(), "report-document")
    await record_page_error(pool, uuid4(), "report-document", "runtime_error")
    await record_export_blocked(pool, uuid4(), ("x",))


def test_enumerations_are_closed():
    assert is_known_screen("report-document") and not is_known_screen("unknown-page")
    assert is_known_error_kind("render_error") and not is_known_error_kind("custom")
