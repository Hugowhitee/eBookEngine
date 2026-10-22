"""Regressions for optional Libron EPUB embedding (no proprietary fixture fonts)."""
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

from lxml import etree
import pytest

from ebookengine import libron
from ebookengine.core import ChangeSession, DocumentError, EpubSource
from test_core import fixture_book


def _font_zip(tmp_path, monkeypatch, *, missing=()):
    class DummyFont:
        def getname(self):
            return "Libron", "Regular"
    monkeypatch.setattr(libron.ImageFont, "truetype",
                        lambda *args, **kwargs: DummyFont())
    path = tmp_path / "Libron.zip"
    with ZipFile(path, "w") as archive:
        for style, name in libron.FONTS.items():
            if style not in missing:
                archive.writestr(name, b"\x00\x01\x00\x00fake-test-font")
    return path


def test_opt_in_embedding_preserves_every_original_book_resource(tmp_path, monkeypatch):
    source_path = fixture_book(tmp_path)
    source = EpubSource(source_path)
    zip_path = _font_zip(tmp_path, monkeypatch)
    session = ChangeSession(source)
    session.set_libron_zip(zip_path)
    assert session.changes["typography"].enabled
    output = session.build()
    assert session.verify_candidate(output)

    with ZipFile(source_path) as original, ZipFile(BytesIO(output)) as result:
        assert set(original.namelist()).issubset(result.namelist())
        assert result.namelist()[0] == "mimetype"
        assert result.testzip() is None
        assert "META-INF/Libron-OFL.txt" in result.namelist()
        assert b"SIL OPEN FONT LICENSE" in result.read("META-INF/Libron-OFL.txt")
        fonts = [p for p in result.namelist() if p.endswith(".ttf")]
        assert len(fonts) == 4
        stylesheet = next(p for p in result.namelist()
                          if p.endswith("ebookengine-libron.css"))
        assert b'font-family: "Libron"' in result.read(stylesheet)
        for name in original.namelist():
            if name.endswith(".xhtml"):
                before = etree.fromstring(original.read(name))
                after = etree.fromstring(result.read(name))
                assert "".join(before.itertext()) == "".join(after.itertext())
                assert b"ebookengine-libron.css" in result.read(name)
            elif name != source.opf_path:
                assert original.read(name) == result.read(name)

    session.undo()
    assert "typography" not in session.changes
    unchanged = session.build()
    assert session.verify_candidate(unchanged)
    with ZipFile(BytesIO(unchanged)) as result:
        assert all(not name.endswith(".ttf") for name in result.namelist())
    session.redo()
    assert session.changes["typography"].enabled
    assert session.verify_candidate(session.build())


def test_missing_libron_style_rejected_before_processing(tmp_path, monkeypatch):
    source = EpubSource(fixture_book(tmp_path))
    session = ChangeSession(source)
    path = _font_zip(tmp_path, monkeypatch, missing=("BoldItalic",))
    with pytest.raises(DocumentError, match="four TTF styles"):
        session.set_libron_zip(path)
    assert "typography" not in session.changes


def test_candidate_must_match_latest_font_and_metadata_edits(tmp_path, monkeypatch):
    source = EpubSource(fixture_book(tmp_path))
    session = ChangeSession(source)
    session.set_libron_zip(_font_zip(tmp_path, monkeypatch))
    first = session.build()
    session.assign("description", "A reviewed description")
    with pytest.raises(DocumentError, match="verouderd"):
        session.verify_candidate(first)
    updated = session.build()
    assert session.verify_candidate(updated)
    with ZipFile(BytesIO(updated)) as archive:
        assert b"A reviewed description" in archive.read(source.opf_path)
        assert b"SIL OPEN FONT LICENSE" in archive.read("META-INF/Libron-OFL.txt")



def test_epub3_libron_uses_true_type_mime(tmp_path, monkeypatch):
    book = fixture_book(tmp_path)
    epub3 = tmp_path / "epub3.epub"
    with ZipFile(book) as original, ZipFile(epub3, "w") as output:
        for entry in original.infolist():
            content = original.read(entry)
            if entry.filename == "content.opf":
                content = content.replace(b'version="2.0"', b'version="3.0"')
            output.writestr(entry, content)
    session = ChangeSession(EpubSource(epub3))
    session.set_libron_zip(_font_zip(tmp_path, monkeypatch))
    candidate = session.build()
    assert session.verify_candidate(candidate)
    with ZipFile(BytesIO(candidate)) as archive:
        package = etree.fromstring(archive.read("content.opf"))
        fonts = [item for item in package.iter()
                 if isinstance(item.tag, str) and item.tag.endswith("item")
                 and (item.get("href") or "").endswith(".ttf")]
        assert len(fonts) == 4
        assert all(item.get("media-type") == "font/ttf" for item in fonts)
