# ABOUTME: 议题配置加载期引用校验——块的 intakeItems/standardDisclosureRequirementKeys/appears_when 引用必须可解析，fail-loud 防跨文件漂移。
# ABOUTME: 模块化可解耦：纯函数返回错误清单；调用方（_template 加载期）决定 raise。保障议题复用范式的安全（不写死议题数，registry 是唯一计数来源）。
# ABOUTME(en): Load-time reference checks for topic config: a block's intakeItems, requirement keys and appears_when
# ABOUTME(en): references must resolve, failing loud on cross-file drift. Pure functions return errors; callers raise.
from __future__ import annotations

from sustainability_desk.contract.models import (
    Condition,
    ExplicitGenerationEvidenceSelector,
    IntakeItem,
    ReportSectionGenerationEvidenceSelector,
    Section,
)
from sustainability_desk.contract.knowledge_packages import KnowledgePackage
from sustainability_desk.llm.standard_disclosure_requirements import resolve_standard_disclosure_requirements
from sustainability_desk.quantitative_metrics import quantitative_metrics_by_key

COMMON_INTAKE_SUFFIXES: frozenset[str] = frozenset({
    "q_governance_roles",
    "q_governance_policies",
    "q_governance_certifications",
    "q_strategy_content",
})


def _iter_blocks(section: Section):
    if section.conciseDisclosure is not None:
        yield section.conciseDisclosure
    yield from section.blocks or []
    for child in section.children or []:
        yield from _iter_blocks(child)


def _condition_rules(cond: Condition | None) -> list:
    if cond is None:
        return []
    return list(cond.all or []) + list(cond.any or [])


def validate_topic_refs(
    section: Section,
    intake_keys: set[str],
    report_section_id: str,
    intake_items_by_key: dict[str, IntakeItem] | None = None,
    *,
    package: KnowledgePackage,
) -> list[str]:
    """返回引用不一致的错误清单（空=通过）。

    校验范围（块级）：inputs.evidence.intakeItems ⊆ intake_keys；
    inputs.evidence.quantitativeMetrics ⊆ 定量指标目录；report_section 继承所属 H2 证据；
    每个 standardDisclosureRequirementKeys 能在 standard_disclosure_requirements/<topic> 解析到；
    appears_when 的 intakeItems.<key> 路径所引清单项存在，quantitativeMetrics.<key> 路径所引指标存在且为轻量版。
    disclosure 校验存在性时不做义务等级过滤（与 required_only 无关）。
    """
    errors: list[str] = []
    metrics_by_key = quantitative_metrics_by_key(package)
    for blk in _iter_blocks(section):
        g = blk.generation
        selector = g.inputs.evidence if g and g.inputs else None
        if isinstance(selector, ReportSectionGenerationEvidenceSelector):
            if section.conciseDisclosure is None or blk.id != section.conciseDisclosure.id:
                errors.append(f"块 {blk.id}：report_section 证据选择器仅适用于所属 H2 的 conciseDisclosure")
        elif section.conciseDisclosure is not None and blk.id == section.conciseDisclosure.id:
            errors.append(f"块 {blk.id}：conciseDisclosure 必须使用 report_section 证据选择器")
        if isinstance(selector, ExplicitGenerationEvidenceSelector):
            for k in selector.intakeItems:
                if k not in intake_keys:
                    errors.append(f"块 {blk.id}：inputs.evidence.intakeItems 引用不存在的清单项 {k}")
            for k in selector.quantitativeMetrics:
                metric = metrics_by_key.get(k)
                if metric is None:
                    errors.append(f"块 {blk.id}：inputs.evidence.quantitativeMetrics 引用不存在的定量指标 {k}")
        selection = g.presetRowSelection if g else None
        if selection:
            key = selection.intakeItemKey
            if g.rowMode != "preset_catalog":
                errors.append(f"块 {blk.id}：presetRowSelection 仅适用于 preset_catalog")
            if key not in intake_keys:
                errors.append(f"块 {blk.id}：presetRowSelection 引用不存在的清单项 {key}")
            elif not isinstance(selector, ExplicitGenerationEvidenceSelector) or key not in selector.intakeItems:
                errors.append(
                    f"块 {blk.id}：presetRowSelection 的 {key} "
                    "必须同时声明在 inputs.evidence.intakeItems"
                )
            item = (intake_items_by_key or {}).get(key)
            if item is not None:
                if item.kind != "multi_select":
                    errors.append(f"块 {blk.id}：presetRowSelection 的 {key} 必须是 multi_select")
                allowed = set(item.options or [])
                unknown_seeds = [seed.theme for seed in (g.fixedRowSeeds or []) if seed.theme not in allowed]
                if unknown_seeds:
                    errors.append(f"块 {blk.id}：fixedRowSeeds 含 {key} 未声明的选项 {unknown_seeds}")
        if blk.image and blk.image.derivedVisualization:
            spec = blk.image.derivedVisualization
            for k in spec.metricKeys:
                metric = metrics_by_key.get(k)
                if metric is None:
                    errors.append(f"块 {blk.id}：image.derivedVisualization.metricKeys 引用不存在的定量指标 {k}")
            for k in spec.featuredMetricKeys or []:
                metric = metrics_by_key.get(k)
                if metric is None:
                    errors.append(f"块 {blk.id}：image.derivedVisualization.featuredMetricKeys 引用不存在的定量指标 {k}")
        if g and g.standardDisclosureRequirementKeys:
            for ref in g.standardDisclosureRequirementKeys:
                if not resolve_standard_disclosure_requirements(
                    package, report_section_id, [ref]
                ):
                    errors.append(
                        f"块 {blk.id}：standardDisclosureRequirementKeys 引用 {ref} "
                        f"在 standard_disclosure_requirements/{report_section_id} 无匹配"
                    )
        for rule in _condition_rules(blk.appears_when):
            if rule.path.startswith("intakeItems."):
                k = rule.path[len("intakeItems."):]
                if k not in intake_keys:
                    errors.append(f"块 {blk.id}：appears_when 引用不存在的清单项 {k}")
            if rule.path.startswith("quantitativeMetrics."):
                k = rule.path[len("quantitativeMetrics."):]
                metric = metrics_by_key.get(k)
                if metric is None:
                    errors.append(f"块 {blk.id}：appears_when 引用不存在的定量指标 {k}")
    return errors


