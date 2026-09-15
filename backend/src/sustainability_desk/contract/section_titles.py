# ABOUTME: 统一解析章节用户可见标题，并用正文或子级标题指纹判断实例标题是否过期。
# ABOUTME: 稳定 Section.title 只服务导航与回退；正文预览、Word、artifact 和诊断必须调用本模块。
# ABOUTME(en): Resolves user-visible section titles and judges staleness by fingerprinting prose or child titles.
# ABOUTME(en): The stable Section.title serves navigation only; previews, Word and diagnostics call this module.
from __future__ import annotations

from hashlib import sha256
import json

from sustainability_desk.contract.knowledge_packages import knowledge_package_of
from sustainability_desk.contract.models import Block, Report, Section
from sustainability_desk.contract.report_values import resolve_report_ref
from sustainability_desk.contract.topic_registry import load_topic_contract


def _inline_text(section: Section, report: Report) -> str:
    parts: list[str] = []
    for inline in section.titleContent or []:
        if inline.kind == "text" and inline.text:
            parts.append(inline.text)
        elif inline.kind == "ref" and inline.ref:
            value = resolve_report_ref(inline.ref, report)
            if value not in (None, ""):
                parts.append(str(value))
            elif inline.fallback:
                parts.append(inline.fallback)
    return "".join(parts).strip()


def resolved_display_title(section: Section, report: Report) -> str:
    """实例动态标题 → resolved titleContent → 稳定 title。"""
    if section.displayTitle is not None:
        return section.displayTitle.text
    inline = _inline_text(section, report)
    return inline or section.title


def paragraph_fingerprint(content: list[dict] | list[object] | None) -> str:
    payload = []
    for item in content or []:
        if hasattr(item, "model_dump"):
            payload.append(item.model_dump(exclude_none=True))
        else:
            payload.append(item)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def block_fingerprint(block: Block) -> str:
    return paragraph_fingerprint(block.content)


def module_fingerprint(section: Section, report: Report) -> str:
    """H1 标题只依赖当前适用 H2 固定名及已解析 H4 标题，不传正文。"""
    payload: list[dict[str, object]] = []
    for h2 in section.children or []:
        h4_titles = [
            {
                "title": resolved_display_title(h4, report),
                "sourceFingerprint": section_title_input_fingerprint(h4, report),
            }
            for h3 in h2.children or []
            for h4 in h3.children or []
            if h4.headingLevel == 4 and not title_source_block_is_omitted(h4)
        ]
        payload.append({"reportSectionId": h2.reportSectionId, "title": h2.title, "h4": h4_titles})
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def section_title_input_fingerprint(section: Section, report: Report) -> str | None:
    if section.reportModuleId is not None:
        return module_fingerprint(section, report)
    declaration = section.titleGeneration
    if declaration is None:
        return None
    try:
        block = next(block for block in section.blocks if block.id == declaration.sourceBlockId)
    except StopIteration:
        return None
    return block_fingerprint(block)


def title_source_block_is_omitted(section: Section) -> bool:
    """titleGeneration 源块受控省略：节不进正文与目录，不承担标题义务。

    该谓词由标题新鲜度判定、模块标题上下文与模块指纹三处共用：
    恒判 stale 会让用户看不见的节阻断整份报告导出，
    已省略 H4 的标题也不得进入模块标题输入面。
    """
    declaration = section.titleGeneration
    if declaration is None:
        return False
    source = next(
        (block for block in section.blocks if block.id == declaration.sourceBlockId),
        None,
    )
    return source is not None and source.state == "omitted"


def module_title_is_fixed(section: Section, report: Report) -> bool:
    """A report module without titleGenerationGuidance keeps its navigation title; no generation."""

    if section.reportModuleId is None:
        return False
    modules = load_topic_contract(knowledge_package_of(report)).reportModulesById
    return modules[section.reportModuleId].titleGenerationGuidance is None


def display_title_is_stale(section: Section, report: Report) -> bool:
    if title_source_block_is_omitted(section) or module_title_is_fixed(section, report):
        return False
    if section.displayTitle is None:
        return section.reportModuleId is not None or section.titleGeneration is not None
    expected = section_title_input_fingerprint(section, report)
    return expected is not None and section.displayTitle.inputFingerprint != expected
