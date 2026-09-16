# ABOUTME(en): Knowledge package registry — one self-contained directory of authoring data per
# ABOUTME(en): standards framework × language. Every loader resolves its files through a package;
# ABOUTME(en): there is no default package and no global data root.
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sustainability_desk.contract.language import Language
from sustainability_desk.contract.models import Pillar, Report

BACKEND = Path(__file__).resolve().parents[3]
KNOWLEDGE_PACKAGES_ROOT = BACKEND / "data" / "knowledge_packages"
MANIFEST_FILE_NAME = "package.yaml"

Framework = Literal["sse_sustainability_guidelines", "hkex_esg_reporting_code", "gri_standards"]
MainlandStandard = Literal["sse", "szse", "bse"]

# How a standard decides which topics are material. This is a property of the standard, not of what the
# account is entitled to, so it lives on the package manifest and drives whether the scoring step exists.
#
# - "double": the user scores every applicable topic on both axes (impact and financial). SSE and ESRS.
# - "financial_primary": the financial axis only. HKEX's Code treats materiality as what the board judges
#   important to investors and names double materiality as something issuers *may* also refer to; ISSB is
#   the same shape.
# - "impact_primary": the impact axis only — the mirror of the above. GRI 3 judges significance from the
#   organisation's impacts on the economy, environment and people, with no financial dimension.
# - "applicability": no scoring at all — each disclosure is reported when it applies to the undertaking.
#   VSME works this way, which is why EFRAG excludes it from IG 1 (the double materiality guidance).
#
# The single-axis regimes still classify into the same Materiality vocabulary; they simply never produce
# "dual", and their matrix has one dimension to plot rather than two.
MaterialityRegime = Literal["double", "financial_primary", "impact_primary", "applicability"]


class PillarTitles(BaseModel):
    """Display titles of the four topic-chapter pillars in the package language."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    governance: str = Field(min_length=1)
    strategy: str = Field(min_length=1)
    iro_management: str = Field(min_length=1)
    metrics_targets: str = Field(min_length=1)

    def title(self, pillar: Pillar) -> str:
        return getattr(self, pillar)


class MainlandStandardNames(BaseModel):
    """Display names of the three mainland exchange guidelines, keyed by the DisclosureProfile code."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sse: str = Field(min_length=1)
    szse: str = Field(min_length=1)
    bse: str = Field(min_length=1)

    def name(self, standard: MainlandStandard) -> str:
        return getattr(self, standard)

    def by_code(self) -> dict[str, str]:
        return self.model_dump()


class DisclosureBasis(BaseModel):
    """Which standards a report of this package declares as its preparation basis.

    A package either lets the user pick one mainland standard (SSE/SZSE/BSE, optionally adding the
    HKEX guide) or names its standards outright; the two shapes are mutually exclusive.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    mainland_standard_selectable: bool
    primary_standard_names: tuple[str, ...] = ()
    mainland_standard_names: MainlandStandardNames | None = None
    hong_kong_guide_name: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> DisclosureBasis:
        if self.mainland_standard_selectable:
            if self.mainland_standard_names is None or not self.hong_kong_guide_name:
                raise ValueError(
                    "a selectable mainland basis must name sse, szse, bse and the Hong Kong guide"
                )
            if self.primary_standard_names:
                raise ValueError("a selectable mainland basis does not declare primary_standard_names")
        else:
            if not self.primary_standard_names:
                raise ValueError("a fixed disclosure basis must declare primary_standard_names")
            if self.mainland_standard_names is not None or self.hong_kong_guide_name is not None:
                raise ValueError("a fixed disclosure basis carries no mainland standard names")
        return self


class KnowledgePackageManifest(BaseModel):
    """Identity of a knowledge package; content files live beside the manifest under fixed names."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["sustainability_desk.knowledge_package.v1"]
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    language: Language
    framework: Framework
    display_name: str = Field(min_length=1, max_length=200)
    pillar_titles: PillarTitles
    disclosure_basis: DisclosureBasis
    # Deliberately has no default: how a standard decides materiality is the first thing to settle when
    # authoring a package, and inheriting "double" silently would put a scoring step in front of users
    # whose standard never asked for one.
    materiality_regime: MaterialityRegime
    # 封存包：内容留在仓库并继续受编译审计守护（防其悄悄烂掉），但不绑定 report profile，
    # 建报时不可选。用于「暂不推进但不想丢弃」的知识包，与「删除」和「在售」都不同。
    sealed: bool = False


