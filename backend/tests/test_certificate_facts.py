# ABOUTME: 证书事实合并与表格投影的合同测试——同一张证书跨议题只出现一行。
# ABOUTME: 关注「认证范围会不会又在多处重复」，而非投影函数的内部形状。
from __future__ import annotations

from dataclasses import dataclass

from sustainability_desk.contract.certificate_facts import (
    certificate_facts_from_records,
    certificate_table_rows,
)


@dataclass
class _Record:
    certificate_fact: dict | None


def _fact(name: str, issuer: str = "华信技术检验有限公司", scope: str = "导轨表、数显电表") -> dict:
    return {
        "certificate_name": name,
        "issuer": issuer,
        "covered_scope": scope,
        "unreadable_fields": [],
    }


def test_same_certificate_uploaded_for_several_topics_yields_one_row() -> None:
    """一张 ISO 14001 天然横跨环境、能源、污染物等议题，用户可能各传一张照片。

    集中承载位必须按证书身份归并——这正是议题正文不再复述认证范围的前提。
    """
    records = [_Record(_fact("环境管理体系认证证书")) for _ in range(5)]
    facts = certificate_facts_from_records(records)
    assert len(facts) == 1
    assert len(certificate_table_rows(facts)) == 1


def test_different_certificates_are_kept_apart() -> None:
    """不同证书不得被合并；实测某企业持有 9 类证书。"""
    records = [
        _Record(_fact("环境管理体系认证证书")),
        _Record(_fact("质量管理体系认证证书")),
        _Record(_fact("环境管理体系认证证书", issuer="另一家认证机构")),
    ]
    assert len(certificate_facts_from_records(records)) == 3


def test_unreadable_certificate_does_not_become_a_disclosed_row() -> None:
    """名称都读不出的证书不足以支撑一行公开披露——入口已如实登记为不可辨认。"""
    records = [
        _Record({"certificate_name": "", "unreadable_fields": ["certificate_name"]}),
        _Record(None),
    ]
    assert certificate_facts_from_records(records) == []


def test_row_carries_scope_so_topic_body_need_not_repeat_it() -> None:
    """认证范围集中在本表承载；标准号并入名称列，不单独占列。"""
    rows = certificate_table_rows([_fact("环境管理体系认证证书")])
    values = [cell.value for cell in rows[0].children]
    assert values[0] == "环境管理体系认证证书"
    assert values[1] == "华信技术检验有限公司"
    assert values[2] == "导轨表、数显电表"


def test_non_certificate_assets_are_ignored() -> None:
    """照片、组织架构图等素材不进证书清单。"""
    assert certificate_facts_from_records([_Record(None), _Record({})]) == []


def test_same_certificate_survives_title_wording_drift() -> None:
    """两次识别对同一张证书给出的名称可能不同，归并不得因此漏判。

    真实模型下同一张图两次调用，一次名称为「环境管理体系认证证书」、
    另一次带上了图中的英文副标题，按名称比对出了两行。标准号是印在证书上的稳定标识，
    比人读的标题可靠，故作为首选身份。
    """
    records = [
        _Record(_fact("环境管理体系认证证书")),
        _Record(_fact("环境管理体系认证证书 CERTIFICATE OF ENVIRONMENTAL MANAGEMENT SYSTEM")),
    ]
    assert len(certificate_facts_from_records(records)) == 1


def test_honors_without_certificate_wording_are_still_deduped() -> None:
    """国家高新技术企业、杰出雇主这类荣誉名里没有「认证」「证书」字样，仍须能归并。"""
    def honor(name: str) -> dict:
        return {"certificate_name": name, "issuer": "浙江省科技厅"}

    records = [_Record(honor("国家高新技术企业")), _Record(honor("国家高新技术企业"))]
    assert len(certificate_facts_from_records(records)) == 1
    mixed = [_Record(honor("国家高新技术企业")), _Record(honor("杰出雇主 2026"))]
    assert len(certificate_facts_from_records(mixed)) == 2


def test_user_corrected_facts_are_protected_from_agent_rerun() -> None:
    """用户更正过的证书事实不被识别重跑覆盖——与题注同型的归属保护。

    识别结论会进报告正文与成果章，用户有权更正；若重跑就翻回机器结论，
    用户的更正等于没做。SQL 侧由 certificate_fact_source='user' 分支保证。
    """
    from pathlib import Path

    dal = (
        Path(__file__).resolve().parents[1]
        / "src/sustainability_desk/persistence/layout_evidence_assets.py"
    ).read_text(encoding="utf-8")
    assert "certificate_fact_source = 'user'" in dal
    assert "when evidence_assets.certificate_fact_source = 'user'" in dal
    assert "then evidence_assets.certificate_fact" in dal


