# ABOUTME: 版本化 ReportProfile 的严格加载与服务端选择，区分报告产品语义与账户权益。
# ABOUTME: Profile 不拥有正文或客户事实；客户端只能按 id 请求已注册的 Profile。
# ABOUTME(en): Strict loading and server-side selection of versioned ReportProfiles, separate from account entitlements.
# ABOUTME(en): A Profile binds one knowledge package to product semantics and owns no prose or customer facts.
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    load_knowledge_package,
)

BACKEND = Path(__file__).resolve().parents[3]
PROFILE_REGISTRY = BACKEND / "data" / "report_profiles.yaml"

# 报告类型 = 生产管线身份，不是商业档位名；当前只有轻量版一条管线。
ReportType = Literal["lightweight"]
# 创建端点接受的报告类型；验收工具与前端不各写一份字面值。
DEFAULT_CUSTOMER_REPORT_TYPE: ReportType = "lightweight"
# Profile 边界上可被裁决的操作；除工作台外其余对轻量版恒开放，仍显式声明以便服务端统一断言。
ReportProfileOperation = Literal["report_flow", "report_state", "export", "workbench"]


class ReportProfile(BaseModel):
    """一份报告产品 Profile；业务能力均由服务端按 Profile 解释。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_type: ReportType
    display_name: str = Field(min_length=1, max_length=200)
    # The knowledge package (standards framework × language) every report on this Profile is built from.
    knowledge_package: str
    requires_synthetic_data: bool = False
    generation_required_field_ids: tuple[str, ...] = ()
    workbench_enabled: bool = True


class ReportProfileRegistry(BaseModel):
    """所有已审核报告 Profile 的唯一加载边界。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    profiles: dict[str, ReportProfile]
    defaults: dict[ReportType, str]

    @model_validator(mode="after")
    def validate_profiles(self) -> "ReportProfileRegistry":
        if not self.profiles:
            raise ValueError("ReportProfile 注册表不得为空")
        invalid = [profile_id for profile_id in self.profiles if "@" not in profile_id]
        if invalid:
            raise ValueError(f"ReportProfile ID 必须包含版本: {invalid}")
        for profile_id, profile in self.profiles.items():
            # Fail at registry load, not at first report: a Profile naming a missing package is a
            # configuration defect, not a per-request condition.
            load_knowledge_package(profile.knowledge_package)
        profile_types = {profile.report_type for profile in self.profiles.values()}
        if set(self.defaults) != profile_types:
            raise ValueError("每个已注册报告类型必须恰有一个服务端默认 Profile")
        for report_type, profile_id in self.defaults.items():
            profile = self.profiles.get(profile_id)
            if profile is None or profile.report_type != report_type:
                raise ValueError(f"报告类型 {report_type} 的默认 Profile 无效: {profile_id}")
        return self


@lru_cache(maxsize=1)
def load_report_profile_registry() -> ReportProfileRegistry:
    """加载并冻结所有可用 ReportProfile。"""

    return ReportProfileRegistry.model_validate(
        yaml.safe_load(PROFILE_REGISTRY.read_text(encoding="utf-8"))
    )


class ReportProfileOperationError(ValueError):
    """Profile 边界拒绝当前操作；携带排查用 profile_id 与面向用户的稳定 code。

    profile_id 是内部产品配置标识，只作排查上下文：它曾随 `未知 ReportProfile: {id}`
    的消息经 8 个 router 的 `detail=str(error)` 透传到 409 响应体。API 边界据 code
    生成用户文案，不读取本异常的消息。
    """

    def __init__(self, code: str, message: str, *, profile_id: str) -> None:
        # 消息即用户文案：本异常的既有捕获点用 `detail=str(error)` 透传，只要把
        # profile_id 拼进消息，换个包装仍会泄露。内部上下文只留在属性上，由 API
        # 边界写日志，不进响应体。
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.profile_id = profile_id


def require_report_profile(profile_id: str) -> ReportProfile:
    """按稳定版本 ID 获取 Profile；未知 ID 一律拒绝。"""

    try:
        return load_report_profile_registry().profiles[profile_id]
    except KeyError as exc:
        raise ReportProfileOperationError(
            "report_profile_unknown",
            "报告配置不可识别，请联系支持人员",
            profile_id=profile_id,
        ) from exc


def knowledge_package_for_profile(profile_id: str) -> KnowledgePackage:
    """Resolve the knowledge package a report Profile is built on."""

    return load_knowledge_package(require_report_profile(profile_id).knowledge_package)


def default_report_profile_id(report_type: ReportType) -> str:
    """由服务端为请求的报告类型选择唯一已审核 Profile。"""

    try:
        return load_report_profile_registry().defaults[report_type]
    except KeyError as exc:
        raise ReportProfileOperationError(
            "report_type_unavailable",
            "当前报告类型不可用，请联系支持人员",
            profile_id=report_type,
        ) from exc


def assert_report_profile_operation(
    profile_id: str, operation: ReportProfileOperation
) -> ReportProfile:
    """在产品 Profile 边界拒绝未开放操作。"""

    profile = require_report_profile(profile_id)
    # 工作台编辑必须由服务端裁决：前端隐藏入口不构成防护，直接调用 API 仍会改到正文。
    if operation == "workbench" and not profile.workbench_enabled:
        raise ReportProfileOperationError(
            "workbench_disabled",
            "该报告未启用报告工作台",
            profile_id=profile_id,
        )
    return profile


def report_profile_capability_matrix(profile_id: str) -> dict[str, bool]:
    """返回 Profile 的显式产品能力矩阵；前端展示不得替代此服务端裁决。"""

    profile = require_report_profile(profile_id)
    return {
        "report_flow": True,
        "report_state": True,
        "export": True,
        "material_workspace": True,
        "workbench": profile.workbench_enabled,
    }
