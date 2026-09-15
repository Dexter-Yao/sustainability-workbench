# ABOUTME: 证据门控（material_gated selector）机制单测——缺证据受控省略、组合门控「或」语义与合同派生。
# ABOUTME: 判定发生在 Mapping 之后、模型调用之前，属确定性 Harness 裁剪；本文件不触发任何模型调用。
from uuid import uuid4

import pytest

from sustainability_desk.contract.compiled_definition import _absence_behavior
from sustainability_desk.contract.evidence_resolution import generation_evidence_keys
from sustainability_desk.contract.models import Block, IntakeItem, Report
from sustainability_desk.llm.generate_all import BlockMappedEvidence, _material_gate_verdict
from sustainability_desk.material.mapping.decisions import BlockMaterialDecision
from knowledge_package_fixtures import SSE_PACKAGE


def _material_gated_block(intake_items: list[str] | None = None) -> Block:
    return Block.model_validate(
        {
            "id": "waste_management.iro_disposal_evidence",
            "type": "paragraph",
            "blockType": "generative",
            "source": "ai",
            "generation": {
                "task": {"focus": "基于用户上传的危废处置合同或处置记录形成有据叙述。"},
                "inputs": {
                    "evidence": {
                        "kind": "material_gated",
                        "intakeItems": intake_items or [],
                    }
                },
            },
        }
    )


def _report_with_answer(*, answered: bool) -> Report:
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[],
        intakeItems=[
            IntakeItem(
                key="waste_management.q_disposal_evidence",
                contentScopeId="waste_management",
                prompt="危险废弃物处置情况",
                kind="text",
                answer="委托有资质单位处置，签有处置合同。" if answered else None,
            )
        ],
    )


def _decision(disposition: str) -> BlockMaterialDecision:
    material_ids = (
        (uuid4(),)
        if disposition in {"supported", "partially_supported"}
        else ()
    )
    return BlockMaterialDecision(
        scope_id="report-section:waste_management",
        block_id="waste_management.iro_disposal_evidence",
        disposition=disposition,
        material_ids=material_ids,
        reason="测试判定",
    )


def test_material_gated_selector_derives_omit_absence_behavior() -> None:
    assert _absence_behavior(_material_gated_block()) == "omit_if_unsupported"


def test_other_selectors_keep_context_only_absence_behavior() -> None:
    block = Block.model_validate(
        {
            "id": "b",
            "type": "paragraph",
            "blockType": "generative",
            "source": "ai",
            "generation": {
                "task": {"focus": "x"},
                "inputs": {"evidence": {"kind": "explicit", "intakeItems": []}},
            },
        }
    )
    assert _absence_behavior(block) == "generate_context_only"


def test_material_gated_evidence_keys_expose_declared_intake_only() -> None:
    block = _material_gated_block(["waste_management.q_disposal_evidence"])
    report = _report_with_answer(answered=True)
    intake_keys, metric_keys = generation_evidence_keys(block, report, report)
    assert intake_keys == ("waste_management.q_disposal_evidence",)
    assert metric_keys == ()


@pytest.mark.parametrize(
    ("disposition", "answered", "expect_omitted"),
    [
        (None, False, True),  # 无 Mapping 决定且无答案：省略
        ("not_applicable", False, True),
        ("context_only", False, True),
        ("needs_attention", False, True),
        ("supported", False, False),  # 材料支持即出具
        ("partially_supported", False, False),
        (None, True, False),  # intake 答案支持即出具（组合门控「或」语义）
        ("not_applicable", True, False),
    ],
)
def test_material_gate_omission_decision_matrix(
    disposition: str | None, answered: bool, expect_omitted: bool
) -> None:
    block = _material_gated_block(["waste_management.q_disposal_evidence"])
    report = _report_with_answer(answered=answered)
    mapped = BlockMappedEvidence(
        decision=_decision(disposition) if disposition else None,
        file_routing_disposition=(
            "mapping_decision" if disposition else "no_applicable_file_dossier"
        ),
    )
    verdict = _material_gate_verdict(block, report, mapped)
    assert (verdict is not None) is expect_omitted
    if verdict is not None:
        # 省略时 trace 必须能直答两条门控臂各自为何未开：文件臂记 Mapping 处置
        # （无决定记 no_decision），intake 臂记「已声明但无实质答案」。
        assert verdict == {
            "sustainability_desk.material_gate.file_arm": disposition or "no_decision",
            "sustainability_desk.material_gate.intake_arm": "no_substantive_answer",
        }


