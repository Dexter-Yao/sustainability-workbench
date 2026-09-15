# ABOUTME: 表格 AI 生成编排——定行(propose_rows)/单行补全(complete_row)/行级并发(fill_table_rows)/单行重生成。
# ABOUTME: 三能力共用单行补全逻辑；行级并发用 bounded_gather（max_concurrency + 失败隔离 + 顺序对应）。
# ABOUTME(en): Table generation: propose_rows, complete_row, row-level fill_table_rows and single-row regeneration.
# ABOUTME(en): All three share the single-row completion logic; row concurrency uses bounded_gather with isolation.
from __future__ import annotations

import logging

from pydantic import create_model

from sustainability_desk.contract.compiled_definition import load_compiled_report_definition
from sustainability_desk.contract.knowledge_packages import knowledge_package_of
from sustainability_desk.contract.loader import assessment_vocabulary
from sustainability_desk.contract.evidence_resolution import intake_ready_text
from sustainability_desk.contract.models import (
    Block,
    ExplicitGenerationEvidenceSelector,
    FixedRowSeed,
    GsColDef,
    Report,
    RowOrigin,
)
from sustainability_desk.contract.topic_registry import load_topic_contract
from sustainability_desk.contract.table_ops import (
    build_expanded_rows,
    build_preset_catalog_rows,
    data_row,
    resolve_preset_row_seeds,
)
from sustainability_desk.contract.visibility import visible, visible_block_in_report
from sustainability_desk.llm.concurrency import MAX_INFLIGHT_LLM_CALLS, bounded_gather, run_agent
from sustainability_desk.llm.ai_observability import (
    GuardrailIssueTrace,
    ObservationRun,
    record_guardrail_evaluation,
)
from sustainability_desk.llm.generation_guardrails import (
    GuardrailIssue,
    GuardrailViolation,
    MAX_GENERATION_ATTEMPTS,
    check_table_cells,
    build_retry_instruction,
)
from sustainability_desk.llm.client import build_agent
from sustainability_desk.llm.model_registry import DEFAULT_MODEL_ID
from sustainability_desk.llm.prompt_profiles import PromptLabels, prompt_labels, answer_wording
from sustainability_desk.observability.registry import Stage, register_stage
from sustainability_desk.observability.stages import open_stage, require_current_stage
from sustainability_desk.llm.prompts import (
    CATALOG_ROW_SUPPORT_EVIDENCE_KEY,
    CATALOG_ROW_SUPPORT_STATUS_KEY,
    CATALOG_ROW_WRITING_RULE_KEY,
    ModelContext,
    build_model_context,
    model_context_observation_metadata,
    render_adaptive_propose_prompt,
    render_catalog_table_fill_prompt,
    render_complete_prompt,
    render_propose_prompt,
)
from sustainability_desk.llm.table_schema import (
    RowSeed,
    RowSeedList,
    expanded_row_model,
    row_model_from_columns,
)
from sustainability_desk.llm.table_validate import validate_seeds
from sustainability_desk.material.intake.file_agent_contract import FileMaterial
from sustainability_desk.material.mapping.decisions import BlockMaterialDecision

logger = logging.getLogger(__name__)

# 逐行 span 阶段声明（与使用处同址；实例由表格块定行派生，spec 决策点 B）。
# scopes=None：与 generation.block 同理，报告范围语义由单元根 span 携带。
GENERATION_ROW_STAGE = register_stage(
    Stage(id="generation.row", kind="llm")
)

DEFAULT_MAX_ROWS = 8  # 表格无显式 rowCount 时的默认行数上限（与并发无关）


def _template_report(instance_report: Report) -> Report:
    """服务端模板态 Report：表结构、生成元数据与显隐条件均以服务端契约为准。

    The template is the instance report's own knowledge package; there is no default package.
    """
    from sustainability_desk.llm.generate import _template

    return _template(knowledge_package_of(instance_report))


def _resolve_block(block_id: str, instance_report: Report) -> tuple[Block, Report]:
    """取服务端模板表块；实例 Report 只提供事实值与当前章节装配状态。"""
    template = _template_report(instance_report)
    return template.find_block(block_id), template


