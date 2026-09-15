# ABOUTME: 验证资料语义映射只从已编译报告定义派生章节任务，不维护平行 target 目录。
# ABOUTME: 同一生成 Block 必须且只能属于一个 Mapping Scope，模型只接收当前 scope 的高信号任务地图。
from __future__ import annotations

from uuid import uuid4


from sustainability_desk.contract.compiled_definition import load_compiled_report_definition
from sustainability_desk.contract.report_revision import build_report_revision
from local_e2e_fixture import (
    load_local_e2e_fixture_recipe,
    synthesize_stored_report_state,
)
from sustainability_desk.llm.generate_all import blocks_for_report
from sustainability_desk.material.agent_pipeline import _fingerprint
from sustainability_desk.material.mapping.scope import (
    assemble_mapping_tasks,
    material_routes_to_scope,
)
from knowledge_package_fixtures import SSE_PACKAGE


def test_mapping_scopes_cover_each_generation_contract_exactly_once() -> None:
    definition = load_compiled_report_definition(SSE_PACKAGE)

    assembly = assemble_mapping_tasks(definition)

    mapped_block_ids = [
        task.block_id
        for scope in assembly.scopes
        for task in scope.block_tasks
    ]
    expected_block_ids = [
        contract.block_id
        for contract in definition.generation_contracts.values()
    ]
    assert sorted(mapped_block_ids) == sorted(expected_block_ids)
    assert len(mapped_block_ids) == len(set(mapped_block_ids))


def test_report_section_scope_reuses_compiled_semantic_tasks() -> None:
    definition = load_compiled_report_definition(SSE_PACKAGE)
    assembly = assemble_mapping_tasks(definition)
    climate_scope = next(
        scope
        for scope in assembly.scopes
        if scope.report_section_id == "climate_change"
    )

    assert climate_scope.scope_id == "report-section:climate_change"
    assert climate_scope.scope_kind == "esg_topic"
    assert len(climate_scope.block_tasks) >= 2
    for task in climate_scope.block_tasks:
        contract = definition.generation_for_block(task.block_id)
        assert task.semantic_task == contract.semantic_task
        assert task.intake_item_ids == contract.intake_item_ids
        assert task.quantitative_metric_ids == contract.quantitative_metric_ids
        assert task.absence_behavior == contract.absence_behavior
        assert task.information_needs
        if task.quantitative_metric_ids:
            assert any(
                "数值由定量输入链独立提供" in need
                for need in task.information_needs
            )


def test_non_topic_generation_contracts_receive_stable_report_area_scopes() -> None:
    definition = load_compiled_report_definition(SSE_PACKAGE)
    assembly = assemble_mapping_tasks(definition)

    non_topic_scopes = [
        scope for scope in assembly.scopes if scope.report_section_id is None
    ]

    assert non_topic_scopes
    assert all(scope.scope_id.startswith("report-area:") for scope in non_topic_scopes)
    assert all(scope.scope_kind == "report_area" for scope in non_topic_scopes)
    assert all(scope.block_tasks for scope in non_topic_scopes)


def test_mapping_assembly_filters_to_current_report_revision_blocks() -> None:
    definition = load_compiled_report_definition(SSE_PACKAGE)

    assembly = assemble_mapping_tasks(
        definition,
        active_block_ids=frozenset({"company_intro.body", "climate.gov_structure"}),
    )

    assert [
        task.block_id
        for scope in assembly.scopes
        for task in scope.block_tasks
    ] == ["company_intro.body", "climate.gov_structure"]
    assert [scope.scope_kind for scope in assembly.scopes] == [
        "report_area",
        "esg_topic",
    ]


def test_mapping_assembly_uses_visible_e2e_generation_blocks() -> None:
    definition = load_compiled_report_definition(SSE_PACKAGE)
    report = build_report_revision(
        synthesize_stored_report_state(load_local_e2e_fixture_recipe()), package=SSE_PACKAGE
    )
    visible_block_ids = frozenset(block.id for block in blocks_for_report(report))
    all_block_ids = {block.id for block in report.iter_blocks()}
    assembly = assemble_mapping_tasks(
        definition,
        active_block_ids=visible_block_ids,
    )
    mapped_block_ids = {
        task.block_id for scope in assembly.scopes for task in scope.block_tasks
    }

    assert "climate.iro_reduction_practice" in all_block_ids
    assert "climate.iro_reduction_practice" not in visible_block_ids
    assert "climate.iro_reduction_practice" not in mapped_block_ids
    assert mapped_block_ids.issubset(visible_block_ids)


def test_file_material_routes_only_to_its_compiled_scopes() -> None:
    definition = load_compiled_report_definition(SSE_PACKAGE)
    assembly = assemble_mapping_tasks(definition)
    company_scope = next(
        scope for scope in assembly.scopes if scope.scope_id == "report-area:company_intro"
    )
    climate_scope = next(
        scope
        for scope in assembly.scopes
        if scope.report_section_id == "climate_change"
    )
    supply_chain_scope = next(
        scope
        for scope in assembly.scopes
        if scope.report_section_id == "sustainable_supply_chain_management"
    )

    assert material_routes_to_scope(
        company_scope,
        ("report-area:company_intro",),
    )
    assert not material_routes_to_scope(
        climate_scope,
        ("report-area:company_intro",),
    )
    assert material_routes_to_scope(
        climate_scope,
        ("report-section:climate_change",),
    )
    assert material_routes_to_scope(
        supply_chain_scope,
        ("report-section:sustainable_supply_chain_management",),
    )
    assert not material_routes_to_scope(
        supply_chain_scope,
        ("unknown",),
    )


def test_material_scope_has_no_trial_only_broadcast_exception() -> None:
    definition = load_compiled_report_definition(SSE_PACKAGE)
    assembly = assemble_mapping_tasks(definition)
    climate_scope = next(
        scope
        for scope in assembly.scopes
        if scope.report_section_id == "climate_change"
    )
    supply_chain_scope = next(
        scope
        for scope in assembly.scopes
        if scope.report_section_id == "sustainable_supply_chain_management"
    )

    assert material_routes_to_scope(
        climate_scope,
        ("report-section:climate_change",),
    )
    assert not material_routes_to_scope(
        supply_chain_scope,
        ("report-section:climate_change",),
    )


def test_mapping_input_fingerprint_handles_dossier_identity_values() -> None:
    fingerprint = _fingerprint({"selectedDossierIds": [uuid4()]})

    assert len(fingerprint) == 64
