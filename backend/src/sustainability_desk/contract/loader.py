# ABOUTME: 加载并校验 YAML 契约为 Report 对象；含章节 headingLevel 结构校验与表块列 key 标识符校验。
# ABOUTME: validate_column_keys_in_blocks 为可复用校验核心，供契约加载与议题模板加载共用。
# ABOUTME(en): Loads and validates YAML contracts into Report objects: headingLevel structure and column key checks.
# ABOUTME(en): validate_column_keys_in_blocks is the reusable core, shared by contract and topic template loading.
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

import yaml

from sustainability_desk.contract.models import (
    AssessmentVocabulary,
    Block,
    QuantitativeMetricsVocabulary,
    Report,
    Section,
)

if TYPE_CHECKING:
    from sustainability_desk.contract.knowledge_packages import KnowledgePackage


def _validate_heading_levels(sections: list[Section], parent_level: int = 0) -> None:
    """章节树 headingLevel 须为父级 + 1（顶层 = 1），不得跳级或回退。"""
    for sec in sections:
        if sec.headingLevel != parent_level + 1:
            raise ValueError(
                f"章节 {sec.key} 的 headingLevel={sec.headingLevel} 非法："
                f"应为父级层级 + 1（父级={parent_level}）。"
            )
        if sec.children:
            _validate_heading_levels(sec.children, sec.headingLevel)


def validate_column_keys_in_blocks(blocks: Iterable[Block], *, where: str) -> None:
    """表块列 key 必须是合法 ASCII Python 标识符（行模型 create_model 以其作字段名）。

    不合法时抛出 ValueError，错误信息含来源标签（where）、块 id 与非法列 key，便于定位。
    """
    for blk in blocks:
        if blk.table is None:
            continue
        for col in blk.table.colDefs:
            if not (col.key.isascii() and col.key.isidentifier()):
                raise ValueError(
                    f"[{where}] 块 {blk.id} 的列 key {col.key!r} 非法："
                    f"须为合法 ASCII 标识符（无中文/点号/短横线、不以数字开头）。"
                )
        _validate_catalog_table(blk, where=where)
        _validate_row_expansion(blk, where=where)


