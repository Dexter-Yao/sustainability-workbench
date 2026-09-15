# ABOUTME: ESG 定量指标目录读取层，后端作为当前指标 SSOT 供 readiness、API 与附录逻辑消费。
# ABOUTME: 149 项单一权威目录，无档位子集；未作答不是错误，只校验已作答项。
# ABOUTME(en): Read layer over the ESG quantitative metric catalog, the backend SSOT for readiness, API and appendix.
# ABOUTME(en): One authoritative catalog of 149 metrics, no profile subsets; unanswered is not an error, answers are.
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import get_args

from pydantic import BaseModel, ConfigDict, Field

from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    knowledge_package_of,
    load_knowledge_package,
)
from sustainability_desk.contract.models import (
    Block,
    GsTableCell,
    GsTableRow,
    QuantitativeMetricsMeta,
    QuantitativeNoValueReason,
    Report,
    Section,
    QuantitativeMetricsVocabulary,
)
from sustainability_desk.contract.loader import quantitative_metrics_vocabulary
from sustainability_desk.contract.topic_registry import load_topic_contract

# Workbook sheet names are catalog data: each metric names its sheet, and the ordered distinct
# set of those names is the package's sheet list (see quantitative_metric_sheets).
QuantitativeMetricSheet = str


def greenhouse_gas_accounting_standard_options(package: KnowledgePackage) -> tuple[str, ...]:
    """The package's selectable standards followed by its "other" sentinel: workbook list and API options."""

    vocabulary = quantitative_metrics_vocabulary(package)
    return (*vocabulary.greenhouseGasAccountingStandards, vocabulary.otherStandardLabel)

APPENDIX_METRICS_BLOCK_ID = "appendix.esg_key_performance_metrics"


class QuantitativeMetricDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    sheet: QuantitativeMetricSheet
    # Code of the standard's KPI this metric reports (e.g. "A1.1", "D28"); packages whose standard numbers its
    # KPIs print it in the appendix table (kpi_code column) and the content index.
    kpiCode: str | None = None
    category: str
    groupPath: list[str]
    metricLabel: str
    standaloneLabel: str | None = None
    unit: str
    # 声明该指标由目录内其他指标求和得出（如温室气体排放总量＝范围一＋范围二）。
    # 派生关系是目录事实而非某个页面的实现细节：录入端据此自动求和并置为只读，
    # 下游只消费求得的值。将来纳入范围三，只需在此追加 key，无需改动任何计算代码。
    sumOfMetricKeys: list[str] = []
    requiresGreenhouseGasAccountingStandard: bool = False
    # 用户可见两段（design.md §2.2.1）：metricDefinition 常驻指标名下方，说明这一项要填的是什么、
    # 怎么算；termExplanation 折进 ⓘ，承载术语解释与核算口径背景。两段都直接写给用户看，
    # 不得出现「用户……」「这里需要」等作者视角措辞。
    metricDefinition: str = Field(default="", max_length=60)
    termExplanation: str = Field(default="", max_length=80)


@dataclass(frozen=True)
class QuantitativeMetricsValidationIssue:
    """目录内在线录入与 xlsx 导入共用的领域校验结果。"""

    code: str
    message: str
    metric_key: str | None = None


def quantitative_no_value_reasons() -> tuple[str, ...]:
    """从 QuantitativeNoValueReason 合同枚举派生可选值，禁止维护第二份清单。"""

    return tuple(get_args(QuantitativeNoValueReason.__value__))


def quantitative_no_value_reason_labels(package: KnowledgePackage) -> dict[str, str]:
    """无值原因的人类可读注释，按合同枚举顺序；模板说明与附录投影的唯一出口。

    Wording comes from the package so an English or Traditional Chinese workbook does not print
    Simplified Chinese; the enum still fixes the order and the set of keys.
    """

    labels = quantitative_metrics_vocabulary(package).noValueReasonLabels
    return {reason: labels[reason] for reason in quantitative_no_value_reasons()}


@lru_cache(maxsize=None)
def _all_quantitative_metrics(package_id: str) -> tuple[QuantitativeMetricDef, ...]:
    package = load_knowledge_package(package_id)
    data = json.loads(package.quantitative_metrics_path.read_text(encoding="utf-8"))
    metrics = tuple(QuantitativeMetricDef.model_validate(item) for item in data)
    _assert_sum_relations_resolvable(metrics)
    return metrics


def all_quantitative_metrics(package: KnowledgePackage) -> tuple[QuantitativeMetricDef, ...]:
    return _all_quantitative_metrics(package.id)


def quantitative_metric_sheets(package: KnowledgePackage) -> tuple[str, ...]:
    """Workbook sheet names of the package's metric catalog, in first-appearance order."""

    return tuple(dict.fromkeys(metric.sheet for metric in all_quantitative_metrics(package)))


