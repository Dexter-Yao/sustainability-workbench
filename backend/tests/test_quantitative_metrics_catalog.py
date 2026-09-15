# ABOUTME: 轻量披露定量指标目录合同测试，锁定包内指标目录的分组、计数与口径边界。
# ABOUTME: 目录唯一真相源是知识包的 quantitative_metrics.json，无外部参考工作簿。
from __future__ import annotations

import re
from collections import Counter

from sustainability_desk.contract.models import GsTableCell, GsTableRow, QuantitativeMetricDraft, QuantitativeMetricsMeta, ReportMeta
from sustainability_desk.quantitative_metrics import (
    greenhouse_gas_accounting_standard_options,
    all_quantitative_metrics,
    apply_quantitative_metrics_table_projection,
    derived_sum_metric_value,
    quantitative_metric_display_label,
    quantitative_metrics_by_key,
)
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.contract.loader import load_package_contract


def test_lightweight_quantitative_metric_counts_by_sheet() -> None:
    metrics = all_quantitative_metrics(SSE_PACKAGE)

    assert len(metrics) == 149
    assert Counter(metric.sheet for metric in metrics) == {
        "经济+环境": 45,
        "社会": 82,
        "治理": 22,
    }


def test_greenhouse_gas_accounting_standard_options_have_one_backend_owner() -> None:
    assert greenhouse_gas_accounting_standard_options(SSE_PACKAGE) == (
        "《温室气体核算体系》（GHG Protocol）",
        "ISO 14064-1:2018及《工业企业温室气体排放核算和报告通则》（GB/T 32150-2015）",
        "其他",
    )


def test_lightweight_greenhouse_gas_and_water_intensity_guidance() -> None:
    metrics = {metric.key: metric for metric in all_quantitative_metrics(SSE_PACKAGE)}

    # 断言派生指标「说明了自己是算出来的」这一不变量，而非逐字文案——
    # 文案属可迭代内容，钉死原文会让每次措辞打磨都误报为缺陷。
    greenhouse_gas_total = metrics["economic_environment_r07"]
    assert "自动" in greenhouse_gas_total.metricDefinition

    water_intensity = metrics["economic_environment_r44"]
    assert water_intensity.unit == "吨/百万营业收入"
    assert "自动" in water_intensity.metricDefinition


def test_greenhouse_gas_total_is_declared_as_derived_sum() -> None:
    """总量是派生量而非第三个输入：求和关系写在目录里，录入与导入两条通道共同消费。

    标签显式标注口径（范围一+范围二），将来纳入范围三只需追加 sumOfMetricKeys，
    不改任何计算代码，也不会让模型或用户误解总量的边界。
    """
    total = quantitative_metrics_by_key(SSE_PACKAGE)["economic_environment_r07"]

    assert total.sumOfMetricKeys == [
        "economic_environment_r04",
        "economic_environment_r05",
    ]
    assert quantitative_metric_display_label(total) == "温室气体排放总量（范围一+范围二）"


def test_derived_sum_requires_every_source_value() -> None:
    """来源未填齐时不得产出部分求和的数字，只能保持无值。"""
    total = quantitative_metrics_by_key(SSE_PACKAGE)["economic_environment_r07"]

    assert derived_sum_metric_value(
        total,
        {"economic_environment_r04": "200", "economic_environment_r05": "300"},
    ) == "500"
    assert derived_sum_metric_value(
        total,
        {"economic_environment_r04": "200", "economic_environment_r05": None},
    ) is None
    # 十进制求和不得引入二进制浮点误差。
    assert derived_sum_metric_value(
        total,
        {"economic_environment_r04": "0.1", "economic_environment_r05": "0.2"},
    ) == "0.3"


def test_hierarchical_metric_has_unambiguous_standalone_label() -> None:
    metric = quantitative_metrics_by_key(SSE_PACKAGE)["social_r74"]

    assert metric.metricLabel == "境内"
    assert metric.groupPath[-1] == "已授权专利项目数"
    assert quantitative_metric_display_label(metric) == "已授权专利项目数（境内）"


def test_appendix_metrics_table_is_rebuilt_from_quantitative_meta() -> None:
    report = load_package_contract(SSE_PACKAGE)
    report.meta = ReportMeta(
        quantitativeMetrics=QuantitativeMetricsMeta(
            metrics={"economic_environment_r04": QuantitativeMetricDraft(value="12.5")}
        )
    )
    appendix = next(section for section in report.sections if section.key == "report_appendix")
    table = appendix.children[0].blocks[0].table
    table.children.append(
        GsTableRow(
            children=[
                GsTableCell(colKey="category", value="历史缓存"),
                GsTableCell(colKey="metric", value="不应导出"),
            ]
        )
    )

    projected = apply_quantitative_metrics_table_projection(report)
    projected_table = projected.sections[-1].children[0].blocks[0].table
    values = [cell.value for row in projected_table.children if not row.headerRow for cell in row.children]

    assert "不应导出" not in values
    assert "范围一：温室气体排放总量" in values
    assert "12.5" in values


