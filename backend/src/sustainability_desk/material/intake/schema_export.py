# ABOUTME: 导出资料工作区公共 Pydantic 合同，供前端生成类型并执行边界解析。
# ABOUTME: 生成物只包含 HTTP 投影，不包含内部 WorkspaceState、任务 payload 或原始资料正文。
# ABOUTME(en): Exports the public material workspace Pydantic contract for frontend types and boundary parsing.
# ABOUTME(en): The artifact holds HTTP projections only, never WorkspaceState, task payloads or raw material text.
import json
from pathlib import Path

from sustainability_desk.contract.schema_export import (
    _require_defaulted_containers,
    _strip_noise,
)
from sustainability_desk.material.intake.public_models import MaterialApiContracts

OUT = (
    Path(__file__).resolve().parents[5]
    / "frontend"
    / "lib"
    / "material-workspace.schema.json"
)


def _strip_openapi_discriminators(node: object) -> None:
    """JSON Schema 的 oneOf 已足够；移除 Ajv 严格模式不接受的 OpenAPI 扩展。"""
    if isinstance(node, dict):
        node.pop("discriminator", None)
        for value in node.values():
            _strip_openapi_discriminators(value)
    elif isinstance(node, list):
        for value in node:
            _strip_openapi_discriminators(value)


def _require_locator_discriminants(schema: dict) -> None:
    """公共投影必须显式携带 locator kind，前端不得靠字段形状猜类型。"""
    definitions = schema.get("$defs", {})
    for name in (
        "PdfPageLocator",
        "DocxParagraphLocator",
        "DocxTableLocator",
        "XlsxRangeLocator",
        "ImageRegionLocator",
    ):
        definition = definitions.get(name)
        if not isinstance(definition, dict):
            continue
        required = definition.setdefault("required", [])
        if "kind" not in required:
            required.insert(0, "kind")


def build_schema() -> dict:
    schema = MaterialApiContracts.model_json_schema()
    _strip_noise(schema)
    _require_defaulted_containers(schema)
    _strip_openapi_discriminators(schema)
    _require_locator_discriminants(schema)
    return schema


def export_schema() -> None:
    OUT.write_text(
        json.dumps(build_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    export_schema()
    print(f"已导出资料 API JSON Schema → {OUT}")
