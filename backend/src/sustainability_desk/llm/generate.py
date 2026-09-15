# ABOUTME: AI 生成服务——按 block_id 取模板 brief、组装任务专用提示词、调用大模型产出多版本正文。
# ABOUTME: 仅 generative/constrained 块可生成；模型默认走注册表 DEFAULT_MODEL_ID（生成用思考型模型），可经 by_block.model 覆盖。
# ABOUTME(en): AI generation service: takes a block's template brief, assembles a task prompt, produces prose variants.
# ABOUTME(en): Only generative/constrained blocks generate; the model defaults to DEFAULT_MODEL_ID, overridable.
from __future__ import annotations

import logging
from functools import lru_cache
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    knowledge_package_of,
    load_knowledge_package,
)
from sustainability_desk.contract.loader import load_package_contract
from sustainability_desk.contract.compiled_definition import load_compiled_report_definition
from sustainability_desk.contract.evidence_resolution import generation_evidence_keys
from sustainability_desk.contract.language import Language, count_length
from sustainability_desk.contract.models import Block, Report
from sustainability_desk.contract.visibility import visible, visible_block_in_report
from sustainability_desk.llm.generation_guardrails import (
    GuardrailIssue,
    GuardrailViolation,
    MAX_GENERATION_ATTEMPTS,
    build_retry_instruction,
    check_display_title_variants,
    check_paragraph_variants,
)
from sustainability_desk.llm.client import build_agent
from sustainability_desk.llm.concurrency import run_agent
from sustainability_desk.llm.ai_observability import (
    GuardrailIssueTrace,
    ObservationRun,
    record_guardrail_evaluation,
)
from sustainability_desk.llm.model_registry import DEFAULT_MODEL_ID
from sustainability_desk.llm.provider_output import parse_stringified_json
from sustainability_desk.llm.prompts import (
    ModelContext,
    build_model_context,
    contributing_intake_item_ids,
    model_context_observation_metadata,
    render_prompt,
)
from sustainability_desk.material.intake.file_agent_contract import FileMaterial
from sustainability_desk.material.mapping.decisions import BlockMaterialDecision

logger = logging.getLogger(__name__)




class GeneratedParagraphVariant(BaseModel):
    """一个不可拆分的标题—正文候选；未声明标题任务时 displayTitle 为空。"""

    model_config = ConfigDict(extra="forbid")

    displayTitle: str | None = None
    content: str

    @field_validator("displayTitle", "content")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("标题和正文不得为空")
        return stripped


class GeneratedParagraphVariants(BaseModel):
    """大模型结构化输出：若干完整、可直接采用的成对版本。"""

    model_config = ConfigDict(extra="forbid")

    variants: list[GeneratedParagraphVariant]

    @field_validator("variants", mode="before")
    @classmethod
    def _parse_stringified_variants(cls, value: object) -> object:
        # Qwen 经工具调用提交时会把数组或其元素序列化成 JSON 字符串（如 company_intro.body），
        # 输出重试无效；在合同边界解析后仍走同一结构校验。
        parsed = parse_stringified_json(value)
        if isinstance(parsed, list):
            return [parse_stringified_json(item) for item in parsed]
        return parsed


def _length_warnings(
    variants: list[str], target: tuple[int, int] | None, language: Language
) -> list[str]:
    """字数软校验：返回越界版本的提示文本（区间内不提示）；目标缺省则不校验。软约束，不阻断生成。"""
    if not target:
        return []
    lo, hi = target
    out: list[str] = []
    for i, v in enumerate(variants):
        n = count_length(v, language)
        if n < lo or n > hi:
            out.append(f"版本{i} 字数 {n} 越出目标区间 {lo}–{hi}")
    return out


