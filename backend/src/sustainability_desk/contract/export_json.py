# ABOUTME: 导出契约 JSON 供前端 Plate 加载：模板（结构 SSOT，字段无值）+ 样本填充实例（演示/验收）。
# ABOUTME: None 可选项剔除使输出紧凑；前端据模板构建可编辑状态，据实例预览填充效果。
# ABOUTME(en): Exports contract JSON for the frontend Plate: the template (structural SSOT) plus a filled sample.
# ABOUTME(en): Dropping None optionals keeps output compact; the template drives editing, the instance previews filling.
from pathlib import Path

from sustainability_desk.contract.knowledge_packages import KnowledgePackage, load_knowledge_package
from sustainability_desk.contract.loader import load_package_contract

ROOT = Path(__file__).resolve().parents[4]
BACKEND = Path(__file__).resolve().parents[3]
# The frontend ships one static contract projection; it follows the package the UI is built for.
FRONTEND_CONTRACT_PACKAGE_ID = "sse_zh_hans"


def _dump(report, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(report.model_dump_json(indent=2, exclude_none=True, by_alias=True), encoding="utf-8")
    return dst


def export_contract_json(package: KnowledgePackage, dst: Path) -> Path:
    """模板契约（字段无值）→ JSON。"""
    return _dump(load_package_contract(package), dst)


def export_instance_json(package: KnowledgePackage, dst: Path) -> Path:
    """样本值（inputs=CompanyInputs + content=ReportContent）→ 单一 typed 管线装配 + 内容写回 → 实例 JSON。"""
    from sustainability_desk.contract.build_report import build_report
    from sustainability_desk.contract.company_inputs import parse_company_inputs
    from sustainability_desk.contract.fill import ReportContent, apply_report_content
    from sustainability_desk.export.docx_renderer import load_values

    raw = load_values(package.sample_values_path)
    report = build_report(parse_company_inputs(raw["inputs"], package=package))
    report = apply_report_content(report, ReportContent.model_validate(raw.get("content") or {}))
    return _dump(report, dst)


def main() -> None:
    out = BACKEND / "out"
    package = load_knowledge_package(FRONTEND_CONTRACT_PACKAGE_ID)
    tpl = export_contract_json(package, out / "contract.json")
    inst = export_instance_json(package, out / "instance.json")
    print(f"contract.json: {tpl}")
    print(f"instance.json: {inst}")


if __name__ == "__main__":
    main()
