# ABOUTME: 定义解析器对原文件结构的能力声明、覆盖计数和显式缺口。
# ABOUTME: 下游否定性判断只能依据完整覆盖状态，不能把未解析内容当成不存在。
# ABOUTME(en): Declares each parser's capability over source structure, its coverage counts and explicit gaps.
# ABOUTME(en): Negative judgements may rely only on complete coverage; unparsed content is never treated as absent.
from __future__ import annotations

from hashlib import sha256
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from sustainability_desk.material.intake.parsed_material_locators import ParsedNodeLocator

type ParseCoverageDisposition = Literal[
    "complete_for_declared_capabilities",
    "incomplete_usable",
    "failed",
]
type ParseGapEffect = Literal[
    "positive_evidence_only",
    "negative_evidence_blocked",
    "source_unusable",
]
type ParseCapability = Literal[
    "text",
    "tables",
    "defined_tables",
    "named_ranges",
    "charts",
    "images",
    "formulas",
    "headers_footers",
    "comments",
    "revisions",
    "layout",
]


class ParseCoverageModel(BaseModel):
    """解析覆盖率合同的严格不可变基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CapabilityCoverage(ParseCoverageModel):
    """单项解析能力对应的源单元与已解析单元计数。"""

    capability: ParseCapability
    source_unit_count: int = Field(ge=0)
    parsed_unit_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _parsed_units_do_not_exceed_source(self) -> "CapabilityCoverage":
        if self.parsed_unit_count > self.source_unit_count:
            raise ValueError("能力已解析单元数不得超过源单元数")
        return self

    @computed_field
    @property
    def complete(self) -> bool:
        """该能力声明范围是否完整解析。"""

        return self.parsed_unit_count == self.source_unit_count


class ParseGap(ParseCoverageModel):
    """解析缺口及其对证据使用的影响。"""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    effect: ParseGapEffect
    locator: ParsedNodeLocator | None = None


class ParseCoverage(ParseCoverageModel):
    """一个资料版本的解析覆盖率结论。"""

    disposition: ParseCoverageDisposition
    source_units_total: int = Field(ge=0)
    source_units_parsed: int = Field(ge=0)
    text_characters_parsed: int = Field(ge=0)
    table_cells_parsed: int = Field(ge=0)
    capabilities: tuple[CapabilityCoverage, ...]
    gaps: tuple[ParseGap, ...] = ()

    @model_validator(mode="after")
    def _validate_disposition(self) -> "ParseCoverage":
        if self.source_units_parsed > self.source_units_total:
            raise ValueError("已解析源单元数不得超过源单元总数")
        capability_names = [
            capability.capability for capability in self.capabilities
        ]
        if len(capability_names) != len(set(capability_names)):
            raise ValueError("同一解析能力只能声明一次")

        all_capabilities_complete = all(
            capability.complete for capability in self.capabilities
        )
        if self.disposition == "complete_for_declared_capabilities":
            if self.source_units_parsed != self.source_units_total:
                raise ValueError("完整覆盖状态要求源单元全部解析")
            if not all_capabilities_complete:
                raise ValueError("完整覆盖状态要求全部声明能力完整")
            if self.gaps:
                raise ValueError("完整覆盖状态不得同时声明解析缺口")
        elif self.disposition == "failed":
            if not any(gap.effect == "source_unusable" for gap in self.gaps):
                raise ValueError("解析失败必须声明 source_unusable 缺口")
        return self

    @computed_field
    @property
    def allows_negative_evidence(self) -> bool:
        """是否允许下游把未命中解释为材料中不存在。"""

        return self.disposition == "complete_for_declared_capabilities" and not any(
            gap.effect in {"negative_evidence_blocked", "source_unusable"}
            for gap in self.gaps
        )


def parse_coverage_fingerprint(coverage: ParseCoverage) -> str:
    """生成覆盖率合同的确定性 SHA-256 指纹。"""

    canonical = json.dumps(
        coverage.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()
