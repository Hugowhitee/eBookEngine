"""PDF preview, searchable-layer OCR, and opt-in Docling reconstruction.

PDF page imagery is never rasterized as part of OCR output. The original page
is preserved and invisible selectable text is layered on top where missing.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import importlib.util
import re
from typing import Callable

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from .core import DocumentError, atomic_save


@dataclass(frozen=True)
class PdfInfo:
    pages: int
    title: str
    author: str
    has_text: tuple[bool, ...]
    encrypted: bool = False


def inspect_pdf(path: str | Path) -> PdfInfo:
    with Path(path).open("rb") as f:
        reader = PdfReader(f, strict=False)
        if reader.is_encrypted:
            raise DocumentError("PDF is beveiligd. Open eerst een toegestane, ontsleutelde kopie.")
        pages = len(reader.pages)
        if pages == 0:
            raise DocumentError("PDF bevat geen pagina's")
        if pages > 3000:
            raise DocumentError("PDF heeft te veel pagina's voor betrouwbare verwerking")
        metadata = reader.metadata or {}
        title = (metadata.get("/Title") or "").strip()
        author = (metadata.get("/Author") or "").strip()
    pdf = pdfium.PdfDocument(str(path))
    try:
        presence = []
        for i in range(len(pdf)):
            page = pdf[i]
            text = page.get_textpage()
            content = text.get_text_range()
            presence.append(len(re.sub(r"\s", "", content)) > 20)
            text.close()
            page.close()
    finally:
        pdf.close()
    return PdfInfo(pages,title,author,tuple(presence))


def page_image(path: str|Path|bytes, index: int, scale:float=1.2) -> Image.Image:
    doc = pdfium.PdfDocument(bytes(path) if isinstance(path, (bytearray,bytes)) else str(path))
    try:
        p=doc[index]
        try:
            img=p.render(scale=scale).to_pil()
            return img.copy()
        finally:
            p.close()
    finally:
        doc.close()


def has_tesseract() -> bool:
    try:
        import pytesseract,sys,os
        bundle=Path(getattr(sys,'_MEIPASS','')) / 'tesseract'
        exe=bundle/'tesseract.exe'
        if exe.is_file():
            pytesseract.pytesseract.tesseract_cmd=str(exe)
            os.environ['TESSDATA_PREFIX']=str(bundle/'tessdata')
        pytesseract.get_tesseract_version()
        return True
    except (ImportError,FileNotFoundError,OSError,RuntimeError):
        return False


def searchable_pdf(path: str|Path, *, progress:Callable[[int,int,str],None]|None=None,
                   cancelled:Callable[[],bool]|None=None, language="eng") -> tuple[bytes,tuple[int,...]]:
    """Add invisible selectable OCR text to image-only pages of PDF.

    ReportLab text rendering mode 3: selectable text, no additional visible ink.
    Safe failure means no candidate is returned.
    """
    if not has_tesseract():
        raise DocumentError("OCR-engine ontbreekt. Installeer de OCR-module voordat je een scan verwerkt.")
    import pytesseract
    info=inspect_pdf(path)
    reader=PdfReader(str(path),strict=False)
    writer=PdfWriter()
    affected=[]
    for i,page in enumerate(reader.pages):
        if cancelled and cancelled():
            raise DocumentError("Verwerking geannuleerd; origineel is niet gewijzigd")
        if progress: progress(i,info.pages,f"OCR pagina {i+1} van {info.pages}")
        if info.has_text[i]:
            writer.add_page(page)
            continue
        # Use true source crop/rotation/mediabox. Only text overlay is merged.
        img=page_image(path,i,scale=2.0)
        width,height=img.size
        if not width or not height:
            raise DocumentError("Ongeldige PDF-pagina")
        data=pytesseract.image_to_data(img,lang=language,config="--psm 3",output_type=pytesseract.Output.DICT)
        buf=BytesIO()
        target_w=float(page.mediabox.width)
        target_h=float(page.mediabox.height)
        c=canvas.Canvas(buf,pagesize=(target_w,target_h))
        layer=c.beginText()
        layer.setTextRenderMode(3)
        words=0
        for j,text in enumerate(data["text"]):
            text=(text or "").strip()
            if not text:
                continue
            # Do not hallucinate missing words for an unreadable scan.
            try: confidence=float(data["conf"][j])
            except (TypeError,ValueError): confidence=-1
            if confidence < 25:
                continue
            x=data["left"][j]*target_w/width
            y=target_h-(data["top"][j]+data["height"][j])*target_h/height
            wordwidth=max(1.0,data["width"][j]*target_w/width)
            wordheight=max(1.0,data["height"][j]*target_h/height)
            layer.setFont("Helvetica",max(3.0,wordheight*0.8))
            layer.setTextOrigin(x,y)
            # Characters unsupported by Helvetica fall back to question marks;
            # source page pixels remain original, but OCR text is a proposal.
            safe_word=text.encode("latin-1",errors="replace").decode("latin-1")
            layer.textOut(safe_word + " ")
            words+=1
        if not words:
            raise DocumentError(f"Pagina {i+1}: geen betrouwbare OCR-tekst. De originele PDF blijft intact.")
        c.drawText(layer)
        c.showPage()
        c.save()
        buf.seek(0)
        overlay=PdfReader(buf).pages[0]
        page.merge_page(overlay)
        writer.add_page(page)
        affected.append(i)
    if progress: progress(info.pages,info.pages,"OCR gecontroleerd")
    if reader.metadata:
        writer.add_metadata({k:str(v) for k,v in reader.metadata.items() if isinstance(k,str) and v is not None})
    out=BytesIO()
    writer.write(out)
    pdf_bytes=out.getvalue()
    post=pdfium.PdfDocument(pdf_bytes)
    try:
        if len(post)!=info.pages:
            raise DocumentError("OCR-output heeft niet alle pagina's")
        for i in affected:
            p=post[i]
            t=p.get_textpage()
            if not t.get_text_range().strip():
                raise DocumentError(f"OCR-tekst voor pagina {i+1} ontbreekt")
            t.close();p.close()
    finally:
        post.close()
    return pdf_bytes,tuple(affected)


def has_docling() -> bool:
    from .layout_runtime import ready
    return ready() or importlib.util.find_spec("docling") is not None


def reconstruct_pdf_html(path: str|Path, *, cancelled=None,progress=None) -> str:
    from .layout_runtime import ready,convert
    if ready():
        return convert(path,cancelled=cancelled,progress=progress)
    if not importlib.util.find_spec('docling'):
        raise DocumentError('Geavanceerde PDF-engine is nog niet geïnstalleerd')
    from docling.document_converter import DocumentConverter,InputFormat,PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling_core.types.doc import ImageRefMode
    opts=PdfPipelineOptions(generate_page_images=True,generate_picture_images=True,images_scale=1.5)
    converter=DocumentConverter(format_options={InputFormat.PDF:PdfFormatOption(pipeline_options=opts)})
    if cancelled and cancelled():raise DocumentError('Geannuleerd')
    return converter.convert(str(path)).document.export_to_html(image_mode=ImageRefMode.EMBEDDED)

def pdf_metadata(path: str|Path, changes: dict[str,str]):
    if not changes:return Path(path).read_bytes()
    reader=PdfReader(str(path));writer=PdfWriter();writer.append(reader)
    update={}
    for field,name in [('title','/Title'),('author','/Author')]:
        if field in changes:update[name]=changes[field]
    preserved={k:str(v) for k,v in (reader.metadata or {}).items() if isinstance(k,str) and v is not None}
    writer.add_metadata({**preserved,**update})
    mem=BytesIO();writer.write(mem)
    check=PdfReader(mem)
    if len(check.pages)!=len(reader.pages):raise DocumentError('Export mist PDF-pagina\'s')
    return mem.getvalue()
