# ABOUTME: 用户可见准则批注条款原文读取器，供前端批注和诊断使用。
# ABOUTME: 本模块不参与 Prompt 装配；准则披露要求映射由 standard_disclosure_requirements 独立承担。
# ABOUTME(en): Reader for user-visible clause texts behind disclosure annotations, used by the frontend and diagnostics.
# ABOUTME(en): Takes no part in prompt assembly; requirement mapping is owned by standard_disclosure_requirements.
from __future__ import annotations

from functools import lru_cache

import yaml
from pydantic import BaseModel, ConfigDict

from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    load_knowledge_package,
)


class UserVisibleDisclosureClauseText(BaseModel):
    """用户可见准则批注中的一个准则条款原文。"""

    model_config = ConfigDict(frozen=True)

    clauseReference: str
    clauseOriginalText: str


class UserVisibleDisclosureClauseAnnotationEntry(BaseModel):
    """一个报告内容主题对应的用户可见大陆准则条款集合。"""

    model_config = ConfigDict(frozen=True)

    reportContentTopicName: str
    reportSectionKey: str
    mainlandStandard: str
    appendixIndexClauseReferences: list[str]
    clauseOriginalTexts: list[UserVisibleDisclosureClauseText]


@lru_cache(maxsize=None)
def _load_user_visible_disclosure_clause_annotations(
    package_id: str,
) -> tuple[UserVisibleDisclosureClauseAnnotationEntry, ...]:
    package = load_knowledge_package(package_id)
    raw = yaml.safe_load(package.clause_annotations_path.read_text(encoding="utf-8")) or {}
    return tuple(
        UserVisibleDisclosureClauseAnnotationEntry.model_validate(item)
        for item in raw.get("entries", []) or []
    )


def load_user_visible_disclosure_clause_annotations(
    package: KnowledgePackage,
) -> list[UserVisibleDisclosureClauseAnnotationEntry]:
    """读取用户可见准则批注条款原文事实源。"""
    return list(_load_user_visible_disclosure_clause_annotations(package.id))


def find_user_visible_disclosure_clause_annotation_entry(
    package: KnowledgePackage, *, mainland_standard: str, report_section_key: str
) -> UserVisibleDisclosureClauseAnnotationEntry | None:
    """按大陆准则与稳定报告章节 key 定位用户可见条款原文。"""
    for entry in load_user_visible_disclosure_clause_annotations(package):
        if entry.mainlandStandard != mainland_standard:
            continue
        if entry.reportSectionKey == report_section_key:
            return entry
    return None
