# ABOUTME: 验证 MaterialSetSnapshot 的不可变身份和增量 Mapping、Block 失效范围。
# ABOUTME: 新资料交给全部章节语义判断；移除资料只沿既有采用 lineage 传播。
from __future__ import annotations

from uuid import UUID, uuid4

from sustainability_desk.material.mapping.decisions import (
    BlockMaterialDecision,
    ValidatedMappingResult,
)
from sustainability_desk.material.mapping.scope import (
    MappingBlockTask,
    MappingScopeDefinition,
)
from sustainability_desk.material.mapping.snapshot import (
    MappingScopeLineage,
    MaterialSetMember,
    MaterialSetSnapshot,
    _legacy_material_set_fingerprint,
    build_frozen_mapping_plan,
    build_material_set_snapshot,
    plan_block_refresh,
    plan_incremental_mapping,
)


def _member(
    *,
    binding_id: UUID | None = None,
    source_id: UUID | None = None,
    declaration_revision: int = 1,
    marker: str = "a",
) -> MaterialSetMember:
    return MaterialSetMember(
        binding_id=binding_id or uuid4(),
        dossier_id=uuid4(),
        source_id=source_id or uuid4(),
        source_sha256=marker * 64,
        declaration_revision=declaration_revision,
        dossier_fingerprint=marker * 64,
    )


def _scopes() -> tuple[MappingScopeDefinition, ...]:
    return (
        MappingScopeDefinition(
            scope_id="report-section:climate",
            scope_kind="esg_topic",
            title="气候",
            report_section_id="climate",
            block_tasks=(
                MappingBlockTask(
                    block_id="climate.governance",
                    title="治理",
                    semantic_task="说明治理机制。",
                    absence_behavior="generate_context_only",
                ),
            ),
        ),
        MappingScopeDefinition(
            scope_id="report-section:supply",
            scope_kind="esg_topic",
            title="供应链",
            report_section_id="supply",
            block_tasks=(
                MappingBlockTask(
                    block_id="supply.management",
                    title="管理",
                    semantic_task="说明供应链管理。",
                    absence_behavior="generate_context_only",
                ),
            ),
        ),
    )


def test_changed_or_added_dossier_is_reconsidered_by_every_scope() -> None:
    report_id = uuid4()
    original = _member()
    changed = _member(
        binding_id=original.binding_id,
        source_id=original.source_id,
        declaration_revision=2,
        marker="b",
    )
    previous = build_material_set_snapshot(
        report_id=report_id,
        members=(original,),
    )
    current = build_material_set_snapshot(
        report_id=report_id,
        members=(changed,),
    )

    plan = plan_incremental_mapping(
        previous=previous,
        current=current,
        scopes=_scopes(),
        previous_lineage=(),
    )

    assert plan.changed_binding_ids == (original.binding_id,)
    assert set(plan.rerun_scope_ids) == {
        "report-section:climate",
        "report-section:supply",
    }
    assert not plan.reusable_scope_ids


def test_v1_snapshot_remains_readable_until_generation_rebuilds_v2_plan() -> None:
    report_id = uuid4()
    member = _member()
    legacy = MaterialSetSnapshot.model_validate(
        {
            "contract": "sustainability_desk.material_set_snapshot.v1",
            "report_id": report_id,
            "members": [member.model_dump(mode="json")],
            "input_fingerprint": _legacy_material_set_fingerprint(
                report_id, (member,)
            ),
        }
    )

    assert legacy.mapping_plan.scopes == ()


def test_frozen_mapping_plan_contains_only_routed_nonempty_scopes() -> None:
    first = _member()
    second = _member(marker="b")
    climate, supply = _scopes()

    plan = build_frozen_mapping_plan(
        candidate_dossier_ids=(first.dossier_id, second.dossier_id),
        routed_scopes=(
            (climate, (first.dossier_id,)),
            (supply, ()),
        ),
    )
    snapshot = build_material_set_snapshot(
        report_id=uuid4(),
        members=(first, second),
        mapping_plan=plan,
    )

    assert snapshot.mapping_plan.candidate_dossier_ids == tuple(
        sorted((first.dossier_id, second.dossier_id), key=str)
    )
    assert snapshot.mapping_plan.scope_ids == ("report-section:climate",)
    assert snapshot.mapping_plan.scopes[0].dossier_ids == (first.dossier_id,)
    assert snapshot.mapping_plan.block_ids == ("climate.governance",)


def test_removed_dossier_only_invalidates_scope_that_adopted_its_source() -> None:
    report_id = uuid4()
    removed = _member()
    kept = _member(marker="b")
    previous = build_material_set_snapshot(
        report_id=report_id,
        members=(removed, kept),
    )
    current = build_material_set_snapshot(
        report_id=report_id,
        members=(kept,),
    )

    plan = plan_incremental_mapping(
        previous=previous,
        current=current,
        scopes=_scopes(),
        previous_lineage=(
            MappingScopeLineage(
                scope_id="report-section:climate",
                adopted_source_ids=(removed.source_id,),
            ),
            MappingScopeLineage(
                scope_id="report-section:supply",
                adopted_source_ids=(kept.source_id,),
            ),
        ),
    )

    assert plan.removed_source_ids == (removed.source_id,)
    assert plan.rerun_scope_ids == ("report-section:climate",)
    assert plan.reusable_scope_ids == ("report-section:supply",)


def _mapping_result(
    *,
    material_id: UUID,
    decision_reason: str,
) -> ValidatedMappingResult:
    return ValidatedMappingResult(
        scope_id="report-section:climate",
        block_decisions=(
            BlockMaterialDecision(
                scope_id="report-section:climate",
                block_id="climate.governance",
                disposition="supported",
                material_ids=(material_id,),
                reason=decision_reason,
            ),
            BlockMaterialDecision(
                scope_id="report-section:climate",
                block_id="climate.training",
                disposition="context_only",
                material_ids=(),
                reason="未发现培训事实。",
            ),
        ),
    )


def test_block_reuse_ignores_run_identity_and_explanatory_reason() -> None:
    material_id = uuid4()
    previous = _mapping_result(
        material_id=material_id,
        decision_reason="资料直接支持。",
    )
    current = _mapping_result(
        material_id=material_id,
        decision_reason="定位内容足以支持。",
    )

    plan = plan_block_refresh(previous=previous, current=current)

    assert plan.regenerate_block_ids == ()
    assert set(plan.reusable_block_ids) == {
        "climate.governance",
        "climate.training",
    }


def test_only_block_with_changed_selected_material_is_regenerated() -> None:
    previous = _mapping_result(
        material_id=uuid4(),
        decision_reason="资料直接支持。",
    )
    current = _mapping_result(
        material_id=uuid4(),
        decision_reason="资料直接支持。",
    )

    plan = plan_block_refresh(previous=previous, current=current)

    assert plan.regenerate_block_ids == ("climate.governance",)
    assert plan.reusable_block_ids == ("climate.training",)
