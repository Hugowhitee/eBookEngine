"""Audit local EPUB chapter/NCX links without modifying book contents."""
from zipfile import ZipFile

from ebookengine.core import EpubSource
from ebookengine.links import audit_internal_links
from ebookengine.preflight import inspect_epub
from test_core import fixture_book


def _rewrite(tmp_path, chapter1, chapter2):
    src = fixture_book(tmp_path)
    result = tmp_path / "links.epub"
    with ZipFile(src) as before, ZipFile(result, "w") as after:
        for entry in before.infolist():
            value = before.read(entry)
            if entry.filename == "chapter1.xhtml":
                value = chapter1
            elif entry.filename == "chapter2.xhtml":
                value = chapter2
            after.writestr(entry, value)
    return result


def test_internal_anchor_and_relative_resource_are_valid(tmp_path):
    src = _rewrite(
        tmp_path,
        b'<html><body><!-- note --><p><a href="chapter2.xhtml#end">Next</a></p></body></html>',
        b'<html><body><h2 id="end">The end</h2></body></html>',
    )
    raw = src.read_bytes()
    assert audit_internal_links(EpubSource(src)) == ()
    assert src.read_bytes() == raw


def test_missing_local_file_and_bad_fragment_are_reported(tmp_path):
    src = _rewrite(
        tmp_path,
        b'<html><body><img src="missing.png"/><a href="chapter2.xhtml#missing">Skip</a></body></html>',
        b'<html><body><p id="present">Real content</p></body></html>',
    )
    findings = audit_internal_links(EpubSource(src))
    assert {f.code for f in findings} == {"broken-resource", "broken-anchor"}
    preflight = inspect_epub(src)
    assert preflight.requires_review
    assert {"broken-resource", "broken-anchor"} <= {f.code for f in preflight.findings}
    assert not preflight.safe_to_auto_reconstruct


def test_duplicate_id_and_xml_comments_do_not_crash(tmp_path):
    src = _rewrite(
        tmp_path,
        b'<html><body><!-- comment --><p id="same">A</p><p id="same">B</p></body></html>',
        b'<html><body><p>C</p></body></html>',
    )
    findings = audit_internal_links(EpubSource(src))
    assert sum(f.code == "duplicate-anchor" for f in findings) == 1
    assert inspect_epub(src).requires_review


def test_external_links_are_not_fetched_or_marked_broken(tmp_path):
    src = _rewrite(
        tmp_path,
        b'<html><body><a href="https://example.org/docs#part">External</a><a href="mailto:a@b.org">Mail</a></body></html>',
        b'<html><body><p>Chapter</p></body></html>',
    )
    assert audit_internal_links(EpubSource(src)) == ()


def test_xml_base_is_reported_as_unverified_not_false_broken(tmp_path):
    src = _rewrite(
        tmp_path,
        b'<html xml:base="https://example.org/book/" xmlns:xml="http://www.w3.org/XML/1998/namespace"><body><a href="chapter88.xhtml">Special</a></body></html>',
        b'<html><body><p>Chapter</p></body></html>',
    )
    codes = {x.code for x in audit_internal_links(EpubSource(src))}
    assert "unverified-xml-base" in codes
    assert "broken-resource" not in codes