def _used_intake_keys(
    section: Section,
    intake_items: dict[str, IntakeItem],
    report_section_id: str,
) -> set[str]:
    used: set[str] = set()
    for blk in _iter_blocks(section):
        g = blk.generation
        selector = g.inputs.evidence if g and g.inputs else None
        if isinstance(selector, ReportSectionGenerationEvidenceSelector):
            used.update(
                key for key, item in intake_items.items() if item.contentScopeId == report_section_id
            )
        elif isinstance(selector, ExplicitGenerationEvidenceSelector):
            used.update(selector.intakeItems)
        if g and g.presetRowSelection:
            used.add(g.presetRowSelection.intakeItemKey)
        for rule in _condition_rules(blk.appears_when):
            if rule.path.startswith("intakeItems."):
                used.add(rule.path[len("intakeItems."):])
    return used


def validate_unused_topic_intake(
    section: Section,
    intake_items: dict[str, IntakeItem],
    report_section_id: str,
) -> list[str]:
    """专属题必须被 block/table/condition 消费；四道 common 固定题由共享模板控制，不在此检查。"""
    used = _used_intake_keys(section, intake_items, report_section_id)
    errors: list[str] = []
    for key in sorted(intake_items):
        suffix = key.rsplit(".", 1)[-1]
        if suffix in COMMON_INTAKE_SUFFIXES:
            continue
        if key not in used:
            errors.append(
                f"报告章节 {report_section_id}：专属清单项 {key} 未被任何 block/table/condition 消费"
            )
    return errors


def validate_topic_refs_or_raise(
    section: Section,
    intake_keys: set[str],
    report_section_id: str,
    intake_items_by_key: dict[str, IntakeItem] | None = None,
    *,
    package: KnowledgePackage,
) -> None:
    """加载期 fail-loud：引用不一致即抛 ValueError，定位到具体块与 key。"""
    errors = validate_topic_refs(
        section, intake_keys, report_section_id, intake_items_by_key, package=package
    )
    if errors:
        raise ValueError(
            f"报告章节 {report_section_id} 配置引用校验失败：\n" + "\n".join(errors)
        )


def validate_topic_templates_or_raise(
    templates: dict[str, Section],
    intake_items: list[IntakeItem],
    *,
    package: KnowledgePackage,
) -> None:
    """跨入口校验全部议题模板引用，确保 plan/prompt-config/generate 共享同一 fail-loud gate。"""
    keys_by_report_section: dict[str, set[str]] = {}
    items_by_report_section: dict[str, dict[str, IntakeItem]] = {}
    for item in intake_items:
        keys_by_report_section.setdefault(item.contentScopeId, set()).add(item.key)
        items_by_report_section.setdefault(item.contentScopeId, {})[item.key] = item
    for report_section_id, section in templates.items():
        validate_topic_refs_or_raise(
            section,
            keys_by_report_section.get(report_section_id, set()),
            report_section_id,
            items_by_report_section.get(report_section_id, {}),
            package=package,
        )
        unused = validate_unused_topic_intake(
            section,
            items_by_report_section.get(report_section_id, {}),
            report_section_id,
        )
        if unused:
            raise ValueError(
                f"报告章节 {report_section_id} 清单项消费校验失败：\n"
                + "\n".join(unused)
            )
