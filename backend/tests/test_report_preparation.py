# ABOUTME: 验证轻量版准备中心以 Profile 字段与 compiled 输入义务共同阻断生成，议题引导问题不阻断。
# ABOUTME: 资料处理和待确认状态对用户可见，但不成为轻量版自动流程的人工作业门。
from uuid import uuid4

from sustainability_desk.contract.models import (
    MaterialityAssessmentInput,
    MaterialityScoreInput,
    MaterialityThreshold,
    QuantitativeMetricDraft,
    QuantitativeMetricsMeta,
)
from sustainability_desk.contract.report_preparation import project_report_preparation
from sustainability_desk.contract.report_profiles import require_report_profile
from sustainability_desk.contract.stored_report_state import (
    StoredIntakeAnswer,
    StoredReportMetaV4,
    StoredReportStateV4,
)


def _preparation(
    state: StoredReportStateV4, *, primary_input_mode: str | None = "questions"
):
    return project_report_preparation(
        report_id=uuid4(),
        report_state_seq=1,
        state=state,
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=0,
        # 定量信息不是生成门槛，留空按「尚未收集」在范围投影补全。
        required_quantitative_metric_keys=None,
        primary_input_mode=primary_input_mode,
    )


def _state(**fields: str) -> StoredReportStateV4:
    return StoredReportStateV4(version=4, fields=fields)


def test_profile_fields_and_generation_obligations_block_first_generation() -> None:
    projection = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=1,
        state=_state(),
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=0,
    )

    assert not projection.generation_eligible
    # 生成门槛只有 profile.generation_required_field_ids；公司简介已不再阻断生成，
    # 报告期起止为可选（由报告年份派生默认值）。
    assert {item.target_handle for item in projection.generation_blockers} == {
        "field.company_registered_name",
        "field.industry_major_category",
        "field.reporting_year",
    }
    assert [area.status for area in projection.areas] == [
        "needs_input",
        "optional_empty",
        "optional_empty",
        "optional_empty",
    ]
    # 未做二选一的报告不预设主输入路径；前端据 None 引导用户选择。
    assert projection.primary_input_mode is None


def test_primary_input_mode_projects_report_level_choice() -> None:
    projection = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=1,
        state=_state(),
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=0,
        primary_input_mode="questions",
    )

    assert projection.primary_input_mode == "questions"
    # questions 路径追加「议题信息」区块（materials 区块保持在末位）；
    # 问题全部选填，空回答是 optional_empty 而非门槛。
    questions_area = next(
        area for area in projection.areas if area.id == "topic_questions"
    )
    assert questions_area.required_for_generation is False
    assert questions_area.status == "optional_empty"
    assert questions_area.href == "/intake/questions"

    materials_projection = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=1,
        state=_state(),
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=0,
        primary_input_mode="materials",
    )
    assert all(
        area.id != "topic_questions" for area in materials_projection.areas
    )


def test_topic_questions_area_counts_answered_topic_items() -> None:
    state = _state().model_copy(
        update={
            "intakeItems": {
                # 议题题：计入回答进度。
                "climate.q_climate_risk_choices": StoredIntakeAnswer(answer=["台风"]),
                # 报告级题（front_* scope）：不计入议题信息区块。
                "company_profile": StoredIntakeAnswer(answer="公司简介内容。"),
                # 空列表多选与空白文本都不算已回答。
                "climate.q_climate_opportunity_choices": StoredIntakeAnswer(answer=[]),
            }
        }
    )
    projection = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=1,
        state=state,
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=0,
        primary_input_mode="questions",
    )

    questions_area = next(
        area for area in projection.areas if area.id == "topic_questions"
    )
    assert questions_area.status == "ready"
    assert questions_area.summary.startswith("已回答 1 / ")


def test_zero_files_assessment_and_metrics_do_not_block_lightweight_report() -> None:
    projection = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=2,
        state=_state(
            company_registered_name="汉美科技股份有限公司",
            industry_major_category="制造业",
            report_period_start="2025-01-01",
            report_period_end="2025-12-31",
            reporting_year="2025",
        ).model_copy(
            update={
                "intakeItems": {
                    "company_profile": StoredIntakeAnswer(
                        answer="公司从事节能设备研发、制造与服务，业务覆盖多个行业客户。"
                    )
                }
            }
        ),
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=0,
    )

    assert projection.generation_eligible
    assert not projection.generation_blockers
    assert projection.areas[0].status == "ready"
    assert all(
        area.status == "optional_empty" for area in projection.areas[1:]
    )


