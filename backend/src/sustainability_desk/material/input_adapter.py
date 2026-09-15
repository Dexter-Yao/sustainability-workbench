# ABOUTME: 资料工作区到轻量版报告输入的唯一适配器，投影可写字段、内容清单、指标和附录输入。
# ABOUTME: 适配器只在状态解析边界校验与应用 typed 写入；模型不能直接改写 StoredReportStateV4。
# ABOUTME(en): Sole adapter from material workspace to lightweight report inputs, metrics and appendix inputs.
# ABOUTME(en): Applies typed writes only at the state parse boundary; models never rewrite StoredReportStateV4.
from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sustainability_desk.contract.compiled_definition import load_compiled_report_definition
from sustainability_desk.contract.models import (
    IntakeItem,
    QuantitativeMetricDraft,
    ReaderFeedbackContactInformation,
    ReportInputMetadata,
)
from sustainability_desk.contract.report_values import is_valid_contact_email
from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    load_knowledge_package,
)
from sustainability_desk.contract.loader import load_package_contract
from sustainability_desk.contract.stored_report_state import StoredReportStateV4
from sustainability_desk.planner import load_topic_intake
from sustainability_desk.quantitative_metrics import all_quantitative_metrics


class UnknownMaterialTargetError(ValueError):
    """资料模块请求了当前 adapter 未暴露的报告输入。"""


class TargetValueConflictError(Exception):
    """目标题已被其他用户操作修改，提案不能继续声称基于当前值。"""


class MaterialInputTarget(BaseModel):
    """供资料解析 Harness 和前端投影消费的可写报告输入定义。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    target_type: Literal["field", "intake", "quantitative_metric", "appendix"]
    scope_id: str
    prompt: str
    kind: Literal[
        "text", "single_select", "multi_select", "number", "percent",
        "year", "month", "date", "url", "email",
    ]
    options: tuple[str, ...] = ()
    option_groups: tuple["MaterialInputOptionGroup", ...] = ()
    collection_priority: Literal["core", "recommended", "optional"] = "recommended"
    min_chars: int | None = None
    max_chars: int | None = None


class MaterialInputOptionGroup(BaseModel):
    """多选题的人类审阅分组与最小选择合同。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    label: str
    options: tuple[str, ...]
    min_selections: int = Field(ge=0)


