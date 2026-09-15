# ABOUTME: 本地端到端验收的 15 文件选择清单、排版素材清单与测试输入装载边界。
# ABOUTME: 文件声明与准入走生产合同；结构化输入沿用既有 owner，不建立平行语义。
# ABOUTME(en): The 15-file selection manifest, layout asset manifest and test input loading boundary for local E2E.
# ABOUTME(en): File declaration and admission follow production contracts; structured input keeps its existing owner.
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import UUID

import openpyxl
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sustainability_desk.assets.scoring import parse_scoring
from sustainability_desk.assets.scoring_template import create_scoring_template
from sustainability_desk.assets.quantitative_parser import parse_quantitative_workbook
from sustainability_desk.assets.quantitative_template import (
    GHG_STANDARD_CELL,
    QUANTITATIVE_CONFIG_SHEET,
    QUANTITATIVE_HEADER_ROW,
    create_quantitative_template,
)
from sustainability_desk.contract.build_report import build_report
from sustainability_desk.contract.knowledge_packages import KnowledgePackage
from sustainability_desk.contract.loader import load_package_contract
from sustainability_desk.contract.compiled_definition import COMPILED_SEMANTICS_VERSION
from sustainability_desk.contract.company_inputs import CompanyInputs
from sustainability_desk.contract.report_profiles import knowledge_package_for_profile
from sustainability_desk.contract.report_revision import (
    build_report_revision,
    company_inputs_from_stored_state,
)
from sustainability_desk.contract.stakeholder_engagement import (
    reconcile_stakeholder_engagement_profile,
)
from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.contract.assessment_classify import DEFAULT_THRESHOLD
from sustainability_desk.contract.models import (
    MaterialityAssessmentInput,
    MaterialityScoreInput,
)
from sustainability_desk.contract.stored_report_state import (
    StoredReportStateV4,
    empty_stored_report_state,
)
from sustainability_desk.contract.structured_inputs import (
    StructuredInputContext,
    quantitative_metrics_context_fingerprint,
)
from sustainability_desk.contract.topic_registry import applicable_scoring_topics, resolve_topic
from sustainability_desk.quantitative_metrics import quantitative_metric_sheets
from sustainability_desk.material.input_adapter import InputWrite, LightweightReportInputAdapter
from sustainability_desk.material.intake.files import validate_material_file
from sustainability_desk.material.intake.image_agent_contract import ImageAssetCategory
from sustainability_desk.material.intake.models import (
    MaterialKind,
    UserFileDeclaration,
    ValidatedMaterialFile,
)

# 本模块住在 backend/tests/ 下，故 parents[2] 即仓库根。
# 不用固定层数从 __file__ 反推更深的路径：搬动文件时那种写法会静默指向仓库外，
# 表现为 fixture「文件不存在」而非「路径算错」，排查成本远高于在此写清楚。
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SELECTION_MANIFEST_PATH = (
    _REPOSITORY_ROOT
    / "backend"
    / "tests"
    / "fixtures"
    / "local_e2e"
    / "shengyuan"
    / "shengyuan_materials.yaml"
)
_FIXTURE_REPORT_ID = UUID("00000000-0000-0000-0000-000000000015")
DEFAULT_INPUT_FIXTURE_PATH = (
    _REPOSITORY_ROOT
    / "backend"
    / "tests"
    / "fixtures"
    / "local_e2e"
    / "shengyuan"
    / "shengyuan_report_inputs.yaml"
)

SelectionDomain = Literal["company_basics", "climate", "supply_chain"]
_REQUIRED_TAG_BY_SELECTION_DOMAIN: dict[SelectionDomain, str] = {
    "company_basics": "company_and_report_basics",
    "climate": "climate_change",
    "supply_chain": "sustainable_supply_chain_management",
}


