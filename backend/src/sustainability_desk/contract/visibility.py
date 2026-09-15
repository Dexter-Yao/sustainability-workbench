# ABOUTME: 条件可见性与 assessment 引用解析的合同层实现，供生成、诊断与导出共用。
# ABOUTME: 本模块不依赖导出或 LLM 层；未知路径和未知操作按 fail-closed 处理。
# ABOUTME(en): Contract-layer conditional visibility and assessment reference resolution, shared across the codebase.
# ABOUTME(en): Depends on neither the export nor the LLM layer; unknown paths and operators are handled fail-closed.
from __future__ import annotations

from sustainability_desk.contract.models import ConditionRule, Report
from sustainability_desk.contract.report_values import resolve_report_ref
from sustainability_desk.quantitative_metrics import quantitative_metric_value

_COUNT_KEYS = {"dual", "impact_only", "financial_only", "non_material"}
_COUNT_ALIASES = {"impact": "impact_only", "financial": "financial_only", "non": "non_material"}


def find_block(report: Report, block_id: str):
    """按 block id 在 Report 中查找块；未找到返回 None。"""
    for block in report.iter_blocks():
        if block.id == block_id:
            return block
    return None


def assessment_counts(report: Report) -> dict[str, int]:
    """返回双重重要性象限计数，供条件与行内引用共用。"""
    counts = {"dual": 0, "impact_only": 0, "financial_only": 0, "non_material": 0}
    for topic in report.assessment.topics if report.assessment else []:
        if topic.materiality == "dual":
            counts["dual"] += 1
        elif topic.materiality == "impact":
            counts["impact_only"] += 1
        elif topic.materiality == "financial":
            counts["financial_only"] += 1
        elif topic.materiality == "non":
            counts["non_material"] += 1
    return counts


def assessment_value(ref: str, report: Report):
    """解析 assessment.* 引用；无法解析返回 None。"""
    if ref.startswith("assessment.counts."):
        key = ref[len("assessment.counts."):]
        key = _COUNT_ALIASES.get(key, key)
        if key in _COUNT_KEYS:
            return assessment_counts(report)[key]
    if ref.startswith("assessment.topics.") and ref.endswith(".materiality"):
        topic_id = ref[len("assessment.topics."):-len(".materiality")]
        topics = report.assessment.topics if report.assessment else []
        topic = next(
            (entry for entry in topics if entry.assessmentTopicId == topic_id), None
        )
        return topic.materiality if topic else None
    return None


def resolve_path(path: str, report: Report) -> tuple[bool, object | None]:
    """解析条件路径；ok=False 表示无法解析，调用方应 fail-closed。"""
    if path.startswith("fields.") and path.endswith(".value"):
        field = report.fields.get(path[len("fields."):-len(".value")])
        return True, (field.value if field is not None else None)
    if path.startswith("intakeItems."):
        key = path[len("intakeItems."):]
        item = next((entry for entry in report.intakeItems if entry.key == key), None)
        answer = item.answer if item else None
        if isinstance(answer, str):
            answer = answer.strip() or None
        elif isinstance(answer, list):
            answer = answer or None
        supplement = (
            item.supplement.strip()
            if item and isinstance(item.supplement, str) and item.supplement.strip()
            else None
        )
        return True, (answer or supplement)
    if path.startswith("quantitativeMetrics."):
        key = path[len("quantitativeMetrics."):]
        return True, quantitative_metric_value(report, key)
    if path.startswith("disclosureProfile.") or path.startswith("appendixPackage."):
        return True, resolve_report_ref(path, report)
    # 议题重要性策略是报告级事实（用户是否评分），不是账户权益。
    # 权益（EffectiveReportScope）按设计不进 Report，故条件只能读这里。
    if path == "meta.materialityStrategy":
        return True, (report.meta.materialityStrategy if report.meta else None)
    if path.startswith("assessment."):
        return True, assessment_value(path, report)
    if path.startswith("blocks.") and path.endswith(".state"):
        block = find_block(report, path[len("blocks."):-len(".state")])
        return True, (block.state if block else None)
    return False, None


def _is_empty(value: object | None) -> bool:
    return value in (None, "", False)


def eval_rule(rule: ConditionRule, report: Report, issues: list[dict] | None = None) -> bool:
    """求值单条条件规则；未知 path/op 均 fail-closed。"""
    ok, value = resolve_path(rule.path, report)
    if not ok:
        if issues is not None:
            issues.append({"path": rule.path, "op": rule.op, "reason": "无法解析的 path（fail-closed）"})
        return False
    op = rule.op
    if op == "exists":
        return not _is_empty(value)
    if op == "not_exists":
        return _is_empty(value)
    if op == "eq":
        return value == rule.value
    if op == "ne":
        return value != rule.value
    if op == "gt":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and isinstance(rule.value, (int, float))
            and value > rule.value
        )
    if op == "in":
        if not isinstance(rule.value, (list, tuple)):
            return False
        if isinstance(value, (list, tuple)):
            return any(entry in rule.value for entry in value)
        return value in rule.value
    if op == "contains_any":
        if not isinstance(rule.value, (list, tuple)):
            return False
        haystack = "、".join(str(entry) for entry in value) if isinstance(value, (list, tuple)) else str(value or "")
        return any(str(needle) in haystack for needle in rule.value if str(needle).strip())
    if issues is not None:
        issues.append({"path": rule.path, "op": op, "reason": "未知 op（fail-closed）"})
    return False


def visible(node, report: Report, issues: list[dict] | None = None) -> bool:
    """判断节点是否可见；无 appears_when 时默认可见。"""
    condition = getattr(node, "appears_when", None)
    if not condition:
        return True
    if condition.all:
        return all(eval_rule(rule, report, issues) for rule in condition.all)
    if condition.any:
        return any(eval_rule(rule, report, issues) for rule in condition.any)
    return True


def visible_block_in_report(report: Report, block_id: str, issues: list[dict] | None = None) -> bool:
    """判断块在当前报告可见章节路径内是否可见；任一祖先章节隐藏即隐藏。"""

    def walk(sections) -> bool | None:
        for section in sections:
            if not visible(section, report, issues):
                continue
            for block in section.blocks:
                if block.id == block_id:
                    return visible(block, report, issues)
            found = walk(section.children or [])
            if found is not None:
                return found
        return None

    return bool(walk(report.sections))