def test_certificate_fact_request_only_accepts_report_visible_fields() -> None:
    """用户可改的字段与入口解析同集：报告不呈现的内容既不读也不收。"""
    from sustainability_desk.api.material_router import LayoutAssetCertificateFactRequest

    assert set(LayoutAssetCertificateFactRequest.model_fields) == {
        "certificate_name",
        "issuer",
        "covered_scope",
        "holder_name",
    }


def test_certificate_table_carries_provenance_commentary() -> None:
    """证书表必须带出处批注——它声明 source=user_input，会被通用批注策略跳过。

    表里的字来自模型对证书图片的识别，不是用户填写值的确定性投影。缺了批注，
    审阅稿会出现一张无出处的表，而机构名、认证范围恰恰是最该被人工核对的内容。
    """
    import inspect

    from sustainability_desk.contract.certificate_facts import CERTIFICATE_TABLE_BLOCK_ID
    from sustainability_desk.export.format_profile import load_format_profile
    from sustainability_desk.report_review_packages import build_customer_commentary_package
    from knowledge_package_fixtures import SSE_PACKAGE

    CERTIFICATE_TABLE_EXPLANATION = load_format_profile(
        SSE_PACKAGE
    ).delivery_texts.explanations.certificate_table

    source = inspect.getsource(build_customer_commentary_package)
    assert "CERTIFICATE_TABLE_BLOCK_ID" in source
    # 批注须先于 source != "ai" 的跳过判定，否则永远走不到
    assert source.index("CERTIFICATE_TABLE_BLOCK_ID") < source.index('unit_block.source != "ai"')
    assert "可在资料处理页更正" in CERTIFICATE_TABLE_EXPLANATION

    # 必须真正构造一次：只读源码测不出字段名写错——若把 unit_kind 写成
    # unit_label，源码断言全绿，交付阶段却整轮失败。
    from sustainability_desk.report_review_packages import CustomerCommentaryEntry

    entry = CustomerCommentaryEntry(
        anchor_id=f"block:{CERTIFICATE_TABLE_BLOCK_ID}",
        unit_kind="table",
        basis=("uploaded_layout_image",),
        explanation=CERTIFICATE_TABLE_EXPLANATION,
    )
    assert entry.unit_kind == "table"


def test_certificate_rows_survive_stored_state_validation() -> None:
    """证书行写入报告状态时必须通过 StoredReportStateV4 校验。

    若整个 dump GsTableCell，会把 Plate 文本骨架 children
    一起写进状态，被 StoredTableCell 的 extra=forbid 拒绝，生成在收尾处整轮失败。
    单元测试测不到——只有真实写状态才会撞上。
    """
    from sustainability_desk.contract.certificate_facts import CERTIFICATE_TABLE_BLOCK_ID
    from sustainability_desk.contract.stored_report_state import StoredReportStateV4

    rows = certificate_table_rows([_fact("环境管理体系认证证书")])
    payload = {
        "children": [
            {
                "children": [
                    {"type": cell.type, "colKey": cell.colKey, "value": cell.value}
                    for cell in row.children
                ]
            }
            for row in rows
        ],
        "state": "ready",
    }
    state = StoredReportStateV4.model_validate(
        {"version": 4, "tableBlocks": {CERTIFICATE_TABLE_BLOCK_ID: payload}}
    )
    stored = state.tableBlocks[CERTIFICATE_TABLE_BLOCK_ID]
    assert stored.children[0].children[0].value == "环境管理体系认证证书"


def test_third_party_holder_is_named_in_the_table() -> None:
    """持证主体不是报告主体时须在表中写明，否则读者会误以为是报告主体自有。

    正文体裁合同已有同一条规则，但那条只约束模型生成的正文；本表由代码确定性成行，
    须各自落实。入口只在持证主体与报告主体不一致时填 holder_name，一致则留空。
    """
    fact = _fact("质量管理体系认证证书")
    fact["holder_name"] = "母公司股份有限公司"
    value = certificate_table_rows([fact])[0].children[0].value
    assert "持证主体：母公司股份有限公司" in value

    own = certificate_table_rows([_fact("环境管理体系认证证书")])[0].children[0].value
    assert "持证主体" not in own
