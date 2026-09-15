# ABOUTME: 验证 Mapping 只能选择既有 FileMaterial，不能再产生或改写企业事实。
# ABOUTME: 决定必须完整覆盖当前 scope，且每个材料身份都来自冻结 FileDossier。
from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from sustainability_desk.material.intake.file_agent_contract import (
    FileDossier,
    FileMaterial,
    FileSourceRevision,
    file_dossier_fingerprint,
)
from sustainability_desk.material.mapping.decisions import (
    BlockMaterialDecisionDraft,
    MappingDecisionError,
    validate_mapping_decisions,
)
from sustainability_desk.material.mapping.scope import MappingBlockTask, MappingScopeDefinition


def _dossier() -> FileDossier:
    revision = FileSourceRevision(
        source_id=uuid4(), source_sha256="a" * 64, declaration_revision=1
    )
    material = FileMaterial(
        material_id=uuid4(),
        applicable_scope_ids=("report-section:climate_change",),
        content_markdown="董事会每年审议气候相关风险。",
    )
    return FileDossier(
        source_revision=revision,
        relevance="relevant",
        relevance_reason="文件包含气候治理制度。",
        materials=(material,),
        dossier_fingerprint=file_dossier_fingerprint(
            source_revision=revision,
            relevance="relevant",
            relevance_reason="文件包含气候治理制度。",
            materials=(material,),
            attention_items=(),
        ),
    )


def _scope() -> MappingScopeDefinition:
    return MappingScopeDefinition(
        scope_id="report-section:climate_change",
        scope_kind="esg_topic",
        title="应对气候变化",
        report_section_id="climate_change",
        block_tasks=(
            MappingBlockTask(
                block_id="climate.governance",
                title="治理",
                semantic_task="说明气候治理机制。",
                absence_behavior="generate_context_only",
            ),
            MappingBlockTask(
                block_id="climate.training",
                title="培训",
                semantic_task="说明气候培训。",
                absence_behavior="generate_context_only",
            ),
        ),
    )


def test_mapping_validator_selects_existing_file_material_only() -> None:
    dossier = _dossier()
    material_id = dossier.materials[0].material_id

    result = validate_mapping_decisions(
        scope=_scope(),
        dossiers=(dossier,),
        block_decisions=(
            BlockMaterialDecisionDraft(
                block_id="climate.governance",
                disposition="supported",
                material_ids=(material_id,),
                reason="资料直接说明治理安排。",
            ),
            BlockMaterialDecisionDraft(
                block_id="climate.training",
                disposition="context_only",
                reason="资料未说明培训。",
            ),
        ),
    )

    assert result.block_decisions[0].material_ids == (material_id,)
    assert not hasattr(result, "facts")


def test_mapping_rejects_invalid_material_decision_shape() -> None:
    with pytest.raises(ValidationError):
        BlockMaterialDecisionDraft(
            block_id="climate.governance",
            disposition="supported",
            material_ids=(),
            reason="资料支持。",
        )
    with pytest.raises(ValidationError):
        BlockMaterialDecisionDraft(
            block_id="climate.governance",
            disposition="context_only",
            material_ids=(uuid4(),),
            reason="无资料。",
        )
    with pytest.raises(ValidationError):
        BlockMaterialDecisionDraft(
            block_id="climate.governance",
            disposition="needs_attention",
            material_ids=(uuid4(),),
            reason="资料对治理职责存在无法消解的矛盾。",
        )


def test_mapping_requires_complete_scope_coverage() -> None:
    with pytest.raises(MappingDecisionError, match="完整覆盖"):
        validate_mapping_decisions(
            scope=_scope(),
            dossiers=(_dossier(),),
            block_decisions=(
                BlockMaterialDecisionDraft(
                    block_id="climate.governance",
                    disposition="context_only",
                    reason="无资料。",
                ),
            ),
        )


def test_mapping_rejects_material_outside_current_scope() -> None:
    dossier = _dossier()
    with pytest.raises(MappingDecisionError, match="scope 外或未知"):
        validate_mapping_decisions(
            scope=_scope(),
            dossiers=(dossier,),
            block_decisions=(
                BlockMaterialDecisionDraft(
                    block_id="climate.governance",
                    disposition="supported",
                    material_ids=(uuid4(),),
                    reason="错误选择。",
                ),
                BlockMaterialDecisionDraft(
                    block_id="climate.training",
                    disposition="context_only",
                    reason="无资料。",
                ),
            ),
        )
