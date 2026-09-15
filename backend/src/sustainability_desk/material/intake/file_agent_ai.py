# ABOUTME: 将单文件只读工作区注册为 Pydantic AI 工具，并经统一模型出口执行资料理解。
# ABOUTME: 报告背景从议题合同派生；模型判断候选相关性，Harness 只守结构、权限与版本边界。
# ABOUTME(en): Registers the single-file read-only workspace as Pydantic AI tools, run via the unified model exit.
# ABOUTME(en): Report background derives from topic contracts; the model judges relevance, the Harness guards structure.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Json
from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimits

from sustainability_desk.llm.ai_observability import ObservationRun
from sustainability_desk.llm.client import build_agent
from sustainability_desk.llm.concurrency import run_agent
from sustainability_desk.llm.model_registry import DEFAULT_MODEL_ID
from sustainability_desk.material.intake.file_agent_contract import (
    FileAgentRunReceipt,
    FileAgentRunResult,
    FileAgentToolRequest,
    FileAgentTraceEvent,
    FileDossier,
    FileDossierDraft,
    AttentionItemDraft,
    FileMaterialDraft,
)
from sustainability_desk.llm.prompt_profiles import FileAgentTexts
from sustainability_desk.material.intake.file_agent_workspace import (
    FileAgentWorkspace,
    FileAgentWorkspaceError,
)



