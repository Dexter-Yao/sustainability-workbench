# ABOUTME: 报告与状态快照的数据访问——所有 SQL 以 account_id 限定，service role 也必须通过应用层所有权断言。
# ABOUTME: 状态写入走 state_seq 乐观锁；建报在 Account 行锁内断言活跃报告上限并写入初始审计事件。
# ABOUTME(en): Data access for reports and state snapshots — every SQL is scoped by account_id, and even the
# ABOUTME(en): service role passes application-level ownership assertions. State writes use a state_seq lock.
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import asyncpg

from sustainability_desk.accounts.report_execution_scope import execution_scope_kind_for_profile
from sustainability_desk.contract.stored_report_state import (
    SERVER_OWNED_STATE_FIELDS,
    StoredReportMetaV4,
    StoredReportStateV4,
)

@dataclass(frozen=True)
class ReportSummary:
    id: UUID
    title: str
    report_type: str
    report_profile_id: str
    data_classification: Literal["synthetic", "customer"]
    created_under_profile_id: str
    contract_version: str
    status: str
    created_at: str
    updated_at: str
    # 列表显示名派生源：state.fields 中的公司注册名（创建路径与旧行读不到时为 None）。
    company_registered_name: str | None = None


@dataclass(frozen=True)
class ReportState:
    report_id: UUID
    state: dict[str, Any]
    state_seq: int
    contract_version: str


@dataclass(frozen=True)
class LockedLightweightReportState:
    """结构化输入事务内锁定的轻量版 V4 状态与最小 Report 元数据。"""

    report_id: UUID
    title: str
    report_profile_id: str
    state: StoredReportStateV4
    state_seq: int
    contract_version: str


class StateConflictError(Exception):
    """state_seq 不匹配：调用方持有的快照已过期。"""

    def __init__(
        self,
        report_id: str,
        *,
        current: LockedLightweightReportState | None = None,
    ) -> None:
        self.current = current
        super().__init__(report_id)


class ReportNotFoundError(Exception):
    """报告不存在或不属于当前 Account。"""


class ReportProfileMismatchError(Exception):
    """结构化输入端点只接受轻量版 V4 Report。"""


class ActiveReportLimitError(Exception):
    """Account 的活跃报告数量已达 Profile 上限。

    account_id 是排查用的上下文，不是给用户看的文案：若被 `str(exc)` 原样透传到
    创建端点的 403 detail，界面会把账户内部 id 当成错误提示显示出来
    （用户看到一串裸 UUID，既无可行动信息又泄露内部标识）。
    面向用户的说明由 API 边界按范围名额生成，本层只携带事实。
    """

    def __init__(self, account_id: str, *, limit: int, scope: str) -> None:
        super().__init__(f"Account {account_id} 的 {scope} 活跃报告已达上限 {limit}")
        self.account_id = account_id
        self.limit = limit
        self.scope = scope


def _stored_state_dict(state: dict[str, Any]) -> dict[str, Any]:
    """在数据库读写边界解析并归一化 V4 状态。"""

    return StoredReportStateV4.model_validate(state).model_dump(
        by_alias=True,
        mode="json",
    )


