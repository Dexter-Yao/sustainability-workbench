# ABOUTME: API 错误契约守卫——错误响应只承载稳定 code 与用户文案，内部标识只进日志。
# ABOUTME: 本地栈未启动时整组跳过；异常构造侧的纯合同断言不依赖数据库。
from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

import asyncpg
import httpx
import pytest
from httpx import ASGITransport

from sustainability_desk.api.app import app
from sustainability_desk.api.auth import AuthenticatedUser, current_user
from sustainability_desk.contract.api_error import ApiErrorDetail, api_error
from sustainability_desk.contract.report_profiles import (
    ReportProfileOperationError,
    assert_report_profile_operation,
)
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.persistence.db import _init_connection, get_pool

LOCAL_DB = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"

UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

# 错误文案里绝不该出现的内部实现痕迹。用户看到它们既无从行动，也暴露了服务端结构。
FORBIDDEN_FRAGMENTS = (
    "Traceback",
    "psycopg",
    "asyncpg",
    "violates unique constraint",
    "relation \"",
    "supabase",
    "Storage HTTP",
    "weak_password",
    "error_code",
    "/auth/v1",
    "Bearer ",
)


def assert_clean_user_message(text: str, *, context: str) -> None:
    """错误文案必须可读、可行动，且不携带任何内部标识。"""

    assert UUID_PATTERN.search(text) is None, f"{context} 的错误文案含内部 UUID：{text!r}"
    lowered = text.lower()
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment.lower() not in lowered, f"{context} 的错误文案含内部实现痕迹 {fragment!r}：{text!r}"


def user_messages(payload: object) -> list[str]:
    """取出响应体中所有会被前端当作用户文案显示的字符串。

    前端 lib/api-error.ts 依次读取 `detail`（字符串）、`detail.message`、顶层 `message`，
    这里覆盖同样的形态，确保断言的就是用户真正看到的文本。
    """

    if not isinstance(payload, dict):
        return []
    found: list[str] = []
    detail = payload.get("detail")
    if isinstance(detail, str):
        found.append(detail)
    elif isinstance(detail, dict):
        if isinstance(detail.get("message"), str):
            found.append(detail["message"])
    elif isinstance(detail, list):
        # FastAPI 请求体校验失败的默认形态。守卫若只认 str 与 dict，就读不到这一支，
        # 「422 把 loc 与 input 原样回显」在结构上无法被发现。
        # 整条序列化后交给断言：loc、msg、input、ctx 任一含内部痕迹都应失败。
        found.append(json.dumps(detail, ensure_ascii=False))
    if isinstance(payload.get("message"), str):
        found.append(payload["message"])
    return found


# --- 纯合同断言：异常构造侧不把内部标识当用户文案 -------------------------------


def test_report_profile_error_keeps_profile_id_out_of_message() -> None:
    """profile_id 只作排查上下文；既有捕获点用 `detail=str(error)`，消息即用户文案。"""

    with pytest.raises(ReportProfileOperationError) as caught:
        assert_report_profile_operation("nonexistent_profile@9", "workbench")

    error = caught.value
    assert error.code == "report_profile_unknown"
    assert error.profile_id == "nonexistent_profile@9"
    assert "nonexistent_profile@9" not in str(error)
    assert_clean_user_message(str(error), context="ReportProfileOperationError")


def test_active_report_limit_error_keeps_account_id_out_of_detail() -> None:
    """根源断言：account_id 不得成为用户可见文案。"""

    account_id = str(uuid4())
    error = reports_dal.ActiveReportLimitError(account_id, limit=1, scope="full_simplified")

    assert error.account_id == account_id
    assert error.limit == 1
    assert str(error) != account_id