class FileAgentOutputModel(BaseModel):
    """File Agent 最终传输提案的严格基类，不承担持久化领域事实。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FileDossierProposal(FileAgentOutputModel):
    """兼容原生嵌套值和 provider JSON 字符串的模型输出传输边界。"""

    relevance: Literal["relevant", "not_relevant"]
    relevance_reason: str
    materials: Json[tuple[FileMaterialDraft, ...]] | tuple[FileMaterialDraft, ...] = ()
    attention_items: (
        Json[tuple[AttentionItemDraft, ...]] | tuple[AttentionItemDraft, ...]
    ) = ()

    def to_draft(self) -> FileDossierDraft:
        """将已解析的 transport proposal 收敛为唯一业务草稿合同。"""

        return FileDossierDraft(
            relevance=self.relevance,
            relevance_reason=self.relevance_reason,
            materials=self.materials,
            attention_items=self.attention_items,
        )


@dataclass
class FileAgentDeps:
    """一次文件理解的只读工作区与已冻结的 FileDossier。"""

    workspace: FileAgentWorkspace
    completed_dossier: FileDossier | None = None

    def finalize(self, draft: FileDossierDraft) -> FileDossier:
        """在严格结构化输出边界验证并冻结当前文件的资料理解。"""

        if self.completed_dossier is not None:
            raise FileAgentWorkspaceError("文件理解已经冻结，不能重复提交")
        self.completed_dossier = self.workspace.finalize(draft)
        return self.completed_dossier


def build_report_need_catalog(material_scopes) -> dict[str, Any]:
    """从当前报告范围 SSOT 派生 File Agent 所需的最小资料边界。"""

    return {
        "allowedMaterialScopes": [
            {
                "scopeAlias": scope.alias,
                "title": scope.title,
                "kind": scope.kind,
                "withinReportScope": scope.within_report_scope,
            }
            for scope in material_scopes
        ],
    }


def _execute(
    ctx: RunContext[FileAgentDeps],
    request: FileAgentToolRequest,
) -> dict[str, Any]:
    try:
        return ctx.deps.workspace.execute(request).model_dump(mode="json")
    except FileAgentWorkspaceError as error:
        raise ModelRetry(str(error)) from error


def build_file_understanding_agent(
    model_id: str = DEFAULT_MODEL_ID,
    *,
    texts: FileAgentTexts,
) -> Agent[FileAgentDeps, FileDossierProposal]:
    """构造真实 tool-calling Agent；构造本身不产生模型请求。指令措辞由知识包 prompt profile 拥有。"""

    agent = build_agent(
        model_id,
        output_type=FileDossierProposal,
        instructions=texts.instructions,
        deps_type=FileAgentDeps,
        retries=1,
    )

    @agent.tool
    async def convert_file(ctx: RunContext[FileAgentDeps]) -> dict[str, Any]:
        """用当前文件类型获批准的 parser 转成只读 Markdown，并返回可打开产物清单。"""

        return _execute(ctx, FileAgentToolRequest(tool_name="convert_file"))

    @agent.tool
    async def read_file(
        ctx: RunContext[FileAgentDeps],
        path: str,
    ) -> dict[str, Any]:
        """完整读取 convert_file 返回的一份 Markdown 产物；不接受任意路径或局部范围。"""

        return _execute(
            ctx,
            FileAgentToolRequest(tool_name="read_file", path=path),
        )

    @agent.output_validator
    async def validate_dossier_draft(
        ctx: RunContext[FileAgentDeps],
        proposal: FileDossierProposal,
    ) -> FileDossierProposal:
        """将模型的严格结构化候选绑定到已读文件与当前 compiled scope。"""

        try:
            ctx.deps.finalize(proposal.to_draft())
        except ValueError as error:
            raise ModelRetry(str(error)) from error
        return proposal

    return agent


def _initial_prompt(workspace: FileAgentWorkspace, texts: FileAgentTexts) -> str:
    """投影单文件任务、用户意图与由 SSOT 派生的报告需要。"""

    context = workspace.context
    payload = {
        "productTask": {
            "objective": context.product_task.objective,
            "reportSubjectName": context.product_task.report_subject_name,
            "reportPeriodLabel": context.product_task.report_period_label,
        },
        "reportNeedCatalog": build_report_need_catalog(
            context.product_task.material_scopes,
        ),
        "scope": {
            "label": context.product_task.scope_label,
            "allowedScopeAliases": [scope.alias for scope in context.product_task.material_scopes],
            "coveredScopeAliases": [
                scope.alias for scope in context.product_task.covered_scopes()
            ],
            "coverage": texts.coverage_note,
        },
        "file": {
            "workspaceInputPath": f"input/{context.filename}",
            "filename": context.filename,
            "materialKind": context.material_kind,
            "sizeBytes": context.size_bytes,
        },
        "userDeclaration": {
            "authority": "user_intent_not_file_evidence",
            "description": context.declaration.description,
            "topicTags": context.declaration.topic_tags,
            "revision": context.source_revision.declaration_revision,
        },
        "completion": texts.completion_note,
    }
    return texts.task_preamble + "\n" + json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class FileUnderstandingAgentAdapter:
    """经统一并发与 trace 执行真实多轮工具调用。"""

    def __init__(
        self,
        *,
        texts: FileAgentTexts,
        model_id: str = DEFAULT_MODEL_ID,
        max_model_requests: int = 6,
        agent: Agent[FileAgentDeps, FileDossierProposal] | None = None,
    ) -> None:
        if max_model_requests < 2:
            raise ValueError("File Agent 至少需要两次模型调用")
        self._model_id = model_id
        self._max_model_requests = max_model_requests
        self._texts = texts
        self._agent = agent or build_file_understanding_agent(model_id, texts=texts)

    async def run(
        self,
        workspace: FileAgentWorkspace,
        *,
        observation: ObservationRun,
        run_id: UUID | None = None,
        attempt: int = 1,
    ) -> FileAgentRunResult:
        """让模型自主调查并把最小结构输出绑定到冻结文件版本。"""

        started_at = datetime.now(timezone.utc)
        prompt = _initial_prompt(workspace, self._texts)
        context_fingerprint = sha256(prompt.encode("utf-8")).hexdigest()
        deps = FileAgentDeps(workspace=workspace)
        await run_agent(
            self._agent,
            prompt,
            observation.invocation(
                model_id=self._model_id,
                evidence_selector_kind="file_agent_workspace",
                context_fingerprint=context_fingerprint,
                task_context={
                    "materialKind": workspace.context.material_kind,
                    "declarationRevision": (
                        workspace.context.source_revision.declaration_revision
                    ),
                    "toolBudget": self._max_model_requests,
                },
            ),
            deps=deps,
            usage_limits=UsageLimits(request_limit=self._max_model_requests),
        )
        dossier = deps.completed_dossier
        if dossier is None:
            raise RuntimeError("File Agent 未通过完成工具冻结 FileDossier")
        events = [
            FileAgentTraceEvent(
                sequence=1,
                occurred_at=started_at,
                event_type="context_prepared",
                detail_code="model_context_ready",
            )
        ]
        for tool_receipt in workspace.tool_receipts:
            events.append(
                FileAgentTraceEvent(
                    sequence=len(events) + 1,
                    occurred_at=datetime.now(timezone.utc),
                    event_type="tool_completed",
                    tool_name=tool_receipt.request.tool_name,
                    receipt_id=tool_receipt.receipt_id,
                    detail_code=f"{tool_receipt.request.tool_name}_completed",
                )
            )
        events.extend(
            (
                FileAgentTraceEvent(
                    sequence=len(events) + 1,
                    occurred_at=datetime.now(timezone.utc),
                    event_type="dossier_validated",
                    detail_code="typed_dossier_and_source_revision_valid",
                ),
                FileAgentTraceEvent(
                    sequence=len(events) + 2,
                    occurred_at=datetime.now(timezone.utc),
                    event_type="run_completed",
                    detail_code="file_understanding_completed",
                ),
            )
        )
        receipt = FileAgentRunReceipt(
            run_id=run_id or uuid4(),
            observation_run_id=observation.runId,
            attempt=attempt,
            status="completed",
            source_revision=workspace.context.source_revision,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            tool_receipts=workspace.tool_receipts,
            trace_events=tuple(events),
            dossier_fingerprint=dossier.dossier_fingerprint,
        )
        return FileAgentRunResult(
            status="completed",
            dossier=dossier,
            checkpoint=None,
            receipt=receipt,
        )
