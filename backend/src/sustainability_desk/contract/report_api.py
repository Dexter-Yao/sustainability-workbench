# ABOUTME: 报告导航、状态持久化与状态驱动生成接口的严格公共响应合同。
# ABOUTME: 后端响应与前端 Ajv 解析均由这些 Pydantic 模型派生，禁止手写平行数据形状。
# ABOUTME(en): Strict public response contract for report navigation, state persistence and state-driven generation.
# ABOUTME(en): Backend responses and frontend Ajv parsing derive from these models; hand-written shapes are banned.
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sustainability_desk.contract.models import (
    AssessmentCounts,
    AssessmentScoreScale,
    MaterialityAssessmentInput,
    MaterialityThreshold,
    QuantitativeMetricDraft,
    QuantitativeMetricsMeta,
    SectionDisplayTitle,
)
from sustainability_desk.contract.structured_inputs import StructuredInputStatus
from sustainability_desk.quantitative_metrics import QuantitativeMetricDef
from sustainability_desk.lightweight_report_readiness import LightweightReportReadiness
from sustainability_desk.contract.block_provenance import ReportBlockProvenanceProjection
from sustainability_desk.contract.report_lineage import ReportLineageProjection
from sustainability_desk.contract.language import Language
from sustainability_desk.contract.report_profiles import ReportType, knowledge_package_for_profile
from sustainability_desk.contract.report_preparation import ReportPreparationProjection
from sustainability_desk.contract.report_generation import ReportGenerationProjection
from sustainability_desk.contract.stored_report_state import StoredReportStateV4


class ReportApiModel(BaseModel):
    """报告核心 API 响应及嵌套 DTO 的严格解析基类。"""

    model_config = ConfigDict(extra="forbid")


def _derive_language_from_profile(data: object) -> object:
    """Project the report language from its Profile when the producer did not spell it out.

    The Profile registry is the single owner of profile → package → language; DAL rows and
    routers therefore never carry a second copy of the language that could drift.
    """

    if isinstance(data, dict) and "language" not in data and "report_profile_id" in data:
        return {
            **data,
            "language": knowledge_package_for_profile(data["report_profile_id"]).language,
        }
    return data


class ReportSummaryResponse(ReportApiModel):
    """报告列表与生命周期操作共用的权威摘要。"""

    id: UUID
    title: str
    report_type: ReportType
    report_profile_id: str
    # Output language of the report, derived from its Profile's knowledge package (BCP 47).
    language: Language
    data_classification: Literal["synthetic", "customer"]
    created_under_profile_id: str
    contract_version: str
    status: Literal["active", "archived"]
    created_at: str
    updated_at: str
    # 派生自 state.fields 的公司注册名，仅供列表显示名；未填写或旧数据为 None。
    company_registered_name: str | None = None

    _derive_language = model_validator(mode="before")(_derive_language_from_profile)


class ReportListResponse(ReportApiModel):
    """报告列表响应。"""

    reports: list[ReportSummaryResponse]


class ReportCapabilitiesResponse(ReportApiModel):
    """Account 与单份 Report 合并后的实际能力。"""

    allowed_report_section_ids: list[str]
    section_regeneration_limit: int = Field(ge=0)
    can_generate: bool
    can_regenerate_sections: bool
    can_export_word: bool
    material_agent_enabled: bool
    # 评分页、模板下载导入与矩阵预览是否开放。与"评分是否进入交付物"是两件事：
    # 浏览器据此决定页面可用性，不得自行反推能力。
    collects_materiality_assessment: bool
    allowed_quantitative_metric_keys: list[str]
    allowed_report_artifact_kinds: list[Literal["word", "review"]]


class InternalAuditArtifactResponse(ReportApiModel):
    """内部审计权限持有者的跨 Account 交付物定位投影。"""

    artifact_id: UUID
    report_id: UUID
    report_title: str = Field(min_length=1, max_length=200)
    account_email: str = Field(min_length=3, max_length=320)
    filename: str = Field(min_length=1, max_length=500)
    created_at: str
    download_href: str