def test_gate_intake_arm_rejects_pure_status_marker_supplement() -> None:
    """纯状态标记补充说明（「暂无」）不得打开门控；真实事实补充照常开门。

    门控 selector 声明「存在实质答案」，零证据不得出具。
    姿态与 prompt 投影不受影响（否定状态补充仍按口径信息进入生成）。
    """
    block = _material_gated_block(["waste_management.q_disposal_evidence"])
    mapped = BlockMappedEvidence()

    marker_only = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[],
        intakeItems=[
            IntakeItem(
                key="waste_management.q_disposal_evidence",
                contentScopeId="waste_management",
                prompt="危险废弃物处置情况",
                kind="text",
                answer=None,
                supplement="暂无",
            )
        ],
    )
    assert _material_gate_verdict(block, marker_only, mapped) is not None

    real_supplement = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[],
        intakeItems=[
            IntakeItem(
                key="waste_management.q_disposal_evidence",
                contentScopeId="waste_management",
                prompt="危险废弃物处置情况",
                kind="text",
                answer=None,
                supplement="委托苏州绿净环保处置，联系电话 0512-0000 0000。",
            )
        ],
    )
    assert _material_gate_verdict(block, real_supplement, mapped) is None


def test_pure_material_gate_ignores_unrelated_intake_answers() -> None:
    """未声明 intakeItems 的纯材料门控块：其他题有答案也不放行。"""
    block = _material_gated_block([])
    report = _report_with_answer(answered=True)
    mapped = BlockMappedEvidence()
    verdict = _material_gate_verdict(block, report, mapped)
    assert verdict is not None
    assert verdict["sustainability_desk.material_gate.intake_arm"] == "not_declared"


def test_batch_one_blocks_compile_with_omit_absence_behavior() -> None:
    """批次 1 两个真实证据门控块的编译合同：组合门控与纯材料门控各一。"""
    from sustainability_desk.contract.compiled_definition import load_compiled_report_definition

    definition = load_compiled_report_definition(SSE_PACKAGE)
    expected = {
        "anti_bribery_anti_corruption.iro_whistleblowing_mechanism": (
            "anti_bribery_anti_corruption.q_whistleblowing_channels",
        ),
        "waste_management.iro_hazardous_disposal_evidence": (),
        "environmental_compliance_management.iro_compliance_audit_evidence": (),
        "sustainable_supply_chain_management.iro_supplier_traceability_commitments": (),
        "sustainable_supply_chain_management.iro_responsible_minerals": (),
        "data_security_customer_privacy_protection.iro_drills_continuity_evidence": (),
        "product_quality_safety.iro_recall_feedback_evidence": (),
        "anti_unfair_competition.iro_partner_fair_competition_terms": (),
        "sm.strategy": ("sustainability_strategy",),
    }
    actual_gated = {
        contract.block_id
        for contract in definition.generation_contracts.values()
        if contract.absence_behavior == "omit_if_unsupported"
    }
    assert actual_gated == set(expected)
    for block_id, intake_ids in expected.items():
        contract = definition.generation_for_block(block_id)
        assert contract.absence_behavior == "omit_if_unsupported", block_id
        assert contract.intake_item_ids == intake_ids, block_id


def test_persistence_accepts_material_gated_paragraph_omission() -> None:
    """受控省略资格以编译合同为准：门控段落可省略、普通段落不可、无理由不可。"""
    from sustainability_desk.persistence.section_generations import _is_allowed_omission

    item = {
        "blockId": "waste_management.iro_hazardous_disposal_evidence",
        "kind": "paragraph",
        "status": "omitted",
        "reason": "本块按报告合同仅在有对应资料支持时出具；本轮未获得适用资料，已省略。",
    }
    assert _is_allowed_omission(item, allow_contract_omissions=False, package=SSE_PACKAGE)
    assert not _is_allowed_omission({**item, "reason": ""}, allow_contract_omissions=False, package=SSE_PACKAGE)
    assert not _is_allowed_omission(
        {**item, "blockId": "waste_management.iro_classification_and_disposal"},
        allow_contract_omissions=False, package=SSE_PACKAGE,
    )


def test_apply_generation_results_stores_omitted_paragraph_state() -> None:
    from sustainability_desk.persistence.section_generations import apply_generation_results

    block_id = "waste_management.iro_hazardous_disposal_evidence"
    patched = apply_generation_results(
        {},
        (block_id,),
        [
            {
                "blockId": block_id,
                "kind": "paragraph",
                "status": "omitted",
                "reason": "本块按报告合同仅在有对应资料支持时出具；本轮未获得适用资料，已省略。",
            }
        ], package=SSE_PACKAGE,
    )
    assert patched["generatedBlocks"][block_id] == {"state": "omitted"}


