# ABOUTME: 未评分（complete_coverage）时「议题重要性评估」节改用确定性四段叙述的合同测试。
# ABOUTME: 守护两分支互斥、动态字段现算、科技伦理说明只以脚注出现一次。
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sustainability_desk.api.app import plan_report
from sustainability_desk.contract.renderability import block_is_renderable
from sustainability_desk.contract.report_values import resolve_report_ref
from sustainability_desk.contract.topic_registry import applicable_scoring_topics

from test_plan import _report_with_topics
from knowledge_package_fixtures import SSE_PACKAGE

UNSCORED_IDS = [
    "sm.unscored_purpose",
    "sm.unscored_identification",
    "sm.unscored_screening",
    "sm.unscored_coverage",
]
SCORED_ONLY_IDS = [
    "sm.materiality_intro",
    "sm.topic_library",
    "sm.process_step1",
    "sm.process_step2",
    "sm.process_step3",
    "sm.process_step4",
]


def _materiality_blocks(report):
    found = []

    def walk(sections):
        for section in sections:
            if section.key == "sm.materiality":
                found.extend(section.blocks or [])
            walk(section.children or [])

    walk(report.sections)
    return found


def _renderable_ids(report):
    return [b.id for b in _materiality_blocks(report) if block_is_renderable(b, report)]


def _unscored_report():
    report = plan_report(_report_with_topics("dual"), package=SSE_PACKAGE)["report"]
    report.assessmentInput = None
    return plan_report(report, package=SSE_PACKAGE)["report"]


def _scored_report():
    return plan_report(_report_with_topics("dual"), package=SSE_PACKAGE)["report"]


def test_unscored_report_uses_the_deterministic_narrative_branch():
    report = _unscored_report()
    assert report.meta.materialityStrategy == "complete_coverage"
    ids = _renderable_ids(report)
    for block_id in UNSCORED_IDS:
        assert block_id in ids, block_id


def test_scored_report_keeps_the_original_branch():
    report = _scored_report()
    assert report.meta.materialityStrategy is None
    ids = _renderable_ids(report)
    for block_id in UNSCORED_IDS:
        assert block_id not in ids, block_id
    for block_id in SCORED_ONLY_IDS:
        assert block_id in ids, block_id


def test_the_two_branches_are_mutually_exclusive():
    """两套文本任何时候只出现一套——并存会让同一节读到两段互相重复的引言。"""

    unscored = set(_renderable_ids(_unscored_report()))
    scored = set(_renderable_ids(_scored_report()))
    assert not (unscored & set(SCORED_ONLY_IDS))
    assert not (scored & set(UNSCORED_IDS))


def test_topic_count_and_standard_name_are_derived_not_hardcoded():
    """议题数量随适用范围现算，准则名称随企业上市地现算；写死必然对不上。"""

    report = _unscored_report()
    coverage = next(b for b in _materiality_blocks(report) if b.id == "sm.unscored_coverage")
    refs = [inline.ref for inline in coverage.content if inline.ref]
    assert "assessment.applicableTopicCount" in refs
    assert "disclosureProfile.selectedStandardNames" in refs

    expected = len(applicable_scoring_topics(report, package=SSE_PACKAGE))
    assert resolve_report_ref("assessment.applicableTopicCount", report) == expected
    # 该报告是「无科技伦理敏感业务」配置（22 个适用评分议题，含恒适用的风险管理）。
    assert expected == 22
    assert "上海证券交易所" in str(resolve_report_ref("disclosureProfile.selectedStandardNames", report))


def test_reporting_year_renders_when_present():
    """段二以报告年份起句。该字段 requiredBefore=export，交付时必有值；
    此处补齐 fixture 缺失的字段，验证 ref 真能渲染成年份而非留空。"""

    from sustainability_desk.contract.models import Field
    from sustainability_desk.contract.report_values import display_report_ref

    report = _unscored_report()
    report.fields["reporting_year"] = Field(
        key="reporting_year",
        label="报告年份",
        type="year",
        source="user_input",
        value=2025,
    )
    identification = next(
        b for b in _materiality_blocks(report) if b.id == "sm.unscored_identification"
    )
    assert identification.content[0].ref == "reporting_year"
    assert display_report_ref("reporting_year", report) == 2025


def test_technology_ethics_note_appears_once_as_a_footnote():
    """未评分分支把该说明挂成脚注；原独立段落必须让位，否则同一句在同一节出现两次。"""

    report = _unscored_report()
    ids = _renderable_ids(report)
    assert "sm.topic_table_note1" not in ids

    coverage = next(b for b in _materiality_blocks(report) if b.id == "sm.unscored_coverage")
    assert coverage.footnote, "覆盖段应携带科技伦理脚注"
    footnote_text = "".join(inline.text or "" for inline in coverage.footnote)
    assert "科技伦理不构成本年度实质性议题" in footnote_text
    # 脚注文本不得同时出现在正文 content 里。
    body = "".join(inline.text or "" for inline in coverage.content)
    assert "科技伦理" not in body


def test_scored_report_still_shows_the_note_as_a_paragraph():
    """评分分支不受影响：该说明仍是表下的独立注释段。"""

    report = _scored_report()
    assert "sm.topic_table_note1" in _renderable_ids(report)


def test_due_diligence_has_its_own_section_so_no_cross_reference_note_is_needed():
    """删除的 note2 曾声称「尽职调查已融入风险管理，详见风险管理章节」——该断言与事实相反。

    尽职调查有独立章节（`topic_sections/due_diligence.yaml`），
    `disclosure_standards_index.yaml:58` 第五十二条也指向「尽职调查」而非「风险管理」。
    该注属潜伏错误，已整条删除。
    """

    report = plan_report(_report_with_topics("dual"), package=SSE_PACKAGE)["report"]
    titles = set()

    def walk(sections):
        for section in sections:
            titles.add(section.title)
            walk(section.children or [])

    walk(report.sections)
    assert "尽职调查" in titles
    assert not any(b.id == "sm.topic_table_note2" for b in report.iter_blocks())


def test_single_note_is_unnumbered():
    """本节只剩一条注，按 GB/T 1.1-2020 §9.10 应写「注：」而非「注1：」。"""

    report = _scored_report()
    note = next(b for b in _materiality_blocks(report) if b.id == "sm.topic_table_note1")
    text = "".join(inline.text or "" for inline in note.content)
    assert text.startswith("注：")
    assert "注1" not in text


def test_plan_report_binds_knowledge_package_from_argument() -> None:
    """plan_report 在入口把包绑到 Report 上，不依赖客户端投影自带。

    前端投影（frontend/public/contract.json）不带 knowledgePackageId，包由服务端从
    report_profile_id 权威解析。不在入口绑定，下游每处按包解析都要各自补传，
    漏一处即运行期 ValueError——曾表现为基本资料页整页 500，三个包同现。
    """

    incoming = _report_with_topics("dual").model_copy(update={"knowledgePackageId": None})
    planned = plan_report(incoming, package=SSE_PACKAGE)["report"]

    assert planned.knowledgePackageId == SSE_PACKAGE.id
