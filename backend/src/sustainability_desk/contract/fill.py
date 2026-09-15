# ABOUTME: 把一份值字典（fields/generated/tables）填入模板 Report，产出自包含填充 Report。
# ABOUTME: 字段值→Field.value、生成正文→Block.content、表格数据行→GsTable.children；块驱动，未知键忽略。
# ABOUTME(en): Fills a values dict (fields/generated/tables) into a template Report, yielding a self-contained Report.
# ABOUTME(en): Field values to Field.value, prose to Block.content, rows to GsTable.children; unknown keys ignored.
from pydantic import BaseModel, ConfigDict

from sustainability_desk.contract.models import AppendixPackage, DisclosureProfile, AssessmentResult, Inline, Report
from sustainability_desk.contract.table_ops import harvest_table_rows


class ReportContent(BaseModel):
    """生成正文写回的 typed 契约（取代裸 dict 的 generated/tables）：块级正文 + 表格数据行。"""

    model_config = ConfigDict(extra="forbid")

    generated: dict[str, str] = {}                      # block id → 段落正文
    tables: dict[str, list[dict]] = {}                  # block id → 数据行 [{列key: 值}]


def _accepts_generated_text(block) -> bool:
    return block.type == "paragraph" and block.blockType in {"generative", "constrained"}


def apply_report_content(report: Report, content: ReportContent) -> Report:
    """把生成正文/表格行写回 Report（深拷贝，不改传入）；预置表头行保留、仅替换数据行。"""
    report = report.model_copy(deep=True)
    for blk in report.iter_blocks():
        if blk.id in content.generated and _accepts_generated_text(blk):
            blk.content = [Inline(kind="text", text=str(content.generated[blk.id]))]
        if blk.table is not None and blk.id in content.tables:
            header_rows = [r for r in blk.table.children if r.headerRow]
            blk.table.children = header_rows + harvest_table_rows(blk,content.tables[blk.id])
    return report


def fill_report(report: Report, values: dict) -> Report:
    """填充并返回 report 的新副本：字段值 / 生成正文 / 表格行 / 结构化问卷各归其位。

    纯函数——深拷贝后填充，不改传入 report，避免复用同一模板契约连续装配时交叉污染。
    """
    report = report.model_copy(deep=True)
    fields_v = values.get("fields", {}) or {}
    for key, field in report.fields.items():
        if key in fields_v:
            field.value = fields_v[key]

    gen = values.get("generated", {}) or {}
    tbls = values.get("tables", {}) or {}
    for blk in report.iter_blocks():
        if blk.id in gen and _accepts_generated_text(blk):
            blk.content = [Inline(kind="text", text=str(gen[blk.id]))]
        if blk.table is not None and blk.id in tbls:
            entries = tbls[blk.id]
            for i, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    raise ValueError(
                        f"表块 {blk.id} 第 {i} 行应为列键字典（{{列key: 值}}），实为 {type(entry).__name__}"
                    )
            # 预置表头行（含跨列大标题/列名行）保留，仅替换数据行
            header_rows = [r for r in blk.table.children if r.headerRow]
            blk.table.children = header_rows + harvest_table_rows(blk,entries)

    if values.get("disclosureProfile"):
        report.disclosureProfile = DisclosureProfile.model_validate(values["disclosureProfile"])
    if values.get("appendixPackage"):
        report.appendixPackage = AppendixPackage.model_validate(values["appendixPackage"])

    intake_v = values.get("intake", {}) or {}
    for item in report.intakeItems:
        if item.key not in intake_v:
            continue
        spec = intake_v[item.key]
        if isinstance(spec, dict):  # {answer?, supplement?}
            if "answer" in spec:
                item.answer = spec["answer"]
            if "supplement" in spec:
                item.supplement = spec["supplement"]
        else:  # 标量直接作答案（填空题或单选）
            item.answer = spec

    assess = values.get("assessment")
    if assess:
        report.assessment = AssessmentResult.model_validate(assess)
    return report
