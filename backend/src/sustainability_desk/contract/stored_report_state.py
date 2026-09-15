# ABOUTME: 轻量版 StoredReportState 的严格持久化合同，按版本定义报告实例快照允许保存的字段。
# ABOUTME: V4 删除全局缺失策略；必填值仍由阶段化 readiness 判定，不由存储 schema 冒充业务门禁。
# ABOUTME(en): Strict persistence contract for the lightweight StoredReportState, versioned per snapshot field set.
# ABOUTME(en): V4 drops the global missing-value policy; required values stay with phased readiness, not the schema.
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sustainability_desk.contract.models import (
    AppendixPackage,
    BlockState,
    DisclosureProfile,
    Inline,
    MaterialityAssessmentInput,
    PrimaryInputMode,
    QuantitativeMetricsMeta,
    SectionDisplayTitle,
    StakeholderEngagementProfile,
)
from sustainability_desk.contract.structured_inputs import StructuredInputFreshness

STORED_REPORT_STATE_VERSION = 4


class StoredReportStateModel(BaseModel):
    """状态快照及其嵌套 DTO 的严格解析基类。"""

    model_config = ConfigDict(extra="forbid")


class StoredIntakeAnswer(StoredReportStateModel):
    """用户答案快照项：只保留实例答案，不接受题目结构。"""

    answer: str | list[str] | None = None
    supplement: str | None = None


class StoredCompanyBusinessSummary(StoredReportStateModel):
    """公司业务摘要快照项：派生值与其来源指纹同体保存。

    指纹取自压缩来源 `company_profile`；来源变化即摘要过期，须重算。
    值与指纹分开保存会让两者可能不一致，故合为一项。
    """

    text: str = Field(min_length=1)
    sourceFingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class StoredGeneratedBlock(StoredReportStateModel):
    """生成段落快照项：仅允许正文与生命周期状态。"""

    content: list[Inline] | None = None
    state: BlockState | None = None


class StoredImageBlock(StoredReportStateModel):
    """素材图片承载位快照项：仅保存按序放置的资产引用，题注与替代文本归资产 owner。"""

    layoutAssetIds: list[UUID] = Field(
        default_factory=list,
        json_schema_extra={"default": []},
    )
    state: Literal["ready"] = "ready"


class StoredTableCell(StoredReportStateModel):
    """表格单元格快照：保留用户值，不接受 Plate 文本骨架或列合同。"""

    type: Literal["td", "th"] = "td"
    colKey: str | None = None
    value: str | list[str] | None = None
    options: list[str] | None = None
    colSpan: int = Field(default=1, ge=1)
    rowSpan: int = Field(default=1, ge=1)
    cellState: BlockState | None = None


class StoredRowOrigin(StoredReportStateModel):
    """AI 定行的可重生成事实；不包含行级生成规格。"""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
    )

    from_: Literal["ai", "user"] = Field(default="ai", alias="from")
    theme: str | None = None
    category: str | None = None
    driver_hint: str | None = None


class StoredTableRow(StoredReportStateModel):
    """表格用户行快照：结构、generation 与 appears_when 均由运行时模板拥有。"""

    type: Literal["tr"] = "tr"
    headerRow: bool = False
    state: BlockState | None = None
    origin: StoredRowOrigin | None = None
    children: list[StoredTableCell] = Field(
        default_factory=list,
        json_schema_extra={"default": []},
    )


class StoredTableBlock(StoredReportStateModel):
    """表格实例快照项：表头和列合同仍由运行时模板提供。

    ``state="omitted"`` 与空行共同表示本轮没有足以形成数据行的用户资料；
    该处置是报告状态的一部分，不能由导出器临时猜测。
    """

    children: list[StoredTableRow] = Field(
        default_factory=list,
        json_schema_extra={"default": []},
    )
    state: BlockState | None = None


