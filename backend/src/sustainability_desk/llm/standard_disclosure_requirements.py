# ABOUTME: 准则披露要求加载器——按 standardDisclosureRequirementKeys 解析准则合规映射。
# ABOUTME: 上下文边界硬约束：仅暴露标题、要求正文、义务等级；来源标签与映射键不进模型上下文。
# ABOUTME(en): Disclosure requirement loader: resolves the mapping by standardDisclosureRequirementKeys.
# ABOUTME(en): Hard context boundary: only title, requirement text and obligation level are exposed to the model.
from __future__ import annotations

import re
from functools import lru_cache

import yaml
from pydantic import BaseModel, ConfigDict

from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    load_knowledge_package,
)

# 准则正文内 <ref>…</ref> 为内部交叉引用标记（指向待填充的议题通用框架），不进模型可见正文。
_REF_MARKUP = re.compile(r"<ref>.*?</ref>", re.DOTALL)


class StandardDisclosureRequirement(BaseModel):
    """准则披露要求的模型可见投影。"""

    model_config = ConfigDict(frozen=True)

    standardDisclosureRequirementTitle: str
    standardDisclosureRequirementText: str
    disclosureRequirementObligationLevel: str


@lru_cache(maxsize=None)
def _points_by_key(
    package_id: str, report_section_id: str
) -> dict[str, StandardDisclosureRequirement]:
    """加载某议题全部准则披露要求为 {key: StandardDisclosureRequirement}。"""
    package = load_knowledge_package(package_id)
    path = package.standard_disclosure_requirements_dir / f"{report_section_id}.yaml"
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, StandardDisclosureRequirement] = {}
    for mapping in raw.get("topicStandardDisclosureRequirementGroups", []) or []:
        for req in mapping.get("standardDisclosureRequirements", []) or []:
            key = req.get("standardDisclosureRequirementKey")
            if not key:
                continue
            out[key] = StandardDisclosureRequirement(
                standardDisclosureRequirementTitle=req["standardDisclosureRequirementTitle"],
                standardDisclosureRequirementText=_REF_MARKUP.sub("", req["standardDisclosureRequirementText"]).strip(),
                disclosureRequirementObligationLevel=req.get("disclosureRequirementObligationLevel", ""),
            )
    return out


def resolve_standard_disclosure_requirements(
    package: KnowledgePackage,
    report_section_id: str,
    refs: list[str] | None,
    *,
    required_only: bool = False,
) -> list[StandardDisclosureRequirement]:
    """按 refs 解析准则披露要求；支持精确 key 与 `<prefix>.*` 通配。未命中跳过。

    去重保序：同一要点被多个 ref 命中只取一次，输出顺序按 refs 顺序、通配内按库内顺序。
    required_only=True 只保留 obligation=required；默认保留全部义务等级。
    """
    if not refs:
        return []
    by_key = _points_by_key(package.id, report_section_id)
    seen: set[str] = set()
    out: list[StandardDisclosureRequirement] = []
    for ref in refs:
        if ref.endswith(".*"):
            prefix = ref[:-1]  # 去掉尾部 *，保留点号前缀
            matched = [k for k in by_key if k.startswith(prefix)]
        else:
            matched = [ref] if ref in by_key else []
        for k in matched:
            if k in seen:
                continue
            point = by_key[k]
            if required_only and point.disclosureRequirementObligationLevel != "required":
                continue
            seen.add(k)
            out.append(point)
    return out
