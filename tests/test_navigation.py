"""Deterministic EPUB 2 NCX reconstruction regression cases."""
from io import BytesIO
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED

from ebookengine.core import ChangeSession, EpubSource
from ebookengine.navigation import propose_ncx
from ebookengine.preflight import inspect_epub
from lxml import etree

CONTAINER = b"""<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
<rootfiles><rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
OPF = b"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="2.0">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="id">urn:isbn:1234567890000</dc:identifier>
<dc:title>Sample Book</dc:title><dc:creator>Original Author</dc:creator><dc:language>en</dc:language>
</metadata>
<manifest>
<item id="one" href="Text/one.xhtml" media-type="application/xhtml+xml"/>
<item id="two" href="Text/two.xhtml" media-type="application/xhtml+xml"/>
</manifest>
<spine><itemref idref="one"/><itemref idref="two"/></spine>
</package>"""
ONE = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>One</title></head>
<body><h1>First chapter</h1><p>Hello, reader.</p></body></html>"""
TWO = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Two</title></head>
<body><h2>Second chapter</h2><p>Goodbye, reader.</p></body></html>"""


def epub2(tmp_path, *, opf=OPF, first=ONE, second=TWO):
    target = tmp_path / "nav-missing.epub"
    with ZipFile(target, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr("META-INF/container.xml", CONTAINER, compress_type=ZIP_DEFLATED)
        archive.writestr("OPS/package.opf", opf, compress_type=ZIP_DEFLATED)
        archive.writestr("OPS/Text/one.xhtml", first, compress_type=ZIP_DEFLATED)
        archive.writestr("OPS/Text/two.xhtml", second, compress_type=ZIP_DEFLATED)
    return target


def test_missing_ncx_rebuilt_from_verified_spine_headings(tmp_path):
    source_path = epub2(tmp_path)
    original = source_path.read_bytes()
    source = EpubSource(source_path)
    plan = propose_ncx(source)
    assert plan is not None
    assert [name for name, _ in plan.entries] == ["First chapter", "Second chapter"]
    assert plan.path == "OPS/ebookengine-toc.ncx"
    assert [href for _, href in plan.entries] == ["Text/one.xhtml", "Text/two.xhtml"]
    session = ChangeSession(source)
    assert session.changes["navigation"].enabled
    result = session.build()
    assert session.verify_candidate(result)

    with ZipFile(source_path) as before, ZipFile(BytesIO(result)) as after:
        assert after.namelist()[0] == "mimetype"
        assert after.getinfo("mimetype").compress_type == ZIP_STORED
        assert set(after.namelist()) == set(before.namelist()) | {plan.path}
        for name in before.namelist():
            if name != "OPS/package.opf":
                assert after.read(name) == before.read(name)
        package = etree.fromstring(after.read("OPS/package.opf"))
        spine = package.xpath('//*[local-name()="spine"]')[0]
        assert spine.get("toc") == plan.identifier
        toc = etree.fromstring(after.read(plan.path))
        assert toc.xpath('//*[local-name()="text"]/text()') == [
            "Sample Book", "First chapter", "Second chapter"
        ]
    assert source_path.read_bytes() == original
    assert EpubSource(_save(tmp_path, result)).navnames == (
        "First chapter", "Second chapter"
    )


def _save(tmp_path, result):
    path = tmp_path / "result.epub"
    path.write_bytes(result)
    return path


def test_navigation_proposal_can_be_disabled_without_repacking(tmp_path):
    path = epub2(tmp_path)
    session = ChangeSession(EpubSource(path))
    session.toggle("navigation")
    result = session.build()
    assert result == path.read_bytes()
    assert session.verify_candidate(result)


def test_no_unfounded_chapter_names_or_fixed_layout_changes(tmp_path):
    no_heading = ONE.replace(b"<h1>First chapter</h1>", b"<p>Just text</p>")
    assert propose_ncx(EpubSource(epub2(tmp_path, first=no_heading))) is None
    fixed = OPF.replace(b"</metadata>",
                        b'<meta property="rendition:layout">pre-paginated</meta></metadata>')
    assert propose_ncx(EpubSource(epub2(tmp_path, opf=fixed))) is None


def test_epub3_is_not_mislabeled_as_epub2_repair(tmp_path):
    epub3 = OPF.replace(b'version="2.0"', b'version="3.0"')
    assert propose_ncx(EpubSource(epub2(tmp_path, opf=epub3))) is None


def test_rebuild_not_repeated_after_successful_export(tmp_path):
    path = epub2(tmp_path)
    first = ChangeSession(EpubSource(path)).build()
    fixed_source = EpubSource(_save(tmp_path, first))
    assert propose_ncx(fixed_source) is None
    assert "navigation" not in ChangeSession(fixed_source).changes
