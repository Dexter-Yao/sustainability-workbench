# ABOUTME: 将固定骨架、议题注册表、内容清单、议题模板、指标和准则要求编译为唯一只读关系索引。
# ABOUTME: 编译结果只描述 authoring contract，不接受运行态用户值，也不持久化为第二份报告合同。
# ABOUTME(en): Compiles skeleton, topic registry, material inventory, templates, metrics and disclosure requirements.
# ABOUTME(en): Describes the authoring contract only: no runtime user values, never persisted as a second contract.
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping, NoReturn, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.contract.models import (
    Block,
    ConclusionKind,
    Condition,
    ExplicitGenerationEvidenceSelector,
    IntakeItem,
    MaterialGatedGenerationEvidenceSelector,
    Pillar,
    ReaderFeedbackContactInformation,
    Report,
    ReportInputMetadata,
    ReportSectionGenerationEvidenceSelector,
    Section,
)
from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    load_knowledge_package,
)
from sustainability_desk.contract.pillar_semantics import PillarPurpose, pillar_purpose_for
from sustainability_desk.contract.topic_registry import (
    AssessmentTopicRef,
    ReportModuleRef,
    ReportSectionRef,
    ResolvedTopicContract,
    load_topic_contract,
)
from sustainability_desk.contract.topic_section_template import compiled_metric_disclosure_keys
from sustainability_desk.quantitative_metrics import QuantitativeMetricDef, all_quantitative_metrics

_STANDARD_REF_MARKUP = re.compile(r"<ref>.*?</ref>", re.DOTALL)

NodeKind = Literal[
    "report_module",
    "report_section",
    "section",
    "block",
    "intake_item",
    "quantitative_metric",
    "assessment_topic",
    "appendix_projection",
]

# 此版本只标识 compiler、支柱语义与缺失行为的解释规则；authoring 文件版本仍由 contract_version() 单独拥有。
COMPILED_SEMANTICS_VERSION = "sustainability_desk.compiled_report_definition.semantics.v3"

_Key = TypeVar("_Key")
_Value = TypeVar("_Value")


class _ImmutableMapping(dict[_Key, _Value]):
    """可序列化且支持安全 deepcopy 的只读 dict 快照。"""

    __slots__ = ()

    def __init__(self, values: Mapping[_Key, _Value]) -> None:
        dict.__init__(self, values)

    @staticmethod
    def _reject_mutation(*args: object, **kwargs: object) -> NoReturn:
        raise TypeError("compiled mapping is immutable")

    __setitem__ = _reject_mutation
    __delitem__ = _reject_mutation
    clear = _reject_mutation
    pop = _reject_mutation
    popitem = _reject_mutation
    setdefault = _reject_mutation
    update = _reject_mutation
    __ior__ = _reject_mutation

    def __deepcopy__(self, memo: dict[int, object]) -> _ImmutableMapping[_Key, _Value]:
        memo[id(self)] = self
        return self


class _ImmutableList(list[_Value]):
    """保留 Pydantic list 序列化语义、同时拒绝所有原地变更。"""

    __slots__ = ()

    def __init__(self, values: list[_Value]) -> None:
        list.__init__(self, values)

    @staticmethod
    def _reject_mutation(*args: object, **kwargs: object) -> NoReturn:
        raise TypeError("compiled list is immutable")

    __setitem__ = _reject_mutation
    __delitem__ = _reject_mutation
    __iadd__ = _reject_mutation
    __imul__ = _reject_mutation
    append = _reject_mutation
    clear = _reject_mutation
    extend = _reject_mutation
    insert = _reject_mutation
    pop = _reject_mutation
    remove = _reject_mutation
    reverse = _reject_mutation
    sort = _reject_mutation

    def __deepcopy__(self, memo: dict[int, object]) -> _ImmutableList[_Value]:
        memo[id(self)] = self
        return self
AbsenceBehavior = Literal[
    "render_deterministically",
    "generate_context_only",
    "omit_if_unsupported",
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)


