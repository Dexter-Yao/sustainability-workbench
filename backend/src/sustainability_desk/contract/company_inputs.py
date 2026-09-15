# ABOUTME: 合成/生产公司「上游输入」的 typed parse-first 契约——只暴露用户真正提供的原料，派生字段绝不进此层。
# ABOUTME: extra=forbid + 逐项校验（字段 key∈user_input、intake 作答合 kind、topic id∈registry），捏造上游不产的数据即 fail-loud。
# ABOUTME(en): Typed parse-first contract for company upstream inputs: only what the user gave, no derived fields.
# ABOUTME(en): Bound to one knowledge package; per-item checks (field key, answer kind, topic id) fail loud on fabrication.
from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    load_knowledge_package,
)
from sustainability_desk.contract.loader import load_package_contract
from sustainability_desk.contract.materiality_scoring import validate_materiality_score
from sustainability_desk.contract.models import (
    AppendixPackage,
    DisclosureProfile,
    IntakeItem,
    MaterialityAssessmentInput,
    QuantitativeMetricsMeta,
)
from sustainability_desk.contract.topic_registry import all_assessment_topics
from sustainability_desk.planner import load_topic_intake

# 派生字段绝不由上游输入提供（现算）；显式列出以给出可读报错。
_DERIVED_FIELD_KEYS = frozenset({"industry", "company_business_summary"})


@lru_cache(maxsize=None)
def _user_input_field_keys(package_id: str) -> frozenset[str]:
    contract = load_package_contract(load_knowledge_package(package_id))
    return frozenset(k for k, f in contract.fields.items() if f.source == "user_input")


@lru_cache(maxsize=None)
def _intake_defs(package_id: str) -> dict[str, IntakeItem]:
    package = load_knowledge_package(package_id)
    contract = load_package_contract(package)
    defs: dict[str, IntakeItem] = {item.key: item for item in contract.intakeItems}
    for item in load_topic_intake(package):
        defs[item.key] = item
    return defs


@lru_cache(maxsize=None)
def _scored_assessment_topic_ids(package_id: str) -> frozenset[str]:
    return frozenset(
        topic.id
        for topic in all_assessment_topics(load_knowledge_package(package_id))
        if topic.materialityDetermination.kind == "scored"
    )


@lru_cache(maxsize=None)
def _assessment_score_scale(package_id: str):
    scale = load_package_contract(load_knowledge_package(package_id)).assessmentScoreScale
    if scale is None:
        raise ValueError("报告模板未声明双重重要性评分尺度")
    return scale


class IntakeAnswerSpec(BaseModel):
    """一道内容清单题的作答——answer 形状在 CompanyInputs 校验时对齐 IntakeItem.kind。"""

    model_config = ConfigDict(extra="forbid")

    answer: str | list[str] | None = None
    supplement: str | None = None


class CompanyInputs(BaseModel):
    """公司「上游输入」的 parse-first 契约：只含用户真正提供的原料，派生量（industry/summary/materiality）不在此层。

    business_summary 为「简介压缩步骤（上下文工程步骤0）产物」的 typed 占位——eval 直接给定，避免每轮跑 LLM；
    其为 derived 产物的显式命名边界，而非藏在 fields 里的手设派生字段。

    knowledgePackageId names the package whose contract every key is validated against; fixtures
    never author it — ``parse_company_inputs`` injects it from the package they are parsed for.
    """

    model_config = ConfigDict(extra="forbid")

    knowledgePackageId: str
    fields: dict[str, str | int | float] = {}
    company_profile: str = ""
    business_summary: str = ""
    intake: dict[str, IntakeAnswerSpec] = {}
    assessmentInput: MaterialityAssessmentInput | None = None
    # Packages with a fixed disclosure basis (no mainland standard choice) never collect this;
    # the default keeps their inputs free of a choice that does not exist for them.
    disclosureProfile: DisclosureProfile = DisclosureProfile()
    appendixPackage: AppendixPackage = AppendixPackage()
    quantitativeMetrics: QuantitativeMetricsMeta | None = None
    materialityStrategy: Literal["complete_coverage"] | None = None

    @property
    def knowledge_package(self) -> KnowledgePackage:
        return load_knowledge_package(self.knowledgePackageId)

    @model_validator(mode="after")
    def _validate_fields_are_user_input(self) -> CompanyInputs:
        allowed = _user_input_field_keys(self.knowledgePackageId)
        for key in self.fields:
            if key in _DERIVED_FIELD_KEYS:
                raise ValueError(f"派生字段 {key!r} 不得由上游输入提供（现算）")
            if key not in allowed:
                raise ValueError(f"未知或非 user_input 字段 key：{key!r}")
        return self

    @model_validator(mode="after")
    def _validate_intake_answers(self) -> CompanyInputs:
        defs = _intake_defs(self.knowledgePackageId)
        for key, spec in self.intake.items():
            if key == "company_profile":
                raise ValueError(
                    "company_profile 只能由 CompanyInputs.company_profile 提供"
                )
            item = defs.get(key)
            if item is None:
                raise ValueError(f"未知内容清单项 key：{key!r}")
            _validate_answer_shape(item, spec.answer)
        return self

    @model_validator(mode="after")
    def _validate_assessment_scores(self) -> CompanyInputs:
        if self.materialityStrategy == "complete_coverage":
            if self.assessmentInput is not None:
                raise ValueError("完整议题覆盖策略不得携带或伪造重要性评分")
            return self
        if self.assessmentInput is None:
            raise ValueError("非完整议题覆盖策略必须提供重要性评分输入")
        scale = _assessment_score_scale(self.knowledgePackageId)
        scored_ids = _scored_assessment_topic_ids(self.knowledgePackageId)
        for score in self.assessmentInput.scores:
            if score.assessmentTopicId not in scored_ids:
                raise ValueError(f"未知评分议题 id：{score.assessmentTopicId!r}（不在 topic_registry）")
            validate_materiality_score(score.financialScore, scale)
            validate_materiality_score(score.impactScore, scale)
        return self


def parse_company_inputs(raw: dict[str, Any], *, package: KnowledgePackage) -> CompanyInputs:
    """Parse authored upstream inputs for one package; the package identity is never authored."""

    if "knowledgePackageId" in raw:
        raise ValueError("knowledgePackageId is bound by the parser, not authored in fixtures")
    return CompanyInputs.model_validate({**raw, "knowledgePackageId": package.id})


def _validate_answer_shape(item: IntakeItem, answer: str | list[str] | None) -> None:
    """作答形状须与 IntakeItem.kind 一致；选择题取值须 ∈ options（防伪造选项）。"""
    if answer is None:
        return
    options = set(item.options or [])
    if item.kind == "text":
        if not isinstance(answer, str):
            raise ValueError(f"清单项 {item.key}（text）作答应为字符串，实为 {type(answer).__name__}")
    elif item.kind == "single_select":
        if not isinstance(answer, str) or answer not in options:
            raise ValueError(f"清单项 {item.key}（single_select）作答须为选项之一：{sorted(options)}")
    elif item.kind == "multi_select":
        if not isinstance(answer, list) or any(a not in options for a in answer):
            raise ValueError(f"清单项 {item.key}（multi_select）作答须为选项子集：{sorted(options)}")