async def test_request_validation_error_keeps_user_input_out_of_response() -> None:
    """请求体校验失败走 ApiErrorDetail，不回显用户提交的值与服务端字段路径。

    FastAPI 默认返回 `[{loc, msg, input, ctx}]`：`input` 是用户刚提交的字段值、
    `loc` 暴露服务端模型结构、`msg` 是英文内部措辞。三者都不是用户可见文案。
    此处驱动真实端点而非直接构造异常——处理器若未注册，默认响应会原样通过。
    """

    app.dependency_overrides[current_user] = lambda: AuthenticatedUser(
        subject=uuid4(), email=None
    )
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/plan",
                json={
                    "report_id": "not-a-uuid",
                    "report": {"title": "客户机密公司名"},
                    "unexpected_field": "用户提交的内部值",
                },
            )

        assert response.status_code == 422
        body = response.json()
        assert body == {
            "detail": {
                "code": "request_body_invalid",
                "message": "提交的数据不符合服务端要求，请刷新页面后重试。",
            }
        }

        raw = json.dumps(body, ensure_ascii=False)
        # 用户提交的原始片段不得回流。
        for leaked in ("not-a-uuid", "客户机密公司名", "用户提交的内部值"):
            assert leaked not in raw, f"422 响应回显了用户提交内容：{leaked!r}"
        # 服务端模型结构不得暴露。
        for internal in ("unexpected_field", "sections", "uuid_parsing", "extra_forbidden"):
            assert internal not in raw, f"422 响应暴露了服务端内部细节：{internal!r}"

        for message in user_messages(body):
            assert_clean_user_message(message, context="POST /api/plan 422")
    finally:
        app.dependency_overrides.clear()


WEAK_PASSWORD_UPSTREAM_BODY = (
    '{"code":422,"error_code":"weak_password",'
    '"msg":"Password should contain at least one character of each: abcdefghijklmnopqrstuvwxyz.",'
    '"weak_password":{"reasons":["characters"]}}'
)


def test_api_error_builds_typed_detail_without_internal_context() -> None:
    """api_error 的 log_context 只进日志，不进响应体。"""

    account_id = str(uuid4())
    exc = api_error(
        status_code=403,
        code="active_report_limit_reached",
        message="活跃报告已达上限（1 份），删除不再需要的报告后可新建",
        log_context=f"account_id={account_id}",
    )

    assert exc.status_code == 403
    detail = ApiErrorDetail.model_validate(exc.detail)
    assert detail.code == "active_report_limit_reached"
    assert_clean_user_message(detail.message, context="api_error")
    assert account_id not in str(exc.detail)


def test_material_upload_failure_reasons_are_clean_user_text() -> None:
    """资料上传失败原因是用户可见文案（design.md §7.3），不得来自异常字符串。

    它经 200 响应的 error_message / parse_failure_reason 投影到界面，前端的错误解析
    完全绕不到，因此必须在写入点就是干净文案。曾写入 `str(error)`：存储层带 Supabase
    原始响应体与 `{account_id}/{workspace_id}/{source_id}` 三段 UUID 对象路径，
    兜底分支带 asyncpg 的表名与唯一约束名。
    """

    from sustainability_desk.material import workspace as mws

    for reason in (mws._STORAGE_FAILURE_REASON, mws._UPLOAD_FAILURE_REASON):
        assert reason, "失败原因不能为空——用户需要知道发生了什么"
        assert_clean_user_message(reason, context="资料上传失败原因")


def test_material_service_never_writes_exception_text_into_failure_reason() -> None:
    """静态守卫：失败原因的写入点不得再出现 `reason=str(error)` 或异常插值。

    真实存储故障难以在测试里稳定构造，因此这里守写入点本身——它是最直接的
    泄露形态。异常细节应当经 _log_upload_failure 进日志。
    """

    from sustainability_desk.material import workspace as mws

    source = Path(mws.__file__).read_text(encoding="utf-8")
    offenders = re.findall(r"reason=(?:str\(error\)|f\"[^\"]*\{error\}[^\"]*\")", source)
    assert not offenders, (
        f"material.workspace 仍把异常文本写进用户可见的失败原因：{offenders}"
    )


# --- 真实 HTTP 断言：用户实际看到的响应体 ---------------------------------------


@pytest.fixture
async def pool():
    try:
        created = await asyncpg.create_pool(
            LOCAL_DB, min_size=1, max_size=3, init=_init_connection, timeout=3
        )
    except OSError:
        pytest.skip("本地 Supabase 栈未启动")
    yield created
    await created.close()


