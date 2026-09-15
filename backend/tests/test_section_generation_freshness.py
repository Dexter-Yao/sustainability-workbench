# ABOUTME: 页面生成新鲜度指纹测试，锁定模型可见输入变化与正文编辑的不同语义。
# ABOUTME: 指纹只描述目标页面生成输入；它不把生成正文自身变成循环依赖。
from sustainability_desk.contract.models import (
    Block,
    ExplicitGenerationEvidenceSelector,
    GenerationInputs,
    GenerationSpec,
    GenerationTask,
    Inline,
    IntakeItem,
    Report,
    Section,
)
from sustainability_desk.persistence.section_generations import (
    section_generation_input_fingerprint,
)
from knowledge_package_fixtures import SSE_PACKAGE


def _report() -> Report:
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="新鲜度测试",
        sections=[
            Section(
                key="climate_change",
                title="应对气候变化",
                headingLevel=2,
                reportSectionId="climate_change",
                blocks=[
                    Block(
                        id="climate.summary",
                        type="paragraph",
                        blockType="generative",
                        source="ai",
                        content=[Inline(kind="text", text="原正文")],
                        generation=GenerationSpec(
                            task=GenerationTask(focus="说明气候工作"),
                            inputs=GenerationInputs(
                                evidence=ExplicitGenerationEvidenceSelector(
                                    kind="explicit",
                                    intakeItems=["climate.q_demo"],
                                )
                            ),
                        ),
                    )
                ],
            )
        ],
        intakeItems=[
            IntakeItem(
                key="climate.q_demo",
                contentScopeId="climate_change",
                prompt="是否开展气候工作？",
                kind="text",
                answer="是",
            )
        ],
    )


def test_generation_fingerprint_changes_with_visible_fact_not_generated_text(
    monkeypatch,
) -> None:
    report = _report()
    monkeypatch.setattr("sustainability_desk.llm.generate._template", lambda *_: report)
    baseline = section_generation_input_fingerprint(
        report,
        "climate_change",
        allow_synthetic_definition_fallback=True,
    )

    report.sections[0].blocks[0].content = [
        Inline(kind="text", text="用户手工修改后的正文")
    ]
    assert (
        section_generation_input_fingerprint(
            report,
            "climate_change",
            allow_synthetic_definition_fallback=True,
        )
        == baseline
    )

    report.intakeItems[0].answer = "否"
    assert (
        section_generation_input_fingerprint(
            report,
            "climate_change",
            allow_synthetic_definition_fallback=True,
        )
        != baseline
    )