def _assert_sum_relations_resolvable(metrics: tuple[QuantitativeMetricDef, ...]) -> None:
    """加载即校验求和关系自洽：来源须存在、同单位、不自引用、不嵌套派生。

    目录是唯一真相源，这些不变量在此 fail-loud 才能保证下游求和无需再做防御。
    嵌套派生（来源本身也是派生量）当前不支持——真要出现须先明确求值顺序，
    而非让各消费端自行递归。
    """

    by_key = {metric.key: metric for metric in metrics}
    for metric in metrics:
        for source_key in metric.sumOfMetricKeys:
            source = by_key.get(source_key)
            if source is None:
                raise ValueError(
                    f"定量指标 {metric.key} 的求和来源 {source_key} 不在目录中"
                )
            if source_key == metric.key:
                raise ValueError(f"定量指标 {metric.key} 的求和来源不得为自身")
            if source.unit != metric.unit:
                raise ValueError(
                    f"定量指标 {metric.key} 与求和来源 {source_key} 单位不一致："
                    f"{metric.unit} ≠ {source.unit}"
                )
            if source.sumOfMetricKeys:
                raise ValueError(
                    f"定量指标 {metric.key} 的求和来源 {source_key} 本身是派生量，"
                    "暂不支持嵌套求和"
                )


@lru_cache(maxsize=None)
def _quantitative_metrics_by_key(package_id: str) -> dict[str, QuantitativeMetricDef]:
    return {metric.key: metric for metric in _all_quantitative_metrics(package_id)}


def quantitative_metrics_by_key(package: KnowledgePackage) -> dict[str, QuantitativeMetricDef]:
    """按指标 key 索引目录定义，供合同校验与模型上下文投影使用。"""
    return _quantitative_metrics_by_key(package.id)


def validate_complete_quantitative_metrics(
    value: QuantitativeMetricsMeta,
    *,
    package: KnowledgePackage,
    allowed_metric_keys: frozenset[str] | None = None,
) -> tuple[QuantitativeMetricsValidationIssue, ...]:
    """校验已作答指标的二选一语义、目录归属和温室气体核算标准。

    未作答的指标不产出 issue：定量信息是选填页（design.md：
    「整表留空＝暂不提交保持现状」）。若缺 key 与「key 在但两字段
    皆空」走同一条拒绝路径，选填页会实际成为必填页——用户须对全部指标逐个显式声明
    「不填」；目录一扩容（69→149）全部存量报告即刻不可导出，且用户要回去对从没见过
    的指标逐个点选才能恢复。作答与否是用户的选择，只有「作答了却没说清填的是什么」
    才是错误。
    """

    catalog = tuple(
        metric
        for metric in all_quantitative_metrics(package)
        if allowed_metric_keys is None or metric.key in allowed_metric_keys
    )
    required = {metric.key: metric for metric in catalog}
    actual_keys = set(value.metrics)
    issues: list[QuantitativeMetricsValidationIssue] = []
    for key in sorted(actual_keys & set(required)):
        draft = value.metrics[key]
        if (draft.value is None) == (draft.noValueReason is None):
            issues.append(
                QuantitativeMetricsValidationIssue(
                    code="quantitative_value_choice_invalid",
                    metric_key=key,
                    message=f"指标 {key} 必须且只能填写数值或无值原因之一",
                )
            )
    for key in sorted(actual_keys - set(required)):
        issues.append(
            QuantitativeMetricsValidationIssue(
                code="quantitative_key_unexpected",
                metric_key=key,
                message=f"定量信息包含目录外指标：{key}",
            )
        )
    standard = value.greenhouseGasAccountingStandard
    other = str(value.greenhouseGasAccountingStandardOther or "").strip()
    other_label = quantitative_metrics_vocabulary(package).otherStandardLabel
    if standard is not None and standard not in greenhouse_gas_accounting_standard_options(package):
        issues.append(
            QuantitativeMetricsValidationIssue(
                code="ghg_standard_invalid",
                message="温室气体核算标准不在允许范围内",
            )
        )
    if standard == other_label and not other:
        issues.append(
            QuantitativeMetricsValidationIssue(
                code="ghg_standard_other_required",
                message="选择“其他”核算标准时必须填写具体标准",
            )
        )
    if standard != other_label and other:
        issues.append(
            QuantitativeMetricsValidationIssue(
                code="ghg_standard_other_unexpected",
                message="仅选择“其他”核算标准时可填写具体标准",
            )
        )
    requires_standard = any(
        metric.requiresGreenhouseGasAccountingStandard
        and value.metrics.get(metric.key) is not None
        and value.metrics[metric.key].value is not None
        for metric in catalog
    )
    if requires_standard and standard is None:
        issues.append(
            QuantitativeMetricsValidationIssue(
                code="ghg_standard_required",
                message="已填写温室气体指标数值，必须选择核算标准",
            )
        )
    return tuple(issues)


