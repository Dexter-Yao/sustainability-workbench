# ABOUTME: GenerationSpec 生成元数据字段契约测试——typed task、targetChars、rowCount 与披露要求经 model_validate 回放。
# ABOUTME: 守护任务与证据显式声明，并确保已删除的旧任务字段加载期失败。
import pytest
from pydantic import ValidationError

from sustainability_desk.contract.models import GenerationSpec


def test_generation_spec_carries_paragraph_generation_metadata():
    spec = GenerationSpec.model_validate(
        {
            "task": {
                "focus": "说明气候治理职责。",
                "noFactGuidance": "缺少企业事实时形成低承诺方向性正文。",
            },
            "targetChars": [250, 400],
            "standardDisclosureRequirementKeys": ["climate.gov.governance_body"],
            "simplifiedWritingGuidance": ["轻量版仅作方向性概括，不扩写未提供的具体流程。"],
        }
    )
    assert spec.targetChars == (250, 400)
    assert spec.standardDisclosureRequirementKeys == ["climate.gov.governance_body"]
    assert spec.simplifiedWritingGuidance == ["轻量版仅作方向性概括，不扩写未提供的具体流程。"]
    assert spec.task.focus == "说明气候治理职责。"
    assert spec.task.noFactGuidance is not None


def test_generation_spec_carries_table_row_count():
    spec = GenerationSpec.model_validate(
        {"task": {"focus": "climate_physical_risk"}, "rowCount": [3, 6]}
    )
    assert spec.rowCount == (3, 6)


def test_generation_spec_generation_metadata_optional():
    spec = GenerationSpec.model_validate({"task": {"focus": "x"}})
    assert spec.targetChars is None
    assert spec.rowCount is None
    assert spec.standardDisclosureRequirementKeys is None
    assert spec.simplifiedWritingGuidance is None


@pytest.mark.parametrize(
    "removed",
    [
        "promptKey",
        "posture",
        "constraints",
        "regenerable",
        "industryBenchmarkWritingPatternBranch",
    ],
)
def test_generation_spec_rejects_removed_task_fields(removed: str) -> None:
    payload = {
        "task": {"focus": "说明任务。"},
        removed: (
            {
                "trigger": {"whenBlockSpecificInputsAreAbsent": True},
                "writingPatternReference": "历史写作参考。",
            }
            if removed == "industryBenchmarkWritingPatternBranch"
            else "old"
        ),
    }

    with pytest.raises(ValidationError):
        GenerationSpec.model_validate(payload)