def _initial_state_dict(
    report_type: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    """按 Report Profile 严格解析创建时状态。"""

    if report_type == "lightweight":
        return _stored_state_dict(state)
    raise ValueError(f"未知报告类型：{report_type}")


def _summary(row: asyncpg.Record) -> ReportSummary:
    data = dict(row)
    company = data.get("company_registered_name")
    return ReportSummary(
        id=row["id"],
        title=row["title"],
        report_type=row["report_type"],
        report_profile_id=row["report_profile_id"],
        data_classification=row["data_classification"],
        created_under_profile_id=row["created_under_profile_id"],
        contract_version=row["contract_version"],
        status=row["status"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
        company_registered_name=str(company).strip() or None if company is not None else None,
    )


async def assert_report_owner(pool: asyncpg.Pool, account_id: UUID, report_id: UUID) -> None:
    owned = await pool.fetchval(
        "select 1 from reports where id = $1 and account_id = $2 and status = 'active'",
        report_id, account_id,
    )
    if owned is None:
        raise ReportNotFoundError(str(report_id))


async def list_reports(pool: asyncpg.Pool, account_id: UUID) -> list[ReportSummary]:
    rows = await pool.fetch(
        """
        select r.id, r.title, r.report_type, r.report_profile_id, r.data_classification,
               r.created_under_profile_id, r.contract_version, r.status, r.created_at, r.updated_at,
               rs.state -> 'fields' ->> 'company_registered_name' as company_registered_name
        from reports r
        left join report_states rs on rs.report_id = r.id
        where r.account_id = $1
        order by (r.status = 'active') desc, r.updated_at desc
        """,
        account_id,
    )
    return [_summary(r) for r in rows]


async def get_report_summary(
    pool: asyncpg.Pool, account_id: UUID, report_id: UUID
) -> ReportSummary:
    """读取一份活动报告的产品元数据；生成与导出据此保留显式 trial 升级边界。"""
    row = await pool.fetchrow(
        """
        select id, title, report_type, report_profile_id, data_classification, created_under_profile_id,
               contract_version, status, created_at, updated_at
        from reports where id = $1 and account_id = $2 and status = 'active'
        """,
        report_id,
        account_id,
    )
    if row is None:
        raise ReportNotFoundError(str(report_id))
    return _summary(row)


async def create_report(
    pool: asyncpg.Pool,
    account_id: UUID,
    title: str,
    report_type: str,
    report_profile_id: str,
    data_classification: Literal["synthetic", "customer"],
    contract_version: str,
    initial_state: dict[str, Any],
    active_scope_limit: int,
    profile_id: str,
) -> ReportSummary:
    stored_state = _initial_state_dict(report_type, initial_state)
    async with pool.acquire() as conn, conn.transaction():
        exists = await conn.fetchval("select 1 from accounts where id = $1 for update", account_id)
        if exists is None:
            raise ReportNotFoundError(str(account_id))
        active_profiles = await conn.fetch(
            "select created_under_profile_id from reports where account_id = $1 and status = 'active'",
            account_id,
        )
        creation_scope = execution_scope_kind_for_profile(profile_id)
        active_count = sum(
            execution_scope_kind_for_profile(row["created_under_profile_id"])
            == creation_scope
            for row in active_profiles
        )
        if active_count >= active_scope_limit:
            raise ActiveReportLimitError(
                str(account_id), limit=active_scope_limit, scope=creation_scope
            )
        row = await conn.fetchrow(
            """
            insert into reports (
              account_id, title, report_type, report_profile_id, data_classification,
              created_under_profile_id, contract_version
            ) values ($1, $2, $3, $4, $5, $6, $7)
            returning id, title, report_type, report_profile_id, data_classification, created_under_profile_id,
                      contract_version, status, created_at, updated_at
            """,
            account_id, title, report_type, report_profile_id, data_classification, profile_id, contract_version,
        )
        await conn.execute(
            "insert into report_states (report_id, state) values ($1, $2)",
            row["id"], stored_state,
        )
        await conn.execute("update accounts set last_active_at = now() where id = $1", account_id)
        await conn.execute(
            """
            insert into report_events (report_id, actor, event_type, payload)
            values ($1, 'user', 'report_created', $2)
            """,
            row["id"],
            {"contractVersion": contract_version, "profileId": profile_id,
             "reportType": report_type, "reportProfileId": report_profile_id,
             "dataClassification": data_classification},
        )
    return _summary(row)


async def archive_report(
    pool: asyncpg.Pool, account_id: UUID, report_id: UUID
) -> tuple[str, ...]:
    """删除报告并交出该报告上传文件的对象路径，供调用方清除存储。

    报告行本身保留为 archived：它只占极小空间，而 report_events 的生成、导出与删除
    记录经 `report_id` 外键 CASCADE 绑在它上面，硬删会一并抹掉合规所需的审计留痕
    （legal-compliance.md：报告审计按提供服务、合同和争议处理所需期限保存）。
    真正需要回收的是用户上传的文件——它们既占存储又含用户原始资料，因此这里返回
    对象路径，由调用方在存储侧真删；不返回则文件会随报告一起被无限期留存。
    """
    async with pool.acquire() as conn, conn.transaction():
        result = await conn.execute(
            "update reports set status = 'archived', updated_at = now() where id = $1 and account_id = $2 and status = 'active'",
            report_id, account_id,
        )
        if result != "UPDATE 1":
            raise ReportNotFoundError(str(report_id))
        purgeable = await conn.fetch(
            """
            select s.object_path
            from material_sources s
            join material_workspaces w on w.id = s.workspace_id
            where w.report_id = $1 and w.account_id = $2 and s.object_path <> ''
            """,
            report_id,
            account_id,
        )
        await conn.execute(
            "insert into report_events (report_id, actor, event_type) values ($1, 'user', 'report_archived')",
            report_id,
        )
    return tuple(row["object_path"] for row in purgeable)


async def get_state(
    pool: asyncpg.Pool | asyncpg.Connection,
    account_id: UUID,
    report_id: UUID,
) -> ReportState:
    row = await pool.fetchrow(
        """
        select s.report_id, s.state, s.state_seq, r.contract_version
        from report_states s join reports r on r.id = s.report_id
        where s.report_id = $1 and r.account_id = $2 and r.status = 'active'
        """,
        report_id, account_id,
    )
    if row is None:
        raise ReportNotFoundError(str(report_id))
    return ReportState(
        report_id=row["report_id"], state=_stored_state_dict(row["state"]),
        state_seq=row["state_seq"], contract_version=row["contract_version"],
    )


async def lock_lightweight_v4_state(
    conn: asyncpg.Connection,
    account_id: UUID,
    report_id: UUID,
    expected_state_seq: int,
) -> LockedLightweightReportState:
    """锁定权威状态行并校验 Account、Profile、V4 与调用方序号。"""

    row = await conn.fetchrow(
        """
        select s.report_id, s.state, s.state_seq, r.title, r.report_type,
               r.report_profile_id, r.contract_version
        from report_states s
        join reports r on r.id = s.report_id
        where s.report_id = $1 and r.account_id = $2 and r.status = 'active'
        for update of s
        """,
        report_id,
        account_id,
    )
    if row is None:
        raise ReportNotFoundError(str(report_id))
    if row["report_type"] != "lightweight":
        raise ReportProfileMismatchError(str(report_id))
    try:
        state = StoredReportStateV4.model_validate(row["state"])
    except ValueError as error:
        raise ReportProfileMismatchError(str(report_id)) from error
    locked = LockedLightweightReportState(
        report_id=row["report_id"],
        title=row["title"],
        report_profile_id=row["report_profile_id"],
        state=state,
        state_seq=int(row["state_seq"]),
        contract_version=row["contract_version"],
    )
    if locked.state_seq != expected_state_seq:
        raise StateConflictError(str(report_id), current=locked)
    return locked


async def get_lightweight_v4_snapshot(
    pool: asyncpg.Pool,
    account_id: UUID,
    report_id: UUID,
) -> LockedLightweightReportState:
    """读取 report-bound 结构化输入所需的同一份权威状态与报告元数据。"""

    row = await pool.fetchrow(
        """
        select s.report_id, s.state, s.state_seq, r.title, r.report_type,
               r.report_profile_id, r.contract_version
        from report_states s
        join reports r on r.id = s.report_id
        where s.report_id = $1 and r.account_id = $2 and r.status = 'active'
        """,
        report_id,
        account_id,
    )
    if row is None:
        raise ReportNotFoundError(str(report_id))
    if row["report_type"] != "lightweight":
        raise ReportProfileMismatchError(str(report_id))
    try:
        state = StoredReportStateV4.model_validate(row["state"])
    except ValueError as error:
        raise ReportProfileMismatchError(str(report_id)) from error
    return LockedLightweightReportState(
        report_id=row["report_id"],
        title=row["title"],
        report_profile_id=row["report_profile_id"],
        state=state,
        state_seq=int(row["state_seq"]),
        contract_version=row["contract_version"],
    )


async def save_locked_lightweight_v4_state(
    conn: asyncpg.Connection,
    *,
    account_id: UUID,
    locked: LockedLightweightReportState,
    state: StoredReportStateV4,
    event_type: str,
    event_payload: dict[str, Any],
) -> int:
    """在既有行锁事务内 CAS 写入 V4、失效下游并追加不含用户原值的审计事件。"""

    new_seq = await conn.fetchval(
        """
        update report_states
        set state = $1, state_seq = state_seq + 1, updated_at = now()
        where report_id = $2 and state_seq = $3
        returning state_seq
        """,
        state.model_dump(by_alias=True, mode="json"),
        locked.report_id,
        locked.state_seq,
    )
    if new_seq is None:
        raise StateConflictError(str(locked.report_id))
    await conn.execute(
        "update reports set updated_at = now() where id = $1",
        locked.report_id,
    )
    await conn.execute(
        """
        insert into report_events (report_id, actor, event_type, payload)
        values ($1, 'user', $2, $3)
        """,
        locked.report_id,
        event_type,
        {**event_payload, "stateSeq": int(new_seq)},
    )
    return int(new_seq)


def _preserve_server_owned(
    requested: StoredReportStateV4,
    locked: StoredReportStateV4,
    *,
    writes: frozenset[str],
) -> StoredReportStateV4:
    """以锁内权威值覆盖服务端拥有字段；`writes` 声明的字段除外。

    保全集合派生自 `SERVER_OWNED_STATE_FIELDS`（合同侧唯一声明处），不在此枚举：
    契约新增报告级字段时默认受保护，不必记得回到这里补一行。

    `writes` 是本次调用方**有权改写**的字段。generic 客户端通道传空集——它只能
    原样往返服务端事实；服务端专用写入器只声明自己那一个字段，从而写得进去、
    又碰不到别人的地盘。保全与 CAS 在同一事务同一行锁内，锁内旧值定义上不陈旧。
    """

    protected = SERVER_OWNED_STATE_FIELDS - writes
    meta_updates = {
        name.removeprefix("meta."): getattr(
            locked.meta or StoredReportMetaV4(), name.removeprefix("meta.")
        )
        for name in protected
        if name.startswith("meta.")
    }
    top_updates: dict[str, Any] = {
        name: getattr(locked, name) for name in protected if "." not in name
    }
    if meta_updates:
        top_updates["meta"] = (requested.meta or StoredReportMetaV4()).model_copy(
            update=meta_updates
        )
    return requested.model_copy(update=top_updates)


async def put_state(
    pool: asyncpg.Pool,
    account_id: UUID,
    report_id: UUID,
    state: dict[str, Any],
    base_seq: int,
    *,
    validate: Callable[[StoredReportStateV4], None] | None = None,
    transform: Callable[[StoredReportStateV4], StoredReportStateV4] | None = None,
    writes: frozenset[str] = frozenset(),
) -> int:
    """写入 V4 状态；`validate` 在锁内、权威字段覆盖之后作用于实际落库的状态。

    `transform` 是写入边界的服务端派生对齐（如评分收窄到当前适用范围）：同样在
    锁内、权威覆盖之后执行——作用于请求体会被 `_preserve_server_owned` 静默丢弃
    （否则入口收窄形同虚设，用户改科技伦理为「否」的合法
    编辑会被锁内范围校验 403 死锁）。
    `writes` 声明本次调用方有权改写哪些服务端拥有字段（见 `_preserve_server_owned`）。
    默认空集即 generic 客户端通道语义：服务端事实只能原样往返。
    """
    requested_state = StoredReportStateV4.model_validate(state)
    unknown = writes - SERVER_OWNED_STATE_FIELDS
    if unknown:
        raise ValueError(f"未登记为服务端拥有的字段不必声明写入：{sorted(unknown)}")
    async with pool.acquire() as conn, conn.transaction():
        locked = await lock_lightweight_v4_state(
            conn,
            account_id,
            report_id,
            base_seq,
        )
        next_state = _preserve_server_owned(
            requested_state, locked.state, writes=writes
        )
        if transform is not None:
            next_state = transform(next_state)
        # 范围校验必须作用于**实际落库的** next_state：服务端拥有字段刚被锁内权威值覆盖，
        # 校验请求体会与落库对象不是同一份——既可能因一个反正会被丢弃的字段拒绝合法写入，
        # 也可能放行锁内已有的越界事实。调用方传入校验器，在锁内、覆盖之后执行。
        if validate is not None:
            validate(next_state)
        return await save_locked_lightweight_v4_state(
            conn,
            account_id=account_id,
            locked=locked,
            state=next_state,
            event_type="state_saved",
            event_payload={},
        )
