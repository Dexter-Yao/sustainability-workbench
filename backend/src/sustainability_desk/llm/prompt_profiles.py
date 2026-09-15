# ABOUTME(en): Prompt Profile type contract and loader: one report-generation prompt profile per knowledge
# ABOUTME(en): package, identified by the package id. It owns every model-visible sentence the code renders —
# ABOUTME(en): system segments, labels, evidence postures, agent instructions — so a package fully decides
# ABOUTME(en): what the model reads in its language; code owns only structure, control flow and validation.
from __future__ import annotations

from functools import lru_cache
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from sustainability_desk.contract.evidence_resolution import AnswerWording
from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    load_knowledge_package,
)


class _ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


NonEmptyText = Field(min_length=1)


class GlobalPromptSegments(_ProfileModel):
    """跨议题稳定 System 片段；体裁由 Profile、事实边界由 EvidencePosture 拥有。"""

    context_fields: tuple[str, ...]
    role: str
    report_body_contract: str
    expression_guidance: str
    content_format: str


class EvidenceLabels(_ProfileModel):
    """Labels of the user-facts rendering inside <filled_content> and metric materials."""

    intake_item: str = NonEmptyText
    intake_note: str = NonEmptyText
    mapped_material: str = NonEmptyText
    metric_material_label: str = NonEmptyText  # {metric_name}
    metric_source_line: str = NonEmptyText
    metric_category_path: str = NonEmptyText
    metric_name: str = NonEmptyText
    metric_unit: str = NonEmptyText
    metric_value: str = NonEmptyText
    metric_note: str = NonEmptyText
    metric_accounting_standard: str = NonEmptyText
    metric_no_value_boundary: str = NonEmptyText
    part_separator: str = NonEmptyText
    no_metric_values: str = NonEmptyText
    # Lead words of a projected intake answer: "已选择：<options>" and "补充说明：<supplement>".
    selected_lead: str = NonEmptyText
    supplement_lead: str = NonEmptyText


class StructureLabels(_ProfileModel):
    """Labels of the structural System segments (placement, scope, prior disclosure, posture, IRO)."""

    topic_scope_heading: str = NonEmptyText
    report_section: str = NonEmptyText
    pillar: str = NonEmptyText
    content_unit: str = NonEmptyText
    placement_anchor_note: str = NonEmptyText
    placement_output_note: str = NonEmptyText
    prior_disclosure_heading: str = NonEmptyText
    prior_disclosure_item: str = NonEmptyText  # {pillar_title} {text}
    prior_disclosure_footer: str = NonEmptyText
    evidence_level: str = NonEmptyText
    source_use: str = NonEmptyText
    assertion_style: str = NonEmptyText
    context_only_calibration_lead: str = NonEmptyText
    iro_context_directive: str = NonEmptyText


class OutputLabels(_ProfileModel):
    """Sentences of the <output_contract>, <length> and display-title segments."""

    single_variant: str = NonEmptyText
    variants_same_level: str = NonEmptyText  # {n}
    variants_diverse: str = NonEmptyText  # {n}
    structured_output_lead: str = NonEmptyText
    content_complete: str = NonEmptyText
    display_title_pairing: str = NonEmptyText
    display_title_sync: str = NonEmptyText
    short_paragraph_per_variant: str = NonEmptyText
    length_metric_narrative: str = NonEmptyText  # {min} {max}
    length_default: str = NonEmptyText  # {max}


class TableLabels(_ProfileModel):
    """Sentences of the table prompts: column specs, row proposal, catalog fill, row completion."""

    options_multi_template: str = NonEmptyText  # {options}
    options_single_template: str = NonEmptyText  # {options}
    hint_template: str = NonEmptyText  # {hint}
    propose_task: str = NonEmptyText  # {count_min} {count_max}
    column_requirements: str = NonEmptyText
    catalog_task: str = NonEmptyText  # {kind_label}
    catalog_user_material_rules: str = NonEmptyText
    row_input_context_heading: str = NonEmptyText
    user_supported_guide: str = NonEmptyText
    framework_guide: str = NonEmptyText
    adaptive_task: str = NonEmptyText  # {kind_label} {count_min} {count_max}
    adaptive_field_rule: str = NonEmptyText
    adaptive_reference_intro: str = NonEmptyText
    reference_note: str = NonEmptyText  # {reference}
    none: str = NonEmptyText
    opportunity_coverage: str = NonEmptyText  # {categories}
    expansion_task: str = NonEmptyText
    expansion_units_intro: str = NonEmptyText  # {count} {unit_labels}
    expansion_shared_intro: str = NonEmptyText
    expansion_units_lead: str = NonEmptyText
    unit_name: str = NonEmptyText  # {label}
    unit_heading: str = NonEmptyText  # {label}
    complete_row_task: str = NonEmptyText
    row_theme: str = NonEmptyText
    row_category: str = NonEmptyText
    row_driver_hint: str = NonEmptyText


class TableSupportLabels(_ProfileModel):
    """Row-level input-support texts of catalog tables (business meaning and writing rule per anchor)."""

    default_evidence: str = NonEmptyText
    default_writing_rule: str = NonEmptyText
    user_supported_evidence: str = NonEmptyText  # {theme}
    user_supported_rule: str = NonEmptyText
    framework_evidence: str = NonEmptyText  # {theme}
    framework_rule: str = NonEmptyText
    reference_evidence: str = NonEmptyText  # {name}
    reference_rule: str = NonEmptyText
    custom_anchor_evidence: str = NonEmptyText  # {row_id}
    custom_anchor_rule: str = NonEmptyText


