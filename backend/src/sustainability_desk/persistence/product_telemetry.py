# ABOUTME: 产品使用观测的写入边界——页面到达、前端错误与导出拦截，统一落 report_events。
# ABOUTME: 只接受受控枚举与稳定标识；错误消息、用户输入与堆栈不进入本表，避免审计表承载用户数据。
# ABOUTME(en): Write boundary for product usage observation — screen reached, frontend errors, blocked exports,
# ABOUTME(en): all into report_events. Accepts controlled enums and stable ids only; no user input or stacks.
from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

# 页面标识取自前端既有 screenId，不另立命名体系。
type ScreenId = Literal[
    "report-config",
    "materiality-scoring",
    "quantitative-intake",
    "input-path",
    "topic-questions",
    "materials-upload",
    "materials-processing",
    "report-document",
    "report-generation",
    "reports",
]

# 错误只按类型分档：具体消息可能含用户填写的企业信息，不落审计表。
type FrontendErrorKind = Literal[
    "render_error",  # React 渲染期异常（ErrorBoundary 捕获）
    "unhandled_rejection",  # 未处理的 Promise 拒绝
    "runtime_error",  # window.onerror
    "chunk_load_error",  # 静态资源加载失败，通常是发布期缓存错配
]

_SCREEN_IDS: frozenset[str] = frozenset(
    (
        "report-config",
        "materiality-scoring",
        "quantitative-intake",
        "input-path",
        "topic-questions",
        "materials-upload",
        "materials-processing",
        "report-document",
        "report-generation",
        "reports",
    )
)

_ERROR_KINDS: frozenset[str] = frozenset(
    ("render_error", "unhandled_rejection", "runtime_error", "chunk_load_error")
)


def is_known_screen(screen_id: str) -> bool:
    return screen_id in _SCREEN_IDS


def is_known_error_kind(kind: str) -> bool:
    return kind in _ERROR_KINDS


async def record_page_reached(
    pool: asyncpg.Pool, report_id: UUID, screen_id: str
) -> None:
    """记录用户到达某页面。

    产品端无第三方埋点；没有该事件时页面到达只能由保存动作反推，看不见"打开了但没填"。
    观测失败不得影响用户操作，因此异常只记日志。
    """
    if not is_known_screen(screen_id):
        logger.warning("忽略未知 screenId 的页面到达事件")
        return
    try:
        await pool.execute(
            "insert into report_events (report_id, actor, event_type, payload) "
            "values ($1, 'user', 'page_reached', $2)",
            report_id,
            {"screenId": screen_id},
        )
    except Exception:
        logger.exception("页面到达事件写入失败 report_id=%s", report_id)


async def record_page_error(
    pool: asyncpg.Pool, report_id: UUID, screen_id: str, kind: str
) -> None:
    """记录前端错误的发生位置与类型。

    只存 screenId 与受控 kind：错误消息与堆栈可能带出用户填写的企业信息，
    诊断细节走浏览器控制台与运行日志，不进审计表。
    """
    if not is_known_screen(screen_id) or not is_known_error_kind(kind):
        logger.warning("忽略未知形态的前端错误事件")
        return
    try:
        await pool.execute(
            "insert into report_events (report_id, actor, event_type, payload) "
            "values ($1, 'user', 'page_error', $2)",
            report_id,
            {"screenId": screen_id, "kind": kind},
        )
    except Exception:
        logger.exception("前端错误事件写入失败 report_id=%s", report_id)


async def record_export_blocked(
    pool: asyncpg.Pool, report_id: UUID, issue_codes: tuple[str, ...]
) -> None:
    """记录工作台导出被诊断闸拦截。

    生成链路的 export_blocked 已有台账，工作台 `POST /api/export` 的 422 也须落台账，
    否则这段漏斗不可见。只存稳定 issue code，不存 message——后者含报告正文片段。
    """
    try:
        await pool.execute(
            "insert into report_events (report_id, actor, event_type, payload) "
            "values ($1, 'system', 'workbench_export_blocked', $2)",
            report_id,
            {"issueCodes": list(issue_codes), "issueCount": len(issue_codes)},
        )
    except Exception:
        logger.exception("导出拦截事件写入失败 report_id=%s", report_id)
