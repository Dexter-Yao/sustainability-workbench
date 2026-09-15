# ABOUTME: 公司业务摘要派生（上下文工程步骤0）单测——是否需要派生、来源指纹失效与不调模型的短路分支。
# ABOUTME: 判定规则的唯一真相源是 llm/derive；本测试锁其行为，防调用方各自实现同名规则而漂移。
from sustainability_desk.contract.stored_report_state import StoredCompanyBusinessSummary
from sustainability_desk.llm.derive import (
    company_business_summary_is_stale,
    company_profile_fingerprint,
    needs_company_business_summary,
)
from sustainability_desk.llm.prompt_profiles import load_prompt_profile
from knowledge_package_fixtures import SSE_PACKAGE

COMPANY_BUSINESS_SUMMARY_TARGET_CHARS = load_prompt_profile(
    SSE_PACKAGE
).company_business_summary.target_length
_LONG = "甲" * (COMPANY_BUSINESS_SUMMARY_TARGET_CHARS + 50)
_SHORT = "公司主营精密电子元器件与连接器的研发、制造与销售。"


def test_short_or_empty_profile_needs_no_derivation():
    """简介为空则无来源；本身已不长于目标长度则直接可作背景，都不必调模型。"""
    assert needs_company_business_summary("", package=SSE_PACKAGE) is False
    assert needs_company_business_summary("   ", package=SSE_PACKAGE) is False
    assert needs_company_business_summary(_SHORT, package=SSE_PACKAGE) is False
    assert len(_SHORT) <= COMPANY_BUSINESS_SUMMARY_TARGET_CHARS


def test_long_profile_needs_derivation():
    assert needs_company_business_summary(_LONG, package=SSE_PACKAGE) is True


def test_missing_summary_for_long_profile_is_stale():
    assert company_business_summary_is_stale(_LONG, None, package=SSE_PACKAGE) is True


def test_matching_fingerprint_is_not_stale():
    """来源未变则复用已有摘要，不重复调用模型。"""
    stored = StoredCompanyBusinessSummary(
        text="已有摘要", sourceFingerprint=company_profile_fingerprint(_LONG)
    )
    assert company_business_summary_is_stale(_LONG, stored, package=SSE_PACKAGE) is False


def test_changed_profile_invalidates_stored_summary():
    """用户改了公司简介，已有摘要即过期——否则全篇背景停留在旧简介且无从察觉。"""
    stored = StoredCompanyBusinessSummary(
        text="旧摘要", sourceFingerprint=company_profile_fingerprint(_LONG)
    )
    assert company_business_summary_is_stale(_LONG + "新增业务线。", stored, package=SSE_PACKAGE) is True


def test_short_profile_never_stale_even_without_summary():
    """短简介不需要摘要，因此不存在"过期"，不会触发重算。"""
    assert company_business_summary_is_stale(_SHORT, None, package=SSE_PACKAGE) is False


def test_fingerprint_ignores_surrounding_whitespace():
    """指纹取自正文本身；仅首尾空白变化不应触发重算。"""
    assert company_profile_fingerprint(_LONG) == company_profile_fingerprint(f"  {_LONG}\n")
