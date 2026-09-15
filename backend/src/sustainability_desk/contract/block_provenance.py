# ABOUTME: 报告逐块溯源的公共投影合同：内容依据、资料处置、指标与生成运行事实的稳定 code 视图。
# ABOUTME: 只承载文件名、显示名、计数与 code；不含 run/span/模型/路径/prompt，轨迹缺失是合法状态而非错误。
# ABOUTME(en): Public per-block provenance projection: evidence basis, material disposition, metrics and run facts as stable codes.
# ABOUTME(en): Carries only file names, display names, counts and codes; never run/span/model ids, paths or prompts.
from __future__ import annotations

from datetime import datetime
from typing import Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sustainability_desk.contract.models import Inline

BLOCK_PROVENANCE_CONTRACT = "sustainability_desk.block_provenance.v1"

#: Why a block reads the way it does; shared vocabulary with the customer commentary package.
type ProvenanceBasis = Literal[
    "structured_input",
    "validated_material",
    "quantitative_metric",
    "industry_disclosure_context",
    "deterministic_report_projection",
    "uploaded_layout_image",
]
#: Mapping disposition of the block plus the explicit "no decision was made" state.
type MaterialDispositionCode = Literal[
    "supported",
    "partially_supported",
    "context_only",
    "needs_attention",
    "not_applicable",
    "no_decision",
]
#: Closed vocabulary of online guardrail issue keys. A test asserts it equals the keys used in
#: llm/generation_guardrails.py and llm/generate.py, so adding a guardrail forces a contract update.
type GuardrailIssueCode = Literal[
    "ai_text_cell_empty",
    "approximate_number_comma",
    "empty_output",
    "empty_variants",
    "expanded_unit_missing",
    "incomplete_output",
    "internal_leak",
    "internal_path_leak",
    "metric_narrative_maturity",
    "missing_display_title",
    "missing_or_negative_statement",
    "numeric_range_missing_percent",
    "output_format",
    "output_self_numbering",
    "placeholder_output",
    "required_cell_empty",
    "social_sensitive_statement",
    "table_company_subject",
    "template_residue",
    "title_trailing_punctuation",
    "too_many_paragraphs_without_substantive_input",
    "unsupported_actual_iro_classification",
    "unsupported_formal_name",
    "unsupported_numeric_claim",
    "unsupported_evidence_gated_fact",
]
type GuardrailVerdict = Literal["accepted", "accepted_after_retry", "rejected", "not_evaluated"]
type EvidenceSelectorKind = Literal["explicit", "report_section", "material_gated"]
type EvidenceLevel = Literal["block_facts", "context_only", "metric_narrative"]
type GenerationOutcome = Literal["ready", "omitted", "not_generated"]
type OmissionCode = Literal["no_supporting_material", "empty_table"]
type TraceAvailability = Literal["available", "unavailable"]

GUARDRAIL_ISSUE_CODES: frozenset[str] = frozenset(get_args(GuardrailIssueCode.__value__))


class BlockProvenanceModel(BaseModel):
    """Strict immutable base for the provenance contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class BlockProvenanceSource(BlockProvenanceModel):
    """One uploaded file adopted for the block, with the number of FileMaterial units taken from it."""

    material_name: str = Field(min_length=1, max_length=500)
    adopted_material_count: int = Field(ge=1)


class BlockProvenanceIntakeItem(BlockProvenanceModel):
    """An intake question the block's evidence selector declares, and whether it had a substantive answer."""

    question: str = Field(min_length=1, max_length=1_000)
    answered: bool


class BlockProvenanceMetric(BlockProvenanceModel):
    """A quantitative metric the block actually consumed and the user actually filled in."""

    metric_name: str = Field(min_length=1, max_length=300)
    value: str = Field(min_length=1, max_length=100)
    unit: str | None = Field(default=None, max_length=50)


class BlockProvenanceRun(BlockProvenanceModel):
    """Run facts for one block, projected from the generation trace as counts and codes only."""

    stage_status: Literal["succeeded", "failed"]
    attempt_count: int = Field(ge=0)
    guardrail: GuardrailVerdict
    guardrail_issue_codes: tuple[GuardrailIssueCode, ...] = ()
    evidence_selector_kind: EvidenceSelectorKind | None = None
    evidence_level: EvidenceLevel | None = None
    intake_fact_count: int = Field(default=0, ge=0)
    metric_evidence_count: int = Field(default=0, ge=0)
    prior_disclosure_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _issues_match_verdict(self) -> "BlockProvenanceRun":
        if self.guardrail in {"accepted", "not_evaluated"} and self.guardrail_issue_codes:
            raise ValueError("未被拒绝过的守卫判定不得携带问题类别")
        return self


class BlockProvenanceEntry(BlockProvenanceModel):
    """User-safe provenance of one report block."""

    block_id: str = Field(min_length=1, max_length=300)
    basis: tuple[ProvenanceBasis, ...] = Field(min_length=1)
    generation_outcome: GenerationOutcome
    omission: OmissionCode | None = None
    material_disposition: MaterialDispositionCode
    sources: tuple[BlockProvenanceSource, ...] = ()
    intake_items: tuple[BlockProvenanceIntakeItem, ...] = ()
    metrics: tuple[BlockProvenanceMetric, ...] = ()
    attention_note: bool = False
    #: Generated baseline text, returned only for AI paragraph blocks so the client can derive edits.
    generated_content: list[Inline] | None = None
    run: BlockProvenanceRun | None = None

    @model_validator(mode="after")
    def _omission_matches_outcome(self) -> "BlockProvenanceEntry":
        if (self.omission is not None) != (self.generation_outcome == "omitted"):
            raise ValueError("省略原因必须且只能出现在受控省略的块上")
        if self.generation_outcome == "not_generated" and self.run is not None:
            raise ValueError("未经生成的块没有运行事实")
        return self


class ReportBlockProvenanceProjection(BlockProvenanceModel):
    """Per-block provenance of the latest successfully generated report revision."""

    contract: Literal["sustainability_desk.block_provenance.v1"] = BLOCK_PROVENANCE_CONTRACT
    report_id: UUID
    revision: int = Field(ge=1)
    generated_report_state_seq: int = Field(ge=1)
    generated_at: datetime
    trace_availability: TraceAvailability
    blocks: tuple[BlockProvenanceEntry, ...]

    @model_validator(mode="after")
    def _run_facts_only_with_trace(self) -> "ReportBlockProvenanceProjection":
        if self.trace_availability == "unavailable" and any(
            block.run is not None for block in self.blocks
        ):
            raise ValueError("轨迹不可用时不得携带任何运行事实")
        block_ids = [block.block_id for block in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("同一块不得重复出现")
        return self
