# ABOUTME: 定义排版素材图片识别 Agent 的任务、识别档案(题注/替代文本/归属范围/类别)与运行收据合同。
# ABOUTME: ImageDossier 只承载单图识别结论;素材一律以原图进报告,放置排位与渲染由代码侧确定性完成。
# ABOUTME(en): Defines the layout-asset image Agent contract: task, recognition profile and run receipt.
# ABOUTME(en): An ImageDossier holds single-image conclusions; assets enter the report as originals, placed in code.
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sustainability_desk.material.intake.file_agent_contract import (
    SHA256_PATTERN,
    AttentionItem,
    AttentionItemDraft,
    FileMaterialScope,
    FileSourceRevision,
)
from sustainability_desk.llm.provider_output import parse_stringified_json
from sustainability_desk.material.intake.models import MaterialKind, UserFileDeclaration

# 类别是素材归档与人工核对的可读事实；`certificate_or_award` 另触发证书事实解析
# （见 CertificateFact），其余取值不驱动生成分支，因此不区分图形形态。
type ImageAssetCategory = Literal[
    "certificate_or_award",  # 证书/奖项/资质；触发 certificate_fact 解析
    "photo",  # 活动/现场/产品照片
    "document_scan",  # 文档扫描或截图
    "other",
]
type ImageAgentRunStatus = Literal["completed", "failed"]