def _validate_row_expansion(blk: Block, *, where: str) -> None:
    """子行展开契约校验：共享列与子行列互斥、各子行列集合相同、二者并集恰覆盖全部列、
    options 收窄为列级子集、genHintOverride 只作用于本子行列。
    加载期 fail-loud，下游据此确定性推导 schema 与行结构。"""
    g = blk.generation
    if g is None:
        return
    expansion = g.rowExpansion
    if (expansion is not None) != (g.rowMode == "expanded_rows"):
        raise ValueError(
            f"[{where}] 块 {blk.id} 的 rowMode=expanded_rows 与 rowExpansion 声明须同时出现。"
        )
    if expansion is None:
        return
    if len(expansion.units) < 2:
        raise ValueError(f"[{where}] 块 {blk.id} rowExpansion 至少需两个子行，否则应使用普通均匀表。")

    col_options = {c.key: c.options for c in blk.table.colDefs}
    unit_keys = [u.key for u in expansion.units]
    if len(set(unit_keys)) != len(unit_keys):
        raise ValueError(f"[{where}] 块 {blk.id} rowExpansion 子行 key 重复：{unit_keys}。")
    for key in unit_keys:
        if not (key.isascii() and key.isidentifier()):
            raise ValueError(f"[{where}] 块 {blk.id} rowExpansion 子行 key {key!r} 须为合法 ASCII 标识符。")

    # 共享列每业务行只填一次（跨子行 rowSpan 合并）；子行列由每个子行各填一次。
    # 各子行填写的列集合必须相同——同一张表的每个子行都是一整行，列结构不能因子行而异。
    shared = set(expansion.sharedColumnKeys)
    for col_key in (*expansion.sharedColumnKeys, *(k for u in expansion.units for k in u.columnKeys)):
        if col_key not in col_options:
            raise ValueError(f"[{where}] 块 {blk.id} rowExpansion 引用了不存在的列 {col_key!r}。")
    unit_columns = {u.key: set(u.columnKeys) for u in expansion.units}
    overlap = shared & set().union(*unit_columns.values())
    if overlap:
        raise ValueError(
            f"[{where}] 块 {blk.id} 列 {sorted(overlap)} 既是共享列又归属子行；共享列与子行列须互斥。"
        )
    distinct_shapes = {frozenset(cols) for cols in unit_columns.values()}
    if len(distinct_shapes) != 1:
        raise ValueError(
            f"[{where}] 块 {blk.id} 各子行填写的列不一致：{ {k: sorted(v) for k, v in unit_columns.items()} }；"
            "每个子行都是完整一行，列集合须相同。"
        )
    covered = shared | next(iter(distinct_shapes))
    if covered != set(col_options):
        raise ValueError(
            f"[{where}] 块 {blk.id} rowExpansion 未覆盖全部列：缺 {sorted(set(col_options) - covered)}。"
        )

    for unit in expansion.units:
        if not unit.columnKeys:
            raise ValueError(f"[{where}] 块 {blk.id} 子行「{unit.label}」未绑定任何列。")
        owned = set(unit.columnKeys)
        for col_key, narrowed in (unit.optionsNarrowing or {}).items():
            if col_key not in owned:
                raise ValueError(
                    f"[{where}] 块 {blk.id} 子行「{unit.label}」收窄了非本子行的列 {col_key!r}。"
                )
            allowed = col_options.get(col_key) or []
            if not narrowed:
                raise ValueError(f"[{where}] 块 {blk.id} 子行「{unit.label}」列 {col_key!r} 的候选收窄为空。")
            extra = [opt for opt in narrowed if opt not in allowed]
            if extra:
                raise ValueError(
                    f"[{where}] 块 {blk.id} 子行「{unit.label}」列 {col_key!r} 的候选 {extra} 不在列级 options 内。"
                )
        for col_key in (unit.genHintOverride or {}):
            if col_key not in owned:
                raise ValueError(
                    f"[{where}] 块 {blk.id} 子行「{unit.label}」为非本子行的列 {col_key!r} 声明了写作要求。"
                )


def _validate_catalog_table(blk: Block, *, where: str) -> None:
    """目录表结构校验（preset_catalog / adaptive_catalog 共用）：锚点列（首个 ai_text 之前）非空、
    至少一个 ai_text 列、末列为 ai_text。preset 需 fixedRowSeeds 每条带 category；adaptive 需 rowCount 上下限
    与 referenceCatalog 典型参考清单。fail-loud 定位到来源文件。"""
    g = blk.generation
    if not (g and g.rowMode in ("preset_catalog", "adaptive_catalog")):
        return
    cols = blk.table.colDefs
    ai_idx = next((i for i, c in enumerate(cols) if c.cellType == "ai_text"), None)
    if ai_idx is None or ai_idx == 0:
        raise ValueError(f"[{where}] 块 {blk.id} {g.rowMode} 表须有锚点列（首个 ai_text 之前的前导列）与至少一个 ai_text 列。")
    if cols[-1].cellType != "ai_text":
        raise ValueError(f"[{where}] 块 {blk.id} {g.rowMode} 表末列（应对措施）须为 ai_text。")
    if blk.table.iroKind is None:
        raise ValueError(f"[{where}] 块 {blk.id} {g.rowMode} 表须声明 table.iroKind（risk / opportunity / risk_and_opportunity）。")
    if g.rowMode == "preset_catalog":
        seeds = g.fixedRowSeeds or []
        if not seeds:
            raise ValueError(f"[{where}] 块 {blk.id} preset_catalog 表须在 fixedRowSeeds 声明预设目录。")
        for seed in seeds:
            if not (seed.category and seed.category.strip()):
                raise ValueError(f"[{where}] 块 {blk.id} preset_catalog 行「{seed.theme}」缺 category（类型分组键）。")
    else:  # adaptive_catalog
        if not (g.rowCount and g.rowCount[1] >= g.rowCount[0] >= 1):
            raise ValueError(f"[{where}] 块 {blk.id} adaptive_catalog 表须声明 rowCount [min,max] 以约束前置生成条目数。")
        if not (g.referenceCatalog or []):
            raise ValueError(f"[{where}] 块 {blk.id} adaptive_catalog 表须在 referenceCatalog 声明典型参考清单（供前置生成参照）。")


