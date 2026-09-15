# ABOUTME: 生成编排总控——遍历可生成块，按输出类型分派段落/表格生成，并发执行、失败隔离、汇总。
# ABOUTME: paragraph 缺少企业事实时仍由 ModelContext 进入 context_only；空表格按显式策略受控省略。
# ABOUTME(en): Generation orchestration: walks generable blocks, dispatching paragraph or table generation by type,
# ABOUTME(en): running concurrently with failure isolation. Paragraphs without company facts still enter context_only.
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from sustainability_desk.contract.evidence_resolution import generation_has_gate_opening_evidence
from sustainability_desk.contract.models import (
    Block,
    GsTableRow,
    Inline,
    MaterialGatedGenerationEvidenceSelector,
    Report,
    Section,
)
from sustainability_desk.contract.prior_disclosure import PILLAR_ORDER, pillar_rank_in_report
from sustainability_desk.contract.visibility import visible
from sustainability_desk.llm.concurrency import MAX_INFLIGHT_LLM_CALLS, bounded_gather
from sustainability_desk.llm.generate import generate_variants
from sustainability_desk.llm.ai_observability import ObservationRun
from sustainability_desk.llm.generation_guardrails import GuardrailViolation
from sustainability_desk.llm.table_gen import generate_table
from sustainability_desk.material.intake.file_agent_contract import FileMaterial
from sustainability_desk.material.mapping.decisions import BlockMaterialDecision
from sustainability_desk.observability.registry import Stage, register_stage
from sustainability_desk.observability.stages import open_stage, require_current_stage

logger = logging.getLogger(__name__)

# ---- 链路阶段声明（与使用处同址，导入即登记；spec 决策点 B）----
# scopes=None：块生成既服务生产两种报告范围，也被 eval 在其自身根 span 下直调；
# 报告范围语义由单元根 span 携带，这里不重复约束。
BLOCKS_CONCLUSION_STAGE = register_stage(
    Stage(id="generation.blocks.conclusion", kind="orchestration")
)
BLOCKS_REST_STAGE = register_stage(
    Stage(id="generation.blocks.rest", kind="orchestration")
)
# 议题内按支柱分阶段：先落定的支柱正文成为后续支柱的已披露事实（prior_disclosure）。
# 阶段数固定为四，不随议题数增长；同支柱内仍全并发。
BLOCKS_PILLAR_STAGE = register_stage(
    Stage(id="generation.blocks.pillar", kind="orchestration")
)
# 逐块 span：实例数量与身份由报告契约的 block 集合派生，无需登记实例。
GENERATION_BLOCK_STAGE = register_stage(
    Stage(id="generation.block", kind="llm")
)