def derived_sum_metric_value(
    metric: QuantitativeMetricDef,
    values_by_key: dict[str, str | None],
) -> str | None:
    """按目录声明的求和关系得出派生值；来源任一缺失或非数值则返回 None。

    用 Decimal 而非 float：报告里的数字不接受二进制浮点误差（0.1+0.2）。
    返回 None 表示派生不成立，调用方应保留无值语义，不得产出部分求和的数字。
    """

    if not metric.sumOfMetricKeys:
        return None
    total = Decimal(0)
    for source_key in metric.sumOfMetricKeys:
        raw = str(values_by_key.get(source_key) or "").strip()
        if not raw:
            return None
        try:
            total += Decimal(raw)
        except InvalidOperation:
            return None
    return format(total.normalize(), "f")


def quantitative_metrics_meta(report: object) -> dict:
    """读取 Report.meta.quantitativeMetrics 投影为字典；兼容 typed ReportMeta 与裸 dict，缺失/形态不符返回空。"""
    meta = getattr(report, "meta", None)
    quant = meta.get("quantitativeMetrics") if isinstance(meta, dict) else getattr(meta, "quantitativeMetrics", None)
    if quant is not None and hasattr(quant, "model_dump"):
        return quant.model_dump()
    return quant if isinstance(quant, dict) else {}


def quantitative_metric_draft(report: object, key: str) -> dict:
    """读取单项指标草稿；仅返回字典形态，避免把异常结构传播到下游。"""
    metrics = quantitative_metrics_meta(report).get("metrics")
    if not isinstance(metrics, dict):
        return {}
    draft = metrics.get(key)
    return draft if isinstance(draft, dict) else {}


def quantitative_metric_value(report: object, key: str) -> str | None:
    """读取已填写指标值；Report 解析边界已将空白和未填写状态归一为空值。"""
    value = quantitative_metric_draft(report, key).get("value")
    text = str(value or "").strip()
    return text or None


def quantitative_metric_display_label(metric: QuantitativeMetricDef) -> str:
    """返回脱离原 Excel 层级后仍完整可理解的指标名称。"""
    standalone = (metric.standaloneLabel or "").strip()
    return standalone or metric.metricLabel.strip()


def _metric_topic_name(metric: QuantitativeMetricDef, *, section_titles: frozenset[str]) -> str:
    """附录第一列只显示议题名称；目录中仅人力资本发展以"-子类"细分 category。

    A category that already names a report section (or has no hyphen) is used as is; otherwise the part
    before the hyphen is used only when it names a section, so "Anti-corruption" is never cut.

    Some categories name no report section by design: they group denominator-style basics that no topic
    chapter owns (sse_zh_hans "经济绩效" and "公司治理-董事会", hkex "Economic Performance"). Those print
    as declared. Only a category meant to name a section yet spelled differently is a defect —
    test_quantitative_metrics_catalog guards that set.
    """

    category = metric.category.strip()
    if category in section_titles or "-" not in category:
        return category
    head = category.split("-", 1)[0].strip()
    return head if head in section_titles else category


def _metric_remark(
    metric: QuantitativeMetricDef,
    draft: dict,
    meta: dict,
    *,
    vocabulary: QuantitativeMetricsVocabulary,
) -> str:
    parts: list[str] = []
    standard = meta.get("greenhouseGasAccountingStandard")
    if standard == vocabulary.otherStandardLabel:
        standard = meta.get("greenhouseGasAccountingStandardOther")
    if metric.requiresGreenhouseGasAccountingStandard and isinstance(standard, str) and standard.strip():
        parts.append(vocabulary.accountingStandardRemarkTemplate.format(standard=standard.strip()))
    note = draft.get("note")
    if isinstance(note, str) and note.strip():
        parts.append(note.strip())
    return vocabulary.remarkSeparator.join(parts)


#: 只进审阅稿、不进正式稿的表格列键。渲染层据此把这些列标为备注色，
#: 使读者一眼看出它们不在对客交付版里；裁列本身仍由投影按 variant 完成。
REVIEW_ONLY_COLUMN_KEYS = frozenset({"remark"})


