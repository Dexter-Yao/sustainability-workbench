# ABOUTME: 报告获取与反馈合同测试：按发布方式二选一输出获取方式段落，读者经反馈邮箱索取报告。
# ABOUTME: 官网地址填的是公司官网（编制期即存在），不是本报告文件的下载链接；未填时落入不含地址的默认句。

from sustainability_desk.contract.loader import load_contract
from sustainability_desk.contract.visibility import visible
from sustainability_desk.diagnostics import diagnose
from knowledge_package_fixtures import SSE_PACKAGE

CONTRACT = SSE_PACKAGE.report_contract_path


def _template(SSE_PACKAGE):
    return load_contract(CONTRACT)


def _with_publication(report, *, channel: str | None, url: str | None):
    fields = dict(report.fields)
    if channel is not None:
        fields["report_publication_channel"] = fields[
            "report_publication_channel"
        ].model_copy(update={"value": channel})
    if url is not None:
        fields["report_publication_website_url"] = fields[
            "report_publication_website_url"
        ].model_copy(update={"value": url})
    return report.model_copy(update={"fields": fields})


def test_template_declares_publication_channel_with_conditional_website_url():
    """发布方式为选填单选；官网地址仅在选「公司官网发布」时出现。"""

    report = _template(SSE_PACKAGE)

    channel = report.fields["report_publication_channel"]
    assert channel.type == "enum"
    assert channel.required is False
    assert list(channel.options or []) == ["公司官网发布", "线下发布"]

    url = report.fields["report_publication_website_url"]
    assert url.type == "url"
    assert url.required is False
    assert url.appears_when is not None
    assert url.appears_when.all[0].path == "fields.report_publication_channel.value"
    assert url.appears_when.all[0].value == "公司官网发布"


def test_exactly_one_access_paragraph_visible_in_every_case():
    """四种情形各出且只出一段：漏掉互斥会让「关于本报告」重复或缺失获取方式。"""

    report = _template(SSE_PACKAGE)
    cases = {
        ("未选择", None, None): "about.access",
        ("官网发布且已填地址", "公司官网发布", "https://www.example.com"): "about.access.website",
        # 选了官网却没填地址：落入不含地址的默认句，而不是留下半句话。
        ("官网发布未填地址", "公司官网发布", None): "about.access",
        ("线下发布", "线下发布", None): "about.access",
    }
    for (label, channel, url), expected in cases.items():
        current = _with_publication(report, channel=channel, url=url)
        shown = [
            block_id
            for block_id in ("about.access.website", "about.access")
            if visible(current.find_block(block_id), current)
        ]
        assert shown == [expected], f"{label}: {shown}"


def test_website_paragraph_carries_the_url_and_default_paragraph_does_not():
    """带地址的分支引用官网字段；默认句不含任何引用，两段其余文字一致。"""

    report = _template(SSE_PACKAGE)

    website = report.find_block("about.access.website")
    assert [inline.ref for inline in website.content if inline.kind == "ref"] == [
        "report_publication_website_url"
    ]

    default = report.find_block("about.access")
    assert [inline.ref for inline in default.content if inline.kind == "ref"] == []

    prefix = "本报告以独立报告形式发布，提供简体中文版本。"
    for block in (website, default):
        assert "".join(
            inline.text for inline in block.content if inline.kind == "text"
        ).startswith(prefix)


def test_website_selected_without_url_warns_without_blocking():
    """选了官网却没填地址：warn 引导补齐，不阻断导出。"""

    report = _with_publication(_template(SSE_PACKAGE), channel="公司官网发布", url=None)

    matching = [
        issue
        for issue in diagnose(report).issues
        if issue.fieldKey == "report_publication_website_url"
    ]
    assert [issue.level for issue in matching] == ["warn"]


def test_reader_feedback_email_carries_report_request_channel():
    """线下发布时读者经反馈邮箱索取报告，该段落必须承载这件事。"""

    report = _template(SSE_PACKAGE)

    contact_block = report.find_block("about.contact")
    assert contact_block is not None
    assert [inline.ref for inline in contact_block.content if inline.kind == "ref"] == [
        "appendixPackage.readerFeedbackContactInformation.email"
    ]
    assert "如需获取本报告" in "".join(
        inline.text for inline in contact_block.content if inline.kind == "text"
    )
    assert contact_block.appears_when is not None
    assert (
        contact_block.appears_when.all[0].path
        == "appendixPackage.readerFeedbackContactInformation.email"
    )
    assert report.inputGuidance is not None
    assert "appendixPackage.readerFeedbackContactInformation.email" in report.inputGuidance
