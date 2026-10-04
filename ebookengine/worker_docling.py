"""Isolated heavy document conversion process, called via managed Python."""
from pathlib import Path
import sys


def run():
    if len(sys.argv)!=4:raise SystemExit('source target modeldir expected')
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter,PdfFormatOption
    from docling_core.types.doc import ImageRefMode
    source,dest,models=sys.argv[1:]
    opts=PdfPipelineOptions(generate_page_images=True,generate_picture_images=True,
                            images_scale=1.5,artifacts_path=Path(models))
    converter=DocumentConverter(format_options={InputFormat.PDF:PdfFormatOption(pipeline_options=opts)})
    result=converter.convert(source)
    content=result.document.export_to_html(image_mode=ImageRefMode.EMBEDDED)
    Path(dest).write_text(content,encoding='utf8')

if __name__=='__main__':run()
