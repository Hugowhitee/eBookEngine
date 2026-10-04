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


def test_epub_nested_relative_resources_keep_full_content(tmp_path):
    """Valid ../ references inside the archive must not be rejected."""
    src=fixture_book(tmp_path)
    path=tmp_path/'nested.epub'
    nested=OPF.replace(b'href="chapter1.xhtml"',b'href="Text/chapter1.xhtml"')              .replace(b'href="chapter2.xhtml"',b'href="Text/chapter2.xhtml"')              .replace(b'href="cover.jpg"',b'href="Images/cover.jpg"')              .replace(b'href="proper.jpg"',b'href="Images/proper.jpg"')
    nested=nested.replace(b'Images/cover.jpg',b'Text/../Images/cover.jpg')
    with ZipFile(src) as z, ZipFile(path,'w') as out:
        for name in z.namelist():
            data=z.read(name)
            if name=='content.opf':data=nested
            elif name.startswith('chapter'):name='Text/'+name
            elif name.endswith('.jpg'):name='Images/'+name
            out.writestr(name,data,compress_type=ZIP_STORED if name=='mimetype' else ZIP_DEFLATED)
        out.writestr('extra-not-listed.txt',b'Unmanifested publisher note')
    book=EpubSource(path)
    assert book.paths['placeholder']=='Images/cover.jpg'
    session=ChangeSession(book)
    session.assign('description','Added description')
    result=session.build()
    with ZipFile(BytesIO(result)) as z,ZipFile(path) as original:
        for name in original.namelist():
            if name !='content.opf':assert z.read(name)==original.read(name)
    # Outside the EPUB root remains invalid even when the first path is nested.
    assert book.read_section(0)


def test_relative_path_escape_is_rejected():
    from ebookengine.core import _join
    assert _join('OEBPS/Text','../Images/picture.jpg') == 'OEBPS/Images/picture.jpg'
    with pytest.raises(DocumentError):_join('OEBPS/Text','../../../private.txt')
    with pytest.raises(DocumentError):_join('OEBPS/Text','%2Fetc/passwd')


def test_epub3_cover_properties_and_metadata_timestamp(tmp_path):
    from lxml import etree
    source_path=fixture_book(tmp_path)
    target=tmp_path/'epub3.epub'
    version3=OPF.replace(b'version="2.0"',b'version="3.0"')
    version3=version3.replace(b'id="placeholder" href=',b'id="placeholder" properties="cover-image" href=')
    with ZipFile(source_path) as z, ZipFile(target,'w') as out:
        for name in z.namelist():
            payload=version3 if name=='content.opf' else z.read(name)
            out.writestr(name,payload,compress_type=ZIP_STORED if name=='mimetype' else ZIP_DEFLATED)
    book=EpubSource(target)
    session=ChangeSession(book)
    session.assign('cover','proper')
    result=session.build()
    with ZipFile(BytesIO(result)) as z:
        tree=etree.fromstring(z.read('content.opf'))
        ns={'opf':'http://www.idpf.org/2007/opf'}
        fields={e.get('id'):(e.get('properties') or '') for e in tree.xpath('.//opf:item',namespaces=ns)}
        assert 'cover-image' in fields['proper'].split()
        assert 'cover-image' not in fields['placeholder'].split()
        assert len(tree.xpath('.//opf:meta[@property="dcterms:modified"]',namespaces=ns))==1
    assert session.verify_candidate(result)


def test_export_verifies_exact_built_candidate_and_rejects_stale_edit(tmp_path):
    src=EpubSource(fixture_book(tmp_path))
    changes=ChangeSession(src)
    changes.assign('description','Reviewed by reader')
    built=changes.build()
    assert changes.verify_candidate(built) is True
    with pytest.raises(DocumentError):changes.verify_candidate(built[:-10]+b'1234567890')
    changes.assign('title','New book title')
    with pytest.raises(DocumentError):changes.verify_candidate(built)
    rebuilt=changes.build()
    assert changes.verify_candidate(rebuilt)
    changes.undo()
    with pytest.raises(DocumentError):changes.verify_candidate(rebuilt)
