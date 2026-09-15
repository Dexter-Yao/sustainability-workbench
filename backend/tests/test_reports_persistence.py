# ABOUTME: 报告持久化 DAL 与端点的集成测试——验证 Account 建报、乐观锁、隔离与归档。
# ABOUTME: 本地栈未启动时整组跳过；测试 Account/身份/Grant 在夹具内自建自清。
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from httpx import ASGITransport

from sustainability_desk.api.app import app
from sustainability_desk.api.auth import AuthenticatedUser, current_user
from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.persistence import reports as dal
from sustainability_desk.persistence.db import _init_connection, get_pool
from knowledge_package_fixtures import SSE_PACKAGE, SSE_REPORT_PROFILE_ID

LOCAL_DB = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"

STATE_V4 = {"version": 4, "fields": {}, "intakeItems": {}, "generatedBlocks": {}, "tableBlocks": {}}


@pytest.fixture
async def pool():
    try:
        p = await asyncpg.create_pool(LOCAL_DB, min_size=1, max_size=3, init=_init_connection, timeout=3)
    except OSError:
        pytest.skip("本地 Supabase 栈未启动")
    yield p
    await p.close()


@pytest.fixture
async def users(pool):
    principals = []
    for index in range(2):
        subject = uuid4()
        await pool.execute("insert into auth.users (id) values ($1)", subject)
        account_id = await pool.fetchval(
            "insert into accounts (email) values ($1) returning id",
            f"reports-{subject}@example.edu.cn",
        )
        await pool.execute(
            "insert into account_identities (account_id, identity_issuer, identity_subject) values ($1, 'primary', $2)",
            account_id,
            subject,
        )
        await pool.execute(
            """
            insert into account_entitlement_grants
              (account_id, profile_id, starts_at, ends_at, granted_by, reason)
            values ($1, 'local_single_user@1', now(), now() + interval '1 year', 'test', 'integration_test')
            """,
            account_id,
        )
        principals.append(Principal(subject, account_id))
    yield tuple(principals)
    for principal in principals:
        await pool.execute("delete from accounts where id = $1", principal.account_id)
        await pool.execute("delete from auth.users where id = $1", principal.subject)


@dataclass(frozen=True)
class Principal:
    subject: UUID
    account_id: UUID


async def _create(pool, principal, title="测试报告"):
    return await dal.create_report(
        pool,
        account_id=principal.account_id,
        title=title,
        report_type="lightweight",
        report_profile_id="sse_zh_hans@1",
        data_classification="customer",
        contract_version=contract_version(SSE_PACKAGE),
        initial_state=STATE_V4,
        active_scope_limit=1,
        profile_id="local_single_user@1",
    )


async def test_create_report_writes_state_and_event(pool, users):
    owner, _ = users
    summary = await _create(pool, owner)
    assert summary.contract_version == contract_version(SSE_PACKAGE)
    assert summary.report_type == "lightweight" and summary.report_profile_id == "sse_zh_hans@1"
    assert summary.data_classification == "customer"

    state = await dal.get_state(pool, owner.account_id, summary.id)
    assert state.state_seq == 1 and state.state["version"] == 4

    events = await pool.fetch(
        "select event_type from report_events where report_id = $1 order by id", summary.id
    )
    assert [e["event_type"] for e in events] == ["report_created"]


async def test_put_state_optimistic_lock(pool, users):
    owner, _ = users
    summary = await _create(pool, owner, "锁测试")
    new_seq = await dal.put_state(pool, owner.account_id, summary.id, {**STATE_V4, "fields": {"a": 1}}, base_seq=1)
    assert new_seq == 2
    with pytest.raises(dal.StateConflictError):
        await dal.put_state(pool, owner.account_id, summary.id, STATE_V4, base_seq=1)


async def test_generic_put_cannot_overwrite_structured_input_freshness(
    pool,
    users,
):
    owner, _ = users
    summary = await _create(pool, owner, "结构化输入 owner 测试")
    authoritative = "a" * 64
    raw = await pool.fetchval(
        "select state from report_states where report_id = $1",
        summary.id,
    )
    raw["structuredInputFreshness"] = {
        "assessmentContextFingerprint": authoritative,
        "quantitativeMetricsContextFingerprint": None,
    }
    await pool.execute(
        "update report_states set state = $1 where report_id = $2",
        raw,
        summary.id,
    )

    await dal.put_state(
        pool,
        owner.account_id,
        summary.id,
        {
            **STATE_V4,
            "structuredInputFreshness": {
                "assessmentContextFingerprint": "b" * 64,
                "quantitativeMetricsContextFingerprint": "c" * 64,
            },
        },
        base_seq=1,
    )

    stored = await dal.get_state(pool, owner.account_id, summary.id)
    assert stored.state["structuredInputFreshness"] == {
        "assessmentContextFingerprint": authoritative,
        "quantitativeMetricsContextFingerprint": None,
    }


