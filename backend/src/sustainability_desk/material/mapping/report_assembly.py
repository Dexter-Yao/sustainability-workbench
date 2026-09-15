# ABOUTME: 从当前 StoredReportState 与报告级执行范围装配唯一有效的 Mapping 任务。
# ABOUTME: File Agent、快照路由和 Mapping worker 必须共用此投影，不能各自推断活跃 Block 或 scope。
# ABOUTME(en): Assembles the one effective Mapping task set from StoredReportState and report execution scope.
# ABOUTME(en): File Agent, snapshot routing and the Mapping worker share this projection, never inferring scope alone.
from __future__ import annotations

from dataclasses import dataclass

from sustainability_desk.accounts.report_execution_scope import EffectiveReportScope
from sustainability_desk.contract.compiled_definition import CompiledReportDefinition
from sustainability_desk.contract.models import Report
from sustainability_desk.contract.report_revision import build_report_revision
from sustainability_desk.contract.stored_report_state import StoredReportStateV4
from sustainability_desk.llm.generate_all import blocks_for_report
from sustainability_desk.material.mapping.scope import (
    MappingScopeDefinition,
    MappingTaskAssembly,
    assemble_mapping_tasks,
)


@dataclass(frozen=True)
class EffectiveMappingTaskAssembly:
    """当前 revision 在已授权范围内可执行的 Report 与 Mapping 任务。"""

    report: Report
    active_block_ids: frozenset[str]
    mapping_tasks: MappingTaskAssembly

    def scope(self, scope_id: str) -> MappingScopeDefinition | None:
        """按稳定 scope 身份返回本 revision 的唯一 Mapping 任务。"""

        return next(
            (
                scope
                for scope in self.mapping_tasks.scopes
                if scope.scope_id == scope_id
            ),
            None,
        )


def assemble_effective_mapping_tasks(
    definition: CompiledReportDefinition,
    state: StoredReportStateV4,
    execution_scope: EffectiveReportScope,
) -> EffectiveMappingTaskAssembly:
    """按固定顺序从当前状态装配唯一可执行的 Mapping scope 集合。"""

    report = execution_scope.project_report(
        build_report_revision(state, package=execution_scope.knowledge_package)
    )
    active_block_ids = frozenset(
        block.id for block in blocks_for_report(report)
    )
    return EffectiveMappingTaskAssembly(
        report=report,
        active_block_ids=active_block_ids,
        mapping_tasks=assemble_mapping_tasks(
            definition,
            active_block_ids=active_block_ids,
        ),
    )


def require_current_mapping_scope(
    assembly: EffectiveMappingTaskAssembly,
    frozen_scope: MappingScopeDefinition,
) -> MappingScopeDefinition:
    """验证冻结任务仍等于当前 scope，避免范围或语义漂移后继续调用模型。"""

    current_scope = assembly.scope(frozen_scope.scope_id)
    if current_scope is None:
        raise ValueError("冻结 Mapping scope 已不属于当前报告范围")
    if current_scope != frozen_scope:
        raise ValueError("冻结 Mapping scope 的 Block 或语义任务已变化")
    return current_scope