def _build_table_model_context(
    block: Block,
    template: Report,
    instance_report: Report,
    *,
    row_seed: RowSeed | None = None,
    mapped_file_materials: tuple[FileMaterial, ...] = (),
    block_material_decision: BlockMaterialDecision | None = None,
) -> ModelContext:
    """生产表格使用编译关系；合成单测块只回退到其局部 typed Report。"""

    definition = load_compiled_report_definition(knowledge_package_of(instance_report))
    return build_model_context(
        block,
        template,
        instance_report,
        definition=(definition if f"block/{block.id}" in definition.nodes_by_id else None),
        row_seed=row_seed,
        mapped_file_materials=mapped_file_materials,
        block_material_decision=block_material_decision,
    )


def prepare_table_model_context(
    block_id: str,
    instance_report: Report,
    *,
    mapped_file_materials: tuple[FileMaterial, ...] = (),
    block_material_decision: BlockMaterialDecision | None = None,
) -> ModelContext:
    """使用正式模板与当前报告建立表格生成的权威 ModelContext。"""
    block, template = _resolve_block(block_id, instance_report)
    _ensure_generative_table(block)
    _ensure_instance_visible(block_id, block, instance_report)
    return _build_table_model_context(
        block,
        template,
        instance_report,
        mapped_file_materials=mapped_file_materials,
        block_material_decision=block_material_decision,
    )


def _ensure_generative_table(block: Block) -> None:
    if block.type != "table" or block.table is None:
        raise ValueError(f"块 {block.id} 不是表块")
    if block.blockType not in ("generative", "constrained") or block.generation is None:
        raise ValueError(f"块 {block.id} 不是可生成表（blockType={block.blockType}）")


def _ensure_instance_visible(block_id: str, block: Block, instance_report: Report) -> None:
    try:
        instance_report.find_block(block_id)
    except KeyError as exc:
        raise ValueError("该表格当前不在报告中；请先完成对应章节装配后再生成。") from exc
    if not visible_block_in_report(instance_report, block_id) or not visible(block, instance_report):
        raise ValueError("该表格当前不可见；请先完成对应前置填写后再生成。")


def _row_count(block: Block) -> tuple[int, int]:
    """定行上下限取自 block.generation.rowCount；缺省 (3, DEFAULT_MAX_ROWS)。"""
    rc = block.generation.rowCount if block.generation and block.generation.rowCount else None
    return rc if rc else (3, DEFAULT_MAX_ROWS)


def _fixed_row_seeds(block: Block) -> list[RowSeed]:
    """从块契约读取固定行种子；存在时不再调用 AI 定行。"""
    seeds = block.generation.fixedRowSeeds if block.generation and block.generation.fixedRowSeeds else None
    if not seeds:
        return []
    return [
        RowSeed(theme=seed.theme, category=seed.category, driver_hint=seed.driver_hint)
        for seed in seeds
    ]


def _assessment_iro_row_seeds(block: Block, instance_report: Report) -> list[RowSeed] | None:
    """由评分结果确定 IRO 表的议题行；模型不可自行增删或改名。"""
    if block.table is None or block.table.rowSource != "assessment_iro":
        return None
    if instance_report.assessment is None:
        return []
    package = knowledge_package_of(instance_report)
    registry = load_topic_contract(package).assessmentTopicsById
    materiality_labels = assessment_vocabulary(package).materiality
    rows: list[RowSeed] = []
    for result in instance_report.assessment.topics:
        if result.determination != "scored" or result.materiality not in {"dual", "financial"}:
            continue
        topic = registry.get(result.assessmentTopicId)
        if topic is None:
            raise ValueError(f"IRO 表遇到未知评分议题：{result.assessmentTopicId}")
        rows.append(
            RowSeed(
                theme=topic.name,
                category=getattr(materiality_labels, result.materiality),
            )
        )
    return rows


def _apply_fixed_seed_cells(block: Block, row_seed: RowSeed, cells: dict[str, object]) -> dict[str, object]:
    """固定行表由系统写入行主题和归类，LLM 只负责补全说明类单元格。"""
    has_system_row_seed = bool(_fixed_row_seeds(block)) or (
        block.table is not None and block.table.rowSource == "assessment_iro"
    )
    if not has_system_row_seed:
        return cells
    normalized = dict(cells)
    col_keys = {col.key for col in block.table.colDefs} if block.table else set()
    for key in ("risk_name", "risk_type", "iro_topic"):
        if key in col_keys:
            normalized[key] = row_seed.theme
            break
    if row_seed.category and "risk_category" in col_keys:
        normalized["risk_category"] = row_seed.category
    return normalized