async def test_owner_isolation_and_archive(pool, users):
    owner, other = users
    summary = await _create(pool, owner, "隔离测试")
    assert await dal.list_reports(pool, other.account_id) == []
    with pytest.raises(dal.ReportNotFoundError):
        await dal.get_state(pool, other.account_id, summary.id)

    await dal.archive_report(pool, owner.account_id, summary.id)
    archived = await dal.list_reports(pool, owner.account_id)
    assert len(archived) == 1 and archived[0].status == "archived"
    with pytest.raises(dal.ReportNotFoundError):
        await dal.get_state(pool, owner.account_id, summary.id)

    # 删除对用户不可撤销：不提供恢复入口，报告行保留仅为承载审计事件。
    events = await pool.fetch(
        "select event_type from report_events where report_id = $1 order by id", summary.id
    )
    assert [event["event_type"] for event in events][-1:] == ["report_archived"]


async def test_router_endpoints_with_conflict_409(pool, users):
    owner, _ = users
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[current_user] = lambda: AuthenticatedUser(subject=owner.subject, email=None)
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # The Profile is pinned: this case asserts SSE package facts (language, fields), so it
            # must not ride on the server default, which follows the target market and does change.
            created = await client.post(
                "/api/reports",
                json={"title": "端点测试", "report_profile_id": SSE_REPORT_PROFILE_ID},
            )
            assert created.status_code == 201
            report_id = created.json()["id"]
            # Language is a projection of the Profile's knowledge package, never a stored copy.
            assert created.json()["report_profile_id"] == SSE_REPORT_PROFILE_ID
            assert created.json()["language"] == SSE_PACKAGE.language

            listed = await client.get("/api/reports")
            assert [r["id"] for r in listed.json()["reports"]] == [report_id]

            got = await client.get(f"/api/reports/{report_id}/state")
            assert got.status_code == 200 and got.json()["state_seq"] == 1
            assert got.json()["report_profile_id"] == SSE_REPORT_PROFILE_ID
            assert got.json()["language"] == SSE_PACKAGE.language

            unknown_nested = await client.put(
                f"/api/reports/{report_id}/state",
                json={
                    "state": {
                        **STATE_V4,
                        "fields": {"company_registered_name": "端点测试公司"},
                        "generatedBlocks": {
                            "company_intro.body": {
                                "content": [{"kind": "text", "text": "正文", "ignored": True}],
                                "state": "ready",
                            }
                        },
                    },
                    "base_seq": 1,
                },
            )
            assert unknown_nested.status_code == 422

            saved = await client.put(
                f"/api/reports/{report_id}/state",
                json={
                    "state": {
                        **STATE_V4,
                        "fields": {"company_registered_name": "端点测试公司"},
                        "generatedBlocks": {
                            "company_intro.body": {
                                "content": [{"kind": "text", "text": "正文"}],
                                "state": "ready",
                            }
                        },
                        "tableBlocks": {
                            "sustainability_mgmt.governance_table": {
                                "children": [{
                                    "children": [{
                                        "type": "td", "colKey": "name", "value": "用户行",
                                    }],
                                    "origin": {"from": "ai", "theme": "气候风险"},
                                }]
                            }
                        },
                    },
                    "base_seq": 1,
                },
            )
            assert saved.status_code == 200 and saved.json()["state_seq"] == 2, saved.text

            # 列表摘要携带派生的公司注册名，供前端组成可区分的显示名。
            listed_after_fill = await client.get("/api/reports")
            assert listed_after_fill.json()["reports"][0]["company_registered_name"] == "端点测试公司"

            normalized = await client.get(f"/api/reports/{report_id}/state")
            assert normalized.json()["state"]["generatedBlocks"]["company_intro.body"] == {
                "content": [{"kind": "text", "text": "正文", "ref": None, "fallback": None, "marks": None}],
                "state": "ready",
            }
            row = normalized.json()["state"]["tableBlocks"]["sustainability_mgmt.governance_table"]["children"][0]
            assert row["origin"] == {"from": "ai", "theme": "气候风险", "category": None, "driver_hint": None}
            assert "children" not in row["children"][0]

            unknown_top = await client.put(
                f"/api/reports/{report_id}/state",
                json={"state": {**STATE_V4, "unknown": "rejected"}, "base_seq": 2},
            )
            assert unknown_top.status_code == 422

            stale = await client.put(
                f"/api/reports/{report_id}/state", json={"state": STATE_V4, "base_seq": 1}
            )
            assert stale.status_code == 409

            bad_version = await client.put(
                f"/api/reports/{report_id}/state", json={"state": {"version": 1}, "base_seq": 2}
            )
            assert bad_version.status_code == 422

            malformed = await client.put(
                f"/api/reports/{report_id}/state",
                json={"state": {**STATE_V4, "fields": {"x": {"not": "a field value"}}}, "base_seq": 2},
            )
            assert malformed.status_code == 422

            archived = await client.delete(f"/api/reports/{report_id}")
            assert archived.status_code == 204
    finally:
        app.dependency_overrides.clear()


