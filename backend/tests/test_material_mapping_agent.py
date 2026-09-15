# ABOUTME: 验证 Mapping Agent 读取当前 scope 的 FileMaterial 并输出纯选择候选。
# ABOUTME: Agent 没有文件读取、事实写入或跨轮状态工具；Harness 负责 alias 解析和完整性校验。
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
from sustainability_desk.material.mapping.agent import (
    MappingAgentDeps,
    MappingDossierEntry,
    MappingMaterialChoice,
    MappingProposal,
    build_mapping_agent,
    render_mapping_task,
)
from sustainability_desk.material.mapping.scope import MappingBlockTask, MappingScopeDefinition
from sustainability_desk.persistence.material_agent_pipeline import MappingRunInput
from sustainability_desk.llm.prompt_profiles import load_prompt_profile
from knowledge_package_fixtures import SSE_PACKAGE

MAPPING_TEXTS = load_prompt_profile(SSE_PACKAGE).agent_instructions.mapping_agent
MAPPING_AGENT_INSTRUCTIONS = MAPPING_TEXTS.instructions


def _dossier() -> FileDossier:
    revision = FileSourceRevision(
        source_id=uuid4(), source_sha256="a" * 64, declaration_revision=1
    )
    material = FileMaterial(
        material_id=uuid4(),
        applicable_scope_ids=("report-section:climate_change",),
        content_markdown="董事会每年审议气候风险，并明确相关职责。",
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


def _deps() -> MappingAgentDeps:
    return MappingAgentDeps(
        scope=MappingScopeDefinition(
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
            ),
        ),
        dossier_entries=(
            MappingDossierEntry(
                dossier=_dossier(),
                filename="气候治理制度.docx",
                user_description="本文件说明气候治理职责。",
            ),
        ),
    )


def test_mapping_task_exposes_only_scope_material_aliases_and_task_data() -> None:
    rendered = render_mapping_task(_deps(), MAPPING_TEXTS)

    assert "climate.governance" in rendered
    assert "material_1" in rendered
    assert "董事会每年审议气候风险" in rendered
    assert "materialId" not in rendered
    assert "不得改写、概括、补充、合并或推断" in MAPPING_AGENT_INSTRUCTIONS


def test_mapping_run_input_rejects_direct_material_content_or_decisions() -> None:
    deps = _deps()

    with pytest.raises(ValidationError):
        MappingRunInput.model_validate(
            {
                "scope": deps.scope.model_dump(mode="json"),
                "dossier_ids": [str(deps.dossier_entries[0].dossier.dossier_id)],
                "block_decisions": [{"block_id": "climate.governance"}],
            }
        )


def test_mapping_harness_resolves_aliases_to_frozen_material_ids() -> None:
    deps = _deps()
    result = deps.validate(
        MappingProposal(
            block_decisions=(
                MappingMaterialChoice(
                    block_id="climate.governance",
                    disposition="supported",
                    material_aliases=("material_1",),
                    reason="资料直接说明治理职责。",
                ),
            )
        )
    )

    assert result.block_decisions[0].material_ids == (
        deps.dossier_entries[0].dossier.materials[0].material_id,
    )


def test_mapping_agent_has_no_domain_mutation_tools() -> None:
    agent = build_mapping_agent(texts=MAPPING_TEXTS)

    assert not agent._function_toolset.tools