def test_basic_info_alone_makes_lightweight_report_generation_eligible() -> None:
    """轻量版定位：只填四项基本信息即可生成。

    不填公司简介、不填重要性评分、不填定量信息、不传资料，都不得阻断生成。
    """

    projection = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=2,
        state=_state(
            company_registered_name="汉美科技股份有限公司",
            industry_major_category="制造业",
            report_period_start="2025-01-01",
            report_period_end="2025-12-31",
            reporting_year="2025",
        ),
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=0,
    )

    assert projection.generation_eligible
    assert not projection.generation_blockers


def test_optional_inputs_and_file_attention_have_user_friendly_status() -> None:
    state = _state(
        company_registered_name="汉美科技股份有限公司",
        industry_major_category="制造业",
        report_period_start="2025-01-01",
        report_period_end="2025-12-31",
        reporting_year="2025",
    ).model_copy(
        update={
            "intakeItems": {
                "company_profile": StoredIntakeAnswer(
                    answer="公司从事节能设备研发、制造与服务，业务覆盖多个行业客户。"
                )
            },
            "assessmentInput": MaterialityAssessmentInput(
                reportingYear=2025,
                threshold=MaterialityThreshold(financial=3, impact=3),
                scores=[
                    MaterialityScoreInput(
                        assessmentTopicId="climate_change",
                        financialScore=4,
                        impactScore=4,
                    )
                ],
            ),
            "meta": StoredReportMetaV4(
                quantitativeMetrics=QuantitativeMetricsMeta(
                    metrics={
                        "energy_consumption": QuantitativeMetricDraft(
                            value="100"
                        )
                    }
                )
            ),
        }
    )
    projection = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=3,
        state=state,
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=3,
        attention_item_count=2,
    )

    assert projection.generation_eligible
    # 只评了 1 个议题：评分未覆盖全部适用议题，生成时按未评分处理，
    # 因此呈现为 needs_input 而不是 ready。
    assert projection.areas[1].status == "needs_input"
    assert projection.assessment_partially_scored
    assert projection.assessment_scored_topic_count == 1
    assert projection.assessment_applicable_topic_count > 1
    assert projection.areas[2].status == "ready"
    assert projection.areas[3].status == "needs_attention"
    assert "可选确认" in projection.areas[3].summary


def test_no_value_reason_placeholders_do_not_count_as_filled_metrics() -> None:
    """定量页自动保存把留空项整批记为「尚未收集」；该占位与备注都不算已填写。

    「已填写」与定量页完成度、附录 KPI 表同口径：只数数值非空的指标。
    """
    state = _state().model_copy(
        update={
            "meta": StoredReportMetaV4(
                quantitativeMetrics=QuantitativeMetricsMeta(
                    metrics={
                        "energy_consumption": QuantitativeMetricDraft(
                            noValueReason="not_collected"
                        ),
                        "water_consumption": QuantitativeMetricDraft(
                            noValueReason="not_collected", note="数据整理中"
                        ),
                    }
                )
            ),
        }
    )
    projection = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=2,
        state=state,
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=0,
    )

    metrics_area = next(
        area for area in projection.areas if area.id == "quantitative_metrics"
    )
    assert metrics_area.status == "optional_empty"
    assert metrics_area.summary == "尚未填写；不会阻断轻量版生成。"


def test_mapping_progress_is_not_described_as_file_understanding() -> None:
    projection = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=3,
        state=_state(),
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=4,
        processing_mapping_scope_count=8,
    )

    materials = next(area for area in projection.areas if area.id == "materials")
    assert materials.status == "processing"
    # design.md §7.1：资料语义一律用「处理」不用「理解」——「理解」是对模型能力的过度承诺。
    assert materials.summary == "已处理 4 份文件，8 个报告范围正在匹配资料。"
    assert "理解" not in materials.summary


def test_pending_file_description_blocks_generation_but_not_zero_files() -> None:
    """待补充说明的 active 文件会阻断生成；完全没有文件仍是 optional，不阻断。"""

    base_state = _state(
        company_registered_name="汉美科技股份有限公司",
        industry_major_category="制造业",
        report_period_start="2025-01-01",
        report_period_end="2025-12-31",
        reporting_year="2025",
    ).model_copy(
        update={
            "intakeItems": {
                "company_profile": StoredIntakeAnswer(
                    answer="公司从事节能设备研发、制造与服务，业务覆盖多个行业客户。"
                )
            },
        }
    )

    zero_files = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=1,
        state=base_state,
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=0,
        pending_file_description_count=0,
    )
    assert zero_files.generation_eligible
    materials_area = next(area for area in zero_files.areas if area.id == "materials")
    assert materials_area.status == "optional_empty"

    pending_description = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=2,
        state=base_state,
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=2,
        pending_file_description_count=2,
    )
    assert not pending_description.generation_eligible
    assert {
        blocker.target_handle for blocker in pending_description.generation_blockers
    } == {"materials.pending_description"}
    blocker = pending_description.generation_blockers[0]
    assert blocker.href == "/materials"
    assert "2 份文件待补充说明" in blocker.message
    materials_area = next(
        area for area in pending_description.areas if area.id == "materials"
    )
    assert materials_area.status == "needs_input"
    assert "待补充说明" in materials_area.summary

    # 问答路径下只有排版素材缺说明时，入口由调用方指向议题信息页；blocker 文案不变。
    questions_path = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=3,
        state=base_state,
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=1,
        pending_file_description_count=1,
        primary_input_mode="questions",
        pending_description_href="/intake/questions",
    )
    blocker = questions_path.generation_blockers[0]
    assert blocker.target_handle == "materials.pending_description"
    assert blocker.href == "/intake/questions"
    assert "1 份文件待补充说明" in blocker.message


