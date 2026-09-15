# ABOUTME: Word 图表编号端到端测试——正文全文连续 + 附录 A.N、双稿编号一致、命名题注样式与 FigureSpec 投影。
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

from docx import Document
from PIL import Image

from sustainability_desk.contract.models import (
    Block,
    GsColDef,
    GsTable,
    ImageModel,
    Report,
    Section,
)
from sustainability_desk.contract.table_ops import data_row
from sustainability_desk.export.docx_renderer import (
    ResolvedEvidenceImage,
    build_document_render_plan,
    render_docx,
)
from sustainability_desk.export.figure_projection import FigureSpec
from knowledge_package_fixtures import SSE_PACKAGE


def _png(color: tuple[int, int, int] = (10, 120, 10)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (60, 40), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _table_block(block_id: str, caption: str | None) -> Block:
    cols = [GsColDef(key="item", header="项目"), GsColDef(key="value", header="数值")]
    return Block(
        id=block_id,
        type="table",
        blockType="generative",
        source="ai",
        table=GsTable(
            caption=caption,
            colDefs=cols,
            children=[
                data_row(cols, {"item": "范围一排放", "value": "100"}, state="ready")
            ],
        ),
    )


def _image_block(block_id: str) -> Block:
    return Block(
        id=block_id,
        type="image",
        blockType="slot",
        source="user_input",
        image=ImageModel(layoutAssetSlot=True, layoutAssetIds=[uuid4()]),
    )


def _numbering_report() -> tuple[Report, dict[str, tuple[ResolvedEvidenceImage, ...]]]:
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="图表编号测试",
        sections=[
            Section(
                key="body",
                title="正文",
                headingLevel=1,
                blocks=[
                    _table_block("body.tbl1", "温室气体排放汇总"),
                    _image_block("body.img1"),
                    _image_block("body.img2"),
                    _table_block("body.tbl2", None),
                ],
            ),
            Section(
                key="report_appendix",
                title="附录",
                headingLevel=1,
                children=[
                    Section(
                        key="appendix.data",
                        title="一、数据表",
                        headingLevel=2,
                        blocks=[
                            _table_block("appendix.tbl1", "关键绩效指标"),
                            _image_block("appendix.img1"),
                        ],
                    )
                ],
            ),
        ],
    )
    resolved = {
        "body.img1": (
            ResolvedEvidenceImage(width_cm=16.0,
                data=_png(), caption="治理架构图", alt_text="治理架构图"
            ),
        ),
        "body.img2": (
            ResolvedEvidenceImage(width_cm=16.0,
                data=_png((200, 30, 30)), caption=None, alt_text="无题注图"
            ),
        ),
        "appendix.img1": (
            ResolvedEvidenceImage(width_cm=16.0,
                data=_png((30, 30, 200)), caption="附录流程图", alt_text="附录流程图"
            ),
        ),
    }
    return report, resolved


def _caption_paragraphs(path) -> list[tuple[str, str]]:
    document = Document(str(path))
    return [
        (paragraph.text, paragraph.style.name)
        for paragraph in document.paragraphs
        if paragraph.style.name in {"Caption Figure", "Caption Table"}
    ]


def test_figure_and_table_numbering_across_body_and_appendix(
    base_template, out_dir
) -> None:
    report, resolved = _numbering_report()
    figure_specs: list[FigureSpec] = []
    output = render_docx(
        report,
        base_template,
        out_dir / "numbering.docx",
        resolved_images=resolved,
        figure_specs_out=figure_specs,
    )

    captions = _caption_paragraphs(output)
    # 正文全文连续（图/表独立计数），附录子树改编 A.N；无题注图表输出纯编号。
    assert captions == [
        ("表1　温室气体排放汇总", "Caption Table"),
        ("图1　治理架构图", "Caption Figure"),
        ("图2", "Caption Figure"),
        ("表2", "Caption Table"),
        ("表A.1　关键绩效指标", "Caption Table"),
        ("图A.1　附录流程图", "Caption Figure"),
    ]
    # FigureSpec 投影与 Word 题注一致，供图表目录等下游消费。
    assert [
        (spec.number_label, spec.block_id, spec.kind, spec.in_appendix)
        for spec in figure_specs
    ] == [
        ("表1", "body.tbl1", "table", False),
        ("图1", "body.img1", "evidence_image", False),
        ("图2", "body.img2", "evidence_image", False),
        ("表2", "body.tbl2", "table", False),
        ("表A.1", "appendix.tbl1", "table", True),
        ("图A.1", "appendix.img1", "evidence_image", True),
    ]


def test_standard_and_review_variants_share_identical_figure_numbering(
    base_template, out_dir
) -> None:
    report, resolved = _numbering_report()
    plan = build_document_render_plan(report)
    standard = render_docx(
        report,
        base_template,
        out_dir / "numbering-standard.docx",
        resolved_images=resolved,
        render_plan=plan,
    )
    review = render_docx(
        report,
        base_template,
        out_dir / "numbering-review.docx",
        resolved_images=resolved,
        render_plan=plan,
        delivery_variant="review",
        review_generated_at=datetime.now(timezone.utc),
    )

    assert _caption_paragraphs(standard) == _caption_paragraphs(review)


def test_trial_document_starts_figure_numbering_from_one(
    base_template, out_dir
) -> None:
    """每份文档独立计数：每次渲染新建编号引擎，各自从 图1/表1 起编。

    版式档 Literal 不做运行时校验：传入未登记的档值会一律落到非完整版式分支，
    渲染出一份没有封面、没有目录、没有正文编号节的裸文档——**验证一条生产环境
    根本不存在的路径**却照常绿灯。故本用例必须使用真实存在的版式档。
    """
    from sustainability_desk.contract.models import Field

    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="气候独立编号",
        fields={
            "company_registered_name": Field(
                key="company_registered_name",
                label="公司注册名称",
                type="string",
                source="user_input",
                value="测试企业股份有限公司",
            ),
            "reporting_year": Field(
                key="reporting_year",
                label="报告年度",
                type="string",
                source="user_input",
                value="2025",
            ),
        },
        sections=[
            Section(
                key="climate_change",
                title="应对气候变化",
                headingLevel=2,
                reportSectionId="climate_change",
                blocks=[_image_block("climate.img1")],
            )
        ],
    )
    resolved = {
        "climate.img1": (
            ResolvedEvidenceImage(width_cm=16.0,
                data=_png(), caption="气候治理架构", alt_text="气候治理架构"
            ),
        )
    }
    output = render_docx(
        report,
        base_template,
        out_dir / "numbering-climate.docx",
        resolved_images=resolved,
    )
    assert ("图1　气候治理架构", "Caption Figure") in _caption_paragraphs(output)
