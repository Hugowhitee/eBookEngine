"""Real-file self-test for packaged Windows releases; no user documents needed.

This tests the same engine entrypoints used by Open/Improve/Save, including
bundled PDF rendering and OCR. It deliberately does not claim that GUI clicks,
Docling model setup or local AI are verified by a passing smoke test.
"""
from __future__ import annotations
import json
from io import BytesIO
from pathlib import Path
import tempfile
from zipfile import ZipFile,ZIP_STORED,ZIP_DEFLATED

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from .core import EpubSource,ChangeSession,atomic_save,DocumentError
from .pdf_engine import inspect_pdf,page_image,searchable_pdf,has_tesseract


def _make_epub(path):
    opf=b'''<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">smoke</dc:identifier><dc:title>Smoke fixture</dc:title><dc:creator>Engine</dc:creator><meta name="cover" content="img"/></metadata><manifest><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/><item id="b" href="b.xhtml" media-type="application/xhtml+xml"/><item id="img" href="cover.jpg" media-type="image/jpeg"/></manifest><spine><itemref idref="a"/><itemref idref="b"/></spine></package>'''
    container=b'''<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''
    image=BytesIO();Image.new('RGB',(220,340),'navy').save(image,format='JPEG')
    parts={'META-INF/container.xml':container,'content.opf':opf,
           'a.xhtml':b'<html><body><h1>Chapter 1</h1><p>ONE preserved.</p></body></html>',
           'b.xhtml':b'<html><body><h1>Chapter 2</h1><p>TWO preserved.</p></body></html>',
           'cover.jpg':image.getvalue()}
    with ZipFile(path,'w') as z:
        z.writestr('mimetype',b'application/epub+zip',compress_type=ZIP_STORED)
        for p,v in parts.items():z.writestr(p,v,compress_type=ZIP_DEFLATED)


def _make_image_only_pdf(path):
    text=BytesIO();c=canvas.Canvas(text,pagesize=(612,792))
    c.setFont('Helvetica-Bold',28)
    c.drawString(32,580,'SAMPLE OCR CHECK')
    c.drawString(32,520,'DOCUMENT PRINT 12345')
    c.save()
    image=page_image(text.getvalue(),0,scale=2.0)
    c=canvas.Canvas(str(path),pagesize=(612,792))
    c.drawImage(ImageReader(image),0,0,width=612,height=792)
    c.save()


def run_test():
    proof={'epub':False,'pdf':False,'ocr':False}
    with tempfile.TemporaryDirectory(prefix='ebookengine-selftest-') as work:
        base=Path(work)
        original=base/'source.epub';_make_epub(original)
        source=EpubSource(original);session=ChangeSession(source)
        session.assign('description','A verified description.')
        result=session.build()
        assert session.verify_candidate(result)
        exported=atomic_save(base/'result.epub',result,original=original)
        check=EpubSource(exported)
        assert len(check.spine)==2 and check.description=='A verified description.'
        with ZipFile(original) as before,ZipFile(exported) as after:
            assert before.read('b.xhtml')==after.read('b.xhtml')
        proof['epub']=True
        pdf=base/'scan.pdf';_make_image_only_pdf(pdf)
        assert inspect_pdf(pdf).has_text==(False,)
        proof['pdf']=True
        if not has_tesseract():raise DocumentError('Bundled OCR engine unavailable')
        data,changed=searchable_pdf(pdf)
        assert changed==(0,) and len(data)>500
        import pypdfium2 as pdfium
        doc=pdfium.PdfDocument(data)
        try:
            page=doc[0]; layer=page.get_textpage();txt=layer.get_text_range().upper()
            assert 'SAMPLE' in txt and 'OCR' in txt,txt[:200]
            layer.close();page.close()
        finally:doc.close()
        proof['ocr']=True
    return proof


def dispatch():
    import sys
    if len(sys.argv)>1 and sys.argv[1]=='--self-test':
        if len(sys.argv)!=3:raise SystemExit('Usage: --self-test <proof.json>')
        proof_path=Path(sys.argv[2]);proof_path.parent.mkdir(parents=True,exist_ok=True)
        try:
            data=run_test()
            data['status']='pass'
            proof_path.write_text(json.dumps(data,indent=2),encoding='utf8')
        except Exception as exc:
            proof_path.write_text(json.dumps({'status':'fail','error':str(exc)},indent=2),encoding='utf8')
            raise SystemExit(2)
        raise SystemExit(0)
    from .gui import main
    main()