async def test_put_state_rejects_invalid_reader_feedback_email(pool, users):
    owner, _ = users
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[current_user] = lambda: AuthenticatedUser(subject=owner.subject, email=None)
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/reports", json={"title": "邮箱校验"})
            report_id = created.json()["id"]

            invalid = await client.put(
                f"/api/reports/{report_id}/state",
                json={
                    "state": {
                        **STATE_V4,
                        "appendixPackage": {
                            "readerFeedbackContactInformation": {"email": "请发送至 user@example.com"}
                        },
                    },
                    "base_seq": 1,
                },
            )
            assert invalid.status_code == 422
            detail = invalid.json()["detail"]
            assert detail["code"] == "invalid_reader_feedback_email"
            assert detail["field"] == "appendixPackage.readerFeedbackContactInformation.email"

            valid = await client.put(
                f"/api/reports/{report_id}/state",
                json={
                    "state": {
                        **STATE_V4,
                        "appendixPackage": {
                            "readerFeedbackContactInformation": {"email": "esg@example.com"}
                        },
                    },
                    "base_seq": 1,
                },
            )
            assert valid.status_code == 200, valid.text

            empty = await client.put(
                f"/api/reports/{report_id}/state",
                json={"state": STATE_V4, "base_seq": 2},
            )
            assert empty.status_code == 200, empty.text
    finally:
        app.dependency_overrides.clear()


async def test_archive_returns_uploaded_file_paths_for_purge(pool, users):
    """删除报告必须交出上传文件的对象路径，否则文件在存储里无限期留存。

    报告行保留是为了承载审计事件（report_events 经外键绑在它上面），
    但用户上传的文件既占存储又含原始资料，必须真删；DAL 交出路径、API 边界执行删除。
    """
    owner, _ = users
    summary = await _create(pool, owner, "含资料的报告")
    workspace_id = uuid4()
    await pool.execute(
        """
        insert into material_workspaces
          (id, report_id, account_id, adapter_id, contract_version, status)
        values ($1, $2, $3, 'material_intake@1', $4, 'active')
        """,
        workspace_id, summary.id, owner.account_id, contract_version(SSE_PACKAGE),
    )
    object_path = f"{owner.account_id}/{workspace_id}/{uuid4()}.pdf"
    await pool.execute(
        """
        insert into material_sources
          (workspace_id, account_id, source_label, original_filename, object_path,
           kind, media_type, size_bytes, sha256)
        values ($1, $2, '测试资料', 'a.pdf', $3, 'pdf', 'application/pdf', 10, $4)
        """,
        workspace_id, owner.account_id, object_path, "0" * 64,
    )

    purgeable = await dal.archive_report(pool, owner.account_id, summary.id)

    assert object_path in purgeable, "删除报告未交出上传文件路径，文件将永远留在存储里"


async def test_archive_without_files_returns_nothing_to_purge(pool, users):
    owner, _ = users
    summary = await _create(pool, owner, "无资料的报告")

    assert await dal.archive_report(pool, owner.account_id, summary.id) == ()


async def test_put_state_validates_what_actually_persists(pool, users):
    """范围校验必须作用于锁内覆盖之后的落库状态，而不是请求体。

    put_state 会用锁内权威值覆盖 assessmentInput 等四个字段。若校验请求体，
    校验对象与落库对象就不是同一份：既可能因一个反正会被丢弃的字段拒绝合法写入，
    也可能放行锁内已有的越界事实。
    """
    owner, _ = users
    summary = await _create(pool, owner, "校验目标测试")
    seen: list[dal.StoredReportStateV4] = []

    await dal.put_state(
        pool,
        owner.account_id,
        summary.id,
        {**STATE_V4, "fields": {"company_registered_name": "某公司"}},
        1,
        validate=seen.append,
    )

    assert len(seen) == 1, "校验器未被调用，范围校验形同虚设"
    # 锁内权威字段：校验看到的必须是覆盖后的值，而不是请求体里的值。
    assert seen[0].assessmentInput is None
    assert seen[0].fields["company_registered_name"] == "某公司"


async def test_put_state_rejection_prevents_the_write(pool, users):
    """校验器抛错必须阻断写入，而不是先落库再报错。"""
    owner, _ = users
    summary = await _create(pool, owner, "拒绝写入测试")

    def reject(_state: dal.StoredReportStateV4) -> None:
        raise ValueError("超出范围")

    with pytest.raises(ValueError):
        await dal.put_state(
            pool,
            owner.account_id,
            summary.id,
            {**STATE_V4, "fields": {"company_registered_name": "不该落库"}},
            1,
            validate=reject,
        )

    stored = await dal.get_state(pool, owner.account_id, summary.id)
    assert stored.state["fields"] == {}, "校验失败后仍写入了数据"
    assert stored.state_seq == 1