@lru_cache(maxsize=None)
def _frozen_model_type(model_type: type[BaseModel]) -> type[BaseModel]:
    """为可变 authoring DTO 构造仅供编译快照使用的冻结子类。"""

    if model_type.model_config.get("frozen"):
        return model_type

    def mutable_model_copy(
        instance: BaseModel,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> BaseModel:
        """显式复制从缓存快照派生独立、可变的原 authoring DTO。"""

        mutable = _deep_thaw(instance)
        assert isinstance(mutable, BaseModel)
        return BaseModel.model_copy(mutable, update=update, deep=deep)

    return type(
        f"CompiledFrozen{model_type.__name__}",
        (model_type,),
        {
            "__module__": __name__,
            "__compiled_mutable_model_type__": model_type,
            "model_config": ConfigDict(
                **{**model_type.model_config, "frozen": True}
            ),
            "model_copy": mutable_model_copy,
        },
    )


def _deep_freeze(value: object) -> object:
    """递归复制 authoring 值，避免缓存通过任意嵌套引用被原地污染。"""

    if isinstance(value, BaseModel):
        model_type = type(value)
        frozen_type = _frozen_model_type(model_type)
        fields = {
            name: _deep_freeze(getattr(value, name))
            for name in model_type.model_fields
        }
        return frozen_type.model_construct(
            _fields_set=value.model_fields_set,
            **fields,
        )
    if isinstance(value, Mapping):
        return _ImmutableMapping(
            {
                _deep_freeze(key): _deep_freeze(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, list):
        return _ImmutableList([_deep_freeze(item) for item in value])
    if isinstance(value, tuple):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: object) -> object:
    """从只读编译快照构造不共享嵌套引用的 authoring DTO。"""

    if isinstance(value, BaseModel):
        frozen_type = type(value)
        mutable_type = getattr(
            frozen_type, "__compiled_mutable_model_type__", frozen_type
        )
        fields = {
            name: _deep_thaw(getattr(value, name))
            for name in frozen_type.model_fields
        }
        return mutable_type.model_construct(
            _fields_set=value.model_fields_set,
            **fields,
        )
    if isinstance(value, Mapping):
        return {
            _deep_thaw(key): _deep_thaw(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_deep_thaw(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_deep_thaw(item) for item in value)
    if isinstance(value, frozenset):
        return {_deep_thaw(item) for item in value}
    return value


class ContractCompileError(ValueError):
    """稳定、可定位的 authoring contract 编译失败。"""

    def __init__(
        self,
        code: str,
        *,
        owner_kind: str,
        owner_id: str,
        source_location: str,
        message: str,
    ) -> None:
        self.code = code
        self.owner_kind = owner_kind
        self.owner_id = owner_id
        self.source_location = source_location
        self.detail = message
        super().__init__(
            f"[{code}] {owner_kind} {owner_id}（{source_location}）：{message}"
        )


class ContractValidationError(ValueError):
    """已编译定义未通过跨节点 ContractAudit 时拒绝生产消费。"""


class CompiledReportNode(_FrozenModel):
    node_id: str
    kind: NodeKind
    source_id: str
    parent_id: str | None = None
    ordered_child_ids: tuple[str, ...] = ()
    title: str
    heading_level: int | None = None
    report_module_id: str | None = None
    report_section_id: str | None = None
    assessment_topic_ids: tuple[str, ...] = ()
    owner_kind: str
    output_kind: str
    generation_kind: str
    visibility_contract: Condition | None = None


class CompiledNodePlacement(_FrozenModel):
    node_id: str
    ancestor_node_ids: tuple[str, ...]
    report_module_id: str | None = None
    report_section_id: str | None = None
    report_section_title: str | None = None
    pillar: Pillar | None = None
    pillar_title: str | None = None
    pillar_purpose: PillarPurpose | None = None
    content_unit_title: str | None = None


class CompiledGenerationContract(_FrozenModel):
    node_id: str
    block_id: str
    block_type: str
    absence_behavior: AbsenceBehavior
    semantic_task: str
    intake_item_ids: tuple[str, ...] = ()
    quantitative_metric_ids: tuple[str, ...] = ()
    field_ids: tuple[str, ...] = ()
    standard_requirement_refs: tuple[str, ...] = ()
    report_section_id: str | None = None
    display_title_guidance: str | None = None
    evidence_output_facets: tuple[str, ...] = ()
    produces_conclusion: ConclusionKind | None = None


class CompiledInputObligation(_FrozenModel):
    """从各输入 authoring owner 派生的一项阶段化输入义务。"""

    target_handle: str
    owner_kind: Literal["field", "intake_item", "appendix_value"]
    owner_id: str
    path: str
    label: str
    obligation: Literal["required_for_readiness", "optional"]
    required_before: Literal["workbench", "generation", "export"] | None = None
    appears_when: Condition | None = None

    @model_validator(mode="after")
    def _required_phase_matches_obligation(self) -> "CompiledInputObligation":
        # 阶段蕴含必填，但必填不蕴含阶段：一个字段可以「须填且在 readiness 引导用户补齐」，
        # 却不构成任何阶段门禁（正文不引用它，或承载块缺失时自行隐藏）。
        # 反向仍是错误——设了门禁阶段却标 optional，会让门禁没有引导来源。
        if self.required_before is not None and self.obligation != "required_for_readiness":
            raise ValueError("设定 required_before 的输入义务必须同时是 required_for_readiness")
        return self


class CompiledStandardRequirement(_FrozenModel):
    requirement_id: str
    report_section_id: str
    title: str
    text: str
    obligation_level: str


class StandardRequirementSourceLabel(_FrozenModel):
    """披露要求作者源中的单条准则定位。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    standard: str
    clauseRef: str


class StandardRequirementAuthoring(_FrozenModel):
    """披露要求作者源中的完整要求；所有业务字段必须显式存在。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    standardDisclosureRequirementKey: str
    standardDisclosureRequirementTitle: str
    excerptFrom: str
    standardDisclosureRequirementText: str
    disclosureRequirementObligationLevel: Literal[
        "required", "encouraged", "conditional"
    ]
    sourceClauseReferenceLabels: list[StandardRequirementSourceLabel]
    note: str | None = None


class StandardRequirementGroupAuthoring(_FrozenModel):
    """披露要求作者源中的报告支柱分组。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    topicSectionKey: str
    pillar: Pillar
    standardDisclosureRequirements: list[StandardRequirementAuthoring]


class StandardRequirementLibraryAuthoring(_FrozenModel):
    """单个议题披露要求 YAML 的严格根合同。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    topicStandardDisclosureRequirementGroups: list[StandardRequirementGroupAuthoring]


class CompiledTopicRelationship(_FrozenModel):
    report_section_id: str
    report_module_id: str
    assessment_topic_ids: tuple[str, ...]
    applicability: str | None = None


class CompiledReportDefinition(_FrozenModel):
    """所有确定性报告关系的唯一内部消费入口。"""

    schema_version: Literal["sustainability_desk.compiled_report_definition.v1"] = (
        "sustainability_desk.compiled_report_definition.v1"
    )
    package_id: str
    contract_version: str
    compiled_semantics_version: str
    fixed_report_definition: Report
    report_modules: tuple[ReportModuleRef, ...]
    report_sections: tuple[ReportSectionRef, ...]
    assessment_topics: tuple[AssessmentTopicRef, ...]
    nodes_by_id: Mapping[str, CompiledReportNode]
    input_definitions_by_id: Mapping[str, IntakeItem]
    metric_definitions_by_id: Mapping[str, QuantitativeMetricDef]
    standard_requirements_by_id: Mapping[str, CompiledStandardRequirement]
    node_placements: Mapping[str, CompiledNodePlacement]
    input_consumers: Mapping[str, tuple[str, ...]]
    metric_consumers: Mapping[str, tuple[str, ...]]
    topic_relationships: tuple[CompiledTopicRelationship, ...]
    visibility_contracts: Mapping[str, Condition]
    generation_contracts: Mapping[str, CompiledGenerationContract]
    input_obligations_by_target_handle: Mapping[str, CompiledInputObligation]
    deterministic_diagnostics: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _freeze_relation_indexes(self) -> CompiledReportDefinition:
        """Pydantic 解析完成后将全部嵌套 authoring 值复制为只读快照。"""

        for name in type(self).model_fields:
            object.__setattr__(self, name, _deep_freeze(getattr(self, name)))
        return self

    def block_node_id(self, block_id: str) -> str:
        node_id = f"block/{block_id}"
        if node_id not in self.nodes_by_id:
            raise KeyError(block_id)
        return node_id

    def placement_for_block(self, block_id: str) -> CompiledNodePlacement:
        return self.node_placements[self.block_node_id(block_id)]

    def generation_for_block(self, block_id: str) -> CompiledGenerationContract:
        return self.generation_contracts[self.block_node_id(block_id)]


def _standard_requirement_library(path: Path) -> StandardRequirementLibraryAuthoring:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        suffix = f":{mark.line + 1}:{mark.column + 1}" if mark is not None else ""
        raise ContractCompileError(
            "invalid_standard_requirement_yaml",
            owner_kind="standard_requirement_library",
            owner_id=path.stem,
            source_location=f"standard_disclosure_requirements/{path.name}{suffix}",
            message=str(error),
        ) from error
    try:
        return StandardRequirementLibraryAuthoring.model_validate(raw)
    except ValidationError as error:
        first_error = error.errors(include_url=False)[0]
        field_location = ".".join(str(part) for part in first_error["loc"])
        raise ContractCompileError(
            "invalid_standard_requirement_authoring",
            owner_kind="standard_requirement_library",
            owner_id=path.stem,
            source_location=(
                f"standard_disclosure_requirements/{path.name}:{field_location}"
            ),
            message=str(first_error["msg"]),
        ) from error


def _standard_requirements(package: KnowledgePackage) -> dict[str, CompiledStandardRequirement]:
    requirements: dict[str, CompiledStandardRequirement] = {}
    for path in sorted(package.standard_disclosure_requirements_dir.glob("*.yaml")):
        library = _standard_requirement_library(path)
        for group in library.topicStandardDisclosureRequirementGroups:
            for item in group.standardDisclosureRequirements:
                key = item.standardDisclosureRequirementKey
                if key in requirements:
                    raise ContractCompileError(
                        "duplicate_standard_requirement_id",
                        owner_kind="standard_requirement",
                        owner_id=key,
                        source_location=path.name,
                        message="准则披露要求 key 重复。",
                    )
                requirements[key] = CompiledStandardRequirement(
                    requirement_id=key,
                    report_section_id=path.stem,
                    title=item.standardDisclosureRequirementTitle,
                    text=_STANDARD_REF_MARKUP.sub(
                        "", item.standardDisclosureRequirementText
                    ).strip(),
                    obligation_level=item.disclosureRequirementObligationLevel,
                )
    return requirements


def _node_id(kind: NodeKind, source_id: str) -> str:
    return f"{kind}/{source_id}"


def _absence_behavior(block: Block) -> AbsenceBehavior:
    """从内容执行方式与证据选择器派生缺事实行为，不把 constrained 当作省略信号。

    ``material_gated`` selector 是块级显式声明「存在性由证据判定」：缺证据时整块
    受控省略（生成编排置 omitted），而非退回方向性生成。
    """

    if block.blockType in {"fixed", "slot"}:
        return "render_deterministically"
    selector = block.generation.inputs.evidence if block.generation else None
    if isinstance(selector, MaterialGatedGenerationEvidenceSelector):
        return "omit_if_unsupported"
    return "generate_context_only"


def _matches_requirement_ref(
    ref: str,
    requirements: Mapping[str, CompiledStandardRequirement],
    report_section_id: str | None,
) -> bool:
    if ref.endswith(".*"):
        return any(
            key.startswith(ref[:-1])
            and requirement.report_section_id == report_section_id
            for key, requirement in requirements.items()
        )
    requirement = requirements.get(ref)
    return bool(
        requirement is not None
        and requirement.report_section_id == report_section_id
    )


def _validate_conclusion_wiring(
    generations: Mapping[str, CompiledGenerationContract],
) -> None:
    """报告级结论的产出方校验：每种结论至多一个产出方。

    生成编排据此排阶段（产出方先于其余块），因此产出方必须在编译期唯一确定；
    两个块同时声明产出同一结论会让阶段划分产生歧义，故 fail-closed。
    """
    producers: dict[str, list[str]] = {}
    for contract in generations.values():
        if contract.produces_conclusion:
            producers.setdefault(contract.produces_conclusion, []).append(contract.block_id)
    for kind, blocks in producers.items():
        if len(blocks) > 1:
            raise ContractCompileError(
                "duplicate_conclusion_producer",
                owner_kind="block",
                owner_id=sorted(blocks)[0],
                source_location="report_contract/topic_sections",
                message=f"结论 {kind} 有多个产出方：{sorted(blocks)}；产出方须唯一。",
            )


def compile_report_definition(
    *,
    fixed: Report,
    topic_templates: Mapping[str, Section],
    intake_items: tuple[IntakeItem, ...] | list[IntakeItem],
    topic_contract: ResolvedTopicContract,
    metrics: tuple[QuantitativeMetricDef, ...] | list[QuantitativeMetricDef],
    standard_requirements: Mapping[str, CompiledStandardRequirement],
    package_id: str,
    compiled_contract_version: str,
    compiled_semantics_version: str = COMPILED_SEMANTICS_VERSION,
) -> CompiledReportDefinition:
    """严格编译全部 authoring sources；未知引用一律 fail-closed。"""

    inputs: dict[str, IntakeItem] = {}
    for item in [*(fixed.intakeItems or []), *intake_items]:
        if item.key in inputs:
            raise ContractCompileError(
                "duplicate_input_id",
                owner_kind="intake_item",
                owner_id=item.key,
                source_location="topic_intake",
                message="内容清单稳定 key 重复。",
            )
        inputs[item.key] = item
    metric_index = {metric.key: metric for metric in metrics}
    if len(metric_index) != len(metrics):
        raise ContractCompileError(
            "duplicate_metric_id",
            owner_kind="quantitative_metric",
            owner_id="*",
            source_location="quantitative_metrics.json",
            message="定量指标 key 重复。",
        )

    input_obligations: list[CompiledInputObligation] = []
    for field in fixed.fields.values():
        if field.source != "user_input":
            continue
        input_obligations.append(
            CompiledInputObligation(
                target_handle=f"field.{field.key}",
                owner_kind="field",
                owner_id=field.key,
                path=f"fields.{field.key}.value",
                label=field.label,
                obligation=(
                    "required_for_readiness" if field.required else "optional"
                ),
                # 阶段由字段显式声明；required 只表达"用户须填"，不再隐式合成门禁阶段。
                # 旧的 `"workbench" if field.required` 会把每个必填字段都变成最早阶段义务，
                # 使 13 个字段无差别阻断导出（含 9 个正文根本不引用或承载块自门控的字段）。
                required_before=field.requiredBefore,
                appears_when=field.appears_when,
            )
        )
    for item in inputs.values():
        input_obligations.append(
            CompiledInputObligation(
                target_handle=item.key,
                owner_kind="intake_item",
                owner_id=item.key,
                path=f"intakeItems.{item.key}",
                label=item.prompt,
                obligation=(
                    "required_for_readiness"
                    if item.requiredBefore is not None
                    else "optional"
                ),
                required_before=item.requiredBefore,
            )
        )
    for field_name, model_field in (
        ReaderFeedbackContactInformation.model_fields.items()
    ):
        metadata = next(
            (
                item
                for item in model_field.metadata
                if isinstance(item, ReportInputMetadata)
            ),
            None,
        )
        if metadata is None:
            continue
        input_obligations.append(
            CompiledInputObligation(
                target_handle=metadata.target_handle,
                owner_kind="appendix_value",
                owner_id=field_name,
                path=(
                    "appendixPackage.readerFeedbackContactInformation."
                    f"{field_name}"
                ),
                label=metadata.label,
                obligation=(
                    "required_for_readiness"
                    if metadata.required_before is not None
                    else "optional"
                ),
                required_before=metadata.required_before,
            )
        )
    obligations_by_target_handle: dict[str, CompiledInputObligation] = {}
    obligations_by_path: dict[str, CompiledInputObligation] = {}
    for obligation in input_obligations:
        if obligation.target_handle in obligations_by_target_handle:
            raise ContractCompileError(
                "duplicate_input_obligation_target",
                owner_kind=obligation.owner_kind,
                owner_id=obligation.owner_id,
                source_location=obligation.path,
                message=f"输入目标 {obligation.target_handle} 重复。",
            )
        if obligation.path in obligations_by_path:
            raise ContractCompileError(
                "duplicate_input_obligation_path",
                owner_kind=obligation.owner_kind,
                owner_id=obligation.owner_id,
                source_location=obligation.path,
                message="输入义务 path 重复。",
            )
        obligations_by_target_handle[obligation.target_handle] = obligation
        obligations_by_path[obligation.path] = obligation

    nodes: dict[str, CompiledReportNode] = {}
    placements: dict[str, CompiledNodePlacement] = {}
    visibility: dict[str, Condition] = {}
    generations: dict[str, CompiledGenerationContract] = {}
    input_consumers: dict[str, list[str]] = {key: [] for key in inputs}
    metric_consumers: dict[str, list[str]] = {key: [] for key in metric_index}

    def add_node(node: CompiledReportNode) -> None:
        if node.node_id in nodes:
            raise ContractCompileError(
                "duplicate_node_id",
                owner_kind=node.kind,
                owner_id=node.source_id,
                source_location="compiled node index",
                message=f"编译节点 ID {node.node_id} 重复。",
            )
        nodes[node.node_id] = node
        if node.visibility_contract is not None:
            visibility[node.node_id] = node.visibility_contract

    for module in topic_contract.source.reportModules:
        add_node(
            CompiledReportNode(
                node_id=_node_id("report_module", module.id),
                kind="report_module",
                source_id=module.id,
                title=module.navigationTitle,
                owner_kind="topic_registry",
                output_kind="structure",
                generation_kind="none",
            )
        )
    for section in topic_contract.source.reportSections:
        members = topic_contract.assessmentTopicsByReportSectionId[section.id]
        add_node(
            CompiledReportNode(
                node_id=_node_id("report_section", section.id),
                kind="report_section",
                source_id=section.id,
                parent_id=_node_id("report_module", section.reportModuleId),
                title=section.title,
                heading_level=2,
                report_module_id=section.reportModuleId,
                report_section_id=section.id,
                assessment_topic_ids=tuple(item.id for item in members),
                owner_kind="topic_registry",
                output_kind="structure",
                generation_kind="planner_branch",
            )
        )
    for topic in topic_contract.source.assessmentTopics:
        parent = (
            _node_id("report_section", topic.reportSectionId)
            if topic.reportSectionId is not None
            else None
        )
        add_node(
            CompiledReportNode(
                node_id=_node_id("assessment_topic", topic.id),
                kind="assessment_topic",
                source_id=topic.id,
                parent_id=parent,
                title=topic.name,
                report_section_id=topic.reportSectionId,
                assessment_topic_ids=(topic.id,),
                owner_kind="topic_registry",
                output_kind="assessment",
                generation_kind="none",
            )
        )

    def add_section_tree(
        section: Section,
        *,
        parent_id: str | None,
        ancestors: tuple[str, ...],
        report_module_id: str | None,
        report_section_id: str | None,
        report_section_title: str | None,
        pillar: Pillar | None,
        pillar_title: str | None,
        content_unit_title: str | None,
    ) -> str:
        effective_module = section.reportModuleId or report_module_id
        effective_report_section = section.reportSectionId or report_section_id
        effective_report_title = (
            section.title if section.reportSectionId is not None else report_section_title
        )
        effective_pillar_id = section.pillar if section.headingLevel == 3 else pillar
        effective_pillar = section.title if section.headingLevel == 3 else pillar_title
        effective_pillar_purpose = (
            pillar_purpose_for(effective_pillar_id, effective_pillar or "")
            if effective_pillar_id is not None
            else None
        )
        effective_unit = section.title if section.headingLevel == 4 else content_unit_title
        section_node_id = _node_id("section", section.key)
        block_ids = [_node_id("block", block.id) for block in section.blocks]
        if section.conciseDisclosure is not None:
            block_ids.append(_node_id("block", section.conciseDisclosure.id))
        child_ids = [_node_id("section", child.key) for child in section.children or ()]
        add_node(
            CompiledReportNode(
                node_id=section_node_id,
                kind="section",
                source_id=section.key,
                parent_id=parent_id,
                ordered_child_ids=tuple([*block_ids, *child_ids]),
                title=section.title,
                heading_level=section.headingLevel,
                report_module_id=effective_module,
                report_section_id=effective_report_section,
                assessment_topic_ids=tuple(
                    item.id
                    for item in topic_contract.assessmentTopicsByReportSectionId.get(
                        effective_report_section or "", ()
                    )
                ),
                owner_kind="report_contract" if effective_report_section is None else "topic_section",
                output_kind="structure",
                generation_kind="title" if section.titleGeneration is not None else "none",
                visibility_contract=section.appears_when,
            )
        )
        current_ancestors = (*ancestors, section_node_id)
        placements[section_node_id] = CompiledNodePlacement(
            node_id=section_node_id,
            ancestor_node_ids=ancestors,
            report_module_id=effective_module,
            report_section_id=effective_report_section,
            report_section_title=effective_report_title,
            pillar=effective_pillar_id,
            pillar_title=effective_pillar,
            pillar_purpose=effective_pillar_purpose,
            content_unit_title=effective_unit,
        )

        def add_block(block: Block) -> None:
            block_node_id = _node_id("block", block.id)
            add_node(
                CompiledReportNode(
                    node_id=block_node_id,
                    kind="block",
                    source_id=block.id,
                    parent_id=section_node_id,
                    title=block.table.caption if block.table and block.table.caption else block.id,
                    heading_level=section.headingLevel,
                    report_module_id=effective_module,
                    report_section_id=effective_report_section,
                    assessment_topic_ids=tuple(
                        item.id
                        for item in topic_contract.assessmentTopicsByReportSectionId.get(
                            effective_report_section or "", ()
                        )
                    ),
                    owner_kind="report_contract" if effective_report_section is None else "topic_section",
                    output_kind=block.type,
                    generation_kind=block.blockType,
                    visibility_contract=block.appears_when,
                )
            )
            placements[block_node_id] = CompiledNodePlacement(
                node_id=block_node_id,
                ancestor_node_ids=current_ancestors,
                report_module_id=effective_module,
                report_section_id=effective_report_section,
                report_section_title=effective_report_title,
                pillar=effective_pillar_id,
                pillar_title=effective_pillar,
                pillar_purpose=effective_pillar_purpose,
                content_unit_title=effective_unit,
            )
            generation = block.generation
            if generation is None:
                return
            selector = generation.inputs.evidence
            if isinstance(selector, ExplicitGenerationEvidenceSelector):
                intake_keys = tuple(selector.intakeItems)
                metric_keys = tuple(selector.quantitativeMetrics)
            elif isinstance(selector, MaterialGatedGenerationEvidenceSelector):
                intake_keys = tuple(selector.intakeItems)
                metric_keys = ()
            elif isinstance(selector, ReportSectionGenerationEvidenceSelector):
                if effective_report_section is None:
                    raise ContractCompileError(
                        "report_section_selector_without_owner",
                        owner_kind="block",
                        owner_id=block.id,
                        source_location="topic_sections",
                        message="report_section selector 的块没有报告 H2 owner。",
                    )
                intake_keys = tuple(
                    item.key
                    for item in inputs.values()
                    if item.contentScopeId == effective_report_section
                )
                metric_keys = compiled_metric_disclosure_keys(
                    topic_templates[effective_report_section]
                )
            else:  # pragma: no cover - Pydantic 判别联合已封闭
                raise AssertionError(selector)
            for key in intake_keys:
                if key not in inputs:
                    raise ContractCompileError(
                        "unknown_generation_input",
                        owner_kind="block",
                        owner_id=block.id,
                        source_location="topic_sections",
                        message=f"generation selector 引用未知 intake item：{key}",
                    )
                input_consumers[key].append(block_node_id)
            for key in metric_keys:
                if key not in metric_index:
                    raise ContractCompileError(
                        "unknown_generation_metric",
                        owner_kind="block",
                        owner_id=block.id,
                        source_location="topic_sections",
                        message=f"generation selector 引用未知 quantitative metric：{key}",
                    )
                metric_consumers[key].append(block_node_id)
            for key in generation.inputs.fields:
                if key not in fixed.fields:
                    raise ContractCompileError(
                        "unknown_generation_field",
                        owner_kind="block",
                        owner_id=block.id,
                        source_location="report_contract/topic_sections",
                        message=f"generation inputs 引用未知 field：{key}",
                    )
            refs = tuple(generation.standardDisclosureRequirementKeys or ())
            for ref in refs:
                if not _matches_requirement_ref(
                    ref, standard_requirements, effective_report_section
                ):
                    raise ContractCompileError(
                        "unknown_standard_requirement",
                        owner_kind="block",
                        owner_id=block.id,
                        source_location="topic_sections",
                        message=f"引用未知准则披露要求：{ref}",
                    )
            generations[block_node_id] = CompiledGenerationContract(
                node_id=block_node_id,
                block_id=block.id,
                block_type=block.blockType,
                absence_behavior=_absence_behavior(block),
                semantic_task=generation.task.focus.strip(),
                intake_item_ids=intake_keys,
                quantitative_metric_ids=metric_keys,
                field_ids=tuple(generation.inputs.fields),
                standard_requirement_refs=refs,
                report_section_id=effective_report_section,
                display_title_guidance=(
                    section.titleGeneration.guidance
                    if section.titleGeneration is not None
                    and section.titleGeneration.sourceBlockId == block.id
                    else None
                ),
                evidence_output_facets=tuple(
                    dict.fromkeys(
                        seed.category
                        for seed in (generation.fixedRowSeeds or ())
                        if seed.category
                    )
                ),
                produces_conclusion=generation.producesConclusion,
            )

        for block in section.blocks:
            add_block(block)
        if section.conciseDisclosure is not None:
            add_block(section.conciseDisclosure)
        for child in section.children or ():
            add_section_tree(
                child,
                parent_id=section_node_id,
                ancestors=current_ancestors,
                report_module_id=effective_module,
                report_section_id=effective_report_section,
                report_section_title=effective_report_title,
                pillar=effective_pillar_id,
                pillar_title=effective_pillar,
                content_unit_title=effective_unit,
            )
        return section_node_id

    for section in fixed.sections:
        add_section_tree(
            section,
            parent_id=None,
            ancestors=(),
            report_module_id=None,
            report_section_id=None,
            report_section_title=None,
            pillar=None,
            pillar_title=None,
            content_unit_title=None,
        )
    for report_section_id, section in topic_templates.items():
        definition = topic_contract.reportSectionsById.get(report_section_id)
        if definition is None:
            raise ContractCompileError(
                "unknown_report_section_template",
                owner_kind="report_section",
                owner_id=report_section_id,
                source_location="topic_sections",
                message="议题模板不属于 topic registry。",
            )
        add_section_tree(
            section,
            parent_id=_node_id("report_section", report_section_id),
            ancestors=(
                _node_id("report_module", definition.reportModuleId),
                _node_id("report_section", report_section_id),
            ),
            report_module_id=definition.reportModuleId,
            report_section_id=report_section_id,
            report_section_title=definition.title,
            pillar=None,
            pillar_title=None,
            content_unit_title=None,
        )

    for module in topic_contract.source.reportModules:
        node_id = _node_id("report_module", module.id)
        nodes[node_id] = nodes[node_id].model_copy(
            update={
                "ordered_child_ids": tuple(
                    _node_id("report_section", section.id)
                    for section in topic_contract.reportSectionsByReportModuleId[module.id]
                )
            }
        )
    for report_section in topic_contract.source.reportSections:
        node_id = _node_id("report_section", report_section.id)
        nodes[node_id] = nodes[node_id].model_copy(
            update={"ordered_child_ids": (_node_id("section", report_section.id),)}
        )

    for item in inputs.values():
        parent = (
            _node_id("report_section", item.contentScopeId)
            if item.contentScopeId in topic_contract.reportSectionsById
            else None
        )
        add_node(
            CompiledReportNode(
                node_id=_node_id("intake_item", item.key),
                kind="intake_item",
                source_id=item.key,
                parent_id=parent,
                title=item.prompt,
                report_section_id=(item.contentScopeId if parent else None),
                owner_kind="topic_intake" if parent else "report_contract",
                output_kind="input",
                generation_kind="none",
            )
        )
    for metric in metric_index.values():
        add_node(
            CompiledReportNode(
                node_id=_node_id("quantitative_metric", metric.key),
                kind="quantitative_metric",
                source_id=metric.key,
                title=metric.standaloneLabel or metric.metricLabel,
                owner_kind="quantitative_metrics",
                output_kind="metric",
                generation_kind="none",
            )
        )
    appendix_node_id = _node_id("appendix_projection", "report_appendix")
    add_node(
        CompiledReportNode(
            node_id=appendix_node_id,
            kind="appendix_projection",
            source_id="report_appendix",
            parent_id=_node_id("section", "report_appendix"),
            title="附录确定性投影",
            owner_kind="report_contract",
            output_kind="appendix",
            generation_kind="none",
        )
    )
    appendix_parent_id = _node_id("section", "report_appendix")
    if appendix_parent_id in nodes:
        parent = nodes[appendix_parent_id]
        nodes[appendix_parent_id] = parent.model_copy(
            update={"ordered_child_ids": (*parent.ordered_child_ids, appendix_node_id)}
        )

    def validate_condition(node_id: str, condition: Condition) -> None:
        node = nodes[node_id]
        if bool(condition.all) == bool(condition.any):
            raise ContractCompileError(
                "invalid_visibility_condition",
                owner_kind=node.kind,
                owner_id=node.source_id,
                source_location=node.owner_kind,
                message="visibility 必须且只能声明非空 all 或 any。",
            )
        for rule in (*(condition.all or ()), *(condition.any or ())):
            path = rule.path
            valid = False
            if path.startswith("fields.") and path.endswith(".value"):
                valid = path[len("fields.") : -len(".value")] in fixed.fields
            elif path.startswith("intakeItems."):
                valid = path[len("intakeItems.") :] in inputs
            elif path.startswith("quantitativeMetrics."):
                valid = path[len("quantitativeMetrics.") :] in metric_index
            elif path in {
                "meta.materialityStrategy",
                "appendixPackage.externalAssuranceReport.isIncluded",
                "appendixPackage.externalAssuranceReport.fileLabel",
                "appendixPackage.readerFeedbackContactInformation.address",
                "appendixPackage.readerFeedbackContactInformation.email",
                "appendixPackage.readerFeedbackContactInformation.phone",
            }:
                valid = True
            elif path.startswith("assessment.counts."):
                valid = path.rsplit(".", 1)[-1] in {
                    "dual", "impact", "impact_only", "financial", "financial_only", "non", "non_material"
                }
            elif path.startswith("assessment.topics.") and path.endswith(".materiality"):
                topic_id = path[len("assessment.topics.") : -len(".materiality")]
                valid = topic_id in {topic.id for topic in topic_contract.source.assessmentTopics}
            elif path.startswith("blocks.") and path.endswith(".state"):
                valid = _node_id("block", path[len("blocks.") : -len(".state")]) in nodes
            if not valid:
                raise ContractCompileError(
                    "unknown_visibility_path",
                    owner_kind=node.kind,
                    owner_id=node.source_id,
                    source_location=node.owner_kind,
                    message=f"visibility 引用无法解析的 path：{path}",
                )

    for node_id, condition in visibility.items():
        validate_condition(node_id, condition)

    relationships = tuple(
        CompiledTopicRelationship(
            report_section_id=resolved.definition.id,
            report_module_id=resolved.definition.reportModuleId,
            assessment_topic_ids=tuple(topic.id for topic in resolved.assessmentTopics),
            applicability=resolved.applicability,
        )
        for resolved in topic_contract.resolvedReportSectionsById.values()
    )
    _validate_conclusion_wiring(generations)
    return CompiledReportDefinition(
        package_id=package_id,
        contract_version=compiled_contract_version,
        compiled_semantics_version=compiled_semantics_version,
        fixed_report_definition=fixed,
        report_modules=topic_contract.source.reportModules,
        report_sections=topic_contract.source.reportSections,
        assessment_topics=topic_contract.source.assessmentTopics,
        nodes_by_id=MappingProxyType(nodes),
        input_definitions_by_id=MappingProxyType(inputs),
        metric_definitions_by_id=MappingProxyType(metric_index),
        standard_requirements_by_id=MappingProxyType(dict(standard_requirements)),
        node_placements=MappingProxyType(placements),
        input_consumers=MappingProxyType(
            {key: tuple(dict.fromkeys(value)) for key, value in input_consumers.items()}
        ),
        metric_consumers=MappingProxyType(
            {key: tuple(dict.fromkeys(value)) for key, value in metric_consumers.items()}
        ),
        topic_relationships=relationships,
        visibility_contracts=MappingProxyType(visibility),
        generation_contracts=MappingProxyType(generations),
        input_obligations_by_target_handle=MappingProxyType(
            obligations_by_target_handle
        ),
    )


@lru_cache(maxsize=8)
def _load_compiled_report_definition(package_id: str, version: str) -> CompiledReportDefinition:
    from sustainability_desk.contract.loader import load_package_contract
    from sustainability_desk.planner import load_topic_intake, load_topic_templates

    package = load_knowledge_package(package_id)
    return compile_report_definition(
        fixed=load_package_contract(package),
        topic_templates=load_topic_templates(package),
        intake_items=load_topic_intake(package),
        topic_contract=load_topic_contract(package),
        metrics=all_quantitative_metrics(package),
        standard_requirements=_standard_requirements(package),
        package_id=package.id,
        compiled_contract_version=version,
    )


@lru_cache(maxsize=8)
def _load_validated_compiled_report_definition(
    package_id: str,
    version: str,
    semantics_version: str,
) -> CompiledReportDefinition:
    """生产入口：严格编译后必须通过跨节点 ContractAudit。"""

    from sustainability_desk.contract.audit import audit_contract

    definition = _load_compiled_report_definition(package_id, version)
    errors = tuple(
        finding for finding in audit_contract(definition) if finding.severity == "error"
    )
    if errors:
        detail = "；".join(
            f"{item.code}（{item.owner_kind}/{item.owner_id}）" for item in errors
        )
        raise ContractValidationError(f"报告合同审计未通过：{detail}")
    if definition.compiled_semantics_version != semantics_version:
        raise RuntimeError("compiled definition 语义版本与 validated loader 不一致")
    return definition


def load_compiled_report_definition(package: KnowledgePackage) -> CompiledReportDefinition:
    """返回该知识包唯一生产有效 definition；运行态 Report 从不进入缓存。"""

    return _load_validated_compiled_report_definition(
        package.id, contract_version(package), COMPILED_SEMANTICS_VERSION
    )