@lru_cache(maxsize=None)
def _template_for_package(package_id: str) -> Report:
    from sustainability_desk.planner import load_topic_templates, with_topic_sections

    package = load_knowledge_package(package_id)
    # validated definition 是跨文件关系的唯一生产门禁；这里仅将其已验证的来源投影回
    # 生成器需要的 template Report，不能再运行平行 validator。
    load_compiled_report_definition(package)
    report = load_package_contract(package)
    templates = load_topic_templates(package)
    return with_topic_sections(report, templates)


def _template(package: KnowledgePackage) -> Report:
    """模板态契约（含各块写作 brief + 议题章节模板）；与实例 Report 分离——实例只提供事实值。

    合并议题章节模板（topic_sections），使议题生成块可被 find_block 定位并装配 typed task 与证据上下文。
    """
    return _template_for_package(package.id)


def prepare_generation_context(
    block_id: str,
    instance_report: Report,
    *,
    allow_synthetic_definition_fallback: bool = False,
    mapped_file_materials: tuple[FileMaterial, ...] = (),
    block_material_decision: BlockMaterialDecision | None = None,
) -> tuple[Block, ModelContext]:
    """校验当前生成目标并建立唯一 ModelContext。"""

    block = _template(knowledge_package_of(instance_report)).find_block(block_id)
    if block is None:
        raise ValueError(f"模板中不存在生成块 {block_id}")
    try:
        instance_report.find_block(block_id)
    except KeyError as exc:
        raise ValueError("该内容当前不在报告中；请先完成对应章节装配后再生成。") from exc
    if not visible_block_in_report(instance_report, block_id) or not visible(block, instance_report):
        raise ValueError("该内容当前不可见；请先完成对应前置填写后再生成。")
    if block.blockType not in ("generative", "constrained"):
        raise ValueError(f"块 {block_id} 不是可生成块（blockType={block.blockType}）")
    package = knowledge_package_of(instance_report)
    template = _template(package)
    canonical_definition = load_compiled_report_definition(package)
    if f"block/{block.id}" not in canonical_definition.nodes_by_id:
        if not allow_synthetic_definition_fallback:
            raise ValueError("生成目标不在 validated definition 中，拒绝使用局部 fallback。")
        return block, build_model_context(
            block,
            template,
            instance_report,
            definition=None,
            mapped_file_materials=mapped_file_materials,
            block_material_decision=block_material_decision,
        )
    return block, build_model_context(
        block,
        template,
        instance_report,
        definition=canonical_definition,
        mapped_file_materials=mapped_file_materials,
        block_material_decision=block_material_decision,
    )