class InternalAuditArtifactListResponse(ReportApiModel):
    artifacts: list[InternalAuditArtifactResponse]


class ReportStateResponse(ReportApiModel):
    """报告状态快照及其乐观锁序号。"""

    state: StoredReportStateV4
    state_seq: int = Field(ge=1)
    contract_version: str
    report_profile_id: str
    # Output language of the report, derived from its Profile's knowledge package (BCP 47).
    language: Language
    capabilities: ReportCapabilitiesResponse

    _derive_language = model_validator(mode="before")(_derive_language_from_profile)


class PutReportStateResponse(ReportApiModel):
    """成功持久化后的新状态序号。"""

    state_seq: int = Field(ge=1)


class AssessmentCatalogTopicResponse(ReportApiModel):
    """由议题 Registry 与当前报告适用性共同投影的可评分议题。"""

    assessmentTopicId: str
    name: str
    dimension: str
    order: int = Field(ge=0)
    reportSectionId: str


class AssessmentScoreWrite(ReportApiModel):
    """在线评分的一项用户事实；名称、适用性、章节与期间均由服务端拥有。"""

    assessmentTopicId: str
    financialScore: float
    impactScore: float


class ResolvedAssessmentTopicResponse(ReportApiModel):
    """权威 resolved materiality 的可展示议题投影；固定议题不伪造分数。"""

    assessmentTopicId: str
    name: str
    dimension: str
    order: int = Field(ge=0)
    reportSectionId: str | None
    determination: Literal["scored", "fixed"]
    materiality: Literal["dual", "impact", "financial", "non"]
    financialScore: float | None = None
    impactScore: float | None = None


class ResolvedAssessmentResponse(ReportApiModel):
    """由 assessmentInput 与 Registry 现算的唯一展示结果。"""

    reportingYear: int
    threshold: MaterialityThreshold | None
    counts: AssessmentCounts
    topics: list[ResolvedAssessmentTopicResponse]


class PutAssessmentInputRequest(ReportApiModel):
    """整批替换重要性评分；expected_state_seq 防止覆盖其他入口的新状态。"""

    expected_state_seq: int = Field(ge=1)
    threshold: MaterialityThreshold
    scores: list[AssessmentScoreWrite]


class PutQuantitativeMetricsRequest(ReportApiModel):
    """整批替换全目录定量草稿；单位与期间不是客户端可写事实。"""

    expected_state_seq: int = Field(ge=1)
    metrics: dict[str, QuantitativeMetricDraft]
    greenhouseGasAccountingStandard: str | None = None
    greenhouseGasAccountingStandardOther: str | None = None


class AssessmentInputResponse(ReportApiModel):
    """当前报告的重要性目录、权威输入及 scoped freshness。"""

    status: StructuredInputStatus
    state_seq: int = Field(ge=1)
    contract_version: str
    context_fingerprint: str = Field(min_length=64, max_length=64)
    score_scale: AssessmentScoreScale
    topics: list[AssessmentCatalogTopicResponse]
    current: MaterialityAssessmentInput | None
    resolved: ResolvedAssessmentResponse | None
    readiness: LightweightReportReadiness


class QuantitativeMetricsResponse(ReportApiModel):
    """当前报告的完整指标目录、权威输入及 scoped freshness。"""

    status: StructuredInputStatus
    state_seq: int = Field(ge=1)
    contract_version: str
    context_fingerprint: str = Field(min_length=64, max_length=64)
    catalog: list[QuantitativeMetricDef]
    greenhouse_gas_accounting_standard_options: list[str]
    no_value_reasons: list[str]
    current: QuantitativeMetricsMeta
    readiness: LightweightReportReadiness


class StructuredInputMutationResponse(ReportApiModel):
    """结构化输入原子写成功后的完整权威状态，不要求客户端拼接局部结果。"""

    state: StoredReportStateV4
    state_seq: int = Field(ge=1)
    contract_version: str
    readiness: LightweightReportReadiness


