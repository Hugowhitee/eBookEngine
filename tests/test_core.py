from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED
import hashlib
import pytest

from ebookengine.core import (EpubSource, ChangeSession, DocumentError, sniff, atomic_save)

OPF=b'''<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">test-book</dc:identifier><dc:title>Test Title</dc:title><dc:creator>Test Author</dc:creator><meta name="cover" content="placeholder"/></metadata><manifest><item id="a" href="chapter1.xhtml" media-type="application/xhtml+xml"/><item id="b" href="chapter2.xhtml" media-type="application/xhtml+xml"/><item id="placeholder" href="cover.jpg" media-type="image/jpeg"/><item id="proper" href="proper.jpg" media-type="image/jpeg"/></manifest><spine><itemref idref="a"/><itemref idref="b"/></spine></package>'''
CONTAINER=b'''<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''


def fixture_book(tmp_path, extra=None):
    from PIL import Image
    buf=BytesIO()
    Image.new('RGB',(320,500),'white').save(buf,format='JPEG'); white=buf.getvalue()
    buf=BytesIO()
    Image.new('RGB',(500,650),'red').save(buf,format='JPEG'); red=buf.getvalue()
    p=tmp_path/'test.epub'
    with ZipFile(p,'w') as z:
        z.writestr('mimetype','application/epub+zip',compress_type=ZIP_STORED)
        z.writestr('META-INF/container.xml',CONTAINER)
        z.writestr('content.opf',OPF)
        z.writestr('chapter1.xhtml',b'<html><body><h1>Start</h1><p>First chapter 1.</p></body></html>')
        z.writestr('chapter2.xhtml',b'<html><body><h1>End</h1><p>Last chapter 2, it must survive.</p></body></html>')
        z.writestr('cover.jpg',white)
        z.writestr('proper.jpg',red)
        if extra:
            for k,v in extra.items():z.writestr(k,v)
    return p


def test_multichapter_content_immutability_and_undo(tmp_path):
    p=fixture_book(tmp_path)
    assert sniff(p)=='EPUB'
    source=EpubSource(p)
    assert source.info.chapters==('Start','End')
    changes=ChangeSession(source)
    changes.assign('cover','proper')
    changes.assign('description','New user-provided description')
    changes.assign('title','New title')
    changes.undo(); assert 'title' not in changes.changes
    changes.redo(); assert changes.changes['title'].after=='New title'
    result=changes.build()
    with ZipFile(BytesIO(result)) as z, ZipFile(p) as original:
        assert 'Last chapter 2' in z.read('chapter2.xhtml').decode()
        assert set(z.namelist())==set(original.namelist())
        for key in original.namelist():
            if key!='content.opf': assert z.read(key)==original.read(key)
        assert b'New user-provided description' in z.read('content.opf')
        assert b'content="proper"' in z.read('content.opf')
    assert p.read_bytes()!=result
    out=atomic_save(tmp_path/'output.epub',result,original=p)
    assert EpubSource(out).info.description=='New user-provided description'
    with pytest.raises(DocumentError): atomic_save(p,result,original=p)


def test_malformed_untrusted_zip_and_format(tmp_path):
    p=fixture_book(tmp_path,{'../outside.txt':b'attack'})
    with pytest.raises(DocumentError): EpubSource(p)
    text=tmp_path/'renamed.epub';text.write_text('not-epub')
    with pytest.raises(DocumentError): sniff(text)


def test_no_changes_consistent(tmp_path):
    p=fixture_book(tmp_path)
    source=EpubSource(p)
    session=ChangeSession(source)
    out=session.build()
    assert EpubSource(tmp_path.joinpath('copy.epub').write_bytes(out) and tmp_path/'copy.epub').info.title=='Test Title'
