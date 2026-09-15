# ABOUTME: 报告跨资料、受控输入、正文与产物的统一谱系合同，供持久化和投影共同消费。
# ABOUTME: 谱系只保存稳定引用、版本和用户可解释的判定，不复制资料正文、Prompt、模型思维或私有路径。
# ABOUTME(en): Unified lineage contract across a report's materials, controlled inputs, prose and artifacts.
# ABOUTME(en): Stores only stable references, versions and explainable verdicts; no material prose, prompt or path.
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field

from sustainability_desk.material.intake.models import SourceLocator


# 值里的 simplified 是公开契约字面量（流经 schema_export 到前端，或已落库）；
# 内部实现已统一为 lightweight，此处待下次契约版本变更时一并收敛（docs/todos.md）。
LineageAdapterId = Literal["simplified-report-input@2"]
LineageEdgeKind = Literal[
    "source_fragment_to_input_resolution",
    "input_resolution_to_report_input",
    "source_fragment_to_fact",
    "fact_to_report_input",
    "report_input_to_block",
    "evidence_fact_to_requirement",
    "requirement_to_gap",
    "blueprint_to_block",
    "block_to_claim",
    "block_to_artifact",
]
LineageStatus = Literal["active", "stale", "superseded"]
LineageDecision = Literal[
    "candidate",
    "confirmed",
    "auto_applied",
    "held_low_confidence",
    "blocked_conflict",
    "invalid",
    "not_applicable",
]


def stable_lineage_edge_id(*parts: object) -> UUID:
    """从不可变业务身份推导可重放的谱系边 ID，避免重试复制同一关系。"""

    if not parts or any(not str(part) for part in parts):
        raise ValueError("谱系边稳定身份不得为空")
    return uuid5(
        NAMESPACE_URL,
        "sustainability_desk.report_lineage.v1:" + "\x1f".join(str(part) for part in parts),
    )


class ReportLineageModel(BaseModel):
    """跨层谱系的严格、不可变传输基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportLineageEdge(ReportLineageModel):
    """一条可审计的有向关系；业务对象仍由各自领域 owner 持有。"""

    id: UUID = Field(default_factory=uuid4)
    report_id: UUID
    adapter_id: LineageAdapterId
    edge_kind: LineageEdgeKind
    from_kind: str = Field(min_length=1, max_length=100)
    from_ref: str = Field(min_length=1, max_length=300)
    to_kind: str = Field(min_length=1, max_length=100)
    to_ref: str = Field(min_length=1, max_length=300)
    decision: LineageDecision
    reason_code: str = Field(min_length=1, max_length=100)
    explanation: str = Field(min_length=1, max_length=1_000)
    source_id: UUID | None = None
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    fragment_id: str | None = Field(default=None, min_length=1, max_length=200)
    fragment_locator: SourceLocator | None = None
    run_id: UUID | None = None
    report_state_seq: int | None = Field(default=None, ge=1)
    input_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    context_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: LineageStatus = "active"


class ReportLineageEdgeProjection(ReportLineageModel):
    """面向同一报告授权用户的受限谱系边，不暴露内部 trace 或私有对象定位。"""

    id: UUID
    edge_kind: LineageEdgeKind
    from_kind: str
    from_ref: str
    to_kind: str
    to_ref: str
    decision: LineageDecision
    reason_code: str
    explanation: str
    status: LineageStatus
    source_id: UUID | None = None
    source_name: str | None = Field(default=None, max_length=500)
    fragment_id: str | None = None
    fragment_locator: SourceLocator | None = None
    report_state_seq: int | None = Field(default=None, ge=1)
    created_at: datetime


class ReportLineageBlockProjection(ReportLineageModel):
    """单个报告 Block 的用户可解释摘要；详细边仍由统一列表拥有。"""

    block_id: str = Field(min_length=1, max_length=300)
    status: Literal["linked", "no_user_provided_content", "changed_after_generation", "not_generated"]
    source_count: int = Field(ge=0)
    input_count: int = Field(ge=0)
    generated_report_state_seq: int | None = Field(default=None, ge=1)


class ReportLineageProjection(ReportLineageModel):
    """报告全过程的唯一公共谱系投影；阶段时间线继续由各领域进度 owner 派生。"""

    report_id: UUID
    report_state_seq: int = Field(ge=1)
    edges: tuple[ReportLineageEdgeProjection, ...]
    blocks: tuple[ReportLineageBlockProjection, ...]