class PromptLabels(_ProfileModel):
    """Every code-rendered label or sentence the generation model reads, in the package language."""

    key_value_separator: str = NonEmptyText
    list_separator: str = NonEmptyText
    evidence: EvidenceLabels
    structure: StructureLabels
    output: OutputLabels
    table: TableLabels
    table_support: TableSupportLabels


class EvidencePostureText(_ProfileModel):
    source_use: str = NonEmptyText
    assertion_style: str = NonEmptyText


class EvidencePostureTexts(_ProfileModel):
    """The three evidence postures' model-visible wording (levels are code-owned)."""

    block_facts: EvidencePostureText
    context_only: EvidencePostureText
    metric_narrative: EvidencePostureText


class ContextOnlyCalibrationTexts(_ProfileModel):
    """Positive writing examples per source pillar when a block has no company facts."""

    governance: tuple[str, ...] = Field(min_length=1)
    strategy: tuple[str, ...] = Field(min_length=1)
    iro_management: tuple[str, ...] = Field(min_length=1)


class MetricNarrativeProcessLabels(_ProfileModel):
    statistics: str = NonEmptyText
    collection: str = NonEmptyText
    validation: str = NonEmptyText
    tracking: str = NonEmptyText


class MetricNarrativeTexts(_ProfileModel):
    """Wording of the no-value metric narrative authorization rules."""

    process_labels: MetricNarrativeProcessLabels
    purpose: str = NonEmptyText
    two_sentence_structure: str = NonEmptyText  # {processes}
    calibration_sentence: str = NonEmptyText
    prohibitions: str = NonEmptyText
    catalog_selection_lead: str = NonEmptyText
    general_indicator_rule: str = NonEmptyText


class FileAgentTexts(_ProfileModel):
    instructions: str = NonEmptyText
    task_preamble: str = NonEmptyText
    coverage_note: str = NonEmptyText
    completion_note: str = NonEmptyText


class MappingAgentTexts(_ProfileModel):
    instructions: str = NonEmptyText
    task_preamble: str = NonEmptyText
    completion_note: str = NonEmptyText


class ImageAgentTexts(_ProfileModel):
    instructions: str = NonEmptyText
    task_preamble: str = NonEmptyText


class AgentInstructionTexts(_ProfileModel):
    """Instruction texts of the material agents; tool contracts stay code-owned."""

    file_agent: FileAgentTexts
    mapping_agent: MappingAgentTexts
    image_agent: ImageAgentTexts


class ModuleTitleGenerationTexts(_ProfileModel):
    """Wording of the report-module title task; only packages whose modules declare
    titleGenerationGuidance need it."""

    system_instruction: str = NonEmptyText  # {module_count}
    tone: str = NonEmptyText
    tone_label: str = NonEmptyText
    module_id_label: str = NonEmptyText
    requirement_label: str = NonEmptyText
    sections_label: str = NonEmptyText
    h4_titles_label: str = NonEmptyText
    none: str = NonEmptyText


class CompanyBusinessSummaryTexts(_ProfileModel):
    """Instructions and target length (in the package's length unit) of the company summary derivation."""

    instructions: str = NonEmptyText
    target_length: int = Field(gt=0)


class ReportGenerationPromptProfile(_ProfileModel):
    """一套具有明确企业与报告适用范围的报告生成 Prompt Profile。"""

    schema_version: Literal["sustainability_desk.prompt_profile.v1"]
    profile_id: str
    shared_system_segments: GlobalPromptSegments
    labels: PromptLabels
    evidence_postures: EvidencePostureTexts
    context_only_calibration: ContextOnlyCalibrationTexts
    public_risk_disclosure_guidance: str = NonEmptyText
    metric_narrative: MetricNarrativeTexts
    agent_instructions: AgentInstructionTexts
    company_business_summary: CompanyBusinessSummaryTexts
    module_title_generation: ModuleTitleGenerationTexts | None = None


@lru_cache(maxsize=None)
def _load_prompt_profile(package_id: str) -> ReportGenerationPromptProfile:
    package = load_knowledge_package(package_id)
    payload = yaml.safe_load(package.prompt_profile_path.read_text(encoding="utf-8"))
    profile = ReportGenerationPromptProfile.model_validate(payload)
    if profile.profile_id != package.id:
        raise ValueError(
            f"prompt profile id {profile.profile_id!r} does not match package {package.id!r}"
        )
    return profile


def load_prompt_profile(package: KnowledgePackage) -> ReportGenerationPromptProfile:
    """Load the report-generation prompt profile of a knowledge package."""

    return _load_prompt_profile(package.id)


def prompt_labels(package: KnowledgePackage) -> PromptLabels:
    """The package's model-visible labels."""

    return load_prompt_profile(package).labels


def answer_wording(labels: PromptLabels) -> AnswerWording:
    """The words the contract layer needs to project an intake answer to model-visible text."""

    return AnswerWording(
        selected_lead=labels.evidence.selected_lead,
        supplement_lead=labels.evidence.supplement_lead,
        list_separator=labels.list_separator,
        part_separator=labels.evidence.part_separator,
    )
