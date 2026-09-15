# ABOUTME: 双重重要性评分尺度的确定性校验，供导入、上游输入与实例 Report 共享。
# ABOUTME: 数值边界由 Report.assessmentScoreScale 模板配置拥有；本模块不保留第二份业务阈值。
# ABOUTME(en): Deterministic validation of the double materiality scoring scale, shared by import, inputs and Reports.
# ABOUTME(en): Numeric bounds are owned by Report.assessmentScoreScale; no second copy of business thresholds here.
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from math import isfinite

from sustainability_desk.contract.models import AssessmentScoreScale


def validate_materiality_score(value: object, scale: AssessmentScoreScale) -> float:
    """解析并校验一项原始评分；失败时给出面向用户的尺度原因。"""
    if isinstance(value, bool):
        raise ValueError("评分必须是数值")
    try:
        score = float(value)
    except (TypeError, ValueError):
        raise ValueError("评分必须是数值") from None
    if not isfinite(score):
        raise ValueError("评分必须是有限数值")
    if score <= scale.minimumExclusive:
        raise ValueError(f"评分必须大于 {scale.minimumExclusive:g}")
    if score > scale.maximum:
        raise ValueError(f"评分不得大于 {scale.maximum:g}")

    try:
        multiple = Decimal(str(scale.multipleOf))
        units = Decimal(str(score)) / multiple
    except (InvalidOperation, ValueError):
        raise ValueError("评分格式无效") from None
    if units != units.to_integral_value():
        raise ValueError(f"评分必须按 {scale.multipleOf:g} 的步长填写")
    return score
