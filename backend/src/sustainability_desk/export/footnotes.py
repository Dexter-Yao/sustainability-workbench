# ABOUTME: Word 脚注写入——把契约声明的脚注块投影为 footnotes.xml 条目与正文上标引用。
# ABOUTME: python-docx 1.2.0 无脚注 API，故直接操作 OOXML；样式按名解析，编号与分隔线由母版承载。
# ABOUTME(en): Word footnote writing — projects contract-declared footnote blocks into footnotes.xml and body refs.
# ABOUTME(en): python-docx 1.2.0 has no footnote API, so OOXML is edited directly; numbering comes from the template.
"""Word 脚注的写入实现与使用边界。

编号与上标样式遵循 GB/T 7714-2015 与 GB/T 1.1-2020 §10.4.4（条文脚注上标、另行空两汉字、
细实线分隔）；分隔线与编号由母版承载，渲染期不重建。参数见 word_zh profile 的 ``footnotes`` 段。

**使用边界**：脚注的合法宿主是 ``blockType: fixed``、文本由契约或确定性 ref 决定、
且正式稿与审阅稿同时存在的块。以下三类内容**不得**用脚注：

1. **表的口径说明**——归表注（``GsTable.disclaimer``），随表走；移到页脚会让读者
   对着表却看不到口径。
2. **审阅稿专属内容**（资料处理说明页、口径备注列、批注）——脚注两稿必须一字不差，
   而正式稿会对 Report 做裁列投影，一挂脚注即破坏该不变量。批注与脚注的分工：批注说
   「这段内容怎么来的」（元信息，审阅期消费），脚注说「这段内容适用于什么范围」
   （内容本身，永久随交付物）。
3. **AI 生成正文**——脚注的典型内容是来源与口径，而 source refs 按上下文边界刻意不进
   prompt（``llm/generate.py`` 的 ``GenerationSourceRefs``）；模型看不到来源却要写来源
   脚注，只能编造。脚注的触发条件与文本一律由代码确定性判定，模型不参与。

同类中文报告文档的通行做法是「注：」独立成段或括号内联，均零脚注引用。故脚注只用于确实
修复缺陷处，不作默认形态铺开。
"""
from __future__ import annotations

from xml.sax.saxutils import escape

from docx.document import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# 母版保留的分隔符条目占用 -1 与 0；正文脚注从 1 开始。
_RESERVED_FOOTNOTE_IDS = (-1, 0)
_FIRST_FOOTNOTE_ID = 1


class FootnotePartMissingError(RuntimeError):
    """母版缺少 footnotes part：分隔细实线与样式随之缺失，不得静默降级为正文段。"""


def _footnotes_part(document: Document):
    try:
        return document.part.part_related_by(RT.FOOTNOTES)
    except KeyError as exc:  # pragma: no cover - 母版损坏才会走到
        raise FootnotePartMissingError(
            "母版缺少 word/footnotes.xml：脚注分隔线与编号由母版承载，不能在渲染期凭空创建。"
        ) from exc


def resolve_style_id(document: Document, *, style_name: str, style_type: str) -> str:
    """按样式「名称」解析 styleId。

    不接受硬编码 id：normalize_template 会改写样式表，Word 自身也会重排 styleId，
    按 id 绑定必然随母版变动而失效。解析不到即 fail-loud，不回落到某个猜测值——
    回落只会产出样式错误却看似成功的交付物。
    """

    styles_root = document.styles.element
    wanted = style_name.strip().lower()
    for style in styles_root.findall(qn("w:style")):
        if style.get(qn("w:type")) != style_type:
            continue
        name_el = style.find(qn("w:name"))
        name = (name_el.get(qn("w:val")) if name_el is not None else "") or ""
        if name.strip().lower() == wanted:
            style_id = style.get(qn("w:styleId"))
            if style_id:
                return style_id
    raise FootnotePartMissingError(
        f"母版样式表缺少 {style_type} 样式「{style_name}」，无法按规范渲染脚注。"
    )


def _next_footnote_id(footnotes_root) -> int:
    used = {
        int(el.get(qn("w:id")))
        for el in footnotes_root.findall(qn("w:footnote"))
        if el.get(qn("w:id")) is not None
    }
    candidate = _FIRST_FOOTNOTE_ID
    while candidate in used or candidate in _RESERVED_FOOTNOTE_IDS:
        candidate += 1
    return candidate


def _footnote_element(footnote_id: int, text: str, *, text_style_id: str, reference_style_id: str):
    """构造 footnotes.xml 中的一条脚注：编号标记 + 制表位 + 正文。"""

    return etree.fromstring(
        f'<w:footnote xmlns:w="{W}" w:id="{footnote_id}">'
        f'<w:p><w:pPr><w:pStyle w:val="{escape(text_style_id, {chr(34): "&quot;"})}"/></w:pPr>'
        f'<w:r><w:rPr><w:rStyle w:val="{escape(reference_style_id, {chr(34): "&quot;"})}"/></w:rPr>'
        f"<w:footnoteRef/></w:r>"
        f"<w:r><w:tab/></w:r>"
        f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'
        f"</w:p></w:footnote>"
    )


def _reference_run(footnote_id: int, *, reference_style_id: str):
    return etree.fromstring(
        f'<w:r xmlns:w="{W}"><w:rPr>'
        f'<w:rStyle w:val="{escape(reference_style_id, {chr(34): "&quot;"})}"/></w:rPr>'
        f'<w:footnoteReference w:id="{footnote_id}"/></w:r>'
    )


def add_footnote(
    document: Document,
    paragraph: Paragraph,
    text: str,
    *,
    text_style_name: str,
    reference_style_name: str,
) -> int:
    """在 paragraph 末尾追加脚注引用，并把 text 写入 footnotes.xml；返回脚注编号。

    直接在渲染期插入引用 run——渲染器手上就有段落对象，无需先在正文留标记再回头替换。
    标记法会把编码格式混进业务文本，并经渲染计划泄漏到审阅稿批注锚点与审阅材料。
    """

    body = text.strip()
    if not body:
        raise ValueError("脚注正文为空：空脚注在交付物中表现为孤立编号，必须在调用前判定。")

    text_style_id = resolve_style_id(document, style_name=text_style_name, style_type="paragraph")
    reference_style_id = resolve_style_id(
        document, style_name=reference_style_name, style_type="character"
    )

    part = _footnotes_part(document)
    root = etree.fromstring(part.blob)
    footnote_id = _next_footnote_id(root)
    root.append(
        _footnote_element(
            footnote_id,
            body,
            text_style_id=text_style_id,
            reference_style_id=reference_style_id,
        )
    )
    part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    paragraph._p.append(_reference_run(footnote_id, reference_style_id=reference_style_id))
    return footnote_id