class InputWrite(BaseModel):
    """一次经过 typed 解析、合同校验后可原子应用的报告输入写入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_key: str
    answer: str | int | float | list[str]
    supplement: str | None = None
    expected_definition_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_target_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


@lru_cache(maxsize=None)
def _definitions(package_id: str) -> dict[str, IntakeItem]:
    package = load_knowledge_package(package_id)
    contract = load_package_contract(package)
    topics = load_topic_intake(package)
    return {item.key: item for item in [*contract.intakeItems, *topics]}


@lru_cache(maxsize=1)
def _appendix_metadata() -> dict[str, ReportInputMetadata]:
    result: dict[str, ReportInputMetadata] = {}
    for field in ReaderFeedbackContactInformation.model_fields.values():
        metadata = next(
            (
                item
                for item in field.metadata
                if isinstance(item, ReportInputMetadata)
            ),
            None,
        )
        if metadata is not None:
            result[metadata.target_handle] = metadata
    return result


class LightweightReportInputAdapter:
    """报告的资料输入边界；目标题目录来自报告所属知识包。"""

    adapter_id = "simplified-report-input@2"

    def __init__(self, package: KnowledgePackage) -> None:
        self._package = package

    @staticmethod
    def fingerprint(
        answer: str | int | float | list[str] | None,
        supplement: str | None,
    ) -> str:
        payload = json.dumps(
            {"answer": answer, "supplement": supplement},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def target(self, key: str) -> MaterialInputTarget:
        definition = _definitions(self._package.id).get(key)
        if definition is not None:
            return MaterialInputTarget(
                key=definition.key,
                target_type="intake",
                scope_id="profile" if definition.key == "company_profile" else definition.contentScopeId,
                prompt=definition.prompt,
                kind=definition.kind,
                options=tuple(definition.options or ()),
                option_groups=tuple(
                    MaterialInputOptionGroup(
                        key=group.key,
                        label=group.label,
                        options=tuple(group.options),
                        min_selections=group.minSelections,
                    )
                    for group in definition.optionGroups or ()
                ),
                collection_priority=definition.collectionPriority,
                min_chars=definition.minChars,
                max_chars=definition.maxChars,
            )
        contract = load_package_contract(self._package)
        if key.startswith("field."):
            field_key = key.removeprefix("field.")
            field = contract.fields.get(field_key)
            if field is None or field.source != "user_input":
                raise UnknownMaterialTargetError(f"资料模块不可写入目标：{key}")
            return MaterialInputTarget(
                key=key,
                target_type="field",
                scope_id="report_configuration",
                prompt=f"请从企业资料中提取“{field.label}”。",
                kind={"string": "text", "enum": "single_select"}.get(
                    field.type, field.type,
                ),
                options=tuple(field.options or ()),
                collection_priority="core" if field.required else "recommended",
            )
        if key.startswith("metric."):
            metric_key = key.removeprefix("metric.")
            metric = next(
                (
                    item
                    for item in all_quantitative_metrics(self._package)
                    if item.key == metric_key
                ),
                None,
            )
            if metric is None:
                raise UnknownMaterialTargetError(f"资料模块不可写入目标：{key}")
            return MaterialInputTarget(
                key=key,
                target_type="quantitative_metric",
                scope_id="quantitative_metrics",
                prompt=(
                    f"请提取 ESG 定量指标“{metric.metricLabel}”的报告期数值；"
                    f"单位为{metric.unit}，只填写数值。"
                ),
                kind="number",
                collection_priority="recommended",
            )
        metadata = _appendix_metadata().get(key)
        obligation = (
            load_compiled_report_definition(self._package)
            .input_obligations_by_target_handle.get(key)
        )
        if (
            metadata is not None
            and obligation is not None
            and obligation.owner_kind == "appendix_value"
        ):
            return MaterialInputTarget(
                key=key,
                target_type="appendix",
                scope_id="report_configuration",
                prompt=f"请从企业资料中提取“{obligation.label}”。",
                kind="email" if metadata.value_type == "email" else "text",
                collection_priority=(
                    "core"
                    if obligation.obligation == "required_for_readiness"
                    else "optional"
                ),
            )
        raise UnknownMaterialTargetError(f"资料模块不可写入目标：{key}")

    def target_fingerprint(self, key: str) -> str:
        """绑定提案创建时的题型合同；题干、选项或限制变化后必须重新审阅。"""
        target = self.target(key)
        payload = json.dumps(
            target.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def current_value(
        self,
        state: StoredReportStateV4,
        target_key: str,
    ) -> tuple[str | int | float | list[str] | None, str | None]:
        """从唯一持久化状态读取一个 adapter target 的当前值。"""

        return self._current_value(
            state.model_dump(mode="python"),
            target_key,
        )

    def targets(self, scope_id: str | None = None) -> list[MaterialInputTarget]:
        contract = load_package_contract(self._package)
        projected = [
            *(self.target(key) for key in _definitions(self._package.id)),
            *(
                self.target(f"field.{key}")
                for key, field in contract.fields.items()
                if field.source == "user_input"
            ),
            *(
                self.target(f"metric.{metric.key}")
                for metric in all_quantitative_metrics(self._package)
            ),
            *(
                self.target(key)
                for key, obligation in (
                    load_compiled_report_definition(self._package)
                    .input_obligations_by_target_handle.items()
                )
                if obligation.owner_kind == "appendix_value"
            ),
        ]
        return [target for target in projected if scope_id is None or target.scope_id == scope_id]

    def validate_write(self, write: InputWrite) -> InputWrite:
        target = self.target(write.target_key)
        if write.expected_definition_fingerprint != self.target_fingerprint(write.target_key):
            raise TargetValueConflictError(f"目标题定义已变化：{write.target_key}")
        answer = write.answer
        options = set(target.options)
        if target.kind == "text":
            if not isinstance(answer, str):
                raise ValueError(f"目标 {target.key} 的答案必须是文本")
            length = len(answer.strip())
            if target.min_chars is not None and length < target.min_chars:
                raise ValueError(f"目标 {target.key} 至少 {target.min_chars} 个字符")
            if target.max_chars is not None and length > target.max_chars:
                raise ValueError(f"目标 {target.key} 最多 {target.max_chars} 个字符")
        elif target.kind == "single_select":
            if not isinstance(answer, str) or answer not in options:
                raise ValueError(f"目标 {target.key} 的答案必须是声明选项之一")
        elif target.kind == "multi_select":
            if not isinstance(answer, list) or not answer or any(item not in options for item in answer):
                raise ValueError(f"目标 {target.key} 的答案必须是非空选项子集")
            if len(answer) != len(set(answer)):
                raise ValueError(f"目标 {target.key} 不得重复选择选项")
            selected = set(answer)
            for group in target.option_groups:
                count = len(selected.intersection(group.options))
                if count < group.min_selections:
                    raise ValueError(
                        f"目标 {target.key} 的{group.label}至少选择 {group.min_selections} 项"
                    )
        else:
            if not isinstance(answer, (str, int, float)) or isinstance(answer, bool):
                raise ValueError(f"目标 {target.key} 的答案必须是单个标量")
            if target.target_type == "quantitative_metric":
                QuantitativeMetricDraft(value=str(answer), note=write.supplement)
            elif target.target_type == "field":
                field_key = target.key.removeprefix("field.")
                field = load_package_contract(self._package).fields[field_key]
                field.model_copy(update={"value": answer})
            elif target.target_type == "appendix" and target.kind == "email":
                if not is_valid_contact_email(str(answer).strip()):
                    raise ValueError(f"目标 {target.key} 的答案必须是邮箱地址")
        if target.kind != "text" and write.supplement and target.max_chars is not None:
            if len(write.supplement.strip()) > target.max_chars:
                raise ValueError(f"目标 {target.key} 的补充说明最多 {target.max_chars} 个字符")
        return write

    def apply(self, state: dict[str, object], writes: list[InputWrite]) -> dict[str, object]:
        """在内存副本中原子校验并应用一组同 scope 写入；调用方负责数据库事务。"""
        return self._apply(state, writes, require_single_scope=True)

    def apply_automatic(
        self, state: dict[str, object], writes: list[InputWrite],
    ) -> dict[str, object]:
        """将一次自动预处理的跨域输入原子投影到唯一报告状态。"""
        return self._apply(state, writes, require_single_scope=False)

    def _apply(
        self,
        state: dict[str, object],
        writes: list[InputWrite],
        *,
        require_single_scope: bool,
    ) -> dict[str, object]:
        """共享的严格写入实现；只允许自动 Harness 跨输入域提交。"""
        if not writes:
            raise ValueError("至少需要一条已接受提案")
        keys = [write.target_key for write in writes]
        if len(keys) != len(set(keys)):
            raise ValueError("同一批次不得重复写入目标题")
        validated = [self.validate_write(write) for write in writes]
        scopes = {self.target(write.target_key).scope_id for write in validated}
        if require_single_scope and len(scopes) != 1:
            raise ValueError("资料提案必须按单一议题批次写入")

        updated = copy.deepcopy(state)
        for write in validated:
            current = self._current_value(updated, write.target_key)
            current_fingerprint = self.fingerprint(
                current[0], current[1]
            )
            if current_fingerprint != write.expected_target_fingerprint:
                raise TargetValueConflictError(write.target_key)
        for write in validated:
            self._apply_one(updated, write)
        return updated

    def _current_value(
        self, state: dict[str, object], target_key: str,
    ) -> tuple[str | int | float | list[str] | None, str | None]:
        """从唯一 StoredReportStateV4 形态读取一个目标的当前值。"""
        target = self.target(target_key)
        if target.target_type == "intake":
            item = (state.get("intakeItems") or {}).get(target_key)  # type: ignore[union-attr]
            return (
                item.get("answer") if isinstance(item, dict) else None,
                item.get("supplement") if isinstance(item, dict) else None,
            )
        if target.target_type == "field":
            fields = state.get("fields") or {}
            return (fields.get(target_key.removeprefix("field.")) if isinstance(fields, dict) else None, None)
        if target.target_type == "quantitative_metric":
            meta = state.get("meta") or {}
            quantitative = meta.get("quantitativeMetrics") if isinstance(meta, dict) else None
            metrics = quantitative.get("metrics") if isinstance(quantitative, dict) else None
            metric = metrics.get(target_key.removeprefix("metric.")) if isinstance(metrics, dict) else None
            return (metric.get("value") if isinstance(metric, dict) else None, metric.get("note") if isinstance(metric, dict) else None)
        appendix = state.get("appendixPackage") or {}
        reader = appendix.get("readerFeedbackContactInformation") if isinstance(appendix, dict) else None
        key = target_key.rsplit(".", 1)[-1]
        return (reader.get(key) if isinstance(reader, dict) else None, None)

    def _apply_one(self, state: dict[str, object], write: InputWrite) -> None:
        """把已校验写入按 target_type 投影至唯一状态位置。"""
        target = self.target(write.target_key)
        if target.target_type == "intake":
            items = state.setdefault("intakeItems", {})
            if not isinstance(items, dict):
                raise ValueError("报告 intakeItems 状态格式不正确")
            items[write.target_key] = {"answer": write.answer, "supplement": write.supplement}
            return
        if target.target_type == "field":
            fields = state.setdefault("fields", {})
            if not isinstance(fields, dict):
                raise ValueError("报告 fields 状态格式不正确")
            fields[write.target_key.removeprefix("field.")] = write.answer
            return
        if target.target_type == "quantitative_metric":
            meta = state.get("meta")
            if meta is None:
                meta = {}
                state["meta"] = meta
            if not isinstance(meta, dict):
                raise ValueError("报告 meta 状态格式不正确")
            quantitative = meta.get("quantitativeMetrics")
            if quantitative is None:
                quantitative = {}
                meta["quantitativeMetrics"] = quantitative
            if not isinstance(quantitative, dict):
                raise ValueError("报告 quantitativeMetrics 状态格式不正确")
            metrics = quantitative.get("metrics")
            if metrics is None:
                metrics = {}
                quantitative["metrics"] = metrics
            if not isinstance(metrics, dict):
                raise ValueError("报告 metrics 状态格式不正确")
            metrics[write.target_key.removeprefix("metric.")] = {
                "value": str(write.answer), "note": write.supplement,
            }
            return
        appendix = state.get("appendixPackage")
        if appendix is None:
            appendix = {}
            state["appendixPackage"] = appendix
        if not isinstance(appendix, dict):
            raise ValueError("报告 appendixPackage 状态格式不正确")
        reader = appendix.get("readerFeedbackContactInformation")
        if reader is None:
            reader = {}
            appendix["readerFeedbackContactInformation"] = reader
        if not isinstance(reader, dict):
            raise ValueError("报告 reader feedback 状态格式不正确")
        reader[write.target_key.rsplit(".", 1)[-1]] = write.answer
