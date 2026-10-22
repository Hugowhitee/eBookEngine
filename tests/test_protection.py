"""Only EPUB font obfuscation is exempt from encryption blockers."""
from zipfile import ZipFile

import pytest

from ebookengine.core import ChangeSession, DocumentError, EpubSource
from ebookengine.preflight import inspect_epub
from ebookengine.protection import is_font_obfuscation_only
from test_core import fixture_book

ENCRYPTION = b'''<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
 xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
 <enc:EncryptedData>
  <enc:EncryptionMethod Algorithm="http://www.idpf.org/2008/embedding"/>
  <enc:CipherData><enc:CipherReference URI="book-font.ttf"/></enc:CipherData>
 </enc:EncryptedData>
</encryption>'''


def _protected_book(tmp_path, encryption=ENCRYPTION, font_mime="font/ttf"):
    original = fixture_book(tmp_path)
    output = tmp_path / "font-obfuscated.epub"
    with ZipFile(original) as source, ZipFile(output, "w") as target:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == "content.opf":
                extra = ('<item id="font" href="book-font.ttf" media-type="' +
                         font_mime + '"/></manifest>').encode()
                data = data.replace(b"</manifest>", extra)
            target.writestr(item, data)
        target.writestr("book-font.ttf", b"obfuscated-publisher-font")
        target.writestr("META-INF/encryption.xml", encryption)
    return output


def test_standard_obfuscated_font_is_not_treated_as_drm(tmp_path):
    path = _protected_book(tmp_path)
    original = path.read_bytes()
    source = EpubSource(path)
    assert is_font_obfuscation_only(source)
    inspection = inspect_epub(path)
    assert "obfuscated-font" in {x.code for x in inspection.findings}
    assert not any(x.severity == "blocker" for x in inspection.findings)
    session = ChangeSession(source)
    session.assign("description", "Verified metadata")
    candidate = session.build()
    assert session.verify_candidate(candidate)
    from io import BytesIO
    with ZipFile(BytesIO(candidate)) as output:
        assert output.read("book-font.ttf") == b"obfuscated-publisher-font"
        assert output.read("META-INF/encryption.xml") == ENCRYPTION
    assert path.read_bytes() == original


@pytest.mark.parametrize("algorithm", [
    "http://example.org/unknown-encryption",
    "http://www.idpf.org/2008/embeddingWRONG",
])
def test_unknown_algorithm_remains_blocker(tmp_path, algorithm):
    encrypted = ENCRYPTION.replace(b"http://www.idpf.org/2008/embedding",
                                   algorithm.encode())
    path = _protected_book(tmp_path, encryption=encrypted)
    source = EpubSource(path)
    assert not is_font_obfuscation_only(source)
    assert any(x.severity == "blocker" for x in inspect_epub(path).findings)
    session = ChangeSession(source)
    session.assign("title", "New title")
    with pytest.raises(DocumentError, match="Encrypted"):
        session.build()


def test_nonfont_obfuscated_target_is_not_accepted(tmp_path):
    path = _protected_book(tmp_path, font_mime="application/xhtml+xml")
    source = EpubSource(path)
    # Refuse a claimed obfuscated 'font' that isn't declared as font media
    # even if the URI ends in .ttf (the MIME is inconsistent).
    assert not is_font_obfuscation_only(source)