def _normalize_generated_table_cells(block: Block, cells: dict[str, object]) -> dict[str, object]:
    """对高确定性表格列做最小归一化；写回后用户仍可在前端删改。

    A ``presetFullCoverage`` multi-select column is filled with every option by the system:
    the contract, not the model, decides that the row spans the whole option set.
    """
    if not block.table:
        return cells
    normalized = dict(cells)
    for col in block.table.colDefs:
        if col.presetFullCoverage and col.cellType == "multi_select" and col.options:
            normalized[col.key] = list(col.options)
    return normalized


async def complete_row(block_id: str, row_seed: RowSeed, instance_report: Report,
                       *, model_id: str = DEFAULT_MODEL_ID, unit_ordinal: int = 0,
                       observation: ObservationRun,
                       mapped_file_materials: tuple[FileMaterial, ...] = (),
                       block_material_decision: BlockMaterialDecision | None = None) -> dict:
    """单行补全（原子能力）：据 row_seed + 列规格结构化输出整行；结构化或 L1 失败均最多尝试 3 次。

    契约声明 rowExpansion 时，一次调用产出该业务行的全部披露子行（嵌套结构化输出），
    使模型在同一次判断中区分各子行语义；rowSpan 与占位格不进入模型视野，由 table_ops 展开。
    """
    block, template = _resolve_block(block_id, instance_report)
    _ensure_generative_table(block)
    _ensure_instance_visible(block_id, block, instance_report)
    expansion = block.generation.rowExpansion if block.generation else None
    row_model = (
        expanded_row_model(block.table.colDefs, expansion)
        if expansion is not None
        else row_model_from_columns(block.table.colDefs)
    )
    ctx = _build_table_model_context(
        block,
        template,
        instance_report,
        row_seed=row_seed,
        mapped_file_materials=mapped_file_materials,
        block_material_decision=block_material_decision,
    )
    system, user = render_complete_prompt(ctx, block.table.colDefs, expansion=expansion)
    # 结构化解析失败由 Pydantic AI 内置输出校验重试处理（build_agent retries=2）；本循环只做 L1 业务断言的有界重试。
    retry_instruction = ""
    last_issues = []
    # Issues from earlier attempts stay in the retry instruction: a fix for attempt 2 must not undo attempt 1's.
    accumulated_issues: list = []
    # 逐行 span：行集合由表格块的定行派生；一行的多次 L1 重试同属一个 span，
    # 尝试次数以属性记录。行级失败（GuardrailViolation）由 span 状态如实携带。
    parent = require_current_stage(f"表块 {block_id} 第 {unit_ordinal} 行的补全")
    with open_stage(
        GENERATION_ROW_STAGE,
        trace_id=parent.trace_id,
        report_id=parent.report_id,
        scope=parent.scope,
        **{
            "sustainability_desk.block_id": block_id,
            "sustainability_desk.row_ordinal": unit_ordinal,
        },
    ) as row_stage:
        for attempt in range(MAX_GENERATION_ATTEMPTS):
            attempt_system = system + (("\n\n" + retry_instruction) if retry_instruction else "")
            agent = build_agent(model_id, output_type=row_model, instructions=attempt_system)
            invocation = observation.invocation(
                block_id=block_id,
                model_id=model_id,
                task_context=ctx.model_dump(mode="json"),
                **model_context_observation_metadata(block, ctx),
            )
            result = await run_agent(
                agent,
                user,
                invocation,
            )
            cells = {
                k: ({kk: (list(vv) if isinstance(vv, list) else vv) for kk, vv in v.items()}
                    if isinstance(v, dict)
                    else list(v) if isinstance(v, list) else v)
                for k, v in result.output.model_dump().items()
            }
            cells = _apply_fixed_seed_cells(block, row_seed, cells)
            cells = _normalize_generated_table_cells(block, cells)
            last_issues = check_table_cells(block, instance_report, ctx, cells)
            accumulated_issues.extend(last_issues)
            next_retry_instruction = (
                build_retry_instruction(accumulated_issues)
                if last_issues and attempt < MAX_GENERATION_ATTEMPTS - 1
                else ""
            )
            record_guardrail_evaluation(
                invocation,
                issues=[
                    GuardrailIssueTrace(
                        key=issue.key,
                        message=issue.message,
                        evidence=issue.evidence,
                        location=issue.location,
                    )
                    for issue in last_issues
                ],
                retry_instruction=next_retry_instruction,
            )
            if not last_issues:
                row_stage.set_attribute("sustainability_desk.attempts", attempt + 1)
                return {"cells": cells, "state": "ready"}
            if next_retry_instruction:
                logger.warning(
                    "表块 %s 单行 L1 断言未通过：第 %d 次尝试发现 %d 项问题，准备重试",
                    block_id, attempt + 1, len(last_issues),
                )
                retry_instruction = next_retry_instruction
        row_stage.set_attribute("sustainability_desk.attempts", MAX_GENERATION_ATTEMPTS)
        raise GuardrailViolation(last_issues)


