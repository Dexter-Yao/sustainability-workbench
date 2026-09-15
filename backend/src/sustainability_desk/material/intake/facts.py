# ABOUTME: 资料事实与提案的来源失效传播；来源删除或改性时同步撤销依赖状态。
# ABOUTME: confirmed fact 是填写提案的唯一事实边界；存量 WorkspaceState 仍按此语义解析。
# ABOUTME(en): Propagates source invalidation across material facts and proposals when a source changes.
# ABOUTME(en): A confirmed fact is the only factual boundary for intake proposals; stored WorkspaceState follows it.
from __future__ import annotations

from uuid import UUID

from sustainability_desk.material.intake.models import (
    InputProposal,
    MaterialFactClaim,
    WorkspaceState,
)


def stale_source_dependencies(
    state: WorkspaceState,
    *,
    source_id: UUID,
    reason: str,
) -> WorkspaceState:
    """来源失效时同步撤销事实支撑和所有尚未写入的依赖提案。"""
    stale_fact_ids: set[UUID] = set()
    facts: list[MaterialFactClaim] = []
    for fact in state.facts:
        depends_on_source = any(
            reference.source_id == source_id for reference in fact.evidence_refs
        )
        if depends_on_source and fact.status in {"candidate", "confirmed", "conflicted"}:
            stale_fact_ids.add(fact.fact_id)
            facts.append(
                fact.model_copy(
                    update={
                        "status": "stale",
                        "confirmation_method": None,
                        "stale_reason": reason,
                    }
                )
            )
        else:
            facts.append(fact)
    proposals = stale_proposals_for_fact_ids(
        state.proposals,
        fact_ids=stale_fact_ids,
        reason=reason,
        source_id=source_id,
    )
    stale_gap_ids = {
        gap.gap_id
        for gap in state.gaps
        if gap.status == "open"
        and any(reference.source_id == source_id for reference in gap.evidence_refs)
    }
    gaps = [
        gap.model_copy(update={"status": "stale"})
        if gap.gap_id in stale_gap_ids
        else gap
        for gap in state.gaps
    ]
    clarifications = [
        clarification.model_copy(update={"status": "dismissed"})
        if clarification.status == "open"
        and bool(set(clarification.gap_ids).intersection(stale_gap_ids))
        else clarification
        for clarification in state.clarifications
    ]
    return state.model_copy(
        update={
            "facts": facts,
            "proposals": proposals,
            "gaps": gaps,
            "clarifications": clarifications,
        }
    )


def stale_proposals_for_fact_ids(
    proposals: list[InputProposal],
    *,
    fact_ids: set[UUID],
    reason: str,
    source_id: UUID | None = None,
) -> list[InputProposal]:
    """撤销仍依赖失效事实或来源、且尚未写入 Report 的提案。"""
    return [
        proposal.model_copy(
            update={"status": "stale", "stale_reason": reason}
        )
        if proposal.status in {"proposed", "accepted"}
        and (
            (
                source_id is not None
                and any(
                    reference.source_id == source_id
                    for reference in proposal.evidence_refs
                )
            )
            or bool(set(proposal.fact_claim_ids).intersection(fact_ids))
        )
        else proposal
        for proposal in proposals
    ]