class KnowledgePackage(BaseModel):
    """A loaded package: manifest plus the resolved paths of its authoring files."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    root: Path
    manifest: KnowledgePackageManifest

    @property
    def language(self) -> Language:
        return self.manifest.language

    @property
    def report_contract_path(self) -> Path:
        return self.root / "report_contract.yaml"

    @property
    def topic_registry_path(self) -> Path:
        return self.root / "topic_registry.yaml"

    @property
    def topic_intake_common_path(self) -> Path:
        return self.root / "topic_intake_common.yaml"

    @property
    def topic_intake_dir(self) -> Path:
        return self.root / "topic_intake"

    @property
    def topic_sections_dir(self) -> Path:
        return self.root / "topic_sections"

    @property
    def standard_disclosure_requirements_dir(self) -> Path:
        return self.root / "standard_disclosure_requirements"

    @property
    def requirement_coverage_path(self) -> Path:
        return self.root / "standard_disclosure_requirement_coverage.yaml"

    @property
    def report_level_obligations_path(self) -> Path:
        return self.root / "report_level_disclosure_obligations.yaml"

    @property
    def disclosure_standards_index_path(self) -> Path:
        return self.root / "disclosure_standards_index.yaml"

    @property
    def clause_annotations_path(self) -> Path:
        return self.root / "user_visible_disclosure_clause_annotations.yaml"

    @property
    def stakeholder_engagement_path(self) -> Path:
        return self.root / "stakeholder_engagement.yaml"

    @property
    def quantitative_metrics_path(self) -> Path:
        return self.root / "quantitative_metrics.json"

    @property
    def prompt_profile_path(self) -> Path:
        return self.root / "prompt_profile.yaml"

    @property
    def format_profile_path(self) -> Path:
        return self.root / "format_profile.yaml"

    @property
    def sample_values_path(self) -> Path:
        return self.root / "sample_values.yaml"

    @property
    def base_template_path(self) -> Path:
        return self.root / "export" / "base_template.docx"

    def authoring_files(self) -> tuple[Path, ...]:
        """Every authored YAML/JSON file of the package in a stable order; generated artifacts excluded."""

        return tuple(
            sorted(
                path
                for pattern in ("*.yaml", "*.json")
                for path in self.root.rglob(pattern)
                if "export" not in path.relative_to(self.root).parts
            )
        )


class UnknownKnowledgePackageError(ValueError):
    """The requested package id has no directory under the packages root."""


def all_knowledge_package_ids() -> tuple[str, ...]:
    return tuple(
        sorted(
            path.name
            for path in KNOWLEDGE_PACKAGES_ROOT.iterdir()
            if path.is_dir() and (path / MANIFEST_FILE_NAME).is_file()
        )
    )


@lru_cache(maxsize=None)
def load_knowledge_package(package_id: str) -> KnowledgePackage:
    root = KNOWLEDGE_PACKAGES_ROOT / package_id
    manifest_path = root / MANIFEST_FILE_NAME
    if not manifest_path.is_file():
        raise UnknownKnowledgePackageError(package_id)
    manifest = KnowledgePackageManifest.model_validate(
        yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    )
    if manifest.id != package_id:
        raise ValueError(
            f"knowledge package manifest id {manifest.id!r} does not match directory {package_id!r}"
        )
    return KnowledgePackage(id=package_id, root=root, manifest=manifest)


def knowledge_package_of(report: Report) -> KnowledgePackage:
    """Resolve the package a Report was built from; a Report without one cannot resolve topics."""

    if report.knowledgePackageId is None:
        raise ValueError("Report is not bound to a knowledge package")
    return load_knowledge_package(report.knowledgePackageId)


def bind_knowledge_package(
    report: Report, package: KnowledgePackage, *, validate_references: bool = True
) -> Report:
    """Stamp the authoritative package onto a client-supplied Report and run package-scoped checks.

    包身份由服务端从 `reports.report_profile_id` 解析，客户端从不决定；客户端投影
    （`frontend/public/contract.json`）是单包静态快照，刻意不带 `knowledgePackageId`。

    为什么必须在这里重新校验：`model_copy` 在 pydantic v2 下**不重跑**验证器，
    而 `Report._validate_stakeholder_engagement` 在未绑定包时按设计跳过。二者叠加，
    只 `model_copy` 会让绑定后的报告完全失去引用校验（未知沟通方式将一路进正文）。
    故绑定与校验在此合为一个动作，调用方不必各自记得补一次。

    `validate_references=False` 留给**只借用该包某一份目录、不主张报告归属该包**的调用
    （如指标摘要预览图：它按调用方指名的 Profile 取指标目录，而 Report 可能来自另一个包）。
    此时做跨包引用校验必然误报——用港交所目录去核对上交所议题，没有一条对得上。
    """

    bound = report.model_copy(update={"knowledgePackageId": package.id})
    if validate_references and bound.stakeholderEngagement is not None:
        from sustainability_desk.contract.stakeholder_engagement import (
            validate_stakeholder_engagement_profile,
        )

        validate_stakeholder_engagement_profile(
            bound.stakeholderEngagement, package=package
        )
    return bound


def knowledge_package_id_for_path(path: Path) -> str | None:
    """The package a file belongs to by location, or None when it lives outside the packages root."""

    resolved = path.resolve()
    root = KNOWLEDGE_PACKAGES_ROOT.resolve()
    if not resolved.is_relative_to(root):
        return None
    parts = resolved.relative_to(root).parts
    return parts[0] if len(parts) > 1 else None


def knowledge_package_for_path(path: Path) -> KnowledgePackage:
    package_id = knowledge_package_id_for_path(path)
    if package_id is None:
        raise ValueError(f"{path} does not belong to a knowledge package")
    return load_knowledge_package(package_id)
