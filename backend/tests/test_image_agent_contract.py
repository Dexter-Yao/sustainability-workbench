# ABOUTME: 图片识别 Agent 合同的形状与指纹校验:Dossier 指纹自校验、收据终态形状、历史 payload 回读容忍。
# ABOUTME: 本合同只承载单图识别结论;素材一律以原图进报告,不承载任何结构化重绘规格。
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sustainability_desk.material.intake.file_agent_contract import FileSourceRevision
from sustainability_desk.material.intake.image_agent_contract import (
    CertificateFact,
    ImageAgentRunReceipt,
    ImageDossier,
    ImageDossierDraft,
    image_dossier_fingerprint,
)


def _source_revision() -> FileSourceRevision:
    return FileSourceRevision(
        source_id=uuid4(),
        source_sha256="a" * 64,
        declaration_revision=1,
    )


def test_draft_accepts_minimal_recognition() -> None:
    draft = ImageDossierDraft(
        summary="ISO 9001 质量管理体系认证证书,颁发机构与有效期清晰可见。",
        category="certificate_or_award",
        caption="ISO 9001 质量管理体系认证证书",
        alt_text="公司获得的 ISO 9001 质量管理体系认证证书扫描件。",
        scope_alias="scope_1",
        placement_reason="证书类资质属于公司介绍范围。",
        certificate_fact=CertificateFact(
            certificate_name="ISO 9001 质量管理体系认证证书",
        ),
    )
    assert draft.attention_items == ()
    assert draft.certificate_fact is not None


def test_draft_rejects_retired_structured_chart_field() -> None:
    # 素材一律以原图进报告;模型若仍提交该字段,在合同边界即拒绝。
    with pytest.raises(ValidationError):
        ImageDossierDraft(
            summary="示例",
            category="document_scan",
            caption="题注",
            alt_text="替代文本",
            scope_alias="scope_1",
            placement_reason="放置原因",
            structured_chart={"kind": "process_flow", "steps": ["受理", "审批"]},  # type: ignore[call-arg]
        )


def test_dossier_fingerprint_self_validates() -> None:
    revision = _source_revision()
    fields = dict(
        summary="客户投诉处理流程图,共三个步骤,文字清晰。",
        category="other",
        caption="客户投诉处理流程",
        alt_text="展示客户投诉受理、问题分析与整改反馈三步流程的示意图。",
        scope_id="report-section:data_security",
        placement_reason="流程内容属于该议题管理举措。",
        attention_items=(),
    )
    fingerprint = image_dossier_fingerprint(source_revision=revision, **fields)
    dossier = ImageDossier(
        source_revision=revision, dossier_fingerprint=fingerprint, **fields
    )
    assert dossier.category == "other"

    with pytest.raises(ValidationError, match="内容指纹无效"):
        ImageDossier(source_revision=revision, dossier_fingerprint="b" * 64, **fields)


def test_receipt_terminal_shape() -> None:
    revision = _source_revision()
    now = datetime.now(tz=UTC)
    with pytest.raises(ValidationError, match="完成运行必须携带"):
        ImageAgentRunReceipt(
            run_id=uuid4(),
            attempt=1,
            status="completed",
            source_revision=revision,
            started_at=now,
            finished_at=now,
        )
    with pytest.raises(ValidationError, match="失败运行必须携带"):
        ImageAgentRunReceipt(
            run_id=uuid4(),
            attempt=1,
            status="failed",
            source_revision=revision,
            started_at=now,
            finished_at=now,
        )
    receipt = ImageAgentRunReceipt(
        run_id=uuid4(),
        attempt=1,
        status="failed",
        source_revision=revision,
        started_at=now,
        finished_at=now,
        failure_code="model_output_invalid",
    )
    assert receipt.dossier_fingerprint is None


def test_certificate_category_requires_parsed_certificate_fact() -> None:
    """证书类图片必须给出 typed 证书事实——条件必填放在合同层而非提示词。

    模型漏解析时应在边界失败并触发重试，不让一张证书静默退化成只有题注的配图。
    """
    with pytest.raises(ValidationError, match="必须给出 certificate_fact"):
        ImageDossierDraft(
            summary="一张环境管理体系认证证书。",
            category="certificate_or_award",
            caption="环境管理体系认证证书",
            alt_text="公司环境管理体系认证证书。",
            scope_alias="scope_1",
            placement_reason="资质属于公司介绍范围。",
        )


def test_non_certificate_category_must_not_carry_certificate_fact() -> None:
    """非证书类不得夹带证书事实，避免下游把照片当资质来源。"""
    with pytest.raises(ValidationError, match="只有 certificate_or_award"):
        ImageDossierDraft(
            summary="一张车间现场照片。",
            category="photo",
            caption="生产车间现场",
            alt_text="员工在生产线上作业。",
            scope_alias="scope_1",
            placement_reason="现场照片适合公司介绍。",
            certificate_fact=CertificateFact(certificate_name="不该出现"),
        )


def test_unreadable_certificate_fields_are_recorded_not_guessed() -> None:
    """辨认不出的字段留空并登记——fail-loud 的结构化表达。

    实测（qwen3.7-plus）：清晰证书七字段全对；高斯模糊后模型如实把七个字段
    全部登记为不可辨认，不编造。合同必须能表达这个状态，否则模型只能在猜与报错间二选一。
    """
    fact = CertificateFact(
        certificate_name="认证证书",
        unreadable_fields=("issuer", "covered_scope"),
    )
    assert fact.issuer is None
    assert fact.covered_scope is None
    assert "issuer" in fact.unreadable_fields


def test_stringified_structure_with_unescaped_quotes_is_repaired() -> None:
    """模型把嵌套结构序列化成字符串时，中文正文里的引号不会转义，整串不是合法 JSON。

    实测（真实素材夹具）：message 写成「图片底部注明"本图为…"」，
    json.loads 直接失败。若不修复，这条本该提醒用户的告警会连同整次识别一起丢失。
    """
    payload = (
        '\n[{"code": "synthetic_notice", "message": "图片底部注明"本图为合成示意图"，'
        '非真实证书。", "next_action": "确认是否替换为真实证书。"}]\n'
    )
    draft = ImageDossierDraft(
        summary="一张合成的认证证书示意图。",
        category="photo",
        caption="认证证书示意图",
        alt_text="一张标注为合成示意的证书图片。",
        scope_alias="scope_1",
        placement_reason="资质类图片适合公司介绍。",
        attention_items=payload,
    )
    assert len(draft.attention_items) == 1
    assert '"本图为合成示意图"' in draft.attention_items[0].message


def test_unrepairable_string_still_fails_loudly() -> None:
    """修不好的字符串按既有路径失败，不猜内容、不静默吞掉。"""
    with pytest.raises(ValidationError):
        ImageDossierDraft(
            summary="一张图片。",
            category="photo",
            caption="图片",
            alt_text="一张图片。",
            scope_alias="scope_1",
            placement_reason="适合公司介绍。",
            attention_items="这不是 JSON，只是一句话",
        )