async def fill_table_rows(
    block_id: str,
    seeds: list[RowSeed],
    instance_report: Report,
    *,
    max_concurrency: int = MAX_INFLIGHT_LLM_CALLS,
    model_id: str = DEFAULT_MODEL_ID,
    observation: ObservationRun,
    mapped_file_materials: tuple[FileMaterial, ...] = (),
    block_material_decision: BlockMaterialDecision | None = None,
) -> list[dict]:
    """行级并发补全：并发调 complete_row，部分失败隔离（标 failed、保留 seed）、顺序对应。

    返回 GsTableRow 节点形态的**数据行**（不含表头行）；前端写回须拼接到既有 headerRows 之后、
    不可整体替换 table.children，否则会冲掉 YAML 预置的跨列大标题/列名行。行级并发原样保留。
    """
    seeds = list(seeds)
    block, _ = _resolve_block(block_id, instance_report)
    col_defs = block.table.colDefs
    indexed_seeds = list(enumerate(seeds))
    results = await bounded_gather(
        indexed_seeds,
        lambda pair: complete_row(
            block_id,
            pair[1],
            instance_report,
            model_id=model_id,
            unit_ordinal=pair[0],
            observation=observation,
            mapped_file_materials=mapped_file_materials,
            block_material_decision=block_material_decision,
        ),
        limit=max_concurrency,
    )
    expansion = block.generation.rowExpansion if block.generation else None
    rows: list[dict] = []
    for i, (seed, res) in enumerate(zip(seeds, results)):
        origin = RowOrigin(theme=seed.theme, category=seed.category, driver_hint=seed.driver_hint)
        failed = isinstance(res, Exception)
        if failed:
            logger.warning(
                "表块 %s 第 %d 行（%s）补全失败（%s），标记 failed",
                block_id, i, seed.theme, type(res).__name__,
            )
        cells = {} if failed else res["cells"]
        state = "failed" if failed else res["state"]
        if expansion is not None:
            # 一个业务行展开为多个披露子行；失败时同样铺满子行，保持行结构与人审定位稳定。
            built = build_expanded_rows(col_defs, expansion, [cells], state=state, origin=origin)
        else:
            built = [data_row(col_defs, cells, state=state, origin=origin)]
        rows.extend(row.model_dump(by_alias=True) for row in built)
    return rows


# —— 目录表通用引擎：锚点/AI 列拆分 + 整表一次填充（preset_catalog 与 adaptive_catalog 共用）——
# 锚点列 = 首个 ai_text 之前的前导列（类型/名称/类别等）；AI 列 = 其余（ai_text + 受控多选）。
# preset_catalog 锚点来自固定 fixedRowSeeds；adaptive_catalog 锚点由前置一步据业务 + referenceCatalog 生成。


def _anchor_ai_split(col_defs: list[GsColDef]) -> tuple[list[GsColDef], list[GsColDef]]:
    idx = next((i for i, c in enumerate(col_defs) if c.cellType == "ai_text"), len(col_defs))
    return col_defs[:idx], col_defs[idx:]


def _table_kind_label(block: Block, instance_report: Report) -> str:
    """Model-facing label of the IRO kinds a catalog table enumerates, from ``table.iroKind``."""
    kind = block.table.iroKind if block.table else None
    if kind is None:
        raise ValueError(f"目录表 {block.id} 未声明 table.iroKind")
    labels = assessment_vocabulary(knowledge_package_of(instance_report)).iroKind
    if kind == "risk_and_opportunity":
        return labels.risk_opportunity
    return getattr(labels, kind)


