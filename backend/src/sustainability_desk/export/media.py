# ABOUTME: 收敛 DOCX 包中未被引用的显式关系与部件，避免模板残留的图片、图表或外部数据关系进入交付物。
# ABOUTME: 只按 OOXML 显式关系类型和包可达性裁剪；样式、编号等隐式依赖始终由关系图保留。
# ABOUTME(en): Prunes unreferenced explicit relationships and parts from a DOCX package, so leftover template images,
# ABOUTME(en): charts or external data links never reach the deliverable. Implicit dependencies stay via the rel graph.
import re
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree

_RID_RE = re.compile(r'r:(?:embed|link|id)="([^"]+)"')
_RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_EXPLICIT_RELATIONSHIP_TYPES = frozenset({
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject",
})


def _source_part(rels_name: str) -> str:
    """word/_rels/document.xml.rels → word/document.xml；_rels/.rels → ''。"""
    if rels_name == "_rels/.rels":
        return ""
    parent, filename = rels_name.rsplit("/_rels/", 1)
    return f"{parent}/{filename[: -len('.rels')]}"


def _rels_part_name(source_part: str) -> str:
    """word/document.xml → word/_rels/document.xml.rels；根包 → _rels/.rels。"""
    if not source_part:
        return "_rels/.rels"
    parent, filename = source_part.rsplit("/", 1)
    return f"{parent}/_rels/{filename}.rels"


def _resolve_target(source_part: str, target: str) -> str:
    """把相对 source_part 目录的 Target 解析为包内绝对路径（处理 ../ 与 ./）。"""
    base = source_part.rsplit("/", 1)[0] if "/" in source_part else ""
    out: list[str] = []
    for seg in (base + "/" + target).split("/"):
        if seg == "..":
            if out:
                out.pop()
        elif seg in ("", "."):
            continue
        else:
            out.append(seg)
    return "/".join(out)


def _strip_rels(data: bytes, drop_ids: set[str]) -> bytes:
    """按 Id 删除自闭合的 <Relationship .../> 标签，其余字节保持不变。"""
    txt = data.decode("utf-8")
    for rid in drop_ids:
        txt = re.sub(r"<Relationship\b[^>]*\bId=\"" + re.escape(rid) + r"\"[^>]*/>", "", txt)
    return txt.encode("utf-8")


def _relationship_records(data: bytes) -> tuple[dict[str, str], ...]:
    root = ElementTree.fromstring(data)
    return tuple(
        dict(relationship.attrib)
        for relationship in root.findall(f"{{{_RELATIONSHIPS_NS}}}Relationship")
    )


def _is_explicit_relationship(relationship: dict[str, str]) -> bool:
    return relationship.get("Type") in _EXPLICIT_RELATIONSHIP_TYPES


def _used_relation_ids(source_part: str, contents: dict[str, bytes]) -> set[str]:
    if not source_part.endswith(".xml") or source_part not in contents:
        return set()
    return set(_RID_RE.findall(contents[source_part].decode("utf-8", "ignore")))


def _reachable_parts(contents: dict[str, bytes]) -> tuple[set[str], dict[str, set[str]]]:
    """从 OOXML 根关系开始遍历有效内部关系，返回可达部件和待删除关系 Id。"""
    reachable: set[str] = set()
    pending = [""]
    dropped_relation_ids: dict[str, set[str]] = {}
    visited_sources: set[str] = set()

    while pending:
        source = pending.pop()
        if source in visited_sources:
            continue
        visited_sources.add(source)
        rels_name = _rels_part_name(source)
        if rels_name not in contents:
            continue
        used_ids = _used_relation_ids(source, contents)
        for relationship in _relationship_records(contents[rels_name]):
            rel_id = relationship.get("Id")
            if not rel_id:
                continue
            if _is_explicit_relationship(relationship) and rel_id not in used_ids:
                dropped_relation_ids.setdefault(rels_name, set()).add(rel_id)
                continue
            if relationship.get("TargetMode") == "External":
                continue
            target = _resolve_target(source, relationship.get("Target", ""))
            if target in contents and target not in reachable:
                reachable.add(target)
                pending.append(target)
    return reachable, dropped_relation_ids


