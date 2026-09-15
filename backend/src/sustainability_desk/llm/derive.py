# ABOUTME: 公司业务摘要派生——上下文工程步骤0：把 company_profile 压缩为约100字主营业务概述，供每个块的 <report_subject> 统一引用。
# ABOUTME: 本模块是该派生的唯一真相源：压缩来源、目标长度、来源指纹与是否需要重算的判定都在此，调用方不另行实现同名规则。
# ABOUTME(en): Company business summary, context step 0: compresses company_profile to ~100 chars for <report_subject>.
# ABOUTME(en): Sole source of truth for it: compression source, target length, fingerprint and recompute verdict.
from __future__ import annotations

from hashlib import sha256

from sustainability_desk.contract.knowledge_packages import KnowledgePackage, knowledge_package_of
from sustainability_desk.contract.language import count_length
from sustainability_desk.contract.models import Report
from sustainability_desk.llm.client import build_agent
from sustainability_desk.llm.concurrency import run_agent
from sustainability_desk.llm.ai_observability import ObservationRun
from sustainability_desk.llm.model_registry import DEFAULT_MODEL_ID
from sustainability_desk.llm.prompt_profiles import load_prompt_profile
from sustainability_desk.llm.prompts import _xml_escape

# 派生字段 key：与 report_contract.yaml fields、报告生成 Prompt Profile 的 context_fields 保持一致。
COMPANY_BUSINESS_SUMMARY_KEY = "company_business_summary"
# 压缩源：关于公司章节的完整公司简介（intakeItem）。
_SOURCE_INTAKE_KEY = "company_profile"
# Instructions and the target length (in the package's length unit) belong to the package prompt
# profile (company_business_summary); the derivation rule below is language-neutral.


def _company_profile_text(report: Report) -> str:
    for item in report.intakeItems or []:
        if item.key == _SOURCE_INTAKE_KEY and isinstance(item.answer, str):
            return item.answer.strip()
    return ""


def _company_profile_user_prompt(profile: str) -> str:
    """将用户公司简介定界为模型输入，避免简介文本伪造系统标签或结构边界。"""
    return "<company_profile>\n" + _xml_escape(profile) + "\n</company_profile>"


def company_profile_text(report: Report) -> str:
    """本派生的压缩来源正文；来源 key 由本模块单点拥有。"""
    return _company_profile_text(report)


def company_profile_fingerprint(profile: str) -> str:
    """压缩来源指纹：来源正文变化即摘要过期。"""
    return sha256(profile.strip().encode("utf-8")).hexdigest()


def company_business_summary_is_stale(profile: str, stored, *, package: KnowledgePackage) -> bool:
    """判定已保存摘要是否需要重算：无摘要、或来源正文已变。

    stored 为 StoredCompanyBusinessSummary | None。简介为空或本身已足够短时
    不需要摘要（见 needs_company_business_summary），该判定与本函数配合使用。
    """
    if not needs_company_business_summary(profile, package=package):
        return False
    if stored is None:
        return True
    return stored.sourceFingerprint != company_profile_fingerprint(profile)


def needs_company_business_summary(profile: str, *, package: KnowledgePackage) -> bool:
    """简介为空则无摘要可派生；本身已不长于目标长度（按包语言的长度单位）则直接可作背景。"""
    text = (profile or "").strip()
    target = load_prompt_profile(package).company_business_summary.target_length
    return bool(text) and count_length(text, package.language) > target


async def derive_company_business_summary(
    report: Report,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    observation: ObservationRun,
) -> str:
    """步骤0：从 company_profile 压缩主营业务概述（约100字）。

    简介未填写、或本身已不长于目标长度时不调用模型：前者无来源，后者直接可作背景。
    """
    package = knowledge_package_of(report)
    profile = _company_profile_text(report)
    if not needs_company_business_summary(profile, package=package):
        return profile if profile else ""
    instructions = load_prompt_profile(package).company_business_summary.instructions
    agent = build_agent(model_id, output_type=str, instructions=instructions)
    result = await run_agent(
        agent,
        _company_profile_user_prompt(profile),
        observation.invocation(
            block_id="company.business_summary",
            model_id=model_id,
            task_context={"companyProfile": profile},
        ),
    )
    return (result.output or "").strip()