class ImageAgentContractModel(BaseModel):
    """图片识别 Agent 跨层合同的严格不可变基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ImageAgentProductTask(ImageAgentContractModel):
    """单图识别所需的最小产品任务;scope 目录只含拥有素材承载位的报告范围。"""

    objective: Literal[
        "理解当前排版素材图片，形成其进入报告所需的题注、替代文本与归属范围"
    ] = "理解当前排版素材图片，形成其进入报告所需的题注、替代文本与归属范围"
    report_id: UUID
    report_subject_name: str | None = Field(default=None, min_length=1, max_length=300)
    report_period_label: str | None = Field(default=None, min_length=1, max_length=100)
    scope_label: str = Field(default="轻量版完整路径 ESG 报告", min_length=1, max_length=100)
    material_scopes: tuple[FileMaterialScope, ...] = Field(min_length=1)


class ImageAgentContext(ImageAgentContractModel):
    """模型可见的单图任务边界;像素尺寸由代码侧读取,供审计与降采样判断。"""

    source_revision: FileSourceRevision
    filename: str = Field(min_length=1, max_length=500)
    material_kind: MaterialKind
    size_bytes: int = Field(gt=0)
    image_width_px: int | None = Field(default=None, gt=0)
    image_height_px: int | None = Field(default=None, gt=0)
    declaration: UserFileDeclaration
    product_task: ImageAgentProductTask


class CertificateFact(ImageAgentContractModel):
    """一张资质证书在入口被解析出的领域事实；下游直接消费，不需再读图。

    这是 parse-first 边界：证书图片的可披露内容在识别阶段一次性解析为 typed 字段，
    而不是留在自由文本 summary 里等下游正则或再次读图。字段取自证书正面的稳定要素。

    **字段以终为始**：只读报告真会用到的内容。不读标准号、生效日期与有效期截止日：
    标准号从不进交付稿（读它只是为了给去重当键，属实现细节泄漏进模型任务）；
    有效期则是多此一举的判断：用户主动上传的证书默认视为有效，
    与「用户上传即声明为报告主体自有或经授权使用」的既有归属推定同源，系统没有立场
    替用户判定他的证书过没过期。

    `unreadable_fields` 是 fail-loud 的表达方式：任何字段辨认不出即留空并在此登记，
    不猜测、不用相近内容顶替。实测（qwen3.7-plus）：清晰证书各字段全对；
    高斯模糊后模型如实把全部字段登记为不可辨认，不编造。
    """

    # 证书名允许为空：图片模糊到连标题都读不出时，必须能如实登记为
    # 不可辨认，而不是逼模型编一个名字。是否可用由 unreadable_fields 与下游判定。
    certificate_name: str = Field(default="", max_length=120)
    # 表格「颁发机构」列；正文体裁另有「不写发证机构」的规则，两者是不同呈现面。
    issuer: str | None = Field(default=None, max_length=120)
    # 集中承载于成果章表格，使议题正文不再复述这串产品与业务范围。
    covered_scope: str | None = Field(default=None, max_length=600)
    # 持证主体不是报告主体时，正文必须写明（见 report_body_contract）。
    holder_name: str | None = Field(default=None, max_length=120)
    unreadable_fields: tuple[str, ...] = ()


class ImageDossierDraft(ImageAgentContractModel):
    """模型提交的单图识别结论;scope alias 只在本次运行有效。"""

    contract: Literal["sustainability_desk.image_dossier_draft.v1"] = (
        "sustainability_desk.image_dossier_draft.v1"
    )
    summary: str = Field(min_length=1, max_length=600)
    category: ImageAssetCategory
    caption: str = Field(min_length=1, max_length=50)
    alt_text: str = Field(min_length=1, max_length=300)
    scope_alias: str = Field(min_length=1, max_length=100)
    placement_reason: str = Field(min_length=1, max_length=300)
    certificate_fact: CertificateFact | None = None
    attention_items: tuple[AttentionItemDraft, ...] = ()

    @field_validator("certificate_fact", "attention_items", mode="before")
    @classmethod
    def _parse_stringified_structure(cls, value: object) -> object:
        """还原被模型序列化成 JSON 字符串的嵌套对象与数组。

        还原本身由 llm/provider_output.parse_stringified_json 承担（三条调用路径共用，
        同一 provider 行为不维护三份实现）。certificate_fact 与 attention_items 都会中招，
        字段内容全对但外层是 str，输出重试无效。在合同边界解析，解析后仍走同一结构校验，
        不放宽字段类型、不让下游各自兼容。

        字符串本身就是坏 JSON 时（实测模糊证书图：模型在 message 里写了未转义的内层引号）
        原样返回，让结构校验按既有路径失败。该失败不阻断生成——图片识别失败时整块跳过放置、
        界面显示「资料暂不可用」（design.md §3.4），这正是模糊素材应得的处置。
        """

        if not isinstance(value, str):
            return value
        text = value.strip()
        parsed = parse_stringified_json(text)
        if not isinstance(parsed, str):
            return parsed
        # 共用实现只做「合法 JSON 字符串」的还原，畸形 JSON 的修复是本路径独有的：
        # 中文正文里带引号时，模型序列化出的字符串内层引号未转义，整串因此不是合法 JSON
        # （如 message 里写了「图片底部注明"…"」）。逐字符扫描，把处于
        # 字符串值内部、且后面不是 JSON 结构符的引号转义后重试；仍失败则原样返回，
        # 由结构校验按既有路径失败——不猜内容、不吞掉这条告警。
        repaired: list[str] = []
        in_string = False
        for index, char in enumerate(text):
            if char == '"':
                following = text[index + 1 :].lstrip()
                closes = following[:1] in {",", ":", "}", "]", ""}
                if in_string and not closes:
                    repaired.append('\\"')
                    continue
                in_string = not in_string
            repaired.append(char)
        try:
            return json.loads("".join(repaired))
        except json.JSONDecodeError:
            return value

    @model_validator(mode="after")
    def _validate_certificate_fact(self) -> "ImageDossierDraft":
        """证书类图片必须给出证书事实；非证书类不得夹带。

        条件必填放在合同层而非提示词：模型漏解析时在边界失败并触发重试，
        不让一张证书静默退化成只有题注的配图。
        """

        if self.category == "certificate_or_award" and self.certificate_fact is None:
            raise ValueError("category 为 certificate_or_award 时必须给出 certificate_fact")
        if self.category != "certificate_or_award" and self.certificate_fact is not None:
            raise ValueError("只有 certificate_or_award 才可携带 certificate_fact")
        return self


class ImageDossier(ImageAgentContractModel):
    """一份冻结图片素材的识别档案;题注与替代文本以此为 owner 源。"""

    contract: Literal["sustainability_desk.image_dossier.v1"] = "sustainability_desk.image_dossier.v1"
    dossier_id: UUID = Field(default_factory=uuid4)
    source_revision: FileSourceRevision
    summary: str = Field(min_length=1, max_length=600)
    category: ImageAssetCategory
    caption: str = Field(min_length=1, max_length=50)
    alt_text: str = Field(min_length=1, max_length=300)
    scope_id: str = Field(min_length=1)
    placement_reason: str = Field(min_length=1, max_length=300)
    certificate_fact: CertificateFact | None = None
    attention_items: tuple[AttentionItem, ...] = ()
    dossier_fingerprint: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_dossier(self) -> "ImageDossier":
        expected = image_dossier_fingerprint(
            source_revision=self.source_revision,
            summary=self.summary,
            category=self.category,
            caption=self.caption,
            alt_text=self.alt_text,
            scope_id=self.scope_id,
            placement_reason=self.placement_reason,
            certificate_fact=self.certificate_fact,
            attention_items=self.attention_items,
        )
        if self.dossier_fingerprint != expected:
            raise ValueError("ImageDossier 内容指纹无效")
        return self


def image_dossier_fingerprint(
    *,
    source_revision: FileSourceRevision,
    summary: str,
    category: ImageAssetCategory,
    caption: str,
    alt_text: str,
    scope_id: str,
    placement_reason: str,
    certificate_fact: "CertificateFact | None" = None,
    attention_items: tuple[AttentionItem, ...],
) -> str:
    """生成不依赖运行身份的 ImageDossier 内容指纹。"""

    payload = {
        "sourceRevision": source_revision.model_dump(mode="json"),
        "summary": summary,
        "category": category,
        "caption": caption,
        "altText": alt_text,
        "scopeId": scope_id,
        "placementReason": placement_reason,
        "certificateFact": (
            certificate_fact.model_dump(mode="json") if certificate_fact else None
        ),
        "attentionItems": [
            {
                "code": item.code,
                "message": item.message,
                "nextAction": item.next_action,
            }
            for item in attention_items
        ],
    }
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class ImageAgentRunReceipt(ImageAgentContractModel):
    """单次图片识别运行的可追溯收据。"""

    run_id: UUID
    observation_run_id: str | None = None
    attempt: int = Field(ge=1)
    status: ImageAgentRunStatus
    source_revision: FileSourceRevision
    started_at: datetime
    finished_at: datetime
    dossier_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    failure_code: str | None = None

    @model_validator(mode="after")
    def _validate_terminal_shape(self) -> "ImageAgentRunReceipt":
        if self.status == "completed" and self.dossier_fingerprint is None:
            raise ValueError("完成运行必须携带 ImageDossier 指纹")
        if self.status == "failed" and self.failure_code is None:
            raise ValueError("失败运行必须携带 failure_code")
        return self
