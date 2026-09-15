# ABOUTME: 「关于本报告」小节结构合同：五个常驻小节 + 条件出现的报告鉴证 + 章末不编号审批段。
# ABOUTME: 编号由 section_number 按可见章节树推导，本测试锁结构与可见性，不复制编号实现。
"""该章五段若缺小节标题，与参考模板不一致。

「关于本报告」章在中文可持续发展报告中的惯用形态是：
「一、报告范围」「二、时间范围」「三、编制依据」「四、编制原则」「五、报告获取及意见反馈」
「六、报告鉴证」，审批说明为章末**不编号**段落。本测试锁定这一形态。
"""

from pathlib import Path

from sustainability_desk.contract.fill import fill_report
from sustainability_desk.contract.loader import load_contract
from sustainability_desk.contract.renderability import section_is_renderable
from sustainability_desk.contract.section_number import number_sections
from sustainability_desk.export.docx_renderer import load_values_flat
from knowledge_package_fixtures import SSE_PACKAGE

BACKEND = Path(__file__).resolve().parents[1]
CONTRACT = SSE_PACKAGE.report_contract_path
SAMPLE_VALUES = SSE_PACKAGE.sample_values_path


def _about(report):
    return next(sec for sec in report.sections if sec.key == "about_report")


def _filled():
    return fill_report(load_contract(CONTRACT), load_values_flat(SAMPLE_VALUES))


def _numbered_titles(report):
    labels = number_sections(
        report.sections, lambda node: section_is_renderable(node, report)
    )
    return [
        (labels.get(child.key, ""), child.title)
        for child in _about(report).children or []
        if section_is_renderable(child, report)
    ]


def test_chapter_opening_stays_outside_any_subsection():
    """开篇段在章标题之下、第一个小节之前；参考模板同形。"""

    about = _about(load_contract(CONTRACT))

    assert [block.id for block in about.blocks] == ["about.opening"]


def test_subsections_carry_every_remaining_block():
    """19 个块全部有归属：小节化不得丢块，也不得把块留在章级与小节之间。"""

    about = _about(load_contract(CONTRACT))
    grouped = {
        child.key: [block.id for block in child.blocks]
        for child in about.children or []
    }

    assert grouped == {
        "about_report.scope": [
            "about.scope",
            "about.scope_without_short_name",
            "about.scope_parent_only",
            "about.scope_parent_only_without_short_name",
            "about.scope_special",
            "about.scope_special_without_short_name",
        ],
        "about_report.timeframe": ["about.timeframe"],
        "about_report.basis": ["about.basis"],
        "about_report.principles": [
            "about.principles",
            "about.principle_materiality",
            "about.principle_balance",
            "about.principle_quant",
            "about.principle_consistency",
        ],
        "about_report.access": [
            "about.access.website",
            "about.access",
            "about.contact",
        ],
        "about_report.assurance": ["about.assurance"],
        "about_report.approval": ["about.approval"],
    }
    total = len(about.blocks) + sum(len(ids) for ids in grouped.values())
    assert total == 19


def test_five_standing_subsections_number_one_through_five():
    """填齐常规字段时，五个常驻小节连续编号；审批段不占号。"""

    assert _numbered_titles(_filled()) == [
        ("一、", "报告范围"),
        ("二、", "时间范围"),
        ("三、", "编制依据"),
        ("四、", "编制原则"),
        ("五、", "报告获取及意见反馈"),
        ("", ""),
    ]


def test_assurance_subsection_appears_only_when_assurance_is_provided():
    """报告鉴证是条件小节：未提供鉴证时整节不出现，也不占「六、」。"""

    report = _filled()
    assert ("六、", "报告鉴证") not in _numbered_titles(report)

    fields = dict(report.fields)
    for key, value in (
        ("assurance_provider_name", "某某会计师事务所"),
        ("assurance_standard", "ISAE 3000"),
    ):
        fields[key] = fields[key].model_copy(update={"value": value})
    appendix = report.appendixPackage.model_copy(
        update={
            "externalAssuranceReport": report.appendixPackage.externalAssuranceReport.model_copy(
                update={"isIncluded": True}
            )
        }
    )
    with_assurance = report.model_copy(
        update={"fields": fields, "appendixPackage": appendix}
    )

    assert _numbered_titles(with_assurance)[-2] == ("六、", "报告鉴证")


def test_approval_paragraph_sits_in_a_transparent_group_without_number():
    """审批说明按参考模板为章末不编号段落：空标题分组节，编号推导对其透明。"""

    about = _about(load_contract(CONTRACT))
    approval = next(
        child for child in about.children or [] if child.key == "about_report.approval"
    )

    assert approval.title == ""
    assert [block.id for block in approval.blocks] == ["about.approval"]