class BlockMappedEvidence(BaseModel):
    """一个 Block 经 Harness 验证后可见的 FileMaterial、决定与文件路由处置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    materials: tuple[FileMaterial, ...] = ()
    decision: BlockMaterialDecision | None = None
    file_routing_disposition: Literal[
        "mapping_decision",
        "no_applicable_file_dossier",
    ] = "no_applicable_file_dossier"


def _is_generable(block: Block) -> bool:
    """可生成块：blockType 为 constrained/generative 且带生成规格。生成次数上限由前端「整节重写」统一约束。"""
    return block.blockType in ("constrained", "generative") and block.generation is not None


def _result_kind(block: Block) -> Literal["table", "paragraph"]:
    """结果项的输出类型；持久化与失败投影据此分支，不再从 block.type 反推。"""
    return "table" if block.type == "table" else "paragraph"


def _material_gate_verdict(
    block: Block,
    instance_report: Report,
    mapped: BlockMappedEvidence,
) -> dict[str, str] | None:
    """证据门控块（material_gated selector）在文件资料与 intake 答案均缺席时受控省略。

    「或」语义：Mapping 判定 supported/partially_supported，或声明的 intakeItems 有
    实质答案，任一满足即照常生成（返回 None）；两者皆无时返回两条门控臂的判定依据，
    由调用方置 omitted 并写入块级 span——trace 必须能直答「这个块为什么消失」。
    判定发生在 Mapping 完成之后、模型调用之前，属确定性 Harness 裁剪，不交给模型。
    """

    selector = block.generation.inputs.evidence if block.generation else None
    if not isinstance(selector, MaterialGatedGenerationEvidenceSelector):
        return None
    if mapped.decision is not None and mapped.decision.disposition in {
        "supported",
        "partially_supported",
    }:
        return None
    intake_declared = bool(selector.intakeItems)
    if intake_declared and generation_has_gate_opening_evidence(
        instance_report,
        intake_item_ids=tuple(selector.intakeItems),
    ):
        return None
    return {
        "sustainability_desk.material_gate.file_arm": (
            mapped.decision.disposition
            if mapped.decision is not None
            else "no_decision"
        ),
        "sustainability_desk.material_gate.intake_arm": (
            "no_substantive_answer" if intake_declared else "not_declared"
        ),
    }


def _title_section_key(report: Report, block_id: str) -> str | None:
    def walk(sections: list[Section]) -> str | None:
        for section in sections:
            declaration = section.titleGeneration
            if declaration is not None and declaration.sourceBlockId == block_id:
                return section.key
            found = walk(section.children or [])
            if found is not None:
                return found
        return None

    return walk(report.sections)


async def _generate_one(
    block: Block,
    instance_report: Report,
    n: int,
    model_id: str | None,
    observation: ObservationRun,
    empty_table_policy: Literal["ready", "omit"],
    mapped_evidence: BlockMappedEvidence | None,
) -> dict:
    """生成单块当前版本；合同错误归 blocked、其他异常归 failed，均不向外抛（隔离）。"""
    mkw = {"model_id": model_id} if model_id else {}
    mapped = mapped_evidence or BlockMappedEvidence()
    base = {
        "blockId": block.id,
        "kind": _result_kind(block),
        "fileRoutingDisposition": mapped.file_routing_disposition,
    }
    gate_facts = _material_gate_verdict(block, instance_report, mapped)
    if gate_facts is not None:
        block_stage = require_current_stage(f"块 {block.id} 的证据门控省略")
        for attribute_key, attribute_value in gate_facts.items():
            block_stage.set_attribute(attribute_key, attribute_value)
        return {
            **base,
            "status": "omitted",
            "reason": "本块按报告合同仅在有对应资料支持时出具；本轮未获得适用资料，已省略。",
            **({"rows": []} if block.type == "table" else {}),
        }
    try:
        if block.type == "table":
            rows = await generate_table(
                block.id,
                instance_report,
                observation=observation,
                mapped_file_materials=mapped.materials,
                block_material_decision=mapped.decision,
                **mkw,
            )
            if not rows and empty_table_policy == "omit":
                return {
                    **base,
                    "status": "omitted",
                    "reason": "当前表格缺少可披露的用户资料，已按报告合同省略。",
                    "rows": [],
                }
            return {
                **base,
                "status": "ready",
                "rows": rows,
            }
        variants = await generate_variants(
            block.id,
            instance_report,
            n=n,
            observation=observation,
            mapped_file_materials=mapped.materials,
            block_material_decision=mapped.decision,
            **mkw,
        )
        return {
            **base,
            "status": "ready",
            "titleSectionKey": _title_section_key(instance_report, block.id),
            "variants": [variant.model_dump() for variant in variants],
        }
    except GuardrailViolation as exc:
        logger.warning("生成编排：块 %s 未通过 L1 守卫（%s）", block.id, exc)
        # issue key 供报告级失败投影分类使用（内部宽结果，不进公共响应合同）。
        return {
            **base,
            "status": "blocked",
            "reason": str(exc),
            "guardrailIssueKeys": sorted({issue.key for issue in exc.issues}),
        }
    except ValueError as exc:
        # 可见性或合同前置不满足：合规阻断、标注、不算 Provider 故障。
        logger.warning("生成编排：块 %s 阻断（%s）", block.id, exc)
        return {**base, "status": "blocked", "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — 单块生成异常隔离，不影响其余块
        logger.warning("生成编排：块 %s 生成失败（%s）", block.id, type(exc).__name__)
        return {**base, "status": "failed", "reason": f"生成失败：{type(exc).__name__}"}


def _section_blocks(section: Section, report: Report) -> list[Block]:
    if not visible(section, report):
        return []
    blocks = list(section.blocks)
    for child in section.children or []:
        blocks.extend(_section_blocks(child, report))
    return blocks


def blocks_for_section(instance_report: Report, section_key: str) -> list[Block]:
    """返回服务端合同中某工作台页面的全部可见可生成块；页面不存在时返回空。"""
    scoped = _blocks_for_scope(instance_report, section_key)
    return [
        block
        for block in scoped
        if _is_generable(block) and visible(block, instance_report)
    ]


def blocks_for_report(instance_report: Report) -> list[Block]:
    """返回完整报告中当前可见且具有生成合同的 Block。"""

    return [
        block
        for block in _blocks_for_scope(instance_report, None)
        if _is_generable(block) and visible(block, instance_report)
    ]


def _blocks_for_scope(instance_report: Report, section_key: str | None) -> list[Block]:
    if not section_key:
        out: list[Block] = []
        for section in instance_report.sections:
            out.extend(_section_blocks(section, instance_report))
        return out

    def walk(sections: list[Section]) -> Section | None:
        for section in sections:
            if not visible(section, instance_report):
                continue
            if section.key == section_key:
                return section
            found = walk(section.children or [])
            if found:
                return found
        return None

    section = walk(instance_report.sections)
    if section is None:
        return []
    return _section_blocks(section, instance_report)


async def generate_all(
    instance_report: Report,
    *,
    section_key: str | None = None,
    block_ids: frozenset[str] | None = None,
    n: int = 3,
    max_concurrency: int = MAX_INFLIGHT_LLM_CALLS,
    model_id: str | None = None,
    observation: ObservationRun,
    empty_table_policy: Literal["ready", "omit"] = "ready",
    on_block_started: Callable[[str], Awaitable[None]] | None = None,
    on_block_completed: Callable[[str, dict], Awaitable[None]] | None = None,
    mapped_evidence_by_block: dict[str, BlockMappedEvidence] | None = None,
) -> list[dict]:
    """生成全部当前版本：遍历报告可生成且可见块，内容就绪即并发生成，汇总 per-block 结果。

    可见块＝appears_when 满足（隐身块不生成）。块间默认无依赖，阶段内全并发（复用 table_gen 的 batch 并发）。
    唯一的次序来自契约：声明 `producesConclusion` 的块先于其余块生成，其产出并入在途 Report，
    供其余块的 ModelContext 解析为方向参照。编排只读该声明，不认具体 block id。
    结论是增强而非前置条件——产出块隐藏、失败或缺某议题时，其余块照常生成，只是少一层方向校准。
    结果由前端按 blockId 写回，不落服务端（守不碰持久化）。paragraph 的缺事实语义由 ModelContext
    统一表达；单块失败隔离（failed）。
    """
    # 隐身即不生成：appears_when 不满足的块直接排除（复用合同层 visible 求值，fail-closed）。
    blocks = (
        blocks_for_section(instance_report, section_key)
        if section_key is not None
        else blocks_for_report(instance_report)
    )
    if block_ids is not None:
        blocks = [block for block in blocks if block.id in block_ids]
    async def run_stage(stage_blocks: list[Block], report: Report) -> list[dict]:
        async def generate_and_record(block: Block) -> dict:
            if on_block_started is not None:
                await on_block_started(block.id)
            # 逐块 span：block 集合由报告契约派生，span 数量随契约自动变化；
            # 完整性由收束断言按 compiled_definition 比对（spec §3.5），此处只如实记录。
            parent = require_current_stage(f"块 {block.id} 的生成")
            with open_stage(
                GENERATION_BLOCK_STAGE,
                trace_id=parent.trace_id,
                report_id=parent.report_id,
                scope=parent.scope,
                **{"sustainability_desk.block_id": block.id},
            ) as block_stage:
                result = await _generate_one(
                    block,
                    report,
                    n,
                    model_id,
                    observation,
                    empty_table_policy,
                    (mapped_evidence_by_block or {}).get(block.id),
                )
                block_stage.set_attribute(
                    "sustainability_desk.block_status", str(result.get("status", ""))
                )
                # 该块承载的准则披露要求：交付后的覆盖判定据此归因，
                # trace 要能直答「这条准则要求由哪个块承载、那个块当次是什么状态」。
                requirement_keys = (
                    block.generation.standardDisclosureRequirementKeys
                    if block.generation
                    else None
                )
                if requirement_keys:
                    block_stage.set_attribute(
                        "sustainability_desk.standard_requirement_keys", list(requirement_keys)
                    )
            if on_block_completed is not None:
                await on_block_completed(block.id, result)
            return result

        stage_results = await bounded_gather(
            stage_blocks,
            generate_and_record,
            limit=max_concurrency,
        )
        collected: list[dict] = []
        for blk, res in zip(stage_blocks, stage_results):
            if isinstance(res, Exception):  # _generate_one 已内捕异常；此为 batch 兜底
                logger.warning("生成编排：块 %s 未预期异常（%s）", blk.id, type(res).__name__)
                collected.append({"blockId": blk.id, "kind": _result_kind(blk),
                                  "status": "failed", "reason": f"生成失败：{type(res).__name__}"})
            else:
                collected.append(res)
        return collected

    # 阶段一：契约声明 producesConclusion 的块（若本次在范围内且可见）。
    # 它们的结论是其余块的方向参照，必须先落定；编排只读契约声明，不认具体 block id。
    conclusion_blocks = [block for block in blocks if _produces_conclusion(block)]
    rest_blocks = [block for block in blocks if not _produces_conclusion(block)]
    if not conclusion_blocks:
        return await _run_pillar_stages(rest_blocks, instance_report, run_stage)

    async with _staged_span(BLOCKS_CONCLUSION_STAGE, len(conclusion_blocks)):
        out = await run_stage(conclusion_blocks, instance_report)
    # 阶段二：其余块。把阶段一的产出并入在途 Report，使其 ModelContext 能解析出结论。
    # 失败或空产出不阻断——其余块有自身资料与生成合同，缺方向参照只是少一层校准。
    staged_report = report_with_stage_results(instance_report, conclusion_blocks, out)
    async with _staged_span(BLOCKS_REST_STAGE, len(rest_blocks)):
        out.extend(await _run_pillar_stages(rest_blocks, staged_report, run_stage))
    return out


async def _run_pillar_stages(
    blocks: list[Block],
    report: Report,
    run_stage: Callable[[list[Block], Report], Awaitable[list[dict]]],
) -> list[dict]:
    """按支柱先后分阶段生成，把已落定的支柱正文并入在途 Report。

    先落定的支柱正文即后续支柱的已披露事实（prior_disclosure），据此让下游块
    不复述已经写过的内容。同支柱内的块彼此无先后，仍全并发。
    阶段划分只读报告结构中既有的支柱归属，不新增契约声明。
    """

    if not blocks:
        return []
    by_rank: dict[int, list[Block]] = {}
    for block in blocks:
        by_rank.setdefault(pillar_rank_in_report(report, block.id), []).append(block)
    if len(by_rank) == 1:
        return await run_stage(blocks, report)

    collected: list[dict] = []
    staged_report = report
    for rank in sorted(by_rank):
        stage_blocks = by_rank[rank]
        pillar_title = PILLAR_ORDER[rank] if 0 <= rank < len(PILLAR_ORDER) else "无支柱"
        async with _staged_span(
            BLOCKS_PILLAR_STAGE, len(stage_blocks), pillar_title=pillar_title
        ):
            results = await run_stage(stage_blocks, staged_report)
        collected.extend(results)
        # 本支柱产出并入在途 Report，供后续支柱解析已披露正文。
        staged_report = report_with_stage_results(
            staged_report, stage_blocks, results
        )
    return collected


@asynccontextmanager
async def _staged_span(stage: Stage, block_count: int, *, pillar_title: str | None = None):
    """为各生成阶段开一个阶段 span。

    阶段串行使在先阶段成为报告级生成的关键路径前缀；不加以区分，轨迹里只能看到
    一批 block span，无法回答"生成为什么久"。

    支柱阶段必须带 pillar_title：四个支柱阶段的 stage id 相同，不带身份属性时
    调用树里是四个同名 span，无从回答"哪个支柱慢""哪个支柱断了"。
    """
    parent = require_current_stage("分阶段块生成")
    attributes: dict[str, object] = {"sustainability_desk.block_count": block_count}
    if pillar_title is not None:
        attributes["sustainability_desk.pillar_title"] = pillar_title
    with open_stage(
        stage,
        trace_id=parent.trace_id,
        report_id=parent.report_id,
        scope=parent.scope,
        **attributes,
    ) as handle:
        yield handle


def _produces_conclusion(block: Block) -> bool:
    """本块是否按契约产出报告级结论（据此排阶段）。"""
    return bool(block.generation and block.generation.producesConclusion)


def report_with_stage_results(
    report: Report, stage_blocks: list[Block], stage_results: list[dict]
) -> Report:
    """把阶段产出并入 Report 副本（不改传入），供后续阶段的 ModelContext 解析。

    公开给 eval：judge 的 CaseInputs 必须从与生成器同一份在途 Report 投影，
    否则 prior_disclosures 恒为空，judge 看不到生成器实际看见的已披露正文。
    并入口径只此一处，不允许调用方另写一套。

    generate_all 本身不持久化；此副本只在本次编排内传递，落库仍由调用方在返回后完成。
    """
    rows_by_block = {
        res["blockId"]: res.get("rows") or []
        for res in stage_results
        if res.get("status") == "ready" and res.get("rows")
    }
    # 段落正文同样并入：下游块的 prior_disclosure 据此解析「本议题已经写了什么」。
    # 选定候选与落库口径一致（variants[0]，见 persistence/section_generations.py），
    # 避免在途 Report 与最终报告出现两套正文。
    text_by_block: dict[str, str] = {}
    for res in stage_results:
        if res.get("status") != "ready":
            continue
        variants = res.get("variants")
        if not isinstance(variants, list) or not variants:
            continue
        first = variants[0]
        content = first.get("content") if isinstance(first, dict) else None
        if isinstance(content, str) and content.strip():
            text_by_block[res["blockId"]] = content.strip()
    stage_ids = {block.id for block in stage_blocks}
    staged_rows = stage_ids & set(rows_by_block)
    staged_texts = stage_ids & set(text_by_block)
    if not staged_rows and not staged_texts:
        return report
    staged = report.model_copy(deep=True)
    for block in staged.iter_blocks():
        if block.id in staged_rows and block.table is not None:
            headers = [row for row in block.table.children if row.headerRow]
            block.table.children = headers + [
                GsTableRow.model_validate(row) for row in rows_by_block[block.id]
            ]
        elif block.id in staged_texts and block.type == "paragraph":
            block.content = [Inline(kind="text", text=text_by_block[block.id])]
            block.state = "ready"
    return staged
