from io import BytesIO
import base64
from zipfile import ZipFile
from lxml import etree
from PIL import Image
from ebookengine.conversion import structured_html_to_epub
from ebookengine.core import EpubSource


def test_structured_export_preserves_figures_and_valid_xhtml(tmp_path):
    image=Image.new('RGB',(240,260),'red');memory=BytesIO();image.save(memory,format='PNG')
    source='<html><body><h1>Chapter</h1><p>'+('A sentence with valid words. '*8)+'</p><img alt="drawing" src="data:image/png;base64,'+base64.b64encode(memory.getvalue()).decode()+'"/></body></html>'
    result=structured_html_to_epub(source,'Title','Author',original_pages=(memory.getvalue(),))
    path=tmp_path/'export.epub';path.write_bytes(result)
    book=EpubSource(path)
    assert len(book.spine)==2
    with ZipFile(BytesIO(result)) as z:
        for name in ('OEBPS/content.opf','OEBPS/main.xhtml','OEBPS/visual.xhtml','OEBPS/toc.ncx'):
            etree.fromstring(z.read(name))
        assert z.read('OEBPS/images/illustration-001.png')==memory.getvalue()
        assert z.read('OEBPS/images/source-page-0001.jpg')==memory.getvalue()
        assert b'<img' in z.read('OEBPS/main.xhtml')
