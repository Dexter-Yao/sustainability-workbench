# ABOUTME: 对 CompiledReportDefinition 运行稳定、无副作用的确定性合同审计。
# ABOUTME: 默认不输出；显式模块调用才打印完整 finding，error 由测试和 CI 负责失败。
# ABOUTME(en): Runs a stable, side-effect-free deterministic contract audit over a CompiledReportDefinition.
# ABOUTME(en): Silent by default; only an explicit module run prints findings, and errors are failed by tests and CI.
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from sustainability_desk.contract.compiled_definition import CompiledReportDefinition, load_compiled_report_definition


class ContractAuditFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    severity: Literal["error", "warning", "review"]
    owner_kind: str
    owner_id: str
    related_ids: tuple[str, ...] = ()
    message: str


def audit_contract(definition: CompiledReportDefinition) -> tuple[ContractAuditFinding, ...]:
    findings: list[ContractAuditFinding] = []
    nodes = definition.nodes_by_id

    for node in nodes.values():
        if node.parent_id is not None and node.parent_id not in nodes:
            findings.append(
                ContractAuditFinding(
                    code="invalid_parent_reference",
                    severity="error",
                    owner_kind=node.kind,
                    owner_id=node.source_id,
                    related_ids=(node.parent_id,),
                    message="父节点引用不存在。",
                )
            )
        missing_children = tuple(
            child_id for child_id in node.ordered_child_ids if child_id not in nodes
        )
        if missing_children:
            findings.append(
                ContractAuditFinding(
                    code="invalid_child_reference",
                    severity="error",
                    owner_kind=node.kind,
                    owner_id=node.source_id,
                    related_ids=missing_children,
                    message="子节点引用不存在。",
                )
            )
        if node.kind == "section" and node.parent_id:
            parent = nodes.get(node.parent_id)
            if (
                parent is not None
                and parent.kind == "section"
                and parent.heading_level is not None
                and node.heading_level != parent.heading_level + 1
            ):
                findings.append(
                    ContractAuditFinding(
                        code="invalid_heading_level",
                        severity="error",
                        owner_kind=node.kind,
                        owner_id=node.source_id,
                        related_ids=(parent.source_id,),
                        message="heading level 必须等于直属 Section 父级加一。",
                    )
                )

    for input_id, consumers in definition.input_consumers.items():
        if not consumers:
            item = definition.input_definitions_by_id[input_id]
            findings.append(
                ContractAuditFinding(
                    code="unconsumed_intake_item",
                    severity="review",
                    owner_kind="intake_item",
                    owner_id=input_id,
                    message=(
                        f"内容清单项没有生成消费者；如只服务确定性用户输入，应在 owner 合同明确用途。"
                        f" scope={item.contentScopeId}"
                    ),
                )
            )

    for node_id, generation in definition.generation_contracts.items():
        node = nodes[node_id]
        if node.generation_kind in {"fixed", "slot"}:
            findings.append(
                ContractAuditFinding(
                    code="deterministic_node_has_generation_contract",
                    severity="error",
                    owner_kind="block",
                    owner_id=generation.block_id,
                    message="fixed/slot 节点不得进入模型生成合同。",
                )
            )

    shared: dict[tuple[str | None, str | None, tuple[str, ...], tuple[str, ...]], list] = {}
    for generation in definition.generation_contracts.values():
        # 图片块输出的是视觉（image），与同证据段落不构成重复叙述，不进入职责互斥审查。
        if nodes[generation.node_id].output_kind == "image":
            continue
        placement = definition.node_placements[generation.node_id]
        evidence_key = (
            placement.report_section_id,
            placement.pillar_title,
            generation.intake_item_ids,
            generation.quantitative_metric_ids,
        )
        if generation.intake_item_ids or generation.quantitative_metric_ids:
            shared.setdefault(evidence_key, []).append(generation)
    for candidates in shared.values():
        if len(candidates) < 2:
            continue
        facets = [set(candidate.evidence_output_facets) for candidate in candidates]
        proven_disjoint = all(
            left and right and left.isdisjoint(right)
            for index, left in enumerate(facets)
            for right in facets[index + 1 :]
        )
        if not proven_disjoint:
            findings.append(
                ContractAuditFinding(
                    code="shared_evidence_requires_review",
                    severity="review",
                    owner_kind="generation_contract",
                    owner_id=candidates[0].block_id,
                    related_ids=tuple(candidate.block_id for candidate in candidates[1:]),
                    message="同一支柱内多个生成节点共享完全相同的 Evidence，且合同未证明输出职责互斥。",
                )
            )

    deterministic_refs: dict[str, list[str]] = {}
    for block in definition.fixed_report_definition.iter_blocks():
        for inline in block.content or ():
            if inline.kind == "ref" and inline.ref and inline.ref.startswith("assessment.counts."):
                deterministic_refs.setdefault(inline.ref, []).append(block.id)
    for ref, block_ids in deterministic_refs.items():
        unique = tuple(dict.fromkeys(block_ids))
        if len(unique) > 1:
            findings.append(
                ContractAuditFinding(
                    code="duplicate_deterministic_fact_rendering",
                    severity="review",
                    owner_kind="report_contract",
                    owner_id=unique[0],
                    related_ids=unique[1:],
                    message=f"同一重要性计数事实 {ref} 在固定章节重复渲染。",
                )
            )

    return tuple(findings)


def main() -> None:
    findings = audit_contract(load_compiled_report_definition())
    print(json.dumps([item.model_dump(mode="json") for item in findings], ensure_ascii=False, indent=2))
    if any(item.severity == "error" for item in findings):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
