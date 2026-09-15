# ABOUTME: 生成证据姿态合同，根据解析后的块级事实强度统一生成与 Judge 的事实使用边界。
# ABOUTME: 有块级事实时允许相关的一般性正向归纳；新增具体或负向事实必须有直接依据。
# ABOUTME(en): Generation evidence posture contract: one fact-usage boundary for generation and Judge alike.
# ABOUTME(en): Levels and the resolution rule are code-owned; the wording of each posture belongs to the
# ABOUTME(en): package prompt profile (EvidencePostureTexts), so the model reads it in the report language.
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from sustainability_desk.llm.prompt_profiles import EvidencePostureTexts

EvidenceLevel = Literal["block_facts", "context_only", "metric_narrative"]


class EvidencePosture(BaseModel):
    """当前生成任务可如何使用输入证据的类型化语义。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    level: EvidenceLevel
    sourceUse: str
    assertionStyle: str


def evidence_posture(texts: EvidencePostureTexts, level: EvidenceLevel) -> EvidencePosture:
    """A posture of the given level, worded by the package profile."""

    text = getattr(texts, level)
    return EvidencePosture(
        level=level, sourceUse=text.source_use, assertionStyle=text.assertion_style
    )


def resolve_evidence_posture(
    texts: EvidencePostureTexts,
    *,
    substantive_input_present: bool,
    metric_narrative: bool = False,
) -> EvidencePosture:
    """根据 parse-first 的块级事实判定返回唯一证据姿态。

    Wording notes kept from the SSE profile authoring: the block_facts assertion style separates
    "facts fit the task" from "facts do not fit", and ends with the per-fact relevance test; the
    placement of that sentence measurably changes how often unrelated user facts leak into a block.
    """

    if metric_narrative:
        return evidence_posture(texts, "metric_narrative")
    return evidence_posture(
        texts, "block_facts" if substantive_input_present else "context_only"
    )