class LocalE2EContractModel(BaseModel):
    """本地验收配置的严格、不可变解析边界。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SelectedMaterial(LocalE2EContractModel):
    """一项去重准入资料及模拟用户提供的权威文件声明。"""

    caseId: str = Field(pattern=r"^material-\d{2}$")
    ordinal: int = Field(ge=1)
    relativePath: str = Field(min_length=1)
    selectionDomains: tuple[SelectionDomain, ...] = Field(min_length=1)
    selectionRationale: str = Field(min_length=1)
    expectedKind: MaterialKind
    expectedMediaType: str = Field(min_length=1)
    expectedSizeBytes: int = Field(gt=0)
    expectedSha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectedPdfPageCount: int | None = Field(default=None, ge=1)
    declaration: UserFileDeclaration

    @model_validator(mode="after")
    def _validate_selection(self) -> "SelectedMaterial":
        path = PurePosixPath(self.relativePath)
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise ValueError("选择资料路径必须是 corpus 根目录下的规范相对路径")
        if path.name != self.relativePath.split("/")[-1]:
            raise ValueError("选择资料路径必须使用 POSIX 分隔符")
        if self.expectedKind not in {"pdf", "docx", "xlsx"}:
            raise ValueError("本地验收只接纳语义资料格式，不接纳图片")
        if self.expectedKind == "pdf":
            if (
                self.expectedPdfPageCount is None
                or self.expectedPdfPageCount > 10
            ):
                raise ValueError("本地验收 PDF 必须记录页数且不得超过 10 页")
        elif self.expectedPdfPageCount is not None:
            raise ValueError("非 PDF 资料不得记录 PDF 页数")
        if self.declaration.role != "semantic_material":
            raise ValueError("本地验收选择项必须全部是 semantic_material")
        required_tags = {
            _REQUIRED_TAG_BY_SELECTION_DOMAIN[domain]
            for domain in self.selectionDomains
        }
        if not required_tags.issubset(self.declaration.topic_tags):
            raise ValueError("用户文件标签必须覆盖清单中的选择领域")
        return self


class SelectedDeliverableMaterial(LocalE2EContractModel):
    """一项交付演练资料及用户提供的权威文件声明（v3）。

    与 v2 验收选择项的差异：按生产准入合同接纳全部语义格式（含 pptx、≤40 页 PDF）
    与排版素材（png/jpeg/webp/单页 pdf），不再限定 15 文件语义清单。
    """

    caseId: str = Field(pattern=r"^material-\d{2}$")
    ordinal: int = Field(ge=1)
    relativePath: str = Field(min_length=1)
    selectionRationale: str = Field(min_length=1)
    expectedKind: MaterialKind
    expectedMediaType: str = Field(min_length=1)
    expectedSizeBytes: int = Field(gt=0)
    expectedSha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectedPdfPageCount: int | None = Field(default=None, ge=1)
    declaration: UserFileDeclaration

    @model_validator(mode="after")
    def _validate_selection(self) -> "SelectedDeliverableMaterial":
        path = PurePosixPath(self.relativePath)
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise ValueError("选择资料路径必须是 corpus 根目录下的规范相对路径")
        if path.name != self.relativePath.split("/")[-1]:
            raise ValueError("选择资料路径必须使用 POSIX 分隔符")
        if (self.expectedKind == "pdf") != (self.expectedPdfPageCount is not None):
            raise ValueError("PDF 资料必须记录页数；非 PDF 资料不得记录页数")
        if self.declaration.role == "semantic_material":
            if self.expectedKind not in {"pdf", "docx", "xlsx", "pptx"}:
                raise ValueError("语义资料格式必须在生产准入合同内")
            if (self.expectedPdfPageCount or 0) > 40:
                raise ValueError("语义资料 PDF 不得超过 40 页")
            if len((self.declaration.description or "").strip()) < 10:
                raise ValueError("交付演练语义资料说明必须完整（不少于 10 字）")
        else:
            if self.expectedKind not in {"png", "jpeg", "webp", "pdf"}:
                raise ValueError("排版素材格式必须在生产准入合同内")
            if self.expectedKind == "pdf" and self.expectedPdfPageCount != 1:
                raise ValueError("排版素材 PDF 仅接受单页")
        return self


class LocalE2EDeliverableSelectionManifest(LocalE2EContractModel):
    """交付演练资料清单（v3）：真实企业资料 corpus 的全量上传预期。"""

    contract: Literal["sustainability_desk.local_e2e_selection_manifest.v3"]
    manifestId: str = Field(min_length=1)
    artifactPurpose: Literal["local_e2e_test", "customer_deliverable_rehearsal"]
    corpusRootRelative: str = Field(min_length=1)
    selectionBasis: Literal["path_and_filename_only", "customer_provided_corpus"]
    selectionPolicyVersion: str = Field(min_length=1)
    selectedFileCount: int = Field(ge=1, le=30)
    excludedPathSegments: tuple[str, ...] = ()
    uploadBatches: tuple[tuple[str, ...], ...] = Field(min_length=1)
    files: tuple[SelectedDeliverableMaterial, ...] = Field(min_length=1)
    # 排版素材与语义资料是不同建模面：不进上传批次，由 runner 单独上传（与 v2 同一约束）。
    layoutAssetRootRelative: str | None = None
    layoutAssets: tuple["SelectedLayoutAsset", ...] = ()

    @model_validator(mode="after")
    def _validate_selection_integrity(
        self,
    ) -> "LocalE2EDeliverableSelectionManifest":
        if len(self.files) != self.selectedFileCount:
            raise ValueError("选择清单文件数必须与 selectedFileCount 一致")
        case_ids = [item.caseId for item in self.files]
        paths = [item.relativePath for item in self.files]
        hashes = [item.expectedSha256 for item in self.files]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("选择清单 caseId 不得重复")
        if len(set(paths)) != len(paths):
            raise ValueError("选择清单路径不得重复")
        if len(set(hashes)) != len(hashes):
            raise ValueError("选择清单不得包含内容重复文件")
        if [item.ordinal for item in self.files] != list(
            range(1, self.selectedFileCount + 1)
        ):
            raise ValueError("选择清单 ordinal 必须从 1 连续递增")
        flattened_batches = [
            case_id for batch in self.uploadBatches for case_id in batch
        ]
        if any(not 1 <= len(batch) <= 10 for batch in self.uploadBatches):
            raise ValueError("每个资料上传批次必须包含 1 至 10 个文件")
        if len(flattened_batches) != len(set(flattened_batches)):
            raise ValueError("同一选择项不得重复进入上传批次")
        if set(flattened_batches) != set(case_ids):
            raise ValueError("上传批次必须恰好覆盖全部选择项")
        for item in self.files:
            if any(
                segment in PurePosixPath(item.relativePath).parts
                for segment in self.excludedPathSegments
            ):
                raise ValueError(f"选择资料不得来自排除目录：{item.relativePath}")
        layout_case_ids = [item.caseId for item in self.layoutAssets]
        if set(layout_case_ids) & set(flattened_batches):
            raise ValueError("排版素材不进入语义资料上传批次，由 runner 单独上传")
        layout_paths = [item.relativePath for item in self.layoutAssets]
        layout_hashes = [item.expectedSha256 for item in self.layoutAssets]
        if len(set(layout_case_ids)) != len(layout_case_ids):
            raise ValueError("排版素材 caseId 不得重复")
        if len(set(layout_paths)) != len(layout_paths):
            raise ValueError("排版素材路径不得重复")
        if set(layout_hashes) & set(hashes) or len(set(layout_hashes)) != len(layout_hashes):
            raise ValueError("排版素材不得与任何选择项内容重复")
        if [item.ordinal for item in self.layoutAssets] != list(
            range(1, len(self.layoutAssets) + 1)
        ):
            raise ValueError("排版素材 ordinal 必须从 1 连续递增")
        if self.layoutAssets and not self.layoutAssetRootRelative:
            raise ValueError("声明排版素材时必须给出素材根目录")
        return self


LayoutAssetImageAnalysisExpectation = Literal["succeeded", "failed"]
_LAYOUT_ASSET_KINDS: frozenset[str] = frozenset({"png", "jpeg", "webp", "pdf"})


class SelectedLayoutAsset(LocalE2EContractModel):
    """一项排版素材及模拟用户提供的权威文件声明。

    排版素材与 15 文件语义清单是不同建模面：它不进 Mapping，只走
    Image Agent 识别→evidence_assets 提升→确定性放置链路；识别失败是
    受控分支（expectedImageAnalysis=failed），不阻断报告生成。
    """

    caseId: str = Field(pattern=r"^layout-\d{2}$")
    ordinal: int = Field(ge=1)
    relativePath: str = Field(min_length=1)
    selectionRationale: str = Field(min_length=1)
    expectedKind: Literal["png", "jpeg", "webp", "pdf"]
    expectedMediaType: str = Field(min_length=1)
    expectedSizeBytes: int = Field(gt=0)
    expectedSha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectedPdfPageCount: int | None = Field(default=None, ge=1)
    expectedImageAnalysis: LayoutAssetImageAnalysisExpectation
    # 省略表示不断言识别类别；声明时要求 Image Agent 落库的 category 恰好一致。
    expectedImageCategory: ImageAssetCategory | None = None
    declaration: UserFileDeclaration

    @model_validator(mode="after")
    def _validate_layout_selection(self) -> "SelectedLayoutAsset":
        path = PurePosixPath(self.relativePath)
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise ValueError("排版素材路径必须是素材根目录下的规范相对路径")
        if path.name != self.relativePath.split("/")[-1]:
            raise ValueError("排版素材路径必须使用 POSIX 分隔符")
        if self.expectedKind == "pdf":
            if self.expectedPdfPageCount != 1:
                raise ValueError("排版素材 PDF 必须恰好 1 页")
        elif self.expectedPdfPageCount is not None:
            raise ValueError("非 PDF 排版素材不得记录 PDF 页数")
        if self.declaration.role != "layout_asset":
            raise ValueError("排版素材声明必须使用 layout_asset 角色")
        if (
            self.expectedImageCategory is not None
            and self.expectedImageAnalysis != "succeeded"
        ):
            raise ValueError("只有预期识别成功的排版素材才能声明识别类别")
        return self


LocalE2EDeliverableSelectionManifest.model_rebuild()


class LocalE2ESelectionManifest(LocalE2EContractModel):
    """15 文件与排版素材选择预期；运行事实由后续 run manifest 单独记录。"""

    contract: Literal["sustainability_desk.local_e2e_selection_manifest.v2"]
    manifestId: str = Field(min_length=1)
    artifactPurpose: Literal["local_e2e_test"]
    corpusRootRelative: str = Field(min_length=1)
    selectionBasis: Literal["path_and_filename_only"]
    selectionPolicyVersion: str = Field(min_length=1)
    selectedFileCount: Literal[15]
    excludedPathSegments: tuple[str, ...] = ()
    uploadBatches: tuple[tuple[str, ...], ...] = Field(min_length=1)
    files: tuple[SelectedMaterial, ...] = Field(min_length=15, max_length=15)
    layoutAssetRootRelative: str | None = None
    layoutAssets: tuple[SelectedLayoutAsset, ...] = ()

    @model_validator(mode="after")
    def _validate_selection_integrity(self) -> "LocalE2ESelectionManifest":
        case_ids = [item.caseId for item in self.files]
        paths = [item.relativePath for item in self.files]
        hashes = [item.expectedSha256 for item in self.files]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("选择清单 caseId 不得重复")
        if len(set(paths)) != len(paths):
            raise ValueError("选择清单路径不得重复")
        if len(set(hashes)) != len(hashes):
            raise ValueError("选择清单不得包含内容重复文件")
        if [item.ordinal for item in self.files] != list(range(1, self.selectedFileCount + 1)):
            raise ValueError("选择清单 ordinal 必须从 1 连续递增")
        flattened_batches = [
            case_id for batch in self.uploadBatches for case_id in batch
        ]
        if any(not 1 <= len(batch) <= 10 for batch in self.uploadBatches):
            raise ValueError("每个资料上传批次必须包含 1 至 10 个文件")
        if len(flattened_batches) != len(set(flattened_batches)):
            raise ValueError("同一选择项不得重复进入上传批次")
        layout_case_ids = [item.caseId for item in self.layoutAssets]
        if set(layout_case_ids) & set(flattened_batches):
            raise ValueError("排版素材不进入语义资料上传批次，由 runner 单独上传")
        if set(flattened_batches) != set(case_ids):
            raise ValueError("上传批次必须恰好覆盖全部选择项")
        for item in self.files:
            if any(segment in PurePosixPath(item.relativePath).parts for segment in self.excludedPathSegments):
                raise ValueError(f"选择资料不得来自排除目录：{item.relativePath}")
        layout_paths = [item.relativePath for item in self.layoutAssets]
        layout_hashes = [item.expectedSha256 for item in self.layoutAssets]
        if len(set(layout_case_ids)) != len(layout_case_ids):
            raise ValueError("排版素材 caseId 不得重复")
        if len(set(layout_paths)) != len(layout_paths):
            raise ValueError("排版素材路径不得重复")
        if set(layout_hashes) & set(hashes) or len(set(layout_hashes)) != len(layout_hashes):
            raise ValueError("排版素材不得与任何选择项内容重复")
        if [item.ordinal for item in self.layoutAssets] != list(
            range(1, len(self.layoutAssets) + 1)
        ):
            raise ValueError("排版素材 ordinal 必须从 1 连续递增")
        if self.layoutAssets and not self.layoutAssetRootRelative:
            raise ValueError("声明排版素材时必须给出素材根目录")
        return self


class LocalE2EFixtureRecipe(LocalE2EContractModel):
    """测试元数据加正式输入操作；业务值仍由现有 owner 解析和持久化。"""

    contract: Literal["sustainability_desk.local_e2e_report_input_fixture.v1"]
    fixtureId: str = Field(min_length=1)
    artifactPurpose: Literal["local_e2e_test", "customer_deliverable_rehearsal"]
    fixtureBasis: Literal["simulated_for_local_e2e", "customer_provided_materials"]
    # The report Profile the synthetic report is created on; every key below is bound to its package.
    reportProfileId: str = Field(pattern=r"^[a-z_]+@[1-9][0-9]*$")
    corpusId: str = Field(min_length=1)
    reportingEntity: str = Field(min_length=1, max_length=300)
    reportingYear: int = Field(ge=2000, le=2100)
    consolidationScope: str = Field(min_length=1, max_length=1_000)
    assessmentScores: dict[str, "LocalE2EMaterialityScore"] = Field(min_length=1)
    greenhouseGasAccountingStandard: str = Field(min_length=1)
    inputWrites: tuple[InputWrite, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_write_keys_are_unique(self) -> "LocalE2EFixtureRecipe":
        keys = [write.target_key for write in self.inputWrites]
        if len(keys) != len(set(keys)):
            raise ValueError("本地验收 fixture 不得重复写入同一目标题")
        return self

    @property
    def knowledge_package(self) -> KnowledgePackage:
        return knowledge_package_for_profile(self.reportProfileId)


class LocalE2EMaterialityScore(LocalE2EContractModel):
    """本地验收评分表的一行合成输入；实际校验仍由正式评分表解析执行。"""

    financialScore: float = Field(gt=0, le=5)
    impactScore: float = Field(gt=0, le=5)


@dataclass(frozen=True)
class VerifiedSelectedMaterial:
    """选择预期与正式文件门禁观察值的成对结果。"""

    selection: "SelectedMaterial | SelectedDeliverableMaterial"
    absolute_path: Path
    validated: ValidatedMaterialFile


@dataclass(frozen=True)
class VerifiedSelectedLayoutAsset:
    """排版素材预期与正式文件门禁观察值的成对结果。"""

    selection: SelectedLayoutAsset
    absolute_path: Path
    validated: ValidatedMaterialFile


@dataclass(frozen=True)
class LocalE2EStructuredInputArtifacts:
    """同一次正式工作簿 round-trip 形成的状态与可审阅输入文件。"""

    state: StoredReportStateV4
    assessment_workbook: bytes
    quantitative_workbook: bytes


def _load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_local_e2e_selection_manifest(
    path: Path = DEFAULT_SELECTION_MANIFEST_PATH,
) -> "LocalE2ESelectionManifest | LocalE2EDeliverableSelectionManifest":
    """按 contract 字段严格解析选择清单（v2 验收清单或 v3 交付演练清单）。"""
    raw = _load_yaml(path)
    if (
        isinstance(raw, dict)
        and raw.get("contract") == "sustainability_desk.local_e2e_selection_manifest.v3"
    ):
        return LocalE2EDeliverableSelectionManifest.model_validate(raw)
    return LocalE2ESelectionManifest.model_validate(raw)


def load_local_e2e_fixture_recipe(
    path: Path = DEFAULT_INPUT_FIXTURE_PATH,
) -> LocalE2EFixtureRecipe:
    """严格解析带用途标签的正式输入操作 fixture。"""
    return LocalE2EFixtureRecipe.model_validate(_load_yaml(path))


def verify_selected_materials(
    manifest: "LocalE2ESelectionManifest | LocalE2EDeliverableSelectionManifest",
    *,
    package: KnowledgePackage,
    repository_root: Path = _REPOSITORY_ROOT,
) -> tuple[VerifiedSelectedMaterial, ...]:
    """以正式准入门禁复核选择项的路径、类型、大小、页数和内容指纹。"""
    from sustainability_desk.material.workspace import (
        MaterialWorkspaceService,
    )

    corpus_root = (repository_root / manifest.corpusRootRelative).resolve()
    expected_root = repository_root.resolve()
    if not corpus_root.is_relative_to(expected_root):
        raise ValueError("corpus 根目录不得越出仓库")

    verified: list[VerifiedSelectedMaterial] = []
    observed_hashes: set[str] = set()
    for selection in manifest.files:
        absolute_path = (corpus_root / selection.relativePath).resolve()
        if not absolute_path.is_relative_to(corpus_root):
            raise ValueError(f"选择资料路径越出 corpus：{selection.relativePath}")
        if not absolute_path.is_file():
            raise ValueError(f"选择资料不存在：{selection.relativePath}")
        data = absolute_path.read_bytes()
        validated = validate_material_file(
            filename=absolute_path.name,
            content_type=selection.expectedMediaType,
            data=data,
        )
        MaterialWorkspaceService.validate_report_file_declaration_for_policy(
            selection.declaration,
            validated,
            MaterialWorkspaceService.report_file_ingress_policy(package),
        )
        observed = {
            "kind": validated.kind,
            "media_type": validated.media_type,
            "size_bytes": validated.size_bytes,
            "sha256": validated.sha256,
            "pdf_page_count": validated.pdf_page_count,
        }
        expected = {
            "kind": selection.expectedKind,
            "media_type": selection.expectedMediaType,
            "size_bytes": selection.expectedSizeBytes,
            "sha256": selection.expectedSha256,
            "pdf_page_count": selection.expectedPdfPageCount,
        }
        if observed["sha256"] != expected["sha256"]:
            raise ValueError(f"选择资料 SHA-256 漂移：{selection.relativePath}")
        if observed != expected:
            raise ValueError(
                f"选择资料准入事实漂移：{selection.relativePath}；"
                f"expected={expected!r}；observed={observed!r}"
            )
        if validated.sha256 in observed_hashes:
            raise ValueError(f"选择资料出现重复内容：{selection.relativePath}")
        observed_hashes.add(validated.sha256)
        verified.append(
            VerifiedSelectedMaterial(
                selection=selection,
                absolute_path=absolute_path,
                validated=validated,
            )
        )
    return tuple(verified)


def verify_selected_layout_assets(
    manifest: "LocalE2ESelectionManifest | LocalE2EDeliverableSelectionManifest",
    *,
    package: KnowledgePackage,
    repository_root: Path = _REPOSITORY_ROOT,
) -> tuple[VerifiedSelectedLayoutAsset, ...]:
    """以正式准入门禁复核排版素材的路径、类型、大小和内容指纹。

    坏图字节（合法图片 magic 但内容损坏）按产品语义应当通过上传准入，
    在 Image Agent 解码阶段才失败；因此这里只复核准入事实，不做像素解码。
    v3 交付演练清单把排版素材并入 files 随语义批次上传，不携带独立
    layoutAssets 段，此处返回空集。
    """
    from sustainability_desk.material.workspace import (
        MaterialWorkspaceService,
    )

    if not getattr(manifest, "layoutAssets", None):
        return ()
    if manifest.layoutAssetRootRelative is None:
        raise ValueError("排版素材清单缺少素材根目录")
    asset_root = (repository_root / manifest.layoutAssetRootRelative).resolve()
    if not asset_root.is_relative_to(repository_root.resolve()):
        raise ValueError("排版素材根目录不得越出仓库")

    verified: list[VerifiedSelectedLayoutAsset] = []
    observed_hashes: set[str] = set()
    for selection in manifest.layoutAssets:
        absolute_path = (asset_root / selection.relativePath).resolve()
        if not absolute_path.is_relative_to(asset_root):
            raise ValueError(f"排版素材路径越出素材根目录：{selection.relativePath}")
        if not absolute_path.is_file():
            raise ValueError(f"排版素材不存在：{selection.relativePath}")
        data = absolute_path.read_bytes()
        validated = validate_material_file(
            filename=absolute_path.name,
            content_type=selection.expectedMediaType,
            data=data,
        )
        MaterialWorkspaceService.validate_report_file_declaration_for_policy(
            selection.declaration,
            validated,
            MaterialWorkspaceService.report_file_ingress_policy(package),
        )
        observed = {
            "kind": validated.kind,
            "media_type": validated.media_type,
            "size_bytes": validated.size_bytes,
            "sha256": validated.sha256,
            "pdf_page_count": validated.pdf_page_count,
        }
        expected = {
            "kind": selection.expectedKind,
            "media_type": selection.expectedMediaType,
            "size_bytes": selection.expectedSizeBytes,
            "sha256": selection.expectedSha256,
            "pdf_page_count": selection.expectedPdfPageCount,
        }
        if observed != expected:
            raise ValueError(
                f"排版素材准入事实漂移：{selection.relativePath}；"
                f"expected={expected!r}；observed={observed!r}"
            )
        if validated.sha256 in observed_hashes:
            raise ValueError(f"排版素材出现重复内容：{selection.relativePath}")
        observed_hashes.add(validated.sha256)
        verified.append(
            VerifiedSelectedLayoutAsset(
                selection=selection,
                absolute_path=absolute_path,
                validated=validated,
            )
        )
    return tuple(verified)


def synthesize_company_inputs(recipe: LocalE2EFixtureRecipe) -> CompanyInputs:
    """经正式写入、评分工作簿 round-trip 和冻结边界合成 CompanyInputs。"""
    state = synthesize_stored_report_state(recipe)
    inputs = company_inputs_from_stored_state(state, package=recipe.knowledge_package)
    report = build_report(inputs)
    if report.assessmentInput != inputs.assessmentInput:
        raise ValueError("重要性信息未按 CompanyInputs 原样进入 Report.assessmentInput")
    if report.meta.quantitativeMetrics != inputs.quantitativeMetrics:
        raise ValueError("定量信息未按 CompanyInputs 原样进入 Report.meta.quantitativeMetrics")
    return inputs


def synthesize_stored_report_state(
    recipe: LocalE2EFixtureRecipe,
    *,
    report_id: UUID = _FIXTURE_REPORT_ID,
) -> StoredReportStateV4:
    """合成经正式工作簿 round-trip 验证的 StoredReportStateV4。"""

    return synthesize_structured_input_artifacts(
        recipe,
        report_id=report_id,
    ).state


def synthesize_structured_input_artifacts(
    recipe: LocalE2EFixtureRecipe,
    *,
    report_id: UUID = _FIXTURE_REPORT_ID,
) -> LocalE2EStructuredInputArtifacts:
    """把 fixture 作为正式 InputWrite 应用，再经官方评分表生成与解析补入评分。"""

    package = recipe.knowledge_package
    adapter = LightweightReportInputAdapter(package)
    initial_state = empty_stored_report_state().model_dump(by_alias=True, mode="json")
    initial_state["fields"] = {
        "company_registered_name": recipe.reportingEntity,
        "reporting_year": recipe.reportingYear,
        "report_period_start": f"{recipe.reportingYear}-01-01",
        "report_period_end": f"{recipe.reportingYear}-12-31",
        "consolidation_scope": recipe.consolidationScope,
    }
    report_contract = load_package_contract(package)
    if report_contract.disclosureProfile is None:
        raise ValueError("本地 E2E 报告合同缺少轻量版披露配置")
    initial_state["disclosureProfile"] = report_contract.disclosureProfile.model_dump(
        by_alias=True,
        mode="json",
    )
    initial_state["appendixPackage"] = report_contract.appendixPackage.model_dump(
        by_alias=True,
        mode="json",
    ) if report_contract.appendixPackage is not None else None
    raw_state = adapter.apply_automatic(
        initial_state,
        list(recipe.inputWrites),
    )
    meta = raw_state.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("定量 InputWrite 未创建 Report.meta")
    quantitative = meta.get("quantitativeMetrics")
    if not isinstance(quantitative, dict):
        raise ValueError("定量 InputWrite 未创建 Report.meta.quantitativeMetrics")
    provisional = StoredReportStateV4.model_validate(raw_state)
    assessment_context = _build_assessment_context(provisional, package)
    structured_input_context = StructuredInputContext(
        reportId=report_id,
        contractVersion=contract_version(package),
        compiledSemanticsVersion=COMPILED_SEMANTICS_VERSION,
    )
    assessment_workbook = _fill_scoring_template(
        create_scoring_template(
            assessment_context,
            context=structured_input_context,
        ),
        scores=recipe.assessmentScores,
        expected_topic_ids={
            topic.id for topic in applicable_scoring_topics(assessment_context)
        },
        package=package,
    )
    parsed = parse_scoring(
        assessment_workbook,
        report=assessment_context,
        context=structured_input_context,
    )
    quantitative_workbook = openpyxl.load_workbook(
        BytesIO(
            create_quantitative_template(
                assessment_context,
                context=structured_input_context,
            )
        )
    )
    quantitative_workbook[QUANTITATIVE_CONFIG_SHEET][GHG_STANDARD_CELL] = (
        recipe.greenhouseGasAccountingStandard
    )
    partial_metrics = quantitative.get("metrics") or {}
    for worksheet in quantitative_workbook.worksheets:
        if worksheet.title not in quantitative_metric_sheets(package):
            continue
        for row in range(QUANTITATIVE_HEADER_ROW + 1, worksheet.max_row + 1):
            key = worksheet.cell(row, 1).value
            if not isinstance(key, str):
                continue
            draft = partial_metrics.get(key)
            if isinstance(draft, dict) and draft.get("value") is not None:
                worksheet.cell(row, 5, draft["value"])
                worksheet.cell(row, 7, draft.get("department"))
                worksheet.cell(row, 8, draft.get("note"))
            else:
                worksheet.cell(row, 6, "not_collected")
    quantitative_stream = BytesIO()
    quantitative_workbook.save(quantitative_stream)
    quantitative_workbook_bytes = quantitative_stream.getvalue()
    parsed_quantitative = parse_quantitative_workbook(
        quantitative_workbook_bytes,
        report=assessment_context,
        context=structured_input_context,
    )
    reporting_year = provisional.fields.get("reporting_year")
    if not isinstance(reporting_year, int):
        raise ValueError("本地验收 fixture 缺少整数 reporting_year")
    raw_state["assessmentInput"] = MaterialityAssessmentInput(
        reportingYear=reporting_year,
        threshold=DEFAULT_THRESHOLD,
        scores=[
            MaterialityScoreInput(
                assessmentTopicId=item.assessmentTopicId,
                financialScore=item.financialScore,
                impactScore=item.impactScore,
            )
            for item in parsed.scored
        ],
    ).model_dump(mode="json")
    raw_state["meta"] = {
        "quantitativeMetrics": parsed_quantitative.model_dump(mode="json"),
        "materialityStrategy": None,
    }
    raw_state["structuredInputFreshness"] = {
        "assessmentContextFingerprint": parsed.context_fingerprint,
        "quantitativeMetricsContextFingerprint": (
            quantitative_metrics_context_fingerprint(
                assessment_context,
                structured_input_context,
            )
        ),
    }
    # 利益相关方沟通档案在产品流中由工作台首访经 reconcile 落库;headless fixture 用
    # 同一生产函数与默认映射合成,否则导出闸的"议题未分配沟通对象"诊断必然阻断交付。
    synthesized = StoredReportStateV4.model_validate(raw_state)
    raw_state["stakeholderEngagement"] = reconcile_stakeholder_engagement_profile(
        build_report_revision(synthesized, package=package)
    ).model_dump(mode="json", by_alias=True)
    return LocalE2EStructuredInputArtifacts(
        state=StoredReportStateV4.model_validate(raw_state),
        assessment_workbook=assessment_workbook,
        quantitative_workbook=quantitative_workbook_bytes,
    )


def _build_assessment_context(state: StoredReportStateV4, package: KnowledgePackage):
    """从已写入的正式状态构建仅用于模板适用性判定的 Report。"""
    profile_item = state.intakeItems.get("company_profile")
    company_profile = profile_item.answer if profile_item is not None else ""
    if not isinstance(company_profile, str):
        raise ValueError("公司简介 fixture 必须为文本")
    return build_report(
        CompanyInputs(
            knowledgePackageId=package.id,
            fields=dict(state.fields),
            company_profile=company_profile,
            disclosureProfile=state.disclosureProfile,
            appendixPackage=state.appendixPackage,
            quantitativeMetrics=(
                state.meta.quantitativeMetrics if state.meta is not None else None
            ),
            materialityStrategy="complete_coverage",
        )
    )


def _fill_scoring_template(
    content: bytes,
    *,
    scores: dict[str, LocalE2EMaterialityScore],
    expected_topic_ids: set[str],
    package: KnowledgePackage,
) -> bytes:
    """把合成评分逐项写入官方动态模板，拒绝缺项、冗余项和统一默认值。"""
    if set(scores) != expected_topic_ids:
        missing = sorted(expected_topic_ids - set(scores))
        extra = sorted(set(scores) - expected_topic_ids)
        raise ValueError(f"评分 fixture 与当前适用议题不一致：missing={missing} extra={extra}")
    workbook = openpyxl.load_workbook(BytesIO(content))
    worksheet = workbook["重要性评分表"]
    written_topic_ids: set[str] = set()
    for row in range(1, worksheet.max_row + 1):
        label_value = worksheet.cell(row, 1).value
        if not isinstance(label_value, str):
            continue
        topic = resolve_topic(package, label_value.strip())
        if topic is not None and topic.materialityDetermination.kind == "scored":
            score = scores.get(topic.id)
            if score is None:
                raise ValueError(f"评分 fixture 缺少适用议题：{topic.id}")
            worksheet.cell(row, 2, score.financialScore)
            worksheet.cell(row, 3, score.impactScore)
            written_topic_ids.add(topic.id)
    if written_topic_ids != expected_topic_ids:
        raise ValueError("官方评分表的适用议题与 fixture 评分范围不一致")
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()
