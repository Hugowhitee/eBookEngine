"""Conservative EPUB 2 NCX repair, independent of the eventual editor UI.

We generate a missing table of contents only when every linear XHTML spine
section has a real heading and a stable relative path. No text is invented,
no chapter is reordered, and EPUB 3 publications are deliberately excluded.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import quote
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

from lxml import etree

from .core import DC_NS, EPUB_NS, DocumentError, verify_archive

NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
XHTML_NS = "http://www.w3.org/1999/xhtml"
MAX_CHAPTER = 2 * 1024 * 1024


@dataclass(frozen=True)
class NcxPlan:
    path: str
    href: str
    identifier: str
    publication_uid: str
    title: str
    entries: tuple[tuple[str, str], ...]


def propose_ncx(source) -> NcxPlan | None:
    """Return a deterministic plan only when there are no ambiguous sections."""
    opf = source.opf
    if not opf.get("version", "").startswith("2."):
        return None
    manifest = opf.find(f"{{{EPUB_NS}}}manifest")
    spine = opf.find(f"{{{EPUB_NS}}}spine")
    if manifest is None or spine is None or spine.get("toc"):
        return None
    if any(item.get("media-type") == "application/x-dtbncx+xml" for item in manifest):
        return None  # A present but broken NCX needs separate review.
    layout_values = [(node.text or "").strip().lower()
                     for node in source.metadata.iter()
                     if isinstance(node.tag, str)
                     and node.get("property", "").endswith("layout")]
    if "pre-paginated" in layout_values:
        return None
    if not source.title or len(source.title) > 500 or len(source.spine) > 1000:
        return None
    uid_id = opf.get("unique-identifier")
    identifiers = source.metadata.findall(f"{{{DC_NS}}}identifier")
    uid = next(((n.text or "").strip() for n in identifiers
                if uid_id and n.get("id") == uid_id), "")
    if not uid:
        return None

    candidates = []
    with ZipFile(BytesIO(source.raw)) as archive:
        for itemref in spine.findall(f"{{{EPUB_NS}}}itemref"):
            if itemref.get("linear", "yes") == "no":
                continue
            ident = itemref.get("idref")
            item = source.items.get(ident)
            if item is None or item.get("media-type") != "application/xhtml+xml":
                return None
            path = source.paths[ident]
            if archive.getinfo(path).file_size > MAX_CHAPTER:
                return None
            try:
                root = etree.fromstring(archive.read(path), parser=etree.XMLParser(
                    resolve_entities=False, load_dtd=False, no_network=True))
            except (etree.XMLSyntaxError, ValueError):
                return None
            if root.tag != f"{{{XHTML_NS}}}html":
                return None
            body = root.find(f"{{{XHTML_NS}}}body")
            if body is None:
                return None
            headings = [el for el in body.iter()
                        if isinstance(el.tag, str) and
                        etree.QName(el).namespace == XHTML_NS and
                        etree.QName(el).localname in ("h1", "h2", "h3", "h4", "h5", "h6")]
            if not headings:
                return None
            title = " ".join("".join(headings[0].itertext()).split())
            if not title or len(title) > 240:
                return None
            href = source.paths[ident][len(source.base) + 1:] if source.base else source.paths[ident]
            candidates.append((title, quote(href, safe="/.-_~")))
        if not candidates:
            return None
        existing = set(archive.namelist())
        ids = set(source.items)
        counter = 1
        while True:
            suffix = "" if counter == 1 else "-" + str(counter)
            path = (source.base + "/" if source.base else "") + "ebookengine-toc" + suffix + ".ncx"
            identifier = "ebookengine-toc" + suffix
            if path not in existing and identifier not in ids:
                break
            counter += 1
    return NcxPlan(path, PurePosixPath(path).name, identifier, uid, source.title,
                   tuple(candidates))


def apply_ncx(source, candidate: bytes, plan: NcxPlan) -> bytes:
    """Attach the selected NCX to the EPUB 2 manifest and spine.

    Verifies that every pre-existing entry except OPF remains byte-identical,
    and refuses a plan that no longer matches the original publication.
    """
    if propose_ncx(source) != plan:
        raise DocumentError("NCX repair plan is stale or unsupported")
    with ZipFile(BytesIO(candidate)) as previous:
        verify_archive(previous)
        if plan.path in previous.namelist():
            raise DocumentError("NCX target already exists")
        opf = etree.fromstring(previous.read(source.opf_path), parser=etree.XMLParser(
            resolve_entities=False, load_dtd=False, no_network=True))
        if not opf.get("version", "").startswith("2."):
            raise DocumentError("EPUB version changed during NCX repair")
        manifest = opf.find(f"{{{EPUB_NS}}}manifest")
        spine = opf.find(f"{{{EPUB_NS}}}spine")
        if manifest is None or spine is None or spine.get("toc"):
            raise DocumentError("EPUB structure changed during NCX repair")
        etree.SubElement(manifest, f"{{{EPUB_NS}}}item", id=plan.identifier,
                         href=plan.href, **{"media-type": "application/x-dtbncx+xml"})
        spine.set("toc", plan.identifier)

        ncx = etree.Element(f"{{{NCX_NS}}}ncx", nsmap={None: NCX_NS}, version="2005-1")
        header = etree.SubElement(ncx, f"{{{NCX_NS}}}head")
        etree.SubElement(header, f"{{{NCX_NS}}}meta", name="dtb:uid",
                         content=plan.publication_uid)
        doc_title = etree.SubElement(ncx, f"{{{NCX_NS}}}docTitle")
        etree.SubElement(doc_title, f"{{{NCX_NS}}}text").text = plan.title
        nav_map = etree.SubElement(ncx, f"{{{NCX_NS}}}navMap")
        for index, (title, href) in enumerate(plan.entries, 1):
            point = etree.SubElement(nav_map, f"{{{NCX_NS}}}navPoint",
                                     id="navPoint-" + str(index), playOrder=str(index))
            label = etree.SubElement(point, f"{{{NCX_NS}}}navLabel")
            etree.SubElement(label, f"{{{NCX_NS}}}text").text = title
            etree.SubElement(point, f"{{{NCX_NS}}}content", src=href)
        changed_opf = etree.tostring(opf, encoding="utf-8", xml_declaration=True)
        changed_ncx = etree.tostring(ncx, encoding="utf-8", xml_declaration=True)

        output = BytesIO()
        with ZipFile(output, "w") as target:
            for info in previous.infolist():
                value = changed_opf if info.filename == source.opf_path else previous.read(info.filename)
                target.writestr(info, value, compress_type=ZIP_STORED
                                if info.filename == "mimetype" else info.compress_type)
            target.writestr(plan.path, changed_ncx, compress_type=ZIP_DEFLATED)
        generated = output.getvalue()
        with ZipFile(BytesIO(generated)) as verified:
            verify_archive(verified)
            if verified.namelist()[0] != "mimetype" or verified.testzip() is not None:
                raise DocumentError("Invalid EPUB 2 NCX archive")
            if set(verified.namelist()) != set(previous.namelist()) | {plan.path}:
                raise DocumentError("Unexpected archive changes during NCX repair")
            for name in previous.namelist():
                if name != source.opf_path and previous.read(name) != verified.read(name):
                    raise DocumentError("Existing EPUB content changed during NCX repair")
            parsed_ncx = etree.fromstring(verified.read(plan.path))
            targets = parsed_ncx.xpath('//*[local-name()="content"]/@src')
            if targets != [target for _, target in plan.entries]:
                raise DocumentError("Generated NCX targets do not match reviewed plan")
    return generated
