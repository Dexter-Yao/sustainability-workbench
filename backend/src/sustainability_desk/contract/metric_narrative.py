# ABOUTME: 无报告期数值时的指标正文产品授权合同，供生成、Judge 和审阅投影共同消费。
# ABOUTME: 该合同只描述允许的披露阶段与过程，不把指标缺值伪装成企业提供的事实。
# ABOUTME(en): Product authorization contract for metric prose when no reporting-period value exists.
# ABOUTME(en): Describes only the permitted disclosure stage and process; never dresses a missing metric up as a fact.
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, model_validator

if TYPE_CHECKING:
    from sustainability_desk.llm.prompt_profiles import MetricNarrativeTexts


class MetricNarrativePolicy(BaseModel):
    """financial/dual 无值指标 H4 的 agent-readable 产品授权。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["building_without_values"] = "building_without_values"
    indicator_source: Literal["catalog", "generated_general"]
    catalog_metric_labels: tuple[str, ...] = ()
    allowed_stage: Literal["building"] = "building"
    allowed_processes: tuple[
        Literal["statistics", "collection", "validation", "tracking"], ...
    ] = ("statistics", "collection", "validation", "tracking")
    future_disclosure_allowed: Literal[True] = True

    @model_validator(mode="after")
    def validate_indicator_source(self) -> MetricNarrativePolicy:
        if self.indicator_source == "catalog" and not self.catalog_metric_labels:
            raise ValueError("catalog 指标正文必须提供目录指标名称")
        if self.indicator_source == "generated_general" and self.catalog_metric_labels:
            raise ValueError("generated_general 指标正文不得携带目录指标名称")
        if len(self.catalog_metric_labels) != len(set(self.catalog_metric_labels)):
            raise ValueError("catalog_metric_labels 不得重复")
        if len(self.allowed_processes) != len(set(self.allowed_processes)):
            raise ValueError("allowed_processes 不得重复")
        return self


def metric_narrative_policy_rules(
    policy: MetricNarrativePolicy, texts: MetricNarrativeTexts, *, list_separator: str
) -> tuple[str, ...]:
    """把 typed policy 投影为生成、Judge 和人工审阅共同使用的可读规则；措辞由包 profile 拥有。"""

    processes = list_separator.join(
        getattr(texts.process_labels, item) for item in policy.allowed_processes
    )
    rules = [
        texts.purpose,
        texts.two_sentence_structure.format(processes=processes),
        texts.calibration_sentence,
        texts.prohibitions,
    ]
    if policy.indicator_source == "catalog":
        rules.append(
            texts.catalog_selection_lead + list_separator.join(policy.catalog_metric_labels)
        )
    else:
        rules.append(texts.general_indicator_rule)
    return tuple(rules)
