# ABOUTME: L8 schema 自动生成的后端侧测试——Literal 别名提为独立 $def + 导出产物与当前模型一致。
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sustainability_desk.contract.models import Report
from sustainability_desk.contract.schema_export import (
    build_report_api_schema,
    build_schema,
    build_section_generation_schema,
    build_stored_report_state_schema,
)

SCHEMA_JSON = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "report.schema.json"
STORED_STATE_SCHEMA_JSON = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "lib"
    / "stored-report-state.schema.json"
)
SECTION_GENERATION_SCHEMA_JSON = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "lib"
    / "section-generation.schema.json"
)
REPORT_API_SCHEMA_JSON = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "lib"
    / "report-api.schema.json"
)
LITERAL_ALIASES = [
    "BlockType", "BlockState", "Source", "NodeType", "FieldType",
    "CellType", "Mark", "Materiality",
]


def test_literal_aliases_become_named_defs():
    """Report 使用的 Literal 类型别名在 JSON Schema 中是独立 $def。"""
    defs = Report.model_json_schema()["$defs"]
    missing = [n for n in LITERAL_ALIASES if n not in defs]
    assert not missing, f"以下别名未成为独立 $def：{missing}"


def test_committed_schema_json_is_current():
    """提交的 report.schema.json 与当前 model_json_schema 一致（防 Pydantic 改了忘重导出）。"""
    committed = json.loads(SCHEMA_JSON.read_text(encoding="utf-8"))
    assert committed == build_schema(), "report.schema.json 已过期，请重跑 python -m sustainability_desk.contract.schema_export"


def test_runtime_report_rejects_unknown_nested_fields() -> None:
    with pytest.raises(ValidationError):
        Report.model_validate(
            {
                "title": "报告",
                "fields": {
                    "company": {
                        "key": "company",
                        "label": "公司",
                        "type": "string",
                        "source": "user_input",
                        "debug": "不得静默接受",
                    }
                },
                "sections": [],
            }
        )


def test_committed_runtime_boundary_schemas_are_current() -> None:
    assert json.loads(STORED_STATE_SCHEMA_JSON.read_text(encoding="utf-8")) == (
        build_stored_report_state_schema()
    )
    assert json.loads(
        SECTION_GENERATION_SCHEMA_JSON.read_text(encoding="utf-8")
    ) == build_section_generation_schema()
    assert json.loads(
        REPORT_API_SCHEMA_JSON.read_text(encoding="utf-8")
    ) == build_report_api_schema()
