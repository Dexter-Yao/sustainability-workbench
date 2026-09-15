# ABOUTME: 冻结报告当前可用的语义资料集合，并计算资料与 Mapping 结果的精确失效范围。
# ABOUTME: 指纹只表达领域输入与事实投影变化，不把运行身份或模型措辞原因当作正文失效依据。
# ABOUTME(en): Freezes the semantic material set a report can use and computes exact invalidation scope.
# ABOUTME(en): Fingerprints express domain input and fact changes only, never run identity or model wording.
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sustainability_desk.material.intake.file_agent_contract import FileDossier
from sustainability_desk.material.mapping.decisions import ValidatedMappingResult
from sustainability_desk.material.mapping.scope import MappingScopeDefinition

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class SnapshotContractModel(BaseModel):
    """资料 snapshot 与失效计划的严格不可变基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class MaterialSetMember(SnapshotContractModel):
    """一个 active semantic binding 在 snapshot 中冻结的领域身份。"""

    binding_id: UUID
    dossier_id: UUID
    source_id: UUID
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    declaration_revision: int = Field(ge=1)
    dossier_fingerprint: str = Field(pattern=SHA256_PATTERN)


class MappingPlanScope(SnapshotContractModel):
    """本次快照中确实需要 Mapping 的一个编译 scope。"""

    scope_id: str = Field(min_length=1)
    dossier_ids: tuple[UUID, ...] = Field(min_length=1)
    block_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_unique_members(self) -> "MappingPlanScope":
        if len(self.dossier_ids) != len(set(self.dossier_ids)):
            raise ValueError("Mapping plan scope 不得重复 dossier")
        if len(self.block_ids) != len(set(self.block_ids)):
            raise ValueError("Mapping plan scope 不得重复 Block")
        return self


class FrozenMappingPlan(SnapshotContractModel):
    """由 Dossier 路由与编译 scope 派生的冻结投影，不拥有独立资料事实。"""

    candidate_dossier_ids: tuple[UUID, ...] = ()
    scopes: tuple[MappingPlanScope, ...] = ()

    @model_validator(mode="after")
    def _validate_plan(self) -> "FrozenMappingPlan":
        if len(self.candidate_dossier_ids) != len(set(self.candidate_dossier_ids)):
            raise ValueError("Mapping plan 不得重复 candidate dossier")
        scope_ids = [scope.scope_id for scope in self.scopes]
        if len(scope_ids) != len(set(scope_ids)):
            raise ValueError("Mapping plan 不得重复 scope")
        candidates = set(self.candidate_dossier_ids)
        for scope in self.scopes:
            if not set(scope.dossier_ids).issubset(candidates):
                raise ValueError("Mapping plan scope 引用了非 candidate dossier")
        return self

    @property
    def scope_ids(self) -> tuple[str, ...]:
        return tuple(scope.scope_id for scope in self.scopes)

    @property
    def block_ids(self) -> tuple[str, ...]:
        return tuple(
            block_id
            for scope in self.scopes
            for block_id in scope.block_ids
        )


class MaterialSetSnapshot(SnapshotContractModel):
    """一次 Mapping 与报告生成共同引用的不可变语义资料集合。"""

    contract: Literal[
        "sustainability_desk.material_set_snapshot.v1",
        "sustainability_desk.material_set_snapshot.v2",
    ] = "sustainability_desk.material_set_snapshot.v2"
    snapshot_id: UUID = Field(default_factory=uuid4)
    report_id: UUID
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    members: tuple[MaterialSetMember, ...]
    mapping_plan: FrozenMappingPlan = Field(default_factory=FrozenMappingPlan)
    input_fingerprint: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_identity_and_fingerprint(self) -> "MaterialSetSnapshot":
        binding_ids = [member.binding_id for member in self.members]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("MaterialSetSnapshot 不得重复包含同一 Binding")
        expected = (
            _legacy_material_set_fingerprint(self.report_id, self.members)
            if self.contract == "sustainability_desk.material_set_snapshot.v1"
            else material_set_fingerprint(
                self.report_id,
                self.members,
                self.mapping_plan,
            )
        )
        if self.input_fingerprint != expected:
            raise ValueError("MaterialSetSnapshot 输入指纹无效")
        return self


class MappingScopeLineage(SnapshotContractModel):
    """上一次有效 Mapping Scope 实际采用过的来源集合。"""

    scope_id: str
    adopted_source_ids: tuple[UUID, ...]


class IncrementalMappingPlan(SnapshotContractModel):
    """资料集合变化对章节级 Mapping Scope 的最小重算计划。"""

    changed_binding_ids: tuple[UUID, ...]
    removed_source_ids: tuple[UUID, ...]
    rerun_scope_ids: tuple[str, ...]
    reusable_scope_ids: tuple[str, ...]


class BlockRefreshPlan(SnapshotContractModel):
    """新旧 Mapping 结果之间需要重新生成或可复用的 Block。"""

    regenerate_block_ids: tuple[str, ...]
    reusable_block_ids: tuple[str, ...]


def member_from_dossier(
    *,
    binding_id: UUID,
    dossier: FileDossier,
) -> MaterialSetMember:
    """从经校验 FileDossier 构造 snapshot 成员，不复制 dossier 正文。"""

    revision = dossier.source_revision
    return MaterialSetMember(
        binding_id=binding_id,
        dossier_id=dossier.dossier_id,
        source_id=revision.source_id,
        source_sha256=revision.source_sha256,
        declaration_revision=revision.declaration_revision,
        dossier_fingerprint=dossier.dossier_fingerprint,
    )


def material_set_fingerprint(
    report_id: UUID,
    members: tuple[MaterialSetMember, ...],
    mapping_plan: FrozenMappingPlan | None = None,
) -> str:
    """生成与成员输入顺序无关的资料集合指纹。"""

    mapping_plan = mapping_plan or FrozenMappingPlan()

    payload = {
        "reportId": str(report_id),
        "members": [
            member.model_dump(mode="json")
            for member in sorted(members, key=lambda item: str(item.binding_id))
        ],
        "mappingPlan": mapping_plan.model_dump(mode="json"),
    }
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _legacy_material_set_fingerprint(
    report_id: UUID,
    members: tuple[MaterialSetMember, ...],
) -> str:
    """校验已持久化的 V1 snapshot；新写入一律使用带 mapping plan 的 V2。"""

    payload = {
        "reportId": str(report_id),
        "members": [
            member.model_dump(mode="json")
            for member in sorted(members, key=lambda item: str(item.binding_id))
        ],
    }
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def build_material_set_snapshot(
    *,
    report_id: UUID,
    members: tuple[MaterialSetMember, ...],
    mapping_plan: FrozenMappingPlan | None = None,
) -> MaterialSetSnapshot:
    """冻结当前 active semantic binding 集合。"""

    ordered = tuple(sorted(members, key=lambda item: str(item.binding_id)))
    mapping_plan = mapping_plan or FrozenMappingPlan()
    return MaterialSetSnapshot(
        report_id=report_id,
        members=ordered,
        mapping_plan=mapping_plan,
        input_fingerprint=material_set_fingerprint(
            report_id,
            ordered,
            mapping_plan,
        ),
    )


def build_frozen_mapping_plan(
    *,
    candidate_dossier_ids: tuple[UUID, ...],
    routed_scopes: tuple[tuple[MappingScopeDefinition, tuple[UUID, ...]], ...],
) -> FrozenMappingPlan:
    """从已完成的 Dossier 路由冻结非空 Mapping 工作，不为零资料制造任务。"""

    return FrozenMappingPlan(
        candidate_dossier_ids=tuple(sorted(candidate_dossier_ids, key=str)),
        scopes=tuple(
            MappingPlanScope(
                scope_id=scope.scope_id,
                dossier_ids=tuple(sorted(dossier_ids, key=str)),
                block_ids=tuple(task.block_id for task in scope.block_tasks),
            )
            for scope, dossier_ids in sorted(
                routed_scopes,
                key=lambda item: item[0].scope_id,
            )
            if dossier_ids
        ),
    )


def plan_incremental_mapping(
    *,
    previous: MaterialSetSnapshot,
    current: MaterialSetSnapshot,
    scopes: tuple[MappingScopeDefinition, ...],
    previous_lineage: tuple[MappingScopeLineage, ...],
) -> IncrementalMappingPlan:
    """新增/变更交给全部 scope 判断；纯移除只重算曾采用该来源的 scope。"""

    if previous.report_id != current.report_id:
        raise ValueError("不能比较不同报告的 MaterialSetSnapshot")
    previous_by_binding = {
        member.binding_id: member for member in previous.members
    }
    current_by_binding = {member.binding_id: member for member in current.members}
    changed_binding_ids = {
        binding_id
        for binding_id, member in current_by_binding.items()
        if previous_by_binding.get(binding_id) != member
    }
    removed_members = tuple(
        member
        for binding_id, member in previous_by_binding.items()
        if binding_id not in current_by_binding
    )
    removed_source_ids = {member.source_id for member in removed_members}

    all_scope_ids = {scope.scope_id for scope in scopes}
    if changed_binding_ids:
        rerun_scope_ids = set(all_scope_ids)
    else:
        rerun_scope_ids = {
            lineage.scope_id
            for lineage in previous_lineage
            if removed_source_ids.intersection(lineage.adopted_source_ids)
        }
    unknown_lineage_scopes = rerun_scope_ids - all_scope_ids
    if unknown_lineage_scopes:
        raise ValueError(
            "Mapping lineage 引用了当前报告合同之外的 scope："
            f"{', '.join(sorted(unknown_lineage_scopes))}"
        )

    return IncrementalMappingPlan(
        changed_binding_ids=tuple(
            sorted(changed_binding_ids, key=str)
        ),
        removed_source_ids=tuple(sorted(removed_source_ids, key=str)),
        rerun_scope_ids=tuple(sorted(rerun_scope_ids)),
        reusable_scope_ids=tuple(sorted(all_scope_ids - rerun_scope_ids)),
    )


def _block_material_fingerprint(
    result: ValidatedMappingResult,
    block_id: str,
) -> str:
    """仅按已选择的 FileMaterial 身份和处置决定正文是否需要重建。"""
    decision = next(
        (
            candidate
            for candidate in result.block_decisions
            if candidate.block_id == block_id
        ),
        None,
    )
    if decision is None:
        raise ValueError(
            f"Mapping 结果没有完整覆盖 Block：{block_id}"
        )
    payload = {
        "blockId": block_id,
        "disposition": decision.disposition,
        "materialIds": [str(item) for item in decision.material_ids],
    }
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def plan_block_refresh(
    *,
    previous: ValidatedMappingResult,
    current: ValidatedMappingResult,
) -> BlockRefreshPlan:
    """忽略运行身份和解释性 reason，只按 Block 实际资料投影决定正文失效。"""

    if previous.scope_id != current.scope_id:
        raise ValueError("不能比较不同 Mapping Scope 的结果")
    previous_blocks = {
        decision.block_id for decision in previous.block_decisions
    }
    current_blocks = {decision.block_id for decision in current.block_decisions}
    if previous_blocks != current_blocks:
        raise ValueError("新旧 Mapping 结果的 Block 集合不一致")

    regenerate = {
        block_id
        for block_id in current_blocks
        if _block_material_fingerprint(previous, block_id)
        != _block_material_fingerprint(current, block_id)
    }
    return BlockRefreshPlan(
        regenerate_block_ids=tuple(sorted(regenerate)),
        reusable_block_ids=tuple(sorted(current_blocks - regenerate)),
    )