def _strip_content_type_overrides(data: bytes, removed_parts: set[str]) -> bytes:
    """同步删除已裁剪部件的 Content Type Override，避免包内留下悬空声明。"""
    text = data.decode("utf-8")
    for part in removed_parts:
        text = re.sub(
            r'<Override\b[^>]*\bPartName="/' + re.escape(part) + r'"[^>]*/>',
            "",
            text,
        )
    return text.encode("utf-8")


def prune_unreferenced_parts(docx_path: Path) -> tuple[int, int]:
    """删除模板遗留的不可达部件及无引用显式关系，防止 Word 发现外部文件链接。"""
    docx_path = Path(docx_path)
    with zipfile.ZipFile(docx_path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}

    reachable, dropped_relation_ids = _reachable_parts(contents)
    package_parts = {
        name
        for name in contents
        if name != "[Content_Types].xml" and not name.endswith(".rels")
    }
    removed_parts = package_parts - reachable
    if not removed_parts and not dropped_relation_ids:
        return len(package_parts), len(package_parts)

    tmp = docx_path.with_suffix(".tmp.docx")
    with zipfile.ZipFile(docx_path) as source, zipfile.ZipFile(
        tmp, "w", zipfile.ZIP_DEFLATED
    ) as destination:
        for item in source.infolist():
            name = item.filename
            if name in removed_parts:
                continue
            source_part = _source_part(name) if name.endswith(".rels") else None
            if source_part is not None and source_part and source_part not in reachable:
                continue
            data = contents[name]
            if name in dropped_relation_ids:
                data = _strip_rels(data, dropped_relation_ids[name])
            if name == "[Content_Types].xml":
                data = _strip_content_type_overrides(data, removed_parts)
            destination.writestr(item, data)
    shutil.move(str(tmp), str(docx_path))
    return len(package_parts), len(reachable)


def prune_unused_media(docx_path: Path) -> tuple[int, int]:
    """删除未引用 media，并先裁剪模板遗留的不可达图表与外部数据关系。"""
    docx_path = Path(docx_path)
    prune_unreferenced_parts(docx_path)
    with zipfile.ZipFile(docx_path) as z:
        names = z.namelist()
        contents = {n: z.read(n) for n in names}

    media_files = {n for n in names if n.startswith("word/media/")}

    # 每个 xml part（非 .rels）用到的 rId
    used: dict[str, set[str]] = {}
    for n, data in contents.items():
        if n.endswith(".xml") and not n.endswith(".rels"):
            used[n] = set(_RID_RE.findall(data.decode("utf-8", "ignore")))

    referenced: set[str] = set()
    drop_rel_ids: dict[str, set[str]] = {}
    for n, data in contents.items():
        if not n.endswith(".rels"):
            continue
        src = _source_part(n)
        src_used = used.get(src, set())
        for rel_id, target in re.findall(r'<Relationship\b[^>]*?\bId="([^"]+)"[^>]*?\bTarget="([^"]+)"', data.decode("utf-8", "ignore")):
            if "media/" not in target:
                continue
            media_path = _resolve_target(src, target)
            if rel_id in src_used:
                referenced.add(media_path)
            else:
                drop_rel_ids.setdefault(n, set()).add(rel_id)

    orphans = media_files - referenced
    if not orphans:
        return (len(media_files), len(media_files))

    tmp = docx_path.with_suffix(".tmp.docx")
    with zipfile.ZipFile(docx_path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            n = item.filename
            if n in orphans:
                continue
            data = contents[n]
            if n in drop_rel_ids:
                data = _strip_rels(data, drop_rel_ids[n])
            zout.writestr(item, data)
    shutil.move(str(tmp), str(docx_path))
    return (len(media_files), len(media_files - orphans))
