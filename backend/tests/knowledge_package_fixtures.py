# ABOUTME(en): Test-side handle on the mainland (sse_zh_hans) knowledge package. Tests that pin the
# ABOUTME(en): SSE authoring data bind to it explicitly instead of computing data paths from __file__.
from __future__ import annotations

from pathlib import Path

from sustainability_desk.contract.knowledge_packages import load_knowledge_package

SSE_PACKAGE_ID = "sse_zh_hans"
SSE_PACKAGE = load_knowledge_package(SSE_PACKAGE_ID)
SSE_DATA: Path = SSE_PACKAGE.root
SSE_REPORT_PROFILE_ID = "sse_zh_hans@1"


def sse_model_context(**overrides):
    """A ModelContext bound to the SSE package with a context-only posture; tests override fields."""

    from sustainability_desk.contract.evidence_semantics import resolve_evidence_posture
    from sustainability_desk.llm.prompt_profiles import load_prompt_profile
    from sustainability_desk.llm.prompts import ModelContext

    profile = load_prompt_profile(SSE_PACKAGE)
    fields = {
        "knowledge_package_id": SSE_PACKAGE.id,
        "output_language": SSE_PACKAGE.language,
        "evidence_posture": resolve_evidence_posture(
            profile.evidence_postures, substantive_input_present=False
        ),
    }
    fields.update(overrides)
    return ModelContext(**fields)


def sse_evidence_posture(level: str):
    """The SSE package's wording of one evidence posture level."""

    from sustainability_desk.contract.evidence_semantics import evidence_posture
    from sustainability_desk.llm.prompt_profiles import load_prompt_profile

    return evidence_posture(load_prompt_profile(SSE_PACKAGE).evidence_postures, level)
