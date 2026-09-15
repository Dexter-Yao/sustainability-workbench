# ABOUTME: 轻量版报告级显式生成命令、运行进度与交付物的公共合同。
# ABOUTME: 公共投影只含用户可理解事件和下载句柄，不暴露 Prompt、成本、内部路径或 debug。
# ABOUTME(en): Public contract for lightweight report-level generation commands, run progress and deliverables.
# ABOUTME(en): The public projection carries only user-facing events and download handles; no prompt, path or debug.
from __future__ import annotations

from datetime import datetime
import re
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

type ReportGenerationStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "superseded",
]
type ReportArtifactKind = Literal[
    "word",
    "review",
]

# The formal and review deliverables share one layout and differ only by the filename infix,
# which the package's format profile owns (labels.delivery_filename_variants).
_DELIVERY_FILENAME_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")


def delivery_docx_filename(
    *,
    company_registered_name: str,
    variant: str,
    generated_at: datetime,
) -> str:
    """从报告主体、交付类型和冻结生成时点派生唯一的客户 Word 文件名。

    文件名是对外 artifact 投影，不是 Storage 路径或报告正文事实。日期统一按
    中国时区冻结到天；主体名称仅清除跨平台文件系统禁止字符，不改写其余名称。
    """

    subject = _DELIVERY_FILENAME_FORBIDDEN.sub(" ", company_registered_name)
    subject = " ".join(subject.split()).strip(". ")
    if not subject:
        raise ValueError("公司注册名称无法形成安全的交付文件名")
    date = generated_at.astimezone(_CHINA_TIMEZONE).date().isoformat()
    return f"{subject}_{variant}_{date}.docx"


class ReportGenerationModel(BaseModel):
    """轻量版报告级生成公共合同的严格不可变基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CreateReportGenerationRequest(ReportGenerationModel):
    """用户显式发起一次生成或更新；幂等键由客户端在一次意图内保持稳定。

    `model_id` 省略即用服务端当前默认模型；给出时必须是**当前环境可选**的已注册 id
    （凭据齐备），由服务端裁定，客户端不自行解释可用性。
    """

    idempotency_key: UUID
    base_report_state_seq: int = Field(ge=1)
    model_id: str | None = Field(default=None, min_length=1, max_length=64)


class ReportGenerationEvent(ReportGenerationModel):
    """同一运行记录派生的用户友好增量说明。"""

    sequence: int = Field(ge=1)
    event_type: Literal[
        "queued",
        "started",
        "block_started",
        "block_completed",
        "report_saved",
        "artifacts_ready",
        "export_blocked",
        "failed",
        "superseded",
    ]
    message: str = Field(min_length=1, max_length=1_000)
    current_object: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
    )
    action_required: bool = False
    occurred_at: datetime


class ReportArtifactProjection(ReportGenerationModel):
    """客户可下载的交付物句柄；内部审计包不会对普通客户开放下载。"""

    artifact_id: UUID
    kind: ReportArtifactKind
    filename: str = Field(min_length=1, max_length=500)
    media_type: str = Field(min_length=1, max_length=200)
    download_href: str = Field(pattern=r"^/api/reports/")


class ReportGenerationProjection(ReportGenerationModel):
    """创建响应、轮询进度和交付页共用的报告级运行投影。"""

    contract: Literal["sustainability_desk.report_generation.v1"] = (
        "sustainability_desk.report_generation.v1"
    )
    run_id: UUID
    report_id: UUID
    status: ReportGenerationStatus
    base_report_state_seq: int = Field(ge=1)
    result_report_state_seq: int | None = Field(default=None, ge=2)
    completed_block_count: int = Field(ge=0)
    total_block_count: int = Field(ge=1)
    summary: str = Field(min_length=1, max_length=1_000)
    started_at: datetime | None = None
    events: tuple[ReportGenerationEvent, ...]
    artifacts: tuple[ReportArtifactProjection, ...] = ()
    workbench_enabled: bool