def test_non_material_gated_block_is_never_pruned_by_gate() -> None:
    block = Block.model_validate(
        {
            "id": "b",
            "type": "paragraph",
            "blockType": "generative",
            "source": "ai",
            "generation": {
                "task": {"focus": "x"},
                "inputs": {"evidence": {"kind": "explicit", "intakeItems": []}},
            },
        }
    )
    assert _material_gate_verdict(block, Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[]), BlockMappedEvidence()) is None


def test_report_level_completion_accepts_material_gated_paragraph_omission() -> None:
    """报告级完结校验：门控段落省略计成功、普通段落省略仍被拒（合同判定，不信任自述）。"""
    from sustainability_desk.persistence.lightweight_report_generations import _validate_completion

    gated = "waste_management.iro_hazardous_disposal_evidence"
    plain = "waste_management.iro_classification_and_disposal"
    fingerprint = "a" * 64
    omitted = {
        "blockId": gated,
        "kind": "paragraph",
        "status": "omitted",
        "reason": "本块按报告合同仅在有对应资料支持时出具；本轮未获得适用资料，已省略。",
    }
    ready = {"blockId": plain, "kind": "paragraph", "status": "ready"}

    _validate_completion(
        expected_block_ids=(gated, plain),
        content_fingerprint=fingerprint,
        block_results=(omitted, ready),
        artifacts=(),
        export_blocked=True, package=SSE_PACKAGE,
    )

    import pytest as _pytest

    with _pytest.raises(ValueError, match="必须成功生成或形成受控"):
        _validate_completion(
            expected_block_ids=(gated, plain),
            content_fingerprint=fingerprint,
            block_results=(
                {**omitted, "blockId": plain},
                {**ready, "blockId": gated},
            ),
            artifacts=(),
            export_blocked=True, package=SSE_PACKAGE,
        )


def test_omitted_paragraph_state_collapses_section_via_report_revision() -> None:
    """机制核心承诺端到端：存量 {state:"omitted"} 段落经修订投影后不可渲染，
    单块 H4 整节从正文与目录消失。"""
    from sustainability_desk.contract.renderability import (
        block_is_renderable,
        section_is_renderable,
    )
    from sustainability_desk.contract.report_revision import build_report_revision
    from sustainability_desk.contract.stored_report_state import empty_stored_report_state

    block_id = "anti_bribery_anti_corruption.iro_whistleblowing_mechanism"
    payload = empty_stored_report_state().model_dump(by_alias=True, mode="json")
    payload["generatedBlocks"] = {block_id: {"state": "omitted"}}
    from sustainability_desk.contract.stored_report_state import StoredReportStateV4

    state = StoredReportStateV4.model_validate(payload)
    revision = build_report_revision(state, tolerate_incomplete_assessment=True, package=SSE_PACKAGE)

    def find(sections):
        for section in sections:
            for block in section.blocks:
                if block.id == block_id:
                    return section, block
            found = find(section.children or [])
            if found:
                return found
        return None

    located = find(revision.sections)
    assert located is not None, "举报机制块必须在完整轻量版修订树内"
    section, block = located
    assert block.state == "omitted"
    assert not block_is_renderable(block, revision)
    assert not section_is_renderable(section, revision)


def test_stored_state_with_retired_disclosure_detail_level_still_parses() -> None:
    """迁移 shim 回归：存量 JSONB 带已废弃 disclosureDetailLevel 键必须可读且被剥离。

    shim 被误删时存量读取会直接 ValidationError；本测试是其唯一报警器
    （complete_batch 等原样写回路径不冲洗旧键，见 models.py shim 注释）。
    """
    from sustainability_desk.contract.stored_report_state import StoredReportStateV4, empty_stored_report_state

    payload = empty_stored_report_state().model_dump(by_alias=True, mode="json")
    payload["disclosureProfile"] = {
        "mainlandStandard": "szse",
        "includesHongKongExchangeGuide": False,
        "additionalDisclosureReferences": [],
        "disclosureDetailLevel": "lightweight",
    }
    parsed = StoredReportStateV4.model_validate(payload)
    assert parsed.disclosureProfile is not None
    assert parsed.disclosureProfile.mainlandStandard == "szse"
    assert "disclosureDetailLevel" not in parsed.disclosureProfile.model_dump()