def validate_column_keys(report: Report) -> None:
    """契约报告内所有表块列 key 校验入口；调用可复用核心函数。"""
    validate_column_keys_in_blocks(report.iter_blocks(), where="契约")


def validate_ai_source_paragraphs(sections: Iterable[Section], *, where: str) -> None:
    """来源合同中的 AI 段落只声明任务；占位正文不得冒充运行态内容。"""

    def blocks(section: Section) -> Iterable[Block]:
        yield from section.blocks
        if section.conciseDisclosure is not None:
            yield section.conciseDisclosure

    for section in sections:
        for block in blocks(section):
            if (
                block.type == "paragraph"
                and block.source == "ai"
                and block.blockType in {"generative", "constrained"}
            ):
                if block.content:
                    raise ValueError(f"[{where}] AI 段落 {block.id} 不得预置模板正文。")
                if block.generation is None or not block.generation.task.focus.strip():
                    raise ValueError(f"[{where}] AI 段落 {block.id} 必须通过 generation.task 声明任务。")
        validate_ai_source_paragraphs(section.children or [], where=where)


@lru_cache(maxsize=8)
def _load_contract_cached(resolved_path: str) -> Report:
    path = Path(resolved_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    report = Report.model_validate(raw)
    if path.suffix in {".yaml", ".yml"}:
        validate_ai_source_paragraphs(report.sections, where="契约")
    _validate_heading_levels(report.sections)
    validate_column_keys(report)
    from sustainability_desk.contract.knowledge_packages import knowledge_package_id_for_path

    package_id = knowledge_package_id_for_path(path)
    if package_id is not None and report.knowledgePackageId is None:
        report = report.model_copy(update={"knowledgePackageId": package_id})
    return report


def load_contract(path: Path) -> Report:
    """装载并校验报告契约;按路径进程内缓存读盘+校验(单次约 26ms),
    每次调用返回深拷贝(约 1ms),调用方可安全持有与改写。"""
    return _load_contract_cached(str(Path(path).resolve())).model_copy(deep=True)


def load_package_contract(package: "KnowledgePackage") -> Report:
    """Load a package's fixed report contract; the template carries the package identity."""

    report = load_contract(package.report_contract_path)
    if report.knowledgePackageId != package.id:
        raise ValueError(
            f"contract at {package.report_contract_path} resolved to package "
            f"{report.knowledgePackageId!r}, expected {package.id!r}"
        )
    return report


def assessment_vocabulary(package: "KnowledgePackage") -> AssessmentVocabulary:
    """The package's assessment display vocabulary; a contract without it cannot render assessments."""

    vocabulary = load_package_contract(package).assessmentVocabulary
    if vocabulary is None:
        raise ValueError(f"knowledge package {package.id} declares no assessmentVocabulary")
    return vocabulary


def quantitative_metrics_vocabulary(package: "KnowledgePackage") -> QuantitativeMetricsVocabulary:
    """The package's metrics-table wording; a contract without it cannot validate the accounting standard."""

    vocabulary = load_package_contract(package).quantitativeMetricsVocabulary
    if vocabulary is None:
        raise ValueError(f"knowledge package {package.id} declares no quantitativeMetricsVocabulary")
    return vocabulary
