# ABOUTME: 阶段化输入义务的唯一运行时解析器，供工作台、生成和导出门禁共同消费。
# ABOUTME: 本模块只读取 CompiledReportDefinition 与 Report 当前值，不另存必填规则或用户事实。
# ABOUTME(en): The single runtime resolver for phased input obligations, shared by workbench, generation and export.
# ABOUTME(en): Reads only CompiledReportDefinition and the Report's current values; stores no separate rules or facts.
from __future__ import annotations

from sustainability_desk.contract.knowledge_packages import KnowledgePackage, knowledge_package_of
from sustainability_desk.contract.compiled_definition import (
    CompiledInputObligation,
    CompiledReportDefinition,
    load_compiled_report_definition,
)
from sustainability_desk.contract.models import Report, RequiredBefore
from sustainability_desk.contract.visibility import resolve_path, visible

_PHASE_ORDER: dict[RequiredBefore, int] = {
    "workbench": 0,
    "generation": 1,
    "export": 2,
}


def _resolve_definition(
    definition: CompiledReportDefinition | None, package: KnowledgePackage | None
) -> CompiledReportDefinition:
    if definition is not None:
        return definition
    if package is None:
        raise ValueError("input obligations require a compiled definition or a knowledge package")
    return load_compiled_report_definition(package)


def input_obligations_due(
    phase: RequiredBefore,
    *,
    definition: CompiledReportDefinition | None = None,
    package: KnowledgePackage | None = None,
) -> tuple[CompiledInputObligation, ...]:
    """返回截至指定阶段必须完成的义务；可选输入永不成为门禁。"""

    compiled = _resolve_definition(definition, package)
    phase_order = _PHASE_ORDER[phase]
    return tuple(
        obligation
        for obligation in compiled.input_obligations_by_target_handle.values()
        if obligation.required_before is not None
        and _PHASE_ORDER[obligation.required_before] <= phase_order
    )


def required_report_configuration_obligations(
    *,
    definition: CompiledReportDefinition | None = None,
    package: KnowledgePackage | None = None,
) -> tuple[CompiledInputObligation, ...]:
    """返回「报告配置」阶段须由用户填写的字段义务，与门禁阶段无关。

    readiness 面向的是引导用户把基本信息补齐，不等于交付阻断：一个字段可以须填
    （出现在引导清单里），却因正文不引用或承载块自门控而不阻断导出。
    只取 field：议题作答与附录联系方式各有自己的引导阶段，不属报告配置。
    """

    compiled = _resolve_definition(definition, package)
    return tuple(
        obligation
        for obligation in compiled.input_obligations_by_target_handle.values()
        if obligation.obligation == "required_for_readiness"
        and obligation.owner_kind == "field"
    )


def missing_required_report_configuration_obligations(
    report: Report,
    *,
    definition: CompiledReportDefinition | None = None,
) -> tuple[CompiledInputObligation, ...]:
    """解析当前报告缺失的报告配置字段义务，供 readiness 引导消费。"""

    return _missing_among(
        report,
        required_report_configuration_obligations(
            definition=definition,
            package=None if definition is not None else knowledge_package_of(report),
        ),
    )


def missing_input_obligations(
    report: Report,
    phase: RequiredBefore,
    *,
    definition: CompiledReportDefinition | None = None,
) -> tuple[CompiledInputObligation, ...]:
    """解析当前报告在指定阶段缺失的可见义务。"""

    return _missing_among(
        report,
        input_obligations_due(
            phase,
            definition=definition,
            package=None if definition is not None else knowledge_package_of(report),
        ),
    )


def _missing_among(
    report: Report,
    obligations: tuple[CompiledInputObligation, ...],
) -> tuple[CompiledInputObligation, ...]:
    missing: list[CompiledInputObligation] = []
    for obligation in obligations:
        if not visible(obligation, report):
            continue
        resolved, value = resolve_path(obligation.path, report)
        if not resolved or _is_missing(value):
            missing.append(obligation)
            continue
        if (
            obligation.owner_kind == "intake_item"
            and not _intake_obligation_complete(obligation.owner_id, report)
        ):
            missing.append(obligation)
    return tuple(missing)


def _is_missing(value: object | None) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        return not value
    return False


def _intake_obligation_complete(item_key: str, report: Report) -> bool:
    """对带 requiredBefore 的选择题执行其真实选项与分组合同。"""

    item = next((entry for entry in report.intakeItems if entry.key == item_key), None)
    if item is None:
        return False
    if item.kind == "text":
        return bool(
            (isinstance(item.answer, str) and item.answer.strip())
            or (isinstance(item.supplement, str) and item.supplement.strip())
        )
    options = set(item.options or ())
    if item.kind == "single_select":
        return isinstance(item.answer, str) and item.answer in options
    if not isinstance(item.answer, list) or not item.answer:
        return False
    if any(answer not in options for answer in item.answer):
        return False
    return all(
        sum(option in item.answer for option in group.options)
        >= group.minSelections
        for group in item.optionGroups or ()
    )
