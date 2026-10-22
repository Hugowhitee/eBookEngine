"""Optional, local-only Libron embedding for reflowable EPUBs.

The ordinary EPUB path never loads or downloads fonts. A user-selected official
Libron.zip supplies unmodified TrueType files; its OFL notice is bundled with
the resulting publication. This is deliberately not font subsetting.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from posixpath import dirname, join, relpath
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

from lxml import etree
from PIL import ImageFont

from .core import DocumentError, EPUB_NS, DC_NS, verify_archive

XHTML_NS = "http://www.w3.org/1999/xhtml"
STYLES = ("Regular", "Italic", "Bold", "BoldItalic")
FONTS = {style: f"Libron-{style}.ttf" for style in STYLES}
MAX_FONT_BYTES = 3 * 1024 * 1024
MAX_ZIP_BYTES = 8 * 1024 * 1024


class _LazyArchive(Mapping):
    """Access original ZIP entries on demand rather than copying all assets."""
    def __init__(self, archive):
        self.archive = archive
        self.names = tuple(archive.namelist())

    def __iter__(self):
        return iter(self.names)

    def __len__(self):
        return len(self.names)

    def __getitem__(self, name):
        if name not in self.archive.NameToInfo:
            raise KeyError(name)
        return self.archive.read(name)


def load_libron_zip(path: str | Path) -> dict[str, bytes]:
    """Read the four original Libron TTF styles; never accept partial families."""
    path = Path(path)
    if path.stat().st_size > MAX_ZIP_BYTES:
        raise DocumentError("Libron ZIP is unexpectedly large")
    result = {}
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 32:
                raise DocumentError("Too many entries in Libron archive")
            for info in entries:
                if info.is_dir():
                    continue
                name = info.filename.split("/")[-1]
                style = next((s for s, expected in FONTS.items()
                              if name.casefold() == expected.casefold()), None)
                if style is None:
                    continue
                if style in result or not 0 < info.file_size <= MAX_FONT_BYTES:
                    raise DocumentError("Duplicate or oversized Libron font")
                data = archive.read(info)
                if data[:4] != b"\x00\x01\x00\x00":
                    raise DocumentError(f"Invalid TrueType data: {name}")
                try:
                    family, _ = ImageFont.truetype(BytesIO(data), size=16).getname()
                except (OSError, ValueError) as exc:
                    raise DocumentError(f"Unreadable font: {name}") from exc
                if family.strip().casefold() != "libron":
                    raise DocumentError(f"Unexpected font family: {family}")
                result[style] = data
    except (OSError, ValueError) as exc:
        raise DocumentError("Cannot read Libron ZIP") from exc
    if set(result) != set(STYLES):
        raise DocumentError("Select the standard Libron.zip with all four TTF styles")
    return result


def _parse_xml(data: bytes):
    return etree.fromstring(
        data, parser=etree.XMLParser(resolve_entities=False, load_dtd=False,
                                     no_network=True, recover=False)
    )


def embed_libron(source, candidate: bytes, fonts: dict[str, bytes],
                 license_text: bytes) -> bytes:
    """Add a separate font stylesheet and licensed fonts, retaining book text.

    This feature intentionally declines fixed-layout/encrypted EPUBs instead of
    silently overriding their publisher styling or font encryption.
    """
    if set(fonts) != set(STYLES):
        raise DocumentError("Complete Libron font family required")
    if not license_text or b"SIL OPEN FONT LICENSE" not in license_text:
        raise DocumentError("Libron copyright and OFL notice required")

    with ZipFile(BytesIO(candidate)) as archive:
        verify_archive(archive)
        original = _LazyArchive(archive)
        if "META-INF/encryption.xml" in original:
            raise DocumentError("Font embedding unavailable for encrypted EPUB")
        opf = _parse_xml(original[source.opf_path])
        metadata = opf.find(f"{{{EPUB_NS}}}metadata")
        if metadata is None:
            raise DocumentError("Missing EPUB package metadata")
        if any("pre-paginated" in (node.text or "").lower()
               for node in metadata.iter()
               if node.get("property", "").endswith("layout")):
            raise DocumentError("Libron is not applied to fixed-layout EPUBs")

        manifest = opf.find(f"{{{EPUB_NS}}}manifest")
        if manifest is None:
            raise DocumentError("Missing EPUB manifest")
        manifest_ids = {item.get("id") for item in manifest}
        prefix = dirname(source.opf_path)
        stylesheet = join(prefix, "styles/ebookengine-libron.css")
        font_paths = {s: join(prefix, "fonts/" + FONTS[s]) for s in STYLES}
        notice_path = "META-INF/Libron-OFL.txt"
        new_paths = {stylesheet, notice_path, *font_paths.values()}
        if new_paths.intersection(original):
            raise DocumentError("Libron assets already exist; remove previous embedding first")
        ids = {"ebookengine-libron-style", *("ebookengine-libron-" + s.lower() for s in STYLES)}
        if ids.intersection(manifest_ids):
            raise DocumentError("Libron manifest identifiers already exist")

        altered = {}
        for style in STYLES:
            etree.SubElement(manifest, f"{{{EPUB_NS}}}item", id="ebookengine-libron-" + style.lower(),
                             href="fonts/" + FONTS[style], **{"media-type": "application/vnd.ms-opentype"})
        etree.SubElement(manifest, f"{{{EPUB_NS}}}item", id="ebookengine-libron-style",
                         href="styles/ebookengine-libron.css", **{"media-type": "text/css"})
        if opf.get("version", "2.0").startswith("3"):
            rows = metadata.xpath('./opf:meta[@property="dcterms:modified"]',
                                  namespaces={"opf": EPUB_NS})
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if rows:
                rows[0].text = stamp
                for extra in rows[1:]:
                    metadata.remove(extra)
            else:
                etree.SubElement(metadata, f"{{{EPUB_NS}}}meta",
                                 property="dcterms:modified").text = stamp

        touched = []
        for itemref in opf.findall(f".//{{{EPUB_NS}}}spine/{{{EPUB_NS}}}itemref"):
            target_id = itemref.get("idref")
            item = next((el for el in manifest if el.get("id") == target_id), None)
            if item is None or item.get("media-type") != "application/xhtml+xml":
                continue
            path = source.paths[target_id]
            doc = _parse_xml(original[path])
            html = doc if etree.QName(doc).localname == "html" else None
            if html is None:
                raise DocumentError(f"Unsupported XHTML root: {path}")
            ns = etree.QName(html).namespace
            tag = (lambda value: f"{{{ns}}}{value}" if ns else value)
            head = next((el for el in html if etree.QName(el).localname == "head"), None)
            if head is None:
                head = etree.Element(tag("head"))
                html.insert(0, head)
            css_href = relpath(stylesheet, start=dirname(path) or ".")
            etree.SubElement(head, tag("link"),
                             rel="stylesheet", type="text/css", href=css_href)
            altered[path] = etree.tostring(doc, encoding="utf-8", xml_declaration=True)
            if "".join(_parse_xml(original[path]).itertext()) != "".join(_parse_xml(altered[path]).itertext()):
                raise DocumentError(f"Text changed unexpectedly: {path}")
            touched.append(path)
        if not touched:
            raise DocumentError("No reflowable XHTML chapters available")

        altered[source.opf_path] = etree.tostring(opf, encoding="utf-8", xml_declaration=True)
        rules = [
            "/* Explicitly requested Libron typography; no !important or fixed point sizes. */",
        ]
        for style in STYLES:
            weight = "700" if "Bold" in style else "400"
            slant = "italic" if "Italic" in style else "normal"
            rules.append(f'@font-face {{ font-family: "Libron"; src: url("../fonts/{FONTS[style]}") format("truetype"); font-style: {slant}; font-weight: {weight}; }}')
        rules.append('body { font-family: "Libron", serif; }')
        altered[stylesheet] = ("\n".join(rules) + "\n").encode("utf-8")
        altered[notice_path] = license_text
        altered.update({path: fonts[style] for style, path in font_paths.items()})

        output = BytesIO()
        with ZipFile(output, "w") as destination:
            for info in archive.infolist():
                destination.writestr(info, altered.get(info.filename, original[info.filename]),
                                     compress_type=ZIP_STORED if info.filename == "mimetype" else info.compress_type)
            for path in [stylesheet, *font_paths.values(), notice_path]:
                destination.writestr(path, altered[path], compress_type=ZIP_DEFLATED)

    value = output.getvalue()
    with ZipFile(BytesIO(value)) as result:
        verify_archive(result)
        if result.testzip() is not None or set(original) - set(result.namelist()):
            raise DocumentError("Invalid Libron EPUB output")
        if result.namelist()[0] != "mimetype":
            raise DocumentError("Invalid EPUB archive ordering")
        for name, payload in original.items():
            if name not in altered and result.read(name) != payload:
                raise DocumentError(f"Unrequested file modification: {name}")
        for name in touched:
            if "".join(_parse_xml(result.read(name)).itertext()) != "".join(_parse_xml(original[name]).itertext()):
                raise DocumentError(f"Author text not preserved: {name}")
    return value