class StructuredInputConflictResponse(ReportApiModel):
    """409 冲突时返回当前权威快照，客户端只能重载而不能猜测合并。"""

    code: Literal["report_state_conflict"] = "report_state_conflict"
    message: str
    current: StructuredInputMutationResponse


class StructuredInputPreconditionResponse(ReportApiModel):
    """409 前置条件不满足时返回稳定顶层错误，不伪造当前状态快照。"""

    code: Literal[
        "contract_upgrade_required",
        "simplified_v4_required",
    ]
    message: str


StructuredInputErrorResponse = (
    StructuredInputConflictResponse | StructuredInputPreconditionResponse
)


class RewriteAllowanceResponse(ReportApiModel):
    """指定报告页面的服务端权威重写额度。"""

    section_key: str
    quota: int = Field(ge=0)
    used: int = Field(ge=0)
    remaining: int = Field(ge=0)


class SectionGenerationFreshnessResponse(ReportApiModel):
    """当前模型可见输入与最近成功生成输入的比较结果。"""

    status: Literal["not_generated", "fresh", "stale"]
    current_input_fingerprint: str = Field(min_length=64, max_length=64)
    generated_input_fingerprint: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )


class ModuleTitleGenerationResponse(ReportApiModel):
    """报告模块标题原子写回后的公共响应。"""

    section_titles: dict[str, SectionDisplayTitle]
    state_seq: int = Field(ge=1)


class ReportProfileOption(ReportApiModel):
    """建报时可选的一项报告配置：一个知识包（准则 × 语言）的产品化投影。

    只暴露选择所需的事实。Profile 的能力字段（工作台开关、生成必填字段、合成数据要求）
    是服务端裁决依据，不进客户端——客户端按 id 请求，不自行解释能力。
    """

    report_profile_id: str
    display_name: str
    language: Literal["zh-Hans", "zh-Hant", "en"]


class ReportProfileOptionsResponse(ReportApiModel):
    """建报可选配置清单与服务端默认项。"""

    profiles: tuple[ReportProfileOption, ...]
    default_report_profile_id: str


class GenerationModelOption(ReportApiModel):
    """一次生成可选的模型。

    只暴露选择所需的事实：稳定 id 与服务商标识。**部署名与端点、密钥环境变量名
    一律不进客户端**——部署名是私有基础设施事实（如某资源上的具体部署），
    泄漏它既无助于选择，也把服务端拓扑写进了界面。
    """

    model_id: str
    vendor: str


class GenerationModelOptionsResponse(ReportApiModel):
    """当前环境可选的生成模型清单与服务端默认项。

    清单只含凭据齐备者：列出一个点下去才失败的选项，等于把配置错误推迟到生成现场。
    """

    models: tuple[GenerationModelOption, ...]
    default_model_id: str


class ReportApiContractBundle(ReportApiModel):
    """仅用于导出一份包含全部核心响应定义的前端运行时 schema。"""

    report_summary: ReportSummaryResponse | None = None
    report_list: ReportListResponse | None = None
    report_state: ReportStateResponse | None = None
    report_lineage: ReportLineageProjection | None = None
    block_provenance: ReportBlockProvenanceProjection | None = None
    report_preparation: ReportPreparationProjection | None = None
    report_generation: ReportGenerationProjection | None = None
    internal_audit_artifacts: InternalAuditArtifactListResponse | None = None
    put_report_state: PutReportStateResponse | None = None
    assessment_input: AssessmentInputResponse | None = None
    quantitative_metrics: QuantitativeMetricsResponse | None = None
    structured_input_mutation: StructuredInputMutationResponse | None = None
    structured_input_conflict: StructuredInputConflictResponse | None = None
    rewrite_allowance: RewriteAllowanceResponse | None = None
    generation_freshness: SectionGenerationFreshnessResponse | None = None
    module_title_generation: ModuleTitleGenerationResponse | None = None
    report_profile_options: ReportProfileOptionsResponse | None = None
    generation_model_options: GenerationModelOptionsResponse | None = None
