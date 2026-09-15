# ABOUTME: 解析版本化权益 Profile；本机单用户模式下权益只含活跃报告上限与章节重写额度。
# ABOUTME: 配置缺失或未知字段一律启动失败，授权边界不得猜测或回退。
# ABOUTME(en): Parses versioned entitlement Profiles; locally an entitlement is only the active-report
# ABOUTME(en): limit and section-regeneration quota. Missing config or unknown fields fail at startup.
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# 报告执行范围的唯一词汇别名；report_execution_scope 与观测模块从此处引用，
# 不得再手写平行字面量。
# 值里的 simplified 是公开契约字面量（流经 schema_export 到前端，或已落库）；
# 内部实现已统一为 lightweight，此处待下次契约版本变更时一并收敛（docs/todos.md）。
ReportScopeKind = Literal["full_simplified"]

BACKEND = Path(__file__).resolve().parents[3]
PROFILE_REGISTRY = BACKEND / "data" / "entitlement_profiles.yaml"


class EntitlementProfile(BaseModel):
    """一个不可变权益版本的可执行合同。

    报告形态（章节集合、交付物种类、资料 Agent 与 Word 导出）在单档模式下是常量，
    由 `report_execution_scope.execution_scope_for_profile()` 拥有，不在此重复声明。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    active_report_limit: int = Field(ge=1)
    section_regeneration_limit: int = Field(ge=0)


class EntitlementRegistry(BaseModel):
    """权益注册表根合同。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    profiles: dict[str, EntitlementProfile]

    @model_validator(mode="after")
    def validate_versioned_ids(self) -> "EntitlementRegistry":
        if not self.profiles:
            raise ValueError("权益注册表不得为空")
        invalid = [profile_id for profile_id in self.profiles if "@" not in profile_id]
        if invalid:
            raise ValueError(f"权益 Profile ID 必须包含版本: {invalid}")
        return self


@lru_cache(maxsize=1)
def load_entitlement_registry() -> EntitlementRegistry:
    return EntitlementRegistry.model_validate(yaml.safe_load(PROFILE_REGISTRY.read_text("utf-8")))


def require_profile(profile_id: str) -> EntitlementProfile:
    try:
        return load_entitlement_registry().profiles[profile_id]
    except KeyError as exc:
        raise ValueError(f"未知权益 Profile: {profile_id}") from exc
