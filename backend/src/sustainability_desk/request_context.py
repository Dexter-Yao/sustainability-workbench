# ABOUTME: HTTP 请求关联上下文——校验或生成 X-Request-ID，并供日志与生成 Trace 读取。
# ABOUTME: 外部请求 ID 仅接受有限 ASCII 字符，避免日志注入和无界字段。
# ABOUTME(en): HTTP request correlation context — validates or generates X-Request-ID for logs and generation traces.
# ABOUTME(en): An external request id accepts only a limited ASCII set, avoiding log injection and unbounded fields.
from __future__ import annotations

import re
import logging
import time
from contextvars import ContextVar
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_REQUEST_ID = ContextVar("sustainability_desk_request_id", default="")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
logger = logging.getLogger(__name__)


def current_request_id() -> str:
    """返回当前请求 ID；非 HTTP 调用返回空串。"""
    return _REQUEST_ID.get()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """为请求建立关联 ID，并在响应头返回最终值。"""

    async def dispatch(self, request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if _SAFE_REQUEST_ID.fullmatch(supplied) else f"req-{uuid4().hex}"
        token = _REQUEST_ID.set(request_id)
        started = time.monotonic()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "request_completed requestId=%s method=%s path=%s status=%d durationMs=%d",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                round((time.monotonic() - started) * 1000),
            )
            return response
        except Exception:
            logger.exception(
                "request_failed requestId=%s method=%s path=%s durationMs=%d",
                request_id,
                request.method,
                request.url.path,
                round((time.monotonic() - started) * 1000),
            )
            raise
        finally:
            _REQUEST_ID.reset(token)