class GenerationSourceRefs(BaseModel):
    """当前块生成实际消费的用户来源稳定标识；只供生成期落库，不进 ModelContext、不进 prompt。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intake_item_ids: tuple[str, ...] = ()
    material_ids: tuple[UUID, ...] = ()


def generation_source_refs(
    block_id: str,
    instance_report: Report,
    *,
    block_material_decision: BlockMaterialDecision | None = None,
) -> GenerationSourceRefs:
    """与 ``build_model_context`` 同一 selector、同一清单过滤、同一采用决定，解析本次实际消费的来源。

    清单项只计「有答案或补充说明」的项；文件资料只在采用决定为 supported / partially_supported
    时按决定顺序计入。结果是生成期领域事实，随生成结果落库，导出期不得重推（状态可能已变）。
    """

    package = knowledge_package_of(instance_report)
    block = _template(package).find_block(block_id)
    if block is None:
        raise ValueError(f"模板中不存在生成块 {block_id}")
    definition = load_compiled_report_definition(package)
    intake_keys, _metric_keys = generation_evidence_keys(
        block,
        _template(package),
        instance_report,
        definition if f"block/{block.id}" in definition.nodes_by_id else None,
    )
    material_ids: tuple[UUID, ...] = ()
    if (
        block_material_decision is not None
        and block_material_decision.block_id == block_id
        and block_material_decision.disposition in {"supported", "partially_supported"}
    ):
        material_ids = tuple(block_material_decision.material_ids)
    return GenerationSourceRefs(
        intake_item_ids=contributing_intake_item_ids(intake_keys, instance_report),
        material_ids=material_ids,
    )


async def generate_variants_from_model_context(
    block: Block,
    instance_report: Report,
    model_context: ModelContext,
    *,
    n: int = 3,
    model_id: str = DEFAULT_MODEL_ID,
    observation: ObservationRun,
    max_attempts: int = MAX_GENERATION_ATTEMPTS,
) -> list[GeneratedParagraphVariant]:
    """用已解析的唯一 ModelContext 完成结构化生成、Guardrail 与重试。"""

    if not 1 <= max_attempts <= MAX_GENERATION_ATTEMPTS:
        raise ValueError(
            f"max_attempts 必须在 1 到 {MAX_GENERATION_ATTEMPTS} 之间"
        )
    block_id = block.id
    ctx = model_context
    system, user = render_prompt(ctx, n=n)
    retry_instruction = ""
    last_issues = []
    # Issues from earlier attempts stay in the retry instruction: a fix for attempt 2 must not undo attempt 1's.
    accumulated_issues: list[GuardrailIssue] = []
    variants: list[GeneratedParagraphVariant] = []
    for attempt in range(max_attempts):
        attempt_system = system + (("\n\n" + retry_instruction) if retry_instruction else "")
        agent = build_agent(
            model_id,
            output_type=GeneratedParagraphVariants,
            instructions=attempt_system,
        )
        invocation = observation.invocation(
            block_id=block_id,
            model_id=model_id,
            task_context=ctx.model_dump(mode="json"),
            **model_context_observation_metadata(block, ctx),
        )
        variants = (await run_agent(agent, user, invocation)).output.variants[:n]
        contents = [variant.content for variant in variants]
        last_issues = []
        if ctx.display_title_task is not None and any(
            variant.displayTitle is None for variant in variants
        ):
            last_issues.append(
                GuardrailIssue(
                    key="missing_display_title",
                    message="声明标题任务的段落必须同时返回 displayTitle。",
                )
            )
        last_issues.extend(
            check_paragraph_variants(block, instance_report, ctx, contents)
        )
        if ctx.display_title_task is not None:
            last_issues.extend(
                check_display_title_variants(
                    block,
                    instance_report,
                    ctx,
                    [variant.displayTitle or "" for variant in variants],
                )
            )
        accumulated_issues.extend(last_issues)
        next_retry_instruction = (
            build_retry_instruction(accumulated_issues)
            if last_issues and attempt < max_attempts - 1
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
            break
        if next_retry_instruction:
            logger.warning(
                "生成 L1 断言未通过：块 %s 第 %d 次尝试发现 %d 项问题，准备重试",
                block_id, attempt + 1, len(last_issues),
            )
            retry_instruction = next_retry_instruction
    else:
        raise GuardrailViolation(last_issues)
    target = block.generation.targetChars if block.generation else None
    for warning in _length_warnings(
        [variant.content for variant in variants], target, ctx.output_language
    ):
        logger.warning("生成字数软校验：块 %s %s", block_id, warning)
    return variants


async def generate_variants(
    block_id: str,
    instance_report: Report,
    *,
    n: int = 3,
    model_id: str = DEFAULT_MODEL_ID,
    observation: ObservationRun,
    allow_synthetic_definition_fallback: bool = False,
    mapped_file_materials: tuple[FileMaterial, ...] = (),
    block_material_decision: BlockMaterialDecision | None = None,
) -> list[GeneratedParagraphVariant]:
    """为某 generative/constrained 块生成 n 个候选正文版本；事实从实例 Report 取。model_id 缺省走默认模型。"""
    block, model_context = prepare_generation_context(
        block_id,
        instance_report,
        allow_synthetic_definition_fallback=allow_synthetic_definition_fallback,
        mapped_file_materials=mapped_file_materials,
        block_material_decision=block_material_decision,
    )
    return await generate_variants_from_model_context(
        block,
        instance_report,
        model_context,
        n=n,
        model_id=model_id,
        observation=observation,
    )
