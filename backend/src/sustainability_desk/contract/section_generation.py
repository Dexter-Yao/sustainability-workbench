# ABOUTME: 整节生成 API 的严格输出合同，定义 Report 原子写回后的唯一公共投影。
# ABOUTME: 前端类型与运行时解析 schema 均由本模型生成，不得手写平行响应形状。
# ABOUTME(en): Strict output contract for the whole-section generation API after an atomic Report write-back.
# ABOUTME(en): Frontend types and the runtime parse schema derive from this model; parallel response shapes are banned.
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sustainability_desk.contract.models import GsTableRow, SectionDisplayTitle


class SectionGenerationContractModel(BaseModel):
    """整节生成响应及嵌套 DTO 的严格解析基类。"""

    model_config = ConfigDict(extra="forbid")


class ParagraphGenerationResult(SectionGenerationContractModel):
    """从 Report 正文状态投影的一项段落结果。"""

    block_id: str
    text: str


class TableGenerationResult(SectionGenerationContractModel):
    """从 Report 表格状态投影的一项表格结果。"""

    block_id: str
    rows: list[GsTableRow]


class SectionRewriteAllowance(SectionGenerationContractModel):
    """整节生成完成后的服务端权威重写额度。"""

    quota: int = Field(ge=0)
    used: int = Field(ge=0)
    reserved: int = Field(ge=0)
    remaining: int = Field(ge=0)


class SectionGenerationResponse(SectionGenerationContractModel):
    """整节生成或幂等重放的完整公共响应。"""

    batch_id: UUID
    mode: Literal["initial", "regeneration"]
    replayed: bool
    state_seq: int = Field(ge=1)
    results: list[ParagraphGenerationResult | TableGenerationResult]
    section_titles: dict[str, SectionDisplayTitle]
    input_fingerprint: str = Field(min_length=64, max_length=64)
    freshness: Literal["fresh"]
    company_business_summary: str | None
    allowance: SectionRewriteAllowance
