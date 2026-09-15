# ABOUTME: 将当前 scope 的既有 FileMaterial 映射为 block 采用决定。
# ABOUTME: Mapping 不解释原始文件、不改写资料内容；Harness 解析并校验模型的选择后才持久化。
# ABOUTME(en): Maps existing FileMaterial in the current scope into block adoption decisions.
# ABOUTME(en): Mapping never interprets source files or rewrites material; the Harness validates before persisting.
from __future__ import annotations

from dataclasses import dataclass
import json
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimits

from sustainability_desk.llm.ai_observability import ObservationRun
from sustainability_desk.llm.client import build_agent
from sustainability_desk.llm.prompt_profiles import MappingAgentTexts
from sustainability_desk.llm.concurrency import run_agent
from sustainability_desk.llm.model_registry import DEFAULT_MODEL_ID
from sustainability_desk.material.intake.file_agent_contract import FileDossier, FileMaterial
from sustainability_desk.material.mapping.decisions import (
    BlockMaterialDecisionDraft,
    BlockMaterialDisposition,
    MappingDecisionError,
    ValidatedMappingResult,
    materials_for_scope,
    validate_mapping_decisions,
)
from sustainability_desk.material.mapping.scope import MappingScopeDefinition


class MappingAgentContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MappingDossierEntry(MappingAgentContractModel):
    """冻结 dossier 及其用户声明；模型只接收其中当前 scope 的资料投影。"""

    dossier: FileDossier
    filename: str = Field(min_length=1, max_length=500)
    user_description: str = Field(min_length=1, max_length=2_000)


class MappingMaterialChoice(MappingAgentContractModel):
    block_id: str = Field(min_length=1)
    disposition: BlockMaterialDisposition
    material_aliases: tuple[str, ...] = ()
    reason: str = Field(min_length=1, max_length=2_000)


class MappingProposal(MappingAgentContractModel):
    """模型唯一输出：对既有资料的完整 block 选择，不携带企业事实。"""

    block_decisions: tuple[MappingMaterialChoice, ...]


@dataclass(frozen=True)
class MappingMaterialContext:
    alias: str
    dossier_alias: str
    filename: str
    user_description: str
    content_markdown: str
    attention_notes: tuple[str, ...]
    material: FileMaterial


@dataclass
class MappingAgentDeps:
    scope: MappingScopeDefinition
    dossier_entries: tuple[MappingDossierEntry, ...]
    completed_result: ValidatedMappingResult | None = None

    def __post_init__(self) -> None:
        if any(not entry.dossier.candidate_for_mapping for entry in self.dossier_entries):
            raise ValueError("Mapping Agent 只能接收相关 FileDossier")

    @property
    def materials(self) -> tuple[MappingMaterialContext, ...]:
        entries: list[MappingMaterialContext] = []
        ordinal = 0
        for dossier_ordinal, entry in enumerate(self.dossier_entries, start=1):
            for material in materials_for_scope((entry.dossier,), self.scope.scope_id):
                ordinal += 1
                entries.append(
                    MappingMaterialContext(
                        alias=f"material_{ordinal}",
                        dossier_alias=f"file_{dossier_ordinal}",
                        filename=entry.filename,
                        user_description=entry.user_description,
                        content_markdown=material.content_markdown,
                        attention_notes=tuple(item.message for item in entry.dossier.attention_items),
                        material=material,
                    )
                )
        return tuple(entries)

    def validate(self, proposal: MappingProposal) -> ValidatedMappingResult:
        aliases = {item.alias: item.material.material_id for item in self.materials}
        try:
            drafts = tuple(
                BlockMaterialDecisionDraft(
                    block_id=item.block_id,
                    disposition=item.disposition,
                    material_ids=tuple(aliases[alias] for alias in item.material_aliases),
                    reason=item.reason,
                )
                for item in proposal.block_decisions
            )
        except KeyError as error:
            raise MappingDecisionError("Block 决定引用了当前 scope 不存在的资料别名") from error
        return validate_mapping_decisions(
            scope=self.scope,
            dossiers=tuple(entry.dossier for entry in self.dossier_entries),
            block_decisions=drafts,
        )




def render_mapping_task(deps: MappingAgentDeps, texts: MappingAgentTexts) -> str:
    payload = {
        "mappingTask": deps.scope.model_projection(),
        "materials": [
            {
                "materialAlias": item.alias,
                "fileAlias": item.dossier_alias,
                "filename": item.filename,
                "userDescription": item.user_description,
                "contentMarkdown": item.content_markdown,
                "attentionNotes": list(item.attention_notes),
            }
            for item in deps.materials
        ],
        "completion": texts.completion_note,
    }
    return texts.task_preamble + "\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def build_mapping_agent(
    model_id: str = DEFAULT_MODEL_ID, *, texts: MappingAgentTexts
) -> Agent[MappingAgentDeps, MappingProposal]:
    """Mapping Agent 的指令措辞由知识包 prompt profile 拥有；决策合同与校验留在代码。"""
    agent = build_agent(model_id, output_type=MappingProposal, instructions=texts.instructions, deps_type=MappingAgentDeps, retries=1)

    @agent.output_validator
    async def validate_proposal(ctx: RunContext[MappingAgentDeps], proposal: MappingProposal) -> MappingProposal:
        try:
            ctx.deps.completed_result = ctx.deps.validate(proposal)
        except MappingDecisionError as error:
            raise ModelRetry(str(error)) from error
        return proposal

    return agent


class MappingAgentRunner:
    """以至多一次结构化修复执行当前 scope 的受限 Mapping 提案。"""

    def __init__(
        self,
        *,
        observation: ObservationRun,
        texts: MappingAgentTexts,
        model_id: str = DEFAULT_MODEL_ID,
        max_model_requests: int = 2,
    ) -> None:
        if max_model_requests != 2:
            raise ValueError("Mapping Harness 固定为初次提案加至多一次修复")
        self._observation = observation
        self._model_id = model_id
        self._texts = texts

    async def run(self, deps: MappingAgentDeps) -> ValidatedMappingResult:
        agent = build_mapping_agent(self._model_id, texts=self._texts)
        await run_agent(
            agent,
            render_mapping_task(deps, self._texts),
            self._observation.invocation(
                block_id=deps.scope.scope_id,
                model_id=self._model_id,
                evidence_selector_kind="material_set_snapshot",
                task_context={"scopeId": deps.scope.scope_id, "materialCount": len(deps.materials), "requestBudget": 2},
            ),
            deps=deps,
            usage_limits=UsageLimits(request_limit=2),
        )
        if deps.completed_result is None:
            raise RuntimeError("Mapping Agent 未形成经验证的完整资料采用决定")
        return deps.completed_result
