# ABOUTME: 章节编号推导——按可见章节树位置算每节序号，产出 {sectionKey: 编号前缀}；编号渲染期推导、不进数据。
# ABOUTME: 镜像前端 lib/section-number.ts，同一 golden fixture 守护两端一致；可见性作注入谓词，不依赖具体实现。
# ABOUTME(en): Section numbering: each ordinal comes from position in the visible section tree, derived at render time.
# ABOUTME(en): Mirrors the frontend lib/section-number.ts with one golden fixture; visibility is an injected predicate.
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

# chapter_cn: 第N章 / 一、 / （一） / 1.   decimal: 1 / 1.1 / 1.1.1 (a subtree under an unnumbered
# chapter stays unnumbered, so front-matter subsections never collide with chapter numbers).
SectionNumberingScheme = Literal["chapter_cn", "decimal"]

# 不参与「第N章」编号的 H1：前置说明章与附录，其子节照常编号。
UNNUMBERED_CHAPTER_KEYS = frozenset({"about_report", "company_intro", "report_appendix"})

_CN_DIGITS = "零一二三四五六七八九"


def _cn(n: int) -> str:
    """正整数转中文数字（报告章节量级，支持 1–99）。"""
    if n < 10:
        return _CN_DIGITS[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + _CN_DIGITS[n - 10]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _CN_DIGITS[tens] + "十" + (_CN_DIGITS[ones] if ones else "")
    return str(n)


def _label(level: int, ordinal: int) -> str:
    """按 headingLevel 决定编号格式（方案 A）：H1「第N章 」/ H2「N、」/ H3「（N）」。"""
    if level == 1:
        return f"第{_cn(ordinal)}章 "
    if level == 2:
        return f"{_cn(ordinal)}、"
    if level == 3:
        return f"（{_cn(ordinal)}）"
    return f"{ordinal}. "


def _has_title(sec: Any) -> bool:
    if getattr(sec, "titleContent", None):
        return True
    title = getattr(sec, "title", None)
    return bool(title and title.strip())


def number_sections(
    sections: list[Any],
    is_visible: Callable[[Any], bool],
    *,
    scheme: SectionNumberingScheme = "chapter_cn",
    unnumbered_chapter_keys: frozenset[str] | tuple[str, ...] = UNNUMBERED_CHAPTER_KEYS,
) -> dict[str, str]:
    """按可见章节树位置推导每节编号前缀。

    - 序号按「同一父节点下同 headingLevel 的可见有标题兄弟」计数；格式按 headingLevel 与 scheme。
    - 前置大章（白名单）label 为空；chapter_cn 下其子节照常从「一、」起编号，decimal 下整棵子树不编号。
    - 空标题分组节透明：不占号，其子节并入父级同层编号。
    - 不可见节（appears_when 不满足）不占号、不产 label。
    """
    out: dict[str, str] = {}

    def walk(secs: list[Any], counters: dict[int, int], path: tuple[int, ...], numbered: bool) -> None:
        for sec in secs:
            if not is_visible(sec):
                continue
            kids = getattr(sec, "children", None) or []
            if not _has_title(sec):
                walk(kids, counters, path, numbered)  # 透明分组节：子节并入父级同层编号
                continue
            level = getattr(sec, "headingLevel", 1) or 1
            if level == 1 and sec.key in unnumbered_chapter_keys:
                out[sec.key] = ""
                walk(kids, {}, (), scheme == "chapter_cn")
                continue
            if not numbered:
                out[sec.key] = ""
                walk(kids, {}, (), False)
                continue
            counters[level] = counters.get(level, 0) + 1
            current_path = (*path, counters[level])
            out[sec.key] = (
                _label(level, counters[level])
                if scheme == "chapter_cn"
                else ".".join(str(n) for n in current_path) + " "
            )
            walk(kids, {}, current_path, True)  # 有标题节点：子节新起一组计数

    walk(sections, {}, (), True)
    return out
