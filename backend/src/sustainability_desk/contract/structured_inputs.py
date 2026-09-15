# ABOUTME: 结构化输入工作簿的上下文指纹与 typed 校验错误，供重要性和定量导入共同消费。
# ABOUTME: 指纹只覆盖工作簿实际依赖的 Report 事实及权威目录，避免无关正文变化制造虚假过期。
# ABOUTME(en): Context fingerprints and typed validation errors for structured input workbooks.
# ABOUTME(en): A fingerprint covers only the Report facts the workbook depends on, so unrelated edits cannot fake it.
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from sustainability_desk.contract.knowledge_packages import knowledge_package_of
from sustainability_desk.contract.loader import load_package_contract
from sustainability_desk.contract.models import IntakeItem, Report, ReportContractModel
from sustainability_desk.contract.topic_registry import (
    TECHNOLOGY_ETHICS_FIELD,
    applicable_scoring_topics,
    load_topic_contract,
)

STRUCTURED_INPUT_METADATA_SHEET = "_模板元数据"
type StructuredInputKind = Literal[
    "assessment",
    "quantitative_metrics",
    "topic_questions",
    "report_basics",
    "unified_workbook",
]
type StructuredInputStatus = Literal[
    "missing",
    "unverified",
    "stale",
    "current",
]


class StructuredInputContext(ReportContractModel):
    """工作簿生成与导入共享的不可猜测运行上下文。"""

    reportId: UUID
    contractVersion: str = Field(min_length=1)
    compiledSemanticsVersion: str = Field(min_length=1)


class StructuredInputFreshness(ReportContractModel):
    """V4 只保存最近一次成功导入所对应的上下文，不复制工作簿内容。"""

    assessmentContextFingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    quantitativeMetricsContextFingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class StructuredInputCellError(ReportContractModel):
    """可由前端稳定定位到工作簿单元格的导入错误。"""

    code: str = Field(min_length=1)
    sheet: str = Field(min_length=1)
    row: int = Field(ge=1)
    column: str = Field(min_length=1)
    message: str = Field(min_length=1)


class StructuredInputWorkbookError(ValueError):
    """整份工作簿校验失败；errors 包含全部已发现问题，不返回部分解析结果。"""

    def __init__(self, errors: list[StructuredInputCellError]) -> None:
        if not errors:
            raise ValueError("StructuredInputWorkbookError 至少需要一个错误")
        self.errors = tuple(errors)
        super().__init__("；".join(error.message for error in errors))


def canonical_json_sha256(value: object) -> str:
    """以稳定 JSON 编码生成 sha256；禁止依赖 Python repr 或字典插入顺序。"""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _field_value(report: Report, key: str) -> str | int | float | None:
    field = report.fields.get(key)
    return field.value if field is not None else None


def _base_context(context: StructuredInputContext) -> dict[str, str]:
    return {
        "reportId": str(context.reportId),
        "contractVersion": context.contractVersion,
        "compiledSemanticsVersion": context.compiledSemanticsVersion,
    }


def assessment_context_fingerprint(
    report: Report,
    context: StructuredInputContext,
) -> str:
    """指纹化重要性模板真实依赖：适用性、评分尺度与议题注册表。"""

    technology_ethics = _field_value(report, TECHNOLOGY_ETHICS_FIELD)
    score_scale = report.assessmentScoreScale
    if score_scale is None:
        score_scale = load_package_contract(knowledge_package_of(report)).assessmentScoreScale
    if score_scale is None:
        raise ValueError("报告模板未声明双重重要性评分尺度")
    payload = {
        **_base_context(context),
        "kind": "assessment",
        "reportingYear": _field_value(report, "reporting_year"),
        "technologyEthicsSensitiveActivity": technology_ethics,
        "scoreScale": score_scale.model_dump(mode="json"),
        "scoredTopicIds": [
            topic.id for topic in applicable_scoring_topics(report)
        ],
    }
    return canonical_json_sha256(payload)


def quantitative_metrics_context_fingerprint(
    report: Report,
    context: StructuredInputContext,
) -> str:
    """指纹化定量答案的口径依赖：企业边界与报告期间。

    指纹回答的是「用户已填的数值还成不成立」，不是「目录有没有变过」。故不含
    contractVersion/compiledSemanticsVersion，也不含目录清单：新增一项指标不改变
    已填数值的口径，把它算进来会使全部存量报告在合同升级当天失效，而用户要回去对
    从没见过的指标逐个声明「不填」才能恢复。
    真正使答案失效的是企业边界与报告期间变化，二者在下方 payload 中。

    目录变更由完整性校验各自负责：缺失的指标是「未作答」，不是「答案失效」。
    """

    payload = {
        "reportId": str(context.reportId),
        "kind": "quantitative_metrics",
        "companyRegisteredName": _field_value(
            report,
            "company_registered_name",
        ),
        "reportingYear": _field_value(report, "reporting_year"),
        "reportPeriodStart": _field_value(report, "report_period_start"),
        "reportPeriodEnd": _field_value(report, "report_period_end"),
        "consolidationScope": _field_value(report, "consolidation_scope"),
    }
    return canonical_json_sha256(payload)


def topic_question_items(
    report: Report,
    *,
    allowed_report_section_ids: frozenset[str] | None = None,
) -> tuple[IntakeItem, ...]:
    """从装配后 Report 过滤议题引导问题（front_* 报告级题归基础资料面）。

    模板、解析器与指纹必须共用本过滤，避免三处各自定义「议题题」产生漂移。
    """

    topic_section_ids = set(load_topic_contract(knowledge_package_of(report)).reportSectionsById)
    return tuple(
        item
        for item in report.intakeItems
        if item.contentScopeId in topic_section_ids
        and (
            allowed_report_section_ids is None
            or item.contentScopeId in allowed_report_section_ids
        )
    )


