# ABOUTME: 校验 Mapping Agent 对既有 FileMaterial 的 block 采用决定。
# ABOUTME: 本模块不创建、改写或推断文件事实；文件资料内容只由 File Agent 拥有。
# ABOUTME(en): Validates the Mapping Agent's block adoption decisions over existing FileMaterial.
# ABOUTME(en): It creates, rewrites or infers no file facts; file material content is owned solely by the File Agent.
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sustainability_desk.material.intake.file_agent_contract import FileDossier, FileMaterial
from sustainability_desk.material.mapping.scope import MappingScopeDefinition

type BlockMaterialDisposition = Literal[
    "supported", "partially_supported", "context_only", "needs_attention", "not_applicable"
]


class MappingContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BlockMaterialDecisionDraft(MappingContractModel):
    """模型对当前 scope 内一个 block 的有序资料采用候选。"""

    block_id: str = Field(min_length=1)
    disposition: BlockMaterialDisposition
    material_ids: tuple[UUID, ...] = ()
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_shape(self) -> "BlockMaterialDecisionDraft":
        if len(self.material_ids) != len(set(self.material_ids)):
            raise ValueError("同一 Block 不得重复采用同一资料内容")
        if self.disposition in {"supported", "partially_supported"} and not self.material_ids:
            raise ValueError("有资料支持的 Block 必须采用至少一条资料内容")
        if self.disposition in {
            "context_only",
            "needs_attention",
            "not_applicable",
        } and self.material_ids:
            raise ValueError(f"{self.disposition} 的 Block 不得采用资料内容")
        return self


class BlockMaterialDecision(MappingContractModel):
    """经 Harness 校验后，当前 block 的正式资料采用与顺序事实。"""

    contract: Literal["sustainability_desk.block_material_decision.v1"] = "sustainability_desk.block_material_decision.v1"
    scope_id: str
    block_id: str
    disposition: BlockMaterialDisposition
    material_ids: tuple[UUID, ...]
    reason: str


class ValidatedMappingResult(MappingContractModel):
    """一次 scope Mapping 的完整、可持久化结果。"""

    scope_id: str
    block_decisions: tuple[BlockMaterialDecision, ...]


class MappingDecisionError(ValueError):
    """Mapping 输出违反冻结资料、scope 或完整覆盖边界。"""


def materials_for_scope(
    dossiers: tuple[FileDossier, ...], scope_id: str
) -> tuple[FileMaterial, ...]:
    """从冻结 FileDossier 投影当前 scope 可用资料，保持文件内原有顺序。"""

    if any(dossier.contract != "sustainability_desk.file_dossier.v7" for dossier in dossiers):
        raise MappingDecisionError("新 Mapping 只接受当前 v7 FileDossier")
    materials = tuple(
        material
        for dossier in dossiers
        if dossier.candidate_for_mapping
        for material in dossier.materials
        if scope_id in material.applicable_scope_ids
    )
    material_ids = [material.material_id for material in materials]
    if len(material_ids) != len(set(material_ids)):
        raise MappingDecisionError("当前 scope 存在重复资料内容身份")
    return materials


def validate_mapping_decisions(
    *,
    scope: MappingScopeDefinition,
    dossiers: tuple[FileDossier, ...],
    block_decisions: tuple[BlockMaterialDecisionDraft, ...],
) -> ValidatedMappingResult:
    """将模型选择限制到当前 frozen scope 的既有 FileMaterial。"""

    scope_block_ids = {task.block_id for task in scope.block_tasks}
    decision_block_ids = [item.block_id for item in block_decisions]
    if len(decision_block_ids) != len(set(decision_block_ids)) or set(decision_block_ids) != scope_block_ids:
        raise MappingDecisionError("Mapping 输出必须完整覆盖 scope 内每个 Block 且不得包含额外 Block")
    allowed_material_ids = {
        material.material_id for material in materials_for_scope(dossiers, scope.scope_id)
    }
    decisions: list[BlockMaterialDecision] = []
    for draft in block_decisions:
        unknown = set(draft.material_ids) - allowed_material_ids
        if unknown:
            raise MappingDecisionError("Block 采用了当前 scope 外或未知的资料内容")
        decisions.append(
            BlockMaterialDecision(
                scope_id=scope.scope_id,
                block_id=draft.block_id,
                disposition=draft.disposition,
                material_ids=draft.material_ids,
                reason=draft.reason,
            )
        )
    return ValidatedMappingResult(scope_id=scope.scope_id, block_decisions=tuple(decisions))
