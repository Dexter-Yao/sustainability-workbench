# ABOUTME: 链路阶段的唯一词汇表——阶段常量声明在实现它的模块内，导入即登记，冲突即抛错。
# ABOUTME: 本模块只做聚合与加载期校验，不是第二份事实；阶段的存在与其代码同址（spec 决策点 B）。
# ABOUTME(en): Single vocabulary of pipeline stages — a Stage is declared in the module implementing it, importing
# ABOUTME(en): registers it, conflict raises. Only aggregates and validates at load time; not a second truth.
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from sustainability_desk.accounts.report_execution_scope import ReportScopeKind

StageKind = Literal[
    "orchestration",
    "llm",
    "agent",
    "tool",
    "deterministic",
    "external_process",
]


class StageRegistrationError(Exception):
    """阶段登记冲突。同 id 不同定义意味着两处代码在争夺同一词汇，必须当场失败。"""


class Stage(BaseModel):
    """一个链路阶段。与使用它的 open_stage 调用声明在同一文件，经 register_stage 登记。

    字段里没有 parent：span 父子由代码真实调用结构（显式句柄或同任务 ContextVar）
    决定，不再维护一棵声明式树（旧方案的虚构节点与豁免空洞正源于此）。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: StageKind
    # None 表示不受报告执行范围约束（eval 运行、API 直连操作）。
    scopes: tuple[ReportScopeKind, ...] | None = None
    # 工作单元根阶段：create_observation_run 只接受 unit_root 阶段，
    # 观测事件的 operation 词汇由此派生，不再是自由字符串。
    unit_root: bool = False
    # 仅 external_process：数值必须从实现处的代码常量派生（如 toc 的超时常量），
    # 不得在此另行维护一份会漂移的副本。
    external_dependency: str | None = None
    timeout_seconds: int | None = None

    @model_validator(mode="after")
    def _check_field_dependencies(self) -> "Stage":
        if self.kind == "external_process":
            if self.external_dependency is None or self.timeout_seconds is None:
                raise ValueError(
                    f"stage {self.id}：external_process 必须声明 external_dependency 与 timeout_seconds"
                )
        elif self.external_dependency is not None or self.timeout_seconds is not None:
            raise ValueError(
                f"stage {self.id}：只有 external_process 才能声明 external_dependency / timeout_seconds"
            )
        if self.scopes is not None and not self.scopes:
            raise ValueError(
                f"stage {self.id}：scopes 空元组无意义——不受范围约束应显式用 None"
            )
        return self


_REGISTRY: dict[str, Stage] = {}


def register_stage(stage: Stage) -> Stage:
    """登记一个阶段常量并原样返回。声明模块在 import 时调用，重复且不一致即抛错。"""
    existing = _REGISTRY.get(stage.id)
    if existing is not None and existing != stage:
        raise StageRegistrationError(
            f"阶段 {stage.id} 重复登记且定义不一致——同一 id 只能有一处声明"
        )
    _REGISTRY[stage.id] = stage
    return stage


def registered_stage(stage_id: str) -> Stage | None:
    """按 id 查询已登记阶段；仅供运行期一致性校验与投影使用。"""
    return _REGISTRY.get(stage_id)


def registered_stages() -> tuple[Stage, ...]:
    """当前进程内已登记的全部阶段（按 id 排序）。集合内容取决于已导入的模块。"""
    return tuple(_REGISTRY[key] for key in sorted(_REGISTRY))


_DECLARING_MODULES = (
    # 供人读投影使用的声明模块清单；运行期不依赖它——阶段随实现模块导入自动登记。
    "sustainability_desk.material.agent_pipeline",
    "sustainability_desk.lightweight_report_generation",
    "sustainability_desk.llm.generate_all",
    "sustainability_desk.llm.table_gen",
    "sustainability_desk.export.toc",
)


def _import_declaring_modules() -> None:
    import importlib

    for name in _DECLARING_MODULES:
        importlib.import_module(name)


def main() -> None:
    """打印当前阶段词汇表——非工程视角的只读投影，由代码生成，不回写。"""
    _import_declaring_modules()
    for stage in registered_stages():
        scope_text = "*" if stage.scopes is None else ",".join(stage.scopes)
        root_text = " [unit-root]" if stage.unit_root else ""
        extra = (
            f" external={stage.external_dependency} timeout={stage.timeout_seconds}s"
            if stage.kind == "external_process"
            else ""
        )
        print(f"{stage.id}  kind={stage.kind}  scopes={scope_text}{root_text}{extra}")


if __name__ == "__main__":
    main()
