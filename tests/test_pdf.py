from pathlib import Path
from io import BytesIO
import pytest
from PIL import Image,ImageDraw,ImageFont
from reportlab.pdfgen.canvas import Canvas
from pypdf import PdfReader
from ebookengine.pdf_engine import inspect_pdf,page_image,searchable_pdf,has_tesseract
from ebookengine.core import sniff,DocumentError


def digital(tmp_path):
    p=tmp_path/'digital.pdf';c=Canvas(str(p),pagesize=(600,800))
    c.drawString(50,700,'A sample document containing searchable text for inspection.');c.save()
    return p


def scanned(tmp_path):
    p=tmp_path/'scanned.pdf';img=Image.new('RGB',(900,350),'white');d=ImageDraw.Draw(img)
    d.text((70,110),'This scanned document contains searchable words.',fill='black',font=ImageFont.truetype(str(next(x for x in (Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),Path('C:/Windows/Fonts/arial.ttf')) if x.exists())),34))
    picture=tmp_path/'source.png';img.save(picture)
    c=Canvas(str(p),pagesize=(600,330));c.drawImage(str(picture),0,0,width=600,height=330);c.save()
    return p


def test_inspection_and_render(tmp_path):
    p=digital(tmp_path);assert sniff(p)=='PDF'
    info=inspect_pdf(p)
    assert info.pages==1 and info.has_text==(True,)
    assert page_image(p,0).width>500


@pytest.mark.skipif(not has_tesseract(),reason='No OCR binary installed')
def test_scanned_ocr_preserves_page_visual(tmp_path):
    p=scanned(tmp_path)
    assert not inspect_pdf(p).has_text[0]
    before=page_image(p,0).convert('RGB')
    candidate, affected=searchable_pdf(p)
    out=tmp_path/'recognized.pdf';out.write_bytes(candidate)
    assert affected==(0,)
    assert len(PdfReader(out).pages)==1
    assert len(PdfReader(out).pages[0].extract_text())>10
    after=page_image(out,0).convert('RGB')
    from PIL import ImageChops,ImageStat
    diff=ImageStat.Stat(ImageChops.difference(before,after)).mean
    assert max(diff) < 1.7  # invisible OCR text must not repaint pages
    with pytest.raises(DocumentError):
        searchable_pdf(p,cancelled=lambda:True)