def _grouped(items: list, key) -> list[tuple[str, list]]:
    """按 key(item) 分组并保序（分组即并发单元）。"""
    groups: list[tuple[str, list]] = []
    index: dict[str, int] = {}
    for it in items:
        k = key(it) or ""
        if k not in index:
            index[k] = len(groups)
            groups.append((k, []))
        groups[index[k]][1].append(it)
    return groups


def _catalog_support_materials(block: Block, instance_report: Report) -> dict[str, str]:
    """取本表绑定内容清单的模型可见文本；与 prompt material 解析口径保持一致。"""
    inputs = block.generation.inputs if block.generation else None
    selector = inputs.evidence if inputs else None
    keys = selector.intakeItems if isinstance(selector, ExplicitGenerationEvidenceSelector) else []
    by_key = {item.key: item for item in instance_report.intakeItems}
    package = knowledge_package_of(instance_report)
    wording = answer_wording(prompt_labels(package))
    materials: dict[str, str] = {}
    for key in keys:
        item = by_key.get(key)
        if item is None:
            continue
        text = intake_ready_text(item, language=package.language, wording=wording)
        if text:
            materials[key] = text
    return materials


def _catalog_row_support(
    seed: FixedRowSeed, materials: dict[str, str], labels: PromptLabels
) -> dict[str, str]:
    """由结构化问卷投影判定固定目录行是否有直接用户支持。"""
    theme = seed.theme.strip()
    supporting_labels = [key for key, text in materials.items() if theme and theme in text]
    words = labels.table_support
    if supporting_labels:
        return {
            CATALOG_ROW_SUPPORT_STATUS_KEY: "user_supported_anchor",
            CATALOG_ROW_SUPPORT_EVIDENCE_KEY: words.user_supported_evidence.format(theme=theme),
            CATALOG_ROW_WRITING_RULE_KEY: words.user_supported_rule,
        }
    return {
        CATALOG_ROW_SUPPORT_STATUS_KEY: "framework_anchor",
        CATALOG_ROW_SUPPORT_EVIDENCE_KEY: words.framework_evidence.format(theme=theme),
        CATALOG_ROW_WRITING_RULE_KEY: words.framework_rule,
    }