def test_material_set_confirmation_blocker_coexists_with_pending_description() -> None:
    """共存矩阵：零文件无 blocker；缺说明时只出缺说明；说明齐未确认才出确认。"""

    base_state = _state(
        company_registered_name="汉美科技股份有限公司",
        industry_major_category="制造业",
        report_period_start="2025-01-01",
        report_period_end="2025-12-31",
        reporting_year="2025",
    ).model_copy(
        update={
            "intakeItems": {
                "company_profile": StoredIntakeAnswer(
                    answer="公司从事节能设备研发、制造与服务，业务覆盖多个行业客户。"
                )
            },
        }
    )

    zero_files = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=1,
        state=base_state,
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=0,
        pending_file_description_count=0,
        material_set_requires_confirmation=False,
    )
    assert zero_files.generation_eligible
    assert not zero_files.generation_blockers

    pending_description_and_unconfirmed = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=2,
        state=base_state,
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=2,
        pending_file_description_count=1,
        material_set_requires_confirmation=True,
    )
    assert {
        blocker.target_handle
        for blocker in pending_description_and_unconfirmed.generation_blockers
    } == {"materials.pending_description"}

    described_but_unconfirmed = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=3,
        state=base_state,
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=2,
        pending_file_description_count=0,
        material_set_requires_confirmation=True,
    )
    assert not described_but_unconfirmed.generation_eligible
    assert {
        blocker.target_handle
        for blocker in described_but_unconfirmed.generation_blockers
    } == {"materials.unconfirmed"}
    blocker = described_but_unconfirmed.generation_blockers[0]
    assert blocker.href == "/materials"

    confirmed = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=4,
        state=base_state,
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=2,
        pending_file_description_count=0,
        material_set_requires_confirmation=False,
    )
    assert confirmed.generation_eligible
    assert not confirmed.generation_blockers


def test_topic_questions_never_block_generation_on_either_input_path() -> None:
    """议题引导问题全部选填：无论 materials 还是 questions 路径都不得阻断生成。

    这是与导出闸口径统一的生成侧一半：两闸都不把议题义务当门槛，
    只改一侧就会出现"生成得了却导不出"。
    """
    from local_e2e_fixture import (
        load_local_e2e_fixture_recipe,
        synthesize_stored_report_state,
    )

    state = synthesize_stored_report_state(load_local_e2e_fixture_recipe())
    stripped = state.model_copy(
        update={
            "intakeItems": {
                key: value
                for key, value in state.intakeItems.items()
                if not key.startswith("climate.")
            }
        }
    )

    materials = _preparation(stripped, primary_input_mode="materials")
    assert not [
        blocker
        for blocker in materials.generation_blockers
        if blocker.target_handle.startswith("climate.")
    ]
    # materials 路径不展示议题信息区块（该步不在其序列里）。
    assert "topic_questions" not in {area.id for area in materials.areas}

    questions = _preparation(stripped, primary_input_mode="questions")
    assert not [
        blocker
        for blocker in questions.generation_blockers
        if blocker.target_handle.startswith("climate.")
    ]


def test_inverted_report_period_blocks_generation() -> None:
    """报告期截止早于起始是非法领域状态,必须以结构化阻断项拦下,不得流入生成。"""

    projection = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=1,
        state=_state(
            company_registered_name="示例企业",
            industry_major_category="制造业",
            report_period_start="2025-12-31",
            report_period_end="2025-01-01",
        ),
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=0,
    )
    handles = {item.target_handle for item in projection.generation_blockers}
    assert "field.report_period_range" in handles
    assert not projection.generation_eligible
    blocker = next(
        item
        for item in projection.generation_blockers
        if item.target_handle == "field.report_period_range"
    )
    assert "截止日期不能早于起始日期" in blocker.message

    valid = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=1,
        state=_state(
            company_registered_name="示例企业",
            industry_major_category="制造业",
            report_period_start="2025-01-01",
            report_period_end="2025-12-31",
            reporting_year="2025",
        ),
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=0,
    )
    assert "field.report_period_range" not in {
        item.target_handle for item in valid.generation_blockers
    }


