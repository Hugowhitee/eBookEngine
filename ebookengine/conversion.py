"""Structured PDF-to-EPUB export with original-page appendix for audit.

Requires a local document layout engine; plain digital PDF text extraction is
NOT treated as equivalent to reconstructed illustrations/reading order.
"""
from __future__ import annotations
import base64
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
import hashlib
import re
import uuid
from html import escape
from lxml import html, etree
from PIL import Image

from .core import DocumentError,EpubSource
from .pdf_engine import inspect_pdf, reconstruct_pdf_html, page_image


def structured_html_to_epub(markup: str, title: str, author: str,
                            *, original_pages: tuple[bytes,...]=()) -> bytes:
    if not markup.strip():
        raise DocumentError("Document engine returned no structured content")
    root=html.fromstring(markup)
    for element in root.xpath("//script|//iframe|//object|//embed|//link|//form|//video|//audio"):
        element.drop_tree()
    # Re-encode only explicitly embedded images as named EPUB resources.
    images={}
    for element in root.xpath("//img"):
        src=element.get('src','')
        m=re.match(r'^data:image/(png|jpeg|webp);base64,(.+)$',src,re.I|re.S)
        if not m:
            element.set('alt',(element.get('alt') or 'Afbeelding niet opgenomen')[:140])
            element.attrib.pop('src',None)
            continue
        ext={'jpeg':'jpg'}.get(m.group(1).lower(),m.group(1).lower())
        payload=base64.b64decode(m.group(2),validate=True)
        if len(payload)>25*1024*1024:raise DocumentError('Illustratie overschrijdt de groottebeperking')
        with Image.open(BytesIO(payload)) as image:
            image.verify()
        path=f'images/illustration-{len(images)+1:03}.{ext}'
        images[path]=payload
        element.set('src',path)
    body=root.xpath('//body')
    content=body[0] if body else root
    for e in content.iter():
        for attribute in list(e.attrib):
            if attribute.lower().startswith('on') or attribute in ('style','srcset','formaction'):
                e.attrib.pop(attribute,None)
        if e.tag=='a' and (e.get('href','').startswith(('http:','https:','javascript:'))):
            e.attrib.pop('href',None)
    serialized=''.join(etree.tostring(node,method='xml',encoding='unicode') for node in content)
    # No ungrounded editing: output is only what structured engine returned.
    if len(''.join(content.itertext()).strip())<50:
        raise DocumentError('Document extractie heeft onvoldoende tekst')
    body_markup=serialized
    image_items=[]
    for i,(name,payload) in enumerate(images.items()):
        typ={'jpg':'image/jpeg','png':'image/png','webp':'image/webp'}[name.rsplit('.',1)[1]]
        image_items.append((f'pic{i}',name,typ,payload))
    extra_html=''
    extras=[]
    if original_pages:
        extra_html='<h1>Source pages (visual reference)</h1><p>Original rendered pages for checking figures and reading order.</p>'
        for i,page in enumerate(original_pages):
            name=f'images/source-page-{i+1:04}.jpg'
            extras.append((f'source{i}',name,'image/jpeg',page))
            extra_html+=f'<div class="source-page"><h2>Page {i+1}</h2><img src="{name}" alt="Original page {i+1}"/></div>'
    title_xml=escape(title or 'Converted document')
    author_xml=escape(author or 'Unknown')
    uid=f'urn:uuid:{uuid.uuid4()}'
    content_xhtml=(f'''<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en"><head><title>{title_xml}</title><link href="base.css" rel="stylesheet" type="text/css" /></head><body>{body_markup}</body></html>''').encode()
    extras_xhtml=(f'''<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en"><head><title>Original pages</title><link href="base.css" rel="stylesheet" type="text/css"/></head><body>{extra_html}</body></html>''').encode()
    manifest=''.join(f'<item id="{id}" href="{path}" media-type="{typ}"/>' for id,path,typ,_ in image_items+extras)
    if extras: manifest+='<item id="visual" href="visual.xhtml" media-type="application/xhtml+xml"/>'
    spine='<itemref idref="main"/>'+('<itemref idref="visual"/>' if extras else '')
    opf=f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">{uid}</dc:identifier><dc:title>{title_xml}</dc:title><dc:creator>{author_xml}</dc:creator><dc:language>en</dc:language></metadata><manifest><item id="main" href="main.xhtml" media-type="application/xhtml+xml"/><item id="css" href="base.css" media-type="text/css"/><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>{manifest}</manifest><spine toc="ncx">{spine}</spine></package>'''.encode()
    ncx=f'''<?xml version="1.0" encoding="utf-8"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:uid" content="{uid}"/></head><docTitle><text>{title_xml}</text></docTitle><navMap><navPoint id="main" playOrder="1"><navLabel><text>Document</text></navLabel><content src="main.xhtml"/></navPoint>{'<navPoint id="visual" playOrder="2"><navLabel><text>Original pages</text></navLabel><content src="visual.xhtml"/></navPoint>' if extras else ''}</navMap></ncx>'''.encode()
    container=b'''<?xml version="1.0" encoding="utf-8"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''
    css=b'body{line-height:1.48;} img{max-width:100%;height:auto;} h1,h2,h3{page-break-after:avoid;break-after:avoid-page} .source-page{page-break-before:always} .source-page img{max-height:98vh;object-fit:contain}'
    buf=BytesIO()
    with ZipFile(buf,'w') as z:
        z.writestr('mimetype','application/epub+zip',compress_type=ZIP_STORED)
        z.writestr('META-INF/container.xml',container,compress_type=ZIP_DEFLATED)
        files={'content.opf':opf,'toc.ncx':ncx,'main.xhtml':content_xhtml,'base.css':css}
        if extras: files['visual.xhtml']=extras_xhtml
        for path,payload in files.items():z.writestr('OEBPS/'+path,payload,compress_type=ZIP_DEFLATED)
        for _,path,_,payload in image_items+extras:z.writestr('OEBPS/'+path,payload,compress_type=ZIP_DEFLATED)
    result=buf.getvalue()
    with ZipFile(BytesIO(result)) as check:
        for name in ('OEBPS/main.xhtml','OEBPS/content.opf','OEBPS/toc.ncx'):
            etree.fromstring(check.read(name))
        if extras: etree.fromstring(check.read('OEBPS/visual.xhtml'))
        if check.testzip() is not None:raise DocumentError('Generated EPUB is corrupt')
    return result


def reconstruct_pdf_epub(path: str|Path, *, progress=None, cancelled=None) -> bytes:
    if cancelled and cancelled():raise DocumentError('Geannuleerd')
    info=inspect_pdf(path)
    if progress:progress(0,0,'Geavanceerde PDF-layout wordt lokaal geanalyseerd')
    markup=reconstruct_pdf_html(path,cancelled=cancelled,progress=progress)
    if cancelled and cancelled():raise DocumentError('Geannuleerd')
    # A visual source appendix means figures are never irretrievable even if
    # extraction model misses a diagram; no claim that reading order is exact.
    pages=[]
    for idx in range(info.pages):
        if cancelled and cancelled():raise DocumentError('Geannuleerd')
        if progress:progress(idx,info.pages,'Visuele bronreferentie bewaren')
        im=page_image(path,idx,scale=1.2).convert('RGB')
        file=BytesIO();im.save(file,format='JPEG',quality=78)
        pages.append(file.getvalue())
    content=structured_html_to_epub(markup,info.title or Path(path).stem,info.author,original_pages=tuple(pages))
    # Verify complete original page appendices and a parseable EPUB.
    with ZipFile(BytesIO(content)) as z:
        count=sum(n.startswith('OEBPS/images/source-page-') for n in z.namelist())
        if count!=info.pages:raise DocumentError('Niet alle bronpagina\'s bewaard')
    return content
