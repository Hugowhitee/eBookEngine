"""Only demonstrably unreferenced OS archive debris may be removed."""
from io import BytesIO
from zipfile import ZipFile, ZIP_STORED

import pytest

from ebookengine.core import ChangeSession, DocumentError, EpubSource
from ebookengine.hygiene import removable_entries, remove_os_debris
from test_core import fixture_book


def test_os_debris_cleanup_preserves_book_and_is_undoable(tmp_path):
    book = fixture_book(tmp_path, {
        "__MACOSX/._cover.jpg": b"Finder metadata",
        "OEBPS/.DS_Store": b"Finder index",
        "Thumbs.db": b"Windows thumbnail cache",
    })
    original = book.read_bytes()
    source = EpubSource(book)
    paths = removable_entries(source)
    assert set(paths) == {"__MACOSX/._cover.jpg", "OEBPS/.DS_Store", "Thumbs.db"}
    session = ChangeSession(source)
    assert session.changes["archive_hygiene"].enabled
    result = session.build()
    assert session.verify_candidate(result)
    with ZipFile(book) as before, ZipFile(BytesIO(result)) as after:
        assert not set(paths) & set(after.namelist())
        assert set(after.namelist()) == set(before.namelist()) - set(paths)
        for name in after.namelist():
            assert after.read(name) == before.read(name)
    assert book.read_bytes() == original
    session.undo()
    assert "archive_hygiene" not in session.changes
    restored = session.build()
    assert session.verify_candidate(restored)
    with ZipFile(BytesIO(restored)) as archive:
        assert set(paths) <= set(archive.namelist())
    session.redo()
    assert session.verify_candidate(session.build())


def test_never_remove_manifest_declared_debris(tmp_path):
    book = fixture_book(tmp_path)
    target = tmp_path / "declared.epub"
    with ZipFile(book) as before, ZipFile(target, "w") as after:
        for item in before.infolist():
            data = before.read(item)
            if item.filename == "content.opf":
                data = data.replace(
                    b"</manifest>",
                    b'<item id="cache" href=".DS_Store" media-type="application/octet-stream"/></manifest>',
                )
            after.writestr(item, data)
        after.writestr(".DS_Store", b"Publisher-linked asset")
    source = EpubSource(target)
    assert removable_entries(source) == ()
    assert "archive_hygiene" not in ChangeSession(source).changes


def test_never_remove_source_referenced_debris(tmp_path):
    book = fixture_book(tmp_path)
    target = tmp_path / "linked.epub"
    with ZipFile(book) as before, ZipFile(target, "w") as after:
        for item in before.infolist():
            data = before.read(item)
            if item.filename == "chapter1.xhtml":
                data = data.replace(b"</body>", b'<a href=".DS_Store">File reference</a></body>')
            after.writestr(item, data)
        after.writestr(".DS_Store", b"Linked extra content")
    source = EpubSource(target)
    assert removable_entries(source) == ()


def test_unapproved_or_nonexistent_removal_is_rejected(tmp_path):
    book = fixture_book(tmp_path, {"Thumbs.db": b"cache"})
    source = EpubSource(book)
    assert removable_entries(source) == ("Thumbs.db",)
    with pytest.raises(DocumentError, match="Unapproved"):
        remove_os_debris(source, source.raw, ("chapter1.xhtml",))
    with pytest.raises(DocumentError, match="Unapproved"):
        remove_os_debris(source, source.raw, ("Thumbs.db", "Thumbs.db"))


def test_repeated_cleanup_does_not_drop_any_new_author_content(tmp_path):
    book = fixture_book(tmp_path, {"Thumbs.db": b"cache"})
    source = EpubSource(book)
    session = ChangeSession(source)
    session.assign("description", "Metadata adjustment")
    result = session.build()
    assert session.verify_candidate(result)
    with ZipFile(BytesIO(result)) as archive:
        assert b"Metadata adjustment" in archive.read("content.opf")
        assert b"Last chapter 2" in archive.read("chapter2.xhtml")
        assert "Thumbs.db" not in archive.namelist()