def test_sentence_style_obligation_label_is_not_double_prefixed() -> None:
    """句子型义务 label(如公司简介的完整提示)不得再包一层"请完成…。",避免病句。"""

    projection = project_report_preparation(
        report_id=uuid4(),
        report_state_seq=1,
        state=_state(
            company_registered_name="示例企业",
            industry_major_category="制造业",
            report_period_start="2025-01-01",
            report_period_end="2025-12-31",
            reporting_year="2025",
        ),
        profile=require_report_profile("sse_zh_hans@1"),
        active_file_count=0,
    )
    for blocker in projection.generation_blockers:
        assert "请完成请" not in blocker.message
        assert "。。" not in blocker.message


def test_preparation_projects_the_materiality_area_so_the_step_can_complete() -> None:
    """准备中心必须产出评分区块，否则左栏那一步永远无法完成。

    步骤是否展示读 collects_materiality_assessment（对所有范围恒为 True），
    步骤能否完成读 preparation.areas。若区块按报告侧口径裁剪，两侧口径不一致：
    用户把评分填满，圆点仍恒为灰、列表完成度分母也少一项。
    评分不参与生成资格由 required_for_generation=False 表达，不靠裁剪区块。
    """
    from inspect import signature

    from sustainability_desk.contract.report_preparation import project_report_preparation

    # 不得再引入任何 include_* 开关裁剪该区块——那正是口径分裂的来源。
    assert "include_materiality" not in signature(project_report_preparation).parameters

    projection = _preparation(_state())
    materiality = next((a for a in projection.areas if a.id == "materiality"), None)

    assert materiality is not None, "缺少评分区块，左栏评分步将永远停在未完成"
    # 展示≠阻断：区块在场，但不参与生成资格判定。
    assert materiality.required_for_generation is False
    assert not any("materiality" in b.target_handle for b in projection.generation_blockers)


def test_every_required_field_has_a_chinese_label() -> None:
    """必填字段都必须有中文名，缺一个就会让界面显示裸英文标识符。

    `reporting_year` 曾是必填却未登记，阻断文案退化成「请填写reporting_year。」，
    任何范围都会遇到。这里从 Profile 反射必填清单，使新增必填字段自动纳入覆盖。
    """
    from sustainability_desk.contract.report_preparation import _field_label
    from sustainability_desk.contract.report_profiles import require_report_profile

    for profile_id in ("sse_zh_hans@1",):
        profile = require_report_profile(profile_id)
        for field_id in profile.generation_required_field_ids:
            label = _field_label(field_id)
            assert label != field_id, f"{field_id} 未登记中文名"
            assert not label.isascii(), f"{field_id} 的文案仍是英文：{label}"


def test_missing_field_label_fails_loudly() -> None:
    """未登记的字段直接抛错，不静默把标识符当文案给用户。"""
    from sustainability_desk.contract.report_preparation import _field_label

    import pytest

    with pytest.raises(KeyError, match="缺少用户可见中文名"):
        _field_label("some_unregistered_field")


def test_scoring_step_is_absent_when_the_package_does_not_score_materiality(monkeypatch) -> None:
    """评分步骤的存在由知识包的 materiality_regime 决定，不是每份报告都有的固定步骤。

    applicability 型准则（如 VSME）按「是否适用于本企业」逐条取舍，没有重要性评分这一步；
    投影仍产出该区块就会让用户看见一个永远填不完、也不该存在的步骤。当前四个包都不是
    该型，故此处构造一个，否则这条分支无任何用例覆盖。
    """
    from sustainability_desk.contract import report_preparation
    from sustainability_desk.contract.knowledge_packages import knowledge_package_of

    def area_ids(state: StoredReportStateV4) -> list[str]:
        return [area.id for area in _preparation(state).areas]

    assert "materiality" in area_ids(_state())

    real = knowledge_package_of

    def as_applicability(report):
        package = real(report)
        return package.model_copy(
            update={"manifest": package.manifest.model_copy(update={"materiality_regime": "applicability"})}
        )

    monkeypatch.setattr(report_preparation, "knowledge_package_of", as_applicability)
    ids = area_ids(_state())
    assert "materiality" not in ids
    # 其余步骤不受影响：关掉的是评分，不是整个准备流程。
    assert "report_identity" in ids and "quantitative_metrics" in ids