class StoredReportMetaV4(StoredReportStateModel):
    """V4 报告级状态；缺失处置由输入义务与 Block 合同拥有。"""

    quantitativeMetrics: QuantitativeMetricsMeta = Field(
        default_factory=QuantitativeMetricsMeta
    )
    materialityStrategy: Literal["complete_coverage"] | None = None
    # 报告级填报方式二选一；None = 用户尚未选择。只驱动分步流编排与义务归属，
    # 不改写任何已填输入（两条证据轨在生成侧本就允许任一为空）。
    primaryInputMode: PrimaryInputMode | None = None


#: 服务端拥有的字段：只由专用写入器改写，generic 客户端通道只能原样往返。
#:
#: 这是所有权的**唯一声明处**——`put_state` 的锁内保全由它派生，不再在函数体里
#: 逐个枚举。默认方向是「受保护」：契约新增报告级字段时若未登记为前端拥有，
#: generic 通道就抹不掉它。若改为白名单枚举、新增字段默认不受保护，
#: 新提升为报告级事实的字段（如 `meta.primaryInputMode`）一旦漏配，
#: 客户端整体 PUT 就会把它写回 null，用户答完必答题仍被生成门禁挡住。
#:
#: 顶层字段用字段名；`meta` 的子字段用 `meta.` 前缀。
SERVER_OWNED_STATE_FIELDS: frozenset[str] = frozenset(
    {
        "assessmentInput",
        "structuredInputFreshness",
        # 派生值，由生成编排写入并自带来源指纹；用户没有「清空业务摘要」这个动作。
        "companyBusinessSummary",
        "meta.materialityStrategy",
        "meta.quantitativeMetrics",
        # 编排事实，只由 PATCH /primary-input-mode 写；None = 尚未选择，
        # 产品上没有「取消填报方式」这个动作，因此保全不损失任何功能。
        "meta.primaryInputMode",
    }
)


class StoredReportStateV4(StoredReportStateModel):
    """V4 严格状态边界；不接受旧缺失策略，未完成输入交由 readiness 处理。"""

    version: Literal[4]
    fields: dict[str, str | int | float | None] = Field(
        default_factory=dict,
        json_schema_extra={"default": {}},
    )
    intakeItems: dict[str, StoredIntakeAnswer] = Field(
        default_factory=dict,
        json_schema_extra={"default": {}},
    )
    assessmentInput: MaterialityAssessmentInput | None = None
    disclosureProfile: DisclosureProfile | None = None
    appendixPackage: AppendixPackage | None = None
    meta: StoredReportMetaV4 | None = None
    stakeholderEngagement: StakeholderEngagementProfile | None = None
    sectionTitles: dict[str, SectionDisplayTitle] = Field(
        default_factory=dict,
        json_schema_extra={"default": {}},
    )
    generatedBlocks: dict[str, StoredGeneratedBlock] = Field(
        default_factory=dict,
        json_schema_extra={"default": {}},
    )
    tableBlocks: dict[str, StoredTableBlock] = Field(
        default_factory=dict,
        json_schema_extra={"default": {}},
    )
    imageBlocks: dict[str, StoredImageBlock] = Field(
        default_factory=dict,
        json_schema_extra={"default": {}},
    )
    structuredInputFreshness: StructuredInputFreshness = Field(
        default_factory=StructuredInputFreshness
    )
    # 派生值不进 fields（fields 只承载用户输入）；派生态与其来源指纹在此单独持有。
    companyBusinessSummary: StoredCompanyBusinessSummary | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_retired_version(cls, value: object) -> object:
        """旧本地报告不做迁移或双读，明确要求用户重建。"""

        if (
            isinstance(value, dict)
            and "version" in value
            and value.get("version") != STORED_REPORT_STATE_VERSION
        ):
            raise ValueError("状态版本已废弃，请重建报告")
        return value


def empty_stored_report_state() -> StoredReportStateV4:
    """构造新报告的唯一空 V4 状态。"""

    return StoredReportStateV4(version=STORED_REPORT_STATE_VERSION)