async def _fill_catalog_table(
    block_id: str,
    catalog_rows: list[dict[str, str | None]],
    instance_report: Report,
    *,
    model_id: str,
    observation: ObservationRun,
    mapped_file_materials: tuple[FileMaterial, ...] = (),
    block_material_decision: BlockMaterialDecision | None = None,
) -> list[dict]:
    """目录表整表填充：一次调用生成所有行，按锚点列回填，失败时整表重试。"""
    block, template = _resolve_block(block_id, instance_report)
    anchors, _ai_cols = _anchor_ai_split(block.table.colDefs)
    group_key, id_col = anchors[0].key, anchors[-1]
    row_model = row_model_from_columns(block.table.colDefs)
    rows_model = create_model("CatalogTableRows", rows=(list[row_model], ...))
    ctx = _build_table_model_context(
        block,
        template,
        instance_report,
        mapped_file_materials=mapped_file_materials,
        block_material_decision=block_material_decision,
    )
    system, user = render_catalog_table_fill_prompt(
        ctx,
        catalog_rows,
        block.table.colDefs,
        kind_label=_table_kind_label(block, instance_report),
    )
    expected_ids = [str(row.get(id_col.key, "")).strip() for row in catalog_rows]
    retry_instruction = ""
    last_issues: list[GuardrailIssue] = []
    for attempt in range(MAX_GENERATION_ATTEMPTS):
        attempt_system = system + (("\n\n" + retry_instruction) if retry_instruction else "")
        agent = build_agent(model_id, output_type=rows_model, instructions=attempt_system)
        invocation = observation.invocation(
            block_id=block_id,
            model_id=model_id,
            task_context=ctx.model_dump(mode="json"),
            **model_context_observation_metadata(block, ctx),
        )
        result = await run_agent(
            agent,
            user,
            invocation,
        )
        by_id: dict[str, dict] = {}
        for row in result.output.rows:
            dumped = {k: (list(v) if isinstance(v, list) else v) for k, v in row.model_dump().items()}
            by_id[str(dumped.get(id_col.key, "")).strip()] = dumped
        fills: list[dict] = []
        issues: list[GuardrailIssue] = []
        for anchor in catalog_rows:
            row_id = str(anchor.get(id_col.key, "")).strip()
            generated = by_id.get(row_id)
            if generated is None:
                issues.append(GuardrailIssue("catalog_row_missing", f"缺少条目「{row_id}」的生成结果。", row_id, row_id))
                generated = {}
            merged = dict(generated)
            for col in anchors:
                if anchor.get(col.key):
                    merged[col.key] = anchor[col.key]
            merged = _normalize_generated_table_cells(block, merged)
            issues.extend(check_table_cells(block, instance_report, ctx, merged))
            fills.append(merged)
        extra_ids = sorted(set(by_id) - set(expected_ids))
        for row_id in extra_ids:
            issues.append(GuardrailIssue("catalog_row_extra", f"生成了未在锚点清单中的条目「{row_id}」。", row_id, row_id))
        next_retry_instruction = (
            build_retry_instruction(issues)
            if issues and attempt < MAX_GENERATION_ATTEMPTS - 1
            else ""
        )
        record_guardrail_evaluation(
            invocation,
            issues=[
                GuardrailIssueTrace(
                    key=issue.key,
                    message=issue.message,
                    evidence=issue.evidence,
                    location=issue.location,
                )
                for issue in issues
            ],
            retry_instruction=next_retry_instruction,
        )
        if not issues:
            groups = [
                (label, list(items))
                for label, items in _grouped(fills, key=lambda row: str(row.get(group_key, "")))
            ]
            rows = build_preset_catalog_rows(block.table.colDefs, groups, state="ready")
            return [r.model_dump(by_alias=True) for r in rows]
        last_issues = issues
        if next_retry_instruction:
            logger.warning("表块 %s 整表 L1 断言未通过：第 %d 次 %d 项，准备重试", block_id, attempt + 1, len(issues))
            retry_instruction = next_retry_instruction
    raise GuardrailViolation(last_issues)


async def _generate_preset_catalog(
    block_id: str,
    instance_report: Report,
    *,
    model_id: str,
    observation: ObservationRun,
    mapped_file_materials: tuple[FileMaterial, ...] = (),
    block_material_decision: BlockMaterialDecision | None = None,
) -> list[dict]:
    """preset_catalog：固定 fixedRowSeeds 锚点，整表一次填充。"""
    block, _ = _resolve_block(block_id, instance_report)
    _ensure_generative_table(block)
    _ensure_instance_visible(block_id, block, instance_report)
    seeds = resolve_preset_row_seeds(block, instance_report)
    if not seeds:
        return []
    anchors, _ = _anchor_ai_split(block.table.colDefs)
    group_key, id_key = anchors[0].key, anchors[-1].key
    support_materials = _catalog_support_materials(block, instance_report)
    labels = prompt_labels(knowledge_package_of(instance_report))
    catalog_rows = [
        {
            group_key: seed.category or "",
            id_key: seed.theme,
            "referenceImpact": seed.referenceImpact,
            **_catalog_row_support(seed, support_materials, labels),
        }
        for seed in seeds
    ]
    return await _fill_catalog_table(
        block_id,
        catalog_rows,
        instance_report,
        model_id=model_id,
        observation=observation,
        mapped_file_materials=mapped_file_materials,
        block_material_decision=block_material_decision,
    )


