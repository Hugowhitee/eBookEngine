"""Opt-in standalone Windows Docling runtime managed inside the UI.

Uses a checksum-verified uv executable to maintain isolated Python/weights.
The application's own interpreter and Calibre installations are untouched.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
from zipfile import ZipFile

from .core import DocumentError
from .local_ai import application_data,_download

UV_RELEASE='0.12.20'
UV_URL=f'https://github.com/astral-sh/uv/releases/download/{UV_RELEASE}/uv-x86_64-pc-windows-msvc.zip'
UV_SHA='95f9bc30fbb3574d276e28ac4a6de932d25153645853d13da8c21eec3bc88d06'
DOCLING_VERSION='2.132.0'


def folder():return application_data()/'engines'/'docling'

def python_path():return folder()/'venv'/'Scripts'/'python.exe'

def cli_path():return folder()/'venv'/'Scripts'/'docling-tools.exe'

def model_folder():return folder()/'models'

def ready():return python_path().is_file() and model_folder().joinpath('.installed').is_file()


def _process(args, *, stage, progress=None,cancelled=None, timeout=1800):
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    # stdout/stderr redirected to a temp log: no PIPE deadlock for verbose uv.
    log=folder()/'setup.log';log.parent.mkdir(parents=True,exist_ok=True)
    if progress:progress(0,0,stage)
    with log.open('w',encoding='utf8') as f:
        task=subprocess.Popen([str(a) for a in args],stdout=f,stderr=subprocess.STDOUT,
                              cwd=str(folder()),creationflags=flags)
        start=time.monotonic()
        while task.poll() is None:
            if cancelled and cancelled():
                task.kill();task.wait()
                raise DocumentError('Installatie geannuleerd (later opnieuw proberen)')
            if time.monotonic()-start>timeout:
                task.kill();task.wait()
                raise DocumentError(f'{stage}: te lang bezig; zie setup.log')
            time.sleep(.3)
        if task.returncode:
            raise DocumentError(f'{stage} mislukt. Laatste regels:\n'+''.join(log.read_text(encoding='utf8',errors='replace').splitlines(True)[-5:]))


def install(*,progress=None,cancelled=None):
    if os.name!='nt' or os.environ.get('PROCESSOR_ARCHITECTURE','').lower() not in ('amd64','x86_64',''):
        raise DocumentError('Geavanceerde layout-engine installatie ondersteunt voorlopig alleen Windows x64')
    base=folder();base.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(base).free<12*1024**3:
        raise DocumentError('Minimaal 12 GB vrije ruimte vereist voor deze zware lokale layout-engine')
    uv=base/'uv.exe'
    if not uv.exists():
        if progress:progress(0,0,'Python engine installer ophalen')
        archive=_download(UV_URL,base/'uv.zip',55_000_000,progress,cancelled)
        with archive.open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()!=UV_SHA:
                archive.unlink(missing_ok=True);raise DocumentError('Runtime-installer heeft een onjuiste checksum')
        with ZipFile(archive) as z:
            members=[m for m in z.infolist() if Path(m.filename).name=='uv.exe' and m.file_size < 35*1024*1024]
            if len(members)!=1:raise DocumentError('uv.exe ontbreekt of is niet uniek')
            uv.write_bytes(z.read(members[0]))
        archive.unlink(missing_ok=True)
    if cancelled and cancelled():raise DocumentError('Installatie afgebroken')
    _process([uv,'python','install','3.12'],stage='Geïsoleerde Python downloaden',progress=progress,cancelled=cancelled)
    _process([uv,'venv',str(base/'venv'),'--python','3.12'],stage='Python-omgeving voorbereiden',progress=progress,cancelled=cancelled)
    _process([uv,'pip','install','--python',python_path(),f'docling=={DOCLING_VERSION}'],
             stage='Document-layout-engine installeren',progress=progress,cancelled=cancelled,timeout=2600)
    models=model_folder();models.mkdir(exist_ok=True)
    _process([cli_path(),'models','download','layout','tableformer','picture_classifier','rapidocr',
              '--output-dir',models],stage='OCR/layout-modellen lokaal opslaan',progress=progress,cancelled=cancelled,timeout=2100)
    _process([python_path(),'-c','from docling.document_converter import DocumentConverter'],
             stage='Installatie controleren',progress=progress,cancelled=cancelled,timeout=90)
    models.joinpath('.installed').write_text(DOCLING_VERSION,encoding='utf8')
    return True


def convert(path: str|Path, *, cancelled=None,progress=None):
    if not ready():raise DocumentError('Geavanceerde layout-engine nog niet geïnstalleerd')
    source=Path(path).resolve()
    # Untrusted documents are processed by an isolated local subprocess, not
    # by downloading/mirroring user documents to a remote conversion service.
    import tempfile
    from .worker_docling import __file__ as source_file
    with tempfile.TemporaryDirectory(prefix='ebookengine-docling-') as dirname:
        dest=Path(dirname)/'document.html'
        _process([python_path(),source_file,str(source),str(dest),str(model_folder())],
                 stage='PDF lokaal reconstrueren',progress=progress,cancelled=cancelled,timeout=3600)
        if not dest.exists() or dest.stat().st_size>150*1024*1024:
            raise DocumentError('PDF-reconstructie ontbreekt of is te groot')
        return dest.read_text(encoding='utf8')