def _appendix_metric_row(
    metric: QuantitativeMetricDef,
    draft: dict,
    meta: dict,
    *,
    column_keys: tuple[str, ...],
    vocabulary: QuantitativeMetricsVocabulary,
    section_titles: frozenset[str],
) -> GsTableRow:
    """从唯一的定量指标事实投影一行对外附录；不保留采集部门或内部来源定位。

    The contract's appendix table declares which columns exist (category / kpi_code / metric / unit /
    value / remark); the projection fills exactly those, in that order.
    """
    values = {
        "category": _metric_topic_name(metric, section_titles=section_titles),
        "kpi_code": metric.kpiCode or "",
        "metric": metric.metricLabel,
        "unit": metric.unit,
        "value": str(draft["value"]).strip(),
        "remark": _metric_remark(metric, draft, meta, vocabulary=vocabulary),
    }
    unknown = [key for key in column_keys if key not in values]
    if unknown:
        raise ValueError(f"appendix KPI table declares unknown columns: {unknown}")
    return GsTableRow(
        state="ready",
        children=[GsTableCell(colKey=key, value=values[key]) for key in column_keys],
    )


def _merge_repeated_categories(rows: list[GsTableRow]) -> list[GsTableRow]:
    """同一议题类别的连续行合并首列：首行 rowSpan=段长，其余行省略该格。

    指标按议题类别成段出现（catalog 顺序即分组顺序），逐行重复类别名会让读者在
    45 行的表里反复扫同一个词。合并约定与 table_ops.expanded_rows 一致——首行出格并
    rowSpan，被合并的行**不出该格**，渲染器据 occupied 网格跳过（docx_renderer 的
    rowSpan 分支）。同段只有一行时不合并（rowSpan=1 即普通格）。
    """

    merged: list[GsTableRow] = []
    start = 0
    while start < len(rows):
        category = rows[start].children[0].value
        end = start + 1
        while end < len(rows) and rows[end].children[0].value == category:
            end += 1
        span = end - start
        for index in range(start, end):
            row = rows[index]
            if index == start:
                head = row.children[0].model_copy(update={"rowSpan": span})
                merged.append(row.model_copy(update={"children": [head, *row.children[1:]]}))
            else:
                merged.append(row.model_copy(update={"children": list(row.children[1:])}))
        start = end
    return merged


def apply_quantitative_metrics_table_projection(
    report: Report,
    *,
    include_remark_column: bool = True,
) -> Report:
    """从 Report.meta.quantitativeMetrics 重建附录 KPI 表，忽略所有缓存或手工表行。

    定量录入元数据是事实源；附录表只是一份面向阅读和 Word 导出的受控投影。
    口径备注是复核性说明，只进入审阅稿与工作台（include_remark_column=True）；
    正式交付稿不含该列。
    """
    meta = quantitative_metrics_meta(report)
    drafts = meta.get("metrics")
    drafts = drafts if isinstance(drafts, dict) else {}

    def project_header_row(row: GsTableRow, remark_index: int | None) -> GsTableRow:
        # Header cells carry no colKey; the remark header is the cell at the remark column's position.
        if include_remark_column or remark_index is None:
            return row
        return row.model_copy(
            update={"children": [cell for i, cell in enumerate(row.children) if i != remark_index]}
        )

    def project_section(section: Section) -> Section:
        blocks: list[Block] = []
        for block in section.blocks:
            if block.id != APPENDIX_METRICS_BLOCK_ID or block.table is None:
                blocks.append(block)
                continue
            col_defs = block.table.colDefs
            remark_index = next((i for i, col in enumerate(col_defs) if col.key == "remark"), None)
            header_rows = [
                project_header_row(row, remark_index) for row in block.table.children if row.headerRow
            ]
            if not include_remark_column:
                col_defs = [col for col in col_defs if col.key != "remark"]
            column_keys = tuple(col.key for col in col_defs)
            package = knowledge_package_of(report)
            vocabulary = quantitative_metrics_vocabulary(package)
            section_titles = frozenset(
                section.title for section in load_topic_contract(package).source.reportSections
            )
            rows = [
                _appendix_metric_row(
                    metric, draft, meta, column_keys=column_keys, vocabulary=vocabulary, section_titles=section_titles
                )
                for metric in all_quantitative_metrics(package)
                if isinstance((draft := drafts.get(metric.key)), dict)
                and quantitative_metric_value(report, metric.key) is not None
            ]
            rows = _merge_repeated_categories(rows)
            blocks.append(
                block.model_copy(
                    update={
                        "state": "ready" if rows else "omitted",
                        "table": block.table.model_copy(
                            update={
                                "colDefs": col_defs,
                                "children": [*header_rows, *rows],
                            }
                        ),
                    }
                )
            )
        children = [project_section(child) for child in section.children or []]
        return section.model_copy(update={"blocks": blocks, "children": children or None})

    return report.model_copy(update={"sections": [project_section(section) for section in report.sections]})