async def _propose_adaptive(
    block_id: str,
    instance_report: Report,
    *,
    model_id: str,
    observation: ObservationRun,
    mapped_file_materials: tuple[FileMaterial, ...] = (),
    block_material_decision: BlockMaterialDecision | None = None,
) -> list[dict]:
    """adaptive_catalog 前置：据业务 + referenceCatalog（典型参考、不强制）生成本企业适用锚点行，去重裁剪。"""
    block, template = _resolve_block(block_id, instance_report)
    anchors, _ = _anchor_ai_split(block.table.colDefs)
    cmin, cmax = _row_count(block)
    ctx = _build_table_model_context(
        block,
        template,
        instance_report,
        mapped_file_materials=mapped_file_materials,
        block_material_decision=block_material_decision,
    )
    row_model = row_model_from_columns(anchors)
    rows_model = create_model("AdaptiveAnchors", rows=(list[row_model], ...))
    references = block.generation.referenceCatalog or []
    system, user = render_adaptive_propose_prompt(
        ctx,
        anchors,
        references,
        count_min=cmin,
        count_max=cmax,
        kind_label=_table_kind_label(block, instance_report),
    )
    agent = build_agent(model_id, output_type=rows_model, instructions=system)
    out = (
        await run_agent(
            agent,
            user,
            observation.invocation(
                block_id=block.id,
                model_id=model_id,
                task_context=ctx.model_dump(mode="json"),
                **model_context_observation_metadata(block, ctx),
            ),
        )
    ).output.rows
    id_key = anchors[-1].key
    anchor_dicts: list[dict] = []
    seen: set[str] = set()
    for r in out:
        d = {k: (list(v) if isinstance(v, list) else v) for k, v in r.model_dump().items()}
        idv = str(d.get(id_key, "")).strip()
        if idv and idv not in seen:
            seen.add(idv)
            anchor_dicts.append(d)
    return anchor_dicts[:cmax]


def _reference_catalog_anchor_rows(
    block: Block, anchors: list[GsColDef], labels: PromptLabels
) -> list[dict[str, str]]:
    """将 referenceCatalog 投影为锚点行；稳定名称来自 schema，不由 LLM 改写。"""
    references = block.generation.referenceCatalog if block.generation else None
    if not references:
        return []
    group_key, id_key = anchors[0].key, anchors[-1].key
    rows: list[dict[str, str]] = []
    for item in references:
        row = {
            group_key: item.category or "",
            id_key: item.name,
            "referenceImpact": item.reference or "",
            CATALOG_ROW_SUPPORT_STATUS_KEY: "framework_anchor",
            CATALOG_ROW_SUPPORT_EVIDENCE_KEY: labels.table_support.reference_evidence.format(
                name=item.name
            ),
            CATALOG_ROW_WRITING_RULE_KEY: labels.table_support.reference_rule,
        }
        rows.append(row)
    return rows


def _project_adaptive_catalog_rows(
    block: Block,
    anchors: list[GsColDef],
    proposed_rows: list[dict],
    support_materials: dict[str, str],
    *,
    count_min: int,
    count_max: int,
    labels: PromptLabels,
) -> list[dict[str, str]]:
    """按 referenceCatalog 与本表绑定用户输入约束 adaptive 锚点，避免目录名称漂移。"""
    reference_rows = _reference_catalog_anchor_rows(block, anchors, labels)
    id_key = anchors[-1].key
    reference_by_id = {row[id_key]: row for row in reference_rows}
    support_text = "\n".join(support_materials.values())

    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for proposed in proposed_rows:
        row_id = str(proposed.get(id_key, "")).strip()
        if not row_id or row_id in seen:
            continue
        if row_id in reference_by_id:
            selected.append(reference_by_id[row_id])
            seen.add(row_id)
            continue
        if row_id in support_text:
            row = {col.key: str(proposed.get(col.key, "")).strip() for col in anchors}
            row.update(
                {
                    CATALOG_ROW_SUPPORT_STATUS_KEY: "user_supported_anchor",
                    CATALOG_ROW_SUPPORT_EVIDENCE_KEY: (
                        labels.table_support.custom_anchor_evidence.format(row_id=row_id)
                    ),
                    CATALOG_ROW_WRITING_RULE_KEY: labels.table_support.custom_anchor_rule,
                }
            )
            selected.append(row)
            seen.add(row_id)

    for reference in reference_rows:
        if len(selected) >= count_min:
            break
        row_id = reference[id_key]
        if row_id not in seen:
            selected.append(reference)
            seen.add(row_id)

    return selected[:count_max]


