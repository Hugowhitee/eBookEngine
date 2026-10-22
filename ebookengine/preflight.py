"""Conservative EPUB preflight for future single-book and batch workflows.

Detection is evidence, never permission to rewrite publisher content. This
module does not apply repairs or claim EPUBCheck / reader validation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from zipfile import ZipFile
import re

from lxml import etree

from .core import DocumentError, EpubSource, EPUB_NS

XHTML = "application/xhtml+xml"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    detail: str
    evidence: str
    automatic: bool = False


@dataclass(frozen=True)
class Preflight:
    source: str
    title: str
    epub_version: str
    layout: str
    workflow: str
    findings: tuple[Finding, ...]
    requires_review: bool
    # No current preflight result authorizes automatic content rewriting.
    safe_to_auto_reconstruct: bool = False

    def to_dict(self):
        return asdict(self)


def inspect_epub(path: str | Path) -> Preflight:
    """Classify before changes; prefer an unresolved finding over a guess.

    The existing EpubSource validates the archive and materializes source
    bytes. This is a preflight, not the eventual streaming implementation.
    """
    source = EpubSource(path)
    opf = source.opf
    metadata = source.metadata
    version = opf.get("version", "")
    evidence: list[Finding] = []

    def note(code, severity, detail, where):
        evidence.append(Finding(code, severity, detail, where))

    with ZipFile(source.path) as archive:
        filenames = set(archive.namelist())
        flags = ("META-INF/encryption.xml", "META-INF/rights.xml",
                 "META-INF/signatures.xml")
        for flag in flags:
            if flag in filenames:
                note("protected-or-signed", "blocker" if "encryption" in flag else "review",
                     "Protected/signed EPUB requires investigation before changing content", flag)

        styles = [item for item in source.items.values()
                  if item.get("media-type") == "text/css"]
        combined_css = b""
        for item in styles:
            target = source.paths[item.get("id")]
            if len(combined_css) < 256_000:
                combined_css += archive.read(target)[:64_000] + b"\n"
        css = combined_css.decode("utf-8", "replace").lower()
        properties = [n for n in metadata.iter()
                      if n.get("property", "").endswith("layout")]
        declared_layouts = {(n.text or "").strip().lower() for n in properties}
        fixed = "pre-paginated" in declared_layouts
        roll = any("scroll" in x or "roll" in x for x in declared_layouts)
        layout = "fixed" if fixed else "roll/unknown" if roll else "reflowable/unknown"

        if fixed:
            note("fixed-layout", "review", "Do not apply generic reflow or typography fixes",
                 "OPF rendition:layout=pre-paginated")
        if css and re.search(r"position\s*:\s*absolute", css) and not fixed:
            note("absolute-positioning", "review",
                 "Absolute-positioned CSS may indicate PDF conversion or intentional layout",
                 "CSS position:absolute")

        nav_items = [x for x in source.items.values()
                     if "nav" in (x.get("properties") or "").split()]
        if version.startswith("3") and not nav_items:
            note("missing-epub3-nav", "review",
                 "EPUB 3 requires a navigation document", source.opf_path)
        if not source.toc_entries and not nav_items:
            note("navigation-unverified", "review",
                 "No usable EPUB navigation was detected by the current parser",
                 source.opf_path)

        if not source.title.strip():
            note("missing-title", "review", "Bibliographic title missing", source.opf_path)
        if not source.author.strip():
            note("missing-author", "review", "Bibliographic author missing", source.opf_path)
        if not source.description.strip():
            note("missing-description", "info", "Optional book description not present",
                 source.opf_path)
        if source.current_cover not in source.covers:
            note("cover-review", "review", "Cover is missing or not recognized",
                 source.opf_path)

        # Signal only, never auto-join paragraphs: poetry, lists and reference
        # books can legitimately contain many short lines.
        suspicious = 0
        for ident in source.spine[:80]:
            entry = source.items[ident]
            if entry.get("media-type") != XHTML:
                continue
            location = source.paths[ident]
            if archive.getinfo(location).file_size > 2_000_000:
                note("large-chapter", "review", "Large chapter needs bounded inspection",
                     location)
                continue
            payload = archive.read(location)
            try:
                root = etree.fromstring(payload, parser=etree.XMLParser(
                    resolve_entities=False, load_dtd=False, no_network=True))
            except etree.XMLSyntaxError:
                note("unparseable-xhtml", "blocker", "XHTML could not be parsed", location)
                continue
            paragraphs = [" ".join("".join(n.itertext()).split())
                          for n in root.iter()
                          if etree.QName(n).localname == "p"]
            lengths = [len(p) for p in paragraphs if p]
            if len(lengths) >= 30 and median(lengths) < 65:
                suspicious += 1
                note("short-line-pattern", "review",
                     "Many short paragraphs: may be OCR/PDF lines or intentional formatting",
                     location)
        if len(source.spine) > 80:
            note("partial-sampling", "info", "Only first 80 spine entries sampled",
                 "spine")

    blocked = any(x.severity == "blocker" for x in evidence)
    # A suspected conversion is for manual reconstruction review, not an
    # algorithm that silently decides all short paragraphs are broken.
    workflow = "review-reconstruction" if suspicious or any(
        x.code == "absolute-positioning" for x in evidence
    ) else "preserve"
    if fixed or roll:
        workflow = "special-layout-review"
    return Preflight(str(source.path), source.title, version, layout, workflow,
                     tuple(evidence), blocked or workflow != "preserve" or any(
                         x.severity == "review" for x in evidence))