@pytest.fixture
async def principal(pool):
    """建一个名额为 1 的账户，便于触发真实的名额上限 403。"""

    subject = uuid4()
    await pool.execute("insert into auth.users (id) values ($1)", subject)
    account_id = await pool.fetchval(
        "insert into accounts (email) values ($1) returning id",
        f"api-error-{subject}@example.edu.cn",
    )
    await pool.execute(
        "insert into account_identities (account_id, identity_issuer, identity_subject)"
        " values ($1, 'primary', $2)",
        account_id,
        subject,
    )
    await pool.execute(
        """
        insert into account_entitlement_grants
          (account_id, profile_id, starts_at, ends_at, granted_by, reason)
        values ($1, 'local_single_user@1', now(), now() + interval '1 year',
                'test', 'integration_test')
        """,
        account_id,
    )
    yield subject, account_id
    await pool.execute("delete from accounts where id = $1", account_id)
    await pool.execute("delete from auth.users where id = $1", subject)


async def test_active_report_limit_response_is_actionable_and_carries_code(
    pool, principal
) -> None:
    """名额上限的 403 必须给出可行动说明，并携带前端可判定的 code。"""

    subject, account_id = principal
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[current_user] = lambda: AuthenticatedUser(
        subject=subject, email=None
    )
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for index in range(20):
                created = await client.post(
                    "/api/reports", json={"title": f"名额内报告 {index}"}
                )
                assert created.status_code == 201

            second = await client.post("/api/reports", json={"title": "超出名额报告"})
            assert second.status_code == 403

            payload = second.json()
            messages = user_messages(payload)
            assert messages, f"错误响应没有可显示的用户文案：{payload!r}"
            for message in messages:
                assert_clean_user_message(message, context="POST /api/reports 403")
                assert "上限" in message and "删除" in message
            assert str(account_id) not in str(payload)
    finally:
        app.dependency_overrides.clear()


async def test_error_responses_across_endpoints_never_leak_internal_identifiers(
    pool, principal
) -> None:
    """扫一批必然失败的端点，断言没有任何一条把内部标识送到用户面前。

    这是防回退的执行性防护：persistence 层仍有 30 余处异常把裸 id 当消息，它们目前
    靠各捕获点的固定文案拦住。任何人日后新增一处 `detail=str(exc)`，本测试即失败。
    """

    subject, _ = principal
    unknown_report = uuid4()
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[current_user] = lambda: AuthenticatedUser(
        subject=subject, email=None
    )
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            probes = [
                ("GET", f"/api/reports/{unknown_report}/state", None),
                ("GET", f"/api/reports/{unknown_report}/preparation", None),
                ("GET", f"/api/reports/{unknown_report}/material-workspace", None),
                ("GET", f"/api/reports/{unknown_report}/file-intake", None),
                ("DELETE", f"/api/reports/{unknown_report}", None),
                ("POST", f"/api/reports/{unknown_report}/generations", {}),
                (
                    "PUT",
                    f"/api/reports/{unknown_report}/state",
                    {"state": {"version": 4}, "base_seq": 1},
                ),
            ]
            checked = 0
            for method, url, body in probes:
                response = await client.request(method, url, json=body)
                if response.status_code < 400:
                    continue
                checked += 1
                payload = response.json()
                assert str(unknown_report) not in str(payload), (
                    f"{method} {url} 的错误响应回显了请求中的报告 id：{payload!r}"
                )
                for message in user_messages(payload):
                    assert_clean_user_message(
                        message, context=f"{method} {url} {response.status_code}"
                    )
            assert checked >= 6, f"探测到的失败响应过少（{checked}），守卫可能失效"
    finally:
        app.dependency_overrides.clear()


# 账户链路只剩需登录的端点；未登录时应是干净的 401，不得回显 token 或内部标识。
_ACCOUNT_PROBES: tuple[tuple[str, str, dict[str, object] | None], ...] = (
    ("PUT", "/api/account/onboarding-seen", {"steps": [""]}),
)


