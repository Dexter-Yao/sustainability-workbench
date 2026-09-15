# ABOUTME: 证书事实的合并与表格投影——把入口解析出的 CertificateFact 收敛为报告级唯一清单。
# ABOUTME: 本模块不调用模型；同一张证书跨议题只出现一次，认证范围只在此集中承载。
# ABOUTME(en): Merge and table projection of certificate facts: CertificateFacts converge into one report-level list.
# ABOUTME(en): Calls no model; a certificate appears once across topics, and certification scope is carried only here.
from __future__ import annotations

from sustainability_desk.contract.models import GsTableCell, GsTableRow

CERTIFICATE_TABLE_BLOCK_ID = "achievements.certificate_table"


def _clean(value: object) -> str:
    return str(value).strip() if isinstance(value, str) else ""


def _name_prefix(fact: dict) -> str:
    """证书名的稳定核心：截到「认证」「证书」等收尾词，丢弃其后的副标题与英文全称。

    同一张证书两次识别，模型可能一次给出「环境管理体系认证证书」、
    另一次带上图中的英文副标题。名称尾部会漂移，核心不会。
    """

    name = _clean(fact.get("certificate_name"))
    for marker in ("认证证书", "管理体系认证", "体系认证", "认证", "证书"):
        index = name.find(marker)
        if index >= 0:
            return name[: index + len(marker)]
    return name[:20]


def _identity(fact: dict) -> str:
    """证书的去重身份：名称核心 + 发证机构。

    同一张证书可能被用户上传多次（不同议题各传一张照片），也可能一张证书天然横跨
    多个议题（一张 ISO 14001 同时适用环境、能源、污染物、废弃物、水资源）。清单按
    身份归并，使集中承载位每张证书只出现一行——这正是议题正文不再复述认证范围的前提。

    身份只用报告本来就要呈现的两个字段。曾用标准号做首选键，但那个字段在交付稿里
    出现 0 次，纯为去重而读——用实现需要反推该问模型什么，是本末倒置。
    """

    return f"{_name_prefix(fact)}|{_clean(fact.get('issuer'))}"


def certificate_facts_from_records(records) -> list[dict]:
    """从排版素材资产记录收敛出报告级证书清单，按首次出现顺序保序去重。

    只取真正解析出名称的证书：名称为空意味着图片模糊到连标题都读不出
    （入口已如实登记 unreadable_fields），这种资产不足以支撑一行公开披露。
    """

    seen: set[str] = set()
    facts: list[dict] = []
    for record in records:
        fact = getattr(record, "certificate_fact", None)
        if not isinstance(fact, dict) or not _clean(fact.get("certificate_name")):
            continue
        identity = _identity(fact)
        if identity in seen:
            continue
        seen.add(identity)
        facts.append(fact)
    return facts


def _certificate_name_cell(fact: dict) -> str:
    """名称列；持证主体不是报告主体时随名称写明，避免读者误认为报告主体自有。

    正文体裁合同已有同一条规则（「持证主体不是报告主体时写明持证主体」），但那条只
    约束模型生成的正文；本表由代码确定性成行，须在此各自落实。入口只在持证主体与
    报告主体不一致时才填 holder_name，一致则留空，故此处非空即需要标注。
    """

    name = _clean(fact.get("certificate_name"))
    holder = _clean(fact.get("holder_name"))
    return f"{name}（持证主体：{holder}）" if holder else name


def certificate_table_rows(facts: list[dict]) -> list[GsTableRow]:
    """证书清单 → 三列数据行；模型不参与，列值全部来自入口解析的原文。"""

    rows: list[GsTableRow] = []
    for fact in facts:
        rows.append(
            GsTableRow(
                children=[
                    GsTableCell(
                        colKey="cert_name", value=_certificate_name_cell(fact)
                    ),
                    GsTableCell(colKey="cert_issuer", value=_clean(fact.get("issuer"))),
                    GsTableCell(
                        colKey="cert_scope", value=_clean(fact.get("covered_scope"))
                    ),
                ]
            )
        )
    return rows
