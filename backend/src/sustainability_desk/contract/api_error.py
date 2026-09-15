# ABOUTME: HTTP 错误响应的领域契约：错误在 API 边界被解析成携带稳定 code 与用户文案的对象。
# ABOUTME: 内部标识（account_id、对象路径、上游响应体、SQL 约束名）只进日志与 trace，永不进响应体。
# ABOUTME(en): Domain contract for HTTP errors: parsed at the API boundary into a stable code plus user copy.
# ABOUTME(en): Internal ids (account_id, paths, upstream bodies, SQL constraint names) go only to logs and traces.
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger("sustainability_desk.api_error")


class ApiErrorDetail(BaseModel):
    """错误响应体的唯一形态：机器判定用 code，用户阅读用 message。

    code 是稳定的领域标识，前端据此决定引导动作（例如名额已满时直接引导去删除报告），
    不再靠匹配中文文案猜测错误种类。message 由代码侧确定性生成，不承载异常内部消息。
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


def api_error(
    *,
    status_code: int,
    code: str,
    message: str,
    cause: BaseException | None = None,
    log_context: str | None = None,
) -> HTTPException:
    """构造 typed 错误响应，并把内部上下文留在服务端日志里。

    `log_context` 承载排查所需的内部事实（异常原文、账户 id、对象路径等）。它只写日志，
    不进响应体——异常消息一旦成为用户文案，任何人日后往异常里加个标识符就会泄露
    （例如 `ActiveReportLimitError(str(account_id))` 经 `detail=str(exc)` 透传，
    界面就会把账户 UUID 当错误提示显示给用户）。
    """

    if log_context or cause is not None:
        logger.warning(
            "api_error code=%s status=%s context=%s cause=%r",
            code,
            status_code,
            log_context or "-",
            cause,
        )
    return HTTPException(
        status_code=status_code,
        detail=ApiErrorDetail(code=code, message=message).model_dump(mode="json"),
    )


REQUEST_BODY_INVALID_CODE = "request_body_invalid"
REQUEST_BODY_INVALID_MESSAGE = "提交的数据不符合服务端要求，请刷新页面后重试。"


def _validation_field_paths(exc: RequestValidationError) -> list[str]:
    """把校验错误的字段位置压成排查用路径，丢弃 input 与上游 ctx。

    只取 loc：`input` 是用户提交的原始片段、`ctx` 是 pydantic 内部细节，两者都不该
    离开服务端。路径本身也只进日志，不进响应体。
    """

    paths: list[str] = []
    for error in exc.errors():
        location = error.get("loc") or ()
        path = ".".join(str(part) for part in location)
        if path:
            paths.append(path)
    return paths


async def handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """请求体校验失败的用户可见投影：与其它错误同走 ApiErrorDetail。

    FastAPI 默认把 `[{loc, msg, input, ctx}]` 原样返回：`input` 回显用户提交的字段值、
    `loc` 暴露服务端模型结构、`msg` 是英文内部措辞。三者都违反「错误响应只承载稳定 code
    与代码侧中文文案」这条边界（schema-contract.md「持久化数据合同」）。
    字段路径是排查所必需的，因此只写日志。
    """

    logger.warning(
        "api_error code=%s status=422 method=%s path=%s fields=%s",
        REQUEST_BODY_INVALID_CODE,
        request.method,
        request.url.path,
        "、".join(_validation_field_paths(exc)) or "-",
    )
    # 包在 detail 里：与 api_error() 构造的 HTTPException 同形态，前端只需一条解析分支。
    return JSONResponse(
        status_code=422,
        content={
            "detail": ApiErrorDetail(
                code=REQUEST_BODY_INVALID_CODE,
                message=REQUEST_BODY_INVALID_MESSAGE,
            ).model_dump(mode="json")
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    """把框架默认错误响应接回本模块的唯一形态。"""

    app.add_exception_handler(
        RequestValidationError, handle_request_validation_error
    )
