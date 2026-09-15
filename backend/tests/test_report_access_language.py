# ABOUTME: 「报告获取及意见反馈」的语言版本口径合同：默认只声明简体中文版，不虚构英文版。
# ABOUTME: 多语言发布时保留中文优先规则；获取方式变体与联络句的文本同样锁定。
"""报告获取说明的语言版本合同测试。"""


from sustainability_desk.contract.loader import load_contract
from knowledge_package_fixtures import SSE_PACKAGE


CONTRACT = SSE_PACKAGE.report_contract_path
EXPECTED_ACCESS_PREFIX = (
    "本报告以独立报告形式发布，提供简体中文版本。"
    "若另行发布其他语言版本，如内容存在差异，以简体中文版为准。"
)


def test_report_access_text_describes_current_and_future_language_versions() -> None:
    """轻量版默认简体中文，不虚构英文版，同时保留多语言发布时的中文优先规则。"""
    report = load_contract(CONTRACT)
    access_block = report.find_block("about.access")
    access_text = "".join(inline.text or "" for inline in access_block.content or [] if inline.kind == "text")

    # 获取方式按发布方式二选一（见 test_report_publication_access.py）；语言版本口径两段一致。
    assert access_text == EXPECTED_ACCESS_PREFIX
    assert "简体中文与英文两种版本" not in access_text

    website_text = "".join(
        inline.text or ""
        for inline in report.find_block("about.access.website").content or []
        if inline.kind == "text"
    )
    assert website_text.startswith(EXPECTED_ACCESS_PREFIX)
    assert "简体中文与英文两种版本" not in website_text

    contact_block = report.find_block("about.contact")
    contact_text = "".join(inline.text or "" for inline in contact_block.content or [] if inline.kind == "text")
    assert contact_text == "如需获取本报告，或对本报告内容有任何垂询或改进建议，敬请通过邮箱与我们联络。"
