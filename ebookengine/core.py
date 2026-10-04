"""Untrusted input inspection and safe EPUB candidate creation.

Sources are immutable. A Candidate is rebuilt from source with declarative edits,
never by applying unchecked incremental mutations to a previous candidate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
from collections import Counter
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED, BadZipFile
import hashlib
import os
import re
import tempfile

from lxml import etree, html
from PIL import Image

MAX_ARCHIVE = 512 * 1024 * 1024
MAX_ENTRY = 100 * 1024 * 1024
MAX_FILES = 10000
EPUB_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
NS = {"opf": EPUB_NS, "dc": DC_NS}

class DocumentError(ValueError):
    pass


def _xml(data: bytes):
    return etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False))


def _safe_path(name: str) -> str:
    decoded = unquote(name).replace("\\", "/")
    path = PurePosixPath(decoded)
    if (not decoded or decoded.startswith("/") or path.is_absolute() or
            any(part in ("", ".", "..") for part in decoded.split("/")) or
            re.match(r"^[A-Za-z]:", decoded) or "\x00" in decoded):
        raise DocumentError(f"Onveilig EPUB-pad: {name}")
    return str(path)


def _join(root: str, href: str):
    path = unquote(urlsplit(href).path)
    return _safe_path(str(PurePosixPath(root) / path))


def sniff(path: str | Path) -> str:
    p = Path(path)
    if not p.is_file():
        raise DocumentError("Bestand niet gevonden")
    with p.open("rb") as f:
        marker = f.read(1024)
    if b"%PDF-" in marker[:16]:
        return "PDF"
    if marker[:2] != b"PK":
        raise DocumentError("Ongeldig of niet ondersteund bestand: alleen PDF en EPUB")
    try:
        with ZipFile(p) as z:
            names = z.namelist()
            if "mimetype" not in names or z.read("mimetype") != b"application/epub+zip":
                raise DocumentError("Dit ZIP-bestand is geen EPUB")
            if "META-INF/container.xml" not in names:
                raise DocumentError("EPUB bevat geen container.xml")
    except (BadZipFile, RuntimeError, KeyError) as exc:
        raise DocumentError("EPUB is beschadigd") from exc
    return "EPUB"


def verify_archive(z: ZipFile):
    entries = z.infolist()
    if len(entries) > MAX_FILES:
        raise DocumentError("EPUB bevat te veel bestanden")
    if sum(e.file_size for e in entries) > MAX_ARCHIVE:
        raise DocumentError("Uitgepakte EPUB is te groot")
    seen = set()
    for e in entries:
        name = _safe_path(e.filename.rstrip("/"))
        if name in seen:
            raise DocumentError(f"Dubbele EPUB-inhoud: {name}")
        seen.add(name)
        if e.file_size > MAX_ENTRY or (e.file_size > 1024 * 1024 and e.file_size > 250 * max(e.compress_size, 1)):
            raise DocumentError("EPUB bevat onveilig gecomprimeerde data")
        # A ZIP Unix symlink can point outside the archive.
        if (e.external_attr >> 16) & 0o170000 == 0o120000:
            raise DocumentError("Symbolische links in EPUB zijn niet toegestaan")


def _text(node):
    return "" if node is None else " ".join(" ".join(node.itertext()).split())

@dataclass(frozen=True)
class BookInfo:
    format: str
    title: str
    author: str
    description: str
    chapters: tuple[str, ...]
    covers: tuple[str, ...]
    current_cover: str | None
    warnings: tuple[str, ...] = ()


class EpubSource:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.raw = self.path.read_bytes()
        with ZipFile(BytesIO(self.raw)) as z:
            verify_archive(z)
            container = _xml(z.read("META-INF/container.xml"))
            rootfiles = container.xpath("//*[local-name()='rootfile']")
            if not rootfiles:
                raise DocumentError("EPUB mist rootfile")
            self.opf_path = _safe_path(rootfiles[0].get("full-path") or "")
            self.base = str(PurePosixPath(self.opf_path).parent)
            if self.base == ".":
                self.base = ""
            self.opf = _xml(z.read(self.opf_path))
            items = self.opf.xpath(".//opf:manifest/opf:item", namespaces=NS)
            self.items = {x.get("id"): x for x in items if x.get("id")}
            self.paths = {ident: _join(self.base, x.get("href") or "") for ident, x in self.items.items()}
            self.spine = [x.get("idref") for x in self.opf.xpath(".//opf:spine/opf:itemref", namespaces=NS)]
            if not self.spine or any(s not in self.paths for s in self.spine):
                raise DocumentError("Onvolledige EPUB-leesvolgorde")
            for path in self.paths.values():
                if path not in z.namelist():
                    raise DocumentError(f"Ontbrekend EPUB-onderdeel: {path}")
            nodes = self.opf.xpath(".//opf:metadata", namespaces=NS)
            if not nodes:
                raise DocumentError("EPUB mist metadata")
            self.metadata = nodes[0]
            self.title = _text(self.metadata.find(f"{{{DC_NS}}}title"))
            self.author = _text(self.metadata.find(f"{{{DC_NS}}}creator"))
            self.description = _text(self.metadata.find(f"{{{DC_NS}}}description"))
            cover_ids = [ident for ident, x in self.items.items() if "cover-image" in (x.get("properties") or "").split()]
            cover_metas = self.metadata.xpath(".//opf:meta[@name='cover']", namespaces=NS)
            cover_ids.extend(x.get("content") for x in cover_metas if x.get("content"))
            self.current_cover = next((x for x in cover_ids if x in self.paths), None)
            images = []
            self.dimensions = {}
            for ident, x in self.items.items():
                if (x.get("media-type") or "").startswith("image/"):
                    try:
                        with Image.open(BytesIO(z.read(self.paths[ident]))) as pic:
                            size = pic.size
                        self.dimensions[ident] = size
                        if size[0] >= 150 and size[1] >= 180:
                            images.append(ident)
                    except Exception:
                        continue
            self.covers = tuple(images)
            self.chapter_names = tuple(self._chapter_name(z, idref) for idref in self.spine)
            self.toc_entries = self._read_ncx(z)
            self.navnames = tuple(item[0] for item in self.toc_entries) if self.toc_entries else self.chapter_names
            self._fingerprint = self._contents_fingerprint(z)

    def _read_ncx(self, z):
        spine = self.opf.xpath('.//opf:spine', namespaces=NS)
        idref = spine[0].get('toc') if spine else None
        if not idref or idref not in self.paths:
            return ()
        tocpath = self.paths[idref]
        try:
            document = _xml(z.read(tocpath))
        except Exception:
            return ()
        base=str(PurePosixPath(tocpath).parent)
        if base == '.':base=''
        results=[]
        for node in document.xpath('//*[local-name()="navPoint"]'):
            label=node.xpath('./*[local-name()="navLabel"]/*[local-name()="text"]')
            link=node.xpath('./*[local-name()="content"]')
            if not label or not link or not link[0].get('src'):continue
            source=link[0].get('src')
            path=_join(base,source)
            if path not in (self.paths[idref] for idref in self.spine):continue
            name=_text(label[0])
            fragment=unquote(urlsplit(source).fragment)
            if name:
                results.append((name[:120],path,fragment))
        return tuple(results)

    def read_section(self, index):
        """A bounded plain-text reading excerpt from the real NCX target."""
        if not self.toc_entries:
            if not 0 <= index < len(self.spine): raise IndexError(index)
            return self._html_text(self.chapter_html(index))
        if not 0 <= index < len(self.toc_entries): raise IndexError(index)
        _,path,anchor=self.toc_entries[index]
        with ZipFile(BytesIO(self.raw)) as z:
            root=html.fromstring(z.read(path))
        try:
            body=root.xpath('//body')
            doc=body[0] if body else root
            nodes=list(doc.iter())
            starts=[j for j,n in enumerate(nodes) if n.get('id')==anchor or n.get('name')==anchor]
            start=starts[0] if starts else 0
            end=len(nodes)
            if index+1<len(self.toc_entries) and self.toc_entries[index+1][1]==path:
                next_anchor=self.toc_entries[index+1][2]
                stops=[j for j,n in enumerate(nodes) if j>start and (n.get('id')==next_anchor or n.get('name')==next_anchor)]
                if stops:end=stops[0]
            lines=[]
            for n in nodes[start:end]:
                if n.tag in ('p','h1','h2','h3','h4','h5','h6','li','td','figcaption','blockquote'):
                    sentence=' '.join(' '.join(n.itertext()).split())
                    if sentence:lines.append(sentence)
                elif n.tag=='img':lines.append('[Image] '+(n.get('alt') or ''))
            return '\n\n'.join(lines)[:180_000] or self.toc_entries[index][0]
        except Exception:
            return self._html_text(etree.tostring(doc))

    @staticmethod
    def _html_text(data):
        root=html.fromstring(data)
        body=root.xpath('//body')
        node=body[0] if body else root
        return '\n\n'.join(' '.join(' '.join(e.itertext()).split()) for e in node.iter()
                           if e.tag in ('p','h1','h2','h3','h4','li'))[:180_000]

    def _chapter_name(self, z, ident):
        path = self.paths[ident]
        try:
            tree = html.fromstring(z.read(path))
            headers = tree.xpath("//*[self::h1 or self::h2 or self::h3 or self::h4]")
            if headers:
                name = " ".join(headers[0].itertext()).strip()
                if name:
                    return name[:95]
        except (etree.XMLSyntaxError, UnicodeDecodeError):
            pass
        return PurePosixPath(path).name

    def _contents_fingerprint(self, z):
        return {p: hashlib.sha256(z.read(p)).digest() for p in self.paths.values()}

    @property
    def info(self):
        notes = []
        if not self.current_cover or (self.current_cover and self.current_cover not in self.covers):
            notes.append("Omslag ontbreekt of is niet als afbeelding herkenbaar")
        if not self.description:
            notes.append("Geen beschrijving in EPUB-metadata")
        if re.fullmatch(r"B0[A-Z0-9]{8}\s+EBOK", self.title.upper()):
            notes.append("Book title appears to be a retailer code; verify manually")
        return BookInfo("EPUB", self.title, self.author, self.description,
                        self.chapter_names, self.covers, self.current_cover, tuple(notes))

    def cover_bytes(self, ident=None):
        ident = ident or self.current_cover
        if ident not in self.paths or ident not in self.dimensions:
            return None
        with ZipFile(BytesIO(self.raw)) as z:
            return z.read(self.paths[ident])

    def chapter_html(self, index):
        if not 0 <= index < len(self.spine):
            raise IndexError(index)
        with ZipFile(BytesIO(self.raw)) as z:
            return z.read(self.paths[self.spine[index]])

    def propose(self):
        # Avoid opaque guessing: metadata requires an actual user input.
        changes = []
        if self.current_cover not in self.covers and len(self.covers) == 1:
            changes.append(Change("cover", self.current_cover or "", self.covers[0], "Single usable cover", True))
        elif self.current_cover in self.covers and len(self.covers)>1:
            # Very narrow retailer-placeholder recognition: only propose an
            # alternative if current artwork clearly prints an ASIN+EBOK code.
            # Never guess from dominant colors / portrait dimensions alone.
            try:
                import pytesseract
                from PIL import ImageOps
                image=Image.open(BytesIO(self.cover_bytes(self.current_cover)))
                image.thumbnail((1000,1400))
                current=pytesseract.image_to_string(image,config="--psm 11").upper()
                if "EBOK" in current and re.search(r"B0[A-Z0-9]{8}", current):
                    choices=[]
                    for ident in self.covers:
                        if ident==self.current_cover:continue
                        pic=Image.open(BytesIO(self.cover_bytes(ident)))
                        pic.thumbnail((1000,1400))
                        text=pytesseract.image_to_string(pic,config="--psm 11").upper()
                        if len(re.sub(r"[^A-Z]","",text))>15 and "EBOK" not in text:
                            choices.append(ident)
                    if len(choices)==1:
                        changes.append(Change("cover",self.current_cover,choices[0],
                            "Retailer placeholder detected; original cover found",True))
            except (ImportError,FileNotFoundError,ValueError,OSError):
                pass
        return changes

    def create(self, edits: dict[str,str], *, extra_css: bool=False) -> bytes:
        """Write EPUB without removing or reordering any source spine/assets.
        Only OPF, explicitly changed metadata and optional targeted CSS injections change.
        """
        valid = {"title", "author", "description", "cover"}
        if not set(edits) <= valid:
            raise DocumentError("Onbekende bewerking")
        if "cover" in edits and edits["cover"] not in self.covers:
            raise DocumentError("Ongeldige omslagselectie")
        tree = _xml(etree.tostring(self.opf))
        meta = tree.find(f"{{{EPUB_NS}}}metadata")
        for key, tag in (("title","title"),("author","creator"),("description","description")):
            if key in edits:
                if len(edits[key]) > 8000:
                    raise DocumentError("Metadataveld te lang")
                node = meta.find(f"{{{DC_NS}}}{tag}")
                if node is None:
                    node = etree.SubElement(meta, f"{{{DC_NS}}}{tag}")
                node.text = edits[key]
        if "cover" in edits:
            ident = edits["cover"]
            # EPUB2 uses OPF meta name=cover; the EPUB3 properties token is
            # prohibited on OPF2 manifest items by stricter validators.
            if tree.get('version','2.0').startswith('3'):
                for x in tree.xpath(".//opf:manifest/opf:item", namespaces=NS):
                    props = [v for v in (x.get("properties") or "").split() if v != "cover-image"]
                    if x.get("id") == ident:
                        props.append("cover-image")
                    if props:
                        x.set("properties", " ".join(props))
                    else:
                        x.attrib.pop("properties", None)
            covers = meta.xpath(".//opf:meta[@name='cover']", namespaces=NS)
            if covers:
                covers[0].set("content", ident)
                for other in covers[1:]:
                    meta.remove(other)
            else:
                etree.SubElement(meta, f"{{{EPUB_NS}}}meta", name="cover", content=ident)
        if edits and tree.get('version','2.0').startswith('3'):
            from datetime import datetime,timezone
            rows=meta.xpath('./opf:meta[@property="dcterms:modified"]',namespaces=NS)
            stamp=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            if rows:
                rows[0].text=stamp
                for other in rows[1:]:meta.remove(other)
            else:
                etree.SubElement(meta,f'{{{EPUB_NS}}}meta',property='dcterms:modified').text=stamp
        modified = {}
        if edits:
            modified[self.opf_path] = etree.tostring(tree, xml_declaration=True, encoding="utf-8")
        if extra_css:
            # Only patch existing stylesheet files, leave content HTML untouched;
            # add when not already present. Avoid duplicating across repeated runs.
            css = b"\n/* eBookEngine: prevent orphaned headings */\nh1,h2,h3,h4,h5,h6 {page-break-after:avoid;break-after:avoid-page;}\n"
            for ident, x in self.items.items():
                if x.get("media-type") == "text/css":
                    path = self.paths[ident]
                    with ZipFile(BytesIO(self.raw)) as orig:
                        previous = orig.read(path)
                    if b"eBookEngine: prevent orphaned headings" not in previous:
                        modified[path] = previous + css
        with ZipFile(BytesIO(self.raw)) as original:
            buffer = BytesIO()
            with ZipFile(buffer, "w") as output:
                names = original.namelist()
                ordered = ["mimetype"] + [x for x in names if x != "mimetype"]
                for name in ordered:
                    original_info = original.getinfo(name)
                    data = modified.get(name, original.read(name))
                    output.writestr(original_info, data,
                                    compress_type=ZIP_STORED if name == "mimetype" else original_info.compress_type)
        candidate = buffer.getvalue()
        self.verify(candidate, modified)
        return candidate

    def verify(self, candidate: bytes, allowed_modified: dict[str, bytes]|None=None):
        with ZipFile(BytesIO(candidate)) as z:
            verify_archive(z)
            first = z.infolist()[0]
            if first.filename != "mimetype" or first.compress_type != ZIP_STORED:
                raise DocumentError("Ongeldige EPUB-container")
            if z.read("mimetype") != b"application/epub+zip":
                raise DocumentError("Ongeldige EPUB-mimetype")
            changed = set((allowed_modified or {}).keys())
            for path, sha in self._fingerprint.items():
                if path not in changed and hashlib.sha256(z.read(path)).digest() != sha:
                    raise DocumentError(f"Inhoud gewijzigd zonder toestemming: {path}")
            opf = _xml(z.read(self.opf_path))
            ids = {x.get("id"):x for x in opf.xpath(".//opf:manifest/opf:item", namespaces=NS)}
            spine = [x.get("idref") for x in opf.xpath(".//opf:spine/opf:itemref", namespaces=NS)]
            if spine != self.spine or set(ids) != set(self.items):
                raise DocumentError("Leesvolgorde of manifest onverwacht veranderd")
            if set(z.namelist()) != set(ZipFile(BytesIO(self.raw)).namelist()):
                raise DocumentError("EPUB verliest een origineel bestand")
            for x in ids.values():
                if _join(self.base, x.get("href") or "") not in z.namelist():
                    raise DocumentError("Ongeldig manifest")
            if z.testzip() is not None:
                raise DocumentError("EPUB is corrupt")
        return True


@dataclass(frozen=True)
class Change:
    field: str
    before: str
    after: str
    reason: str
    enabled: bool = True


class ChangeSession:
    """Declarative change state with snapshot history. Original data never mutates."""
    def __init__(self, source: EpubSource):
        self.source = source
        self.changes: dict[str, Change] = {c.field:c for c in source.propose()}
        self._history: list[dict[str, Change]] = []
        self._redo: list[dict[str, Change]] = []
        self.extra_css = False
        self.candidate: bytes = source.raw

    def _snapshot(self):
        self._history.append(self.changes.copy())
        self._redo.clear()

    def assign(self, field, value, reason="Handmatig gewijzigd"):
        baseline = getattr(self.source.info, "current_cover" if field == "cover" else field, "")
        if field not in ("title", "author", "description", "cover"):
            raise DocumentError("Ongeldige bewerking")
        if field == "cover" and value not in self.source.covers:
            raise DocumentError("Ongeldige omslag")
        self._snapshot()
        if value == baseline:
            self.changes.pop(field, None)
        else:
            self.changes[field] = Change(field, baseline or "", value, reason)

    def toggle(self, field):
        if field not in self.changes:
            return
        self._snapshot()
        c = self.changes[field]
        self.changes[field] = Change(c.field,c.before,c.after,c.reason,not c.enabled)

    def undo(self):
        if self._history:
            self._redo.append(self.changes.copy())
            self.changes = self._history.pop()

    def redo(self):
        if self._redo:
            self._history.append(self.changes.copy())
            self.changes = self._redo.pop()

    def build(self):
        changes = {c.field:c.after for c in self.changes.values() if c.enabled}
        self.candidate = self.source.create(changes,extra_css=self.extra_css)
        return self.candidate


def atomic_save(target: str | Path, content: bytes, *, original: str | Path):
    target = Path(target).resolve()
    if target == Path(original).resolve():
        raise DocumentError("Het oorspronkelijke bestand mag niet overschreven worden")
    target.parent.mkdir(parents=True, exist_ok=True)
    path = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".ebookengine-", suffix=".tmp", delete=False) as f:
            path = Path(f.name)
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(path,target)
    finally:
        if path and path.exists():
            path.unlink()
    return target