async def test_generic_channel_cannot_erase_server_owned_fields(pool, users):
    """generic 客户端通道抹不掉服务端拥有的字段——该缺陷的执行性防护。

    缺陷形态：前端整体 PUT 时基线陈旧，body 里
    `meta.primaryInputMode` 是 null，服务端照单全收，把 PATCH 刚写入的
    「questions」抹回 null。下游 preparation 于是认为用户从未二选一，
    用户答完必答题仍被生成门禁挡住，且没有一层报错。

    保全必须与 CAS 同事务同行锁——锁内旧值定义上不可能陈旧。
    """
    owner, _ = users
    summary = await _create(pool, owner, "服务端拥有字段保全")

    # 专用写入器写入编排事实（等价于 PATCH /primary-input-mode）。
    seq = await dal.put_state(
        pool,
        owner.account_id,
        summary.id,
        {**STATE_V4, "meta": {"primaryInputMode": "questions"}},
        1,
        writes=frozenset({"meta.primaryInputMode"}),
    )

    # generic 通道用陈旧基线整体 PUT：meta 里该字段为 null。
    seq = await dal.put_state(
        pool,
        owner.account_id,
        summary.id,
        {**STATE_V4, "meta": {"primaryInputMode": None}},
        seq,
    )

    stored = await dal.get_lightweight_v4_snapshot(pool, owner.account_id, summary.id)
    assert stored.state.meta is not None
    assert stored.state.meta.primaryInputMode == "questions", (
        "generic 通道抹掉了服务端拥有的编排事实——保全失效"
    )


async def test_declared_writer_can_write_its_own_field(pool, users):
    """声明了 writes 的专用写入器必须写得进去，否则保全会挡住它自己。

    这是「无差别加保全」的坑：primary-input-mode 端点自身就经 put_state 写入，
    若不区分调用方意图，保全会把它要写的新值一并覆盖掉。
    """
    owner, _ = users
    summary = await _create(pool, owner, "专用写入器可写")

    seq = await dal.put_state(
        pool,
        owner.account_id,
        summary.id,
        {**STATE_V4, "meta": {"primaryInputMode": "questions"}},
        1,
        writes=frozenset({"meta.primaryInputMode"}),
    )
    # 同一写入器可以改写自己的字段（用户切换填报方式）。
    await dal.put_state(
        pool,
        owner.account_id,
        summary.id,
        {**STATE_V4, "meta": {"primaryInputMode": "materials"}},
        seq,
        writes=frozenset({"meta.primaryInputMode"}),
    )

    stored = await dal.get_lightweight_v4_snapshot(pool, owner.account_id, summary.id)
    assert stored.state.meta is not None
    assert stored.state.meta.primaryInputMode == "materials"


async def test_put_state_rejects_undeclared_write_target(pool, users):
    """writes 只接受已登记为服务端拥有的字段，拼错或越界立即 fail-loud。"""
    owner, _ = users
    summary = await _create(pool, owner, "写入声明校验")

    with pytest.raises(ValueError):
        await dal.put_state(
            pool,
            owner.account_id,
            summary.id,
            STATE_V4,
            1,
            writes=frozenset({"meta.primaryInputMOde"}),
        )


async def test_create_report_resolves_explicit_profile_and_rejects_unknown(pool, users):
    """`report_profile_id` selects the knowledge package; omitted → the report-type default.

    Unknown or malformed ids are request errors (422) with a stable user message, never a
    fallback to the default Profile — silently rebinding a report to another package would
    change its standards framework and language behind the user's back.
    """
    owner, _ = users
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[current_user] = lambda: AuthenticatedUser(subject=owner.subject, email=None)
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            explicit = await client.post(
                "/api/reports",
                json={"title": "显式配置", "report_profile_id": SSE_REPORT_PROFILE_ID},
            )
            assert explicit.status_code == 201
            assert explicit.json()["report_profile_id"] == SSE_REPORT_PROFILE_ID
            assert explicit.json()["contract_version"] == contract_version(SSE_PACKAGE)

            unknown = await client.post(
                "/api/reports", json={"title": "未知配置", "report_profile_id": "nonexistent@1"}
            )
            assert unknown.status_code == 422
            assert "nonexistent" not in unknown.text

            malformed = await client.post(
                "/api/reports", json={"title": "格式错误", "report_profile_id": "Not-An-Id"}
            )
            assert malformed.status_code == 422
    finally:
        app.dependency_overrides.clear()