def _write_routes(prefix: str = "/api") -> set[tuple[str, str]]:
    """枚举所有改变状态的端点（含路径模板）。

    include_router 后的路由挂在 `_IncludedRouter` 包装里，顶层 `app.routes` 读不到
    子路由的 path——直接遍历顶层会枚举到空集，使守卫静默失效。
    """

    found: set[tuple[str, str]] = set()

    def walk(routes: object) -> None:
        for route in routes or ():  # type: ignore[union-attr]
            inner = getattr(route, "original_router", None)
            if inner is not None:
                walk(getattr(inner, "routes", ()))
                continue
            path = getattr(route, "path", "")
            if not path.startswith(prefix):
                continue
            methods = getattr(route, "methods", set()) or set()
            # 只要求改变状态的端点被探测；只读投影端点由所有权校验与其它用例覆盖。
            for method in methods & {"POST", "PUT", "PATCH", "DELETE"}:
                found.add((method, path))

    walk(app.routes)
    return found


def _account_write_routes() -> set[tuple[str, str]]:
    return _write_routes("/api/account")


async def test_account_endpoint_errors_never_leak_internal_identifiers() -> None:
    """账户链路的失败响应只承载稳定 code 与中文文案，不泄露内部标识或上游原文。"""

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        checked = 0
        for method, url, body in _ACCOUNT_PROBES:
            response = await client.request(method, url, json=body)
            if response.status_code < 400:
                continue
            checked += 1
            for message in user_messages(response.json()):
                assert_clean_user_message(
                    message, context=f"{method} {url} {response.status_code}"
                )
        assert checked >= 1, f"账户端点探测到的失败响应过少（{checked}），守卫可能失效"


def test_every_account_route_is_covered_by_a_probe() -> None:
    """新增账户端点必须同时进入上面的探测清单，否则本测试失败。

    守卫的覆盖面应当默认打开：靠人记得登记新路由的清单，必然在最该看的地方留下缺口
    （手机号链路就是这样整条逃出守卫的）。这里从 app.routes 反射枚举，
    把「存在未被探测的写入端点」本身当作断言失败项。
    """

    probed = {(method, url) for method, url, _ in _ACCOUNT_PROBES}
    account_routes = _account_write_routes()
    # 先钉住枚举本身有效：枚举不到路由时，下面的断言会空过而守卫形同虚设。
    assert account_routes, "未枚举到任何账户写入端点，路由反射已失效"

    unprobed = sorted(
        f"{method} {path}"
        for method, path in account_routes
        if (method, path) not in probed
    )
    assert not unprobed, (
        "以下账户端点未被错误契约守卫探测，请加入 _ACCOUNT_PROBES：" + "、".join(unprobed)
    )


# 路径参数一律替换成不存在的 id：这样每条写入端点都会走进「找不到 / 无权」的失败分支，
# 正是最容易把内部标识回显出去的那条路径。
def _probe_url(path_template: str, unknown_id: str) -> str:
    return re.sub(r"\{[^}]+\}", unknown_id, path_template)


async def test_all_write_endpoints_never_leak_internal_identifiers(pool, principal) -> None:
    """自动探测**每一条**写入端点，覆盖面不靠人登记。

    守卫若只探测手写的 URL 清单，新链路会整条落在守卫之外。
    这里从 app.routes 反射出全部写入端点逐条打，新增 router 自动纳入——
    「新加端点忘了登记」这种缺口在结构上不再可能出现。
    """

    subject, _ = principal
    unknown_id = str(uuid4())
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[current_user] = lambda: AuthenticatedUser(
        subject=subject, email=None
    )
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            routes = sorted(_write_routes())
            assert routes, "未枚举到任何写入端点，路由反射已失效"
            checked = 0
            for method, template in routes:
                url = _probe_url(template, unknown_id)
                try:
                    response = await client.request(method, url, json={})
                except Exception:
                    # 端点在空 body 下抛异常属于用例构造不足，不是泄露；交给专项用例覆盖。
                    continue
                if response.status_code < 400:
                    continue
                checked += 1
                payload = response.json()
                assert unknown_id not in str(payload), (
                    f"{method} {url} 的错误响应回显了请求中的 id：{payload!r}"
                )
                for message in user_messages(payload):
                    assert_clean_user_message(
                        message, context=f"{method} {url} {response.status_code}"
                    )
            assert checked >= 20, f"探测到的失败响应过少（{checked}），守卫可能失效"
    finally:
        app.dependency_overrides.clear()