async def _generate_adaptive_catalog(
    block_id: str,
    instance_report: Report,
    *,
    model_id: str,
    observation: ObservationRun,
    mapped_file_materials: tuple[FileMaterial, ...] = (),
    block_material_decision: BlockMaterialDecision | None = None,
) -> list[dict]:
    """adaptive_catalog：前置生成适用锚点行 → 整表一次填充。"""
    block, _ = _resolve_block(block_id, instance_report)
    _ensure_generative_table(block)
    _ensure_instance_visible(block_id, block, instance_report)
    anchors, _ = _anchor_ai_split(block.table.colDefs)
    cmin, cmax = _row_count(block)
    anchor_dicts = await _propose_adaptive(
        block_id,
        instance_report,
        model_id=model_id,
        observation=observation,
        mapped_file_materials=mapped_file_materials,
        block_material_decision=block_material_decision,
    )
    support_materials = _catalog_support_materials(block, instance_report)
    catalog_rows = _project_adaptive_catalog_rows(
        block,
        anchors,
        anchor_dicts,
        support_materials,
        count_min=cmin,
        count_max=cmax,
        labels=prompt_labels(knowledge_package_of(instance_report)),
    )
    if not catalog_rows:
        raise ValueError("未能据企业业务识别出适用的风险/机遇条目；请补充战略填写内容后重试。")
    return await _fill_catalog_table(
        block_id,
        catalog_rows,
        instance_report,
        model_id=model_id,
        observation=observation,
        mapped_file_materials=mapped_file_materials,
        block_material_decision=block_material_decision,
    )


async def generate_table(
    block_id: str,
    instance_report: Report,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    observation: ObservationRun,
    mapped_file_materials: tuple[FileMaterial, ...] = (),
    block_material_decision: BlockMaterialDecision | None = None,
) -> list[dict]:
    """整表生成；返回**数据行** payload（不改 Report，由前端拼接到 headerRows 之后写回）。

    preset_catalog：固定锚点整表填充；adaptive_catalog：前置生成适用锚点再整表填充；否则走定行 + 行级并发补全。
    """
    block, _ = _resolve_block(block_id, instance_report)
    if block.generation and block.generation.rowMode == "preset_catalog":
        return await _generate_preset_catalog(
            block_id,
            instance_report,
            model_id=model_id,
            observation=observation,
            mapped_file_materials=mapped_file_materials,
            block_material_decision=block_material_decision,
        )
    if block.generation and block.generation.rowMode == "adaptive_catalog":
        return await _generate_adaptive_catalog(
            block_id,
            instance_report,
            model_id=model_id,
            observation=observation,
            mapped_file_materials=mapped_file_materials,
            block_material_decision=block_material_decision,
        )
    assessment_seeds = _assessment_iro_row_seeds(block, instance_report)
    seeds = _fixed_row_seeds(block) or assessment_seeds
    if seeds is None:
        seeds = await propose_rows(
            block_id,
            instance_report,
            model_id=model_id,
            observation=observation,
            mapped_file_materials=mapped_file_materials,
            block_material_decision=block_material_decision,
        )
    rows = await fill_table_rows(
        block_id,
        seeds,
        instance_report,
        model_id=model_id,
        observation=observation,
        mapped_file_materials=mapped_file_materials,
        block_material_decision=block_material_decision,
    )
    if any(row.get("state") == "failed" for row in rows):
        raise ValueError("表格生成未通过确定性检查；请调整输入后重新生成。")
    return rows


async def propose_rows(
    block_id: str,
    instance_report: Report,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    observation: ObservationRun,
    mapped_file_materials: tuple[FileMaterial, ...] = (),
    block_material_decision: BlockMaterialDecision | None = None,
) -> list[RowSeed]:
    """AI 定行：据表主题 + 路径口径结构化输出条目清单，经定行校验（去重/行数）。"""
    block, template = _resolve_block(block_id, instance_report)
    _ensure_generative_table(block)
    _ensure_instance_visible(block_id, block, instance_report)
    cmin, cmax = _row_count(block)
    ctx = _build_table_model_context(
        block,
        template,
        instance_report,
        mapped_file_materials=mapped_file_materials,
        block_material_decision=block_material_decision,
    )
    system, user = render_propose_prompt(ctx, block.table.colDefs, count_min=cmin, count_max=cmax)
    agent = build_agent(model_id, output_type=RowSeedList, instructions=system)
    seeds = (
        await run_agent(
            agent,
            user,
            observation.invocation(
                block_id=block_id,
                model_id=model_id,
                task_context=ctx.model_dump(mode="json"),
                **model_context_observation_metadata(block, ctx),
            ),
        )
    ).output.rows
    kept, issues = validate_seeds(seeds, count_min=cmin, count_max=cmax)
    if len(kept) < cmin:
        reason = "; ".join(issues) or "表格定行不足下限"
        raise ValueError(reason)
    return kept
