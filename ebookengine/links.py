"""Read-only internal-link audit for EPUB content and navigation.

Only checks local href/src references and anchors. It never rewrites a URL,
fetches external links, or assumes that an unknown target may be deleted.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

from lxml import etree

from .core import DocumentError, _join

_CHECKED_TYPES = frozenset({
    "application/xhtml+xml", "application/x-dtbncx+xml", "image/svg+xml",
})
_MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
_MAX_FINDINGS = 200


@dataclass(frozen=True)
class LinkIssue:
    code: str
    source: str
    target: str
    detail: str


def audit_internal_links(source) -> tuple[LinkIssue, ...]:
    """Find broken local assets, XHTML/nav anchors, and repeated IDs.

    Output is evidence for review rather than an automatically safe repair.
    Documents larger than the scan limit are reported as unverified. Returns
    at most 200 findings so malformed books cannot flood UI/state.
    """
    issues: list[LinkIssue] = []

    def issue(code: str, where: str, target: str, detail: str):
        if len(issues) < _MAX_FINDINGS:
            issues.append(LinkIssue(code, where, target, detail))

    with ZipFile(BytesIO(source.raw)) as archive:
        files = set(archive.namelist())
        xml_entries = {
            source.paths[ident] for ident, entry in source.items.items()
            if entry.get("media-type") in _CHECKED_TYPES
        }
        ids: dict[str, set[str]] = {}
        references: list[tuple[str, str]] = []

        for path in sorted(xml_entries):
            if path not in files:
                issue("missing-resource", source.opf_path, path,
                      "Manifest-listed content is missing")
                continue
            info = archive.getinfo(path)
            if info.file_size > _MAX_DOCUMENT_BYTES:
                issue("unverified-large-content", path, path,
                      "Document exceeds the bounded link-scan size")
                continue
            try:
                root = etree.fromstring(
                    archive.read(path),
                    parser=etree.XMLParser(resolve_entities=False, load_dtd=False,
                                           no_network=True, recover=False)
                )
            except etree.XMLSyntaxError:
                issue("unparseable-content", path, path, "Content is not valid XML")
                continue

            existing_ids: set[str] = set()
            for node in root.iter():
                ident = node.get("id")
                if ident:
                    if ident in existing_ids:
                        issue("duplicate-anchor", path, ident,
                              "ID appears more than once in the document")
                    existing_ids.add(ident)
                if etree.QName(node).localname == "a" and node.get("name"):
                    existing_ids.add(node.get("name"))
                if any(element.get("{http://www.w3.org/XML/1998/namespace}base")
                       for element in [node, *node.iterancestors()]):
                    issue("unverified-xml-base", path, path,
                          "xml:base changes URL resolution; reference not auto-checked")
                    continue
                localname = etree.QName(node).localname
                if localname in ("a", "link", "area") and node.get("href"):
                    references.append((path, node.get("href")))
                elif localname in ("img", "image", "source", "audio", "video") and node.get("src"):
                    references.append((path, node.get("src")))
                elif localname == "content" and node.get("src"):
                    references.append((path, node.get("src")))
            ids[path] = existing_ids

        for source_path, url in references:
            if len(issues) >= _MAX_FINDINGS:
                break
            try:
                parsed = urlsplit(url)
                if parsed.scheme or parsed.netloc or url.startswith("//"):
                    continue  # External links are out of scope for offline audit.
                target_path = _join(source_path.rsplit("/", 1)[0]
                                    if "/" in source_path else "", parsed.path
                                    ) if parsed.path else source_path
                if target_path not in files:
                    issue("broken-resource", source_path, url,
                          "Local reference points to a missing EPUB entry")
                    continue
                fragment = unquote(parsed.fragment)
                if fragment and target_path in ids and fragment not in ids[target_path]:
                    issue("broken-anchor", source_path, url,
                          "Target fragment does not exist in the destination")
                elif fragment and target_path in xml_entries and target_path not in ids:
                    issue("unverified-anchor", source_path, url,
                          "Target content could not be inspected for anchors")
            except (DocumentError, ValueError) as exc:
                issue("unsafe-reference", source_path, url, str(exc))

    return tuple(issues)