def test_user_visible_metric_text_carries_no_internal_authoring_traces() -> None:
    """用户可见说明是产品文案，不是编写现场。

    remark/sourceComment 若混入署名待办与写给自己的填写指令，会经
    metrics 页拼进用户可见 ⓘ（见 CLAUDE.md「用户可见文本边界与 LLM 上下文边界同级」）。
    此处把「不得出现作者视角与内部痕迹」变成可执行控制，而非仅写在文档里。
    """

    forbidden = ("用户", "这里需要", "自己填", "待业务确认", "仅轻量版", "TODO", "待确认")
    offenders: list[str] = []
    for metric in all_quantitative_metrics(SSE_PACKAGE):
        for field_name in ("metricDefinition", "termExplanation"):
            text = getattr(metric, field_name)
            if any(mark in text for mark in forbidden) or re.match(r"^[a-zA-Z]+\s*[:：]", text):
                offenders.append(f"{metric.key}.{field_name}: {text}")

    assert not offenders, "用户可见说明含内部编写痕迹：" + "；".join(offenders)


def test_lightweight_metrics_all_carry_user_facing_definition() -> None:
    """轻量版是当前唯一开放的指标集合，每一项都应说明要填的是什么。"""

    missing = [m.key for m in all_quantitative_metrics(SSE_PACKAGE) if not m.metricDefinition.strip()]
    assert not missing, f"轻量版指标缺少用户可见说明：{missing}"


def test_group_path_first_level_always_equals_category() -> None:
    """网页与 Excel 都依赖这条恒等式去掉重复的首层分组，破坏它会让重复重新出现。

    网页的分组标题渲染 category，行内面包屑跳过 groupPath[0]；Excel 无分组标题，
    直接渲染完整 groupPath。两者都建立在「首层即 category」之上。
    """

    offenders = [
        metric.key
        for metric in all_quantitative_metrics(SSE_PACKAGE)
        if not metric.groupPath or metric.groupPath[0] != metric.category
    ]

    assert not offenders, f"groupPath 首层与 category 不一致：{offenders}"


def test_appendix_metrics_table_merges_repeated_topic_categories() -> None:
    """同一议题类别的连续行合并首列：首行 rowSpan=段长，被合并行不出该格。

    否则几十行的表里会逐行重复同一议题名。合并约定与
    `contract/table_ops.expanded_rows` 一致，渲染器据 occupied 网格跳过被合并位。
    """

    report = load_package_contract(SSE_PACKAGE)
    report.meta = ReportMeta(
        quantitativeMetrics=QuantitativeMetricsMeta(
            metrics={
                # 同属「应对气候变化」的范围一与范围二，构成一个两行段。
                "economic_environment_r04": QuantitativeMetricDraft(value="112.98"),
                "economic_environment_r05": QuantitativeMetricDraft(value="204.62"),
            }
        )
    )

    projected = apply_quantitative_metrics_table_projection(report)
    table = projected.sections[-1].children[0].blocks[0].table
    rows = [row for row in table.children if not row.headerRow]
    assert rows, "该 fixture 应产出气候类指标行"

    def category_cell(row):
        return next((cell for cell in row.children if cell.colKey == "category"), None)

    head = category_cell(rows[0])
    assert head is not None and head.rowSpan == len(rows)
    # 被合并行不出类别格：渲染器按 rowSpan 占位，多出一格会整行错列。
    assert all(category_cell(row) is None for row in rows[1:])
    assert all(len(row.children) == len(rows[0].children) - 1 for row in rows[1:])


def test_single_row_category_is_not_merged() -> None:
    """段内只有一行时不合并——rowSpan=1 即普通格，不得产生无 continue 的孤立 restart。"""

    report = load_package_contract(SSE_PACKAGE)
    report.meta = ReportMeta(
        quantitativeMetrics=QuantitativeMetricsMeta(
            metrics={"economic_environment_r02": QuantitativeMetricDraft(value="370.42")}
        )
    )

    projected = apply_quantitative_metrics_table_projection(report)
    table = projected.sections[-1].children[0].blocks[0].table
    rows = [row for row in table.children if not row.headerRow]

    assert len(rows) == 1
    category = next(cell for cell in rows[0].children if cell.colKey == "category")
    assert category.rowSpan == 1
