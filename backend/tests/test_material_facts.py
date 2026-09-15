# ABOUTME: 报告级资料事实候选语义与来源失效传播的合同测试。
# ABOUTME: 模型判断不得冒充已确认事实；来源删除必须同步撤销事实、提案、缺口与澄清。
from uuid import uuid4

from sustainability_desk.material.intake.facts import stale_source_dependencies
from sustainability_desk.material.intake.models import (
    ClarificationRequest,
    EvidenceRef,
    InputProposal,
    MaterialFactClaim,
    MaterialFactClaimDraft,
    MaterialGap,
    WorkspaceState,
    XlsxRangeLocator,
)
from sustainability_desk.material.input_adapter import LightweightReportInputAdapter
from knowledge_package_fixtures import SSE_PACKAGE


def _evidence(source_id=None) -> EvidenceRef:
    return EvidenceRef(
        source_id=source_id or uuid4(),
        source_label="企业信息.xlsx",
        fragment_id="sheet:基础信息:A1:B1",
        locator=XlsxRangeLocator(sheet_name="基础信息", cell_range="A1:B1"),
    )


def _confirmed_fact() -> MaterialFactClaim:
    return MaterialFactClaim.from_draft(
        MaterialFactClaimDraft(
            semantic_key="company_profile",
            value="某科技企业，主营节能设备研发与制造。",
            rationale="资料表格以精确标签给出值。",
            evidence_refs=[_evidence()],
        ),
        status="confirmed",
        confirmation_method="deterministic",
    )


def test_model_fact_draft_never_defaults_to_confirmed() -> None:
    draft = MaterialFactClaimDraft(
        semantic_key="company_profile",
        value="某科技企业",
        rationale="资料明确说明公司业务",
        evidence_refs=[_evidence()],
    )

    claim = MaterialFactClaim.from_draft(draft)

    assert claim.status == "candidate"
    assert claim.confirmation_method is None


def test_workspace_state_keeps_fact_claims_as_report_scoped_state() -> None:
    claim = _confirmed_fact()

    state = WorkspaceState(facts=[claim])
    restored = WorkspaceState.model_validate(state.model_dump(mode="json"))

    assert restored.facts == [claim]


def test_stale_source_dependencies_invalidates_fact_and_active_proposal() -> None:
    fact = _confirmed_fact()
    adapter = LightweightReportInputAdapter(SSE_PACKAGE)
    proposal = InputProposal(
        target_handle=fact.semantic_key,
        proposed_answer=fact.value,
        supplement=fact.supplement,
        rationale=fact.rationale,
        evidence_refs=fact.evidence_refs,
        fact_claim_ids=[fact.fact_id],
        target_fingerprint=adapter.target_fingerprint(fact.semantic_key),
        current_value_fingerprint=adapter.fingerprint(None, None),
        proposed_value_fingerprint=adapter.fingerprint(fact.value, fact.supplement),
    )

    gap = MaterialGap(
        category="conflict",
        description="资料值冲突",
        target_handle=fact.semantic_key,
        evidence_refs=fact.evidence_refs,
    )
    clarification = ClarificationRequest(
        question="请确认采用哪个值？",
        reason="资料冲突",
        gap_ids=[gap.gap_id],
    )

    state = stale_source_dependencies(
        WorkspaceState(
            facts=[fact],
            proposals=[proposal],
            gaps=[gap],
            clarifications=[clarification],
        ),
        source_id=fact.evidence_refs[0].source_id,
        reason="来源资料已删除",
    )

    assert state.facts[0].status == "stale"
    assert state.facts[0].confirmation_method is None
    assert state.facts[0].stale_reason == "来源资料已删除"
    assert state.proposals[0].status == "stale"
    assert state.proposals[0].stale_reason == "来源资料已删除"
    assert state.gaps[0].status == "stale"
    assert state.clarifications[0].status == "dismissed"
