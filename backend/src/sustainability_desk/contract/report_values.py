# ABOUTME: 报告级结构化事实的确定性派生与引用解析，供诊断、导出与前端镜像实现对齐。
# ABOUTME: 本模块只读取 Report，不接触 LLM prompt，不暴露内部原始字段结构。
# ABOUTME(en): Deterministic derivation of report-level structured facts and reference resolution.
# ABOUTME(en): Reads a Report only; touches no LLM prompt and exposes no internal raw field structure.
from __future__ import annotations

import re

from sustainability_desk.contract.knowledge_packages import knowledge_package_of
from sustainability_desk.contract.language import format_month
from sustainability_desk.contract.models import Report

# 联系邮箱采用 ASCII 商务邮箱语法；与前端 isFieldValueAllowed("email") 经
# tests/fixtures/email_validation_golden.json 对齐，两端不得单独放宽或收紧。
CONTACT_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def is_valid_contact_email(value: str) -> bool:
    """判定非空联系邮箱格式；空串代表未填写，由调用方在此之前处理。"""
    return bool(CONTACT_EMAIL_PATTERN.fullmatch(value))


def selected_standard_names(report: Report) -> list[str]:
    """根据报告配置输出对外展示的准则名称列表。

    The package's disclosure basis decides the shape: a selectable mainland basis reads the user's
    choice from ``disclosureProfile``; a fixed basis names its standards outright.
    """
    basis = knowledge_package_of(report).manifest.disclosure_basis
    profile = report.disclosureProfile
    if basis.mainland_standard_selectable:
        mainland = profile.mainlandStandard if profile else "sse"
        names = [basis.mainland_standard_names.name(mainland)]
        if profile and profile.includesHongKongExchangeGuide and basis.hong_kong_guide_name:
            names.append(basis.hong_kong_guide_name)
    else:
        names = list(basis.primary_standard_names)
    for name in profile.additionalDisclosureReferences if profile else []:
        clean = str(name).strip()
        if clean:
            names.append(clean)
    return names


def selected_standard_names_text(report: Report) -> str:
    return "、".join(selected_standard_names(report))


def disclosure_basis_statement(report: Report) -> str:
    return selected_standard_names_text(report)


def _appendix_value(path: str, report: Report):
    pkg = report.appendixPackage
    if pkg is None:
        return None
    if path == "appendixPackage.externalAssuranceReport.isIncluded":
        return pkg.externalAssuranceReport.isIncluded
    if path == "appendixPackage.externalAssuranceReport.fileLabel":
        return pkg.externalAssuranceReport.fileLabel
    if path == "appendixPackage.readerFeedbackContactInformation.address":
        return pkg.readerFeedbackContactInformation.address
    if path == "appendixPackage.readerFeedbackContactInformation.email":
        return pkg.readerFeedbackContactInformation.email
    if path == "appendixPackage.readerFeedbackContactInformation.phone":
        return pkg.readerFeedbackContactInformation.phone
    return None


def _disclosure_value(path: str, report: Report):
    profile = report.disclosureProfile
    if path == "disclosureProfile.mainlandStandard":
        return profile.mainlandStandard if profile else "sse"
    if path == "disclosureProfile.includesHongKongExchangeGuide":
        return profile.includesHongKongExchangeGuide if profile else False
    if path == "disclosureProfile.additionalDisclosureReferences":
        return profile.additionalDisclosureReferences if profile else []
    if path == "disclosureProfile.selectedStandardNames":
        return selected_standard_names_text(report)
    if path == "disclosureProfile.basisStatement":
        return disclosure_basis_statement(report)
    return None


def resolve_report_ref(ref: str | None, report: Report):
    """解析行内引用和值路径；未知引用返回 None，由调用方决定是否占位或诊断。"""
    if not ref:
        return None
    if ref.startswith("disclosureProfile."):
        return _disclosure_value(ref, report)
    if ref.startswith("appendixPackage."):
        return _appendix_value(ref, report)
    if ref == "assessment.applicableTopicCount":
        # 本报告实际披露的议题数量：取「必须由用户评分」的范围，不取含 fixed 的
        # 重要性范围（后者多一个 stakeholder_communication，不进议题章节）。
        # 现算而非读快照——该数随科技伦理适用性与披露档位变化，写死必然写错。
        # 延迟 import：visibility/report_values 刻意保持轻量，不在模块级依赖议题注册表。
        from sustainability_desk.contract.topic_registry import applicable_scoring_topics

        return len(applicable_scoring_topics(report))
    field = report.fields.get(ref)
    if field is not None:
        return field.value
    return None


def display_report_ref(ref: str | None, report: Report):
    """将已解析字段投影为正式报告显示值，不改变 Report 中的原始 typed value。"""

    value = resolve_report_ref(ref, report)
    field = report.fields.get(ref or "")
    if field is not None and field.type == "month" and value not in (None, ""):
        return format_month(str(value), knowledge_package_of(report).language)
    return value
