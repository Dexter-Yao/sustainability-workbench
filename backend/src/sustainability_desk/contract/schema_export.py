# ABOUTME: 由后端 Pydantic 领域模型导出前端运行时 JSON Schema 与同源 TypeScript 生成输入。
# ABOUTME: Report 与 StoredReportStateV4 均由严格模型驱动运行时解析和代码生成。
# ABOUTME(en): Exports frontend runtime JSON Schema and same-source TypeScript input from the backend Pydantic models.
# ABOUTME(en): Report and StoredReportStateV4 drive runtime parsing and codegen from strict models.
import json
from pathlib import Path

from pydantic import BaseModel

from sustainability_desk.contract.models import Report
from sustainability_desk.contract.report_api import ReportApiContractBundle
from sustainability_desk.contract.section_generation import SectionGenerationResponse
from sustainability_desk.contract.stored_report_state import StoredReportStateV4

FRONTEND_LIB = Path(__file__).resolve().parents[4] / "frontend" / "lib"
REPORT_OUT = FRONTEND_LIB / "report.schema.json"
STORED_STATE_OUT = FRONTEND_LIB / "stored-report-state.schema.json"
SECTION_GENERATION_OUT = FRONTEND_LIB / "section-generation.schema.json"
REPORT_API_OUT = FRONTEND_LIB / "report-api.schema.json"


def _strip_noise(node: object) -> None:
    """递归清理：删除 property 级 title（否则 json2ts 为每个字段生成噪音别名）；
    带 properties 的对象关闭 additionalProperties（前端类型不含未知字段；这是前端类型精确化，
    非后端运行时校验，故不要求 Pydantic extra=forbid）。"""
    if isinstance(node, dict):
        node.pop("discriminator", None)
        props = node.get("properties")
        if isinstance(props, dict):
            node.setdefault("additionalProperties", False)
            for prop in props.values():
                if isinstance(prop, dict):
                    prop.pop("title", None)
        for value in node.values():
            _strip_noise(value)
    elif isinstance(node, list):
        for item in node:
            _strip_noise(item)


def _require_defaulted_containers(node: object) -> None:
    """默认空容器（{}/[]）的字段在 API 序列化中总会返回 → 标 required；
    匹配实际返回与前端消费语义，避免生成出多余的 optional 字段。"""
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            required = node.setdefault("required", [])
            for name, prop in props.items():
                if isinstance(prop, dict) and prop.get("default") in ({}, []) and name not in required:
                    required.append(name)
        for value in node.values():
            _require_defaulted_containers(value)
    elif isinstance(node, list):
        for item in node:
            _require_defaulted_containers(item)


def _build_schema(model: type[BaseModel]) -> dict:
    """构建与后端严格运行时模型一致的前端 schema。"""

    schema = model.model_json_schema()
    _strip_noise(schema)
    _require_defaulted_containers(schema)
    return schema


def build_schema() -> dict:
    """Report 的 JSON Schema：运行时解析、前端生成与一致性校验的共同真相。"""

    return _build_schema(Report)


def build_stored_report_state_schema() -> dict:
    """StoredReportStateV4 的前后端共同 JSON Schema。"""

    return _build_schema(StoredReportStateV4)


def build_section_generation_schema() -> dict:
    """SectionGenerationResponse 的前后端共同 JSON Schema。"""

    return _build_schema(SectionGenerationResponse)


def build_report_api_schema() -> dict:
    """报告导航、持久化与状态驱动生成响应的共同 JSON Schema。"""

    return _build_schema(ReportApiContractBundle)



def export_schema() -> None:
    outputs = {
        REPORT_OUT: build_schema(),
        STORED_STATE_OUT: build_stored_report_state_schema(),
        SECTION_GENERATION_OUT: build_section_generation_schema(),
        REPORT_API_OUT: build_report_api_schema(),
    }
    for path, schema in outputs.items():
        path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    export_schema()
    print(f"已导出 JSON Schema → {REPORT_OUT.parent}")