def topic_questions_context_fingerprint(
    report: Report,
    context: StructuredInputContext,
    *,
    allowed_report_section_ids: frozenset[str] | None = None,
) -> str:
    """指纹化议题问题模板真实依赖：题目集合、题型、选项与对齐约束。

    题干与提示文案不入指纹——它们不影响解析对齐与合法值；议题装配范围
    （评分结果、适用性）的变化经题目集合变化自然反映。
    """

    items = topic_question_items(
        report,
        allowed_report_section_ids=allowed_report_section_ids,
    )
    payload = {
        **_base_context(context),
        "kind": "topic_questions",
        "items": [
            {
                "key": item.key,
                "contentScopeId": item.contentScopeId,
                "kind": item.kind,
                "options": item.options,
                "optionGroups": (
                    [
                        {
                            "key": group.key,
                            "options": group.options,
                            "minSelections": group.minSelections,
                        }
                        for group in item.optionGroups
                    ]
                    if item.optionGroups
                    else None
                ),
                "minChars": item.minChars,
                "maxChars": item.maxChars,
            }
            for item in items
        ],
    }
    return canonical_json_sha256(payload)


def context_metadata_values(
    *,
    input_kind: StructuredInputKind,
    context: StructuredInputContext,
    context_fingerprint: str,
) -> dict[str, str]:
    """投影两类工作簿共有的身份与合同元数据。"""

    return {
        "input_kind": input_kind,
        "report_id": str(context.reportId),
        "contract_version": context.contractVersion,
        "compiled_semantics_version": context.compiledSemanticsVersion,
        "context_fingerprint": context_fingerprint,
    }


def quantitative_metadata_values(
    *,
    report: Report,
    context: StructuredInputContext,
    context_fingerprint: str,
) -> dict[str, str]:
    """投影定量工作簿副本；解析器只核对，不将企业和期间副本回写 Report。"""

    company_name = _field_value(report, "company_registered_name") or ""
    period_start = _field_value(report, "report_period_start") or ""
    period_end = _field_value(report, "report_period_end") or ""
    return {
        **context_metadata_values(
            input_kind="quantitative_metrics",
            context=context,
            context_fingerprint=context_fingerprint,
        ),
        "company_name": str(company_name),
        "report_period": f"{period_start} 至 {period_end}".strip(),
        "consolidation_scope": str(
            _field_value(report, "consolidation_scope") or ""
        ),
    }


def append_metadata_sheet(workbook: Any, values: Mapping[str, str]) -> None:
    """写入机器可读元数据页；该页隐藏，用户可见副本由业务工作表另行展示。"""

    worksheet = workbook.create_sheet(STRUCTURED_INPUT_METADATA_SHEET)
    worksheet.append(["字段", "值"])
    for key, value in values.items():
        worksheet.append([key, value])
    worksheet.sheet_state = "hidden"


# 元数据页是模板身份，不是用户填写面。四类不一致对用户是同一件事：这份表格不是当前模板。
# 因此对外只给这一句可执行文案，键名、指纹与 report_id 只留在 code 与日志里。
STALE_WORKBOOK_MESSAGE = (
    "这份表格与当前模板不一致，可能是旧版本。请重新下载模板并填写后再导入。"
)


def validate_metadata_sheet(
    workbook: Any,
    expected: Mapping[str, str],
) -> list[StructuredInputCellError]:
    """严格核对副本元数据并累计全部缺失、重复和不一致问题。

    对外只投影稳定 code 与 ``STALE_WORKBOOK_MESSAGE``；元数据键名属内部标识，
    不进用户可见文本（键名之一是 ``report_id``）。
    """

    if STRUCTURED_INPUT_METADATA_SHEET not in workbook.sheetnames:
        return [
            StructuredInputCellError(
                code="metadata_sheet_missing",
                sheet=STRUCTURED_INPUT_METADATA_SHEET,
                row=1,
                column="A",
                message=STALE_WORKBOOK_MESSAGE,
            )
        ]

    worksheet = workbook[STRUCTURED_INPUT_METADATA_SHEET]
    found: dict[str, tuple[str, int]] = {}
    errors: list[StructuredInputCellError] = []
    for row_number, row in enumerate(
        worksheet.iter_rows(min_row=2, values_only=True),
        start=2,
    ):
        raw_key = row[0] if row else None
        if raw_key is None or not str(raw_key).strip():
            continue
        key = str(raw_key).strip()
        value = "" if len(row) < 2 or row[1] is None else str(row[1]).strip()
        if key in found:
            errors.append(
                StructuredInputCellError(
                    code="metadata_duplicate",
                    sheet=worksheet.title,
                    row=row_number,
                    column="A",
                    message=STALE_WORKBOOK_MESSAGE,
                )
            )
            continue
        found[key] = (value, row_number)

    for key, expected_value in expected.items():
        actual = found.get(key)
        if actual is None:
            errors.append(
                StructuredInputCellError(
                    code="metadata_missing",
                    sheet=worksheet.title,
                    row=1,
                    column="A",
                    message=STALE_WORKBOOK_MESSAGE,
                )
            )
        elif actual[0] != expected_value:
            errors.append(
                StructuredInputCellError(
                    code="metadata_mismatch",
                    sheet=worksheet.title,
                    row=actual[1],
                    column="B",
                    message=STALE_WORKBOOK_MESSAGE,
                )
            )
    return errors
